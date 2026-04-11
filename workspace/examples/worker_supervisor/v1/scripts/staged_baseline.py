"""
Staged baseline — worker_supervisor v1

assess で complexity=complex のため段階的解法を適用。
12 HCs を 7 Phase で順次追加、各 Phase で active / pending HC を分離して検証。

Phase 0: vars only
Phase 1: +HC1 worker demand
Phase 2: +HC2 supervisor demand
Phase 3: +HC3, HC4 max hours
Phase 4: +HC5, HC6 unavailable days
Phase 5: +HC7, HC8 skills + bilingual
Phase 6: +HC9, HC10 rest
Phase 7: +HC11, HC12 pair (FULL)
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
RESULTS.mkdir(parents=True, exist_ok=True)

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
                "id": r["worker_id"], "name": r["name"],
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
                "id": r["supervisor_id"], "name": r["name"], "role": r["role"],
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
                "idx": idx, "week": int(r["week"]), "day": r["day"],
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
def build_model(active_hcs):
    """Build CP-SAT model enforcing only the given set of HCs."""
    m = cp_model.CpModel()
    nW, nV, nS = len(WORKERS), len(SUPERVISORS), len(SHIFTS)
    W_IDX = {w["id"]: i for i, w in enumerate(WORKERS)}
    V_IDX = {v["id"]: i for i, v in enumerate(SUPERVISORS)}
    day_of = {s["idx"]: shift_global_day(s) for s in SHIFTS}

    wx = {(wi, s["idx"]): m.NewBoolVar(f"wx_{wi}_{s['idx']}")
          for wi in range(nW) for s in SHIFTS}
    vx = {(vi, s["idx"]): m.NewBoolVar(f"vx_{vi}_{s['idx']}")
          for vi in range(nV) for s in SHIFTS}

    if "HC1" in active_hcs:
        for s in SHIFTS:
            m.Add(sum(wx[wi, s["idx"]] for wi in range(nW)) == s["w_req"])

    if "HC2" in active_hcs:
        for s in SHIFTS:
            m.Add(sum(vx[vi, s["idx"]] for vi in range(nV)) == s["v_req"])

    if "HC3" in active_hcs:
        for wi, w in enumerate(WORKERS):
            for wk in (1, 2):
                m.Add(sum(wx[wi, s["idx"]] * 8 for s in SHIFTS if s["week"] == wk)
                      <= w["max_h"])

    if "HC4" in active_hcs:
        for vi, v in enumerate(SUPERVISORS):
            for wk in (1, 2):
                m.Add(sum(vx[vi, s["idx"]] * 8 for s in SHIFTS if s["week"] == wk)
                      <= v["max_h"])

    if "HC5" in active_hcs:
        for wi, w in enumerate(WORKERS):
            for s in SHIFTS:
                if s["day"] in w["unavail"]:
                    m.Add(wx[wi, s["idx"]] == 0)

    if "HC6" in active_hcs:
        for vi, v in enumerate(SUPERVISORS):
            for s in SHIFTS:
                if s["day"] in v["unavail"]:
                    m.Add(vx[vi, s["idx"]] == 0)

    if "HC7" in active_hcs:
        for wi, w in enumerate(WORKERS):
            for s in SHIFTS:
                if s["skills"] and not s["skills"].issubset(w["skills"]):
                    m.Add(wx[wi, s["idx"]] == 0)

    if "HC8" in active_hcs:
        for s in SHIFTS:
            if not s["bilingual"]:
                continue
            for wi, w in enumerate(WORKERS):
                if "en" not in w["langs"]:
                    m.Add(wx[wi, s["idx"]] == 0)
            for vi, v in enumerate(SUPERVISORS):
                if "en" not in v["langs"]:
                    m.Add(vx[vi, s["idx"]] == 0)

    if "HC9" in active_hcs:
        for wi in range(nW):
            for s in SHIFTS:
                if s["name"] != "night":
                    continue
                d = day_of[s["idx"]]
                for s2 in SHIFTS:
                    if s2["name"] == "morning" and day_of[s2["idx"]] == d + 1:
                        m.Add(wx[wi, s["idx"]] + wx[wi, s2["idx"]] <= 1)

    if "HC10" in active_hcs:
        for vi in range(nV):
            for s in SHIFTS:
                if s["name"] != "night":
                    continue
                d = day_of[s["idx"]]
                for s2 in SHIFTS:
                    if s2["name"] == "morning" and day_of[s2["idx"]] == d + 1:
                        m.Add(vx[vi, s["idx"]] + vx[vi, s2["idx"]] <= 1)

    if "HC11" in active_hcs:
        for wid, vid in FORB:
            if wid not in W_IDX or vid not in V_IDX:
                continue
            wi, vi = W_IDX[wid], V_IDX[vid]
            for s in SHIFTS:
                m.Add(wx[wi, s["idx"]] + vx[vi, s["idx"]] <= 1)

    if "HC12" in active_hcs:
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


# ---------- Independent HC verifier (all 12 HCs from scratch) ----------
def verify_all_hcs(solver, wx, vx):
    nW, nV = len(WORKERS), len(SUPERVISORS)
    W_IDX = {w["id"]: i for i, w in enumerate(WORKERS)}
    V_IDX = {v["id"]: i for i, v in enumerate(SUPERVISORS)}
    day_of = {s["idx"]: shift_global_day(s) for s in SHIFTS}

    w_val = {(wi, s["idx"]): solver.Value(wx[wi, s["idx"]])
             for wi in range(nW) for s in SHIFTS}
    v_val = {(vi, s["idx"]): solver.Value(vx[vi, s["idx"]])
             for vi in range(nV) for s in SHIFTS}

    viol = {f"HC{i}": 0 for i in range(1, 13)}

    # HC1
    for s in SHIFTS:
        if sum(w_val[wi, s["idx"]] for wi in range(nW)) != s["w_req"]:
            viol["HC1"] += 1
    # HC2
    for s in SHIFTS:
        if sum(v_val[vi, s["idx"]] for vi in range(nV)) != s["v_req"]:
            viol["HC2"] += 1
    # HC3
    for wi, w in enumerate(WORKERS):
        for wk in (1, 2):
            h = sum(8 for s in SHIFTS if s["week"] == wk and w_val[wi, s["idx"]])
            if h > w["max_h"]:
                viol["HC3"] += 1
    # HC4
    for vi, v in enumerate(SUPERVISORS):
        for wk in (1, 2):
            h = sum(8 for s in SHIFTS if s["week"] == wk and v_val[vi, s["idx"]])
            if h > v["max_h"]:
                viol["HC4"] += 1
    # HC5
    for wi, w in enumerate(WORKERS):
        for s in SHIFTS:
            if s["day"] in w["unavail"] and w_val[wi, s["idx"]]:
                viol["HC5"] += 1
    # HC6
    for vi, v in enumerate(SUPERVISORS):
        for s in SHIFTS:
            if s["day"] in v["unavail"] and v_val[vi, s["idx"]]:
                viol["HC6"] += 1
    # HC7
    for wi, w in enumerate(WORKERS):
        for s in SHIFTS:
            if w_val[wi, s["idx"]] and s["skills"] and not s["skills"].issubset(w["skills"]):
                viol["HC7"] += 1
    # HC8
    for s in SHIFTS:
        if not s["bilingual"]:
            continue
        for wi, w in enumerate(WORKERS):
            if w_val[wi, s["idx"]] and "en" not in w["langs"]:
                viol["HC8"] += 1
        for vi, v in enumerate(SUPERVISORS):
            if v_val[vi, s["idx"]] and "en" not in v["langs"]:
                viol["HC8"] += 1
    # HC9
    for wi in range(nW):
        for s in SHIFTS:
            if s["name"] != "night" or not w_val[wi, s["idx"]]:
                continue
            d = day_of[s["idx"]]
            for s2 in SHIFTS:
                if s2["name"] == "morning" and day_of[s2["idx"]] == d + 1 and w_val[wi, s2["idx"]]:
                    viol["HC9"] += 1
    # HC10
    for vi in range(nV):
        for s in SHIFTS:
            if s["name"] != "night" or not v_val[vi, s["idx"]]:
                continue
            d = day_of[s["idx"]]
            for s2 in SHIFTS:
                if s2["name"] == "morning" and day_of[s2["idx"]] == d + 1 and v_val[vi, s2["idx"]]:
                    viol["HC10"] += 1
    # HC11
    for wid, vid in FORB:
        if wid not in W_IDX or vid not in V_IDX:
            continue
        wi, vi = W_IDX[wid], V_IDX[vid]
        for s in SHIFTS:
            if w_val[wi, s["idx"]] and v_val[vi, s["idx"]]:
                viol["HC11"] += 1
    # HC12
    for wid, vid in MENT:
        if wid not in W_IDX or vid not in V_IDX:
            continue
        wi, vi = W_IDX[wid], V_IDX[vid]
        shared = sum(1 for s in SHIFTS
                     if w_val[wi, s["idx"]] and v_val[vi, s["idx"]])
        if shared < 2:
            viol["HC12"] += 1

    return viol


# ---------- Phase definition ----------
# (phase_num, name, active HCs set, newly added at this phase)
PHASES = [
    (0, "Phase0_vars_only",  set(),                                            set()),
    (1, "Phase1_HC1",        {"HC1"},                                           {"HC1"}),
    (2, "Phase2_HC2",        {"HC1", "HC2"},                                    {"HC2"}),
    (3, "Phase3_HC3_HC4",    {"HC1", "HC2", "HC3", "HC4"},                      {"HC3", "HC4"}),
    (4, "Phase4_HC5_HC6",    {"HC1", "HC2", "HC3", "HC4", "HC5", "HC6"},        {"HC5", "HC6"}),
    (5, "Phase5_HC7_HC8",    {"HC1", "HC2", "HC3", "HC4", "HC5", "HC6",
                              "HC7", "HC8"},                                    {"HC7", "HC8"}),
    (6, "Phase6_HC9_HC10",   {"HC1", "HC2", "HC3", "HC4", "HC5", "HC6",
                              "HC7", "HC8", "HC9", "HC10"},                     {"HC9", "HC10"}),
    (7, "Phase7_FULL",       {f"HC{i}" for i in range(1, 13)},                  {"HC11", "HC12"}),
]


def solve_phase(phase_num, name, active_hcs, newly_added):
    t0 = time.time()
    model, wx, vx = build_model(active_hcs)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TIME_LIMIT
    solver.parameters.num_search_workers = NUM_WORKERS
    status = solver.Solve(model)
    elapsed = time.time() - t0
    feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    r = {
        "phase_num": phase_num,
        "name": name,
        "active_hcs": sorted(active_hcs),
        "newly_added": sorted(newly_added),
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

        all_viol = verify_all_hcs(solver, wx, vx)
        active_viol = {hc: v for hc, v in all_viol.items()
                       if hc in active_hcs and v > 0}
        pending_viol = {hc: v for hc, v in all_viol.items()
                        if hc not in active_hcs and v > 0}

        r["active_hc_violations"] = active_viol
        r["active_hc_ok"] = (sum(active_viol.values()) == 0)
        r["pending_hc_violations"] = pending_viol
        r["pending_hc_total"] = sum(pending_viol.values())
    else:
        r["w_assigned"] = None
        r["v_assigned"] = None
        r["active_hc_violations"] = None
        r["active_hc_ok"] = False
        r["pending_hc_violations"] = None
        r["pending_hc_total"] = None
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
    prev_pending = None
    for phase_num, name, active_hcs, newly_added in PHASES:
        added_str = ", ".join(sorted(newly_added)) if newly_added else "(none)"
        print(f"[{name}] adds {added_str}")
        r = solve_phase(phase_num, name, active_hcs, newly_added)
        results.append(r)

        if r["solver_feasible"]:
            active_ok = "✓ active OK" if r["active_hc_ok"] \
                else f"✗ active VIOL {sum(r['active_hc_violations'].values())}"
            pending_str = f"pending={r['pending_hc_total']}"
            delta_str = ""
            if prev_pending is not None:
                delta = r["pending_hc_total"] - prev_pending
                delta_str = f" (Δ={delta:+d})" if delta != 0 else ""

            print(f"    -> {r['solver_status']} | w={r['w_assigned']}, v={r['v_assigned']} | "
                  f"{active_ok} | {pending_str}{delta_str} ({r['time_sec']}s)")

            if r["active_hc_violations"]:
                print(f"       ★ ACTIVE violations (should be 0!): {r['active_hc_violations']}")
            if r["pending_hc_violations"]:
                print(f"       pending: {r['pending_hc_violations']}")

            prev_pending = r["pending_hc_total"]
        else:
            print(f"    -> {r['solver_status']} ({r['time_sec']}s)")
            if first_infeasible is None:
                first_infeasible = name
                print(f"       !!! FIRST INFEASIBLE — wall at {name} !!!")
                print(f"       Newly added HCs causing infeasibility: {sorted(newly_added)}")

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
        print("  → Newly added HCs at this phase caused the wall")


if __name__ == "__main__":
    main()
