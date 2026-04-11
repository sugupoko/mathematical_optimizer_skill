"""
SC weight variants for worker_supervisor v1.

Runs the recommended feasibility-recovery scenario (A: hire W021) under 5
different SC weight profiles to expose tradeoffs.

  V1 balanced
  V2 fairness max     (SC2 + SC3 emphasized)
  V3 coverage max     (SC1 + SC6 emphasized)
  V4 welfare          (SC4 + SC5 limit emphasized)
  V5 senior coverage  (SC7 emphasized)
"""

import json
import time
from pathlib import Path

from improve import (
    DEFAULT_WEIGHTS,
    NUM_WORKERS,
    TIME_LIMIT,
    build_full_model,
    evaluate_solution,
    load_pairs,
    load_shifts,
    load_supervisors,
    load_workers,
    verify_hard_constraints,
)
from ortools.sat.python import cp_model

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

VARIANTS = {
    "V1_balanced": dict(DEFAULT_WEIGHTS),
    "V2_fairness_max": {**DEFAULT_WEIGHTS, "sc2": 8, "sc3": 8},
    "V3_coverage_max": {**DEFAULT_WEIGHTS, "sc1": 15, "sc6": 10},
    "V4_welfare": {**DEFAULT_WEIGHTS, "sc4": 12, "sc5": 12},
    "V5_senior_coverage": {**DEFAULT_WEIGHTS, "sc7": 20},
}


def main():
    workers = load_workers()
    supervisors = load_supervisors()
    shifts = load_shifts()
    forbidden, mentor, preferred = load_pairs()

    # Use Scenario A (hire W021) as the base
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

    print("=" * 72)
    print("SC VARIANT COMPARISON  (base: Scenario A — hire W021)")
    print("=" * 72)

    out = {}
    for name, weights in VARIANTS.items():
        print(f"[{name}] solving...")
        t0 = time.time()
        model, vars_d = build_full_model(
            workers_A, supervisors, shifts, forbidden, mentor, preferred,
            weights=weights,
        )
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = TIME_LIMIT
        solver.parameters.num_search_workers = NUM_WORKERS
        status = solver.Solve(model)
        elapsed = time.time() - t0
        feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

        eval_data = evaluate_solution(solver, vars_d, workers_A, supervisors, shifts, feasible)
        hc_verify = None
        if feasible:
            hc_verify = verify_hard_constraints(
                solver, vars_d, workers_A, supervisors, shifts, forbidden, mentor, preferred
            )

        out[name] = {
            "weights": weights,
            "solver_status": solver.StatusName(status),
            "solver_feasible": feasible,
            "hc_all_satisfied": hc_verify["all_satisfied"] if hc_verify else None,
            "hc_total_violations": hc_verify["total_violations"] if hc_verify else None,
            "hc_violations_by_constraint": hc_verify["by_constraint"] if hc_verify else None,
            "objective": solver.ObjectiveValue() if feasible else None,
            "time_sec": round(elapsed, 2),
            "evaluation": eval_data,
        }
        if eval_data:
            hc_str = "HC OK" if hc_verify["all_satisfied"] else f"HC VIOL ({hc_verify['total_violations']})"
            print(f"    -> {solver.StatusName(status)} | {hc_str} | obj={solver.ObjectiveValue():.0f}  "
                  f"overall={eval_data['scores']['overall']}  ({elapsed:.1f}s)")
        else:
            print(f"    -> {solver.StatusName(status)}  ({elapsed:.1f}s)")

    out_path = RESULTS / "variant_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print()
    print(f"Saved: {out_path}")

    # Summary table
    print()
    print(f"{'Variant':<22} {'obj':>8} {'SC1':>4} {'SC2':>4} {'SC3':>4} {'SC4':>4} "
          f"{'SC5':>4} {'SC6':>4} {'SC7':>4} {'SC8':>4} {'avg':>5}")
    for name, r in out.items():
        if r["evaluation"]:
            sc = r["evaluation"]["scores"]
            print(f"{name:<22} {r['objective']:>8.0f} {sc['SC1_consecutive_days']:>4} "
                  f"{sc['SC2_worker_fairness']:>4} {sc['SC3_supervisor_fairness']:>4} "
                  f"{sc['SC4_worker_night']:>4} {sc['SC5_supervisor_night']:>4} "
                  f"{sc['SC6_min_hours']:>4} {sc['SC7_senior_coverage']:>4} "
                  f"{sc['SC8_preferred_pairs']:>4} {sc['overall']:>5}")


if __name__ == "__main__":
    main()
