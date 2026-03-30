"""3つのベースライン: ランダム / 貪欲法 / CP-SATソルバー"""
from __future__ import annotations
import csv
import random
import json
from pathlib import Path
from ortools.sat.python import cp_model

DATA_DIR = Path(__file__).parent.parent / "data"
RESULTS_DIR = Path(__file__).parent.parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SHIFT_NAMES = ["morning", "afternoon", "night"]
SHIFT_HOURS = 8

# ─── データ読み込み ───

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


# ─── 評価関数（共通） ───

def evaluate(assignments: dict[tuple[int, int], int], employees, shifts):
    """
    assignments: {(emp_idx, shift_idx): 1/0}
    Returns dict with hard/soft violation counts and scores.
    """
    n_emp = len(employees)
    n_shift = len(shifts)

    # Per-employee stats
    emp_shifts = {i: [] for i in range(n_emp)}
    for (e, s), val in assignments.items():
        if val == 1:
            emp_shifts[e].append(s)

    # --- Hard constraints ---
    hc = {"HC1": 0, "HC2": 0, "HC3": 0, "HC4": 0, "HC5": 0}

    # HC1: required_count per shift
    for s_idx, sh in enumerate(shifts):
        assigned = sum(1 for e in range(n_emp) if assignments.get((e, s_idx), 0) == 1)
        if assigned < sh["required_count"]:
            hc["HC1"] += sh["required_count"] - assigned

    # HC2: max_hours_per_week
    for e_idx, emp in enumerate(employees):
        total_hours = len(emp_shifts[e_idx]) * SHIFT_HOURS
        if total_hours > emp["max_hours_per_week"]:
            hc["HC2"] += 1

    # HC3: unavailable_days
    for e_idx, emp in enumerate(employees):
        for s_idx in emp_shifts[e_idx]:
            if shifts[s_idx]["day"] in emp["unavailable_days"]:
                hc["HC3"] += 1

    # HC4: required_skills
    for e_idx, emp in enumerate(employees):
        for s_idx in emp_shifts[e_idx]:
            if not shifts[s_idx]["required_skills"].issubset(emp["skills"]):
                hc["HC4"] += 1

    # HC5: night -> next morning forbidden
    for e_idx in range(n_emp):
        for d_idx in range(len(DAYS) - 1):
            night_idx = d_idx * 3 + 2  # night shift index
            next_morning_idx = (d_idx + 1) * 3  # next day morning
            if night_idx < n_shift and next_morning_idx < n_shift:
                if assignments.get((e_idx, night_idx), 0) == 1 and \
                   assignments.get((e_idx, next_morning_idx), 0) == 1:
                    hc["HC5"] += 1

    total_hc = sum(hc.values())

    # --- Soft constraints ---
    sc = {"SC1": 0, "SC2": 0.0, "SC3": 0, "SC4": 0, "SC5": 0}

    # SC1: consecutive days <= 5
    for e_idx in range(n_emp):
        days_worked = set()
        for s_idx in emp_shifts[e_idx]:
            days_worked.add(s_idx // 3)  # day index
        # Check consecutive runs
        sorted_days = sorted(days_worked)
        max_consec = 0
        consec = 1
        for i in range(1, len(sorted_days)):
            if sorted_days[i] == sorted_days[i-1] + 1:
                consec += 1
            else:
                consec = 1
            max_consec = max(max_consec, consec)
        if max_consec > 5:
            sc["SC1"] += max_consec - 5

    # SC2: fairness (std dev of total hours)
    hours_list = [len(emp_shifts[e]) * SHIFT_HOURS for e in range(n_emp)]
    if hours_list:
        mean_h = sum(hours_list) / len(hours_list)
        variance = sum((h - mean_h) ** 2 for h in hours_list) / len(hours_list)
        sc["SC2"] = round(variance ** 0.5, 2)

    # SC3: min_hours not met
    for e_idx, emp in enumerate(employees):
        total_hours = len(emp_shifts[e_idx]) * SHIFT_HOURS
        if total_hours < emp["min_hours_per_week"]:
            sc["SC3"] += 1

    # SC4: night shifts per person > 2
    for e_idx in range(n_emp):
        night_count = sum(1 for s_idx in emp_shifts[e_idx] if shifts[s_idx]["shift_name"] == "night")
        if night_count > 2:
            sc["SC4"] += night_count - 2

    # SC5: training person in at least 1 shift per day
    for d_idx in range(7):
        has_trainer = False
        for s_offset in range(3):
            s_idx = d_idx * 3 + s_offset
            if s_idx < n_shift:
                for e_idx in range(n_emp):
                    if assignments.get((e_idx, s_idx), 0) == 1 and \
                       "training" in employees[e_idx]["skills"]:
                        has_trainer = True
                        break
            if has_trainer:
                break
        if not has_trainer:
            sc["SC5"] += 1

    # Score: higher is better
    # Feasibility bonus (1000 if all HC satisfied) + soft score
    feasible = 1 if total_hc == 0 else 0
    soft_score = 100 - sc["SC1"] * 5 - sc["SC2"] * 2 - sc["SC3"] * 5 - sc["SC4"] * 5 - sc["SC5"] * 3
    total_score = feasible * 1000 + max(soft_score, 0)

    return {
        "feasible": feasible == 1,
        "hard_violations": hc,
        "total_hard": total_hc,
        "soft_penalties": sc,
        "soft_score": round(soft_score, 1),
        "total_score": round(total_score, 1),
        "hours_per_employee": {employees[e]["name"]: len(emp_shifts[e]) * SHIFT_HOURS for e in range(n_emp)},
    }


# ─── Baseline 1: ランダム ───

def baseline_random(employees, shifts, seed=42):
    random.seed(seed)
    n_emp, n_shift = len(employees), len(shifts)
    assignments = {}
    for s_idx, sh in enumerate(shifts):
        candidates = list(range(n_emp))
        random.shuffle(candidates)
        chosen = candidates[:sh["required_count"]]
        for e in range(n_emp):
            assignments[(e, s_idx)] = 1 if e in chosen else 0
    return assignments


# ─── Baseline 2: 貪欲法（スキル優先） ───

def baseline_greedy(employees, shifts):
    n_emp, n_shift = len(employees), len(shifts)
    assignments = {(e, s): 0 for e in range(n_emp) for s in range(n_shift)}
    emp_hours = [0] * n_emp
    emp_day_assigned = {e: set() for e in range(n_emp)}  # day indices
    emp_night = [0] * n_emp  # night shift count

    for s_idx, sh in enumerate(shifts):
        d_idx = s_idx // 3
        day = sh["day"]
        needed = sh["required_count"]

        # Filter eligible candidates
        candidates = []
        for e_idx, emp in enumerate(employees):
            # HC3: unavailable
            if day in emp["unavailable_days"]:
                continue
            # HC4: skill
            if not sh["required_skills"].issubset(emp["skills"]):
                continue
            # HC2: max hours
            if emp_hours[e_idx] + SHIFT_HOURS > emp["max_hours_per_week"]:
                continue
            # 1 shift per day
            if d_idx in emp_day_assigned[e_idx]:
                continue
            # HC5: night->morning
            if sh["shift_name"] == "morning" and d_idx > 0:
                prev_night_idx = (d_idx - 1) * 3 + 2
                if assignments.get((e_idx, prev_night_idx), 0) == 1:
                    continue

            # Priority: fewer hours first (fairness), training bonus
            priority = -emp_hours[e_idx]
            if "training" in emp["skills"]:
                priority += 1  # slight bonus
            candidates.append((priority, e_idx))

        candidates.sort(reverse=True)
        for _, e_idx in candidates[:needed]:
            assignments[(e_idx, s_idx)] = 1
            emp_hours[e_idx] += SHIFT_HOURS
            emp_day_assigned[e_idx].add(d_idx)
            if sh["shift_name"] == "night":
                emp_night[e_idx] += 1

    return assignments


# ─── Baseline 3: CP-SAT ソルバー ───

def baseline_solver(employees, shifts, time_limit=30):
    n_emp, n_shift = len(employees), len(shifts)
    model = cp_model.CpModel()

    # Variables: x[e, s] = 1 if employee e is assigned to shift s
    x = {}
    for e in range(n_emp):
        for s in range(n_shift):
            x[e, s] = model.new_bool_var(f"x_{e}_{s}")

    # --- Hard constraints ---

    # HC1: required_count per shift
    for s_idx, sh in enumerate(shifts):
        model.add(sum(x[e, s_idx] for e in range(n_emp)) == sh["required_count"])

    # HC2: max_hours_per_week
    for e_idx, emp in enumerate(employees):
        max_shifts = emp["max_hours_per_week"] // SHIFT_HOURS
        model.add(sum(x[e_idx, s] for s in range(n_shift)) <= max_shifts)

    # HC3: unavailable_days
    for e_idx, emp in enumerate(employees):
        for s_idx, sh in enumerate(shifts):
            if sh["day"] in emp["unavailable_days"]:
                model.add(x[e_idx, s_idx] == 0)

    # HC4: required_skills
    for e_idx, emp in enumerate(employees):
        for s_idx, sh in enumerate(shifts):
            if not sh["required_skills"].issubset(emp["skills"]):
                model.add(x[e_idx, s_idx] == 0)

    # HC5: night -> next morning forbidden
    for e_idx in range(n_emp):
        for d_idx in range(len(DAYS) - 1):
            night_idx = d_idx * 3 + 2
            next_morning_idx = (d_idx + 1) * 3
            if night_idx < n_shift and next_morning_idx < n_shift:
                model.add(x[e_idx, night_idx] + x[e_idx, next_morning_idx] <= 1)

    # 1 shift per day
    for e_idx in range(n_emp):
        for d_idx in range(7):
            day_shifts = [d_idx * 3 + offset for offset in range(3) if d_idx * 3 + offset < n_shift]
            model.add(sum(x[e_idx, s] for s in day_shifts) <= 1)

    # --- Soft constraints as objective ---

    # SC2: fairness (minimize max - min hours)
    emp_shift_counts = []
    for e_idx in range(n_emp):
        count = model.new_int_var(0, 7, f"count_{e_idx}")
        model.add(count == sum(x[e_idx, s] for s in range(n_shift)))
        emp_shift_counts.append(count)

    max_count = model.new_int_var(0, 7, "max_count")
    min_count = model.new_int_var(0, 7, "min_count")
    model.add_max_equality(max_count, emp_shift_counts)
    model.add_min_equality(min_count, emp_shift_counts)
    fairness_gap = model.new_int_var(0, 7, "fairness_gap")
    model.add(fairness_gap == max_count - min_count)

    # SC3: min_hours (penalize shortfall)
    shortfall_vars = []
    for e_idx, emp in enumerate(employees):
        min_shifts = emp["min_hours_per_week"] // SHIFT_HOURS
        shortfall = model.new_int_var(0, 7, f"shortfall_{e_idx}")
        model.add(shortfall >= min_shifts - emp_shift_counts[e_idx])
        shortfall_vars.append(shortfall)

    # SC4: night shifts per person <= 2 (penalize excess)
    night_excess_vars = []
    for e_idx in range(n_emp):
        night_shifts_idx = [s for s in range(n_shift) if shifts[s]["shift_name"] == "night"]
        night_count = model.new_int_var(0, 7, f"night_{e_idx}")
        model.add(night_count == sum(x[e_idx, s] for s in night_shifts_idx))
        excess = model.new_int_var(0, 7, f"night_excess_{e_idx}")
        model.add(excess >= night_count - 2)
        night_excess_vars.append(excess)

    # SC5: training person per day
    training_miss = []
    training_emps = [e for e in range(n_emp) if "training" in employees[e]["skills"]]
    for d_idx in range(7):
        day_shifts_idx = [d_idx * 3 + offset for offset in range(3) if d_idx * 3 + offset < n_shift]
        has_trainer = model.new_bool_var(f"trainer_day_{d_idx}")
        # has_trainer = 1 if any training emp is assigned to any shift on this day
        trainer_assignments = [x[e, s] for e in training_emps for s in day_shifts_idx]
        model.add(sum(trainer_assignments) >= 1).only_enforce_if(has_trainer)
        model.add(sum(trainer_assignments) == 0).only_enforce_if(has_trainer.Not())
        miss = model.new_bool_var(f"trainer_miss_{d_idx}")
        model.add(miss == has_trainer.Not())
        training_miss.append(miss)

    # Objective: minimize penalties (lower = better)
    # Weights aligned with evaluation function
    model.minimize(
        fairness_gap * 20  # SC2: fairness (high weight)
        + sum(shortfall_vars) * 5  # SC3: min hours
        + sum(night_excess_vars) * 5  # SC4: night limit
        + sum(training_miss) * 3  # SC5: training coverage
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 4
    status = solver.solve(model)

    assignments = {}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for e in range(n_emp):
            for s in range(n_shift):
                assignments[(e, s)] = solver.value(x[e, s])
        solve_info = {
            "status": "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE",
            "objective": solver.objective_value,
            "wall_time": round(solver.wall_time, 2),
        }
    else:
        # Return empty if infeasible
        for e in range(n_emp):
            for s in range(n_shift):
                assignments[(e, s)] = 0
        solve_info = {"status": "INFEASIBLE", "objective": None, "wall_time": round(solver.wall_time, 2)}

    return assignments, solve_info


# ─── メイン ───

def main():
    employees, shifts = load_data()

    print("=" * 60)
    print("Baseline 1: Random")
    print("=" * 60)
    a1 = baseline_random(employees, shifts)
    r1 = evaluate(a1, employees, shifts)
    print(json.dumps(r1, indent=2, ensure_ascii=False, default=str))

    print("\n" + "=" * 60)
    print("Baseline 2: Greedy (skill-first, fairness-aware)")
    print("=" * 60)
    a2 = baseline_greedy(employees, shifts)
    r2 = evaluate(a2, employees, shifts)
    print(json.dumps(r2, indent=2, ensure_ascii=False, default=str))

    print("\n" + "=" * 60)
    print("Baseline 3: CP-SAT Solver (30s)")
    print("=" * 60)
    a3, info3 = baseline_solver(employees, shifts, time_limit=30)
    r3 = evaluate(a3, employees, shifts)
    print(f"Solver info: {info3}")
    print(json.dumps(r3, indent=2, ensure_ascii=False, default=str))

    # Save results
    results = {"random": r1, "greedy": r2, "solver": {**r3, "solver_info": info3}}
    with open(RESULTS_DIR / "baseline_results.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nResults saved to {RESULTS_DIR / 'baseline_results.json'}")


if __name__ == "__main__":
    main()
