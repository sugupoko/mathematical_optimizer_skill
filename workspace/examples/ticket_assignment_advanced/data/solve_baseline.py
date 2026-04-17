"""ticket_assignment_advanced ベースライン解法。

50 エンジニア × 200 チケット × 4 タイムステップの
全部盛りチケットアサイン最適化問題を CP-SAT で解く。

2段階アプローチ:
  Stage 1: 確定的最適化 (T0 のスナップショットで最適割当)
  Stage 2: シナリオ評価 (100 シナリオで CVaR を計算し、ロバスト性を検証)

Usage:
  python solve_baseline.py
"""

from __future__ import annotations

import csv
import json
import math
import random
import statistics
import time
from pathlib import Path

from ortools.sat.python import cp_model

DATA = Path(__file__).parent

# ============================================================
# データ読み込み
# ============================================================

def load_csv(name: str) -> list[dict]:
    with open(DATA / name, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_json(name: str) -> dict:
    with open(DATA / name, encoding="utf-8") as f:
        return json.load(f)


def load_all():
    engineers = load_csv("engineers.csv")
    tickets = load_csv("tickets.csv")
    deps = load_csv("ticket_dependencies.csv")
    constraints = load_csv("constraints.csv")
    history = load_csv("resolution_history.csv")
    escalation = load_csv("escalation_rules.csv")
    penalties = load_csv("sla_penalties.csv")
    periods = load_csv("time_periods.csv")
    team = load_csv("team_constraints.csv")
    params = load_json("scenario_params.json")

    # 型変換
    for e in engineers:
        e["skills"] = e["skills"].split(",")
        e["max_concurrent"] = int(e["max_concurrent"])
        e["experience_years"] = int(e["experience_years"])
        e["on_shift"] = e["on_shift"] == "True"
        e["fatigue_level"] = float(e["fatigue_level"])
        e["mentoring_eligible"] = e["mentoring_eligible"] == "True"

    for t in tickets:
        t["required_skills"] = t["required_skills"].split(";")
        t["sla_remaining_hours"] = float(t["sla_remaining_hours"])
        t["progress_pct"] = int(t["progress_pct"])
        t["estimated_remaining_hours_mean"] = float(t["estimated_remaining_hours_mean"])
        t["estimated_remaining_hours_std"] = float(t["estimated_remaining_hours_std"])
        t["confidence"] = float(t["confidence"])
        t["max_assignees"] = int(t["max_assignees"])
        t["vip_customer"] = t["vip_customer"] == "True"

    for h in history:
        h["resolution_hours"] = float(h["resolution_hours"])

    for p in penalties:
        p["threshold_hours_remaining"] = float(p["threshold_hours_remaining"])
        p["penalty_multiplier"] = float(p["penalty_multiplier"])

    return {
        "engineers": engineers,
        "tickets": tickets,
        "dependencies": deps,
        "constraints": constraints,
        "history": history,
        "escalation": escalation,
        "penalties": penalties,
        "periods": periods,
        "team": team,
        "params": params,
    }


# ============================================================
# 解決時間の分布推定
# ============================================================

class ResolutionEstimator:
    """過去履歴から解決時間の分布 (mean, std) を推定する。"""

    def __init__(self, history: list[dict]):
        self.personal: dict[tuple[str, str], list[float]] = {}
        self.category: dict[str, list[float]] = {}

        for rec in history:
            skill = rec["skill"]
            eid = rec["engineer_id"]
            hours = rec["resolution_hours"]
            self.personal.setdefault((eid, skill), []).append(hours)
            self.category.setdefault(skill, []).append(hours)

    def estimate(self, engineer_id: str, skill: str, priority: str
                 ) -> tuple[float, float, float]:
        """(mean, std, confidence) を返す。"""
        key = (engineer_id, skill)
        if key in self.personal and len(self.personal[key]) >= 3:
            data = self.personal[key]
            return (
                statistics.mean(data),
                statistics.stdev(data) if len(data) > 1 else 0.5,
                min(0.9, 0.7 + 0.02 * (len(data) - 3)),
            )
        if skill in self.category:
            data = self.category[skill]
            return (
                statistics.mean(data),
                statistics.stdev(data) if len(data) > 1 else 1.0,
                0.3,
            )
        defaults = {"P1": 4.0, "P2": 8.0, "P3": 24.0, "P4": 72.0}
        return (defaults.get(priority, 24.0), 5.0, 0.1)


# ============================================================
# SLA ペナルティ計算
# ============================================================

def compute_sla_penalty(ticket: dict, penalties: list[dict]) -> int:
    """非線形SLAペナルティをスコア化 (整数)。"""
    priority = ticket["priority"]
    sla_remaining = ticket["sla_remaining_hours"]
    is_vip = ticket["vip_customer"]

    base_score = 0
    relevant = [p for p in penalties if p["priority"] == priority]
    # threshold 降順にチェック (最も厳しい条件から)
    relevant.sort(key=lambda p: p["threshold_hours_remaining"])

    for p in relevant:
        if sla_remaining <= p["threshold_hours_remaining"]:
            base_score = max(base_score, int(p["penalty_multiplier"] * 100))

    if base_score == 0:
        base_score = 10  # 通常状態の基本スコア

    # VIP 乗数
    if is_vip:
        vip_entry = [p for p in penalties if p["priority"] == "VIP"]
        if vip_entry:
            base_score = int(base_score * vip_entry[0]["penalty_multiplier"])

    return base_score


# ============================================================
# ティア比較
# ============================================================

TIER_ORDER = {"L1": 1, "L2": 2, "L3": 3, "L4": 4}


def tier_ge(eng_tier: str, required_tier: str) -> bool:
    return TIER_ORDER.get(eng_tier, 0) >= TIER_ORDER.get(required_tier, 0)


def tier_val(tier: str) -> int:
    return TIER_ORDER.get(tier, 0)


# ============================================================
# Stage 1: 確定的 CP-SAT 最適化 (T0)
# ============================================================

def solve_deterministic(data: dict, time_limit: int = 120) -> dict:
    """T0 のスナップショットで確定的最適化。"""

    engineers = [e for e in data["engineers"] if e["on_shift"]]
    tickets = data["tickets"]
    penalties = data["penalties"]
    team = data["team"]
    deps = data["dependencies"]
    estimator = ResolutionEstimator(data["history"])

    # 割当対象: unassigned のみ
    to_assign = [t for t in tickets if t["status"] == "unassigned"]
    # blocked_dependency で blocker が未解決のものは除外
    blocker_ids = {d["blocker_ticket_id"] for d in deps if d["dependency_type"] in ("blocks", "sequence")}
    blocked_by_dep = set()
    for d in deps:
        if d["dependency_type"] in ("blocks", "sequence"):
            blocker = next((t for t in tickets if t["ticket_id"] == d["blocker_ticket_id"]), None)
            if blocker and blocker["status"] not in ("resolved",):
                blocked_by_dep.add(d["blocked_ticket_id"])

    to_assign = [t for t in to_assign if t["ticket_id"] not in blocked_by_dep]

    # 既存割当の負荷計算
    current_load: dict[str, int] = {e["engineer_id"]: 0 for e in engineers}
    for t in tickets:
        if t["assigned_to"] and t["status"] not in ("resolved",):
            if t["assigned_to"] in current_load:
                current_load[t["assigned_to"]] += 1

    # 禁止ペア
    forbidden_pairs = set()
    for tc in team:
        if tc["type"] == "forbidden_pair" and tc["engineer_1"] and tc["engineer_2"]:
            forbidden_pairs.add((tc["engineer_1"], tc["engineer_2"]))
            forbidden_pairs.add((tc["engineer_2"], tc["engineer_1"]))

    print(f"\n=== Stage 1: 確定的最適化 ===")
    print(f"  割当対象チケット: {len(to_assign)} 件 (blocked_dep 除外: {len(blocked_by_dep)} 件)")
    print(f"  利用可能エンジニア: {len(engineers)} 名")

    model = cp_model.CpModel()
    n_tickets = len(to_assign)
    n_eng = len(engineers)

    if n_tickets == 0:
        return {"assignments": {}, "solver_info": {"status": "NO_TICKETS"}}

    # --- 決定変数 ---
    # 通常チケット (max_assignees == 1): x[t, e] = 1 で割当
    # スワーミング (max_assignees > 1): x[t, e, role] = 1 で役割付き割当
    x = {}
    swarming_tickets = []
    single_tickets = []

    for t_idx, ticket in enumerate(to_assign):
        if ticket["max_assignees"] > 1:
            swarming_tickets.append((t_idx, ticket))
            roles = ticket["swarming_roles"].split(",")
            for r_idx, role in enumerate(roles):
                for e_idx in range(n_eng):
                    x[t_idx, e_idx, r_idx] = model.new_bool_var(
                        f"x_{t_idx}_{e_idx}_{role}"
                    )
        else:
            single_tickets.append((t_idx, ticket))
            for e_idx in range(n_eng):
                x[t_idx, e_idx, 0] = model.new_bool_var(f"x_{t_idx}_{e_idx}")

    # --- ハード制約 ---

    # HC01: スキルマッチ — マルチスキルは個人で全カバーまたはスワーミングで分担
    for t_idx, ticket in single_tickets:
        for e_idx, eng in enumerate(engineers):
            if not all(s in eng["skills"] for s in ticket["required_skills"]):
                model.add(x[t_idx, e_idx, 0] == 0)

    # HC11: マルチスキルカバレッジ (スワーミング)
    # スワーミングでは全メンバーの skills の和集合 ⊇ required_skills
    # → 各必要スキルについて、少なくとも1人がそのスキルを持つ
    # ただし「割当しない」も許容: lead が割当されている場合のみ enforce
    for t_idx, ticket in swarming_tickets:
        roles = ticket["swarming_roles"].split(",")
        lead_assigned = model.new_bool_var(f"lead_assigned_{t_idx}")
        lead_vars = [x[t_idx, e_idx, 0] for e_idx in range(n_eng)]
        model.add(sum(lead_vars) >= 1).only_enforce_if(lead_assigned)
        model.add(sum(lead_vars) == 0).only_enforce_if(lead_assigned.Not())

        for skill in ticket["required_skills"]:
            capable = []
            for r_idx in range(len(roles)):
                for e_idx, eng in enumerate(engineers):
                    if skill in eng["skills"]:
                        capable.append(x[t_idx, e_idx, r_idx])
            if capable:
                # lead が割当されている場合のみスキルカバレッジを要求
                model.add(sum(capable) >= 1).only_enforce_if(lead_assigned)

    # HC02: ティア要件
    for t_idx, ticket in single_tickets:
        for e_idx, eng in enumerate(engineers):
            if not tier_ge(eng["tier"], ticket["min_tier"]):
                model.add(x[t_idx, e_idx, 0] == 0)

    for t_idx, ticket in swarming_tickets:
        roles = ticket["swarming_roles"].split(",")
        for r_idx, role in enumerate(roles):
            for e_idx, eng in enumerate(engineers):
                if role == "lead" and not tier_ge(eng["tier"], ticket["min_tier"]):
                    model.add(x[t_idx, e_idx, r_idx] == 0)
                elif role == "support":
                    min_support_tier = max(1, tier_val(ticket["min_tier"]) - 1)
                    if tier_val(eng["tier"]) < min_support_tier:
                        model.add(x[t_idx, e_idx, r_idx] == 0)
                # observer: ティア制限なし

    # HC05/HC06: スワーミングロール — lead は1人、各ロールは1人
    # lead がいなければ support/observer もいない (チーム全体が割当 or 非割当)
    for t_idx, ticket in swarming_tickets:
        roles = ticket["swarming_roles"].split(",")
        lead_vars = [x[t_idx, e_idx, 0] for e_idx in range(n_eng)]

        for r_idx in range(len(roles)):
            role_vars = [x[t_idx, e_idx, r_idx] for e_idx in range(n_eng)]
            model.add(sum(role_vars) <= 1)

        # support/observer は lead がいる場合のみ割当可能
        for r_idx in range(1, len(roles)):
            role_vars = [x[t_idx, e_idx, r_idx] for e_idx in range(n_eng)]
            model.add(sum(role_vars) <= sum(lead_vars))

        # 同一人物が複数ロールを兼任しない
        for e_idx in range(n_eng):
            person_roles = [x[t_idx, e_idx, r_idx] for r_idx in range(len(roles))]
            model.add(sum(person_roles) <= 1)

    # 単一チケット: 最大1人に割当
    for t_idx, ticket in single_tickets:
        vars_for_ticket = [x[t_idx, e_idx, 0] for e_idx in range(n_eng)]
        model.add(sum(vars_for_ticket) <= 1)

    # HC04: 容量制約 (疲労係数込み)
    for e_idx, eng in enumerate(engineers):
        fatigue_penalty = 1 if eng["fatigue_level"] > 0.6 else 0
        effective_cap = eng["max_concurrent"] - current_load.get(eng["engineer_id"], 0) - fatigue_penalty
        effective_cap = max(0, effective_cap)

        all_vars = []
        for t_idx, ticket in single_tickets:
            all_vars.append(x[t_idx, e_idx, 0])
        for t_idx, ticket in swarming_tickets:
            roles = ticket["swarming_roles"].split(",")
            for r_idx in range(len(roles)):
                all_vars.append(x[t_idx, e_idx, r_idx])
        model.add(sum(all_vars) <= effective_cap)

    # HC09: 禁止ペア (スワーミング内)
    for t_idx, ticket in swarming_tickets:
        roles = ticket["swarming_roles"].split(",")
        for e1_idx, eng1 in enumerate(engineers):
            for e2_idx, eng2 in enumerate(engineers):
                if e1_idx >= e2_idx:
                    continue
                if (eng1["engineer_id"], eng2["engineer_id"]) in forbidden_pairs:
                    for r1 in range(len(roles)):
                        for r2 in range(len(roles)):
                            if r1 != r2:
                                model.add(x[t_idx, e1_idx, r1] + x[t_idx, e2_idx, r2] <= 1)

    # HC10: L4 は P1 または P2+VIP のみ
    for t_idx, ticket in single_tickets + swarming_tickets:
        is_swarming = ticket["max_assignees"] > 1
        for e_idx, eng in enumerate(engineers):
            if eng["tier"] == "L4":
                eligible = (ticket["priority"] == "P1" or
                           (ticket["priority"] == "P2" and ticket["vip_customer"]))
                if not eligible:
                    if is_swarming:
                        roles = ticket["swarming_roles"].split(",")
                        for r_idx in range(len(roles)):
                            model.add(x[t_idx, e_idx, r_idx] == 0)
                    else:
                        model.add(x[t_idx, e_idx, 0] == 0)

    # HC12: スワーミング同時参加上限 (2件)
    for e_idx in range(n_eng):
        swarming_participations = []
        for t_idx, ticket in swarming_tickets:
            roles = ticket["swarming_roles"].split(",")
            # この人がこのチケットに参加しているか (any role)
            participating = model.new_bool_var(f"swarm_part_{t_idx}_{e_idx}")
            role_vars = [x[t_idx, e_idx, r_idx] for r_idx in range(len(roles))]
            model.add(sum(role_vars) >= 1).only_enforce_if(participating)
            model.add(sum(role_vars) == 0).only_enforce_if(participating.negated())
            swarming_participations.append(participating)
        if swarming_participations:
            model.add(sum(swarming_participations) <= 2)

    # --- 目的関数 ---
    objective_terms = []

    for t_idx, ticket in single_tickets:
        sla_penalty = compute_sla_penalty(ticket, penalties)
        for e_idx, eng in enumerate(engineers):
            # SC01: SLA 優先
            score = sla_penalty

            # SC02: スキル適性
            mean, std, conf = estimator.estimate(
                eng["engineer_id"], ticket["required_skills"][0], ticket["priority"]
            )
            speed_bonus = max(0, int((1.0 / max(0.1, mean)) * 50 * conf))
            score += speed_bonus

            # SC05: ティア効率 (低ティアほどボーナス)
            tier_diff = tier_val(eng["tier"]) - tier_val(ticket["min_tier"])
            tier_penalty = tier_diff * 10
            score -= tier_penalty

            # SC06: 不確実性ロバスト (低分散を優先)
            robustness = max(0, int((1.0 / max(0.1, std)) * 30))
            score += robustness

            # SC10: 疲労回避
            if eng["fatigue_level"] > 0.6:
                score -= 20

            # SC03: 負荷均等 (現在負荷が少ないエンジニアにボーナス)
            load_bonus = max(0, 15 - current_load.get(eng["engineer_id"], 0) * 5)
            score += load_bonus

            score = max(0, score)
            objective_terms.append(x[t_idx, e_idx, 0] * score)

    for t_idx, ticket in swarming_tickets:
        sla_penalty = compute_sla_penalty(ticket, penalties)
        roles = ticket["swarming_roles"].split(",")
        for r_idx, role in enumerate(roles):
            role_weight = {"lead": 1.0, "support": 0.6, "observer": 0.2}.get(role, 0.5)
            for e_idx, eng in enumerate(engineers):
                score = int(sla_penalty * role_weight)

                if role == "lead":
                    primary_skill = ticket["required_skills"][0]
                    mean, std, conf = estimator.estimate(
                        eng["engineer_id"], primary_skill, ticket["priority"]
                    )
                    score += max(0, int((1.0 / max(0.1, mean)) * 40 * conf))
                    score += max(0, int((1.0 / max(0.1, std)) * 20))

                # SC07: メンタリングボーナス
                if role == "observer" and eng["tier"] == "L1":
                    score += 15

                if eng["fatigue_level"] > 0.6:
                    score -= 15

                score = max(0, score)
                objective_terms.append(x[t_idx, e_idx, r_idx] * score)

    # 最大化
    model.maximize(sum(objective_terms))

    # --- 求解 ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 8

    start_time = time.time()
    status = solver.solve(model)
    wall_time = time.time() - start_time

    status_name = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }.get(status, "UNKNOWN")

    print(f"\n  Solver status: {status_name}")
    print(f"  Wall time: {wall_time:.2f}s")
    print(f"  Objective: {solver.objective_value if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else 'N/A'}")

    # --- 結果抽出 ---
    assignments = {}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for t_idx, ticket in single_tickets:
            for e_idx, eng in enumerate(engineers):
                if solver.value(x[t_idx, e_idx, 0]):
                    assignments[ticket["ticket_id"]] = {
                        "engineer_id": eng["engineer_id"],
                        "role": "lead",
                        "engineer_name": eng["name"],
                        "engineer_tier": eng["tier"],
                    }

        for t_idx, ticket in swarming_tickets:
            roles = ticket["swarming_roles"].split(",")
            team_members = []
            for r_idx, role in enumerate(roles):
                for e_idx, eng in enumerate(engineers):
                    if solver.value(x[t_idx, e_idx, r_idx]):
                        team_members.append({
                            "engineer_id": eng["engineer_id"],
                            "role": role,
                            "engineer_name": eng["name"],
                            "engineer_tier": eng["tier"],
                        })
            if team_members:
                assignments[ticket["ticket_id"]] = team_members

    # 変数数・制約数
    n_vars = sum(1 for k in x)
    proto = model.proto
    n_constraints = len(proto.constraints)

    return {
        "assignments": assignments,
        "solver_info": {
            "status": status_name,
            "objective": solver.objective_value if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
            "wall_time": round(wall_time, 2),
            "num_variables": n_vars,
            "num_constraints": n_constraints,
        },
        "unassigned_count": len(to_assign) - len(assignments),
    }


# ============================================================
# Stage 2: シナリオ評価 (CVaR)
# ============================================================

def evaluate_scenarios(data: dict, assignments: dict, n_scenarios: int = 100) -> dict:
    """割当結果をモンテカルロシナリオで評価。"""
    print(f"\n=== Stage 2: シナリオ評価 ({n_scenarios} シナリオ) ===")

    tickets = {t["ticket_id"]: t for t in data["tickets"]}
    estimator = ResolutionEstimator(data["history"])
    params = data["params"]

    random.seed(params["risk_evaluation"]["scenario_seed"])

    scenario_violations = []

    for s in range(n_scenarios):
        violations = 0
        for tid, assignment in assignments.items():
            ticket = tickets.get(tid)
            if not ticket:
                continue

            # 割当先の情報取得
            if isinstance(assignment, list):
                # スワーミング: lead の能力で推定
                lead = next((a for a in assignment if a["role"] == "lead"), None)
                if not lead:
                    continue
                eid = lead["engineer_id"]
                # スワーミング効率ボーナス
                team_size = len(assignment)
                bonus = params["swarming"]["efficiency_bonus"].get(
                    f"{team_size}_person", 0
                )
            else:
                eid = assignment["engineer_id"]
                bonus = 0

            primary_skill = ticket["required_skills"][0]
            mean, std, conf = estimator.estimate(eid, primary_skill, ticket["priority"])

            # 疲労補正
            eng = next((e for e in data["engineers"] if e["engineer_id"] == eid), None)
            if eng:
                fatigue_mult = 1.0 + 0.5 * eng["fatigue_level"]
                mean *= fatigue_mult
                std *= fatigue_mult

            # スワーミング効率
            mean *= (1.0 - bonus)

            # 対数正規分布からサンプリング
            if std > 0 and mean > 0:
                sigma2 = math.log(1 + (std / mean) ** 2)
                mu = math.log(mean) - sigma2 / 2
                sampled_hours = random.lognormvariate(mu, math.sqrt(sigma2))
            else:
                sampled_hours = mean

            # SLA 違反判定
            remaining = ticket["sla_remaining_hours"]
            if sampled_hours > remaining:
                violations += 1

        scenario_violations.append(violations)

    # CVaR(95%) 計算
    scenario_violations.sort(reverse=True)
    worst_5pct = scenario_violations[:max(1, n_scenarios // 20)]
    cvar_95 = statistics.mean(worst_5pct)

    mean_violations = statistics.mean(scenario_violations)
    median_violations = statistics.median(scenario_violations)
    max_violations = max(scenario_violations)
    min_violations = min(scenario_violations)

    print(f"  SLA 違反数 (全シナリオ):")
    print(f"    平均: {mean_violations:.1f}")
    print(f"    中央値: {median_violations:.0f}")
    print(f"    最小: {min_violations}")
    print(f"    最大: {max_violations}")
    print(f"    CVaR(95%): {cvar_95:.1f}")

    return {
        "n_scenarios": n_scenarios,
        "mean_violations": round(mean_violations, 1),
        "median_violations": median_violations,
        "min_violations": min_violations,
        "max_violations": max_violations,
        "cvar_95": round(cvar_95, 1),
        "violation_distribution": scenario_violations,
    }


# ============================================================
# レポート出力
# ============================================================

def print_report(data: dict, result: dict, scenario_eval: dict):
    """結果サマリーを表示。"""
    tickets = {t["ticket_id"]: t for t in data["tickets"]}
    assignments = result["assignments"]

    print(f"\n{'='*60}")
    print(f"  ticket_assignment_advanced ベースライン結果")
    print(f"{'='*60}")
    print(f"\n  ソルバー: {result['solver_info']['status']} ({result['solver_info']['wall_time']}s)")
    print(f"  変数数: {result['solver_info']['num_variables']}")
    print(f"  制約数: {result['solver_info']['num_constraints']}")
    print(f"  目的関数値: {result['solver_info']['objective']}")
    print(f"\n  割当結果:")
    print(f"    割当成功: {len(assignments)} 件")
    print(f"    未割当: {result['unassigned_count']} 件")

    # 優先度別の割当状況
    assigned_by_priority = {"P1": 0, "P2": 0, "P3": 0, "P4": 0}
    total_by_priority = {"P1": 0, "P2": 0, "P3": 0, "P4": 0}
    unassigned = [t for t in data["tickets"] if t["status"] == "unassigned"]
    for t in unassigned:
        p = t["priority"]
        total_by_priority[p] = total_by_priority.get(p, 0) + 1
        if t["ticket_id"] in assignments:
            assigned_by_priority[p] = assigned_by_priority.get(p, 0) + 1

    print(f"\n  優先度別割当率:")
    for p in ["P1", "P2", "P3", "P4"]:
        total = total_by_priority.get(p, 0)
        assigned = assigned_by_priority.get(p, 0)
        pct = f"{assigned/total*100:.0f}%" if total > 0 else "N/A"
        print(f"    {p}: {assigned}/{total} ({pct})")

    # スワーミングチケットの割当状況
    swarming_assigned = 0
    for tid, a in assignments.items():
        if isinstance(a, list):
            swarming_assigned += 1
    swarming_total = sum(1 for t in unassigned if t["max_assignees"] > 1)
    print(f"\n  スワーミング: {swarming_assigned}/{swarming_total} チーム編成")

    # CVaR
    print(f"\n  リスク評価 (CVaR):")
    print(f"    平均 SLA 違反: {scenario_eval['mean_violations']}")
    print(f"    CVaR(95%): {scenario_eval['cvar_95']} (最悪5%シナリオの平均)")
    print(f"    最悪ケース: {scenario_eval['max_violations']} 件の SLA 違反")

    # P1 チケットの割当詳細
    print(f"\n  P1 チケット割当詳細:")
    for t in unassigned:
        if t["priority"] == "P1" and t["ticket_id"] in assignments:
            a = assignments[t["ticket_id"]]
            if isinstance(a, list):
                members = ", ".join(
                    f"{m['engineer_name']}({m['engineer_tier']},{m['role']})" for m in a
                )
                print(f"    {t['ticket_id']}: {t['title'][:30]}... → [{members}]")
            else:
                print(f"    {t['ticket_id']}: {t['title'][:30]}... → {a['engineer_name']}({a['engineer_tier']})")


# ============================================================
# メイン
# ============================================================

def main():
    data = load_all()

    print(f"=== ticket_assignment_advanced baseline ===")
    print(f"  エンジニア: {len(data['engineers'])} 名"
          f" (on-shift: {sum(1 for e in data['engineers'] if e['on_shift'])})")
    print(f"  チケット: {len(data['tickets'])} 件"
          f" (unassigned: {sum(1 for t in data['tickets'] if t['status']=='unassigned')})")
    print(f"  依存関係: {len(data['dependencies'])} エッジ")
    print(f"  制約: HC {sum(1 for c in data['constraints'] if c['hard_or_soft']=='hard')}"
          f" + SC {sum(1 for c in data['constraints'] if c['hard_or_soft']=='soft')}")

    # Stage 1
    result = solve_deterministic(data, time_limit=120)

    # Stage 2
    scenario_eval = {}
    if result["assignments"]:
        scenario_eval = evaluate_scenarios(data, result["assignments"])

    # レポート
    print_report(data, result, scenario_eval)

    # JSON 出力
    output = {
        "solver_info": result["solver_info"],
        "assignment_count": len(result["assignments"]),
        "unassigned_count": result["unassigned_count"],
        "scenario_evaluation": {k: v for k, v in scenario_eval.items()
                                if k != "violation_distribution"},
        "assignments": {
            tid: a if isinstance(a, list) else [a]
            for tid, a in result["assignments"].items()
        },
    }
    out_path = DATA / "baseline_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n  結果を {out_path} に保存しました。")


if __name__ == "__main__":
    main()
