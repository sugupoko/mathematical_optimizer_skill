"""配送ルート最適化: 3ベースライン（ランダム / 最近傍法 / OR-Tools Routing）"""
from __future__ import annotations
import csv
import math
import json
import random
from pathlib import Path
from ortools.constraint_solver import routing_enums_pb2, pywrapcp

DATA_DIR = Path(__file__).parent.parent / "data"
RESULTS_DIR = Path(__file__).parent.parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

SPEED_KMH = 30
ROAD_FACTOR = 1.3
DEPOT_START_MIN = 8 * 60  # 08:00


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
    """Build distance matrix in meters (int). Index 0 = depot."""
    locations = [depot] + customers
    n = len(locations)
    matrix = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                d = haversine_km(
                    locations[i]["latitude"], locations[i]["longitude"],
                    locations[j]["latitude"], locations[j]["longitude"],
                )
                matrix[i][j] = int(d * 1000)  # meters
    return matrix


def build_time_matrix(dist_matrix):
    """Travel time in minutes."""
    n = len(dist_matrix)
    time_matrix = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            dist_km = dist_matrix[i][j] / 1000
            time_matrix[i][j] = int(dist_km / SPEED_KMH * 60)
    return time_matrix


# ─── 評価関数 ───

def evaluate(routes, depot, customers, vehicles, dist_matrix, time_matrix):
    """Evaluate solution quality."""
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
        time_min = DEPOT_START_MIN  # departure time
        route_dist = 0
        prev = 0  # depot
        stops = []

        for cust_idx in route:  # cust_idx is 1-based (0=depot)
            if cust_idx < 1 or cust_idx > n_cust:
                continue
            c = customers[cust_idx - 1]

            # Travel
            travel = time_matrix[prev][cust_idx]
            time_min += travel
            route_dist += dist_matrix[prev][cust_idx]

            # Time window
            arrival = time_min
            if arrival < c["tw_start"]:
                time_min = c["tw_start"]  # wait
                arrival = c["tw_start"]
            if arrival > c["tw_end"]:
                tw_violations += 1

            # Service
            time_min += c["service_time_min"]

            # Load
            load += c["demand_kg"]
            visited.add(cust_idx)

            stops.append({
                "customer": c["customer_id"],
                "name": c["name"],
                "arrival": arrival,
                "tw": f"{c['time_window_start']}-{c['time_window_end']}",
                "tw_ok": arrival <= c["tw_end"],
                "load_after": load,
            })
            prev = cust_idx

        # Return to depot
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
            "vehicle": veh["vehicle_id"],
            "stops": len(stops),
            "load_kg": load,
            "capacity_kg": veh["capacity_kg"],
            "distance_km": round(route_dist_km, 1),
            "time_h": round(total_time_h, 2),
            "max_hours": veh["max_hours"],
            "stop_details": stops,
        })

    unvisited = [customers[i - 1]["customer_id"] for i in range(1, n_cust + 1) if i not in visited]
    total_dist_km = total_distance_m / 1000
    feasible = tw_violations == 0 and cap_violations == 0 and time_violations == 0 and len(unvisited) == 0

    return {
        "feasible": feasible,
        "total_distance_km": round(total_dist_km, 1),
        "total_cost_yen": round(total_cost),
        "tw_violations": tw_violations,
        "capacity_violations": cap_violations,
        "time_violations": time_violations,
        "unvisited": unvisited,
        "customers_served": len(visited),
        "route_details": route_details,
    }


# ─── Baseline 1: ランダム ───

def baseline_random(customers, vehicles, seed=42):
    random.seed(seed)
    indices = list(range(1, len(customers) + 1))
    random.shuffle(indices)
    n_veh = len(vehicles)
    routes = [[] for _ in range(n_veh)]
    for i, idx in enumerate(indices):
        routes[i % n_veh].append(idx)
    return routes


# ─── Baseline 2: 最近傍法 ───

def baseline_nearest(customers, vehicles, dist_matrix):
    n_cust = len(customers)
    n_veh = len(vehicles)
    routes = [[] for _ in range(n_veh)]
    loads = [0] * n_veh
    times = [DEPOT_START_MIN] * n_veh
    positions = [0] * n_veh  # all start at depot
    visited = set()

    time_mat = build_time_matrix(dist_matrix)

    for _ in range(n_cust):
        best_v, best_c, best_dist = -1, -1, float("inf")
        for v in range(n_veh):
            veh = vehicles[v]
            for c_idx in range(1, n_cust + 1):
                if c_idx in visited:
                    continue
                c = customers[c_idx - 1]
                # Check capacity
                if loads[v] + c["demand_kg"] > veh["capacity_kg"]:
                    continue
                # Check time
                travel = time_mat[positions[v]][c_idx]
                arrival = times[v] + travel
                if arrival < c["tw_start"]:
                    arrival = c["tw_start"]
                finish = arrival + c["service_time_min"]
                # Check max hours
                return_time = finish + time_mat[c_idx][0]
                if (return_time - DEPOT_START_MIN) / 60 > veh["max_hours"]:
                    continue

                d = dist_matrix[positions[v]][c_idx]
                # Prefer within time window
                if arrival <= c["tw_end"] and d < best_dist:
                    best_v, best_c, best_dist = v, c_idx, d

        if best_c == -1:
            # Try without time window check (will violate)
            for v in range(n_veh):
                for c_idx in range(1, n_cust + 1):
                    if c_idx in visited:
                        continue
                    c = customers[c_idx - 1]
                    if loads[v] + c["demand_kg"] > vehicles[v]["capacity_kg"]:
                        continue
                    d = dist_matrix[positions[v]][c_idx]
                    if d < best_dist:
                        best_v, best_c, best_dist = v, c_idx, d

        if best_c == -1:
            break  # can't assign any more

        c = customers[best_c - 1]
        routes[best_v].append(best_c)
        visited.add(best_c)
        travel = time_mat[positions[best_v]][best_c]
        arrival = times[best_v] + travel
        if arrival < c["tw_start"]:
            arrival = c["tw_start"]
        times[best_v] = arrival + c["service_time_min"]
        loads[best_v] += c["demand_kg"]
        positions[best_v] = best_c

    return routes


# ─── Baseline 3: OR-Tools Routing ───

def baseline_solver(depot, customers, vehicles, dist_matrix, time_matrix, time_limit=120):
    n_locations = len(customers) + 1  # 0=depot
    n_vehicles = len(vehicles)

    manager = pywrapcp.RoutingIndexManager(n_locations, n_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    # Distance callback
    def dist_callback(from_idx, to_idx):
        f = manager.IndexToNode(from_idx)
        t = manager.IndexToNode(to_idx)
        return dist_matrix[f][t]

    transit_cb = routing.RegisterTransitCallback(dist_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_cb)

    # Capacity
    def demand_callback(idx):
        node = manager.IndexToNode(idx)
        if node == 0:
            return 0
        return customers[node - 1]["demand_kg"]

    demand_cb = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_cb, 0,
        [v["capacity_kg"] for v in vehicles],
        True, "Capacity"
    )

    # Time windows
    def time_callback(from_idx, to_idx):
        f = manager.IndexToNode(from_idx)
        t = manager.IndexToNode(to_idx)
        travel = time_matrix[f][t]
        service = 0
        if f > 0:
            service = customers[f - 1]["service_time_min"]
        return travel + service

    time_cb = routing.RegisterTransitCallback(time_callback)
    routing.AddDimension(time_cb, 480, 1440, False, "Time")  # 480min max wait, 1440 max

    time_dimension = routing.GetDimensionOrDie("Time")

    # Depot time window (08:00 - 24:00)
    for v in range(n_vehicles):
        start = routing.Start(v)
        time_dimension.CumulVar(start).SetRange(DEPOT_START_MIN, DEPOT_START_MIN)
        # Max hours per vehicle
        end = routing.End(v)
        max_end = DEPOT_START_MIN + vehicles[v]["max_hours"] * 60
        time_dimension.CumulVar(end).SetRange(DEPOT_START_MIN, max_end)

    # Customer time windows
    for c_idx in range(len(customers)):
        node = manager.NodeToIndex(c_idx + 1)
        c = customers[c_idx]
        time_dimension.CumulVar(node).SetRange(c["tw_start"], c["tw_end"])

    # Allow dropping nodes with penalty (since capacity may not fit all)
    penalty = 100000  # high penalty per unvisited
    for c_idx in range(1, n_locations):
        routing.AddDisjunction([manager.NodeToIndex(c_idx)], penalty)

    # Search parameters
    search_params = pywrapcp.DefaultRoutingSearchParameters()
    search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    search_params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    search_params.time_limit.FromSeconds(time_limit)

    solution = routing.SolveWithParameters(search_params)

    routes = []
    info = {"wall_time": "~" + str(time_limit) + "s"}
    if solution:
        info["status"] = "SOLUTION_FOUND"
        info["objective"] = solution.ObjectiveValue()
        for v in range(n_vehicles):
            route = []
            index = routing.Start(v)
            while not routing.IsEnd(index):
                node = manager.IndexToNode(index)
                if node != 0:
                    route.append(node)
                index = solution.Value(routing.NextVar(index))
            routes.append(route)
    else:
        info["status"] = "NO_SOLUTION"
        routes = [[] for _ in range(n_vehicles)]

    return routes, info


def print_routes(result):
    for rd in result["route_details"]:
        print(f"\n  {rd['vehicle']}: {rd['stops']}stops, {rd['load_kg']}/{rd['capacity_kg']}kg, {rd['distance_km']}km, {rd['time_h']}h/{rd['max_hours']}h")
        for s in rd["stop_details"]:
            tw_flag = "OK" if s["tw_ok"] else "LATE"
            h, m = divmod(int(s["arrival"]), 60)
            print(f"    {s['customer']} {s['name']:12s} arrive={h:02d}:{m:02d} tw={s['tw']} [{tw_flag}] load={s['load_after']}kg")
    if result["unvisited"]:
        print(f"  Unvisited: {result['unvisited']}")


def main():
    depot, customers, vehicles = load_data()
    dist_matrix = build_distance_matrix(depot, customers)
    time_matrix = build_time_matrix(dist_matrix)

    all_results = {}

    # Baseline 1: Random
    print("=" * 60)
    print("Baseline 1: Random")
    print("=" * 60)
    r1 = baseline_random(customers, vehicles)
    e1 = evaluate(r1, depot, customers, vehicles, dist_matrix, time_matrix)
    print(f"Feasible: {e1['feasible']}, Distance: {e1['total_distance_km']}km, Cost: ¥{e1['total_cost_yen']}")
    print(f"TW violations: {e1['tw_violations']}, Cap violations: {e1['capacity_violations']}, Unvisited: {len(e1['unvisited'])}")
    print_routes(e1)
    all_results["random"] = e1

    # Baseline 2: Nearest Neighbor
    print("\n" + "=" * 60)
    print("Baseline 2: Nearest Neighbor")
    print("=" * 60)
    r2 = baseline_nearest(customers, vehicles, dist_matrix)
    e2 = evaluate(r2, depot, customers, vehicles, dist_matrix, time_matrix)
    print(f"Feasible: {e2['feasible']}, Distance: {e2['total_distance_km']}km, Cost: ¥{e2['total_cost_yen']}")
    print(f"TW violations: {e2['tw_violations']}, Cap violations: {e2['capacity_violations']}, Unvisited: {len(e2['unvisited'])}")
    print_routes(e2)
    all_results["nearest"] = e2

    # Baseline 3: OR-Tools Solver
    print("\n" + "=" * 60)
    print("Baseline 3: OR-Tools Routing (120s)")
    print("=" * 60)
    r3, info3 = baseline_solver(depot, customers, vehicles, dist_matrix, time_matrix, time_limit=120)
    e3 = evaluate(r3, depot, customers, vehicles, dist_matrix, time_matrix)
    print(f"Solver: {info3}")
    print(f"Feasible: {e3['feasible']}, Distance: {e3['total_distance_km']}km, Cost: ¥{e3['total_cost_yen']}")
    print(f"TW violations: {e3['tw_violations']}, Cap violations: {e3['capacity_violations']}, Unvisited: {len(e3['unvisited'])}")
    print_routes(e3)
    all_results["solver"] = {**e3, "solver_info": info3}

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"{'Method':<20} {'Feasible':<10} {'Dist(km)':<10} {'Cost(¥)':<10} {'TW viol':<10} {'Unvisited'}")
    for name, r in [("Random", e1), ("Nearest", e2), ("Solver", e3)]:
        print(f"{name:<20} {str(r['feasible']):<10} {r['total_distance_km']:<10} {r['total_cost_yen']:<10} {r['tw_violations']:<10} {len(r['unvisited'])}")

    with open(RESULTS_DIR / "baseline_results.json", "w") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nSaved to {RESULTS_DIR / 'baseline_results.json'}")


if __name__ == "__main__":
    main()
