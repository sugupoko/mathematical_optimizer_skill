# 施設配置問題ガイド

「どこに施設を置き、各顧客をどの施設に割り当てるか」を決める問題の考え方・手法選択・評価方法をまとめたガイド。
`facility_location_template.py` と合わせて使う。

---

## 施設配置が必要な場面

| 分野 | 施設（供給側） | 顧客（需要側） | 典型的な制約 |
|------|--------------|--------------|-------------|
| **物流** | 倉庫・配送センター | 小売店・顧客 | 容量、配送距離上限、リードタイム |
| **小売** | 店舗・出店候補地 | 商圏内の住民 | 商圏重複、投資予算 |
| **EV充電** | 充電ステーション | EV利用者 | 電力容量、カバレッジ率、設置予算 |
| **通信** | 基地局 | エリア内の端末 | 電波到達距離、周波数干渉 |
| **医療** | 病院・診療所 | 地域住民 | 診療科、救急搬送時間、ベッド数 |
| **防災** | 避難所・備蓄倉庫 | 地域住民 | 避難距離、収容人数、耐震性 |

共通点: **施設の開設にはコスト（固定費）がかかり、顧客へのサービスにもコスト（距離・時間）がかかる**。
両者のバランスが問題の本質。

---

## 3つの定式化と選び方

### 判断フロー

```
施設の固定費が重要？
  ├── はい → 施設に容量制約がある？
  │     ├── はい → CFL（容量制約付き施設配置）
  │     └── いいえ → UFL（容量制約なし施設配置）
  │
  └── いいえ（固定費は同じ or 無視） → 施設数が決まっている？
        ├── はい → P-median（P箇所に開設）
        └── いいえ → P-center（最大距離の最小化）or カバレッジモデル
```

### 定式化の比較

| 特徴 | UFL | CFL | P-median |
|------|-----|-----|----------|
| **目的** | 固定費+輸送費の最小化 | 固定費+輸送費の最小化 | 距離合計の最小化 |
| **施設数** | 自動で決まる | 自動で決まる | Pを指定 |
| **容量制約** | なし | あり | なし（追加可能） |
| **固定費** | 施設ごとに異なる | 施設ごとに異なる | 考慮しない |
| **典型用途** | 倉庫配置（容量余裕あり） | 倉庫配置（容量が制約） | 公共施設（公平性重視） |
| **規模目安** | 施設50×顧客500程度 | 施設50×顧客500程度 | 施設100×顧客1000程度 |

---

## PuLPでの定式化パターン

### 共通の変数

```python
# y[f] = 1 なら施設fを開設
y = {f: pulp.LpVariable(f"y_{f}", cat="Binary") for f in facilities}

# x[f,c] = 1 なら顧客cを施設fが担当
x = {(f, c): pulp.LpVariable(f"x_{f}_{c}", cat="Binary")
     for f in facilities for c in customers}
```

### 共通の制約

```python
# 各顧客はちょうど1施設に割当
for c in customers:
    prob += lpSum(x[f, c] for f in facilities) == 1

# 開設施設からのみサービス可能
for f in facilities:
    for c in customers:
        prob += x[f, c] <= y[f]
```

### UFL: 目的関数

```python
prob += lpSum(fixed_cost[f] * y[f] for f in facilities) \
     + lpSum(transport_cost[f, c] * x[f, c] for f in facilities for c in customers)
```

### CFL: 容量制約を追加

```python
for f in facilities:
    prob += lpSum(demand[c] * x[f, c] for c in customers) <= capacity[f] * y[f]
```

### P-median: 施設数を固定

```python
prob += lpSum(y[f] for f in facilities) == P
# 目的関数は距離のみ（固定費なし）
prob += lpSum(distance[f, c] * x[f, c] for f in facilities for c in customers)
```

---

## 評価指標

| 指標 | 計算方法 | 意味 |
|------|---------|------|
| **総コスト** | 固定費合計 + 輸送費合計 | 全体の経済性 |
| **固定費比率** | 固定費 / 総コスト | 施設を増やす余地の判断に使う |
| **平均輸送距離** | Σ距離 / 顧客数 | サービスレベルの平均 |
| **最大輸送距離** | max(各顧客の距離) | 最悪ケースの顧客がどれだけ遠いか |
| **カバレッジ率** | 50km以内の顧客 / 全顧客 | 地理的な網羅性 |
| **施設稼働率** | 担当需要 / 容量 | CFLで重要。偏りがないか |
| **開設施設数** | Σ y[f] | 管理コストの目安 |

### 評価のポイント

1. **コスト vs カバレッジのトレードオフ**: 施設を増やせば顧客は近くなるが固定費が増える
2. **最大距離に注目**: 平均が良くても、遠い顧客が1人いれば問題になる
3. **稼働率の偏り**: 1施設に集中すると障害時のリスクが高い

---

## 大規模問題への対応（候補地1000+）

候補施設や顧客が1000を超えると、PuLPの標準的なMIP定式化では時間がかかる。

### 対策1: 候補地の事前フィルタリング

```python
# 全顧客の重心から100km以上離れた候補を除外
centroid_lat = sum(c["latitude"] for c in customers) / len(customers)
centroid_lon = sum(c["longitude"] for c in customers) / len(customers)
filtered = [f for f in facilities
            if haversine_km(f["latitude"], f["longitude"],
                           centroid_lat, centroid_lon) < 100]
```

### 対策2: 地理的クラスタリング

```python
from sklearn.cluster import KMeans
# 顧客をK個のクラスタに分割し、各クラスタの重心付近の候補のみを考慮
coords = [(c["latitude"], c["longitude"]) for c in customers]
kmeans = KMeans(n_clusters=K, random_state=42).fit(coords)
```

### 対策3: ラグランジュ緩和

- 制約「各顧客は1施設に割当」をラグランジュ乗数で目的関数に移す
- 分解された問題は施設ごとに独立に解ける
- 下界の品質が良く、ヒューリスティックで上界も得られる

### 対策4: 列生成法

- 「開設施設 + 担当顧客の組」を列として扱う
- 主問題（集合被覆）+ 副問題（ナップサック）に分解
- 大規模CFLでは列生成が最も効率的な場合がある

---

## 実践的なヒント

### 1. 候補地の生成

実問題では「候補をどこに置くか」自体が難しい。以下の方法で候補を生成する:

- **既存施設**: 現在の倉庫・店舗の場所
- **顧客の重心**: 需要密度の高いエリア
- **行政区域の中心**: 市区町村の役所所在地
- **交通結節点**: 高速IC、鉄道駅の近く
- **格子点**: 対象エリアを格子状に分割（粗い探索用）

### 2. 固定費の設定

固定費は以下を含める:

| 項目 | 例 |
|------|-----|
| 賃料 | 月額50万〜200万円 |
| 人件費 | 常駐スタッフの月給 |
| 設備費（按分） | 棚・フォークリフト等の月額按分 |
| 光熱費 | 空調・照明 |

**注意**: 初期投資（建設費等）がある場合は、月額按分してランニングコストに含めるか、別モデル（投資回収年数）で評価する。

### 3. 輸送コストの計算

```python
# 距離ベース（簡易）
transport_cost = distance_km * cost_per_km

# 需要量ベース（トラックの積載量を考慮）
transport_cost = distance_km * cost_per_km * ceil(demand / truck_capacity)

# APIベース（正確）
# Google Maps Distance Matrix API で実走行距離・時間を取得
```

### 4. 感度分析

最適化の結果は入力パラメータに強く依存する。以下の感度分析を必ず行う:

| パラメータ | 変動幅 | チェック内容 |
|-----------|-------|------------|
| 固定費 | ±20% | 開設施設が変わるか |
| 需要量 | ±30% | 容量違反が発生するか |
| 輸送コスト | ±20% | 割当が変わるか |
| 施設数P | P±1 | コスト・距離のトレードオフ |

```python
# 感度分析の例: 固定費を+20%にして再求解
for f in facilities:
    fixed_costs_high[f] = fixed_costs[f] * 1.2
result_high = solve_ufl(facilities, customers, fixed_costs_high, transport_costs)
# 開設施設が変わったか比較
```

### 5. よくある落とし穴

| 問題 | 原因 | 対策 |
|------|------|------|
| 1施設に全顧客が集中 | 固定費が高すぎて施設を増やせない | 固定費を見直す or P-medianに切り替え |
| 遠い顧客が放置される | 目的関数がコスト最小化のみ | 最大距離制約を追加 |
| 容量違反が解消できない | 総需要 > 総容量 | 施設の追加を提言 |
| 解が安定しない | 固定費と輸送費のスケールが違う | 正規化する（例: 月額に統一） |
| 求解時間が長い | 変数が多い（施設×顧客） | 事前フィルタリング or ラグランジュ緩和 |

---

## テンプレートの使い方

```python
from facility_location_template import (
    build_transport_cost_matrix,
    build_distance_matrix,
    solve_ufl,
    solve_cfl,
    solve_p_median,
    evaluate_solution,
)

# 1. データを読み込む（CSV等）
facilities = [...]  # facility_id, latitude, longitude
customers = [...]   # customer_id, latitude, longitude

# 2. コスト行列を作成
costs = build_transport_cost_matrix(facilities, customers, cost_per_km=150)
distances = build_distance_matrix(facilities, customers)

# 3. 求解（問題に合った定式化を選ぶ）
result = solve_cfl(facilities, customers, fixed_costs, costs,
                   capacities, demands, time_limit=120)

# 4. 評価
metrics = evaluate_solution(result, facilities, customers, fixed_costs, costs,
                           distances=distances, capacities=capacities, demands=demands)
```
