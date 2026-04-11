"""Variant sweep: 5 weight profiles on top of full HC set.

Outputs: ../results/variants_results.json
"""

from __future__ import annotations

import json
from pathlib import Path

from improve import add_objective
from ortools.sat.python import cp_model

from staged_baseline import (
    TIME_LIMIT,
    WORKERS,
    build_model,
    extract_solution,
    load_data,
    verify_all_hcs,
)

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results"
ALL_HCS = {f"HC{i}" for i in range(1, 23)}


PROFILES = [
    ("V1_director_default",  {"cov":100,"su_early":3,"ped_purity":5,"clean":1,"or_balance":1,"surg_fair":1}),
    ("V2_max_throughput",    {"cov":1000,"su_early":0,"ped_purity":1,"clean":0,"or_balance":0,"surg_fair":0}),
    ("V3_union_friendly",    {"cov":100,"su_early":2,"ped_purity":3,"clean":0,"or_balance":5,"surg_fair":15}),
    ("V4_cost_min",          {"cov":80,"su_early":1,"ped_purity":10,"clean":8,"or_balance":3,"surg_fair":1}),
    ("V5_urgent_first",      {"cov":200,"su_early":15,"ped_purity":5,"clean":1,"or_balance":1,"surg_fair":2}),
]


def main():
    data = load_data()
    rooms, surgeons, anesths, nurses, patients, icu = data

    out = []
    for name, w in PROFILES:
        print(f"\n--- {name} {w} ---")
        m, v = build_model(rooms, surgeons, anesths, nurses, patients, icu, ALL_HCS)
        add_objective(m, v, rooms, surgeons, patients, w)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = TIME_LIMIT
        solver.parameters.num_search_workers = WORKERS
        st = solver.Solve(m)
        sn = solver.StatusName(st)
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            print(f"  {sn}")
            out.append({"name": name, "status": sn})
            continue
        pids = [p["patient_id"] for p in patients]
        rids = [r["room_id"] for r in rooms]
        sids = [s["surgeon_id"] for s in surgeons]
        aids = [a["anesth_id"] for a in anesths]
        sol = extract_solution(solver, v, pids, rids, sids, aids)
        vres = verify_all_hcs(sol, rooms, surgeons, anesths, nurses, patients, icu)
        n_ok = sum(1 for x in vres.values() if x["ok"])
        covered = sum(1 for _, loc in sol["sched"].items() if loc is not None)
        print(f"  {sn} covered={covered} HC_ok={n_ok}/22 obj={solver.ObjectiveValue()}")
        out.append({
            "name": name,
            "status": sn,
            "covered": covered,
            "hc_ok": n_ok,
            "objective": solver.ObjectiveValue(),
            "weights": w,
        })

    with open(RESULTS / "variants_results.json", "w", encoding="utf-8") as f:
        json.dump({"variants": out}, f, indent=2, default=str)


if __name__ == "__main__":
    main()
