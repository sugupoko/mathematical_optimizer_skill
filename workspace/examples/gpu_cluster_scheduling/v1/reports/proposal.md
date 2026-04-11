# Proposal — GPU Cluster Scheduling v1

**Audience:** research director, infrastructure lead
**Horizon:** weekly scheduling (168 hours, one cluster)
**Decision requested:** adopt `deadline_first` as the default weekly profile,
with opt-in switches to `tier1_first` and `fair_share` for special weeks.

## Why this matters

The lab's cluster has 44 heterogeneous GPUs (16 H100, 16 A100-80GB, 8 A100-40GB,
4 V100) across 6 nodes and 2 cooling zones. Each week ~75 jobs compete for
7,392 GPU-hours of raw capacity, but real demand for premium GPUs (H100 +
A100-80GB) is tight: pretrain jobs alone book 2,472 of the 2,688 premium
GPU-hours available. At the same time, T1's weekly budget (1,700 GPU-h)
cannot absorb T1's full demand (2,312 GPU-h). **Three jobs a week will be
rejected no matter what we do — the question is which three, and how the
survivors are placed.**

## What we built

A CP-SAT scheduler that takes the full 22-constraint rulebook (gang
scheduling, InfiniBand topology, per-node power budgets, cooling zone caps,
license seats, team quotas, deadlines, T1 fairness floor, T6 guarantee,
pretrain-on-premium restriction, maintenance windows, dataset locality) and
produces a weekly schedule with:

- exact start hours
- GPU assignment per job
- HC-by-HC independently-verified correctness

Model size: **4,166 decision variables, 10,355 constraints**. Solve time at
the final optimise phase: ~180 seconds on 8 workers — acceptable for a
weekly planning run.

## What the numbers say

### Baseline (pure throughput)

| Phase | HC added | Accepted | Root cause |
|-------|----------|----------|------------|
| up to P07 | static + GPU placement | 75/75 | everything fits structurally |
| P08 | dataset locality | 74/75 | 1 job is pinned to a busy node |
| P10 | deadline | 73/75 | 1 more job can't finish before due date |
| P16 | team weekly budget (T1) | **72/75** | T1 cap forces dropping a big pretrain |
| P18 | T1 coverage (70%) | 72/75 | non-binding against the budget cap |

**72 of 75 jobs accepted, 22/22 hard constraints satisfied, OPTIMAL.**

### Comparison of weekly profiles

| profile        | accepted | total slack (h) | overrun past day 5 | fairness spread (‰) | power (MW·h) | operational summary |
|----------------|---------:|----------------:|-------------------:|--------------------:|-------------:|---------------------|
| throughput     | 72 | 3,284 | 3,216 | 1000 | 1.42 | accepts max, nobody's happy |
| **deadline_first** | **72** | **4,902** | **0** | 1000 | 1.35 | **recommended default** |
| fairness       | 72 | 4,866 | 3,216 |  270 | 1.39 | best for T5 student quota |
| green          | 17 | 541 | 576 | 1000 | **0.95** | too aggressive — needs $/kWh tuning |

### Why "deadline_first" wins

- **Same 72 accepts** as raw throughput
- **+50% deadline slack** (3,284 → 4,902 hours) — every accepted job has more
  room to absorb a delay without slipping
- **Zero jobs crossing the day-5 boundary** — gives ops a quiet weekend and a
  buffer window for emergency reruns
- **Comparable power draw** (1.35 MW·h, essentially unchanged)
- **All 22 HCs verified clean**

The tradeoff is a slight extra solver runtime (~90s vs. 45s for throughput)
because tight deadlines fragment the search space — still well under the
weekly planning SLA.

### Why "fairness" is worth a switch

Under the current queue T5 (student) already hits 100% and T4 (research)
is at 91.9%. The fairness profile's real win is tightening the
T1-vs-everyone-else gap: it pushes the best-to-worst team coverage spread
down to ~27 percentage points (from the unconstrained throughput baseline)
without costing a single accept. **Keep it as a manual override**, not
the default — if T5 grows a queue or T1's demand shrinks, the tradeoff
shifts and fairness may start costing throughput.

### Why "green" is not ready

Putting the raw watt-hour metric into the objective with weight 1 collapses
the schedule to 17 jobs. That's a **22% effective utilisation drop** for a
~33% power saving — not worth it at current electricity pricing. We need an
agreed $/kWh figure from ops to set the weight defensibly. Parked for v2.

## Three things to decide this week

1. **Adopt deadline_first as default?** Same accepts, better slack, cleaner
   weekend.
2. **Who approves a fairness-week override?** The fairness profile forces
   T5 above zero at T1's expense (staying within HC17). Is this a director
   call or can the ops lead trigger it?
3. **Fund a power budget study** for the green profile. Goal: a defensible
   $/kWh → SC3 weight mapping before Q3 planning.

## Limitations / honest caveats

- **No mid-job preemption in v1.** Real ML schedulers preempt low-priority
  jobs for high-priority arrivals; we model "accept or reject" only. See
  `spec.md` A5. v2 should add checkpoint-based preemption with a restart
  penalty term.
- **Arrival pattern is static.** We take a weekly snapshot of the queue and
  plan once. If jobs arrive mid-week with tight deadlines, the ops lead
  runs the solver again on the new snapshot; the solver takes ~3 minutes.
- **T1 coverage floor is 70% of demand, not 70% of budget** (A7). If T1
  submits a much larger queue next week, HC17 becomes infeasible. Guard
  rail: the assessor should re-run `opt-assess` before week 5.
- **No historical GPU throughput data.** We treat all H100s as equal; if
  real TFLOPS-effective varies by GPU, SC4 can be refined in v2.

## What comes next

- **v2 (4-6 weeks out):** add mid-job preemption + restart cost, wire
  realistic $/kWh for SC3, add historical utilisation data per GPU for
  smarter H100 selection.
- **v3 (quarterly):** rolling 2-week planning with arrival forecasting.
- **Deploy (separate proposal):** wire the scheduler into Slurm as a
  weekly-job planner; see `/opt-deploy` output (pending).

## Evidence files

All shipped under `v1/`:

- `spec.md` — the locked 22-HC + 8-SC rulebook
- `scripts/staged_baseline.py` — cascade + independent verifier
- `scripts/improve.py` — 4 SC scenarios
- `scripts/variants.py` — 5 director-facing profiles
- `results/baseline_results.json` — raw 19-phase cascade
- `results/improve_results.json` — raw scenario metrics + QA checklist
- `results/variants_results.json` — raw variant metrics
- `reports/baseline_report.md` / `improve_report.md` — full technical detail
