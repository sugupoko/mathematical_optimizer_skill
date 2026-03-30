"""週次シフト最適化パイプライン — 本番運用スクリプト

毎週金曜17時に実行し、翌週のシフト表を自動生成する。
cron: 0 17 * * 5 cd /path/to/project && python scripts/run_weekly.py

パイプライン:
  1. データ取得 → 2. バリデーション → 3. 前処理 → 4. 最適化 → 5. 検証 → 6. 出力
"""
from __future__ import annotations
import csv
import json
import sys
import logging
from datetime import datetime
from pathlib import Path
from ortools.sat.python import cp_model

# ─── 設定 ───

DATA_DIR = Path(__file__).parent.parent / "data"
RESULTS_DIR = Path(__file__).parent.parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)
LOG_DIR = Path(__file__).parent.parent / "log"
LOG_DIR.mkdir(exist_ok=True)

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SHIFT_HOURS = 8
SOLVER_TIME_LIMIT = 30  # seconds
HISTORY_KEEP = 8  # 過去N回分の結果を保持

# 提案Aの需要調整: Wed morning 3→2, Sun afternoon 2→1
DEMAND_OVERRIDES = {
    ("Wed", "morning"): 2,
    ("Sun", "afternoon"): 1,
}

# ─── ロガー ───

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"run_{timestamp}.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ─── Step 1: データ取得 ───

def load_data() -> tuple[list[dict], list[dict]]:
    log.info("Step 1: データ取得")
    employees = []
    with open(DATA_DIR / "employees.csv") as f:
        for row in csv.DictReader(f):
            row["skills"] = set(row["skills"].split(","))
            row["max_hours_per_week"] = int(row["max_hours_per_week"])
            row["min_hours_per_week"] = int(row["min_hours_per_week"])
            unavail = row["unavailable_days"].strip()
            row["unavailable_days"] = set(unavail.split(",")) if unavail else set()
            employees.append(row)

    shifts = []
    with open(DATA_DIR / "shifts.csv") as f:
        for row in csv.DictReader(f):
            row["required_count"] = int(row["required_count"])
            row["required_skills"] = set(row["required_skills"].split(","))
            # 需要調整を適用
            key = (row["day"], row["shift_name"])
            if key in DEMAND_OVERRIDES:
                original = row["required_count"]
                row["required_count"] = DEMAND_OVERRIDES[key]
                log.info(f"  需要調整: {key[0]} {key[1]}: {original} → {row['required_count']}")
            shifts.append(row)

    log.info(f"  従業員: {len(employees)}名, シフト: {len(shifts)}枠")
    return employees, shifts


# ─── Step 2: バリデーション ───

def validate_data(employees: list[dict], shifts: list[dict]) -> dict:
    log.info("Step 2: バリデーション")
    issues = {"critical": [], "warning": []}

    # 従業員数チェック
    if len(employees) == 0:
        issues["critical"].append("従業員データが空です")
    if len(employees) < 8:
        issues["warning"].append(f"従業員が{len(employees)}名しかいません（通常10名）")

    # シフト数チェック
    if len(shifts) != 21:
        issues["warning"].append(f"シフト数が{len(shifts)}（通常21）")

    # スキルチェック: reception可能者が最低限いるか
    reception_count = sum(1 for e in employees if "reception" in e["skills"])
    if reception_count < 5:
        issues["critical"].append(f"reception可能者が{reception_count}名のみ（最低5名必要）")

    # 供給 vs 需要チェック
    total_supply = sum(
        min(e["max_hours_per_week"] // SHIFT_HOURS, 7 - len(e["unavailable_days"]))
        for e in employees
    )
    total_demand = sum(s["required_count"] for s in shifts)
    if total_supply < total_demand:
        issues["critical"].append(
            f"供給不足: 供給{total_supply}シフト < 需要{total_demand}シフト。"
            f"需要を{total_demand - total_supply}シフト以上削減するか、人員を追加してください"
        )

    # 値の範囲チェック
    for e in employees:
        if e["max_hours_per_week"] > 60:
            issues["warning"].append(f"{e['name']}: max_hours={e['max_hours_per_week']}h（労基法上限超過の可能性）")
        if e["min_hours_per_week"] > e["max_hours_per_week"]:
            issues["critical"].append(f"{e['name']}: min_hours > max_hours")

    for level, msgs in issues.items():
        for msg in msgs:
            getattr(log, "error" if level == "critical" else "warning")(f"  [{level}] {msg}")

    if not issues["critical"] and not issues["warning"]:
        log.info("  バリデーション OK")

    return issues


# ─── Step 3: 前処理 ───
# この問題ではCSV読み込み時に完了済み


# ─── Step 4: 最適化 ───

def optimize(employees: list[dict], shifts: list[dict]) -> tuple[dict, dict]:
    log.info(f"Step 4: 最適化実行 (time_limit={SOLVER_TIME_LIMIT}s)")
    n_emp, n_shift = len(employees), len(shifts)
    model = cp_model.CpModel()

    x = {}
    for e in range(n_emp):
        for s in range(n_shift):
            x[e, s] = model.new_bool_var(f"x_{e}_{s}")

    # HC1: required_count
    for s_idx, sh in enumerate(shifts):
        model.add(sum(x[e, s_idx] for e in range(n_emp)) == sh["required_count"])

    # HC2: max hours
    for e_idx, emp in enumerate(employees):
        model.add(sum(x[e_idx, s] for s in range(n_shift)) <= emp["max_hours_per_week"] // SHIFT_HOURS)

    # HC3: unavailable
    for e_idx, emp in enumerate(employees):
        for s_idx, sh in enumerate(shifts):
            if sh["day"] in emp["unavailable_days"]:
                model.add(x[e_idx, s_idx] == 0)

    # HC4: skills
    for e_idx, emp in enumerate(employees):
        for s_idx, sh in enumerate(shifts):
            if not sh["required_skills"].issubset(emp["skills"]):
                model.add(x[e_idx, s_idx] == 0)

    # HC5: night→morning
    for e_idx in range(n_emp):
        for d_idx in range(len(DAYS) - 1):
            ni = d_idx * 3 + 2
            nm = (d_idx + 1) * 3
            if ni < n_shift and nm < n_shift:
                model.add(x[e_idx, ni] + x[e_idx, nm] <= 1)

    # 1 shift per day
    for e_idx in range(n_emp):
        for d_idx in range(7):
            ds = [d_idx * 3 + off for off in range(3) if d_idx * 3 + off < n_shift]
            model.add(sum(x[e_idx, s] for s in ds) <= 1)

    # Soft: fairness, min hours, night limit, training
    emp_counts = []
    for e_idx in range(n_emp):
        c = model.new_int_var(0, 7, f"cnt_{e_idx}")
        model.add(c == sum(x[e_idx, s] for s in range(n_shift)))
        emp_counts.append(c)

    max_c = model.new_int_var(0, 7, "maxc")
    min_c = model.new_int_var(0, 7, "minc")
    model.add_max_equality(max_c, emp_counts)
    model.add_min_equality(min_c, emp_counts)
    gap = model.new_int_var(0, 7, "gap")
    model.add(gap == max_c - min_c)

    min_sf = []
    for e_idx, emp in enumerate(employees):
        ms = emp["min_hours_per_week"] // SHIFT_HOURS
        sf = model.new_int_var(0, 7, f"msf_{e_idx}")
        model.add(sf >= ms - emp_counts[e_idx])
        min_sf.append(sf)

    night_ex = []
    for e_idx in range(n_emp):
        ni_idx = [s for s in range(n_shift) if shifts[s]["shift_name"] == "night"]
        nc = model.new_int_var(0, 7, f"nc_{e_idx}")
        model.add(nc == sum(x[e_idx, s] for s in ni_idx))
        ex = model.new_int_var(0, 7, f"nex_{e_idx}")
        model.add(ex >= nc - 2)
        night_ex.append(ex)

    tmiss = []
    tr_emps = [e for e in range(n_emp) if "training" in employees[e]["skills"]]
    for d_idx in range(7):
        ds = [d_idx * 3 + off for off in range(3) if d_idx * 3 + off < n_shift]
        ta = [x[e, s] for e in tr_emps for s in ds]
        m = model.new_bool_var(f"tm_{d_idx}")
        model.add(sum(ta) >= 1).only_enforce_if(m.Not())
        model.add(sum(ta) == 0).only_enforce_if(m)
        tmiss.append(m)

    model.minimize(gap * 4 + sum(min_sf) * 5 + sum(night_ex) * 5 + sum(tmiss) * 3)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVER_TIME_LIMIT
    solver.parameters.num_workers = 4
    status = solver.solve(model)

    assignments = {}
    info = {"wall_time": round(solver.wall_time, 2), "timestamp": timestamp}

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for e in range(n_emp):
            for s in range(n_shift):
                assignments[(e, s)] = solver.value(x[e, s])
        info["status"] = "OPTIMAL" if status == cp_model.OPTIMAL else "FEASIBLE"
        info["objective"] = solver.objective_value
        log.info(f"  解探索成功: {info['status']}, objective={info['objective']}, time={info['wall_time']}s")
    else:
        info["status"] = "INFEASIBLE"
        log.error("  INFEASIBLE — 解が見つかりませんでした")

    return assignments, info


# ─── Step 5: 結果検証 ───

def verify(assignments: dict, employees: list[dict], shifts: list[dict], info: dict) -> dict:
    log.info("Step 5: 結果検証")
    n_emp = len(employees)
    n_shift = len(shifts)

    if info["status"] == "INFEASIBLE":
        return {"feasible": False, "reason": "solver returned INFEASIBLE"}

    emp_shifts = {i: [] for i in range(n_emp)}
    for (e, s), val in assignments.items():
        if val == 1:
            emp_shifts[e].append(s)

    # HC check
    hc_violations = 0
    for s_idx, sh in enumerate(shifts):
        assigned = sum(1 for e in range(n_emp) if assignments.get((e, s_idx), 0) == 1)
        if assigned != sh["required_count"]:
            hc_violations += 1
            log.warning(f"  HC1違反: {sh['day']} {sh['shift_name']}: {assigned}/{sh['required_count']}")

    # Anomaly: someone assigned > 5 shifts
    for e_idx, emp in enumerate(employees):
        if len(emp_shifts[e_idx]) > 6:
            log.warning(f"  異常: {emp['name']}に{len(emp_shifts[e_idx])}シフト割当")

    # Hours distribution
    hours = [len(emp_shifts[e]) * SHIFT_HOURS for e in range(n_emp)]
    mean_h = sum(hours) / len(hours)
    std_h = (sum((h - mean_h) ** 2 for h in hours) / len(hours)) ** 0.5

    result = {
        "feasible": hc_violations == 0,
        "hc_violations": hc_violations,
        "hours_std": round(std_h, 2),
        "hours_range": f"{min(hours)}-{max(hours)}h",
        "total_assigned": sum(len(emp_shifts[e]) for e in range(n_emp)),
    }

    if result["feasible"]:
        log.info(f"  検証OK: feasible, hours={result['hours_range']}, std={result['hours_std']}h")
    else:
        log.error(f"  検証NG: {hc_violations}件のハード制約違反")

    return result


# ─── Step 6: 出力 ───

def export(assignments: dict, employees: list[dict], shifts: list[dict], info: dict, quality: dict):
    log.info("Step 6: 結果出力")
    n_emp = len(employees)

    # シフト表をCSV出力
    output_file = RESULTS_DIR / f"schedule_{timestamp}.csv"
    with open(output_file, "w", newline="") as f:
        writer = csv.writer(f)
        header = ["employee_id", "name"] + [f"{sh['day']}_{sh['shift_name']}" for sh in shifts]
        writer.writerow(header)
        for e_idx, emp in enumerate(employees):
            row = [emp["employee_id"], emp["name"]]
            for s_idx in range(len(shifts)):
                row.append("*" if assignments.get((e_idx, s_idx), 0) == 1 else "")
            writer.writerow(row)

    # メタデータ出力
    meta_file = RESULTS_DIR / f"meta_{timestamp}.json"
    with open(meta_file, "w") as f:
        json.dump({**info, **quality}, f, indent=2, ensure_ascii=False, default=str)

    log.info(f"  シフト表: {output_file}")
    log.info(f"  メタデータ: {meta_file}")

    # 古い結果の削除
    all_schedules = sorted(RESULTS_DIR.glob("schedule_*.csv"), reverse=True)
    for old in all_schedules[HISTORY_KEEP:]:
        old.unlink()
        log.info(f"  古い結果を削除: {old.name}")

    return output_file


# ─── メイン ───

def main():
    log.info("=" * 50)
    log.info("週次シフト最適化パイプライン開始")
    log.info("=" * 50)

    # Step 1
    employees, shifts = load_data()

    # Step 2
    issues = validate_data(employees, shifts)
    if issues["critical"]:
        log.error("致命的な問題が見つかりました。中断します。")
        log.error("担当者に通知してください。")
        sys.exit(1)

    # Step 4
    assignments, info = optimize(employees, shifts)

    # Step 5
    quality = verify(assignments, employees, shifts, info)

    if not quality["feasible"]:
        log.error("Infeasible — フォールバック: 前回の結果を確認してください")
        # 本番では前回の解をロードするか人間にエスカレーション
        sys.exit(2)

    # Step 6
    output_file = export(assignments, employees, shifts, info, quality)

    log.info("=" * 50)
    log.info(f"完了: {output_file}")
    log.info("=" * 50)


if __name__ == "__main__":
    main()
