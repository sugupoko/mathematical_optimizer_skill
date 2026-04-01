"""シフト最適化: 全ワークフロー一括実行スクリプト。

データ分析 → 3ベースライン → ボトルネック特定 → 改善 → 評価 → 結果保存
"""
from __future__ import annotations

import csv
import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from ortools.sat.python import cp_model

# --- パス設定 ---
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SHIFTS = ["morning", "afternoon", "night"]
HOURS_PER_SHIFT = 8

# =============================================================================
# 1. データ読み込み
# =============================================================================

def load_employees(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        employees = []
        for row in reader:
            emp = {
                "id": row["employee_id"],
                "name": row["name"],
                "skills": [s.strip() for s in row["skills"].split(",")],
                "max_hours": int(row["max_hours_per_week"]),
                "min_hours": int(row["min_hours_per_week"]),
                "unavailable": [d.strip() for d in row["unavailable_days"].split(",") if d.strip()],
            }
            employees.append(emp)
    return employees


def load_shifts(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        shifts = []
        for row in reader:
            s = {
                "day": row["day"],
                "shift_name": row["shift_name"],
                "start_time": row["start_time"],
                "end_time": row["end_time"],
                "required_count": int(row["required_count"]),
                "required_skills": [sk.strip() for sk in row["required_skills"].split(",")],
            }
            shifts.append(s)
    return shifts


def load_constraints(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


# =============================================================================
# 2. データ分析
# =============================================================================

def analyze_data(employees, shifts):
    """供給 vs 需要のギャップ分析。"""
    # --- 需要側 ---
    total_demand_slots = sum(s["required_count"] for s in shifts)
    total_demand_hours = total_demand_slots * HOURS_PER_SHIFT

    demand_by_day = defaultdict(int)
    demand_by_shift = defaultdict(int)
    demand_by_skill = defaultdict(int)
    for s in shifts:
        demand_by_day[s["day"]] += s["required_count"]
        demand_by_shift[s["shift_name"]] += s["required_count"]
        for sk in s["required_skills"]:
            demand_by_skill[sk] += s["required_count"]

    # --- 供給側 ---
    total_supply_hours = sum(e["max_hours"] for e in employees)
    total_min_hours = sum(e["min_hours"] for e in employees)

    skill_supply = defaultdict(int)
    for e in employees:
        for sk in e["skills"]:
            skill_supply[sk] += 1

    # 日ごとの利用可能人数
    avail_by_day = {}
    for d in DAYS:
        avail_by_day[d] = sum(1 for e in employees if d not in e["unavailable"])

    analysis = {
        "num_employees": len(employees),
        "num_shift_slots": len(shifts),
        "total_demand_slots": total_demand_slots,
        "total_demand_hours": total_demand_hours,
        "total_supply_max_hours": total_supply_hours,
        "total_supply_min_hours": total_min_hours,
        "supply_demand_ratio": round(total_supply_hours / total_demand_hours, 2) if total_demand_hours else 0,
        "demand_by_day": dict(demand_by_day),
        "demand_by_shift": dict(demand_by_shift),
        "demand_by_skill": dict(demand_by_skill),
        "skill_supply_count": dict(skill_supply),
        "available_by_day": avail_by_day,
        "feasibility_check": "FEASIBLE" if total_supply_hours >= total_demand_hours else "POTENTIALLY_INFEASIBLE",
    }

    # 日ごとの需要 vs 供給
    day_analysis = {}
    for d in DAYS:
        day_demand = demand_by_day[d]
        day_avail = avail_by_day[d]
        day_analysis[d] = {
            "demand_slots": day_demand,
            "available_employees": day_avail,
            "status": "OK" if day_avail >= day_demand else "TIGHT",
        }
    analysis["day_analysis"] = day_analysis

    return analysis


# =============================================================================
# 3. 評価関数（共通）
# =============================================================================

def evaluate(schedule: list[dict], employees: list[dict], shifts: list[dict]) -> dict:
    """
    schedule: [{"employee_id": ..., "day": ..., "shift_name": ...}, ...]
    """
    emp_map = {e["id"]: e for e in employees}

    # --- ハード制約 ---
    hard_violations = {}

    # HC1: 必要人数
    hc1_violations = 0
    hc1_details = []
    for s in shifts:
        assigned = sum(
            1 for a in schedule
            if a["day"] == s["day"] and a["shift_name"] == s["shift_name"]
        )
        if assigned < s["required_count"]:
            hc1_violations += s["required_count"] - assigned
            hc1_details.append(f"{s['day']}_{s['shift_name']}: {assigned}/{s['required_count']}")
    hard_violations["HC1_required_count"] = hc1_violations

    # HC2: 週最大勤務時間
    hc2_violations = 0
    hours_per_emp = defaultdict(int)
    for a in schedule:
        hours_per_emp[a["employee_id"]] += HOURS_PER_SHIFT
    for eid, hours in hours_per_emp.items():
        if eid in emp_map and hours > emp_map[eid]["max_hours"]:
            hc2_violations += 1
    hard_violations["HC2_max_hours"] = hc2_violations

    # HC3: 利用不可日
    hc3_violations = 0
    for a in schedule:
        e = emp_map.get(a["employee_id"])
        if e and a["day"] in e["unavailable"]:
            hc3_violations += 1
    hard_violations["HC3_unavailable"] = hc3_violations

    # HC4: スキル
    hc4_violations = 0
    for a in schedule:
        e = emp_map.get(a["employee_id"])
        s = next(
            (s for s in shifts if s["day"] == a["day"] and s["shift_name"] == a["shift_name"]),
            None,
        )
        if e and s:
            for sk in s["required_skills"]:
                if sk not in e["skills"]:
                    hc4_violations += 1
    hard_violations["HC4_skills"] = hc4_violations

    # HC5: 夜勤→翌日朝勤禁止
    hc5_violations = 0
    for a in schedule:
        if a["shift_name"] == "night":
            day_idx = DAYS.index(a["day"])
            if day_idx < len(DAYS) - 1:
                next_day = DAYS[day_idx + 1]
                if any(
                    b["employee_id"] == a["employee_id"]
                    and b["day"] == next_day
                    and b["shift_name"] == "morning"
                    for b in schedule
                ):
                    hc5_violations += 1
    hard_violations["HC5_night_morning"] = hc5_violations

    total_hard = sum(hard_violations.values())
    feasible = total_hard == 0

    # --- ソフト制約 ---
    soft_scores = {}

    # SC1: 連続勤務 <= 5日
    sc1_penalty = 0
    for e in employees:
        days_worked = sorted(
            [DAYS.index(a["day"]) for a in schedule if a["employee_id"] == e["id"]]
        )
        max_consec = 0
        consec = 1
        for i in range(1, len(days_worked)):
            if days_worked[i] == days_worked[i - 1] + 1:
                consec += 1
            else:
                max_consec = max(max_consec, consec)
                consec = 1
        max_consec = max(max_consec, consec) if days_worked else 0
        if max_consec > 5:
            sc1_penalty += (max_consec - 5) * 10
    soft_scores["SC1_consecutive"] = -sc1_penalty

    # SC2: 公平性（時間の標準偏差を最小化）
    all_hours = [hours_per_emp.get(e["id"], 0) for e in employees]
    if len(all_hours) > 1:
        std_hours = statistics.stdev(all_hours)
    else:
        std_hours = 0
    soft_scores["SC2_fairness"] = -round(std_hours * 5, 2)  # ペナルティ

    # SC3: 最低勤務時間確保
    sc3_penalty = 0
    for e in employees:
        hours = hours_per_emp.get(e["id"], 0)
        if hours < e["min_hours"]:
            sc3_penalty += (e["min_hours"] - hours)
    soft_scores["SC3_min_hours"] = -sc3_penalty * 3

    # SC4: 夜勤 <= 2回/週
    sc4_penalty = 0
    night_count = defaultdict(int)
    for a in schedule:
        if a["shift_name"] == "night":
            night_count[a["employee_id"]] += 1
    for eid, cnt in night_count.items():
        if cnt > 2:
            sc4_penalty += (cnt - 2) * 8
    soft_scores["SC4_night_limit"] = -sc4_penalty

    # SC5: トレーニング持ちを毎日配置
    sc5_bonus = 0
    training_emps = {e["id"] for e in employees if "training" in e["skills"]}
    for d in DAYS:
        day_assignments = [a for a in schedule if a["day"] == d]
        has_trainer = any(a["employee_id"] in training_emps for a in day_assignments)
        if has_trainer:
            sc5_bonus += 5
    soft_scores["SC5_training"] = sc5_bonus

    total_soft = sum(soft_scores.values())

    return {
        "feasibility": 1 if feasible else 0,
        "hard_violations": total_hard,
        "hard_violations_detail": hard_violations,
        "soft_score": round(total_soft, 2),
        "soft_scores_detail": soft_scores,
        "total_assignments": len(schedule),
        "hours_per_employee": dict(hours_per_emp),
        "hours_std": round(std_hours, 2),
    }


# =============================================================================
# 4. ベースライン1: ランダム割当
# =============================================================================

def solve_random(employees, shifts, seed=42) -> list[dict]:
    """各シフトに必要人数分ランダムに割り当てる。制約は無視。"""
    rng = random.Random(seed)
    schedule = []

    for s in shifts:
        candidates = [e for e in employees if s["day"] not in e["unavailable"]]
        if not candidates:
            candidates = list(employees)

        # スキルフィルタ
        skilled = [e for e in candidates if any(sk in e["skills"] for sk in s["required_skills"])]
        pool = skilled if skilled else candidates

        chosen = rng.sample(pool, min(s["required_count"], len(pool)))
        for e in chosen:
            schedule.append({
                "employee_id": e["id"],
                "day": s["day"],
                "shift_name": s["shift_name"],
            })

    return schedule


# =============================================================================
# 5. ベースライン2: 貪欲法
# =============================================================================

def solve_greedy(employees, shifts) -> list[dict]:
    """
    需要が多いシフトから順に、勤務時間が少ない従業員を優先的に割当。
    ハード制約を考慮する。
    """
    schedule = []
    hours_used = defaultdict(int)
    night_assignments = defaultdict(list)  # emp_id -> [day_indices]

    # 需要が多い順にソート
    sorted_shifts = sorted(shifts, key=lambda s: -s["required_count"])

    for s in sorted_shifts:
        required = s["required_count"]
        assigned_this_shift = []

        # 候補: スキルあり、利用不可日でない、max_hours超えない
        candidates = []
        for e in employees:
            if s["day"] in e["unavailable"]:
                continue
            if not any(sk in e["skills"] for sk in s["required_skills"]):
                continue
            if hours_used[e["id"]] + HOURS_PER_SHIFT > e["max_hours"]:
                continue
            # 同日に既に割り当てられていないか
            if any(a["employee_id"] == e["id"] and a["day"] == s["day"] for a in schedule):
                continue
            # HC5: 夜勤→翌日朝勤チェック
            day_idx = DAYS.index(s["day"])
            if s["shift_name"] == "morning" and day_idx > 0:
                prev_day = DAYS[day_idx - 1]
                if any(
                    a["employee_id"] == e["id"] and a["day"] == prev_day and a["shift_name"] == "night"
                    for a in schedule
                ):
                    continue
            if s["shift_name"] == "night":
                if day_idx < len(DAYS) - 1:
                    next_day = DAYS[day_idx + 1]
                    if any(
                        a["employee_id"] == e["id"] and a["day"] == next_day and a["shift_name"] == "morning"
                        for a in schedule
                    ):
                        continue

            candidates.append(e)

        # 勤務時間が少ない順
        candidates.sort(key=lambda e: hours_used[e["id"]])

        for e in candidates[:required]:
            schedule.append({
                "employee_id": e["id"],
                "day": s["day"],
                "shift_name": s["shift_name"],
            })
            hours_used[e["id"]] += HOURS_PER_SHIFT

    return schedule


# =============================================================================
# 6. ベースライン3: CP-SAT ソルバー (基本版)
# =============================================================================

def solve_cpsat_basic(employees, shifts, time_limit=60, relax_hc1=False) -> tuple[list[dict], float | None]:
    """CP-SATソルバーによる基本的な定式化。

    relax_hc1=True の場合、必要人数をハード制約ではなく最大化目的にする
    （供給不足で infeasible になる場合の対策）。
    """
    model = cp_model.CpModel()
    emp_map = {e["id"]: e for e in employees}

    # 決定変数: x[emp_id, day, shift_name] = 1 ならば割当
    x = {}
    for e in employees:
        for s in shifts:
            # スキルチェック（枝刈り）
            if not any(sk in e["skills"] for sk in s["required_skills"]):
                continue
            if s["day"] in e["unavailable"]:
                continue
            key = (e["id"], s["day"], s["shift_name"])
            x[key] = model.new_bool_var(f"x_{e['id']}_{s['day']}_{s['shift_name']}")

    # HC1: 必要人数
    shortage_vars = []
    for s in shifts:
        assigned = [
            x[(e["id"], s["day"], s["shift_name"])]
            for e in employees
            if (e["id"], s["day"], s["shift_name"]) in x
        ]
        if assigned:
            if relax_hc1:
                # 不足分をペナルティとして最小化
                shortage = model.new_int_var(0, s["required_count"],
                                             f"short_{s['day']}_{s['shift_name']}")
                model.add(sum(assigned) + shortage >= s["required_count"])
                shortage_vars.append(shortage)
            else:
                model.add(sum(assigned) >= s["required_count"])

    # HC2: 週最大勤務時間
    for e in employees:
        weekly = [
            x[key] for key in x if key[0] == e["id"]
        ]
        if weekly:
            model.add(sum(weekly) * HOURS_PER_SHIFT <= e["max_hours"])

    # 同一日に1シフトまで（暗黙の制約）
    for e in employees:
        for d in DAYS:
            day_shifts = [x[key] for key in x if key[0] == e["id"] and key[1] == d]
            if day_shifts:
                model.add(sum(day_shifts) <= 1)

    # HC5: 夜勤→翌日朝勤禁止
    for e in employees:
        for i, d in enumerate(DAYS[:-1]):
            next_d = DAYS[i + 1]
            night_key = (e["id"], d, "night")
            morning_key = (e["id"], next_d, "morning")
            if night_key in x and morning_key in x:
                model.add(x[night_key] + x[morning_key] <= 1)

    # 目的関数
    if relax_hc1 and shortage_vars:
        # 不足を最小化（= 配置を最大化）
        model.minimize(sum(shortage_vars) * 100)
    # else: feasibility探索のみ

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 8

    status = solver.solve(model)
    status_name = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
    }.get(status, "UNKNOWN")
    print(f"  CP-SAT Basic status: {status_name} (relax_hc1={relax_hc1})")

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        if not relax_hc1:
            print("  → HC1をハード制約のまま解けない。緩和モードで再試行...")
            return solve_cpsat_basic(employees, shifts, time_limit, relax_hc1=True)
        return [], None

    schedule = []
    for key, var in x.items():
        if solver.value(var) == 1:
            schedule.append({
                "employee_id": key[0],
                "day": key[1],
                "shift_name": key[2],
            })

    return schedule, solver.objective_value if status == cp_model.OPTIMAL else None


# =============================================================================
# 7. 改善版ソルバー: 目的関数精密一致 + ソフト制約
# =============================================================================

def solve_cpsat_improved(employees, shifts, time_limit=120) -> tuple[list[dict], float | None]:
    """
    改善版CP-SAT: ハード制約 + ソフト制約を目的関数に組み込む。
    評価関数と完全一致させる。
    HC1（必要人数）は緩和し、不足ペナルティとして目的関数に組み込む。
    """
    model = cp_model.CpModel()
    emp_map = {e["id"]: e for e in employees}
    training_emps = {e["id"] for e in employees if "training" in e["skills"]}

    # 決定変数
    x = {}
    for e in employees:
        for s in shifts:
            if not any(sk in e["skills"] for sk in s["required_skills"]):
                continue
            if s["day"] in e["unavailable"]:
                continue
            key = (e["id"], s["day"], s["shift_name"])
            x[key] = model.new_bool_var(f"x_{e['id']}_{s['day']}_{s['shift_name']}")

    # === ハード制約 ===
    objective_terms = []

    # HC1: 必要人数 → 緩和（不足ペナルティ、最重要）
    for s in shifts:
        assigned = [
            x[(e["id"], s["day"], s["shift_name"])]
            for e in employees
            if (e["id"], s["day"], s["shift_name"]) in x
        ]
        if assigned:
            shortage = model.new_int_var(0, s["required_count"],
                                         f"short_{s['day']}_{s['shift_name']}")
            model.add(sum(assigned) + shortage >= s["required_count"])
            # 重いペナルティ（他のソフト制約より優先）
            objective_terms.append(-shortage * 200)

    # HC2: 週最大勤務時間
    for e in employees:
        weekly = [x[key] for key in x if key[0] == e["id"]]
        if weekly:
            model.add(sum(weekly) * HOURS_PER_SHIFT <= e["max_hours"])

    # 同一日に1シフトまで
    for e in employees:
        for d in DAYS:
            day_shifts = [x[key] for key in x if key[0] == e["id"] and key[1] == d]
            if day_shifts:
                model.add(sum(day_shifts) <= 1)

    # HC5: 夜勤→翌日朝勤禁止
    for e in employees:
        for i, d in enumerate(DAYS[:-1]):
            next_d = DAYS[i + 1]
            night_key = (e["id"], d, "night")
            morning_key = (e["id"], next_d, "morning")
            if night_key in x and morning_key in x:
                model.add(x[night_key] + x[morning_key] <= 1)

    # === ソフト制約を目的関数に組み込む ===

    # SC2: 公平性 — 各従業員の勤務時間を平均に近づける
    # 総需要スロット数 / 従業員数 = 目標シフト数
    total_demand = sum(s["required_count"] for s in shifts)
    avg_shifts = total_demand / len(employees)

    # 各従業員の勤務数
    emp_shift_count = {}
    for e in employees:
        emp_vars = [x[key] for key in x if key[0] == e["id"]]
        if emp_vars:
            total = model.new_int_var(0, 7, f"total_{e['id']}")
            model.add(total == sum(emp_vars))
            emp_shift_count[e["id"]] = total

            # 偏差を最小化（絶対値近似）
            dev = model.new_int_var(0, 7, f"dev_{e['id']}")
            target = int(round(avg_shifts))
            model.add(dev >= total - target)
            model.add(dev >= target - total)
            objective_terms.append(-dev * 5)  # SC2 weight=5, ペナルティ

    # SC3: 最低勤務時間確保
    for e in employees:
        min_shifts = e["min_hours"] // HOURS_PER_SHIFT
        emp_vars = [x[key] for key in x if key[0] == e["id"]]
        if emp_vars:
            shortfall = model.new_int_var(0, 7, f"sf_{e['id']}")
            total_var = emp_shift_count.get(e["id"])
            if total_var is not None:
                model.add(shortfall >= min_shifts - total_var)
                model.add(shortfall >= 0)
                objective_terms.append(-shortfall * 3 * HOURS_PER_SHIFT)  # SC3 weight=3

    # SC4: 夜勤 <= 2回
    for e in employees:
        night_vars = [x[key] for key in x if key[0] == e["id"] and key[2] == "night"]
        if night_vars:
            night_total = model.new_int_var(0, 7, f"night_{e['id']}")
            model.add(night_total == sum(night_vars))
            excess = model.new_int_var(0, 7, f"nexcess_{e['id']}")
            model.add(excess >= night_total - 2)
            model.add(excess >= 0)
            objective_terms.append(-excess * 8)  # SC4 weight=8

    # SC5: トレーニング持ちを毎日配置
    for d in DAYS:
        trainer_vars = [
            x[key] for key in x
            if key[1] == d and key[0] in training_emps
        ]
        if trainer_vars:
            has_trainer = model.new_bool_var(f"trainer_{d}")
            model.add(sum(trainer_vars) >= 1).only_enforce_if(has_trainer)
            model.add(sum(trainer_vars) == 0).only_enforce_if(has_trainer.negated())
            objective_terms.append(has_trainer * 5)  # SC5 weight=5

    # SC1: 連続勤務 <= 5日 (近似: 6日連続を禁止するソフト制約)
    for e in employees:
        for start_idx in range(len(DAYS) - 5):
            six_days = [
                x[key] for key in x
                if key[0] == e["id"] and key[1] in DAYS[start_idx:start_idx + 6]
            ]
            if len(six_days) >= 6:
                excess = model.new_int_var(0, 1, f"consec_{e['id']}_{start_idx}")
                model.add(sum(six_days) <= 5 + excess)
                objective_terms.append(-excess * 10)  # SC1 weight=10

    if objective_terms:
        model.maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 8

    status = solver.solve(model)
    status_name = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
    }.get(status, "UNKNOWN")
    print(f"  CP-SAT Improved status: {status_name}")

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return [], None

    schedule = []
    for key, var in x.items():
        if solver.value(var) == 1:
            schedule.append({
                "employee_id": key[0],
                "day": key[1],
                "shift_name": key[2],
            })

    return schedule, solver.objective_value


# =============================================================================
# 8. 改善版2: 2フェーズ (制約優先 + ローカルサーチ)
# =============================================================================

def solve_two_phase(employees, shifts, time_limit=120) -> list[dict]:
    """Phase1: CP-SATでfeasible取得 → Phase2: ローカルサーチで品質改善"""
    # Phase 1: feasible解
    schedule, _ = solve_cpsat_basic(employees, shifts, time_limit=30)
    if not schedule:
        print("  Two-phase: Phase1 failed (infeasible)")
        return []

    base_eval = evaluate(schedule, employees, shifts)
    print(f"  Phase1 score: soft={base_eval['soft_score']}, violations={base_eval['hard_violations']}")

    # Phase 2: ローカルサーチ（スワップベース）
    emp_map = {e["id"]: e for e in employees}
    best_schedule = list(schedule)
    best_score = base_eval["soft_score"]
    best_violations = base_eval["hard_violations"]

    rng = random.Random(42)
    iterations = 5000

    for _ in range(iterations):
        trial = list(best_schedule)
        # ランダムにスワップ: 2つの割当の従業員を入れ替え
        if len(trial) < 2:
            continue

        i, j = rng.sample(range(len(trial)), 2)
        trial[i], trial[j] = (
            {**trial[i], "employee_id": trial[j]["employee_id"]},
            {**trial[j], "employee_id": trial[i]["employee_id"]},
        )

        trial_eval = evaluate(trial, employees, shifts)
        # feasibleかつソフトスコア改善
        if trial_eval["hard_violations"] <= best_violations:
            if trial_eval["soft_score"] > best_score or trial_eval["hard_violations"] < best_violations:
                best_schedule = trial
                best_score = trial_eval["soft_score"]
                best_violations = trial_eval["hard_violations"]

    print(f"  Phase2 final: soft={best_score}, violations={best_violations}")
    return best_schedule


# =============================================================================
# 9. メイン
# =============================================================================

def main():
    print("=" * 60)
    print("シフト最適化 全ワークフロー実行")
    print("=" * 60)

    # --- データ読み込み ---
    employees = load_employees(DATA_DIR / "employees.csv")
    shifts = load_shifts(DATA_DIR / "shifts.csv")
    constraints = load_constraints(DATA_DIR / "constraints.csv")

    print(f"\n従業員数: {len(employees)}")
    print(f"シフト枠数: {len(shifts)}")
    print(f"制約数: {len(constraints)}")

    # --- データ分析 ---
    print("\n" + "=" * 60)
    print("PHASE 1: データ分析")
    print("=" * 60)
    analysis = analyze_data(employees, shifts)
    print(f"  総需要スロット: {analysis['total_demand_slots']}")
    print(f"  総需要時間: {analysis['total_demand_hours']}h")
    print(f"  総供給時間(max): {analysis['total_supply_max_hours']}h")
    print(f"  供給/需要比: {analysis['supply_demand_ratio']}")
    print(f"  フィージビリティ: {analysis['feasibility_check']}")

    print("\n  日別需要 vs 供給:")
    for d in DAYS:
        da = analysis["day_analysis"][d]
        print(f"    {d}: 需要={da['demand_slots']}枠, 利用可能={da['available_employees']}人 [{da['status']}]")

    print(f"\n  スキル別需要: {analysis['demand_by_skill']}")
    print(f"  スキル別供給: {analysis['skill_supply_count']}")

    # --- ベースライン ---
    print("\n" + "=" * 60)
    print("PHASE 2: ベースライン (3手法)")
    print("=" * 60)

    results = {}

    # Baseline 1: ランダム
    print("\n[1/3] ランダム割当")
    sched_random = solve_random(employees, shifts)
    eval_random = evaluate(sched_random, employees, shifts)
    results["random"] = {"schedule": sched_random, "evaluation": eval_random}
    print(f"  割当数: {eval_random['total_assignments']}")
    print(f"  ハード違反: {eval_random['hard_violations']} ({eval_random['hard_violations_detail']})")
    print(f"  ソフトスコア: {eval_random['soft_score']}")

    # Baseline 2: 貪欲法
    print("\n[2/3] 貪欲法")
    sched_greedy = solve_greedy(employees, shifts)
    eval_greedy = evaluate(sched_greedy, employees, shifts)
    results["greedy"] = {"schedule": sched_greedy, "evaluation": eval_greedy}
    print(f"  割当数: {eval_greedy['total_assignments']}")
    print(f"  ハード違反: {eval_greedy['hard_violations']} ({eval_greedy['hard_violations_detail']})")
    print(f"  ソフトスコア: {eval_greedy['soft_score']}")

    # Baseline 3: CP-SAT 基本版
    print("\n[3/3] CP-SAT ソルバー (基本版)")
    sched_cpsat, obj_val = solve_cpsat_basic(employees, shifts)
    eval_cpsat = evaluate(sched_cpsat, employees, shifts)
    results["cpsat_basic"] = {"schedule": sched_cpsat, "evaluation": eval_cpsat}
    print(f"  割当数: {eval_cpsat['total_assignments']}")
    print(f"  ハード違反: {eval_cpsat['hard_violations']} ({eval_cpsat['hard_violations_detail']})")
    print(f"  ソフトスコア: {eval_cpsat['soft_score']}")

    # --- ボトルネック分析 ---
    print("\n" + "=" * 60)
    print("PHASE 3: ボトルネック分析")
    print("=" * 60)

    bottlenecks = []
    # 最良ベースラインの問題点を分析
    best_baseline_name = max(
        ["random", "greedy", "cpsat_basic"],
        key=lambda k: (results[k]["evaluation"]["feasibility"], results[k]["evaluation"]["soft_score"]),
    )
    best_eval = results[best_baseline_name]["evaluation"]
    print(f"  最良ベースライン: {best_baseline_name}")

    if best_eval["hard_violations"] > 0:
        for k, v in best_eval["hard_violations_detail"].items():
            if v > 0:
                bottlenecks.append(f"ハード制約違反: {k} = {v}")
    for k, v in best_eval["soft_scores_detail"].items():
        if v < 0:
            bottlenecks.append(f"ソフト制約ペナルティ: {k} = {v}")

    print("  ボトルネック:")
    for b in bottlenecks:
        print(f"    - {b}")

    # --- 改善 ---
    print("\n" + "=" * 60)
    print("PHASE 4: 改善 (2手法)")
    print("=" * 60)

    # 改善1: 目的関数精密一致
    print("\n[改善1] CP-SAT + ソフト制約目的関数 (パターン1)")
    sched_improved, obj_val_imp = solve_cpsat_improved(employees, shifts)
    eval_improved = evaluate(sched_improved, employees, shifts)
    results["cpsat_improved"] = {"schedule": sched_improved, "evaluation": eval_improved}
    print(f"  割当数: {eval_improved['total_assignments']}")
    print(f"  ハード違反: {eval_improved['hard_violations']} ({eval_improved['hard_violations_detail']})")
    print(f"  ソフトスコア: {eval_improved['soft_score']}")
    print(f"  時間偏差(std): {eval_improved['hours_std']}")

    # 改善2: 2フェーズ
    print("\n[改善2] 2フェーズ (CP-SAT + ローカルサーチ, パターン6)")
    sched_two = solve_two_phase(employees, shifts)
    eval_two = evaluate(sched_two, employees, shifts)
    results["two_phase"] = {"schedule": sched_two, "evaluation": eval_two}
    print(f"  割当数: {eval_two['total_assignments']}")
    print(f"  ハード違反: {eval_two['hard_violations']} ({eval_two['hard_violations_detail']})")
    print(f"  ソフトスコア: {eval_two['soft_score']}")

    # --- 結果まとめ ---
    print("\n" + "=" * 60)
    print("結果サマリー")
    print("=" * 60)
    print(f"{'手法':<20} {'Feasible':>8} {'違反数':>6} {'ソフトスコア':>12} {'時間偏差':>8}")
    print("-" * 58)
    for name in ["random", "greedy", "cpsat_basic", "cpsat_improved", "two_phase"]:
        ev = results[name]["evaluation"]
        print(
            f"{name:<20} {'YES' if ev['feasibility'] else 'NO':>8} "
            f"{ev['hard_violations']:>6} {ev['soft_score']:>12.2f} "
            f"{ev['hours_std']:>8.2f}"
        )

    # --- 結果保存 ---
    print("\n保存中...")

    # 分析結果
    with open(RESULTS_DIR / "analysis.json", "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    # 各手法の結果
    summary = {}
    for name in ["random", "greedy", "cpsat_basic", "cpsat_improved", "two_phase"]:
        ev = results[name]["evaluation"]
        summary[name] = {
            "feasibility": ev["feasibility"],
            "hard_violations": ev["hard_violations"],
            "hard_violations_detail": ev["hard_violations_detail"],
            "soft_score": ev["soft_score"],
            "soft_scores_detail": ev["soft_scores_detail"],
            "total_assignments": ev["total_assignments"],
            "hours_std": ev["hours_std"],
            "hours_per_employee": ev["hours_per_employee"],
        }
    with open(RESULTS_DIR / "all_results.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # ベスト解のスケジュール
    best_name = max(
        summary.keys(),
        key=lambda k: (summary[k]["feasibility"], summary[k]["soft_score"]),
    )
    with open(RESULTS_DIR / "best_schedule.json", "w", encoding="utf-8") as f:
        json.dump({
            "method": best_name,
            "evaluation": summary[best_name],
            "schedule": results[best_name]["schedule"],
        }, f, ensure_ascii=False, indent=2)

    # ボトルネック
    with open(RESULTS_DIR / "bottleneck.json", "w", encoding="utf-8") as f:
        json.dump({
            "best_baseline": best_baseline_name,
            "bottlenecks": bottlenecks,
            "best_method_overall": best_name,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n完了! 最良手法: {best_name}")
    print(f"  Feasible: {summary[best_name]['feasibility']}")
    print(f"  ソフトスコア: {summary[best_name]['soft_score']}")
    print(f"結果は {RESULTS_DIR} に保存されました。")


if __name__ == "__main__":
    main()
