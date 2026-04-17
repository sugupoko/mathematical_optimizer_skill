"""ticket_assignment_advanced 改善スクリプト。

ベースラインからの改善策:

改善A: 優先度階層化 (Priority-Tiered Optimization)
  - P1/P2を最初に割当保証 → 残りスロットでP3/P4
  - P1スワーミングのスコアを大幅引き上げ

改善B: ロバスト目的関数 (CVaR-Aware)
  - SLA残が少ないチ��ットに指数的ペナルティ
  - 解決時間の分散が大きい組合せにペナルティ
  - 疲労×不確実性の相互作用を明示的にモデル化

改善C: 依存グラフ考慮 (Dependency-Aware)
  - root cause チケット解決で下流が解放される効果を目的関数に反映
  - blocked_dependency を先に解くインセンティブ

改善D: 全部盛り (A+B+C)

バリエーション:
  V1: SLA遵守重視
  V2: 負荷均等重視
  V3: ロバスト性重視
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

DATA = Path(__file__).resolve().parent.parent.parent / "data"
RESULTS = Path(__file__).resolve().parent.parent / "results"

# ============================================================
# データ読み込み (baseline と共通)
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
    penalties = load_csv("sla_penalties.csv")
    team = load_csv("team_constraints.csv")
    params = load_json("scenario_params.json")

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
        "engineers": engineers, "tickets": tickets,
        "dependencies": deps, "constraints": constraints,
        "history": history, "penalties": penalties,
        "team": team, "params": params,
    }


# ============================================================
# 共通ユーティリティ
# ============================================================

TIER_ORDER = {"L1": 1, "L2": 2, "L3": 3, "L4": 4}

def tier_ge(eng_tier: str, required_tier: str) -> bool:
    return TIER_ORDER.get(eng_tier, 0) >= TIER_ORDER.get(required_tier, 0)

def tier_val(tier: str) -> int:
    return TIER_ORDER.get(tier, 0)


class ResolutionEstimator:
    def __init__(self, history: list[dict]):
        self.personal: dict[tuple[str, str], list[float]] = {}
        self.category: dict[str, list[float]] = {}
        for rec in history:
            skill, eid = rec["skill"], rec["engineer_id"]
            hours = rec["resolution_hours"]
            self.personal.setdefault((eid, skill), []).append(hours)
            self.category.setdefault(skill, []).append(hours)

    def estimate(self, engineer_id: str, skill: str, priority: str
                 ) -> tuple[float, float, float]:
        key = (engineer_id, skill)
        if key in self.personal and len(self.personal[key]) >= 3:
            data = self.personal[key]
            return (statistics.mean(data),
                    statistics.stdev(data) if len(data) > 1 else 0.5,
                    min(0.9, 0.7 + 0.02 * (len(data) - 3)))
        if skill in self.category:
            data = self.category[skill]
            return (statistics.mean(data),
                    statistics.stdev(data) if len(data) > 1 else 1.0, 0.3)
        defaults = {"P1": 4.0, "P2": 8.0, "P3": 24.0, "P4": 72.0}
        return (defaults.get(priority, 24.0), 5.0, 0.1)


def compute_current_load(engineers, tickets):
    load = {e["engineer_id"]: 0 for e in engineers}
    for t in tickets:
        if t["assigned_to"] and t["status"] != "resolved":
            if t["assigned_to"] in load:
                load[t["assigned_to"]] += 1
    return load


def get_forbidden_pairs(team):
    pairs = set()
    for tc in team:
        if tc["type"] == "forbidden_pair" and tc["engineer_1"] and tc["engineer_2"]:
            pairs.add((tc["engineer_1"], tc["engineer_2"]))
            pairs.add((tc["engineer_2"], tc["engineer_1"]))
    return pairs


def get_blocked_by_deps(tickets, deps):
    blocked = set()
    for d in deps:
        if d["dependency_type"] in ("blocks", "sequence"):
            blocker = next((t for t in tickets if t["ticket_id"] == d["blocker_ticket_id"]), None)
            if blocker and blocker["status"] != "resolved":
                blocked.add(d["blocked_ticket_id"])
    return blocked


def compute_dependency_bonus(ticket_id, deps, tickets):
    """root cause チケットを解くことで解放される下流チケット数。"""
    downstream = sum(1 for d in deps
                     if d["blocker_ticket_id"] == ticket_id
                     and d["dependency_type"] in ("blocks", "sequence"))
    # 下流チケットの優先度も考���
    bonus = 0
    for d in deps:
        if d["blocker_ticket_id"] == ticket_id:
            blocked_t = next((t for t in tickets if t["ticket_id"] == d["blocked_ticket_id"]), None)
            if blocked_t:
                p_bonus = {"P1": 200, "P2": 100, "P3": 30, "P4": 10}.get(blocked_t["priority"], 10)
                bonus += p_bonus
    return bonus


# ============================================================
# 改善版ソルバー
# ============================================================

def solve_improved(
    data: dict,
    strategy: str = "all",  # "priority_tiered", "robust", "dependency", "all"
    variant: str = "balanced",  # "sla_focus", "load_balance", "robust"
    time_limit: int = 120,
) -> dict:
    """改善版 CP-SAT ソルバー。"""

    engineers = [e for e in data["engineers"] if e["on_shift"]]
    tickets = data["tickets"]
    penalties = data["penalties"]
    team = data["team"]
    deps = data["dependencies"]
    estimator = ResolutionEstimator(data["history"])

    to_assign = [t for t in tickets if t["status"] == "unassigned"]
    blocked_by_dep = get_blocked_by_deps(tickets, deps)
    to_assign = [t for t in to_assign if t["ticket_id"] not in blocked_by_dep]

    current_load = compute_current_load(engineers, tickets)
    forbidden_pairs = get_forbidden_pairs(team)

    n_eng = len(engineers)

    # 改善A: P1/P2 を先にソート → スコア大幅引き上げ
    priority_weight = {"P1": 50, "P2": 20, "P3": 5, "P4": 1}

    # バリエーション別の SC 重み
    variant_weights = {
        "balanced":     {"sla": 100, "skill": 70, "load": 50, "robust": 60, "dep": 40, "tier": 30, "fatigue": 20, "mentor": 15},
        "sla_focus":    {"sla": 200, "skill": 50, "load": 20, "robust": 80, "dep": 60, "tier": 10, "fatigue": 10, "mentor": 5},
        "load_balance": {"sla": 60,  "skill": 40, "load": 150, "robust": 30, "dep": 30, "tier": 20, "fatigue": 40, "mentor": 20},
        "robust":       {"sla": 80,  "skill": 50, "load": 40, "robust": 200, "dep": 40, "tier": 20, "fatigue": 30, "mentor": 10},
    }
    w = variant_weights.get(variant, variant_weights["balanced"])

    print(f"\n  Strategy: {strategy}, Variant: {variant}")
    print(f"  Weights: {w}")

    model = cp_model.CpModel()

    # --- 変数 ---
    x = {}
    swarming_tickets = []
    single_tickets = []

    for t_idx, ticket in enumerate(to_assign):
        if ticket["max_assignees"] > 1:
            swarming_tickets.append((t_idx, ticket))
            roles = ticket["swarming_roles"].split(",")
            for r_idx in range(len(roles)):
                for e_idx in range(n_eng):
                    x[t_idx, e_idx, r_idx] = model.new_bool_var(f"x_{t_idx}_{e_idx}_{r_idx}")
        else:
            single_tickets.append((t_idx, ticket))
            for e_idx in range(n_eng):
                x[t_idx, e_idx, 0] = model.new_bool_var(f"x_{t_idx}_{e_idx}")

    # ---- ハード制約 ----

    # HC01: スキルマッチ (単一)
    for t_idx, ticket in single_tickets:
        for e_idx, eng in enumerate(engineers):
            if not all(s in eng["skills"] for s in ticket["required_skills"]):
                model.add(x[t_idx, e_idx, 0] == 0)

    # HC02: ティア要件 (単一)
    for t_idx, ticket in single_tickets:
        for e_idx, eng in enumerate(engineers):
            if not tier_ge(eng["tier"], ticket["min_tier"]):
                model.add(x[t_idx, e_idx, 0] == 0)

    # HC02/HC05: ティア要件 (スワーミング)
    for t_idx, ticket in swarming_tickets:
        roles = ticket["swarming_roles"].split(",")
        for r_idx, role in enumerate(roles):
            for e_idx, eng in enumerate(engineers):
                if role == "lead" and not tier_ge(eng["tier"], ticket["min_tier"]):
                    model.add(x[t_idx, e_idx, r_idx] == 0)
                elif role == "support":
                    min_support = max(1, tier_val(ticket["min_tier"]) - 1)
                    if tier_val(eng["tier"]) < min_support:
                        model.add(x[t_idx, e_idx, r_idx] == 0)

    # HC05/HC06: スワーミングロール
    for t_idx, ticket in swarming_tickets:
        roles = ticket["swarming_roles"].split(",")
        lead_vars = [x[t_idx, e_idx, 0] for e_idx in range(n_eng)]
        for r_idx in range(len(roles)):
            role_vars = [x[t_idx, e_idx, r_idx] for e_idx in range(n_eng)]
            model.add(sum(role_vars) <= 1)
        for r_idx in range(1, len(roles)):
            role_vars = [x[t_idx, e_idx, r_idx] for e_idx in range(n_eng)]
            model.add(sum(role_vars) <= sum(lead_vars))
        for e_idx in range(n_eng):
            person_roles = [x[t_idx, e_idx, r_idx] for r_idx in range(len(roles))]
            model.add(sum(person_roles) <= 1)

    # HC11: マルチスキルカバレッジ (スワーミング)
    for t_idx, ticket in swarming_tickets:
        roles = ticket["swarming_roles"].split(",")
        lead_assigned = model.new_bool_var(f"lead_{t_idx}")
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
                model.add(sum(capable) >= 1).only_enforce_if(lead_assigned)

    # 単一チケット: 最大1人
    for t_idx, ticket in single_tickets:
        model.add(sum(x[t_idx, e_idx, 0] for e_idx in range(n_eng)) <= 1)

    # HC04: 容量制約 (改善: 疲労をより細かく反映)
    for e_idx, eng in enumerate(engineers):
        # 改善B: 疲労度に応じた連続的な容量削減 (0.6超で1スロット、0.8超で2スロット)
        if strategy in ("robust", "all"):
            fatigue_penalty = 0
            if eng["fatigue_level"] > 0.8:
                fatigue_penalty = 2
            elif eng["fatigue_level"] > 0.6:
                fatigue_penalty = 1
        else:
            fatigue_penalty = 1 if eng["fatigue_level"] > 0.6 else 0

        effective_cap = max(0, eng["max_concurrent"] - current_load.get(eng["engineer_id"], 0) - fatigue_penalty)
        all_vars = []
        for t_idx, ticket in single_tickets:
            all_vars.append(x[t_idx, e_idx, 0])
        for t_idx, ticket in swarming_tickets:
            roles = ticket["swarming_roles"].split(",")
            for r_idx in range(len(roles)):
                all_vars.append(x[t_idx, e_idx, r_idx])
        model.add(sum(all_vars) <= effective_cap)

    # HC09: 禁止ペア
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

    # HC10: L4 は P1 or P2+VIP
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

    # HC12: スワーミング同時参加上限
    for e_idx in range(n_eng):
        participations = []
        for t_idx, ticket in swarming_tickets:
            roles = ticket["swarming_roles"].split(",")
            p = model.new_bool_var(f"swpart_{t_idx}_{e_idx}")
            role_vars = [x[t_idx, e_idx, r_idx] for r_idx in range(len(roles))]
            model.add(sum(role_vars) >= 1).only_enforce_if(p)
            model.add(sum(role_vars) == 0).only_enforce_if(p.Not())
            participations.append(p)
        if participations:
            model.add(sum(participations) <= 2)

    # ---- 改善A: P1/P2 割当保証制約 ----
    if strategy in ("priority_tiered", "all"):
        # P1 は割当可能なら必ず割当（単一チケット）
        for t_idx, ticket in single_tickets:
            if ticket["priority"] == "P1":
                eligible = [e_idx for e_idx, eng in enumerate(engineers)
                           if all(s in eng["skills"] for s in ticket["required_skills"])
                           and tier_ge(eng["tier"], ticket["min_tier"])]
                if eligible:
                    model.add(sum(x[t_idx, e_idx, 0] for e_idx in eligible) >= 1)

    # ---- 目的関数 ----
    objective_terms = []

    for t_idx, ticket in single_tickets:
        p_weight = priority_weight[ticket["priority"]]

        # SC01: SLA ペナルティ (改善B: 指数的ペナルティ)
        sla_rem = ticket["sla_remaining_hours"]
        if strategy in ("robust", "all"):
            # 指数的: SLA残が短いほど急激に増加
            if sla_rem <= 0.5:
                sla_score = 500
            elif sla_rem <= 2.0:
                sla_score = int(200 * (2.0 / max(0.1, sla_rem)))
            elif sla_rem <= 8.0:
                sla_score = int(100 * (8.0 / max(0.1, sla_rem)))
            else:
                sla_score = 10
        else:
            sla_score = max(10, int(100 / max(0.1, sla_rem)))

        if ticket["vip_customer"]:
            sla_score = int(sla_score * 1.5)

        # 改善C: 依存グラフボーナス
        dep_bonus = 0
        if strategy in ("dependency", "all"):
            dep_bonus = compute_dependency_bonus(ticket["ticket_id"], deps, tickets)

        for e_idx, eng in enumerate(engineers):
            score = 0

            # SC01: SLA
            score += int(sla_score * p_weight * w["sla"] / 100)

            # SC02: スキル適性
            mean, std, conf = estimator.estimate(
                eng["engineer_id"], ticket["required_skills"][0], ticket["priority"]
            )
            speed_bonus = max(0, int((1.0 / max(0.1, mean)) * 50 * conf))
            score += int(speed_bonus * w["skill"] / 100)

            # SC03: 負荷均等
            cur = current_load.get(eng["engineer_id"], 0)
            load_bonus = max(0, 20 - cur * 4)
            score += int(load_bonus * w["load"] / 100)

            # SC05: ティア効率
            tier_diff = tier_val(eng["tier"]) - tier_val(ticket["min_tier"])
            tier_penalty = tier_diff * 10
            score -= int(tier_penalty * w["tier"] / 100)

            # SC06: ロバスト性 (改善B)
            if strategy in ("robust", "all"):
                # 低分散エンジニアにボーナス + 疲労による分散増をペナルティ
                fatigue_mult = 1.0 + 0.5 * eng["fatigue_level"]
                effective_std = std * fatigue_mult
                robustness = max(0, int((1.0 / max(0.1, effective_std)) * 40))
                score += int(robustness * w["robust"] / 100)
            else:
                robustness = max(0, int((1.0 / max(0.1, std)) * 30))
                score += int(robustness * w["robust"] / 100)

            # SC10: 疲労回避
            if eng["fatigue_level"] > 0.6:
                score -= int(30 * w["fatigue"] / 100)

            # 改善C: 依存ボーナス
            score += int(dep_bonus * w["dep"] / 100)

            score = max(0, score)
            objective_terms.append(x[t_idx, e_idx, 0] * score)

    # スワーミングチケット
    for t_idx, ticket in swarming_tickets:
        p_weight = priority_weight[ticket["priority"]]
        sla_rem = ticket["sla_remaining_hours"]

        if strategy in ("robust", "all"):
            if sla_rem <= 0.5:
                sla_score = 500
            elif sla_rem <= 2.0:
                sla_score = int(200 * (2.0 / max(0.1, sla_rem)))
            elif sla_rem <= 8.0:
                sla_score = int(100 * (8.0 / max(0.1, sla_rem)))
            else:
                sla_score = 10
        else:
            sla_score = max(10, int(100 / max(0.1, sla_rem)))

        if ticket["vip_customer"]:
            sla_score = int(sla_score * 1.5)

        dep_bonus = 0
        if strategy in ("dependency", "all"):
            dep_bonus = compute_dependency_bonus(ticket["ticket_id"], deps, tickets)

        roles = ticket["swarming_roles"].split(",")
        for r_idx, role in enumerate(roles):
            role_w = {"lead": 1.0, "support": 0.6, "observer": 0.2}.get(role, 0.5)
            for e_idx, eng in enumerate(engineers):
                score = int(sla_score * p_weight * role_w * w["sla"] / 100)

                if role == "lead":
                    primary_skill = ticket["required_skills"][0]
                    mean, std, conf = estimator.estimate(
                        eng["engineer_id"], primary_skill, ticket["priority"]
                    )
                    score += int(max(0, (1.0 / max(0.1, mean)) * 40 * conf) * w["skill"] / 100)

                    if strategy in ("robust", "all"):
                        fatigue_mult = 1.0 + 0.5 * eng["fatigue_level"]
                        effective_std = std * fatigue_mult
                        score += int(max(0, (1.0 / max(0.1, effective_std)) * 30) * w["robust"] / 100)

                # SC07: メンタリング
                if role == "observer" and eng["tier"] == "L1":
                    score += int(15 * w["mentor"] / 100)

                if eng["fatigue_level"] > 0.6:
                    score -= int(20 * w["fatigue"] / 100)

                score += int(dep_bonus * role_w * w["dep"] / 100)
                score = max(0, score)
                objective_terms.append(x[t_idx, e_idx, r_idx] * score)

    model.maximize(sum(objective_terms))

    # ---- 求解 ----
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 8

    start = time.time()
    status = solver.solve(model)
    wall = time.time() - start

    status_name = {
        cp_model.OPTIMAL: "OPTIMAL", cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE", cp_model.UNKNOWN: "UNKNOWN",
    }.get(status, "UNKNOWN")

    # ---- 結果抽出 ----
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

    n_vars = sum(1 for _ in x)
    return {
        "strategy": strategy, "variant": variant,
        "assignments": assignments,
        "solver_info": {
            "status": status_name,
            "objective": solver.objective_value if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
            "wall_time": round(wall, 2),
            "num_variables": n_vars,
            "num_constraints": len(model.proto.constraints),
        },
        "assigned_count": len(assignments),
        "unassigned_count": len(to_assign) - len(assignments),
    }


# ============================================================
# シナリオ評価
# ============================================================

def evaluate_scenarios(data, assignments, n_scenarios=100):
    tickets = {t["ticket_id"]: t for t in data["tickets"]}
    estimator = ResolutionEstimator(data["history"])
    params = data["params"]
    random.seed(42)

    scenario_violations = []
    for _ in range(n_scenarios):
        violations = 0
        for tid, assignment in assignments.items():
            ticket = tickets.get(tid)
            if not ticket:
                continue
            if isinstance(assignment, list):
                lead = next((a for a in assignment if a["role"] == "lead"), None)
                if not lead:
                    continue
                eid = lead["engineer_id"]
                bonus = params["swarming"]["efficiency_bonus"].get(
                    f"{len(assignment)}_person", 0)
            else:
                eid = assignment["engineer_id"]
                bonus = 0

            primary_skill = ticket["required_skills"][0]
            mean, std, _ = estimator.estimate(eid, primary_skill, ticket["priority"])
            eng = next((e for e in data["engineers"] if e["engineer_id"] == eid), None)
            if eng:
                fatigue_mult = 1.0 + 0.5 * eng["fatigue_level"]
                mean *= fatigue_mult
                std *= fatigue_mult
            mean *= (1.0 - bonus)

            if std > 0 and mean > 0:
                sigma2 = math.log(1 + (std / mean) ** 2)
                mu = math.log(mean) - sigma2 / 2
                sampled = random.lognormvariate(mu, math.sqrt(sigma2))
            else:
                sampled = mean

            if sampled > ticket["sla_remaining_hours"]:
                violations += 1
        scenario_violations.append(violations)

    scenario_violations.sort(reverse=True)
    worst_5pct = scenario_violations[:max(1, n_scenarios // 20)]
    return {
        "mean_violations": round(statistics.mean(scenario_violations), 1),
        "median_violations": statistics.median(scenario_violations),
        "min_violations": min(scenario_violations),
        "max_violations": max(scenario_violations),
        "cvar_95": round(statistics.mean(worst_5pct), 1),
    }


# ============================================================
# HC 独立検証器
# ============================================================

def verify_hard_constraints(data, assignments):
    """独立 HC 検証。ソルバーの FEASIBLE を信用し���い。"""
    engineers = {e["engineer_id"]: e for e in data["engineers"]}
    tickets = {t["ticket_id"]: t for t in data["tickets"]}
    violations = {}

    for tid, assignment in assignments.items():
        ticket = tickets.get(tid)
        if not ticket:
            continue
        members = assignment if isinstance(assignment, list) else [assignment]

        for m in members:
            eng = engineers.get(m["engineer_id"])
            if not eng:
                violations.setdefault("HC_UNKNOWN_ENG", []).append(tid)
                continue

            # HC01/HC11: スキルカバレッジ
            all_skills = set()
            for mm in members:
                e = engineers.get(mm["engineer_id"])
                if e:
                    all_skills.update(e["skills"])
            for s in ticket["required_skills"]:
                if s not in all_skills:
                    violations.setdefault("HC01/11_SKILL", []).append(f"{tid}:{s}")

            # HC02: ティア
            if m["role"] == "lead" and not tier_ge(eng["tier"], ticket["min_tier"]):
                violations.setdefault("HC02_TIER", []).append(f"{tid}:{m['engineer_id']}")

            # HC03: シフト
            if not eng["on_shift"]:
                violations.setdefault("HC03_SHIFT", []).append(f"{tid}:{m['engineer_id']}")

            # HC10: L4 制限
            if eng["tier"] == "L4":
                ok = (ticket["priority"] == "P1" or
                      (ticket["priority"] == "P2" and ticket["vip_customer"]))
                if not ok:
                    violations.setdefault("HC10_L4", []).append(f"{tid}:{m['engineer_id']}")

    total = sum(len(v) for v in violations.values())
    return {
        "all_satisfied": total == 0,
        "total_violations": total,
        "by_constraint": {k: len(v) for k, v in violations.items()},
        "details": violations,
    }


# ============================================================
# メイン
# ============================================================

def main():
    data = load_all()
    RESULTS.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("  ticket_assignment_advanced 改善実行")
    print("=" * 60)

    # ベースライン再掲
    baseline = load_json("baseline_results.json")
    print(f"\n  ベースライン: {baseline['assignment_count']} 割当, "
          f"CVaR={baseline['scenario_evaluation']['cvar_95']}")

    all_results = {"baseline": baseline}

    # --- 改善策の実行 ---
    strategies = [
        ("priority_tiered", "balanced", "改善A: 優先度階層化"),
        ("robust", "balanced", "改善B: ロバスト目的関数"),
        ("dependency", "balanced", "改善C: 依存グラフ考慮"),
        ("all", "balanced", "改善D: 全部盛り (A+B+C)"),
    ]

    for strategy, variant, label in strategies:
        print(f"\n{'='*40}")
        print(f"  {label}")
        print(f"{'='*40}")

        result = solve_improved(data, strategy=strategy, variant=variant)
        print(f"  Status: {result['solver_info']['status']}")
        print(f"  Assigned: {result['assigned_count']}")
        print(f"  Unassigned: {result['unassigned_count']}")

        # HC 検証
        hc_check = verify_hard_constraints(data, result["assignments"])
        result["hc_verification"] = hc_check
        print(f"  HC all satisfied: {hc_check['all_satisfied']}")
        if not hc_check["all_satisfied"]:
            print(f"    Violations: {hc_check['by_constraint']}")

        # シナリオ評価
        if result["assignments"]:
            scenario = evaluate_scenarios(data, result["assignments"])
            result["scenario_evaluation"] = scenario
            print(f"  CVaR(95%): {scenario['cvar_95']}")
            print(f"  Mean violations: {scenario['mean_violations']}")

        # 優先度別
        assigned_ids = set(result["assignments"].keys())
        unassigned = [t for t in data["tickets"] if t["status"] == "unassigned"]
        for p in ["P1", "P2"]:
            total = sum(1 for t in unassigned if t["priority"] == p)
            done = sum(1 for t in unassigned if t["priority"] == p and t["ticket_id"] in assigned_ids)
            print(f"  {p}: {done}/{total}")

        all_results[f"{strategy}_{variant}"] = result

    # --- バリエーション比較 ---
    print(f"\n{'='*60}")
    print("  バリエーション比較 (strategy=all)")
    print(f"{'='*60}")

    variants = [
        ("sla_focus", "V1: SLA遵守重視"),
        ("load_balance", "V2: ���荷均等重視"),
        ("robust", "V3: ロバスト性重視"),
    ]

    for variant, label in variants:
        print(f"\n  --- {label} ---")
        result = solve_improved(data, strategy="all", variant=variant)
        hc_check = verify_hard_constraints(data, result["assignments"])
        result["hc_verification"] = hc_check
        scenario = evaluate_scenarios(data, result["assignments"]) if result["assignments"] else {}
        result["scenario_evaluation"] = scenario
        print(f"  Status: {result['solver_info']['status']}")
        print(f"  Assigned: {result['assigned_count']}, CVaR: {scenario.get('cvar_95', 'N/A')}")
        all_results[f"all_{variant}"] = result

    # --- 結果保存 ---
    # JSON用に assignments を整理
    output = {}
    for key, res in all_results.items():
        if key == "baseline":
            output[key] = res
            continue
        output[key] = {
            "strategy": res.get("strategy"),
            "variant": res.get("variant"),
            "solver_info": res["solver_info"],
            "assigned_count": res.get("assigned_count", res.get("assignment_count")),
            "unassigned_count": res.get("unassigned_count"),
            "hc_verification": res.get("hc_verification"),
            "scenario_evaluation": res.get("scenario_evaluation"),
        }

    with open(RESULTS / "improve_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n  結果を {RESULTS / 'improve_results.json'} に保存しました。")


if __name__ == "__main__":
    main()
