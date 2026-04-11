# Baseline Report — GPU Cluster Scheduling v1

## Model

- CP-SAT, 75 jobs × 44 GPUs over 168-hour horizon
- 22 HCs total: 6 "static" (structural / memory-prune) + 16 solver-level
- Objective (baseline): maximise `sum(accept[j] * priority[j])`
- Final-phase size: **4,166 vars / 10,355 constraints**

## Staged cascade (19 phases)

Each row adds one dynamic HC on top of the previous. `active_viol` = how many
currently-active HCs fail the independent verifier on the returned solution
(must be 0). `pending_viol` = HCs not yet active but already failing — these
are the constraints we still have to activate.

| # | phase | HC added | vars | constraints | status | accepted | obj | active_viol | pending_viol |
|---|-------|----------|------|-------------|--------|----------|-----|-------------|--------------|
| P01 | static_only | — | 3073 | 6678 | OPTIMAL | 75 | 391 | 0 | 5 |
| P02 | +team_node_whitelist | HC13 | 3073 | 6736 | OPTIMAL | 75 | 391 | 0 | 5 |
| P03 | +gpu_count | HC2 | 3073 | 6736 | OPTIMAL | 75 | 391 | 0 | 4 |
| P04 | +gpu_nonoverlap | HC4 | 3073 | 6848 | OPTIMAL | 75 | 391 | 0 | 4 |
| P05 | +infiniband | HC7 | 3073 | 6848 | OPTIMAL | 75 | 391 | 0 | 4 |
| P06 | +v100_memory | HC20 | 3073 | 6848 | OPTIMAL | 75 | 391 | 0 | 4 |
| P07 | +pretrain_premium_only | HC22 | 3073 | 6848 | OPTIMAL | 75 | 391 | 0 | 4 |
| P08 | +dataset_locality | HC16 | 3073 | 7096 | OPTIMAL | 74 | 387 | 0 | 3 |
| P09 | +single_node_colocation | HC6 | 3270 | 8758 | OPTIMAL | 74 | 387 | 0 | 3 |
| P10 | +deadline | HC14 | 3270 | 8833 | OPTIMAL | 73 | 380 | 0 | 2 |
| P11 | +maintenance | HC15 | 4166 | 10177 | OPTIMAL | 73 | 380 | 0 | 2 |
| P12 | +node_power | HC8 | 4166 | 10183 | OPTIMAL | 73 | 380 | 0 | 2 |
| P13 | +cooling_zone | HC9 | 4166 | 10185 | OPTIMAL | 73 | 380 | 0 | 1 |
| P14 | +licenses | HC10 | 4166 | 10262 | OPTIMAL | 73 | 380 | 0 | 1 |
| P15 | +team_peak_gpus | HC11 | 4166 | 10343 | OPTIMAL | 73 | 378 | 0 | 1 |
| P16 | +team_weekly_budget | HC12 | 4166 | 10349 | OPTIMAL | 72 | 369 | 0 | 0 |
| P17 | +T6_guaranteed | HC21 | 4166 | 10354 | OPTIMAL | 72 | 369 | 0 | 0 |
| P18 | +T1_coverage_70pct | HC17 | 4166 | 10355 | OPTIMAL | 72 | 369 | 0 | 0 |
| P19 | all_HCs_optimize | — (longer solve) | 4166 | 10355 | OPTIMAL | 72 | 369 | 0 | 0 |

(numbers read from `results/baseline_results.json`.)

## Phase-by-phase interpretation

- **P01–P07: 75/75 accepted.** With only structural HCs and single-GPU
  compatibility rules, every job fits somewhere in the 168h horizon.
- **P08 (+dataset_locality) → 74/75.** One job cannot fit under its pinned
  node. This identifies HC16 as load-bearing for 1 rejection.
- **P10 (+deadline) → 73/75.** HC14 is the second-bite constraint. One more
  job cannot complete before its deadline after the cluster is committed to
  earlier jobs. T4/T5 research jobs are likely the victims here.
- **P15 (+team_peak_gpus) → 73/75 (obj drops from 380 → 378).** Accept count
  unchanged but the solver had to reshuffle priorities: a slightly
  lower-priority job replaced a higher one because HC11 prevented the high
  one from running simultaneously.
- **P16 (+team_weekly_budget) → 72/75 (obj 380 → 369).** T1 budget (1700 gph)
  vs demand (2312 gph) forces rejecting one of the largest pretrains. This
  is the **binding economic constraint**.
- **P17 (+T6_guaranteed) → 72/75.** No change: T6 jobs were already
  accepted under the priority-weighted throughput objective (priority 10).
- **P18 (+T1_coverage_70pct) → 72/75.** No change: HC17 threshold 1618 gph
  is below T1's budget 1700, so HC12 is strictly tighter. This documents
  that HC17 is currently **slack** — but it will bind the moment T1 budget
  relaxes.
- **P19 (long optimise) → 72/75.** The feasibility-oriented 45s phases
  already found the priority-weighted optimum; the 180s budget confirms
  OPTIMAL.

## Independent HC verification

Every phase runs `verify_all_hcs(sol, ...)` independently of the solver. From
P18 onward all 22 HCs pass; prior phases only fail HCs that are still
"pending". `active_hc_violations = 0` holds for every phase — the solver
never cheats on a declared-active constraint.

## Binding constraints (summary)

1. **HC16** (dataset_locality) — rejects 1 job
2. **HC14** (deadline) — rejects 1 job
3. **HC12** (team_weekly_budget, T1) — rejects 1 job / rotates priority
4. **HC11** (team_peak_gpus) — not rejecting but reshuffling
5. **HC8/HC9** (power/cooling) — not binding with current demand; would bind
   if T1 added more 8-GPU pretrains or T2 ramped up

## Infeasibility diagnosis

**None observed.** All 19 phases return OPTIMAL/FEASIBLE. The cluster can
serve 72 of 75 jobs under the full constraint set, with the 3 rejects coming
from HC16 + HC14 + HC12. The remaining demand gap (3 jobs) is the
**hard-tradeoff frontier** for the improve phase to navigate.

## Next steps

- `scripts/improve.py` — 4 SC weight scenarios (throughput / deadline_first
  / fairness / green)
- `scripts/variants.py` — 5 director-facing variants for the proposal
- Watch the "green" scenario: SC3 (power) weight = 1 on absolute watt-hours
  dominates the objective and collapses throughput from 72 → 17 jobs. That
  number is the cost of a naive green policy; the director will want a
  proper unit scaling.
