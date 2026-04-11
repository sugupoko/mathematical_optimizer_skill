# Baseline Report — Flexible Job-Shop Scheduling v1

**Script**: `scripts/staged_baseline.py`
**Results**: `results/baseline_results.json`
**Pattern**: OR-Tools CP-SAT — `NewOptionalIntervalVar(start, size, end, presence)`
per (operation, eligible machine) pair, `AddNoOverlap` per machine, plus
`AddCumulative` per tool for HC13.

## 1. Headline

All 11 phases are **FEASIBLE**. The 20 HCs can be satisfied simultaneously
on the v1 data — no phase was the wall. The final optimised makespan with
the baseline (makespan-only) objective is **1770 minutes** (3.7 days of the
5-day horizon), versus the 2340-min first-feasible solution returned with
`stop_after_first_solution` in the intermediate phases.

## 2. Phase-by-phase Table

Active/pending HC split — "active" = HCs added to this phase's model,
"pending" = HCs checked by the independent verifier but not yet enforced.
Violations are measured by `verify_all_hcs()` running on the raw solution.

| Phase | Added HCs | Vars | Cons | Status | Makespan (min) | Active viol | Pending viol |
|---|---|---:|---:|---|---:|---:|---:|
| P01_machine_assign_noov | HC1, HC2, HC4, HC18 | 2318 | 2332 | FEASIBLE | 2265 | 0 | 9 |
| P02_+precedence | +HC3, HC16 | 2318 | 2519 | FEASIBLE | 2370 | 0 | 7 |
| P03_+day_fit | +HC5 | 2545 | 2973 | FEASIBLE | 2400 | 0 | 6 |
| P04_+maint_unavail | +HC6, HC7 | 3079 | 3774 | FEASIBLE | 2400 | 0 | 5 |
| P05_+earliest_due | +HC14, HC15 | 3079 | 4228 | FEASIBLE | 2400 | 0 | 2 |
| P06_+urgent | +HC19 | 3079 | 4253 | FEASIBLE | 2400 | 0 | 2 |
| P07_+tooling | +HC13 | 3079 | 4381 | FEASIBLE | 2370 | 0 | 1 |
| P08_+operator_core | +HC9, HC10 | 5803 | 6099 | FEASIBLE | 2370 | 0 | 3 |
| P09_+operator_caps | +HC11, HC12, HC17 | 5803 | 8851 | FEASIBLE | 2340 | 0 | 0 |
| P10_+setup_limit | +HC8, HC20 | 9283 | 21721 | FEASIBLE | 2340 | 0 | 0 |
| P11_all_HCs | (all 20) | 9283 | 21721 | FEASIBLE | **1770** | 0 | 0 |

**First infeasible phase**: _none_. The model's feasibility wall (where v1
was initially broken) was inside the data generator itself: urgent jobs had
due_day=1 with total op duration > 480 min. The generator was corrected so
all urgent jobs live in the 2-day window `[1, 2]` (total duration ≤ 600 min).
After that fix the 11-phase cascade ran cleanly.

## 3. Variable / Constraint Growth

The model grows as HC layers are added. The biggest jumps:

- **+HC9/HC10 (P08)**: creates `op_op[op,operator]` binaries (227 × 12 ≈
  2724 extra booleans).
- **+HC11/HC12/HC17 (P09)**: adds per-operator no-overlap intervals and
  aggregated weekly-cap constraints. Constraint count nearly doubles.
- **+HC8/HC20 (P10)**: the per-(machine, day, op_type) indicator matrix
  pushes constraint count from ~9k to ~22k and total vars from 5.8k to
  9.3k. HC20 is the single most expensive constraint group.

Peak model size: **9,283 variables / 21,721 constraints** at phases P10-P11.

## 4. Independent Verifier Confirmation

P09, P10 and P11 pass all 20 HCs in the verifier, confirming that the CP-SAT
`FEASIBLE` flag is corroborated by an independent re-check of the raw
solution (machines, starts, ends, operators, tool concurrency, precedence,
due/earliest, urgency, maintenance, and setup-type count).

## 5. What The Baseline Tells Us

1. The problem is **tractable** — the full 20-HC model solves to feasibility
   in well under 30 s with 8 workers.
2. The **CNC / tool bottleneck is not binding**: every phase finishes with
   pending violations reaching zero exactly when we add operator caps
   (P09), meaning operator capacity, not CNC or tooling, is the last
   constraint to "fill in".
3. The **makespan improves by 24%** (2340 → 1770 min) when we let the
   solver run without `stop_after_first_solution` in P11 — plenty of
   headroom for the improve phase to dig into multi-objective trade-offs.

## 6. Next Step

`python scripts/improve.py` runs 4 scenarios (balanced / throughput /
on_time / smooth) on top of the full HC set with different SC weights.
See `reports/improve_report.md`.
