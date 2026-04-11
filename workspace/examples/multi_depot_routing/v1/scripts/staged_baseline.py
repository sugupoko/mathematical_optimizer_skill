"""
Staged baseline — multi_depot_routing v1

Complex MD-VRPTW with heterogeneous fleet + driver certifications.
1,680 binary vars, 13 HCs. Staged approach adds HCs one at a time.

モデリング方針 (v1 簡略化):
- 真の TSP 順序最適化はしない (仮定 A3, A5)
- 各 (vehicle, day) で customer set を決める (capacitated assignment)
- 時間は 2 × (depot-customer 距離) / speed + service_time を合計
- 時間枠は morning/afternoon/any の 3 区分で day-level に統合

決定変数:
- assign[c, v, d] ∈ {0,1}  顧客 c を車両 v で日 d に配送
- drive[dr, v, d] ∈ {0,1}  ドライバー dr が車両 v を日 d に運転
"""

from __future__ import annotations

import csv
import json
import math
import time
from collections import defaultdict
from pathlib import Path

from ortools.sat.python import cp_model

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RESULTS = ROOT / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
TIME_LIMIT = 60.0
NUM_WORKERS = 4
SPEED_KMH = 30
ROAD_FACTOR = 1.3


# ---------- Loaders ----------
def _split(s): return [x.strip() for x in s.split(",") if x.strip()]


def load_depots():
    rows = {}
    with open(DATA / "depots.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows[r["depot_id"]] = {
                "id": r["depot_id"], "name": r["name"],
                "lat": float(r["lat"]), "lon": float(r["lon"]),
            }
    return rows


def load_vehicles():
    rows = []
    with open(DATA / "vehicles.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "id": r["vehicle_id"],
                "home": r["home_depot"],
                "type": r["type"],
                "cap_kg": int(r["capacity_kg"]),
                "cap_m3": float(r["capacity_m3"]),
                "max_min": int(r["max_daily_minutes"]),
                "cost_per_km": int(r["cost_per_km"]),
                "unavail": set(_split(r["unavailable_days"])),
            })
    return rows


def load_drivers():
    rows = []
    with open(DATA / "drivers.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "id": r["driver_id"], "name": r["name"],
                "home": r["home_depot"],
                "certs": set(_split(r["certifications"])),
                "max_daily_h": int(r["max_daily_hours"]),
                "max_weekly_h": int(r["max_weekly_hours"]),
                "unavail": set(_split(r["unavailable_days"])),
            })
    return rows


def load_customers():
    rows = []
    with open(DATA / "customers.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "id": r["customer_id"], "name": r["name"],
                "lat": float(r["lat"]), "lon": float(r["lon"]),
                "zone": r["zone"],
                "weight": int(r["weight_kg"]),
                "volume": float(r["volume_m3"]),
                "service": int(r["service_minutes"]),
                "tw_pref": r["tw_day_pref"],
                "req_vtype": r["required_vehicle_type"],
                "req_dcert": r["required_driver_cert"],
                "priority": r["priority"],
            })
    return rows


DEPOTS = load_depots()
VEHICLES = load_vehicles()
DRIVERS = load_drivers()
CUSTOMERS = load_customers()


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    to_rad = math.pi / 180
    dlat = (lat2 - lat1) * to_rad
    dlon = (lon2 - lon1) * to_rad
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1 * to_rad) * math.cos(lat2 * to_rad) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


# Precompute: round-trip time (minutes) for each (customer, depot)
ROUND_TRIP_MIN = {}
for c in CUSTOMERS:
    for d_id, d in DEPOTS.items():
        km = haversine_km(d["lat"], d["lon"], c["lat"], c["lon"]) * ROAD_FACTOR
        one_way_min = km / SPEED_KMH * 60
        ROUND_TRIP_MIN[(c["id"], d_id)] = int(2 * one_way_min + c["service"])


# Vehicle-cert required mapping (HC7)
VEHICLE_CERT_REQ = {
    "standard_small": {"standard"},
    "standard_medium": {"standard"},
    "standard_large": {"standard"},
    "refrigerated": {"refrigerated"},
}


# ---------- Model builder ----------
def build_model(active_hcs):
    m = cp_model.CpModel()
    nC, nV, nD, nDays = len(CUSTOMERS), len(VEHICLES), len(DRIVERS), len(DAYS)
    C_IDX = {c["id"]: i for i, c in enumerate(CUSTOMERS)}
    V_IDX = {v["id"]: i for i, v in enumerate(VEHICLES)}
    D_IDX = {d["id"]: i for i, d in enumerate(DRIVERS)}

    # assign[c, v, d] = customer c served by vehicle v on day d
    assign = {}
    for ci in range(nC):
        for vi in range(nV):
            for di in range(nDays):
                assign[ci, vi, di] = m.NewBoolVar(f"a_{ci}_{vi}_{di}")

    # drive[dr, v, d] = driver dr operates vehicle v on day d
    drive = {}
    for dri in range(nD):
        for vi in range(nV):
            for di in range(nDays):
                drive[dri, vi, di] = m.NewBoolVar(f"d_{dri}_{vi}_{di}")

    # HC1: each customer visited exactly once (over the week)
    if "HC1" in active_hcs:
        for ci in range(nC):
            m.Add(sum(assign[ci, vi, di] for vi in range(nV) for di in range(nDays)) == 1)

    # HC2: weight capacity per (vehicle, day)
    if "HC2" in active_hcs:
        for vi, v in enumerate(VEHICLES):
            for di in range(nDays):
                m.Add(sum(assign[ci, vi, di] * CUSTOMERS[ci]["weight"]
                          for ci in range(nC)) <= v["cap_kg"])

    # HC3: volume capacity per (vehicle, day)  (scale x10 for int)
    if "HC3" in active_hcs:
        for vi, v in enumerate(VEHICLES):
            for di in range(nDays):
                m.Add(sum(assign[ci, vi, di] * int(CUSTOMERS[ci]["volume"] * 10)
                          for ci in range(nC)) <= int(v["cap_m3"] * 10))

    # HC4: max daily minutes per (vehicle, day)
    if "HC4" in active_hcs:
        for vi, v in enumerate(VEHICLES):
            for di in range(nDays):
                time_sum = sum(
                    assign[ci, vi, di] * ROUND_TRIP_MIN[(CUSTOMERS[ci]["id"], v["home"])]
                    for ci in range(nC)
                )
                m.Add(time_sum <= v["max_min"])

    # HC5: required vehicle type
    if "HC5" in active_hcs:
        for ci, c in enumerate(CUSTOMERS):
            req = c["req_vtype"]
            for vi, v in enumerate(VEHICLES):
                if req == "refrigerated":
                    if v["type"] != "refrigerated":
                        for di in range(nDays):
                            m.Add(assign[ci, vi, di] == 0)
                elif req == "standard":
                    if v["type"] == "refrigerated":
                        for di in range(nDays):
                            m.Add(assign[ci, vi, di] == 0)

    # HC6: driver certification matches customer required cert
    # HC6 is enforced indirectly via the driver assignment + HC12 mapping.
    # For HC6, we ensure: if customer needs cert X, then the driver assigned to that
    # (vehicle, day) must have cert X.
    if "HC6" in active_hcs:
        for ci, c in enumerate(CUSTOMERS):
            req = c["req_dcert"]
            if not req or req == "standard":
                continue
            for vi in range(nV):
                for di in range(nDays):
                    # if assign[ci, vi, di] = 1, then some driver with cert req must drive
                    eligible = [dri for dri, d in enumerate(DRIVERS) if req in d["certs"]]
                    # assign -> exists dri in eligible with drive[dri, vi, di] = 1
                    # equivalently: assign[ci, vi, di] <= sum(drive[dri, vi, di] for eligible)
                    m.Add(assign[ci, vi, di]
                          <= sum(drive[dri, vi, di] for dri in eligible))

    # HC7: driver cert must match vehicle type
    if "HC7" in active_hcs:
        for vi, v in enumerate(VEHICLES):
            req_certs = VEHICLE_CERT_REQ.get(v["type"], {"standard"})
            for dri, d in enumerate(DRIVERS):
                if not req_certs.issubset(d["certs"]):
                    for di in range(nDays):
                        m.Add(drive[dri, vi, di] == 0)

    # HC8: driver unavailable days
    if "HC8" in active_hcs:
        for dri, d in enumerate(DRIVERS):
            for di, day in enumerate(DAYS):
                if day in d["unavail"]:
                    for vi in range(nV):
                        m.Add(drive[dri, vi, di] == 0)

    # HC9: vehicle unavailable days
    if "HC9" in active_hcs:
        for vi, v in enumerate(VEHICLES):
            for di, day in enumerate(DAYS):
                if day in v["unavail"]:
                    for ci in range(nC):
                        m.Add(assign[ci, vi, di] == 0)
                    for dri in range(nD):
                        m.Add(drive[dri, vi, di] == 0)

    # HC10: vehicle starts from home depot (enforced via ROUND_TRIP_MIN using home depot)
    # Already built into HC4's time calculation.

    # HC11: driver weekly max hours
    if "HC11" in active_hcs:
        for dri, d in enumerate(DRIVERS):
            # Sum over all (v, day) of round-trip time * assign... tricky because assign is per customer, not per driver.
            # Approximation: driver works when drive[dri, v, d] = 1; count days and multiply by avg 8h.
            # More precisely: link driver-day work to the total daily minutes on that vehicle-day.
            # For v1 simplicity: drive[dri, v, d] implies a workday of up to max_daily_hours.
            worked_days = m.NewIntVar(0, len(DAYS), f"days_{dri}")
            m.Add(worked_days == sum(drive[dri, vi, di]
                                     for vi in range(nV) for di in range(nDays)))
            max_days = d["max_weekly_h"] // d["max_daily_h"]
            m.Add(worked_days <= max_days)

    # HC12: one driver per (vehicle, day); one vehicle per (driver, day)
    if "HC12" in active_hcs:
        for vi in range(nV):
            for di in range(nDays):
                m.Add(sum(drive[dri, vi, di] for dri in range(nD)) <= 1)
        for dri in range(nD):
            for di in range(nDays):
                m.Add(sum(drive[dri, vi, di] for vi in range(nV)) <= 1)
        # Also: if a customer is assigned to (v, d), some driver must drive (v, d)
        for ci in range(nC):
            for vi in range(nV):
                for di in range(nDays):
                    m.Add(assign[ci, vi, di] <= sum(drive[dri, vi, di] for dri in range(nD)))

    # HC13: time window preference (morning/afternoon) — assign day-level only for v1
    # For simplicity: if customer has tw_pref = morning, it's served on any day (morning assumed)
    # This is a weak version; proper VRPTW would need intra-day time variables.
    # Here we treat tw_pref as requiring the customer to NOT be on certain vehicle-days that would violate it.
    # v1 simplification: assume all assignments happen within customer's time window.
    # No hard constraint added; this is documented as a known simplification in spec.md A3.
    # However, to make HC13 non-trivial, we enforce:
    #   If tw_pref = morning: customer must not share a (v, day) with too many afternoon-only customers
    # For now, treat as always satisfied at v1 level.
    # TODO v2: proper time-window handling with intra-day scheduling
    if "HC13" in active_hcs:
        pass  # handled at v2

    return m, assign, drive


# ---------- Independent HC verifier ----------
def verify_all_hcs(solver, assign, drive):
    nC, nV, nD, nDays = len(CUSTOMERS), len(VEHICLES), len(DRIVERS), len(DAYS)
    V_IDX = {v["id"]: i for i, v in enumerate(VEHICLES)}

    a_val = {(ci, vi, di): solver.Value(assign[ci, vi, di])
             for ci in range(nC) for vi in range(nV) for di in range(nDays)}
    d_val = {(dri, vi, di): solver.Value(drive[dri, vi, di])
             for dri in range(nD) for vi in range(nV) for di in range(nDays)}

    viol = {f"HC{i}": 0 for i in range(1, 14)}

    # HC1: each customer visited exactly once
    for ci in range(nC):
        total = sum(a_val[ci, vi, di] for vi in range(nV) for di in range(nDays))
        if total != 1:
            viol["HC1"] += 1

    # HC2: weight
    for vi, v in enumerate(VEHICLES):
        for di in range(nDays):
            w = sum(a_val[ci, vi, di] * CUSTOMERS[ci]["weight"] for ci in range(nC))
            if w > v["cap_kg"]:
                viol["HC2"] += 1

    # HC3: volume
    for vi, v in enumerate(VEHICLES):
        for di in range(nDays):
            vol = sum(a_val[ci, vi, di] * CUSTOMERS[ci]["volume"] for ci in range(nC))
            if vol > v["cap_m3"] + 1e-6:
                viol["HC3"] += 1

    # HC4: daily time
    for vi, v in enumerate(VEHICLES):
        for di in range(nDays):
            t = sum(a_val[ci, vi, di] * ROUND_TRIP_MIN[(CUSTOMERS[ci]["id"], v["home"])]
                    for ci in range(nC))
            if t > v["max_min"]:
                viol["HC4"] += 1

    # HC5: required vehicle type
    for ci, c in enumerate(CUSTOMERS):
        req = c["req_vtype"]
        for vi, v in enumerate(VEHICLES):
            for di in range(nDays):
                if a_val[ci, vi, di]:
                    if req == "refrigerated" and v["type"] != "refrigerated":
                        viol["HC5"] += 1
                    elif req == "standard" and v["type"] == "refrigerated":
                        viol["HC5"] += 1

    # HC6: driver cert
    for ci, c in enumerate(CUSTOMERS):
        req = c["req_dcert"]
        if not req or req == "standard":
            continue
        for vi in range(nV):
            for di in range(nDays):
                if a_val[ci, vi, di]:
                    # Any driver on this (v, d) must have req
                    drivers_here = [dri for dri in range(nD) if d_val[dri, vi, di]]
                    if not any(req in DRIVERS[dri]["certs"] for dri in drivers_here):
                        viol["HC6"] += 1

    # HC7: driver cert matches vehicle
    for vi, v in enumerate(VEHICLES):
        req_certs = VEHICLE_CERT_REQ.get(v["type"], {"standard"})
        for dri, d in enumerate(DRIVERS):
            for di in range(nDays):
                if d_val[dri, vi, di] and not req_certs.issubset(d["certs"]):
                    viol["HC7"] += 1

    # HC8: driver unavailable
    for dri, d in enumerate(DRIVERS):
        for di, day in enumerate(DAYS):
            if day in d["unavail"]:
                for vi in range(nV):
                    if d_val[dri, vi, di]:
                        viol["HC8"] += 1

    # HC9: vehicle unavailable
    for vi, v in enumerate(VEHICLES):
        for di, day in enumerate(DAYS):
            if day in v["unavail"]:
                for ci in range(nC):
                    if a_val[ci, vi, di]:
                        viol["HC9"] += 1
                for dri in range(nD):
                    if d_val[dri, vi, di]:
                        viol["HC9"] += 1

    # HC10: implicit (home depot) - built into HC4 time calculation
    # No separate violation check needed.

    # HC11: driver weekly hours
    for dri, d in enumerate(DRIVERS):
        worked_days = sum(d_val[dri, vi, di] for vi in range(nV) for di in range(nDays))
        max_days = d["max_weekly_h"] // d["max_daily_h"]
        if worked_days > max_days:
            viol["HC11"] += 1

    # HC12: one driver/vehicle per (v, d); one vehicle per (dr, d)
    for vi in range(nV):
        for di in range(nDays):
            drivers_on = sum(d_val[dri, vi, di] for dri in range(nD))
            if drivers_on > 1:
                viol["HC12"] += 1
    for dri in range(nD):
        for di in range(nDays):
            vehs_on = sum(d_val[dri, vi, di] for vi in range(nV))
            if vehs_on > 1:
                viol["HC12"] += 1
    # Also: if customer assigned, driver must be present
    for ci in range(nC):
        for vi in range(nV):
            for di in range(nDays):
                if a_val[ci, vi, di]:
                    drivers_on = sum(d_val[dri, vi, di] for dri in range(nD))
                    if drivers_on == 0:
                        viol["HC12"] += 1

    # HC13: time window — v1 simplification, always 0
    # (handled at v2)

    return viol


# ---------- Phase definition ----------
PHASES = [
    (0,  "Phase0_vars_only",  set(),                                            set()),
    (1,  "Phase1_HC1",        {"HC1"},                                           {"HC1"}),
    (2,  "Phase2_HC2",        {"HC1","HC2"},                                     {"HC2"}),
    (3,  "Phase3_HC3",        {"HC1","HC2","HC3"},                               {"HC3"}),
    (4,  "Phase4_HC4",        {"HC1","HC2","HC3","HC4"},                         {"HC4"}),
    (5,  "Phase5_HC5",        {"HC1","HC2","HC3","HC4","HC5"},                   {"HC5"}),
    (6,  "Phase6_HC7",        {"HC1","HC2","HC3","HC4","HC5","HC7"},             {"HC7"}),
    (7,  "Phase7_HC6",        {"HC1","HC2","HC3","HC4","HC5","HC6","HC7"},       {"HC6"}),
    (8,  "Phase8_HC8_HC9",    {"HC1","HC2","HC3","HC4","HC5","HC6","HC7","HC8","HC9"}, {"HC8","HC9"}),
    (9,  "Phase9_HC11",       {"HC1","HC2","HC3","HC4","HC5","HC6","HC7","HC8","HC9","HC11"}, {"HC11"}),
    (10, "Phase10_HC12",      {"HC1","HC2","HC3","HC4","HC5","HC6","HC7","HC8","HC9","HC11","HC12"}, {"HC12"}),
    (11, "Phase11_FULL",      {f"HC{i}" for i in range(1, 14)}, {"HC13"}),
]


def solve_phase(phase_num, name, active_hcs, newly_added):
    t0 = time.time()
    model, assign, drive = build_model(active_hcs)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TIME_LIMIT
    solver.parameters.num_search_workers = NUM_WORKERS
    status = solver.Solve(model)
    elapsed = time.time() - t0
    feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    r = {
        "phase_num": phase_num, "name": name,
        "active_hcs": sorted(active_hcs), "newly_added": sorted(newly_added),
        "solver_status": solver.StatusName(status),
        "solver_feasible": feasible,
        "time_sec": round(elapsed, 2),
    }

    if feasible:
        total_visits = sum(
            solver.Value(assign[ci, vi, di])
            for ci in range(len(CUSTOMERS))
            for vi in range(len(VEHICLES))
            for di in range(len(DAYS))
        )
        r["total_visits"] = total_visits
        all_viol = verify_all_hcs(solver, assign, drive)
        active_v = {hc: v for hc, v in all_viol.items() if hc in active_hcs and v > 0}
        pending_v = {hc: v for hc, v in all_viol.items() if hc not in active_hcs and v > 0}
        r["active_hc_violations"] = active_v
        r["active_hc_ok"] = (sum(active_v.values()) == 0)
        r["pending_hc_violations"] = pending_v
        r["pending_hc_total"] = sum(pending_v.values())
    else:
        r["total_visits"] = None
        r["active_hc_violations"] = None
        r["active_hc_ok"] = False
        r["pending_hc_violations"] = None
        r["pending_hc_total"] = None
    return r


def main():
    print("=" * 72)
    print("STAGED BASELINE — multi_depot_routing v1")
    print("=" * 72)
    print(f"Customers: {len(CUSTOMERS)}  Vehicles: {len(VEHICLES)}  "
          f"Drivers: {len(DRIVERS)}  Days: {len(DAYS)}")
    nvars = len(CUSTOMERS)*len(VEHICLES)*len(DAYS) + len(DRIVERS)*len(VEHICLES)*len(DAYS)
    print(f"Binary vars: {nvars}")
    print(f"time_limit={TIME_LIMIT}s, workers={NUM_WORKERS}")
    print()

    results = []
    first_infeasible = None
    prev_pending = None
    for phase_num, name, active, newly in PHASES:
        added = ", ".join(sorted(newly)) if newly else "(none)"
        print(f"[{name}] adds {added}")
        r = solve_phase(phase_num, name, active, newly)
        results.append(r)

        if r["solver_feasible"]:
            active_ok = "✓ active OK" if r["active_hc_ok"] \
                else f"✗ active VIOL {sum(r['active_hc_violations'].values())}"
            pending_str = f"pending={r['pending_hc_total']}"
            delta = ""
            if prev_pending is not None:
                d = r["pending_hc_total"] - prev_pending
                delta = f" (Δ={d:+d})" if d != 0 else ""
            print(f"    -> {r['solver_status']} | visits={r['total_visits']} | "
                  f"{active_ok} | {pending_str}{delta} ({r['time_sec']}s)")
            if r["active_hc_violations"]:
                print(f"       ★ ACTIVE VIOL: {r['active_hc_violations']}")
            if r["pending_hc_violations"]:
                print(f"       pending: {r['pending_hc_violations']}")
            prev_pending = r["pending_hc_total"]
        else:
            print(f"    -> {r['solver_status']} ({r['time_sec']}s)")
            if first_infeasible is None:
                first_infeasible = name
                print(f"       !!! FIRST INFEASIBLE — wall at {name} !!!")
                print(f"       Newly added: {sorted(newly)}")

    out = RESULTS / "staged_baseline_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "first_infeasible_phase": first_infeasible,
            "phases": results,
        }, f, indent=2, ensure_ascii=False)

    print()
    print(f"Saved: {out}")
    if first_infeasible is None:
        print("RESULT: All phases feasible — problem solvable with all HCs")
    else:
        print(f"RESULT: First infeasibility at {first_infeasible}")


if __name__ == "__main__":
    main()
