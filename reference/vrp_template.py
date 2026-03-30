"""配送ルート最適化（VRP）のRouting Library定式化テンプレート。

配送ルート最適化プロジェクト（5難易度×9手法比較）で検証済みのテンプレート。
OR-ToolsのRouting Libraryを使い、容量制約付き配送ルート問題（CVRP）および
時間枠制約付き配送ルート問題（VRPTW）を求解する。

使い方:
  1. このファイルをコピーして問題に合わせて修正
  2. distance_matrix, demands, time_windows を自分のデータに合わせる
  3. 時間制限は長めに設定（品質は時間に比例）

典型的な利用フロー::

    dataset = json.load(open("data.json"))
    routes = solve_vrp(dataset, time_limit=120)
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

from ortools.constraint_solver import routing_enums_pb2, pywrapcp

logger = logging.getLogger(__name__)


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """2点間のHaversine距離を計算する（km単位、道路係数1.3を含む）。

    直線距離に道路係数1.3を乗じて実走行距離を近似する。
    より正確な距離が必要な場合はGoogle Maps APIなどに置き換えること。

    Args:
        lat1: 出発地の緯度（度）
        lng1: 出発地の経度（度）
        lat2: 到着地の緯度（度）
        lng2: 到着地の経度（度）

    Returns:
        2点間の推定道路距離（km）
    """
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a)) * 1.3  # 道路係数


def build_distance_matrix(depot: dict[str, float], locations: list[dict[str, Any]]) -> list[list[int]]:
    """距離マトリクスを構築する（メートル単位の整数）。

    デポと全配送先間の距離をHaversine公式で計算し、
    OR-ToolsのRouting Libraryが要求する整数行列として返す。

    Args:
        depot: デポの座標。``{"lat": float, "lng": float}`` の形式。
        locations: 配送先リスト。各要素に ``"lat"`` と ``"lng"`` を含む。

    Returns:
        (N+1) x (N+1) の距離行列（メートル単位の整数）。index 0 がデポ。
    """
    nodes = [depot] + locations
    n = len(nodes)
    matrix = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                d = haversine_km(
                    nodes[i]["lat"], nodes[i]["lng"],
                    nodes[j]["lat"], nodes[j]["lng"]
                )
                matrix[i][j] = int(d * 1000)  # km → m
    return matrix


def solve_vrp(dataset: dict[str, Any], time_limit: int = 120) -> list[list[int]]:
    """汎用VRPソルバー。

    OR-ToolsのRouting Libraryを使い、容量制約付きVRP（CVRP）を求解する。
    時間枠データが含まれる場合は自動的にVRPTWとして扱う。

    Args:
        dataset: 問題データ。最低限以下の構造が必要::

            {
                "depot": {"lat": 34.71, "lng": 137.73},
                "locations": [{"id": 1, "lat": ..., "lng": ..., "demand": 5}, ...],
                "vehicles": [{"id": 0, "capacity": 80}, ...],
            }

            オプションフィールド:
              - ``locations[].time_window``: ``[start_min, end_min]`` 分単位
              - ``locations[].service_time``: int 分
              - ``vehicles[].working_start``: int 分
              - ``vehicles[].working_end``: int 分

        time_limit: ソルバーの最大実行時間（秒）。デフォルト120秒。
            品質は時間に比例するため、本番では長めに設定すること。

    Returns:
        各車両のルート（ノードIDのリスト）。例: ``[[0, 3, 7, 12, 0], [0, 1, 5, 0], ...]``
        解が見つからない場合は空リストを返す。
    """
    depot = dataset["depot"]
    locations = dataset["locations"]
    vehicles = dataset["vehicles"]
    num_locations = len(locations) + 1  # +depot
    num_vehicles = len(vehicles)

    # --- 距離マトリクス ---
    dist_matrix = build_distance_matrix(depot, locations)

    # --- OR-Tools マネージャー ---
    manager = pywrapcp.RoutingIndexManager(num_locations, num_vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)

    # --- 距離コールバック ---
    def distance_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return dist_matrix[from_node][to_node]

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # --- 容量制約 ---
    demands = [0] + [loc.get("demand", 1) for loc in locations]  # depot=0

    def demand_callback(from_index):
        from_node = manager.IndexToNode(from_index)
        return demands[from_node]

    demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
    capacities = [v.get("capacity", 100) for v in vehicles]
    routing.AddDimensionWithVehicleCapacity(
        demand_callback_index, 0, capacities, True, "Capacity"
    )

    # --- 時間枠制約（あれば） ---
    has_time_windows = any("time_window" in loc for loc in locations)
    if has_time_windows:
        speed_mpm = 500  # 500 m/min ≈ 30 km/h
        service_times = [0] + [loc.get("service_time", 10) for loc in locations]

        def time_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            travel_min = dist_matrix[from_node][to_node] // speed_mpm
            return travel_min + service_times[from_node]

        time_callback_index = routing.RegisterTransitCallback(time_callback)

        max_time = 600  # 10時間（分）
        routing.AddDimension(time_callback_index, 60, max_time, False, "Time")

        time_dimension = routing.GetDimensionOrDie("Time")
        for i, loc in enumerate(locations):
            if "time_window" in loc:
                index = manager.NodeToIndex(i + 1)
                tw = loc["time_window"]
                time_dimension.CumulVar(index).SetRange(int(tw[0]), int(tw[1]))

        # 車両の勤務時間制約
        for v_id, v in enumerate(vehicles):
            start = v.get("working_start", 0)
            end = v.get("working_end", max_time)
            start_index = routing.Start(v_id)
            end_index = routing.End(v_id)
            time_dimension.CumulVar(start_index).SetRange(int(start), int(end))
            time_dimension.CumulVar(end_index).SetRange(int(start), int(end))

    # --- 探索パラメータ ---
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    )
    search_parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_parameters.time_limit.FromSeconds(time_limit)

    logger.info("Solving VRP (%d locations, %d vehicles, limit=%ds)...",
                len(locations), num_vehicles, time_limit)

    # --- 解く ---
    solution = routing.SolveWithParameters(search_parameters)

    if not solution:
        logger.error("No solution found")
        return []

    # --- 結果抽出 ---
    routes = []
    total_distance = 0
    for v_id in range(num_vehicles):
        index = routing.Start(v_id)
        route = []
        route_distance = 0
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            route.append(node)
            prev_index = index
            index = solution.Value(routing.NextVar(index))
            route_distance += dist_matrix[manager.IndexToNode(prev_index)][manager.IndexToNode(index)]
        route.append(0)  # depot
        routes.append(route)
        total_distance += route_distance

    logger.info("Total distance: %.1f km", total_distance / 1000)
    logger.info("Routes: %d", len([r for r in routes if len(r) > 2]))

    return routes


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

    data_path = sys.argv[1] if len(sys.argv) > 1 else "data.json"
    with open(data_path) as f:
        dataset = json.load(f)

    routes = solve_vrp(dataset)
    for i, route in enumerate(routes):
        if len(route) > 2:
            print(f"Vehicle {i}: {route}")
