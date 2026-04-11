"""
One-shot baseline — 比較用

段階化せず、最初から全 12 HC を入れて解く。
staged が HC7+HC8 で infeasible を検出した問題に対して、
一発解きだと情報がどうなるかを確認する。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import staged_baseline as sb
from ortools.sat.python import cp_model

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

TIME_LIMIT = 60.0
NUM_WORKERS = 4


def main():
    print("=" * 72)
    print("ONE-SHOT BASELINE — worker_supervisor v1")
    print("=" * 72)
    print(f"Workers: {len(sb.WORKERS)}  Supervisors: {len(sb.SUPERVISORS)}  Shifts: {len(sb.SHIFTS)}")
    print(f"Attempting to solve with ALL 12 HCs at once (max_phase=12)...")
    print()

    t0 = time.time()
    model, *_ = sb.build_model(max_phase=12)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TIME_LIMIT
    solver.parameters.num_search_workers = NUM_WORKERS

    status = solver.Solve(model)
    elapsed = time.time() - t0
    feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    print(f"Status: {solver.StatusName(status)}")
    print(f"Time: {elapsed:.2f}s")
    print(f"Feasible: {feasible}")

    if not feasible:
        print()
        print("!!! INFEASIBLE !!!")
        print("One-shot tells us the problem is infeasible with ALL 12 HCs,")
        print("but does NOT tell us WHICH constraints are the bottleneck.")
        print()
        print("Contrast with staged: Phase 5 (+HC7+HC8) was the first infeasible phase,")
        print("isolating the bottleneck to skill + bilingual constraints in <1 second.")

    result = {
        "approach": "one_shot",
        "solver_status": solver.StatusName(status),
        "solver_feasible": feasible,
        "time_sec": round(elapsed, 2),
    }

    with open(RESULTS / "one_shot_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {RESULTS / 'one_shot_results.json'}")


if __name__ == "__main__":
    main()
