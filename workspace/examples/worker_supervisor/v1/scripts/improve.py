"""
Improve — worker_supervisor v1

Baseline: Phase 5 (HC7+HC8) で壁。en+reception 4名 vs 需要 5名/シフト の鳩の巣違反。

4 シナリオで feasibility 回復を試みる:
  A. W021 (en+reception) を 1 名追加採用 (入力変更)
  B. HC1 を bilingual+reception シフトで 5→4 に緩和 (仕様変更)
  C. HC1 を soft 化 (penalty 付き shortage 許容)
  D. HC8 を soft 化 (非英語可を bilingual シフトに許容)

各シナリオで **独立 HC 検証器** を実行し、元の 12 HC をどの程度満たすか記録する。
ソルバーの feasible フラグではなく、hc_all_satisfied を主として判定。
"""

from __future__ import annotations

import csv
import json
import time
from collections import defaultdict
from pathlib import Path

from ortools.sat.python import cp_model

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RESULTS = ROOT / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

DAYS_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TIME_LIMIT = 60.0
NUM_WORKERS = 4


# ---------- Loaders (same as staged_baseline) ----------
def _split(s): return [x.strip() for x in s.split(",") if x.strip()]


def load_workers():
    rows = []
    with open(DATA / "workers.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "id": r["worker_id"], "name": r["name"],
                "skills": set(_split(r["skills"])), "level": r["level"],
                "max_h": int(r["max_hours_per_week"]),
                "min_h": int(r["min_hours_per_week"]),
                "unavail": set(_split(r["unavailable_days"])),
                "langs": set(_split(r["languages"])),
            })
    return rows


def load_supervisors():
    rows = []
    with open(DATA / "supervisors.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "id": r["supervisor_id"], "name": r["name"], "role": r["role"],
                "max_h": int(r["max_hours_per_week"]),
                "min_h": int(r["min_hours_per_week"]),
                "unavail": set(_split(r["unavailable_days"])),
                "langs": set(_split(r["languages"])),
                "specs": set(_split(r["specialties"])),
            })
    return rows


def load_shifts():
    rows = []
    with open(DATA / "shifts.csv", encoding="utf-8") as f:
        for idx, r in enumerate(csv.DictReader(f)):
            rows.append({
                "idx": idx, "week": int(r["week"]), "day": r["day"],
                "name": r["shift_name"],
                "w_req": int(r["worker_required"]),
                "v_req": int(r["supervisor_required"]),
                "skills": set(_split(r["required_skills"])),
                "bilingual": r["bilingual_required"].strip().lower() == "yes",
                "hours": 8,
            })
    return rows


def load_pairs():
    forb, ment, pref = [], [], []
    with open(DATA / "pair_constraints.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t = r["constraint_type"]
            tup = (r["entity1"], r["entity2"])
            if t == "forbidden": forb.append(tup)
            elif t == "mentorship": ment.append(tup)
            elif t == "preferred": pref.append(tup)
    return forb, ment, pref


def shift_global_day(s):
    return (s["week"] - 1) * 7 + DAYS_ORDER.index(s["day"])


# ---------- Default weights ----------
DEFAULT_WEIGHTS = {
    "sc1": 3, "sc2": 2, "sc3": 2, "sc4": 4, "sc5": 4,
    "sc6": 2, "sc7": 3, "sc8": -2,
    "shortage_hc1": 1000, "shortage_hc8": 1000,
}


# ---------- Full model builder with optional softening ----------
def build_full_model(workers, supervisors, shifts, forbidden, mentor, preferred,
                     soften_hc1=False, soften_hc8=False, relax_hc1_bilingual=False,
                     weights=None):
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update(weights)

    m = cp_model.CpModel()
    nW, nV, nS = len(workers), len(supervisors), len(shifts)
    W_IDX = {wo["id"]: i for i, wo in enumerate(workers)}
    V_IDX = {v["id"]: i for i, v in enumerate(supervisors)}
    day_of = {s["idx"]: shift_global_day(s) for s in shifts}

    wx = {(wi, s["idx"]): m.NewBoolVar(f"wx_{wi}_{s['idx']}")
          for wi in range(nW) for s in shifts}
    vx = {(vi, s["idx"]): m.NewBoolVar(f"vx_{vi}_{s['idx']}")
          for vi in range(nV) for s in shifts}

    # ---- HC1 worker demand ----
    w_short = {}
    for s in shifts:
        si = s["idx"]
        target = s["w_req"]
        if relax_hc1_bilingual and s["bilingual"] and "reception" in s["skills"]:
            target = 4
        if soften_hc1:
            slack = m.NewIntVar(0, target, f"ws_{si}")
            w_short[si] = slack
            m.Add(sum(wx[wi, si] for wi in range(nW)) + slack == target)
        else:
            m.Add(sum(wx[wi, si] for wi in range(nW)) == target)

    # ---- HC2 supervisor demand ----
    for s in shifts:
        m.Add(sum(vx[vi, s["idx"]] for vi in range(nV)) == s["v_req"])

    # ---- HC3, HC4 max hours ----
    for wi, wo in enumerate(workers):
        for wk in (1, 2):
            m.Add(sum(wx[wi, s["idx"]] * 8 for s in shifts if s["week"] == wk)
                  <= wo["max_h"])
    for vi, v in enumerate(supervisors):
        for wk in (1, 2):
            m.Add(sum(vx[vi, s["idx"]] * 8 for s in shifts if s["week"] == wk)
                  <= v["max_h"])

    # ---- HC5, HC6 unavailable ----
    for wi, wo in enumerate(workers):
        for s in shifts:
            if s["day"] in wo["unavail"]:
                m.Add(wx[wi, s["idx"]] == 0)
    for vi, v in enumerate(supervisors):
        for s in shifts:
            if s["day"] in v["unavail"]:
                m.Add(vx[vi, s["idx"]] == 0)

    # ---- HC7 skill ----
    for wi, wo in enumerate(workers):
        for s in shifts:
            if s["skills"] and not s["skills"].issubset(wo["skills"]):
                m.Add(wx[wi, s["idx"]] == 0)

    # ---- HC8 bilingual ----
    nonbi_penalty = []
    for s in shifts:
        if not s["bilingual"]:
            continue
        for wi, wo in enumerate(workers):
            if "en" not in wo["langs"]:
                if soften_hc8:
                    nonbi_penalty.append(wx[wi, s["idx"]])
                else:
                    m.Add(wx[wi, s["idx"]] == 0)
        for vi, v in enumerate(supervisors):
            if "en" not in v["langs"]:
                if soften_hc8:
                    nonbi_penalty.append(vx[vi, s["idx"]])
                else:
                    m.Add(vx[vi, s["idx"]] == 0)

    # ---- HC9, HC10 rest ----
    for wi in range(nW):
        for s in shifts:
            if s["name"] != "night":
                continue
            d = day_of[s["idx"]]
            for s2 in shifts:
                if s2["name"] == "morning" and day_of[s2["idx"]] == d + 1:
                    m.Add(wx[wi, s["idx"]] + wx[wi, s2["idx"]] <= 1)
    for vi in range(nV):
        for s in shifts:
            if s["name"] != "night":
                continue
            d = day_of[s["idx"]]
            for s2 in shifts:
                if s2["name"] == "morning" and day_of[s2["idx"]] == d + 1:
                    m.Add(vx[vi, s["idx"]] + vx[vi, s2["idx"]] <= 1)

    # ---- HC11 forbidden pairs ----
    for wid, vid in forbidden:
        if wid not in W_IDX or vid not in V_IDX:
            continue
        wi, vi = W_IDX[wid], V_IDX[vid]
        for s in shifts:
            m.Add(wx[wi, s["idx"]] + vx[vi, s["idx"]] <= 1)

    # ---- HC12 mentorship ----
    for wid, vid in mentor:
        if wid not in W_IDX or vid not in V_IDX:
            continue
        wi, vi = W_IDX[wid], V_IDX[vid]
        pair_vars = []
        for s in shifts:
            p = m.NewBoolVar(f"mpair_{wid}_{vid}_{s['idx']}")
            m.Add(p <= wx[wi, s["idx"]])
            m.Add(p <= vx[vi, s["idx"]])
            m.Add(p >= wx[wi, s["idx"]] + vx[vi, s["idx"]] - 1)
            pair_vars.append(p)
        m.Add(sum(pair_vars) >= 2)

    # ---- SC objective terms ----
    obj_terms = []
    if w_short:
        obj_terms.append((w["shortage_hc1"], sum(w_short.values())))
    if nonbi_penalty:
        obj_terms.append((w["shortage_hc8"], sum(nonbi_penalty)))

    # SC2 worker fairness (hours spread)
    w_hours = []
    for wi in range(nW):
        h = m.NewIntVar(0, 80, f"wh_{wi}")
        m.Add(h == sum(wx[wi, s["idx"]] * 8 for s in shifts))
        w_hours.append(h)
    max_wh = m.NewIntVar(0, 80, "maxwh")
    min_wh = m.NewIntVar(0, 80, "minwh")
    m.AddMaxEquality(max_wh, w_hours)
    m.AddMinEquality(min_wh, w_hours)
    spread_w = m.NewIntVar(0, 80, "spreadw")
    m.Add(spread_w == max_wh - min_wh)
    obj_terms.append((w["sc2"], spread_w))

    # SC3 supervisor fairness
    v_hours = []
    for vi in range(nV):
        h = m.NewIntVar(0, 80, f"vh_{vi}")
        m.Add(h == sum(vx[vi, s["idx"]] * 8 for s in shifts))
        v_hours.append(h)
    max_vh = m.NewIntVar(0, 80, "maxvh")
    min_vh = m.NewIntVar(0, 80, "minvh")
    m.AddMaxEquality(max_vh, v_hours)
    m.AddMinEquality(min_vh, v_hours)
    spread_v = m.NewIntVar(0, 80, "spreadv")
    m.Add(spread_v == max_vh - min_vh)
    obj_terms.append((w["sc3"], spread_v))

    # SC4 worker night > 4
    sc4 = []
    for wi in range(nW):
        nc = m.NewIntVar(0, 14, f"nc_{wi}")
        m.Add(nc == sum(wx[wi, s["idx"]] for s in shifts if s["name"] == "night"))
        exc = m.NewIntVar(0, 14, f"nexc_{wi}")
        m.Add(exc >= nc - 4)
        m.Add(exc >= 0)
        sc4.append(exc)
    obj_terms.append((w["sc4"], sum(sc4)))

    # SC5 supervisor night > 3
    sc5 = []
    for vi in range(nV):
        nc = m.NewIntVar(0, 14, f"vnc_{vi}")
        m.Add(nc == sum(vx[vi, s["idx"]] for s in shifts if s["name"] == "night"))
        exc = m.NewIntVar(0, 14, f"vnexc_{vi}")
        m.Add(exc >= nc - 3)
        m.Add(exc >= 0)
        sc5.append(exc)
    obj_terms.append((w["sc5"], sum(sc5)))

    # SC6 min hours shortfall (over 2 weeks)
    sc6 = []
    for wi, wo in enumerate(workers):
        target = wo["min_h"] * 2
        sh = m.NewIntVar(0, target, f"sh_{wi}")
        m.Add(sh >= target - w_hours[wi])
        m.Add(sh >= 0)
        sc6.append(sh)
    obj_terms.append((w["sc6"], sum(sc6)))

    # SC8 preferred pairs bonus (negative weight)
    pref_pair_vars = []
    for wid, vid in preferred:
        if wid not in W_IDX or vid not in V_IDX:
            continue
        wi, vi = W_IDX[wid], V_IDX[vid]
        for s in shifts:
            p = m.NewBoolVar(f"pref_{wid}_{vid}_{s['idx']}")
            m.Add(p <= wx[wi, s["idx"]])
            m.Add(p <= vx[vi, s["idx"]])
            m.Add(p >= wx[wi, s["idx"]] + vx[vi, s["idx"]] - 1)
            pref_pair_vars.append(p)
    if pref_pair_vars:
        obj_terms.append((w["sc8"], sum(pref_pair_vars)))

    m.Minimize(sum(coef * term for coef, term in obj_terms))

    return m, {
        "wx": wx, "vx": vx,
        "w_short": w_short, "nonbi_penalty": nonbi_penalty,
        "spread_w": spread_w, "spread_v": spread_v,
        "sc4": sc4, "sc5": sc5, "sc6": sc6,
        "pref_pair_vars": pref_pair_vars,
        "w_hours": w_hours, "v_hours": v_hours,
    }


# ---------- Independent HC verifier (all 12 HCs from raw assignment) ----------
def verify_all_hcs(solver, vars_d, workers, supervisors, shifts, forbidden, mentor):
    wx = vars_d["wx"]
    vx = vars_d["vx"]
    nW, nV = len(workers), len(supervisors)
    W_IDX = {wo["id"]: i for i, wo in enumerate(workers)}
    V_IDX = {v["id"]: i for i, v in enumerate(supervisors)}
    day_of = {s["idx"]: shift_global_day(s) for s in shifts}

    w_val = {(wi, s["idx"]): solver.Value(wx[wi, s["idx"]])
             for wi in range(nW) for s in shifts}
    v_val = {(vi, s["idx"]): solver.Value(vx[vi, s["idx"]])
             for vi in range(nV) for s in shifts}

    viol = {f"HC{i}": 0 for i in range(1, 13)}

    for s in shifts:
        if sum(w_val[wi, s["idx"]] for wi in range(nW)) != s["w_req"]:
            viol["HC1"] += 1
    for s in shifts:
        if sum(v_val[vi, s["idx"]] for vi in range(nV)) != s["v_req"]:
            viol["HC2"] += 1
    for wi, wo in enumerate(workers):
        for wk in (1, 2):
            h = sum(8 for s in shifts if s["week"] == wk and w_val[wi, s["idx"]])
            if h > wo["max_h"]:
                viol["HC3"] += 1
    for vi, v in enumerate(supervisors):
        for wk in (1, 2):
            h = sum(8 for s in shifts if s["week"] == wk and v_val[vi, s["idx"]])
            if h > v["max_h"]:
                viol["HC4"] += 1
    for wi, wo in enumerate(workers):
        for s in shifts:
            if s["day"] in wo["unavail"] and w_val[wi, s["idx"]]:
                viol["HC5"] += 1
    for vi, v in enumerate(supervisors):
        for s in shifts:
            if s["day"] in v["unavail"] and v_val[vi, s["idx"]]:
                viol["HC6"] += 1
    for wi, wo in enumerate(workers):
        for s in shifts:
            if w_val[wi, s["idx"]] and s["skills"] and not s["skills"].issubset(wo["skills"]):
                viol["HC7"] += 1
    for s in shifts:
        if not s["bilingual"]:
            continue
        for wi, wo in enumerate(workers):
            if w_val[wi, s["idx"]] and "en" not in wo["langs"]:
                viol["HC8"] += 1
        for vi, v in enumerate(supervisors):
            if v_val[vi, s["idx"]] and "en" not in v["langs"]:
                viol["HC8"] += 1
    for wi in range(nW):
        for s in shifts:
            if s["name"] != "night" or not w_val[wi, s["idx"]]:
                continue
            d = day_of[s["idx"]]
            for s2 in shifts:
                if s2["name"] == "morning" and day_of[s2["idx"]] == d + 1 and w_val[wi, s2["idx"]]:
                    viol["HC9"] += 1
    for vi in range(nV):
        for s in shifts:
            if s["name"] != "night" or not v_val[vi, s["idx"]]:
                continue
            d = day_of[s["idx"]]
            for s2 in shifts:
                if s2["name"] == "morning" and day_of[s2["idx"]] == d + 1 and v_val[vi, s2["idx"]]:
                    viol["HC10"] += 1
    for wid, vid in forbidden:
        if wid not in W_IDX or vid not in V_IDX:
            continue
        wi, vi = W_IDX[wid], V_IDX[vid]
        for s in shifts:
            if w_val[wi, s["idx"]] and v_val[vi, s["idx"]]:
                viol["HC11"] += 1
    for wid, vid in mentor:
        if wid not in W_IDX or vid not in V_IDX:
            continue
        wi, vi = W_IDX[wid], V_IDX[vid]
        shared = sum(1 for s in shifts
                     if w_val[wi, s["idx"]] and v_val[vi, s["idx"]])
        if shared < 2:
            viol["HC12"] += 1

    return {
        "all_satisfied": all(n == 0 for n in viol.values()),
        "total_violations": sum(viol.values()),
        "by_constraint": viol,
    }


# ---------- SC scoring (0-100) ----------
def score_scs(solver, vars_d, workers, supervisors, shifts, preferred):
    wx = vars_d["wx"]; vx = vars_d["vx"]
    nW, nV = len(workers), len(supervisors)

    w_val = {(wi, s["idx"]): solver.Value(wx[wi, s["idx"]])
             for wi in range(nW) for s in shifts}
    v_val = {(vi, s["idx"]): solver.Value(vx[vi, s["idx"]])
             for vi in range(nV) for s in shifts}

    w_hours_per = [sum(8 for s in shifts if w_val[wi, s["idx"]]) for wi in range(nW)]
    v_hours_per = [sum(8 for s in shifts if v_val[vi, s["idx"]]) for vi in range(nV)]

    day_of = {s["idx"]: shift_global_day(s) for s in shifts}

    # SC1 consecutive > 5
    sc1_viol = 0
    for wi in range(nW):
        work_days = sorted({day_of[s["idx"]] for s in shifts if w_val[wi, s["idx"]]})
        max_c = cur = 0
        prev = -10
        for d in work_days:
            if d == prev + 1:
                cur += 1
            else:
                cur = 1
            max_c = max(max_c, cur)
            prev = d
        if max_c > 5:
            sc1_viol += 1
    sc1 = max(0, 100 - sc1_viol * (100 / nW))

    # SC2 worker fairness
    spread_w = max(w_hours_per) - min(w_hours_per) if w_hours_per else 0
    sc2 = max(0, 100 - spread_w * (100 / 40))

    # SC3 supervisor fairness
    spread_v = max(v_hours_per) - min(v_hours_per) if v_hours_per else 0
    sc3 = max(0, 100 - spread_v * (100 / 40))

    # SC4 worker night <= 4
    sc4_v = sum(1 for wi in range(nW)
                if sum(1 for s in shifts if s["name"] == "night" and w_val[wi, s["idx"]]) > 4)
    sc4 = max(0, 100 - sc4_v * (100 / nW))

    # SC5 supervisor night <= 3
    sc5_v = sum(1 for vi in range(nV)
                if sum(1 for s in shifts if s["name"] == "night" and v_val[vi, s["idx"]]) > 3)
    sc5 = max(0, 100 - sc5_v * (100 / nV))

    # SC6 min hours met
    sc6_missed = sum(1 for wi, wo in enumerate(workers)
                     if w_hours_per[wi] < wo["min_h"] * 2)
    sc6 = max(0, 100 - sc6_missed * (100 / nW))

    # SC7 daily senior presence
    senior_idx = {i for i, wo in enumerate(workers) if wo["level"] == "senior"}
    sc7_missing = 0
    for d in range(14):
        has = any(w_val[wi, s["idx"]] for wi in senior_idx for s in shifts if day_of[s["idx"]] == d)
        if not has:
            sc7_missing += 1
    sc7 = max(0, 100 - sc7_missing * (100 / 14))

    # SC8 preferred pair bonus
    W_IDX = {wo["id"]: i for i, wo in enumerate(workers)}
    V_IDX = {v["id"]: i for i, v in enumerate(supervisors)}
    pref_count = 0
    for wid, vid in preferred:
        if wid not in W_IDX or vid not in V_IDX:
            continue
        wi, vi = W_IDX[wid], V_IDX[vid]
        for s in shifts:
            if w_val[wi, s["idx"]] and v_val[vi, s["idx"]]:
                pref_count += 1
    # target: each pair ~3 shared shifts
    sc8 = min(100, (pref_count / max(1, len(preferred) * 3)) * 100)

    overall = round((sc1 + sc2 + sc3 + sc4 + sc5 + sc6 + sc7 + sc8) / 8, 1)
    return {
        "scores": {
            "SC1": round(sc1, 1), "SC2": round(sc2, 1),
            "SC3": round(sc3, 1), "SC4": round(sc4, 1),
            "SC5": round(sc5, 1), "SC6": round(sc6, 1),
            "SC7": round(sc7, 1), "SC8": round(sc8, 1),
            "overall": overall,
        },
        "raw": {
            "spread_w": spread_w, "spread_v": spread_v,
            "sc1_violators": sc1_viol, "sc6_missed": sc6_missed,
            "pref_achieved": pref_count,
        }
    }


# ---------- Scenario runner ----------
def run_scenario(name, workers, supervisors, shifts, forbidden, mentor, preferred,
                 soften_hc1=False, soften_hc8=False, relax_hc1_bilingual=False):
    t0 = time.time()
    model, vars_d = build_full_model(
        workers, supervisors, shifts, forbidden, mentor, preferred,
        soften_hc1=soften_hc1, soften_hc8=soften_hc8, relax_hc1_bilingual=relax_hc1_bilingual,
    )
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TIME_LIMIT
    solver.parameters.num_search_workers = NUM_WORKERS
    status = solver.Solve(model)
    elapsed = time.time() - t0
    feasible = status in (cp_model.OPTIMAL, cp_model.FEASIBLE)

    r = {
        "scenario": name,
        "solver_status": solver.StatusName(status),
        "solver_feasible": feasible,
        "time_sec": round(elapsed, 2),
    }
    if feasible:
        r["objective"] = solver.ObjectiveValue()
        hc = verify_all_hcs(solver, vars_d, workers, supervisors, shifts, forbidden, mentor)
        r["hc_all_satisfied"] = hc["all_satisfied"]
        r["hc_total_violations"] = hc["total_violations"]
        r["hc_violations_by_constraint"] = hc["by_constraint"]
        r["sc_evaluation"] = score_scs(solver, vars_d, workers, supervisors, shifts, preferred)
    return r


def main():
    workers = load_workers()
    supervisors = load_supervisors()
    shifts = load_shifts()
    forbidden, mentor, preferred = load_pairs()

    print("=" * 72)
    print("IMPROVE — worker_supervisor v1")
    print("=" * 72)
    print("Baseline: wall at Phase 5 (HC7+HC8). Root cause: en+reception 4 vs demand 5.")
    print()

    results = {}

    # --- A: Hire W021 ---
    print("[A] Hire W021 (en+reception+phone+chat, mid, 40h)")
    w021 = {
        "id": "W021", "name": "新規採用",
        "skills": {"reception", "phone", "chat"},
        "level": "mid", "max_h": 40, "min_h": 24,
        "unavail": set(), "langs": {"ja", "en"},
    }
    workers_A = workers + [w021]
    results["A_hire_W021"] = run_scenario(
        "A_hire_W021", workers_A, supervisors, shifts, forbidden, mentor, preferred)

    # --- B: Relax HC1 5->4 on bilingual+reception ---
    print("[B] Relax HC1 5->4 on bilingual+reception shifts")
    results["B_relax_HC1"] = run_scenario(
        "B_relax_HC1", workers, supervisors, shifts, forbidden, mentor, preferred,
        relax_hc1_bilingual=True)

    # --- C: Soften HC1 ---
    print("[C] Soften HC1 (shortage with penalty)")
    results["C_soft_HC1"] = run_scenario(
        "C_soft_HC1", workers, supervisors, shifts, forbidden, mentor, preferred,
        soften_hc1=True)

    # --- D: Soften HC8 ---
    print("[D] Soften HC8 (non-en on bilingual shifts)")
    results["D_soft_HC8"] = run_scenario(
        "D_soft_HC8", workers, supervisors, shifts, forbidden, mentor, preferred,
        soften_hc8=True)

    def _print(label, r):
        if not r.get("solver_feasible"):
            print(f"   [{label}] {r['solver_status']} ({r['time_sec']}s)")
            return
        hc_str = "HC ALL OK ✓" if r["hc_all_satisfied"] else f"HC VIOL {r['hc_total_violations']} ✗"
        sc = r["sc_evaluation"]["scores"]
        print(f"   [{label}] solver={r['solver_status']} | {hc_str} | obj={r['objective']:.0f} | "
              f"overall SC={sc['overall']} ({r['time_sec']}s)")
        if not r["hc_all_satisfied"]:
            viol = {k: v for k, v in r["hc_violations_by_constraint"].items() if v > 0}
            print(f"         violations: {viol}")

    print()
    _print("A", results["A_hire_W021"])
    _print("B", results["B_relax_HC1"])
    _print("C", results["C_soft_HC1"])
    _print("D", results["D_soft_HC8"])

    out = RESULTS / "improve_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
