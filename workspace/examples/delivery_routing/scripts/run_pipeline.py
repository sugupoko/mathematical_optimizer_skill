#!/usr/bin/env python3
"""配送ルート最適化 — 本番パイプライン

実行頻度: 日次（毎朝06:00）
入力:     data/depot.csv, data/customers.csv, data/vehicles.csv
出力:     results/routes_YYYYMMDD_HHMMSS.json + 配送指示書txt
ログ:     log/run_YYYYMMDD_HHMMSS.log
"""

import csv
import json
import logging
import math
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ─── パス設定 ───
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = BASE_DIR / "results"
LOG_DIR = BASE_DIR / "log"
RESULTS_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

# ─── ロガー ───
log_path = LOG_DIR / f"run_{TIMESTAMP}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# ─── 定数 ───
SPEED_KMH = 30.0
ROAD_FACTOR = 1.3
AM_DEPART = "08:00"
PM_DEPART = "12:30"
SOLVER_TIME_LIMIT = 60  # 秒/便
HISTORY_KEEP = 7  # 1週間分


# ═══════════════════════════════════════════
# 1. データ読み込み
# ═══════════════════════════════════════════
def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_data():
    depot_rows = load_csv(DATA_DIR / "depot.csv")
    depot = {
        "id": depot_rows[0]["id"],
        "name": depot_rows[0]["name"],
        "lat": float(depot_rows[0]["latitude"]),
        "lon": float(depot_rows[0]["longitude"]),
    }
    customers = []
    for r in load_csv(DATA_DIR / "customers.csv"):
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
    for r in load_csv(DATA_DIR / "vehicles.csv"):
        vehicles.append({
            "id": r["vehicle_id"],
            "capacity": float(r["capacity_kg"]),
            "max_hours": float(r["max_hours"]),
            "cost_per_km": float(r["cost_per_km"]),
        })
    return depot, customers, vehicles


# ═══════════════════════════════════════════
# 2. 距離/時間行列
# ═══════════════════════════════════════════
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def build_matrices(depot, customers):
    nodes = [depot] + customers
    n = len(nodes)
    dist = [[0.0] * n for _ in range(n)]
    ttime = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            d = haversine_km(nodes[i]["lat"], nodes[i]["lon"],
                             nodes[j]["lat"], nodes[j]["lon"]) * ROAD_FACTOR
            dist[i][j] = round(d, 2)
            ttime[i][j] = round(d / SPEED_KMH * 60, 2)
    return dist, ttime


def hhmm_to_min(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def min_to_hhmm(m):
    return f"{int(m) // 60:02d}:{int(m) % 60:02d}"


# ═══════════════════════════════════════════
# 3. バリデーション
# ═══════════════════════════════════════════
def validate(depot, customers, vehicles):
    errors = []
    warnings = []

    if not customers:
        errors.append("顧客データが空です")
    if not vehicles:
        errors.append("車両データが空です")

    total_demand = sum(c["demand"] for c in customers)
    total_cap_2trips = sum(v["capacity"] for v in vehicles) * 2
    if total_demand > total_cap_2trips:
        errors.append(f"2便でもカバー不可: 需要{total_demand}kg > 2便容量{total_cap_2trips}kg")

    max_cap = max(v["capacity"] for v in vehicles) if vehicles else 0
    for c in customers:
        if c["demand"] > max_cap:
            errors.append(f"{c['id']}: 需要{c['demand']}kg > 最大車両容量{max_cap}kg")

    for c in customers:
        tw_s = hhmm_to_min(c["tw_start"])
        tw_e = hhmm_to_min(c["tw_end"])
        if tw_e <= tw_s:
            errors.append(f"{c['id']}: 時間枠不正 {c['tw_start']}~{c['tw_end']}")

    # 東京圏チェック (35.5-35.8, 139.5-139.9)
    for c in customers:
        if not (35.0 <= c["lat"] <= 36.0 and 139.0 <= c["lon"] <= 140.5):
            warnings.append(f"{c['id']}: 座標が東京圏外 ({c['lat']}, {c['lon']})")

    for w in warnings:
        logger.warning(w)
    return errors


# ═══════════════════════════════════════════
# 4. AM/PM分割 + OR-Tools最適化
# ═══════════════════════════════════════════
def solve_ampm(depot, customers, vehicles, dist, ttime):
    from ortools.constraint_solver import routing_enums_pb2, pywrapcp

    mid_threshold = hhmm_to_min("12:00")
    am_cids = []
    pm_cids = []
    for ci, c in enumerate(customers):
        tw_mid = (hhmm_to_min(c["tw_start"]) + hhmm_to_min(c["tw_end"])) / 2
        if tw_mid <= mid_threshold:
            am_cids.append(ci)
        else:
            pm_cids.append(ci)

    # 全部AMならcapacityベースで分割
    if len(pm_cids) == 0:
        total_cap = sum(v["capacity"] for v in vehicles)
        sorted_cids = sorted(range(len(customers)),
                             key=lambda ci: hhmm_to_min(customers[ci]["tw_end"]))
        cum = 0
        am_cids = []
        pm_cids = []
        for ci in sorted_cids:
            if cum + customers[ci]["demand"] <= total_cap * 0.95:
                am_cids.append(ci)
                cum += customers[ci]["demand"]
            else:
                pm_cids.append(ci)

    logger.info(f"  AM: {len(am_cids)}件 ({sum(customers[ci]['demand'] for ci in am_cids):.0f}kg)")
    logger.info(f"  PM: {len(pm_cids)}件 ({sum(customers[ci]['demand'] for ci in pm_cids):.0f}kg)")

    def solve_subset(cids, depart_min, label):
        subset = [customers[ci] for ci in cids]
        n_c = len(subset)
        if n_c == 0:
            return []

        n_v = len(vehicles)
        nodes_ll = [(depot["lat"], depot["lon"])] + [(c["lat"], c["lon"]) for c in subset]
        n_nodes = len(nodes_ll)
        sub_dist = [[0.0] * n_nodes for _ in range(n_nodes)]
        sub_ttime = [[0.0] * n_nodes for _ in range(n_nodes)]
        for i in range(n_nodes):
            for j in range(n_nodes):
                if i == j:
                    continue
                d = haversine_km(nodes_ll[i][0], nodes_ll[i][1],
                                 nodes_ll[j][0], nodes_ll[j][1]) * ROAD_FACTOR
                sub_dist[i][j] = round(d, 2)
                sub_ttime[i][j] = round(d / SPEED_KMH * 60, 2)

        manager = pywrapcp.RoutingIndexManager(n_nodes, n_v, 0)
        routing = pywrapcp.RoutingModel(manager)

        def distance_cb(fi, ti):
            return int(sub_dist[manager.IndexToNode(fi)][manager.IndexToNode(ti)] * 1000)

        transit_cb = routing.RegisterTransitCallback(distance_cb)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_cb)

        def demand_cb(fi):
            node = manager.IndexToNode(fi)
            return 0 if node == 0 else int(subset[node - 1]["demand"])

        d_cb = routing.RegisterUnaryTransitCallback(demand_cb)
        caps = [int(v["capacity"]) for v in vehicles]
        routing.AddDimensionWithVehicleCapacity(d_cb, 0, caps, True, "Capacity")

        def time_cb(fi, ti):
            fn = manager.IndexToNode(fi)
            tn = manager.IndexToNode(ti)
            t = sub_ttime[fn][tn]
            s = 0 if fn == 0 else subset[fn - 1]["service_min"]
            return int(t + s)

        t_cb = routing.RegisterTransitCallback(time_cb)
        max_t = 24 * 60
        routing.AddDimension(t_cb, max_t, max_t, False, "Time")
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
        sp.time_limit.seconds = SOLVER_TIME_LIMIT

        solution = routing.SolveWithParameters(sp)
        if solution is None:
            logger.warning(f"  {label}: 解なし")
            return []

        routes = []
        for vi in range(n_v):
            rcids = []
            idx = routing.Start(vi)
            while not routing.IsEnd(idx):
                node = manager.IndexToNode(idx)
                if node > 0:
                    rcids.append(cids[node - 1])
                idx = solution.Value(routing.NextVar(idx))
            if rcids:
                routes.append({"vehicle_idx": vi, "customer_indices": rcids, "depart_min": depart_min})
        return routes

    am_routes = solve_subset(am_cids, hhmm_to_min(AM_DEPART), "AM")
    pm_routes = solve_subset(pm_cids, hhmm_to_min(PM_DEPART), "PM")
    return am_routes + pm_routes


# ═══════════════════════════════════════════
# 5. 結果検証
# ═══════════════════════════════════════════
def verify(routes, depot, customers, vehicles, dist, ttime):
    total_dist = 0.0
    total_cost = 0.0
    tw_violations = 0
    cap_violations = 0
    visited = set()

    for route in routes:
        vidx = route["vehicle_idx"]
        cids = route["customer_indices"]
        v = vehicles[vidx]
        load = sum(customers[ci]["demand"] for ci in cids)
        if load > v["capacity"]:
            cap_violations += 1

        cur_time = route.get("depart_min", hhmm_to_min(AM_DEPART))
        prev = 0
        rdist = 0.0
        for ci in cids:
            mi = ci + 1
            travel = ttime[prev][mi]
            arrive = cur_time + travel
            c = customers[ci]
            tw_s = hhmm_to_min(c["tw_start"])
            tw_e = hhmm_to_min(c["tw_end"])
            wait = max(0, tw_s - arrive)
            start_service = arrive + wait
            if start_service > tw_e:
                tw_violations += 1
            depart = start_service + c["service_min"]
            rdist += dist[prev][mi]
            visited.add(ci)
            prev = mi
            cur_time = depart

        rdist += dist[prev][0]
        total_dist += rdist
        total_cost += rdist * v["cost_per_km"]

    unvisited = [customers[i]["id"] for i in range(len(customers)) if i not in visited]
    return {
        "total_distance_km": round(total_dist, 2),
        "total_cost_yen": round(total_cost, 0),
        "tw_violations": tw_violations,
        "cap_violations": cap_violations,
        "visited_count": len(visited),
        "unvisited_count": len(unvisited),
        "unvisited": unvisited,
        "num_routes": len(routes),
    }


# ═══════════════════════════════════════════
# 6. 出力
# ═══════════════════════════════════════════
def export_results(routes, meta, customers, vehicles):
    # JSON ルートデータ
    json_path = RESULTS_DIR / f"routes_{TIMESTAMP}.json"
    export_data = {
        "timestamp": TIMESTAMP,
        "meta": meta,
        "routes": [],
    }
    for route in routes:
        v = vehicles[route["vehicle_idx"]]
        cids = route["customer_indices"]
        export_data["routes"].append({
            "vehicle": v["id"],
            "depart": min_to_hhmm(route.get("depart_min", hhmm_to_min(AM_DEPART))),
            "customers": [customers[ci]["id"] for ci in cids],
            "customer_names": [customers[ci]["name"] for ci in cids],
            "load_kg": sum(customers[ci]["demand"] for ci in cids),
            "capacity_kg": v["capacity"],
        })
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
    logger.info(f"ルートデータ出力: {json_path}")

    # テキスト配送指示書
    txt_path = RESULTS_DIR / f"route_sheet_{TIMESTAMP}.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"配送指示書 ({TIMESTAMP})\n")
        f.write("=" * 50 + "\n")
        for rd in export_data["routes"]:
            f.write(f"\n{rd['vehicle']} ({rd['depart']}出発) 積載: {rd['load_kg']:.0f}/{rd['capacity_kg']:.0f}kg\n")
            for i, (cid, name) in enumerate(zip(rd["customers"], rd["customer_names"]), 1):
                f.write(f"  {i}. {cid} {name}\n")
    logger.info(f"配送指示書出力: {txt_path}")

    # 古いファイルの削除
    for pattern in ["routes_*.json", "route_sheet_*.txt"]:
        files = sorted(RESULTS_DIR.glob(pattern))
        if len(files) > HISTORY_KEEP:
            for old in files[:-HISTORY_KEEP]:
                old.unlink()
                logger.info(f"古いファイル削除: {old.name}")


# ═══════════════════════════════════════════
# 7. フォールバック: 最近傍法
# ═══════════════════════════════════════════
def solve_nearest_neighbor_fallback(customers, vehicles, dist):
    logger.warning("フォールバック: 最近傍法を使用")
    n_c = len(customers)
    assigned = [False] * n_c
    routes = []
    for vidx, v in enumerate(vehicles):
        route_cids = []
        load = 0.0
        prev = 0
        while True:
            best_ci = None
            best_d = float("inf")
            for ci in range(n_c):
                if assigned[ci]:
                    continue
                if load + customers[ci]["demand"] > v["capacity"]:
                    continue
                d = dist[prev][ci + 1]
                if d < best_d:
                    best_d = d
                    best_ci = ci
            if best_ci is None:
                break
            assigned[best_ci] = True
            route_cids.append(best_ci)
            load += customers[best_ci]["demand"]
            prev = best_ci + 1
        routes.append({"vehicle_idx": vidx, "customer_indices": route_cids,
                        "depart_min": hhmm_to_min(AM_DEPART)})
    return routes


# ═══════════════════════════════════════════
# メイン
# ═══════════════════════════════════════════
def main():
    logger.info("=" * 50)
    logger.info("配送ルート最適化パイプライン 開始")
    logger.info("=" * 50)

    # Step 1: データ読み込み
    logger.info("[Step 1] データ読み込み")
    try:
        depot, customers, vehicles = load_data()
    except FileNotFoundError as e:
        logger.error(f"データファイルが見つかりません: {e}")
        sys.exit(1)
    logger.info(f"  デポ: {depot['name']}")
    logger.info(f"  顧客: {len(customers)}件, 車両: {len(vehicles)}台")
    logger.info(f"  総需要: {sum(c['demand'] for c in customers):.0f}kg, "
                f"1便容量: {sum(v['capacity'] for v in vehicles):.0f}kg")

    # Step 2: 距離行列
    logger.info("[Step 2] 距離行列構築")
    dist, ttime = build_matrices(depot, customers)

    # Step 3: バリデーション
    logger.info("[Step 3] バリデーション")
    errors = validate(depot, customers, vehicles)
    if errors:
        for err in errors:
            logger.error(f"  致命的エラー: {err}")
        logger.error("パイプライン中断")
        sys.exit(1)
    logger.info("  バリデーション OK")

    # Step 4: AM/PM分割最適化
    logger.info(f"[Step 4] AM/PM分割最適化 (time_limit={SOLVER_TIME_LIMIT}s/便)")
    routes = solve_ampm(depot, customers, vehicles, dist, ttime)

    if not routes:
        logger.warning("ソルバーが解を返しませんでした。フォールバック実行。")
        routes = solve_nearest_neighbor_fallback(customers, vehicles, dist)

    # Step 5: 結果検証
    logger.info("[Step 5] 結果検証")
    meta = verify(routes, depot, customers, vehicles, dist, ttime)
    logger.info(f"  総距離: {meta['total_distance_km']}km")
    logger.info(f"  総コスト: {meta['total_cost_yen']:.0f}円")
    logger.info(f"  訪問: {meta['visited_count']}/{len(customers)}件")
    logger.info(f"  時間枠違反: {meta['tw_violations']}件")
    logger.info(f"  容量違反: {meta['cap_violations']}件")

    if meta["unvisited_count"] > 0:
        logger.warning(f"未訪問あり: {meta['unvisited']}")
    if meta["tw_violations"] > 0:
        logger.warning(f"時間枠違反あり: {meta['tw_violations']}件")

    # Step 6: 出力
    logger.info("[Step 6] 結果出力")
    export_results(routes, meta, customers, vehicles)

    logger.info("=" * 50)
    logger.info("配送ルート最適化パイプライン 完了")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
