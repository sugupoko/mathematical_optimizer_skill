"""
Improve scenarios for worker_supervisor v1.

Phase 5 of the staged baseline showed infeasibility caused by:
  - 4 bilingual morning shifts (Tue/Thu × 2 weeks) demanding 5 reception workers
  - But only 4 workers have BOTH "en" AND "reception" (W002,W004,W008,W010)
  → 5 needed vs pool of 4 → structurally infeasible (HC1+HC7+HC8 interaction)

This script runs four feasibility-recovery scenarios on top of the full
12-HC model, then layers the SC objective on the feasible ones.

  Scenario A: Hire 1 new bilingual reception worker (W021)
  Scenario B: Relax HC1 worker_required from 5 to 4 for the 4 bilingual shifts
  Scenario C: Soften HC1 (penalize shortage but allow it)
  Scenario D: Soften HC8 (penalize non-bilingual on bilingual shifts)

Reference: spec.md (R1-R6, HC1-HC12, SC1-SC8)
"""

import csv
import json
import time
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

from ortools.sat.python import cp_model

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RESULTS = ROOT / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

DAYS_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TIME_LIMIT = 60.0
NUM_WORKERS = 4


# ---------------------------------------------------------------------------
# Data loaders
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
                    "hours": 8,
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


def shift_global_day(s):
    return (s["week"] - 1) * 7 + DAYS_ORDER.index(s["day"])


# ---------------------------------------------------------------------------
# Default SC weights (balanced)
# ---------------------------------------------------------------------------
DEFAULT_WEIGHTS = {
    "sc1": 5,    # consecutive day cap
    "sc2": 1,    # worker hours stddev (proxy: max-min)
    "sc3": 1,    # supervisor hours stddev (proxy: max-min)
    "sc4": 3,    # worker night > 4
    "sc5": 3,    # supervisor night > 3
    "sc6": 2,    # min hours shortfall
    "sc7": 4,    # daily senior coverage
    "sc8": -1,   # preferred pair (negative = reward)
    "shortage_HC1": 1000,  # huge penalty (used by Scenario C)
    "shortage_HC8": 1000,  # huge penalty (used by Scenario D)
}


# ---------------------------------------------------------------------------
# Build full model with optional softening
# ---------------------------------------------------------------------------
def build_full_model(
    workers,
    supervisors,
    shifts,
    forbidden,
    mentor,
    preferred,
    soften_hc1=False,
    soften_hc8=False,
    relax_hc1_bilingual=False,
    weights=None,
):
    """Build the complete model (HC1-HC12) with optional relaxations.

    Returns (model, vars_dict, objective_terms_dict).
    """
    weights = weights or DEFAULT_WEIGHTS
    m = cp_model.CpModel()

    nW, nV, nS = len(workers), len(supervisors), len(shifts)
    W_IDX = {w["id"]: i for i, w in enumerate(workers)}
    V_IDX = {v["id"]: i for i, v in enumerate(supervisors)}

    wx = {(w, s): m.NewBoolVar(f"wx_{w}_{s}") for w in range(nW) for s in range(nS)}
    vx = {(v, s): m.NewBoolVar(f"vx_{v}_{s}") for v in range(nV) for s in range(nS)}

    # Slack variables for soft scenarios
    w_short = {}  # HC1 slack
    v_short = {}  # HC2 slack (always 0 unless soften_hc1)
    nonbi_w = {}  # HC8 slack (worker non-bilingual on bilingual shift assignments)
    nonbi_v = {}

    # ---- HC1 worker demand ----
    for s in shifts:
        si = s["idx"]
        target = s["w_req"]
        if relax_hc1_bilingual and s["bilingual"] and "reception" in s["skills"]:
            target = 4  # relax bilingual+reception shifts
        if soften_hc1:
            slack = m.NewIntVar(0, target, f"w_short_{si}")
            w_short[si] = slack
            m.Add(sum(wx[w, si] for w in range(nW)) + slack >= target)
            m.Add(sum(wx[w, si] for w in range(nW)) <= target)
        else:
            m.Add(sum(wx[w, si] for w in range(nW)) == target)

    # ---- HC2 supervisor demand ----
    for s in shifts:
        si = s["idx"]
        m.Add(sum(vx[v, si] for v in range(nV)) == s["v_req"])

    # ---- HC3 worker max hours/week ----
    for w_i, w in enumerate(workers):
        for wk in (1, 2):
            ss = [s["idx"] for s in shifts if s["week"] == wk]
            m.Add(sum(wx[w_i, si] * 8 for si in ss) <= w["max_h"])

    # ---- HC4 supervisor max hours/week ----
    for v_i, v in enumerate(supervisors):
        for wk in (1, 2):
            ss = [s["idx"] for s in shifts if s["week"] == wk]
            m.Add(sum(vx[v_i, si] * 8 for si in ss) <= v["max_h"])

    # ---- HC5/HC6 unavailable days ----
    for w_i, w in enumerate(workers):
        for s in shifts:
            if s["day"] in w["unavail"]:
                m.Add(wx[w_i, s["idx"]] == 0)
    for v_i, v in enumerate(supervisors):
        for s in shifts:
            if s["day"] in v["unavail"]:
                m.Add(vx[v_i, s["idx"]] == 0)

    # ---- HC7 skills (workers only) ----
    for w_i, w in enumerate(workers):
        for s in shifts:
            if s["skills"] and not s["skills"].issubset(w["skills"]):
                m.Add(wx[w_i, s["idx"]] == 0)

    # ---- HC8 bilingual: en for both worker and supervisor (A6) ----
    if not soften_hc8:
        for s in shifts:
            if not s["bilingual"]:
                continue
            for w_i, w in enumerate(workers):
                if "en" not in w["langs"]:
                    m.Add(wx[w_i, s["idx"]] == 0)
            for v_i, v in enumerate(supervisors):
                if "en" not in v["langs"]:
                    m.Add(vx[v_i, s["idx"]] == 0)
    else:
        # Soft HC8: count non-bilingual assignments on bilingual shifts as penalty
        for s in shifts:
            if not s["bilingual"]:
                continue
            for w_i, w in enumerate(workers):
                if "en" not in w["langs"]:
                    nonbi_w[(w_i, s["idx"])] = wx[w_i, s["idx"]]
            for v_i, v in enumerate(supervisors):
                if "en" not in v["langs"]:
                    nonbi_v[(v_i, s["idx"])] = vx[v_i, s["idx"]]

    # ---- HC9 worker rest (night → next morning forbidden) ----
    by_day = defaultdict(dict)
    for s in shifts:
        by_day[shift_global_day(s)][s["shift"]] = s["idx"]

    for d in range(13):
        night = by_day[d].get("night")
        if night is None:
            continue
        next_day = by_day.get(d + 1, {})
        nm = next_day.get("morning")
        na = next_day.get("afternoon")
        if nm is not None:
            for w_i in range(nW):
                m.Add(wx[w_i, night] + wx[w_i, nm] <= 1)
        # ---- HC10 supervisor rest (12h: night → next morning AND afternoon forbidden) ----
        for next_s in (nm, na):
            if next_s is None:
                continue
            for v_i in range(nV):
                m.Add(vx[v_i, night] + vx[v_i, next_s] <= 1)

    # ---- HC11 forbidden pair ----
    for (a, b) in forbidden:
        w_i = W_IDX.get(a)
        v_i = V_IDX.get(b)
        if w_i is None or v_i is None:
            continue
        for s in shifts:
            m.Add(wx[w_i, s["idx"]] + vx[v_i, s["idx"]] <= 1)

    # ---- HC12 mentor pair: ≥ 2 co-shifts in 2 weeks ----
    mentor_pair_vars = {}
    for (a, b) in mentor:
        w_i = W_IDX.get(a)
        v_i = V_IDX.get(b)
        if w_i is None or v_i is None:
            continue
        pvars = []
        for s in shifts:
            si = s["idx"]
            p = m.NewBoolVar(f"pair_{a}_{b}_{si}")
            m.AddBoolAnd([wx[w_i, si], vx[v_i, si]]).OnlyEnforceIf(p)
            m.AddBoolOr([wx[w_i, si].Not(), vx[v_i, si].Not()]).OnlyEnforceIf(p.Not())
            pvars.append(p)
        m.Add(sum(pvars) >= 2)
        mentor_pair_vars[(a, b)] = pvars

    # =====================================================================
    # Soft constraint expressions (SC1-SC8)
    # =====================================================================
    obj_terms = []

    # ----- SC1: consecutive working days ≤ 5 (penalize 6+ via slack) -----
    # Implementation: for any 6 consecutive days window, sum of "worked" indicators ≤ 5 + slack
    daily_worked = {}
    for w_i in range(nW):
        for d in range(14):
            day_shifts = [shifts[i]["idx"] for i in range(nS) if shift_global_day(shifts[i]) == d]
            v = m.NewBoolVar(f"daily_worked_{w_i}_{d}")
            # v=1 iff any wx in day_shifts is 1
            m.AddMaxEquality(v, [wx[w_i, si] for si in day_shifts])
            daily_worked[(w_i, d)] = v
    sc1_slacks = []
    for w_i in range(nW):
        for start in range(0, 14 - 5):
            window = [daily_worked[(w_i, d)] for d in range(start, start + 6)]
            slack = m.NewIntVar(0, 6, f"sc1_slack_{w_i}_{start}")
            m.Add(sum(window) - 5 <= slack)
            sc1_slacks.append(slack)
    obj_terms.append((weights["sc1"], sum(sc1_slacks)))

    # ----- SC2 worker hours fairness: minimize (max-min) of hours -----
    w_hours = []
    for w_i in range(nW):
        h = sum(wx[w_i, s["idx"]] * 8 for s in shifts)
        w_hours.append(h)
    w_max = m.NewIntVar(0, 200, "w_hours_max")
    w_min = m.NewIntVar(0, 200, "w_hours_min")
    for h in w_hours:
        m.Add(h <= w_max)
        m.Add(h >= w_min)
    sc2_term = m.NewIntVar(0, 200, "sc2_spread")
    m.Add(sc2_term == w_max - w_min)
    obj_terms.append((weights["sc2"], sc2_term))

    # ----- SC3 supervisor hours fairness -----
    v_hours = []
    for v_i in range(nV):
        h = sum(vx[v_i, s["idx"]] * 8 for s in shifts)
        v_hours.append(h)
    v_max = m.NewIntVar(0, 200, "v_hours_max")
    v_min = m.NewIntVar(0, 200, "v_hours_min")
    for h in v_hours:
        m.Add(h <= v_max)
        m.Add(h >= v_min)
    sc3_term = m.NewIntVar(0, 200, "sc3_spread")
    m.Add(sc3_term == v_max - v_min)
    obj_terms.append((weights["sc3"], sc3_term))

    # ----- SC4 worker night ≤ 4 -----
    sc4_slacks = []
    for w_i in range(nW):
        nights = [wx[w_i, s["idx"]] for s in shifts if s["shift"] == "night"]
        slack = m.NewIntVar(0, len(nights), f"sc4_w_{w_i}")
        m.Add(sum(nights) - 4 <= slack)
        sc4_slacks.append(slack)
    obj_terms.append((weights["sc4"], sum(sc4_slacks)))

    # ----- SC5 supervisor night ≤ 3 -----
    sc5_slacks = []
    for v_i in range(nV):
        nights = [vx[v_i, s["idx"]] for s in shifts if s["shift"] == "night"]
        slack = m.NewIntVar(0, len(nights), f"sc5_v_{v_i}")
        m.Add(sum(nights) - 3 <= slack)
        sc5_slacks.append(slack)
    obj_terms.append((weights["sc5"], sum(sc5_slacks)))

    # ----- SC6 minimum hours (per worker, summed over 2 weeks = 2 × min_h) -----
    sc6_slacks = []
    for w_i, w in enumerate(workers):
        target = w["min_h"] * 2
        h = sum(wx[w_i, s["idx"]] * 8 for s in shifts)
        slack = m.NewIntVar(0, target, f"sc6_w_{w_i}")
        m.Add(h + slack >= target)
        sc6_slacks.append(slack)
    for v_i, v in enumerate(supervisors):
        target = v["min_h"] * 2
        h = sum(vx[v_i, s["idx"]] * 8 for s in shifts)
        slack = m.NewIntVar(0, target, f"sc6_v_{v_i}")
        m.Add(h + slack >= target)
        sc6_slacks.append(slack)
    obj_terms.append((weights["sc6"], sum(sc6_slacks)))

    # ----- SC7 daily senior coverage ≥ 1 -----
    senior_idx = [w_i for w_i, w in enumerate(workers) if w["level"] == "senior"]
    sc7_slacks = []
    for d in range(14):
        day_shifts = [s["idx"] for s in shifts if shift_global_day(s) == d]
        senior_assignments = sum(wx[w_i, si] for w_i in senior_idx for si in day_shifts)
        slack = m.NewIntVar(0, 1, f"sc7_d_{d}")
        m.Add(senior_assignments + slack >= 1)
        sc7_slacks.append(slack)
    obj_terms.append((weights["sc7"], sum(sc7_slacks)))

    # ----- SC8 preferred pair reward -----
    pref_pair_vars = []
    for (a, b) in preferred:
        w_i = W_IDX.get(a)
        v_i = V_IDX.get(b)
        if w_i is None or v_i is None:
            continue
        for s in shifts:
            si = s["idx"]
            p = m.NewBoolVar(f"pref_{a}_{b}_{si}")
            m.AddBoolAnd([wx[w_i, si], vx[v_i, si]]).OnlyEnforceIf(p)
            m.AddBoolOr([wx[w_i, si].Not(), vx[v_i, si].Not()]).OnlyEnforceIf(p.Not())
            pref_pair_vars.append(p)
    obj_terms.append((weights["sc8"], sum(pref_pair_vars) if pref_pair_vars else 0))

    # ----- Soft slacks for HC1/HC8 -----
    if soften_hc1 and w_short:
        obj_terms.append((weights["shortage_HC1"], sum(w_short.values())))
    if soften_hc8:
        all_nonbi = list(nonbi_w.values()) + list(nonbi_v.values())
        if all_nonbi:
            obj_terms.append((weights["shortage_HC8"], sum(all_nonbi)))

    # Build objective
    total_obj = sum(coef * term for coef, term in obj_terms if not isinstance(term, int) or term != 0)
    m.Minimize(total_obj)

    return m, {
        "wx": wx,
        "vx": vx,
        "w_short": w_short,
        "nonbi_w": nonbi_w,
        "nonbi_v": nonbi_v,
        "sc1_slacks": sc1_slacks,
        "sc2_term": sc2_term,
        "sc3_term": sc3_term,
        "sc4_slacks": sc4_slacks,
        "sc5_slacks": sc5_slacks,
        "sc6_slacks": sc6_slacks,
        "sc7_slacks": sc7_slacks,
        "pref_pair_vars": pref_pair_vars,
        "w_hours": w_hours,
        "v_hours": v_hours,
    }


# ---------------------------------------------------------------------------
# Independent HC verifier — re-checks all 12 HCs from the raw assignment
# ---------------------------------------------------------------------------
def verify_hard_constraints(solver, vars_d, workers, supervisors, shifts,
                             forbidden, mentor, preferred):
    """Re-check HC1..HC12 independently of the solver.

    This does NOT rely on the model's internal satisfiability. It reads the
    assignment variables and checks each constraint from scratch, so soft
    relaxations (HC1/HC8) are exposed as violations.
    """
    nW, nV = len(workers), len(supervisors)
    W_IDX = {w["id"]: i for i, w in enumerate(workers)}
    V_IDX = {v["id"]: i for i, v in enumerate(supervisors)}
    wx = vars_d["wx"]
    vx = vars_d["vx"]

    # Read assignment
    w_assign = {(wi, s["idx"]): solver.Value(wx[wi, s["idx"]])
                for wi in range(nW) for s in shifts}
    v_assign = {(vi, s["idx"]): solver.Value(vx[vi, s["idx"]])
                for vi in range(nV) for s in shifts}

    violations = {f"HC{i}": [] for i in range(1, 13)}

    # HC1: worker demand met
    for s in shifts:
        si = s["idx"]
        cnt = sum(w_assign[wi, si] for wi in range(nW))
        if cnt < s["w_req"]:
            violations["HC1"].append(
                f"shift {si} ({s['day']}-{s['shift']} w{s['week']}): {cnt}/{s['w_req']}"
            )

    # HC2: supervisor demand met
    for s in shifts:
        si = s["idx"]
        cnt = sum(v_assign[vi, si] for vi in range(nV))
        if cnt < s["v_req"]:
            violations["HC2"].append(
                f"shift {si} ({s['day']}-{s['shift']} w{s['week']}): {cnt}/{s['v_req']}"
            )

    # HC3: worker max hours per week
    for wi, w in enumerate(workers):
        for wk in (1, 2):
            h = sum(w_assign[wi, s["idx"]] * 8 for s in shifts if s["week"] == wk)
            if h > w["max_h"]:
                violations["HC3"].append(f"{w['id']} week{wk}: {h}h > {w['max_h']}h")

    # HC4: supervisor max hours per week
    for vi, v in enumerate(supervisors):
        for wk in (1, 2):
            h = sum(v_assign[vi, s["idx"]] * 8 for s in shifts if s["week"] == wk)
            if h > v["max_h"]:
                violations["HC4"].append(f"{v['id']} week{wk}: {h}h > {v['max_h']}h")

    # HC5: worker unavailable days
    for wi, w in enumerate(workers):
        for s in shifts:
            if s["day"] in w["unavail"] and w_assign[wi, s["idx"]]:
                violations["HC5"].append(f"{w['id']} assigned on unavailable {s['day']}")

    # HC6: supervisor unavailable days
    for vi, v in enumerate(supervisors):
        for s in shifts:
            if s["day"] in v["unavail"] and v_assign[vi, s["idx"]]:
                violations["HC6"].append(f"{v['id']} assigned on unavailable {s['day']}")

    # HC7: worker skill match
    for wi, w in enumerate(workers):
        for s in shifts:
            if w_assign[wi, s["idx"]] and s["skills"] and not s["skills"].issubset(w["skills"]):
                violations["HC7"].append(
                    f"{w['id']} on {s['day']}-{s['shift']} missing skills {s['skills'] - w['skills']}"
                )

    # HC8: bilingual shifts require en-capable worker and supervisor
    for s in shifts:
        if not s["bilingual"]:
            continue
        for wi, w in enumerate(workers):
            if w_assign[wi, s["idx"]] and "en" not in w["langs"]:
                violations["HC8"].append(
                    f"{w['id']} (no en) on bilingual shift {s['day']}-{s['shift']} w{s['week']}"
                )
        for vi, v in enumerate(supervisors):
            if v_assign[vi, s["idx"]] and "en" not in v["langs"]:
                violations["HC8"].append(
                    f"{v['id']} (no en) on bilingual shift {s['day']}-{s['shift']} w{s['week']}"
                )

    # HC9: worker rest — no morning after night (previous day)
    # Build global day index for sequential checking
    day_idx = {}
    for s in shifts:
        day_idx[s["idx"]] = shift_global_day(s)
    # For each worker, check night on day D followed by morning on day D+1
    for wi in range(nW):
        night_days = set()
        morning_days = set()
        for s in shifts:
            if w_assign[wi, s["idx"]]:
                if s["shift"] == "night":
                    night_days.add(day_idx[s["idx"]])
                elif s["shift"] == "morning":
                    morning_days.add(day_idx[s["idx"]])
        for nd in night_days:
            if (nd + 1) in morning_days:
                violations["HC9"].append(f"{workers[wi]['id']}: night day{nd} -> morning day{nd+1}")

    # HC10: supervisor rest (same pattern, stricter 12h)
    for vi in range(nV):
        night_days = set()
        morning_days = set()
        for s in shifts:
            if v_assign[vi, s["idx"]]:
                if s["shift"] == "night":
                    night_days.add(day_idx[s["idx"]])
                elif s["shift"] == "morning":
                    morning_days.add(day_idx[s["idx"]])
        for nd in night_days:
            if (nd + 1) in morning_days:
                violations["HC10"].append(f"{supervisors[vi]['id']}: night day{nd} -> morning day{nd+1}")

    # HC11: forbidden pairs (worker-supervisor never on same shift)
    for w_id, v_id in forbidden:
        if w_id not in W_IDX or v_id not in V_IDX:
            continue
        wi, vi = W_IDX[w_id], V_IDX[v_id]
        for s in shifts:
            if w_assign[wi, s["idx"]] and v_assign[vi, s["idx"]]:
                violations["HC11"].append(
                    f"forbidden pair ({w_id},{v_id}) both on shift {s['idx']} ({s['day']}-{s['shift']})"
                )

    # HC12: mentorship pairs must share ≥2 shifts over 2 weeks
    for w_id, v_id in mentor:
        if w_id not in W_IDX or v_id not in V_IDX:
            continue
        wi, vi = W_IDX[w_id], V_IDX[v_id]
        shared = sum(1 for s in shifts
                     if w_assign[wi, s["idx"]] and v_assign[vi, s["idx"]])
        if shared < 2:
            violations["HC12"].append(f"mentorship ({w_id},{v_id}) shared only {shared}/2 shifts")

    totals = {hc: len(lst) for hc, lst in violations.items()}
    all_satisfied = all(n == 0 for n in totals.values())

    return {
        "all_satisfied": all_satisfied,
        "total_violations": sum(totals.values()),
        "by_constraint": totals,
        "details": {hc: lst[:5] for hc, lst in violations.items() if lst},  # first 5 of each
    }


# ---------------------------------------------------------------------------
# Score SC results 0-100
# ---------------------------------------------------------------------------
def evaluate_solution(solver, vars_d, workers, supervisors, shifts, status_feasible):
    if not status_feasible:
        return None

    nW = len(workers)
    nV = len(supervisors)

    # SC1 violations
    sc1 = sum(solver.Value(s) for s in vars_d["sc1_slacks"])
    # SC2/SC3 spread
    sc2 = solver.Value(vars_d["sc2_term"])
    sc3 = solver.Value(vars_d["sc3_term"])
    # SC4/SC5 night excess
    sc4 = sum(solver.Value(s) for s in vars_d["sc4_slacks"])
    sc5 = sum(solver.Value(s) for s in vars_d["sc5_slacks"])
    # SC6 hours shortfall
    sc6 = sum(solver.Value(s) for s in vars_d["sc6_slacks"])
    # SC7 senior coverage missing days
    sc7 = sum(solver.Value(s) for s in vars_d["sc7_slacks"])
    # SC8 preferred pairs achieved
    sc8 = sum(solver.Value(p) for p in vars_d["pref_pair_vars"])

    # 0-100 scores: simple piecewise (lower violations = higher score)
    def s_inv(v, max_bad):
        return max(0, 100 - int(100 * v / max_bad)) if max_bad > 0 else 100

    scores = {
        "SC1_consecutive_days": s_inv(sc1, 20),
        "SC2_worker_fairness": s_inv(sc2, 80),
        "SC3_supervisor_fairness": s_inv(sc3, 80),
        "SC4_worker_night": s_inv(sc4, 20),
        "SC5_supervisor_night": s_inv(sc5, 10),
        "SC6_min_hours": s_inv(sc6, 200),
        "SC7_senior_coverage": s_inv(sc7, 14),
        "SC8_preferred_pairs": min(100, int(100 * sc8 / max(1, len(vars_d["pref_pair_vars"]) * 0.3))),
    }
    scores["overall"] = round(sum(scores.values()) / len(scores), 1)

    raw = {
        "sc1_violations": sc1,
        "sc2_spread": sc2,
        "sc3_spread": sc3,
        "sc4_excess": sc4,
        "sc5_excess": sc5,
        "sc6_shortfall": sc6,
        "sc7_missing_days": sc7,
        "sc8_pairs_achieved": sc8,
    }
    return {"scores": scores, "raw": raw}


# ---------------------------------------------------------------------------
# Solve a scenario
# ---------------------------------------------------------------------------
def solve_scenario(name, workers, supervisors, shifts, forbidden, mentor, preferred,
                   soften_hc1=False, soften_hc8=False, relax_hc1_bilingual=False,
                   weights=None):
    t0 = time.time()
    model, vars_d = build_full_model(
        workers, supervisors, shifts, forbidden, mentor, preferred,
        soften_hc1=soften_hc1,
        soften_hc8=soften_hc8,
        relax_hc1_bilingual=relax_hc1_bilingual,
        weights=weights,
    )
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TIME_LIMIT
    solver.parameters.num_search_workers = NUM_WORKERS
    status = solver.Solve(model)
    elapsed = time.time() - t0
    feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    obj = solver.ObjectiveValue() if feasible else None

    extra = {}
    if soften_hc1 and feasible:
        extra["hc1_shortage_total"] = sum(solver.Value(s) for s in vars_d["w_short"].values())
        extra["hc1_shortage_per_shift"] = {
            int(si): int(solver.Value(s)) for si, s in vars_d["w_short"].items() if solver.Value(s) > 0
        }
    if soften_hc8 and feasible:
        extra["hc8_nonbilingual_worker_assignments"] = sum(
            solver.Value(v) for v in vars_d["nonbi_w"].values()
        )
        extra["hc8_nonbilingual_supervisor_assignments"] = sum(
            solver.Value(v) for v in vars_d["nonbi_v"].values()
        )

    eval_data = evaluate_solution(solver, vars_d, workers, supervisors, shifts, feasible)

    # Independent HC verification (does not trust the solver's 'feasible' flag)
    hc_verify = None
    if feasible:
        hc_verify = verify_hard_constraints(
            solver, vars_d, workers, supervisors, shifts, forbidden, mentor, preferred
        )

    return {
        "scenario": name,
        "solver_status": solver.StatusName(status),
        "solver_feasible": feasible,
        "hc_all_satisfied": hc_verify["all_satisfied"] if hc_verify else None,
        "hc_total_violations": hc_verify["total_violations"] if hc_verify else None,
        "hc_violations_by_constraint": hc_verify["by_constraint"] if hc_verify else None,
        "hc_violation_samples": hc_verify["details"] if hc_verify else None,
        "objective": obj,
        "time_sec": round(elapsed, 2),
        "evaluation": eval_data,
        **extra,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    workers = load_workers()
    supervisors = load_supervisors()
    shifts = load_shifts()
    forbidden, mentor, preferred = load_pairs()

    print("=" * 72)
    print("IMPROVE — worker_supervisor v1")
    print("=" * 72)
    print(f"Workers: {len(workers)}  Supervisors: {len(supervisors)}  Shifts: {len(shifts)}")
    print(f"time_limit per scenario = {TIME_LIMIT}s")
    print()

    results = {}

    def _print_result(label, r):
        status_str = r["solver_status"]
        hc_str = "HC ALL OK" if r["hc_all_satisfied"] else f"HC VIOLATED ({r['hc_total_violations']})"
        violated = {k: v for k, v in (r["hc_violations_by_constraint"] or {}).items() if v > 0}
        print(f"    -> {status_str} | {hc_str} | obj={r['objective']} ({r['time_sec']}s)")
        if violated:
            print(f"       violations: {violated}")

    # ---- Scenario A: hire 1 bilingual reception worker (W021) ----
    w021 = {
        "id": "W021",
        "name": "新規 採用",
        "skills": {"reception", "phone", "chat"},
        "level": "mid",
        "max_h": 40,
        "min_h": 24,
        "unavail": set(),
        "langs": {"ja", "en"},
    }
    workers_A = workers + [w021]
    print("[A] Hire W021 (en+reception+phone+chat, mid, 24-40h)...")
    results["A_hire_W021"] = solve_scenario(
        "A_hire_W021", workers_A, supervisors, shifts, forbidden, mentor, preferred,
    )
    _print_result("A", results["A_hire_W021"])

    # ---- Scenario B: relax HC1 (5→4) on 4 bilingual reception shifts ----
    print("[B] Relax HC1 5->4 on bilingual+reception shifts...")
    results["B_relax_HC1_bilingual"] = solve_scenario(
        "B_relax_HC1_bilingual", workers, supervisors, shifts, forbidden, mentor, preferred,
        relax_hc1_bilingual=True,
    )
    _print_result("B", results["B_relax_HC1_bilingual"])

    # ---- Scenario C: soft HC1 ----
    print("[C] Soft HC1 (allow shortage with penalty)...")
    results["C_soft_HC1"] = solve_scenario(
        "C_soft_HC1", workers, supervisors, shifts, forbidden, mentor, preferred,
        soften_hc1=True,
    )
    _print_result("C", results["C_soft_HC1"])

    # ---- Scenario D: soft HC8 ----
    print("[D] Soft HC8 (allow non-bilingual on bilingual shifts)...")
    results["D_soft_HC8"] = solve_scenario(
        "D_soft_HC8", workers, supervisors, shifts, forbidden, mentor, preferred,
        soften_hc8=True,
    )
    _print_result("D", results["D_soft_HC8"])

    out = RESULTS / "improve_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print()
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
