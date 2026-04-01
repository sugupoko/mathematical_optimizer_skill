"""ITSMチケットアサイン最適化テンプレート。

動的なチケット割当問題をCP-SATソルバーで解くためのテンプレート。
ITSMインシデント管理、Jiraタスク割当、カスタマーサポート振り分けなど、
「どのチケットを誰に割り当てるか」を決める問題全般に適用できる。

以下の機能を含む:
  - LLMベースの解決時間推定（過去履歴→カテゴリ平均→デフォルトのフォールバック）
  - 滞留検知（正常/警告/危険/ブロック の4段階）
  - ティア階層制約（L1/L2/L3）
  - ブロック状態の扱い（スロット消費 or 解放）
  - 公平性を考慮した目的関数
  - 再アサイン候補の検出

使い方:
  1. このファイルをコピーして問題に合わせて修正
  2. チケット・エンジニアデータを自分の環境に合わせる
  3. ティア階層・スキル要件を実際の組織構造に合わせる
  4. evaluate_assignment() で解の品質を必ず検証する

典型的な利用フロー::

    estimator = LLMEstimator(history_records)
    eng_states = build_engineer_state(engineers, assigned_tickets)
    assignments, info = solve_ticket_assignment(
        new_tickets, eng_states, estimator, tiers_can_handle
    )
    metrics = evaluate_assignment(assignments, new_tickets, eng_states, estimator)
"""

from __future__ import annotations

import logging
import math
import statistics
from typing import Any

from ortools.sat.python import cp_model

logger = logging.getLogger(__name__)


# ===========================================================================
# 1. LLM推定: 過去履歴から解決時間を推定する
# ===========================================================================


class LLMEstimator:
    """過去の対応履歴からチケット解決時間を推定する。

    実際のLLM APIを呼ぶ代わりに、履歴データの統計で推定する。
    LLMテキスト分析を組み込む場合は estimate() を拡張する。

    フォールバックチェーン:
      1. 個人履歴（スキル×エンジニア）≥3件 → 信頼度 0.7-0.9
      2. 個人履歴 1-2件 → 信頼度 0.4
      3. カテゴリ平均 → 信頼度 0.3
      4. 優先度別デフォルト → 信頼度 0.1

    Attributes:
        history: 生の履歴レコードリスト
        personal_stats: {(skill, engineer_id): [resolution_hours, ...]}
        category_stats: {skill: [resolution_hours, ...]}
    """

    # 優先度別のデフォルト解決時間（時間）
    DEFAULT_BY_PRIORITY: dict[str, float] = {
        "P1": 4.0,
        "P2": 8.0,
        "P3": 24.0,
        "P4": 72.0,
    }

    def __init__(self, history_records: list[dict]) -> None:
        """履歴レコードから統計情報を構築する。

        Args:
            history_records: 過去の対応履歴。各要素は以下の構造::

                {
                    "ticket_id": "T-001",
                    "skill": "network",
                    "engineer_id": "E-01",
                    "resolution_hours": 3.5,
                    "priority": "P2",
                    "experience_years": 5,
                }
        """
        self.history = history_records

        # 個人×スキル別の統計を構築
        self.personal_stats: dict[tuple[str, str], list[float]] = {}
        # カテゴリ（スキル）別の統計を構築
        self.category_stats: dict[str, list[float]] = {}

        for rec in history_records:
            skill = rec.get("skill", "unknown")
            eng_id = rec.get("engineer_id", "unknown")
            hours = rec.get("resolution_hours")
            if hours is None:
                continue

            # 個人統計
            key = (skill, eng_id)
            self.personal_stats.setdefault(key, []).append(hours)

            # カテゴリ統計
            self.category_stats.setdefault(skill, []).append(hours)

        logger.info(
            "LLMEstimator初期化: 個人統計=%d件, カテゴリ統計=%d件",
            len(self.personal_stats),
            len(self.category_stats),
        )

    def estimate(
        self, ticket: dict, engineer: dict | None = None
    ) -> dict[str, Any]:
        """チケットの残り解決時間を推定する。

        フォールバックチェーンに従い、利用可能な最も信頼度の高い
        データソースで推定する。

        Args:
            ticket: チケット情報::

                {
                    "ticket_id": "T-100",
                    "skill": "network",
                    "priority": "P2",
                    "elapsed_hours": 2.0,  # 経過時間（任意）
                }

            engineer: エンジニア情報（任意）::

                {
                    "id": "E-01",
                    "experience_years": 5,
                }

        Returns:
            推定結果::

                {
                    "remaining_h": 6.0,    # 残り推定時間
                    "confidence": 0.7,     # 信頼度 (0.0-1.0)
                    "method": "personal",  # 推定手法
                    "reasoning": "...",    # 推定根拠
                }
        """
        skill = ticket.get("skill", "unknown")
        priority = ticket.get("priority", "P3")
        elapsed_h = ticket.get("elapsed_hours", 0.0)

        eng_id = engineer.get("id") if engineer else None
        exp_years = engineer.get("experience_years", 3) if engineer else 3

        # --- フォールバックチェーン ---

        # 1. 個人履歴（スキル×エンジニア）
        if eng_id:
            personal_key = (skill, eng_id)
            personal_data = self.personal_stats.get(personal_key, [])

            if len(personal_data) >= 3:
                # 十分なデータあり
                median_h = statistics.median(personal_data)
                adjusted_h = self._adjust_by_experience(median_h, exp_years)
                remaining = max(0.0, adjusted_h - elapsed_h)
                # 件数に応じて信頼度を調整（3件→0.7, 10件以上→0.9）
                conf = min(0.9, 0.7 + 0.02 * (len(personal_data) - 3))
                return {
                    "remaining_h": round(remaining, 1),
                    "confidence": round(conf, 2),
                    "method": "personal",
                    "reasoning": (
                        f"{eng_id}の{skill}対応履歴{len(personal_data)}件の"
                        f"中央値{median_h:.1f}h（経験年数{exp_years}年で補正）"
                    ),
                }

            if len(personal_data) >= 1:
                # 少数データ
                avg_h = statistics.mean(personal_data)
                adjusted_h = self._adjust_by_experience(avg_h, exp_years)
                remaining = max(0.0, adjusted_h - elapsed_h)
                return {
                    "remaining_h": round(remaining, 1),
                    "confidence": 0.4,
                    "method": "personal_few",
                    "reasoning": (
                        f"{eng_id}の{skill}対応履歴{len(personal_data)}件の"
                        f"平均{avg_h:.1f}h（データ少のため信頼度低）"
                    ),
                }

        # 2. カテゴリ平均
        category_data = self.category_stats.get(skill, [])
        if category_data:
            median_h = statistics.median(category_data)
            adjusted_h = self._adjust_by_experience(median_h, exp_years)
            remaining = max(0.0, adjusted_h - elapsed_h)
            return {
                "remaining_h": round(remaining, 1),
                "confidence": 0.3,
                "method": "category",
                "reasoning": (
                    f"{skill}カテゴリ全体の中央値{median_h:.1f}h"
                    f"（{len(category_data)}件, 経験年数{exp_years}年で補正）"
                ),
            }

        # 3. 優先度別デフォルト
        default_h = self.DEFAULT_BY_PRIORITY.get(priority, 24.0)
        remaining = max(0.0, default_h - elapsed_h)
        return {
            "remaining_h": round(remaining, 1),
            "confidence": 0.1,
            "method": "default",
            "reasoning": (
                f"履歴なし。優先度{priority}のデフォルト{default_h:.1f}hを使用"
            ),
        }

    @staticmethod
    def _adjust_by_experience(base_hours: float, experience_years: int) -> float:
        """経験年数による補正。ベテランほど速く解決する。

        補正率: 1.0（0年） → 0.7（10年以上）

        Args:
            base_hours: 基準の解決時間
            experience_years: 経験年数

        Returns:
            補正後の解決時間
        """
        # 経験0年→補正なし、10年→30%短縮、それ以上は横ばい
        factor = max(0.7, 1.0 - 0.03 * min(experience_years, 10))
        return base_hours * factor


# ===========================================================================
# 2. 滞留検知
# ===========================================================================


def detect_stagnation(
    ticket: dict,
    now: float,
    llm_estimate: dict | None = None,
) -> dict[str, Any]:
    """チケットの滞留状態を判定する。

    経過時間と期待進捗を比較して、対応が遅れていないかを検知する。
    ブロック状態（外部要因による停止）と滞留（対応遅延）を区別する。

    Args:
        ticket: チケット情報::

            {
                "ticket_id": "T-100",
                "priority": "P2",
                "created_at": 1700000000.0,   # UNIXタイムスタンプ
                "status": "in_progress",       # or "blocked"
                "progress_pct": 30,            # 進捗率 0-100
                "blocked_reason": None,        # "vendor" / "customer" / etc.
            }

        now: 現在時刻（UNIXタイムスタンプ）
        llm_estimate: LLMEstimatorの推定結果（任意）。
            指定された場合、推定残り時間を考慮した閾値調整を行う。

    Returns:
        滞留判定結果::

            {
                "ticket_id": "T-100",
                "elapsed_h": 12.0,
                "expected_pct": 75.0,
                "actual_pct": 30,
                "gap": 45.0,
                "level": "critical",  # normal / warning / critical / blocked
                "reasoning": "...",
            }
    """
    ticket_id = ticket.get("ticket_id", "unknown")
    created_at = ticket.get("created_at", now)
    actual_pct = ticket.get("progress_pct", 0)
    status = ticket.get("status", "in_progress")
    blocked_reason = ticket.get("blocked_reason")
    priority = ticket.get("priority", "P3")

    elapsed_h = (now - created_at) / 3600.0

    # --- ブロック状態は滞留ではない ---
    if status == "blocked" or blocked_reason:
        return {
            "ticket_id": ticket_id,
            "elapsed_h": round(elapsed_h, 1),
            "expected_pct": 0.0,
            "actual_pct": actual_pct,
            "gap": 0.0,
            "level": "blocked",
            "reasoning": f"外部要因でブロック中: {blocked_reason or '理由不明'}",
        }

    # --- 期待解決時間の算出 ---
    if llm_estimate and llm_estimate.get("remaining_h") is not None:
        # LLM推定がある場合: 総推定時間 = 経過 + 残り
        total_estimated_h = elapsed_h + llm_estimate["remaining_h"]
    else:
        # デフォルト: 優先度別のSLA時間
        sla_hours = {"P1": 4.0, "P2": 8.0, "P3": 24.0, "P4": 72.0}
        total_estimated_h = sla_hours.get(priority, 24.0)

    # 期待進捗率（線形モデル）
    if total_estimated_h > 0:
        expected_pct = min(100.0, (elapsed_h / total_estimated_h) * 100.0)
    else:
        expected_pct = 100.0

    gap = max(0.0, expected_pct - actual_pct)

    # --- レベル判定 ---
    # gap: 期待進捗と実績の乖離（ポイント）
    if gap >= 50.0:
        level = "critical"
        reasoning = (
            f"期待進捗{expected_pct:.0f}%に対し実績{actual_pct}%。"
            f"乖離{gap:.0f}pt — 再アサインを検討"
        )
    elif gap >= 25.0:
        level = "warning"
        reasoning = (
            f"期待進捗{expected_pct:.0f}%に対し実績{actual_pct}%。"
            f"乖離{gap:.0f}pt — 注意が必要"
        )
    else:
        level = "normal"
        reasoning = f"進捗は正常範囲内（乖離{gap:.0f}pt）"

    return {
        "ticket_id": ticket_id,
        "elapsed_h": round(elapsed_h, 1),
        "expected_pct": round(expected_pct, 1),
        "actual_pct": actual_pct,
        "gap": round(gap, 1),
        "level": level,
        "reasoning": reasoning,
    }


# ===========================================================================
# 3. エンジニア状態の構築
# ===========================================================================


def build_engineer_state(
    engineers: list[dict],
    assigned_tickets: list[dict],
    *,
    release_blocked: bool = False,
) -> dict[str, dict]:
    """各エンジニアの現在の作業状態を構築する。

    割当済みチケットからスロット消費数・滞留状況を計算し、
    新規割当に使える調整済みスロット数を返す。

    Args:
        engineers: エンジニア情報のリスト::

            [
                {
                    "id": "E-01",
                    "name": "田中",
                    "skills": ["network", "server"],
                    "tier": "L2",
                    "max_slots": 5,
                    "experience_years": 8,
                },
            ]

        assigned_tickets: 現在割当済みのチケットリスト::

            [
                {
                    "ticket_id": "T-050",
                    "assigned_to": "E-01",
                    "status": "in_progress",
                    "stagnation_level": "critical",  # 任意
                    "blocked_reason": None,
                },
            ]

        release_blocked: Trueの場合、ブロック中チケットはスロットを
            消費しないとみなす（エンジニアが他の作業に取りかかれる前提）。

    Returns:
        エンジニアID → 状態辞書のマッピング::

            {
                "E-01": {
                    "id": "E-01",
                    "name": "田中",
                    "skills": ["network", "server"],
                    "tier": "L2",
                    "max_slots": 5,
                    "experience_years": 8,
                    "assigned_count": 4,
                    "blocked_count": 1,
                    "effective_slots": 3,       # ブロック解放考慮後
                    "stagnant_critical": 1,     # critical滞留チケット数
                    "adjusted_slots": 2,        # 滞留ペナルティ後
                },
            }
    """
    # エンジニアごとのチケット集計
    eng_tickets: dict[str, list[dict]] = {e["id"]: [] for e in engineers}
    for t in assigned_tickets:
        assignee = t.get("assigned_to")
        if assignee in eng_tickets:
            eng_tickets[assignee].append(t)

    result: dict[str, dict] = {}
    for eng in engineers:
        eid = eng["id"]
        tickets = eng_tickets.get(eid, [])
        max_slots = eng.get("max_slots", 5)

        # 割当数の集計
        assigned_count = len(tickets)
        blocked_count = sum(
            1
            for t in tickets
            if t.get("status") == "blocked" or t.get("blocked_reason")
        )

        # 有効スロット計算
        if release_blocked:
            # ブロック中チケットはスロットを消費しない
            consuming = assigned_count - blocked_count
        else:
            consuming = assigned_count
        effective_slots = max(0, max_slots - consuming)

        # 滞留(critical)チケット数
        stagnant_critical = sum(
            1 for t in tickets if t.get("stagnation_level") == "critical"
        )

        # 滞留ペナルティ: critical1件につき0.5スロット分のペナルティ
        # （滞留対応に注意を割かれるため実質的な処理能力が下がる）
        stagnant_penalty = math.ceil(stagnant_critical * 0.5)
        adjusted_slots = max(0, effective_slots - stagnant_penalty)

        result[eid] = {
            "id": eid,
            "name": eng.get("name", eid),
            "skills": eng.get("skills", []),
            "tier": eng.get("tier", "L1"),
            "max_slots": max_slots,
            "experience_years": eng.get("experience_years", 0),
            "assigned_count": assigned_count,
            "blocked_count": blocked_count,
            "effective_slots": effective_slots,
            "stagnant_critical": stagnant_critical,
            "adjusted_slots": adjusted_slots,
        }

    return result


# ===========================================================================
# 4. CP-SATソルバー: チケットアサイン最適化
# ===========================================================================


def solve_ticket_assignment(
    tickets_to_assign: list[dict],
    eng_states: dict[str, dict],
    estimator: LLMEstimator,
    tiers_can_handle: dict[str, list[str]],
    *,
    time_limit: int = 30,
    reassign_ids: set[str] | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """CP-SATでチケットの最適割当を求解する。

    スキル一致、ティア階層、スロット容量のハード制約を満たしつつ、
    スコア（スキル適合+SLA緊急度+経験+LLM信頼度）を最大化する。

    Args:
        tickets_to_assign: 割当対象チケットのリスト::

            [
                {
                    "ticket_id": "T-100",
                    "skill": "network",
                    "priority": "P1",
                    "required_tier": "L2",  # 最低必要ティア
                    "elapsed_hours": 2.0,
                },
            ]

        eng_states: build_engineer_state() の戻り値
        estimator: LLMEstimatorインスタンス
        tiers_can_handle: ティア→対応可能な最低ティアリスト::

            {
                "L1": ["L1"],
                "L2": ["L1", "L2"],
                "L3": ["L1", "L2", "L3"],
            }

        time_limit: ソルバーの最大実行時間（秒）
        reassign_ids: 再アサイン対象のチケットIDセット。
            指定された場合、これらのチケットにはボーナススコアを付与する。

    Returns:
        (assignments, solver_info) のタプル。

        assignments: {ticket_id: engineer_id}
        solver_info: ソルバーの実行情報::

            {
                "status": "OPTIMAL",
                "objective": 1234,
                "wall_time": 0.5,
                "num_variables": 100,
                "num_constraints": 50,
            }
    """
    if reassign_ids is None:
        reassign_ids = set()

    model = cp_model.CpModel()
    eng_list = list(eng_states.values())
    n_tickets = len(tickets_to_assign)
    n_engineers = len(eng_list)

    if n_tickets == 0 or n_engineers == 0:
        return {}, {"status": "TRIVIAL", "objective": 0, "wall_time": 0.0}

    # --- 決定変数 ---
    # x[t, e] = 1 ならチケットtをエンジニアeに割り当てる
    x: dict[tuple[int, int], Any] = {}
    for t_idx in range(n_tickets):
        for e_idx in range(n_engineers):
            x[t_idx, e_idx] = model.new_bool_var(f"x_{t_idx}_{e_idx}")

    # --- ハード制約 ---

    # HC1: 各チケットは最大1人に割当（割当しないことも許容）
    for t_idx in range(n_tickets):
        model.add(sum(x[t_idx, e_idx] for e_idx in range(n_engineers)) <= 1)

    # HC2: スキル一致 — エンジニアが必要スキルを持たない場合は割当禁止
    for t_idx, ticket in enumerate(tickets_to_assign):
        required_skill = ticket.get("skill", "")
        for e_idx, eng in enumerate(eng_list):
            if required_skill and required_skill not in eng.get("skills", []):
                model.add(x[t_idx, e_idx] == 0)

    # HC3: ティア制約 — チケットの必要ティア以上のエンジニアのみ割当可能
    tier_rank = {"L1": 1, "L2": 2, "L3": 3}
    for t_idx, ticket in enumerate(tickets_to_assign):
        required_tier = ticket.get("required_tier", "L1")
        req_rank = tier_rank.get(required_tier, 1)
        for e_idx, eng in enumerate(eng_list):
            eng_rank = tier_rank.get(eng.get("tier", "L1"), 1)
            if eng_rank < req_rank:
                model.add(x[t_idx, e_idx] == 0)

    # HC4: スロット容量 — エンジニアの調整済みスロットを超えない
    for e_idx, eng in enumerate(eng_list):
        capacity = eng.get("adjusted_slots", 0)
        model.add(
            sum(x[t_idx, e_idx] for t_idx in range(n_tickets)) <= capacity
        )

    # --- スコア計算（目的関数の係数） ---
    SCALE = 100  # CP-SATは整数のみなのでスケーリング

    # 優先度ボーナス: P1チケットの割当を強く優先
    priority_bonus = {"P1": 50, "P2": 30, "P3": 10, "P4": 0}

    # SLAクリティカルボーナス: 経過時間がSLAの80%を超えたら追加スコア
    sla_hours = {"P1": 4.0, "P2": 8.0, "P3": 24.0, "P4": 72.0}

    objective_terms = []

    for t_idx, ticket in enumerate(tickets_to_assign):
        ticket_priority = ticket.get("priority", "P3")
        elapsed_h = ticket.get("elapsed_hours", 0.0)
        ticket_sla = sla_hours.get(ticket_priority, 24.0)

        for e_idx, eng in enumerate(eng_list):
            score = 0

            # スキル適合スコア（基本スコア）
            required_skill = ticket.get("skill", "")
            if required_skill in eng.get("skills", []):
                score += 20

            # SLA緊急度: 期限が近いほど高スコア
            if ticket_sla > 0:
                urgency = min(1.0, elapsed_h / ticket_sla)
                score += int(urgency * 30)

            # 経験年数ボーナス
            exp = eng.get("experience_years", 0)
            score += min(10, exp)  # 最大10pt

            # LLM信頼度ボーナス: 推定精度が高い組み合わせを優先
            est = estimator.estimate(ticket, engineer=eng)
            confidence = est.get("confidence", 0.0)
            score += int(confidence * 10)

            # 優先度ボーナス
            score += priority_bonus.get(ticket_priority, 0)

            # SLAクリティカルボーナス（SLAの80%超過）
            if ticket_sla > 0 and elapsed_h / ticket_sla >= 0.8:
                score += 40

            # 再アサインボーナス（滞留検知で再アサイン対象となったチケット）
            if ticket.get("ticket_id") in reassign_ids:
                score += 25

            # 公平性ペナルティ: 既に多くのチケットを持つエンジニアを抑制
            load_ratio = eng.get("assigned_count", 0) / max(
                1, eng.get("max_slots", 5)
            )
            fairness_penalty = int(load_ratio * 15)
            score -= fairness_penalty

            # スケーリングして追加
            objective_terms.append(x[t_idx, e_idx] * score)

    # --- 目的関数: スコア合計を最大化 ---
    model.maximize(sum(objective_terms))

    # --- 求解 ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit

    status = solver.solve(model)
    status_name = solver.status_name(status)

    assignments: dict[str, str] = {}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for t_idx, ticket in enumerate(tickets_to_assign):
            for e_idx, eng in enumerate(eng_list):
                if solver.value(x[t_idx, e_idx]) == 1:
                    assignments[ticket["ticket_id"]] = eng["id"]

    solver_info = {
        "status": status_name,
        "objective": solver.objective_value if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else 0,
        "wall_time": round(solver.wall_time, 2),
        "num_variables": n_tickets * n_engineers,
        "num_constraints": model.proto.constraints.__len__() if hasattr(model.proto, "constraints") else -1,
    }

    logger.info(
        "ソルバー完了: status=%s, 割当=%d/%d, time=%.2fs",
        status_name,
        len(assignments),
        n_tickets,
        solver.wall_time,
    )

    return assignments, solver_info


# ===========================================================================
# 5. 評価関数
# ===========================================================================


def evaluate_assignment(
    assignments: dict[str, str],
    tickets: list[dict],
    eng_states: dict[str, dict],
    estimator: LLMEstimator,
) -> dict[str, Any]:
    """割当結果を多角的に評価する。

    Args:
        assignments: {ticket_id: engineer_id}
        tickets: 割当対象チケットのリスト
        eng_states: エンジニア状態辞書
        estimator: LLMEstimatorインスタンス

    Returns:
        評価指標::

            {
                "assigned": 8,           # 割当成功数
                "total": 10,             # 割当対象数
                "rate": 0.8,             # 割当率
                "hc_violations": 0,      # ハード制約違反数
                "avg_score": 65.3,       # 平均スコア
                "skill_match": 1.0,      # スキル一致率
                "by_priority": {"P1": {"total": 2, "assigned": 2}, ...},
                "sla_critical": 1,       # SLAクリティカル（80%超過）割当数
                "reassigned": 0,         # 再アサインされたチケット数
                "load_std": 0.5,         # 負荷の標準偏差（公平性指標）
            }
    """
    total = len(tickets)
    assigned = len(assignments)
    ticket_map = {t["ticket_id"]: t for t in tickets}

    # --- スキル一致チェック ---
    skill_matches = 0
    hc_violations = 0
    scores: list[float] = []
    sla_critical_count = 0
    reassigned_count = 0
    sla_hours = {"P1": 4.0, "P2": 8.0, "P3": 24.0, "P4": 72.0}

    # 優先度別集計
    by_priority: dict[str, dict[str, int]] = {}
    for t in tickets:
        p = t.get("priority", "P3")
        by_priority.setdefault(p, {"total": 0, "assigned": 0})
        by_priority[p]["total"] += 1

    for tid, eid in assignments.items():
        ticket = ticket_map.get(tid, {})
        eng = eng_states.get(eid, {})
        priority = ticket.get("priority", "P3")

        # 優先度別割当数
        if priority in by_priority:
            by_priority[priority]["assigned"] += 1

        # スキル一致
        required_skill = ticket.get("skill", "")
        if required_skill in eng.get("skills", []):
            skill_matches += 1
        else:
            hc_violations += 1

        # スコア計算（簡易版）
        est = estimator.estimate(ticket, engineer=eng)
        score = est.get("confidence", 0.0) * 100
        scores.append(score)

        # SLAクリティカル判定
        elapsed_h = ticket.get("elapsed_hours", 0.0)
        ticket_sla = sla_hours.get(priority, 24.0)
        if ticket_sla > 0 and elapsed_h / ticket_sla >= 0.8:
            sla_critical_count += 1

    # --- 負荷の公平性 ---
    load_values = []
    for eng in eng_states.values():
        max_s = max(1, eng.get("max_slots", 5))
        assigned_count = eng.get("assigned_count", 0)
        # この割当での追加分をカウント
        new_assigned = sum(1 for eid in assignments.values() if eid == eng["id"])
        load_values.append((assigned_count + new_assigned) / max_s)

    load_std = round(statistics.stdev(load_values), 2) if len(load_values) >= 2 else 0.0

    return {
        "assigned": assigned,
        "total": total,
        "rate": round(assigned / max(1, total), 2),
        "hc_violations": hc_violations,
        "avg_score": round(statistics.mean(scores), 1) if scores else 0.0,
        "skill_match": round(skill_matches / max(1, assigned), 2),
        "by_priority": by_priority,
        "sla_critical": sla_critical_count,
        "reassigned": reassigned_count,
        "load_std": load_std,
    }


# ===========================================================================
# 6. 再アサイン候補の検出
# ===========================================================================


def find_reassign_candidates(
    assigned_tickets: list[dict],
    now: float,
) -> list[dict]:
    """滞留がcriticalかつブロックされていないチケットを再アサイン候補として返す。

    Args:
        assigned_tickets: 現在割当済みのチケットリスト。
            各チケットには stagnation_level と blocked_reason が含まれる想定。
        now: 現在時刻（UNIXタイムスタンプ）

    Returns:
        再アサイン候補のリスト::

            [
                {
                    "ticket_id": "T-050",
                    "assigned_to": "E-01",
                    "stagnation_level": "critical",
                    "elapsed_h": 12.5,
                    "reason": "進捗が大幅に遅延（critical）",
                },
            ]
    """
    candidates = []
    for ticket in assigned_tickets:
        stag_level = ticket.get("stagnation_level", "normal")
        blocked_reason = ticket.get("blocked_reason")
        status = ticket.get("status", "in_progress")

        # ブロック中は再アサインの対象外（外部要因であり担当者の責任ではない）
        if status == "blocked" or blocked_reason:
            continue

        if stag_level == "critical":
            created_at = ticket.get("created_at", now)
            elapsed_h = (now - created_at) / 3600.0
            candidates.append({
                "ticket_id": ticket.get("ticket_id", "unknown"),
                "assigned_to": ticket.get("assigned_to", "unknown"),
                "stagnation_level": stag_level,
                "elapsed_h": round(elapsed_h, 1),
                "reason": "進捗が大幅に遅延（critical）",
            })

    logger.info("再アサイン候補: %d件", len(candidates))
    return candidates


# ===========================================================================
# メインブロック: 最小使用例
# ===========================================================================


if __name__ == "__main__":
    import time

    logging.basicConfig(level=logging.INFO)

    # --- サンプルデータ ---
    # 過去の対応履歴
    history = [
        {"skill": "network", "engineer_id": "E-01", "resolution_hours": 3.0, "priority": "P2"},
        {"skill": "network", "engineer_id": "E-01", "resolution_hours": 4.5, "priority": "P2"},
        {"skill": "network", "engineer_id": "E-01", "resolution_hours": 3.5, "priority": "P2"},
        {"skill": "server", "engineer_id": "E-02", "resolution_hours": 6.0, "priority": "P2"},
        {"skill": "server", "engineer_id": "E-02", "resolution_hours": 5.0, "priority": "P3"},
        {"skill": "database", "engineer_id": "E-03", "resolution_hours": 8.0, "priority": "P1"},
    ]

    # エンジニア一覧
    engineers = [
        {"id": "E-01", "name": "田中", "skills": ["network", "server"], "tier": "L2", "max_slots": 5, "experience_years": 8},
        {"id": "E-02", "name": "佐藤", "skills": ["server", "database"], "tier": "L2", "max_slots": 5, "experience_years": 5},
        {"id": "E-03", "name": "鈴木", "skills": ["network", "database", "server"], "tier": "L3", "max_slots": 3, "experience_years": 12},
        {"id": "E-04", "name": "高橋", "skills": ["network"], "tier": "L1", "max_slots": 6, "experience_years": 1},
    ]

    # 現在割当済みのチケット
    now = time.time()
    assigned_tickets = [
        {"ticket_id": "T-001", "assigned_to": "E-01", "status": "in_progress", "stagnation_level": "normal"},
        {"ticket_id": "T-002", "assigned_to": "E-01", "status": "blocked", "blocked_reason": "vendor"},
        {"ticket_id": "T-003", "assigned_to": "E-02", "status": "in_progress", "stagnation_level": "critical",
         "created_at": now - 36000},  # 10時間前
    ]

    # 新規割当対象チケット
    new_tickets = [
        {"ticket_id": "T-010", "skill": "network", "priority": "P1", "required_tier": "L2", "elapsed_hours": 1.0},
        {"ticket_id": "T-011", "skill": "server", "priority": "P2", "required_tier": "L1", "elapsed_hours": 0.0},
        {"ticket_id": "T-012", "skill": "database", "priority": "P3", "required_tier": "L2", "elapsed_hours": 5.0},
        {"ticket_id": "T-013", "skill": "network", "priority": "P2", "required_tier": "L1", "elapsed_hours": 6.5},
    ]

    # ティア階層定義
    tiers_can_handle = {
        "L1": ["L1"],
        "L2": ["L1", "L2"],
        "L3": ["L1", "L2", "L3"],
    }

    # --- 実行 ---
    print("=" * 60)
    print("チケットアサイン最適化 — サンプル実行")
    print("=" * 60)

    # 1. 推定器の構築
    estimator = LLMEstimator(history)

    # 2. 推定のデモ
    est = estimator.estimate(new_tickets[0], engineer=engineers[0])
    print(f"\n[推定] T-010 → E-01: 残り{est['remaining_h']}h (信頼度{est['confidence']}, {est['method']})")

    # 3. 滞留検知のデモ
    stag = detect_stagnation(
        {"ticket_id": "T-003", "priority": "P2", "created_at": now - 36000,
         "status": "in_progress", "progress_pct": 20},
        now,
    )
    print(f"[滞留] T-003: {stag['level']} — {stag['reasoning']}")

    # 4. エンジニア状態の構築
    eng_states = build_engineer_state(engineers, assigned_tickets, release_blocked=True)
    for eid, state in eng_states.items():
        print(f"[状態] {state['name']}: 割当{state['assigned_count']}, 調整済スロット{state['adjusted_slots']}")

    # 5. 再アサイン候補の検出
    reassign_cands = find_reassign_candidates(assigned_tickets, now)
    reassign_ids = {c["ticket_id"] for c in reassign_cands}
    print(f"\n[再アサイン候補] {len(reassign_cands)}件: {[c['ticket_id'] for c in reassign_cands]}")

    # 6. 最適割当の求解
    assignments, info = solve_ticket_assignment(
        new_tickets, eng_states, estimator, tiers_can_handle,
        time_limit=10, reassign_ids=reassign_ids,
    )
    print(f"\n[割当結果] {info['status']} (目的関数値={info['objective']}, 時間={info['wall_time']}s)")
    for tid, eid in assignments.items():
        eng_name = eng_states[eid]["name"]
        print(f"  {tid} → {eid} ({eng_name})")

    # 7. 評価
    metrics = evaluate_assignment(assignments, new_tickets, eng_states, estimator)
    print(f"\n[評価]")
    print(f"  割当率: {metrics['rate']*100:.0f}% ({metrics['assigned']}/{metrics['total']})")
    print(f"  スキル一致率: {metrics['skill_match']*100:.0f}%")
    print(f"  HC違反: {metrics['hc_violations']}件")
    print(f"  負荷標準偏差: {metrics['load_std']}")
    print(f"  優先度別: {metrics['by_priority']}")
