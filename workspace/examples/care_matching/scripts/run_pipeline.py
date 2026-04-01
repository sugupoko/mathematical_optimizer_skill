#!/usr/bin/env python3
"""介護マッチング最適化 — 本番パイプライン

実行頻度: 月次 or 都度（利用者/ヘルパーの変更時）
入力:     data/care_receivers.csv, data/caregivers.csv,
          data/compatibility_history.csv, data/constraints.csv
出力:     results/matching_YYYYMMDD_HHMMSS.csv + meta JSON
ログ:     log/run_YYYYMMDD_HHMMSS.log
"""

import csv
import json
import logging
import os
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
SOLVER_TIME_LIMIT = 60
HISTORY_KEEP = 6  # 半年分

# 区の隣接関係
ADJACENT = {
    "杉並区": {"世田谷区", "渋谷区", "新宿区", "中野区"},
    "世田谷区": {"杉並区", "渋谷区"},
    "渋谷区": {"杉並区", "世田谷区", "新宿区"},
    "新宿区": {"杉並区", "渋谷区", "中野区"},
    "中野区": {"杉並区", "新宿区"},
}

# NGペア
NG_PAIRS = {("R004", "C004")}

# 資格ランク
QUAL_RANK = {"介護福祉士": 3, "初任者研修": 2, "any": 1}


# ═══════════════════════════════════════════
# 1. データ読み込み
# ═══════════════════════════════════════════
def load_csv(filename):
    with open(DATA_DIR / filename, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_data():
    receivers_raw = load_csv("care_receivers.csv")
    caregivers_raw = load_csv("caregivers.csv")
    history_raw = load_csv("compatibility_history.csv")

    R = {}
    for r in receivers_raw:
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
    for c in caregivers_raw:
        C[c["caregiver_id"]] = {
            "name": c["name"],
            "gender": c["gender"],
            "qualification": c["qualification"],
            "district": c["district"],
            "available_days": set(c["available_days"].split(",")),
            "max_clients": int(c["max_clients"]),
            "experience_years": int(c["experience_years"]),
        }

    HIST = {}
    for h in history_raw:
        HIST[(h["receiver_id"], h["caregiver_id"])] = int(h["satisfaction_score"])

    return R, C, HIST


# ═══════════════════════════════════════════
# 2. 制約チェック・互換性スコア
# ═══════════════════════════════════════════
def qual_meets(caregiver_qual, required_qual):
    if required_qual == "any":
        return True
    return QUAL_RANK.get(caregiver_qual, 0) >= QUAL_RANK.get(required_qual, 0)


def check_hard(rid, cid, R, C):
    r = R[rid]
    c = C[cid]
    violations = []
    if r["service_type"] in ("身体介護", "both") and c["qualification"] != "介護福祉士":
        if r["required_qualification"] == "介護福祉士":
            violations.append("HC01")
        elif r["service_type"] == "身体介護":
            violations.append("HC01")
    if r["care_level"] >= 4 and c["experience_years"] < 3:
        violations.append("HC02")
    if len(r["preferred_days"] & c["available_days"]) == 0:
        violations.append("HC04")
    if (rid, cid) in NG_PAIRS:
        violations.append("HC05")
    return violations


def is_feasible(rid, cid, R, C):
    return len(check_hard(rid, cid, R, C)) == 0


def compatibility_score(rid, cid, R, C, HIST):
    r = R[rid]
    c = C[cid]
    score = 0.0
    if (rid, cid) in HIST:
        score += HIST[(rid, cid)] * 5
    if r["district"] == c["district"]:
        score += 20
    elif c["district"] in ADJACENT.get(r["district"], set()):
        score += 10
    if r["preferred_gender"] == "any":
        score += 15
    elif r["preferred_gender"] == c["gender"]:
        score += 15
    overlap = len(r["preferred_days"] & c["available_days"])
    total = len(r["preferred_days"])
    if total > 0:
        score += 15 * (overlap / total)
    if qual_meets(c["qualification"], r["required_qualification"]):
        score += 10
    if r["care_level"] >= 4:
        if c["experience_years"] >= 10:
            score += 10
        elif c["experience_years"] >= 5:
            score += 5
    elif r["care_level"] >= 3:
        if c["experience_years"] >= 5:
            score += 5
    return round(score, 2)


# ═══════════════════════════════════════════
# 3. バリデーション
# ═══════════════════════════════════════════
def validate(R, C, HIST):
    errors = []
    warnings = []

    if not R:
        errors.append("利用者データが空です")
    if not C:
        errors.append("ヘルパーデータが空です")

    total_capacity = sum(c["max_clients"] for c in C.values())
    if total_capacity < len(R):
        errors.append(f"受入容量不足: {total_capacity}名分 < 利用者{len(R)}名")

    kaigo_needed = sum(1 for r in R.values()
                       if r["required_qualification"] == "介護福祉士")
    kaigo_supply = sum(1 for c in C.values()
                       if c["qualification"] == "介護福祉士")
    if kaigo_supply < kaigo_needed:
        warnings.append(f"介護福祉士不足の可能性: 必要{kaigo_needed}名, 供給{kaigo_supply}名")

    RIDS = sorted(R.keys())
    CIDS = sorted(C.keys())
    feasible_count = sum(1 for rid in RIDS for cid in CIDS
                         if is_feasible(rid, cid, R, C))
    if feasible_count == 0:
        errors.append("実行可能なペアが1つもありません")
    elif feasible_count < len(RIDS):
        warnings.append(f"実行可能ペア数が少ない ({feasible_count}/{len(RIDS)*len(CIDS)})")

    for w in warnings:
        logger.warning(w)
    return errors


# ═══════════════════════════════════════════
# 4. CP-SAT改善版ソルバー
# ═══════════════════════════════════════════
def solve(R, C, HIST):
    RIDS = sorted(R.keys())
    CIDS = sorted(C.keys())

    # 互換性スコア事前計算
    SCORES = {}
    for rid in RIDS:
        for cid in CIDS:
            SCORES[(rid, cid)] = compatibility_score(rid, cid, R, C, HIST)

    model = cp_model.CpModel()

    x = {}
    for rid in RIDS:
        for cid in CIDS:
            x[(rid, cid)] = model.NewBoolVar(f"x_{rid}_{cid}")

    # 各利用者は最大1名のヘルパー
    for rid in RIDS:
        model.Add(sum(x[(rid, cid)] for cid in CIDS) <= 1)

    # 各ヘルパーはmax_clients以下
    for cid in CIDS:
        model.Add(sum(x[(rid, cid)] for rid in RIDS) <= C[cid]["max_clients"])

    # ハード制約
    for rid in RIDS:
        for cid in CIDS:
            if not is_feasible(rid, cid, R, C):
                model.Add(x[(rid, cid)] == 0)

    # 目的関数
    obj_terms = []

    # 互換性スコア
    for rid in RIDS:
        for cid in CIDS:
            score_int = int(SCORES[(rid, cid)] * 100)
            obj_terms.append(score_int * x[(rid, cid)])

    # マッチボーナス
    for rid in RIDS:
        obj_terms.append(5000 * sum(x[(rid, cid)] for cid in CIDS))

    # 継続ボーナス（満足度5）
    for (rid, cid), score in HIST.items():
        if score == 5 and rid in R and cid in C:
            if is_feasible(rid, cid, R, C):
                obj_terms.append(3000 * x[(rid, cid)])

    # 性別一致ボーナス
    for rid in RIDS:
        if R[rid]["preferred_gender"] != "any":
            for cid in CIDS:
                if C[cid]["gender"] == R[rid]["preferred_gender"]:
                    obj_terms.append(800 * x[(rid, cid)])

    # 地区一致ボーナス
    for rid in RIDS:
        for cid in CIDS:
            if R[rid]["district"] == C[cid]["district"]:
                obj_terms.append(600 * x[(rid, cid)])
            elif C[cid]["district"] in ADJACENT.get(R[rid]["district"], set()):
                obj_terms.append(300 * x[(rid, cid)])

    # 経験ボーナス（要介護5）
    for rid in RIDS:
        if R[rid]["care_level"] == 5:
            for cid in CIDS:
                if C[cid]["experience_years"] >= 10:
                    obj_terms.append(500 * x[(rid, cid)])

    # 公平性: 最大負荷ペナルティ
    loads = {}
    for cid in CIDS:
        loads[cid] = model.NewIntVar(0, C[cid]["max_clients"], f"load_{cid}")
        model.Add(loads[cid] == sum(x[(rid, cid)] for rid in RIDS))
    max_load = model.NewIntVar(0, max(C[cid]["max_clients"] for cid in CIDS), "max_load")
    for cid in CIDS:
        model.Add(max_load >= loads[cid])
    obj_terms.append(-1000 * max_load)

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

    return assignment, SCORES


# ═══════════════════════════════════════════
# 5. 結果検証
# ═══════════════════════════════════════════
def verify(assignment, R, C, HIST, SCORES):
    RIDS = sorted(R.keys())
    CIDS = sorted(C.keys())
    matched = {rid: cid for rid, cid in assignment.items() if cid is not None}

    # HC違反
    hc_violations = 0
    for rid, cid in matched.items():
        v = check_hard(rid, cid, R, C)
        hc_violations += len(v)

    # 互換性
    scores = [SCORES[(rid, cid)] for rid, cid in matched.items()]
    avg_compat = round(sum(scores) / len(scores), 2) if scores else 0

    # 性別一致
    gender_ok = 0
    gender_applicable = 0
    for rid, cid in matched.items():
        if R[rid]["preferred_gender"] != "any":
            gender_applicable += 1
            if R[rid]["preferred_gender"] == C[cid]["gender"]:
                gender_ok += 1
    gender_rate = round(gender_ok / gender_applicable, 4) if gender_applicable else 1.0

    # 地区一致
    district_same = sum(1 for rid, cid in matched.items()
                        if R[rid]["district"] == C[cid]["district"])
    district_rate = round(district_same / len(matched), 4) if matched else 0

    # 継続維持
    s5_pairs = [(rid, cid) for (rid, cid), s in HIST.items() if s == 5]
    continuity_kept = sum(1 for rid, cid in s5_pairs if assignment.get(rid) == cid)

    # 負荷分布
    load = defaultdict(int)
    for cid in CIDS:
        load[cid] = 0
    for rid, cid in matched.items():
        load[cid] += 1
    loads = list(load.values())
    avg_load = sum(loads) / len(loads) if loads else 0
    load_std = round((sum((x - avg_load) ** 2 for x in loads) / len(loads)) ** 0.5, 4) if loads else 0

    return {
        "match_count": len(matched),
        "total_receivers": len(RIDS),
        "match_rate": round(len(matched) / len(RIDS), 4) if RIDS else 0,
        "hc_violations": hc_violations,
        "avg_compatibility": avg_compat,
        "total_score": round(sum(scores), 2),
        "gender_match_rate": gender_rate,
        "district_same_rate": district_rate,
        "continuity_kept": continuity_kept,
        "continuity_total": len(s5_pairs),
        "workload_std": load_std,
        "workload_distribution": dict(load),
    }


# ═══════════════════════════════════════════
# 6. 出力
# ═══════════════════════════════════════════
def export_results(assignment, meta, R, C, SCORES):
    # CSV
    csv_path = RESULTS_DIR / f"matching_{TIMESTAMP}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["receiver_id", "receiver_name", "care_level", "district",
                         "caregiver_id", "caregiver_name", "compatibility"])
        for rid in sorted(assignment.keys()):
            cid = assignment[rid]
            if cid:
                writer.writerow([
                    rid, R[rid]["name"], R[rid]["care_level"], R[rid]["district"],
                    cid, C[cid]["name"], SCORES[(rid, cid)],
                ])
            else:
                writer.writerow([rid, R[rid]["name"], R[rid]["care_level"],
                                 R[rid]["district"], "", "未割当", 0])
    logger.info(f"マッチング表出力: {csv_path}")

    # JSON メタデータ
    json_path = RESULTS_DIR / f"meta_{TIMESTAMP}.json"
    meta["timestamp"] = TIMESTAMP
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    logger.info(f"メタデータ出力: {json_path}")

    # 古いファイルの削除
    for pattern in ["matching_*.csv", "meta_*.json"]:
        files = sorted(RESULTS_DIR.glob(pattern))
        if len(files) > HISTORY_KEEP:
            for old in files[:-HISTORY_KEEP]:
                old.unlink()
                logger.info(f"古いファイル削除: {old.name}")


# ═══════════════════════════════════════════
# 7. フォールバック: 貪欲法
# ═══════════════════════════════════════════
def solve_greedy_fallback(R, C, HIST):
    logger.warning("フォールバック: 貪欲法を使用")
    RIDS = sorted(R.keys())
    CIDS = sorted(C.keys())
    SCORES = {}
    for rid in RIDS:
        for cid in CIDS:
            SCORES[(rid, cid)] = compatibility_score(rid, cid, R, C, HIST)

    assignment = {}
    load = defaultdict(int)
    sorted_rids = sorted(RIDS, key=lambda rid: -R[rid]["care_level"])
    for rid in sorted_rids:
        best_cid = None
        best_score = -1
        for cid in CIDS:
            if load[cid] >= C[cid]["max_clients"]:
                continue
            if not is_feasible(rid, cid, R, C):
                continue
            s = SCORES[(rid, cid)]
            if s > best_score:
                best_score = s
                best_cid = cid
        if best_cid is not None:
            assignment[rid] = best_cid
            load[best_cid] += 1
        else:
            assignment[rid] = None
    return assignment, SCORES


# ═══════════════════════════════════════════
# メイン
# ═══════════════════════════════════════════
def main():
    logger.info("=" * 50)
    logger.info("介護マッチング最適化パイプライン 開始")
    logger.info("=" * 50)

    # Step 1: データ読み込み
    logger.info("[Step 1] データ読み込み")
    try:
        R, C, HIST = load_data()
    except FileNotFoundError as e:
        logger.error(f"データファイルが見つかりません: {e}")
        sys.exit(1)
    logger.info(f"  利用者: {len(R)}名, ヘルパー: {len(C)}名, 履歴: {len(HIST)}件")

    # Step 2: バリデーション
    logger.info("[Step 2] バリデーション")
    errors = validate(R, C, HIST)
    if errors:
        for err in errors:
            logger.error(f"  致命的エラー: {err}")
        logger.error("パイプライン中断")
        sys.exit(1)
    logger.info("  バリデーション OK")

    # Step 3: 最適化実行
    logger.info(f"[Step 3] CP-SAT最適化 (time_limit={SOLVER_TIME_LIMIT}s)")
    assignment, SCORES = solve(R, C, HIST)

    # フォールバック
    if all(v is None for v in assignment.values()):
        logger.warning("CP-SATが解を返しませんでした。フォールバック実行。")
        assignment, SCORES = solve_greedy_fallback(R, C, HIST)

    # Step 4: 結果検証
    logger.info("[Step 4] 結果検証")
    meta = verify(assignment, R, C, HIST, SCORES)
    logger.info(f"  マッチ: {meta['match_count']}/{meta['total_receivers']}名")
    logger.info(f"  HC違反: {meta['hc_violations']}件")
    logger.info(f"  平均互換性: {meta['avg_compatibility']}")
    logger.info(f"  性別一致率: {meta['gender_match_rate']:.1%}")
    logger.info(f"  地区一致率: {meta['district_same_rate']:.1%}")
    logger.info(f"  継続維持: {meta['continuity_kept']}/{meta['continuity_total']}ペア")
    logger.info(f"  負荷偏差: {meta['workload_std']}")

    if meta["hc_violations"] > 0:
        logger.error("ハード制約違反あり。結果を確認してください。")

    # Step 5: 出力
    logger.info("[Step 5] 結果出力")
    export_results(assignment, meta, R, C, SCORES)

    logger.info("=" * 50)
    logger.info("介護マッチング最適化パイプライン 完了")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
