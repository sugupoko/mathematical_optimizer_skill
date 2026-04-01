#!/usr/bin/env python3
"""構造最適化 -- 本番パイプライン

実行頻度: プロジェクト単位（新規構造設計時）
入力:     data/structure.json, data/constraints.json
出力:     results/design_YYYYMMDD_HHMMSS.json + topology_*.npy
ログ:     log/run_YYYYMMDD_HHMMSS.log
"""

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import numpy as np

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

# --- テンプレート読み込み ---
PROJECT_ROOT = BASE_DIR.parents[2]
REFERENCE_DIR = PROJECT_ROOT / "reference"
sys.path.insert(0, str(REFERENCE_DIR))
from continuous_optimization_template import (
    optimize_beam_structure,
    optimize_topology_2d,
)


# =========================================================
# 1. データ読み込み
# =========================================================
def load_data():
    with open(DATA_DIR / "structure.json", encoding="utf-8") as f:
        structure = json.load(f)
    with open(DATA_DIR / "constraints.json", encoding="utf-8") as f:
        constraints = json.load(f)
    return structure, constraints


# =========================================================
# 2. バリデーション
# =========================================================
def validate(structure, constraints):
    errors = []

    mat = structure.get("material", {})
    if mat.get("E", 0) <= 0:
        errors.append("ヤング率 E が0以下です")
    if mat.get("density", 0) <= 0:
        errors.append("密度が0以下です")
    if mat.get("yield_stress", 0) <= 0:
        errors.append("降伏応力が0以下です")

    dims = structure.get("dimensions", {})
    if dims.get("length", 0) <= 0:
        errors.append("梁の全長が0以下です")

    loads = structure.get("loads", [])
    if not loads:
        errors.append("荷重が定義されていません")
    for ld in loads:
        if ld.get("magnitude", 0) <= 0:
            errors.append(f"荷重 {ld.get('id', '?')}: 大きさが0以下です")

    sc = constraints.get("stress_constraints", {})
    if sc.get("safety_factor", 0) < 1.0:
        errors.append(f"安全率が1.0未満です ({sc.get('safety_factor')})")

    dc = constraints.get("deflection_constraints", {})
    if dc.get("max_deflection", 0) <= 0:
        errors.append("最大たわみが0以下です")

    dim_c = constraints.get("dimension_constraints", {})
    if dim_c.get("min_width", 0) >= dim_c.get("max_width", 0):
        errors.append("幅の範囲が不正 (min >= max)")
    if dim_c.get("min_height", 0) >= dim_c.get("max_height", 0):
        errors.append("高さの範囲が不正 (min >= max)")

    tc = constraints.get("topology_constraints", {})
    vf = tc.get("volume_fraction", 0)
    if not (0 < vf < 1):
        errors.append(f"体積率が範囲外です ({vf})")

    topo = structure.get("topology_optimization", {})
    if topo.get("nx", 0) < 2 or topo.get("ny", 0) < 2:
        errors.append("メッシュサイズが小さすぎます (nx, ny >= 2)")

    return errors


# =========================================================
# 3. 断面最適化
# =========================================================
def run_beam_optimization(structure, constraints):
    logger.info("  SLSQP で断面最適化中...")
    result = optimize_beam_structure(
        loads=structure["loads"],
        material_props={
            "E": structure["material"]["E"],
            "density": structure["material"]["density"],
            "yield_stress": structure["material"]["yield_stress"],
            "length": structure["dimensions"]["length"],
        },
        constraints={
            "max_deflection": constraints["deflection_constraints"]["max_deflection"],
            "safety_factor": constraints["stress_constraints"]["safety_factor"],
            "min_width": constraints["dimension_constraints"]["min_width"],
            "max_width": constraints["dimension_constraints"]["max_width"],
            "min_height": constraints["dimension_constraints"]["min_height"],
            "max_height": constraints["dimension_constraints"]["max_height"],
        },
        method="SLSQP",
    )
    return result


# =========================================================
# 4. トポロジー最適化
# =========================================================
def run_topology_optimization(structure, constraints):
    topo_cfg = structure["topology_optimization"]
    nx = topo_cfg["nx"]
    ny = topo_cfg["ny"]
    vf = constraints["topology_constraints"]["volume_fraction"]

    # 片持ち梁: 左端を完全固定、右端中央に下向き荷重
    supports = {}
    for iy in range(ny + 1):
        node_id = iy * (nx + 1)
        supports[node_id] = (True, True)

    load_node = (ny // 2) * (nx + 1) + nx
    loads = {load_node: (0.0, -1.0)}

    logger.info("  SIMP法でトポロジー最適化中 (vf=%.0f%%, %dx%d)...", vf * 100, nx, ny)
    result = optimize_topology_2d(
        nx=nx, ny=ny,
        loads=loads,
        supports=supports,
        volume_fraction=vf,
        penalty=3.0,
        r_min=1.5,
        iterations=100,
        tol=0.01,
    )
    return result


# =========================================================
# 5. 結果検証
# =========================================================
def verify_beam(beam_result, constraints):
    issues = []
    sf = constraints["stress_constraints"]["safety_factor"]
    sigma_allow = beam_result.get("allowable_stress", None)

    if beam_result["stress_ratio"] > 1.0:
        issues.append(
            f"応力制約違反: 応力比 {beam_result['stress_ratio']:.3f} > 1.0"
        )
    if beam_result["deflection_ratio"] > 1.0:
        issues.append(
            f"たわみ制約違反: たわみ比 {beam_result['deflection_ratio']:.3f} > 1.0"
        )
    if not beam_result.get("success", False):
        issues.append("SLSQP が収束しませんでした")

    return issues


# =========================================================
# 6. 出力
# =========================================================
def export_results(beam_result, topo_result, structure, constraints):
    design = {
        "timestamp": TIMESTAMP,
        "problem": structure.get("problem_name", ""),
        "beam_optimization": {
            "method": "SLSQP",
            "success": beam_result["success"],
            "optimal_width_m": beam_result["optimal_width"],
            "optimal_height_m": beam_result["optimal_height"],
            "weight_kg": beam_result["weight"],
            "stress_ratio": beam_result["stress_ratio"],
            "deflection_ratio": beam_result["deflection_ratio"],
            "iterations": beam_result["iterations"],
            "elapsed_sec": beam_result["elapsed_sec"],
        },
        "topology_optimization": {
            "method": "SIMP",
            "volume_fraction_target": constraints["topology_constraints"]["volume_fraction"],
            "volume_fraction_actual": topo_result["volume_fraction_actual"],
            "compliance": topo_result["compliance"],
            "iterations": topo_result["iterations"],
            "elapsed_sec": topo_result["elapsed_sec"],
            "mesh": f"{structure['topology_optimization']['nx']}x{structure['topology_optimization']['ny']}",
        },
    }

    # 設計JSON出力
    json_path = RESULTS_DIR / f"design_{TIMESTAMP}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(design, f, ensure_ascii=False, indent=2, default=str)
    logger.info("設計データ出力: %s", json_path)

    # トポロジー密度配列出力
    density_path = RESULTS_DIR / f"topology_{TIMESTAMP}.npy"
    np.save(str(density_path), topo_result["density"])
    logger.info("トポロジー密度出力: %s", density_path)

    return json_path


# =========================================================
# メイン
# =========================================================
def main():
    logger.info("=" * 50)
    logger.info("構造最適化パイプライン 開始")
    logger.info("=" * 50)

    # Step 1: データ読み込み
    logger.info("[Step 1] データ読み込み")
    try:
        structure, constraints = load_data()
    except FileNotFoundError as e:
        logger.error("データファイルが見つかりません: %s", e)
        sys.exit(1)
    logger.info("  問題: %s", structure.get("problem_name", ""))
    logger.info("  材料: %s", structure["material"]["name"])

    # Step 2: バリデーション
    logger.info("[Step 2] バリデーション")
    errors = validate(structure, constraints)
    if errors:
        for err in errors:
            logger.error("  致命的エラー: %s", err)
        logger.error("パイプライン中断")
        sys.exit(1)
    logger.info("  バリデーション OK")

    # Step 3: 断面最適化
    logger.info("[Step 3] 断面最適化（SLSQP）")
    t0 = time.time()
    beam_result = run_beam_optimization(structure, constraints)
    beam_elapsed = time.time() - t0
    logger.info("  幅: %.4f m, 高さ: %.4f m",
                beam_result["optimal_width"], beam_result["optimal_height"])
    logger.info("  重量: %.1f kg", beam_result["weight"])
    logger.info("  応力比: %.3f, たわみ比: %.3f",
                beam_result["stress_ratio"], beam_result["deflection_ratio"])
    logger.info("  収束: %s (%.3f秒)", beam_result["success"], beam_elapsed)

    # Step 4: トポロジー最適化
    logger.info("[Step 4] トポロジー最適化（SIMP法）")
    t0 = time.time()
    topo_result = run_topology_optimization(structure, constraints)
    topo_elapsed = time.time() - t0
    logger.info("  コンプライアンス: %.4f", topo_result["compliance"])
    logger.info("  体積率: %.1f%%", topo_result["volume_fraction_actual"] * 100)
    logger.info("  反復数: %d (%.1f秒)", topo_result["iterations"], topo_elapsed)

    # Step 5: 結果検証
    logger.info("[Step 5] 結果検証")
    issues = verify_beam(beam_result, constraints)
    if issues:
        for issue in issues:
            logger.warning("  注意: %s", issue)
    else:
        logger.info("  全制約を満足しています")

    # 重量削減率の計算
    max_w = (constraints["dimension_constraints"]["max_width"]
             * constraints["dimension_constraints"]["max_height"]
             * structure["dimensions"]["length"]
             * structure["material"]["density"])
    reduction = (1 - beam_result["weight"] / max_w) * 100
    logger.info("  重量削減率: %.1f%% (最大断面 %.1fkg -> %.1fkg)",
                reduction, max_w, beam_result["weight"])

    # Step 6: 出力
    logger.info("[Step 6] 結果出力")
    json_path = export_results(beam_result, topo_result, structure, constraints)

    logger.info("=" * 50)
    logger.info("構造最適化パイプライン 完了")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
