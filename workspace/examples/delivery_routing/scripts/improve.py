"""改善策: AM/PM分割で全顧客をカバー + ソルバー最適化"""
from __future__ import annotations
import csv
import math
import json
from pathlib import Path
from ortools.constraint_solver import routing_enums_pb2, pywrapcp

DATA_DIR = Path(__file__).parent.parent / "data"
RESULTS_DIR = Path(__file__).parent.parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

SPEED_KMH = 30
ROAD_FACTOR = 1.3
DEPOT_START_MIN = 8 * 60


def load_data():
    with open(DATA_DIR / "depot.csv") as f:
        depot = list(csv.DictReader(f))[0]
        depot["latitude"] = float(depot["latitude"])
        depot["longitude"] = float(depot["longitude"])
    customers = []
    with open(DATA_DIR / "customers.csv") as f:
        for row in csv.DictReader(f):
            row["latitude"] = float(row["latitude"])
            row["longitude"] = float(row["longitude"])
            row["demand_kg"] = int(row["demand_kg"])
            row["service_time_min"] = int(row["service_time_min"])
            h1, m1 = row["time_window_start"].split(":")
            h2, m2 = row["time_window_end"].split(":")
            row["tw_start"] = int(h1) * 60 + int(m1)
            row["tw_end"] = int(h2) * 60 + int(m2)
            customers.append(row)
    vehicles = []
    with open(DATA_DIR / "vehicles.csv") as f:
        for row in csv.DictReader(f):
            row["capacity_kg"] = int(row["capacity_kg"])
            row["max_hours"] = int(row["max_hours"])
            row["cost_per_km"] = int(row["cost_per_km"])
            vehicles.append(row)
    return depot, customers, vehicles


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a)) * ROAD_FACTOR


def build_distance_matrix(depot, customers):
    locations = [depot] + customers
    n = len(locations)
    matrix = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                matrix[i][j] = int(haversine_km(
                    locations[i]["latitude"], locations[i]["longitude"],
                    locations[j]["latitude"], locations[j]["longitude"],
                ) * 1000)
    return matrix


def build_time_matrix(dist_matrix):
    n = len(dist_matrix)
    return [[int(dist_matrix[i][j] / 1000 / SPEED_KMH * 60) for j in range(n)] for i in range(n)]


def evaluate_routes(routes, depot, customers, vehicles, dist_matrix, time_matrix):
    n_cust = len(customers)
    visited = set()
    total_distance_m = 0
    total_cost = 0
    tw_violations = 0
    cap_violations = 0
    time_violations = 0
    route_details = []

    for v_idx, route in enumerate(routes):
        if v_idx >= len(vehicles):
            break
        veh = vehicles[v_idx]
        load = 0
        time_min = DEPOT_START_MIN
        route_dist = 0
        prev = 0
        stops = []

        for cust_idx in route:
            if cust_idx < 1 or cust_idx > n_cust:
                continue
            c = customers[cust_idx - 1]
            travel = time_matrix[prev][cust_idx]
            time_min += travel
            route_dist += dist_matrix[prev][cust_idx]
            arrival = time_min
            if arrival < c["tw_start"]:
                time_min = c["tw_start"]
                arrival = c["tw_start"]
            if arrival > c["tw_end"]:
                tw_violations += 1
            time_min += c["service_time_min"]
            load += c["demand_kg"]
            visited.add(cust_idx)
            stops.append({
                "customer": c["customer_id"], "name": c["name"],
                "arrival": arrival, "tw_ok": arrival <= c["tw_end"],
                "load_after": load,
            })
            prev = cust_idx

        route_dist += dist_matrix[prev][0]
        time_min += time_matrix[prev][0]
        total_time_h = (time_min - DEPOT_START_MIN) / 60
        if load > veh["capacity_kg"]:
            cap_violations += 1
        if total_time_h > veh["max_hours"]:
            time_violations += 1
        route_dist_km = route_dist / 1000
        total_distance_m += route_dist
        total_cost += route_dist_km * veh["cost_per_km"]
        route_details.append({
            "vehicle": veh["vehicle_id"], "stops": len(stops),
            "load_kg": load, "capacity_kg": veh["capacity_kg"],
            "distance_km": round(route_dist_km, 1),
            "time_h": round(total_time_h, 2), "max_hours": veh["max_hours"],
            "stop_details": stops,
        })

    unvisited = [customers[i - 1]["customer_id"] for i in range(1, n_cust + 1) if i not in visited]
    total_dist_km = total_distance_m / 1000
    feasible = tw_violations == 0 and cap_violations == 0 and time_violations == 0 and len(unvisited) == 0

    return {
        "feasible": feasible, "total_distance_km": round(total_dist_km, 1),
        "total_cost_yen": round(total_cost), "tw_violations": tw_violations,
        "capacity_violations": cap_violations, "time_violations": time_violations,
        "unvisited": unvisited, "customers_served": len(visited),
        "route_details": route_details,
    }


def solve_vrp(depot, customers, vehicles, dist_matrix, time_matrix, time_limit=120):
    """OR-Tools Routing solver."""
    n_loc = len(customers) + 1
    n_veh = len(vehicles)
    manager = pywrapcp.RoutingIndexManager(n_loc, n_veh, 0)
    routing = pywrapcp.RoutingModel(manager)

    def dist_cb(f, t):
        return dist_matrix[manager.IndexToNode(f)][manager.IndexToNode(t)]

    transit_cb = routing.RegisterTransitCallback(dist_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_cb)

    def demand_cb(idx):
        node = manager.IndexToNode(idx)
        return 0 if node == 0 else customers[node - 1]["demand_kg"]

    d_cb = routing.RegisterUnaryTransitCallback(demand_cb)
    routing.AddDimensionWithVehicleCapacity(d_cb, 0, [v["capacity_kg"] for v in vehicles], True, "Cap")

    def time_cb(f, t):
        fn, tn = manager.IndexToNode(f), manager.IndexToNode(t)
        travel = time_matrix[fn][tn]
        service = customers[fn - 1]["service_time_min"] if fn > 0 else 0
        return travel + service

    t_cb = routing.RegisterTransitCallback(time_cb)
    routing.AddDimension(t_cb, 480, 1440, False, "Time")
    td = routing.GetDimensionOrDie("Time")

    for v in range(n_veh):
        td.CumulVar(routing.Start(v)).SetRange(DEPOT_START_MIN, DEPOT_START_MIN)
        td.CumulVar(routing.End(v)).SetRange(DEPOT_START_MIN, DEPOT_START_MIN + vehicles[v]["max_hours"] * 60)

    for c_idx in range(len(customers)):
        node = manager.NodeToIndex(c_idx + 1)
        td.CumulVar(node).SetRange(customers[c_idx]["tw_start"], customers[c_idx]["tw_end"])

    # Allow drops with high penalty
    for c_idx in range(1, n_loc):
        routing.AddDisjunction([manager.NodeToIndex(c_idx)], 100000)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromSeconds(time_limit)

    sol = routing.SolveWithParameters(params)
    routes = []
    if sol:
        for v in range(n_veh):
            route = []
            idx = routing.Start(v)
            while not routing.IsEnd(idx):
                node = manager.IndexToNode(idx)
                if node != 0:
                    route.append(node)
                idx = sol.Value(routing.NextVar(idx))
            routes.append(route)
    return routes


def main():
    depot, customers, vehicles = load_data()
    dist_matrix = build_distance_matrix(depot, customers)
    time_matrix = build_time_matrix(dist_matrix)

    # ─── 改善策A: AM/PM分割 ───
    # AM: 時間枠が早い顧客（tw_end <= 13:00）
    # PM: 時間枠が遅い顧客（tw_start >= 11:00）
    # 重なる顧客はAM優先で割り振り

    print("=" * 60)
    print("改善策A: AM/PM分割")
    print("  AM便で早い時間枠の顧客を配送 → デポに戻る → PM便で残りを配送")
    print("=" * 60)

    # Split customers
    am_indices = []
    pm_indices = []
    for i, c in enumerate(customers):
        if c["tw_end"] <= 13 * 60:  # must be done by 13:00
            am_indices.append(i)
        elif c["tw_start"] >= 11 * 60:  # can start from 11:00
            pm_indices.append(i)
        else:
            # Overlapping — assign to AM if early start, else PM
            if c["tw_start"] <= 9 * 60 + 30:
                am_indices.append(i)
            else:
                pm_indices.append(i)

    am_demand = sum(customers[i]["demand_kg"] for i in am_indices)
    pm_demand = sum(customers[i]["demand_kg"] for i in pm_indices)
    print(f"  AM: {len(am_indices)} customers, {am_demand}kg")
    print(f"  PM: {len(pm_indices)} customers, {pm_demand}kg")
    print(f"  Total capacity per trip: {sum(v['capacity_kg'] for v in vehicles)}kg")

    # Solve AM
    am_customers = [customers[i] for i in am_indices]
    am_dist = build_distance_matrix(depot, am_customers)
    am_time = build_time_matrix(am_dist)

    print("\n--- AM Routes ---")
    am_routes = solve_vrp(depot, am_customers, vehicles, am_dist, am_time, time_limit=60)
    am_result = evaluate_routes(am_routes, depot, am_customers, vehicles, am_dist, am_time)
    print(f"  Feasible: {am_result['feasible']}, Dist: {am_result['total_distance_km']}km, Served: {am_result['customers_served']}/{len(am_customers)}")
    for rd in am_result["route_details"]:
        stops_str = " → ".join(s["customer"] for s in rd["stop_details"])
        print(f"  {rd['vehicle']}: {rd['load_kg']}/{rd['capacity_kg']}kg, {rd['distance_km']}km | {stops_str}")

    # Solve PM
    pm_customers = [customers[i] for i in pm_indices]
    pm_dist = build_distance_matrix(depot, pm_customers)
    pm_time = build_time_matrix(pm_dist)

    # PM departure: assume vehicles return by ~12:00, depart again at 12:30
    # Adjust time windows for PM solver (keep as-is, just change depot start)
    print("\n--- PM Routes ---")
    pm_routes = solve_vrp(depot, pm_customers, vehicles, pm_dist, pm_time, time_limit=60)
    pm_result = evaluate_routes(pm_routes, depot, pm_customers, vehicles, pm_dist, pm_time)
    print(f"  Feasible: {pm_result['feasible']}, Dist: {pm_result['total_distance_km']}km, Served: {pm_result['customers_served']}/{len(pm_customers)}")
    for rd in pm_result["route_details"]:
        stops_str = " → ".join(s["customer"] for s in rd["stop_details"])
        print(f"  {rd['vehicle']}: {rd['load_kg']}/{rd['capacity_kg']}kg, {rd['distance_km']}km | {stops_str}")

    # Combined results
    total_dist = am_result["total_distance_km"] + pm_result["total_distance_km"]
    total_cost = am_result["total_cost_yen"] + pm_result["total_cost_yen"]
    total_served = am_result["customers_served"] + pm_result["customers_served"]
    all_feasible = am_result["feasible"] and pm_result["feasible"]
    am_unvisited = am_result["unvisited"]
    pm_unvisited = pm_result["unvisited"]

    print(f"\n--- Combined ---")
    print(f"  Feasible: {all_feasible}")
    print(f"  Total distance: {total_dist:.1f}km")
    print(f"  Total cost: ¥{total_cost}")
    print(f"  Customers served: {total_served}/20")
    if am_unvisited or pm_unvisited:
        print(f"  AM unvisited: {am_unvisited}")
        print(f"  PM unvisited: {pm_unvisited}")

    # ─── Comparison ───
    print("\n" + "=" * 60)
    print("比較サマリー")
    print("=" * 60)
    print(f"{'手法':<25} {'Feasible':<10} {'Dist(km)':<10} {'Cost(¥)':<10} {'Served'}")
    print("-" * 65)
    print(f"{'ベースライン(ソルバー)':<25} {'No':<10} {'84.5':<10} {'9510':<10} {'19/20'}")
    print(f"{'改善策A(AM/PM分割)':<25} {str(all_feasible):<10} {total_dist:<10.1f} {total_cost:<10} {f'{total_served}/20'}")

    # Save
    results = {
        "am_pm_split": {
            "am": am_result, "pm": pm_result,
            "combined": {
                "feasible": all_feasible,
                "total_distance_km": round(total_dist, 1),
                "total_cost_yen": total_cost,
                "customers_served": total_served,
            }
        }
    }
    with open(RESULTS_DIR / "improve_results.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nSaved to {RESULTS_DIR / 'improve_results.json'}")


if __name__ == "__main__":
    main()
