"""ベースライン v2: HC1(人数充足)をソフト化してソルバーを動かす
供給46 < 需要48 のため、HC1を完全充足できない。
HC1のショートフォールを最小化しつつ、他のHCは厳守する。
"""
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
        total_hours = len(emp_shifts[e_idx]) * SHIFT_HOURS
        if total_hours > emp["max_hours_per_week"]:
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
            if days_worked[i] == days_worked[i-1] + 1:
                consec += 1
            else:
                consec = 1
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
        night_count = sum(1 for s in emp_shifts[e_idx] if shifts[s]["shift_name"] == "night")
        if night_count > 2:
            sc["SC4"] += night_count - 2

    training_emps = {e for e in range(n_emp) if "training" in employees[e]["skills"]}
    for d_idx in range(7):
        has = False
        for off in range(3):
            s_idx = d_idx * 3 + off
            if s_idx < n_shift:
                for e in range(n_emp):
                    if assignments.get((e, s_idx), 0) == 1 and e in training_emps:
                        has = True; break
            if has: break
        if not has:
            sc["SC5"] += 1

    feasible = total_hc == 0
    soft_score = 100 - sc["SC1"] * 5 - sc["SC2"] * 2 - sc["SC3"] * 5 - sc["SC4"] * 5 - sc["SC5"] * 3
    total_score = (1000 if feasible else 0) + max(soft_score, 0)

    # staffing detail
    staffing = {}
    for s_idx, sh in enumerate(shifts):
        assigned = sum(1 for e in range(n_emp) if assignments.get((e, s_idx), 0) == 1)
        key = f"{sh['day']}_{sh['shift_name']}"
        staffing[key] = f"{assigned}/{sh['required_count']}"

    return {
        "feasible": feasible,
        "hard_violations": hc,
        "total_hard": total_hc,
        "soft_penalties": sc,
        "soft_score": round(soft_score, 1),
        "total_score": round(total_score, 1),
        "hours_per_employee": {employees[e]["name"]: len(emp_shifts[e]) * SHIFT_HOURS for e in range(n_emp)},
        "staffing": staffing,
    }


def solver_relaxed(employees, shifts, time_limit=30):
    """HC1をソフト化: 人員ショートフォールを最小化。他HCは厳守。"""
    n_emp, n_shift = len(employees), len(shifts)
    model = cp_model.CpModel()

    x = {}
    for e in range(n_emp):
        for s in range(n_shift):
            x[e, s] = model.new_bool_var(f"x_{e}_{s}")

    # HC2-5 (hard)
    for e_idx, emp in enumerate(employees):
        max_shifts = emp["max_hours_per_week"] // SHIFT_HOURS
        model.add(sum(x[e_idx, s] for s in range(n_shift)) <= max_shifts)
    for e_idx, emp in enumerate(employees):
        for s_idx, sh in enumerate(shifts):
            if sh["day"] in emp["unavailable_days"]:
                model.add(x[e_idx, s_idx] == 0)
    for e_idx, emp in enumerate(employees):
        for s_idx, sh in enumerate(shifts):
            if not sh["required_skills"].issubset(emp["skills"]):
                model.add(x[e_idx, s_idx] == 0)
    for e_idx in range(n_emp):
        for d_idx in range(len(DAYS) - 1):
            night_idx = d_idx * 3 + 2
            next_morning_idx = (d_idx + 1) * 3
            if night_idx < n_shift and next_morning_idx < n_shift:
                model.add(x[e_idx, night_idx] + x[e_idx, next_morning_idx] <= 1)
    # 1 shift per day
    for e_idx in range(n_emp):
        for d_idx in range(7):
            day_shifts_idx = [d_idx * 3 + off for off in range(3) if d_idx * 3 + off < n_shift]
            model.add(sum(x[e_idx, s] for s in day_shifts_idx) <= 1)

    # HC1 relaxed: shortfall variables
    shortfall_hc1 = []
    for s_idx, sh in enumerate(shifts):
        assigned = sum(x[e, s_idx] for e in range(n_emp))
        sf = model.new_int_var(0, sh["required_count"], f"sf_{s_idx}")
        model.add(sf >= sh["required_count"] - assigned)
        shortfall_hc1.append(sf)

    # Soft: fairness
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

    # Soft: min hours shortfall
    min_sf = []
    for e_idx, emp in enumerate(employees):
        ms = emp["min_hours_per_week"] // SHIFT_HOURS
        sf = model.new_int_var(0, 7, f"msf_{e_idx}")
        model.add(sf >= ms - emp_counts[e_idx])
        min_sf.append(sf)

    # Soft: night excess
    night_ex = []
    for e_idx in range(n_emp):
        ni = [s for s in range(n_shift) if shifts[s]["shift_name"] == "night"]
        nc = model.new_int_var(0, 7, f"nc_{e_idx}")
        model.add(nc == sum(x[e_idx, s] for s in ni))
        ex = model.new_int_var(0, 7, f"nex_{e_idx}")
        model.add(ex >= nc - 2)
        night_ex.append(ex)

    # Soft: training coverage
    tmiss = []
    tr_emps = [e for e in range(n_emp) if "training" in employees[e]["skills"]]
    for d_idx in range(7):
        ds = [d_idx * 3 + off for off in range(3) if d_idx * 3 + off < n_shift]
        ta = [x[e, s] for e in tr_emps for s in ds]
        m = model.new_bool_var(f"tm_{d_idx}")
        model.add(sum(ta) >= 1).only_enforce_if(m.Not())
        model.add(sum(ta) == 0).only_enforce_if(m)
        tmiss.append(m)

    # Objective: HC1 shortfall (highest priority) + soft penalties
    model.minimize(
        sum(shortfall_hc1) * 100   # HC1 shortfall (critical)
        + gap * 20                  # SC2 fairness
        + sum(min_sf) * 5           # SC3 min hours
        + sum(night_ex) * 5         # SC4 night limit
        + sum(tmiss) * 3            # SC5 training
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 4
    status = solver.solve(model)

    assignments = {}
    info = {"status": str(status), "wall_time": round(solver.wall_time, 2)}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for e in range(n_emp):
            for s in range(n_shift):
                assignments[(e, s)] = solver.value(x[e, s])
        info["status"] = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"
        info["objective"] = solver.objective_value
        info["hc1_shortfall"] = sum(solver.value(sf) for sf in shortfall_hc1)
        info["fairness_gap"] = solver.value(gap)
    else:
        for e in range(n_emp):
            for s in range(n_shift):
                assignments[(e, s)] = 0
        info["status"] = "INFEASIBLE"

    return assignments, info


def main():
    employees, shifts = load_data()

    print("=" * 60)
    print("Solver (HC1 relaxed): minimize staffing shortfall + soft")
    print("=" * 60)
    a, info = solver_relaxed(employees, shifts, time_limit=30)
    r = evaluate(a, employees, shifts)
    print(f"Solver info: {info}")
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))

    # Save
    with open(RESULTS_DIR / "baseline_v2_results.json", "w") as f:
        json.dump({"solver_relaxed": {**r, "solver_info": info}}, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nSaved to {RESULTS_DIR / 'baseline_v2_results.json'}")


if __name__ == "__main__":
    main()
