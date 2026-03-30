# 多目的最適化ガイド

## なぜ多目的最適化が必要か

実務の最適化問題は、ほぼ必ず複数の目的が競合する。

```
シフト最適化:  人件費 vs スタッフの公平性 vs 希望シフトの充足率
配送ルート:    総距離 vs 車両台数 vs 時間枠違反 vs ドライバー負荷の均等化
生産計画:      利益 vs 在庫コスト vs 納期遵守率
```

**重み付け和だけでは不十分な理由**:
- 重みの決め方が恣意的（「コスト:品質 = 7:3」に根拠があるか？）
- パレートフロントの凹部分にある解が見つからない
- 「コストをあとX円増やすと品質がどれだけ上がるか」が見えない

多目的最適化の目的は「最適解を1つ出す」ことではなく、**トレードオフの構造を明らかにして意思決定を支援する**こと。

---

## 3つのアプローチ

### 1. 重み付け和法（現状のアプローチ）

複数の目的関数を重み付けして1つの目的関数にまとめる。

```python
from ortools.sat.python import cp_model

model = cp_model.CpModel()

# ... 変数と制約の定義 ...

# 目的関数: w1 * コスト最小化 + w2 * 公平性最大化
w_cost = 7
w_fairness = 3

model.minimize(
    w_cost * total_cost - w_fairness * fairness_score
)

solver = cp_model.CpSolver()
status = solver.solve(model)
```

**メリット**:
- 実装が最も簡単（目的関数を1つにするだけ）
- どのソルバーでもそのまま使える
- 解が1つだけ出るので意思決定が楽

**デメリット**:
- 重みの決め方に根拠がない（ヒアリングで聞いても「全部大事」と言われがち）
- パレートフロントの凹部分にある解が見つからない（数学的限界）
- 重みを変えて複数回解いても、得られる解に偏りが出る

**使いどころ**: 最初のベースラインとして。ヒアリングで優先順位が明確に聞けた時。

---

### 2. ε-制約法

1つの目的を最適化し、他の目的は「ε以下」の制約として扱う。

```python
from ortools.sat.python import cp_model


def solve_with_epsilon(cost_limit):
    """コストをε以下に制約して、公平性を最大化する"""
    model = cp_model.CpModel()

    # ... 変数と制約の定義 ...

    # ε-制約: コストはcost_limit以下
    model.add(total_cost <= cost_limit)

    # 目的: 公平性を最大化
    model.maximize(fairness_score)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60
    status = solver.solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "cost": solver.value(total_cost),
            "fairness": solver.value(fairness_score),
            "status": "OK",
        }
    else:
        return {"status": "INFEASIBLE"}


# まず単目的で上限/下限を確認
result_min_cost = solve_with_epsilon(cost_limit=10**9)  # 制約なし → コスト下限
result_max_cost = solve_with_epsilon(cost_limit=0)       # 最厳 → 実行不能の境界を探す
```

**メリット**:
- 凹部分のパレート解も見つかる
- 「コストはX以下で品質を最大化してほしい」という要望に直接対応できる
- 制約を追加するだけなので、モデル変更が小さい

**デメリット**:
- εの値を手動で設定する必要がある
- 1回の実行で1つの解しか得られない

**使いどころ**: 「予算はX万円以内で」「違反は3件以下で」といった上限が明確な時。

---

### 3. パレートフロント探索

ε-制約法を複数のε値で繰り返し実行し、パレートフロントの全体像を描く。

```python
import numpy as np
import matplotlib.pyplot as plt
from ortools.sat.python import cp_model


def build_model():
    """モデルを構築して返す（毎回新しいモデルが必要）"""
    model = cp_model.CpModel()
    # ... 変数と制約の定義 ...
    # total_cost, fairness_score を返す
    return model, total_cost, fairness_score, variables


def solve_with_epsilon(cost_limit):
    """コスト制約付きで公平性を最大化"""
    model, total_cost, fairness_score, variables = build_model()
    model.add(total_cost <= cost_limit)
    model.maximize(fairness_score)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60
    status = solver.solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "cost": solver.value(total_cost),
            "fairness": solver.value(fairness_score),
            "feasible": True,
        }
    return {"feasible": False}


# ============================================================
# Step 1: 各目的の上限・下限を求める
# ============================================================

# コスト最小化（公平性は無視）
model, total_cost, fairness_score, _ = build_model()
model.minimize(total_cost)
solver = cp_model.CpSolver()
solver.solve(model)
cost_min = solver.value(total_cost)

# 公平性最大化（コストは無視）
model, total_cost, fairness_score, _ = build_model()
model.maximize(fairness_score)
solver = cp_model.CpSolver()
solver.solve(model)
cost_at_max_fairness = solver.value(total_cost)

print(f"コスト範囲: {cost_min} 〜 {cost_at_max_fairness}")

# ============================================================
# Step 2: ε値を等間隔に設定してパレート解を収集
# ============================================================
n_points = 10
epsilon_values = np.linspace(cost_min, cost_at_max_fairness, n_points)

pareto_points = []
for eps in epsilon_values:
    result = solve_with_epsilon(int(eps))
    if result["feasible"]:
        pareto_points.append(result)
        print(f"  ε={int(eps)}: コスト={result['cost']}, 公平性={result['fairness']}")

# ============================================================
# Step 3: パレートフロントを可視化
# ============================================================
costs = [p["cost"] for p in pareto_points]
fairness = [p["fairness"] for p in pareto_points]

fig, ax = plt.subplots(figsize=(8, 6))
ax.scatter(costs, fairness, s=80, zorder=5)
ax.plot(costs, fairness, "--", alpha=0.5)

# 各点にラベルを付ける
for i, p in enumerate(pareto_points):
    ax.annotate(
        f"案{i+1}", (p["cost"], p["fairness"]),
        textcoords="offset points", xytext=(8, 8), fontsize=9,
    )

ax.set_xlabel("コスト（円）", fontsize=12)
ax.set_ylabel("公平性スコア", fontsize=12)
ax.set_title("パレートフロント: コスト vs 公平性", fontsize=14)
ax.grid(True, alpha=0.3)
fig.tight_layout()
fig.savefig("pareto_front.png", dpi=150)
plt.close()
print("パレートフロントを pareto_front.png に保存しました")
```

**メリット**:
- トレードオフの全体像が一目でわかる
- 「膝の点」（最もバランスの良い点）を見つけられる
- 意思決定者に選択肢を提示できる

**デメリット**:
- ソルバーをn回実行するため時間がかかる
- 3目的以上になると可視化が難しい

---

## 膝の点（Knee Point）の自動検出

パレートフロント上で「これ以上コストを下げても品質がほとんど上がらない」境目を自動検出する。

```python
import numpy as np


def find_knee_point(costs, fairness_scores):
    """
    パレートフロント上の膝の点を検出する。
    直線（両端を結ぶ線）から最も離れた点が「膝」。
    """
    # 正規化
    costs_norm = (np.array(costs) - min(costs)) / (max(costs) - min(costs) + 1e-9)
    scores_norm = (np.array(fairness_scores) - min(fairness_scores)) / (
        max(fairness_scores) - min(fairness_scores) + 1e-9
    )

    # 両端を結ぶ直線からの距離
    p1 = np.array([costs_norm[0], scores_norm[0]])
    p2 = np.array([costs_norm[-1], scores_norm[-1]])
    line_vec = p2 - p1
    line_len = np.linalg.norm(line_vec)

    distances = []
    for i in range(len(costs)):
        point = np.array([costs_norm[i], scores_norm[i]])
        # 点と直線の距離
        d = abs(np.cross(line_vec, p1 - point)) / (line_len + 1e-9)
        distances.append(d)

    knee_idx = int(np.argmax(distances))
    return knee_idx


# 使い方
knee = find_knee_point(costs, fairness)
print(f"推奨案: 案{knee+1} (コスト={costs[knee]}, 公平性={fairness[knee]})")
print("  → コストと公平性のバランスが最も良い点です")
```

---

## 意思決定者への見せ方

### 原則: 「最適解」ではなく「選択肢と根拠」を提示する

```
NG: 「最適化の結果、この解が最適です」
OK: 「3つの案を用意しました。どのバランスが御社に合いますか？」
```

### 提示のテンプレート

```markdown
## 改善案の比較

| | 案A（コスト重視） | 案B（バランス型）★推奨 | 案C（品質重視） |
|---|---|---|---|
| コスト | 120万円/月 | 135万円/月 | 160万円/月 |
| 品質スコア | 72点 | 88点 | 95点 |
| 現状比コスト | -15% | -4% | +14% |
| 現状比品質 | +20% | +47% | +58% |

### トレードオフの構造
- 案A→案B: コスト+15万円で品質+16点（**1万円あたり1.07点の改善**）
- 案B→案C: コスト+25万円で品質+7点（1万円あたり0.28点の改善）
- → **案Bが限界利益の変曲点**（これ以上投資しても品質改善が鈍化）
```

### 限界利益的な説明

```python
# パレート解の隣接する点の間で、追加コストあたりの品質改善を計算
for i in range(len(pareto_points) - 1):
    delta_cost = pareto_points[i+1]["cost"] - pareto_points[i]["cost"]
    delta_quality = pareto_points[i+1]["fairness"] - pareto_points[i]["fairness"]
    if delta_cost != 0:
        marginal = delta_quality / delta_cost
        print(f"案{i+1}→案{i+2}: コスト+{delta_cost}で品質+{delta_quality} "
              f"(限界改善率: {marginal:.4f})")
```

---

## 判断フロー

```
目的が複数ある？
  ├── 1つだけ → 通常の単目的最適化
  └── 複数ある
        ├── 優先順位が明確
        │     「コストが最重要、品質は最低ラインを超えればOK」
        │     → 辞書式順序（最重要を先に最適化、次に次重要を最適化）
        │
        ├── トレードオフを見たい
        │     「コストと品質のバランスを検討したい」
        │     → ε-制約法 or パレートフロント探索
        │     → 意思決定者にグラフを見せて選んでもらう
        │
        └── とりあえず1つの解が欲しい
              「まず動くものを見せてほしい」
              → 重み付け和（ヒアリングで重みを決定）
              → 後から多目的に拡張
```

### 辞書式順序法の実装

```python
from ortools.sat.python import cp_model

# Step 1: コストを最小化
model1, total_cost, fairness_score, _ = build_model()
model1.minimize(total_cost)
solver1 = cp_model.CpSolver()
solver1.solve(model1)
optimal_cost = solver1.value(total_cost)

# Step 2: コストを最適値に固定して、公平性を最大化
model2, total_cost, fairness_score, _ = build_model()
model2.add(total_cost <= optimal_cost)  # コストは最適値以下
model2.maximize(fairness_score)
solver2 = cp_model.CpSolver()
solver2.solve(model2)

print(f"コスト: {solver2.value(total_cost)} (最小)")
print(f"公平性: {solver2.value(fairness_score)} (コスト最小の中で最大)")
```

---

## 実務での注意点

### パレート解が多すぎる問題

パレート解を10個も20個も並べると、意思決定者は混乱して「全部よくわからないから現状のままで」となる。

```
原則: 3〜5案に絞る
  - 案1: 最もコスト重視
  - 案2: バランス型（膝の点）★推奨
  - 案3: 最も品質重視
  - (案4: 現場からのリクエストに最も近い案)
```

### 公平性指標の使い分け

「公平にしてほしい」と言われた時、何をもって「公平」とするかで結果が変わる。

| 指標 | 意味 | 使いどころ |
|------|------|----------|
| **min-max** | 最も不利な人を改善 | 「誰も極端に不利にならない」を保証したい時 |
| **標準偏差** | ばらつきを抑える | 全体として均等にしたい時 |
| **ジニ係数** | 不平等度 | 経済学的な公平性を議論する時 |
| **最小値の最大化** | 底上げ | 「最低でもX回は希望が通る」を保証したい時 |

```python
# CP-SAT での公平性指標の実装例

# min-max: 最大負荷を最小化
max_load = model.new_int_var(0, max_possible, "max_load")
for worker in workers:
    model.add(load[worker] <= max_load)
model.minimize(max_load)

# 最小値の最大化: 底上げ
min_satisfaction = model.new_int_var(0, max_possible, "min_sat")
for worker in workers:
    model.add(satisfaction[worker] >= min_satisfaction)
model.maximize(min_satisfaction)

# 標準偏差の最小化（CP-SATでは直接扱えない → 近似）
# → max - min を最小化するか、各値と平均の差の絶対値の和を最小化
mean_val = sum(load[w] for w in workers)  # N倍のまま扱う
total_deviation = model.new_int_var(0, max_possible * len(workers), "dev")
for w in workers:
    abs_dev = model.new_int_var(0, max_possible, f"abs_dev_{w}")
    diff = model.new_int_var(-max_possible, max_possible, f"diff_{w}")
    model.add(diff == load[w] * len(workers) - mean_val)
    model.add_abs_equality(abs_dev, diff)
model.minimize(pulp.lpSum(abs_dev for _ in workers))  # 平均絶対偏差
```

### 「最適」という言葉に注意

- 多目的最適化には「唯一の最適解」は存在しない
- パレート最適解は全て「これ以上どの目的も改善できない」という意味で最適
- 意思決定者に「どれが正解か」を聞かれたら、「どれもパレート最適であり、御社の優先順位で選ぶものです」と説明する
- 推奨を出す時は「膝の点」を根拠にする（コスト効率が最も良い点）
