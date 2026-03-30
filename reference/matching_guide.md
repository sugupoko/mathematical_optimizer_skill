# マッチング問題ガイド

双方に希望がある割当問題の考え方・手法選択・評価方法をまとめたガイド。
`matching_template.py` と合わせて使う。

---

## マッチングが必要な場面

「誰を誰に割り当てるか」を決める問題は、あらゆる業界に存在する。

| 分野 | 供給側 | 需要側 | 典型的な制約 |
|------|--------|--------|-------------|
| **介護** | ヘルパー | 利用者 | 資格、対応曜日、地域、性別、要介護度、相性 |
| **求人** | 求職者 | 企業 | スキル、勤務地、給与レンジ、経験年数、カルチャーフィット |
| **教育** | 家庭教師 | 生徒 | 科目、レベル、曜日、指導経験、指導スタイル |
| **不動産** | 物件 | 顧客 | 予算、間取り、エリア、築年数、ペット可否 |
| **メンタリング** | メンター | メンティー | 専門分野、キャリア段階、言語、時間帯、相性 |

共通点: **双方に選好（好み）がある**。片方だけ最適化すると、もう片方が不満を持つ。

---

## 問題の分類テーブル

問題の特徴を見て、手法を選ぶ。

| 特徴 | 推奨手法 | 理由 |
|------|---------|------|
| 1対1、安定性重視 | **Gale-Shapley** | 安定マッチングが数学的に保証される |
| 1対多（1人が複数を担当） | **CP-SAT / MIP** | 容量制約を自然に扱える |
| 制約が複雑（資格、時間帯、距離…） | **CP-SAT** | 任意の制約を追加できる |
| 重み付き最大マッチング | **ハンガリアン法 / CP-SAT** | 総マッチスコア最大化 |
| 動的（リアルタイムで到着） | **オンラインマッチング** | 全体が見えない状態で逐次決定 |
| 大規模（1万+ペア） | **ヒューリスティック + 局所探索** | ソルバーが時間内に解けない場合 |

**迷ったらCP-SAT**。Gale-Shapleyは「安定性が最重要」の時だけ。

---

## Gale-Shapley vs CP-SAT の使い分け

### Gale-Shapley（安定マッチングアルゴリズム）

| 項目 | 内容 |
|------|------|
| **計算量** | O(n²) — 数万件でも瞬時 |
| **安定性** | 保証される（ブロッキングペアが0） |
| **偏り** | 提案側に最適、受入側には最悪の安定解 |
| **制約追加** | 困難（アルゴリズムの外で事前フィルタする必要がある） |
| **目的関数** | カスタマイズ不可（安定性のみが目的） |
| **1対多** | 拡張版（Gale-Shapley with quotas）で対応可能だが複雑化する |

**適するケース**: 安定性が最重要で、制約が少ない場面。
研修医マッチング（NRMP）、学校選択問題など。

```python
def gale_shapley(proposer_prefs, acceptor_prefs):
    """
    proposer_prefs: {proposer_id: [acceptor_id, ...]}  ← 好きな順
    acceptor_prefs: {acceptor_id: [proposer_id, ...]}  ← 好きな順
    """
    free_proposers = list(proposer_prefs.keys())
    # 受入側: 選好を順位に変換（O(1)で比較するため）
    acceptor_rank = {}
    for a, prefs in acceptor_prefs.items():
        acceptor_rank[a] = {p: rank for rank, p in enumerate(prefs)}

    proposals = {p: 0 for p in free_proposers}  # 次に提案する相手のインデックス
    current_match = {}  # acceptor → proposer

    while free_proposers:
        proposer = free_proposers.pop(0)
        prefs = proposer_prefs[proposer]
        if proposals[proposer] >= len(prefs):
            continue  # 全員に振られた

        acceptor = prefs[proposals[proposer]]
        proposals[proposer] += 1

        if acceptor not in current_match:
            current_match[acceptor] = proposer
        elif acceptor_rank[acceptor].get(proposer, float('inf')) < \
             acceptor_rank[acceptor].get(current_match[acceptor], float('inf')):
            # 今の相手より好き → 乗り換え
            rejected = current_match[acceptor]
            current_match[acceptor] = proposer
            free_proposers.append(rejected)
        else:
            free_proposers.append(proposer)

    return {v: k for k, v in current_match.items()}  # proposer → acceptor
```

### CP-SAT（制約プログラミング）

| 項目 | 内容 |
|------|------|
| **計算量** | 規模依存（100ペアなら秒、1000ペアなら分〜時間） |
| **安定性** | ソフト制約として近似可能（ブロッキングペアにペナルティ） |
| **偏り** | 目的関数の設計次第で双方に公平にできる |
| **制約追加** | 容易（資格、時間帯、距離、上限…何でも追加可能） |
| **目的関数** | 完全にカスタマイズ可能（満足度最大化、公平性最大化、コスト最小化…） |
| **1対多** | 自然に対応（割当数上限を制約にするだけ） |

**適するケース**: 現実の業務で制約が多い場面。
介護マッチング、求人マッチング、家庭教師割当など。

```python
from ortools.sat.python import cp_model

def solve_matching_cpsat(suppliers, demanders, compatibility, constraints=None):
    """
    suppliers: ["ヘルパーA", "ヘルパーB", ...]
    demanders: ["利用者1", "利用者2", ...]
    compatibility: {(supplier_idx, demander_idx): score}  ← 相性スコア
    """
    model = cp_model.CpModel()
    n_sup = len(suppliers)
    n_dem = len(demanders)

    # 変数: x[i,j] = 1 なら supplier_i が demander_j を担当
    x = {}
    for i in range(n_sup):
        for j in range(n_dem):
            x[i, j] = model.new_bool_var(f'x_{i}_{j}')

    # 制約1: 各demander は最大1人の supplier に割当
    for j in range(n_dem):
        model.add(sum(x[i, j] for i in range(n_sup)) <= 1)

    # 制約2: 各supplier の担当数上限（例: 最大3人）
    capacity = 3
    for i in range(n_sup):
        model.add(sum(x[i, j] for j in range(n_dem)) <= capacity)

    # 制約3: 相性スコアが0（不可）のペアは割当禁止
    for i in range(n_sup):
        for j in range(n_dem):
            if compatibility.get((i, j), 0) == 0:
                model.add(x[i, j] == 0)

    # 目的関数: 相性スコアの合計を最大化
    model.maximize(
        sum(compatibility.get((i, j), 0) * x[i, j]
            for i in range(n_sup) for j in range(n_dem))
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60
    status = solver.solve(model)

    results = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for i in range(n_sup):
            for j in range(n_dem):
                if solver.value(x[i, j]) == 1:
                    results.append((suppliers[i], demanders[j],
                                    compatibility.get((i, j), 0)))
    return results
```

### 安定性をCP-SATで近似する方法

Gale-Shapleyの安定性をCP-SATでも近似できる。
ブロッキングペアにペナルティを与える方法:

```python
# ブロッキングペアのペナルティ
# p が r を現パートナーより好み、r も p を現パートナーより好む場合にペナルティ
BLOCKING_PENALTY = 100
for p_id in p_ids:
    for r_id in r_ids:
        # pがrをどの程度好むか（順位）
        # rがpをどの程度好むか（順位）
        # 両方とも現パートナーより好む場合、ペナルティ変数を立てる
        ...
```

ただし完全な安定性の保証はできない。安定性が絶対なら Gale-Shapley を使うこと。

---

## 評価指標

マッチング結果の良し悪しは複数の指標で評価する。1つだけ見ても不十分。

### 主要指標

| 指標 | 定義 | 目標 |
|------|------|------|
| **マッチ率** | マッチ成立数 / 全体数 | 高いほど良い（100%が理想） |
| **安定性** | ブロッキングペアの数（「今の相手よりお互いに好きな相手がいる」ペア） | 0が理想 |
| **満足度** | 各人が割り当てられた相手の選好順位の平均 | 低いほど良い（第1希望=1） |
| **公平性** | 供給側と需要側の満足度の標準偏差・ジニ係数 | 0に近いほど公平 |
| **待ち時間** | リクエストからマッチ成立までの所要時間 | 動的マッチングの場合に重要 |

### 指標間のトレードオフ

- **マッチ率 vs 品質**: 全員をマッチさせると互換性スコアが下がる
- **安定性 vs 最適性**: 安定マッチングが最高スコアとは限らない
- **公平性 vs 効率**: 一方に有利な割当の方が総スコアが高いことがある
- **提案側 vs 受入側**: 双方を同時に最適化はできない（パレート最適を目指す）

クライアントに「どの指標を優先するか」を必ず確認すること。

```python
def evaluate_matching(matching, proposer_prefs, acceptor_prefs):
    """マッチング結果を多面的に評価する"""
    metrics = {}

    # マッチ率
    total = max(len(proposer_prefs), len(acceptor_prefs))
    metrics['match_rate'] = len(matching) / total if total > 0 else 0

    # 満足度（選好順位の平均、低いほど良い）
    proposer_ranks = []
    acceptor_ranks = []
    for proposer, acceptor in matching.items():
        if acceptor in proposer_prefs.get(proposer, []):
            proposer_ranks.append(proposer_prefs[proposer].index(acceptor))
        if proposer in acceptor_prefs.get(acceptor, []):
            acceptor_ranks.append(acceptor_prefs[acceptor].index(proposer))

    metrics['proposer_avg_rank'] = (sum(proposer_ranks) / len(proposer_ranks)
                                     if proposer_ranks else float('inf'))
    metrics['acceptor_avg_rank'] = (sum(acceptor_ranks) / len(acceptor_ranks)
                                     if acceptor_ranks else float('inf'))

    # ブロッキングペア数
    blocking_pairs = 0
    for p1, a1 in matching.items():
        for p2, a2 in matching.items():
            if p1 == p2:
                continue
            p1_prefs = proposer_prefs.get(p1, [])
            a2_prefs = acceptor_prefs.get(a2, [])
            if (a2 in p1_prefs and a1 in p1_prefs and
                p1_prefs.index(a2) < p1_prefs.index(a1) and
                p1 in a2_prefs and p2 in a2_prefs and
                a2_prefs.index(p1) < a2_prefs.index(p2)):
                blocking_pairs += 1
    metrics['blocking_pairs'] = blocking_pairs // 2  # 重複除去

    return metrics
```

---

## 介護マッチングの具体例

最もよくある事例として、訪問介護の利用者×ヘルパーマッチングを解説する。

### Step 1: データ設計

```python
# ヘルパー（供給側）
helpers = [
    {'id': 'H1', 'name': '田中', 'qualifications': ['介護福祉士', '喀痰吸引'],
     'available': ['月AM', '火AM', '水PM', '木AM', '金PM'],
     'area': '北区', 'experience_years': 8, 'gender': '女性'},
    {'id': 'H2', 'name': '鈴木', 'qualifications': ['介護福祉士'],
     'available': ['月PM', '火PM', '水AM', '木PM', '金AM'],
     'area': '北区', 'experience_years': 3, 'gender': '男性'},
    {'id': 'H3', 'name': '佐藤', 'qualifications': ['初任者研修'],
     'available': ['月AM', '月PM', '火AM', '水AM', '木AM'],
     'area': '南区', 'experience_years': 1, 'gender': '女性'},
]

# 利用者（需要側）
users = [
    {'id': 'U1', 'name': '山田様', 'care_level': 3,
     'required_qualifications': ['介護福祉士'],
     'schedule': ['月AM', '木AM'], 'area': '北区',
     'notes': '女性ヘルパー希望'},
    {'id': 'U2', 'name': '佐々木様', 'care_level': 4,
     'required_qualifications': ['介護福祉士', '喀痰吸引'],
     'schedule': ['火AM', '金PM'], 'area': '北区',
     'notes': '経験3年以上希望'},
    {'id': 'U3', 'name': '高橋様', 'care_level': 2,
     'required_qualifications': ['初任者研修'],
     'schedule': ['月AM', '水AM'], 'area': '南区',
     'notes': '特になし'},
]
```

### Step 2: 相性スコアの設計

相性スコアは**何を重視するか**で大きく変わる。クライアントと合意してから決める。

```python
def compute_compatibility(helper, user):
    """相性スコアを0-100で返す。0は割当不可。"""
    score = 0

    # 1. 資格チェック（必須条件 → 満たさなければ0）
    for req in user['required_qualifications']:
        if req not in helper['qualifications']:
            return 0  # 割当不可

    # 2. スケジュール一致度（必須条件）
    schedule_overlap = set(helper['available']) & set(user['schedule'])
    if len(schedule_overlap) < len(user['schedule']):
        return 0  # 全スケジュールをカバーできない

    # 3. エリアの一致（重み: 30点）
    if helper['area'] == user['area']:
        score += 30
    else:
        score += 10  # 別エリアでも行けるが移動コスト

    # 4. 経験年数（重み: 20点）
    # 介護度が高い利用者にはベテランを優先
    experience_match = min(helper['experience_years'] / max(user['care_level'], 1), 1.0)
    score += int(experience_match * 20)

    # 5. 相性（過去の実績があれば加点）（重み: 30点）
    # ここは実データがあれば使う。なければ仮定で進める。
    score += 20  # 仮定: 中程度の相性

    # 6. 担当の継続性（重み: 20点）
    # 既に担当していれば加点。利用者の安心感。
    score += 0  # 初回マッチングでは0

    return score
```

**注意**: この重みはヒアリングで調整する。「資格が最重要」「地域は気にしない」など、現場の声を反映させる。

### Step 3: 制約の定義

```python
# ハード制約（絶対に守る）
hard_constraints = [
    '資格要件を満たすこと',
    'スケジュールがカバーできること',
    '1ヘルパーの担当は最大5人まで（労働基準）',
    '利用者の拒否リストに載っているヘルパーは割当しない',
]

# ソフト制約（できるだけ守る、重み付きペナルティ）
soft_constraints = [
    ('同一エリア優先', 30),       # 移動時間の削減
    ('経験年数と介護度の適合', 20),  # 安全性
    ('担当継続性', 20),            # 利用者の安心感
    ('ヘルパー間の公平性', 15),     # 担当数の偏りを減らす
    ('ヘルパーの希望', 15),         # 離職防止
]
```

### Step 4: CP-SAT で定式化

```python
from ortools.sat.python import cp_model

def solve_care_matching(helpers, users, compatibility):
    model = cp_model.CpModel()

    H = range(len(helpers))
    U = range(len(users))

    # 変数
    x = {}
    for h in H:
        for u in U:
            x[h, u] = model.new_bool_var(f'assign_{h}_{u}')

    # ハード制約1: 相性0（不可）のペアは割当禁止
    for h in H:
        for u in U:
            if compatibility[h][u] == 0:
                model.add(x[h, u] == 0)

    # ハード制約2: 各利用者は1人のヘルパーに割当（未割当も許容する場合は <= 1）
    for u in U:
        model.add(sum(x[h, u] for h in H) <= 1)

    # ハード制約3: 各ヘルパーの担当上限
    max_capacity = 5
    for h in H:
        model.add(sum(x[h, u] for u in U) <= max_capacity)

    # ソフト制約: 公平性（担当数の最大と最小の差を最小化）
    loads = []
    for h in H:
        load = model.new_int_var(0, max_capacity, f'load_{h}')
        model.add(load == sum(x[h, u] for u in U))
        loads.append(load)

    max_load = model.new_int_var(0, max_capacity, 'max_load')
    min_load = model.new_int_var(0, max_capacity, 'min_load')
    model.add_max_equality(max_load, loads)
    model.add_min_equality(min_load, loads)
    load_diff = model.new_int_var(0, max_capacity, 'load_diff')
    model.add(load_diff == max_load - min_load)

    # 目的関数: 相性スコア合計 - 公平性ペナルティ
    fairness_weight = 50  # 公平性の重み（チューニング対象）
    model.maximize(
        sum(compatibility[h][u] * x[h, u] for h in H for u in U)
        - fairness_weight * load_diff
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 60
    status = solver.solve(model)

    results = []
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for h in H:
            for u in U:
                if solver.value(x[h, u]) == 1:
                    results.append({
                        'helper': helpers[h]['name'],
                        'user': users[u]['name'],
                        'score': compatibility[h][u],
                    })
        print(f'目的関数値: {solver.objective_value}')
        print(f'担当数の偏り: {solver.value(load_diff)}')
    else:
        print('解が見つかりません。制約を緩和してください。')

    return results
```

### Step 5: 結果の評価

```python
# 確認すべきこと:
# 1. マッチ率が低すぎないか（制約が厳しすぎる可能性）
# 2. 一方の満足度だけが極端に低くないか
# 3. ブロッキングペアの数（安定性が必要な場合）
# 4. 担当数の偏り（公平性）
# 5. 未割当の利用者がいないか
```

---

## ヒアリングで聞くべきこと（マッチング特有）

マッチング問題では、**選好の構造**と**暗黙のNG条件**を引き出すことが最も重要。

### 質問1: 「今、どうやってマッチングしていますか？」

```
目的: 現状の意思決定プロセスを理解する
例:
- 「ベテランの○○さんが経験と勘で割り振っている」
  → その人の判断基準 = 暗黙の目的関数
- 「前月のシフトをコピーして微調整している」
  → 継続性が最重要制約
- 「Excelで空いている人を上から埋めている」
  → 先着順 = 公平性が考慮されていない可能性
```

### 質問2: 「絶対にやってはいけない組合せは？」

```
目的: ハード制約（NG条件）を引き出す
例:
- 「○○さんと△△さんは相性が悪い」 → NG制約
- 「介護度4以上には経験2年以上でないと」 → 資格制約
- 「男性ヘルパーNGの利用者がいる」 → 属性制約
★ 聞かないと出てこないことが多い。具体例で確認する。
```

### 質問3: 「理想のマッチングとは？」

```
目的: 目的関数の重みを合意する
例:
- 「全員にまんべんなく割り振りたい」 → 公平性重視
- 「利用者の満足度が最優先」 → 需要側の選好重視
- 「移動時間を減らしたい」 → コスト最小化
- 「なるべく同じ担当が続くように」 → 継続性重視
★ 複数の回答が出たら、優先順位をつけてもらう。
```

### 質問4: 「どのくらいの頻度で変わりますか？」

```
目的: 問題の動的性を理解する
例:
- 「月1回作り直す」 → バッチ処理で十分
- 「毎日変わる。当日キャンセルもある」 → 動的マッチングが必要
- 「基本は固定で、異動時だけ見直す」 → 差分更新で対応可能
★ 動的なら再計算の速度が重要。Gale-Shapleyの方が有利な場合も。
```

### 質問5: 「データはどこにありますか？」

```
目的: 入手可能なデータと、仮定で埋める部分を明確にする
例:
- 「利用者の情報はケアマネのファイルにある」 → 取得可能
- 「ヘルパーの好みは聞いたことがない」 → 仮定が必要
- 「過去の割当履歴はシステムにある」 → 相性の推定に使える
★ 「ないデータ」を把握することが最も重要。
  何を仮定で埋めたかを明示する（/opt-assess の出力に記載）。
```

---

## 判断フロー

問題を受け取ったら、この順番で考える。

```
1. 問題の構造を確認する
   ├── 1対1か？ 1対多か？ 多対多か？
   ├── 両側に選好があるか？ 片側だけか？
   └── マッチングは固定か？ 動的か？

2. 制約の複雑さを確認する
   ├── 資格・属性制約はあるか？
   ├── 時間帯・スケジュール制約はあるか？
   ├── 地理的制約はあるか？
   └── 制約が3つ以上 → CP-SAT一択

3. 目的関数を確認する
   ├── 安定性が最重要 → Gale-Shapley
   ├── 総スコア最大化（制約なし） → ハンガリアン法
   ├── 総スコア最大化（制約あり） → CP-SAT
   └── 公平性重視 → CP-SAT（min-max目的関数）

4. 規模を確認する
   ├── 100 × 100 以下 → CP-SAT（秒で解ける）
   ├── 1,000 × 1,000 以下 → CP-SAT（制限時間を設定して最良解）
   ├── 10,000 × 10,000 → 地域分割 or 2段階最適化
   └── 100,000+ → ヒューリスティック or 問題分割が必須

5. ベースラインを作る（/opt-baseline）
   ├── ランダム割当（下限の確認）
   ├── 貪欲法（スコア順に割当）
   └── ソルバー（CP-SAT）
   → 3つを比較してボトルネックを特定
```

---

## よくある落とし穴

### 1. 相性スコアの設計が粗すぎる

```
× スコア = 資格が合えば1、合わなければ0
○ スコア = 資格適合(0.25) + 曜日重複率(0.25) + 地域(0.20) + 性別(0.15) + 経験(0.15)
```

スコアが0か1しかないと、ソルバーは差別化できずランダムに近い結果になる。

### 2. 安定性を無視してクレームが来る

CP-SATで最適化しても、ブロッキングペアが残ることがある。
「AさんとBさんが互いに相手を好むのに別々にマッチされた」は現場でクレームになる。

**対策**: ブロッキングペアを必ずチェックし、数が多ければペナルティを追加する。

### 3. 制約を全部ハードにしてしまう

すべてをハード制約にすると実行不能（INFEASIBLE）になりやすい。

**対策**: 「絶対に破れない」ものだけハード、それ以外はソフト制約（ペナルティ）にする。

```
ハード: 資格要件、法的制約
ソフト: 地域の近さ、性別希望、曜日の重なり数
```

### 4. 公平性を考慮しない

目的関数が「総スコア最大化」だけだと、一部のペアに良いマッチが集中し、
残りが大幅に不利になる。

**対策**: ジニ係数や最小満足度の底上げを目的関数に含める。

### 5. 既存マッチングの変更コストを無視する

既にマッチが存在する状態で再最適化すると、大量の入れ替えが発生して
現場が混乱する。

**対策**: 既存マッチの維持にボーナスを与える（変更コストを目的関数に含める）。

```python
# 既存マッチの維持ボーナス
KEEP_BONUS = 50
for p_id, r_id in existing_matches.items():
    objective_terms.append(x[p_id, r_id] * KEEP_BONUS)
```

---

## 規模感と計算時間の目安

| 規模（供給側 x 需要側） | Gale-Shapley | CP-SAT | ハンガリアン法 |
|------------------------|-------------|--------|--------------|
| 10 x 10 | 瞬時 | 瞬時 | 瞬時 |
| 100 x 100 | 瞬時 | 1〜5秒 | 瞬時 |
| 1,000 x 1,000 | 瞬時 | 30秒〜数分 | 数秒 |
| 10,000 x 10,000 | 〜1秒 | 時間制限必須 | 数分 |
| 100,000+ | 数秒 | 分割が必要 | メモリ制約 |

大規模な場合の対策:
- **地域分割**: 地域ごとに独立したサブ問題に分解
- **2段階最適化**: 粗いクラスタリング → クラスタ内で精密マッチング
- **時間制限**: CP-SATの `max_time_in_seconds` を設定し、途中のFEASIBLE解を採用
