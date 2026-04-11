"""Staged baseline for COVID-19 Vaccine Allocation v1.

Integer CP-SAT model over 5 groups x 6 sites x 10 weeks x 3 vaccines x 2 doses.

Decision variables (integer >= 0):
    dose1[g, s, w, v]  number of 1st doses
    dose2[g, s, w, v]  number of 2nd doses  (0 for VJ)

Phases progressively activate HCs so we can see which binds.

Run:
    python staged_baseline.py

Outputs:
    ../results/baseline_results.json
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from ortools.sat.python import cp_model

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
RESULTS = HERE.parent / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

WEEKS = list(range(1, 11))          # 1..10
TIME_LIMIT = 20
WORKERS = 8


# ---------- loader ----------
def load_data():
    with open(DATA / "priority_groups.csv", encoding="utf-8") as f:
        groups = list(csv.DictReader(f))
    for g in groups:
        g["population"] = int(g["population"])
        g["priority_rank"] = int(g["priority_rank"])

    with open(DATA / "sites.csv", encoding="utf-8") as f:
        sites = list(csv.DictReader(f))
    for s in sites:
        s["weekly_capacity_doses"] = int(s["weekly_capacity_doses"])
        s["has_ultralow_freezer"] = int(s["has_ultralow_freezer"])
        s["has_standard_freezer"] = int(s["has_standard_freezer"])

    with open(DATA / "vaccine_types.csv", encoding="utf-8") as f:
        vaccines = list(csv.DictReader(f))
    for v in vaccines:
        v["doses_required"] = int(v["doses_required"])
        v["gap_weeks"] = int(v["gap_weeks"])

    with open(DATA / "weekly_supply.csv", encoding="utf-8") as f:
        supply_rows = list(csv.DictReader(f))
    supply = defaultdict(int)
    for r in supply_rows:
        supply[(int(r["week"]), r["vaccine_id"])] = int(r["doses_arriving"])

    return groups, sites, vaccines, dict(supply)


# ---------- model builder ----------
def build_model(groups, sites, vaccines, supply, active_hcs: set):
    m = cp_model.CpModel()

    G = [g["group_id"] for g in groups]
    S = [s["site_id"] for s in sites]
    V = [v["vaccine_id"] for v in vaccines]
    pop = {g["group_id"]: g["population"] for g in groups}
    rank = {g["group_id"]: g["priority_rank"] for g in groups}
    site_cap = {s["site_id"]: s["weekly_capacity_doses"] for s in sites}
    ultralow = {s["site_id"]: s["has_ultralow_freezer"] for s in sites}
    standard_f = {s["site_id"]: s["has_standard_freezer"] for s in sites}
    staff = {s["site_id"]: s["staffing_level"] for s in sites}
    vinfo = {v["vaccine_id"]: v for v in vaccines}

    gap = {v["vaccine_id"]: v["gap_weeks"] for v in vaccines}
    doses_req = {v["vaccine_id"]: v["doses_required"] for v in vaccines}

    # Large per-cell upper bound: can't exceed site capacity in one week.
    BIG = max(site_cap.values())

    # ---- Decision variables ----
    dose1 = {}
    dose2 = {}
    for g in G:
        for s in S:
            for w in WEEKS:
                for v in V:
                    dose1[g, s, w, v] = m.NewIntVar(0, BIG, f"d1_{g}_{s}_{w}_{v}")
                    dose2[g, s, w, v] = m.NewIntVar(0, BIG, f"d2_{g}_{s}_{w}_{v}")

    # HC8: VJ 2nd doses always 0 — structural, always enforced.
    for g in G:
        for s in S:
            for w in WEEKS:
                m.Add(dose2[g, s, w, "VJ"] == 0)

    # HC4: VP only at ultralow sites
    if "HC4" in active_hcs:
        for s in S:
            if not ultralow[s]:
                for g in G:
                    for w in WEEKS:
                        m.Add(dose1[g, s, w, "VP"] == 0)
                        m.Add(dose2[g, s, w, "VP"] == 0)

    # HC5: VM only at standard-or-ultralow sites
    if "HC5" in active_hcs:
        for s in S:
            if not (standard_f[s] or ultralow[s]):
                for g in G:
                    for w in WEEKS:
                        m.Add(dose1[g, s, w, "VM"] == 0)
                        m.Add(dose2[g, s, w, "VM"] == 0)

    # HC15: low-staffing sites -> VJ only (no 2-dose vaccines at all)
    if "HC15" in active_hcs:
        for s in S:
            if staff[s] == "low":
                for g in G:
                    for w in WEEKS:
                        m.Add(dose1[g, s, w, "VP"] == 0)
                        m.Add(dose2[g, s, w, "VP"] == 0)
                        m.Add(dose1[g, s, w, "VM"] == 0)
                        m.Add(dose2[g, s, w, "VM"] == 0)

    # HC2: weekly site capacity (first + second doses)
    if "HC2" in active_hcs:
        for s in S:
            for w in WEEKS:
                m.Add(
                    sum(
                        dose1[g, s, w, v] + dose2[g, s, w, v]
                        for g in G for v in V
                    )
                    <= site_cap[s]
                )

    # HC3: weekly supply limit per vaccine (doses arriving that week)
    # HC18 extends this to cumulative (inventory rule). HC3 is instantaneous.
    if "HC3" in active_hcs:
        for v in V:
            for w in WEEKS:
                m.Add(
                    sum(
                        dose1[g, s, w, v] + dose2[g, s, w, v]
                        for g in G for s in S
                    )
                    <= supply.get((w, v), 0)
                )

    # HC18: cumulative inventory — cumulative used <= cumulative arrived.
    # This is the physically correct rule; HC3 is the simpler proxy.
    if "HC18" in active_hcs:
        for v in V:
            for w in WEEKS:
                cum_supply = sum(supply.get((ww, v), 0) for ww in WEEKS if ww <= w)
                m.Add(
                    sum(
                        dose1[g, s, ww, v] + dose2[g, s, ww, v]
                        for g in G for s in S for ww in WEEKS if ww <= w
                    )
                    <= cum_supply
                )

    # HC6: VP 2nd dose exactly 3 weeks after 1st at same site and group.
    # dose2[g,s,w,VP] == dose1[g,s,w-3,VP]  (for w>=4 since weeks are 1-indexed)
    if "HC6" in active_hcs:
        for g in G:
            for s in S:
                for w in WEEKS:
                    if w - gap["VP"] >= 1:
                        m.Add(dose2[g, s, w, "VP"] == dose1[g, s, w - gap["VP"], "VP"])
                    else:
                        m.Add(dose2[g, s, w, "VP"] == 0)

    # HC7: VM 2nd dose exactly 4 weeks after 1st
    if "HC7" in active_hcs:
        for g in G:
            for s in S:
                for w in WEEKS:
                    if w - gap["VM"] >= 1:
                        m.Add(dose2[g, s, w, "VM"] == dose1[g, s, w - gap["VM"], "VM"])
                    else:
                        m.Add(dose2[g, s, w, "VM"] == 0)

    # HC9: implicit in HC6/HC7 (dose2 linked to dose1 of the SAME vaccine).
    # HC13: monotonic cumulative — implied by dose variables being >= 0.
    # HC17: integer >=0 — enforced by variable domain.

    # HC10: 1st dose of 2-dose vaccine cannot be in a week that leaves no
    # room for the 2nd dose. For VP: w + 3 <= 10 -> w <= 7. For VM: w <= 6.
    if "HC10" in active_hcs:
        for g in G:
            for s in S:
                for w in WEEKS:
                    if w + gap["VP"] > max(WEEKS):
                        m.Add(dose1[g, s, w, "VP"] == 0)
                    if w + gap["VM"] > max(WEEKS):
                        m.Add(dose1[g, s, w, "VM"] == 0)

    # HC16: all 1st doses of 2-dose vaccines must have matching 2nd doses.
    # Under HC6/HC7 this is automatic because dose2 at w = dose1 at w-gap,
    # so EVERY dose1 given in an eligible week is echoed by a dose2 later.
    # We add no extra constraint — the structural equality handles it.

    # HC1 / HC14: total group doses <= population
    # Interpretation: people vaccinated = (1st doses of VP + 1st doses of VM
    # + VJ doses). 2nd doses don't count as additional people. HC14 is the
    # same rule.
    if "HC1" in active_hcs or "HC14" in active_hcs:
        for g in G:
            people = sum(
                dose1[g, s, w, "VP"] + dose1[g, s, w, "VM"] + dose1[g, s, w, "VJ"]
                for s in S for w in WEEKS
            )
            m.Add(people <= pop[g])

    # HC11: G2 may only start at week >= 3 (simplified priority chaining; A-rule)
    if "HC11" in active_hcs:
        for s in S:
            for v in V:
                for w in WEEKS:
                    if w < 3:
                        m.Add(dose1["G2", s, w, v] == 0)

    # HC12: G4 may only start at week >= 4 (simplified; A-rule)
    if "HC12" in active_hcs:
        for s in S:
            for v in V:
                for w in WEEKS:
                    if w < 4:
                        m.Add(dose1["G4", s, w, v] == 0)
        # Also gate G5 at week >= 5 to keep the rollout realistic
        for s in S:
            for v in V:
                for w in WEEKS:
                    if w < 5:
                        m.Add(dose1["G5", s, w, v] == 0)

    # ---- Baseline objective: maximize total people vaccinated ----
    total_people = sum(
        dose1[g, s, w, "VP"] + dose1[g, s, w, "VM"] + dose1[g, s, w, "VJ"]
        for g in G for s in S for w in WEEKS
    )
    people_var = m.NewIntVar(0, sum(pop.values()), "total_people")
    m.Add(people_var == total_people)
    m.Maximize(people_var)

    vb = {
        "dose1": dose1,
        "dose2": dose2,
        "people_var": people_var,
        "G": G,
        "S": S,
        "V": V,
        "WEEKS": WEEKS,
    }
    return m, vb


# ---------- solution extraction ----------
def extract_solution(solver, vb):
    sol = {"dose1": {}, "dose2": {}}
    for (g, s, w, v), var in vb["dose1"].items():
        val = solver.Value(var)
        if val > 0:
            sol["dose1"][(g, s, w, v)] = val
    for (g, s, w, v), var in vb["dose2"].items():
        val = solver.Value(var)
        if val > 0:
            sol["dose2"][(g, s, w, v)] = val
    sol["total_people"] = solver.Value(vb["people_var"])
    return sol


# ---------- independent verifier ----------
def verify_all_hcs(sol, groups, sites, vaccines, supply):
    pop = {g["group_id"]: g["population"] for g in groups}
    site_cap = {s["site_id"]: s["weekly_capacity_doses"] for s in sites}
    ultralow = {s["site_id"]: s["has_ultralow_freezer"] for s in sites}
    standard_f = {s["site_id"]: s["has_standard_freezer"] for s in sites}
    staff = {s["site_id"]: s["staffing_level"] for s in sites}
    gap = {v["vaccine_id"]: v["gap_weeks"] for v in vaccines}
    G = [g["group_id"] for g in groups]
    S = [s["site_id"] for s in sites]
    V = [v["vaccine_id"] for v in vaccines]

    d1 = sol["dose1"]
    d2 = sol["dose2"]

    def g1(g, s, w, v): return d1.get((g, s, w, v), 0)
    def g2(g, s, w, v): return d2.get((g, s, w, v), 0)

    results = {}
    def add(k, ok, msgs):
        results[k] = {"ok": ok, "violations": msgs[:5]}

    # HC1 & HC14: total people per group <= population
    msgs = []
    for g in G:
        people = sum(g1(g, s, w, v) for s in S for w in WEEKS for v in V)
        if people > pop[g]:
            msgs.append(f"{g}: {people} > pop {pop[g]}")
    add("HC1", not msgs, msgs)
    add("HC14", not msgs, msgs)

    # HC2: weekly site capacity
    msgs = []
    for s in S:
        for w in WEEKS:
            tot = sum(g1(g, s, w, v) + g2(g, s, w, v) for g in G for v in V)
            if tot > site_cap[s]:
                msgs.append(f"{s} w{w}: {tot} > cap {site_cap[s]}")
    add("HC2", not msgs, msgs)

    # HC3: weekly per-vaccine supply
    msgs = []
    for v in V:
        for w in WEEKS:
            tot = sum(g1(g, s, w, v) + g2(g, s, w, v) for g in G for s in S)
            if tot > supply.get((w, v), 0):
                msgs.append(f"{v} w{w}: {tot} > supply {supply.get((w, v), 0)}")
    add("HC3", not msgs, msgs)

    # HC4: VP only at ultralow
    msgs = []
    for s in S:
        if ultralow[s]:
            continue
        for g in G:
            for w in WEEKS:
                if g1(g, s, w, "VP") + g2(g, s, w, "VP") > 0:
                    msgs.append(f"VP at non-ultralow {s}")
                    break
    add("HC4", not msgs, msgs)

    # HC5: VM only at standard/ultralow
    msgs = []
    for s in S:
        if standard_f[s] or ultralow[s]:
            continue
        for g in G:
            for w in WEEKS:
                if g1(g, s, w, "VM") + g2(g, s, w, "VM") > 0:
                    msgs.append(f"VM at no-freezer {s}")
                    break
    add("HC5", not msgs, msgs)

    # HC6: VP 3-week gap equality
    msgs = []
    for g in G:
        for s in S:
            for w in WEEKS:
                expected = g1(g, s, w - gap["VP"], "VP") if w - gap["VP"] >= 1 else 0
                if g2(g, s, w, "VP") != expected:
                    msgs.append(f"VP gap {g}/{s}/w{w}: {g2(g, s, w, 'VP')} vs {expected}")
    add("HC6", not msgs, msgs)

    # HC7: VM 4-week gap
    msgs = []
    for g in G:
        for s in S:
            for w in WEEKS:
                expected = g1(g, s, w - gap["VM"], "VM") if w - gap["VM"] >= 1 else 0
                if g2(g, s, w, "VM") != expected:
                    msgs.append(f"VM gap {g}/{s}/w{w}: {g2(g, s, w, 'VM')} vs {expected}")
    add("HC7", not msgs, msgs)

    # HC8: no VJ 2nd dose
    msgs = []
    for g in G:
        for s in S:
            for w in WEEKS:
                if g2(g, s, w, "VJ") > 0:
                    msgs.append(f"VJ d2 at {g}/{s}/w{w}")
    add("HC8", not msgs, msgs)

    # HC9: implicit — HC6/HC7 handle vaccine matching. We pass if both do.
    add("HC9", results["HC6"]["ok"] and results["HC7"]["ok"], [])

    # HC10: VP w1 cannot exceed week 7; VM w1 cannot exceed week 6
    msgs = []
    for g in G:
        for s in S:
            for w in WEEKS:
                if w + gap["VP"] > max(WEEKS) and g1(g, s, w, "VP") > 0:
                    msgs.append(f"VP d1 {g}/{s}/w{w} no horizon")
                if w + gap["VM"] > max(WEEKS) and g1(g, s, w, "VM") > 0:
                    msgs.append(f"VM d1 {g}/{s}/w{w} no horizon")
    add("HC10", not msgs, msgs)

    # HC11: G2 should not start before w3
    msgs = []
    for s in S:
        for v in V:
            for w in WEEKS:
                if w < 3 and g1("G2", s, w, v) > 0:
                    msgs.append(f"G2 early at {s}/w{w}/{v}")
    add("HC11", not msgs, msgs)

    # HC12: G4 before w4, G5 before w5
    msgs = []
    for s in S:
        for v in V:
            for w in WEEKS:
                if w < 4 and g1("G4", s, w, v) > 0:
                    msgs.append(f"G4 early")
                if w < 5 and g1("G5", s, w, v) > 0:
                    msgs.append(f"G5 early")
    add("HC12", not msgs, msgs)

    # HC13: monotonic cumulative — automatically true for non-negative int doses.
    add("HC13", True, [])

    # HC15: low-staffing -> VJ only
    msgs = []
    for s in S:
        if staff[s] != "low":
            continue
        for g in G:
            for w in WEEKS:
                for v in ("VP", "VM"):
                    if g1(g, s, w, v) + g2(g, s, w, v) > 0:
                        msgs.append(f"{v} at low-staff {s}")
    add("HC15", not msgs, msgs)

    # HC16: every dose1 of 2-dose vaccine has a matching dose2.
    # Sum check: total dose1 == total dose2 for VP and VM.
    msgs = []
    for v in ("VP", "VM"):
        t1 = sum(g1(g, s, w, v) for g in G for s in S for w in WEEKS)
        t2 = sum(g2(g, s, w, v) for g in G for s in S for w in WEEKS)
        if t1 != t2:
            msgs.append(f"{v}: d1 total {t1} != d2 total {t2}")
    add("HC16", not msgs, msgs)

    # HC17: non-negative integers — always true from solver
    add("HC17", True, [])

    # HC18: cumulative supply rule
    msgs = []
    for v in V:
        cum = 0
        used = 0
        for w in WEEKS:
            cum += supply.get((w, v), 0)
            used += sum(g1(g, s, w, v) + g2(g, s, w, v) for g in G for s in S)
            if used > cum:
                msgs.append(f"{v} w{w}: used {used} > cum supply {cum}")
                break
    add("HC18", not msgs, msgs)

    return results


# ---------- driver ----------
def solve_phase(name, active_hcs, data, time_limit=TIME_LIMIT):
    groups, sites, vaccines, supply = data
    print(f"\n=== PHASE {name}  HCs={sorted(active_hcs)} ===")
    m, vb = build_model(groups, sites, vaccines, supply, active_hcs)
    n_vars = len(m.Proto().variables)
    n_cons = len(m.Proto().constraints)
    print(f"  model size: vars={n_vars} constraints={n_cons}")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = WORKERS
    if "P12" not in name:
        solver.parameters.stop_after_first_solution = True
    status = solver.Solve(m)
    sn = solver.StatusName(status)
    obj = solver.ObjectiveValue() if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None
    print(f"  status={sn}  obj={obj}")

    entry = {
        "phase": name,
        "status": sn,
        "objective": obj,
        "vars": n_vars,
        "constraints": n_cons,
        "active_hcs": sorted(active_hcs),
    }

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        sol = extract_solution(solver, vb)
        verify = verify_all_hcs(sol, groups, sites, vaccines, supply)
        active_viol = sum(0 if verify[k]["ok"] else 1 for k in verify if k in active_hcs)
        pending_viol = sum(0 if verify[k]["ok"] else 1 for k in verify if k not in active_hcs)
        n_ok = sum(1 for v in verify.values() if v["ok"])
        print(f"  verify: {n_ok}/{len(verify)} ok  active_viol={active_viol}  pending_viol={pending_viol}")
        for k, v in verify.items():
            if not v["ok"] and k in active_hcs:
                print(f"    {k} (active) FAIL: {v['violations'][:2]}")
        entry["total_people"] = sol["total_people"]
        entry["active_hc_violations"] = active_viol
        entry["pending_hc_violations"] = pending_viol
        entry["verify"] = {k: {"ok": v["ok"], "n_viol": len(v["violations"])}
                           for k, v in verify.items()}
    return entry


def main():
    data = load_data()
    groups, sites, vaccines, supply = data
    print(f"Loaded: {len(groups)} groups, {len(sites)} sites, {len(vaccines)} vaccines, "
          f"{len(supply)} supply rows")
    print(f"Total population: {sum(g['population'] for g in groups)}")
    print(f"Total VP supply: {sum(supply.get((w, 'VP'), 0) for w in WEEKS)}")
    print(f"Total VM supply: {sum(supply.get((w, 'VM'), 0) for w in WEEKS)}")
    print(f"Total VJ supply: {sum(supply.get((w, 'VJ'), 0) for w in WEEKS)}")

    all_hcs = {f"HC{i}" for i in range(1, 19)}
    phases = [
        ("P01_caps_only",              {"HC1", "HC2", "HC14", "HC17"}),
        ("P02_+supply",                {"HC1", "HC2", "HC3", "HC14", "HC17"}),
        ("P03_+storage",               {"HC1", "HC2", "HC3", "HC4", "HC5", "HC14", "HC17"}),
        ("P04_+staffing",              {"HC1","HC2","HC3","HC4","HC5","HC14","HC15","HC17"}),
        ("P05_+VJ_singledose",         {"HC1","HC2","HC3","HC4","HC5","HC8","HC14","HC15","HC17"}),
        ("P06_+VP_gap",                {"HC1","HC2","HC3","HC4","HC5","HC6","HC8","HC9","HC14","HC15","HC17"}),
        ("P07_+VM_gap",                {"HC1","HC2","HC3","HC4","HC5","HC6","HC7","HC8","HC9","HC14","HC15","HC17"}),
        ("P08_+horizon_rule",          {"HC1","HC2","HC3","HC4","HC5","HC6","HC7","HC8","HC9","HC10","HC14","HC15","HC16","HC17"}),
        ("P09_+priority_gates",        {"HC1","HC2","HC3","HC4","HC5","HC6","HC7","HC8","HC9","HC10","HC11","HC12","HC13","HC14","HC15","HC16","HC17"}),
        ("P10_+cum_inventory",         all_hcs),
        ("P11_all_HCs_feas",           all_hcs),
        ("P12_all_HCs_opt",            all_hcs),
    ]

    all_entries = []
    first_infeasible = None
    for name, active in phases:
        entry = solve_phase(name, active, data)
        all_entries.append(entry)
        if entry["status"] not in ("OPTIMAL", "FEASIBLE") and first_infeasible is None:
            first_infeasible = name
            print(f"\n!!! first infeasible at {name} — stopping cascade")
            break

    out = {
        "first_infeasible": first_infeasible,
        "phases": all_entries,
        "n_hcs": 18,
        "total_population": sum(g["population"] for g in groups),
        "total_supply": {
            v["vaccine_id"]: sum(supply.get((w, v["vaccine_id"]), 0) for w in WEEKS)
            for v in vaccines
        },
    }
    with open(RESULTS / "baseline_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved to {RESULTS / 'baseline_results.json'}")


if __name__ == "__main__":
    main()
