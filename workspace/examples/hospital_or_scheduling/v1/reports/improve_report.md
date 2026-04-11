# Improvement Report — Hospital OR Scheduling v1

## Scenarios

Four weight profiles on the same full-HC model (all 22 HCs always active).

| Scenario | covered | surgeon_spread (min) | OR max (min) | non-ped in ped room | semi-urgent earliness | HC ok | Status |
|---|---|---|---|---|---|---|---|
| balanced   | 49/50 | 375 | 300 | 5 | 49 | 22/22 | OPTIMAL |
| coverage   | **50/50** | 815 | 410 | 0 | 50 | 22/22 | OPTIMAL |
| fairness   | 34/50 | **175** | 300 | 0 | 35 | 22/22 | OPTIMAL |
| efficiency | 49/50 | 470 | 300 | 5 | 49 | 22/22 | OPTIMAL |

(`surgeon_spread` = max − min minutes across surgeons actually used; lower is fairer.)

## Variant Sweep (variants.py)

| Profile | covered | HC_ok | Notes |
|---|---|---|---|
| V1_director_default | 49 | 22 | balanced, one elective dropped |
| V2_max_throughput | **50** | 22 | pure coverage — huge surgeon spread |
| V3_union_friendly | 32 | 22 | heavy fairness weight (15) — big coverage loss |
| V4_cost_min | 49 | 22 | penalises cleaning & ped-room leakage |
| V5_urgent_first | 49 | 22 | semi-urgent all scheduled by day 1–2 |

## Trade-off Curve (coverage vs fairness)

```
cov 50  |  V2, coverage
cov 49  |  balanced, V1, V4, V5, efficiency   <-- recommended operating point
cov 48  |
cov ... |
cov 34  |  fairness
cov 32  |  V3_union_friendly
```

Moving from "balanced" to "coverage" buys 1 additional patient (+2%) for a
**2.2× worse surgeon spread** (815 vs 375 min). Moving from "balanced" to
"fairness" saves 200 min of spread but **drops 15 patients** — a poor trade.

## QA Checklist (spec-code consistency)

- [x] HC1–HC22 encoded in `build_model`
- [x] HC16 absorbed into HC2 with `+30` cleaning — documented in spec A1
- [x] A2 nurse pool aggregation — documented and mirrored in verifier
- [x] A3 ICU 1-day occupancy — verifier checks only day of surgery
- [x] A5 HC22 treated as hard — verifier flags mismatches
- [x] A8 cardiac→OR1-only — enforced in HC8 block
- [x] Independent verifier re-runs on every scenario (not trusting solver flag)
- [x] All 4 scenarios return 22/22 HC_ok

## Recommendation

**Adopt the "balanced" profile** (or V5_urgent_first if semi-urgent earliness is
the top ministerial KPI). Coverage-only buys 1 patient at the cost of surgeon
burnout risk; fairness-first is unacceptable — 16 patients turned away when the
physical capacity exists.

If management accepts dropping 1 elective case to preserve surgeon fairness, the
balanced profile is the Pareto-optimal operating point. Otherwise pick
`coverage` for the one extra patient.

## Known residuals

- `non_ped_in_ped_room = 5` in balanced/efficiency — OR5/OR6 is still used by
  adult cases. Under `coverage` and `fairness` profiles this drops to 0, showing
  the model can reserve ped rooms when SC8 is weighted.
- Surgeon spread 375 min in balanced translates to ~1 extra half-day of
  operating for the busiest surgeon vs the quietest. Acceptable.
