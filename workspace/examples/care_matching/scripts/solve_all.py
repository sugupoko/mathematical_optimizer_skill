#!/usr/bin/env python3
"""
介護マッチング最適化 — 全ベースライン + 改善版を一括実行
15利用者 x 10ヘルパー の割当問題
"""
import csv
import json
import os
import random
import sys
from collections import defaultdict
from copy import deepcopy

# ---------- paths ----------
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
RESULTS = os.path.join(BASE, "results")
os.makedirs(RESULTS, exist_ok=True)

# ---------- adjacency (Tokyo wards) ----------
ADJACENT = {
    "杉並区": {"世田谷区", "渋谷区", "新宿区", "中野区"},
    "世田谷区": {"杉並区", "渋谷区"},
    "渋谷区": {"杉並区", "世田谷区", "新宿区"},
    "新宿区": {"杉並区", "渋谷区", "中野区"},
    "中野区": {"杉並区", "新宿区"},
}

# ---------- load data ----------
def load_csv(filename):
    with open(os.path.join(DATA, filename), encoding="utf-8") as f:
        return list(csv.DictReader(f))

receivers = load_csv("care_receivers.csv")
caregivers = load_csv("caregivers.csv")
history = load_csv("compatibility_history.csv")
constraints_raw = load_csv("constraints.csv")

# parse into dicts keyed by id
R = {}
for r in receivers:
    R[r["receiver_id"]] = {
        "name": r["name"],
        "care_level": int(r["care_level"]),
        "district": r["district"],
        "preferred_days": set(r["preferred_days"].split(",")),
        "preferred_gender": r["preferred_gender"],
        "required_qualification": r["required_qualification"],
        "service_type": r["service_type"],
    }

C = {}
for c in caregivers:
    C[c["caregiver_id"]] = {
        "name": c["name"],
        "gender": c["gender"],
        "qualification": c["qualification"],
        "district": c["district"],
        "available_days": set(c["available_days"].split(",")),
        "max_clients": int(c["max_clients"]),
        "experience_years": int(c["experience_years"]),
    }

# history lookup
HIST = {}  # (rid, cid) -> score
for h in history:
    HIST[(h["receiver_id"], h["caregiver_id"])] = int(h["satisfaction_score"])

# NG pairs
NG_PAIRS = {("R004", "C004")}

RIDS = sorted(R.keys())
CIDS = sorted(C.keys())

# ---------- qualification hierarchy ----------
QUAL_RANK = {"介護福祉士": 3, "初任者研修": 2, "any": 1}

def qual_meets(caregiver_qual, required_qual):
    """Does caregiver qualification meet requirement?"""
    if required_qual == "any":
        return True
    return QUAL_RANK.get(caregiver_qual, 0) >= QUAL_RANK.get(required_qual, 0)


# ---------- hard constraint check ----------
def check_hard(rid, cid):
    """Return list of violated hard constraints. Empty = feasible."""
    r = R[rid]
    c = C[cid]
    violations = []
    # HC01: body care needs 介護福祉士
    if r["service_type"] in ("身体介護", "both") and c["qualification"] != "介護福祉士":
        if r["required_qualification"] == "介護福祉士":
            violations.append("HC01")
        elif r["service_type"] == "身体介護":
            violations.append("HC01")
    # HC02: care level >= 4 needs experience >= 3
    if r["care_level"] >= 4 and c["experience_years"] < 3:
        violations.append("HC02")
    # HC04: schedule overlap
    if len(r["preferred_days"] & c["available_days"]) == 0:
        violations.append("HC04")
    # HC05: NG pair
    if (rid, cid) in NG_PAIRS:
        violations.append("HC05")
    return violations


def is_feasible(rid, cid):
    return len(check_hard(rid, cid)) == 0


# ---------- compatibility score ----------
def compatibility_score(rid, cid):
    """Compute a 0-100 compatibility score."""
    r = R[rid]
    c = C[cid]
    score = 0.0

    # 1) History satisfaction (0-25)
    if (rid, cid) in HIST:
        score += HIST[(rid, cid)] * 5  # max 25

    # 2) District match (0-20)
    if r["district"] == c["district"]:
        score += 20
    elif c["district"] in ADJACENT.get(r["district"], set()):
        score += 10

    # 3) Gender preference (0-15)
    if r["preferred_gender"] == "any":
        score += 15
    elif r["preferred_gender"] == c["gender"]:
        score += 15

    # 4) Schedule overlap (0-15)
    overlap = len(r["preferred_days"] & c["available_days"])
    total = len(r["preferred_days"])
    if total > 0:
        score += 15 * (overlap / total)

    # 5) Qualification fit (0-10)
    if qual_meets(c["qualification"], r["required_qualification"]):
        score += 10

    # 6) Experience for high care levels (0-10)
    if r["care_level"] >= 4:
        if c["experience_years"] >= 10:
            score += 10
        elif c["experience_years"] >= 5:
            score += 5
    elif r["care_level"] >= 3:
        if c["experience_years"] >= 5:
            score += 5

    # 7) Continuity bonus for score=5 pairs (0-5 extra)
    # included in history already

    return round(score, 2)


# precompute scores
SCORES = {}
for rid in RIDS:
    for cid in CIDS:
        SCORES[(rid, cid)] = compatibility_score(rid, cid)


# ---------- evaluation ----------
def evaluate(assignment, label=""):
    """
    assignment: dict {rid: cid or None}
    Returns metrics dict.
    """
    matched = {rid: cid for rid, cid in assignment.items() if cid is not None}
    n_matched = len(matched)
    n_total = len(RIDS)

    hc_violations = 0
    hc_detail = []
    for rid, cid in matched.items():
        v = check_hard(rid, cid)
        if v:
            hc_violations += len(v)
            hc_detail.append({"receiver": rid, "caregiver": cid, "violations": v})

    # avg compatibility
    scores = [SCORES[(rid, cid)] for rid, cid in matched.items()]
    avg_compat = round(sum(scores) / len(scores), 2) if scores else 0

    # gender match
    gender_ok = 0
    gender_applicable = 0
    for rid, cid in matched.items():
        r = R[rid]
        if r["preferred_gender"] != "any":
            gender_applicable += 1
            if r["preferred_gender"] == C[cid]["gender"]:
                gender_ok += 1
    gender_rate = round(gender_ok / gender_applicable, 4) if gender_applicable else 1.0

    # district match (same or adjacent)
    district_same = 0
    district_adj = 0
    for rid, cid in matched.items():
        if R[rid]["district"] == C[cid]["district"]:
            district_same += 1
        elif C[cid]["district"] in ADJACENT.get(R[rid]["district"], set()):
            district_adj += 1
    district_rate = round((district_same + district_adj) / n_matched, 4) if n_matched else 0

    # continuity (score=5 pairs maintained)
    score5_pairs = [(rid, cid) for (rid, cid), s in HIST.items() if s == 5]
    continuity_kept = sum(1 for rid, cid in score5_pairs if assignment.get(rid) == cid)
    continuity_total = len(score5_pairs)
    continuity_rate = round(continuity_kept / continuity_total, 4) if continuity_total else 1.0

    # workload fairness (std dev of assigned counts)
    load = defaultdict(int)
    for cid in CIDS:
        load[cid] = 0
    for rid, cid in matched.items():
        load[cid] += 1
    loads = list(load.values())
    avg_load = sum(loads) / len(loads) if loads else 0
    load_std = round((sum((x - avg_load) ** 2 for x in loads) / len(loads)) ** 0.5, 4) if loads else 0

    metrics = {
        "label": label,
        "match_rate": round(n_matched / n_total, 4),
        "n_matched": n_matched,
        "n_total": n_total,
        "hc_violations": hc_violations,
        "hc_detail": hc_detail,
        "avg_compatibility": avg_compat,
        "gender_match_rate": gender_rate,
        "district_match_rate": district_rate,
        "district_same": district_same,
        "district_adjacent": district_adj,
        "continuity_rate": continuity_rate,
        "continuity_kept": continuity_kept,
        "continuity_total": continuity_total,
        "workload_std": load_std,
        "workload_distribution": dict(load),
        "total_score": round(sum(scores), 2),
        "assignments": {rid: cid for rid, cid in assignment.items()},
    }
    return metrics


# ======================================================================
# Baseline 1: Random
# ======================================================================
def solve_random(seed=42):
    random.seed(seed)
    assignment = {}
    load = defaultdict(int)
    shuffled_rids = list(RIDS)
    random.shuffle(shuffled_rids)

    for rid in shuffled_rids:
        candidates = [cid for cid in CIDS if load[cid] < C[cid]["max_clients"]]
        if candidates:
            cid = random.choice(candidates)
            assignment[rid] = cid
            load[cid] += 1
        else:
            assignment[rid] = None
    return assignment


# ======================================================================
# Baseline 2: Greedy (care-level priority)
# ======================================================================
def solve_greedy():
    assignment = {}
    load = defaultdict(int)
    # sort receivers by care level descending (higher = more critical)
    sorted_rids = sorted(RIDS, key=lambda rid: -R[rid]["care_level"])

    for rid in sorted_rids:
        best_cid = None
        best_score = -1
        for cid in CIDS:
            if load[cid] >= C[cid]["max_clients"]:
                continue
            if not is_feasible(rid, cid):
                continue
            s = SCORES[(rid, cid)]
            if s > best_score:
                best_score = s
                best_cid = cid
        if best_cid is not None:
            assignment[rid] = best_cid
            load[best_cid] += 1
        else:
            # fallback: try any feasible even if score is 0
            for cid in CIDS:
                if load[cid] < C[cid]["max_clients"] and is_feasible(rid, cid):
                    assignment[rid] = cid
                    load[cid] += 1
                    break
            else:
                assignment[rid] = None
    return assignment


# ======================================================================
# Baseline 3: CP-SAT solver (basic)
# ======================================================================
def solve_cpsat_basic():
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()

    # x[rid][cid] = 1 if rid assigned to cid
    x = {}
    for rid in RIDS:
        for cid in CIDS:
            x[(rid, cid)] = model.NewBoolVar(f"x_{rid}_{cid}")

    # each receiver assigned to at most 1 caregiver
    for rid in RIDS:
        model.Add(sum(x[(rid, cid)] for cid in CIDS) <= 1)

    # each caregiver within max_clients
    for cid in CIDS:
        model.Add(sum(x[(rid, cid)] for rid in RIDS) <= C[cid]["max_clients"])

    # hard constraints
    for rid in RIDS:
        for cid in CIDS:
            if not is_feasible(rid, cid):
                model.Add(x[(rid, cid)] == 0)

    # objective: maximize total compatibility + bonus for matching
    obj_terms = []
    for rid in RIDS:
        for cid in CIDS:
            score_int = int(SCORES[(rid, cid)] * 100)
            obj_terms.append(score_int * x[(rid, cid)])

    # bonus for matching (encourage full match)
    match_bonus = 5000
    for rid in RIDS:
        obj_terms.append(match_bonus * sum(x[(rid, cid)] for cid in CIDS))

    model.Maximize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    status = solver.Solve(model)

    assignment = {}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for rid in RIDS:
            assigned = False
            for cid in CIDS:
                if solver.Value(x[(rid, cid)]) == 1:
                    assignment[rid] = cid
                    assigned = True
                    break
            if not assigned:
                assignment[rid] = None
    else:
        for rid in RIDS:
            assignment[rid] = None

    return assignment


# ======================================================================
# Improvement: CP-SAT with continuity + fairness
# ======================================================================
def solve_cpsat_improved():
    from ortools.sat.python import cp_model

    model = cp_model.CpModel()

    x = {}
    for rid in RIDS:
        for cid in CIDS:
            x[(rid, cid)] = model.NewBoolVar(f"x_{rid}_{cid}")

    # each receiver assigned to at most 1 caregiver
    for rid in RIDS:
        model.Add(sum(x[(rid, cid)] for cid in CIDS) <= 1)

    # each caregiver within max_clients
    for cid in CIDS:
        model.Add(sum(x[(rid, cid)] for rid in RIDS) <= C[cid]["max_clients"])

    # hard constraints
    for rid in RIDS:
        for cid in CIDS:
            if not is_feasible(rid, cid):
                model.Add(x[(rid, cid)] == 0)

    # --- objective components ---
    obj_terms = []

    # 1) compatibility score (scaled x100)
    for rid in RIDS:
        for cid in CIDS:
            score_int = int(SCORES[(rid, cid)] * 100)
            obj_terms.append(score_int * x[(rid, cid)])

    # 2) match bonus (ensure everyone is matched)
    match_bonus = 5000
    for rid in RIDS:
        obj_terms.append(match_bonus * sum(x[(rid, cid)] for cid in CIDS))

    # 3) continuity bonus for score=5 pairs (very high priority)
    continuity_bonus = 3000
    for (rid, cid), score in HIST.items():
        if score == 5 and rid in R and cid in C:
            if is_feasible(rid, cid):
                obj_terms.append(continuity_bonus * x[(rid, cid)])

    # 4) gender match bonus
    gender_bonus = 800
    for rid in RIDS:
        r = R[rid]
        if r["preferred_gender"] != "any":
            for cid in CIDS:
                if C[cid]["gender"] == r["preferred_gender"]:
                    obj_terms.append(gender_bonus * x[(rid, cid)])

    # 5) district match bonus
    district_same_bonus = 600
    district_adj_bonus = 300
    for rid in RIDS:
        for cid in CIDS:
            if R[rid]["district"] == C[cid]["district"]:
                obj_terms.append(district_same_bonus * x[(rid, cid)])
            elif C[cid]["district"] in ADJACENT.get(R[rid]["district"], set()):
                obj_terms.append(district_adj_bonus * x[(rid, cid)])

    # 6) experience bonus for care level 5
    exp_bonus = 500
    for rid in RIDS:
        if R[rid]["care_level"] == 5:
            for cid in CIDS:
                if C[cid]["experience_years"] >= 10:
                    obj_terms.append(exp_bonus * x[(rid, cid)])

    # 7) Fairness: minimize max load deviation
    # Use auxiliary variables for load balancing
    loads = {}
    for cid in CIDS:
        loads[cid] = model.NewIntVar(0, C[cid]["max_clients"], f"load_{cid}")
        model.Add(loads[cid] == sum(x[(rid, cid)] for rid in RIDS))

    # target load = 15 receivers / 10 caregivers = 1.5, so either 1 or 2
    # penalize deviation from 1.5 via max_load variable
    max_load = model.NewIntVar(0, max(C[cid]["max_clients"] for cid in CIDS), "max_load")
    for cid in CIDS:
        model.Add(max_load >= loads[cid])

    # penalty for high max_load
    fairness_penalty = 1000
    obj_terms.append(-fairness_penalty * max_load)

    model.Maximize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60
    status = solver.Solve(model)

    assignment = {}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for rid in RIDS:
            assigned = False
            for cid in CIDS:
                if solver.Value(x[(rid, cid)]) == 1:
                    assignment[rid] = cid
                    assigned = True
                    break
            if not assigned:
                assignment[rid] = None
    else:
        for rid in RIDS:
            assignment[rid] = None

    return assignment


# ======================================================================
# Data analysis
# ======================================================================
def data_analysis():
    """Print and return data analysis summary."""
    analysis = {}

    # Supply vs demand
    total_capacity = sum(C[cid]["max_clients"] for cid in CIDS)
    analysis["receivers"] = len(RIDS)
    analysis["caregivers"] = len(CIDS)
    analysis["total_capacity"] = total_capacity
    analysis["capacity_ratio"] = round(total_capacity / len(RIDS), 2)

    # by district
    r_district = defaultdict(int)
    c_district = defaultdict(int)
    for rid in RIDS:
        r_district[R[rid]["district"]] += 1
    for cid in CIDS:
        c_district[C[cid]["district"]] += 1
    analysis["receiver_by_district"] = dict(r_district)
    analysis["caregiver_by_district"] = dict(c_district)

    # qualification distribution
    qual_dist = defaultdict(int)
    for cid in CIDS:
        qual_dist[C[cid]["qualification"]] += 1
    analysis["qualification_distribution"] = dict(qual_dist)

    # receivers needing 介護福祉士
    need_kaigo = sum(1 for rid in RIDS if R[rid]["required_qualification"] == "介護福祉士")
    analysis["receivers_need_kaigofukushishi"] = need_kaigo

    # care level distribution
    cl_dist = defaultdict(int)
    for rid in RIDS:
        cl_dist[R[rid]["care_level"]] += 1
    analysis["care_level_distribution"] = dict(cl_dist)

    # gender preference
    gp = defaultdict(int)
    for rid in RIDS:
        gp[R[rid]["preferred_gender"]] += 1
    analysis["gender_preference"] = dict(gp)

    # gender supply
    gs = defaultdict(int)
    for cid in CIDS:
        gs[C[cid]["gender"]] += 1
    analysis["gender_supply"] = dict(gs)

    # score-5 pairs
    s5 = [(rid, cid) for (rid, cid), s in HIST.items() if s == 5]
    analysis["score5_pairs"] = len(s5)
    analysis["score5_detail"] = [{"receiver": rid, "caregiver": cid} for rid, cid in s5]

    # feasible pairs count
    feasible_count = sum(1 for rid in RIDS for cid in CIDS if is_feasible(rid, cid))
    analysis["feasible_pairs"] = feasible_count
    analysis["total_pairs"] = len(RIDS) * len(CIDS)

    return analysis


# ======================================================================
# Main
# ======================================================================
def main():
    print("=" * 60)
    print("  介護マッチング最適化 — solve_all.py")
    print("=" * 60)

    # --- Data Analysis ---
    print("\n--- データ分析 ---")
    analysis = data_analysis()
    for k, v in analysis.items():
        print(f"  {k}: {v}")

    # save analysis
    with open(os.path.join(RESULTS, "data_analysis.json"), "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    # --- Run baselines ---
    results_all = {}

    print("\n--- Baseline 1: Random ---")
    a1 = solve_random()
    m1 = evaluate(a1, "random")
    results_all["random"] = m1
    print(f"  Match rate: {m1['match_rate']}, HC violations: {m1['hc_violations']}, "
          f"Avg compat: {m1['avg_compatibility']}, Continuity: {m1['continuity_rate']}")

    print("\n--- Baseline 2: Greedy (care-level priority) ---")
    a2 = solve_greedy()
    m2 = evaluate(a2, "greedy")
    results_all["greedy"] = m2
    print(f"  Match rate: {m2['match_rate']}, HC violations: {m2['hc_violations']}, "
          f"Avg compat: {m2['avg_compatibility']}, Continuity: {m2['continuity_rate']}")

    print("\n--- Baseline 3: CP-SAT (basic) ---")
    a3 = solve_cpsat_basic()
    m3 = evaluate(a3, "cpsat_basic")
    results_all["cpsat_basic"] = m3
    print(f"  Match rate: {m3['match_rate']}, HC violations: {m3['hc_violations']}, "
          f"Avg compat: {m3['avg_compatibility']}, Continuity: {m3['continuity_rate']}")

    print("\n--- Improvement: CP-SAT with continuity + fairness ---")
    a4 = solve_cpsat_improved()
    m4 = evaluate(a4, "cpsat_improved")
    results_all["cpsat_improved"] = m4
    print(f"  Match rate: {m4['match_rate']}, HC violations: {m4['hc_violations']}, "
          f"Avg compat: {m4['avg_compatibility']}, Continuity: {m4['continuity_rate']}")

    # --- Summary ---
    print("\n" + "=" * 60)
    print("  結果サマリー")
    print("=" * 60)
    header = f"{'Method':<20} {'Match%':>7} {'HCviol':>7} {'AvgCompat':>10} {'Gender%':>8} {'District%':>10} {'Cont%':>7} {'LoadStd':>8} {'TotalScore':>11}"
    print(header)
    print("-" * len(header))
    for key in ["random", "greedy", "cpsat_basic", "cpsat_improved"]:
        m = results_all[key]
        print(f"{key:<20} {m['match_rate']:>7.1%} {m['hc_violations']:>7} "
              f"{m['avg_compatibility']:>10.2f} {m['gender_match_rate']:>8.1%} "
              f"{m['district_match_rate']:>10.1%} {m['continuity_rate']:>7.1%} "
              f"{m['workload_std']:>8.2f} {m['total_score']:>11.2f}")

    # --- Save all results ---
    # Convert for JSON serialization
    def clean_for_json(obj):
        if isinstance(obj, dict):
            return {k: clean_for_json(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [clean_for_json(i) for i in obj]
        if isinstance(obj, set):
            return sorted(list(obj))
        return obj

    with open(os.path.join(RESULTS, "all_results.json"), "w", encoding="utf-8") as f:
        json.dump(clean_for_json(results_all), f, ensure_ascii=False, indent=2)

    # Save individual results
    for key in results_all:
        with open(os.path.join(RESULTS, f"{key}_result.json"), "w", encoding="utf-8") as f:
            json.dump(clean_for_json(results_all[key]), f, ensure_ascii=False, indent=2)

    # Save comparison summary
    summary = []
    for key in ["random", "greedy", "cpsat_basic", "cpsat_improved"]:
        m = results_all[key]
        summary.append({
            "method": key,
            "match_rate": m["match_rate"],
            "hc_violations": m["hc_violations"],
            "avg_compatibility": m["avg_compatibility"],
            "gender_match_rate": m["gender_match_rate"],
            "district_match_rate": m["district_match_rate"],
            "continuity_rate": m["continuity_rate"],
            "workload_std": m["workload_std"],
            "total_score": m["total_score"],
        })
    with open(os.path.join(RESULTS, "comparison_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n結果を {RESULTS}/ に保存しました。")
    return results_all


if __name__ == "__main__":
    results = main()
