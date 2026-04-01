#!/usr/bin/env python3
"""チケットアサイン最適化 — 本番パイプライン

実行頻度: 15分ごと + P1即時トリガー
入力:     data/engineers.csv, data/tickets.csv, data/resolution_history.csv
出力:     results/assignments_YYYYMMDD_HHMMSS.json
ログ:     log/run_YYYYMMDD_HHMMSS.log
"""

import csv
import json
import logging
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from ortools.sat.python import cp_model

# ─── パス設定 ───
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = BASE_DIR / "results"
LOG_DIR = BASE_DIR / "log"
RESULTS_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")

# ─── ロガー ───
log_path = LOG_DIR / f"run_{TIMESTAMP}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# ─── 定数 ───
NOW = datetime(2026, 4, 1, 14, 0)  # シミュレーション用現在時刻
SOLVER_TIME_LIMIT = 30
HISTORY_KEEP = 96  # 15分×96 = 24時間分

TIER_ORDER = {"L1": 1, "L2": 2, "L3": 3}
TIER_ALLOWED_TYPES = {
    "L1": {"service_request", "incident_low"},
    "L2": {"service_request", "incident_low", "incident_mid", "change_standard"},
    "L3": {"service_request", "incident_low", "incident_mid", "change_standard",
            "incident_high", "incident_critical", "change_emergency"},
}
PRIORITY_ORDER = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
STAGNATION_HOURS = 6
STAGNATION_THRESHOLD = 0.5  # 期待進捗の50%未満で停滞


# ═══════════════════════════════════════════
# 1. データ読み込み
# ═══════════════════════════════════════════
def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_data():
    engineers = load_csv(DATA_DIR / "engineers.csv")
    tickets = load_csv(DATA_DIR / "tickets.csv")
    history = load_csv(DATA_DIR / "resolution_history.csv")

    for e in engineers:
        e["skills"] = set(e["skills"].split(","))
        e["max_concurrent"] = int(e["max_concurrent"])
        e["experience_years"] = int(e["experience_years"])
        e["on_shift"] = e["on_shift"].strip() == "True"

    for t in tickets:
        t["sla_remaining_hours"] = float(t["sla_remaining_hours"])
        t["progress_pct"] = int(t["progress_pct"])
        t["estimated_remaining_hours"] = float(t["estimated_remaining_hours"])
        t["sla_deadline"] = datetime.strptime(t["sla_deadline"], "%Y-%m-%d %H:%M")
        t["created_at"] = datetime.strptime(t["created_at"], "%Y-%m-%d %H:%M")
        t["assigned_to"] = t["assigned_to"].strip() if t["assigned_to"].strip() else None

    for h in history:
        h["resolution_hours"] = float(h["resolution_hours"])

    return engineers, tickets, history


# ═══════════════════════════════════════════
# 2. LLMエスティメータ（解決時間予測）
# ═══════════════════════════════════════════
def build_estimator(history):
    personal = defaultdict(list)
    category = defaultdict(list)
    for h in history:
        personal[(h["engineer_id"], h["skill"])].append(h["resolution_hours"])
        category[h["skill"]].append(h["resolution_hours"])

    personal_avg = {k: sum(v) / len(v) for k, v in personal.items()}
    category_avg = {k: sum(v) / len(v) for k, v in category.items()}

    def estimate(engineer_id, skill):
        key = (engineer_id, skill)
        if key in personal_avg:
            return personal_avg[key], "personal"
        if skill in category_avg:
            return category_avg[skill], "category"
        return 2.0, "default"

    return estimate


# ═══════════════════════════════════════════
# 3. 停滞検出
# ═══════════════════════════════════════════
def detect_stagnation(tickets):
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

        if elapsed > STAGNATION_HOURS and t["progress_pct"] < expected_pct * STAGNATION_THRESHOLD:
            stagnant.append({
                "ticket_id": t["ticket_id"],
                "assigned_to": t["assigned_to"],
                "progress_pct": t["progress_pct"],
                "expected_pct": round(expected_pct, 1),
                "elapsed_hours": round(elapsed, 1),
            })
    return stagnant


# ═══════════════════════════════════════════
# 4. バリデーション
# ═══════════════════════════════════════════
def validate(engineers, tickets):
    errors = []
    warnings = []

    if not engineers:
        errors.append("エンジニアデータが空です")
    if not tickets:
        errors.append("チケットデータが空です")

    on_shift = sum(1 for e in engineers if e["on_shift"])
    if on_shift == 0:
        errors.append("勤務中のエンジニアが0名です")

    unassigned = [t for t in tickets if t["status"] == "unassigned"]
    p1_unassigned = [t for t in unassigned if t["priority"] == "P1"]
    if p1_unassigned:
        warnings.append(f"P1未アサイン: {len(p1_unassigned)}件 — 即時対応が必要")

    sla_risk = [t for t in tickets if t["sla_remaining_hours"] < 6]
    if sla_risk:
        warnings.append(f"SLAリスク(<6h): {len(sla_risk)}件")

    for w in warnings:
        logger.warning(w)
    return errors


# ═══════════════════════════════════════════
# 5. エンジニア状態管理
# ═══════════════════════════════════════════
def build_engineer_state(engineers, tickets, release_blocked=False):
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
        eng_map[eid] = {
            **e,
            "current_load": current,
            "available_slots": max(0, e["max_concurrent"] - current),
        }
    return eng_map


def is_available(eng, ticket, eng_state):
    e = eng_state[eng["engineer_id"]]
    if e["available_slots"] <= 0:
        return False
    if ticket["required_skill"] not in eng["skills"]:
        return False
    if TIER_ORDER[eng["tier"]] < TIER_ORDER[ticket["min_tier"]]:
        return False
    if ticket["type"] not in TIER_ALLOWED_TYPES[eng["tier"]]:
        return False
    if not eng["on_shift"]:
        if eng["tier"] == "L3" and ticket["priority"] == "P1":
            pass
        else:
            return False
    return True


# ═══════════════════════════════════════════
# 6. スコアリング
# ═══════════════════════════════════════════
def compute_score(eng, ticket, estimator, eng_state):
    score = 0.0
    if ticket["required_skill"] in eng["skills"]:
        score += 30.0
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
    exp = min(eng["experience_years"], 15)
    score += (exp / 15.0) * 15.0
    eng_tier = TIER_ORDER[eng["tier"]]
    min_tier = TIER_ORDER[ticket["min_tier"]]
    if eng_tier == min_tier:
        score += 10.0
    elif eng_tier == min_tier + 1:
        score += 5.0
    else:
        score += 2.0
    _, source = estimator(eng["engineer_id"], ticket["required_skill"])
    if source == "personal":
        score += 5.0
    elif source == "category":
        score += 3.0
    else:
        score += 1.0
    return score


# ═══════════════════════════════════════════
# 7. CP-SAT ソルバー（複合改善: ブロック解放 + 停滞再アサイン）
# ═══════════════════════════════════════════
def solve_combined(engineers, tickets, estimator):
    stagnant_info = detect_stagnation(tickets)
    stagnant_ids = {s["ticket_id"] for s in stagnant_info}

    unassigned = [t for t in tickets if t["status"] == "unassigned"]
    stagnant_tickets = [t for t in tickets if t["ticket_id"] in stagnant_ids]

    eng_state = build_engineer_state(engineers, tickets, release_blocked=True)

    # 停滞チケットのスロット解放
    extra_slots = defaultdict(int)
    for t in stagnant_tickets:
        if t["assigned_to"]:
            extra_slots[t["assigned_to"]] += 1

    all_tickets = list(unassigned) + list(stagnant_tickets)
    if not all_tickets:
        return [], stagnant_info

    model = cp_model.CpModel()
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

    # 各チケット最大1名
    for ti in range(len(all_tickets)):
        vv = [x[ti, ei] for ei in range(len(engineers)) if (ti, ei) in x]
        if vv:
            model.Add(sum(vv) <= 1)

    # エンジニア容量
    for ei, e in enumerate(engineers):
        eid = e["engineer_id"]
        es = eng_state[eid]
        slots = es["available_slots"] + extra_slots.get(eid, 0)
        vv = [x[ti, ei] for ti in range(len(all_tickets)) if (ti, ei) in x]
        if vv:
            model.Add(sum(vv) <= slots)

    # 目的関数
    obj_terms = []
    for (ti, ei), var in x.items():
        t = all_tickets[ti]
        priority_bonus = {"P1": 5000, "P2": 3000, "P3": 1000, "P4": 0}.get(t["priority"], 0)
        obj_terms.append((scores[ti, ei] + priority_bonus) * var)

    if obj_terms:
        model.Maximize(sum(obj_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_TIME_LIMIT
    status = solver.Solve(model)

    status_name = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
    }.get(status, "UNKNOWN")
    logger.info(f"CP-SAT status: {status_name}")

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
                "priority": t["priority"],
                "is_reassign": t["ticket_id"] in stagnant_ids,
            })
    else:
        for t in all_tickets:
            assignments.append({
                "ticket_id": t["ticket_id"],
                "engineer_id": None,
                "score": 0,
                "priority": t["priority"],
                "is_reassign": t["ticket_id"] in stagnant_ids,
            })

    return assignments, stagnant_info


# ═══════════════════════════════════════════
# 8. 結果検証
# ═══════════════════════════════════════════
def verify(assignments, tickets, engineers):
    ticket_map = {t["ticket_id"]: t for t in tickets}
    eng_map = {e["engineer_id"]: e for e in engineers}

    assigned = [a for a in assignments if a["engineer_id"] is not None]
    total = len(assignments)
    assignment_rate = len(assigned) / total if total > 0 else 0

    hc_violations = 0
    for a in assigned:
        t = ticket_map[a["ticket_id"]]
        e = eng_map[a["engineer_id"]]
        if t["required_skill"] not in e["skills"]:
            hc_violations += 1
        if TIER_ORDER[e["tier"]] < TIER_ORDER[t["min_tier"]]:
            hc_violations += 1

    scores_list = [a["score"] for a in assigned]
    avg_score = sum(scores_list) / len(scores_list) if scores_list else 0

    by_priority = {}
    for p in ["P1", "P2", "P3", "P4"]:
        p_all = [a for a in assignments if a["priority"] == p]
        p_assigned = [a for a in p_all if a["engineer_id"] is not None]
        by_priority[p] = {"total": len(p_all), "assigned": len(p_assigned)}

    reassigned = [a for a in assigned if a.get("is_reassign")]

    return {
        "total_tickets": total,
        "assigned_count": len(assigned),
        "assignment_rate": round(assignment_rate, 4),
        "hc_violations": hc_violations,
        "avg_score": round(avg_score, 2),
        "by_priority": by_priority,
        "reassigned_count": len(reassigned),
    }


# ═══════════════════════════════════════════
# 9. 出力
# ═══════════════════════════════════════════
def export_results(assignments, meta, stagnant_info):
    json_path = RESULTS_DIR / f"assignments_{TIMESTAMP}.json"
    export_data = {
        "timestamp": TIMESTAMP,
        "meta": meta,
        "stagnant_detected": len(stagnant_info),
        "assignments": assignments,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)
    logger.info(f"アサイン結果出力: {json_path}")

    # 古いファイルの削除
    files = sorted(RESULTS_DIR.glob("assignments_*.json"))
    if len(files) > HISTORY_KEEP:
        for old in files[:-HISTORY_KEEP]:
            old.unlink()
            logger.info(f"古いファイル削除: {old.name}")


# ═══════════════════════════════════════════
# 10. フォールバック: 貪欲法
# ═══════════════════════════════════════════
def solve_greedy_fallback(engineers, tickets, estimator):
    logger.warning("フォールバック: 貪欲法を使用")
    stagnant_info = detect_stagnation(tickets)
    stagnant_ids = {s["ticket_id"] for s in stagnant_info}

    unassigned = [t for t in tickets if t["status"] == "unassigned"]
    stagnant_tickets = [t for t in tickets if t["ticket_id"] in stagnant_ids]
    all_tickets = list(unassigned) + list(stagnant_tickets)
    all_tickets.sort(key=lambda t: (PRIORITY_ORDER[t["priority"]], t["sla_remaining_hours"]))

    eng_state = build_engineer_state(engineers, tickets, release_blocked=True)
    extra_slots = defaultdict(int)
    for t in stagnant_tickets:
        if t["assigned_to"]:
            extra_slots[t["assigned_to"]] += 1
    for eid in extra_slots:
        if eid in eng_state:
            eng_state[eid]["available_slots"] += extra_slots[eid]

    assignments = []
    for t in all_tickets:
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
                "priority": t["priority"],
                "is_reassign": t["ticket_id"] in stagnant_ids,
            })
            eng_state[best_eng["engineer_id"]]["available_slots"] -= 1
        else:
            assignments.append({
                "ticket_id": t["ticket_id"],
                "engineer_id": None,
                "score": 0,
                "priority": t["priority"],
                "is_reassign": t["ticket_id"] in stagnant_ids,
            })
    return assignments, stagnant_info


# ═══════════════════════════════════════════
# メイン
# ═══════════════════════════════════════════
def main():
    logger.info("=" * 50)
    logger.info("チケットアサイン最適化パイプライン 開始")
    logger.info("=" * 50)

    # Step 1: データ読み込み
    logger.info("[Step 1] データ読み込み")
    try:
        engineers, tickets, history = load_data()
    except FileNotFoundError as e:
        logger.error(f"データファイルが見つかりません: {e}")
        sys.exit(1)

    estimator = build_estimator(history)
    on_shift = sum(1 for e in engineers if e["on_shift"])
    unassigned_count = sum(1 for t in tickets if t["status"] == "unassigned")
    logger.info(f"  エンジニア: {len(engineers)}名 (勤務中: {on_shift}名)")
    logger.info(f"  チケット: {len(tickets)}件 (未アサイン: {unassigned_count}件)")

    # Step 2: バリデーション
    logger.info("[Step 2] バリデーション")
    errors = validate(engineers, tickets)
    if errors:
        for err in errors:
            logger.error(f"  致命的エラー: {err}")
        logger.error("パイプライン中断")
        sys.exit(1)
    logger.info("  バリデーション OK")

    # Step 3: 停滞検出
    logger.info("[Step 3] 停滞検出")
    stagnant_preview = detect_stagnation(tickets)
    logger.info(f"  停滞チケット: {len(stagnant_preview)}件")

    # Step 4: 最適化実行（複合改善: ブロック解放 + 停滞再アサイン）
    logger.info(f"[Step 4] CP-SAT最適化 (time_limit={SOLVER_TIME_LIMIT}s)")
    assignments, stagnant_info = solve_combined(engineers, tickets, estimator)

    # フォールバック
    if not assignments or all(a["engineer_id"] is None for a in assignments):
        assignments, stagnant_info = solve_greedy_fallback(engineers, tickets, estimator)

    # Step 5: 結果検証
    logger.info("[Step 5] 結果検証")
    meta = verify(assignments, tickets, engineers)
    logger.info(f"  アサイン: {meta['assigned_count']}/{meta['total_tickets']}件 ({meta['assignment_rate']:.1%})")
    logger.info(f"  HC違反: {meta['hc_violations']}件")
    logger.info(f"  平均スコア: {meta['avg_score']}")
    for p, v in meta["by_priority"].items():
        if v["total"] > 0:
            logger.info(f"  {p}: {v['assigned']}/{v['total']}件")
    logger.info(f"  再アサイン: {meta['reassigned_count']}件")

    if meta["hc_violations"] > 0:
        logger.error("ハード制約違反あり。結果を確認してください。")

    # Step 6: 出力
    logger.info("[Step 6] 結果出力")
    export_results(assignments, meta, stagnant_info)

    logger.info("=" * 50)
    logger.info("チケットアサイン最適化パイプライン 完了")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
