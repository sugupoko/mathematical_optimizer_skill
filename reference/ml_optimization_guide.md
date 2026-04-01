# ML × 最適化 — 組合せガイド

## この文書の目的

機械学習（ML）と数理最適化は「予測」と「意思決定」という異なる役割を持つ。
この2つを組み合わせると、どちらか単体ではできない問題が解ける。

```
ML単体:   「来週の需要は120個です」     → で、どうすればいいの？
最適化単体: 「需要が120個なら最適解はこう」 → その120個は正しいの？
ML+最適化: 「来週120個と予測」→「120個に最適なシフト/発注/ルートはこう」
```

---

## 4つの組合せパターン

### パターン1: ML予測 → 最適化で意思決定（最も一般的）

```
┌──────────┐     ┌──────────┐
│   ML     │ ──→ │  最適化   │
│  予測する  │     │  決める   │
└──────────┘     └──────────┘
  何が起きるか      何をすべきか
```

**MLが「未来の状態」を予測し、その予測値をソルバーの入力パラメータに使う。**

| ML予測 | 最適化 | 実社会の例 |
|--------|--------|-----------|
| 来客数予測 | シフト人数最適化 | コンビニ・飲食店 |
| 需要予測 | 在庫発注量最適化 | ECサイト・小売 |
| 解決時間予測 | チケットアサイン | ITSM（本スキルパックで実装済み） |
| 故障確率予測 | 保守スケジュール最適化 | 製造業・インフラ |
| クリック率予測 | 広告配信最適化 | Web広告 |
| 配送時間予測 | 配送ルート最適化 | 宅配・物流 |
| 電力需要予測 | 発電計画最適化 | エネルギー |
| 患者到着予測 | 手術室スケジュール | 病院 |

**実装パターン:**
```python
# Step 1: MLで予測
from sklearn.ensemble import GradientBoostingRegressor

model = GradientBoostingRegressor()
model.fit(X_train, y_train)
predicted_demand = model.predict(X_next_week)  # [120, 95, 140, ...]

# Step 2: 予測値をソルバーの入力に
from ortools.sat.python import cp_model

for day, demand in enumerate(predicted_demand):
    required_staff = max(1, int(demand / 40))  # 40人あたり1名
    model.add(sum(x[e, day] for e in employees) >= required_staff)
```

**注意点:**
- 予測は必ず外れる → **信頼区間を使ってロバストに**
- 予測値をそのまま使うより「最悪ケース」も考慮する
```python
# 予測の信頼区間を使う
predicted = model.predict(X)        # 120
upper_bound = predicted * 1.2       # 144（20%上振れを想定）

# 最悪ケースでも対応できるシフトを組む
model.add(sum(x[e, day] for e in employees) >= upper_bound_staff)
```

---

### パターン2: 最適化 → MLでフィルタリング/評価

```
┌──────────┐     ┌──────────┐
│  最適化   │ ──→ │   ML     │
│ 候補を生成 │     │ 評価する  │
└──────────┘     └──────────┘
  数学的に最適      現場で使えるか
```

**ソルバーが「数学的に最適な案」を複数生成し、MLが「現場で受け入れられるか」を判定する。**

| 最適化出力 | ML評価 | 実社会の例 |
|-----------|--------|-----------|
| シフト表の候補5案 | 過去の修正パターンから却下確率を予測 | 病院・工場 |
| 配送ルート候補 | ドライバーの好みを学習して満足度予測 | 宅配 |
| マッチング候補 | 過去のフィードバックから相性を予測 | 介護・求人 |
| 投資ポートフォリオ | リスクシナリオでストレステスト | 金融 |

**実装パターン:**
```python
# Step 1: ソルバーで複数解を生成
solutions = []
for i in range(5):
    # ランダムな初期解やパラメータ変更で多様な解を生成
    sol = solve_with_variation(data, seed=i)
    solutions.append(sol)

# Step 2: MLで各解を評価
for sol in solutions:
    features = extract_features(sol)  # シフト表の特徴量
    rejection_prob = rejection_model.predict_proba([features])[0][1]
    sol['rejection_risk'] = rejection_prob

# Step 3: リスクが低い解を推薦
best = min(solutions, key=lambda s: s['rejection_risk'])
```

---

### パターン3: MLが目的関数/制約を学習

```
┌──────────┐     ┌──────────┐
│   ML     │ ──→ │  最適化   │
│ 基準を学ぶ │     │ 基準で解く │
└──────────┘     └──────────┘
  何が良い解か      良い解を探す
```

**過去の「良い解」からMLが暗黙の評価基準を学習し、ソルバーの目的関数に組み込む。**

| ML学習対象 | 最適化への反映 | 実社会の例 |
|-----------|-------------|-----------|
| ベテランのシフト修正パターン | 修正されにくい目的関数を学習 | 病院のシフト |
| ドライバーのルート選択 | 「この道は嫌」を距離行列に反映 | 配送 |
| 顧客のマッチング満足度 | 互換性スコアの重みを学習 | 介護・求人 |
| 品質検査員の判断 | 不良品を出さないパラメータ範囲を学習 | 製造 |

**実装パターン:**
```python
# Step 1: 過去の「良い解」から特徴を学習
# 例: 過去のシフト表で修正されなかったもの = 良い解
good_schedules = load_accepted_schedules()
bad_schedules = load_rejected_schedules()

# 「良い解」の特徴を学習
from sklearn.ensemble import RandomForestClassifier
model = RandomForestClassifier()
model.fit(features, labels)  # 1=accepted, 0=rejected

# Step 2: 学習した基準をソルバーの目的関数に組み込む
# MLモデルの特徴量重要度から重みを抽出
importances = model.feature_importances_
# → fairness_weight, night_shift_weight, etc.

# Step 3: 学習した重みでソルバーを実行
model.maximize(
    fairness_term * learned_fairness_weight
    + night_shift_term * learned_night_weight
    + ...
)
```

---

### パターン4: MLとソルバーの交互実行（ループ）

```
┌──────────┐     ┌──────────┐
│   ML     │ ←─→ │  最適化   │
│ 設計/改善  │     │  実行/評価 │
└──────────┘     └──────────┘
  戦略を考える      戦略を試す
```

**LLM/MLがアルゴリズムや戦略を設計し、ソルバーで実行・評価。結果をフィードバックして改善を繰り返す。**

| ML役割 | 最適化役割 | 手法名 |
|--------|----------|--------|
| ヒューリスティクスの設計 | 実行して評価 | FunSearch, EoH |
| 失敗分析→改善案 | 改善案を実行 | ReEvo |
| 複数戦略を同時進化 | 各戦略を評価 | RoCo |
| パラメータ探索 | 各パラメータで最適化 | ベイズ最適化 |

**実装パターン（LLM × ソルバー）:**
```python
# ReEvo方式: 実行→分析→改善のループ
for round in range(3):
    # Step 1: LLMがヒューリスティクスを設計/改善
    if round == 0:
        heuristic_code = llm.generate("シフト割当のヒューリスティクスを書いて")
    else:
        heuristic_code = llm.generate(
            f"前回の結果: {last_result}\n"
            f"問題点: {analysis}\n"
            f"改善したヒューリスティクスを書いて"
        )

    # Step 2: 実行して評価
    result = execute_heuristic(heuristic_code, data)
    score = evaluate(result)

    # Step 3: 結果を分析
    analysis = analyze_failures(result)
    last_result = {"score": score, "violations": result["violations"]}

# → ラウンドごとにスコアが改善していく
```

---

## パターンの選び方

```
MLと最適化を組み合わせたい
  │
  何がMLで何が最適化？
  │
  ├── 「将来の値」が不確実 → パターン1（ML予測→最適化）
  │     例: 来週の需要がわからない → 予測してからシフトを組む
  │
  ├── 「何が良い解か」が不明確 → パターン3（ML学習→目的関数）
  │     例: ベテランが手動で修正する基準がわからない → 学習する
  │
  ├── 「最適解が現場で通るか」が不安 → パターン2（最適化→ML評価）
  │     例: 数学的に最適だが使ってもらえるか → 受入予測する
  │
  └── 「アルゴリズム自体を改善したい」→ パターン4（交互実行）
        例: ソルバーの重みやヒューリスティクスを自動チューニング
```

---

## 本スキルパックとの対応

### 既に実装済み

| パターン | 実装箇所 |
|---------|---------|
| パターン1 | `ticket_assignment_template.py` のLLMEstimator（解決時間予測→アサイン最適化） |
| パターン4 | `opt-improve` のLLMヒューリスティック進化（FunSearch/ReEvo/EoH/RoCo） |

### テンプレートを応用して実装可能

| ユースケース | ベーステンプレート | 追加するML部分 |
|------------|----------------|--------------|
| 需要予測→シフト最適化 | `scheduling_template.py` | scikit-learnで来客数を予測し、`required_count`を動的に設定 |
| 配送時間予測→ルート最適化 | `vrp_template.py` | 過去の実績から移動時間を学習し、`time_matrix`を実績ベースに置換 |
| 故障予測→保守スケジュール | `ticket_assignment_template.py` | センサーデータから故障確率を予測し、優先度スコアに反映 |
| 相性予測→マッチング | `matching_template.py` | 過去のフィードバックから互換性スコアをMLで予測 |
| 立地需要予測→施設配置 | `facility_location_template.py` | 人口動態や商圏データから将来需要を予測し、`demands`に反映 |

---

## 実装のコツ

### 1. まず最適化だけで動かす（ML抜き）

```
最初からMLと最適化を同時に作らない。

Step 1: 固定パラメータで最適化を動かす（仮定ベース）
Step 2: 結果を見て「このパラメータが不確実だ」を特定
Step 3: そのパラメータだけMLで予測に置き換える
```

### 2. MLの予測誤差を考慮する

```
MLの予測は必ず外れる。対策:

  ├── ロバスト最適化: 最悪ケースでも実行可能な解を求める
  │     → 予測値 ± 信頼区間の範囲で最適化
  │
  ├── シナリオ最適化: 複数シナリオで解いて共通して良い解を選ぶ
  │     → 需要が100/120/150の3パターンで最適化、共通部分を採用
  │
  └── 段階的確定: 近い将来は確定、遠い将来は柔軟に
        → 今週のシフトは確定、来週は仮、再来週は予備
```

### 3. MLモデルの更新サイクルを設計する

```
最適化は毎日/毎週実行するが、MLモデルの再学習はどの頻度？

  ├── 予測モデル: 月1回再学習（データが蓄積したら）
  ├── 評価モデル: 四半期1回（修正履歴が溜まったら）
  └── ヒューリスティクス進化: プロジェクト単位（1回やれば済む）

→ /opt-deploy の監視指標に「MLモデルの精度劣化」を含める
```

---

## 参考文献

| テーマ | 参考 |
|--------|------|
| ML+最適化の全般 | Bengio et al. (2021) "Machine Learning for Combinatorial Optimization: a Methodological Tour d'Horizon" |
| 需要予測+在庫最適化 | Syntetos et al. (2016) "Supply chain forecasting: Theory, practice, their gap and the future" |
| LLM+最適化 | Romera-Paredes et al. (2024) "FunSearch: Mathematical discoveries from program search with LLMs" |
| ロバスト最適化 | Ben-Tal et al. "Robust Optimization" |
