"""SC重み付けバリアント比較: 5パターンの重みプロファイルでスコア比較。

各SCを0-100でスコアリングし、重みプロファイルごとの結果を比較する。

Usage:
    python variants.py
"""

from __future__ import annotations

import json
import logging
import copy
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from baseline import evaluate, load_data
from improve import solve_cpsat_improved


VARIANTS = {
    "V1_balanced": {
        "description": "バランス型（デフォルト）",
        "weights": {
            "underfill": 1000,
            "fairness": 50,
            "min_hours": 30,
            "night_limit": 20,
            "training": 15,
            "consecutive": 25,
        },
    },
    "V2_fairness_max": {
        "description": "公平性最重視",
        "weights": {
            "underfill": 1000,
            "fairness": 300,
            "min_hours": 100,
            "night_limit": 20,
            "training": 15,
            "consecutive": 25,
        },
    },
    "V3_coverage_max": {
        "description": "充足率最重視",
        "weights": {
            "underfill": 2000,
            "fairness": 10,
            "min_hours": 10,
            "night_limit": 5,
            "training": 5,
            "consecutive": 5,
        },
    },
    "V4_welfare": {
        "description": "従業員福利重視（夜勤・連勤制限強化）",
        "weights": {
            "underfill": 1000,
            "fairness": 80,
            "min_hours": 50,
            "night_limit": 100,
            "training": 15,
            "consecutive": 100,
        },
    },
    "V5_training_focus": {
        "description": "研修体制重視",
        "weights": {
            "underfill": 1000,
            "fairness": 50,
            "min_hours": 30,
            "night_limit": 20,
            "training": 200,
            "consecutive": 25,
        },
    },
}


def main():
    data = load_data()
    results = {}

    for variant_id, variant in VARIANTS.items():
        logger.info("=== %s: %s ===", variant_id, variant["description"])
        schedule, obj_val = solve_cpsat_improved(data, weights=variant["weights"])
        evaluation = evaluate(schedule, data)

        results[variant_id] = {
            "description": variant["description"],
            "weights": variant["weights"],
            "feasible": evaluation["feasible"],
            "hard_violations": evaluation["hard_violations"],
            "hard_violations_detail": evaluation["hard_violations_detail"],
            "soft_score_total": evaluation["soft_score_total"],
            "soft_scores": evaluation["soft_scores"],
            "total_assignments": evaluation["stats"]["total_assignments"],
            "hours_std_dev": evaluation["stats"]["hours_std_dev"],
            "hours_per_employee": evaluation["stats"]["hours_per_employee"],
            "objective_value": obj_val,
        }

    # Save
    with open(RESULTS_DIR / "variant_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info("Results saved to %s", RESULTS_DIR / "variant_results.json")

    # Print comparison table
    print("\n" + "="*100)
    print("  SC Weight Variant Comparison (0-100 scores)")
    print("="*100)
    print(f"{'Variant':<24} {'HC':>4} {'SC Total':>8} {'SC1':>6} {'SC2':>6} {'SC3':>6} {'SC4':>6} {'SC5':>6} {'StdDev':>7}")
    print("-"*100)
    for vid, r in results.items():
        sc = r["soft_scores"]
        print(f"{r['description']:<24} {r['hard_violations']:>4} {r['soft_score_total']:>8.1f} "
              f"{sc['SC1_consecutive']:>6.1f} {sc['SC2_fairness']:>6.1f} {sc['SC3_min_hours']:>6.1f} "
              f"{sc['SC4_night_limit']:>6.1f} {sc['SC5_training']:>6.1f} {r['hours_std_dev']:>7.2f}")


if __name__ == "__main__":
    main()
