"""シフト最適化 改善策: 3シナリオの検証。

シナリオA: 1名追加（E011: phone+reception, max40h）
シナリオB: 夜勤最低人数を2→1に緩和
シナリオC: 公平性重視の重み調整（現行10名のまま）

Usage:
    python improve.py
"""

from __future__ import annotations

import csv
import json
import logging
import copy
from pathlib import Path
from typing import Any

from ortools.sat.python import cp_model

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SHIFTS = ["morning", "afternoon", "night"]
HOURS_PER_SHIFT = 8
DAY_INDEX = {d: i for i, d in enumerate(DAYS)}


def load_data() -> dict[str, Any]:
    employees = []
    with open(DATA_DIR / "employees.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            emp = {
                "id": row["employee_id"],
                "name": row["name"],
                "skills": [s.strip() for s in row["skills"].split(",")],
                "max_hours": int(row["max_hours_per_week"]),
                "min_hours": int(row["min_hours_per_week"]),
                "unavailable_days": [d.strip() for d in row["unavailable_days"].split(",") if d.strip()],
            }
            employees.append(emp)

    shifts = []
    with open(DATA_DIR / "shifts.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            s = {
                "day": row["day"],
                "shift": row["shift_name"],
                "required": int(row["required_count"]),
                "skill": row["required_skills"].strip(),
            }
            shifts.append(s)

    return {"employees": employees, "shifts": shifts}


# Import evaluator from baseline
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from baseline import evaluate


def solve_cpsat_improved(
    data: dict,
    time_limit: int = 60,
    weights: dict[str, int] | None = None,
) -> tuple[list[dict], float]:
    """CP-SAT solver with configurable weights.

    Returns (schedule, objective_value).
    """
    if weights is None:
        weights = {
            "underfill": 1000,
            "fairness": 50,
            "min_hours": 30,
            "night_limit": 20,
            "training": 15,
            "consecutive": 25,
        }

    model = cp_model.CpModel()
    employees = data["employees"]
    shifts_def = data["shifts"]
    training_emps = {e["id"] for e in employees if "training" in e["skills"]}

    # Decision variables
    x = {}
    for e in employees:
        for sdef in shifts_def:
            key = (e["id"], sdef["day"], sdef["shift"])
            if sdef["skill"] not in e["skills"]:
                continue
            if sdef["day"] in e["unavailable_days"]:
                continue
            x[key] = model.new_bool_var(f'x_{e["id"]}_{sdef["day"]}_{sdef["shift"]}')

    # HC1: Required count (soft with penalty)
    underfill_vars = {}
    for sdef in shifts_def:
        assigned_vars = [x[key] for key in x if key[1] == sdef["day"] and key[2] == sdef["shift"]]
        if assigned_vars:
            underfill = model.new_int_var(0, sdef["required"], f'underfill_{sdef["day"]}_{sdef["shift"]}')
            model.add(sum(assigned_vars) + underfill >= sdef["required"])
            underfill_vars[(sdef["day"], sdef["shift"])] = underfill

    # HC2: Max hours
    for e in employees:
        emp_vars = [x[key] for key in x if key[0] == e["id"]]
        if emp_vars:
            model.add(sum(emp_vars) * HOURS_PER_SHIFT <= e["max_hours"])

    # HC5: No morning after night
    for e in employees:
        for i, day in enumerate(DAYS[:-1]):
            next_day = DAYS[i + 1]
            night_key = (e["id"], day, "night")
            morning_key = (e["id"], next_day, "morning")
            if night_key in x and morning_key in x:
                model.add(x[night_key] + x[morning_key] <= 1)

    # A1: 1 shift per day
    for e in employees:
        for day in DAYS:
            day_vars = [x[key] for key in x if key[0] == e["id"] and key[1] == day]
            if day_vars:
                model.add(sum(day_vars) <= 1)

    # Objective
    objective_terms = []

    # Underfill penalty
    for key, uvar in underfill_vars.items():
        objective_terms.append(uvar * weights["underfill"])

    # SC2: Fairness
    emp_hour_vars = {}
    for e in employees:
        emp_vars = [x[key] for key in x if key[0] == e["id"]]
        if emp_vars:
            h = model.new_int_var(0, e["max_hours"] // HOURS_PER_SHIFT, f'shifts_{e["id"]}')
            model.add(h == sum(emp_vars))
            emp_hour_vars[e["id"]] = h

    if emp_hour_vars:
        max_shifts = model.new_int_var(0, 7, "max_shifts")
        min_shifts = model.new_int_var(0, 7, "min_shifts")
        model.add_max_equality(max_shifts, list(emp_hour_vars.values()))
        model.add_min_equality(min_shifts, list(emp_hour_vars.values()))
        gap = model.new_int_var(0, 7, "gap")
        model.add(gap == max_shifts - min_shifts)
        objective_terms.append(gap * weights["fairness"])

    # SC3: Min hours shortfall
    for e in employees:
        if e["id"] in emp_hour_vars:
            min_shifts_needed = e["min_hours"] // HOURS_PER_SHIFT
            shortfall = model.new_int_var(0, min_shifts_needed, f'shortfall_{e["id"]}')
            model.add(shortfall >= min_shifts_needed - emp_hour_vars[e["id"]])
            objective_terms.append(shortfall * weights["min_hours"])

    # SC4: Night shifts <= 2
    for e in employees:
        night_vars = [x[key] for key in x if key[0] == e["id"] and key[2] == "night"]
        if night_vars:
            excess_night = model.new_int_var(0, 5, f'excess_night_{e["id"]}')
            model.add(excess_night >= sum(night_vars) - 2)
            objective_terms.append(excess_night * weights["night_limit"])

    # SC5: Training coverage
    for day in DAYS:
        trainer_vars = []
        for shift in SHIFTS:
            for eid in training_emps:
                key = (eid, day, shift)
                if key in x:
                    trainer_vars.append(x[key])
        if trainer_vars:
            has_trainer = model.new_bool_var(f'has_trainer_{day}')
            model.add(sum(trainer_vars) >= 1).only_enforce_if(has_trainer)
            model.add(sum(trainer_vars) == 0).only_enforce_if(has_trainer.negated())
            no_trainer = model.new_bool_var(f'no_trainer_{day}')
            model.add(no_trainer == has_trainer.negated())
            objective_terms.append(no_trainer * weights["training"])

    # SC1: Consecutive days
    for e in employees:
        for start in range(len(DAYS) - 5):
            window_vars = []
            for di in range(6):
                day = DAYS[start + di]
                day_vars = [x[key] for key in x if key[0] == e["id"] and key[1] == day]
                if day_vars:
                    day_works = model.new_bool_var(f'works_{e["id"]}_{day}_w{start}')
                    model.add(sum(day_vars) >= 1).only_enforce_if(day_works)
                    model.add(sum(day_vars) == 0).only_enforce_if(day_works.negated())
                    window_vars.append(day_works)
            if len(window_vars) == 6:
                all_six = model.new_bool_var(f'all6_{e["id"]}_{start}')
                model.add(sum(window_vars) >= 6).only_enforce_if(all_six)
                model.add(sum(window_vars) <= 5).only_enforce_if(all_six.negated())
                objective_terms.append(all_six * weights["consecutive"])

    model.minimize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 8

    status = solver.solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return [], float("inf")

    schedule = []
    for key, var in x.items():
        if solver.value(var) == 1:
            schedule.append({"employee_id": key[0], "day": key[1], "shift": key[2]})

    return schedule, solver.objective_value


def main():
    data = load_data()
    results = {}

    # ===== Scenario A: +1 staff =====
    logger.info("=== Scenario A: +1 staff (E011) ===")
    data_a = copy.deepcopy(data)
    data_a["employees"].append({
        "id": "E011",
        "name": "新規 パート",
        "skills": ["reception", "phone"],
        "max_hours": 40,
        "min_hours": 16,
        "unavailable_days": [],
    })
    sched_a, obj_a = solve_cpsat_improved(data_a)
    eval_a = evaluate(sched_a, data_a)
    logger.info("Scenario A: HC violations=%d, soft_total=%.1f, obj=%.1f",
                eval_a["hard_violations"], eval_a["soft_score_total"], obj_a)
    results["scenario_a_add_staff"] = {
        "description": "1名追加（E011: reception+phone, max40h）",
        "schedule": sched_a,
        "evaluation": eval_a,
        "objective_value": obj_a,
    }

    # ===== Scenario B: Night min 1 =====
    logger.info("=== Scenario B: Night min reduced to 1 ===")
    data_b = copy.deepcopy(data)
    for sdef in data_b["shifts"]:
        if sdef["shift"] == "night":
            sdef["required"] = 1
    sched_b, obj_b = solve_cpsat_improved(data_b)
    eval_b = evaluate(sched_b, data_b)
    logger.info("Scenario B: HC violations=%d, soft_total=%.1f, obj=%.1f",
                eval_b["hard_violations"], eval_b["soft_score_total"], obj_b)
    results["scenario_b_night_relax"] = {
        "description": "夜勤最低人数を2→1に緩和",
        "schedule": sched_b,
        "evaluation": eval_b,
        "objective_value": obj_b,
    }

    # ===== Scenario C: Fairness emphasis =====
    logger.info("=== Scenario C: Fairness emphasis ===")
    fairness_weights = {
        "underfill": 1000,
        "fairness": 200,  # 50 -> 200
        "min_hours": 80,  # 30 -> 80
        "night_limit": 40,  # 20 -> 40
        "training": 15,
        "consecutive": 25,
    }
    sched_c, obj_c = solve_cpsat_improved(data, weights=fairness_weights)
    eval_c = evaluate(sched_c, data)
    logger.info("Scenario C: HC violations=%d, soft_total=%.1f, obj=%.1f",
                eval_c["hard_violations"], eval_c["soft_score_total"], obj_c)
    results["scenario_c_fairness"] = {
        "description": "公平性重視の重み調整（現行10名）",
        "schedule": sched_c,
        "evaluation": eval_c,
        "objective_value": obj_c,
    }

    # ===== Baseline (current CP-SAT for comparison) =====
    logger.info("=== Baseline (current) ===")
    sched_base, obj_base = solve_cpsat_improved(data)
    eval_base = evaluate(sched_base, data)
    results["baseline_cpsat"] = {
        "description": "現行CP-SAT（ベースライン）",
        "schedule": sched_base,
        "evaluation": eval_base,
        "objective_value": obj_base,
    }

    # Save results
    output = {}
    for key, res in results.items():
        ev = res["evaluation"]
        output[key] = {
            "description": res["description"],
            "feasible": ev["feasible"],
            "hard_violations": ev["hard_violations"],
            "hard_violations_detail": ev["hard_violations_detail"],
            "soft_score_total": ev["soft_score_total"],
            "soft_scores": ev["soft_scores"],
            "total_assignments": ev["stats"]["total_assignments"],
            "hours_std_dev": ev["stats"]["hours_std_dev"],
            "hours_per_employee": ev["stats"]["hours_per_employee"],
            "objective_value": res["objective_value"],
        }

    with open(RESULTS_DIR / "improve_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logger.info("Results saved to %s", RESULTS_DIR / "improve_results.json")

    # Print comparison table
    print("\n" + "="*80)
    print("  Improvement Scenario Comparison")
    print("="*80)
    print(f"{'Scenario':<30} {'HC Viol':>8} {'Soft Total':>10} {'Assignments':>12} {'Std Dev':>8}")
    print("-"*80)
    for key in ["baseline_cpsat", "scenario_a_add_staff", "scenario_b_night_relax", "scenario_c_fairness"]:
        o = output[key]
        print(f"{o['description']:<30} {o['hard_violations']:>8} {o['soft_score_total']:>10.1f} {o['total_assignments']:>12} {o['hours_std_dev']:>8.2f}")


if __name__ == "__main__":
    main()
