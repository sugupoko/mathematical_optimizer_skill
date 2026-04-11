"""GPU Cluster Scheduling v1 — 5 weight-profile sweep.

Reuses build_with_objective() from improve.py to explore the SC weight space
for the research director / infrastructure lead's review.
"""

from __future__ import annotations

import json
from pathlib import Path

from ortools.sat.python import cp_model

from improve import build_with_objective
from staged_baseline import (
    FINAL_TIME_LIMIT,
    WORKERS,
    extract_solution,
    load_data,
    verify_all_hcs,
)

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results"

PROFILES = [
    ("V1_director_default",
     {"w_sc1": 6, "w_sc2": 8,  "w_sc3": 0, "w_sc4": 2, "w_sc5": 4, "w_sc6": 2, "w_sc7": 0, "w_sc8": 1}),
    ("V2_max_throughput",
     {"w_sc1": 15,"w_sc2": 5,  "w_sc3": 0, "w_sc4": 0, "w_sc5": 0, "w_sc6": 0, "w_sc7": 0, "w_sc8": 0}),
    ("V3_tier1_first",
     {"w_sc1": 3, "w_sc2": 20, "w_sc3": 0, "w_sc4": 5, "w_sc5": 0, "w_sc6": 4, "w_sc7": 0, "w_sc8": 0}),
    ("V4_green",
     {"w_sc1": 2, "w_sc2": 3,  "w_sc3": 1, "w_sc4": 15,"w_sc5": 0, "w_sc6": 0, "w_sc7": 0, "w_sc8": 0}),
    ("V5_fair_share",
     {"w_sc1": 5, "w_sc2": 3,  "w_sc3": 0, "w_sc4": 1, "w_sc5": 25,"w_sc6": 1, "w_sc7": 0, "w_sc8": 0}),
]


def main():
    data = load_data()
    nodes, gpus, teams, jobs, licenses, maint = data
    out = []
    for name, w in PROFILES:
        print(f"\n--- {name} {w} ---")
        m, vb, metrics = build_with_objective(data, w)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = FINAL_TIME_LIMIT
        solver.parameters.num_search_workers = WORKERS
        st = solver.Solve(m)
        sn = solver.StatusName(st)
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            print(f"  {sn}")
            out.append({"name": name, "status": sn, "weights": w})
            continue
        sol = extract_solution(solver, vb, jobs)
        v = verify_all_hcs(sol, nodes, gpus, teams, jobs, licenses, maint)
        n_ok = sum(1 for x in v.values() if x["ok"])
        n_acc = sum(1 for s in sol.values() if s is not None)
        print(f"  {sn} obj={solver.ObjectiveValue()} acc={n_acc}/{len(jobs)} HC_ok={n_ok}/22")
        team_cov = {}
        for tid, (cov_var, demand) in metrics["team_coverage"].items():
            got = solver.Value(cov_var)
            team_cov[tid] = {
                "served_gph": got, "demand_gph": demand,
                "coverage_pct": round(100 * got / demand, 1) if demand else 100.0,
            }
        out.append({
            "name": name,
            "status": sn,
            "objective": solver.ObjectiveValue(),
            "accepted": n_acc,
            "hc_ok": n_ok,
            "weights": w,
            "metrics": {
                "sc1_accept": solver.Value(metrics["sc1_accept"]),
                "sc2_tier": solver.Value(metrics["sc2_tier"]),
                "sc3_power": solver.Value(metrics["sc3_power"]),
                "sc4_non_h100_pretrain": solver.Value(metrics["sc4_non_h100_pretrain"]),
                "sc5_spread_x1000pct": solver.Value(metrics["sc5_spread"]),
                "sc6_slack": solver.Value(metrics["sc6_slack"]),
                "sc8_overrun": solver.Value(metrics["sc8_overrun"]),
            },
            "team_coverage": team_cov,
        })
    with open(RESULTS / "variants_results.json", "w", encoding="utf-8") as f:
        json.dump({"variants": out}, f, indent=2, default=str)
    print(f"\nSaved {RESULTS / 'variants_results.json'}")


if __name__ == "__main__":
    main()
