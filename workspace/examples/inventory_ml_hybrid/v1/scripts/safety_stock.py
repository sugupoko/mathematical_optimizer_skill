"""Convert (forecast, prediction_std) into weekly order requirements.

Service level: 95% (z = 1.65)
safety_stock = z * prediction_std * sqrt(lead_time)
reorder_point = lead_time * mean_daily_demand + safety_stock
order_quantity = max(0, (forecast_week + safety_stock - current_stock))
                 rounded up to the supplier's case_size.

Current stock is estimated as: 2 * avg_daily_demand (i.e. ~2 days on hand).

Outputs:
    results/order_requirements.csv         (ML)
    results/order_requirements_naive.csv   (naive)
"""

from __future__ import annotations

import math
import os

import numpy as np
import pandas as pd

HERE = os.path.abspath(os.path.dirname(__file__))
V1 = os.path.abspath(os.path.join(HERE, ".."))
DATA = os.path.join(V1, "data")
RESULTS = os.path.join(V1, "results")

Z = 1.65  # 95% service level
INITIAL_STOCK_DAYS = 2.0


def load_masters() -> tuple[pd.DataFrame, pd.DataFrame]:
    skus = pd.read_csv(os.path.join(DATA, "skus.csv"))
    suppliers = pd.read_csv(os.path.join(DATA, "suppliers.csv"))
    return skus, suppliers


def build_requirements(forecast_path: str, out_path: str, label: str) -> pd.DataFrame:
    fc = pd.read_csv(forecast_path)
    skus, suppliers = load_masters()

    # weekly aggregate per (store, sku)
    agg = fc.groupby(["store_id", "sku_id"]).agg(
        forecast_week=("predicted_units", "sum"),
        mean_daily=("predicted_units", "mean"),
        std_daily=("prediction_std", "mean"),
    ).reset_index()

    agg = agg.merge(skus[["sku_id", "category", "case_size", "supplier_id",
                          "shelf_life_days", "unit_volume_m3", "needs_refrigeration"]],
                    on="sku_id")
    agg = agg.merge(suppliers[["supplier_id", "lead_time_days"]], on="supplier_id")

    agg["safety_stock"]  = Z * agg["std_daily"] * np.sqrt(agg["lead_time_days"].clip(lower=1))
    agg["reorder_point"] = agg["lead_time_days"] * agg["mean_daily"] + agg["safety_stock"]
    agg["current_stock"] = INITIAL_STOCK_DAYS * agg["mean_daily"]

    raw_q = agg["forecast_week"] + agg["safety_stock"] - agg["current_stock"]
    raw_q = raw_q.clip(lower=0)
    agg["required_units"] = raw_q
    # Round UP to nearest case
    agg["required_cases"] = np.ceil(agg["required_units"] / agg["case_size"]).astype(int)
    agg["required_cases"] = agg["required_cases"].clip(upper=40)  # HC02 max_order sanity cap

    agg["order_volume_m3"] = agg["required_cases"] * agg["case_size"] * agg["unit_volume_m3"]
    agg["label"] = label

    cols = ["store_id", "sku_id", "category", "supplier_id", "lead_time_days",
            "case_size", "forecast_week", "mean_daily", "std_daily",
            "safety_stock", "reorder_point", "current_stock",
            "required_units", "required_cases", "order_volume_m3",
            "needs_refrigeration", "shelf_life_days", "label"]
    out = agg[cols].copy()
    out.to_csv(out_path, index=False)
    print(f"[safety_stock] {label}: {len(out)} rows, total cases {int(out['required_cases'].sum())}")
    return out


def main() -> None:
    build_requirements(
        os.path.join(RESULTS, "forecast.csv"),
        os.path.join(RESULTS, "order_requirements.csv"),
        "ml",
    )
    build_requirements(
        os.path.join(RESULTS, "forecast_naive.csv"),
        os.path.join(RESULTS, "order_requirements_naive.csv"),
        "naive",
    )


if __name__ == "__main__":
    main()
