"""
シフト最適化ベースライン: ランダム / 貪欲法 / CP-SAT ソルバー
"""
import csv
import json
import random
import os
import statistics
from pathlib import Path
from ortools.sat.python import cp_model

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SHIFT_NAMES = ["morning", "afternoon", "night"]
SHIFT_HOURS = 8

# --- データ読み込み ---
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


# --- 評価関数 ---
def evaluate(assignment, employees, shifts):
    """assignment: dict of (emp_idx, shift_idx) -> 1/0"""
    violations = {"HC1": 0, "HC2": 0, "HC3": 0, "HC4": 0, "HC5": 0}
    soft_violations = {"SC1": 0, "SC2": 0, "SC3": 0, "SC4": 0, "SC5": 0}

    n_emp = len(employees)
    n_shift = len(shifts)

    # HC1: 各シフトの必要人数
    total_shortage = 0
    for s_idx, shift in enumerate(shifts):
        assigned = sum(assignment.get((e, s_idx), 0) for e in range(n_emp))
        if assigned < shift["required_count"]:
            violations["HC1"] += shift["required_count"] - assigned
            total_shortage += shift["required_count"] - assigned

    # 従業員ごとのチェック
    emp_hours = []
    for e_idx, emp in enumerate(employees):
        assigned_shifts = [s for s in range(n_shift) if assignment.get((e_idx, s), 0)]
        hours = len(assigned_shifts) * SHIFT_HOURS
        emp_hours.append(hours)

        # HC2: 最大勤務時間
        if hours > emp["max_hours"]:
            violations["HC2"] += 1

        # HC3: 利用不可日
        for s_idx in assigned_shifts:
            if shifts[s_idx]["day"] in emp["unavailable"]:
                violations["HC3"] += 1

        # HC4: スキル
        for s_idx in assigned_shifts:
            if shifts[s_idx]["required_skills"] not in emp["skills"]:
                violations["HC4"] += 1

        # HC5: 夜勤翌日朝勤禁止
        for d in range(len(DAYS) - 1):
            night_idx = d * 3 + 2  # night
            next_morning_idx = (d + 1) * 3  # next day morning
            if (assignment.get((e_idx, night_idx), 0) and
                assignment.get((e_idx, next_morning_idx), 0)):
                violations["HC5"] += 1

        # SC1: 連続勤務5日以下
        work_days = set()
        for s_idx in assigned_shifts:
            day_idx = s_idx // 3
            work_days.add(day_idx)
        max_consecutive = 0
        current = 0
        for d in range(7):
            if d in work_days:
                current += 1
                max_consecutive = max(max_consecutive, current)
            else:
                current = 0
        if max_consecutive > 5:
            soft_violations["SC1"] += max_consecutive - 5

        # SC3: 最低勤務時間
        if hours < emp["min_hours"]:
            soft_violations["SC3"] += 1

        # SC4: 夜勤週2回以下
        night_count = sum(1 for s in assigned_shifts if s % 3 == 2)
        if night_count > 2:
            soft_violations["SC4"] += night_count - 2

    # SC2: 公平性（勤務時間の標準偏差）
    if len(emp_hours) > 1:
        soft_violations["SC2"] = round(statistics.stdev(emp_hours), 2)

    # SC5: training保持者の配置
    training_emps = [i for i, e in enumerate(employees) if "training" in e["skills"]]
    for d in range(7):
        day_shifts = [d * 3, d * 3 + 1, d * 3 + 2]
        has_trainer = False
        for s_idx in day_shifts:
            for e_idx in training_emps:
                if assignment.get((e_idx, s_idx), 0):
                    has_trainer = True
                    break
            if has_trainer:
                break
        if not has_trainer:
            soft_violations["SC5"] += 1

    total_hard = sum(violations.values())
    feasible = total_hard == 0
    total_assigned = sum(assignment.values())

    return {
        "feasible": feasible,
        "total_hard_violations": total_hard,
        "hard_violations": violations,
        "soft_violations": soft_violations,
        "total_assigned": total_assigned,
        "total_shortage": total_shortage,
        "emp_hours": emp_hours,
    }


# --- ベースライン1: ランダム ---
def baseline_random(employees, shifts, seed=42):
    random.seed(seed)
    n_emp = len(employees)
    n_shift = len(shifts)
    assignment = {}
    for s_idx, shift in enumerate(shifts):
        chosen = random.sample(range(n_emp), min(shift["required_count"], n_emp))
        for e in chosen:
            assignment[(e, s_idx)] = 1
    return assignment


# --- ベースライン2: 貪欲法（スキル適合+余裕優先） ---
def baseline_greedy(employees, shifts):
    n_emp = len(employees)
    assignment = {}
    emp_hours_used = [0] * n_emp
    emp_day_assigned = [set() for _ in range(n_emp)]  # 1日1シフト制約
    emp_night = [0] * n_emp  # 夜勤カウント

    for s_idx, shift in enumerate(shifts):
        day = shift["day"]
        day_idx = DAYS.index(day)
        shift_type = s_idx % 3  # 0=morning, 1=afternoon, 2=night
        required_skill = shift["required_skills"]
        needed = shift["required_count"]
        assigned_count = 0

        # 候補をスコア順にソート（残り時間が多い人優先）
        candidates = []
        for e_idx, emp in enumerate(employees):
            # スキルチェック
            if required_skill not in emp["skills"]:
                continue
            # 利用不可日チェック
            if day in emp["unavailable"]:
                continue
            # 1日1シフトチェック
            if day_idx in emp_day_assigned[e_idx]:
                continue
            # 最大時間チェック
            if emp_hours_used[e_idx] + SHIFT_HOURS > emp["max_hours"]:
                continue
            # HC5: 夜勤翌日朝勤チェック
            if shift_type == 0 and day_idx > 0:
                prev_night = (day_idx - 1) * 3 + 2
                if assignment.get((e_idx, prev_night), 0):
                    continue
            if shift_type == 2 and day_idx < 6:
                # この人が夜勤に入ると翌朝勤が使えなくなる（先読みはしない、貪欲なので）
                pass

            remaining = emp["max_hours"] - emp_hours_used[e_idx]
            candidates.append((e_idx, remaining))

        # 残り時間が多い順
        candidates.sort(key=lambda x: -x[1])
        for e_idx, _ in candidates[:needed]:
            assignment[(e_idx, s_idx)] = 1
            emp_hours_used[e_idx] += SHIFT_HOURS
            emp_day_assigned[e_idx].add(day_idx)
            if shift_type == 2:
                emp_night[e_idx] += 1
            assigned_count += 1

    return assignment


# --- ベースライン3: CP-SAT ソルバー ---
def baseline_solver(employees, shifts, time_limit=30):
    model = cp_model.CpModel()
    n_emp = len(employees)
    n_shift = len(shifts)

    # 決定変数
    x = {}
    for e in range(n_emp):
        for s in range(n_shift):
            x[(e, s)] = model.NewBoolVar(f"x_{e}_{s}")

    # HC1の不足を計る変数（HC1を完全充足できない可能性があるため）
    shortage = {}
    for s in range(n_shift):
        shortage[s] = model.NewIntVar(0, shifts[s]["required_count"], f"short_{s}")

    # HC1: 各シフトの人数（不足を許容）
    for s_idx, shift in enumerate(shifts):
        model.Add(
            sum(x[(e, s_idx)] for e in range(n_emp)) + shortage[s_idx]
            >= shift["required_count"]
        )

    # HC2: 週あたり最大勤務時間
    for e_idx, emp in enumerate(employees):
        model.Add(
            sum(x[(e_idx, s)] for s in range(n_shift)) * SHIFT_HOURS
            <= emp["max_hours"]
        )

    # HC3: 利用不可日
    for e_idx, emp in enumerate(employees):
        for s_idx, shift in enumerate(shifts):
            if shift["day"] in emp["unavailable"]:
                model.Add(x[(e_idx, s_idx)] == 0)

    # HC4: スキル
    for e_idx, emp in enumerate(employees):
        for s_idx, shift in enumerate(shifts):
            if shift["required_skills"] not in emp["skills"]:
                model.Add(x[(e_idx, s_idx)] == 0)

    # HC5: 夜勤翌日朝勤禁止
    for e in range(n_emp):
        for d in range(len(DAYS) - 1):
            night = d * 3 + 2
            next_morning = (d + 1) * 3
            model.Add(x[(e, night)] + x[(e, next_morning)] <= 1)

    # 1日1シフト（仮定A2）
    for e in range(n_emp):
        for d in range(len(DAYS)):
            day_shifts = [d * 3 + t for t in range(3)]
            model.Add(sum(x[(e, s)] for s in day_shifts) <= 1)

    # 目的関数: 不足の最小化（最優先） + 公平性（副次）
    # 不足最小化
    total_shortage = sum(shortage[s] for s in range(n_shift))

    # 公平性: 各従業員の勤務シフト数の max - min を最小化
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

    # SC4: 夜勤週2回以下（ソフト）
    night_excess = []
    for e in range(n_emp):
        night_shifts = [d * 3 + 2 for d in range(7)]
        night_cnt = model.NewIntVar(0, 7, f"night_{e}")
        model.Add(night_cnt == sum(x[(e, s)] for s in night_shifts))
        excess = model.NewIntVar(0, 7, f"night_excess_{e}")
        model.AddMaxEquality(excess, [night_cnt - 2, model.NewConstant(0)])
        night_excess.append(excess)

    # 重み付き目的関数
    model.Minimize(
        total_shortage * 1000  # 不足は最優先
        + fairness_gap * 10   # 公平性
        + sum(night_excess) * 5  # 夜勤制限
    )

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

    return assignment, status, solver


# --- メイン ---
def main():
    employees, shifts = load_data()
    results = {}

    # ベースライン1: ランダム
    a_random = baseline_random(employees, shifts)
    r_random = evaluate(a_random, employees, shifts)
    results["random"] = r_random
    print("=== ランダム ===")
    print(f"  feasible: {r_random['feasible']}")
    print(f"  hard violations: {r_random['total_hard_violations']} {r_random['hard_violations']}")
    print(f"  shortage: {r_random['total_shortage']}")
    print(f"  soft violations: {r_random['soft_violations']}")
    print(f"  emp_hours: {r_random['emp_hours']}")
    print()

    # ベースライン2: 貪欲法
    a_greedy = baseline_greedy(employees, shifts)
    r_greedy = evaluate(a_greedy, employees, shifts)
    results["greedy"] = r_greedy
    print("=== 貪欲法 ===")
    print(f"  feasible: {r_greedy['feasible']}")
    print(f"  hard violations: {r_greedy['total_hard_violations']} {r_greedy['hard_violations']}")
    print(f"  shortage: {r_greedy['total_shortage']}")
    print(f"  soft violations: {r_greedy['soft_violations']}")
    print(f"  emp_hours: {r_greedy['emp_hours']}")
    print()

    # ベースライン3: ソルバー
    a_solver, status, solver_obj = baseline_solver(employees, shifts)
    r_solver = evaluate(a_solver, employees, shifts)
    status_name = {0: "UNKNOWN", 1: "MODEL_INVALID", 2: "FEASIBLE", 3: "INFEASIBLE", 4: "OPTIMAL"}
    results["solver"] = r_solver
    results["solver"]["solver_status"] = status_name.get(status, str(status))
    results["solver"]["solve_time"] = round(solver_obj.WallTime(), 2)
    print("=== ソルバー (CP-SAT) ===")
    print(f"  status: {status_name.get(status, status)}")
    print(f"  solve_time: {solver_obj.WallTime():.2f}s")
    print(f"  feasible: {r_solver['feasible']}")
    print(f"  hard violations: {r_solver['total_hard_violations']} {r_solver['hard_violations']}")
    print(f"  shortage: {r_solver['total_shortage']}")
    print(f"  soft violations: {r_solver['soft_violations']}")
    print(f"  emp_hours: {r_solver['emp_hours']}")

    # 結果を保存
    with open(RESULTS_DIR / "baseline_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n結果を {RESULTS_DIR / 'baseline_results.json'} に保存しました。")


if __name__ == "__main__":
    main()
