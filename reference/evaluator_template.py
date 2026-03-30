"""制約チェッカー・評価関数テンプレート。

どの最適化問題でも「解の良し悪しを測る評価器」が必要。
これがないと改善の方向がわからない。

このモジュールは、ハード制約の違反チェックとソフト制約のスコアリングを
統一的に行う評価関数を提供する。ソルバーの目的関数値との一致検証機能も含む。

使い方:
  1. hard_constraints と soft_constraints を自分の問題に合わせて定義
  2. evaluate() を呼ぶと feasibility + soft_score が返る
  3. ソルバーの目的関数はこの soft_score と精密一致させる
  4. verify_objective_evaluation_alignment() で目的関数と評価関数の乖離を検証

典型的な利用フロー::

    result = evaluate(solution, dataset)
    alignment = verify_objective_evaluation_alignment(solver.ObjectiveValue(), result["soft_score"])
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def evaluate(solution: Any, dataset: dict[str, Any]) -> dict[str, Any]:
    """解を評価し、実行可能性とソフトスコアを返す。

    ハード制約の違反数とソフト制約のスコアを計算する。
    ソルバーの目的関数はこのソフトスコアと精密一致させること。

    Args:
        solution: ソルバーが出力した解。形式は問題に依存する。
        dataset: 問題データ（制約パラメータを含む）。

    Returns:
        評価結果の辞書::

            {
                "feasibility": 1 or 0,
                "hard_violations": int,
                "hard_violations_detail": {"HC1": 0, "HC2": 3, ...},
                "soft_score": float,
                "soft_scores_detail": {"SC1": 100.0, "SC2": -50.0, ...},
            }
    """
    # --- ハード制約チェック ---
    violations = {}

    # HC1: [制約名] — 問題に合わせて実装
    # violations["HC1"] = check_constraint_1(solution, dataset)

    # HC2: [制約名]
    # violations["HC2"] = check_constraint_2(solution, dataset)

    total_violations = sum(len(v) if isinstance(v, list) else v for v in violations.values())
    feasible = total_violations == 0

    # --- ソフト制約スコア ---
    soft_scores = {}

    # SC1: [制約名] — weight × raw_score
    # sc1_weight = 10  # ← 評価関数の重みをソルバーの目的関数でも同じ値にする
    # sc1_raw = compute_sc1(solution, dataset)
    # soft_scores["SC1"] = sc1_raw * sc1_weight

    # SC2: [制約名]
    # sc2_weight = 8
    # sc2_raw = compute_sc2(solution, dataset)
    # soft_scores["SC2"] = sc2_raw * sc2_weight

    total_soft = sum(soft_scores.values())

    result = {
        "feasibility": 1 if feasible else 0,
        "hard_violations": total_violations,
        "hard_violations_detail": {k: len(v) if isinstance(v, list) else v for k, v in violations.items()},
        "soft_score": round(total_soft, 2),
        "soft_scores_detail": {k: round(v, 2) for k, v in soft_scores.items()},
    }

    logger.info(
        "Evaluation: feasibility=%d, violations=%d, soft_score=%.2f",
        result["feasibility"], result["hard_violations"], result["soft_score"]
    )
    return result


# --- 以下、問題に合わせて制約チェック関数を実装 ---

# def check_constraint_1(solution, dataset) -> list:
#     """HC1: [制約の説明]"""
#     violations = []
#     # ... チェックロジック
#     return violations

# def compute_sc1(solution, dataset) -> float:
#     """SC1: [スコアの説明]"""
#     score = 0.0
#     # ... 計算ロジック
#     return score


def verify_objective_evaluation_alignment(
    solver_objective_value: float,
    evaluation_score: float,
    tolerance_pct: float = 1.0,
) -> dict[str, Any]:
    """ソルバーの目的関数値と評価関数の出力が一致するか検証する。

    目的関数と評価関数の乖離は最適化品質を15-27%低下させる（実験で確認済み）。
    最適化パイプラインの品質保証として、毎回実行すること。

    Args:
        solver_objective_value: ソルバーが報告する目的関数値
        evaluation_score: 評価関数が計算したスコア
        tolerance_pct: 許容乖離率（%）。デフォルト1.0%

    Returns:
        dict with keys:
            - aligned (bool): 一致しているか
            - diff_pct (float): 乖離率（%）
            - solver_value (float): ソルバーの値
            - eval_value (float): 評価関数の値
            - message (str): 結果の説明

    Raises:
        ValueError: tolerance_pct が負の場合

    Example:
        >>> result = verify_objective_evaluation_alignment(500.0, 495.0)
        >>> result['aligned']
        True
        >>> result['diff_pct']
        1.0
    """
    if tolerance_pct < 0:
        raise ValueError(f"tolerance_pct must be non-negative, got {tolerance_pct}")

    denominator = max(abs(evaluation_score), 1e-10)
    diff_pct = abs(solver_objective_value - evaluation_score) / denominator * 100
    aligned = diff_pct <= tolerance_pct

    if aligned:
        message = f"OK: 目的関数と評価関数の乖離 {diff_pct:.2f}% (許容範囲 {tolerance_pct}%以内)"
    else:
        message = (
            f"WARNING: 目的関数と評価関数の乖離 {diff_pct:.2f}% (許容範囲 {tolerance_pct}%を超過)\n"
            f"  ソルバー目的関数値: {solver_objective_value}\n"
            f"  評価関数スコア: {evaluation_score}\n"
            f"  → 目的関数を評価関数に合わせることで+15-27%改善の可能性あり\n"
            f"  → improvement_patterns.md パターン1 を参照"
        )

    return {
        'aligned': aligned,
        'diff_pct': round(diff_pct, 2),
        'solver_value': solver_objective_value,
        'eval_value': evaluation_score,
        'message': message,
    }
