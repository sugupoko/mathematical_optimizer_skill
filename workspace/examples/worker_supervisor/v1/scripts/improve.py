"""
Improve — worker_supervisor v1

Baseline Phase 5 で HC7+HC8 の組合せで infeasible を検出。
根本原因: en+reception を持つ作業者 4名 vs 5名要求 → 鳩の巣違反。

シナリオ:
  A: hire W021 (new bilingual + reception worker)
  B: relax HC1 5→4 for bilingual+reception shifts
  C: soften HC1 (penalty)
  D: soften HC8 (allow non-en on bilingual shifts)

各シナリオで独立 HC 検証器を実行し、元の12個の HC をどの程度満たすか記録。
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


# ---------- Loaders (reuse from staged_baseline via import) ----------
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


# ---------- Full model builder with optional softening ----------
def build_full_model(
    workers, supervisors, shifts, forbidden, mentor, preferred,
    soften_hc1=False, soften_hc8=False, relax_hc1_bilingual=False,
    weights=None,
):
    DEFAULT_W = {
        "sc1": 3, "sc2": 2, "sc3": 2, "sc4": 4, "sc5": 4,
        "sc6": 2, "sc7": 3, "sc8": -2,
        "shortage_hc1": 1000, "shortage_hc8": 1000,
    }
    w = dict(DEFAULT_W)
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
            m.Add(sum(wx[wi, s["idx"]] * 8 for s in shifts if s["week"] == wk) <= wo["max_h"])
    for vi, v in enumerate(supervisors):
        for wk in (1, 2):
            m.Add(sum(vx[vi, s["idx"]] * 8 for s in shifts if s["week"] == wk) <= v["max_h"])

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
    nonbi_penalty_vars = []
    for s in shifts:
        if not s["bilingual"]:
            continue
        for wi, wo in enumerate(workers):
            if "en" not in wo["langs"]:
                if soften_hc8:
                    nonbi_penalty_vars.append(wx[wi, s["idx"]])
                else:
                    m.Add(wx[wi, s["idx"]] == 0)
        for vi, v in enumerate(supervisors):
            if "en" not in v["langs"]:
                if soften_hc8:
                    nonbi_penalty_vars.append(vx[vi, s["idx"]])
                else:
                    m.Add(vx[vi, s["idx"]] == 0)

    # ---- HC9, HC10 rest (night -> next morning) ----
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

    # ---- HC11 forbidden ----
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
            p = m.NewBoolVar(f"pair_{wid}_{vid}_{s['idx']}")
            m.Add(p <= wx[wi, s["idx"]])
            m.Add(p <= vx[vi, s["idx"]])
            m.Add(p >= wx[wi, s["idx"]] + vx[vi, s["idx"]] - 1)
            pair_vars.append(p)
        m.Add(sum(pair_vars) >= 2)

    # ---- SC objective terms ----
    obj_terms = []
    if w_short:
        obj_terms.append((w["shortage_hc1"], sum(w_short.values())))
    if nonbi_penalty_vars:
        obj_terms.append((w["shortage_hc8"], sum(nonbi_penalty_vars)))

    # SC2: worker fairness
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

    # SC3: supervisor fairness
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

    # SC4: worker night <= 4
    sc4_exc = []
    for wi in range(nW):
        nc = m.NewIntVar(0, 14, f"nc_{wi}")
        m.Add(nc == sum(wx[wi, s["idx"]] for s in shifts if s["name"] == "night"))
        exc = m.NewIntVar(0, 14, f"nexc_{wi}")
        m.Add(exc >= nc - 4)
        m.Add(exc >= 0)
        sc4_exc.append(exc)
    obj_terms.append((w["sc4"], sum(sc4_exc)))

    # SC5: supervisor night <= 3
    sc5_exc = []
    for vi in range(nV):
        nc = m.NewIntVar(0, 14, f"vnc_{vi}")
        m.Add(nc == sum(vx[vi, s["idx"]] for s in shifts if s["name"] == "night"))
        exc = m.NewIntVar(0, 14, f"vnexc_{vi}")
        m.Add(exc >= nc - 3)
        m.Add(exc >= 0)
        sc5_exc.append(exc)
    obj_terms.append((w["sc5"], sum(sc5_exc)))

    # SC6: min hours
    sc6_sh = []
    for wi, wo in enumerate(workers):
        target = wo["min_h"] * 2  # 2 weeks
        sh = m.NewIntVar(0, target, f"sh_{wi}")
        m.Add(sh >= target - w_hours[wi])
        m.Add(sh >= 0)
        sc6_sh.append(sh)
    obj_terms.append((w["sc6"], sum(sc6_sh)))

    # SC8: preferred pairs bonus (negative weight)
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
        "wx": wx, "vx": vx, "w_short": w_short, "nonbi_penalty": nonbi_penalty_vars,
        "spread_w": spread_w, "spread_v": spread_v,
        "sc4_exc": sc4_exc, "sc5_exc": sc5_exc, "sc6_sh": sc6_sh,
        "pref_pair_vars": pref_pair_vars,
        "w_hours": w_hours, "v_hours": v_hours,
    }


# ---------- Independent HC verifier ----------
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

    violations = {f"HC{i}": 0 for i in range(1, 13)}

    # HC1
    for s in shifts:
        if sum(w_val[wi, s["idx"]] for wi in range(nW)) != s["w_req"]:
            violations["HC1"] += 1
    # HC2
    for s in shifts:
        if sum(v_val[vi, s["idx"]] for vi in range(nV)) != s["v_req"]:
            violations["HC2"] += 1
    # HC3
    for wi, wo in enumerate(workers):
        for wk in (1, 2):
            h = sum(8 for s in shifts if s["week"] == wk and w_val[wi, s["idx"]])
            if h > wo["max_h"]:
                violations["HC3"] += 1
    # HC4
    for vi, v in enumerate(supervisors):
        for wk in (1, 2):
            h = sum(8 for s in shifts if s["week"] == wk and v_val[vi, s["idx"]])
            if h > v["max_h"]:
                violations["HC4"] += 1
    # HC5
    for wi, wo in enumerate(workers):
        for s in shifts:
            if s["day"] in wo["unavail"] and w_val[wi, s["idx"]]:
                violations["HC5"] += 1
    # HC6
    for vi, v in enumerate(supervisors):
        for s in shifts:
            if s["day"] in v["unavail"] and v_val[vi, s["idx"]]:
                violations["HC6"] += 1
    # HC7
    for wi, wo in enumerate(workers):
        for s in shifts:
            if w_val[wi, s["idx"]] and s["skills"] and not s["skills"].issubset(wo["skills"]):
                violations["HC7"] += 1
    # HC8
    for s in shifts:
        if not s["bilingual"]:
            continue
        for wi, wo in enumerate(workers):
            if w_val[wi, s["idx"]] and "en" not in wo["langs"]:
                violations["HC8"] += 1
        for vi, v in enumerate(supervisors):
            if v_val[vi, s["idx"]] and "en" not in v["langs"]:
                violations["HC8"] += 1
    # HC9
    for wi in range(nW):
        for s in shifts:
            if s["name"] != "night" or not w_val[wi, s["idx"]]:
                continue
            d = day_of[s["idx"]]
            for s2 in shifts:
                if s2["name"] == "morning" and day_of[s2["idx"]] == d + 1 and w_val[wi, s2["idx"]]:
                    violations["HC9"] += 1
    # HC10
    for vi in range(nV):
        for s in shifts:
            if s["name"] != "night" or not v_val[vi, s["idx"]]:
                continue
            d = day_of[s["idx"]]
            for s2 in shifts:
                if s2["name"] == "morning" and day_of[s2["idx"]] == d + 1 and v_val[vi, s2["idx"]]:
                    violations["HC10"] += 1
    # HC11
    for wid, vid in forbidden:
        if wid not in W_IDX or vid not in V_IDX:
            continue
        wi, vi = W_IDX[wid], V_IDX[vid]
        for s in shifts:
            if w_val[wi, s["idx"]] and v_val[vi, s["idx"]]:
                violations["HC11"] += 1
    # HC12
    for wid, vid in mentor:
        if wid not in W_IDX or vid not in V_IDX:
            continue
        wi, vi = W_IDX[wid], V_IDX[vid]
        shared = sum(1 for s in shifts
                     if w_val[wi, s["idx"]] and v_val[vi, s["idx"]])
        if shared < 2:
            violations["HC12"] += 1

    return {
        "all_satisfied": all(n == 0 for n in violations.values()),
        "total_violations": sum(violations.values()),
        "by_constraint": violations,
    }


# ---------- SC scoring (0-100) ----------
def score_soft_constraints(solver, vars_d, workers, supervisors, shifts, forbidden, mentor, preferred):
    wx = vars_d["wx"]; vx = vars_d["vx"]
    nW, nV = len(workers), len(supervisors)

    w_val = {(wi, s["idx"]): solver.Value(wx[wi, s["idx"]])
             for wi in range(nW) for s in shifts}
    v_val = {(vi, s["idx"]): solver.Value(vx[vi, s["idx"]])
             for vi in range(nV) for s in shifts}

    # Worker hours
    w_hours_per = [sum(8 for s in shifts if w_val[wi, s["idx"]]) for wi in range(nW)]
    v_hours_per = [sum(8 for s in shifts if v_val[vi, s["idx"]]) for vi in range(nV)]

    # SC1: consecutive days > 5
    day_of = {s["idx"]: shift_global_day(s) for s in shifts}
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
    sc1_score = max(0, 100 - sc1_viol * (100 / nW))

    # SC2: worker fairness
    spread_w = max(w_hours_per) - min(w_hours_per) if w_hours_per else 0
    sc2_score = max(0, 100 - spread_w * (100 / 40))

    # SC3: supervisor fairness
    spread_v = max(v_hours_per) - min(v_hours_per) if v_hours_per else 0
    sc3_score = max(0, 100 - spread_v * (100 / 40))

    # SC4: worker night <= 4
    sc4_viol = 0
    for wi in range(nW):
        nc = sum(1 for s in shifts if s["name"] == "night" and w_val[wi, s["idx"]])
        if nc > 4:
            sc4_viol += 1
    sc4_score = max(0, 100 - sc4_viol * (100 / nW))

    # SC5: supervisor night <= 3
    sc5_viol = 0
    for vi in range(nV):
        nc = sum(1 for s in shifts if s["name"] == "night" and v_val[vi, s["idx"]])
        if nc > 3:
            sc5_viol += 1
    sc5_score = max(0, 100 - sc5_viol * (100 / nV))

    # SC6: min hours
    sc6_missed = sum(1 for wi, wo in enumerate(workers) if w_hours_per[wi] < wo["min_h"] * 2)
    sc6_score = max(0, 100 - sc6_missed * (100 / nW))

    # SC7: senior per day
    senior_ids = {wo["id"] for wo in workers if wo["level"] == "senior"}
    senior_idx_set = {i for i, wo in enumerate(workers) if wo["id"] in senior_ids}
    sc7_missing = 0
    for d in range(14):
        has = False
        for wi in senior_idx_set:
            for s in shifts:
                if day_of[s["idx"]] == d and w_val[wi, s["idx"]]:
                    has = True
                    break
            if has:
                break
        if not has:
            sc7_missing += 1
    sc7_score = max(0, 100 - sc7_missing * (100 / 14))

    # SC8: preferred pairs
    W_IDX = {wo["id"]: i for i, wo in enumerate(workers)}
    V_IDX = {v["id"]: i for i, v in enumerate(supervisors)}
    pref_achieved = 0
    pref_total = len(preferred) * len(shifts)
    for wid, vid in preferred:
        if wid not in W_IDX or vid not in V_IDX:
            continue
        wi, vi = W_IDX[wid], V_IDX[vid]
        for s in shifts:
            if w_val[wi, s["idx"]] and v_val[vi, s["idx"]]:
                pref_achieved += 1
    sc8_score = min(100, (pref_achieved / max(1, len(preferred) * 3)) * 100)  # target ~3 shared per pair

    overall = round(
        (sc1_score + sc2_score + sc3_score + sc4_score + sc5_score + sc6_score + sc7_score + sc8_score) / 8,
        1
    )

    return {
        "scores": {
            "SC1": round(sc1_score, 1),
            "SC2": round(sc2_score, 1),
            "SC3": round(sc3_score, 1),
            "SC4": round(sc4_score, 1),
            "SC5": round(sc5_score, 1),
            "SC6": round(sc6_score, 1),
            "SC7": round(sc7_score, 1),
            "SC8": round(sc8_score, 1),
            "overall": overall,
        },
        "raw": {
            "w_spread": spread_w,
            "v_spread": spread_v,
            "sc1_violators": sc1_viol,
            "sc6_missed": sc6_missed,
            "pref_achieved": pref_achieved,
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
        hc_verify = verify_all_hcs(solver, vars_d, workers, supervisors, shifts, forbidden, mentor)
        r["hc_all_satisfied"] = hc_verify["all_satisfied"]
        r["hc_total_violations"] = hc_verify["total_violations"]
        r["hc_violations_by_constraint"] = hc_verify["by_constraint"]
        r["sc_evaluation"] = score_soft_constraints(
            solver, vars_d, workers, supervisors, shifts, forbidden, mentor, preferred
        )
    return r


def main():
    workers = load_workers()
    supervisors = load_supervisors()
    shifts = load_shifts()
    forbidden, mentor, preferred = load_pairs()

    print("=" * 72)
    print("IMPROVE — worker_supervisor v1")
    print("=" * 72)
    print(f"Baseline: Phase 5 (HC7+HC8) infeasible (en+reception pool < demand)")
    print()

    results = {}

    # --- A: hire W021 ---
    print("[A] Hire W021 (en+reception, mid, 40h)")
    w021 = {
        "id": "W021", "name": "新規採用", "skills": {"reception", "phone", "chat"},
        "level": "mid", "max_h": 40, "min_h": 24, "unavail": set(), "langs": {"ja", "en"},
    }
    workers_A = workers + [w021]
    r_A = run_scenario("A_hire_W021", workers_A, supervisors, shifts, forbidden, mentor, preferred)
    results["A_hire_W021"] = r_A

    # --- B: relax HC1 5->4 on bilingual+reception ---
    print("[B] Relax HC1 5->4 on bilingual+reception shifts")
    r_B = run_scenario("B_relax_HC1", workers, supervisors, shifts, forbidden, mentor, preferred,
                       relax_hc1_bilingual=True)
    results["B_relax_HC1"] = r_B

    # --- C: soften HC1 ---
    print("[C] Soften HC1 (allow shortage)")
    r_C = run_scenario("C_soft_HC1", workers, supervisors, shifts, forbidden, mentor, preferred,
                       soften_hc1=True)
    results["C_soft_HC1"] = r_C

    # --- D: soften HC8 ---
    print("[D] Soften HC8 (allow non-en on bilingual shifts)")
    r_D = run_scenario("D_soft_HC8", workers, supervisors, shifts, forbidden, mentor, preferred,
                       soften_hc8=True)
    results["D_soft_HC8"] = r_D

    def _print(label, r):
        if not r.get("solver_feasible"):
            print(f"   [{label}] {r['solver_status']} ({r['time_sec']}s)")
            return
        hc_str = "HC ALL OK" if r["hc_all_satisfied"] else f"HC VIOL {r['hc_total_violations']}"
        sc = r["sc_evaluation"]["scores"]
        print(f"   [{label}] {r['solver_status']} | {hc_str} | obj={r['objective']:.0f} | "
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
