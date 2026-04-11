"""FJSP v1 variant sweep: 5 director-facing weight profiles over the full HC set.

Reuses build_with_objective from improve.py.
"""

from __future__ import annotations

import json
from pathlib import Path

from ortools.sat.python import cp_model

from improve import build_with_objective
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
    ("V1_director_default",  {"makespan":3, "tardiness":5, "m_balance":1, "setup":1, "o_balance":1, "prio_early":1}),
    ("V2_max_throughput",    {"makespan":10,"tardiness":1, "m_balance":0, "setup":0, "o_balance":0, "prio_early":0}),
    ("V3_union_friendly",    {"makespan":1, "tardiness":2, "m_balance":2, "setup":1, "o_balance":15,"prio_early":1}),
    ("V4_cost_min_setup",    {"makespan":2, "tardiness":3, "m_balance":2, "setup":10,"o_balance":1, "prio_early":1}),
    ("V5_urgent_first",      {"makespan":2, "tardiness":25,"m_balance":1, "setup":1, "o_balance":1, "prio_early":10}),
]


def main():
    data = load_data()
    machines, operators, jobs, operations, tools = data
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
        sol = extract_solution(solver, vb, machines, operators, operations)
        v = verify_all_hcs(sol, machines, operators, jobs, operations, tools)
        n_ok = sum(1 for x in v.values() if x["ok"])
        print(f"  {sn} obj={solver.ObjectiveValue()} HC_ok={n_ok}/20")
        out.append({
            "name": name,
            "status": sn,
            "objective": solver.ObjectiveValue(),
            "hc_ok": n_ok,
            "weights": w,
            "metrics": {
                "makespan": solver.Value(metrics["makespan"]),
                "total_tardiness": solver.Value(metrics["total_tardiness"]),
                "mload_spread": solver.Value(metrics["mload_spread"]),
                "total_setup": solver.Value(metrics["total_setup"]),
                "oload_spread": solver.Value(metrics["oload_spread"]),
            },
        })
    with open(RESULTS / "variants_results.json", "w", encoding="utf-8") as f:
        json.dump({"variants": out}, f, indent=2, default=str)
    print(f"\nSaved {RESULTS / 'variants_results.json'}")


if __name__ == "__main__":
    main()
