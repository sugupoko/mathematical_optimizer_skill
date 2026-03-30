# PuLP + HiGHS 使い分けガイド

## いつ使うか

- CP-SAT では扱いにくい**連続変数を含む混合整数計画 (MIP)** を解きたい時
- **線形計画 (LP)** を高速に解きたい時
- CPLEX/Gurobi の**無料代替**が必要な時
- 問題が「線形」で表現できる（目的関数・制約が全て1次式）場合

```
PuLP+HiGHS を検討すべきサイン:
  - 「生産量を何トンにするか」のような連続値の決定変数がある
  - 「輸送量をどう配分するか」のような流量問題がある
  - 制約が全て線形不等式 (ax + by ≤ c) で書ける
  - 変数が数万〜数十万規模で、CP-SATでは遅い
```

---

## CP-SAT vs PuLP+HiGHS の判断基準

| 特徴 | CP-SAT | PuLP+HiGHS |
|------|--------|-------------|
| **変数の型** | 整数・ブール（離散のみ） | 連続・整数・ブール（混合OK） |
| **制約の表現力** | 非線形制約も可（AllDifferent, If-Then等） | 線形制約のみ |
| **目的関数** | 線形のみ（工夫で非線形近似可） | 線形のみ |
| **得意な規模** | 〜数千変数 | 〜数十万変数（LP）、〜数万変数（MIP） |
| **速度（LP）** | 不向き | 非常に高速 |
| **速度（整数計画）** | 制約伝播が効く問題で高速 | 分枝限定法ベース |
| **商用ソルバーへの移行** | 不可（独自API） | solver変更だけで移行可能 |
| **ライセンス** | Apache 2.0 | MIT（HiGHS）/ BSD（PuLP） |

### 判断フロー

```
連続変数が必要？
  ├── いいえ → 制約は線形だけ？
  │     ├── いいえ → CP-SAT（AllDifferent, If-Then等が使える）
  │     └── はい → 変数が1万以下なら CP-SAT、超えるなら PuLP+HiGHS
  │
  └── はい → 制約は全て線形？
        ├── いいえ → 線形化を検討 → 無理なら非線形ソルバー（scipy等）
        └── はい → PuLP+HiGHS
```

---

## 基本構造（PuLP）

```python
import pulp

# ============================================================
# 1. 問題を定義する
# ============================================================
prob = pulp.LpProblem("production_mix", pulp.LpMaximize)

# ============================================================
# 2. 変数を作る
# ============================================================

# 連続変数（生産量など）
x = pulp.LpVariable("product_A", lowBound=0, cat="Continuous")
y = pulp.LpVariable("product_B", lowBound=0, cat="Continuous")

# 整数変数（トラック台数など）
n_trucks = pulp.LpVariable("n_trucks", lowBound=0, cat="Integer")

# バイナリ変数（施設を開くか否か）
facilities = {
    i: pulp.LpVariable(f"open_{i}", cat="Binary")
    for i in range(num_facilities)
}

# まとめて作る場合（便利）
products = ["A", "B", "C"]
production = pulp.LpVariable.dicts(
    "prod", products, lowBound=0, cat="Continuous"
)

# ============================================================
# 3. 目的関数を設定する
# ============================================================
profit = {"A": 100, "B": 150, "C": 120}
prob += pulp.lpSum(profit[p] * production[p] for p in products), "Total_Profit"

# ============================================================
# 4. 制約を追加する
# ============================================================

# 資源制約
resource_usage = {"A": 2, "B": 3, "C": 1.5}
prob += (
    pulp.lpSum(resource_usage[p] * production[p] for p in products) <= 1000,
    "Resource_Limit",
)

# 需要上限
demand = {"A": 200, "B": 150, "C": 300}
for p in products:
    prob += production[p] <= demand[p], f"Demand_{p}"

# ============================================================
# 5. HiGHS で解く
# ============================================================
solver = pulp.HiGHS_CMD(
    msg=True,           # ログ表示
    timeLimit=60,       # 60秒で打ち切り
    gapRel=0.01,        # 最適性ギャップ1%で停止（MIPの場合）
)
prob.solve(solver)

# ============================================================
# 6. 結果を取り出す
# ============================================================
print(f"Status: {pulp.LpStatus[prob.status]}")
print(f"目的関数値: {pulp.value(prob.objective):.2f}")

for p in products:
    print(f"  {p}: {production[p].varValue:.2f}")

# 制約のスラック（余裕）を確認
for name, constraint in prob.constraints.items():
    print(f"  {name}: スラック = {constraint.slack:.2f}")
```

---

## 実用Tips

### HiGHS のパラメータ設定

```python
# 時間制限（秒）
solver = pulp.HiGHS_CMD(timeLimit=300)

# 最適性ギャップ（MIPの場合、0.01 = 1%以内で停止）
solver = pulp.HiGHS_CMD(gapRel=0.01)

# スレッド数
solver = pulp.HiGHS_CMD(threads=4)

# 全部まとめて
solver = pulp.HiGHS_CMD(
    msg=True,
    timeLimit=300,
    gapRel=0.01,
    threads=4,
    options=["primal_feasibility_tolerance=1e-6"],
)

# HiGHS_CMD が使えない環境では HiGHS(api) を使う
solver = pulp.HiGHS(msg=True, timeLimit=300, gapRel=0.01)
```

### 大規模MIPのコツ

```python
# 1. まずLP緩和で下限/上限を確認
#    → 整数変数を連続変数にして解き、LP上限と整数解の差を見る
for v in prob.variables():
    if v.cat == "Integer":
        v.cat = "Continuous"  # 一時的に緩和
prob.solve(solver)
lp_upper_bound = pulp.value(prob.objective)

# 2. 変数固定（明らかに0/1になるものを固定）
#    → LP緩和で 0 や 1 に張り付いている変数を固定する
for v in prob.variables():
    if v.cat == "Binary":
        if v.varValue is not None and v.varValue > 0.99:
            v.bounds(1, 1)  # 1に固定
        elif v.varValue is not None and v.varValue < 0.01:
            v.bounds(0, 0)  # 0に固定

# 3. 初期解の投入（ウォームスタート）
#    → 貪欲法で見つけた解を初期値として与える
for p in products:
    production[p].setInitialValue(greedy_solution[p])
solver = pulp.HiGHS_CMD(warmStart=True, timeLimit=300)
prob.solve(solver)
```

### PuLP から商用ソルバーへの切り替え

```python
# PuLP の最大の利点: モデル定義はそのまま、solver だけ変える

# HiGHS（無料、PuLP同梱）
solver = pulp.HiGHS_CMD(msg=True, timeLimit=300)

# Gurobi（商用、要ライセンス）
solver = pulp.GUROBI(msg=True, timeLimit=300)

# CPLEX（商用、要ライセンス）
solver = pulp.CPLEX_CMD(msg=True, timelimit=300)

# CBC（無料、PuLP同梱、HiGHSより遅いことが多い）
solver = pulp.PULP_CBC_CMD(msg=True, timeLimit=300)

# 使い方は同じ
prob.solve(solver)
```

**移行の判断**: HiGHS で解いて最適性ギャップが大きい（>5%）場合、Gurobiに切り替えると劇的に改善することがある。特に大規模MIPで差が出る。

---

## よくある適用例

### 1. 生産計画（連続量の製品ミックス）

```python
# 「どの製品をいくつ作れば利益最大か」
# 連続変数 + 線形制約 → PuLP+HiGHS の典型問題

products = ["A", "B", "C"]
machines = ["切断", "組立", "検査"]

# 各製品の各工程にかかる時間（時間/個）
process_time = {
    ("A", "切断"): 2, ("A", "組立"): 3, ("A", "検査"): 1,
    ("B", "切断"): 1, ("B", "組立"): 4, ("B", "検査"): 2,
    ("C", "切断"): 3, ("C", "組立"): 1, ("C", "検査"): 1.5,
}
capacity = {"切断": 480, "組立": 480, "検査": 480}  # 各工程の利用可能時間
profit = {"A": 100, "B": 150, "C": 120}

prob = pulp.LpProblem("production_plan", pulp.LpMaximize)
x = pulp.LpVariable.dicts("produce", products, lowBound=0)
prob += pulp.lpSum(profit[p] * x[p] for p in products)
for m in machines:
    prob += pulp.lpSum(process_time[p, m] * x[p] for p in products) <= capacity[m]
```

### 2. 輸送問題（拠点間の輸送量配分）

```python
# 「どの工場からどの倉庫に何トン運べば輸送コスト最小か」
factories = ["工場1", "工場2"]
warehouses = ["倉庫A", "倉庫B", "倉庫C"]
supply = {"工場1": 300, "工場2": 500}
demand = {"倉庫A": 200, "倉庫B": 250, "倉庫C": 350}
cost = {
    ("工場1", "倉庫A"): 10, ("工場1", "倉庫B"): 15, ("工場1", "倉庫C"): 20,
    ("工場2", "倉庫A"): 12, ("工場2", "倉庫B"): 8,  ("工場2", "倉庫C"): 14,
}

prob = pulp.LpProblem("transport", pulp.LpMinimize)
x = pulp.LpVariable.dicts("ship", (factories, warehouses), lowBound=0)
prob += pulp.lpSum(cost[f, w] * x[f][w] for f in factories for w in warehouses)
for f in factories:
    prob += pulp.lpSum(x[f][w] for w in warehouses) <= supply[f]
for w in warehouses:
    prob += pulp.lpSum(x[f][w] for f in factories) >= demand[w]
```

### 3. 施設配置問題

```python
# 「どの候補地に施設を建てれば、固定費+輸送費が最小か」
# バイナリ変数（建てるか否か）+ 連続変数（供給量）の混合整数計画

candidates = range(5)   # 候補地
customers = range(20)   # 顧客
fixed_cost = [100, 120, 80, 150, 90]  # 施設建設の固定費
transport_cost = {(i, j): ... for i in candidates for j in customers}  # 輸送コスト

prob = pulp.LpProblem("facility_location", pulp.LpMinimize)
open_facility = pulp.LpVariable.dicts("open", candidates, cat="Binary")
serve = pulp.LpVariable.dicts("serve", (candidates, customers), lowBound=0)

# 目的: 固定費 + 輸送費
prob += (
    pulp.lpSum(fixed_cost[i] * open_facility[i] for i in candidates)
    + pulp.lpSum(transport_cost[i, j] * serve[i][j]
                 for i in candidates for j in customers)
)

# 各顧客の需要を満たす
for j in customers:
    prob += pulp.lpSum(serve[i][j] for i in candidates) >= demand[j]

# 施設が開いていないと供給できない（Big-M制約）
M = max(demand.values()) * len(customers)
for i in candidates:
    prob += pulp.lpSum(serve[i][j] for j in customers) <= M * open_facility[i]
```

### 4. ポートフォリオ最適化（線形近似）

```python
# 注: 本来は二次計画だが、リスクをCVaRで近似すれば線形化できる
assets = ["株式A", "株式B", "債券C", "REIT_D"]
expected_return = {"株式A": 0.08, "株式B": 0.12, "債券C": 0.03, "REIT_D": 0.06}

prob = pulp.LpProblem("portfolio", pulp.LpMaximize)
weight = pulp.LpVariable.dicts("w", assets, lowBound=0, upBound=0.4)  # 最大40%

# 目的: 期待リターン最大化
prob += pulp.lpSum(expected_return[a] * weight[a] for a in assets)

# 合計100%
prob += pulp.lpSum(weight[a] for a in assets) == 1.0

# 債券を最低20%（リスク抑制）
prob += weight["債券C"] >= 0.2
```

---

## セットアップ

```bash
pip install pulp
# HiGHS は PuLP 2.7+ に同梱されている（追加インストール不要）

# 動作確認
python -c "import pulp; pulp.HiGHS_CMD().available()"
# True と出れば OK
```

### トラブルシューティング

```bash
# HiGHS_CMD が見つからない場合
pip install --upgrade pulp

# それでもダメなら HiGHS を直接インストール
pip install highspy
# → solver を pulp.HiGHS(msg=True) に変更して使う
```
