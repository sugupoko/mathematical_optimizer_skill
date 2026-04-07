"""
シフト最適化 改善策の実験:
  改善策A: 不可能性の定量化（何人追加で全充足可能か）
  改善策B: 制約緩和（夜勤を2名→1名に削減）
  改善策C: 公平性の強化（現行人員のまま SC2 を最適化）
"""
import csv
import json
import statistics
from pathlib import Path
from ortools.sat.python import cp_model

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SHIFT_HOURS = 8


def load_data():
    employees = []
    with open(DATA_DIR / "employees.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["skills"] = set(row["skills"].split(","))
            row["max_hours"] = int(row["max_hours_per_week"])
            row["min_hours"] = int(row["min_hours_per_week"])
            row["unavailable"] = set(row["unavailable_days"].split(",")) - {""}
            employees.append(row)

    shifts = []
    with open(DATA_DIR / "shifts.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["required_count"] = int(row["required_count"])
            shifts.append(row)

    return employees, shifts


def evaluate(assignment, employees, shifts):
    violations = {"HC1": 0, "HC2": 0, "HC3": 0, "HC4": 0, "HC5": 0}
    soft_violations = {"SC1": 0, "SC2": 0, "SC3": 0, "SC4": 0, "SC5": 0}
    n_emp = len(employees)
    n_shift = len(shifts)

    total_shortage = 0
    for s_idx, shift in enumerate(shifts):
        assigned = sum(assignment.get((e, s_idx), 0) for e in range(n_emp))
        if assigned < shift["required_count"]:
            violations["HC1"] += shift["required_count"] - assigned
            total_shortage += shift["required_count"] - assigned

    emp_hours = []
    for e_idx, emp in enumerate(employees):
        assigned_shifts = [s for s in range(n_shift) if assignment.get((e_idx, s), 0)]
        hours = len(assigned_shifts) * SHIFT_HOURS
        emp_hours.append(hours)
        if hours > emp["max_hours"]:
            violations["HC2"] += 1
        for s_idx in assigned_shifts:
            if shifts[s_idx]["day"] in emp["unavailable"]:
                violations["HC3"] += 1
            if shifts[s_idx]["required_skills"] not in emp["skills"]:
                violations["HC4"] += 1
        for d in range(len(DAYS) - 1):
            night_idx = d * 3 + 2
            next_morning_idx = (d + 1) * 3
            if (assignment.get((e_idx, night_idx), 0) and
                assignment.get((e_idx, next_morning_idx), 0)):
                violations["HC5"] += 1

        work_days = set()
        for s_idx in assigned_shifts:
            work_days.add(s_idx // 3)
        max_consecutive = current = 0
        for d in range(7):
            if d in work_days:
                current += 1
                max_consecutive = max(max_consecutive, current)
            else:
                current = 0
        if max_consecutive > 5:
            soft_violations["SC1"] += max_consecutive - 5
        if hours < emp["min_hours"]:
            soft_violations["SC3"] += 1
        night_count = sum(1 for s in assigned_shifts if s % 3 == 2)
        if night_count > 2:
            soft_violations["SC4"] += night_count - 2

    if len(emp_hours) > 1:
        soft_violations["SC2"] = round(statistics.stdev(emp_hours), 2)

    training_emps = [i for i, e in enumerate(employees) if "training" in e["skills"]]
    for d in range(7):
        day_shifts = [d * 3 + t for t in range(3)]
        has_trainer = any(
            assignment.get((e_idx, s_idx), 0)
            for s_idx in day_shifts for e_idx in training_emps
        )
        if not has_trainer:
            soft_violations["SC5"] += 1

    total_hard = sum(violations.values())
    return {
        "feasible": total_hard == 0,
        "total_hard_violations": total_hard,
        "hard_violations": violations,
        "soft_violations": soft_violations,
        "total_shortage": total_shortage,
        "emp_hours": emp_hours,
    }


def build_solver(employees, shifts, extra_employees=None, night_override=None):
    """共通ソルバー構築。extra_employees: 追加従業員リスト、night_override: 夜勤人数上書き"""
    all_employees = list(employees)
    if extra_employees:
        all_employees.extend(extra_employees)

    model = cp_model.CpModel()
    n_emp = len(all_employees)
    n_shift = len(shifts)

    x = {}
    for e in range(n_emp):
        for s in range(n_shift):
            x[(e, s)] = model.NewBoolVar(f"x_{e}_{s}")

    shortage = {}
    for s in range(n_shift):
        req = shifts[s]["required_count"]
        if night_override is not None and s % 3 == 2:
            req = night_override
        shortage[s] = model.NewIntVar(0, req, f"short_{s}")
        model.Add(sum(x[(e, s)] for e in range(n_emp)) + shortage[s] >= req)

    for e_idx, emp in enumerate(all_employees):
        model.Add(sum(x[(e_idx, s)] for s in range(n_shift)) * SHIFT_HOURS <= emp["max_hours"])
        for s_idx, shift in enumerate(shifts):
            if shift["day"] in emp["unavailable"]:
                model.Add(x[(e_idx, s_idx)] == 0)
            if shift["required_skills"] not in emp["skills"]:
                model.Add(x[(e_idx, s_idx)] == 0)
        for d in range(len(DAYS) - 1):
            model.Add(x[(e_idx, d * 3 + 2)] + x[(e_idx, (d + 1) * 3)] <= 1)
        for d in range(len(DAYS)):
            day_shifts = [d * 3 + t for t in range(3)]
            model.Add(sum(x[(e_idx, s)] for s in day_shifts) <= 1)

    total_shortage = sum(shortage[s] for s in range(n_shift))

    emp_shift_counts = []
    for e in range(n_emp):
        cnt = model.NewIntVar(0, 21, f"cnt_{e}")
        model.Add(cnt == sum(x[(e, s)] for s in range(n_shift)))
        emp_shift_counts.append(cnt)

    max_shifts = model.NewIntVar(0, 21, "max_shifts")
    min_shifts = model.NewIntVar(0, 21, "min_shifts")
    model.AddMaxEquality(max_shifts, emp_shift_counts)
    model.AddMinEquality(min_shifts, emp_shift_counts)
    fairness_gap = model.NewIntVar(0, 21, "fairness_gap")
    model.Add(fairness_gap == max_shifts - min_shifts)

    night_excess = []
    for e in range(n_emp):
        night_shifts = [d * 3 + 2 for d in range(7)]
        night_cnt = model.NewIntVar(0, 7, f"night_{e}")
        model.Add(night_cnt == sum(x[(e, s)] for s in night_shifts))
        excess = model.NewIntVar(0, 7, f"night_excess_{e}")
        model.AddMaxEquality(excess, [night_cnt - 2, model.NewConstant(0)])
        night_excess.append(excess)

    model.Minimize(
        total_shortage * 1000
        + fairness_gap * 10
        + sum(night_excess) * 5
    )

    return model, x, n_emp, all_employees


def solve_and_evaluate(model, x, n_emp, n_shift, all_employees, shifts, time_limit=30):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 4
    status = solver.Solve(model)

    assignment = {}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for e in range(n_emp):
            for s in range(n_shift):
                if solver.Value(x[(e, s)]):
                    assignment[(e, s)] = 1

    result = evaluate(assignment, all_employees, shifts)
    status_name = {0: "UNKNOWN", 1: "MODEL_INVALID", 2: "FEASIBLE", 3: "INFEASIBLE", 4: "OPTIMAL"}
    result["solver_status"] = status_name.get(status, str(status))
    result["solve_time"] = round(solver.WallTime(), 2)
    return result


# --- 改善策A: 人員追加シミュレーション ---
def improve_a_add_staff(employees, shifts):
    """1人ずつ追加して、何人で全充足できるか調べる"""
    print("=== 改善策A: 人員追加シミュレーション ===")
    n_shift = len(shifts)

    for n_add in range(1, 5):
        extra = []
        for i in range(n_add):
            extra.append({
                "employee_id": f"NEW{i+1:03d}",
                "name": f"追加従業員{i+1}",
                "skills": {"reception", "phone"},
                "max_hours": 40,
                "min_hours": 24,
                "unavailable": set(),
            })

        model, x, n_emp, all_emp = build_solver(employees, shifts, extra_employees=extra)
        result = solve_and_evaluate(model, x, n_emp, n_shift, all_emp, shifts)
        print(f"  +{n_add}人: feasible={result['feasible']}, "
              f"shortage={result['total_shortage']}, "
              f"hard={result['total_hard_violations']}, "
              f"SD={result['soft_violations']['SC2']}h")

        if result["feasible"]:
            print(f"  → {n_add}人追加で全シフト充足可能！")
            return n_add, result

    return None, None


# --- 改善策B: 夜勤人数削減 ---
def improve_b_relax_night(employees, shifts):
    """夜勤の必要人数を2→1に削減"""
    print("\n=== 改善策B: 夜勤人数 2→1 に削減 ===")
    n_shift = len(shifts)

    model, x, n_emp, all_emp = build_solver(employees, shifts, night_override=1)
    result = solve_and_evaluate(model, x, n_emp, n_shift, all_emp, shifts)

    # 評価は元の required_count で行うので HC1 が出るが、
    # 緩和後の基準で再評価する
    # 夜勤を1名にした場合の充足状況を直接チェック
    print(f"  feasible(元基準): {result['feasible']}, shortage(元基準): {result['total_shortage']}")
    print(f"  hard violations: {result['hard_violations']}")
    print(f"  soft violations: {result['soft_violations']}")
    print(f"  emp_hours: {result['emp_hours']}")

    # 緩和基準での再評価
    relaxed_shifts = []
    for s in shifts:
        rs = dict(s)
        if shifts.index(s) % 3 == 2:  # night
            rs["required_count"] = 1
        relaxed_shifts.append(rs)

    # ソルバーを緩和基準で再度走らせる
    model2, x2, n_emp2, all_emp2 = build_solver(employees, relaxed_shifts)
    result_relaxed = solve_and_evaluate(model2, x2, n_emp2, len(relaxed_shifts), all_emp2, relaxed_shifts)
    print(f"  feasible(緩和基準): {result_relaxed['feasible']}, "
          f"shortage: {result_relaxed['total_shortage']}, "
          f"SD: {result_relaxed['soft_violations']['SC2']}h")

    return result_relaxed


# --- 改善策C: 公平性の強化 ---
def improve_c_fairness(employees, shifts):
    """公平性（max-min gap）を最小化しつつ、不足も最小化"""
    print("\n=== 改善策C: 公平性の強化 ===")
    n_shift = len(shifts)

    model = cp_model.CpModel()
    n_emp = len(employees)

    x = {}
    for e in range(n_emp):
        for s in range(n_shift):
            x[(e, s)] = model.NewBoolVar(f"x_{e}_{s}")

    shortage = {}
    for s in range(n_shift):
        shortage[s] = model.NewIntVar(0, shifts[s]["required_count"], f"short_{s}")
        model.Add(sum(x[(e, s)] for e in range(n_emp)) + shortage[s] >= shifts[s]["required_count"])

    for e_idx, emp in enumerate(employees):
        model.Add(sum(x[(e_idx, s)] for s in range(n_shift)) * SHIFT_HOURS <= emp["max_hours"])
        for s_idx, shift in enumerate(shifts):
            if shift["day"] in emp["unavailable"]:
                model.Add(x[(e_idx, s_idx)] == 0)
            if shift["required_skills"] not in emp["skills"]:
                model.Add(x[(e_idx, s_idx)] == 0)
        for d in range(len(DAYS) - 1):
            model.Add(x[(e_idx, d * 3 + 2)] + x[(e_idx, (d + 1) * 3)] <= 1)
        for d in range(len(DAYS)):
            day_shifts = [d * 3 + t for t in range(3)]
            model.Add(sum(x[(e_idx, s)] for s in day_shifts) <= 1)

    total_shortage = sum(shortage[s] for s in range(n_shift))

    # 公平性: 各従業員のシフト数と上限の比率を揃える
    # max_hours が異なるので、比率ベースで公平性を測る
    # → シンプルに max-min gap を最小化
    emp_shift_counts = []
    for e in range(n_emp):
        cnt = model.NewIntVar(0, 21, f"cnt_{e}")
        model.Add(cnt == sum(x[(e, s)] for s in range(n_shift)))
        emp_shift_counts.append(cnt)

    max_shifts = model.NewIntVar(0, 21, "max_shifts")
    min_shifts = model.NewIntVar(0, 21, "min_shifts")
    model.AddMaxEquality(max_shifts, emp_shift_counts)
    model.AddMinEquality(min_shifts, emp_shift_counts)
    fairness_gap = model.NewIntVar(0, 21, "fairness_gap")
    model.Add(fairness_gap == max_shifts - min_shifts)

    # SC3: 最低勤務時間の不足
    min_hours_deficit = []
    for e_idx, emp in enumerate(employees):
        min_shifts_needed = emp["min_hours"] // SHIFT_HOURS
        deficit = model.NewIntVar(0, 10, f"min_deficit_{e_idx}")
        model.AddMaxEquality(deficit, [min_shifts_needed - emp_shift_counts[e_idx], model.NewConstant(0)])
        min_hours_deficit.append(deficit)

    # 夜勤制限
    night_excess = []
    for e in range(n_emp):
        night_shifts = [d * 3 + 2 for d in range(7)]
        night_cnt = model.NewIntVar(0, 7, f"night_{e}")
        model.Add(night_cnt == sum(x[(e, s)] for s in night_shifts))
        excess = model.NewIntVar(0, 7, f"night_excess_{e}")
        model.AddMaxEquality(excess, [night_cnt - 2, model.NewConstant(0)])
        night_excess.append(excess)

    # 目的関数: 不足最小化（最優先）→ 公平性（重み UP）→ 最低時間確保 → 夜勤制限
    model.Minimize(
        total_shortage * 1000
        + fairness_gap * 50      # 公平性の重みを 10 → 50 に UP
        + sum(min_hours_deficit) * 20  # 最低勤務時間も重視
        + sum(night_excess) * 5
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    solver.parameters.num_workers = 4
    status = solver.Solve(model)

    assignment = {}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for e in range(n_emp):
            for s in range(n_shift):
                if solver.Value(x[(e, s)]):
                    assignment[(e, s)] = 1

    result = evaluate(assignment, employees, shifts)
    result["solve_time"] = round(solver.WallTime(), 2)
    status_name = {0: "UNKNOWN", 1: "MODEL_INVALID", 2: "FEASIBLE", 3: "INFEASIBLE", 4: "OPTIMAL"}
    result["solver_status"] = status_name.get(status, str(status))

    print(f"  feasible: {result['feasible']}, shortage: {result['total_shortage']}")
    print(f"  hard violations: {result['hard_violations']}")
    print(f"  soft violations: {result['soft_violations']}")
    print(f"  emp_hours: {result['emp_hours']}")

    return result


def main():
    employees, shifts = load_data()
    results = {}

    # 改善策A
    n_add, result_a = improve_a_add_staff(employees, shifts)
    results["improve_a_add_staff"] = {
        "staff_added": n_add,
        "result": result_a,
    }

    # 改善策B
    result_b = improve_b_relax_night(employees, shifts)
    results["improve_b_relax_night"] = result_b

    # 改善策C
    result_c = improve_c_fairness(employees, shifts)
    results["improve_c_fairness"] = result_c

    with open(RESULTS_DIR / "improve_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)

    print(f"\n結果を {RESULTS_DIR / 'improve_results.json'} に保存しました。")


if __name__ == "__main__":
    main()
