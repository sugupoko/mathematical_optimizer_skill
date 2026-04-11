# Spec — GPU Cluster Scheduling (v1)

**Status:** v1 initial draft, built from lab-provided cluster inventory + one
week of pending job queue. Locked before baseline run.

**Scale:**
- 6 nodes / 44 GPUs / 6 teams / 75 jobs / 3 licenses / 2 maintenance windows
- 168-hour (one-week) horizon
- Model size: ~4,166 decision variables, ~10,355 constraints (final phase)

## Source references (Ref)

- **R1**: `data/nodes.csv` — cluster inventory provided by infra team
- **R2**: `data/gpus.csv` — generated from nodes (8 GPU/node for N1–N5, 4 for N6)
- **R3**: `data/teams.csv` — quotas negotiated at quarterly capacity review
- **R4**: `data/jobs.csv` — weekly job queue snapshot from the scheduler
- **R5**: `data/licenses.csv` — procurement database
- **R6**: `data/maintenance.csv` — planned maintenance calendar

## Scope & decisions

The scheduler decides, for each job in the 1-week queue:

1. **accept / reject** — can we run this job this week at all?
2. **start hour** — integer 0..168-duration
3. **GPU assignment** — exactly `gpus_required` GPUs, pinned at start

**Explicit simplification:** we do *not* model mid-job preemption in v1. A job
either runs contiguously start-to-start+duration or is rejected. See A5.

## Hard constraints (22)

| id  | description | source |
|-----|-------------|--------|
| HC1 | each accepted job runs for exactly `hours_required` contiguous hours | R4 |
| HC2 | each accepted job uses exactly `gpus_required` GPUs | R4 |
| HC3 | GPU memory per allocated GPU >= `min_gpu_memory_gb` | R4, R2 |
| HC4 | a GPU runs at most 1 job at a time (no oversubscription) | operational policy |
| HC5 | gang scheduling — all N GPUs of a multi-GPU job share the same start | R4 (distributed-training req.) |
| HC6 | multi-GPU jobs stay on a single node unless `needs_infiniband=True` | R1 interconnect topology |
| HC7 | InfiniBand-required jobs run only on nodes whose `interconnect` contains "InfiniBand" | R1 |
| HC8 | per-node power budget not exceeded at any instant (sum of `peak_watts` + idle baseline) | R1 `power_budget_watts` |
| HC9 | cooling zone A supports <=24 active GPUs simultaneously; zone B <=12 | facilities team |
| HC10 | license seats respected: CUDA-advanced 20, NCCL-pro 8 (distributed only) | R5 |
| HC11 | per-team `max_gpus_at_once` not exceeded at any hour | R3 |
| HC12 | per-team weekly budget `max_concurrent_gpu_hours` not exceeded | R3 |
| HC13 | per-team `allowed_nodes` whitelist respected | R3 |
| HC14 | job completion time <= `deadline_hour` | R4 (paper/experiment deadlines) |
| HC15 | no job on a node during that node's maintenance window | R6 |
| HC16 | dataset locality — if `dataset_cached_node` is set, job runs only there | R4 |
| HC17 | tier-1 (T1 foundation models) served >= 70% of its demanded gpu-hours | charter |
| HC18 | non-preemptable jobs are not interrupted (automatic under the "contiguous" model) | R4 `preemptable` |
| HC19 | min run duration 1 hour (no sub-hour thrashing) | operational policy |
| HC20 | V100 cannot run jobs requiring > 16 GB memory | R2, R4 |
| HC21 | T6 (infrastructure/debug) must have all its jobs scheduled | charter |
| HC22 | pretrain jobs must run on H100 or A100-80GB only | R4 `job_type`, R2 |

### How they are enforced

- **Static-pruning only**: HC1 (fixed-size intervals), HC3 (data-level compat
  filter — memory cannot physically change), HC5 (shared `start[j]` integer
  var across GPUs of the same job), HC18 (no preemption by modelling choice),
  HC19 (smallest hours_required is 1).
- **Solver constraint**: every other HC is enforced by CP-SAT. This is what
  lets the staged baseline cascade isolate which HC is the infeasibility
  culprit.

## Soft constraints (SCs)

| id  | description |
|-----|-------------|
| SC1 | maximise total jobs scheduled (throughput) |
| SC2 | prefer higher-tier teams (T1 > T2 > T3 > T4 > T5, T6 guaranteed) |
| SC3 | minimise total power consumption (kWh) |
| SC4 | prefer H100 for pretrain (don't waste premium HW; penalty for pretrain on A100-80GB) |
| SC5 | balance load across teams (fairness: minimise max–min coverage% spread) |
| SC6 | meet deadlines with slack (maximise sum of `deadline - end` over accepted jobs) |
| SC7 | minimise cross cooling-zone usage (always zero under HC6+HC7, tracked for honesty) |
| SC8 | prefer completion within first 5 days (120h), leaving buffer for emergencies |

## Assumptions (A)

- **A1**: The 168-hour horizon starts at hour 0 = Monday 00:00. All times are
  in cluster-local time. Deadlines are hours-from-horizon-start.
- **A2**: Power budget is per node and applies instantaneously. We charge
  each running GPU `peak_watts - idle_watts` during its interval and a fixed
  `idle_watts` baseline for the whole horizon (baked into HC8 headroom).
  This slightly under-reports power for partially idle GPUs but is a sound
  upper bound on peak demand.
- **A3**: Cooling zone limits are expressed as "simultaneously-active GPUs"
  counts (24 in A, 12 in B), not watts. This is a facility-team simplification
  of a nonlinear thermal model. Reasonable because GPUs at full load dominate.
- **A4**: License CUDA-advanced counts 1 seat *per job* (not per GPU), NCCL-pro
  counts 1 seat per distributed (gpus_required > 1) job. Seats are released
  at job end.
- **A5**: v1 does NOT model preemption. Real production ML schedulers preempt
  low-priority jobs for high-priority ones; v2 will add checkpoint-based
  preemption with a restart penalty. Confirmed with infra lead 2026-04-03.
- **A6**: Dataset locality (HC16) is hard: if the dataset isn't cached on the
  node, the job must be rejected rather than staged-with-delay. v2 could add
  a "stage-in" phase with a transfer-time surcharge.
- **A7**: HC17 threshold is 70% of T1's *demand*, not 70% of its budget. T1's
  budget (1700 gph) is slightly above 70% of demand (2312 * 0.7 = 1618) so
  the constraint is feasible; if T1 submits a larger queue next week, this
  must be rechecked.
- **A8**: The HC9 zone-A limit of 24 concurrent GPUs assumes all GPUs in zone A
  are equally demanding thermally. Realistic because zone A hosts 16 H100 +
  16 A100-80GB. Note 32 GPUs in zone A total > 24 limit → HC9 is load-bearing.

## Known tradeoffs / tensions

- **HC8 vs throughput**: node N1/N2 power budgets (6000W) can fit only
  ~7 H100s at full peak (8*700 + 8*70 = 5600W + idle = OK), so a single 8-GPU
  pretrain is feasible but two concurrent 4-GPU jobs on one node also fit.
- **HC12 vs HC17**: T1 budget (1700 gph) is tight against its demand (2312).
  At 70% coverage, other SCs have limited maneuvering room for T1.
- **HC9 vs HC22**: pretrain-on-premium (HC22) keeps pretrain in zone A; HC9
  caps zone A at 24. If many distributed pretrains run in parallel, we hit
  HC9 before HC8.
