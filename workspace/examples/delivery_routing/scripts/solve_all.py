#!/usr/bin/env python3
"""
Delivery Routing Optimization — Full Workflow
==============================================
1. Data analysis (demand vs capacity, distances, time windows)
2. Three baselines: Random, Nearest Neighbor, OR-Tools Routing
3. AM/PM split improvement when capacity is insufficient
4. Evaluation & JSON export
"""

import csv
import json
import math
import os
import random
import sys
import time
from datetime import datetime, timedelta
from copy import deepcopy

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SPEED_KMH = 30.0
ROAD_FACTOR = 1.3
DEPOT_DEPARTURE = "08:00"
SOLVER_TIME_LIMIT_S = 120

# ---------------------------------------------------------------------------
# Data Loading
# ---------------------------------------------------------------------------

def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_data():
    depot_rows = load_csv(os.path.join(DATA_DIR, "depot.csv"))
    depot = {
        "id": depot_rows[0]["id"],
        "name": depot_rows[0]["name"],
        "lat": float(depot_rows[0]["latitude"]),
        "lon": float(depot_rows[0]["longitude"]),
    }

    customers = []
    for r in load_csv(os.path.join(DATA_DIR, "customers.csv")):
        customers.append({
            "id": r["customer_id"],
            "name": r["name"],
            "lat": float(r["latitude"]),
            "lon": float(r["longitude"]),
            "demand": float(r["demand_kg"]),
            "tw_start": r["time_window_start"],
            "tw_end": r["time_window_end"],
            "service_min": int(r["service_time_min"]),
        })

    vehicles = []
    for r in load_csv(os.path.join(DATA_DIR, "vehicles.csv")):
        vehicles.append({
            "id": r["vehicle_id"],
            "capacity": float(r["capacity_kg"]),
            "max_hours": float(r["max_hours"]),
            "cost_per_km": float(r["cost_per_km"]),
        })

    return depot, customers, vehicles

# ---------------------------------------------------------------------------
# Haversine & Matrix
# ---------------------------------------------------------------------------

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def build_matrices(depot, customers):
    """Build distance & travel-time matrices.  Index 0 = depot."""
    nodes = [depot] + customers
    n = len(nodes)
    dist = [[0.0] * n for _ in range(n)]
    ttime = [[0.0] * n for _ in range(n)]  # minutes
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            d = haversine_km(nodes[i]["lat"], nodes[i]["lon"],
                             nodes[j]["lat"], nodes[j]["lon"]) * ROAD_FACTOR
            dist[i][j] = round(d, 2)
            ttime[i][j] = round(d / SPEED_KMH * 60, 2)  # minutes
    return dist, ttime

# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def hhmm_to_min(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def min_to_hhmm(m):
    return f"{int(m) // 60:02d}:{int(m) % 60:02d}"


DEPOT_DEPART_MIN = hhmm_to_min(DEPOT_DEPARTURE)

# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate_routes(routes, depot, customers, vehicles, dist, ttime):
    """
    routes: list of dicts {vehicle_idx, customer_indices}
    customer_indices are 0-based into customers list.
    Returns metrics dict.
    """
    total_dist = 0.0
    total_cost = 0.0
    tw_violations = 0
    cap_violations = 0
    visited = set()
    route_details = []

    for route in routes:
        vidx = route["vehicle_idx"]
        cids = route["customer_indices"]
        v = vehicles[vidx]
        load = sum(customers[ci]["demand"] for ci in cids)
        cap_viol = max(0, load - v["capacity"])
        if cap_viol > 0:
            cap_violations += 1

        # simulate drive
        cur_time = route.get("depart_min", DEPOT_DEPART_MIN)
        prev = 0  # depot index in matrix
        rdist = 0.0
        stops = []
        route_tw_violations = 0

        for ci in cids:
            mi = ci + 1  # matrix index (0 = depot)
            travel = ttime[prev][mi]
            arrive = cur_time + travel
            c = customers[ci]
            tw_s = hhmm_to_min(c["tw_start"])
            tw_e = hhmm_to_min(c["tw_end"])

            wait = max(0, tw_s - arrive)
            start_service = arrive + wait
            tw_viol = max(0, start_service - tw_e)
            if tw_viol > 0:
                route_tw_violations += 1

            depart = start_service + c["service_min"]
            rdist += dist[prev][mi]
            visited.add(ci)
            stops.append({
                "customer": c["id"],
                "name": c["name"],
                "arrive": min_to_hhmm(arrive),
                "start_service": min_to_hhmm(start_service),
                "depart": min_to_hhmm(depart),
                "tw_violated": tw_viol > 0,
                "tw_violation_min": round(tw_viol, 1),
            })
            prev = mi
            cur_time = depart

        # return to depot
        rdist += dist[prev][0]
        cur_time += ttime[prev][0]
        total_hours = (cur_time - route.get("depart_min", DEPOT_DEPART_MIN)) / 60

        tw_violations += route_tw_violations
        total_dist += rdist
        total_cost += rdist * v["cost_per_km"]

        route_details.append({
            "vehicle": v["id"],
            "load_kg": load,
            "capacity_kg": v["capacity"],
            "distance_km": round(rdist, 2),
            "duration_hours": round(total_hours, 2),
            "max_hours": v["max_hours"],
            "over_time": round(max(0, total_hours - v["max_hours"]), 2),
            "tw_violations": route_tw_violations,
            "cap_violation": cap_viol > 0,
            "stops": stops,
        })

    unvisited = [customers[i]["id"] for i in range(len(customers)) if i not in visited]

    return {
        "total_distance_km": round(total_dist, 2),
        "total_cost_yen": round(total_cost, 0),
        "tw_violations": tw_violations,
        "capacity_violations": cap_violations,
        "unvisited_count": len(unvisited),
        "unvisited": unvisited,
        "routes": route_details,
    }

# ---------------------------------------------------------------------------
# Baseline 1: Random Assignment
# ---------------------------------------------------------------------------

def random_baseline(customers, vehicles):
    random.seed(42)
    indices = list(range(len(customers)))
    random.shuffle(indices)
    n_v = len(vehicles)
    routes = [{"vehicle_idx": i, "customer_indices": []} for i in range(n_v)]
    for i, ci in enumerate(indices):
        routes[i % n_v]["customer_indices"].append(ci)
    return routes

# ---------------------------------------------------------------------------
# Baseline 2: Nearest Neighbor Greedy
# ---------------------------------------------------------------------------

def nearest_neighbor_baseline(customers, vehicles, dist):
    n_c = len(customers)
    assigned = [False] * n_c
    routes = []

    for vidx, v in enumerate(vehicles):
        route_cids = []
        load = 0.0
        cur_time = DEPOT_DEPART_MIN
        prev = 0  # depot matrix idx

        while True:
            best_ci = None
            best_dist = float("inf")
            for ci in range(n_c):
                if assigned[ci]:
                    continue
                c = customers[ci]
                if load + c["demand"] > v["capacity"]:
                    continue
                mi = ci + 1
                d = dist[prev][mi]
                if d < best_dist:
                    best_dist = d
                    best_ci = ci
            if best_ci is None:
                break
            assigned[best_ci] = True
            route_cids.append(best_ci)
            load += customers[best_ci]["demand"]
            mi = best_ci + 1
            travel_min = best_dist / SPEED_KMH * 60
            cur_time += travel_min + customers[best_ci]["service_min"]
            prev = mi

        routes.append({"vehicle_idx": vidx, "customer_indices": route_cids})

    return routes

# ---------------------------------------------------------------------------
# Baseline 3: OR-Tools Routing Solver
# ---------------------------------------------------------------------------

def ortools_solver(depot, customers, vehicles, dist, ttime, time_limit_s=SOLVER_TIME_LIMIT_S):
    from ortools.constraint_solver import routing_enums_pb2, pywrapcp

    n_c = len(customers)
    n_v = len(vehicles)
    n_nodes = 1 + n_c  # 0=depot

    manager = pywrapcp.RoutingIndexManager(n_nodes, n_v, 0)
    routing = pywrapcp.RoutingModel(manager)

    # Distance callback (in meters for integer arithmetic)
    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return int(dist[from_node][to_node] * 1000)

    transit_cb_idx = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_cb_idx)

    # Capacity
    def demand_callback(from_index):
        node = manager.IndexToNode(from_index)
        if node == 0:
            return 0
        return int(customers[node - 1]["demand"])

    demand_cb_idx = routing.RegisterUnaryTransitCallback(demand_callback)
    caps = [int(v["capacity"]) for v in vehicles]
    routing.AddDimensionWithVehicleCapacity(demand_cb_idx, 0, caps, True, "Capacity")

    # Time windows
    def time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        travel = ttime[from_node][to_node]
        service = 0
        if from_node > 0:
            service = customers[from_node - 1]["service_min"]
        return int(travel + service)

    time_cb_idx = routing.RegisterTransitCallback(time_callback)
    max_time = 24 * 60  # minutes in a day
    routing.AddDimension(time_cb_idx, max_time, max_time, False, "Time")
    time_dim = routing.GetDimensionOrDie("Time")

    # Depot time window
    for v_idx in range(n_v):
        start = routing.Start(v_idx)
        time_dim.CumulVar(start).SetRange(DEPOT_DEPART_MIN, DEPOT_DEPART_MIN)

    # Customer time windows (soft)
    for ci in range(n_c):
        idx = manager.NodeToIndex(ci + 1)
        c = customers[ci]
        tw_s = hhmm_to_min(c["tw_start"])
        tw_e = hhmm_to_min(c["tw_end"])
        time_dim.CumulVar(idx).SetRange(tw_s, max_time)
        # soft upper bound — penalty for lateness
        time_dim.SetCumulVarSoftUpperBound(idx, tw_e, 1000)

    # Allow dropping visits with penalty
    penalty = 100000
    for ci in range(n_c):
        routing.AddDisjunction([manager.NodeToIndex(ci + 1)], penalty)

    # Search parameters
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    search_params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search_params.time_limit.seconds = time_limit_s

    solution = routing.SolveWithParameters(search_params)

    if solution is None:
        print("  OR-Tools: No solution found")
        return None

    routes = []
    for v_idx in range(n_v):
        route_cids = []
        idx = routing.Start(v_idx)
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            if node > 0:
                route_cids.append(node - 1)
            idx = solution.Value(routing.NextVar(idx))
        routes.append({"vehicle_idx": v_idx, "customer_indices": route_cids})

    return routes

# ---------------------------------------------------------------------------
# Improvement: AM/PM Split
# ---------------------------------------------------------------------------

def am_pm_split(depot, customers, vehicles, dist, ttime):
    """
    Split customers into AM (early TW) and PM (late TW) groups.
    Run OR-Tools solver on each half separately, vehicles do 2 trips.
    """
    from ortools.constraint_solver import routing_enums_pb2, pywrapcp

    # Classify by time window midpoint
    am_cids = []
    pm_cids = []
    mid_threshold = hhmm_to_min("12:00")

    for ci, c in enumerate(customers):
        tw_mid = (hhmm_to_min(c["tw_start"]) + hhmm_to_min(c["tw_end"])) / 2
        if tw_mid <= mid_threshold:
            am_cids.append(ci)
        else:
            pm_cids.append(ci)

    # If PM group is empty, split by demand priority
    if len(pm_cids) == 0:
        # Sort by tw_end ascending, split roughly in half by capacity
        sorted_cids = sorted(range(len(customers)), key=lambda ci: hhmm_to_min(customers[ci]["tw_end"]))
        total_cap = sum(v["capacity"] for v in vehicles)
        cum = 0
        am_cids = []
        pm_cids = []
        for ci in sorted_cids:
            if cum + customers[ci]["demand"] <= total_cap * 0.95:
                am_cids.append(ci)
                cum += customers[ci]["demand"]
            else:
                pm_cids.append(ci)

    print(f"  AM/PM split: AM={len(am_cids)} customers, PM={len(pm_cids)} customers")
    print(f"  AM demand: {sum(customers[ci]['demand'] for ci in am_cids)} kg")
    print(f"  PM demand: {sum(customers[ci]['demand'] for ci in pm_cids)} kg")

    def solve_subset(cids, depart_min, label):
        subset = [customers[ci] for ci in cids]
        n_c = len(subset)
        if n_c == 0:
            return []

        n_v = len(vehicles)
        # Build sub-matrices
        nodes_lat_lon = [(depot["lat"], depot["lon"])] + [(c["lat"], c["lon"]) for c in subset]
        n_nodes = len(nodes_lat_lon)
        sub_dist = [[0.0]*n_nodes for _ in range(n_nodes)]
        sub_ttime = [[0.0]*n_nodes for _ in range(n_nodes)]
        for i in range(n_nodes):
            for j in range(n_nodes):
                if i == j:
                    continue
                d = haversine_km(nodes_lat_lon[i][0], nodes_lat_lon[i][1],
                                 nodes_lat_lon[j][0], nodes_lat_lon[j][1]) * ROAD_FACTOR
                sub_dist[i][j] = round(d, 2)
                sub_ttime[i][j] = round(d / SPEED_KMH * 60, 2)

        manager = pywrapcp.RoutingIndexManager(n_nodes, n_v, 0)
        routing = pywrapcp.RoutingModel(manager)

        def distance_callback(fi, ti):
            fn = manager.IndexToNode(fi)
            tn = manager.IndexToNode(ti)
            return int(sub_dist[fn][tn] * 1000)

        transit_cb = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_cb)

        # Capacity
        def demand_callback(fi):
            node = manager.IndexToNode(fi)
            return 0 if node == 0 else int(subset[node-1]["demand"])

        demand_cb = routing.RegisterUnaryTransitCallback(demand_callback)
        caps = [int(v["capacity"]) for v in vehicles]
        routing.AddDimensionWithVehicleCapacity(demand_cb, 0, caps, True, "Capacity")

        # Time
        def time_callback(fi, ti):
            fn = manager.IndexToNode(fi)
            tn = manager.IndexToNode(ti)
            t = sub_ttime[fn][tn]
            s = 0 if fn == 0 else subset[fn-1]["service_min"]
            return int(t + s)

        time_cb = routing.RegisterTransitCallback(time_callback)
        max_t = 24 * 60
        routing.AddDimension(time_cb, max_t, max_t, False, "Time")
        time_dim = routing.GetDimensionOrDie("Time")

        for vi in range(n_v):
            time_dim.CumulVar(routing.Start(vi)).SetRange(depart_min, depart_min)

        for si in range(n_c):
            idx = manager.NodeToIndex(si + 1)
            c = subset[si]
            tw_s = hhmm_to_min(c["tw_start"])
            tw_e = hhmm_to_min(c["tw_end"])
            time_dim.CumulVar(idx).SetRange(tw_s, max_t)
            time_dim.SetCumulVarSoftUpperBound(idx, tw_e, 1000)

        penalty = 100000
        for si in range(n_c):
            routing.AddDisjunction([manager.NodeToIndex(si + 1)], penalty)

        sp = pywrapcp.DefaultRoutingSearchParameters()
        sp.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        sp.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        sp.time_limit.seconds = 60

        solution = routing.SolveWithParameters(sp)
        if solution is None:
            print(f"  {label}: No solution")
            return []

        routes = []
        for vi in range(n_v):
            rcids = []
            idx = routing.Start(vi)
            while not routing.IsEnd(idx):
                node = manager.IndexToNode(idx)
                if node > 0:
                    rcids.append(cids[node - 1])  # map back to original index
                idx = solution.Value(routing.NextVar(idx))
            if rcids:
                routes.append({"vehicle_idx": vi, "customer_indices": rcids, "depart_min": depart_min})
        return routes

    am_routes = solve_subset(am_cids, DEPOT_DEPART_MIN, "AM")
    pm_routes = solve_subset(pm_cids, hhmm_to_min("12:30"), "PM")

    return am_routes + pm_routes

# ---------------------------------------------------------------------------
# Data Analysis
# ---------------------------------------------------------------------------

def analyze_data(depot, customers, vehicles, dist, ttime):
    total_demand = sum(c["demand"] for c in customers)
    total_cap = sum(v["capacity"] for v in vehicles)
    n_c = len(customers)

    # distance stats from depot
    depot_dists = [dist[0][ci+1] for ci in range(n_c)]
    avg_depot_dist = sum(depot_dists) / n_c

    # inter-customer distances
    inter = []
    for i in range(n_c):
        for j in range(i+1, n_c):
            inter.append(dist[i+1][j+1])
    avg_inter = sum(inter) / len(inter) if inter else 0

    # time window tightness
    tw_widths = []
    for c in customers:
        tw_widths.append(hhmm_to_min(c["tw_end"]) - hhmm_to_min(c["tw_start"]))
    avg_tw = sum(tw_widths) / len(tw_widths)

    analysis = {
        "num_customers": n_c,
        "num_vehicles": len(vehicles),
        "total_demand_kg": total_demand,
        "total_capacity_kg": total_cap,
        "capacity_ratio": round(total_demand / total_cap, 3),
        "capacity_sufficient": total_demand <= total_cap,
        "avg_distance_from_depot_km": round(avg_depot_dist, 2),
        "avg_inter_customer_distance_km": round(avg_inter, 2),
        "max_distance_from_depot_km": round(max(depot_dists), 2),
        "avg_time_window_width_min": round(avg_tw, 1),
        "min_time_window_width_min": min(tw_widths),
        "vehicles": [{"id": v["id"], "capacity": v["capacity"], "max_hours": v["max_hours"], "cost_per_km": v["cost_per_km"]} for v in vehicles],
        "demand_per_customer": {c["id"]: c["demand"] for c in customers},
    }
    return analysis

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("Delivery Routing Optimization — Full Workflow")
    print("=" * 60)

    # Load
    depot, customers, vehicles = load_data()
    dist, ttime = build_matrices(depot, customers)

    # 1. Analysis
    print("\n[1] Data Analysis")
    analysis = analyze_data(depot, customers, vehicles, dist, ttime)
    print(f"  Customers: {analysis['num_customers']}")
    print(f"  Vehicles:  {analysis['num_vehicles']}")
    print(f"  Total demand: {analysis['total_demand_kg']} kg")
    print(f"  Total capacity: {analysis['total_capacity_kg']} kg")
    print(f"  Capacity ratio: {analysis['capacity_ratio']} ({'INSUFFICIENT' if not analysis['capacity_sufficient'] else 'OK'})")
    print(f"  Avg dist from depot: {analysis['avg_distance_from_depot_km']} km")
    print(f"  Avg time window: {analysis['avg_time_window_width_min']} min")

    with open(os.path.join(RESULTS_DIR, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    # 2. Baselines
    results = {}

    # 2a. Random
    print("\n[2a] Baseline: Random Assignment")
    r_routes = random_baseline(customers, vehicles)
    r_eval = evaluate_routes(r_routes, depot, customers, vehicles, dist, ttime)
    results["random"] = r_eval
    print(f"  Distance: {r_eval['total_distance_km']} km")
    print(f"  Cost: ¥{r_eval['total_cost_yen']:,.0f}")
    print(f"  TW violations: {r_eval['tw_violations']}")
    print(f"  Capacity violations: {r_eval['capacity_violations']}")
    print(f"  Unvisited: {r_eval['unvisited_count']}")

    # 2b. Nearest Neighbor
    print("\n[2b] Baseline: Nearest Neighbor")
    nn_routes = nearest_neighbor_baseline(customers, vehicles, dist)
    nn_eval = evaluate_routes(nn_routes, depot, customers, vehicles, dist, ttime)
    results["nearest_neighbor"] = nn_eval
    print(f"  Distance: {nn_eval['total_distance_km']} km")
    print(f"  Cost: ¥{nn_eval['total_cost_yen']:,.0f}")
    print(f"  TW violations: {nn_eval['tw_violations']}")
    print(f"  Capacity violations: {nn_eval['capacity_violations']}")
    print(f"  Unvisited: {nn_eval['unvisited_count']}")

    # 2c. OR-Tools Solver (single trip)
    print("\n[2c] Baseline: OR-Tools Routing Solver")
    ort_routes = ortools_solver(depot, customers, vehicles, dist, ttime)
    if ort_routes:
        ort_eval = evaluate_routes(ort_routes, depot, customers, vehicles, dist, ttime)
        results["ortools_single"] = ort_eval
        print(f"  Distance: {ort_eval['total_distance_km']} km")
        print(f"  Cost: ¥{ort_eval['total_cost_yen']:,.0f}")
        print(f"  TW violations: {ort_eval['tw_violations']}")
        print(f"  Capacity violations: {ort_eval['capacity_violations']}")
        print(f"  Unvisited: {ort_eval['unvisited_count']}")
    else:
        results["ortools_single"] = {"error": "No solution found"}
        print("  No solution found")

    # 3. Improvement: AM/PM Split
    if not analysis["capacity_sufficient"]:
        print("\n[3] Improvement: AM/PM Split (demand > capacity)")
        ampm_routes = am_pm_split(depot, customers, vehicles, dist, ttime)
        ampm_eval = evaluate_routes(ampm_routes, depot, customers, vehicles, dist, ttime)
        results["ampm_split"] = ampm_eval
        print(f"  Distance: {ampm_eval['total_distance_km']} km")
        print(f"  Cost: ¥{ampm_eval['total_cost_yen']:,.0f}")
        print(f"  TW violations: {ampm_eval['tw_violations']}")
        print(f"  Capacity violations: {ampm_eval['capacity_violations']}")
        print(f"  Unvisited: {ampm_eval['unvisited_count']}")

    # 4. Save all results
    with open(os.path.join(RESULTS_DIR, "all_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Summary comparison
    print("\n" + "=" * 60)
    print("Summary Comparison")
    print("=" * 60)
    print(f"{'Method':<25} {'Dist(km)':>10} {'Cost(¥)':>12} {'TW Viol':>8} {'Cap Viol':>9} {'Unvisited':>9}")
    print("-" * 75)
    for method, ev in results.items():
        if "error" in ev:
            print(f"{method:<25} {'N/A':>10}")
            continue
        print(f"{method:<25} {ev['total_distance_km']:>10.1f} {ev['total_cost_yen']:>12,.0f} {ev['tw_violations']:>8} {ev['capacity_violations']:>9} {ev['unvisited_count']:>9}")

    print(f"\nResults saved to {RESULTS_DIR}/")
    return results


if __name__ == "__main__":
    main()
