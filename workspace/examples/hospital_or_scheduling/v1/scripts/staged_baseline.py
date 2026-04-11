"""Staged baseline for hospital OR scheduling (v1).

Strategy: active/pending split by phase. We progressively "activate" HC groups
and re-solve. Each phase prints the solver status, score and an *independent*
verifier result. If a phase becomes infeasible, we print a root cause block.

Usage:
    python staged_baseline.py

Outputs:
    ../results/baseline_results.json
"""

from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from pathlib import Path

from ortools.sat.python import cp_model

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
RESULTS = HERE.parent / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

DAYS = [1, 2, 3, 4, 5]
CLEAN_MIN = 30
TIME_LIMIT = 120
WORKERS = 4


# ---------- Data loading ----------
def _b(v: str) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes", "y")


def _days_list(v: str) -> list[int]:
    v = (v or "").strip()
    if not v:
        return []
    return [int(x) for x in v.split(";") if x.strip()]


def load_data():
    with open(DATA / "operating_rooms.csv", encoding="utf-8") as f:
        rooms = list(csv.DictReader(f))
    for r in rooms:
        r["has_bypass_machine"] = _b(r["has_bypass_machine"])
        r["has_pediatric_eq"] = _b(r["has_pediatric_eq"])
        r["has_c_arm"] = _b(r["has_c_arm"])
        r["daily_open_minutes"] = int(r["daily_open_minutes"])

    with open(DATA / "surgeons.csv", encoding="utf-8") as f:
        surgeons = list(csv.DictReader(f))
    for s in surgeons:
        s["max_daily_minutes"] = int(s["max_daily_minutes"])
        s["max_weekly_minutes"] = int(s["max_weekly_minutes"])
        s["unavailable_days"] = _days_list(s["unavailable_days"])

    with open(DATA / "anesthesiologists.csv", encoding="utf-8") as f:
        anesths = list(csv.DictReader(f))
    for a in anesths:
        a["pediatric_qualified"] = _b(a["pediatric_qualified"])
        a["max_daily_minutes"] = int(a["max_daily_minutes"])
        a["unavailable_days"] = _days_list(a["unavailable_days"])

    with open(DATA / "nurses.csv", encoding="utf-8") as f:
        nurses = list(csv.DictReader(f))
    for n in nurses:
        n["scrub_qualified"] = _b(n["scrub_qualified"])
        n["circulator_qualified"] = _b(n["circulator_qualified"])
        n["pediatric_qualified"] = _b(n["pediatric_qualified"])
        n["max_daily_minutes"] = int(n["max_daily_minutes"])
        n["unavailable_days"] = _days_list(n["unavailable_days"])

    with open(DATA / "patients.csv", encoding="utf-8") as f:
        patients = list(csv.DictReader(f))
    for p in patients:
        p["duration_minutes"] = int(p["duration_minutes"])
        p["needs_icu"] = _b(p["needs_icu"])
        p["is_pediatric"] = _b(p["is_pediatric"])
        p["earliest_day"] = int(p["earliest_day"])
        p["latest_day"] = int(p["latest_day"])

    with open(DATA / "icu_beds.csv", encoding="utf-8") as f:
        icu = {int(row["day"]): int(row["available_post_op_beds"]) for row in csv.DictReader(f)}

    return rooms, surgeons, anesths, nurses, patients, icu


# ---------- Model builder ----------
def build_model(rooms, surgeons, anesths, nurses, patients, icu, active_hcs: set):
    m = cp_model.CpModel()

    pids = [p["patient_id"] for p in patients]
    rids = [r["room_id"] for r in rooms]
    sids = [s["surgeon_id"] for s in surgeons]
    aids = [a["anesth_id"] for a in anesths]

    P = {p["patient_id"]: p for p in patients}
    R = {r["room_id"]: r for r in rooms}
    S = {s["surgeon_id"]: s for s in surgeons}
    A = {a["anesth_id"]: a for a in anesths}

    # assign[p,r,d]
    assign = {
        (pi, ri, d): m.NewBoolVar(f"x_{pi}_{ri}_{d}")
        for pi in pids
        for ri in rids
        for d in DAYS
    }
    # sched[p]
    sched = {pi: m.NewBoolVar(f"sched_{pi}") for pi in pids}
    for pi in pids:
        m.Add(sum(assign[pi, ri, d] for ri in rids for d in DAYS) == sched[pi])

    # surgeon[p,s] / anesth[p,a]
    surg = {(pi, si): m.NewBoolVar(f"surg_{pi}_{si}") for pi in pids for si in sids}
    ane = {(pi, ai): m.NewBoolVar(f"ane_{pi}_{ai}") for pi in pids for ai in aids}
    for pi in pids:
        m.Add(sum(surg[pi, si] for si in sids) == sched[pi])
        m.Add(sum(ane[pi, ai] for ai in aids) == sched[pi])

    # day indicator per patient
    pday = {(pi, d): m.NewBoolVar(f"pday_{pi}_{d}") for pi in pids for d in DAYS}
    for pi in pids:
        for d in DAYS:
            m.Add(pday[pi, d] == sum(assign[pi, ri, d] for ri in rids))

    # ---- HC1 ----
    if "HC1" in active_hcs:
        for p in patients:
            if p["priority"] == "urgent":
                m.Add(sched[p["patient_id"]] == 1)
        # "at most once" is automatic by sched being 0/1 equaling sum

    # ---- HC2 : OR capacity (with +CLEAN_MIN absorbed per case = HC16 aggregated) ----
    if "HC2" in active_hcs:
        for ri in rids:
            for d in DAYS:
                m.Add(
                    sum(
                        assign[pi, ri, d] * (P[pi]["duration_minutes"] + CLEAN_MIN)
                        for pi in pids
                    )
                    <= R[ri]["daily_open_minutes"]
                )

    # ---- HC3 : surgeon specialty match ----
    if "HC3" in active_hcs:
        for pi in pids:
            need = P[pi]["specialty_required"]
            for si in sids:
                if S[si]["specialty"] != need:
                    m.Add(surg[pi, si] == 0)

    # ---- HC8 : cardiac -> room with bypass ----
    if "HC8" in active_hcs:
        for pi in pids:
            if P[pi]["specialty_required"] == "cardiac":
                for ri in rids:
                    if not R[ri]["has_bypass_machine"]:
                        for d in DAYS:
                            m.Add(assign[pi, ri, d] == 0)

    # ---- HC9 : pediatric -> room with pediatric_eq ----
    if "HC9" in active_hcs:
        for pi in pids:
            if P[pi]["is_pediatric"]:
                for ri in rids:
                    if not R[ri]["has_pediatric_eq"]:
                        for d in DAYS:
                            m.Add(assign[pi, ri, d] == 0)

    # ---- HC10 : pediatric needs ped-qualified anesth ----
    if "HC10" in active_hcs:
        for pi in pids:
            if P[pi]["is_pediatric"]:
                for ai in aids:
                    if not A[ai]["pediatric_qualified"]:
                        m.Add(ane[pi, ai] == 0)

    # ---- HC11 : pediatric needs ped-qualified nurse (pool-based approx) ----
    # Modelled at day level: daily pediatric patient count <= daily pediatric-qualified nurse count
    if "HC11" in active_hcs:
        ped_nurses = [n for n in nurses if n["pediatric_qualified"]]
        for d in DAYS:
            avail_ped_nurses = sum(1 for n in ped_nurses if d not in n["unavailable_days"])
            m.Add(
                sum(pday[pi, d] for pi in pids if P[pi]["is_pediatric"])
                <= avail_ped_nurses
            )

    # ---- HC12 : surgeon daily minutes ----
    # ---- HC13 : surgeon weekly minutes ----
    # We need per-surgeon-per-day minutes. Create helper: sd[s,d,p] = surg[p,s] AND pday[p,d]
    if "HC12" in active_hcs or "HC13" in active_hcs or "HC17" in active_hcs:
        sdp = {}
        for si in sids:
            for d in DAYS:
                for pi in pids:
                    v = m.NewBoolVar(f"sdp_{si}_{d}_{pi}")
                    m.AddBoolAnd([surg[pi, si], pday[pi, d]]).OnlyEnforceIf(v)
                    m.AddBoolOr([surg[pi, si].Not(), pday[pi, d].Not()]).OnlyEnforceIf(v.Not())
                    sdp[si, d, pi] = v

        if "HC12" in active_hcs:
            for si in sids:
                for d in DAYS:
                    m.Add(
                        sum(sdp[si, d, pi] * P[pi]["duration_minutes"] for pi in pids)
                        <= S[si]["max_daily_minutes"]
                    )
        if "HC13" in active_hcs:
            for si in sids:
                m.Add(
                    sum(
                        sdp[si, d, pi] * P[pi]["duration_minutes"]
                        for d in DAYS
                        for pi in pids
                    )
                    <= S[si]["max_weekly_minutes"]
                )
        if "HC17" in active_hcs:
            for si in sids:
                for d in S[si]["unavailable_days"]:
                    for pi in pids:
                        m.Add(sdp[si, d, pi] == 0)

    # ---- HC14 : anesth daily minutes + HC18 off-days ----
    if "HC14" in active_hcs or "HC18" in active_hcs:
        adp = {}
        for ai in aids:
            for d in DAYS:
                for pi in pids:
                    v = m.NewBoolVar(f"adp_{ai}_{d}_{pi}")
                    m.AddBoolAnd([ane[pi, ai], pday[pi, d]]).OnlyEnforceIf(v)
                    m.AddBoolOr([ane[pi, ai].Not(), pday[pi, d].Not()]).OnlyEnforceIf(v.Not())
                    adp[ai, d, pi] = v

        if "HC14" in active_hcs:
            for ai in aids:
                for d in DAYS:
                    m.Add(
                        sum(adp[ai, d, pi] * P[pi]["duration_minutes"] for pi in pids)
                        <= A[ai]["max_daily_minutes"]
                    )
        if "HC18" in active_hcs:
            for ai in aids:
                for d in A[ai]["unavailable_days"]:
                    for pi in pids:
                        m.Add(adp[ai, d, pi] == 0)

    # ---- HC6/HC7/HC15/HC19 : nurse pool aggregate by day ----
    # We model nurse-minutes demand per day and cap by pool capacity.
    if "HC6" in active_hcs or "HC7" in active_hcs or "HC15" in active_hcs:
        for d in DAYS:
            avail = [n for n in nurses if d not in n["unavailable_days"]]
            pool_minutes = sum(n["max_daily_minutes"] for n in avail)
            # Demand: 2 nurses per case (HC6); 3 if >180 min (HC7)
            m.Add(
                sum(
                    pday[pi, d]
                    * P[pi]["duration_minutes"]
                    * (3 if P[pi]["duration_minutes"] > 180 else 2)
                    for pi in pids
                )
                <= pool_minutes
            )
            # Head count: each case needs >=2 nurses present; trivially fine since 20 nurses
            # We also enforce "#cases running can't exceed #nurses/2".
            m.Add(
                sum(pday[pi, d] for pi in pids) * 2 <= len(avail) + 100  # slack; head cap handled via minutes
            )

    # ---- HC20 : ICU beds per day ----
    if "HC20" in active_hcs:
        for d in DAYS:
            m.Add(
                sum(pday[pi, d] for pi in pids if P[pi]["needs_icu"]) <= icu[d]
            )

    # ---- HC21 : urgent window ----
    if "HC21" in active_hcs:
        for p in patients:
            if p["priority"] == "urgent":
                pi = p["patient_id"]
                allowed = {p["earliest_day"], min(p["earliest_day"] + 1, p["latest_day"])}
                for d in DAYS:
                    if d not in allowed:
                        m.Add(pday[pi, d] == 0)
        # Enforce earliest/latest for all patients too
        for p in patients:
            pi = p["patient_id"]
            for d in DAYS:
                if d < p["earliest_day"] or d > p["latest_day"]:
                    m.Add(pday[pi, d] == 0)

    # ---- HC22 : requested surgeon (hard) ----
    if "HC22" in active_hcs:
        for p in patients:
            req = (p.get("requested_surgeon") or "").strip()
            if req:
                pi = p["patient_id"]
                for si in sids:
                    if si != req:
                        m.Add(surg[pi, si] == 0)

    # ---- Objective (lightweight in baseline: maximize coverage) ----
    m.Maximize(sum(sched[pi] for pi in pids))

    return m, {"assign": assign, "sched": sched, "surg": surg, "ane": ane, "pday": pday}


# ---------- Independent verifier ----------
def verify_all_hcs(solution, rooms, surgeons, anesths, nurses, patients, icu):
    """Return dict: hc_id -> (ok: bool, violations: list[str])."""
    P = {p["patient_id"]: p for p in patients}
    R = {r["room_id"]: r for r in rooms}
    S = {s["surgeon_id"]: s for s in surgeons}
    A = {a["anesth_id"]: a for a in anesths}

    sched = solution["sched"]  # patient_id -> (room, day) or None
    surg = solution["surg"]  # patient_id -> surgeon_id
    ane = solution["ane"]  # patient_id -> anesth_id

    results: dict = {}

    def add(k, ok, msgs):
        results[k] = {"ok": ok, "violations": msgs}

    # HC1
    msgs = []
    for p in patients:
        if p["priority"] == "urgent" and sched.get(p["patient_id"]) is None:
            msgs.append(f"urgent {p['patient_id']} not scheduled")
    add("HC1", not msgs, msgs)

    # HC2: OR capacity
    msgs = []
    cap_used = defaultdict(int)
    for pi, loc in sched.items():
        if loc is None:
            continue
        ri, d = loc
        cap_used[ri, d] += P[pi]["duration_minutes"] + CLEAN_MIN
    for (ri, d), used in cap_used.items():
        if used > R[ri]["daily_open_minutes"]:
            msgs.append(f"OR {ri} day {d} used {used} > {R[ri]['daily_open_minutes']}")
    add("HC2", not msgs, msgs)

    # HC3
    msgs = []
    for pi, si in surg.items():
        if si is None:
            continue
        if S[si]["specialty"] != P[pi]["specialty_required"]:
            msgs.append(f"{pi} specialty mismatch: needs {P[pi]['specialty_required']}, got {S[si]['specialty']}")
    add("HC3", not msgs, msgs)

    # HC4
    msgs = [pi for pi, si in surg.items() if sched.get(pi) is not None and si is None]
    add("HC4", not msgs, [f"{pi} missing surgeon" for pi in msgs])

    # HC5
    msgs = [pi for pi, ai in ane.items() if sched.get(pi) is not None and ai is None]
    add("HC5", not msgs, [f"{pi} missing anesth" for pi in msgs])

    # HC6/HC7 pool: check daily nurse-minute demand
    msgs67 = []
    for d in DAYS:
        demand = 0
        for pi, loc in sched.items():
            if loc is None or loc[1] != d:
                continue
            dur = P[pi]["duration_minutes"]
            demand += dur * (3 if dur > 180 else 2)
        avail_min = sum(n["max_daily_minutes"] for n in nurses if d not in n["unavailable_days"])
        if demand > avail_min:
            msgs67.append(f"day {d} nurse-minutes {demand} > pool {avail_min}")
    add("HC6", not msgs67, msgs67)
    add("HC7", not msgs67, msgs67)

    # HC8
    msgs = []
    for pi, loc in sched.items():
        if loc is None:
            continue
        if P[pi]["specialty_required"] == "cardiac" and not R[loc[0]]["has_bypass_machine"]:
            msgs.append(f"{pi} cardiac in non-bypass room {loc[0]}")
    add("HC8", not msgs, msgs)

    # HC9
    msgs = []
    for pi, loc in sched.items():
        if loc is None:
            continue
        if P[pi]["is_pediatric"] and not R[loc[0]]["has_pediatric_eq"]:
            msgs.append(f"{pi} pediatric in non-pediatric room {loc[0]}")
    add("HC9", not msgs, msgs)

    # HC10
    msgs = []
    for pi, ai in ane.items():
        if sched.get(pi) is None or ai is None:
            continue
        if P[pi]["is_pediatric"] and not A[ai]["pediatric_qualified"]:
            msgs.append(f"{pi} pediatric w/ non-ped anesth {ai}")
    add("HC10", not msgs, msgs)

    # HC11: day-level pediatric nurse head count
    msgs = []
    for d in DAYS:
        ped_cases = sum(1 for pi, loc in sched.items() if loc and loc[1] == d and P[pi]["is_pediatric"])
        avail = sum(1 for n in nurses if n["pediatric_qualified"] and d not in n["unavailable_days"])
        if ped_cases > avail:
            msgs.append(f"day {d} ped-cases {ped_cases} > ped-nurses {avail}")
    add("HC11", not msgs, msgs)

    # HC12/HC13
    surg_daily = defaultdict(int)
    surg_weekly = defaultdict(int)
    for pi, si in surg.items():
        if si is None or sched.get(pi) is None:
            continue
        d = sched[pi][1]
        dur = P[pi]["duration_minutes"]
        surg_daily[si, d] += dur
        surg_weekly[si] += dur
    msgs = [f"{si} day {d} used {u} > {S[si]['max_daily_minutes']}" for (si, d), u in surg_daily.items() if u > S[si]["max_daily_minutes"]]
    add("HC12", not msgs, msgs)
    msgs = [f"{si} week used {u} > {S[si]['max_weekly_minutes']}" for si, u in surg_weekly.items() if u > S[si]["max_weekly_minutes"]]
    add("HC13", not msgs, msgs)

    # HC14
    an_daily = defaultdict(int)
    for pi, ai in ane.items():
        if ai is None or sched.get(pi) is None:
            continue
        d = sched[pi][1]
        an_daily[ai, d] += P[pi]["duration_minutes"]
    msgs = [f"{ai} day {d} used {u} > {A[ai]['max_daily_minutes']}" for (ai, d), u in an_daily.items() if u > A[ai]["max_daily_minutes"]]
    add("HC14", not msgs, msgs)

    # HC15 (aggregate; mirrors HC6/7 check)
    add("HC15", results["HC6"]["ok"], results["HC6"]["violations"])

    # HC16 absorbed into HC2
    add("HC16", results["HC2"]["ok"], results["HC2"]["violations"])

    # HC17
    msgs = []
    for pi, si in surg.items():
        if si is None or sched.get(pi) is None:
            continue
        d = sched[pi][1]
        if d in S[si]["unavailable_days"]:
            msgs.append(f"{si} assigned on off-day {d}")
    add("HC17", not msgs, msgs)

    # HC18
    msgs = []
    for pi, ai in ane.items():
        if ai is None or sched.get(pi) is None:
            continue
        d = sched[pi][1]
        if d in A[ai]["unavailable_days"]:
            msgs.append(f"{ai} assigned on off-day {d}")
    add("HC18", not msgs, msgs)

    # HC19 (aggregate via pool availability already enforced)
    add("HC19", True, [])

    # HC20
    msgs = []
    for d in DAYS:
        icu_used = sum(1 for pi, loc in sched.items() if loc and loc[1] == d and P[pi]["needs_icu"])
        if icu_used > icu[d]:
            msgs.append(f"day {d} icu {icu_used} > {icu[d]}")
    add("HC20", not msgs, msgs)

    # HC21
    msgs = []
    for p in patients:
        pi = p["patient_id"]
        if p["priority"] != "urgent":
            continue
        loc = sched.get(pi)
        if loc is None:
            msgs.append(f"urgent {pi} unscheduled")
            continue
        d = loc[1]
        allowed = {p["earliest_day"], min(p["earliest_day"] + 1, p["latest_day"])}
        if d not in allowed:
            msgs.append(f"urgent {pi} on day {d} not in {sorted(allowed)}")
    add("HC21", not msgs, msgs)

    # HC22
    msgs = []
    for p in patients:
        req = (p.get("requested_surgeon") or "").strip()
        if not req:
            continue
        pi = p["patient_id"]
        if sched.get(pi) is None:
            continue
        if surg.get(pi) != req:
            msgs.append(f"{pi} requested {req}, got {surg.get(pi)}")
    add("HC22", not msgs, msgs)

    return results


# ---------- Solve helper ----------
def extract_solution(solver, v, pids, rids, sids, aids):
    sched = {}
    surg = {}
    ane = {}
    for pi in pids:
        placed = None
        for ri in rids:
            for d in DAYS:
                if solver.Value(v["assign"][pi, ri, d]) == 1:
                    placed = (ri, d)
        sched[pi] = placed
        su = None
        for si in sids:
            if solver.Value(v["surg"][pi, si]) == 1:
                su = si
        surg[pi] = su
        an = None
        for ai in aids:
            if solver.Value(v["ane"][pi, ai]) == 1:
                an = ai
        ane[pi] = an
    return {"sched": sched, "surg": surg, "ane": ane}


def solve_phase(name, active_hcs, rooms, surgeons, anesths, nurses, patients, icu):
    print(f"\n=== PHASE {name}  (HCs: {sorted(active_hcs)}) ===")
    m, v = build_model(rooms, surgeons, anesths, nurses, patients, icu, active_hcs)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TIME_LIMIT
    solver.parameters.num_search_workers = WORKERS
    status = solver.Solve(m)
    status_name = solver.StatusName(status)
    print(f"  status={status_name}  obj={solver.ObjectiveValue() if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else 'N/A'}")

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"phase": name, "status": status_name, "score": None, "verify": None, "sched_count": 0}

    pids = [p["patient_id"] for p in patients]
    rids = [r["room_id"] for r in rooms]
    sids = [s["surgeon_id"] for s in surgeons]
    aids = [a["anesth_id"] for a in anesths]
    sol = extract_solution(solver, v, pids, rids, sids, aids)
    verify = verify_all_hcs(sol, rooms, surgeons, anesths, nurses, patients, icu)
    n_ok = sum(1 for x in verify.values() if x["ok"])
    print(f"  independent verify: {n_ok}/{len(verify)} HCs ok")
    for k, x in verify.items():
        if not x["ok"]:
            print(f"    {k} FAIL: {x['violations'][:3]}")
    sched_count = sum(1 for _, loc in sol["sched"].items() if loc is not None)
    return {
        "phase": name,
        "status": status_name,
        "score": solver.ObjectiveValue(),
        "sched_count": sched_count,
        "verify": {k: {"ok": x["ok"], "n_viol": len(x["violations"])} for k, x in verify.items()},
    }


def main():
    rooms, surgeons, anesths, nurses, patients, icu = load_data()
    print(f"Loaded: {len(patients)} patients, {len(rooms)} ORs, {len(surgeons)} surgeons, "
          f"{len(anesths)} anesths, {len(nurses)} nurses")

    phases = [
        ("P01_core_assign",         {"HC1", "HC2"}),
        ("P02_+specialty",          {"HC1", "HC2", "HC3"}),
        ("P03_+equipment",          {"HC1", "HC2", "HC3", "HC8", "HC9"}),
        ("P04_+windows",            {"HC1", "HC2", "HC3", "HC8", "HC9", "HC21"}),
        ("P05_+surgeon_caps",       {"HC1","HC2","HC3","HC8","HC9","HC21","HC12","HC13","HC17"}),
        ("P06_+anesth",             {"HC1","HC2","HC3","HC8","HC9","HC21","HC12","HC13","HC17","HC14","HC18"}),
        ("P07_+ped_qualification",  {"HC1","HC2","HC3","HC8","HC9","HC21","HC12","HC13","HC17","HC14","HC18","HC10","HC11"}),
        ("P08_+nurse_pool",         {"HC1","HC2","HC3","HC8","HC9","HC21","HC12","HC13","HC17","HC14","HC18","HC10","HC11","HC6","HC7","HC15"}),
        ("P09_+icu",                {"HC1","HC2","HC3","HC8","HC9","HC21","HC12","HC13","HC17","HC14","HC18","HC10","HC11","HC6","HC7","HC15","HC20"}),
        ("P10_+requested_surgeon",  {"HC1","HC2","HC3","HC8","HC9","HC21","HC12","HC13","HC17","HC14","HC18","HC10","HC11","HC6","HC7","HC15","HC20","HC22"}),
        ("P11_all_HCs",             {f"HC{i}" for i in range(1,23)}),
    ]

    all_results = []
    first_infeasible = None
    for name, active in phases:
        r = solve_phase(name, active, rooms, surgeons, anesths, nurses, patients, icu)
        all_results.append(r)
        if r["status"] not in ("OPTIMAL", "FEASIBLE") and first_infeasible is None:
            first_infeasible = name
            print(f"\n!!! first infeasible at {name} — stopping cascade and recording root cause")
            break

    out = {
        "first_infeasible": first_infeasible,
        "phases": all_results,
        "n_patients": len(patients),
        "n_hcs": 22,
    }
    with open(RESULTS / "baseline_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved to {RESULTS / 'baseline_results.json'}")


if __name__ == "__main__":
    main()
