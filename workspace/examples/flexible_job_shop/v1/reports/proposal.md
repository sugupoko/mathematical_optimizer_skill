# Production Schedule Optimisation — Proposal for Manufacturing Director

**Audience**: Manufacturing director, production planner, shop-floor supervisor
**Scope**: 5 working days, 15 machines, 12 operators, 40 jobs (~249 operations)
**Recommendation**: adopt the **balanced** weight profile as the weekly
planning default, with the **on_time** profile held in reserve for weeks
dominated by urgent orders.

## 1. What Changed vs. The Current Manual Plan

Today the planner writes the weekly schedule by hand in Excel, starting
with urgent jobs and filling in the rest. This typically yields a feasible
plan but leaves 15-25% of machine capacity idle mid-week and creates
day-end overruns on CNC and grinding when T03/T05 tools collide.

The v1 optimiser:

1. Formalises 20 hard constraints (HC1-HC20) into a CP-SAT model so that
   maintenance windows, operator off-days, tool quantity and precedence
   cannot silently drift.
2. Runs 4 scenarios (balanced / throughput / on_time / smooth) against
   the same HC set, so the director can **see the trade-off curve**
   instead of taking a single plan on faith.
3. Produces a fully scheduled week (minute-level start/end per op,
   machine, operator) that can be dropped straight into the shop-floor
   dispatcher.

## 2. Recommended Profile: `balanced`

Weights: `3·makespan + 5·tardiness + 1·m_balance + 1·setup + 1·o_balance + 1·prio_early`

Why balanced:

- **Tardiness penalty (×5)** keeps urgent/high jobs inside their due days.
- **Makespan (×3)** pulls the week tight but does not dominate.
- Small balance / setup weights prevent pathological "one machine does all
  the work, the rest idle" solutions.

All other scenarios and variants are available as alternatives — see
`reports/improve_report.md` for the head-to-head.

## 3. What The Director Is Asked To Decide

1. **Approve the balanced profile** as the weekly default (or point at an
   alternative).
2. **Confirm the 6 assessment questions** in `reports/assess_report.md`.
   The most load-bearing ones are (a) single shift vs 2-shift, (b) accept
   HC8 approximated via HC20, and (c) weekly operator cap vs strict daily.
3. **Approve a 1-week pilot**: run the optimiser on next week's backlog,
   publish the optimiser plan alongside the manual plan, and compare
   on-time %, total setup count, and machine utilisation after the week.

## 4. Known Limitations (v1)

- **Sequence-dependent setup time is approximated**. If the real setup
  variance between op_types is > 25 min, v2 should model explicit setup
  intervals.
- **Operator daily cap** is enforced as a weekly budget (A4). If daily
  fatigue / HR rules require strict per-day caps, that is a tightening
  that shrinks the feasible region and will be done in v2.
- **No rework / scrap handling** — every op is assumed to finish correctly
  the first time.

## 5. Next Steps After Approval

- `/opt-deploy` the balanced profile: wrap it in a runbook, add a Monday
  08:00 trigger, attach the HC verifier as a gate, define a manual
  fallback if the solver returns INFEASIBLE.
- Instrument on-time % and setup-count KPIs; review after the first pilot
  week to decide v2 priorities.
