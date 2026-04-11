"""
Staged baseline — worker_supervisor v1

12 HCs incrementally added to localize which constraint group breaks feasibility.

Phase 0: variables only
Phase 1: +HC1 worker demand
Phase 2: +HC2 supervisor demand
Phase 3: +HC3, HC4 max hours
Phase 4: +HC5, HC6 unavailable days
Phase 5: +HC7, HC8 skills + bilingual
Phase 6: +HC9, HC10 rest constraints
Phase 7: +HC11, HC12 pair constraints (FULL)
"""

from __future__ import annotations

import csv
import json
import time
from collections import defaultdict
from pathlib import Path

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


# ---------- Loaders ----------
def _split(s): return [x.strip() for x in s.split(",") if x.strip()]


def load_workers():
    rows = []
    with open(DATA / "workers.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "id": r["worker_id"],
                "name": r["name"],
                "skills": set(_split(r["skills"])),
                "level": r["level"],
                "max_h": int(r["max_hours_per_week"]),
                "min_h": int(r["min_hours_per_week"]),
                "unavail": set(_split(r["unavailable_days"])),
                "langs": set(_split(r["languages"])),
            })
    return rows


def load_supervisors():
    rows = []
    with open(DATA / "supervisors.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "id": r["supervisor_id"],
                "name": r["name"],
                "role": r["role"],
                "max_h": int(r["max_hours_per_week"]),
                "min_h": int(r["min_hours_per_week"]),
                "unavail": set(_split(r["unavailable_days"])),
                "langs": set(_split(r["languages"])),
                "specs": set(_split(r["specialties"])),
            })
    return rows


def load_shifts():
    rows = []
    with open(DATA / "shifts.csv", encoding="utf-8") as f:
        for idx, r in enumerate(csv.DictReader(f)):
            rows.append({
                "idx": idx,
                "week": int(r["week"]),
                "day": r["day"],
                "name": r["shift_name"],
                "w_req": int(r["worker_required"]),
                "v_req": int(r["supervisor_required"]),
                "skills": set(_split(r["required_skills"])),
                "bilingual": r["bilingual_required"].strip().lower() == "yes",
                "hours": 8,
            })
    return rows


def load_pairs():
    forb, ment, pref = [], [], []
    with open(DATA / "pair_constraints.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t = r["constraint_type"]
            tup = (r["entity1"], r["entity2"])
            if t == "forbidden": forb.append(tup)
            elif t == "mentorship": ment.append(tup)
            elif t == "preferred": pref.append(tup)
    return forb, ment, pref


WORKERS = load_workers()
SUPERVISORS = load_supervisors()
SHIFTS = load_shifts()
FORB, MENT, PREF = load_pairs()


def shift_global_day(s):
    return (s["week"] - 1) * 7 + DAYS_ORDER.index(s["day"])


# ---------- Model builder ----------
def build_model(max_phase):
    m = cp_model.CpModel()
    nW, nV, nS = len(WORKERS), len(SUPERVISORS), len(SHIFTS)
    W_IDX = {w["id"]: i for i, w in enumerate(WORKERS)}
    V_IDX = {v["id"]: i for i, v in enumerate(SUPERVISORS)}

    wx = {(w, s): m.NewBoolVar(f"wx_{w}_{s}") for w in range(nW) for s in range(nS)}
    vx = {(v, s): m.NewBoolVar(f"vx_{v}_{s}") for v in range(nV) for s in range(nS)}

    day_of = {s["idx"]: shift_global_day(s) for s in SHIFTS}

    # Phase 1: HC1 worker demand
    if max_phase >= 1:
        for s in SHIFTS:
            m.Add(sum(wx[w, s["idx"]] for w in range(nW)) == s["w_req"])

    # Phase 2: HC2 supervisor demand
    if max_phase >= 2:
        for s in SHIFTS:
            m.Add(sum(vx[v, s["idx"]] for v in range(nV)) == s["v_req"])

    # Phase 3: HC3, HC4 max hours
    if max_phase >= 3:
        for wi, w in enumerate(WORKERS):
            for wk in (1, 2):
                m.Add(sum(wx[wi, s["idx"]] * 8 for s in SHIFTS if s["week"] == wk) <= w["max_h"])
        for vi, v in enumerate(SUPERVISORS):
            for wk in (1, 2):
                m.Add(sum(vx[vi, s["idx"]] * 8 for s in SHIFTS if s["week"] == wk) <= v["max_h"])

    # Phase 4: HC5, HC6 unavailable days
    if max_phase >= 4:
        for wi, w in enumerate(WORKERS):
            for s in SHIFTS:
                if s["day"] in w["unavail"]:
                    m.Add(wx[wi, s["idx"]] == 0)
        for vi, v in enumerate(SUPERVISORS):
            for s in SHIFTS:
                if s["day"] in v["unavail"]:
                    m.Add(vx[vi, s["idx"]] == 0)

    # Phase 5: HC7 (skill), HC8 (bilingual)
    if max_phase >= 5:
        for wi, w in enumerate(WORKERS):
            for s in SHIFTS:
                if s["skills"] and not s["skills"].issubset(w["skills"]):
                    m.Add(wx[wi, s["idx"]] == 0)
        # HC8: bilingual shift → all workers and supervisors must have 'en'
        for s in SHIFTS:
            if not s["bilingual"]:
                continue
            for wi, w in enumerate(WORKERS):
                if "en" not in w["langs"]:
                    m.Add(wx[wi, s["idx"]] == 0)
            for vi, v in enumerate(SUPERVISORS):
                if "en" not in v["langs"]:
                    m.Add(vx[vi, s["idx"]] == 0)

    # Phase 6: HC9 worker rest, HC10 supervisor rest
    # Next-day morning forbidden if nurse had night previous day
    if max_phase >= 6:
        # Group shifts by day for worker and supervisor
        for wi in range(nW):
            for s in SHIFTS:
                if s["name"] != "night":
                    continue
                d = day_of[s["idx"]]
                # Find morning shifts on d+1
                for s2 in SHIFTS:
                    if s2["name"] == "morning" and day_of[s2["idx"]] == d + 1:
                        m.Add(wx[wi, s["idx"]] + wx[wi, s2["idx"]] <= 1)
        for vi in range(nV):
            for s in SHIFTS:
                if s["name"] != "night":
                    continue
                d = day_of[s["idx"]]
                for s2 in SHIFTS:
                    if s2["name"] == "morning" and day_of[s2["idx"]] == d + 1:
                        m.Add(vx[vi, s["idx"]] + vx[vi, s2["idx"]] <= 1)

    # Phase 7: HC11 forbidden, HC12 mentorship
    if max_phase >= 7:
        # HC11: forbidden pairs not on same shift
        for wid, vid in FORB:
            if wid not in W_IDX or vid not in V_IDX:
                continue
            wi, vi = W_IDX[wid], V_IDX[vid]
            for s in SHIFTS:
                m.Add(wx[wi, s["idx"]] + vx[vi, s["idx"]] <= 1)

        # HC12: mentorship pairs share ≥ 2 shifts over 2 weeks
        # We need pair_and[w,v,s] = wx[w,s] AND vx[v,s]
        for wid, vid in MENT:
            if wid not in W_IDX or vid not in V_IDX:
                continue
            wi, vi = W_IDX[wid], V_IDX[vid]
            pair_vars = []
            for s in SHIFTS:
                p = m.NewBoolVar(f"pair_{wid}_{vid}_{s['idx']}")
                m.Add(p <= wx[wi, s["idx"]])
                m.Add(p <= vx[vi, s["idx"]])
                m.Add(p >= wx[wi, s["idx"]] + vx[vi, s["idx"]] - 1)
                pair_vars.append(p)
            m.Add(sum(pair_vars) >= 2)

    return m, wx, vx


# ---------- Independent HC verifier ----------
def verify_all_hcs(solver, wx, vx):
    nW, nV, nS = len(WORKERS), len(SUPERVISORS), len(SHIFTS)
    W_IDX = {w["id"]: i for i, w in enumerate(WORKERS)}
    V_IDX = {v["id"]: i for i, v in enumerate(SUPERVISORS)}
    day_of = {s["idx"]: shift_global_day(s) for s in SHIFTS}

    w_val = {(wi, s["idx"]): solver.Value(wx[wi, s["idx"]])
             for wi in range(nW) for s in SHIFTS}
    v_val = {(vi, s["idx"]): solver.Value(vx[vi, s["idx"]])
             for vi in range(nV) for s in SHIFTS}

    violations = {f"HC{i}": 0 for i in range(1, 13)}

    # HC1
    for s in SHIFTS:
        if sum(w_val[wi, s["idx"]] for wi in range(nW)) != s["w_req"]:
            violations["HC1"] += 1
    # HC2
    for s in SHIFTS:
        if sum(v_val[vi, s["idx"]] for vi in range(nV)) != s["v_req"]:
            violations["HC2"] += 1
    # HC3, HC4
    for wi, w in enumerate(WORKERS):
        for wk in (1, 2):
            h = sum(8 for s in SHIFTS if s["week"] == wk and w_val[wi, s["idx"]])
            if h > w["max_h"]:
                violations["HC3"] += 1
    for vi, v in enumerate(SUPERVISORS):
        for wk in (1, 2):
            h = sum(8 for s in SHIFTS if s["week"] == wk and v_val[vi, s["idx"]])
            if h > v["max_h"]:
                violations["HC4"] += 1
    # HC5, HC6
    for wi, w in enumerate(WORKERS):
        for s in SHIFTS:
            if s["day"] in w["unavail"] and w_val[wi, s["idx"]]:
                violations["HC5"] += 1
    for vi, v in enumerate(SUPERVISORS):
        for s in SHIFTS:
            if s["day"] in v["unavail"] and v_val[vi, s["idx"]]:
                violations["HC6"] += 1
    # HC7
    for wi, w in enumerate(WORKERS):
        for s in SHIFTS:
            if w_val[wi, s["idx"]] and s["skills"] and not s["skills"].issubset(w["skills"]):
                violations["HC7"] += 1
    # HC8
    for s in SHIFTS:
        if not s["bilingual"]:
            continue
        for wi, w in enumerate(WORKERS):
            if w_val[wi, s["idx"]] and "en" not in w["langs"]:
                violations["HC8"] += 1
        for vi, v in enumerate(SUPERVISORS):
            if v_val[vi, s["idx"]] and "en" not in v["langs"]:
                violations["HC8"] += 1
    # HC9, HC10
    for wi in range(nW):
        for s in SHIFTS:
            if s["name"] != "night" or not w_val[wi, s["idx"]]:
                continue
            d = day_of[s["idx"]]
            for s2 in SHIFTS:
                if s2["name"] == "morning" and day_of[s2["idx"]] == d + 1 and w_val[wi, s2["idx"]]:
                    violations["HC9"] += 1
    for vi in range(nV):
        for s in SHIFTS:
            if s["name"] != "night" or not v_val[vi, s["idx"]]:
                continue
            d = day_of[s["idx"]]
            for s2 in SHIFTS:
                if s2["name"] == "morning" and day_of[s2["idx"]] == d + 1 and v_val[vi, s2["idx"]]:
                    violations["HC10"] += 1
    # HC11
    for wid, vid in FORB:
        if wid not in W_IDX or vid not in V_IDX:
            continue
        wi, vi = W_IDX[wid], V_IDX[vid]
        for s in SHIFTS:
            if w_val[wi, s["idx"]] and v_val[vi, s["idx"]]:
                violations["HC11"] += 1
    # HC12
    for wid, vid in MENT:
        if wid not in W_IDX or vid not in V_IDX:
            continue
        wi, vi = W_IDX[wid], V_IDX[vid]
        shared = sum(1 for s in SHIFTS
                     if w_val[wi, s["idx"]] and v_val[vi, s["idx"]])
        if shared < 2:
            violations["HC12"] += 1

    return {
        "total": sum(violations.values()),
        "by_hc": violations,
        "all_ok": sum(violations.values()) == 0,
    }


# ---------- Phase runner ----------
PHASES = [
    (0, "Phase0_vars_only",      "(no constraints)"),
    (1, "Phase1_HC1",            "+HC1 worker demand"),
    (2, "Phase2_HC2",            "+HC2 supervisor demand"),
    (3, "Phase3_HC3_HC4",        "+HC3 HC4 max hours"),
    (4, "Phase4_HC5_HC6",        "+HC5 HC6 unavailable days"),
    (5, "Phase5_HC7_HC8",        "+HC7 HC8 skills + bilingual"),
    (6, "Phase6_HC9_HC10",       "+HC9 HC10 rest"),
    (7, "Phase7_FULL",           "+HC11 HC12 pair (FULL)"),
]


def solve_phase(max_phase, name, desc):
    t0 = time.time()
    model, wx, vx = build_model(max_phase)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TIME_LIMIT
    solver.parameters.num_search_workers = NUM_WORKERS
    status = solver.Solve(model)
    elapsed = time.time() - t0
    feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    r = {
        "phase_num": max_phase,
        "name": name,
        "description": desc,
        "solver_status": solver.StatusName(status),
        "solver_feasible": feasible,
        "time_sec": round(elapsed, 2),
    }

    if feasible:
        w_assigned = sum(solver.Value(wx[wi, s["idx"]])
                         for wi in range(len(WORKERS)) for s in SHIFTS)
        v_assigned = sum(solver.Value(vx[vi, s["idx"]])
                         for vi in range(len(SUPERVISORS)) for s in SHIFTS)
        r["w_assigned"] = w_assigned
        r["v_assigned"] = v_assigned
        verify = verify_all_hcs(solver, wx, vx)
        r["hc_verify"] = verify
    else:
        r["w_assigned"] = None
        r["v_assigned"] = None
        r["hc_verify"] = None
    return r


def main():
    print("=" * 72)
    print("STAGED BASELINE — worker_supervisor v1")
    print("=" * 72)
    print(f"Workers: {len(WORKERS)}  Supervisors: {len(SUPERVISORS)}  Shifts: {len(SHIFTS)}")
    print(f"Variables: {len(WORKERS)*len(SHIFTS) + len(SUPERVISORS)*len(SHIFTS)}")
    print(f"time_limit = {TIME_LIMIT}s, workers = {NUM_WORKERS}")
    print()

    results = []
    first_infeasible = None
    for max_p, name, desc in PHASES:
        print(f"[{name}] {desc}")
        r = solve_phase(max_p, name, desc)
        results.append(r)
        if r["solver_feasible"]:
            hc = r["hc_verify"]
            hc_str = "HC ALL OK" if hc["all_ok"] else f"HC VIOL {hc['total']}"
            print(f"    -> {r['solver_status']} | w={r['w_assigned']}, v={r['v_assigned']} | {hc_str} ({r['time_sec']}s)")
            if not hc["all_ok"]:
                viol = {k: v for k, v in hc["by_hc"].items() if v > 0}
                print(f"       violations (incl. not-yet-added HCs): {viol}")
        else:
            print(f"    -> {r['solver_status']} ({r['time_sec']}s)")
            if first_infeasible is None:
                first_infeasible = name
                print(f"       !!! FIRST INFEASIBLE !!!")

    out = RESULTS / "staged_baseline_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "first_infeasible_phase": first_infeasible,
            "phases": results,
        }, f, indent=2, ensure_ascii=False)

    print()
    print(f"Saved: {out}")
    if first_infeasible is None:
        print("RESULT: All phases feasible — problem is solvable with all HCs")
    else:
        print(f"RESULT: First infeasibility at {first_infeasible}")


if __name__ == "__main__":
    main()
