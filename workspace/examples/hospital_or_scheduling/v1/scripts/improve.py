"""Improvement run with 4 scenarios: balanced / coverage / fairness / efficiency.

Each scenario reuses the full HC set from staged_baseline and changes the
objective weights only. Solutions are independently verified.

Outputs: ../results/improve_results.json
"""

from __future__ import annotations

import json
from pathlib import Path

from ortools.sat.python import cp_model

from staged_baseline import (
    CLEAN_MIN,
    DAYS,
    TIME_LIMIT,
    WORKERS,
    build_model,
    extract_solution,
    load_data,
    verify_all_hcs,
)

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

ALL_HCS = {f"HC{i}" for i in range(1, 23)}


def add_objective(m, v, rooms, surgeons, patients, weights):
    """Add a weighted composite objective to the model.

    SC1 coverage, SC2 surgeon fairness, SC3 OR balance, SC5 cleaning overhead,
    SC6 requested surgeon honoured (auto since HC22 hard), SC7 early semi-urgent,
    SC8 pediatric-room purity.
    """
    pids = [p["patient_id"] for p in patients]
    rids = [r["room_id"] for r in rooms]
    sids = [s["surgeon_id"] for s in surgeons]
    P = {p["patient_id"]: p for p in patients}
    R = {r["room_id"]: r for r in rooms}

    assign = v["assign"]
    sched = v["sched"]
    surg = v["surg"]
    pday = v["pday"]

    # SC1 coverage
    cov = sum(sched[pi] for pi in pids)

    # SC7 early semi-urgent (reward = (6 - d) * sched_on_day)
    su_reward = 0
    for p in patients:
        if p["priority"] == "semi_urgent":
            for d in DAYS:
                su_reward += (6 - d) * pday[p["patient_id"], d]

    # SC8 pediatric room reserved: penalise non-pediatric patient in OR5/OR6
    ped_rooms = [r["room_id"] for r in rooms if r["has_pediatric_eq"]]
    sc8_penalty = 0
    for pi in pids:
        if not P[pi]["is_pediatric"]:
            for ri in ped_rooms:
                for d in DAYS:
                    sc8_penalty += assign[pi, ri, d]

    # SC5 cleaning overhead = #scheduled cases * CLEAN_MIN
    sc5 = sum(sched[pi] for pi in pids)  # proxy = # cases

    # SC3 OR-day load balance: minimise max load deviation
    load = {}
    max_load = m.NewIntVar(0, 600, "max_load_or_day")
    for ri in rids:
        for d in DAYS:
            ll = sum(assign[pi, ri, d] * P[pi]["duration_minutes"] for pi in pids)
            ld = m.NewIntVar(0, 600, f"load_{ri}_{d}")
            m.Add(ld == ll)
            m.Add(max_load >= ld)
            load[ri, d] = ld

    # SC2 surgeon fairness: minimise max-min among surgeons actually used
    s_load = {}
    max_s_load = m.NewIntVar(0, 3000, "max_s_load")
    for si in sids:
        ll = sum(surg[pi, si] * P[pi]["duration_minutes"] for pi in pids)
        sl = m.NewIntVar(0, 3000, f"sload_{si}")
        m.Add(sl == ll)
        m.Add(max_s_load >= sl)
        s_load[si] = sl

    wcov = weights.get("cov", 100)
    wsu = weights.get("su_early", 3)
    wped = weights.get("ped_purity", 5)
    wclean = weights.get("clean", 1)
    wbal = weights.get("or_balance", 1)
    wfair = weights.get("surg_fair", 1)

    m.Maximize(
        wcov * cov
        + wsu * su_reward
        - wped * sc8_penalty
        - wclean * sc5
        - wbal * max_load
        - wfair * max_s_load
    )


def run_scenario(name, weights, rooms, surgeons, anesths, nurses, patients, icu):
    print(f"\n=== SCENARIO {name}  weights={weights} ===")
    m, v = build_model(rooms, surgeons, anesths, nurses, patients, icu, ALL_HCS)
    add_objective(m, v, rooms, surgeons, patients, weights)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TIME_LIMIT
    solver.parameters.num_search_workers = WORKERS
    status = solver.Solve(m)
    sn = solver.StatusName(status)
    print(f"  status={sn}")
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"scenario": name, "status": sn}

    pids = [p["patient_id"] for p in patients]
    rids = [r["room_id"] for r in rooms]
    sids = [s["surgeon_id"] for s in surgeons]
    aids = [a["anesth_id"] for a in anesths]
    sol = extract_solution(solver, v, pids, rids, sids, aids)
    vres = verify_all_hcs(sol, rooms, surgeons, anesths, nurses, patients, icu)
    n_ok = sum(1 for x in vres.values() if x["ok"])
    print(f"  verify: {n_ok}/{len(vres)} HCs ok; obj={solver.ObjectiveValue()}")

    # Compute SC metrics from the solution
    P = {p["patient_id"]: p for p in patients}
    sched = sol["sched"]
    surg = sol["surg"]
    covered = sum(1 for pi, loc in sched.items() if loc is not None)

    # surgeon minutes load
    s_minutes = {s["surgeon_id"]: 0 for s in surgeons}
    for pi, si in surg.items():
        if si is None or sched.get(pi) is None:
            continue
        s_minutes[si] += P[pi]["duration_minutes"]
    used = [v for v in s_minutes.values() if v > 0]
    surg_spread = max(used) - min(used) if used else 0

    # OR-day load
    or_load = {}
    for pi, loc in sched.items():
        if loc is None:
            continue
        or_load[loc] = or_load.get(loc, 0) + P[pi]["duration_minutes"]
    or_max = max(or_load.values()) if or_load else 0

    # Pediatric-room purity
    ped_rooms = {r["room_id"] for r in rooms if r["has_pediatric_eq"]}
    non_ped_in_ped_room = sum(
        1 for pi, loc in sched.items()
        if loc and loc[0] in ped_rooms and not P[pi]["is_pediatric"]
    )

    # Semi-urgent earliness score
    su_early = 0
    for p in patients:
        if p["priority"] == "semi_urgent" and sched.get(p["patient_id"]):
            su_early += 6 - sched[p["patient_id"]][1]

    metrics = {
        "covered": covered,
        "surgeon_spread_min": surg_spread,
        "or_max_minutes": or_max,
        "non_ped_in_ped_room": non_ped_in_ped_room,
        "semi_urgent_earliness": su_early,
        "objective": solver.ObjectiveValue(),
        "hc_ok": n_ok,
        "hc_total": len(vres),
    }
    print(f"  metrics: {metrics}")
    return {"scenario": name, "status": sn, "metrics": metrics}


def main():
    data = load_data()
    scenarios = {
        "balanced":        {"cov":100,"su_early":3,"ped_purity":5,"clean":1,"or_balance":1,"surg_fair":1},
        "coverage":        {"cov":500,"su_early":1,"ped_purity":1,"clean":0,"or_balance":0,"surg_fair":0},
        "fairness":        {"cov":100,"su_early":2,"ped_purity":3,"clean":0,"or_balance":3,"surg_fair":8},
        "efficiency":      {"cov":100,"su_early":2,"ped_purity":8,"clean":5,"or_balance":5,"surg_fair":1},
    }

    results = []
    for name, w in scenarios.items():
        r = run_scenario(name, w, *data)
        results.append(r)

    with open(RESULTS / "improve_results.json", "w", encoding="utf-8") as f:
        json.dump({"scenarios": results}, f, indent=2, default=str)
    print(f"\nSaved to {RESULTS / 'improve_results.json'}")


if __name__ == "__main__":
    main()
