"""ML demand-forecast pipeline.

Trains a RandomForestRegressor on 22 months, validates on last 2 months,
then produces a 7-day forecast per (store, sku) with 80% prediction intervals.

Also computes a naive last-4-week same-day-of-week baseline for comparison.

Outputs:
    results/forecast.csv
    results/forecast_naive.csv
    results/forecast_metrics.json
"""

from __future__ import annotations

import json
import os
import time
from datetime import timedelta

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_percentage_error, mean_squared_error

HERE = os.path.abspath(os.path.dirname(__file__))
V1 = os.path.abspath(os.path.join(HERE, ".."))
DATA = os.path.join(V1, "data")
RESULTS = os.path.join(V1, "results")
os.makedirs(RESULTS, exist_ok=True)


# ---------------------------------------------------------------------------
def load_data() -> pd.DataFrame:
    df = pd.read_csv(os.path.join(DATA, "sales_history.csv"))
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values(["store_id", "sku_id", "date"]).reset_index(drop=True)


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["dow"] = df["date"].dt.dayofweek
    df["dom"] = df["date"].dt.day
    df["month"] = df["date"].dt.month
    df["is_weekend"] = (df["dow"] >= 5).astype(int)

    # lag + rolling per (store, sku) - already sorted by (store, sku, date)
    g = df.groupby(["store_id", "sku_id"], sort=False)["units_sold"]
    df["lag_1"]  = g.shift(1)
    df["lag_7"]  = g.shift(7)
    df["lag_14"] = g.shift(14)
    df["lag_28"] = g.shift(28)
    shifted = g.shift(1)
    df["roll_mean_7"]  = shifted.groupby([df["store_id"], df["sku_id"]], sort=False).transform(
        lambda s: s.rolling(7,  min_periods=1).mean())
    df["roll_mean_28"] = shifted.groupby([df["store_id"], df["sku_id"]], sort=False).transform(
        lambda s: s.rolling(28, min_periods=1).mean())

    df["store_idx"] = df["store_id"].astype("category").cat.codes
    df["sku_idx"]   = df["sku_id"].astype("category").cat.codes
    # sku -> category (joined later, but keep cheap)
    return df


FEATURES = [
    "dow", "dom", "month", "is_weekend", "is_holiday", "is_promo",
    "temperature_c",
    "lag_1", "lag_7", "lag_14", "lag_28",
    "roll_mean_7", "roll_mean_28",
    "store_idx", "sku_idx",
]


def train_and_validate(df: pd.DataFrame) -> tuple[RandomForestRegressor, dict, pd.DataFrame, float]:
    df_feat = add_features(df).dropna(subset=["lag_28", "roll_mean_28"]).reset_index(drop=True)

    split_date = df_feat["date"].max() - pd.Timedelta(days=60)
    train = df_feat[df_feat["date"] <= split_date]
    val   = df_feat[df_feat["date"] >  split_date]

    X_train = train[FEATURES].values
    y_train = train["units_sold"].values
    X_val   = val[FEATURES].values
    y_val   = val["units_sold"].values

    print(f"[forecast] train rows: {len(train):,}  val rows: {len(val):,}")

    t0 = time.time()
    model = RandomForestRegressor(
        n_estimators=50,
        max_depth=14,
        min_samples_leaf=5,
        n_jobs=-1,
        random_state=42,
    )
    model.fit(X_train, y_train)
    print(f"[forecast] trained in {time.time()-t0:.1f}s")

    pred_val = model.predict(X_val)
    residuals = y_val - pred_val
    resid_std = float(np.std(residuals))

    # Overall metrics (replace zero y to avoid MAPE blowup)
    y_val_safe = np.where(y_val == 0, 1, y_val)
    mape = float(mean_absolute_percentage_error(y_val_safe, np.clip(pred_val, 0, None)))
    rmse = float(np.sqrt(mean_squared_error(y_val, pred_val)))
    bias = float(np.mean(pred_val - y_val))

    # per-category metrics (join sku -> category)
    skus = pd.read_csv(os.path.join(DATA, "skus.csv"))[["sku_id", "category"]]
    val_out = val.copy()
    val_out["pred"] = pred_val
    val_out = val_out.merge(skus, on="sku_id")
    cat_metrics = {}
    for cat, sub in val_out.groupby("category"):
        y = sub["units_sold"].values
        p = np.clip(sub["pred"].values, 0, None)
        y_safe = np.where(y == 0, 1, y)
        cat_metrics[cat] = {
            "mape": float(mean_absolute_percentage_error(y_safe, p)),
            "rmse": float(np.sqrt(mean_squared_error(y, p))),
            "bias": float(np.mean(p - y)),
            "n": int(len(sub)),
        }

    # Feature importance
    imp = dict(sorted(
        zip(FEATURES, model.feature_importances_.tolist()),
        key=lambda kv: kv[1],
        reverse=True,
    ))

    metrics = {
        "overall": {"mape": mape, "rmse": rmse, "bias": bias, "resid_std": resid_std,
                    "train_rows": int(len(train)), "val_rows": int(len(val))},
        "per_category": cat_metrics,
        "feature_importance": imp,
        "model": "RandomForestRegressor",
        "n_estimators": 50,
    }
    return model, metrics, df_feat, resid_std


# ---------------------------------------------------------------------------
# Forecast next 7 days
# ---------------------------------------------------------------------------
def forecast_next_week(model: RandomForestRegressor, df_feat: pd.DataFrame,
                       resid_std: float) -> pd.DataFrame:
    """Iteratively roll forward 7 days, updating lags as we go."""
    df = df_feat.copy()
    last_date = df["date"].max()
    horizon = [last_date + pd.Timedelta(days=i) for i in range(1, 8)]

    # minimal features we need to update from the history
    store_cat = pd.read_csv(os.path.join(DATA, "stores.csv"))[["store_id"]]
    skus = pd.read_csv(os.path.join(DATA, "skus.csv"))[["sku_id"]]
    store_idx = {s: i for i, s in enumerate(sorted(store_cat["store_id"].unique()))}
    sku_idx   = {k: i for i, k in enumerate(sorted(skus["sku_id"].unique()))}

    # recent per-(store,sku) history as a list
    hist = {}
    for (sid, skid), sub in df.groupby(["store_id", "sku_id"]):
        hist[(sid, skid)] = sub["units_sold"].tolist()[-40:]

    # use the last known temperature per day-of-year as a simple proxy
    temp_by_dow = df.groupby(df["date"].dt.dayofweek)["temperature_c"].mean().to_dict()

    rows = []
    for d in horizon:
        dow = d.dayofweek
        dom = d.day
        month = d.month
        is_weekend = int(dow >= 5)
        # no promo / holiday assumed for next week
        is_holiday = 0
        is_promo = 0
        temp = float(temp_by_dow.get(dow, 20.0))

        for sid in store_idx:
            for skid in sku_idx:
                h = hist[(sid, skid)]
                def lag(k): return h[-k] if len(h) >= k else h[0]
                lag1 = lag(1); lag7 = lag(7); lag14 = lag(14); lag28 = lag(28)
                roll7  = float(np.mean(h[-7:]))
                roll28 = float(np.mean(h[-28:]))
                x = np.array([[dow, dom, month, is_weekend, is_holiday, is_promo, temp,
                               lag1, lag7, lag14, lag28, roll7, roll28,
                               store_idx[sid], sku_idx[skid]]], dtype=float)
                pred = float(model.predict(x)[0])
                pred = max(0.0, pred)
                rows.append({
                    "date": d.date().isoformat(),
                    "store_id": sid,
                    "sku_id": skid,
                    "predicted_units": pred,
                    "prediction_std": resid_std,
                    "lower_80": max(0.0, pred - 1.2816 * resid_std),
                    "upper_80": pred + 1.2816 * resid_std,
                })
                # update rolling history with prediction
                hist[(sid, skid)].append(pred)

    out = pd.DataFrame(rows)
    return out


def naive_forecast(df: pd.DataFrame) -> pd.DataFrame:
    """Last 4-week same-day-of-week average."""
    last_date = df["date"].max()
    horizon = [last_date + pd.Timedelta(days=i) for i in range(1, 8)]
    rows = []
    for d in horizon:
        target_dow = d.dayofweek
        cutoff = d - pd.Timedelta(days=28)
        sub = df[(df["date"] >= cutoff) & (df["date"] <= last_date) & (df["date"].dt.dayofweek == target_dow)]
        agg = sub.groupby(["store_id", "sku_id"])["units_sold"].mean().reset_index()
        for _, r in agg.iterrows():
            rows.append({
                "date": d.date().isoformat(),
                "store_id": r["store_id"],
                "sku_id": r["sku_id"],
                "predicted_units": float(r["units_sold"]),
            })
    out = pd.DataFrame(rows)
    # attach a std estimate: rolling 28-day stdev per (store, sku)
    std_map = df.groupby(["store_id", "sku_id"])["units_sold"].std().reset_index().rename(
        columns={"units_sold": "prediction_std"})
    out = out.merge(std_map, on=["store_id", "sku_id"], how="left")
    out["lower_80"] = np.clip(out["predicted_units"] - 1.2816 * out["prediction_std"], 0, None)
    out["upper_80"] = out["predicted_units"] + 1.2816 * out["prediction_std"]
    return out


def main() -> None:
    print("[forecast] loading sales history")
    df = load_data()
    print(f"[forecast] rows: {len(df):,}")

    model, metrics, df_feat, resid_std = train_and_validate(df)

    print("[forecast] overall MAPE:", round(metrics["overall"]["mape"], 4),
          "RMSE:", round(metrics["overall"]["rmse"], 3),
          "bias:", round(metrics["overall"]["bias"], 3))

    fc = forecast_next_week(model, df_feat, resid_std)
    fc.to_csv(os.path.join(RESULTS, "forecast.csv"), index=False)
    print(f"[forecast] ML forecast rows: {len(fc)}")

    fn = naive_forecast(df)
    fn.to_csv(os.path.join(RESULTS, "forecast_naive.csv"), index=False)
    print(f"[forecast] naive forecast rows: {len(fn)}")

    with open(os.path.join(RESULTS, "forecast_metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)
    print("[forecast] metrics saved")


if __name__ == "__main__":
    main()
