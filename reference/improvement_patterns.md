# 改善の定石パターン集

実験で検証済みの改善パターン。/opt-improve で「次に何を試すか」を選ぶ時に参照。

---

## パターン1: 目的関数の精密一致（最優先、+15-27%）

**いつ使う**: ソルバーで解けたがスコアが低い時

```python
# Before: ヒューリスティックな重み
objective_terms.append(var * prof * prof)  # prof^2のボーナス
objective_terms.append(var * (-cost_adjusted))  # 独自のコスト調整

# After: 評価関数と完全一致
# 評価関数のコードを読んで、同じ計算式を使う
sc1_weight = 10  # 評価関数と同じ重み
objective_terms.append(var * prof * sc1_weight)  # 線形、評価関数と同じ
sc2_weight = 8
objective_terms.append(var * (-cost / 10000) * sc2_weight)  # 評価関数と同じスケール
```

**なぜ効く**: ソルバーは目的関数を最大化する。目的関数と評価関数がズレていると、「ソルバーにとっての最適解」≠「評価上の最適解」になる。

---

## パターン2: AM/PM分割（時間帯による分解）

**いつ使う**: 時間制約（時間枠、納期等）がボトルネックの時

```python
# 午前と午後を別問題として解く
am_items = [item for item in items if item['time_window'][0] < 780]  # 13:00前
pm_items = [item for item in items if item['time_window'][0] >= 780]

am_solution = solve(am_items, vehicles)  # 午前だけで解く
pm_solution = solve(pm_items, vehicles)  # 午後だけで解く

# 同じ車両がAMルートとPMルートの両方を担当
# → 車両増なしで2倍のルートが組める
```

**実績**: 時間制約違反31件→0件（配送ルート最適化プロジェクト）

---

## パターン3: Cluster + ソルバー（空間分割）

**いつ使う**: 大規模問題（100+ノード）でソルバー単体が遅い/解けない時

```python
from sklearn.cluster import KMeans
import numpy as np

# 1. 地理的にクラスタリング
coords = np.array([[loc['lat'], loc['lng']] for loc in locations])
kmeans = KMeans(n_clusters=num_vehicles, random_state=42)
labels = kmeans.fit_predict(coords)

# 2. 各クラスタ内でOR-Toolsで最適化（小さい問題）
for cluster_id in range(num_vehicles):
    cluster_locs = [loc for loc, label in zip(locations, labels) if label == cluster_id]
    route = solve_tsp(depot, cluster_locs)  # 小規模TSP、瞬殺
```

**実績**: 400箇所で516km（Production規模で最短距離）

---

## パターン4: SWO + IFS（ソルバー不要の制約充足）

**いつ使う**: ソルバーが使えない環境で制約を満たしたい時

```python
def swo_ifs_solve(dataset, max_rounds=30):
    """SWO（違反フィードバック）+ IFS（バックトラック）"""
    priorities = {}  # (slot) → priority score

    for round in range(max_rounds):
        schedule = greedy_build(dataset, priorities)  # 優先度に従って構築
        violations = check_violations(schedule, dataset)

        if sum(violations.values()) == 0:
            return schedule  # 解けた！

        # SWO: 違反箇所の優先度を上げる
        for violation in violations:
            priorities[violation['location']] += 10

        # IFS: 構築中に行き詰まったらバックトラック
        # （greedy_build内で実装）

    return schedule

def greedy_build(dataset, priorities):
    """優先度付き貪欲法 + バックトラック"""
    schedule = []
    undo_stack = []

    # 優先度が高い順にスロットを処理
    slots = sorted(dataset['slots'], key=lambda s: -priorities.get(s['id'], 0))

    for slot in slots:
        candidate = find_best_candidate(slot, dataset, schedule)
        if candidate:
            schedule.append(candidate)
            undo_stack.append(candidate)
        else:
            # バックトラック: 直近の割当を取り消して再試行
            for depth in range(min(10, len(undo_stack))):
                undone = undo_stack.pop()
                schedule.remove(undone)
                new_candidate = find_best_candidate(slot, dataset, schedule)
                if new_candidate:
                    schedule.append(new_candidate)
                    break

    return schedule
```

**実績**: シフト最適化Hardでソルバーなしfeasible達成（soft=18,908）

---

## パターン5: ヒューリスティック → ソルバー修復

**いつ使う**: ヒューリスティクスで良い解が出るが制約違反がある時

```python
# 1. ヒューリスティクスで高品質な解を生成
heuristic_solution = run_heuristic(dataset)  # 速い、スコア高い、でも違反あり

# 2. ソルバーで修復（良い部分を保存、悪い部分だけ直す）
model = cp_model.CpModel()
# ... 変数と制約を定義 ...

# ヒューリスティクスの解をヒントとして渡す
for assignment in heuristic_solution:
    var = x[assignment['key']]
    model.add_hint(var, 1)  # 「できればこの割当を維持して」

# 保存ボーナス: ヒューリスティクスの割当を維持するとボーナス
for assignment in heuristic_solution:
    var = x[assignment['key']]
    objective_terms.append(var * preservation_bonus)  # 維持するとスコア+

# 3. ソルバーは制約を守りつつ、できるだけ元の解を維持する
```

**実績**: 元のヒューリスティクス14違反→修復後0違反、soft=18,170

---

## パターン6: 制約優先 → 品質改善（発想の逆転）

**いつ使う**: 「まずfeasibleを見つける」のが最優先の時

```python
# Phase 1: feasibilityだけ追求（目的関数なし）
model = cp_model.CpModel()
# ... 全ハード制約を追加 ...
# model.maximize(...) ← これを設定しない！
solver.solve(model)  # 超高速（0.29秒で見つかる）

# Phase 2: feasible解をベースに品質を改善
# ローカルサーチでスワップ・再配置
for _ in range(5000):
    swap = random_swap(solution)
    if is_feasible(swap) and soft_score(swap) > soft_score(solution):
        solution = swap
```

**実績**: 0.29秒でfeasible取得、その後ローカルサーチで改善

---

## どのパターンを選ぶか

```
状況:
  ├── スコアが低い → パターン1（目的関数一致）← 最優先
  ├── 時間制約が壁 → パターン2（AM/PM分割）
  ├── 規模が大きい → パターン3（Cluster+ソルバー）
  ├── ソルバーが使えない → パターン4（SWO+IFS）
  ├── 良い解があるが違反 → パターン5（ヒューリスティック→修復）
  └── まずfeasibleが欲しい → パターン6（制約優先）
```
