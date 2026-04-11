"""
Staged baseline for worker_supervisor v1.

7 phases incrementally add hard constraints HC1-HC12 to identify
which constraint first makes the problem infeasible.

Variables:
  worker_x[w, s]      ∈ {0,1}  worker w assigned to shift s
  supervisor_x[v, s]  ∈ {0,1}  supervisor v assigned to shift s
  pair[w, v, s]       ∈ {0,1}  AND of the two (only for HC11 forbidden + HC12 mentor)

Run:
  python staged_baseline.py
"""

import csv
import json
import os
import time
from collections import defaultdict
from pathlib import Path

from ortools.sat.python import cp_model

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RESULTS = ROOT / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
def _split(s):
    return [x.strip() for x in s.split(",") if x.strip()]


def load_workers():
    rows = []
    with open(DATA / "workers.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(
                {
                    "id": r["worker_id"],
                    "name": r["name"],
                    "skills": set(_split(r["skills"])),
                    "level": r["level"],
                    "max_h": int(r["max_hours_per_week"]),
                    "min_h": int(r["min_hours_per_week"]),
                    "unavail": set(_split(r["unavailable_days"])),
                    "langs": set(_split(r["languages"])),
                }
            )
    return rows


def load_supervisors():
    rows = []
    with open(DATA / "supervisors.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(
                {
                    "id": r["supervisor_id"],
                    "name": r["name"],
                    "role": r["role"],
                    "max_h": int(r["max_hours_per_week"]),
                    "min_h": int(r["min_hours_per_week"]),
                    "unavail": set(_split(r["unavailable_days"])),
                    "langs": set(_split(r["languages"])),
                    "specs": set(_split(r["specialties"])),
                }
            )
    return rows


def load_shifts():
    rows = []
    with open(DATA / "shifts.csv", encoding="utf-8") as f:
        for idx, r in enumerate(csv.DictReader(f)):
            rows.append(
                {
                    "idx": idx,
                    "week": int(r["week"]),
                    "day": r["day"],
                    "shift": r["shift_name"],
                    "start": r["start_time"],
                    "end": r["end_time"],
                    "w_req": int(r["worker_required"]),
                    "v_req": int(r["supervisor_required"]),
                    "skills": set(_split(r["required_skills"])),
                    "bilingual": r["bilingual_required"].strip().lower() == "yes",
                    "hours": 8,  # A1: all shifts are 8h
                }
            )
    return rows


def load_pairs():
    forbidden, mentor, preferred = [], [], []
    with open(DATA / "pair_constraints.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t = r["constraint_type"]
            tup = (r["entity1"], r["entity2"])
            if t == "forbidden":
                forbidden.append(tup)
            elif t == "mentorship":
                mentor.append(tup)
            elif t == "preferred":
                preferred.append(tup)
    return forbidden, mentor, preferred


WORKERS = load_workers()
SUPERVISORS = load_supervisors()
SHIFTS = load_shifts()
FORBIDDEN, MENTOR, PREFERRED = load_pairs()

W_IDX = {w["id"]: i for i, w in enumerate(WORKERS)}
V_IDX = {v["id"]: i for i, v in enumerate(SUPERVISORS)}

DAYS_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def shift_global_day(s):
    """Return absolute day index 0..13 across the 2 weeks."""
    return (s["week"] - 1) * 7 + DAYS_ORDER.index(s["day"])


# ---------------------------------------------------------------------------
# Build model up to a given phase
# ---------------------------------------------------------------------------
def build_model(max_phase: int):
    m = cp_model.CpModel()

    nW, nV, nS = len(WORKERS), len(SUPERVISORS), len(SHIFTS)
    wx = {(w, s): m.NewBoolVar(f"wx_{w}_{s}") for w in range(nW) for s in range(nS)}
    vx = {(v, s): m.NewBoolVar(f"vx_{v}_{s}") for v in range(nV) for s in range(nS)}

    constraint_count = 0

    # ---- Phase 1: HC1 worker demand ----
    if max_phase >= 1:
        for s in SHIFTS:
            m.Add(sum(wx[w, s["idx"]] for w in range(nW)) == s["w_req"])
            constraint_count += 1

    # ---- Phase 2: HC2 supervisor demand ----
    if max_phase >= 2:
        for s in SHIFTS:
            m.Add(sum(vx[v, s["idx"]] for v in range(nV)) == s["v_req"])
            constraint_count += 1

    # ---- Phase 3: HC3, HC4 max hours per week ----
    if max_phase >= 3:
        for w_i, w in enumerate(WORKERS):
            for wk in (1, 2):
                ss = [s["idx"] for s in SHIFTS if s["week"] == wk]
                m.Add(sum(wx[w_i, si] * 8 for si in ss) <= w["max_h"])
                constraint_count += 1
        for v_i, v in enumerate(SUPERVISORS):
            for wk in (1, 2):
                ss = [s["idx"] for s in SHIFTS if s["week"] == wk]
                m.Add(sum(vx[v_i, si] * 8 for si in ss) <= v["max_h"])
                constraint_count += 1

    # ---- Phase 4: HC5, HC6 unavailable days ----
    if max_phase >= 4:
        for w_i, w in enumerate(WORKERS):
            for s in SHIFTS:
                if s["day"] in w["unavail"]:
                    m.Add(wx[w_i, s["idx"]] == 0)
                    constraint_count += 1
        for v_i, v in enumerate(SUPERVISORS):
            for s in SHIFTS:
                if s["day"] in v["unavail"]:
                    m.Add(vx[v_i, s["idx"]] == 0)
                    constraint_count += 1

    # ---- Phase 5: HC7 skills, HC8 bilingual ----
    if max_phase >= 5:
        for w_i, w in enumerate(WORKERS):
            for s in SHIFTS:
                if s["skills"] and not s["skills"].issubset(w["skills"]):
                    m.Add(wx[w_i, s["idx"]] == 0)
                    constraint_count += 1
        # HC8 bilingual: en required for both worker and supervisor (A6)
        for s in SHIFTS:
            if not s["bilingual"]:
                continue
            for w_i, w in enumerate(WORKERS):
                if "en" not in w["langs"]:
                    m.Add(wx[w_i, s["idx"]] == 0)
                    constraint_count += 1
            for v_i, v in enumerate(SUPERVISORS):
                if "en" not in v["langs"]:
                    m.Add(vx[v_i, s["idx"]] == 0)
                    constraint_count += 1

    # ---- Phase 6: HC9 (worker 11h rest), HC10 (supervisor 12h rest) ----
    if max_phase >= 6:
        # Index shifts by (global_day, name)
        by_day = defaultdict(dict)
        for s in SHIFTS:
            by_day[shift_global_day(s)][s["shift"]] = s["idx"]

        for d in range(13):
            night = by_day[d].get("night")
            if night is None:
                continue
            next_day = by_day.get(d + 1, {})
            next_morning = next_day.get("morning")
            next_afternoon = next_day.get("afternoon")
            # HC9 worker: night -> next morning forbidden
            if next_morning is not None:
                for w_i in range(nW):
                    m.Add(wx[w_i, night] + wx[w_i, next_morning] <= 1)
                    constraint_count += 1
            # HC10 supervisor: night -> next morning + next afternoon forbidden
            for next_s in (next_morning, next_afternoon):
                if next_s is None:
                    continue
                for v_i in range(nV):
                    m.Add(vx[v_i, night] + vx[v_i, next_s] <= 1)
                    constraint_count += 1

    # ---- Phase 7: HC11 forbidden pair, HC12 mentor pair ----
    if max_phase >= 7:
        # HC11: forbidden pair w,v cannot both be 1 on same shift
        for (a, b) in FORBIDDEN:
            w_i = W_IDX.get(a)
            v_i = V_IDX.get(b)
            if w_i is None or v_i is None:
                continue
            for s in SHIFTS:
                m.Add(wx[w_i, s["idx"]] + vx[v_i, s["idx"]] <= 1)
                constraint_count += 1
        # HC12: mentor pair must coexist on the same shift at least 2 times
        for (a, b) in MENTOR:
            w_i = W_IDX.get(a)
            v_i = V_IDX.get(b)
            if w_i is None or v_i is None:
                continue
            pair_vars = []
            for s in SHIFTS:
                p = m.NewBoolVar(f"pair_{a}_{b}_{s['idx']}")
                m.AddBoolAnd([wx[w_i, s["idx"]], vx[v_i, s["idx"]]]).OnlyEnforceIf(p)
                m.AddBoolOr([wx[w_i, s["idx"]].Not(), vx[v_i, s["idx"]].Not()]).OnlyEnforceIf(p.Not())
                pair_vars.append(p)
            m.Add(sum(pair_vars) >= 2)
            constraint_count += 1

    return m, wx, vx, constraint_count


# ---------------------------------------------------------------------------
# Solve a single phase
# ---------------------------------------------------------------------------
PHASE_INFO = {
    0: ("Phase 0", "(none) variables only"),
    1: ("Phase 1", "+HC1 worker demand"),
    2: ("Phase 2", "+HC2 supervisor demand"),
    3: ("Phase 3", "+HC3,HC4 max hours"),
    4: ("Phase 4", "+HC5,HC6 unavailable days"),
    5: ("Phase 5", "+HC7,HC8 skills/bilingual"),
    6: ("Phase 6", "+HC9,HC10 rest"),
    7: ("Phase 7", "+HC11,HC12 pair constraints"),
}


def solve_phase(phase: int, time_limit: float = 30.0):
    t0 = time.time()
    model, wx, vx, n_added = build_model(phase)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = 4

    status = solver.Solve(model)
    elapsed = time.time() - t0

    name, desc = PHASE_INFO[phase]
    feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    result = {
        "phase": phase,
        "name": name,
        "description": desc,
        "added_hard_constraints": n_added,
        "status": solver.StatusName(status),
        "feasible": feasible,
        "objective": solver.ObjectiveValue() if feasible and model.HasObjective() else None,
        "time_sec": round(elapsed, 3),
        "num_branches": solver.NumBranches(),
        "num_conflicts": solver.NumConflicts(),
    }

    if feasible:
        worker_total = sum(
            solver.Value(wx[w, s])
            for w in range(len(WORKERS))
            for s in range(len(SHIFTS))
        )
        sup_total = sum(
            solver.Value(vx[v, s])
            for v in range(len(SUPERVISORS))
            for s in range(len(SHIFTS))
        )
        result["worker_assignments"] = int(worker_total)
        result["supervisor_assignments"] = int(sup_total)

    return result


def main():
    print("=" * 70)
    print("STAGED BASELINE — worker_supervisor v1")
    print("=" * 70)
    print(f"Workers: {len(WORKERS)}  Supervisors: {len(SUPERVISORS)}  Shifts: {len(SHIFTS)}")
    print(f"Binary vars: {len(WORKERS)*len(SHIFTS) + len(SUPERVISORS)*len(SHIFTS)}")
    print("-" * 70)

    all_results = []
    first_infeasible = None

    for phase in range(0, 8):
        r = solve_phase(phase)
        all_results.append(r)
        flag = "OK   " if r["feasible"] else "INFEA"
        print(
            f"[{flag}] {r['name']:8s} {r['description']:35s} "
            f"+{r['added_hard_constraints']:4d} cons  "
            f"{r['time_sec']:6.2f}s  {r['status']}"
        )
        if not r["feasible"] and first_infeasible is None:
            first_infeasible = phase

    print("-" * 70)
    if first_infeasible is None:
        print("All 7 phases FEASIBLE")
    else:
        print(f"First infeasible: Phase {first_infeasible} ({PHASE_INFO[first_infeasible][1]})")

    summary = {
        "n_workers": len(WORKERS),
        "n_supervisors": len(SUPERVISORS),
        "n_shifts": len(SHIFTS),
        "binary_vars": len(WORKERS) * len(SHIFTS) + len(SUPERVISORS) * len(SHIFTS),
        "first_infeasible_phase": first_infeasible,
        "phases": all_results,
    }

    out = RESULTS / "staged_baseline_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
