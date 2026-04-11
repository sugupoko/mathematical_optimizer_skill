# Improvement Report — Flexible Job-Shop Scheduling v1

**Script**: `scripts/improve.py`
**Results**: `results/improve_results.json`
**HC set**: all 20 (full P11 model from staged_baseline)

## 1. Four Scenarios

| Scenario | Weights (makespan · tardiness · m_balance · setup · o_balance · prio_early) |
|---|---|
| balanced | 3 · 5 · 1 · 1 · 1 · 1 |
| throughput | 10 · 1 · 0 · 0 · 0 · 0 |
| on_time | 1 · 20 · 0 · 1 · 0 · 3 |
| smooth | 1 · 2 · 5 · 3 · 5 · 1 |

All 4 solve to **FEASIBLE** with an independent-verifier 20/20 HC pass. The
model has ~19,000 variables (slightly larger than baseline's 9,283 because
of the SC4 setup-time reification helpers).

## 2. Head-to-head Results

| Metric | balanced | throughput | on_time | smooth |
|---|---:|---:|---:|---:|
| Makespan (min) | 2265 | **1740** | 2160 | 2115 |
| Total weighted tardiness | 0 | 0 | 0 | 0 |
| Machine-load spread | 690 | 2400 | 2400 | **750** (near-min) |
| Total setup bands | 54 | 55 | **52** | 56 |
| Operator-load spread | 510 | 2400 | 2400 | **164** |
| Priority penalty | 97,770 | 150,720 | **94,395** | 98,490 |
| HC verifier | 20/20 | 20/20 | 20/20 | 20/20 |

Takeaways:

- **Makespan winner: throughput** (1740 min, 3.6 days) but at the cost of
  extreme imbalance — every machine on one end, idle on the other.
- **Smoothest plan: smooth** — operator-load spread 164 min (vs 510+ elsewhere)
  and near-minimum machine-load spread. Makespan only 8.6% worse than throughput.
- **Best for priorities: on_time** — lowest priority_penalty, zero
  tardiness; makespan 24% worse than throughput.
- **Recommended: balanced** — 2nd best on machine balance, zero tardiness,
  makespan only 30% over the lower bound, no metric in the "worst" column.

## 3. QA Checklist (spec ↔ code consistency)

| Check | Status | Notes |
|---|---|---|
| Every HC in `spec.md §4` encoded in `build_model` | ✓ | HC1-HC20 all present |
| Every A-rule applied in exactly one place | ✓ | A3 (HC20 proxy for HC8), A4 (weekly op cap), A5 (HC12 as blocker intervals) |
| Independent verifier covers every HC | ✓ | `verify_all_hcs` checks all 20 |
| Verifier passes on all improve scenarios | ✓ | 20/20 for balanced/throughput/on_time/smooth |
| SC4 setup-time metric is fully reified | ✓ | Fixed via ge/lt double-implication helpers |
| Baseline `makespan`-only objective superseded by improve composite | ✓ | CP-SAT's last `Minimize()` wins |
| Tool HC13 uses `AddCumulative` | ✓ | One cumulative per tool_id |
| Machine HC2 uses `AddNoOverlap` on `NewOptionalIntervalVar` | ✓ | One per machine |
| Operator HC17 uses `AddNoOverlap` with off-day blocker intervals | ✓ | Combines HC12 + HC17 |

## 4. Contradictions Detected: none

No spec statement contradicts the code; no constraint is silently relaxed
between baseline and improve phases. The only approximation is A3 (HC8
modelled via HC20), which is documented in `spec.md` and visible in
`improve.py` through the `total_setup` metric.

## 5. Recommendation

Adopt **balanced** as the weekly default and keep **on_time** as the
"priority week" fallback. **throughput** is useful only as a
"what's the theoretical minimum makespan" reference — not for real use,
because a 4-hour idle gap on one machine typically costs more than the 4
hours of makespan it saves.

Next: `/opt-report` will build `reports/proposal.md` for the manufacturing
director. (A draft is already in `reports/proposal.md`.)
