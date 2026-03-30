"""改善策A/B/C の実装と検証"""
from __future__ import annotations
import csv
import json
from pathlib import Path
from ortools.sat.python import cp_model

DATA_DIR = Path(__file__).parent.parent / "data"
RESULTS_DIR = Path(__file__).parent.parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SHIFT_HOURS = 8


def load_data():
    employees = []
    with open(DATA_DIR / "employees.csv") as f:
        for row in csv.DictReader(f):
            row["skills"] = set(row["skills"].split(","))
            row["max_hours_per_week"] = int(row["max_hours_per_week"])
            row["min_hours_per_week"] = int(row["min_hours_per_week"])
            unavail = row["unavailable_days"].strip()
            row["unavailable_days"] = set(unavail.split(",")) if unavail else set()
            employees.append(row)
    shifts = []
    with open(DATA_DIR / "shifts.csv") as f:
        for row in csv.DictReader(f):
            row["required_count"] = int(row["required_count"])
            row["required_skills"] = set(row["required_skills"].split(","))
            shifts.append(row)
    return employees, shifts


def evaluate(assignments, employees, shifts):
    n_emp = len(employees)
    n_shift = len(shifts)
    emp_shifts = {i: [] for i in range(n_emp)}
    for (e, s), val in assignments.items():
        if val == 1:
            emp_shifts[e].append(s)

    hc = {"HC1": 0, "HC2": 0, "HC3": 0, "HC4": 0, "HC5": 0}
    for s_idx, sh in enumerate(shifts):
        assigned = sum(1 for e in range(n_emp) if assignments.get((e, s_idx), 0) == 1)
        if assigned < sh["required_count"]:
            hc["HC1"] += sh["required_count"] - assigned
    for e_idx, emp in enumerate(employees):
        if len(emp_shifts[e_idx]) * SHIFT_HOURS > emp["max_hours_per_week"]:
            hc["HC2"] += 1
    for e_idx, emp in enumerate(employees):
        for s_idx in emp_shifts[e_idx]:
            if shifts[s_idx]["day"] in emp["unavailable_days"]:
                hc["HC3"] += 1
    for e_idx, emp in enumerate(employees):
        for s_idx in emp_shifts[e_idx]:
            if not shifts[s_idx]["required_skills"].issubset(emp["skills"]):
                hc["HC4"] += 1
    for e_idx in range(n_emp):
        for d_idx in range(len(DAYS) - 1):
            night_idx = d_idx * 3 + 2
            next_morning_idx = (d_idx + 1) * 3
            if night_idx < n_shift and next_morning_idx < n_shift:
                if assignments.get((e_idx, night_idx), 0) == 1 and \
                   assignments.get((e_idx, next_morning_idx), 0) == 1:
                    hc["HC5"] += 1
    total_hc = sum(hc.values())

    sc = {"SC1": 0, "SC2": 0.0, "SC3": 0, "SC4": 0, "SC5": 0}
    for e_idx in range(n_emp):
        days_worked = sorted(set(s_idx // 3 for s_idx in emp_shifts[e_idx]))
        consec = 1
        for i in range(1, len(days_worked)):
            consec = consec + 1 if days_worked[i] == days_worked[i-1] + 1 else 1
            if consec > 5:
                sc["SC1"] += 1
    hours_list = [len(emp_shifts[e]) * SHIFT_HOURS for e in range(n_emp)]
    if hours_list:
        mean_h = sum(hours_list) / len(hours_list)
        sc["SC2"] = round((sum((h - mean_h) ** 2 for h in hours_list) / len(hours_list)) ** 0.5, 2)
    for e_idx, emp in enumerate(employees):
        if len(emp_shifts[e_idx]) * SHIFT_HOURS < emp["min_hours_per_week"]:
            sc["SC3"] += 1
    for e_idx in range(n_emp):
        nc = sum(1 for s in emp_shifts[e_idx] if shifts[s]["shift_name"] == "night")
        if nc > 2:
            sc["SC4"] += nc - 2
    training_emps = {e for e in range(n_emp) if "training" in employees[e]["skills"]}
    for d_idx in range(7):
        has = any(
            assignments.get((e, d_idx * 3 + off), 0) == 1 and e in training_emps
            for off in range(3) for e in range(n_emp)
            if d_idx * 3 + off < n_shift
        )
        if not has:
            sc["SC5"] += 1

    feasible = total_hc == 0
    soft_score = 100 - sc["SC1"] * 5 - sc["SC2"] * 2 - sc["SC3"] * 5 - sc["SC4"] * 5 - sc["SC5"] * 3
    total_score = (1000 if feasible else 0) + max(soft_score, 0)

    staffing = {}
    for s_idx, sh in enumerate(shifts):
        assigned = sum(1 for e in range(n_emp) if assignments.get((e, s_idx), 0) == 1)
        staffing[f"{sh['day']}_{sh['shift_name']}"] = f"{assigned}/{sh['required_count']}"

    return {
        "feasible": feasible, "hard_violations": hc, "total_hard": total_hc,
        "soft_penalties": sc, "soft_score": round(soft_score, 1),
        "total_score": round(total_score, 1),
        "hours_per_employee": {employees[e]["name"]: len(emp_shifts[e]) * SHIFT_HOURS for e in range(n_emp)},
        "staffing": staffing,
    }


def build_solver(employees, shifts, *, relax_hc5=False, modified_required=None):
    """共通ソルバー構築。オプションでHC5緩和やrequired_count変更。"""
    n_emp, n_shift = len(employees), len(shifts)
    model = cp_model.CpModel()

    x = {}
    for e in range(n_emp):
        for s in range(n_shift):
            x[e, s] = model.new_bool_var(f"x_{e}_{s}")

    # HC1: required_count (possibly modified)
    for s_idx, sh in enumerate(shifts):
        req = modified_required[s_idx] if modified_required else sh["required_count"]
        model.add(sum(x[e, s_idx] for e in range(n_emp)) == req)

    # HC2: max hours
    for e_idx, emp in enumerate(employees):
        model.add(sum(x[e_idx, s] for s in range(n_shift)) <= emp["max_hours_per_week"] // SHIFT_HOURS)

    # HC3: unavailable
    for e_idx, emp in enumerate(employees):
        for s_idx, sh in enumerate(shifts):
            if sh["day"] in emp["unavailable_days"]:
                model.add(x[e_idx, s_idx] == 0)

    # HC4: skills
    for e_idx, emp in enumerate(employees):
        for s_idx, sh in enumerate(shifts):
            if not sh["required_skills"].issubset(emp["skills"]):
                model.add(x[e_idx, s_idx] == 0)

    # HC5: night->morning (optional relaxation)
    hc5_violations = []
    if not relax_hc5:
        for e_idx in range(n_emp):
            for d_idx in range(len(DAYS) - 1):
                ni = d_idx * 3 + 2
                nm = (d_idx + 1) * 3
                if ni < n_shift and nm < n_shift:
                    model.add(x[e_idx, ni] + x[e_idx, nm] <= 1)
    else:
        # Soft: penalize but allow
        for e_idx in range(n_emp):
            for d_idx in range(len(DAYS) - 1):
                ni = d_idx * 3 + 2
                nm = (d_idx + 1) * 3
                if ni < n_shift and nm < n_shift:
                    v = model.new_bool_var(f"hc5v_{e_idx}_{d_idx}")
                    model.add(x[e_idx, ni] + x[e_idx, nm] <= 1 + v)
                    hc5_violations.append(v)

    # 1 shift per day
    for e_idx in range(n_emp):
        for d_idx in range(7):
            ds = [d_idx * 3 + off for off in range(3) if d_idx * 3 + off < n_shift]
            model.add(sum(x[e_idx, s] for s in ds) <= 1)

    # Soft objectives
    emp_counts = []
    for e_idx in range(n_emp):
        c = model.new_int_var(0, 7, f"cnt_{e_idx}")
        model.add(c == sum(x[e_idx, s] for s in range(n_shift)))
        emp_counts.append(c)

    max_c = model.new_int_var(0, 7, "maxc")
    min_c = model.new_int_var(0, 7, "minc")
    model.add_max_equality(max_c, emp_counts)
    model.add_min_equality(min_c, emp_counts)
    gap = model.new_int_var(0, 7, "gap")
    model.add(gap == max_c - min_c)

    # SC3: min hours shortfall
    min_sf = []
    for e_idx, emp in enumerate(employees):
        ms = emp["min_hours_per_week"] // SHIFT_HOURS
        sf = model.new_int_var(0, 7, f"msf_{e_idx}")
        model.add(sf >= ms - emp_counts[e_idx])
        min_sf.append(sf)

    # SC4: night excess
    night_ex = []
    for e_idx in range(n_emp):
        ni_idx = [s for s in range(n_shift) if shifts[s]["shift_name"] == "night"]
        nc = model.new_int_var(0, 7, f"nc_{e_idx}")
        model.add(nc == sum(x[e_idx, s] for s in ni_idx))
        ex = model.new_int_var(0, 7, f"nex_{e_idx}")
        model.add(ex >= nc - 2)
        night_ex.append(ex)

    # SC5: training
    tmiss = []
    tr_emps = [e for e in range(n_emp) if "training" in employees[e]["skills"]]
    for d_idx in range(7):
        ds = [d_idx * 3 + off for off in range(3) if d_idx * 3 + off < n_shift]
        ta = [x[e, s] for e in tr_emps for s in ds]
        m = model.new_bool_var(f"tm_{d_idx}")
        model.add(sum(ta) >= 1).only_enforce_if(m.Not())
        model.add(sum(ta) == 0).only_enforce_if(m)
        tmiss.append(m)

    # 目的関数: 評価関数と精密一致（パターン1）
    # 評価関数: soft_score = 100 - SC1*5 - SC2*2 - SC3*5 - SC4*5 - SC5*3
    # SC2 = std_dev of hours ≈ gap * some_factor (近似)
    # gap=0: std=0, gap=1: std≈2.53, gap=2: std≈5.06 → gap*2を使う
    obj_terms = (
        gap * 4            # SC2: fairness (gap→std_dev近似、weight=2)
        + sum(min_sf) * 5  # SC3: min hours (weight=5)
        + sum(night_ex) * 5  # SC4: night (weight=5)
        + sum(tmiss) * 3   # SC5: training (weight=3)
    )
    if relax_hc5:
        obj_terms += sum(hc5_violations) * 50  # HC5 violation heavy penalty

    model.minimize(obj_terms)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    solver.parameters.num_workers = 4
    status = solver.solve(model)

    assignments = {}
    info = {"wall_time": round(solver.wall_time, 2)}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for e in range(n_emp):
            for s in range(n_shift):
                assignments[(e, s)] = solver.value(x[e, s])
        info["status"] = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"
        info["objective"] = solver.objective_value
        info["gap"] = solver.value(gap)
        if relax_hc5:
            info["hc5_violations_allowed"] = sum(solver.value(v) for v in hc5_violations)
    else:
        for e in range(n_emp):
            for s in range(n_shift):
                assignments[(e, s)] = 0
        info["status"] = "INFEASIBLE"

    return assignments, info


def main():
    employees, shifts = load_data()
    results = {}

    # ─── 改善策A: HC5緩和（夜勤→朝勤を許可、ただし高ペナルティ） ───
    print("=" * 60)
    print("改善策A: HC5(夜勤→朝勤禁止)を緩和")
    print("  目的: HC5を壊してでもHC1(人員充足)を完全達成")
    print("=" * 60)
    a_a, info_a = build_solver(employees, shifts, relax_hc5=True)
    r_a = evaluate(a_a, employees, shifts)
    print(f"Solver: {info_a}")
    print(f"Feasible: {r_a['feasible']}, HC: {r_a['hard_violations']}, Soft: {r_a['soft_score']}, Total: {r_a['total_score']}")
    print(f"Hours: {r_a['hours_per_employee']}")
    results["A_relax_hc5"] = {**r_a, "solver_info": info_a}

    # ─── 改善策B: 運用変更（Wed朝3→2、Sun午後2→1） ───
    print("\n" + "=" * 60)
    print("改善策B: 運用変更 — 需要を2シフト削減")
    print("  Wed morning: 3→2, Sun afternoon: 2→1")
    print("=" * 60)
    mod_req = [sh["required_count"] for sh in shifts]
    # Wed morning = index 6 (Wed=2, morning=0, 2*3+0=6)
    mod_req[6] = 2  # Wed morning: 3→2
    # Sun afternoon = index 19 (Sun=6, afternoon=1, 6*3+1=19)
    mod_req[19] = 1  # Sun afternoon: 2→1

    a_b, info_b = build_solver(employees, shifts, modified_required=mod_req)
    # Evaluate with modified shifts for HC1 check
    shifts_mod = []
    for i, sh in enumerate(shifts):
        sh_copy = dict(sh)
        sh_copy["required_count"] = mod_req[i]
        shifts_mod.append(sh_copy)
    r_b = evaluate(a_b, employees, shifts_mod)
    print(f"Solver: {info_b}")
    print(f"Feasible: {r_b['feasible']}, HC: {r_b['hard_violations']}, Soft: {r_b['soft_score']}, Total: {r_b['total_score']}")
    print(f"Hours: {r_b['hours_per_employee']}")
    results["B_reduced_demand"] = {**r_b, "solver_info": info_b}

    # Also evaluate against original requirements (to show what changed)
    r_b_orig = evaluate(a_b, employees, shifts)
    print(f"\n(元の需要基準で評価: HC1={r_b_orig['hard_violations']['HC1']}件不足)")
    results["B_reduced_demand_vs_original"] = r_b_orig

    # ─── 改善策C: 需要1シフトだけ削減（最小変更） ───
    print("\n" + "=" * 60)
    print("改善策C: 最小運用変更 — 需要を1シフトだけ削減 + ソフト最適化")
    print("  Sun afternoon: 2→1 のみ（水曜朝は3人維持）")
    print("=" * 60)
    mod_req2 = [sh["required_count"] for sh in shifts]
    mod_req2[19] = 1  # Sun afternoon only

    a_c, info_c = build_solver(employees, shifts, modified_required=mod_req2)
    shifts_mod2 = []
    for i, sh in enumerate(shifts):
        sh_copy = dict(sh)
        sh_copy["required_count"] = mod_req2[i]
        shifts_mod2.append(sh_copy)
    r_c = evaluate(a_c, employees, shifts_mod2)
    print(f"Solver: {info_c}")
    print(f"Feasible: {r_c['feasible']}, HC: {r_c['hard_violations']}, Soft: {r_c['soft_score']}, Total: {r_c['total_score']}")
    print(f"Hours: {r_c['hours_per_employee']}")
    r_c_orig = evaluate(a_c, employees, shifts)
    print(f"(元の需要基準: HC1={r_c_orig['hard_violations']['HC1']}件不足)")
    results["C_minimal_change"] = {**r_c, "solver_info": info_c}

    # ─── サマリー ───
    print("\n" + "=" * 60)
    print("改善結果サマリー")
    print("=" * 60)
    print(f"{'手法':<30} {'Feasible':<10} {'HC違反':<8} {'Soft':<8} {'Total':<8}")
    print("-" * 64)
    print(f"{'ベースライン(ソルバーHC1緩和)':<30} {'No':<10} {'2':<8} {'89.4':<8} {'89.4':<8}")
    print(f"{'A: HC5緩和':<30} {str(r_a['feasible']):<10} {r_a['total_hard']:<8} {r_a['soft_score']:<8} {r_a['total_score']:<8}")
    print(f"{'B: 需要2削減':<30} {str(r_b['feasible']):<10} {r_b['total_hard']:<8} {r_b['soft_score']:<8} {r_b['total_score']:<8}")
    print(f"{'C: 需要1削減(最小変更)':<30} {str(r_c['feasible']):<10} {r_c['total_hard']:<8} {r_c['soft_score']:<8} {r_c['total_score']:<8}")

    with open(RESULTS_DIR / "improve_results.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nSaved to {RESULTS_DIR / 'improve_results.json'}")


if __name__ == "__main__":
    main()
