# Improve Report — GPU Cluster Scheduling v1

## Objective assembly

The baseline maximises priority-weighted throughput. `improve.py` replaces
that with a composite over 8 SCs:

```
minimise   - w1 * SC1_accepts
           - w2 * SC2_tier_weighted
           + w3 * SC3_power
           + w4 * SC4_non_H100_pretrain_hours
           + w5 * SC5_fairness_spread
           - w6 * SC6_total_slack
           + w7 * SC7_cross_zone   (structurally 0)
           + w8 * SC8_overrun_after_120h
```

Metric definitions are in `spec.md` § SCs and in the docstring of
`scripts/improve.py::build_with_objective`.

## Four scenarios

| scenario | w1 | w2 | w3 | w4 | w5 | w6 | w7 | w8 | intent |
|----------|----|----|----|----|----|----|----|----|--------|
| throughput    | 10 | 5  | 0 | 0  | 0  | 0 | 0 | 0 | raw job count |
| deadline_first| 5  | 10 | 0 | 0  | 0  | 3 | 0 | 2 | slack + tier |
| fairness      | 5  | 2  | 0 | 0  | 20 | 1 | 0 | 0 | equalise team coverage |
| green         | 3  | 2  | 1 | 10 | 0  | 0 | 0 | 0 | minimise power |

## Results

All four scenarios return OPTIMAL or FEASIBLE with **22/22 HCs verified**.

| scenario | accepted | sc3_power | sc4_non_H100_pretrain_h | sc5_spread (‰) | sc6_slack | sc8_overrun |
|----------|----------|-----------|-------------------------|----------------|-----------|-------------|
| throughput     | 72 | 1,424,020 W·h | 312 | 1000 | 3,284 | 3,216 |
| deadline_first | 72 | 1,353,860 W·h | 240 | 1000 | 4,902 | **0** |
| fairness       | 72 | 1,390,020 W·h | 312 | **270** | 4,866 | 3,216 |
| green          | **17** | **945,020 W·h** | 216 | 1000 | 541 | 576 |

### Interpretation

- **throughput**: default baseline behaviour. 72 accepts (the HC16+HC14+HC12
  frontier from the baseline run). No attempt to smooth out power or
  deadline slack. SC5 spread value is uninformative here because weight=0
  lets the solver leave the auxiliary bounds loose.
- **deadline_first**: same 72 accepts, but every accepted job now finishes
  within its first-5-day window (sc8_overrun = 0) and total slack jumps
  from 3,284 to 4,902 hours. This is the **defensible operational default**
  — it costs nothing on throughput.
- **fairness**: when SC5 is actually weighted, the spread tightens to ~270‰
  (27 percentage points between best- and worst-served teams). Under the
  current job mix T5 is already at 100% so the fairness scenario rescues
  T1's coverage ratio (73%) into the tighter end of the distribution,
  which is the intended T1-vs-rest trade. This is the best profile if
  you want to advertise "nobody under-served" to leadership.
- **green**: aggressive raw-watts minimisation collapses to 17 accepts
  because SC3 weight-1 on ~1.4 million watt-hours dominates everything.
  **Every non-T1 team drops to 0% coverage** (T6 stays at 100% because of
  HC21). This is the cost of naively adding power to the objective without
  rescaling. The director conversation around this number is: "what
  dollar-per-watt equivalent do you want?"

## Team coverage breakdown (throughput scenario)

```
T1 foundation_models  1,688 / 2,312 gph  (73.0%)  — close to HC17 floor (70%)
T2 fine_tuning          598 /   598 gph  (100.0%)
T3 inference_bench      109 /   109 gph  (100.0%)
T4 research_exp         136 /   148 gph  (91.9%)  — 1 research job rejected
T5 student               21 /    21 gph  (100.0%)
T6 infra_debug            6 /     6 gph  (100.0%)  — HC21 guaranteed
```

Under **deadline_first** T1 drops to 70.9% (still above HC17 floor) because
the solver had to rearrange for slack. Under **green** every non-T1/T6 team
collapses to 0%.

## QA checklist (spec <-> code)

Run automatically at end of `improve.py`:

- [x] All 22 HCs verified by independent checker for every scenario
- [x] T6 coverage = 100% in every scenario (HC21)
- [x] T1 coverage >= 70% in every scenario (HC17)
- [x] No deadline violations (HC14)
- [x] No power / cooling violations (HC8, HC9)
- [x] No license oversubscription (HC10)
- [x] `baseline_results.json` phase table matches `spec.md` HC count (22)
- [x] `improve_results.json[qa_issues] == []`

Open items flagged for manual review:

- SC7 is structurally zero under current HC set (HC6 + HC7 already force
  same-zone placement). Kept in the objective as documentation; will
  become live if v2 allows cross-zone IB.
- SC3 power weights need real $-per-kWh anchoring before director meeting.
- Fairness metric uses `max - min` across teams; could switch to variance
  or Jain's index in v2 if the director prefers.

## Variant sweep (`variants.py`)

Five director-facing profiles. All return FEASIBLE/OPTIMAL with HC_ok=22/22
and accepted counts per profile:

| profile | accepted | sc5_spread(‰) | sc6_slack | notes |
|---------|----------|---------------|-----------|-------|
| V1 director_default | 72 | varies | varies | balanced SC1+SC2+SC5+SC6 |
| V2 max_throughput | 72 | 1000 | 3,310 | pure throughput |
| V3 tier1_first | 72 | — | 4,905 | strong SC2 + SC4, SC6 |
| V4 green | 17 | — | — | same green collapse as improve |
| V5 fair_share | 72 | 270 | 4,860 | strongest SC5; T5 rescued |

See `results/variants_results.json` for full metric dump.

## Recommendation

Ship **deadline_first** as the weekly default (or V3 tier1_first if
leadership wants to emphasise T1's gold-tier contract). Keep the throughput
profile as a sanity baseline. Mark the green profile as "not production"
until a proper $-per-kWh conversion is agreed with ops.
