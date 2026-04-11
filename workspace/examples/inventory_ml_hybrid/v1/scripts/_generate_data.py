"""Synthetic data generator for grocery inventory replenishment (ML + Opt hybrid).

Generates:
  - stores.csv       (8 rows)
  - skus.csv         (25 rows)
  - suppliers.csv    (5 rows)
  - trucks.csv       (6 rows)
  - constraints.csv  (18 HC + 8 SC)
  - sales_history.csv (8 * 25 * 730 = 146,000 rows)
"""

from __future__ import annotations

import math
import os
from datetime import date, timedelta

import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)
OUT = os.path.join(os.path.dirname(__file__), "..", "data")
OUT = os.path.abspath(OUT)
os.makedirs(OUT, exist_ok=True)


# ---------------------------------------------------------------------------
# Static masters
# ---------------------------------------------------------------------------

STORES = [
    ("S01", "Shibuya Urban",     "urban",    8500,  400,  120),
    ("S02", "Shinjuku Central",  "urban",    9200,  420,  130),
    ("S03", "Yokohama Bay",      "suburban", 5200,  520,  160),
    ("S04", "Kawasaki West",     "suburban", 4800,  500,  150),
    ("S05", "Chiba Park",        "suburban", 4200,  540,  170),
    ("S06", "Saitama North",     "suburban", 3900,  560,  180),
    ("S07", "Ikebukuro East",    "urban",    7800,  380,  110),
    ("S08", "Machida South",     "suburban", 4500,  500,  150),
]

SKUS = [
    # id,  name,                category,      shelf, vol,   refrig, supplier, case, unit_cost, retail
    # fresh_produce (5) - short shelf, high variance
    ("K01", "Tomato 500g",       "fresh_produce", 5,  0.008, 0, "SUP1",  6, 120, 260),
    ("K02", "Lettuce",           "fresh_produce", 4,  0.012, 0, "SUP1",  6, 100, 220),
    ("K03", "Banana bunch",      "fresh_produce", 6,  0.010, 0, "SUP1",  8, 130, 280),
    ("K04", "Strawberry pack",   "fresh_produce", 3,  0.006, 0, "SUP1",  6, 280, 580),
    ("K05", "Carrot 1kg",        "fresh_produce", 7,  0.011, 0, "SUP1",  6, 110, 240),
    # dairy (5) - refrigerated
    ("K06", "Milk 1L",           "dairy",        10,  0.0012,1, "SUP2", 12,  90, 210),
    ("K07", "Yogurt 400g",       "dairy",        12,  0.0008,1, "SUP2", 12, 110, 250),
    ("K08", "Cheese slice",      "dairy",        14,  0.0005,1, "SUP2", 12, 180, 390),
    ("K09", "Butter 200g",       "dairy",        14,  0.0004,1, "SUP2", 12, 320, 640),
    ("K10", "Cream 200ml",       "dairy",         7,  0.0005,1, "SUP2", 12, 150, 310),
    # deli (3) - refrigerated
    ("K11", "Sandwich",          "deli",          5,  0.0006,1, "SUP3", 10, 180, 390),
    ("K12", "Bento box",         "deli",          6,  0.0015,1, "SUP3",  8, 380, 720),
    ("K13", "Salad bowl",        "deli",          7,  0.0008,1, "SUP3", 10, 220, 450),
    # packaged_food (7) - long shelf, stable
    ("K14", "Instant ramen",     "packaged_food",240, 0.0020,0, "SUP4", 20, 110, 230),
    ("K15", "Rice 2kg",          "packaged_food",365, 0.0032,0, "SUP4", 10, 680,1280),
    ("K16", "Pasta 500g",        "packaged_food",300, 0.0008,0, "SUP4", 20, 160, 320),
    ("K17", "Canned tuna",       "packaged_food",720, 0.0003,0, "SUP4", 24, 140, 290),
    ("K18", "Cereal 500g",       "packaged_food",240, 0.0028,0, "SUP4", 12, 380, 720),
    ("K19", "Chocolate bar",     "packaged_food",180, 0.0002,0, "SUP4", 24, 120, 260),
    ("K20", "Cookies pack",      "packaged_food",180, 0.0010,0, "SUP4", 16, 240, 480),
    # beverages (5) - stable, temperature sensitive
    ("K21", "Cola 500ml",        "beverages",    200, 0.0006,0, "SUP5", 24,  90, 190),
    ("K22", "Orange juice 1L",   "beverages",    180, 0.0012,0, "SUP5", 12, 180, 380),
    ("K23", "Sports drink 500ml","beverages",    200, 0.0006,0, "SUP5", 24, 110, 230),
    ("K24", "Mineral water 2L",  "beverages",    365, 0.0022,0, "SUP5",  6, 100, 210),
    ("K25", "Beer 350ml",        "beverages",    180, 0.0004,0, "SUP5", 24, 200, 420),
]

SUPPLIERS = [
    # id, name, lead_time, min_case, truck_cost, refrig
    ("SUP1", "FreshFarm Kanto",     2,  5, 12000, 0),
    ("SUP2", "Nippon Dairy",        2, 10, 14000, 1),
    ("SUP3", "Daily Deli Kitchen",  1,  4,  9000, 1),
    ("SUP4", "Grocery Wholesale",   3, 10, 16000, 0),
    ("SUP5", "Beverage Dist.",      2,  8, 13000, 0),
]

TRUCKS = [
    # id,   type,        cap,  refrig, fixed, per_km
    ("T01", "standard",   30,  0,  8000, 120),
    ("T02", "standard",   30,  0,  8000, 120),
    ("T03", "standard",   25,  0,  7000, 110),
    ("T04", "refrig",     24,  1, 11000, 150),
    ("T05", "refrig",     22,  1, 10500, 145),
    ("T06", "small_urban",12,  0,  5500,  95),
]


# ---------------------------------------------------------------------------
# Holiday calendar (rough Japan holidays)
# ---------------------------------------------------------------------------
def build_holidays(start: date, end: date) -> set[date]:
    holidays: set[date] = set()
    for y in range(start.year, end.year + 1):
        # New Year
        for d in range(1, 4):
            holidays.add(date(y, 1, d))
        # Golden Week
        for d in range(29, 31):
            holidays.add(date(y, 4, d))
        for d in range(1, 6):
            holidays.add(date(y, 5, d))
        # Obon
        for d in range(13, 17):
            holidays.add(date(y, 8, d))
        # Christmas / year-end
        holidays.add(date(y, 12, 24))
        holidays.add(date(y, 12, 25))
        holidays.add(date(y, 12, 31))
    return {h for h in holidays if start <= h <= end}


def temperature_for_day(d: date) -> float:
    """Average daily temperature in Tokyo-ish."""
    doy = d.timetuple().tm_yday
    base = 15 + 13 * math.sin(2 * math.pi * (doy - 110) / 365.0)
    return float(base + RNG.normal(0, 2.5))


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------
def write_masters() -> None:
    pd.DataFrame(
        STORES,
        columns=["store_id", "name", "region", "daily_footfall", "storage_capacity_m3", "refrigeration_capacity_m3"],
    ).to_csv(os.path.join(OUT, "stores.csv"), index=False)

    pd.DataFrame(
        SKUS,
        columns=["sku_id", "name", "category", "shelf_life_days", "unit_volume_m3", "needs_refrigeration",
                 "supplier_id", "case_size", "unit_cost", "retail_price"],
    ).to_csv(os.path.join(OUT, "skus.csv"), index=False)

    pd.DataFrame(
        SUPPLIERS,
        columns=["supplier_id", "name", "lead_time_days", "min_order_case", "truck_cost_per_trip", "refrigerated_truck"],
    ).to_csv(os.path.join(OUT, "suppliers.csv"), index=False)

    pd.DataFrame(
        TRUCKS,
        columns=["truck_id", "type", "capacity_m3", "refrigerated", "daily_fixed_cost", "cost_per_km"],
    ).to_csv(os.path.join(OUT, "trucks.csv"), index=False)


def write_constraints() -> None:
    rows = [
        # HCs
        ("HC01", "hard", "Order quantity must satisfy safety-stock requirement per (store, sku)"),
        ("HC02", "hard", "Order quantity must not exceed configured max_order per (store, sku)"),
        ("HC03", "hard", "Sum of ordered volume per store must fit within storage_capacity_m3"),
        ("HC04", "hard", "Refrigerated SKUs volume per store must fit within refrigeration_capacity_m3"),
        ("HC05", "hard", "Truck load (m3) must not exceed truck capacity"),
        ("HC06", "hard", "Refrigerated SKUs may only travel on refrigerated trucks"),
        ("HC07", "hard", "Orders must be whole multiples of supplier case_size"),
        ("HC08", "hard", "Each SKU may be ordered only from its mapped supplier"),
        ("HC09", "hard", "Each truck may be used at most once per day"),
        ("HC10", "hard", "Supplier lead time must be respected (order day + lead_time <= delivery)"),
        ("HC11", "hard", "Fresh-category order must not exceed remaining shelf capacity"),
        ("HC12", "hard", "No same-day emergency orders (min lead time = 1 day)"),
        ("HC13", "hard", "Refrigerated trucks required if supplier ships refrigerated goods"),
        ("HC14", "hard", "Truck must be in the supplier's allowed-truck list"),
        ("HC15", "hard", "Each used truck trip must exceed 60% utilization"),
        ("HC16", "hard", "Dry and fresh categories cannot share the same truck trip"),
        ("HC17", "hard", "Each store accepts at most 3 supplier deliveries per day"),
        ("HC18", "hard", "Two conflicting suppliers cannot be received simultaneously (dock clash)"),
        # SCs
        ("SC01", "soft", "Minimise total cost (inventory + waste + transport + stockout)"),
        ("SC02", "soft", "Minimise expected waste on perishables"),
        ("SC03", "soft", "Minimise stockout risk"),
        ("SC04", "soft", "Balance truck utilisation across fleet"),
        ("SC05", "soft", "Prefer longer-shelf-life SKUs for bulk orders"),
        ("SC06", "soft", "Favour local suppliers (lower transport)"),
        ("SC07", "soft", "Minimise number of truck trips"),
        ("SC08", "soft", "Maintain service level per category"),
    ]
    pd.DataFrame(rows, columns=["id", "type", "description"]).to_csv(
        os.path.join(OUT, "constraints.csv"), index=False
    )


def generate_sales() -> pd.DataFrame:
    start = date(2024, 1, 1)
    end = date(2025, 12, 31)  # 2 years incl. leap-year handling -> 731 days, but we clip
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    days = days[:730]  # lock to 730
    holidays = build_holidays(start, end)

    # Per-SKU base demand mean (per store per day)
    base_demand = {}
    for sku in SKUS:
        sku_id, _, cat, *_ = sku
        if cat == "fresh_produce":
            base_demand[sku_id] = RNG.uniform(10, 25)
        elif cat == "dairy":
            base_demand[sku_id] = RNG.uniform(20, 45)
        elif cat == "deli":
            base_demand[sku_id] = RNG.uniform(8, 18)
        elif cat == "packaged_food":
            base_demand[sku_id] = RNG.uniform(15, 35)
        else:  # beverages
            base_demand[sku_id] = RNG.uniform(25, 60)

    category_variance = {
        "fresh_produce": 0.35,
        "dairy": 0.18,
        "deli": 0.28,
        "packaged_food": 0.12,
        "beverages": 0.20,
    }

    store_factor = {s[0]: s[3] / 6000 for s in STORES}  # scale by footfall

    sku_lookup = {s[0]: s for s in SKUS}

    rows = []
    # Pre-compute temperatures once per day
    temps = {d: temperature_for_day(d) for d in days}

    for d in days:
        dow = d.weekday()  # 0=Mon
        is_weekend = 1 if dow >= 5 else 0
        is_holiday = 1 if d in holidays else 0
        temp = temps[d]
        month = d.month
        # monthly trend (payday uplift near end/start of month)
        month_trend = 1.0 + 0.04 * math.sin(2 * math.pi * d.day / 30.0)

        for store in STORES:
            sid = store[0]
            sf = store_factor[sid]
            for sku in SKUS:
                skid, _, cat, *_ = sku
                bd = base_demand[skid] * sf * month_trend

                # weekly seasonality
                if is_weekend:
                    bd *= 1.35
                if is_holiday:
                    bd *= 1.55

                # temperature effect
                if skid in ("K21", "K23", "K24", "K25"):  # cold drinks & beer
                    bd *= 1.0 + max(0.0, (temp - 18) * 0.035)
                if skid in ("K06", "K10"):  # milk/cream - winter uplift
                    bd *= 1.0 + max(0.0, (14 - temp) * 0.015)

                # promo (random, ~8%)
                is_promo = int(RNG.random() < 0.08)
                if is_promo:
                    bd *= 1.30

                # noise
                noise = RNG.normal(0, bd * category_variance[cat])
                units = max(0, int(round(bd + noise)))

                # price: retail with occasional discount on promo
                retail = sku_lookup[skid][9]
                price = retail * (0.85 if is_promo else 1.0)

                rows.append((d.isoformat(), sid, skid, units, round(price, 2),
                             round(temp, 1), is_holiday, is_promo))

    df = pd.DataFrame(
        rows,
        columns=["date", "store_id", "sku_id", "units_sold", "price_actual",
                 "temperature_c", "is_holiday", "is_promo"],
    )
    return df


def main() -> None:
    write_masters()
    write_constraints()
    print("[data-gen] masters + constraints written")

    df = generate_sales()
    path = os.path.join(OUT, "sales_history.csv")
    df.to_csv(path, index=False)
    print(f"[data-gen] sales_history.csv: {len(df):,} rows -> {path}")

    # Small sanity report
    print("[data-gen] date range:", df["date"].min(), "to", df["date"].max())
    print("[data-gen] stores:", df["store_id"].nunique(), "SKUs:", df["sku_id"].nunique())
    print("[data-gen] mean units/day/store/sku:", round(df["units_sold"].mean(), 2))


if __name__ == "__main__":
    main()
