"""スケジューリング問題のCP-SAT定式化テンプレート。

シフト最適化プロジェクト（25手法比較）で検証済みのテンプレート。
CP-SATソルバーを使い、作業者をタスクスロットに割り当てる汎用的な
スケジューリング問題を定式化・求解する。

使い方:
  1. このファイルをコピーして問題に合わせて修正
  2. workers, shifts, stations, constraints を自分のデータに合わせる
  3. 目的関数は評価関数と精密一致させること（+15-27%改善の実績）

典型的な利用フロー::

    dataset = json.load(open("data.json"))
    schedule = solve_scheduling(dataset, time_limit=120)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ortools.sat.python import cp_model

logger = logging.getLogger(__name__)


def solve_scheduling(dataset: dict[str, Any], time_limit: int = 120) -> list[dict[str, str]]:
    """汎用スケジューリングソルバー。

    CP-SATモデルを構築し、作業者をタスクスロットに割り当てる。
    スキルレベルに基づく枝刈り、必要人数の充足、同一シフト内の
    重複割当防止などのハード制約を自動で設定する。

    Args:
        dataset: 問題データ。最低限以下の構造が必要::

            {
                "workers": [{"id": "W001", "skills": {"taskA": 3, "taskB": 5}, "max_hours": 40, ...}],
                "slots": [{"day": "day_1", "shift": "morning", "task": "taskA", "needed": 2, "min_skill": 2}],
                "hard_constraints": {...},
                "soft_constraints": {...},
            }

        time_limit: ソルバーの最大実行時間（秒）。デフォルト120秒。

    Returns:
        割当結果のリスト。各要素は ``{"worker_id", "day", "shift", "task"}`` の辞書。
        実行可能解が見つからない場合は空リストを返す。
    """
    model = cp_model.CpModel()
    workers = dataset["workers"]
    slots = dataset["slots"]

    # --- 決定変数 ---
    # x[w, s] = 1 if worker w is assigned to slot s
    x = {}
    for w in workers:
        for s in slots:
            # スキルがある場合のみ変数を作る（枝刈り）
            task = s.get("task", "")
            if task and task in w.get("skills", {}):
                x[(w["id"], s["day"], s["shift"], task)] = model.new_bool_var(
                    f'x_{w["id"]}_{s["day"]}_{s["shift"]}_{task}'
                )

    # --- ハード制約 ---

    # HC: 各スロットの必要人数を満たす
    for s in slots:
        assigned = [
            x[(w["id"], s["day"], s["shift"], s["task"])]
            for w in workers
            if (w["id"], s["day"], s["shift"], s["task"]) in x
        ]
        if assigned:
            model.add(sum(assigned) >= s["needed"])

    # HC: 各作業者は同一シフトに1タスクまで
    for w in workers:
        for day_shift in set((s["day"], s["shift"]) for s in slots):
            day, shift = day_shift
            tasks_in_shift = [
                x[(w["id"], day, shift, s["task"])]
                for s in slots
                if s["day"] == day and s["shift"] == shift
                and (w["id"], day, shift, s["task"]) in x
            ]
            if tasks_in_shift:
                model.add(sum(tasks_in_shift) <= 1)

    # HC: 最低スキルレベル（変数作成時に枝刈り済みだが、min_skillもチェック）
    for (wid, day, shift, task), var in x.items():
        w = next(w for w in workers if w["id"] == wid)
        s = next(s for s in slots if s["day"] == day and s["shift"] == shift and s["task"] == task)
        if w["skills"].get(task, 0) < s.get("min_skill", 0):
            model.add(var == 0)

    # HC: 週最大労働時間（あれば）
    # hours_per_shift = {"morning": 8, "afternoon": 8, "night": 8}
    # for w in workers:
    #     weekly_hours = []
    #     for (wid, day, shift, task), var in x.items():
    #         if wid == w["id"]:
    #             weekly_hours.append(var * hours_per_shift.get(shift, 8))
    #     if weekly_hours:
    #         model.add(sum(weekly_hours) <= w.get("max_hours", 40))

    # --- 目的関数 ---
    # ★重要: 評価関数と精密一致させる（発見2）
    objective_terms = []

    for (wid, day, shift, task), var in x.items():
        w = next(w for w in workers if w["id"] == wid)
        skill_level = w["skills"].get(task, 0)

        # ソフト制約の重みは評価関数と同じ値を使う
        # SC1: スキルレベル最大化
        sc1_weight = 10  # 評価関数と一致させる
        objective_terms.append(var * skill_level * sc1_weight)

        # SC2: コスト最小化（負の寄与）
        # sc2_weight = 8
        # cost = w.get("cost_per_hour", 1000)
        # objective_terms.append(var * (-cost // 100) * sc2_weight)

    if objective_terms:
        model.maximize(sum(objective_terms))

    # --- ソルバー実行 ---
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 8

    logger.info("Solving scheduling problem (time_limit=%ds)...", time_limit)
    status = solver.solve(model)

    status_name = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
    }.get(status, "UNKNOWN")
    logger.info("Status: %s", status_name)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        logger.error("No feasible solution found")
        return []

    # --- 結果抽出 ---
    schedule = []
    for (wid, day, shift, task), var in x.items():
        if solver.value(var) == 1:
            schedule.append({
                "worker_id": wid,
                "day": day,
                "shift": shift,
                "task": task,
            })

    logger.info("Assignments: %d", len(schedule))
    return schedule


if __name__ == "__main__":
    # 使用例: python scheduling_template.py data.json
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

    data_path = sys.argv[1] if len(sys.argv) > 1 else "data.json"
    with open(data_path) as f:
        dataset = json.load(f)

    schedule = solve_scheduling(dataset)
    print(json.dumps(schedule, ensure_ascii=False, indent=2))
