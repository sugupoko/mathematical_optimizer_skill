"""Four-scenario improvement over the staged baseline (ML forecast).

Scenarios:
    cost_min      - minimise (inventory + transport + stockout) strongly
    service_max   - push service level / safety stock the highest
    waste_min     - penalise overshoot on perishables
    balanced      - equal weights

Each scenario solves the same Phase10 model with a different objective and
reports the resulting cost, waste, service level and trip count.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections import defaultdict

import pandas as pd
from ortools.sat.python import cp_model

from staged_baseline import (
    PHASES, build_model, load_inputs, solve, status_name, verify_all_hcs,
)

HERE = os.path.abspath(os.path.dirname(__file__))
V1 = os.path.abspath(os.path.join(HERE, ".."))
DATA = os.path.join(V1, "data")
RESULTS = os.path.join(V1, "results")

ALL_HCS = {f"HC{i:02d}" for i in range(1, 19)}

SCENARIOS = {
    # weights on: (transport_trips, waste_penalty, stockout_penalty)
    "cost_min":    {"trips": 100, "waste": 10, "stockout": 50},
    "service_max": {"trips":  10, "waste":  5, "stockout": 500},
    "waste_min":   {"trips":  20, "waste":200, "stockout": 30},
    "balanced":    {"trips":  60, "waste": 60, "stockout": 60},
}


def build_and_solve(req, skus, stores, suppliers, trucks, weights):
    m, vars_ = build_model(req, skus, stores, suppliers, trucks, ALL_HCS)
    order = vars_["order"]
    trip = vars_["trip"]
    sku_info = vars_["sku_info"]
    req_map = vars_["req_map"]

    # trips count: sum of trip vars
    trips_total = sum(v for v in trip.values())

    # Waste proxy: overshoot on perishable categories (fresh, dairy, deli)
    # = sum(max(0, order_total - required_cases)) for perishables
    waste_terms = []
    for (s, k) in {(s, k) for (s, k, _d) in order.keys()}:
        cat = sku_info[k]["category"]
        if cat not in ("fresh_produce", "dairy", "deli"):
            continue
        req_cases = req_map.get((s, k), 0)
        tot = sum(order[(s, k, d)] for d in vars_["days"] if (s, k, d) in order)
        ov = m.NewIntVar(0, 200, f"ov_{s}_{k}")
        m.Add(ov >= tot - req_cases)
        waste_terms.append(ov)
    waste_total = sum(waste_terms) if waste_terms else 0

    # Stockout proxy: undershoot below 105% req (safety slack)
    stockout_terms = []
    for (s, k) in {(s, k) for (s, k, _d) in order.keys()}:
        req_cases = req_map.get((s, k), 0)
        target = max(req_cases, int(math.ceil(req_cases * 1.05)))
        tot = sum(order[(s, k, d)] for d in vars_["days"] if (s, k, d) in order)
        un = m.NewIntVar(0, 200, f"un_{s}_{k}")
        m.Add(un >= target - tot)
        stockout_terms.append(un)
    stockout_total = sum(stockout_terms) if stockout_terms else 0

    m.Minimize(weights["trips"] * trips_total +
               weights["waste"] * waste_total +
               weights["stockout"] * stockout_total)

    t0 = time.time()
    solver, status = solve(m, tl=30)
    dt = time.time() - t0
    return solver, status, vars_, dt


def extract_solution(solver, vars_):
    order = {k: solver.Value(v) for k, v in vars_["order"].items()}
    ship = {k: solver.Value(v) for k, v in vars_["ship"].items()}
    trip = {k: solver.Value(v) for k, v in vars_["trip"].items()}
    return order, ship, trip


def score(order: dict, trip: dict, vars_: dict) -> dict:
    sku_info = vars_["sku_info"]
    req_map = vars_["req_map"]
    skus = pd.read_csv(os.path.join(DATA, "skus.csv")).set_index("sku_id")

    total_cases = sum(order.values())
    total_trips = sum(trip.values())

    # Inventory cost = unit_cost * case_size * cases
    inv_cost = 0.0
    waste_units = 0
    stockout_units = 0
    for (s, k) in {(s, k) for (s, k, _d) in order.keys()}:
        tot = sum(order.get((s, k, d), 0) for d in vars_["days"])
        req = req_map.get((s, k), 0)
        inv_cost += tot * skus.loc[k, "case_size"] * skus.loc[k, "unit_cost"]
        cat = sku_info[k]["category"]
        if cat in ("fresh_produce", "dairy", "deli"):
            waste_units += max(0, tot - req) * skus.loc[k, "case_size"]
        stockout_units += max(0, int(math.ceil(req * 1.05)) - tot) * skus.loc[k, "case_size"]

    # Transport cost = trips * 10000 (rough)
    transport_cost = total_trips * 10000

    # Waste cost = waste_units * (0.5 * retail)
    waste_cost = 0.0
    for (s, k) in {(s, k) for (s, k, _d) in order.keys()}:
        tot = sum(order.get((s, k, d), 0) for d in vars_["days"])
        req = req_map.get((s, k), 0)
        cat = sku_info[k]["category"]
        if cat in ("fresh_produce", "dairy", "deli"):
            waste_cost += max(0, tot - req) * skus.loc[k, "case_size"] * skus.loc[k, "unit_cost"] * 0.5

    stockout_cost = stockout_units * 400  # rough retail margin lost

    total_cost = inv_cost + transport_cost + waste_cost + stockout_cost
    # Service level: fraction of (s,k) where order >= req
    pairs = {(s, k) for (s, k, _d) in order.keys()}
    met = sum(1 for (s, k) in pairs
              if sum(order.get((s, k, d), 0) for d in vars_["days"]) >= req_map.get((s, k), 0))
    service_level = met / max(1, len(pairs))

    return {
        "total_cases": int(total_cases),
        "total_trips": int(total_trips),
        "inventory_cost": round(inv_cost, 0),
        "transport_cost": round(transport_cost, 0),
        "waste_cost":     round(waste_cost, 0),
        "stockout_cost":  round(stockout_cost, 0),
        "total_cost":     round(total_cost, 0),
        "waste_units":    int(waste_units),
        "stockout_units": int(stockout_units),
        "service_level":  round(service_level, 4),
    }


def main() -> None:
    req, skus, stores, suppliers, trucks = load_inputs(
        os.path.join(RESULTS, "order_requirements.csv"))

    summary = {}
    for name, w in SCENARIOS.items():
        print(f"\n--- scenario: {name} weights={w}")
        solver, status, vars_, dt = build_and_solve(req, skus, stores, suppliers, trucks, w)
        sname = status_name(status)
        print(f"    status={sname}  time={dt:.1f}s  obj={solver.ObjectiveValue() if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None}")
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            order, ship, trip = extract_solution(solver, vars_)
            ver = verify_all_hcs(vars_, order, ship, trip, ALL_HCS)
            sc = score(order, trip, vars_)
            sc["status"] = sname
            sc["solve_time_s"] = round(dt, 2)
            sc["objective"] = float(solver.ObjectiveValue())
            sc["active_violations"] = sum(ver["active"].values())
            summary[name] = sc
            print(f"    score: {sc}")
        else:
            summary[name] = {"status": sname}

    with open(os.path.join(RESULTS, "improve_results.json"), "w") as f:
        json.dump(summary, f, indent=2, default=float)
    print("\n[improve] saved results/improve_results.json")


if __name__ == "__main__":
    main()
