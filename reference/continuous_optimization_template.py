"""連続最適化・構造最適化テンプレート。

構造設計（梁・トラスの断面最適化）、形状最適化、パラメータチューニング、
トポロジー最適化など、連続変数を扱う最適化問題のテンプレート。

離散（組合せ）最適化（シフト・配送ルート等）ではなく、
設計変数が連続値である問題を対象とする。

scipy.optimize と numpy のみを使用し、商用FEMツールなしで
教育・プロトタイピング用途に十分な精度の最適化を実現する。

使い方:
  1. このファイルをコピーして問題に合わせて修正
  2. 目的関数・制約をカスタマイズ
  3. 初期値とスケーリングを適切に設定すること（収束に大きく影響）

典型的な利用フロー::

    import json
    with open("structure.json") as f:
        structure = json.load(f)
    with open("constraints.json") as f:
        constraints = json.load(f)
    result = optimize_beam_structure(
        loads=structure["loads"],
        material_props=structure["material"],
        constraints=constraints,
    )
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
from scipy import optimize, sparse
from scipy.sparse.linalg import spsolve

logger = logging.getLogger(__name__)


# ============================================================================
# 1. 構造部材（梁）の断面最適化
# ============================================================================

def optimize_beam_structure(
    loads: list[dict[str, Any]],
    material_props: dict[str, float],
    constraints: dict[str, Any],
    method: str = "SLSQP",
) -> dict[str, Any]:
    """梁構造の断面寸法を最適化して重量を最小化する。

    矩形断面の梁を対象に、幅(b)と高さ(h)を設計変数として
    重量（体積 x 密度）を最小化する。応力制約・たわみ制約・
    寸法制約を考慮する。

    Args:
        loads: 荷重条件のリスト。各要素は以下の構造::

            {"position": 0.5, "magnitude": 10000, "type": "point"}

            position: 梁の左端からの相対位置 (0.0-1.0)
            magnitude: 荷重 [N]（下向き正）
            type: "point" または "distributed"

        material_props: 材料特性::

            {
                "E": 210e9,        # ヤング率 [Pa]
                "density": 7850,   # 密度 [kg/m^3]
                "yield_stress": 250e6,  # 降伏応力 [Pa]
                "length": 3.0      # 梁の長さ [m]
            }

        constraints: 設計制約::

            {
                "max_deflection": 0.01,  # 最大たわみ [m]
                "safety_factor": 1.5,     # 安全率
                "min_width": 0.05,        # 最小幅 [m]
                "max_width": 0.5,         # 最大幅 [m]
                "min_height": 0.1,        # 最小高さ [m]
                "max_height": 1.0,        # 最大高さ [m]
                "max_weight": null        # 最大重量 [kg]（オプション）
            }

        method: 最適化手法。"SLSQP"（推奨）、"trust-constr" 等。

    Returns:
        最適化結果の辞書::

            {
                "optimal_width": float,
                "optimal_height": float,
                "weight": float,
                "max_stress": float,
                "max_deflection": float,
                "success": bool,
                "message": str,
                "iterations": int,
            }
    """
    E = material_props["E"]
    density = material_props["density"]
    sigma_allow = material_props["yield_stress"] / constraints.get("safety_factor", 1.5)
    L = material_props["length"]
    max_defl = constraints["max_deflection"]

    # 総荷重（簡易モデル: 単純支持梁に集中荷重）
    total_load = sum(ld["magnitude"] for ld in loads)

    def objective(x: np.ndarray) -> float:
        """目的関数: 重量 = 体積 x 密度。"""
        b, h = x
        return b * h * L * density

    def stress_constraint(x: np.ndarray) -> float:
        """応力制約: sigma_allow - sigma_max >= 0。"""
        b, h = x
        I = b * h**3 / 12  # 断面二次モーメント
        # 最大曲げモーメント（単純支持中央集中荷重の近似）
        M_max = total_load * L / 4
        sigma_max = M_max * (h / 2) / I
        return sigma_allow - sigma_max

    def deflection_constraint(x: np.ndarray) -> float:
        """たわみ制約: max_defl - delta_max >= 0。"""
        b, h = x
        I = b * h**3 / 12
        # 最大たわみ（単純支持中央集中荷重）
        delta_max = total_load * L**3 / (48 * E * I)
        return max_defl - delta_max

    bounds = [
        (constraints.get("min_width", 0.05), constraints.get("max_width", 0.5)),
        (constraints.get("min_height", 0.1), constraints.get("max_height", 1.0)),
    ]

    cons = [
        {"type": "ineq", "fun": stress_constraint},
        {"type": "ineq", "fun": deflection_constraint},
    ]

    # 初期値: 境界の中央
    x0 = np.array([(b[0] + b[1]) / 2 for b in bounds])

    logger.info("梁断面最適化を開始: method=%s, loads=%d個", method, len(loads))
    t0 = time.time()

    result = optimize.minimize(
        objective,
        x0,
        method=method,
        bounds=bounds,
        constraints=cons,
        options={"maxiter": 500, "ftol": 1e-9},
    )

    elapsed = time.time() - t0
    b_opt, h_opt = result.x

    # 最終状態の計算
    I_opt = b_opt * h_opt**3 / 12
    M_max = total_load * L / 4
    sigma_final = M_max * (h_opt / 2) / I_opt
    delta_final = total_load * L**3 / (48 * E * I_opt)

    out = {
        "optimal_width": round(b_opt, 6),
        "optimal_height": round(h_opt, 6),
        "weight": round(b_opt * h_opt * L * density, 3),
        "max_stress": round(sigma_final, 1),
        "max_deflection": round(delta_final, 6),
        "allowable_stress": round(sigma_allow, 1),
        "stress_ratio": round(sigma_final / sigma_allow, 4),
        "deflection_ratio": round(delta_final / max_defl, 4),
        "success": result.success,
        "message": result.message,
        "iterations": result.nit,
        "elapsed_sec": round(elapsed, 4),
    }
    logger.info(
        "最適化完了: weight=%.2f kg, stress_ratio=%.2f, defl_ratio=%.2f",
        out["weight"], out["stress_ratio"], out["deflection_ratio"],
    )
    return out


# ============================================================================
# 2. 形状最適化（2Dプロファイル）
# ============================================================================

def optimize_shape(
    target_area: float,
    perimeter_weight: float = 0.1,
    n_control_points: int = 8,
    symmetry: bool = True,
) -> dict[str, Any]:
    """2Dプロファイルの形状を最適化する。

    制御点で定義された閉曲線の形状を、面積制約を満たしつつ
    周長（材料使用量の指標）を最小化するように最適化する。
    対称性制約を課すことで製造しやすい形状を得る。

    原理:
    - 制御点の半径方向座標 r(theta) を設計変数とする
    - 面積 = sum of 三角形面積（制御点で近似）
    - 周長 = sum of 制御点間の距離
    - 対称性: y軸対称にする場合、半分の点だけ最適化

    Args:
        target_area: 目標面積 [m^2]。この面積以上を確保する。
        perimeter_weight: 周長のペナルティ重み (0-1)。
            大きいほど周長を短くしようとする。
        n_control_points: 制御点の数。多いほど自由度が高いが
            計算コストが増える。
        symmetry: True の場合、y軸対称に制約する。

    Returns:
        最適化結果::

            {
                "control_points": [[x, y], ...],
                "area": float,
                "perimeter": float,
                "success": bool,
            }
    """
    # 角度の等分点
    angles = np.linspace(0, 2 * np.pi, n_control_points, endpoint=False)

    if symmetry:
        # 対称性: 上半分の点だけ最適化（0 ~ pi）
        n_vars = n_control_points // 2 + 1
    else:
        n_vars = n_control_points

    # 初期値: 目標面積に対応する円の半径
    r0 = np.sqrt(target_area / np.pi)
    x0 = np.full(n_vars, r0)

    def _build_points(r_vars: np.ndarray) -> np.ndarray:
        """設計変数から全制御点を構築する。"""
        if symmetry:
            # 上半分から下半分をミラーリング
            r_full = np.zeros(n_control_points)
            r_full[:n_vars] = r_vars
            for i in range(n_vars, n_control_points):
                mirror_idx = n_control_points - i
                if mirror_idx < n_vars:
                    r_full[i] = r_vars[mirror_idx]
                else:
                    r_full[i] = r_vars[0]
        else:
            r_full = r_vars

        pts = np.column_stack([r_full * np.cos(angles), r_full * np.sin(angles)])
        return pts

    def _area(pts: np.ndarray) -> float:
        """Shoelaceの公式で面積を計算。"""
        x, y = pts[:, 0], pts[:, 1]
        return 0.5 * abs(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))

    def _perimeter(pts: np.ndarray) -> float:
        """周長を計算。"""
        diffs = np.diff(np.vstack([pts, pts[:1]]), axis=0)
        return np.sum(np.sqrt(np.sum(diffs**2, axis=1)))

    def objective(r_vars: np.ndarray) -> float:
        pts = _build_points(r_vars)
        area = _area(pts)
        perim = _perimeter(pts)
        # 面積に対する周長の比を最小化（円に近い形が最適）
        # + 面積不足へのペナルティ
        area_penalty = max(0, target_area - area) * 1000
        return perimeter_weight * perim + area_penalty

    def area_constraint(r_vars: np.ndarray) -> float:
        pts = _build_points(r_vars)
        return _area(pts) - target_area

    bounds = [(0.01, r0 * 3)] * n_vars
    cons = [{"type": "ineq", "fun": area_constraint}]

    logger.info("形状最適化を開始: 制御点=%d, 対称=%s", n_control_points, symmetry)

    result = optimize.minimize(
        objective, x0, method="SLSQP", bounds=bounds, constraints=cons,
        options={"maxiter": 300, "ftol": 1e-10},
    )

    pts_opt = _build_points(result.x)
    return {
        "control_points": pts_opt.tolist(),
        "radii": result.x.tolist(),
        "area": round(_area(pts_opt), 6),
        "perimeter": round(_perimeter(pts_opt), 6),
        "target_area": target_area,
        "area_ratio": round(_area(pts_opt) / target_area, 4),
        "success": result.success,
        "message": result.message,
        "iterations": result.nit,
    }


# ============================================================================
# 3. 汎用パラメータチューニング
# ============================================================================

def optimize_parameters(
    objective_fn: Callable[[np.ndarray], float],
    bounds: list[tuple[float, float]],
    constraints: list[dict[str, Any]] | None = None,
    method: str = "differential_evolution",
    x0: np.ndarray | None = None,
    seed: int | None = 42,
    maxiter: int = 1000,
) -> dict[str, Any]:
    """汎用パラメータ最適化ラッパー。

    scipy.optimize の各種手法を統一インターフェースで呼び出す。
    勾配ベースの局所探索からメタヒューリスティクスまで対応する。

    手法の選び方:
    - 凸問題・勾配あり → "SLSQP" or "trust-constr"
    - 非凸・ブラックボックス → "differential_evolution"
    - 制約なし・低次元 → "L-BFGS-B" or "Nelder-Mead"
    - 等式制約あり → "SLSQP" or "trust-constr"

    Args:
        objective_fn: 目的関数。np.ndarray を受け取り float を返す。
        bounds: 各変数の (下限, 上限) のリスト。
        constraints: scipy 形式の制約リスト。None の場合は制約なし。
        method: 最適化手法名。
        x0: 初期値。局所探索手法で必要。None の場合は境界の中央値。
        seed: 乱数シード（differential_evolution 用）。
        maxiter: 最大反復回数。

    Returns:
        最適化結果::

            {
                "optimal_params": list[float],
                "objective_value": float,
                "success": bool,
                "message": str,
                "n_evaluations": int,
                "elapsed_sec": float,
            }
    """
    logger.info("パラメータ最適化を開始: method=%s, dim=%d", method, len(bounds))
    t0 = time.time()

    if method == "differential_evolution":
        result = optimize.differential_evolution(
            objective_fn,
            bounds=bounds,
            constraints=constraints or (),
            seed=seed,
            maxiter=maxiter,
            tol=1e-10,
            polish=True,
        )
        n_evals = result.nfev
    else:
        if x0 is None:
            x0 = np.array([(lo + hi) / 2 for lo, hi in bounds])

        result = optimize.minimize(
            objective_fn,
            x0,
            method=method,
            bounds=bounds,
            constraints=constraints or (),
            options={"maxiter": maxiter},
        )
        n_evals = result.nfev

    elapsed = time.time() - t0

    out = {
        "optimal_params": [round(v, 8) for v in result.x],
        "objective_value": round(float(result.fun), 8),
        "success": bool(result.success),
        "message": str(result.message),
        "n_evaluations": n_evals,
        "elapsed_sec": round(elapsed, 4),
    }
    logger.info("完了: obj=%.6f, evals=%d, time=%.2fs", out["objective_value"], n_evals, elapsed)
    return out


# ============================================================================
# 4. トポロジー最適化（SIMP法 — 2D平面応力）
# ============================================================================

def optimize_topology_2d(
    nx: int,
    ny: int,
    loads: dict[int, tuple[float, float]],
    supports: dict[int, tuple[bool, bool]],
    volume_fraction: float = 0.5,
    penalty: float = 3.0,
    r_min: float = 1.5,
    iterations: int = 100,
    tol: float = 0.01,
) -> dict[str, Any]:
    """2Dトポロジー最適化（SIMP法）。

    密度ベースのSIMP法（Solid Isotropic Material with Penalization）で
    2D平面応力問題のトポロジー最適化を行う。

    各要素に密度変数 rho_e (0-1) を割り当て、
    コンプライアンス（ひずみエネルギー = 柔軟さ）を最小化する
    （= 剛性を最大化する）。

    簡易FEM（4節点四角形要素・平面応力）を内蔵している。

    Args:
        nx: x方向の要素数。
        ny: y方向の要素数。
        loads: 荷重条件。キーはノード番号、値は (fx, fy)。
            ノード番号は左下(0,0)から右へ、下から上への順番。
            ノード番号 = iy * (nx+1) + ix。
        supports: 支持条件。キーはノード番号、値は (x固定, y固定)。
        volume_fraction: 目標体積率 (0 < vf < 1)。
            0.5 = 材料の半分を使う。
        penalty: SIMP法のペナルティ係数。通常3.0。
            大きいほど 0/1 に近い解になるが収束しにくい。
        r_min: 密度フィルタの半径（メッシュ幅の倍数）。
            チェッカーボードパターンを防ぐ。
        iterations: OC法（Optimality Criteria）の最大反復回数。
        tol: 収束判定の閾値（密度変更の最大値）。

    Returns:
        最適化結果::

            {
                "density": 2D numpy array (ny x nx),
                "compliance": float (最終コンプライアンス),
                "volume_fraction": float (最終体積率),
                "convergence": list[float] (各反復のコンプライアンス),
                "iterations": int,
                "elapsed_sec": float,
            }
    """
    logger.info(
        "トポロジー最適化を開始: %dx%d要素, vf=%.2f, p=%.1f",
        nx, ny, volume_fraction, penalty,
    )
    t0 = time.time()

    n_elem = nx * ny
    n_nodes = (nx + 1) * (ny + 1)
    n_dof = 2 * n_nodes

    # --- 要素剛性行列 (4節点四角形, 平面応力, 単位ヤング率) ---
    KE = _element_stiffness_matrix()

    # --- 密度フィルタの重み行列を事前計算 ---
    H, Hs = _prepare_filter(nx, ny, r_min)

    # --- 荷重ベクトル ---
    F = np.zeros(n_dof)
    for node_id, (fx, fy) in loads.items():
        F[2 * node_id] = fx
        F[2 * node_id + 1] = fy

    # --- 固定自由度 ---
    fixed_dofs = []
    for node_id, (fix_x, fix_y) in supports.items():
        if fix_x:
            fixed_dofs.append(2 * node_id)
        if fix_y:
            fixed_dofs.append(2 * node_id + 1)
    fixed_dofs = np.array(fixed_dofs, dtype=int)
    free_dofs = np.setdiff1d(np.arange(n_dof), fixed_dofs)

    # --- 要素の接続情報 ---
    edof = _element_dof_indices(nx, ny)

    # --- 初期密度 ---
    rho = np.full(n_elem, volume_fraction)

    # --- OC法による反復最適化 ---
    convergence = []
    E_min = 1e-9  # void 要素の最小剛性（特異性回避）
    E_0 = 1.0     # solid 要素のヤング率

    for it in range(iterations):
        # 密度フィルタ適用
        rho_phys = np.array(H @ rho / Hs, dtype=float)

        # FEM: 全体剛性行列を組み立て
        K_data = []
        K_rows = []
        K_cols = []
        for e in range(n_elem):
            Ee = E_min + rho_phys[e] ** penalty * (E_0 - E_min)
            ke = Ee * KE
            dofs_e = edof[e]
            for i_local in range(8):
                for j_local in range(8):
                    K_rows.append(dofs_e[i_local])
                    K_cols.append(dofs_e[j_local])
                    K_data.append(ke[i_local, j_local])

        K_global = sparse.coo_matrix(
            (K_data, (K_rows, K_cols)), shape=(n_dof, n_dof)
        ).tocsc()

        # 境界条件を適用して求解
        K_free = K_global[np.ix_(free_dofs, free_dofs)]
        F_free = F[free_dofs]
        U = np.zeros(n_dof)
        U[free_dofs] = spsolve(K_free, F_free)

        # コンプライアンスと感度の計算
        compliance = 0.0
        dc = np.zeros(n_elem)
        for e in range(n_elem):
            ue = U[edof[e]]
            ce = float(ue @ KE @ ue)
            Ee = E_min + rho_phys[e] ** penalty * (E_0 - E_min)
            compliance += Ee * ce
            dc[e] = -penalty * rho_phys[e] ** (penalty - 1) * (E_0 - E_min) * ce

        convergence.append(compliance)

        # 感度フィルタ
        dc = np.array(H @ (rho * dc) / Hs / np.maximum(rho, 1e-3), dtype=float)

        # OC法 (Optimality Criteria) による密度更新
        rho_new = _oc_update(rho, dc, volume_fraction, nx * ny)

        # 収束判定
        change = np.max(np.abs(rho_new - rho))
        rho = rho_new

        if (it + 1) % 10 == 0 or it == 0:
            logger.info(
                "  iter %3d: compliance=%.4f, vol=%.4f, change=%.4f",
                it + 1, compliance, np.mean(rho_phys), change,
            )

        if change < tol and it > 10:
            logger.info("収束しました (change=%.6f < tol=%.4f)", change, tol)
            break

    elapsed = time.time() - t0
    density_2d = rho_phys.reshape(ny, nx)

    out = {
        "density": density_2d,
        "compliance": round(convergence[-1], 6),
        "volume_fraction_actual": round(float(np.mean(rho_phys)), 4),
        "convergence": [round(c, 6) for c in convergence],
        "iterations": len(convergence),
        "elapsed_sec": round(elapsed, 4),
        "nx": nx,
        "ny": ny,
    }
    logger.info(
        "トポロジー最適化完了: compliance=%.4f, vol=%.4f, %d反復, %.2f秒",
        out["compliance"], out["volume_fraction_actual"], out["iterations"], elapsed,
    )
    return out


# --- トポロジー最適化の内部関数 ---

def _element_stiffness_matrix() -> np.ndarray:
    """4節点四角形要素の剛性行列（平面応力、単位ヤング率）。

    要素サイズ 1x1、ポアソン比 0.3 として解析的に計算した8x8行列。
    Sigmund (2001) "A 99 line topology optimization code" に基づく。
    """
    nu = 0.3
    k = [
        1 / 2 - nu / 6,
        1 / 8 + nu / 8,
        -1 / 4 - nu / 12,
        -1 / 8 + 3 * nu / 8,
        -1 / 4 + nu / 12,
        -1 / 8 - nu / 8,
        nu / 6,
        1 / 8 - 3 * nu / 8,
    ]
    KE = (
        1
        / (1 - nu**2)
        * np.array(
            [
                [k[0], k[1], k[2], k[3], k[4], k[5], k[6], k[7]],
                [k[1], k[0], k[7], k[6], k[5], k[4], k[3], k[2]],
                [k[2], k[7], k[0], k[5], k[6], k[3], k[4], k[1]],
                [k[3], k[6], k[5], k[0], k[7], k[2], k[1], k[4]],
                [k[4], k[5], k[6], k[7], k[0], k[1], k[2], k[3]],
                [k[5], k[4], k[3], k[2], k[1], k[0], k[7], k[6]],
                [k[6], k[3], k[4], k[1], k[2], k[7], k[0], k[5]],
                [k[7], k[2], k[1], k[4], k[3], k[6], k[5], k[0]],
            ]
        )
    )
    return KE


def _element_dof_indices(nx: int, ny: int) -> np.ndarray:
    """各要素の自由度インデックスを返す。

    ノード番号付けは左下原点、x方向優先。
    要素番号も左下原点、x方向優先。
    """
    edof = np.zeros((nx * ny, 8), dtype=int)
    for ey in range(ny):
        for ex in range(nx):
            e = ey * nx + ex
            n1 = ey * (nx + 1) + ex          # 左下
            n2 = ey * (nx + 1) + ex + 1      # 右下
            n3 = (ey + 1) * (nx + 1) + ex + 1  # 右上
            n4 = (ey + 1) * (nx + 1) + ex    # 左上
            edof[e] = [
                2 * n1, 2 * n1 + 1,
                2 * n2, 2 * n2 + 1,
                2 * n3, 2 * n3 + 1,
                2 * n4, 2 * n4 + 1,
            ]
    return edof


def _prepare_filter(nx: int, ny: int, r_min: float) -> tuple[sparse.csc_matrix, np.ndarray]:
    """密度フィルタの重み行列を構築する。"""
    n_elem = nx * ny
    rows = []
    cols = []
    vals = []
    for ey1 in range(ny):
        for ex1 in range(nx):
            e1 = ey1 * nx + ex1
            cx1, cy1 = ex1 + 0.5, ey1 + 0.5
            for ey2 in range(max(0, ey1 - int(r_min) - 1), min(ny, ey1 + int(r_min) + 2)):
                for ex2 in range(max(0, ex1 - int(r_min) - 1), min(nx, ex1 + int(r_min) + 2)):
                    e2 = ey2 * nx + ex2
                    cx2, cy2 = ex2 + 0.5, ey2 + 0.5
                    dist = np.sqrt((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2)
                    if dist < r_min:
                        rows.append(e1)
                        cols.append(e2)
                        vals.append(r_min - dist)

    H = sparse.csc_matrix((vals, (rows, cols)), shape=(n_elem, n_elem))
    Hs = np.array(H.sum(axis=1)).flatten()
    return H, Hs


def _oc_update(
    rho: np.ndarray, dc: np.ndarray, vf: float, n_elem: int
) -> np.ndarray:
    """OC法（Optimality Criteria）による密度更新。"""
    move = 0.2
    l1, l2 = 0.0, 1e9

    while (l2 - l1) / (l1 + l2) > 1e-3:
        lmid = 0.5 * (l1 + l2)
        # 更新式
        Be = np.sqrt(-dc / lmid)
        rho_new = np.maximum(0.001, np.maximum(
            rho - move,
            np.minimum(1.0, np.minimum(rho + move, rho * Be)),
        ))
        if np.sum(rho_new) - vf * n_elem > 0:
            l1 = lmid
        else:
            l2 = lmid

    return rho_new


# ============================================================================
# 5. 可視化ヘルパー
# ============================================================================

def plot_topology(
    density: np.ndarray,
    title: str = "トポロジー最適化結果",
    save_path: str | None = None,
) -> None:
    """トポロジー最適化結果の密度分布を可視化する。

    Args:
        density: 2D密度配列 (ny x nx)。0=void, 1=solid。
        title: グラフのタイトル。
        save_path: 保存先パス。None の場合は表示のみ。
    """
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 1, figsize=(12, 4))
    im = ax.imshow(
        1.0 - density,
        cmap="gray",
        origin="lower",
        interpolation="nearest",
        vmin=0,
        vmax=1,
    )
    ax.set_title(title, fontsize=14)
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    fig.colorbar(im, ax=ax, label="密度 (黒=solid, 白=void)", shrink=0.8)
    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        logger.info("トポロジー画像を保存: %s", save_path)
        plt.close(fig)
    else:
        plt.show()


def plot_convergence(
    convergence: list[float],
    title: str = "収束曲線",
    save_path: str | None = None,
) -> None:
    """収束曲線を可視化する。

    Args:
        convergence: 各反復のコンプライアンス値のリスト。
        title: グラフのタイトル。
        save_path: 保存先パス。None の場合は表示のみ。
    """
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 1, figsize=(8, 5))
    ax.plot(range(1, len(convergence) + 1), convergence, "b-", linewidth=1.5)
    ax.set_xlabel("反復回数", fontsize=12)
    ax.set_ylabel("コンプライアンス", fontsize=12)
    ax.set_title(title, fontsize=14)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        logger.info("収束曲線を保存: %s", save_path)
        plt.close(fig)
    else:
        plt.show()


def plot_shape(
    control_points: list[list[float]],
    title: str = "形状最適化結果",
    save_path: str | None = None,
) -> None:
    """形状最適化結果を可視化する。

    Args:
        control_points: 制御点の座標リスト [[x, y], ...]。
        title: グラフのタイトル。
        save_path: 保存先パス。
    """
    import matplotlib.pyplot as plt

    pts = np.array(control_points)
    # 閉曲線にする
    pts_closed = np.vstack([pts, pts[:1]])

    fig, ax = plt.subplots(1, 1, figsize=(6, 6))
    ax.fill(pts_closed[:, 0], pts_closed[:, 1], alpha=0.3, color="steelblue")
    ax.plot(pts_closed[:, 0], pts_closed[:, 1], "b-o", markersize=4)
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=14)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        logger.info("形状画像を保存: %s", save_path)
        plt.close(fig)
    else:
        plt.show()


# ============================================================================
# メイン: デモ実行
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    print("=" * 60)
    print("連続最適化テンプレート — デモ実行")
    print("=" * 60)

    # --- デモ1: 梁断面最適化 ---
    print("\n--- 1. 梁断面最適化 ---")
    beam_result = optimize_beam_structure(
        loads=[{"position": 0.5, "magnitude": 50000, "type": "point"}],
        material_props={
            "E": 210e9,
            "density": 7850,
            "yield_stress": 250e6,
            "length": 3.0,
        },
        constraints={
            "max_deflection": 0.01,
            "safety_factor": 1.5,
            "min_width": 0.05,
            "max_width": 0.3,
            "min_height": 0.1,
            "max_height": 0.5,
        },
    )
    for k, v in beam_result.items():
        print(f"  {k}: {v}")

    # --- デモ2: 形状最適化 ---
    print("\n--- 2. 形状最適化 ---")
    shape_result = optimize_shape(
        target_area=1.0,
        perimeter_weight=0.5,
        n_control_points=12,
        symmetry=True,
    )
    print(f"  面積: {shape_result['area']:.4f} (目標: {shape_result['target_area']})")
    print(f"  周長: {shape_result['perimeter']:.4f}")
    print(f"  成功: {shape_result['success']}")

    # --- デモ3: パラメータチューニング ---
    print("\n--- 3. パラメータチューニング（Rosenbrock関数） ---")
    param_result = optimize_parameters(
        objective_fn=lambda x: sum(100 * (x[1:] - x[:-1] ** 2) ** 2 + (1 - x[:-1]) ** 2),
        bounds=[(-5, 5)] * 3,
        method="differential_evolution",
    )
    print(f"  最適パラメータ: {param_result['optimal_params']}")
    print(f"  目的関数値: {param_result['objective_value']}")
    print(f"  評価回数: {param_result['n_evaluations']}")

    # --- デモ4: トポロジー最適化（片持ち梁） ---
    print("\n--- 4. トポロジー最適化（片持ち梁） ---")
    nx, ny = 60, 20
    # 左端を完全固定
    topo_supports = {}
    for iy in range(ny + 1):
        node_id = iy * (nx + 1)
        topo_supports[node_id] = (True, True)
    # 右端中央に下向き荷重
    load_node = ny // 2 * (nx + 1) + nx
    topo_loads = {load_node: (0.0, -1.0)}

    topo_result = optimize_topology_2d(
        nx=nx,
        ny=ny,
        loads=topo_loads,
        supports=topo_supports,
        volume_fraction=0.5,
        iterations=80,
    )
    print(f"  コンプライアンス: {topo_result['compliance']:.4f}")
    print(f"  体積率: {topo_result['volume_fraction_actual']:.4f}")
    print(f"  反復回数: {topo_result['iterations']}")
    print(f"  計算時間: {topo_result['elapsed_sec']:.2f}秒")

    # 密度分布のASCII表示（簡易）
    density = topo_result["density"]
    print("\n  密度分布（簡易表示）:")
    for iy in range(ny - 1, -1, -3):
        row = "  "
        for ix in range(0, nx, 2):
            val = density[iy, ix]
            if val > 0.7:
                row += "##"
            elif val > 0.3:
                row += ".."
            else:
                row += "  "
        print(row)

    print("\n完了。")
