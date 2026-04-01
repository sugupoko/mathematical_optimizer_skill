#!/usr/bin/env python3
"""シフト最適化 — 本番パイプライン

実行頻度: 週次（毎週金曜17:00）
入力:     data/employees.csv, data/shifts.csv
出力:     results/schedule_YYYYMMDD_HHMMSS.csv + meta JSON
ログ:     log/run_YYYYMMDD_HHMMSS.log
"""
from __future__ import annotations

import csv
import json
import logging
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime
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
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SHIFTS = ["morning", "afternoon", "night"]
HOURS_PER_SHIFT = 8
SOLVER_TIME_LIMIT = 30
HISTORY_KEEP = 8

# 需要調整: 供給368h < 需要384h のため、以下を自動適用
DEMAND_OVERRIDES = {
    ("Wed", "morning"): 2,   # 3→2
    ("Sun", "afternoon"): 1,  # 2→1
}


# ═══════════════════════════════════════════
# 1. データ読み込み
# ═══════════════════════════════════════════
def load_employees(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    employees = []
    for row in rows:
        employees.append({
            "id": row["employee_id"],
            "name": row["name"],
            "skills": [s.strip() for s in row["skills"].split(",")],
            "max_hours": int(row["max_hours_per_week"]),
            "min_hours": int(row["min_hours_per_week"]),
            "unavailable": [d.strip() for d in row["unavailable_days"].split(",") if d.strip()],
        })
    return employees


def load_shifts(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    shifts = []
    for row in rows:
        day = row["day"]
        shift_name = row["shift_name"]
        req = int(row["required_count"])
        # 需要調整の適用
        if (day, shift_name) in DEMAND_OVERRIDES:
            original = req
            req = DEMAND_OVERRIDES[(day, shift_name)]
            logger.info(f"需要調整: {day}_{shift_name} {original}→{req}")
        shifts.append({
            "day": day,
            "shift_name": shift_name,
            "start_time": row["start_time"],
            "end_time": row["end_time"],
            "required_count": req,
            "required_skills": [sk.strip() for sk in row["required_skills"].split(",")],
        })
    return shifts


# ═══════════════════════════════════════════
# 2. バリデーション
# ═══════════════════════════════════════════
def validate(employees: list[dict], shifts: list[dict]) -> list[str]:
    """致命的エラーのリストを返す（空なら問題なし）。"""
    errors = []
    warnings = []

    if len(employees) == 0:
        errors.append("従業員データが空です")
    elif len(employees) < 8:
        warnings.append(f"従業員数が少ない ({len(employees)}名)")

    reception_count = sum(1 for e in employees if "reception" in e["skills"])
    if reception_count < 5:
        errors.append(f"reception可能者が不足 ({reception_count}名 < 5名)")

    total_supply = sum(e["max_hours"] for e in employees)
    total_demand = sum(s["required_count"] for s in shifts) * HOURS_PER_SHIFT
    if total_supply < total_demand:
        errors.append(f"供給不足: {total_supply}h < {total_demand}h（需要調整後）")

    for e in employees:
        if e["min_hours"] > e["max_hours"]:
            errors.append(f"{e['id']}: min_hours({e['min_hours']}) > max_hours({e['max_hours']})")
        if e["max_hours"] > 60:
            warnings.append(f"{e['id']}: max_hours={e['max_hours']}h（労基法超過の可能性）")

    if len(shifts) != 21:
        warnings.append(f"シフト数が想定と異なる ({len(shifts)}件、通常21件)")

    for w in warnings:
        logger.warning(w)

    return errors


# ═══════════════════════════════════════════
# 3. CP-SAT改善版ソルバー
# ═══════════════════════════════════════════
def solve(employees: list[dict], shifts: list[dict]) -> list[dict]:
    """CP-SAT改善版: ハード制約 + ソフト制約を目的関数に組み込み。"""
    model = cp_model.CpModel()
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

    objective_terms = []

    # HC1: 必要人数 → 緩和
    for s in shifts:
        assigned = [x[(e["id"], s["day"], s["shift_name"])]
                    for e in employees
                    if (e["id"], s["day"], s["shift_name"]) in x]
        if assigned:
            shortage = model.new_int_var(0, s["required_count"],
                                         f"short_{s['day']}_{s['shift_name']}")
            model.add(sum(assigned) + shortage >= s["required_count"])
            objective_terms.append(-shortage * 200)

    # HC2: 週最大勤務時間
    for e in employees:
        weekly = [x[k] for k in x if k[0] == e["id"]]
        if weekly:
            model.add(sum(weekly) * HOURS_PER_SHIFT <= e["max_hours"])

    # 同一日1シフトまで
    for e in employees:
        for d in DAYS:
            day_shifts = [x[k] for k in x if k[0] == e["id"] and k[1] == d]
            if day_shifts:
                model.add(sum(day_shifts) <= 1)

    # HC5: 夜勤→翌日朝勤禁止
    for e in employees:
        for i, d in enumerate(DAYS[:-1]):
            next_d = DAYS[i + 1]
            nk = (e["id"], d, "night")
            mk = (e["id"], next_d, "morning")
            if nk in x and mk in x:
                model.add(x[nk] + x[mk] <= 1)

    # SC2: 公平性
    total_demand = sum(s["required_count"] for s in shifts)
    avg_shifts = total_demand / len(employees)
    emp_shift_count = {}
    for e in employees:
        emp_vars = [x[k] for k in x if k[0] == e["id"]]
        if emp_vars:
            total = model.new_int_var(0, 7, f"total_{e['id']}")
            model.add(total == sum(emp_vars))
            emp_shift_count[e["id"]] = total
            dev = model.new_int_var(0, 7, f"dev_{e['id']}")
            target = int(round(avg_shifts))
            model.add(dev >= total - target)
            model.add(dev >= target - total)
            objective_terms.append(-dev * 5)

    # SC3: 最低勤務時間
    for e in employees:
        min_shifts = e["min_hours"] // HOURS_PER_SHIFT
        tv = emp_shift_count.get(e["id"])
        if tv is not None:
            sf = model.new_int_var(0, 7, f"sf_{e['id']}")
            model.add(sf >= min_shifts - tv)
            model.add(sf >= 0)
            objective_terms.append(-sf * 3 * HOURS_PER_SHIFT)

    # SC4: 夜勤 <= 2回
    for e in employees:
        nv = [x[k] for k in x if k[0] == e["id"] and k[2] == "night"]
        if nv:
            nt = model.new_int_var(0, 7, f"night_{e['id']}")
            model.add(nt == sum(nv))
            exc = model.new_int_var(0, 7, f"nexc_{e['id']}")
            model.add(exc >= nt - 2)
            model.add(exc >= 0)
            objective_terms.append(-exc * 8)

    # SC5: トレーニング持ちを毎日配置
    for d in DAYS:
        tv = [x[k] for k in x if k[1] == d and k[0] in training_emps]
        if tv:
            ht = model.new_bool_var(f"trainer_{d}")
            model.add(sum(tv) >= 1).only_enforce_if(ht)
            model.add(sum(tv) == 0).only_enforce_if(ht.negated())
            objective_terms.append(ht * 5)

    # SC1: 連続勤務 <= 5日
    for e in employees:
        for si in range(len(DAYS) - 5):
            sd = [x[k] for k in x if k[0] == e["id"] and k[1] in DAYS[si:si + 6]]
            if len(sd) >= 6:
                exc = model.new_int_var(0, 1, f"consec_{e['id']}_{si}")
                model.add(sum(sd) <= 5 + exc)
                objective_terms.append(-exc * 10)

    if objective_terms:
        model.maximize(sum(objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_TIME_LIMIT
    solver.parameters.num_workers = 8

    status = solver.solve(model)
    status_name = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
    }.get(status, "UNKNOWN")
    logger.info(f"CP-SAT status: {status_name}")

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return []

    schedule = []
    for key, var in x.items():
        if solver.value(var) == 1:
            schedule.append({
                "employee_id": key[0],
                "day": key[1],
                "shift_name": key[2],
            })
    return schedule


# ═══════════════════════════════════════════
# 4. 結果検証
# ═══════════════════════════════════════════
def verify(schedule: list[dict], employees: list[dict], shifts: list[dict]) -> dict:
    emp_map = {e["id"]: e for e in employees}

    # HC1: 必要人数
    hc1 = 0
    for s in shifts:
        assigned = sum(1 for a in schedule
                       if a["day"] == s["day"] and a["shift_name"] == s["shift_name"])
        if assigned < s["required_count"]:
            hc1 += s["required_count"] - assigned

    # HC2: 週最大
    hours_per_emp = defaultdict(int)
    for a in schedule:
        hours_per_emp[a["employee_id"]] += HOURS_PER_SHIFT
    hc2 = sum(1 for eid, h in hours_per_emp.items()
              if eid in emp_map and h > emp_map[eid]["max_hours"])

    # 公平性
    all_hours = [hours_per_emp.get(e["id"], 0) for e in employees]
    hours_std = statistics.stdev(all_hours) if len(all_hours) > 1 else 0

    # 夜勤分布
    night_counts = defaultdict(int)
    for a in schedule:
        if a["shift_name"] == "night":
            night_counts[a["employee_id"]] += 1
    night_over2 = sum(1 for c in night_counts.values() if c > 2)

    return {
        "total_assignments": len(schedule),
        "hc1_shortage": hc1,
        "hc2_overtime": hc2,
        "hours_std": round(hours_std, 2),
        "night_over2_employees": night_over2,
        "hours_per_employee": dict(hours_per_emp),
    }


# ═══════════════════════════════════════════
# 5. 出力
# ═══════════════════════════════════════════
def export_schedule(schedule: list[dict], meta: dict):
    # CSV
    csv_path = RESULTS_DIR / f"schedule_{TIMESTAMP}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["employee_id", "day", "shift_name"])
        writer.writeheader()
        for row in sorted(schedule, key=lambda r: (DAYS.index(r["day"]), r["shift_name"], r["employee_id"])):
            writer.writerow(row)
    logger.info(f"シフト表出力: {csv_path}")

    # JSON メタデータ
    json_path = RESULTS_DIR / f"meta_{TIMESTAMP}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    logger.info(f"メタデータ出力: {json_path}")

    # 古いファイルの削除（HISTORY_KEEP件保持）
    for pattern in ["schedule_*.csv", "meta_*.json"]:
        files = sorted(RESULTS_DIR.glob(pattern))
        if len(files) > HISTORY_KEEP:
            for old in files[:-HISTORY_KEEP]:
                old.unlink()
                logger.info(f"古いファイル削除: {old.name}")


# ═══════════════════════════════════════════
# 6. フォールバック: 貪欲法
# ═══════════════════════════════════════════
def solve_greedy_fallback(employees: list[dict], shifts: list[dict]) -> list[dict]:
    """ソルバー失敗時のフォールバック。"""
    logger.warning("フォールバック: 貪欲法を使用")
    schedule = []
    hours_used = defaultdict(int)
    sorted_shifts = sorted(shifts, key=lambda s: -s["required_count"])

    for s in sorted_shifts:
        candidates = []
        for e in employees:
            if s["day"] in e["unavailable"]:
                continue
            if not any(sk in e["skills"] for sk in s["required_skills"]):
                continue
            if hours_used[e["id"]] + HOURS_PER_SHIFT > e["max_hours"]:
                continue
            if any(a["employee_id"] == e["id"] and a["day"] == s["day"] for a in schedule):
                continue
            candidates.append(e)
        candidates.sort(key=lambda e: hours_used[e["id"]])
        for e in candidates[:s["required_count"]]:
            schedule.append({
                "employee_id": e["id"],
                "day": s["day"],
                "shift_name": s["shift_name"],
            })
            hours_used[e["id"]] += HOURS_PER_SHIFT
    return schedule


# ═══════════════════════════════════════════
# メイン
# ═══════════════════════════════════════════
def main():
    logger.info("=" * 50)
    logger.info("シフト最適化パイプライン 開始")
    logger.info("=" * 50)

    # Step 1: データ読み込み
    logger.info("[Step 1] データ読み込み")
    try:
        employees = load_employees(DATA_DIR / "employees.csv")
        shifts = load_shifts(DATA_DIR / "shifts.csv")
    except FileNotFoundError as e:
        logger.error(f"データファイルが見つかりません: {e}")
        sys.exit(1)
    logger.info(f"  従業員: {len(employees)}名, シフト: {len(shifts)}件")

    total_supply = sum(e["max_hours"] for e in employees)
    total_demand = sum(s["required_count"] for s in shifts) * HOURS_PER_SHIFT
    logger.info(f"  供給: {total_supply}h, 需要(調整後): {total_demand}h")

    # Step 2: バリデーション
    logger.info("[Step 2] バリデーション")
    errors = validate(employees, shifts)
    if errors:
        for err in errors:
            logger.error(f"  致命的エラー: {err}")
        logger.error("パイプライン中断")
        sys.exit(1)
    logger.info("  バリデーション OK")

    # Step 3: 最適化実行
    logger.info(f"[Step 3] CP-SAT最適化 (time_limit={SOLVER_TIME_LIMIT}s)")
    schedule = solve(employees, shifts)

    # フォールバック
    if not schedule:
        logger.warning("CP-SATが解を返しませんでした。フォールバック実行。")
        schedule = solve_greedy_fallback(employees, shifts)
        if not schedule:
            logger.error("フォールバックも失敗。パイプライン中断。")
            sys.exit(1)

    # Step 4: 結果検証
    logger.info("[Step 4] 結果検証")
    meta = verify(schedule, employees, shifts)
    logger.info(f"  割当数: {meta['total_assignments']}")
    logger.info(f"  HC1不足: {meta['hc1_shortage']}枠")
    logger.info(f"  HC2超過: {meta['hc2_overtime']}名")
    logger.info(f"  時間偏差: {meta['hours_std']}h")
    logger.info(f"  夜勤3回以上: {meta['night_over2_employees']}名")

    if meta["hc2_overtime"] > 0:
        logger.error("週最大勤務時間超過あり。結果を確認してください。")

    # Step 5: 出力
    logger.info("[Step 5] 結果出力")
    meta["timestamp"] = TIMESTAMP
    meta["solver_time_limit"] = SOLVER_TIME_LIMIT
    meta["demand_overrides"] = {f"{k[0]}_{k[1]}": v for k, v in DEMAND_OVERRIDES.items()}
    export_schedule(schedule, meta)

    logger.info("=" * 50)
    logger.info("シフト最適化パイプライン 完了")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
