# Hospital OR Weekly Schedule — Proposal for Director

**To**: Hospital Director, OR Manager, Chief of Surgery
**From**: Optimization team
**Date**: 2026-04-11
**Status**: v1 — proposal for approval

## Executive summary

We can schedule **49 of 50 backlogged patients** this week while respecting all
22 clinical hard constraints (specialty, equipment, ICU capacity, staff limits,
urgency windows, surgeon preference). The mathematical model is **feasible**,
**verified independently**, and **optimal** under the recommended "balanced"
objective profile.

- **All urgent cases scheduled within their clinical window.**
- **All semi-urgent cases scheduled before day 3.**
- **ICU bed capacity (4–6/day) respected every day.**
- **Cardiac cases routed exclusively to OR1 (bypass-equipped).**
- **Pediatric cases routed to OR5/OR6 with pediatric-qualified anesthesia and nursing.**

The one unscheduled elective can be accommodated by either
(a) picking the "coverage" profile at the cost of higher surgeon workload spread,
or (b) deferring to next week.

## What we optimised over

| # | Soft goal | Priority | Achieved under "balanced" |
|---|---|---|---|
| SC1 | Maximise scheduled patients | High | 49/50 (98%) |
| SC2 | Surgeon workload fairness | Medium | 375 min spread (~1 half-day) |
| SC3 | OR utilisation balance | Medium | max 300 min/OR/day |
| SC5 | Cleaning overhead | Low | minimised indirectly |
| SC6 | Requested surgeon honoured | High | 100% (enforced hard) |
| SC7 | Semi-urgent early | High | all ≤ day 3 |
| SC8 | Pediatric rooms reserved | Medium | 5 non-ped cases in OR5/OR6 |

## Alternative profiles considered

| Profile | Schedules | Surgeon spread | Recommended? |
|---|---|---|---|
| **balanced (default)** | **49** | **375 min** | **yes** |
| coverage | 50 | 815 min | only if 1 extra patient outweighs surgeon load |
| fairness | 34 | 175 min | no — loses 15 patients |
| efficiency | 49 | 470 min | acceptable alternative |

## Risks and mitigations

1. **Surgeon cap S01 (cardiac)** — 4 patients request S01, totalling ~1170 min
   against a 2100 min weekly cap. Mitigation: S02 covers overflow P02 (valve).
2. **ICU day-2 bottleneck** — 4 beds vs 4 ICU-needing cases. Mitigation: model
   moves one case to day 1 or 3 automatically.
3. **Pediatric anesthesia thin** — only 4 qualified; if 2 call in sick the plan
   degrades. **Recommendation**: escalation SOP to certify a 5th pediatric anesthetist.

## What we need from management

1. **Approve the "balanced" profile** for weekly use.
2. **Confirm HC22 (requested surgeon) is truly hard**, or allow soft deviation;
   soft treatment would give 100% coverage without surgeon spread penalty.
3. **Greenlight pediatric-anesthesia cross-training** to reduce the thinnest pool.
4. **Weekly re-run approval** — once deployed, this script can produce next
   week's schedule from a refreshed `patients.csv` in under 2 minutes.

## Ask

> **May we proceed to `/opt-deploy` and productionise the balanced profile
> schedule as the official weekly plan starting next Monday?**
