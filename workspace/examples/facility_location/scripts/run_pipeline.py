#!/usr/bin/env python3
"""施設配置最適化 -- 本番パイプライン

実行頻度: 四半期 / オンデマンド
入力:     data/candidates.csv, data/customers.csv, data/constraints.csv
出力:     results/facility_plan_YYYYMMDD_HHMMSS.json
ログ:     log/run_YYYYMMDD_HHMMSS.log
"""

import csv
import json
import logging
import math
import sys
import time
from datetime import datetime
from pathlib import Path

# --- パス設定 ---
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = BASE_DIR / "results"
LOG_DIR = BASE_DIR / "log"
RESULTS_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

# --- ロガー ---
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

# --- 定数 ---
COST_PER_KM = 150.0
ROAD_FACTOR = 1.3
SOLVER_TIME_LIMIT = 60
MAX_DISTANCE_KM = 50.0
HISTORY_KEEP = 10

# --- テンプレート読み込み ---
PROJECT_ROOT = BASE_DIR.parents[2]
REFERENCE_DIR = PROJECT_ROOT / "reference"
sys.path.insert(0, str(REFERENCE_DIR))
from facility_location_template import (
    build_distance_matrix,
    build_transport_cost_matrix,
    evaluate_solution,
    solve_cfl,
    solve_ufl,
)


# =========================================================
# 1. データ読み込み
# =========================================================
def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_data():
    raw_fac = load_csv(DATA_DIR / "candidates.csv")
    facilities = []
    for r in raw_fac:
        facilities.append({
            "facility_id": r["facility_id"],
            "name": r["name"],
            "latitude": float(r["latitude"]),
            "longitude": float(r["longitude"]),
            "fixed_cost": float(r["fixed_cost_monthly"]),
            "capacity": float(r["capacity_units"]),
        })

    raw_cust = load_csv(DATA_DIR / "customers.csv")
    customers = []
    for r in raw_cust:
        customers.append({
            "customer_id": r["customer_id"],
            "name": r["name"],
            "latitude": float(r["latitude"]),
            "longitude": float(r["longitude"]),
            "demand": float(r["monthly_demand_units"]),
        })

    constraints = load_csv(DATA_DIR / "constraints.csv")
    return facilities, customers, constraints


# =========================================================
# 2. バリデーション
# =========================================================
def validate(facilities, customers):
    errors = []
    warnings = []

    if not facilities:
        errors.append("候補施設データが空です")
    if not customers:
        errors.append("顧客データが空です")

    for f in facilities:
        if f["capacity"] <= 0:
            errors.append(f"{f['facility_id']}: 容量が0以下 ({f['capacity']})")
        if f["fixed_cost"] <= 0:
            errors.append(f"{f['facility_id']}: 固定費が0以下 ({f['fixed_cost']})")
        if not (35.0 <= f["latitude"] <= 37.0 and 138.5 <= f["longitude"] <= 141.0):
            warnings.append(f"{f['facility_id']}: 座標が関東圏外 ({f['latitude']}, {f['longitude']})")

    for c in customers:
        if c["demand"] <= 0:
            errors.append(f"{c['customer_id']}: 需要が0以下 ({c['demand']})")
        if not (35.0 <= c["latitude"] <= 37.0 and 138.5 <= c["longitude"] <= 141.0):
            warnings.append(f"{c['customer_id']}: 座標が関東圏外 ({c['latitude']}, {c['longitude']})")

    total_demand = sum(c["demand"] for c in customers)
    total_capacity = sum(f["capacity"] for f in facilities)
    if total_demand > total_capacity:
        errors.append(
            f"総需要({total_demand:.0f}) > 総容量({total_capacity:.0f}): "
            "全施設を開設しても需要を賄えません"
        )

    for w in warnings:
        logger.warning(w)
    return errors


# =========================================================
# 3. CFL ソルバー実行
# =========================================================
def run_cfl(facilities, customers, fixed_costs, transport_costs,
            capacities, demands):
    logger.info("  CFL ソルバー実行中 (time_limit=%ds)...", SOLVER_TIME_LIMIT)
    result = solve_cfl(
        facilities, customers, fixed_costs, transport_costs,
        capacities, demands, time_limit=SOLVER_TIME_LIMIT,
    )
    return result


# =========================================================
# 4. UFL フォールバック
# =========================================================
def run_ufl_fallback(facilities, customers, fixed_costs, transport_costs):
    logger.warning("フォールバック: UFL ソルバー（容量制約なし）を実行")
    result = solve_ufl(
        facilities, customers, fixed_costs, transport_costs,
        time_limit=SOLVER_TIME_LIMIT,
    )
    return result


# =========================================================
# 5. 結果検証
# =========================================================
def verify(result, facilities, customers, fixed_costs, transport_costs,
           distances, capacities, demands):
    metrics = evaluate_solution(
        result, facilities, customers, fixed_costs, transport_costs,
        distances=distances, capacities=capacities, demands=demands,
    )

    issues = []

    # 全顧客が割当されているか
    if metrics["unassigned_customers"]:
        issues.append(f"未割当顧客: {metrics['unassigned_customers']}")

    # 容量違反
    if metrics["capacity_violations"]:
        for v in metrics["capacity_violations"]:
            issues.append(f"容量違反: {v}")

    # カバレッジ
    if metrics["distance_stats"]:
        ds = metrics["distance_stats"]
        coverage_count = sum(
            1 for c, f in result["assignments"].items()
            if distances[(f, c)] <= MAX_DISTANCE_KM
        )
        metrics["coverage_50km"] = coverage_count
        metrics["coverage_50km_pct"] = round(
            coverage_count / len(customers) * 100, 1
        )
        if coverage_count < len(customers):
            issues.append(
                f"50kmカバレッジ: {coverage_count}/{len(customers)} "
                f"({metrics['coverage_50km_pct']}%)"
            )

    return metrics, issues


# =========================================================
# 6. 出力
# =========================================================
def export_results(result, metrics, facilities, customers):
    fac_map = {f["facility_id"]: f for f in facilities}
    cust_map = {c["customer_id"]: c for c in customers}

    plan = {
        "timestamp": TIMESTAMP,
        "solver_status": result["status"],
        "summary": {
            "total_cost": metrics["total_cost"],
            "fixed_cost": metrics["fixed_cost"],
            "transport_cost": metrics["transport_cost"],
            "num_opened": metrics["num_opened"],
            "num_customers": metrics["num_customers"],
        },
        "opened_facilities": [],
        "assignments": [],
    }

    for fid in result["opened"]:
        f = fac_map[fid]
        util = metrics["utilization"].get(fid, {})
        plan["opened_facilities"].append({
            "facility_id": fid,
            "name": f["name"],
            "fixed_cost": f["fixed_cost"],
            "capacity": f["capacity"],
            "used": util.get("used", 0),
            "utilization_pct": round(util.get("ratio", 0) * 100, 1),
        })

    for cid, fid in result["assignments"].items():
        c = cust_map[cid]
        plan["assignments"].append({
            "customer_id": cid,
            "customer_name": c["name"],
            "assigned_facility": fid,
            "facility_name": fac_map[fid]["name"],
            "demand": c["demand"],
        })

    if metrics.get("distance_stats"):
        plan["distance_stats"] = metrics["distance_stats"]
    if "coverage_50km" in metrics:
        plan["coverage_50km"] = metrics["coverage_50km"]

    json_path = RESULTS_DIR / f"facility_plan_{TIMESTAMP}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    logger.info("施設計画出力: %s", json_path)

    # 古いファイルの削除
    files = sorted(RESULTS_DIR.glob("facility_plan_*.json"))
    if len(files) > HISTORY_KEEP:
        for old in files[:-HISTORY_KEEP]:
            old.unlink()
            logger.info("古いファイル削除: %s", old.name)

    return json_path


# =========================================================
# メイン
# =========================================================
def main():
    logger.info("=" * 50)
    logger.info("施設配置最適化パイプライン 開始")
    logger.info("=" * 50)

    # Step 1: データ読み込み
    logger.info("[Step 1] データ読み込み")
    try:
        facilities, customers, constraints = load_data()
    except FileNotFoundError as e:
        logger.error("データファイルが見つかりません: %s", e)
        sys.exit(1)
    logger.info("  候補施設: %d, 顧客: %d", len(facilities), len(customers))
    logger.info("  総需要: %.0f, 総容量: %.0f",
                sum(c["demand"] for c in customers),
                sum(f["capacity"] for f in facilities))

    # Step 2: バリデーション
    logger.info("[Step 2] バリデーション")
    errors = validate(facilities, customers)
    if errors:
        for err in errors:
            logger.error("  致命的エラー: %s", err)
        logger.error("パイプライン中断")
        sys.exit(1)
    logger.info("  バリデーション OK")

    # 辞書の作成
    fixed_costs = {f["facility_id"]: f["fixed_cost"] for f in facilities}
    capacities = {f["facility_id"]: f["capacity"] for f in facilities}
    demands = {c["customer_id"]: c["demand"] for c in customers}
    distances = build_distance_matrix(facilities, customers, road_factor=ROAD_FACTOR)
    transport_costs = build_transport_cost_matrix(
        facilities, customers, cost_per_km=COST_PER_KM, road_factor=ROAD_FACTOR,
    )

    # Step 3: CFL ソルバー
    logger.info("[Step 3] CFL ソルバー実行")
    t0 = time.time()
    result = run_cfl(facilities, customers, fixed_costs, transport_costs,
                     capacities, demands)
    elapsed = time.time() - t0
    logger.info("  ステータス: %s (%.1f秒)", result["status"], elapsed)

    # CFL が infeasible なら UFL フォールバック
    if result["status"] != "Optimal":
        logger.warning("  CFL が最適解を返しませんでした (status=%s)", result["status"])
        t0 = time.time()
        result = run_ufl_fallback(facilities, customers, fixed_costs, transport_costs)
        elapsed = time.time() - t0
        logger.info("  UFL ステータス: %s (%.1f秒)", result["status"], elapsed)
        if result["status"] != "Optimal":
            logger.error("UFL も失敗。パイプライン中断。")
            sys.exit(1)

    # Step 4: 結果検証
    logger.info("[Step 4] 結果検証")
    metrics, issues = verify(
        result, facilities, customers, fixed_costs, transport_costs,
        distances, capacities, demands,
    )
    logger.info("  開設施設: %s", metrics["opened_facilities"])
    logger.info("  総コスト: %.0f 円/月", metrics["total_cost"])
    logger.info("  固定費: %.0f, 輸送費: %.0f",
                metrics["fixed_cost"], metrics["transport_cost"])
    if metrics.get("distance_stats"):
        ds = metrics["distance_stats"]
        logger.info("  平均距離: %.1fkm, 最大距離: %.1fkm",
                    ds["avg_distance_km"], ds["max_distance_km"])
    if "coverage_50km" in metrics:
        logger.info("  50kmカバレッジ: %d/%d (%.1f%%)",
                    metrics["coverage_50km"], len(customers),
                    metrics["coverage_50km_pct"])
    if metrics.get("capacity_violations"):
        logger.warning("  容量違反: %d件", len(metrics["capacity_violations"]))
    else:
        logger.info("  容量違反: なし")
    for issue in issues:
        logger.warning("  注意: %s", issue)

    # Step 5: 出力
    logger.info("[Step 5] 結果出力")
    json_path = export_results(result, metrics, facilities, customers)

    logger.info("=" * 50)
    logger.info("施設配置最適化パイプライン 完了")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
