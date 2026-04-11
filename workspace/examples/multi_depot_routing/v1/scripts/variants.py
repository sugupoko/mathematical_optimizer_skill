"""
Variants — multi_depot_routing v1

5 つの SC 重みプロファイルで比較し、トレードオフを明示する。
"""

import json
from pathlib import Path

from improve import DEFAULT_WEIGHTS, run_scenario

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

VARIANTS = {
    "V1_balanced":      {"desc": "バランス型",                      "weights": DEFAULT_WEIGHTS},
    "V2_distance_max":  {"desc": "距離最小化重視 (SC1)",              "weights": {**DEFAULT_WEIGHTS, "sc1_distance": 10}},
    "V3_few_vehicles":  {"desc": "車両数最小化 (SC4)",               "weights": {**DEFAULT_WEIGHTS, "sc4_vehicle_count": 1000}},
    "V4_home_zone":     {"desc": "ホームゾーン重視 (SC5)",           "weights": {**DEFAULT_WEIGHTS, "sc5_off_home": 50}},
    "V5_depot_balance": {"desc": "デポ負担均等化 (SC6)",              "weights": {**DEFAULT_WEIGHTS, "sc6_depot_balance": 100}},
}


def main():
    print("=" * 72)
    print("SC VARIANT COMPARISON — multi_depot_routing v1")
    print("=" * 72)
    print()

    out = {}
    for name, cfg in VARIANTS.items():
        print(f"[{name}] {cfg['desc']}")
        r = run_scenario(name, cfg["weights"])
        out[name] = r
        if r.get("solver_feasible"):
            hc = "HC OK" if r["hc_all_satisfied"] else "HC VIOL"
            sc = r["sc_evaluation"]["scores"]
            raw = r["sc_evaluation"]["raw"]
            print(f"    -> {r['solver_status']} | {hc} | "
                  f"overall={sc['overall']} km={raw['total_km']} used={raw['used_vehicles']} ({r['time_sec']}s)")

    out_path = RESULTS / "variant_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {out_path}")

    print()
    print(f"{'Variant':<22} {'obj':>8} {'km':>8} {'used':>5} {'SC1':>5} {'SC2':>5} {'SC3':>5} {'SC4':>5} {'SC5':>5} {'SC6':>5} {'avg':>5}")
    print("-" * 90)
    for name, r in out.items():
        if r.get("solver_feasible"):
            sc = r["sc_evaluation"]["scores"]
            raw = r["sc_evaluation"]["raw"]
            print(f"{name:<22} {r['objective']:>8.0f} {raw['total_km']:>8.1f} {raw['used_vehicles']:>5} "
                  f"{sc['SC1_distance']:>5.1f} {sc['SC2_fairness']:>5.1f} {sc['SC3_priority']:>5.1f} "
                  f"{sc['SC4_vehicle_count']:>5.1f} {sc['SC5_off_home']:>5.1f} {sc['SC6_depot_balance']:>5.1f} "
                  f"{sc['overall']:>5.1f}")


if __name__ == "__main__":
    main()
