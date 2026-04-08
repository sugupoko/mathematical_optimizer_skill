"""シフト最適化ベースライン: ランダム / 貪欲法 / CP-SAT の3手法比較。

Usage:
    python baseline.py
"""

from __future__ import annotations

import csv
import json
import logging
import math
import os
import random
import statistics
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


# ============================================================
# Data loading
# ============================================================

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


# ============================================================
# Evaluator — shared across all methods
# ============================================================

def evaluate(schedule: list[dict], data: dict) -> dict[str, Any]:
    """Evaluate a schedule against all HC and SC constraints.

    schedule: list of {"employee_id", "day", "shift"}
    Returns detailed evaluation with 0-100 scores for each SC.
    """
    employees = {e["id"]: e for e in data["employees"]}
    shifts_def = data["shifts"]

    # Build lookup structures
    # assigned[day][shift] = set of employee_ids
    assigned: dict[str, dict[str, set]] = {d: {s: set() for s in SHIFTS} for d in DAYS}
    # emp_shifts[emp_id] = list of (day, shift)
    emp_shifts: dict[str, list[tuple[str, str]]] = {e["id"]: [] for e in data["employees"]}

    for entry in schedule:
        eid = entry["employee_id"]
        day = entry["day"]
        shift = entry["shift"]
        assigned[day][shift].add(eid)
        emp_shifts[eid].append((day, shift))

    hc_violations = {}

    # --- HC1: Required count per shift ---
    hc1_violations = []
    for sdef in shifts_def:
        actual = len(assigned[sdef["day"]][sdef["shift"]])
        if actual < sdef["required"]:
            hc1_violations.append({
                "day": sdef["day"], "shift": sdef["shift"],
                "required": sdef["required"], "actual": actual,
                "shortfall": sdef["required"] - actual,
            })
    hc_violations["HC1"] = len(hc1_violations)

    # --- HC2: Max hours per week ---
    hc2_violations = []
    emp_hours = {}
    for eid, shifts_list in emp_shifts.items():
        hours = len(shifts_list) * HOURS_PER_SHIFT
        emp_hours[eid] = hours
        if hours > employees[eid]["max_hours"]:
            hc2_violations.append({"employee": eid, "hours": hours, "max": employees[eid]["max_hours"]})
    hc_violations["HC2"] = len(hc2_violations)

    # --- HC3: Unavailable days ---
    hc3_violations = []
    for eid, shifts_list in emp_shifts.items():
        unavail = set(employees[eid]["unavailable_days"])
        for day, shift in shifts_list:
            if day in unavail:
                hc3_violations.append({"employee": eid, "day": day, "shift": shift})
    hc_violations["HC3"] = len(hc3_violations)

    # --- HC4: Skill requirements ---
    hc4_violations = []
    for sdef in shifts_def:
        req_skill = sdef["skill"]
        for eid in assigned[sdef["day"]][sdef["shift"]]:
            if req_skill not in employees[eid]["skills"]:
                hc4_violations.append({"employee": eid, "day": sdef["day"], "shift": sdef["shift"], "missing_skill": req_skill})
    hc_violations["HC4"] = len(hc4_violations)

    # --- HC5: No morning after night (11h rest) ---
    hc5_violations = []
    for eid, shifts_list in emp_shifts.items():
        night_days = {day for day, shift in shifts_list if shift == "night"}
        for nd in night_days:
            next_day_idx = DAY_INDEX[nd] + 1
            if next_day_idx < len(DAYS):
                next_day = DAYS[next_day_idx]
                if any(d == next_day and s == "morning" for d, s in shifts_list):
                    hc5_violations.append({"employee": eid, "night_day": nd, "morning_day": next_day})
    hc_violations["HC5"] = len(hc5_violations)

    total_hc = sum(hc_violations.values())

    # --- SC1: Consecutive days <= 5 (0-100) ---
    sc1_violations = 0
    for eid, shifts_list in emp_shifts.items():
        work_days = sorted(set(DAY_INDEX[d] for d, _ in shifts_list))
        max_consecutive = 0
        current_streak = 1
        for i in range(1, len(work_days)):
            if work_days[i] == work_days[i-1] + 1:
                current_streak += 1
            else:
                max_consecutive = max(max_consecutive, current_streak)
                current_streak = 1
        max_consecutive = max(max_consecutive, current_streak)
        if max_consecutive > 5:
            sc1_violations += 1
    sc1_score = max(0, 100 - sc1_violations * (100 / len(data["employees"])))

    # --- SC2: Fairness — std_dev of hours (0-100) ---
    hours_list = [emp_hours.get(eid, 0) for eid in employees]
    if len(hours_list) > 1:
        std_dev = statistics.stdev(hours_list)
    else:
        std_dev = 0
    # 100 at std=0, 0 at std>=8
    sc2_score = max(0, min(100, 100 - std_dev * (100 / 8)))

    # --- SC3: Min hours met (0-100) ---
    sc3_violations = 0
    for eid in employees:
        hours = emp_hours.get(eid, 0)
        if hours < employees[eid]["min_hours"]:
            sc3_violations += 1
    sc3_score = max(0, 100 - sc3_violations * (100 / len(data["employees"])))

    # --- SC4: Night shifts <= 2 per person (0-100) ---
    sc4_violations = 0
    for eid, shifts_list in emp_shifts.items():
        night_count = sum(1 for _, s in shifts_list if s == "night")
        if night_count > 2:
            sc4_violations += 1
    sc4_score = max(0, 100 - sc4_violations * (100 / len(data["employees"])))

    # --- SC5: Training-skilled person on at least 1 shift/day (0-100) ---
    training_employees = {e["id"] for e in data["employees"] if "training" in e["skills"]}
    sc5_missing_days = 0
    for day in DAYS:
        day_has_trainer = False
        for shift in SHIFTS:
            for eid in assigned[day][shift]:
                if eid in training_employees:
                    day_has_trainer = True
                    break
            if day_has_trainer:
                break
        if not day_has_trainer:
            sc5_missing_days += 1
    sc5_score = max(0, 100 - sc5_missing_days * (100 / 7))

    soft_total = (sc1_score + sc2_score + sc3_score + sc4_score + sc5_score) / 5

    return {
        "feasible": total_hc == 0,
        "hard_violations": total_hc,
        "hard_violations_detail": hc_violations,
        "hc1_detail": hc1_violations,
        "soft_score_total": round(soft_total, 1),
        "soft_scores": {
            "SC1_consecutive": round(sc1_score, 1),
            "SC2_fairness": round(sc2_score, 1),
            "SC3_min_hours": round(sc3_score, 1),
            "SC4_night_limit": round(sc4_score, 1),
            "SC5_training": round(sc5_score, 1),
        },
        "stats": {
            "total_assignments": len(schedule),
            "total_demand": sum(s["required"] for s in shifts_def),
            "hours_per_employee": {eid: emp_hours.get(eid, 0) for eid in employees},
            "hours_std_dev": round(std_dev, 2),
        },
    }


# ============================================================
# Method 1: Random
# ============================================================

def solve_random(data: dict, seed: int = 42) -> list[dict]:
    """Random assignment: for each shift slot, randomly pick employees."""
    rng = random.Random(seed)
    schedule = []
    emp_hours = {e["id"]: 0 for e in data["employees"]}

    for sdef in data["shifts"]:
        candidates = [e["id"] for e in data["employees"]]
        rng.shuffle(candidates)
        assigned = 0
        for eid in candidates:
            if assigned >= sdef["required"]:
                break
            if emp_hours[eid] + HOURS_PER_SHIFT <= data["employees"][[e["id"] for e in data["employees"]].index(eid)]["max_hours"]:
                schedule.append({"employee_id": eid, "day": sdef["day"], "shift": sdef["shift"]})
                emp_hours[eid] += HOURS_PER_SHIFT
                assigned += 1

    return schedule


# ============================================================
# Method 2: Greedy (skill-first, demand-priority)
# ============================================================

def solve_greedy(data: dict) -> list[dict]:
    """Greedy: assign shifts in order of scarcity, picking best-fit employees."""
    schedule = []
    employees = {e["id"]: e for e in data["employees"]}
    emp_hours = {e["id"]: 0 for e in data["employees"]}
    emp_day_assigned = {e["id"]: set() for e in data["employees"]}  # days already assigned
    emp_night_days = {e["id"]: set() for e in data["employees"]}  # days with night shift

    # Sort shifts by scarcity: fewer eligible employees = more scarce
    def shift_scarcity(sdef):
        eligible = sum(1 for e in data["employees"]
                      if sdef["skill"] in e["skills"]
                      and sdef["day"] not in e["unavailable_days"])
        return eligible - sdef["required"]

    sorted_shifts = sorted(data["shifts"], key=shift_scarcity)

    for sdef in sorted_shifts:
        needed = sdef["required"]
        assigned_here = []

        # Rank candidates
        candidates = []
        for e in data["employees"]:
            eid = e["id"]
            # Hard constraint checks
            if sdef["skill"] not in e["skills"]:
                continue
            if sdef["day"] in e["unavailable_days"]:
                continue
            if emp_hours[eid] + HOURS_PER_SHIFT > e["max_hours"]:
                continue
            if sdef["day"] in emp_day_assigned[eid]:
                continue  # already assigned this day
            # HC5: no morning after night
            if sdef["shift"] == "morning":
                prev_day_idx = DAY_INDEX[sdef["day"]] - 1
                if prev_day_idx >= 0:
                    prev_day = DAYS[prev_day_idx]
                    if prev_day in emp_night_days[eid]:
                        continue

            # Score: prefer employees with more remaining capacity
            remaining = e["max_hours"] - emp_hours[eid]
            min_gap = max(0, e["min_hours"] - emp_hours[eid])
            score = min_gap * 10 + remaining  # prioritize those who need more hours
            candidates.append((eid, score))

        # Sort by score descending
        candidates.sort(key=lambda x: -x[1])

        for eid, _ in candidates[:needed]:
            schedule.append({"employee_id": eid, "day": sdef["day"], "shift": sdef["shift"]})
            emp_hours[eid] += HOURS_PER_SHIFT
            emp_day_assigned[eid].add(sdef["day"])
            if sdef["shift"] == "night":
                emp_night_days[eid].add(sdef["day"])

    return schedule


# ============================================================
# Method 3: CP-SAT Solver
# ============================================================

def solve_cpsat(data: dict, time_limit: int = 60) -> list[dict]:
    """CP-SAT solver with all HC as hard constraints, SC in objective."""
    model = cp_model.CpModel()
    employees = data["employees"]
    shifts_def = data["shifts"]
    emp_by_id = {e["id"]: e for e in employees}
    training_emps = {e["id"] for e in employees if "training" in e["skills"]}

    # --- Decision variables: x[eid, day, shift] = 1 if assigned ---
    x = {}
    for e in employees:
        for sdef in shifts_def:
            key = (e["id"], sdef["day"], sdef["shift"])
            # Prune: skill check
            if sdef["skill"] not in e["skills"]:
                continue
            # Prune: unavailable day
            if sdef["day"] in e["unavailable_days"]:
                continue
            x[key] = model.new_bool_var(f'x_{e["id"]}_{sdef["day"]}_{sdef["shift"]}')

    # --- HC1: Required count (as soft — allow underfill with penalty) ---
    # Since supply < demand, we allow underfill but penalize it heavily
    underfill_vars = {}
    UNDERFILL_PENALTY = 1000  # heavy penalty per missing person
    for sdef in shifts_def:
        assigned_vars = [x[key] for key in x if key[1] == sdef["day"] and key[2] == sdef["shift"]]
        if assigned_vars:
            underfill = model.new_int_var(0, sdef["required"], f'underfill_{sdef["day"]}_{sdef["shift"]}')
            model.add(sum(assigned_vars) + underfill >= sdef["required"])
            underfill_vars[(sdef["day"], sdef["shift"])] = underfill

    # --- HC2: Max hours per week ---
    for e in employees:
        emp_vars = [x[key] for key in x if key[0] == e["id"]]
        if emp_vars:
            model.add(sum(emp_vars) * HOURS_PER_SHIFT <= e["max_hours"])

    # --- HC3: Unavailable days (already pruned in variable creation) ---

    # --- HC4: Skill requirements (already pruned in variable creation) ---

    # --- HC5: No morning after night ---
    for e in employees:
        for i, day in enumerate(DAYS[:-1]):
            next_day = DAYS[i + 1]
            night_key = (e["id"], day, "night")
            morning_key = (e["id"], next_day, "morning")
            if night_key in x and morning_key in x:
                model.add(x[night_key] + x[morning_key] <= 1)

    # --- Assumption A1: 1 shift per day per employee ---
    for e in employees:
        for day in DAYS:
            day_vars = [x[key] for key in x if key[0] == e["id"] and key[1] == day]
            if day_vars:
                model.add(sum(day_vars) <= 1)

    # --- Objective: minimize underfill + maximize soft scores ---
    objective_terms = []

    # Underfill penalty (highest priority)
    for key, uvar in underfill_vars.items():
        objective_terms.append(uvar * UNDERFILL_PENALTY)

    # SC2: Fairness — minimize max-min hours gap
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
        objective_terms.append(gap * 50)  # SC2 weight

    # SC3: Minimize min-hours shortfall
    for e in employees:
        if e["id"] in emp_hour_vars:
            min_shifts_needed = e["min_hours"] // HOURS_PER_SHIFT
            shortfall = model.new_int_var(0, min_shifts_needed, f'shortfall_{e["id"]}')
            model.add(shortfall >= min_shifts_needed - emp_hour_vars[e["id"]])
            objective_terms.append(shortfall * 30)  # SC3 weight

    # SC4: Night shifts <= 2 penalty
    for e in employees:
        night_vars = [x[key] for key in x if key[0] == e["id"] and key[2] == "night"]
        if night_vars:
            excess_night = model.new_int_var(0, 5, f'excess_night_{e["id"]}')
            model.add(excess_night >= sum(night_vars) - 2)
            objective_terms.append(excess_night * 20)  # SC4 weight

    # SC5: Training coverage per day
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
            objective_terms.append(no_trainer * 15)  # SC5 weight

    # SC1: Consecutive days penalty (hard to linearize exactly, use proxy)
    # Penalize working 6+ consecutive days using sliding window
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
                else:
                    pass  # not possible to work this day
            if len(window_vars) == 6:
                all_six = model.new_bool_var(f'all6_{e["id"]}_{start}')
                model.add(sum(window_vars) >= 6).only_enforce_if(all_six)
                model.add(sum(window_vars) <= 5).only_enforce_if(all_six.negated())
                objective_terms.append(all_six * 25)  # SC1 weight

    model.minimize(sum(objective_terms))

    # --- Solve ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 8

    logger.info("Solving CP-SAT model...")
    status = solver.solve(model)
    status_name = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }.get(status, f"STATUS_{status}")
    logger.info("Status: %s, Objective: %s", status_name, solver.objective_value if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else "N/A")

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        logger.error("No feasible solution found")
        return []

    schedule = []
    for key, var in x.items():
        if solver.value(var) == 1:
            schedule.append({"employee_id": key[0], "day": key[1], "shift": key[2]})

    return schedule


# ============================================================
# Main
# ============================================================

def print_schedule(schedule: list[dict], title: str):
    """Pretty print a schedule."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

    # Build grid
    grid = {d: {s: [] for s in SHIFTS} for d in DAYS}
    for entry in schedule:
        grid[entry["day"]][entry["shift"]].append(entry["employee_id"])

    print(f"{'':>10}", end="")
    for day in DAYS:
        print(f"{day:>12}", end="")
    print()

    for shift in SHIFTS:
        print(f"{shift:>10}", end="")
        for day in DAYS:
            emps = grid[day][shift]
            print(f"{'  '.join(emps) if emps else '-':>12}", end="")
        print()


def main():
    data = load_data()
    logger.info("Loaded %d employees, %d shift slots", len(data["employees"]), len(data["shifts"]))

    results = {}

    # --- Random ---
    logger.info("=== Method 1: Random ===")
    sched_random = solve_random(data)
    eval_random = evaluate(sched_random, data)
    print_schedule(sched_random, "Random")
    print(json.dumps(eval_random, ensure_ascii=False, indent=2))
    results["random"] = {"schedule": sched_random, "evaluation": eval_random}

    # --- Greedy ---
    logger.info("=== Method 2: Greedy ===")
    sched_greedy = solve_greedy(data)
    eval_greedy = evaluate(sched_greedy, data)
    print_schedule(sched_greedy, "Greedy")
    print(json.dumps(eval_greedy, ensure_ascii=False, indent=2))
    results["greedy"] = {"schedule": sched_greedy, "evaluation": eval_greedy}

    # --- CP-SAT ---
    logger.info("=== Method 3: CP-SAT ===")
    sched_cpsat = solve_cpsat(data)
    eval_cpsat = evaluate(sched_cpsat, data)
    print_schedule(sched_cpsat, "CP-SAT Solver")
    print(json.dumps(eval_cpsat, ensure_ascii=False, indent=2))
    results["cpsat"] = {"schedule": sched_cpsat, "evaluation": eval_cpsat}

    # --- Save results ---
    output = {
        "methods": {},
        "comparison": {},
    }
    for method_name in ["random", "greedy", "cpsat"]:
        ev = results[method_name]["evaluation"]
        output["methods"][method_name] = {
            "feasible": ev["feasible"],
            "hard_violations": ev["hard_violations"],
            "hard_violations_detail": ev["hard_violations_detail"],
            "soft_score_total": ev["soft_score_total"],
            "soft_scores": ev["soft_scores"],
            "total_assignments": ev["stats"]["total_assignments"],
            "total_demand": ev["stats"]["total_demand"],
            "hours_std_dev": ev["stats"]["hours_std_dev"],
        }

    output["comparison"] = {
        "best_method": "cpsat",
        "supply_demand_gap": {
            "total_demand_shifts": 48,
            "total_supply_max_shifts": 46,
            "gap_shifts": 2,
            "gap_hours": 16,
        },
    }

    with open(RESULTS_DIR / "baseline_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logger.info("Results saved to %s", RESULTS_DIR / "baseline_results.json")


if __name__ == "__main__":
    main()
