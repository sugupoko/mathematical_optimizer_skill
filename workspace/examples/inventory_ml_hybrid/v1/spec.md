# Spec v1 — Inventory Replenishment (ML + Optimization Hybrid)

**Project**: Weekly replenishment for a grocery retail chain
**Version**: v1 (baseline with ML forecast integration)
**Pattern**: ML forecast (RandomForest) → safety stock conversion → CP-SAT replenishment planning

---

## R1. Business goal

Plan next week's **order quantity, supplier choice, delivery day and truck assignment**
for 8 stores × 25 SKUs while (a) meeting a 95% per-SKU service level, (b) minimising
expected waste on perishables, (c) minimising transport cost and (d) respecting
physical store/truck/supplier constraints.

Demand is forecast from **2 years (146,000 rows) of daily POS sales** using a
machine-learning model. The ML output (point forecast + prediction std) feeds a
classical safety-stock formula which becomes the input to a CP-SAT optimiser.

## R2. Entities

- 8 stores (urban/suburban mix, distinct storage + refrigeration capacity)
- 25 SKUs across 5 categories: fresh produce, dairy, deli, packaged food, beverages
- 5 suppliers (lead time 1-3 days; 2 refrigerated fleets)
- 6 trucks (3 standard, 2 refrigerated, 1 small urban)
- 146,000 rows of daily POS history (2024-01-01 to 2025-12-30)

## R3. Decision variables

| Variable | Domain | Meaning |
|---|---|---|
| `order[s,k,d]` | int 0..max_order | cases ordered from SKU k by store s on day d |
| `ship[sup,s,d]` | bool | supplier `sup` ships to store `s` on day `d` |
| `trip[t,sup,d]` | bool | truck `t` serves supplier `sup` on day `d` |

Horizon = 7 days; orders with `d + lead_time >= 7` are fixed to 0.

## R4. Hard constraints (18)

| ID | Description |
|---|---|
| HC01 | Weekly order ≥ safety-stock requirement per (store, SKU) |
| HC02 | Weekly order ≤ 150% of requirement |
| HC03 | Daily order volume per store ≤ storage_capacity_m3 |
| HC04 | Refrigerated SKU volume per store ≤ refrigeration_capacity_m3 |
| HC05 | Truck load ≤ truck capacity |
| HC06 | Refrigerated SKUs only on refrigerated trucks |
| HC07 | Orders in whole case multiples |
| HC08 | Each SKU maps to exactly one supplier |
| HC09 | Each truck at most 1 trip per day |
| HC10 | Delivery day = order day + lead_time (enforced by fixing out-of-range vars) |
| HC11 | Fresh-produce daily order ≤ 50% of store storage |
| HC12 | Minimum 1-day lead time (no same-day emergency) |
| HC13 | Refrigerated trucks required when supplier ships refrigerated goods |
| HC14 | Truck must be in the supplier's allowed list |
| HC15 | Used truck load ≥ 10% of capacity (threshold relaxed from 60% — see A3) |
| HC16 | SUP1 (fresh) and SUP4 (dry wholesale) cannot share the same truck |
| HC17 | Each store accepts ≤ 3 supplier deliveries per day |
| HC18 | (SUP1, SUP4) cannot deliver same day to same store (dock clash) |

## R5. Soft constraints (objective terms)

- **SC1** total cost (inventory + transport + waste + stockout)
- **SC2** perishable waste (overshoot on fresh/dairy/deli)
- **SC3** stockout risk (undershoot below 105% of requirement)
- **SC4** balance truck utilisation
- **SC5** prefer long-shelf-life SKUs for bulk
- **SC6** favour local suppliers
- **SC7** minimise truck trips
- **SC8** category-level service

4 scenarios explored: `cost_min`, `service_max`, `waste_min`, `balanced`.

## R6. ML pipeline

- **Model**: `sklearn.ensemble.RandomForestRegressor(n_estimators=50, max_depth=14, min_samples_leaf=5)`
- **Features**: dow, dom, month, is_weekend, is_holiday, is_promo, temperature_c,
  lag_1/7/14/28, roll_mean_7/28, store_idx, sku_idx (15 features)
- **Train**: 2024-01-01 .. max_date - 60 days (≈128,400 rows)
- **Validate**: last 60 days (≈12,000 rows) → MAPE, RMSE, bias, per-category
- **Forecast**: roll forward 7 days × 8 stores × 25 SKUs = 1,400 predictions
- **Prediction interval**: `±1.2816 × residual_std` (80% CI)

## Assumptions (A1-A8)

- **A1** Each SKU has a single supplier (no multi-sourcing in v1).
- **A2** Current stock proxy = `2 × mean_daily_demand` (2 days on hand when the week begins).
- **A3** HC15 minimum truck utilisation is **10%** not 60% — with 25 SKUs and 7-day
       horizon, 60% makes the problem infeasible for small suppliers (SUP2/SUP3 have
       <7 m³ weekly load, below 60% of any truck). 60% is a goal for a larger SKU set
       or a consolidated weekly delivery run.
- **A4** Lead time is deterministic (suppliers never miss SLA).
- **A5** Promo and holiday flags for the forecast week are set to 0 (no promos assumed).
       In production, the promo calendar would be fed in.
- **A6** Waste proxy only charges overshoot on perishables (fresh/dairy/deli);
       packaged food and beverages are treated as non-perishable within the week.
- **A7** Stockout cost = `1.5 × (retail - unit_cost) × units` to approximate lost
       margin plus goodwill penalty.
- **A8** Transport cost per trip ≈ 10,000 JPY (includes fixed + average km).

## Evaluation

- **Validation** (in-sample): overall MAPE 22.4%, RMSE 8.59, bias −0.24 (near zero).
- **Business evaluation** against real held-out last-7-day sales:
  - ML plan: total cost 10.44M, waste 1,045 units, stockout 2,486 units, SL 66%.
  - Naive plan: total cost 10.67M, waste 1,554 units, stockout 1,455 units, SL 79%.
  - **ML saves 224 k JPY/week (2.1%) by cutting perishable waste by 33%.**
