# Flexible Job-Shop Scheduling (FJSP) — v1 Specification

**Project**: flexible_job_shop
**Version**: v1 (initial)
**Date**: 2026-04-11
**Audience**: Manufacturing director, production planner, shop-floor supervisor

## 1. Business Context

A metal-parts manufacturer runs a 15-machine shop across 5 working days
(Mon-Fri, single 8-hour shift = 480 min/day). 40 production orders (jobs),
each with 4-8 sequential operations, must be routed onto machines, assigned
to operators, and fitted around maintenance, tooling and due-date constraints.

This is a **Flexible Job-Shop Scheduling Problem (FJSP)**: each operation has
a set of eligible machines rather than a single fixed machine, and machines
share tooling and operator resources.

## 2. Sources (Ref Traceability)

- **R1**: `data/machines.csv` — 15 machines, 5 types (lathe/milling/drilling/grinding/cnc)
- **R2**: `data/operators.csv` — 12 multi-skilled operators, 8h/day cap
- **R3**: `data/jobs.csv` — 40 jobs, 4 priority tiers, due-day & earliest-start
- **R4**: `data/operations.csv` — 227 operations with eligible-machine lists, durations, tools
- **R5**: `data/tools.csv` — 5 shared tools with limited quantity (T03 and T05 are singletons)
- **R6**: `data/constraints.csv` — 20 HCs / 6 SCs catalogue

## 3. Decision Variables

Core CP-SAT variables (see `scripts/staged_baseline.py::build_model`):

| Variable | Domain | Meaning |
|---|---|---|
| `pres[op,m]` | {0,1} | Operation `op` is run on machine `m` |
| `start[op,m]` | int, [0, 2400] | Start minute (across whole week) if presence true |
| `end[op,m]` | int, [0, 2400] | End minute |
| `interval[op,m]` | OptionalInterval | Built by `NewOptionalIntervalVar` — feeds `AddNoOverlap` |
| `op_start[op]`, `op_end[op]` | int | Realised start/end of the op across whichever machine was chosen |
| `op_op[op,operator]` | {0,1} | Operator assignment (1 operator per op) |
| `makespan` | int | Max of all `op_end` (objective) |

**Actual variable counts** (from `model.Proto()` after the run):

| Phase | Vars | Constraints | Note |
|---|---:|---:|---|
| P01 (HC1/2/4/18) | 2,318 | 2,332 | Core assignment + no-overlap |
| P08 (+operator core) | 5,803 | 6,099 | `op_op[op,operator]` added |
| P10/P11 (all 20 HCs) | **9,283** | **21,721** | HC20 type indicators dominate |
| improve.py (full SC) | **19,086** | — | SC4 full-reification helpers |

## 4. Hard Constraints (20) — see `data/constraints.csv`

| # | HC | Summary |
|---|---|---|
| HC1 | exactly-one-machine | Each op chosen on exactly one eligible machine |
| HC2 | no-overlap | `AddNoOverlap` per machine |
| HC3 | precedence | `op_start[seq+1] >= op_end[seq]` within job |
| HC4 | duration match | Enforced by `NewOptionalIntervalVar(size=dur)` |
| HC5 | fit-in-day | Each op lies entirely within one 8-hour day |
| HC6 | maintenance | Maintenance windows blocked on each machine |
| HC7 | machine off-days | `unavailable_days` blocked |
| HC8 | setup-dependent time | Simplified via HC20 (A3) |
| HC9 | operator required | Op must have 1 operator assigned when scheduled |
| HC10 | skill match | Operator's `skills` must include op_type |
| HC11 | operator daily cap | Weekly aggregate: `total <= max_daily * available_days` (A4) |
| HC12 | operator off-days | Modelled as fixed "blocker" intervals in HC17 no-overlap |
| HC13 | tool availability | `AddCumulative` per tool |
| HC14 | due day | All ops of job end by `due_day * 480` |
| HC15 | earliest start day | All ops start at or after `earliest_start_day` |
| HC16 | cross-day precedence | Subsumed by HC3 |
| HC17 | operator non-overlap | `AddNoOverlap` on per-operator op intervals |
| HC18 | type compatibility | `op_type` must match `machine.type` |
| HC19 | urgent ≤ day 2 | Urgent jobs finish within first 2 days |
| HC20 | ≤1 type change/machine/day | At most 2 distinct op_types per (machine, day) |

## 5. Soft Objectives (6)

Weighted-sum minimisation (all terms minimised):

| # | SC | Expression |
|---|---|---|
| SC1 | makespan | `max(op_end)` |
| SC2 | total tardiness | `sum(priority_weight[j] * max(0, job_end[j]-due))` |
| SC3 | machine utilisation balance | `max(load_m) - min(load_m)` |
| SC4 | total setup | # (machine,day,op_type) bands used |
| SC5 | operator load balance | `max(load_op) - min(load_op)` |
| SC6 | priority-early | `sum(priority_weight[j] * job_end[j])` (penalise late big jobs) |

Default **balanced** profile: `3*SC1 + 5*SC2 + 1*SC3 + 1*SC4 + 1*SC5 + 1*SC6`.

## 6. A-rules (Documented Assumptions)

- **A1**: All operations are atomic; no in-operation preemption. A job's
  operations are strictly serial (fan-out routings are out of scope for v1).
- **A2**: HORIZON = 5 days × 480 min = 2400 min, single shift. Weekend /
  second shift are not modelled.
- **A3**: HC8 (setup-dependent time) is approximated by HC20 (max 1 op_type
  change per machine per day). No explicit sequence-dependent setup-time
  addition to each op's duration; this under-estimates wall-clock time by
  roughly 15-25 min per changeover. Will be tightened in v2 if real sequence
  data becomes available.
- **A4**: HC11 (operator daily cap) is enforced as a **weekly** aggregate
  (`max_daily * available_days`) rather than strictly per-day, to keep the
  model compact. A-4 under-counts if operators are forced into a single day
  by HC17's no-overlap — but combined with HC17 it still bounds wall-clock
  load reasonably.
- **A5**: HC12 (operator off-days) is implemented by adding a fixed
  full-day "blocker interval" to HC17's per-operator no-overlap. This
  requires HC12 and HC17 to move together; they do in our phase plan.
- **A6**: Tooling (HC13) is modelled via `AddCumulative`, assuming a tool is
  held for the full duration of the op. Tool changeover time between ops is
  ignored.

## 7. Hypothesised Tight Spots

1. **CNC** — only 1 machine of type `cnc`. Its 2400-min weekly cap is the
   binding resource. Data gen was tuned to stay below 2000 min of CNC load.
2. **Tool T03 & T05** — quantity 1 each. Any schedule that needs two CNC +
   T05 jobs to run at the same time is infeasible; `AddCumulative` forces
   serialisation.
3. **Urgent jobs × day-1 maintenance** — M13 grinding has a 0-60 maintenance
   window on day 1, and M01 lathe has a day-3 maintenance; urgent jobs
   (HC19) must finish by day 2, so they crowd day 1 lathes.
4. **Operator off-days** — O02/O05/O08/O11 each miss 1 day; operators with
   rare skills (cnc, grinding) being off creates tight chains.

## 8. Change Log

- v1: initial model. Phases P01-P11 in `staged_baseline.py`, improve
  scenarios in `improve.py`, variant sweep in `variants.py`.
