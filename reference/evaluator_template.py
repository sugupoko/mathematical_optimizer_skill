"""
制約チェッカー・評価関数テンプレート

どの最適化問題でも「解の良し悪しを測る評価器」が必要。
これがないと改善の方向がわからない。

使い方:
  1. hard_constraints と soft_constraints を自分の問題に合わせて定義
  2. evaluate() を呼ぶと feasibility + soft_score が返る
  3. ソルバーの目的関数はこの soft_score と精密一致させる
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def evaluate(solution: Any, dataset: dict) -> dict:
    """
    解を評価する。

    Returns:
        {
            "feasibility": 1 or 0,
            "hard_violations": int,
            "hard_violations_detail": {"HC1": 0, "HC2": 3, ...},
            "soft_score": float,
            "soft_scores_detail": {"SC1": 100.0, "SC2": -50.0, ...},
            ... 問題固有の指標
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
