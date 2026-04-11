"""
Variants — clinic_nurse v1

5 つの SC 重みプロファイルで比較し、トレードオフを明示する。
"""

from __future__ import annotations

import json
from pathlib import Path

from improve import (
    DEFAULT_WEIGHTS,
    load_nurses,
    load_shifts,
    run_scenario,
)

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

VARIANTS = {
    "V1_balanced": {
        "desc": "バランス型（デフォルト）",
        "weights": DEFAULT_WEIGHTS,
    },
    "V2_fairness_max": {
        "desc": "公平性最重視（SC2+SC5）",
        "weights": {**DEFAULT_WEIGHTS, "sc2_fairness": 50, "sc5_weekend": 30},
    },
    "V3_home_max": {
        "desc": "ホームクリニック最重視（SC4）",
        "weights": {**DEFAULT_WEIGHTS, "sc4_home": 50},
    },
    "V4_welfare": {
        "desc": "福利重視（SC1連続勤務+SC6夜勤）",
        "weights": {**DEFAULT_WEIGHTS, "sc1_consecutive": 80, "sc6_evening": 50},
    },
    "V5_min_hours": {
        "desc": "最低時間最重視（SC3）",
        "weights": {**DEFAULT_WEIGHTS, "sc3_min_hours": 50},
    },
}


def main():
    nurses = load_nurses()
    shifts = load_shifts()

    print("=" * 72)
    print("SC VARIANT COMPARISON — clinic_nurse v1")
    print("=" * 72)
    print()

    out = {}
    for name, cfg in VARIANTS.items():
        print(f"[{name}] {cfg['desc']}")
        r = run_scenario(name, nurses, shifts, cfg["weights"])
        out[name] = r
        if r["solver_feasible"]:
            hc = r["hc_verify"]
            hc_str = "HC OK" if hc["all_satisfied"] else f"HC VIOL {hc['total_violations']}"
            sc = r["sc_evaluation"]["scores"]
            print(f"    -> {r['solver_status']} | {hc_str} | obj={r['objective']:.0f} | "
                  f"overall={sc['overall']} ({r['time_sec']}s)")

    out_path = RESULTS / "variant_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {out_path}")

    # Comparison table
    print()
    print(f"{'Variant':<22} {'HC':>4} {'obj':>6} {'SC1':>5} {'SC2':>5} {'SC3':>5} {'SC4':>5} {'SC5':>5} {'SC6':>5} {'avg':>6}")
    print("-" * 76)
    for name, r in out.items():
        if r.get("solver_feasible"):
            hc = "OK" if r["hc_verify"]["all_satisfied"] else "X"
            sc = r["sc_evaluation"]["scores"]
            print(f"{name:<22} {hc:>4} {r['objective']:>6.0f} "
                  f"{sc['SC1_consecutive']:>5.1f} {sc['SC2_fairness']:>5.1f} "
                  f"{sc['SC3_min_hours']:>5.1f} {sc['SC4_home_clinic']:>5.1f} "
                  f"{sc['SC5_weekend']:>5.1f} {sc['SC6_evening']:>5.1f} {sc['overall']:>6.1f}")


if __name__ == "__main__":
    main()
