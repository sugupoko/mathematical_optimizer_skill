# Assess Report — GPU Cluster Scheduling v1

## Problem classification

- **Class:** shared-resource scheduling with gang constraints
- **Sub-class:** multi-resource bin-packing over time with topology awareness
- **Complexity:** **complex** (not "simple", not "hard" — below production HPC
  schedulers like Slurm or Borg but above a trivial greedy)
- **Similar patterns in the pack:** `flexible_job_shop` (intervals + no-overlap
  per resource), `hospital_or_scheduling` (room/team capacity over time),
  `vaccine_allocation` (tier-weighted allocation with budgets)

## Quick sizing

- 75 jobs × avg ~38 compatible GPUs = 2,848 (job, gpu) presence variables
- Plus 75 job-level starts/ends/accepts and cumulative helpers for power,
  cooling, licenses, per-team peaks
- Final-phase model: **4,166 vars / 10,355 constraints** (CP-SAT)
- Demand side: 3,194 gpu-hours vs cluster capacity 7,392 gpu-hours (43% raw
  utilisation if everything fit, but HC6/HC8/HC9/HC12/HC13/HC16/HC22 all bite
  before that)

## Hypotheses (to confirm with solver)

1. **HC12 (team weekly budgets) will drop ~2-3 T1 jobs** — T1 demand 2312 gph
   vs budget 1700. We expect at least one of J01 (8×60=480) or J02 (8×48=384)
   to be rejected.
2. **HC16 (dataset locality) is already a tight prune** — 9 jobs pin specific
   nodes; if those nodes are busy, no substitution possible.
3. **HC6 + HC7 interact**: distributed pretrain (8 GPU, needs_IB=True) can
   only run on N1/N2 (the IB-connected H100 nodes). That's 16 GPUs total, but
   gang-scheduled 8s only fit sequentially on each node → ~3 pretrains can
   occupy N1 through a week.
4. **HC9 zone A binding** — at any instant only 24 of the 32 zone-A GPUs can
   be full-peak active. For multi-GPU jobs this is very restrictive because
   8-GPU pretrains consume a third of the zone-A budget at once.
5. **HC22 "pretrain → premium" forces congestion on H100/A100-80GB**. The
   A100-40GB node (N5) sits mostly idle for pretrain; it hosts finetune and
   research.
6. **HC17 (T1 70% coverage) is likely the binding constraint on SC5 fairness.**
   The scheduler must reserve 1618 gph of premium GPUs for T1 before giving
   T2 a fair share.

## Six confirmation questions for the research director / infra lead

1. Is the 1-week horizon the right planning unit, or should we use a rolling
   8-hour window for short jobs and a daily window for pretrain?
2. Is HC17's "70% of demand" the right fairness guarantee for T1, or should
   it be "70% of budget" (simpler but looser)?
3. Can T6 debug jobs actually preempt anything if they arrive mid-week, or
   does HC21 only apply to jobs submitted before the schedule is published?
4. When `needs_infiniband=True` we restrict to N1/N2 (HC7). Is NVLink+Ethernet
   (N3/N4) acceptable as a fallback for *some* distributed training, with a
   throughput hit? (currently modelled as "no" → HC7 strict)
5. Is zone A's 24-GPU concurrent cap a facility-imposed limit or a watt-based
   limit that we're approximating? If watts, we should push it into HC8.
6. Our power baseline model (A2) charges idle watts always and peak only
   while running. Is that consistent with PDU billing, or does the lab use
   time-weighted average?

## Data quality flags

- `deadline_hour` for some research jobs is the full 168h — suggests "no real
  deadline, but don't slip into next week". Confirm interpretation.
- `dataset_cached_node` is only populated for ~20% of jobs. The rest assume
  network storage. Is that realistic or missing metadata?
- No GPU efficiency / utilisation rating in v1; we treat all H100s as equal.
  If the lab tracks per-GPU throughput (TFLOPS effective), v2 should use it
  in SC4.

## Recommended next step

Run staged baseline (`scripts/staged_baseline.py`). Expect OPTIMAL at each
phase; watch for the first phase where accepted count drops. That phase's
newly-activated HC is the binding one.
