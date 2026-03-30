"""介護マッチング最適化: assess → baseline(3手法) → improve → report

15利用者 × 10ヘルパーの介護マッチング問題を解く。
- Baseline 1: ランダム
- Baseline 2: 貪欲法（制約優先）
- Baseline 3: CP-SAT ソルバー
- 改善: 目的関数の精密一致 + 継続担当ボーナス
"""
from __future__ import annotations
import csv
import json
import random
from pathlib import Path
from collections import defaultdict
from ortools.sat.python import cp_model

DATA_DIR = Path(__file__).parent.parent / "data"
RESULTS_DIR = Path(__file__).parent.parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

# 隣接区マップ（同一区 or 隣接区なら移動OK）
ADJACENT = {
    "杉並区": {"杉並区", "中野区", "世田谷区", "渋谷区", "新宿区"},
    "世田谷区": {"世田谷区", "渋谷区", "杉並区", "中野区"},
    "渋谷区": {"渋谷区", "世田谷区", "杉並区", "新宿区", "中野区"},
    "新宿区": {"新宿区", "渋谷区", "杉並区", "中野区"},
    "中野区": {"中野区", "杉並区", "新宿区", "渋谷区"},
}


def load_data():
    receivers = []
    with open(DATA_DIR / "care_receivers.csv") as f:
        for row in csv.DictReader(f):
            row["care_level"] = int(row["care_level"])
            row["preferred_days"] = set(row["preferred_days"].split(","))
            receivers.append(row)

    caregivers = []
    with open(DATA_DIR / "caregivers.csv") as f:
        for row in csv.DictReader(f):
            row["max_clients"] = int(row["max_clients"])
            row["experience_years"] = int(row["experience_years"])
            row["available_days"] = set(row["available_days"].split(","))
            caregivers.append(row)

    history = {}
    with open(DATA_DIR / "compatibility_history.csv") as f:
        for row in csv.DictReader(f):
            history[(row["receiver_id"], row["caregiver_id"])] = {
                "score": int(row["satisfaction_score"]),
                "notes": row["notes"],
            }

    return receivers, caregivers, history


# ─── ハード制約チェック ───

def is_hard_feasible(r: dict, c: dict, history: dict) -> tuple[bool, list[str]]:
    """利用者rとヘルパーcの組合せがハード制約を満たすか。"""
    violations = []

    # HC01: 身体介護には介護福祉士必須
    if r["service_type"] in ("身体介護", "both") and r["required_qualification"] == "介護福祉士":
        if c["qualification"] != "介護福祉士":
            violations.append("HC01: 身体介護に介護福祉士必須")

    # HC02: 要介護4以上には経験3年以上
    if r["care_level"] >= 4 and c["experience_years"] < 3:
        violations.append("HC02: 要介護4以上に経験3年以上必須")

    # HC04: 曜日の重なり
    overlap = r["preferred_days"] & c["available_days"]
    if not overlap:
        violations.append("HC04: 曜日の重なりなし")

    # HC05: NGペア
    if r["receiver_id"] == "R004" and c["caregiver_id"] == "C004":
        violations.append("HC05: NGペア")

    return len(violations) == 0, violations


def compute_compatibility(r: dict, c: dict, history: dict) -> dict:
    """互換性スコアを計算（0-100点）。"""
    score = 50  # ベース

    key = (r["receiver_id"], c["caregiver_id"])

    # 過去の満足度（最重要）
    if key in history:
        h = history[key]["score"]
        score += (h - 3) * 15  # 5→+30, 4→+15, 3→0, 2→-15, 1→-30

    # SC01: 性別希望
    if r["preferred_gender"] != "any":
        if r["preferred_gender"] == c["gender"]:
            score += 10
        else:
            score -= 10

    # SC02: 同一区内
    if r["district"] == c["district"]:
        score += 15
    elif c["district"] in ADJACENT.get(r["district"], set()):
        score += 5

    # SC06: 要介護5に経験10年以上
    if r["care_level"] == 5 and c["experience_years"] >= 10:
        score += 10

    # 曜日重なりの多さ
    overlap = len(r["preferred_days"] & c["available_days"])
    score += overlap * 3

    return {"score": max(0, min(100, score)), "overlap_days": overlap}


# ─── 評価関数 ───

def evaluate(matches: dict[str, str], receivers, caregivers, history) -> dict:
    """matches: {receiver_id: caregiver_id}"""
    r_map = {r["receiver_id"]: r for r in receivers}
    c_map = {c["caregiver_id"]: c for c in caregivers}

    matched = len(matches)
    total = len(receivers)
    match_rate = matched / total

    # Hard constraint check
    hc_violations = {"HC01": 0, "HC02": 0, "HC03": 0, "HC04": 0, "HC05": 0}

    for rid, cid in matches.items():
        r, c = r_map[rid], c_map[cid]
        ok, viols = is_hard_feasible(r, c, history)
        for v in viols:
            hc_id = v[:4]
            hc_violations[hc_id] += 1

    # HC03: max_clients
    cg_counts = defaultdict(int)
    for cid in matches.values():
        cg_counts[cid] += 1
    for cid, count in cg_counts.items():
        if count > c_map[cid]["max_clients"]:
            hc_violations["HC03"] += count - c_map[cid]["max_clients"]

    total_hc = sum(hc_violations.values())

    # Soft scores
    compatibility_scores = []
    gender_match = 0
    district_match = 0
    continuity_kept = 0
    continuity_total = 0

    for rid, cid in matches.items():
        r, c = r_map[rid], c_map[cid]
        comp = compute_compatibility(r, c, history)
        compatibility_scores.append(comp["score"])

        if r["preferred_gender"] != "any" and r["preferred_gender"] == c["gender"]:
            gender_match += 1
        if r["district"] == c["district"]:
            district_match += 1

        key = (rid, cid)
        if key in history and history[key]["score"] == 5:
            continuity_kept += 1

    # Count how many score-5 pairs exist
    for (rid, cid), h in history.items():
        if h["score"] == 5:
            continuity_total += 1

    avg_compat = sum(compatibility_scores) / max(len(compatibility_scores), 1)

    # Workload fairness
    loads = list(cg_counts.values())
    if loads:
        mean_load = sum(loads) / len(loads)
        load_std = (sum((l - mean_load) ** 2 for l in loads) / len(loads)) ** 0.5
    else:
        load_std = 0

    gender_pref_count = sum(1 for r in receivers if r["preferred_gender"] != "any")
    feasible = total_hc == 0 and matched == total

    # Detail per match
    match_details = []
    for rid, cid in sorted(matches.items()):
        r, c = r_map[rid], c_map[cid]
        comp = compute_compatibility(r, c, history)
        ok, viols = is_hard_feasible(r, c, history)
        hist_score = history.get((rid, cid), {}).get("score", "-")
        match_details.append({
            "receiver": f"{rid} {r['name']}",
            "caregiver": f"{cid} {c['name']}",
            "compat": comp["score"],
            "district": f"{r['district']}→{c['district']}",
            "same_district": r["district"] == c["district"],
            "gender_ok": r["preferred_gender"] == "any" or r["preferred_gender"] == c["gender"],
            "history": hist_score,
            "hc_ok": ok,
            "violations": viols,
        })

    return {
        "feasible": feasible,
        "match_rate": round(match_rate, 2),
        "matched": matched,
        "total": total,
        "hc_violations": hc_violations,
        "total_hc": total_hc,
        "avg_compatibility": round(avg_compat, 1),
        "gender_match": f"{gender_match}/{gender_pref_count}",
        "district_match": f"{district_match}/{matched}",
        "continuity": f"{continuity_kept}/{continuity_total}",
        "workload_std": round(load_std, 2),
        "caregiver_loads": dict(sorted(cg_counts.items())),
        "match_details": match_details,
    }


# ─── Baseline 1: ランダム ───

def baseline_random(receivers, caregivers, history, seed=42):
    random.seed(seed)
    c_map = {c["caregiver_id"]: c for c in caregivers}
    cg_counts = defaultdict(int)
    matches = {}

    indices = list(range(len(receivers)))
    random.shuffle(indices)

    for i in indices:
        r = receivers[i]
        cg_list = list(range(len(caregivers)))
        random.shuffle(cg_list)
        for j in cg_list:
            c = caregivers[j]
            if cg_counts[c["caregiver_id"]] < c["max_clients"]:
                matches[r["receiver_id"]] = c["caregiver_id"]
                cg_counts[c["caregiver_id"]] += 1
                break

    return matches


# ─── Baseline 2: 貪欲法（制約優先） ───

def baseline_greedy(receivers, caregivers, history):
    c_map = {c["caregiver_id"]: c for c in caregivers}
    cg_counts = defaultdict(int)
    matches = {}

    # 優先: 要介護度が高い利用者から割当
    sorted_receivers = sorted(receivers, key=lambda r: -r["care_level"])

    for r in sorted_receivers:
        best_cg = None
        best_score = -1

        for c in caregivers:
            # Hard feasibility check
            ok, _ = is_hard_feasible(r, c, history)
            if not ok:
                continue
            if cg_counts[c["caregiver_id"]] >= c["max_clients"]:
                continue

            comp = compute_compatibility(r, c, history)
            if comp["score"] > best_score:
                best_score = comp["score"]
                best_cg = c

        if best_cg:
            matches[r["receiver_id"]] = best_cg["caregiver_id"]
            cg_counts[best_cg["caregiver_id"]] += 1

    return matches


# ─── Baseline 3 + 改善: CP-SAT ───

def solve_cpsat(receivers, caregivers, history, *, improved=False, time_limit=30):
    n_r, n_c = len(receivers), len(caregivers)
    model = cp_model.CpModel()

    # Variables: x[i,j] = 1 if receiver i is assigned to caregiver j
    x = {}
    for i in range(n_r):
        for j in range(n_c):
            x[i, j] = model.new_bool_var(f"x_{i}_{j}")

    # Each receiver matched to exactly 1 caregiver
    for i in range(n_r):
        model.add(sum(x[i, j] for j in range(n_c)) == 1)

    # HC03: max_clients
    for j in range(n_c):
        model.add(sum(x[i, j] for i in range(n_r)) <= caregivers[j]["max_clients"])

    # HC01, HC02, HC04, HC05: eliminate infeasible pairs
    for i in range(n_r):
        for j in range(n_c):
            ok, _ = is_hard_feasible(receivers[i], caregivers[j], history)
            if not ok:
                model.add(x[i, j] == 0)

    # ─── Objective ───
    obj_terms = []

    for i in range(n_r):
        for j in range(n_c):
            r, c = receivers[i], caregivers[j]
            comp = compute_compatibility(r, c, history)
            weight = comp["score"]

            if improved:
                # 改善: 継続担当ボーナス（SC04）
                key = (r["receiver_id"], c["caregiver_id"])
                if key in history and history[key]["score"] == 5:
                    weight += 30  # 強力なボーナス

                # 改善: 要介護5に経験10年以上（SC06）を強化
                if r["care_level"] == 5 and c["experience_years"] >= 10:
                    weight += 15

            obj_terms.append(x[i, j] * weight)

    # SC05: workload fairness (minimize max load)
    loads = []
    for j in range(n_c):
        load = model.new_int_var(0, caregivers[j]["max_clients"], f"load_{j}")
        model.add(load == sum(x[i, j] for i in range(n_r)))
        loads.append(load)

    max_load = model.new_int_var(0, max(c["max_clients"] for c in caregivers), "max_load")
    model.add_max_equality(max_load, loads)

    # Objective: maximize compatibility - penalize imbalance
    fairness_penalty = 5 if improved else 3
    model.maximize(sum(obj_terms) - max_load * fairness_penalty)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 4
    status = solver.solve(model)

    matches = {}
    info = {"wall_time": round(solver.wall_time, 2)}

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        info["status"] = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"
        info["objective"] = solver.objective_value
        for i in range(n_r):
            for j in range(n_c):
                if solver.value(x[i, j]) == 1:
                    matches[receivers[i]["receiver_id"]] = caregivers[j]["caregiver_id"]
    else:
        info["status"] = "INFEASIBLE"

    return matches, info


def print_result(name, result):
    print(f"\n{'=' * 60}")
    print(f"{name}")
    print(f"{'=' * 60}")
    print(f"Feasible: {result['feasible']}")
    print(f"Match rate: {result['match_rate']} ({result['matched']}/{result['total']})")
    print(f"HC violations: {result['hc_violations']} (total={result['total_hc']})")
    print(f"Avg compatibility: {result['avg_compatibility']}")
    print(f"Gender match: {result['gender_match']}")
    print(f"Same district: {result['district_match']}")
    print(f"Continuity (score=5 kept): {result['continuity']}")
    print(f"Workload std: {result['workload_std']}")
    print(f"Caregiver loads: {result['caregiver_loads']}")
    print()
    for m in result["match_details"]:
        flags = []
        if not m["hc_ok"]:
            flags.append("HC_FAIL")
        if m["same_district"]:
            flags.append("同区")
        if m["gender_ok"]:
            flags.append("性別OK")
        if m["history"] != "-" and int(m["history"]) >= 5:
            flags.append("継続★")
        flag_str = " ".join(f"[{f}]" for f in flags)
        print(f"  {m['receiver']:16s} → {m['caregiver']:16s} compat={m['compat']:3d} hist={m['history']} {m['district']:14s} {flag_str}")


def main():
    receivers, caregivers, history = load_data()
    all_results = {}

    # Baseline 1: Random
    m1 = baseline_random(receivers, caregivers, history)
    e1 = evaluate(m1, receivers, caregivers, history)
    print_result("Baseline 1: ランダム", e1)
    all_results["random"] = e1

    # Baseline 2: Greedy
    m2 = baseline_greedy(receivers, caregivers, history)
    e2 = evaluate(m2, receivers, caregivers, history)
    print_result("Baseline 2: 貪欲法（要介護度優先）", e2)
    all_results["greedy"] = e2

    # Baseline 3: CP-SAT
    m3, info3 = solve_cpsat(receivers, caregivers, history, improved=False)
    e3 = evaluate(m3, receivers, caregivers, history)
    print_result(f"Baseline 3: CP-SAT ソルバー ({info3})", e3)
    all_results["solver"] = {**e3, "solver_info": info3}

    # Improved: CP-SAT + 継続ボーナス + SC06強化
    m4, info4 = solve_cpsat(receivers, caregivers, history, improved=True)
    e4 = evaluate(m4, receivers, caregivers, history)
    print_result(f"改善: CP-SAT + 継続ボーナス + SC06強化 ({info4})", e4)
    all_results["improved"] = {**e4, "solver_info": info4}

    # Summary
    print(f"\n{'=' * 60}")
    print("比較サマリー")
    print(f"{'=' * 60}")
    print(f"{'手法':<30} {'Feasible':<10} {'Match':<8} {'HC':<5} {'Compat':<8} {'継続':<8} {'同区':<8}")
    print("-" * 77)
    for name, r in [("ランダム", e1), ("貪欲法", e2), ("CP-SAT", e3), ("改善(CP-SAT+)", e4)]:
        print(f"{name:<30} {str(r['feasible']):<10} {r['match_rate']:<8} {r['total_hc']:<5} {r['avg_compatibility']:<8} {r['continuity']:<8} {r['district_match']:<8}")

    with open(RESULTS_DIR / "results.json", "w") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nSaved to {RESULTS_DIR / 'results.json'}")


if __name__ == "__main__":
    main()
