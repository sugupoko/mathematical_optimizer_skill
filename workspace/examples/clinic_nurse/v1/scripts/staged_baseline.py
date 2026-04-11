"""
段階的 baseline — clinic_nurse v1

assess で complexity=complex 判定のため、段階的に HC を追加して
各 Phase で feasibility と独立 HC 検証器による違反数を記録する。

Phase 0: 変数のみ（制約なし）
Phase 1: +HC1 (shift demand)
Phase 2: +HC2 (max hours)
Phase 3: +HC3 (unavailable days)
Phase 4: +HC4 (certification)
Phase 5: +HC5 (11h rest between evening -> morning)
Phase 6: +HC6 (1 shift per day)
Phase 7: +HC7 (senior required)
Phase 8: +HC8 (1 clinic per day) = FULL
"""

from __future__ import annotations

import csv
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from ortools.sat.python import cp_model

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RESULTS = ROOT / "results"
REPORTS = ROOT / "reports"
RESULTS.mkdir(parents=True, exist_ok=True)
REPORTS.mkdir(parents=True, exist_ok=True)

DAYS_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TIME_LIMIT = 60.0
NUM_WORKERS = 4


# ---------- Data loaders ----------
def _split(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def load_nurses():
    rows = []
    with open(DATA / "nurses.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "id": r["nurse_id"],
                "name": r["name"],
                "level": r["level"],
                "certs": set(_split(r["certifications"])),
                "max_h": int(r["max_hours_per_week"]),
                "min_h": int(r["min_hours_per_week"]),
                "home": r["home_clinic"],
                "unavail": set(_split(r["unavailable_days"])),
                "langs": set(_split(r["languages"])),
            })
    return rows


def load_shifts():
    rows = []
    with open(DATA / "shifts.csv", encoding="utf-8") as f:
        for idx, r in enumerate(csv.DictReader(f)):
            start_h = int(r["start_time"].split(":")[0]) + int(r["start_time"].split(":")[1]) / 60
            end_h = int(r["end_time"].split(":")[0]) + int(r["end_time"].split(":")[1]) / 60
            dur = end_h - start_h
            rows.append({
                "idx": idx,
                "week": int(r["week"]),
                "day": r["day"],
                "clinic": r["clinic"],
                "name": r["shift_name"],
                "start": r["start_time"],
                "end": r["end_time"],
                "hours": dur,
                "required": int(r["nurse_required"]),
                "certs": set(_split(r["required_certifications"])),
                "senior_req": int(r["senior_required"]),
            })
    return rows


def shift_global_day(s):
    """Returns 0-13 for 2 weeks"""
    return (s["week"] - 1) * 7 + DAYS_ORDER.index(s["day"])


# ---------- Model builder ----------
def build_model(
    nurses, shifts,
    add_hc1=False, add_hc2=False, add_hc3=False, add_hc4=False,
    add_hc5=False, add_hc6=False, add_hc7=False, add_hc8=False,
):
    m = cp_model.CpModel()
    nN, nS = len(nurses), len(shifts)

    # Decision variables: x[nurse, shift] in {0,1}
    x = {(ni, si): m.NewBoolVar(f"x_{ni}_{si}") for ni in range(nN) for si in range(nS)}

    if add_hc1:
        # HC1: each shift has required number of nurses
        for s in shifts:
            m.Add(sum(x[ni, s["idx"]] for ni in range(nN)) == s["required"])

    if add_hc2:
        # HC2: weekly max hours per nurse
        for ni, n in enumerate(nurses):
            for wk in (1, 2):
                wk_shifts = [s for s in shifts if s["week"] == wk]
                hours_sum = sum(
                    int(s["hours"] * 10) * x[ni, s["idx"]] for s in wk_shifts
                )
                # max_h * 10 to match integer scaling
                m.Add(hours_sum <= n["max_h"] * 10)

    if add_hc3:
        # HC3: unavailable days
        for ni, n in enumerate(nurses):
            for s in shifts:
                if s["day"] in n["unavail"]:
                    m.Add(x[ni, s["idx"]] == 0)

    if add_hc4:
        # HC4: cert matching
        for ni, n in enumerate(nurses):
            for s in shifts:
                if not s["certs"].issubset(n["certs"]):
                    m.Add(x[ni, s["idx"]] == 0)

    if add_hc5:
        # HC5: no morning after evening (same nurse, next day)
        # Group shifts by (nurse, global_day, name)
        day_of = {s["idx"]: shift_global_day(s) for s in shifts}
        evening_shifts_by_day = defaultdict(list)  # day -> list of shift idx
        morning_shifts_by_day = defaultdict(list)
        for s in shifts:
            d = day_of[s["idx"]]
            if s["name"] == "evening":
                evening_shifts_by_day[d].append(s["idx"])
            elif s["name"] == "morning":
                morning_shifts_by_day[d].append(s["idx"])

        for ni in range(nN):
            for d in range(14):
                next_d = d + 1
                if next_d not in morning_shifts_by_day:
                    continue
                for ev_si in evening_shifts_by_day.get(d, []):
                    for mo_si in morning_shifts_by_day[next_d]:
                        m.Add(x[ni, ev_si] + x[ni, mo_si] <= 1)

    if add_hc6:
        # HC6: at most 1 shift per day per nurse
        day_of = {s["idx"]: shift_global_day(s) for s in shifts}
        shifts_by_day = defaultdict(list)
        for s in shifts:
            shifts_by_day[day_of[s["idx"]]].append(s["idx"])
        for ni in range(nN):
            for d, s_list in shifts_by_day.items():
                m.Add(sum(x[ni, si] for si in s_list) <= 1)

    if add_hc7:
        # HC7: senior required on senior_required=1 shifts
        senior_idx = [ni for ni, n in enumerate(nurses) if n["level"] == "senior"]
        for s in shifts:
            if s["senior_req"] == 1:
                m.Add(sum(x[ni, s["idx"]] for ni in senior_idx) >= 1)

    if add_hc8:
        # HC8: at most 1 clinic per day per nurse
        # For each (nurse, day), sum of shifts across clinics <= 1
        # Already enforced by HC6 (1 shift/day), so HC8 is implied by HC6
        # But make it explicit for clarity: sum across any clinic's shifts on same day <= 1
        # This is strictly equivalent to HC6 here, so nothing new to add.
        pass

    return m, x


# ---------- Independent HC verifier ----------
def verify_hcs(x_values, nurses, shifts):
    nN, nS = len(nurses), len(shifts)
    day_of = {s["idx"]: shift_global_day(s) for s in shifts}

    violations = {f"HC{i}": 0 for i in range(1, 9)}

    # HC1
    for s in shifts:
        cnt = sum(x_values[ni, s["idx"]] for ni in range(nN))
        if cnt != s["required"]:
            violations["HC1"] += 1

    # HC2
    for ni, n in enumerate(nurses):
        for wk in (1, 2):
            h = sum(s["hours"] for s in shifts if s["week"] == wk and x_values[ni, s["idx"]])
            if h > n["max_h"]:
                violations["HC2"] += 1

    # HC3
    for ni, n in enumerate(nurses):
        for s in shifts:
            if s["day"] in n["unavail"] and x_values[ni, s["idx"]]:
                violations["HC3"] += 1

    # HC4
    for ni, n in enumerate(nurses):
        for s in shifts:
            if x_values[ni, s["idx"]] and not s["certs"].issubset(n["certs"]):
                violations["HC4"] += 1

    # HC5: evening -> next morning
    for ni in range(nN):
        for s in shifts:
            if s["name"] != "evening" or not x_values[ni, s["idx"]]:
                continue
            d = day_of[s["idx"]]
            for s2 in shifts:
                if s2["name"] == "morning" and day_of[s2["idx"]] == d + 1 and x_values[ni, s2["idx"]]:
                    violations["HC5"] += 1

    # HC6: 1 shift per day
    for ni in range(nN):
        day_counts = defaultdict(int)
        for s in shifts:
            if x_values[ni, s["idx"]]:
                day_counts[day_of[s["idx"]]] += 1
        for d, c in day_counts.items():
            if c > 1:
                violations["HC6"] += 1

    # HC7
    senior_idx = {ni for ni, n in enumerate(nurses) if n["level"] == "senior"}
    for s in shifts:
        if s["senior_req"] == 1:
            senior_count = sum(x_values[ni, s["idx"]] for ni in senior_idx)
            if senior_count < 1:
                violations["HC7"] += 1

    # HC8: 1 clinic per day (redundant with HC6, but verify)
    for ni in range(nN):
        day_clinics = defaultdict(set)
        for s in shifts:
            if x_values[ni, s["idx"]]:
                day_clinics[day_of[s["idx"]]].add(s["clinic"])
        for d, cs in day_clinics.items():
            if len(cs) > 1:
                violations["HC8"] += 1

    return {
        "total": sum(violations.values()),
        "by_hc": violations,
        "all_ok": sum(violations.values()) == 0,
    }


# ---------- Phase runner ----------
PHASES = [
    ("phase0_vars_only",  {}),
    ("phase1_hc1",        {"add_hc1": True}),
    ("phase2_hc1_hc2",    {"add_hc1": True, "add_hc2": True}),
    ("phase3_hc1_hc3",    {"add_hc1": True, "add_hc2": True, "add_hc3": True}),
    ("phase4_hc1_hc4",    {"add_hc1": True, "add_hc2": True, "add_hc3": True, "add_hc4": True}),
    ("phase5_hc1_hc5",    {"add_hc1": True, "add_hc2": True, "add_hc3": True, "add_hc4": True, "add_hc5": True}),
    ("phase6_hc1_hc6",    {"add_hc1": True, "add_hc2": True, "add_hc3": True, "add_hc4": True, "add_hc5": True, "add_hc6": True}),
    ("phase7_hc1_hc7",    {"add_hc1": True, "add_hc2": True, "add_hc3": True, "add_hc4": True, "add_hc5": True, "add_hc6": True, "add_hc7": True}),
    ("phase8_full",       {"add_hc1": True, "add_hc2": True, "add_hc3": True, "add_hc4": True, "add_hc5": True, "add_hc6": True, "add_hc7": True, "add_hc8": True}),
]


def solve_phase(name, flags, nurses, shifts):
    t0 = time.time()
    model, x = build_model(nurses, shifts, **flags)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TIME_LIMIT
    solver.parameters.num_search_workers = NUM_WORKERS

    # Phase 0 has no objective; others: use dummy satisfaction
    status = solver.Solve(model)
    elapsed = time.time() - t0

    status_name = solver.StatusName(status)
    feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    result = {
        "phase": name,
        "flags": {k: v for k, v in flags.items() if v},
        "solver_status": status_name,
        "solver_feasible": feasible,
        "time_sec": round(elapsed, 2),
    }

    if feasible:
        x_values = {(ni, si): solver.Value(x[ni, si])
                    for ni in range(len(nurses)) for si in range(len(shifts))}
        total_assigned = sum(x_values.values())

        # Independent HC verifier on the raw assignment (with ALL HCs checked)
        verify = verify_hcs(x_values, nurses, shifts)
        result["total_assigned"] = total_assigned
        result["hc_verify"] = verify
    else:
        result["total_assigned"] = None
        result["hc_verify"] = None

    return result


def main():
    nurses = load_nurses()
    shifts = load_shifts()
    nN, nS = len(nurses), len(shifts)

    print("=" * 72)
    print("STAGED BASELINE — clinic_nurse v1")
    print("=" * 72)
    print(f"Nurses: {nN}  Shifts: {nS}  Variables: {nN*nS}")
    print(f"time_limit per phase = {TIME_LIMIT}s, workers = {NUM_WORKERS}")
    print()

    results = []
    first_infeasible = None
    for name, flags in PHASES:
        print(f"[{name}] solving...")
        r = solve_phase(name, flags, nurses, shifts)
        results.append(r)

        if r["solver_feasible"]:
            hc_tot = r["hc_verify"]["total"]
            hc_str = "HC ALL OK" if r["hc_verify"]["all_ok"] else f"HC VIOL ({hc_tot})"
            print(f"    -> {r['solver_status']} | assigned={r['total_assigned']} | {hc_str} ({r['time_sec']}s)")
            if not r["hc_verify"]["all_ok"]:
                viol = {k: v for k, v in r["hc_verify"]["by_hc"].items() if v > 0}
                print(f"       violations: {viol}")
        else:
            print(f"    -> {r['solver_status']} (infeasible) ({r['time_sec']}s)")
            if first_infeasible is None:
                first_infeasible = name

    out = RESULTS / "staged_baseline_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "first_infeasible_phase": first_infeasible,
            "phases": results,
        }, f, indent=2, ensure_ascii=False)

    print()
    print(f"Saved: {out}")
    if first_infeasible is None:
        print("RESULT: All phases feasible — problem is solvable with all HCs.")
    else:
        print(f"RESULT: First infeasibility at {first_infeasible}")


if __name__ == "__main__":
    main()
