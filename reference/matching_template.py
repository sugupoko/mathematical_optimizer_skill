"""マッチング（割当）問題の定式化テンプレート。

双方に選好がある二部マッチング問題を対象とする。
介護（利用者×ヘルパー）、求人（求職者×企業）、教育（生徒×家庭教師）など、
「誰を誰に割り当てるか」を決める問題全般に適用できる。

2つのアプローチを提供する:
  - Gale-Shapley: 安定マッチング（ブロッキングペアなし）を保証。1対1限定。
  - CP-SAT: 複雑な制約・目的関数に対応。1対多も可能。安定性は近似。

使い方:
  1. このファイルをコピーして問題に合わせて修正
  2. 選好リストまたは互換性スコアを自分のデータに合わせる
  3. CP-SATを使う場合、ハード制約・ソフト目的を問題に応じて設計する
  4. evaluate_matching() で解の品質を必ず検証する

典型的な利用フロー::

    # Gale-Shapley（安定性重視）
    matches = gale_shapley(proposer_prefs, receiver_prefs)

    # CP-SAT（制約・最適性重視）
    result = solve_matching_cpsat(proposers, receivers, compatibility, ...)
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

from ortools.sat.python import cp_model

logger = logging.getLogger(__name__)


# ===========================================================================
# 1. Gale-Shapley 安定マッチング
# ===========================================================================


def gale_shapley(
    proposer_prefs: dict[str, list[str]],
    receiver_prefs: dict[str, list[str]],
) -> dict[str, str]:
    """Gale-Shapley安定マッチングアルゴリズム。

    提案側が順に希望を出し、受入側が最良を選ぶ。
    結果は「安定」= ブロッキングペアが存在しない。

    計算量: O(n²)
    保証: 提案側最適（提案側にとって最良の安定マッチング）

    Args:
        proposer_prefs: 提案側の選好リスト {proposer_id: [receiver_id, ...]}（希望順）
        receiver_prefs: 受入側の選好リスト {receiver_id: [proposer_id, ...]}（希望順）

    Returns:
        マッチング結果 {proposer_id: receiver_id}

    Raises:
        ValueError: 選好リストに不整合がある場合
    """
    # --- 入力バリデーション ---
    if not proposer_prefs:
        logger.warning("提案側の選好リストが空です")
        return {}
    if not receiver_prefs:
        logger.warning("受入側の選好リストが空です")
        return {}

    # 受入側の選好順位を辞書化（O(1)で比較するため）
    # receiver_rank[r][p] = pのrにとっての順位（小さいほど好ましい）
    receiver_rank: dict[str, dict[str, int]] = {}
    for r_id, prefs in receiver_prefs.items():
        receiver_rank[r_id] = {p_id: rank for rank, p_id in enumerate(prefs)}

    # 各提案者の次にプロポーズする相手のインデックス
    next_proposal: dict[str, int] = {p_id: 0 for p_id in proposer_prefs}

    # 現在のマッチング（受入側 → 提案側）
    current_match: dict[str, str] = {}

    # まだマッチしていない提案者のキュー
    free_proposers: deque[str] = deque(proposer_prefs.keys())

    while free_proposers:
        p_id = free_proposers.popleft()
        prefs = proposer_prefs[p_id]

        # この提案者がまだプロポーズしていない相手がいるか
        if next_proposal[p_id] >= len(prefs):
            # 全員に断られた → マッチ不成立
            logger.info("提案者 %s: 全候補に断られ、マッチ不成立", p_id)
            continue

        # 次の候補にプロポーズ
        r_id = prefs[next_proposal[p_id]]
        next_proposal[p_id] += 1

        if r_id not in receiver_rank:
            # 受入側に存在しない候補 → スキップして再キューイング
            logger.debug("提案者 %s: 受入者 %s は存在しないためスキップ", p_id, r_id)
            free_proposers.append(p_id)
            continue

        if r_id not in current_match:
            # 受入者がフリー → マッチ成立
            current_match[r_id] = p_id
            logger.debug("マッチ成立: %s ← %s", r_id, p_id)
        else:
            # 受入者は既にマッチ済み → 比較
            current_p = current_match[r_id]
            ranks = receiver_rank[r_id]

            # 受入側の選好リストに含まれない提案者の処理
            p_rank = ranks.get(p_id)
            current_rank = ranks.get(current_p)

            if p_rank is None:
                # 新しい提案者が受入側の選好リストにない → 拒否
                free_proposers.append(p_id)
                logger.debug("提案者 %s: 受入者 %s の選好リストに含まれず拒否", p_id, r_id)
            elif current_rank is None or p_rank < current_rank:
                # 新しい提案者の方が好ましい → 乗り換え
                current_match[r_id] = p_id
                free_proposers.append(current_p)
                logger.debug(
                    "乗り換え: %s が %s → %s に変更", r_id, current_p, p_id
                )
            else:
                # 現在のパートナーの方が好ましい → 拒否
                free_proposers.append(p_id)
                logger.debug("提案者 %s: 受入者 %s に拒否された", p_id, r_id)

    # 結果を {proposer_id: receiver_id} の形式に変換
    result: dict[str, str] = {p_id: r_id for r_id, p_id in current_match.items()}
    logger.info(
        "Gale-Shapley完了: %d/%d 人がマッチ", len(result), len(proposer_prefs)
    )
    return result


# ===========================================================================
# 2. CP-SAT によるマッチング（制約・目的関数カスタマイズ対応）
# ===========================================================================


def solve_matching_cpsat(
    proposers: list[dict],
    receivers: list[dict],
    compatibility: dict[tuple[str, str], float],
    hard_constraints: list[dict],
    soft_weights: dict[str, float],
    time_limit: int = 60,
) -> dict[str, Any]:
    """CP-SATソルバーによるマッチング最適化。

    Gale-Shapleyでは扱えない複雑な制約（資格要件、地理的距離、
    時間帯の重複、1対多の割当など）に対応する。

    Args:
        proposers: 提案側のリスト。各要素は以下の形式::

            {
                "id": "P001",
                "name": "田中太郎",
                "prefs": ["R001", "R003", "R002"],  # 希望順
                "constraints": {
                    "skills": ["介護福祉士"],
                    "region": "東京都北区",
                    "available_days": ["月", "水", "金"],
                    "gender": "男性",
                    "max_assignments": 1,  # 最大割当数（1対多対応）
                },
            }

        receivers: 受入側のリスト。構造はproposersと同様。
        compatibility: 互換性スコア {(proposer_id, receiver_id): score}。
            スコアは0.0〜1.0。未指定のペアは0とみなす。
        hard_constraints: ハード制約のリスト::

            [
                {"type": "skill_required", "receiver_id": "R001", "skill": "介護福祉士"},
                {"type": "max_distance_km", "threshold": 10.0},
                {"type": "day_overlap_required", "min_days": 1},
                {"type": "gender_preference", "receiver_id": "R002", "gender": "女性"},
                {"type": "exclude_pair", "proposer_id": "P003", "receiver_id": "R001"},
            ]

        soft_weights: ソフト目的の重み（合計1.0を推奨）::

            {
                "compatibility": 0.5,    # 互換性スコアの最大化
                "preference_rank": 0.3,  # 双方の希望順位ボーナス
                "fairness": 0.2,         # 公平性（満足度の偏り最小化）
            }

        time_limit: ソルバーの最大実行時間（秒）。デフォルト60秒。

    Returns:
        結果辞書::

            {
                "status": "OPTIMAL" | "FEASIBLE" | "INFEASIBLE",
                "matches": [{"proposer_id", "receiver_id", "score"}],
                "objective_value": float,
                "stats": {"solve_time_sec", "num_matches", "match_rate"},
            }
    """
    model = cp_model.CpModel()

    # --- IDインデックスの構築 ---
    p_ids = [p["id"] for p in proposers]
    r_ids = [r["id"] for r in receivers]
    p_map = {p["id"]: p for p in proposers}
    r_map = {r["id"]: r for r in receivers}

    # 提案側・受入側の最大割当数（デフォルト1）
    p_max = {
        p["id"]: p.get("constraints", {}).get("max_assignments", 1)
        for p in proposers
    }
    r_max = {
        r["id"]: r.get("constraints", {}).get("max_assignments", 1)
        for r in receivers
    }

    # --- 決定変数 ---
    # x[p, r] = 1 ならば提案者pと受入者rがマッチ
    x: dict[tuple[str, str], Any] = {}
    for p_id in p_ids:
        for r_id in r_ids:
            x[p_id, r_id] = model.new_bool_var(f"x_{p_id}_{r_id}")

    # --- ハード制約: 割当数の上限 ---
    for p_id in p_ids:
        model.add(
            sum(x[p_id, r_id] for r_id in r_ids) <= p_max[p_id]
        )
    for r_id in r_ids:
        model.add(
            sum(x[p_id, r_id] for p_id in p_ids) <= r_max[r_id]
        )

    # --- ハード制約: ユーザ定義 ---
    _apply_hard_constraints(model, x, p_ids, r_ids, p_map, r_map, hard_constraints)

    # --- 目的関数の構築 ---
    objective_terms: list[Any] = []
    # スコアを整数に変換するスケール（CP-SATは整数のみ）
    SCALE = 1000

    # (a) 互換性スコア
    w_compat = soft_weights.get("compatibility", 0.5)
    for p_id in p_ids:
        for r_id in r_ids:
            score = compatibility.get((p_id, r_id), 0.0)
            scaled = int(score * SCALE * w_compat)
            if scaled > 0:
                objective_terms.append(x[p_id, r_id] * scaled)

    # (b) 希望順位ボーナス（双方）
    w_pref = soft_weights.get("preference_rank", 0.3)
    if w_pref > 0:
        for p in proposers:
            prefs = p.get("prefs", [])
            n = len(prefs)
            for rank, r_id in enumerate(prefs):
                if r_id in r_map:
                    # 順位が高いほどボーナスが大きい（1位=n点, 最下位=1点）
                    bonus = int((n - rank) / max(n, 1) * SCALE * w_pref * 0.5)
                    objective_terms.append(x[p["id"], r_id] * bonus)
        for r in receivers:
            prefs = r.get("prefs", [])
            n = len(prefs)
            for rank, p_id in enumerate(prefs):
                if p_id in p_map:
                    bonus = int((n - rank) / max(n, 1) * SCALE * w_pref * 0.5)
                    objective_terms.append(x[p_id, r["id"]] * bonus)

    # (c) 公平性（満足度の最低値を底上げ）
    w_fair = soft_weights.get("fairness", 0.2)
    if w_fair > 0:
        # 各提案者の満足度（マッチした相手の互換性スコア）の最小値を最大化
        min_satisfaction = model.new_int_var(0, SCALE, "min_satisfaction")
        for p_id in p_ids:
            # マッチしていない場合は0（ペナルティは別途考慮可能）
            p_score = sum(
                x[p_id, r_id] * int(compatibility.get((p_id, r_id), 0.0) * SCALE)
                for r_id in r_ids
            )
            model.add(min_satisfaction <= p_score)
        objective_terms.append(min_satisfaction * int(w_fair * SCALE))

    if objective_terms:
        model.maximize(sum(objective_terms))

    # --- ソルバー実行 ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.log_search_progress = False
    status = solver.solve(model)

    status_name = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }.get(status, "UNKNOWN")

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        logger.warning("解が見つかりません: status=%s", status_name)
        return {
            "status": status_name,
            "matches": [],
            "objective_value": 0.0,
            "stats": {
                "solve_time_sec": solver.wall_time,
                "num_matches": 0,
                "match_rate": 0.0,
            },
        }

    # --- 結果の抽出 ---
    matches = []
    for p_id in p_ids:
        for r_id in r_ids:
            if solver.value(x[p_id, r_id]) == 1:
                matches.append({
                    "proposer_id": p_id,
                    "receiver_id": r_id,
                    "score": compatibility.get((p_id, r_id), 0.0),
                })

    num_matched_proposers = len({m["proposer_id"] for m in matches})
    match_rate = num_matched_proposers / len(p_ids) if p_ids else 0.0

    logger.info(
        "CP-SAT完了: status=%s, %d件マッチ, マッチ率=%.1f%%, 計算時間=%.2f秒",
        status_name,
        len(matches),
        match_rate * 100,
        solver.wall_time,
    )

    return {
        "status": status_name,
        "matches": matches,
        "objective_value": solver.objective_value / SCALE if objective_terms else 0.0,
        "stats": {
            "solve_time_sec": solver.wall_time,
            "num_matches": len(matches),
            "match_rate": match_rate,
        },
    }


def _apply_hard_constraints(
    model: cp_model.CpModel,
    x: dict[tuple[str, str], Any],
    p_ids: list[str],
    r_ids: list[str],
    p_map: dict[str, dict],
    r_map: dict[str, dict],
    hard_constraints: list[dict],
) -> None:
    """ハード制約をモデルに追加する（内部関数）。

    対応する制約タイプ:
      - skill_required: 受入者が要求するスキルを提案者が持っていること
      - day_overlap_required: 対応曜日が最低N日重なること
      - gender_preference: 受入者の性別希望に合致すること
      - exclude_pair: 特定のペアを禁止する
    """
    for constraint in hard_constraints:
        c_type = constraint.get("type", "")

        if c_type == "skill_required":
            # 指定スキルを持たない提案者は割当不可
            r_id = constraint["receiver_id"]
            required_skill = constraint["skill"]
            for p_id in p_ids:
                p_skills = p_map[p_id].get("constraints", {}).get("skills", [])
                if required_skill not in p_skills:
                    model.add(x[p_id, r_id] == 0)

        elif c_type == "day_overlap_required":
            # 対応曜日の重なりが最低N日必要
            min_days = constraint.get("min_days", 1)
            for p_id in p_ids:
                p_days = set(
                    p_map[p_id].get("constraints", {}).get("available_days", [])
                )
                for r_id in r_ids:
                    r_days = set(
                        r_map[r_id].get("constraints", {}).get("available_days", [])
                    )
                    overlap = len(p_days & r_days)
                    if overlap < min_days:
                        model.add(x[p_id, r_id] == 0)

        elif c_type == "gender_preference":
            # 受入者の性別希望に合致しない提案者を排除
            r_id = constraint["receiver_id"]
            required_gender = constraint["gender"]
            for p_id in p_ids:
                p_gender = p_map[p_id].get("constraints", {}).get("gender", "")
                if p_gender and p_gender != required_gender:
                    model.add(x[p_id, r_id] == 0)

        elif c_type == "exclude_pair":
            # 特定のペアを明示的に禁止
            p_id = constraint["proposer_id"]
            r_id = constraint["receiver_id"]
            if (p_id, r_id) in x:
                model.add(x[p_id, r_id] == 0)

        else:
            logger.warning("未知の制約タイプ: %s（スキップ）", c_type)


# ===========================================================================
# 3. 評価関数
# ===========================================================================


def evaluate_matching(
    matches: dict[str, str],
    proposers: list[dict],
    receivers: list[dict],
    compatibility: dict[tuple[str, str], float],
) -> dict[str, Any]:
    """マッチング結果を多角的に評価する。

    マッチ率、満足度（双方）、安定性、公平性を計算する。
    ソルバーの目的関数値との比較にも利用できる。

    Args:
        matches: マッチング結果 {proposer_id: receiver_id}
        proposers: 提案側のリスト（prefs を含む）
        receivers: 受入側のリスト（prefs を含む）
        compatibility: 互換性スコア {(proposer_id, receiver_id): score}

    Returns:
        評価結果::

            {
                "match_rate": float,              # マッチできた割合
                "avg_compatibility": float,        # 互換性スコアの平均
                "proposer_satisfaction": float,    # 提案側の平均満足度（0-1）
                "receiver_satisfaction": float,    # 受入側の平均満足度（0-1）
                "satisfaction_gap": float,         # 双方の満足度差（公平性指標）
                "blocking_pairs": int,             # ブロッキングペアの数
                "blocking_pair_details": list,     # ブロッキングペアの詳細
                "fairness_gini": float,            # 互換性スコアのジニ係数
            }
    """
    p_map = {p["id"]: p for p in proposers}
    r_map = {r["id"]: r for r in receivers}

    # --- マッチ率 ---
    match_rate = len(matches) / len(proposers) if proposers else 0.0

    # --- 互換性スコアの平均 ---
    compat_scores = [
        compatibility.get((p_id, r_id), 0.0)
        for p_id, r_id in matches.items()
    ]
    avg_compatibility = (
        sum(compat_scores) / len(compat_scores) if compat_scores else 0.0
    )

    # --- 提案側の満足度（希望順位ベース） ---
    p_satisfactions = []
    for p_id, r_id in matches.items():
        prefs = p_map.get(p_id, {}).get("prefs", [])
        if r_id in prefs:
            rank = prefs.index(r_id)
            # 1位=1.0, 最下位=1/n に正規化
            satisfaction = 1.0 - rank / max(len(prefs), 1)
        else:
            satisfaction = 0.0  # 希望リストにない相手
        p_satisfactions.append(satisfaction)
    proposer_sat = (
        sum(p_satisfactions) / len(p_satisfactions) if p_satisfactions else 0.0
    )

    # --- 受入側の満足度 ---
    reverse_matches = {r_id: p_id for p_id, r_id in matches.items()}
    r_satisfactions = []
    for r_id, p_id in reverse_matches.items():
        prefs = r_map.get(r_id, {}).get("prefs", [])
        if p_id in prefs:
            rank = prefs.index(p_id)
            satisfaction = 1.0 - rank / max(len(prefs), 1)
        else:
            satisfaction = 0.0
        r_satisfactions.append(satisfaction)
    receiver_sat = (
        sum(r_satisfactions) / len(r_satisfactions) if r_satisfactions else 0.0
    )

    # --- 公平性: 満足度の差 ---
    satisfaction_gap = abs(proposer_sat - receiver_sat)

    # --- 安定性: ブロッキングペアの検出 ---
    blocking_pairs = find_blocking_pairs(matches, proposers, receivers)

    # --- 公平性: ジニ係数 ---
    fairness_gini = _gini_coefficient(compat_scores)

    return {
        "match_rate": round(match_rate, 4),
        "avg_compatibility": round(avg_compatibility, 4),
        "proposer_satisfaction": round(proposer_sat, 4),
        "receiver_satisfaction": round(receiver_sat, 4),
        "satisfaction_gap": round(satisfaction_gap, 4),
        "blocking_pairs": len(blocking_pairs),
        "blocking_pair_details": blocking_pairs,
        "fairness_gini": round(fairness_gini, 4),
    }


# ===========================================================================
# 4. 安定性チェック（ブロッキングペア検出）
# ===========================================================================


def find_blocking_pairs(
    matches: dict[str, str],
    proposers: list[dict],
    receivers: list[dict],
) -> list[dict[str, str]]:
    """ブロッキングペアを検出する。

    ブロッキングペア (p, r) とは:
      - pは現在のパートナーよりrを好む
      - rは現在のパートナーよりpを好む
    このようなペアが存在すると、マッチングは「不安定」である。

    Args:
        matches: マッチング結果 {proposer_id: receiver_id}
        proposers: 提案側のリスト（prefs を含む）
        receivers: 受入側のリスト（prefs を含む）

    Returns:
        ブロッキングペアのリスト [{"proposer_id", "receiver_id", "reason"}]
    """
    p_map = {p["id"]: p for p in proposers}
    r_map = {r["id"]: r for r in receivers}

    # 逆引き: receiver → proposer
    reverse_matches = {r_id: p_id for p_id, r_id in matches.items()}

    blocking = []

    for p in proposers:
        p_id = p["id"]
        p_prefs = p.get("prefs", [])
        current_r = matches.get(p_id)

        # pの現在パートナーの順位（マッチなしは最下位扱い）
        if current_r and current_r in p_prefs:
            p_current_rank = p_prefs.index(current_r)
        else:
            p_current_rank = len(p_prefs)  # 最下位

        # pが現在のパートナーより好む受入者を探す
        for rank, r_id in enumerate(p_prefs):
            if rank >= p_current_rank:
                break  # これ以降は現在のパートナー以下

            # rの選好を確認
            r_prefs = r_map.get(r_id, {}).get("prefs", [])
            r_current_p = reverse_matches.get(r_id)

            if r_current_p and r_current_p in r_prefs:
                r_current_rank = r_prefs.index(r_current_p)
            else:
                r_current_rank = len(r_prefs)

            # pがrの選好リストに含まれ、かつ現在のパートナーより上位
            if p_id in r_prefs:
                p_rank_in_r = r_prefs.index(p_id)
                if p_rank_in_r < r_current_rank:
                    blocking.append({
                        "proposer_id": p_id,
                        "receiver_id": r_id,
                        "reason": (
                            f"{p_id}は{r_id}を現パートナー{current_r}より好み、"
                            f"{r_id}は{p_id}を現パートナー{r_current_p}より好む"
                        ),
                    })

    logger.info("ブロッキングペア: %d件検出", len(blocking))
    return blocking


# ===========================================================================
# 5. ユーティリティ関数
# ===========================================================================


def _gini_coefficient(values: list[float]) -> float:
    """ジニ係数を計算する（0=完全平等, 1=完全不平等）。

    マッチングの公平性評価に使用。互換性スコアや満足度の
    偏りを数値化する。
    """
    if not values or len(values) < 2:
        return 0.0

    sorted_vals = sorted(values)
    n = len(sorted_vals)
    total = sum(sorted_vals)

    if total == 0:
        return 0.0

    # ジニ係数の計算
    cumulative = 0.0
    gini_sum = 0.0
    for i, v in enumerate(sorted_vals):
        cumulative += v
        gini_sum += (2 * (i + 1) - n - 1) * v

    return gini_sum / (n * total)


def build_compatibility_from_prefs(
    proposers: list[dict],
    receivers: list[dict],
    base_score: float = 0.3,
) -> dict[tuple[str, str], float]:
    """選好リストから互換性スコアを自動生成するヘルパー。

    選好リストの順位に基づいてスコアを生成する。
    双方の選好を平均して互換性スコアとする。

    Args:
        proposers: 提案側のリスト（prefs を含む）
        receivers: 受入側のリスト（prefs を含む）
        base_score: 選好リストに含まれないペアの基本スコア

    Returns:
        互換性スコア {(proposer_id, receiver_id): score}
    """
    compatibility: dict[tuple[str, str], float] = {}

    p_scores: dict[tuple[str, str], float] = {}
    r_scores: dict[tuple[str, str], float] = {}

    # 提案側の選好からスコア生成
    for p in proposers:
        prefs = p.get("prefs", [])
        n = len(prefs)
        for rank, r_id in enumerate(prefs):
            # 1位=1.0, 最下位に近づくほど低い
            p_scores[p["id"], r_id] = 1.0 - rank / max(n, 1)

    # 受入側の選好からスコア生成
    for r in receivers:
        prefs = r.get("prefs", [])
        n = len(prefs)
        for rank, p_id in enumerate(prefs):
            r_scores[p_id, r["id"]] = 1.0 - rank / max(n, 1)

    # 双方のスコアを平均
    all_pairs = set(p_scores.keys()) | set(r_scores.keys())
    for pair in all_pairs:
        p_score = p_scores.get(pair, base_score)
        r_score = r_scores.get(pair, base_score)
        compatibility[pair] = (p_score + r_score) / 2.0

    # 選好リストに含まれないペアにはbase_scoreを設定
    for p in proposers:
        for r in receivers:
            pair = (p["id"], r["id"])
            if pair not in compatibility:
                compatibility[pair] = base_score

    return compatibility


# ===========================================================================
# メイン: 使用例
# ===========================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # --- 例: 介護マッチング（利用者×ヘルパー） ---
    print("=" * 60)
    print("例1: Gale-Shapley（安定マッチング）")
    print("=" * 60)

    # 利用者（受入側）の希望
    patient_prefs = {
        "利用者A": ["ヘルパー1", "ヘルパー2", "ヘルパー3"],
        "利用者B": ["ヘルパー2", "ヘルパー1", "ヘルパー3"],
        "利用者C": ["ヘルパー1", "ヘルパー3", "ヘルパー2"],
    }

    # ヘルパー（提案側）の希望
    helper_prefs = {
        "ヘルパー1": ["利用者A", "利用者B", "利用者C"],
        "ヘルパー2": ["利用者B", "利用者A", "利用者C"],
        "ヘルパー3": ["利用者A", "利用者C", "利用者B"],
    }

    gs_result = gale_shapley(helper_prefs, patient_prefs)
    print(f"マッチング結果: {gs_result}")

    print()
    print("=" * 60)
    print("例2: CP-SAT（制約付きマッチング）")
    print("=" * 60)

    proposer_list = [
        {
            "id": "H001",
            "name": "ヘルパー田中",
            "prefs": ["P001", "P002", "P003"],
            "constraints": {
                "skills": ["介護福祉士", "ヘルパー2級"],
                "available_days": ["月", "水", "金"],
                "gender": "女性",
            },
        },
        {
            "id": "H002",
            "name": "ヘルパー鈴木",
            "prefs": ["P002", "P001", "P003"],
            "constraints": {
                "skills": ["ヘルパー2級"],
                "available_days": ["火", "木", "土"],
                "gender": "男性",
            },
        },
        {
            "id": "H003",
            "name": "ヘルパー佐藤",
            "prefs": ["P001", "P003", "P002"],
            "constraints": {
                "skills": ["介護福祉士"],
                "available_days": ["月", "火", "水", "木", "金"],
                "gender": "女性",
            },
        },
    ]

    receiver_list = [
        {
            "id": "P001",
            "name": "利用者山田",
            "prefs": ["H001", "H003", "H002"],
            "constraints": {
                "available_days": ["月", "水"],
            },
        },
        {
            "id": "P002",
            "name": "利用者伊藤",
            "prefs": ["H002", "H001", "H003"],
            "constraints": {
                "available_days": ["火", "木"],
            },
        },
        {
            "id": "P003",
            "name": "利用者高橋",
            "prefs": ["H003", "H001", "H002"],
            "constraints": {
                "available_days": ["月", "金"],
            },
        },
    ]

    # 互換性スコアを選好リストから自動生成
    compat = build_compatibility_from_prefs(proposer_list, receiver_list)

    hard = [
        {"type": "skill_required", "receiver_id": "P001", "skill": "介護福祉士"},
        {"type": "day_overlap_required", "min_days": 1},
    ]

    weights = {
        "compatibility": 0.5,
        "preference_rank": 0.3,
        "fairness": 0.2,
    }

    cpsat_result = solve_matching_cpsat(
        proposer_list, receiver_list, compat, hard, weights, time_limit=30
    )

    print(f"ステータス: {cpsat_result['status']}")
    print(f"マッチ数: {cpsat_result['stats']['num_matches']}")
    print(f"マッチ率: {cpsat_result['stats']['match_rate']:.1%}")
    for m in cpsat_result["matches"]:
        print(f"  {m['proposer_id']} → {m['receiver_id']} (スコア: {m['score']:.2f})")

    # --- 評価 ---
    if cpsat_result["matches"]:
        match_dict = {m["proposer_id"]: m["receiver_id"] for m in cpsat_result["matches"]}
        evaluation = evaluate_matching(match_dict, proposer_list, receiver_list, compat)
        print()
        print("--- 評価結果 ---")
        for key, value in evaluation.items():
            if key != "blocking_pair_details":
                print(f"  {key}: {value}")
