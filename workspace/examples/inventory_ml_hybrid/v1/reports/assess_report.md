# Assess Report — Inventory ML + Optimization Hybrid

## 1. Problem classification

- **Class**: Inventory Replenishment with Multi-echelon Routing (hybrid scheduling
  + transport). Demand is stochastic and forecast-driven.
- **Pattern**: *ML forecast → Optimization*. A point + uncertainty forecast becomes
  the right-hand side of the optimisation model.
- **Complexity**: Mid-scale. 200 (store, SKU) pairs × 7 days = 1,400 order slots,
  plus ~250 logistics variables (trips/ships). Fully tractable in CP-SAT.

## 2. Data profile

- **sales_history.csv**: **146,000 rows** (8 stores × 25 SKUs × 730 days)
- 2 years: 2024-01-01 .. 2025-12-30
- Mean units/day/store/SKU: 35.7
- Generated with: weekly seasonality, monthly drift, Japan holidays (New Year,
  Golden Week, Obon, Christmas), temperature effect on cold drinks, 8% random
  promos (+30% uplift), category-specific variance (fresh 35%, packaged 12%).

## 3. Initial hypotheses

| # | Hypothesis | How to test |
|---|---|---|
| H1 | Demand has strong weekly seasonality dominated by weekend effect | Feature importance of `dow` / `is_weekend` |
| H2 | Fresh produce dominates waste risk | Category-level MAPE + overshoot accounting |
| H3 | Refrigeration capacity is the binding store constraint, not storage | HC04 slack in baseline |
| H4 | Truck fleet is *not* binding (6 trucks × 7 days = 42 slots, we need ~15) | Phase-wise trip count |
| H5 | Naive 4-week average over-orders because it can't see weekday patterns | Raw MAPE ML vs naive |

## 4. Requested decisions

- What to order (cases per (store, SKU, day))
- Which supplier sends it (fixed by SKU master)
- Which delivery day (respecting lead time)
- Which truck carries it (respecting refrigeration + allowed list)

## 5. Known unknowns / assumptions to confirm (A1-A8 in spec.md)

- Current on-hand stock is estimated (A2). Real WMS feed would replace it.
- Promo calendar for the forecast week assumed empty (A5).
- Lead time deterministic (A4). Real suppliers have ~15% variance.
- HC15 relaxed from 60% to 10% (A3): needs approval from operations.

## 6. Next steps

1. `_generate_data.py` → produce masters + 146k sales history.
2. `forecast.py` → train RF, measure MAPE on 2-month validation, produce
   ML + naive forecasts for the next week.
3. `safety_stock.py` → Z=1.65 (95% SL), convert to required cases.
4. `staged_baseline.py` → 10-phase CP-SAT build; confirm all 18 HCs feasible.
5. `improve.py` → 4 objective-weighting scenarios.
6. `compare_naive_vs_ml.py` → business value of the ML step.
