"""
Improve — multi_depot_routing v1

Baseline: 全 Phase feasible, 壁なし。
improve では SC1-SC6 を目的関数に組み込んで品質を最適化する。

シナリオ:
  A: balanced (default)
  B: distance emphasized (SC1 強化)
  C: fairness emphasized (SC2 強化)
  D: vehicle count minimized (SC4 強化)

各シナリオで独立 HC 検証器を実行し、全 13 HC 充足を確認する。
"""

from __future__ import annotations

import csv
import json
import math
import time
from pathlib import Path

from ortools.sat.python import cp_model

# Reuse loaders and helpers from staged_baseline
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from staged_baseline import (
    DEPOTS, VEHICLES, DRIVERS, CUSTOMERS, DAYS,
    SPEED_KMH, ROAD_FACTOR, VEHICLE_CERT_REQ,
    haversine_km, ROUND_TRIP_MIN,
    verify_all_hcs,
)

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"

TIME_LIMIT = 60.0
NUM_WORKERS = 4

DEFAULT_WEIGHTS = {
    "sc1_distance": 1,       # per km
    "sc2_fairness": 50,      # per hour spread
    "sc3_priority": 20,      # penalty for high-prio late
    "sc4_vehicle_count": 100, # per vehicle used
    "sc5_off_home": 5,       # per off-home customer assignment
    "sc6_depot_balance": 10, # per depot spread unit
}


def build_full_model(weights=None):
    """Build full model with all 13 HCs + SC objective."""
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update(weights)

    m = cp_model.CpModel()
    nC, nV, nD, nDays = len(CUSTOMERS), len(VEHICLES), len(DRIVERS), len(DAYS)
    C_IDX = {c["id"]: i for i, c in enumerate(CUSTOMERS)}
    V_IDX = {v["id"]: i for i, v in enumerate(VEHICLES)}

    assign = {(ci, vi, di): m.NewBoolVar(f"a_{ci}_{vi}_{di}")
              for ci in range(nC) for vi in range(nV) for di in range(nDays)}
    drive = {(dri, vi, di): m.NewBoolVar(f"d_{dri}_{vi}_{di}")
             for dri in range(nD) for vi in range(nV) for di in range(nDays)}

    # --- All HCs enforced ---
    # HC1
    for ci in range(nC):
        m.Add(sum(assign[ci, vi, di] for vi in range(nV) for di in range(nDays)) == 1)
    # HC2 weight
    for vi, v in enumerate(VEHICLES):
        for di in range(nDays):
            m.Add(sum(assign[ci, vi, di] * CUSTOMERS[ci]["weight"]
                      for ci in range(nC)) <= v["cap_kg"])
    # HC3 volume
    for vi, v in enumerate(VEHICLES):
        for di in range(nDays):
            m.Add(sum(assign[ci, vi, di] * int(CUSTOMERS[ci]["volume"] * 10)
                      for ci in range(nC)) <= int(v["cap_m3"] * 10))
    # HC4 daily time
    for vi, v in enumerate(VEHICLES):
        for di in range(nDays):
            t = sum(assign[ci, vi, di] * ROUND_TRIP_MIN[(CUSTOMERS[ci]["id"], v["home"])]
                    for ci in range(nC))
            m.Add(t <= v["max_min"])
    # HC5 vehicle type
    for ci, c in enumerate(CUSTOMERS):
        req = c["req_vtype"]
        for vi, v in enumerate(VEHICLES):
            if req == "refrigerated" and v["type"] != "refrigerated":
                for di in range(nDays):
                    m.Add(assign[ci, vi, di] == 0)
            elif req == "standard" and v["type"] == "refrigerated":
                for di in range(nDays):
                    m.Add(assign[ci, vi, di] == 0)
    # HC6 driver cert for customer
    for ci, c in enumerate(CUSTOMERS):
        req = c["req_dcert"]
        if not req or req == "standard":
            continue
        for vi in range(nV):
            for di in range(nDays):
                eligible = [dri for dri, d in enumerate(DRIVERS) if req in d["certs"]]
                m.Add(assign[ci, vi, di] <= sum(drive[dri, vi, di] for dri in eligible))
    # HC7 driver-vehicle cert
    for vi, v in enumerate(VEHICLES):
        req_certs = VEHICLE_CERT_REQ.get(v["type"], {"standard"})
        for dri, d in enumerate(DRIVERS):
            if not req_certs.issubset(d["certs"]):
                for di in range(nDays):
                    m.Add(drive[dri, vi, di] == 0)
    # HC8 driver unavailable
    for dri, d in enumerate(DRIVERS):
        for di, day in enumerate(DAYS):
            if day in d["unavail"]:
                for vi in range(nV):
                    m.Add(drive[dri, vi, di] == 0)
    # HC9 vehicle unavailable
    for vi, v in enumerate(VEHICLES):
        for di, day in enumerate(DAYS):
            if day in v["unavail"]:
                for ci in range(nC):
                    m.Add(assign[ci, vi, di] == 0)
                for dri in range(nD):
                    m.Add(drive[dri, vi, di] == 0)
    # HC11 driver weekly max days
    for dri, d in enumerate(DRIVERS):
        worked = m.NewIntVar(0, len(DAYS), f"wd_{dri}")
        m.Add(worked == sum(drive[dri, vi, di] for vi in range(nV) for di in range(nDays)))
        m.Add(worked <= d["max_weekly_h"] // d["max_daily_h"])
    # HC12 one driver per vehicle-day, one vehicle per driver-day
    for vi in range(nV):
        for di in range(nDays):
            m.Add(sum(drive[dri, vi, di] for dri in range(nD)) <= 1)
    for dri in range(nD):
        for di in range(nDays):
            m.Add(sum(drive[dri, vi, di] for vi in range(nV)) <= 1)
    # customer assigned => driver present on (v, d)
    for ci in range(nC):
        for vi in range(nV):
            for di in range(nDays):
                m.Add(assign[ci, vi, di] <= sum(drive[dri, vi, di] for dri in range(nD)))

    # --- SC objective terms ---
    obj_terms = []

    # SC1: total distance (sum of round-trip km)
    # scale km by 1 (integer), factor 10 for sub-km precision
    dist_terms = []
    for ci, c in enumerate(CUSTOMERS):
        for vi, v in enumerate(VEHICLES):
            d = DEPOTS[v["home"]]
            km = haversine_km(d["lat"], d["lon"], c["lat"], c["lon"]) * ROAD_FACTOR
            km_int = int(round(km * 10))  # 0.1km precision
            for di in range(nDays):
                dist_terms.append(assign[ci, vi, di] * km_int * 2)  # round-trip
    total_dist_10 = sum(dist_terms)  # in 0.1km units
    obj_terms.append((w["sc1_distance"], total_dist_10))

    # SC2: driver working hours fairness (spread of worked days)
    driver_days = []
    for dri in range(nD):
        dd = m.NewIntVar(0, len(DAYS), f"dd_{dri}")
        m.Add(dd == sum(drive[dri, vi, di] for vi in range(nV) for di in range(nDays)))
        driver_days.append(dd)
    max_dd = m.NewIntVar(0, len(DAYS), "max_dd")
    min_dd = m.NewIntVar(0, len(DAYS), "min_dd")
    m.AddMaxEquality(max_dd, driver_days)
    m.AddMinEquality(min_dd, driver_days)
    fairness_gap = m.NewIntVar(0, len(DAYS), "fg")
    m.Add(fairness_gap == max_dd - min_dd)
    obj_terms.append((w["sc2_fairness"], fairness_gap))

    # SC3: high priority customers scheduled early (days 0-1 preferred)
    sc3_late = []
    for ci, c in enumerate(CUSTOMERS):
        if c["priority"] != "high":
            continue
        for vi in range(nV):
            for di in range(nDays):
                if di >= 2:  # days 2,3,4 = late
                    sc3_late.append(assign[ci, vi, di] * (di - 1))
    if sc3_late:
        obj_terms.append((w["sc3_priority"], sum(sc3_late)))

    # SC4: vehicle count minimization (used vehicles)
    used = []
    for vi in range(nV):
        u = m.NewBoolVar(f"used_{vi}")
        # u = 1 iff at least one assignment
        m.AddMaxEquality(u, [assign[ci, vi, di]
                             for ci in range(nC) for di in range(nDays)])
        used.append(u)
    obj_terms.append((w["sc4_vehicle_count"], sum(used)))

    # SC5: off-home zone customer assignment (prefer customers in home depot's geographic zone)
    # simplified: penalty if customer zone prefix doesn't match depot
    zone_penalty = []
    DEPOT_ZONES = {"D1": "tokyo", "D2": "saitama", "D3": "yokohama"}
    for ci, c in enumerate(CUSTOMERS):
        for vi, v in enumerate(VEHICLES):
            depot_zone = DEPOT_ZONES.get(v["home"], "")
            if not c["zone"].startswith(depot_zone):
                for di in range(nDays):
                    zone_penalty.append(assign[ci, vi, di])
    if zone_penalty:
        obj_terms.append((w["sc5_off_home"], sum(zone_penalty)))

    # SC6: depot balance (spread of vehicle usage across depots)
    depot_used_count = {}
    for d_id in DEPOTS:
        d_vehs = [vi for vi, v in enumerate(VEHICLES) if v["home"] == d_id]
        cnt = m.NewIntVar(0, len(d_vehs) * len(DAYS), f"dcount_{d_id}")
        m.Add(cnt == sum(drive[dri, vi, di]
                         for dri in range(nD) for vi in d_vehs for di in range(nDays)))
        depot_used_count[d_id] = cnt
    max_dc = m.NewIntVar(0, 100, "max_dc")
    min_dc = m.NewIntVar(0, 100, "min_dc")
    m.AddMaxEquality(max_dc, list(depot_used_count.values()))
    m.AddMinEquality(min_dc, list(depot_used_count.values()))
    depot_spread = m.NewIntVar(0, 100, "depot_spread")
    m.Add(depot_spread == max_dc - min_dc)
    obj_terms.append((w["sc6_depot_balance"], depot_spread))

    m.Minimize(sum(c * t for c, t in obj_terms))

    return m, {
        "assign": assign,
        "drive": drive,
        "total_dist_10": total_dist_10,
        "fairness_gap": fairness_gap,
        "used": used,
        "depot_spread": depot_spread,
    }


def score_scs(solver, vars_d):
    assign = vars_d["assign"]
    drive = vars_d["drive"]
    nC, nV, nD, nDays = len(CUSTOMERS), len(VEHICLES), len(DRIVERS), len(DAYS)

    a_val = {(ci, vi, di): solver.Value(assign[ci, vi, di])
             for ci in range(nC) for vi in range(nV) for di in range(nDays)}
    d_val = {(dri, vi, di): solver.Value(drive[dri, vi, di])
             for dri in range(nD) for vi in range(nV) for di in range(nDays)}

    # SC1: total distance
    total_km = 0.0
    for ci, c in enumerate(CUSTOMERS):
        for vi, v in enumerate(VEHICLES):
            d = DEPOTS[v["home"]]
            km = haversine_km(d["lat"], d["lon"], c["lat"], c["lon"]) * ROAD_FACTOR
            for di in range(nDays):
                if a_val[ci, vi, di]:
                    total_km += 2 * km
    # Score: 100 at 0 km, 0 at 2000 km (arbitrary scale)
    sc1 = max(0, 100 - total_km / 20)

    # SC2: driver working days fairness
    driver_days = [sum(d_val[dri, vi, di] for vi in range(nV) for di in range(nDays))
                   for dri in range(nD)]
    spread_dd = max(driver_days) - min(driver_days) if driver_days else 0
    sc2 = max(0, 100 - spread_dd * 20)  # 100 at 0, 0 at spread 5

    # SC3: priority-early (count of high-prio customers on days 2+)
    sc3_late_count = 0
    total_high = 0
    for ci, c in enumerate(CUSTOMERS):
        if c["priority"] != "high":
            continue
        total_high += 1
        for vi in range(nV):
            for di in range(nDays):
                if a_val[ci, vi, di] and di >= 2:
                    sc3_late_count += 1
    sc3 = max(0, 100 - (sc3_late_count / max(1, total_high)) * 100)

    # SC4: vehicle count
    used_vehicles = sum(1 for vi in range(nV)
                        if any(a_val[ci, vi, di] for ci in range(nC) for di in range(nDays)))
    sc4 = max(0, 100 - (used_vehicles / nV) * 100 + 20)  # roughly: fewer = higher, min 20

    # SC5: off-home assignment ratio
    DEPOT_ZONES = {"D1": "tokyo", "D2": "saitama", "D3": "yokohama"}
    off_home = 0
    total_assigned = 0
    for ci, c in enumerate(CUSTOMERS):
        for vi, v in enumerate(VEHICLES):
            for di in range(nDays):
                if a_val[ci, vi, di]:
                    total_assigned += 1
                    depot_zone = DEPOT_ZONES.get(v["home"], "")
                    if not c["zone"].startswith(depot_zone):
                        off_home += 1
    sc5 = max(0, 100 - (off_home / max(1, total_assigned)) * 100)

    # SC6: depot balance
    depot_counts = {}
    for d_id in DEPOTS:
        d_vehs = [vi for vi, v in enumerate(VEHICLES) if v["home"] == d_id]
        depot_counts[d_id] = sum(d_val[dri, vi, di]
                                 for dri in range(nD) for vi in d_vehs for di in range(nDays))
    ds_values = list(depot_counts.values())
    depot_spread = max(ds_values) - min(ds_values)
    sc6 = max(0, 100 - depot_spread * 10)

    overall = round((sc1 + sc2 + sc3 + sc4 + sc5 + sc6) / 6, 1)
    return {
        "scores": {
            "SC1_distance": round(sc1, 1),
            "SC2_fairness": round(sc2, 1),
            "SC3_priority": round(sc3, 1),
            "SC4_vehicle_count": round(sc4, 1),
            "SC5_off_home": round(sc5, 1),
            "SC6_depot_balance": round(sc6, 1),
            "overall": overall,
        },
        "raw": {
            "total_km": round(total_km, 1),
            "driver_days_spread": spread_dd,
            "high_prio_late_pct": round(sc3_late_count / max(1, total_high) * 100, 1),
            "used_vehicles": used_vehicles,
            "off_home_pct": round(off_home / max(1, total_assigned) * 100, 1),
            "depot_spread": depot_spread,
        }
    }


def run_scenario(name, weights):
    t0 = time.time()
    model, vars_d = build_full_model(weights=weights)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TIME_LIMIT
    solver.parameters.num_search_workers = NUM_WORKERS
    status = solver.Solve(model)
    elapsed = time.time() - t0
    feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    r = {
        "scenario": name, "weights": weights,
        "solver_status": solver.StatusName(status),
        "solver_feasible": feasible,
        "time_sec": round(elapsed, 2),
    }
    if feasible:
        r["objective"] = solver.ObjectiveValue()
        hc = verify_all_hcs(solver, vars_d["assign"], vars_d["drive"])
        total_viol = sum(hc.values())
        r["hc_all_satisfied"] = total_viol == 0
        r["hc_total_violations"] = total_viol
        r["hc_violations_by_constraint"] = {k: v for k, v in hc.items() if v > 0}
        r["sc_evaluation"] = score_scs(solver, vars_d)
    return r


SCENARIOS = {
    "A_balanced":       {"desc": "Balanced (default)",            "weights": DEFAULT_WEIGHTS},
    "B_distance_max":   {"desc": "Distance minimized (SC1 heavy)", "weights": {**DEFAULT_WEIGHTS, "sc1_distance": 5}},
    "C_fairness_max":   {"desc": "Fairness (SC2 heavy)",           "weights": {**DEFAULT_WEIGHTS, "sc2_fairness": 200}},
    "D_few_vehicles":   {"desc": "Vehicle count minimized (SC4)",  "weights": {**DEFAULT_WEIGHTS, "sc4_vehicle_count": 500}},
}


def main():
    print("=" * 72)
    print("IMPROVE — multi_depot_routing v1")
    print("=" * 72)
    print("Baseline: all phases feasible, no wall")
    print()

    results = {}
    for name, cfg in SCENARIOS.items():
        print(f"[{name}] {cfg['desc']}")
        r = run_scenario(name, cfg["weights"])
        results[name] = r

        if r.get("solver_feasible"):
            hc = "HC ALL OK ✓" if r["hc_all_satisfied"] else f"HC VIOL {r['hc_total_violations']} ✗"
            sc = r["sc_evaluation"]["scores"]
            raw = r["sc_evaluation"]["raw"]
            print(f"    -> {r['solver_status']} | {hc} | obj={r['objective']:.0f} | "
                  f"overall SC={sc['overall']} ({r['time_sec']}s)")
            print(f"       km={raw['total_km']}, used_veh={raw['used_vehicles']}, "
                  f"driver_spread={raw['driver_days_spread']}")
            if not r["hc_all_satisfied"]:
                print(f"       violations: {r['hc_violations_by_constraint']}")
        else:
            print(f"    -> {r['solver_status']} ({r['time_sec']}s)")

    out = RESULTS / "improve_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
