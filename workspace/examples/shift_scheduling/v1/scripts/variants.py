"""
ソフト制約の重み配分を変えた複数バリエーションを生成し、スコアを数値比較する。

バリエーション:
  A: バランス型（デフォルト）
  B: 公平性重視（SC2 の重みを上げる）
  C: 夜勤制限重視（SC4 の重みを上げる）
  D: 最低時間確保重視（SC3 の重みを上げる）
  E: トレーナー配置重視（SC5 の重みを上げる）
"""
import csv
import json
import statistics
from pathlib import Path
from ortools.sat.python import cp_model

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = BASE_DIR / "results"
RESULTS_DIR.mkdir(exist_ok=True)

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SHIFT_HOURS = 8
SHIFT_NAMES = ["morning", "afternoon", "night"]


def load_data():
    employees = []
    with open(DATA_DIR / "employees.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["skills"] = set(row["skills"].split(","))
            row["max_hours"] = int(row["max_hours_per_week"])
            row["min_hours"] = int(row["min_hours_per_week"])
            row["unavailable"] = set(row["unavailable_days"].split(",")) - {""}
            employees.append(row)
    shifts = []
    with open(DATA_DIR / "shifts.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["required_count"] = int(row["required_count"])
            shifts.append(row)
    return employees, shifts


def score_solution(assignment, employees, shifts):
    """各ソフト制約のスコアを 0-100 で算出。100 = 完全遵守"""
    n_emp = len(employees)
    n_shift = len(shifts)
    scores = {}

    # --- HC1: 充足率 ---
    total_required = sum(s["required_count"] for s in shifts)
    total_assigned = 0
    for s_idx, shift in enumerate(shifts):
        assigned = sum(assignment.get((e, s_idx), 0) for e in range(n_emp))
        total_assigned += min(assigned, shift["required_count"])
    scores["充足率"] = round(total_assigned / total_required * 100, 1)

    # 従業員ごとの集計
    emp_hours = []
    emp_nights = []
    emp_consecutive = []
    emp_min_met = 0
    trainer_days = 0

    training_emps = [i for i, e in enumerate(employees) if "training" in e["skills"]]

    for e_idx, emp in enumerate(employees):
        assigned_shifts = [s for s in range(n_shift) if assignment.get((e_idx, s), 0)]
        hours = len(assigned_shifts) * SHIFT_HOURS
        emp_hours.append(hours)

        # 夜勤回数
        nights = sum(1 for s in assigned_shifts if s % 3 == 2)
        emp_nights.append(nights)

        # 連続勤務
        work_days = set(s // 3 for s in assigned_shifts)
        max_consec = consec = 0
        for d in range(7):
            if d in work_days:
                consec += 1
                max_consec = max(max_consec, consec)
            else:
                consec = 0
        emp_consecutive.append(max_consec)

        # 最低時間達成
        if hours >= emp["min_hours"]:
            emp_min_met += 1

    # SC1: 連続勤務5日以下 (違反者0 = 100点)
    sc1_violators = sum(1 for c in emp_consecutive if c > 5)
    scores["SC1_連続勤務"] = round((1 - sc1_violators / n_emp) * 100, 1)

    # SC2: 公平性 (SD=0 → 100点、SD=max_hours の平均 → 0点)
    if len(emp_hours) > 1:
        sd = statistics.stdev(emp_hours)
        avg_max = statistics.mean([e["max_hours"] for e in employees])
        scores["SC2_公平性"] = round(max(0, (1 - sd / (avg_max * 0.5)) * 100), 1)
    else:
        scores["SC2_公平性"] = 100.0

    # SC3: 最低勤務時間達成率
    scores["SC3_最低時間"] = round(emp_min_met / n_emp * 100, 1)

    # SC4: 夜勤週2回以下 (違反者0 = 100点)
    sc4_violators = sum(1 for n in emp_nights if n > 2)
    scores["SC4_夜勤制限"] = round((1 - sc4_violators / n_emp) * 100, 1)

    # SC5: トレーナー配置 (7日中何日配置できたか)
    for d in range(7):
        day_shifts = [d * 3 + t for t in range(3)]
        if any(assignment.get((e, s), 0) for s in day_shifts for e in training_emps):
            trainer_days += 1
    scores["SC5_トレーナー"] = round(trainer_days / 7 * 100, 1)

    # 総合スコア（重み付き平均）
    scores["総合"] = round(
        scores["充足率"] * 0.3
        + scores["SC1_連続勤務"] * 0.1
        + scores["SC2_公平性"] * 0.2
        + scores["SC3_最低時間"] * 0.15
        + scores["SC4_夜勤制限"] * 0.15
        + scores["SC5_トレーナー"] * 0.1,
        1
    )

    # 生データも保存
    scores["_raw"] = {
        "emp_hours": emp_hours,
        "emp_nights": emp_nights,
        "emp_consecutive": emp_consecutive,
        "fairness_sd": round(statistics.stdev(emp_hours), 2) if len(emp_hours) > 1 else 0,
    }

    return scores


def solve_variant(employees, shifts, weights, time_limit=30):
    """重み配分を変えてソルバーを実行"""
    model = cp_model.CpModel()
    n_emp = len(employees)
    n_shift = len(shifts)

    x = {}
    for e in range(n_emp):
        for s in range(n_shift):
            x[(e, s)] = model.NewBoolVar(f"x_{e}_{s}")

    # HC1: 不足変数
    shortage = {}
    for s in range(n_shift):
        shortage[s] = model.NewIntVar(0, shifts[s]["required_count"], f"short_{s}")
        model.Add(sum(x[(e, s)] for e in range(n_emp)) + shortage[s] >= shifts[s]["required_count"])

    for e_idx, emp in enumerate(employees):
        # HC2
        model.Add(sum(x[(e_idx, s)] for s in range(n_shift)) * SHIFT_HOURS <= emp["max_hours"])
        # HC3, HC4
        for s_idx, shift in enumerate(shifts):
            if shift["day"] in emp["unavailable"]:
                model.Add(x[(e_idx, s_idx)] == 0)
            if shift["required_skills"] not in emp["skills"]:
                model.Add(x[(e_idx, s_idx)] == 0)
        # HC5
        for d in range(len(DAYS) - 1):
            model.Add(x[(e_idx, d * 3 + 2)] + x[(e_idx, (d + 1) * 3)] <= 1)
        # 1日1シフト
        for d in range(len(DAYS)):
            model.Add(sum(x[(e_idx, d * 3 + t)] for t in range(3)) <= 1)

    total_shortage = sum(shortage[s] for s in range(n_shift))

    # SC2: 公平性 (max-min gap)
    emp_counts = []
    for e in range(n_emp):
        cnt = model.NewIntVar(0, 21, f"cnt_{e}")
        model.Add(cnt == sum(x[(e, s)] for s in range(n_shift)))
        emp_counts.append(cnt)
    max_s = model.NewIntVar(0, 21, "max_s")
    min_s = model.NewIntVar(0, 21, "min_s")
    model.AddMaxEquality(max_s, emp_counts)
    model.AddMinEquality(min_s, emp_counts)
    fairness_gap = model.NewIntVar(0, 21, "gap")
    model.Add(fairness_gap == max_s - min_s)

    # SC3: 最低時間不足
    min_deficit = []
    for e_idx, emp in enumerate(employees):
        needed = emp["min_hours"] // SHIFT_HOURS
        deficit = model.NewIntVar(0, 10, f"mindef_{e_idx}")
        model.AddMaxEquality(deficit, [needed - emp_counts[e_idx], model.NewConstant(0)])
        min_deficit.append(deficit)

    # SC4: 夜勤超過
    night_excess = []
    for e in range(n_emp):
        night_cnt = model.NewIntVar(0, 7, f"night_{e}")
        model.Add(night_cnt == sum(x[(e, d * 3 + 2)] for d in range(7)))
        exc = model.NewIntVar(0, 7, f"nexc_{e}")
        model.AddMaxEquality(exc, [night_cnt - 2, model.NewConstant(0)])
        night_excess.append(exc)

    # SC5: トレーナー未配置日数
    training_emps = [i for i, e in enumerate(employees) if "training" in e["skills"]]
    trainer_miss = []
    for d in range(7):
        day_shifts = [d * 3 + t for t in range(3)]
        has_trainer = model.NewBoolVar(f"trainer_{d}")
        trainer_vars = [x[(e, s)] for e in training_emps for s in day_shifts]
        model.AddMaxEquality(has_trainer, trainer_vars)
        miss = model.NewBoolVar(f"tmiss_{d}")
        model.Add(miss == 1 - has_trainer)
        trainer_miss.append(miss)

    # 重み付き目的関数
    model.Minimize(
        total_shortage * 1000                        # HC1 は常に最優先
        + fairness_gap * weights["fairness"]         # SC2
        + sum(min_deficit) * weights["min_hours"]    # SC3
        + sum(night_excess) * weights["night"]       # SC4
        + sum(trainer_miss) * weights["trainer"]     # SC5
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 4
    status = solver.Solve(model)

    assignment = {}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for e in range(n_emp):
            for s in range(n_shift):
                if solver.Value(x[(e, s)]):
                    assignment[(e, s)] = 1

    return assignment


# --- バリエーション定義 ---
VARIANTS = {
    "A_バランス型": {
        "description": "全ソフト制約を均等に考慮",
        "weights": {"fairness": 10, "min_hours": 10, "night": 10, "trainer": 10},
    },
    "B_公平性重視": {
        "description": "従業員間の勤務時間の偏りを最小化",
        "weights": {"fairness": 50, "min_hours": 10, "night": 5, "trainer": 5},
    },
    "C_夜勤制限重視": {
        "description": "夜勤を週2回以下に強く誘導",
        "weights": {"fairness": 5, "min_hours": 5, "night": 50, "trainer": 5},
    },
    "D_最低時間確保重視": {
        "description": "全員の最低勤務時間をなるべく確保",
        "weights": {"fairness": 5, "min_hours": 50, "night": 5, "trainer": 5},
    },
    "E_トレーナー重視": {
        "description": "毎日トレーニングスキル保持者を配置",
        "weights": {"fairness": 5, "min_hours": 5, "night": 5, "trainer": 50},
    },
}


def main():
    employees, shifts = load_data()
    all_results = {}

    print("=" * 80)
    print("ソフト制約バリエーション比較")
    print("=" * 80)

    for name, variant in VARIANTS.items():
        print(f"\n--- {name}: {variant['description']} ---")
        assignment = solve_variant(employees, shifts, variant["weights"])
        scores = score_solution(assignment, employees, shifts)

        all_results[name] = {
            "description": variant["description"],
            "weights": variant["weights"],
            "scores": {k: v for k, v in scores.items() if not k.startswith("_")},
            "raw": scores["_raw"],
        }

        print(f"  充足率:       {scores['充足率']:6.1f}")
        print(f"  SC1 連続勤務: {scores['SC1_連続勤務']:6.1f}")
        print(f"  SC2 公平性:   {scores['SC2_公平性']:6.1f}  (SD={scores['_raw']['fairness_sd']}h)")
        print(f"  SC3 最低時間: {scores['SC3_最低時間']:6.1f}")
        print(f"  SC4 夜勤制限: {scores['SC4_夜勤制限']:6.1f}")
        print(f"  SC5 トレーナー: {scores['SC5_トレーナー']:6.1f}")
        print(f"  ────────────────────")
        print(f"  総合スコア:   {scores['総合']:6.1f}")

    # 比較テーブル出力
    print("\n" + "=" * 80)
    print("比較サマリ")
    print("=" * 80)
    header = f"{'バリエーション':<20} {'充足率':>6} {'連続':>6} {'公平性':>6} {'最低h':>6} {'夜勤':>6} {'訓練':>6} │ {'総合':>6}"
    print(header)
    print("─" * len(header))
    for name, r in all_results.items():
        s = r["scores"]
        print(f"{name:<20} {s['充足率']:>6.1f} {s['SC1_連続勤務']:>6.1f} {s['SC2_公平性']:>6.1f} {s['SC3_最低時間']:>6.1f} {s['SC4_夜勤制限']:>6.1f} {s['SC5_トレーナー']:>6.1f} │ {s['総合']:>6.1f}")

    # JSON 保存
    with open(RESULTS_DIR / "variant_results.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print(f"\n結果を {RESULTS_DIR / 'variant_results.json'} に保存しました。")


if __name__ == "__main__":
    main()
