"""日次配送ルート最適化パイプライン — 本番運用スクリプト

毎朝6:00に実行し、当日の配送ルートを自動生成する。
cron: 0 6 * * * cd /path/to/project && python scripts/run_daily.py

パイプライン:
  1. データ取得 → 2. バリデーション → 3. 前処理(距離/時間行列)
  → 4. AM/PM分割+最適化 → 5. 検証 → 6. 出力
"""
from __future__ import annotations
import csv
import math
import json
import sys
import logging
from datetime import datetime
from pathlib import Path
from ortools.constraint_solver import routing_enums_pb2, pywrapcp

# ─── 設定 ───

DATA_DIR = Path(__file__).parent.parent / "data"
RESULTS_DIR = Path(__file__).parent.parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)
LOG_DIR = Path(__file__).parent.parent / "log"
LOG_DIR.mkdir(exist_ok=True)

SPEED_KMH = 30
ROAD_FACTOR = 1.3
DEPOT_START_MIN = 8 * 60  # 08:00
SOLVER_TIME_LIMIT = 60  # seconds per phase
HISTORY_KEEP = 14  # 過去2週間分の結果を保持

# AM/PM分割の閾値
AM_CUTOFF_END = 13 * 60    # tw_end <= 13:00 → AM便
PM_CUTOFF_START = 11 * 60  # tw_start >= 11:00 → PM便
OVERLAP_BOUNDARY = 9 * 60 + 30  # 重なりはtw_start <= 09:30ならAM

# ─── ロガー ───

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"run_{timestamp}.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ─── ユーティリティ ───

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a)) * ROAD_FACTOR


def build_matrices(depot, customers):
    locations = [depot] + customers
    n = len(locations)
    dist = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                dist[i][j] = int(haversine_km(
                    locations[i]["latitude"], locations[i]["longitude"],
                    locations[j]["latitude"], locations[j]["longitude"],
                ) * 1000)
    time_mat = [[int(dist[i][j] / 1000 / SPEED_KMH * 60) for j in range(n)] for i in range(n)]
    return dist, time_mat


# ─── Step 1: データ取得 ───

def load_data():
    log.info("Step 1: データ取得")
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

    log.info(f"  デポ: {depot['name']}, 顧客: {len(customers)}件, 車両: {len(vehicles)}台")
    return depot, customers, vehicles


# ─── Step 2: バリデーション ───

def validate(depot, customers, vehicles):
    log.info("Step 2: バリデーション")
    issues = {"critical": [], "warning": []}

    if not customers:
        issues["critical"].append("顧客データが空です")
    if not vehicles:
        issues["critical"].append("車両データが空です")

    total_demand = sum(c["demand_kg"] for c in customers)
    total_cap = sum(v["capacity_kg"] for v in vehicles)

    if total_demand > total_cap * 2:
        issues["critical"].append(
            f"需要{total_demand}kgが2便合計容量{total_cap * 2}kgを超過。配送不可能"
        )
    elif total_demand > total_cap:
        log.info(f"  需要{total_demand}kg > 1便容量{total_cap}kg → AM/PM分割が必要")

    # Coordinate sanity (Tokyo area: lat 35.5-35.8, lon 139.6-140.0)
    for c in customers:
        if not (35.5 < c["latitude"] < 35.9 and 139.5 < c["longitude"] < 140.1):
            issues["warning"].append(f"{c['customer_id']}: 座標が東京圏外 ({c['latitude']}, {c['longitude']})")

    # Max single item
    max_item = max(c["demand_kg"] for c in customers)
    max_veh_cap = max(v["capacity_kg"] for v in vehicles)
    if max_item > max_veh_cap:
        issues["critical"].append(
            f"顧客1件の需要{max_item}kgが最大車両容量{max_veh_cap}kgを超過"
        )

    for c in customers:
        if c["tw_end"] <= c["tw_start"]:
            issues["critical"].append(f"{c['customer_id']}: 時間枠が不正 ({c['tw_start']}-{c['tw_end']})")

    for level, msgs in issues.items():
        for msg in msgs:
            getattr(log, "error" if level == "critical" else "warning")(f"  [{level}] {msg}")

    if not issues["critical"] and not issues["warning"]:
        log.info("  バリデーション OK")

    return issues


# ─── Step 3: 前処理 (AM/PM分割) ───

def split_am_pm(customers):
    log.info("Step 3: AM/PM分割")
    am, pm = [], []
    for i, c in enumerate(customers):
        if c["tw_end"] <= AM_CUTOFF_END:
            am.append(i)
        elif c["tw_start"] >= PM_CUTOFF_START:
            pm.append(i)
        elif c["tw_start"] <= OVERLAP_BOUNDARY:
            am.append(i)
        else:
            pm.append(i)

    am_demand = sum(customers[i]["demand_kg"] for i in am)
    pm_demand = sum(customers[i]["demand_kg"] for i in pm)
    log.info(f"  AM: {len(am)}件 ({am_demand}kg), PM: {len(pm)}件 ({pm_demand}kg)")
    return am, pm


# ─── Step 4: 最適化 ───

def solve_phase(depot, customers_subset, vehicles, dist_matrix, time_matrix, label=""):
    n_loc = len(customers_subset) + 1
    n_veh = len(vehicles)

    if not customers_subset:
        log.info(f"  {label}: 顧客0件、スキップ")
        return [[] for _ in range(n_veh)]

    manager = pywrapcp.RoutingIndexManager(n_loc, n_veh, 0)
    routing = pywrapcp.RoutingModel(manager)

    def dist_cb(f, t):
        return dist_matrix[manager.IndexToNode(f)][manager.IndexToNode(t)]

    tcb = routing.RegisterTransitCallback(dist_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(tcb)

    def demand_cb(idx):
        node = manager.IndexToNode(idx)
        return 0 if node == 0 else customers_subset[node - 1]["demand_kg"]

    dcb = routing.RegisterUnaryTransitCallback(demand_cb)
    routing.AddDimensionWithVehicleCapacity(dcb, 0, [v["capacity_kg"] for v in vehicles], True, "Cap")

    def time_cb(f, t):
        fn, tn = manager.IndexToNode(f), manager.IndexToNode(t)
        travel = time_matrix[fn][tn]
        svc = customers_subset[fn - 1]["service_time_min"] if fn > 0 else 0
        return travel + svc

    ttcb = routing.RegisterTransitCallback(time_cb)
    routing.AddDimension(ttcb, 480, 1440, False, "Time")
    td = routing.GetDimensionOrDie("Time")

    for v in range(n_veh):
        td.CumulVar(routing.Start(v)).SetRange(DEPOT_START_MIN, DEPOT_START_MIN)
        td.CumulVar(routing.End(v)).SetRange(DEPOT_START_MIN, DEPOT_START_MIN + vehicles[v]["max_hours"] * 60)

    for ci in range(len(customers_subset)):
        node = manager.NodeToIndex(ci + 1)
        c = customers_subset[ci]
        td.CumulVar(node).SetRange(c["tw_start"], c["tw_end"])

    for ci in range(1, n_loc):
        routing.AddDisjunction([manager.NodeToIndex(ci)], 100000)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromSeconds(SOLVER_TIME_LIMIT)

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
        log.info(f"  {label}: 解探索成功 (obj={sol.ObjectiveValue()})")
    else:
        routes = [[] for _ in range(n_veh)]
        log.error(f"  {label}: 解が見つかりませんでした")

    return routes


def evaluate_phase(routes, depot, customers_subset, vehicles, dist_matrix, time_matrix):
    n_cust = len(customers_subset)
    visited = set()
    total_dist_m = 0
    total_cost = 0
    tw_viol = cap_viol = time_viol = 0
    details = []

    for v_idx, route in enumerate(routes):
        if v_idx >= len(vehicles):
            break
        veh = vehicles[v_idx]
        load, t, rd, prev = 0, DEPOT_START_MIN, 0, 0
        stops = []
        for ci in route:
            if ci < 1 or ci > n_cust:
                continue
            c = customers_subset[ci - 1]
            t += time_matrix[prev][ci]
            rd += dist_matrix[prev][ci]
            arrival = t
            if arrival < c["tw_start"]:
                t = c["tw_start"]; arrival = t
            if arrival > c["tw_end"]:
                tw_viol += 1
            t += c["service_time_min"]
            load += c["demand_kg"]
            visited.add(ci)
            stops.append({"id": c["customer_id"], "name": c["name"], "arrival": arrival, "tw_ok": arrival <= c["tw_end"], "load": load})
            prev = ci
        rd += dist_matrix[prev][0]
        t += time_matrix[prev][0]
        th = (t - DEPOT_START_MIN) / 60
        if load > veh["capacity_kg"]: cap_viol += 1
        if th > veh["max_hours"]: time_viol += 1
        rdk = rd / 1000
        total_dist_m += rd
        total_cost += rdk * veh["cost_per_km"]
        details.append({"vehicle": veh["vehicle_id"], "stops": len(stops), "load_kg": load, "cap_kg": veh["capacity_kg"], "dist_km": round(rdk, 1), "time_h": round(th, 2), "stop_list": stops})

    unvisited = [customers_subset[i - 1]["customer_id"] for i in range(1, n_cust + 1) if i not in visited]
    return {
        "feasible": tw_viol == 0 and cap_viol == 0 and time_viol == 0 and not unvisited,
        "dist_km": round(total_dist_m / 1000, 1), "cost_yen": round(total_cost),
        "tw_violations": tw_viol, "cap_violations": cap_viol, "time_violations": time_viol,
        "served": len(visited), "total": n_cust, "unvisited": unvisited,
        "routes": details,
    }


# ─── Step 5: 検証 ───

def verify(am_eval, pm_eval, customers):
    log.info("Step 5: 結果検証")
    total_served = am_eval["served"] + pm_eval["served"]
    total_dist = am_eval["dist_km"] + pm_eval["dist_km"]
    total_cost = am_eval["cost_yen"] + pm_eval["cost_yen"]
    all_tw = am_eval["tw_violations"] + pm_eval["tw_violations"]
    all_cap = am_eval["cap_violations"] + pm_eval["cap_violations"]
    feasible = am_eval["feasible"] and pm_eval["feasible"]

    result = {
        "feasible": feasible, "served": total_served, "total": len(customers),
        "dist_km": round(total_dist, 1), "cost_yen": total_cost,
        "tw_violations": all_tw, "cap_violations": all_cap,
    }

    if feasible:
        log.info(f"  検証OK: {total_served}/{len(customers)}件配送, {total_dist:.1f}km, ¥{total_cost}")
    else:
        problems = []
        if am_eval["unvisited"]:
            problems.append(f"AM未配送: {am_eval['unvisited']}")
        if pm_eval["unvisited"]:
            problems.append(f"PM未配送: {pm_eval['unvisited']}")
        if all_tw:
            problems.append(f"時間枠違反: {all_tw}件")
        if all_cap:
            problems.append(f"容量超過: {all_cap}件")
        log.error(f"  検証NG: {'; '.join(problems)}")

    return result


# ─── Step 6: 出力 ───

def export(am_eval, pm_eval, quality, vehicles):
    log.info("Step 6: 結果出力")

    output = {
        "timestamp": timestamp,
        "quality": quality,
        "am": am_eval,
        "pm": pm_eval,
    }

    out_file = RESULTS_DIR / f"routes_{timestamp}.json"
    with open(out_file, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    # Human-readable route sheet
    txt_file = RESULTS_DIR / f"route_sheet_{timestamp}.txt"
    with open(txt_file, "w") as f:
        f.write(f"配送ルート表 ({timestamp})\n")
        f.write("=" * 50 + "\n\n")
        for phase_name, ev in [("【AM便】", am_eval), ("【PM便】", pm_eval)]:
            f.write(f"{phase_name}\n")
            for rd in ev["routes"]:
                if not rd["stop_list"]:
                    continue
                f.write(f"\n  {rd['vehicle']}: {rd['load_kg']}/{rd['cap_kg']}kg, {rd['dist_km']}km\n")
                for s in rd["stop_list"]:
                    h, m = divmod(int(s["arrival"]), 60)
                    tw = "OK" if s["tw_ok"] else "遅延"
                    f.write(f"    {h:02d}:{m:02d} {s['id']} {s['name']} ({s['load']}kg) [{tw}]\n")
            f.write("\n")
        f.write(f"合計: {quality['dist_km']}km, ¥{quality['cost_yen']}, {quality['served']}/{quality['total']}件\n")

    log.info(f"  ルートデータ: {out_file}")
    log.info(f"  配送指示書: {txt_file}")

    # Cleanup old files
    for pattern in ["routes_*.json", "route_sheet_*.txt"]:
        old_files = sorted(RESULTS_DIR.glob(pattern), reverse=True)
        for old in old_files[HISTORY_KEEP:]:
            old.unlink()

    return txt_file


# ─── メイン ───

def main():
    log.info("=" * 50)
    log.info("日次配送ルート最適化パイプライン開始")
    log.info("=" * 50)

    # Step 1
    depot, customers, vehicles = load_data()

    # Step 2
    issues = validate(depot, customers, vehicles)
    if issues["critical"]:
        log.error("致命的な問題。中断します。")
        sys.exit(1)

    # Step 3
    am_idx, pm_idx = split_am_pm(customers)
    am_custs = [customers[i] for i in am_idx]
    pm_custs = [customers[i] for i in pm_idx]

    # Step 4
    log.info("Step 4: 最適化実行")

    am_dist, am_time = build_matrices(depot, am_custs)
    am_routes = solve_phase(depot, am_custs, vehicles, am_dist, am_time, "AM便")
    am_eval = evaluate_phase(am_routes, depot, am_custs, vehicles, am_dist, am_time)

    pm_dist, pm_time = build_matrices(depot, pm_custs)
    pm_routes = solve_phase(depot, pm_custs, vehicles, pm_dist, pm_time, "PM便")
    pm_eval = evaluate_phase(pm_routes, depot, pm_custs, vehicles, pm_dist, pm_time)

    # Step 5
    quality = verify(am_eval, pm_eval, customers)

    if not quality["feasible"]:
        log.error("Infeasible — フォールバック: 前回のルートを確認してください")
        # 本番では前回の解をロードするか人間にエスカレーション
        # ここでは出力して続行（参考情報として）

    # Step 6
    txt_file = export(am_eval, pm_eval, quality, vehicles)

    log.info("=" * 50)
    log.info(f"完了: {txt_file}")
    log.info("=" * 50)


if __name__ == "__main__":
    main()
