"""施設配置問題（Facility Location Problem）の定式化テンプレート。

倉庫・店舗・充電ステーション・基地局・病院など、
「どこに施設を開設し、各顧客をどの施設に割り当てるか」を決める問題全般に適用できる。

3つの定式化を提供する:
  - UFL (Uncapacitated Facility Location): 容量制約なし。固定費+輸送費の最小化。
  - CFL (Capacitated Facility Location): 容量制約付き。需要と供給のバランスを考慮。
  - P-median: 開設施設数を固定（P箇所）。距離（またはコスト）の合計を最小化。

使い方:
  1. このファイルをコピーして問題に合わせて修正
  2. 候補施設の座標・固定費・容量、顧客の座標・需要量を準備
  3. haversine_km() で距離行列を作成（またはAPI距離を利用）
  4. evaluate_solution() で解の品質を検証

典型的な利用フロー::

    # 距離行列を作成
    costs = build_transport_cost_matrix(facilities, customers, cost_per_km=150)

    # UFL で求解
    result = solve_ufl(facilities, customers, fixed_costs, costs, time_limit=60)

    # 評価
    metrics = evaluate_solution(result, facilities, customers, fixed_costs, costs)
"""

from __future__ import annotations

import logging
import math
from typing import Any

import pulp

logger = logging.getLogger(__name__)


# ===========================================================================
# ソルバー選択
# ===========================================================================


def _get_solver(time_limit: int) -> pulp.LpSolver:
    """利用可能なソルバーを選択する（HiGHS優先、なければCBC）。"""
    available = pulp.listSolvers(onlyAvailable=True)
    if "HiGHS_CMD" in available:
        return pulp.HiGHS_CMD(msg=0, timeLimit=time_limit)
    if "PULP_CBC_CMD" in available:
        return pulp.PULP_CBC_CMD(msg=0, timeLimit=time_limit)
    raise RuntimeError(f"利用可能なソルバーがありません: {available}")


# ===========================================================================
# ユーティリティ
# ===========================================================================


def haversine_km(
    lat1: float, lon1: float, lat2: float, lon2: float,
    road_factor: float = 1.3,
) -> float:
    """2点間のHaversine距離を計算する（km単位）。

    直線距離に道路係数を乗じて実走行距離を近似する。
    より正確な距離が必要な場合はGoogle Maps Distance Matrix API等に置き換えること。

    Args:
        lat1: 地点1の緯度（度）
        lon1: 地点1の経度（度）
        lat2: 地点2の緯度（度）
        lon2: 地点2の経度（度）
        road_factor: 道路係数（デフォルト1.3）

    Returns:
        2点間の推定道路距離（km）
    """
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a)) * road_factor


def build_transport_cost_matrix(
    facilities: list[dict[str, Any]],
    customers: list[dict[str, Any]],
    cost_per_km: float = 150.0,
    road_factor: float = 1.3,
) -> dict[tuple[str, str], float]:
    """施設-顧客間の輸送コスト行列を作成する。

    Args:
        facilities: 施設リスト。各要素に ``facility_id``, ``latitude``, ``longitude`` を含む。
        customers: 顧客リスト。各要素に ``customer_id``, ``latitude``, ``longitude`` を含む。
        cost_per_km: km当たりの輸送コスト（円/km）。
        road_factor: 道路係数。

    Returns:
        {(facility_id, customer_id): cost} の辞書。
    """
    costs: dict[tuple[str, str], float] = {}
    for f in facilities:
        for c in customers:
            dist = haversine_km(
                f["latitude"], f["longitude"],
                c["latitude"], c["longitude"],
                road_factor=road_factor,
            )
            costs[(f["facility_id"], c["customer_id"])] = dist * cost_per_km
    return costs


def build_distance_matrix(
    facilities: list[dict[str, Any]],
    customers: list[dict[str, Any]],
    road_factor: float = 1.3,
) -> dict[tuple[str, str], float]:
    """施設-顧客間の距離行列を作成する（km単位）。

    Args:
        facilities: 施設リスト。
        customers: 顧客リスト。
        road_factor: 道路係数。

    Returns:
        {(facility_id, customer_id): distance_km} の辞書。
    """
    distances: dict[tuple[str, str], float] = {}
    for f in facilities:
        for c in customers:
            distances[(f["facility_id"], c["customer_id"])] = haversine_km(
                f["latitude"], f["longitude"],
                c["latitude"], c["longitude"],
                road_factor=road_factor,
            )
    return distances


# ===========================================================================
# 1. Uncapacitated Facility Location (UFL)
# ===========================================================================


def solve_ufl(
    facilities: list[dict[str, Any]],
    customers: list[dict[str, Any]],
    fixed_costs: dict[str, float],
    transport_costs: dict[tuple[str, str], float],
    time_limit: int = 60,
) -> dict[str, Any]:
    """容量制約なし施設配置問題（UFL）を求解する。

    定式化:
      - 決定変数: y[f] ∈ {0,1} = 施設fを開設するか
      - 決定変数: x[f,c] ∈ {0,1} = 顧客cを施設fが担当するか
      - 最小化: Σ fixed_costs[f]*y[f] + Σ transport_costs[f,c]*x[f,c]
      - 制約1: 各顧客はちょうど1施設に割当（Σ_f x[f,c] = 1, ∀c）
      - 制約2: 開設した施設からのみサービス可能（x[f,c] ≤ y[f], ∀f,c）

    Args:
        facilities: 候補施設リスト。各要素に ``facility_id`` を含む。
        customers: 顧客リスト。各要素に ``customer_id`` を含む。
        fixed_costs: {facility_id: 固定費} の辞書。
        transport_costs: {(facility_id, customer_id): 輸送コスト} の辞書。
        time_limit: ソルバーの制限時間（秒）。

    Returns:
        結果辞書:
          - status: ソルバーのステータス
          - objective: 目的関数値（総コスト）
          - opened: 開設した施設のIDリスト
          - assignments: {customer_id: facility_id} の割当
          - solve_time: 求解時間（秒）
    """
    fids = [f["facility_id"] for f in facilities]
    cids = [c["customer_id"] for c in customers]

    prob = pulp.LpProblem("UFL", pulp.LpMinimize)

    # 変数
    y = {f: pulp.LpVariable(f"y_{f}", cat="Binary") for f in fids}
    x = {
        (f, c): pulp.LpVariable(f"x_{f}_{c}", cat="Binary")
        for f in fids
        for c in cids
    }

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

    # 求解
    solver = _get_solver(time_limit)
    import time as _time
    t0 = _time.time()
    prob.solve(solver)
    solve_time = _time.time() - t0

    # 結果の抽出
    opened = [f for f in fids if pulp.value(y[f]) > 0.5]
    assignments = {}
    for c in cids:
        for f in fids:
            if pulp.value(x[(f, c)]) > 0.5:
                assignments[c] = f
                break

    return {
        "status": pulp.LpStatus[prob.status],
        "objective": pulp.value(prob.objective),
        "opened": opened,
        "assignments": assignments,
        "solve_time": round(solve_time, 2),
    }


# ===========================================================================
# 2. Capacitated Facility Location (CFL)
# ===========================================================================


def solve_cfl(
    facilities: list[dict[str, Any]],
    customers: list[dict[str, Any]],
    fixed_costs: dict[str, float],
    transport_costs: dict[tuple[str, str], float],
    capacities: dict[str, float],
    demands: dict[str, float],
    time_limit: int = 60,
) -> dict[str, Any]:
    """容量制約付き施設配置問題（CFL）を求解する。

    UFLに加えて容量制約を追加:
      - 制約3: Σ_c demands[c]*x[f,c] ≤ capacities[f]*y[f], ∀f

    Args:
        facilities: 候補施設リスト。
        customers: 顧客リスト。
        fixed_costs: {facility_id: 固定費}。
        transport_costs: {(facility_id, customer_id): 輸送コスト}。
        capacities: {facility_id: 処理容量}。
        demands: {customer_id: 需要量}。
        time_limit: ソルバーの制限時間（秒）。

    Returns:
        結果辞書（UFLと同じ形式 + utilization情報）。
    """
    fids = [f["facility_id"] for f in facilities]
    cids = [c["customer_id"] for c in customers]

    prob = pulp.LpProblem("CFL", pulp.LpMinimize)

    # 変数
    y = {f: pulp.LpVariable(f"y_{f}", cat="Binary") for f in fids}
    x = {
        (f, c): pulp.LpVariable(f"x_{f}_{c}", cat="Binary")
        for f in fids
        for c in cids
    }

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

    # 求解
    solver = _get_solver(time_limit)
    import time as _time
    t0 = _time.time()
    prob.solve(solver)
    solve_time = _time.time() - t0

    # 結果の抽出
    opened = [f for f in fids if pulp.value(y[f]) > 0.5]
    assignments: dict[str, str] = {}
    for c in cids:
        for f in fids:
            if pulp.value(x[(f, c)]) > 0.5:
                assignments[c] = f
                break

    # 稼働率の計算
    utilization: dict[str, dict[str, float]] = {}
    for f in opened:
        used = sum(demands[c] for c, af in assignments.items() if af == f)
        utilization[f] = {
            "used": used,
            "capacity": capacities[f],
            "ratio": round(used / capacities[f], 3) if capacities[f] > 0 else 0.0,
        }

    return {
        "status": pulp.LpStatus[prob.status],
        "objective": pulp.value(prob.objective),
        "opened": opened,
        "assignments": assignments,
        "utilization": utilization,
        "solve_time": round(solve_time, 2),
    }


# ===========================================================================
# 3. P-median（P箇所に施設を開設して距離合計を最小化）
# ===========================================================================


def solve_p_median(
    facilities: list[dict[str, Any]],
    customers: list[dict[str, Any]],
    distances: dict[tuple[str, str], float],
    p: int,
    time_limit: int = 60,
) -> dict[str, Any]:
    """P-median問題を求解する。

    ちょうどP箇所の施設を開設し、全顧客から最寄り施設への距離合計を最小化する。
    固定費は考慮せず、カバレッジ（距離の公平性）を重視する場面で使う。

    定式化:
      - 最小化: Σ distances[f,c]*x[f,c]
      - 制約1: 各顧客はちょうど1施設に割当
      - 制約2: x[f,c] ≤ y[f]
      - 制約3: Σ_f y[f] = P（ちょうどP箇所を開設）

    Args:
        facilities: 候補施設リスト。
        customers: 顧客リスト。
        distances: {(facility_id, customer_id): 距離(km)}。
        p: 開設する施設数。
        time_limit: ソルバーの制限時間（秒）。

    Returns:
        結果辞書。
    """
    fids = [f["facility_id"] for f in facilities]
    cids = [c["customer_id"] for c in customers]

    if p > len(fids):
        raise ValueError(f"P={p} が候補施設数 {len(fids)} を超えています")

    prob = pulp.LpProblem("P_median", pulp.LpMinimize)

    # 変数
    y = {f: pulp.LpVariable(f"y_{f}", cat="Binary") for f in fids}
    x = {
        (f, c): pulp.LpVariable(f"x_{f}_{c}", cat="Binary")
        for f in fids
        for c in cids
    }

    # 目的関数: 距離合計の最小化
    prob += pulp.lpSum(
        distances[(f, c)] * x[(f, c)] for f in fids for c in cids
    )

    # 制約1: 各顧客はちょうど1施設に割当
    for c in cids:
        prob += pulp.lpSum(x[(f, c)] for f in fids) == 1, f"assign_{c}"

    # 制約2: 開設施設からのみサービス可能
    for f in fids:
        for c in cids:
            prob += x[(f, c)] <= y[f], f"open_{f}_{c}"

    # 制約3: ちょうどP箇所を開設
    prob += pulp.lpSum(y[f] for f in fids) == p, "p_facilities"

    # 求解
    solver = _get_solver(time_limit)
    import time as _time
    t0 = _time.time()
    prob.solve(solver)
    solve_time = _time.time() - t0

    # 結果の抽出
    opened = [f for f in fids if pulp.value(y[f]) > 0.5]
    assignments: dict[str, str] = {}
    for c in cids:
        for f in fids:
            if pulp.value(x[(f, c)]) > 0.5:
                assignments[c] = f
                break

    return {
        "status": pulp.LpStatus[prob.status],
        "objective": pulp.value(prob.objective),
        "opened": opened,
        "assignments": assignments,
        "solve_time": round(solve_time, 2),
    }


# ===========================================================================
# 4. 評価関数
# ===========================================================================


def evaluate_solution(
    result: dict[str, Any],
    facilities: list[dict[str, Any]],
    customers: list[dict[str, Any]],
    fixed_costs: dict[str, float],
    transport_costs: dict[tuple[str, str], float],
    distances: dict[tuple[str, str], float] | None = None,
    capacities: dict[str, float] | None = None,
    demands: dict[str, float] | None = None,
) -> dict[str, Any]:
    """解の品質を評価する。

    Args:
        result: solve_ufl/cfl/p_median の戻り値。
        facilities: 施設リスト。
        customers: 顧客リスト。
        fixed_costs: 固定費辞書。
        transport_costs: 輸送コスト辞書。
        distances: 距離辞書（km）。Noneなら輸送コストから推定しない。
        capacities: 容量辞書（CFL評価用）。
        demands: 需要辞書（CFL評価用）。

    Returns:
        評価メトリクス辞書。
    """
    opened = result["opened"]
    assignments = result["assignments"]

    # コスト内訳
    total_fixed = sum(fixed_costs.get(f, 0) for f in opened)
    total_transport = sum(
        transport_costs.get((f, c), 0) for c, f in assignments.items()
    )
    total_cost = total_fixed + total_transport

    # 距離統計
    dist_stats: dict[str, Any] = {}
    if distances is not None:
        dists = [distances[(f, c)] for c, f in assignments.items()]
        dist_stats = {
            "avg_distance_km": round(sum(dists) / len(dists), 2) if dists else 0,
            "max_distance_km": round(max(dists), 2) if dists else 0,
            "min_distance_km": round(min(dists), 2) if dists else 0,
        }

    # カバレッジ（割当されていない顧客の有無）
    cids = {c["customer_id"] for c in customers}
    unassigned = cids - set(assignments.keys())

    # 施設ごとの割当顧客数
    facility_load: dict[str, int] = {f: 0 for f in opened}
    for c, f in assignments.items():
        if f in facility_load:
            facility_load[f] += 1

    # 容量チェック（CFL用）
    capacity_violations: list[str] = []
    utilization: dict[str, dict[str, Any]] = {}
    if capacities is not None and demands is not None:
        for f in opened:
            used = sum(demands[c] for c, af in assignments.items() if af == f)
            cap = capacities[f]
            utilization[f] = {
                "used": used,
                "capacity": cap,
                "ratio": round(used / cap, 3) if cap > 0 else 0.0,
            }
            if used > cap:
                capacity_violations.append(
                    f"{f}: 需要{used:.0f} > 容量{cap:.0f}"
                )

    return {
        "total_cost": round(total_cost, 0),
        "fixed_cost": round(total_fixed, 0),
        "transport_cost": round(total_transport, 0),
        "num_opened": len(opened),
        "opened_facilities": opened,
        "num_customers": len(assignments),
        "unassigned_customers": list(unassigned),
        "facility_load": facility_load,
        "distance_stats": dist_stats,
        "capacity_violations": capacity_violations,
        "utilization": utilization,
    }


# ===========================================================================
# __main__: 動作確認用サンプル
# ===========================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # --- サンプルデータ: 関東エリアに倉庫を配置 ---
    sample_facilities = [
        {"facility_id": "W1", "latitude": 35.8617, "longitude": 139.6455},  # さいたま
        {"facility_id": "W2", "latitude": 35.6050, "longitude": 140.1233},  # 千葉
        {"facility_id": "W3", "latitude": 35.4437, "longitude": 139.6380},  # 横浜
    ]

    sample_customers = [
        {"customer_id": "C1", "latitude": 35.6895, "longitude": 139.6917},  # 新宿
        {"customer_id": "C2", "latitude": 35.7295, "longitude": 139.7109},  # 池袋
        {"customer_id": "C3", "latitude": 35.6581, "longitude": 139.7014},  # 渋谷
        {"customer_id": "C4", "latitude": 35.6812, "longitude": 139.7671},  # 東京
        {"customer_id": "C5", "latitude": 35.6267, "longitude": 139.7753},  # お台場
    ]

    sample_fixed_costs = {"W1": 1000000, "W2": 800000, "W3": 1200000}
    sample_capacities = {"W1": 500, "W2": 400, "W3": 600}
    sample_demands = {"C1": 100, "C2": 120, "C3": 80, "C4": 150, "C5": 200}

    # 距離・コスト行列を作成
    dist_matrix = build_distance_matrix(sample_facilities, sample_customers)
    cost_matrix = build_transport_cost_matrix(
        sample_facilities, sample_customers, cost_per_km=150,
    )

    print("=" * 60)
    print("UFL (容量制約なし施設配置)")
    print("=" * 60)
    ufl_result = solve_ufl(
        sample_facilities, sample_customers, sample_fixed_costs, cost_matrix,
    )
    print(f"  ステータス: {ufl_result['status']}")
    print(f"  総コスト: {ufl_result['objective']:,.0f} 円")
    print(f"  開設施設: {ufl_result['opened']}")
    print(f"  割当: {ufl_result['assignments']}")
    print(f"  求解時間: {ufl_result['solve_time']}秒")

    print()
    print("=" * 60)
    print("CFL (容量制約付き施設配置)")
    print("=" * 60)
    cfl_result = solve_cfl(
        sample_facilities, sample_customers,
        sample_fixed_costs, cost_matrix,
        sample_capacities, sample_demands,
    )
    print(f"  ステータス: {cfl_result['status']}")
    print(f"  総コスト: {cfl_result['objective']:,.0f} 円")
    print(f"  開設施設: {cfl_result['opened']}")
    print(f"  割当: {cfl_result['assignments']}")
    print(f"  稼働率: {cfl_result['utilization']}")
    print(f"  求解時間: {cfl_result['solve_time']}秒")

    print()
    print("=" * 60)
    print("P-median (P=2)")
    print("=" * 60)
    pmed_result = solve_p_median(
        sample_facilities, sample_customers, dist_matrix, p=2,
    )
    print(f"  ステータス: {pmed_result['status']}")
    print(f"  距離合計: {pmed_result['objective']:.2f} km")
    print(f"  開設施設: {pmed_result['opened']}")
    print(f"  割当: {pmed_result['assignments']}")
    print(f"  求解時間: {pmed_result['solve_time']}秒")

    # 評価
    print()
    print("=" * 60)
    print("CFL 解の詳細評価")
    print("=" * 60)
    metrics = evaluate_solution(
        cfl_result, sample_facilities, sample_customers,
        sample_fixed_costs, cost_matrix,
        distances=dist_matrix,
        capacities=sample_capacities,
        demands=sample_demands,
    )
    for k, v in metrics.items():
        print(f"  {k}: {v}")
