"""
Improve — clinic_nurse v1

Baseline で全 8 HC を満たす feasible 解に到達済み。
improve では SC1-SC6 を目的関数に組み込んで品質を最適化する。

シナリオ:
  A: balanced (default weights)
  B: fairness emphasized (SC2 + SC5)
  C: home clinic emphasized (SC4)
  D: welfare emphasized (SC6 evening limit + SC1 consecutive)

各シナリオで独立 HC 検証器を実行し、hc_all_satisfied を記録する。
"""

from __future__ import annotations

import csv
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from ortools.sat.python import cp_model

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RESULTS = ROOT / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

DAYS_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WEEKEND = {"Sat", "Sun"}
TIME_LIMIT = 60.0
NUM_WORKERS = 4


# ---------- Loaders (same as staged_baseline) ----------
def _split(s): return [x.strip() for x in s.split(",") if x.strip()]


def load_nurses():
    rows = []
    with open(DATA / "nurses.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "id": r["nurse_id"],
                "name": r["name"],
                "level": r["level"],
                "certs": set(_split(r["certifications"])),
                "max_h": int(r["max_hours_per_week"]),
                "min_h": int(r["min_hours_per_week"]),
                "home": r["home_clinic"],
                "unavail": set(_split(r["unavailable_days"])),
                "langs": set(_split(r["languages"])),
            })
    return rows


def load_shifts():
    rows = []
    with open(DATA / "shifts.csv", encoding="utf-8") as f:
        for idx, r in enumerate(csv.DictReader(f)):
            sh = int(r["start_time"].split(":")[0]) + int(r["start_time"].split(":")[1]) / 60
            eh = int(r["end_time"].split(":")[0]) + int(r["end_time"].split(":")[1]) / 60
            rows.append({
                "idx": idx,
                "week": int(r["week"]),
                "day": r["day"],
                "clinic": r["clinic"],
                "name": r["shift_name"],
                "hours": eh - sh,
                "required": int(r["nurse_required"]),
                "certs": set(_split(r["required_certifications"])),
                "senior_req": int(r["senior_required"]),
            })
    return rows


def shift_global_day(s):
    return (s["week"] - 1) * 7 + DAYS_ORDER.index(s["day"])


# ---------- Default weights ----------
DEFAULT_WEIGHTS = {
    "sc1_consecutive": 10,
    "sc2_fairness": 5,
    "sc3_min_hours": 8,
    "sc4_home": 4,
    "sc5_weekend": 3,
    "sc6_evening": 6,
}


# ---------- Full model ----------
def build_full_model(nurses, shifts, weights=None):
    weights = weights or DEFAULT_WEIGHTS
    m = cp_model.CpModel()
    nN, nS = len(nurses), len(shifts)

    # x[n, s] binary
    x = {(ni, si): m.NewBoolVar(f"x_{ni}_{si}")
         for ni in range(nN) for si in range(nS)}

    # --- HC1: shift demand ---
    for s in shifts:
        m.Add(sum(x[ni, s["idx"]] for ni in range(nN)) == s["required"])

    # --- HC2: max hours per week ---
    # hours are scaled by 10 to use integers (5.0h -> 50)
    for ni, n in enumerate(nurses):
        for wk in (1, 2):
            wk_shifts = [s for s in shifts if s["week"] == wk]
            m.Add(
                sum(int(s["hours"] * 10) * x[ni, s["idx"]] for s in wk_shifts)
                <= n["max_h"] * 10
            )

    # --- HC3: unavailable days ---
    for ni, n in enumerate(nurses):
        for s in shifts:
            if s["day"] in n["unavail"]:
                m.Add(x[ni, s["idx"]] == 0)

    # --- HC4: certs ---
    for ni, n in enumerate(nurses):
        for s in shifts:
            if not s["certs"].issubset(n["certs"]):
                m.Add(x[ni, s["idx"]] == 0)

    # --- HC5: no morning after evening (same nurse, next day) ---
    day_of = {s["idx"]: shift_global_day(s) for s in shifts}
    ev_by_day = defaultdict(list)
    mo_by_day = defaultdict(list)
    for s in shifts:
        d = day_of[s["idx"]]
        if s["name"] == "evening":
            ev_by_day[d].append(s["idx"])
        elif s["name"] == "morning":
            mo_by_day[d].append(s["idx"])
    for ni in range(nN):
        for d in range(14):
            for ev_si in ev_by_day.get(d, []):
                for mo_si in mo_by_day.get(d + 1, []):
                    m.Add(x[ni, ev_si] + x[ni, mo_si] <= 1)

    # --- HC6: at most 1 shift per day ---
    shifts_by_day = defaultdict(list)
    for s in shifts:
        shifts_by_day[day_of[s["idx"]]].append(s["idx"])
    for ni in range(nN):
        for d, s_list in shifts_by_day.items():
            m.Add(sum(x[ni, si] for si in s_list) <= 1)

    # --- HC7: senior required ---
    senior_idx = [ni for ni, n in enumerate(nurses) if n["level"] == "senior"]
    for s in shifts:
        if s["senior_req"] == 1:
            m.Add(sum(x[ni, s["idx"]] for ni in senior_idx) >= 1)

    # --- HC8: at most 1 clinic per day --- (subsumed by HC6, nothing to add)

    # ========================================
    # Soft constraints (penalty terms)
    # ========================================
    obj_terms = []

    # Shifts per nurse (integer variable)
    shifts_of_nurse = []
    for ni in range(nN):
        cnt = m.NewIntVar(0, nS, f"cnt_{ni}")
        m.Add(cnt == sum(x[ni, s["idx"]] for s in shifts))
        shifts_of_nurse.append(cnt)

    # Total hours per nurse (scaled x10)
    hours_of_nurse = []
    for ni in range(nN):
        h = m.NewIntVar(0, 1000, f"hours_{ni}")
        m.Add(h == sum(int(s["hours"] * 10) * x[ni, s["idx"]] for s in shifts))
        hours_of_nurse.append(h)

    # --- SC1: consecutive days > 5 penalty ---
    # We create a daily "works" indicator, then count windows of 6+ consecutive days
    sc1_violations = []
    for ni in range(nN):
        # works[d] = 1 if nurse worked on day d
        works = []
        for d in range(14):
            s_list = shifts_by_day[d]
            if not s_list:
                works.append(m.NewConstant(0))
                continue
            w = m.NewBoolVar(f"works_{ni}_{d}")
            m.Add(sum(x[ni, si] for si in s_list) >= 1).OnlyEnforceIf(w)
            m.Add(sum(x[ni, si] for si in s_list) == 0).OnlyEnforceIf(w.Not())
            works.append(w)

        # For each 6-day window, penalty if all 6 are 1
        for d_start in range(14 - 5):
            window = [works[d_start + i] for i in range(6)]
            all_work = m.NewBoolVar(f"allwork_{ni}_{d_start}")
            # all_work = 1 iff all 6 days worked
            m.Add(sum(window) >= 6).OnlyEnforceIf(all_work)
            m.Add(sum(window) <= 5).OnlyEnforceIf(all_work.Not())
            sc1_violations.append(all_work)

    if sc1_violations:
        obj_terms.append((weights["sc1_consecutive"], sum(sc1_violations)))

    # --- SC2: fairness — minimize max-min of shifts count ---
    max_sh = m.NewIntVar(0, nS, "max_sh")
    min_sh = m.NewIntVar(0, nS, "min_sh")
    m.AddMaxEquality(max_sh, shifts_of_nurse)
    m.AddMinEquality(min_sh, shifts_of_nurse)
    fairness_gap = m.NewIntVar(0, nS, "fairness_gap")
    m.Add(fairness_gap == max_sh - min_sh)
    obj_terms.append((weights["sc2_fairness"], fairness_gap))

    # --- SC3: min hours shortfall ---
    sc3_shortfall = []
    for ni, n in enumerate(nurses):
        needed = n["min_h"] * 10  # scaled
        short = m.NewIntVar(0, needed, f"sc3_short_{ni}")
        # For 2 weeks total, min_h per week = min_h, so 2*min_h for 2 weeks
        m.Add(short >= (2 * needed) - hours_of_nurse[ni])
        m.Add(short >= 0)
        sc3_shortfall.append(short)
    obj_terms.append((weights["sc3_min_hours"], sum(sc3_shortfall)))

    # --- SC4: home_clinic mismatch count ---
    sc4_off_home = []
    for ni, n in enumerate(nurses):
        for s in shifts:
            if s["clinic"] != n["home"]:
                sc4_off_home.append(x[ni, s["idx"]])
    if sc4_off_home:
        obj_terms.append((weights["sc4_home"], sum(sc4_off_home)))

    # --- SC5: weekend fair distribution (spread of weekend shifts per nurse) ---
    weekend_count_per_nurse = []
    for ni in range(nN):
        wc = m.NewIntVar(0, 20, f"weekend_{ni}")
        wks = [x[ni, s["idx"]] for s in shifts if s["day"] in WEEKEND]
        m.Add(wc == sum(wks))
        weekend_count_per_nurse.append(wc)
    max_we = m.NewIntVar(0, 20, "max_we")
    min_we = m.NewIntVar(0, 20, "min_we")
    m.AddMaxEquality(max_we, weekend_count_per_nurse)
    m.AddMinEquality(min_we, weekend_count_per_nurse)
    weekend_gap = m.NewIntVar(0, 20, "weekend_gap")
    m.Add(weekend_gap == max_we - min_we)
    obj_terms.append((weights["sc5_weekend"], weekend_gap))

    # --- SC6: evening shifts > 6 per nurse penalty ---
    sc6_excess = []
    for ni in range(nN):
        ev_count = m.NewIntVar(0, 20, f"ev_{ni}")
        m.Add(ev_count == sum(x[ni, s["idx"]] for s in shifts if s["name"] == "evening"))
        exc = m.NewIntVar(0, 20, f"ev_exc_{ni}")
        m.Add(exc >= ev_count - 6)
        m.Add(exc >= 0)
        sc6_excess.append(exc)
    obj_terms.append((weights["sc6_evening"], sum(sc6_excess)))

    # Objective
    m.Minimize(sum(w * term for w, term in obj_terms))

    return m, {
        "x": x,
        "shifts_of_nurse": shifts_of_nurse,
        "hours_of_nurse": hours_of_nurse,
        "fairness_gap": fairness_gap,
        "weekend_gap": weekend_gap,
        "sc1_violations": sc1_violations,
        "sc3_shortfall": sc3_shortfall,
        "sc4_off_home": sc4_off_home,
        "sc6_excess": sc6_excess,
    }


# ---------- Independent HC verifier ----------
def verify_hard_constraints(solver, vars_d, nurses, shifts):
    x = vars_d["x"]
    nN, nS = len(nurses), len(shifts)
    day_of = {s["idx"]: shift_global_day(s) for s in shifts}
    x_val = {(ni, s["idx"]): solver.Value(x[ni, s["idx"]])
             for ni in range(nN) for s in shifts}

    violations = {f"HC{i}": [] for i in range(1, 9)}

    # HC1
    for s in shifts:
        cnt = sum(x_val[ni, s["idx"]] for ni in range(nN))
        if cnt != s["required"]:
            violations["HC1"].append(f"shift {s['idx']}: {cnt}/{s['required']}")

    # HC2
    for ni, n in enumerate(nurses):
        for wk in (1, 2):
            h = sum(s["hours"] for s in shifts if s["week"] == wk and x_val[ni, s["idx"]])
            if h > n["max_h"] + 0.01:
                violations["HC2"].append(f"{n['id']} wk{wk}: {h:.1f}h > {n['max_h']}h")

    # HC3
    for ni, n in enumerate(nurses):
        for s in shifts:
            if s["day"] in n["unavail"] and x_val[ni, s["idx"]]:
                violations["HC3"].append(f"{n['id']} on {s['day']} (unavailable)")

    # HC4
    for ni, n in enumerate(nurses):
        for s in shifts:
            if x_val[ni, s["idx"]] and not s["certs"].issubset(n["certs"]):
                missing = s["certs"] - n["certs"]
                violations["HC4"].append(f"{n['id']} on shift{s['idx']} missing {missing}")

    # HC5
    for ni in range(nN):
        for s in shifts:
            if s["name"] != "evening" or not x_val[ni, s["idx"]]:
                continue
            d = day_of[s["idx"]]
            for s2 in shifts:
                if s2["name"] == "morning" and day_of[s2["idx"]] == d + 1 and x_val[ni, s2["idx"]]:
                    violations["HC5"].append(f"{nurses[ni]['id']} evening d{d} -> morning d{d+1}")

    # HC6
    for ni in range(nN):
        day_counts = defaultdict(int)
        for s in shifts:
            if x_val[ni, s["idx"]]:
                day_counts[day_of[s["idx"]]] += 1
        for d, c in day_counts.items():
            if c > 1:
                violations["HC6"].append(f"{nurses[ni]['id']} day{d}: {c} shifts")

    # HC7
    senior_idx = {ni for ni, n in enumerate(nurses) if n["level"] == "senior"}
    for s in shifts:
        if s["senior_req"] == 1:
            cnt = sum(x_val[ni, s["idx"]] for ni in senior_idx)
            if cnt < 1:
                violations["HC7"].append(f"shift{s['idx']}: 0 seniors")

    # HC8
    for ni in range(nN):
        day_clinics = defaultdict(set)
        for s in shifts:
            if x_val[ni, s["idx"]]:
                day_clinics[day_of[s["idx"]]].add(s["clinic"])
        for d, cs in day_clinics.items():
            if len(cs) > 1:
                violations["HC8"].append(f"{nurses[ni]['id']} day{d}: {cs}")

    totals = {hc: len(lst) for hc, lst in violations.items()}
    return {
        "all_satisfied": all(n == 0 for n in totals.values()),
        "total_violations": sum(totals.values()),
        "by_constraint": totals,
        "samples": {hc: lst[:3] for hc, lst in violations.items() if lst},
    }


# ---------- SC scoring (0-100) ----------
def score_soft_constraints(solver, vars_d, nurses, shifts):
    x = vars_d["x"]
    nN = len(nurses)

    x_val = {(ni, s["idx"]): solver.Value(x[ni, s["idx"]])
             for ni in range(nN) for s in shifts}

    # Raw stats
    shifts_per_nurse = [sum(x_val[ni, s["idx"]] for s in shifts) for ni in range(nN)]
    hours_per_nurse = [sum(s["hours"] for s in shifts if x_val[ni, s["idx"]]) for ni in range(nN)]

    # SC1: consecutive > 5 violations
    day_of = {s["idx"]: shift_global_day(s) for s in shifts}
    sc1_viol_nurses = 0
    for ni in range(nN):
        work_days = sorted({day_of[s["idx"]] for s in shifts if x_val[ni, s["idx"]]})
        max_consec = cur = 0
        prev = -10
        for d in work_days:
            if d == prev + 1:
                cur += 1
            else:
                cur = 1
            max_consec = max(max_consec, cur)
            prev = d
        if max_consec > 5:
            sc1_viol_nurses += 1
    sc1_score = max(0, 100 - sc1_viol_nurses * (100 / nN))

    # SC2: fairness — spread of hours
    spread_h = max(hours_per_nurse) - min(hours_per_nurse) if hours_per_nurse else 0
    # 100 at 0, 0 at spread >= 40
    sc2_score = max(0, 100 - spread_h * (100 / 40))

    # SC3: min hours met
    sc3_missed = sum(1 for ni, n in enumerate(nurses) if hours_per_nurse[ni] < 2 * n["min_h"])
    sc3_score = max(0, 100 - sc3_missed * (100 / nN))

    # SC4: home clinic fit
    home_assignments = 0
    total_assignments = 0
    for ni, n in enumerate(nurses):
        for s in shifts:
            if x_val[ni, s["idx"]]:
                total_assignments += 1
                if s["clinic"] == n["home"]:
                    home_assignments += 1
    sc4_score = round(home_assignments / total_assignments * 100, 1) if total_assignments else 0

    # SC5: weekend distribution
    weekend_counts = []
    for ni in range(nN):
        c = sum(1 for s in shifts if s["day"] in WEEKEND and x_val[ni, s["idx"]])
        weekend_counts.append(c)
    we_spread = max(weekend_counts) - min(weekend_counts) if weekend_counts else 0
    sc5_score = max(0, 100 - we_spread * (100 / 6))

    # SC6: evening <= 6
    sc6_viol = 0
    for ni in range(nN):
        ev = sum(1 for s in shifts if s["name"] == "evening" and x_val[ni, s["idx"]])
        if ev > 6:
            sc6_viol += 1
    sc6_score = max(0, 100 - sc6_viol * (100 / nN))

    overall = round((sc1_score + sc2_score + sc3_score + sc4_score + sc5_score + sc6_score) / 6, 1)

    return {
        "scores": {
            "SC1_consecutive": round(sc1_score, 1),
            "SC2_fairness": round(sc2_score, 1),
            "SC3_min_hours": round(sc3_score, 1),
            "SC4_home_clinic": round(sc4_score, 1),
            "SC5_weekend": round(sc5_score, 1),
            "SC6_evening": round(sc6_score, 1),
            "overall": overall,
        },
        "raw": {
            "hours_per_nurse": hours_per_nurse,
            "shifts_per_nurse": shifts_per_nurse,
            "hours_spread": spread_h,
            "home_fit_pct": sc4_score,
            "weekend_spread": we_spread,
            "sc1_violators": sc1_viol_nurses,
            "sc3_missed": sc3_missed,
            "sc6_violators": sc6_viol,
        }
    }


# ---------- Scenario runner ----------
def run_scenario(name, nurses, shifts, weights):
    t0 = time.time()
    model, vars_d = build_full_model(nurses, shifts, weights=weights)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TIME_LIMIT
    solver.parameters.num_search_workers = NUM_WORKERS
    status = solver.Solve(model)
    elapsed = time.time() - t0
    feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    result = {
        "scenario": name,
        "weights": weights,
        "solver_status": solver.StatusName(status),
        "solver_feasible": feasible,
        "time_sec": round(elapsed, 2),
    }

    if feasible:
        result["objective"] = solver.ObjectiveValue()
        result["hc_verify"] = verify_hard_constraints(solver, vars_d, nurses, shifts)
        result["hc_all_satisfied"] = result["hc_verify"]["all_satisfied"]
        result["sc_evaluation"] = score_soft_constraints(solver, vars_d, nurses, shifts)
    return result


SCENARIOS = {
    "A_balanced": {
        "desc": "Balanced SC weights (default)",
        "weights": DEFAULT_WEIGHTS,
    },
    "B_fairness": {
        "desc": "Fairness emphasized (SC2 + SC5 boosted)",
        "weights": {**DEFAULT_WEIGHTS, "sc2_fairness": 30, "sc5_weekend": 20},
    },
    "C_home_clinic": {
        "desc": "Home clinic preferred (SC4 boosted)",
        "weights": {**DEFAULT_WEIGHTS, "sc4_home": 30},
    },
    "D_welfare": {
        "desc": "Welfare emphasized (SC1 + SC6 boosted)",
        "weights": {**DEFAULT_WEIGHTS, "sc1_consecutive": 50, "sc6_evening": 30},
    },
}


def main():
    nurses = load_nurses()
    shifts = load_shifts()

    print("=" * 72)
    print("IMPROVE — clinic_nurse v1")
    print("=" * 72)
    print(f"Nurses: {len(nurses)}  Shifts: {len(shifts)}  Vars: {len(nurses)*len(shifts)}")
    print()

    results = {}
    for name, cfg in SCENARIOS.items():
        print(f"[{name}] {cfg['desc']}")
        r = run_scenario(name, nurses, shifts, cfg["weights"])
        results[name] = r
        if r["solver_feasible"]:
            hc = r["hc_verify"]
            hc_str = "HC ALL OK" if hc["all_satisfied"] else f"HC VIOL {hc['total_violations']}"
            sc = r["sc_evaluation"]["scores"]
            print(f"    -> {r['solver_status']} | {hc_str} | obj={r['objective']:.0f} | "
                  f"overall SC={sc['overall']} ({r['time_sec']}s)")
            print(f"       SC scores: SC1={sc['SC1_consecutive']} SC2={sc['SC2_fairness']} "
                  f"SC3={sc['SC3_min_hours']} SC4={sc['SC4_home_clinic']} "
                  f"SC5={sc['SC5_weekend']} SC6={sc['SC6_evening']}")
        else:
            print(f"    -> {r['solver_status']} ({r['time_sec']}s)")

    out = RESULTS / "improve_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print()
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
