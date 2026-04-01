#!/usr/bin/env python3
"""
Ticket Assignment Optimization — Full Workflow
==============================================
Data → Analysis → LLM Estimator → Stagnation Detection → 3 Baselines → 3 Improvements → Evaluation
"""

import csv
import json
import math
import os
import sys
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

# OR-Tools
from ortools.sat.python import cp_model

# ──────────────────────────────────────────────
# 0. Constants & Paths
# ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

NOW = datetime(2026, 4, 1, 14, 0)  # current time for stagnation

TIER_ORDER = {"L1": 1, "L2": 2, "L3": 3}

# Tier → allowed ticket types
TIER_ALLOWED_TYPES = {
    "L1": {"service_request", "incident_low"},
    "L2": {"service_request", "incident_low", "incident_mid", "change_standard"},
    "L3": {"service_request", "incident_low", "incident_mid", "change_standard",
            "incident_high", "incident_critical", "change_emergency"},
}

PRIORITY_ORDER = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}


# ──────────────────────────────────────────────
# 1. Data Loading
# ──────────────────────────────────────────────
def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_data():
    engineers = load_csv(DATA_DIR / "engineers.csv")
    tickets = load_csv(DATA_DIR / "tickets.csv")
    history = load_csv(DATA_DIR / "resolution_history.csv")
    constraints = load_csv(DATA_DIR / "constraints.csv")

    # Parse engineers
    for e in engineers:
        e["skills"] = set(e["skills"].split(","))
        e["max_concurrent"] = int(e["max_concurrent"])
        e["experience_years"] = int(e["experience_years"])
        e["on_shift"] = e["on_shift"].strip() == "True"

    # Parse tickets
    for t in tickets:
        t["sla_remaining_hours"] = float(t["sla_remaining_hours"])
        t["progress_pct"] = int(t["progress_pct"])
        t["estimated_remaining_hours"] = float(t["estimated_remaining_hours"])
        t["sla_deadline"] = datetime.strptime(t["sla_deadline"], "%Y-%m-%d %H:%M")
        t["created_at"] = datetime.strptime(t["created_at"], "%Y-%m-%d %H:%M")
        t["assigned_to"] = t["assigned_to"].strip() if t["assigned_to"].strip() else None

    # Parse history
    for h in history:
        h["resolution_hours"] = float(h["resolution_hours"])

    return engineers, tickets, history, constraints


# ──────────────────────────────────────────────
# 2. LLM Estimator (resolution time prediction)
# ──────────────────────────────────────────────
def build_llm_estimator(history):
    """
    Fallback chain:
      1) personal avg for (engineer, skill)
      2) category avg for skill
      3) global default (2.0h)
    """
    personal = defaultdict(list)
    category = defaultdict(list)
    for h in history:
        personal[(h["engineer_id"], h["skill"])].append(h["resolution_hours"])
        category[h["skill"]].append(h["resolution_hours"])

    personal_avg = {k: sum(v) / len(v) for k, v in personal.items()}
    category_avg = {k: sum(v) / len(v) for k, v in category.items()}
    global_avg = 2.0

    def estimate(engineer_id, skill):
        key = (engineer_id, skill)
        if key in personal_avg:
            return personal_avg[key], "personal"
        if skill in category_avg:
            return category_avg[skill], "category"
        return global_avg, "default"

    return estimate, personal_avg, category_avg


# ──────────────────────────────────────────────
# 3. Stagnation Detection
# ──────────────────────────────────────────────
def detect_stagnation(tickets):
    """
    For in_progress tickets: compare expected progress based on elapsed time
    vs actual progress_pct.  blocked_* = external, NOT stagnation.
    Stagnant if: progress < 50% of expected AND ticket open > 6 hours.
    """
    stagnant = []
    for t in tickets:
        if t["status"].startswith("blocked"):
            continue
        if t["status"] != "in_progress":
            continue
        if t["assigned_to"] is None:
            continue

        elapsed = (NOW - t["created_at"]).total_seconds() / 3600.0
        total_est = elapsed + t["estimated_remaining_hours"]
        if total_est <= 0:
            continue
        expected_pct = min(100, (elapsed / total_est) * 100)
        actual_pct = t["progress_pct"]

        if elapsed > 6 and actual_pct < expected_pct * 0.5:
            stagnant.append({
                "ticket_id": t["ticket_id"],
                "assigned_to": t["assigned_to"],
                "progress_pct": actual_pct,
                "expected_pct": round(expected_pct, 1),
                "elapsed_hours": round(elapsed, 1),
            })
    return stagnant


# ──────────────────────────────────────────────
# 4. Engineer Availability & State
# ──────────────────────────────────────────────
def build_engineer_state(engineers, tickets, release_blocked=False):
    """
    Compute current load per engineer.
    If release_blocked=True, blocked tickets don't count toward load.
    on_shift engineers are available.
    L3 off-shift engineers available for P1 (on_call).
    """
    # Count current assigned tickets per engineer
    load = defaultdict(int)
    for t in tickets:
        if t["assigned_to"] is None:
            continue
        if t["status"] == "unassigned":
            continue
        if release_blocked and t["status"].startswith("blocked"):
            continue
        load[t["assigned_to"]] += 1

    eng_map = {}
    for e in engineers:
        eid = e["engineer_id"]
        current = load.get(eid, 0)
        available_slots = max(0, e["max_concurrent"] - current)
        eng_map[eid] = {
            **e,
            "current_load": current,
            "available_slots": available_slots,
        }
    return eng_map


def is_available(eng, ticket, eng_state):
    """Check hard constraints for assignment."""
    e = eng_state[eng["engineer_id"]]
    # HC4: capacity
    if e["available_slots"] <= 0:
        return False
    # HC1: skill match
    if ticket["required_skill"] not in eng["skills"]:
        return False
    # HC2: tier
    if TIER_ORDER[eng["tier"]] < TIER_ORDER[ticket["min_tier"]]:
        return False
    # Tier type constraint
    ttype = ticket["type"]
    if ttype not in TIER_ALLOWED_TYPES[eng["tier"]]:
        return False
    # HC3: shift — on_shift OR (L3 off-shift for P1 on_call)
    if not eng["on_shift"]:
        if eng["tier"] == "L3" and ticket["priority"] == "P1":
            pass  # on_call
        else:
            return False
    return True


# ──────────────────────────────────────────────
# 5. Scoring Function
# ──────────────────────────────────────────────
def compute_score(eng, ticket, estimator, eng_state):
    """
    Score = skill_match(30) + sla_urgency(30) + experience(15) + tier_fit(10) + llm_confidence(5)
    Total max = 90 (not 100, as these are the components)
    """
    score = 0.0

    # Skill match (30): does engineer have the required skill?
    if ticket["required_skill"] in eng["skills"]:
        score += 30.0

    # SLA urgency (30): lower remaining hours → higher score
    sla_h = ticket["sla_remaining_hours"]
    if sla_h <= 2:
        score += 30.0
    elif sla_h <= 6:
        score += 25.0
    elif sla_h <= 12:
        score += 20.0
    elif sla_h <= 24:
        score += 15.0
    elif sla_h <= 48:
        score += 10.0
    else:
        score += 5.0

    # Experience (15): more years → higher score (cap at 15 years)
    exp = min(eng["experience_years"], 15)
    score += (exp / 15.0) * 15.0

    # Tier fit (10): prefer lowest sufficient tier
    eng_tier = TIER_ORDER[eng["tier"]]
    min_tier = TIER_ORDER[ticket["min_tier"]]
    if eng_tier == min_tier:
        score += 10.0
    elif eng_tier == min_tier + 1:
        score += 5.0
    else:
        score += 2.0

    # LLM confidence (5): based on estimator source
    est_time, source = estimator(eng["engineer_id"], ticket["required_skill"])
    if source == "personal":
        score += 5.0
    elif source == "category":
        score += 3.0
    else:
        score += 1.0

    return score


# ──────────────────────────────────────────────
# 6. Baselines
# ──────────────────────────────────────────────
def get_unassigned_tickets(tickets):
    return [t for t in tickets if t["status"] == "unassigned"]


def baseline_round_robin(engineers, tickets, estimator):
    """Simple round-robin assignment."""
    unassigned = sorted(get_unassigned_tickets(tickets),
                        key=lambda t: PRIORITY_ORDER[t["priority"]])
    eng_state = build_engineer_state(engineers, tickets, release_blocked=False)

    # Available engineers sorted by id
    avail_engs = [e for e in engineers if e["on_shift"] or
                  (e["tier"] == "L3")]  # L3 on_call for P1

    assignments = []
    eng_idx = 0
    for t in unassigned:
        assigned = False
        for _ in range(len(avail_engs)):
            e = avail_engs[eng_idx % len(avail_engs)]
            eng_idx += 1
            if is_available(e, t, eng_state):
                score = compute_score(e, t, estimator, eng_state)
                assignments.append({
                    "ticket_id": t["ticket_id"],
                    "engineer_id": e["engineer_id"],
                    "score": round(score, 2),
                    "skill_match": t["required_skill"] in e["skills"],
                })
                eng_state[e["engineer_id"]]["available_slots"] -= 1
                assigned = True
                break
        if not assigned:
            assignments.append({
                "ticket_id": t["ticket_id"],
                "engineer_id": None,
                "score": 0,
                "skill_match": False,
            })
    return assignments


def baseline_greedy(engineers, tickets, estimator):
    """Greedy: sort tickets by SLA urgency × priority, assign best scoring engineer."""
    unassigned = sorted(get_unassigned_tickets(tickets),
                        key=lambda t: (PRIORITY_ORDER[t["priority"]],
                                       t["sla_remaining_hours"]))
    eng_state = build_engineer_state(engineers, tickets, release_blocked=False)

    assignments = []
    for t in unassigned:
        best_eng = None
        best_score = -1
        for e in engineers:
            if is_available(e, t, eng_state):
                s = compute_score(e, t, estimator, eng_state)
                if s > best_score:
                    best_score = s
                    best_eng = e
        if best_eng:
            assignments.append({
                "ticket_id": t["ticket_id"],
                "engineer_id": best_eng["engineer_id"],
                "score": round(best_score, 2),
                "skill_match": t["required_skill"] in best_eng["skills"],
            })
            eng_state[best_eng["engineer_id"]]["available_slots"] -= 1
        else:
            assignments.append({
                "ticket_id": t["ticket_id"],
                "engineer_id": None,
                "score": 0,
                "skill_match": False,
            })
    return assignments


def baseline_cpsat(engineers, tickets, estimator):
    """CP-SAT optimal assignment."""
    unassigned = get_unassigned_tickets(tickets)
    eng_state = build_engineer_state(engineers, tickets, release_blocked=False)
    return _solve_cpsat(engineers, unassigned, eng_state, estimator)


def _solve_cpsat(engineers, unassigned_tickets, eng_state, estimator,
                 extra_slots=None, reassign_tickets=None):
    """
    Core CP-SAT solver.
    extra_slots: dict of engineer_id -> additional slots (from released blocked)
    reassign_tickets: list of tickets to reassign (from stagnation detection)
    """
    if extra_slots is None:
        extra_slots = {}

    all_tickets = list(unassigned_tickets)
    if reassign_tickets:
        all_tickets.extend(reassign_tickets)

    if not all_tickets:
        return []

    model = cp_model.CpModel()

    # Decision variables: x[t_idx, e_idx] = 1 if ticket t assigned to engineer e
    x = {}
    scores = {}
    for ti, t in enumerate(all_tickets):
        for ei, e in enumerate(engineers):
            eid = e["engineer_id"]
            es = eng_state[eid]
            slots = es["available_slots"] + extra_slots.get(eid, 0)
            if slots <= 0:
                continue
            if t["required_skill"] not in e["skills"]:
                continue
            if TIER_ORDER[e["tier"]] < TIER_ORDER[t["min_tier"]]:
                continue
            if t["type"] not in TIER_ALLOWED_TYPES[e["tier"]]:
                continue
            if not e["on_shift"]:
                if not (e["tier"] == "L3" and t["priority"] == "P1"):
                    continue

            x[ti, ei] = model.NewBoolVar(f"x_{ti}_{ei}")
            scores[ti, ei] = int(compute_score(e, t, estimator, eng_state) * 100)

    # Each ticket assigned to at most 1 engineer
    for ti in range(len(all_tickets)):
        vars_for_ticket = [x[ti, ei] for ei in range(len(engineers))
                           if (ti, ei) in x]
        if vars_for_ticket:
            model.Add(sum(vars_for_ticket) <= 1)

    # Capacity constraint per engineer
    for ei, e in enumerate(engineers):
        eid = e["engineer_id"]
        es = eng_state[eid]
        slots = es["available_slots"] + extra_slots.get(eid, 0)
        vars_for_eng = [x[ti, ei] for ti in range(len(all_tickets))
                        if (ti, ei) in x]
        if vars_for_eng:
            model.Add(sum(vars_for_eng) <= slots)

    # Objective: maximize total score + bonus for P1/P2 assignment
    obj_terms = []
    for (ti, ei), var in x.items():
        t = all_tickets[ti]
        priority_bonus = {
            "P1": 5000, "P2": 3000, "P3": 1000, "P4": 0
        }.get(t["priority"], 0)
        obj_terms.append((scores[ti, ei] + priority_bonus) * var)

    # Load balance: minimize max load (soft)
    if obj_terms:
        model.Maximize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 30
    status = solver.Solve(model)

    assignments = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for ti, t in enumerate(all_tickets):
            assigned_eng = None
            best_score = 0
            for ei, e in enumerate(engineers):
                if (ti, ei) in x and solver.Value(x[ti, ei]) == 1:
                    assigned_eng = e
                    best_score = scores[ti, ei] / 100.0
                    break
            assignments.append({
                "ticket_id": t["ticket_id"],
                "engineer_id": assigned_eng["engineer_id"] if assigned_eng else None,
                "score": round(best_score, 2),
                "skill_match": (t["required_skill"] in assigned_eng["skills"])
                               if assigned_eng else False,
            })
    else:
        for t in all_tickets:
            assignments.append({
                "ticket_id": t["ticket_id"],
                "engineer_id": None,
                "score": 0,
                "skill_match": False,
            })

    return assignments


# ──────────────────────────────────────────────
# 7. Improvements
# ──────────────────────────────────────────────
def improvement_a_release_blocked(engineers, tickets, estimator):
    """Release blocked ticket slots → more capacity for new assignments."""
    unassigned = get_unassigned_tickets(tickets)
    eng_state = build_engineer_state(engineers, tickets, release_blocked=True)
    return _solve_cpsat(engineers, unassigned, eng_state, estimator)


def improvement_b_reassign_stagnant(engineers, tickets, estimator):
    """Detect stagnant tickets and reassign them."""
    stagnant_info = detect_stagnation(tickets)
    stagnant_ids = {s["ticket_id"] for s in stagnant_info}

    unassigned = get_unassigned_tickets(tickets)
    stagnant_tickets = [t for t in tickets if t["ticket_id"] in stagnant_ids]

    eng_state = build_engineer_state(engineers, tickets, release_blocked=False)

    # Free up slots from stagnant tickets
    extra_slots = defaultdict(int)
    for t in stagnant_tickets:
        if t["assigned_to"]:
            extra_slots[t["assigned_to"]] += 1

    return _solve_cpsat(engineers, unassigned, eng_state, estimator,
                        extra_slots=dict(extra_slots),
                        reassign_tickets=stagnant_tickets), stagnant_info


def improvement_c_combined(engineers, tickets, estimator):
    """A + B combined: release blocked slots AND reassign stagnant."""
    stagnant_info = detect_stagnation(tickets)
    stagnant_ids = {s["ticket_id"] for s in stagnant_info}

    unassigned = get_unassigned_tickets(tickets)
    stagnant_tickets = [t for t in tickets if t["ticket_id"] in stagnant_ids]

    eng_state = build_engineer_state(engineers, tickets, release_blocked=True)

    # Free up slots from stagnant tickets
    extra_slots = defaultdict(int)
    for t in stagnant_tickets:
        if t["assigned_to"]:
            extra_slots[t["assigned_to"]] += 1

    return _solve_cpsat(engineers, unassigned, eng_state, estimator,
                        extra_slots=dict(extra_slots),
                        reassign_tickets=stagnant_tickets), stagnant_info


# ──────────────────────────────────────────────
# 8. Evaluation
# ──────────────────────────────────────────────
def evaluate(assignments, tickets, engineers, label=""):
    """Comprehensive evaluation of an assignment result."""
    ticket_map = {t["ticket_id"]: t for t in tickets}
    eng_map = {e["engineer_id"]: e for e in engineers}

    total = len(assignments)
    assigned = [a for a in assignments if a["engineer_id"] is not None]
    unassigned_list = [a for a in assignments if a["engineer_id"] is None]

    # Assignment rate
    assignment_rate = len(assigned) / total if total > 0 else 0

    # HC violations
    hc_violations = 0
    for a in assigned:
        t = ticket_map[a["ticket_id"]]
        e = eng_map[a["engineer_id"]]
        # Skill
        if t["required_skill"] not in e["skills"]:
            hc_violations += 1
        # Tier
        if TIER_ORDER[e["tier"]] < TIER_ORDER[t["min_tier"]]:
            hc_violations += 1
        # Type allowed
        if t["type"] not in TIER_ALLOWED_TYPES[e["tier"]]:
            hc_violations += 1

    # Average score
    scores = [a["score"] for a in assigned]
    avg_score = sum(scores) / len(scores) if scores else 0

    # Skill match rate
    skill_matches = sum(1 for a in assigned if a["skill_match"])
    skill_match_rate = skill_matches / len(assigned) if assigned else 0

    # By priority
    by_priority = {}
    for p in ["P1", "P2", "P3", "P4"]:
        p_assignments = [a for a in assignments
                         if ticket_map[a["ticket_id"]]["priority"] == p]
        p_assigned = [a for a in p_assignments if a["engineer_id"] is not None]
        by_priority[p] = {
            "total": len(p_assignments),
            "assigned": len(p_assigned),
            "rate": len(p_assigned) / len(p_assignments) if p_assignments else 0,
            "avg_score": (sum(a["score"] for a in p_assigned) / len(p_assigned))
                         if p_assigned else 0,
        }

    # SLA critical (remaining < 6h)
    sla_critical = [a for a in assignments
                    if ticket_map[a["ticket_id"]]["sla_remaining_hours"] < 6]
    sla_critical_assigned = [a for a in sla_critical if a["engineer_id"] is not None]

    # Reassigned count (tickets that were in_progress/blocked and got reassigned)
    reassigned = [a for a in assigned
                  if ticket_map[a["ticket_id"]]["assigned_to"] is not None and
                  ticket_map[a["ticket_id"]]["assigned_to"] != a["engineer_id"]]

    # Load fairness (std dev of load among available engineers)
    load_dist = defaultdict(int)
    for a in assigned:
        load_dist[a["engineer_id"]] += 1
    if load_dist:
        loads = list(load_dist.values())
        mean_load = sum(loads) / len(loads)
        variance = sum((l - mean_load) ** 2 for l in loads) / len(loads)
        load_std = math.sqrt(variance)
    else:
        load_std = 0

    result = {
        "label": label,
        "total_tickets": total,
        "assigned_count": len(assigned),
        "unassigned_count": len(unassigned_list),
        "assignment_rate": round(assignment_rate, 4),
        "hc_violations": hc_violations,
        "avg_score": round(avg_score, 2),
        "skill_match_rate": round(skill_match_rate, 4),
        "by_priority": {k: {kk: round(vv, 4) if isinstance(vv, float) else vv
                            for kk, vv in v.items()}
                        for k, v in by_priority.items()},
        "sla_critical_total": len(sla_critical),
        "sla_critical_assigned": len(sla_critical_assigned),
        "reassigned_count": len(reassigned),
        "load_fairness_std": round(load_std, 4),
        "assignments": assignments,
    }
    return result


# ──────────────────────────────────────────────
# 9. Data Analysis Summary
# ──────────────────────────────────────────────
def analyze_data(engineers, tickets, history, estimator):
    """Produce a summary of the dataset for the assess report."""
    # Engineers by tier
    tier_counts = defaultdict(int)
    for e in engineers:
        tier_counts[e["tier"]] += 1

    # Engineers on shift
    on_shift = sum(1 for e in engineers if e["on_shift"])

    # Tickets by status
    status_counts = defaultdict(int)
    for t in tickets:
        status_counts[t["status"]] += 1

    # Tickets by priority
    priority_counts = defaultdict(int)
    for t in tickets:
        priority_counts[t["priority"]] += 1

    # Tickets by type
    type_counts = defaultdict(int)
    for t in tickets:
        type_counts[t["type"]] += 1

    # Blocked tickets
    blocked = [t for t in tickets if t["status"].startswith("blocked")]

    # SLA at risk (< 6h remaining)
    sla_risk = [t for t in tickets if t["sla_remaining_hours"] < 6]

    # Skills demand vs supply
    skill_demand = defaultdict(int)
    for t in tickets:
        if t["status"] == "unassigned":
            skill_demand[t["required_skill"]] += 1

    skill_supply = defaultdict(int)
    for e in engineers:
        if e["on_shift"] or (e["tier"] == "L3"):
            for s in e["skills"]:
                skill_supply[s] += 1

    return {
        "engineer_count": len(engineers),
        "tier_counts": dict(tier_counts),
        "on_shift_count": on_shift,
        "ticket_count": len(tickets),
        "status_counts": dict(status_counts),
        "priority_counts": dict(priority_counts),
        "type_counts": dict(type_counts),
        "blocked_count": len(blocked),
        "blocked_tickets": [{"id": t["ticket_id"], "status": t["status"],
                             "assigned_to": t["assigned_to"]}
                            for t in blocked],
        "sla_risk_count": len(sla_risk),
        "sla_risk_tickets": [{"id": t["ticket_id"], "priority": t["priority"],
                              "sla_remaining": t["sla_remaining_hours"]}
                             for t in sla_risk],
        "unassigned_skill_demand": dict(skill_demand),
        "on_shift_skill_supply": dict(skill_supply),
    }


# ──────────────────────────────────────────────
# 10. Main
# ──────────────────────────────────────────────
def main():
    print("=" * 60)
    print("Ticket Assignment Optimization — Full Workflow")
    print("=" * 60)

    # Load
    engineers, tickets, history, constraints = load_data()
    estimator, personal_avg, category_avg = build_llm_estimator(history)

    # Analysis
    print("\n[1/6] Data Analysis...")
    analysis = analyze_data(engineers, tickets, history, estimator)
    print(f"  Engineers: {analysis['engineer_count']} ({analysis['on_shift_count']} on shift)")
    print(f"  Tickets: {analysis['ticket_count']}")
    print(f"  Status: {analysis['status_counts']}")
    print(f"  Priority: {analysis['priority_counts']}")
    print(f"  Blocked: {analysis['blocked_count']}")
    print(f"  SLA at risk (<6h): {analysis['sla_risk_count']}")

    # Stagnation detection
    print("\n[2/6] Stagnation Detection...")
    stagnant = detect_stagnation(tickets)
    print(f"  Stagnant tickets: {len(stagnant)}")
    for s in stagnant:
        print(f"    {s['ticket_id']}: progress={s['progress_pct']}%, "
              f"expected={s['expected_pct']}%, elapsed={s['elapsed_hours']}h")

    # Baselines
    print("\n[3/6] Running Baselines...")

    print("  [3a] Round-Robin...")
    rr_assignments = baseline_round_robin(engineers, tickets, estimator)
    rr_eval = evaluate(rr_assignments, tickets, engineers, "round_robin")
    print(f"    Assigned: {rr_eval['assigned_count']}/{rr_eval['total_tickets']}, "
          f"Avg Score: {rr_eval['avg_score']}, HC violations: {rr_eval['hc_violations']}")

    print("  [3b] Greedy...")
    greedy_assignments = baseline_greedy(engineers, tickets, estimator)
    greedy_eval = evaluate(greedy_assignments, tickets, engineers, "greedy")
    print(f"    Assigned: {greedy_eval['assigned_count']}/{greedy_eval['total_tickets']}, "
          f"Avg Score: {greedy_eval['avg_score']}, HC violations: {greedy_eval['hc_violations']}")

    print("  [3c] CP-SAT Solver...")
    cpsat_assignments = baseline_cpsat(engineers, tickets, estimator)
    cpsat_eval = evaluate(cpsat_assignments, tickets, engineers, "cpsat_baseline")
    print(f"    Assigned: {cpsat_eval['assigned_count']}/{cpsat_eval['total_tickets']}, "
          f"Avg Score: {cpsat_eval['avg_score']}, HC violations: {cpsat_eval['hc_violations']}")

    # Improvements
    print("\n[4/6] Running Improvements...")

    print("  [4a] Improvement A: Release Blocked Slots...")
    imp_a_assignments = improvement_a_release_blocked(engineers, tickets, estimator)
    imp_a_eval = evaluate(imp_a_assignments, tickets, engineers, "improve_a_release_blocked")
    print(f"    Assigned: {imp_a_eval['assigned_count']}/{imp_a_eval['total_tickets']}, "
          f"Avg Score: {imp_a_eval['avg_score']}")

    print("  [4b] Improvement B: Reassign Stagnant...")
    imp_b_result, imp_b_stagnant = improvement_b_reassign_stagnant(
        engineers, tickets, estimator)
    imp_b_eval = evaluate(imp_b_result, tickets, engineers, "improve_b_reassign_stagnant")
    print(f"    Assigned: {imp_b_eval['assigned_count']}/{imp_b_eval['total_tickets']}, "
          f"Avg Score: {imp_b_eval['avg_score']}, Reassigned: {imp_b_eval['reassigned_count']}")

    print("  [4c] Improvement C: Combined (A+B)...")
    imp_c_result, imp_c_stagnant = improvement_c_combined(
        engineers, tickets, estimator)
    imp_c_eval = evaluate(imp_c_result, tickets, engineers, "improve_c_combined")
    print(f"    Assigned: {imp_c_eval['assigned_count']}/{imp_c_eval['total_tickets']}, "
          f"Avg Score: {imp_c_eval['avg_score']}, Reassigned: {imp_c_eval['reassigned_count']}")

    # Save results
    print("\n[5/6] Saving Results...")

    all_results = {
        "analysis": analysis,
        "stagnation": stagnant,
        "baselines": {
            "round_robin": {k: v for k, v in rr_eval.items() if k != "assignments"},
            "greedy": {k: v for k, v in greedy_eval.items() if k != "assignments"},
            "cpsat_baseline": {k: v for k, v in cpsat_eval.items() if k != "assignments"},
        },
        "improvements": {
            "a_release_blocked": {k: v for k, v in imp_a_eval.items() if k != "assignments"},
            "b_reassign_stagnant": {k: v for k, v in imp_b_eval.items() if k != "assignments"},
            "c_combined": {k: v for k, v in imp_c_eval.items() if k != "assignments"},
        },
        "assignments_detail": {
            "round_robin": rr_eval["assignments"],
            "greedy": greedy_eval["assignments"],
            "cpsat_baseline": cpsat_eval["assignments"],
            "improve_a": imp_a_eval["assignments"],
            "improve_b": imp_b_eval["assignments"],
            "improve_c": imp_c_eval["assignments"],
        },
        "estimator_stats": {
            "personal_avg_count": len(personal_avg),
            "category_avg": {k: round(v, 2) for k, v in category_avg.items()},
        },
    }

    with open(RESULTS_DIR / "optimization_results.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)

    # Summary comparison table
    comparison = []
    for label, ev in [("round_robin", rr_eval), ("greedy", greedy_eval),
                       ("cpsat_baseline", cpsat_eval),
                       ("improve_a", imp_a_eval),
                       ("improve_b", imp_b_eval),
                       ("improve_c", imp_c_eval)]:
        comparison.append({
            "method": label,
            "assigned": ev["assigned_count"],
            "total": ev["total_tickets"],
            "rate": ev["assignment_rate"],
            "hc_violations": ev["hc_violations"],
            "avg_score": ev["avg_score"],
            "skill_match_rate": ev["skill_match_rate"],
            "p1_assigned": ev["by_priority"]["P1"]["assigned"],
            "p2_assigned": ev["by_priority"]["P2"]["assigned"],
            "sla_critical_assigned": ev["sla_critical_assigned"],
            "reassigned": ev["reassigned_count"],
            "load_std": ev["load_fairness_std"],
        })

    with open(RESULTS_DIR / "comparison_summary.json", "w", encoding="utf-8") as f:
        json.dump(comparison, f, ensure_ascii=False, indent=2)

    # Print comparison table
    print("\n[6/6] Results Comparison:")
    print(f"{'Method':<28} {'Assigned':>8} {'Rate':>6} {'HC_Vio':>7} "
          f"{'AvgScore':>9} {'Skill%':>7} {'P1':>4} {'P2':>4} {'SLACrit':>8} "
          f"{'Reassign':>9} {'LoadStd':>8}")
    print("-" * 110)
    for c in comparison:
        print(f"{c['method']:<28} {c['assigned']:>4}/{c['total']:<3} "
              f"{c['rate']:>6.1%} {c['hc_violations']:>7} "
              f"{c['avg_score']:>9.2f} {c['skill_match_rate']:>6.1%} "
              f"{c['p1_assigned']:>4} {c['p2_assigned']:>4} "
              f"{c['sla_critical_assigned']:>8} {c['reassigned']:>9} "
              f"{c['load_std']:>8.2f}")

    print(f"\nResults saved to: {RESULTS_DIR}")
    print("Done!")

    return all_results


if __name__ == "__main__":
    results = main()
