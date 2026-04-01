#!/usr/bin/env python3
"""
施設配置最適化 — 全ワークフロー
=================================
関東エリアに倉庫を配置して30小売店にサービスするシナリオ。

1. データ分析（需要・距離・コスト構造の把握）
2. 3ベースライン: 全開設、貪欲法、PuLP UFL
3. 改善: CFL（容量制約付き）、P-median
4. 評価・比較・JSON出力
"""

from __future__ import annotations

import csv
import json
import math
import os
import random
import sys
import time
from typing import Any

# ---------------------------------------------------------------------------
# パス設定
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

# テンプレートのインポート
# BASE_DIR = .../workspace/examples/facility_location
# プロジェクトルート = BASE_DIR の3つ上
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(BASE_DIR)))
REFERENCE_DIR = os.path.join(PROJECT_ROOT, "reference")
sys.path.insert(0, REFERENCE_DIR)
from facility_location_template import (
    haversine_km,
    build_transport_cost_matrix,
    build_distance_matrix,
    solve_ufl,
    solve_cfl,
    solve_p_median,
    evaluate_solution,
)

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
COST_PER_KM = 150.0  # 円/km（月間輸送コスト係数）
ROAD_FACTOR = 1.3
SOLVER_TIME_LIMIT = 60
MAX_DISTANCE_KM = 50.0  # カバレッジ要件

# ---------------------------------------------------------------------------
# データ読み込み
# ---------------------------------------------------------------------------


def load_csv(path: str) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_data() -> tuple[list[dict], list[dict], list[dict]]:
    raw_facilities = load_csv(os.path.join(DATA_DIR, "candidates.csv"))
    facilities = []
    for r in raw_facilities:
        facilities.append({
            "facility_id": r["facility_id"],
            "name": r["name"],
            "latitude": float(r["latitude"]),
            "longitude": float(r["longitude"]),
            "fixed_cost": float(r["fixed_cost_monthly"]),
            "capacity": float(r["capacity_units"]),
        })

    raw_customers = load_csv(os.path.join(DATA_DIR, "customers.csv"))
    customers = []
    for r in raw_customers:
        customers.append({
            "customer_id": r["customer_id"],
            "name": r["name"],
            "latitude": float(r["latitude"]),
            "longitude": float(r["longitude"]),
            "demand": float(r["monthly_demand_units"]),
        })

    constraints = load_csv(os.path.join(DATA_DIR, "constraints.csv"))
    return facilities, customers, constraints


# ---------------------------------------------------------------------------
# 分析
# ---------------------------------------------------------------------------


def analyze_data(facilities, customers, distances, transport_costs):
    """データの基本統計を表示する。"""
    print("=" * 70)
    print("Phase 1: データ分析")
    print("=" * 70)

    total_demand = sum(c["demand"] for c in customers)
    total_capacity = sum(f["capacity"] for f in facilities)
    total_fixed = sum(f["fixed_cost"] for f in facilities)

    print(f"\n■ 問題規模")
    print(f"  候補施設数: {len(facilities)}")
    print(f"  顧客数:     {len(customers)}")
    print(f"  変数数:     y={len(facilities)}, x={len(facilities)*len(customers)} "
          f"(合計 {len(facilities) + len(facilities)*len(customers)})")

    print(f"\n■ 需要・容量バランス")
    print(f"  総需要:     {total_demand:,.0f} units/月")
    print(f"  総容量:     {total_capacity:,.0f} units/月")
    print(f"  需要/容量比: {total_demand/total_capacity:.3f}")
    if total_demand > total_capacity:
        print(f"  *** 警告: 総需要 > 総容量（全施設を開設しても不足）***")
    else:
        print(f"  余裕:      {total_capacity - total_demand:,.0f} units")

    print(f"\n■ 固定費")
    costs = [f["fixed_cost"] for f in facilities]
    print(f"  最小: {min(costs):>12,.0f} 円/月 ({min(facilities, key=lambda x: x['fixed_cost'])['name']})")
    print(f"  最大: {max(costs):>12,.0f} 円/月 ({max(facilities, key=lambda x: x['fixed_cost'])['name']})")
    print(f"  合計: {total_fixed:>12,.0f} 円/月（全施設開設時）")

    print(f"\n■ 距離分布")
    all_dists = []
    for c in customers:
        min_dist = min(
            distances[(f["facility_id"], c["customer_id"])]
            for f in facilities
        )
        all_dists.append((c["customer_id"], c["name"], min_dist))

    all_dists.sort(key=lambda x: x[2], reverse=True)
    avg_min_dist = sum(d[2] for d in all_dists) / len(all_dists)
    max_min_dist = all_dists[0]
    coverage = sum(1 for d in all_dists if d[2] <= MAX_DISTANCE_KM)

    print(f"  各顧客の最寄り施設までの距離（全候補から）:")
    print(f"    平均: {avg_min_dist:.1f} km")
    print(f"    最大: {max_min_dist[2]:.1f} km ({max_min_dist[1]})")
    print(f"    {MAX_DISTANCE_KM}km以内カバレッジ: {coverage}/{len(customers)} "
          f"({coverage/len(customers)*100:.0f}%)")

    if coverage < len(customers):
        print(f"\n  *** 50km超の顧客（要注意）:")
        for cid, name, dist in all_dists:
            if dist > MAX_DISTANCE_KM:
                print(f"      {name}: 最寄り {dist:.1f} km")

    return {
        "total_demand": total_demand,
        "total_capacity": total_capacity,
        "total_fixed_cost": total_fixed,
        "avg_min_distance": round(avg_min_dist, 1),
        "max_min_distance": round(max_min_dist[2], 1),
        "coverage_50km": coverage,
    }


# ---------------------------------------------------------------------------
# ベースライン1: 全施設開設
# ---------------------------------------------------------------------------


def baseline_open_all(facilities, customers, fixed_costs, transport_costs, distances,
                      capacities, demands):
    """全施設を開設し、各顧客を最寄りの施設に割り当てる。"""
    print("\n" + "=" * 70)
    print("Baseline 1: 全施設開設 + 最寄り割当")
    print("=" * 70)

    opened = [f["facility_id"] for f in facilities]
    assignments = {}
    for c in customers:
        cid = c["customer_id"]
        best_f = min(opened, key=lambda f: distances[(f, cid)])
        assignments[cid] = best_f

    result = {
        "status": "Heuristic",
        "objective": None,
        "opened": opened,
        "assignments": assignments,
        "solve_time": 0.0,
    }

    metrics = evaluate_solution(
        result, facilities, customers, fixed_costs, transport_costs,
        distances=distances, capacities=capacities, demands=demands,
    )
    result["objective"] = metrics["total_cost"]

    _print_result("全施設開設", result, metrics)
    return result, metrics


# ---------------------------------------------------------------------------
# ベースライン2: 貪欲法（コスト削減量が大きい施設から順に追加）
# ---------------------------------------------------------------------------


def baseline_greedy(facilities, customers, fixed_costs, transport_costs, distances,
                    capacities, demands):
    """貪欲法: 施設を1つずつ追加し、コスト削減が最大の施設を選ぶ。"""
    print("\n" + "=" * 70)
    print("Baseline 2: 貪欲法（逐次追加）")
    print("=" * 70)

    t0 = time.time()
    fids = [f["facility_id"] for f in facilities]
    cids = [c["customer_id"] for c in customers]

    opened: list[str] = []
    best_cost = float("inf")

    while len(opened) < len(fids):
        best_add = None
        best_add_cost = float("inf")

        for f in fids:
            if f in opened:
                continue
            trial = opened + [f]
            # 各顧客を最寄りの開設施設に割当
            trial_cost = sum(fixed_costs[ff] for ff in trial)
            for cid in cids:
                min_tc = min(transport_costs[(ff, cid)] for ff in trial)
                trial_cost += min_tc
            if trial_cost < best_add_cost:
                best_add_cost = trial_cost
                best_add = f

        if best_add_cost < best_cost:
            opened.append(best_add)
            best_cost = best_add_cost
            print(f"  追加: {best_add} → 総コスト {best_cost:,.0f} 円 "
                  f"(施設数: {len(opened)})")
        else:
            break

    # 最終割当
    assignments = {}
    for cid in cids:
        best_f = min(opened, key=lambda f: transport_costs[(f, cid)])
        assignments[cid] = best_f

    solve_time = time.time() - t0

    result = {
        "status": "Greedy",
        "objective": best_cost,
        "opened": opened,
        "assignments": assignments,
        "solve_time": round(solve_time, 2),
    }

    metrics = evaluate_solution(
        result, facilities, customers, fixed_costs, transport_costs,
        distances=distances, capacities=capacities, demands=demands,
    )

    _print_result("貪欲法", result, metrics)
    return result, metrics


# ---------------------------------------------------------------------------
# ベースライン3: PuLP UFL ソルバー
# ---------------------------------------------------------------------------


def baseline_solver_ufl(facilities, customers, fixed_costs, transport_costs, distances,
                        capacities, demands):
    """PuLP UFL ソルバー。"""
    print("\n" + "=" * 70)
    print("Baseline 3: PuLP UFL ソルバー")
    print("=" * 70)

    result = solve_ufl(
        facilities, customers, fixed_costs, transport_costs,
        time_limit=SOLVER_TIME_LIMIT,
    )

    metrics = evaluate_solution(
        result, facilities, customers, fixed_costs, transport_costs,
        distances=distances, capacities=capacities, demands=demands,
    )

    _print_result("UFL ソルバー", result, metrics)
    return result, metrics


# ---------------------------------------------------------------------------
# 改善1: CFL（容量制約付き）
# ---------------------------------------------------------------------------


def improve_cfl(facilities, customers, fixed_costs, transport_costs, distances,
                capacities, demands):
    """CFL ソルバー（容量制約付き）。"""
    print("\n" + "=" * 70)
    print("Improve 1: CFL ソルバー（容量制約付き）")
    print("=" * 70)

    result = solve_cfl(
        facilities, customers, fixed_costs, transport_costs,
        capacities, demands, time_limit=SOLVER_TIME_LIMIT,
    )

    metrics = evaluate_solution(
        result, facilities, customers, fixed_costs, transport_costs,
        distances=distances, capacities=capacities, demands=demands,
    )

    _print_result("CFL ソルバー", result, metrics)
    return result, metrics


# ---------------------------------------------------------------------------
# 改善2: P-median（施設数を変えて感度分析）
# ---------------------------------------------------------------------------


def improve_p_median(facilities, customers, fixed_costs, transport_costs, distances,
                     capacities, demands):
    """P-median で P=3,4,5 を比較。"""
    print("\n" + "=" * 70)
    print("Improve 2: P-median（施設数の感度分析）")
    print("=" * 70)

    results = {}
    for p in [3, 4, 5]:
        print(f"\n--- P = {p} ---")
        result = solve_p_median(
            facilities, customers, distances, p=p,
            time_limit=SOLVER_TIME_LIMIT,
        )
        metrics = evaluate_solution(
            result, facilities, customers, fixed_costs, transport_costs,
            distances=distances, capacities=capacities, demands=demands,
        )
        _print_result(f"P-median (P={p})", result, metrics)
        results[p] = {"result": result, "metrics": metrics}

    return results


# ---------------------------------------------------------------------------
# カバレッジ制約付きCFL
# ---------------------------------------------------------------------------


def improve_cfl_with_coverage(facilities, customers, fixed_costs, transport_costs,
                              distances, capacities, demands):
    """CFL + 最大距離制約（50km以内）。"""
    print("\n" + "=" * 70)
    print("Improve 3: CFL + カバレッジ制約（50km以内）")
    print("=" * 70)

    import pulp
    from facility_location_template import _get_solver

    fids = [f["facility_id"] for f in facilities]
    cids = [c["customer_id"] for c in customers]

    prob = pulp.LpProblem("CFL_coverage", pulp.LpMinimize)

    y = {f: pulp.LpVariable(f"y_{f}", cat="Binary") for f in fids}
    x = {(f, c): pulp.LpVariable(f"x_{f}_{c}", cat="Binary")
         for f in fids for c in cids}

    # 目的関数
    prob += (
        pulp.lpSum(fixed_costs[f] * y[f] for f in fids)
        + pulp.lpSum(transport_costs[(f, c)] * x[(f, c)] for f in fids for c in cids)
    )

    # 制約1: 各顧客はちょうど1施設に割当
    for c in cids:
        prob += pulp.lpSum(x[(f, c)] for f in fids) == 1, f"assign_{c}"

    # 制約2: 開設施設からのみサービス可能
    for f in fids:
        for c in cids:
            prob += x[(f, c)] <= y[f], f"open_{f}_{c}"

    # 制約3: 容量制約
    for f in fids:
        prob += (
            pulp.lpSum(demands[c] * x[(f, c)] for c in cids) <= capacities[f] * y[f],
            f"cap_{f}",
        )

    # 制約4: カバレッジ制約（50km超の割当を禁止）
    for f in fids:
        for c in cids:
            if distances[(f, c)] > MAX_DISTANCE_KM:
                prob += x[(f, c)] == 0, f"cover_{f}_{c}"

    # 制約5: 最大5施設
    prob += pulp.lpSum(y[f] for f in fids) <= 5, "max_facilities"

    solver = _get_solver(SOLVER_TIME_LIMIT)
    t0 = time.time()
    prob.solve(solver)
    solve_time = time.time() - t0

    opened = [f for f in fids if pulp.value(y[f]) > 0.5]
    assignments = {}
    for c in cids:
        for f in fids:
            if pulp.value(x[(f, c)]) > 0.5:
                assignments[c] = f
                break

    result = {
        "status": pulp.LpStatus[prob.status],
        "objective": pulp.value(prob.objective),
        "opened": opened,
        "assignments": assignments,
        "solve_time": round(solve_time, 2),
    }

    metrics = evaluate_solution(
        result, facilities, customers, fixed_costs, transport_costs,
        distances=distances, capacities=capacities, demands=demands,
    )

    _print_result("CFL + カバレッジ", result, metrics)
    return result, metrics


# ---------------------------------------------------------------------------
# 表示ヘルパー
# ---------------------------------------------------------------------------


def _print_result(label: str, result: dict, metrics: dict):
    """結果を整形表示する。"""
    print(f"\n  [{label}]")
    print(f"  ステータス:   {result['status']}")
    print(f"  総コスト:     {metrics['total_cost']:>12,.0f} 円/月")
    print(f"  　固定費:     {metrics['fixed_cost']:>12,.0f} 円/月")
    print(f"  　輸送費:     {metrics['transport_cost']:>12,.0f} 円/月")
    print(f"  開設施設数:   {metrics['num_opened']}")
    print(f"  開設施設:     {metrics['opened_facilities']}")
    print(f"  割当顧客数:   {metrics['num_customers']}/{len(result['assignments']) + len(metrics['unassigned_customers'])}")
    if metrics["distance_stats"]:
        ds = metrics["distance_stats"]
        print(f"  平均距離:     {ds['avg_distance_km']:.1f} km")
        print(f"  最大距離:     {ds['max_distance_km']:.1f} km")
    if metrics["capacity_violations"]:
        print(f"  容量違反:     {len(metrics['capacity_violations'])}件")
        for v in metrics["capacity_violations"]:
            print(f"    - {v}")
    if metrics["utilization"]:
        print(f"  稼働率:")
        for fid, u in metrics["utilization"].items():
            bar = "#" * int(u["ratio"] * 20) + "." * (20 - int(u["ratio"] * 20))
            print(f"    {fid}: [{bar}] {u['ratio']*100:.0f}% "
                  f"({u['used']:.0f}/{u['capacity']:.0f})")
    print(f"  求解時間:     {result['solve_time']}秒")


# ---------------------------------------------------------------------------
# 結果保存
# ---------------------------------------------------------------------------


def save_results(all_results: dict[str, Any]):
    """全結果をJSONで保存する。"""
    out_path = os.path.join(RESULTS_DIR, "all_results.json")

    # datetime等をシリアライズ可能にする
    def default(o):
        if hasattr(o, "__dict__"):
            return str(o)
        return o

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=default)
    print(f"\n結果を保存: {out_path}")


# ---------------------------------------------------------------------------
# 比較サマリ
# ---------------------------------------------------------------------------


def print_comparison(all_metrics: dict[str, dict]):
    """全手法の比較テーブルを表示する。"""
    print("\n" + "=" * 70)
    print("比較サマリ")
    print("=" * 70)

    header = f"{'手法':<28} {'総コスト':>12} {'固定費':>10} {'輸送費':>10} {'施設数':>5} {'平均距離':>8} {'最大距離':>8} {'容量違反':>6}"
    print(header)
    print("-" * len(header))

    for label, m in all_metrics.items():
        ds = m.get("distance_stats", {})
        avg_d = f"{ds.get('avg_distance_km', 0):.1f}" if ds else "-"
        max_d = f"{ds.get('max_distance_km', 0):.1f}" if ds else "-"
        cv = len(m.get("capacity_violations", []))
        print(f"{label:<28} {m['total_cost']:>12,.0f} {m['fixed_cost']:>10,.0f} "
              f"{m['transport_cost']:>10,.0f} {m['num_opened']:>5} "
              f"{avg_d:>8} {max_d:>8} {cv:>6}")


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------


def main():
    print("施設配置最適化 — 関東エリア倉庫配置")
    print("対象: 10候補地 → 30小売店へのサービス")
    print()

    # データ読み込み
    facilities, customers, constraints = load_data()

    # 辞書の作成
    fixed_costs = {f["facility_id"]: f["fixed_cost"] for f in facilities}
    capacities = {f["facility_id"]: f["capacity"] for f in facilities}
    demands = {c["customer_id"]: c["demand"] for c in customers}

    # 距離・コスト行列
    distances = build_distance_matrix(facilities, customers, road_factor=ROAD_FACTOR)
    transport_costs = build_transport_cost_matrix(
        facilities, customers, cost_per_km=COST_PER_KM, road_factor=ROAD_FACTOR,
    )

    # Phase 1: データ分析
    analysis = analyze_data(facilities, customers, distances, transport_costs)

    # Phase 2: 3ベースライン
    all_results = {}
    all_metrics = {}

    r, m = baseline_open_all(facilities, customers, fixed_costs, transport_costs,
                             distances, capacities, demands)
    all_results["open_all"] = r
    all_metrics["1. 全施設開設"] = m

    r, m = baseline_greedy(facilities, customers, fixed_costs, transport_costs,
                           distances, capacities, demands)
    all_results["greedy"] = r
    all_metrics["2. 貪欲法"] = m

    r, m = baseline_solver_ufl(facilities, customers, fixed_costs, transport_costs,
                               distances, capacities, demands)
    all_results["ufl"] = r
    all_metrics["3. UFL ソルバー"] = m

    # Phase 3: 改善
    r, m = improve_cfl(facilities, customers, fixed_costs, transport_costs,
                       distances, capacities, demands)
    all_results["cfl"] = r
    all_metrics["4. CFL ソルバー"] = m

    pmed_results = improve_p_median(facilities, customers, fixed_costs, transport_costs,
                                    distances, capacities, demands)
    for p, pr in pmed_results.items():
        all_results[f"p_median_{p}"] = pr["result"]
        all_metrics[f"5. P-median (P={p})"] = pr["metrics"]

    r, m = improve_cfl_with_coverage(facilities, customers, fixed_costs, transport_costs,
                                     distances, capacities, demands)
    all_results["cfl_coverage"] = r
    all_metrics["6. CFL+カバレッジ"] = m

    # 比較
    print_comparison(all_metrics)

    # 保存
    # シリアライズ用にresultからutilizationのfloatを調整
    serializable = {}
    for k, v in all_results.items():
        sv = dict(v)
        if "utilization" in sv and sv["utilization"]:
            sv["utilization"] = {
                fid: {kk: round(vv, 3) if isinstance(vv, float) else vv
                      for kk, vv in udict.items()}
                for fid, udict in sv["utilization"].items()
            }
        serializable[k] = sv

    save_results({"analysis": analysis, "results": serializable, "metrics": all_metrics})
    print("\n完了")


if __name__ == "__main__":
    main()
