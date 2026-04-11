"""
One-shot baseline — 比較用

段階化せず、最初から全 HC を入れて解く。
staged との比較のため。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from staged_baseline import (
    build_model,
    load_nurses,
    load_shifts,
    verify_hcs,
)
from ortools.sat.python import cp_model

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

TIME_LIMIT = 60.0
NUM_WORKERS = 4


def main():
    nurses = load_nurses()
    shifts = load_shifts()
    nN, nS = len(nurses), len(shifts)

    print("=" * 72)
    print("ONE-SHOT BASELINE — clinic_nurse v1")
    print("=" * 72)
    print(f"Nurses: {nN}  Shifts: {nS}  Vars: {nN*nS}")
    print(f"Attempting to solve with ALL 8 HCs at once...")
    print()

    t0 = time.time()
    model, x = build_model(
        nurses, shifts,
        add_hc1=True, add_hc2=True, add_hc3=True, add_hc4=True,
        add_hc5=True, add_hc6=True, add_hc7=True, add_hc8=True,
    )
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TIME_LIMIT
    solver.parameters.num_search_workers = NUM_WORKERS

    status = solver.Solve(model)
    elapsed = time.time() - t0
    feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    print(f"Status: {solver.StatusName(status)}")
    print(f"Time: {elapsed:.2f}s")
    print(f"Feasible: {feasible}")

    if feasible:
        x_values = {(ni, s["idx"]): solver.Value(x[ni, s["idx"]])
                    for ni in range(nN) for s in shifts}
        total = sum(x_values.values())
        verify = verify_hcs(x_values, nurses, shifts)
        print(f"Total assignments: {total}")
        hc_status = "ALL OK" if verify["all_ok"] else f"VIOLATIONS {verify['total']}"
        print(f"Independent HC verifier: {hc_status}")
        if not verify["all_ok"]:
            print(f"  by HC: {verify['by_hc']}")
    else:
        print("\n!!!  INFEASIBLE / UNKNOWN — one-shot cannot diagnose which constraint is the problem  !!!")
        print("!!!  Would need staged approach to find the bottleneck                                  !!!")

    result = {
        "approach": "one_shot",
        "solver_status": solver.StatusName(status),
        "solver_feasible": feasible,
        "time_sec": round(elapsed, 2),
    }
    if feasible:
        result["hc_verify"] = verify

    with open(RESULTS / "one_shot_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {RESULTS / 'one_shot_results.json'}")


if __name__ == "__main__":
    main()
