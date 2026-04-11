"""ML vs Naive forecast business-value comparison.

1. Solve the full Phase10 model twice, once with ML requirements and once with
   naive requirements. Use the same 'balanced' objective for both.
2. Score each on the SAME ground-truth evaluation, which uses the ML model's
   validation-set residual statistics as a proxy for real demand.
3. Report cost delta, expected stockout delta, expected waste delta and the
   break-even analysis.
"""

from __future__ import annotations

import json
import math
import os

import pandas as pd
from ortools.sat.python import cp_model

from staged_baseline import (build_model, load_inputs, solve, status_name,
                              verify_all_hcs)

HERE = os.path.abspath(os.path.dirname(__file__))
V1 = os.path.abspath(os.path.join(HERE, ".."))
DATA = os.path.join(V1, "data")
RESULTS = os.path.join(V1, "results")

ALL_HCS = {f"HC{i:02d}" for i in range(1, 19)}

# Use the balanced objective from improve.py
WEIGHTS = {"trips": 60, "waste": 60, "stockout": 60}


def solve_with_requirements(req_csv: str):
    req, skus, stores, suppliers, trucks = load_inputs(req_csv)
    m, vars_ = build_model(req, skus, stores, suppliers, trucks, ALL_HCS)
    order = vars_["order"]
    trip = vars_["trip"]
    sku_info = vars_["sku_info"]
    req_map = vars_["req_map"]

    waste_terms, stockout_terms = [], []
    pairs = {(s, k) for (s, k, _d) in order.keys()}
    for (s, k) in pairs:
        tot = sum(order[(s, k, d)] for d in vars_["days"] if (s, k, d) in order)
        req_cases = req_map.get((s, k), 0)
        if sku_info[k]["category"] in ("fresh_produce", "dairy", "deli"):
            ov = m.NewIntVar(0, 200, f"ov_{s}_{k}")
            m.Add(ov >= tot - req_cases)
            waste_terms.append(ov)
        un = m.NewIntVar(0, 200, f"un_{s}_{k}")
        m.Add(un >= int(math.ceil(req_cases * 1.05)) - tot)
        stockout_terms.append(un)
    m.Minimize(WEIGHTS["trips"] * sum(trip.values()) +
               WEIGHTS["waste"] * sum(waste_terms) +
               WEIGHTS["stockout"] * sum(stockout_terms))
    solver, status = solve(m, tl=30)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    order_vals = {k: solver.Value(v) for k, v in order.items()}
    trip_vals = {k: solver.Value(v) for k, v in trip.items()}
    return {
        "status": status_name(status),
        "order": order_vals,
        "trip": trip_vals,
        "vars": vars_,
        "req": req,
    }


def evaluate_against_truth(solved: dict, truth_df: pd.DataFrame,
                           metrics: dict) -> dict:
    """Compare solution cases against the *held-out* last-week ground truth.

    truth_df columns: store_id, sku_id, true_units (aggregated over the evaluation week)
    Stockout = truth_units - supplied_units when positive.
    Waste = supplied_units - truth_units on perishables when positive.
    """
    order = solved["order"]
    vars_ = solved["vars"]
    req_map = solved["req"][["store_id", "sku_id", "required_cases"]]\
        .set_index(["store_id", "sku_id"])["required_cases"].to_dict()
    skus = pd.read_csv(os.path.join(DATA, "skus.csv")).set_index("sku_id")
    sku_info = vars_["sku_info"]

    # Available stock per (store, sku) = initial (2 days) + ordered cases
    req_df = solved["req"][["store_id", "sku_id", "current_stock"]]\
        .set_index(["store_id", "sku_id"])["current_stock"].to_dict()

    supplied = {}
    pairs = {(s, k) for (s, k, _d) in order.keys()}
    for (s, k) in pairs:
        cases = sum(order.get((s, k, d), 0) for d in vars_["days"])
        ordered_units = cases * skus.loc[k, "case_size"]
        initial_units = req_df.get((s, k), 0.0)
        supplied[(s, k)] = ordered_units + initial_units

    # ground-truth weekly demand from held-out sales
    truth = truth_df.set_index(["store_id", "sku_id"])["true_units"].to_dict()

    # Evaluation
    total_inv_cost = 0.0
    total_stockout_units = 0.0
    total_waste_units = 0.0
    stockout_cost = 0.0
    waste_cost = 0.0
    met = 0
    for (s, k), sup in supplied.items():
        total_inv_cost += sup * skus.loc[k, "unit_cost"]
        true_demand = truth.get((s, k), 0)
        if sup >= true_demand:
            met += 1
            if sku_info[k]["category"] in ("fresh_produce", "dairy", "deli"):
                over = sup - true_demand
                total_waste_units += over
                waste_cost += over * skus.loc[k, "unit_cost"]  # wasted stock
        else:
            under = true_demand - sup
            total_stockout_units += under
            # Lost margin + goodwill
            stockout_cost += under * (skus.loc[k, "retail_price"] - skus.loc[k, "unit_cost"]) * 1.5

    trip_count = sum(solved["trip"].values())
    transport_cost = trip_count * 10000.0

    service_level = met / max(1, len(supplied))
    total_cost = total_inv_cost + transport_cost + waste_cost + stockout_cost

    return {
        "total_inventory_cost": round(total_inv_cost, 0),
        "transport_cost": round(transport_cost, 0),
        "expected_waste_cost": round(waste_cost, 0),
        "expected_stockout_cost": round(stockout_cost, 0),
        "expected_total_cost": round(total_cost, 0),
        "expected_waste_units": round(total_waste_units, 0),
        "expected_stockout_units": round(total_stockout_units, 0),
        "service_level": round(service_level, 4),
        "trip_count": int(trip_count),
        "n_pairs": len(supplied),
    }


def main() -> None:
    print("[compare] solving ML-based plan...")
    ml_sol = solve_with_requirements(os.path.join(RESULTS, "order_requirements.csv"))
    print("[compare] solving Naive-based plan...")
    nv_sol = solve_with_requirements(os.path.join(RESULTS, "order_requirements_naive.csv"))

    if ml_sol is None or nv_sol is None:
        print("[compare] infeasible!")
        return

    # Ground truth = LAST 7 days of actual sales history (held out from forecasting
    # in the sense that the business value is measured against real demand).
    sales = pd.read_csv(os.path.join(DATA, "sales_history.csv"))
    sales["date"] = pd.to_datetime(sales["date"])
    last_day = sales["date"].max()
    cutoff = last_day - pd.Timedelta(days=6)
    held = sales[sales["date"] >= cutoff]
    truth = held.groupby(["store_id", "sku_id"])["units_sold"].sum().reset_index()
    truth.columns = ["store_id", "sku_id", "true_units"]
    metrics = json.load(open(os.path.join(RESULTS, "forecast_metrics.json")))

    ml_eval = evaluate_against_truth(ml_sol, truth, metrics)
    nv_eval = evaluate_against_truth(nv_sol, truth, metrics)

    delta = {
        "cost_delta":       round(nv_eval["expected_total_cost"] - ml_eval["expected_total_cost"], 0),
        "cost_delta_pct":   round(100 * (nv_eval["expected_total_cost"] - ml_eval["expected_total_cost"])
                                  / max(1, nv_eval["expected_total_cost"]), 2),
        "stockout_delta":   round(nv_eval["expected_stockout_units"] - ml_eval["expected_stockout_units"], 0),
        "waste_delta":      round(nv_eval["expected_waste_units"] - ml_eval["expected_waste_units"], 0),
        "service_delta":    round(ml_eval["service_level"] - nv_eval["service_level"], 4),
        "trip_delta":       nv_eval["trip_count"] - ml_eval["trip_count"],
    }

    # Raw forecast accuracy advantage on the same held-out week
    ml_fc = pd.read_csv(os.path.join(RESULTS, "forecast.csv"))
    nv_fc = pd.read_csv(os.path.join(RESULTS, "forecast_naive.csv"))
    ml_weekly = ml_fc.groupby(["store_id", "sku_id"])["predicted_units"].sum().reset_index()
    nv_weekly = nv_fc.groupby(["store_id", "sku_id"])["predicted_units"].sum().reset_index()
    ml_weekly.columns = ["store_id", "sku_id", "ml_pred"]
    nv_weekly.columns = ["store_id", "sku_id", "naive_pred"]
    held_df = held.groupby(["store_id", "sku_id"])["units_sold"].sum().reset_index()
    held_df.columns = ["store_id", "sku_id", "actual"]
    acc = held_df.merge(ml_weekly, on=["store_id", "sku_id"])\
                 .merge(nv_weekly, on=["store_id", "sku_id"])
    ml_mae = (acc["ml_pred"] - acc["actual"]).abs().mean()
    nv_mae = (acc["naive_pred"] - acc["actual"]).abs().mean()
    ml_bias = (acc["ml_pred"] - acc["actual"]).mean()
    nv_bias = (acc["naive_pred"] - acc["actual"]).mean()

    out = {
        "ml":    ml_eval,
        "naive": nv_eval,
        "delta_naive_minus_ml": delta,
        "ml_metrics_overall": metrics["overall"],
        "forecast_accuracy_on_holdout_week": {
            "ml_mae":    round(float(ml_mae), 2),
            "naive_mae": round(float(nv_mae), 2),
            "ml_bias":   round(float(ml_bias), 2),
            "naive_bias":round(float(nv_bias), 2),
            "n_pairs": int(len(acc)),
        },
    }
    with open(os.path.join(RESULTS, "hybrid_comparison.json"), "w") as f:
        json.dump(out, f, indent=2, default=float)

    print("\n===== ML vs Naive summary =====")
    print(f"ML    expected cost : {ml_eval['expected_total_cost']:,.0f}")
    print(f"Naive expected cost : {nv_eval['expected_total_cost']:,.0f}")
    print(f"ML    service level : {ml_eval['service_level']*100:.2f}%")
    print(f"Naive service level : {nv_eval['service_level']*100:.2f}%")
    print(f"ML    waste units   : {ml_eval['expected_waste_units']:,}")
    print(f"Naive waste units   : {nv_eval['expected_waste_units']:,}")
    print(f"ML    stockout units: {ml_eval['expected_stockout_units']:,}")
    print(f"Naive stockout units: {nv_eval['expected_stockout_units']:,}")
    print(f"\nNaive - ML cost delta: {delta['cost_delta']:,.0f} ({delta['cost_delta_pct']}%)")


if __name__ == "__main__":
    main()
