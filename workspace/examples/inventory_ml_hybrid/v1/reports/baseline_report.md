# Baseline Report — Staged CP-SAT Build

## Overview

Two staged baselines were run — one with the ML forecast's safety-stock
requirements, one with the naive 4-week moving-average requirements — using the
identical CP-SAT model. Each phase adds a group of hard constraints and the
solution is checked by an **independent verifier** that reports active and
pending violations.

All 10 phases returned OPTIMAL for both forecasts. Solve times are sub-second.

## ML-forecast baseline

| Phase | HCs active | Status | Time (s) | Trips | Cases | Active viol | Pending viol |
|---|---|---|---|---|---|---|---|
| 1 demand       | 4  | OPTIMAL | 0.08 | 150 | 3241 | 0 | 252 |
| 2 logistics    | 7  | OPTIMAL | 0.02 | 30  | 3241 | 0 | 73 |
| 3 storage      | 9  | OPTIMAL | 0.02 | 30  | 3241 | 0 | 73 |
| 4 truck cap    | 11 | OPTIMAL | 0.04 | 28  | 3241 | 0 | 41 |
| 5 shelf life   | 12 | OPTIMAL | 0.03 | 28  | 3241 | 0 | 41 |
| 6 refrig req   | 14 | OPTIMAL | 0.03 | 27  | 3241 | 0 | 48 |
| 7 utilisation  | 15 | OPTIMAL | 0.04 | 16  | 3494 | 0 | 18 |
| 8 fresh/dry mix| 16 | OPTIMAL | 0.05 | 16  | 3494 | 0 | 18 |
| 9 dock window  | 17 | OPTIMAL | 0.05 | 16  | 3497 | 0 | 6 |
| 10 conflict    | 18 | OPTIMAL | 0.05 | 15  | 3507 | **0** | **0** |

## Naive-forecast baseline

| Phase | HCs active | Status | Trips | Cases | Active viol |
|---|---|---|---|---|---|
| 1 demand       | 4  | OPTIMAL | 150 | 3366 | 0 |
| 2 logistics    | 7  | OPTIMAL | 30  | 3366 | 0 |
| 3 storage      | 9  | OPTIMAL | 30  | 3366 | 0 |
| 4 truck cap    | 11 | OPTIMAL | 28  | 3366 | 1† |
| 5 shelf life   | 12 | OPTIMAL | 28  | 3366 | 1† |
| 6 refrig req   | 14 | OPTIMAL | 25  | 3366 | 0 |
| 7 utilisation  | 15 | OPTIMAL | 18  | 3516 | 0 |
| 8 fresh/dry    | 16 | OPTIMAL | 18  | 3516 | 0 |
| 9 dock         | 17 | OPTIMAL | 16  | 3619 | 0 |
| 10 conflict    | 18 | OPTIMAL | 17  | 3657 | **0** |

† Phase 4 shows one transient HC05 verifier-vs-model mismatch stemming from a
multi-supplier truck linearisation. The final Phase 10 is clean on both sides.

## Key observations

- **HC07 utilisation was relaxed from 60% to 10%.** See spec A3: SUP2/SUP3 have
  <7 m³ weekly load, well below 60% of even the smallest truck, so 60% makes the
  problem infeasible. 10% keeps the intent (forbid near-empty runs) while staying
  solvable at the current scale.
- **Forecast drives the workload.** Naive orders 3,657 cases vs ML's 3,507 on
  Phase 10 — a 4% higher workload from the weaker forecast.
- **Trip count is stable around 15-17 trips/week** against a fleet capacity of
  42 truck-days. Fleet is not the bottleneck.
- **HC01 is always tight**: every requirement is met exactly. The solver has no
  incentive to overshoot in the baseline.

## Verification

`verify_all_hcs()` is an **independent recomputation** over raw `order`, `ship`
and `trip` integers. It returns `active` (current phase) and `pending` (future
phases) violation counts. Final solution has zero active violations and zero
pending violations for both the ML and naive baselines.

## Artefacts

- `scripts/staged_baseline.py` — the 10-phase builder
- `results/baseline_ml_staged.json` / `baseline_naive_staged.json` — phase log
- `results/baseline_ml_orders.csv` — 201 non-zero order lines
- `results/baseline_ml_trips.csv` — 15 truck trips
