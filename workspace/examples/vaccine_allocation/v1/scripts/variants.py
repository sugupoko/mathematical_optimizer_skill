"""Vaccine allocation v1 variant sweep: 5 director-facing weight profiles.

Reuses build_with_objective from improve.py.
"""

from __future__ import annotations

import json
from pathlib import Path

from ortools.sat.python import cp_model

from improve import _group_coverage, build_with_objective
from staged_baseline import (
    TIME_LIMIT,
    WORKERS,
    extract_solution,
    load_data,
    verify_all_hcs,
)

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results"

PROFILES = [
    ("V1_director_default",  {"people":10,"priority":2, "waste":2, "balance":1, "early":0, "ultralow":0}),
    ("V2_max_throughput",    {"people":20,"priority":0, "waste":0, "balance":0, "early":0, "ultralow":0}),
    ("V3_equity_elderly",    {"people":3, "priority":10,"waste":1, "balance":0, "early":1, "ultralow":0}),
    ("V4_min_waste_strict",  {"people":5, "priority":1, "waste":25,"balance":1, "early":0, "ultralow":0}),
    ("V5_cheap_logistics",   {"people":8, "priority":2, "waste":2, "balance":1, "early":0, "ultralow":5}),
]


def main():
    data = load_data()
    groups, sites, vaccines, supply = data
    out = []
    for name, w in PROFILES:
        print(f"\n--- {name} {w} ---")
        m, vb, metrics = build_with_objective(data, w)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = TIME_LIMIT
        solver.parameters.num_search_workers = WORKERS
        st = solver.Solve(m)
        sn = solver.StatusName(st)
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            print(f"  {sn}")
            out.append({"name": name, "status": sn, "weights": w})
            continue
        sol = extract_solution(solver, vb)
        v = verify_all_hcs(sol, groups, sites, vaccines, supply)
        n_ok = sum(1 for x in v.values() if x["ok"])
        cov = _group_coverage(sol, groups)
        print(f"  {sn} obj={solver.ObjectiveValue()}  people={solver.Value(metrics['people'])}  "
              f"waste={solver.Value(metrics['waste'])}  HC_ok={n_ok}/18")
        out.append({
            "name": name,
            "status": sn,
            "objective": solver.ObjectiveValue(),
            "hc_ok": n_ok,
            "weights": w,
            "metrics": {
                "people": solver.Value(metrics["people"]),
                "prio_weighted": solver.Value(metrics["prio_weighted"]),
                "waste": solver.Value(metrics["waste"]),
                "sload_spread": solver.Value(metrics["sload_spread"]),
                "early_penalty": solver.Value(metrics["early_penalty"]),
                "ultralow_use": solver.Value(metrics["ultralow_use"]),
            },
            "coverage_by_group": cov,
        })
    with open(RESULTS / "variants_results.json", "w", encoding="utf-8") as f:
        json.dump({"variants": out}, f, indent=2, default=str)
    print(f"\nSaved {RESULTS / 'variants_results.json'}")


if __name__ == "__main__":
    main()
