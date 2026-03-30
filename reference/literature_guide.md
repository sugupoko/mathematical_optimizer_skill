# 文献・既存手法の調査ガイド

## いつ調査するか

```
問題に出会った
  │
  ④ パターン認識で問題クラスを特定
  │
  ├── 小規模（~100変数）+ 標準的な制約
  │     → 調査不要。CP-SAT / OR-Tools Routing で即解ける
  │
  ├── 中規模（~1,000変数）+ 標準的な制約
  │     → 定番ソルバーの設定調整で対応可能。調査は軽めでOK
  │
  ├── 大規模（10,000+変数）
  │     → ★調査必須。分解戦略・メタヒューリスティクスの選択に論文が役立つ
  │
  ├── 特殊な制約がある
  │     → ★調査推奨。同業界の事例で制約設計のヒントが見つかる
  │
  └── コンペ / 品質を極限まで追求
        → ★調査必須。問題固有のムーブ設計に先行研究が不可欠
```

---

## 問題クラス別の定番手法と調査先

### スケジューリング（シフト、タスク割当、時間割）

| 規模 | 定番手法 | 参考 |
|------|---------|------|
| 小〜中 | CP-SAT（OR-Tools） | OR-Tools公式チュートリアル |
| 中〜大 | MIP（Gurobi, CPLEX, HiGHS） | Gurobi公式事例集 |
| 大規模 | Column Generation | Desrosiers & Lübbecke (2005) |
| 柔軟性重視 | Constraint Programming | IBM CP Optimizer ドキュメント |

**調べるべきキーワード:**
- `nurse scheduling problem` (NSP) — シフト最適化の最も研究された問題
- `employee timetabling` — 時間割
- `job shop scheduling` — 工場のジョブスケジューリング
- `resource-constrained project scheduling` (RCPSP) — プロジェクト管理

**ベンチマーク:**
- NSPLib（看護師スケジューリング）: https://people.cs.kuleuven.be/~pieter.smet/nsplib.html
- INRC-II（国際看護師ロスタリングコンペ）

**教科書:**
- Pinedo "Scheduling: Theory, Algorithms, and Systems" — スケジューリング理論の定番
- Baptiste, Le Pape, Nuijten "Constraint-Based Scheduling" — CP系

---

### 配車・巡回（TSP, VRP, CVRP, VRPTW）

| 規模 | 定番手法 | 参考 |
|------|---------|------|
| ~100ノード | OR-Tools Routing Library | OR-Tools公式VRPチュートリアル |
| ~1,000ノード | HGS-CVRP（Vidal 2022） | github.com/vidalt/HGS-CVRP |
| ~10,000ノード | LKH-3 | webhotel4.ruc.dk/~keld/research/LKH-3/ |
| 時間枠付き | ALNS（Ropke & Pisinger） | Ropke & Pisinger (2006) |
| 動的 | リアルタイム再最適化 | Psaraftis et al. (2016) |

**調べるべきキーワード:**
- `capacitated vehicle routing problem` (CVRP) — 容量制約付き
- `vehicle routing with time windows` (VRPTW) — 時間枠付き
- `pickup and delivery problem` (PDP) — 集荷と配送
- `rich vehicle routing` — 実務的な複合制約

**ベンチマーク:**
- CVRPLIB: http://vrp.galgos.inf.puc-rio.br/index.php — VRP問題の網羅的データベース
- Solomon instances — VRPTW の標準ベンチマーク（100顧客）
- Gehring & Homberger — 大規模VRPTW（200-1000顧客）

**教科書:**
- Toth & Vigo "Vehicle Routing: Problems, Methods, and Applications" — VRPのバイブル
- Laporte, Ropke, Vidal "Heuristics for Vehicle Routing" — メタヒューリスティクス中心

---

### マッチング（割当、安定マッチング）

| 問題タイプ | 定番手法 | 参考 |
|-----------|---------|------|
| 1対1安定マッチング | Gale-Shapley | Gale & Shapley (1962) |
| 重み付き最大マッチング | ハンガリアン法 | Kuhn (1955) |
| 制約付きマッチング | CP-SAT / MIP | 問題に応じて定式化 |
| オンラインマッチング | Karp-Vazirani-Vazirani | KVV (1990) |
| 腎臓交換 | Cycle/Chain formulation | Abraham, Blum, Sandholm (2007) |

**調べるべきキーワード:**
- `stable matching` — 安定マッチング（ノーベル経済学賞2012）
- `hospital-resident matching` — 研修医マッチング
- `home care assignment optimization` — 介護マッチング
- `school choice mechanism` — 学校選択
- `kidney exchange` — 腎臓交換（マッチング理論の応用で最も命に関わる）

**教科書:**
- Roth & Sotomayor "Two-Sided Matching" — マッチング理論の基礎
- Manlove "Algorithmics of Matching Under Preferences" — アルゴリズム寄り

---

### パッキング（ビンパッキング、2Dカッティング）

| 問題タイプ | 定番手法 | 参考 |
|-----------|---------|------|
| 1Dビンパッキング | First Fit Decreasing (FFD) | Johnson (1973) |
| 2Dカッティング | Branch & Bound + ヒューリスティクス | Lodi, Martello, Monaci (2002) |
| 3Dパッキング | ツリー探索 + 配置ヒューリスティクス | 問題特化が必要 |
| ストリップパッキング | NFDH, FFDH | Coffman et al. (1980) |

**調べるべきキーワード:**
- `bin packing problem` — ビンパッキング
- `cutting stock problem` — 切り出し問題（製造業）
- `container loading` — コンテナ積載
- `strip packing` — 帯状パッキング

**ベンチマーク:**
- BPPLIB: https://site.unibo.it/operations-research/en/research/bpplib — ビンパッキング
- 2DCPackLib — 2Dカッティング

---

### ナップサック・集合被覆

| 問題タイプ | 定番手法 | 参考 |
|-----------|---------|------|
| 0-1ナップサック | 動的計画法 / MIP | Kellerer, Pferschy, Pisinger (2004) |
| 多次元ナップサック | MIP + LP緩和 | Pisinger (2005) |
| 集合被覆 | 貪欲法 + MIP | Caprara, Toth, Fischetti (2000) |
| 施設配置 | MIP + ラグランジュ緩和 | Cornuéjols, Nemhauser, Wolsey |

---

## 調査の実践手順

### Step 1: 問題クラスの英語名を特定する

日本語の業務記述から英語の問題クラス名に変換する。これができれば論文検索の80%は完了。

```
よくある変換:
  「シフト表を作りたい」→ nurse scheduling problem
  「配送ルートを最適化」→ vehicle routing problem with time windows
  「人と仕事を割り当て」→ assignment problem / matching
  「箱に詰める」→ bin packing problem
  「最適な組合せを選ぶ」→ knapsack problem / set cover
  「施設をどこに建てるか」→ facility location problem
  「在庫をどれだけ持つか」→ inventory optimization
  「いつ発注するか」→ lot sizing problem
```

### Step 2: 既存の最良手法を確認する

```
調査先（優先度順）:
  1. OR-Tools 公式ドキュメント・チュートリアル
     → 動くコードがすぐ手に入る。まずここから。
  2. Google Scholar で "problem_name survey" を検索
     → サーベイ論文1本で分野の全体像が掴める
  3. ベンチマークサイトの結果表
     → 手法間の性能比較が一目でわかる
  4. GitHub で "problem_name solver" を検索
     → OSSの実装が見つかることがある
  5. Kaggle / AtCoder 等の過去コンペ
     → 実践的なテクニックが上位解法に凝縮されている
```

### Step 3: 調査結果を判断に変換する

```
調べた結果:
  ├── 標準問題に帰着できた + OSSソルバーがある
  │     → そのソルバーを使う（調査終了、実装に移る）
  │
  ├── 標準問題に帰着できた + 規模が大きい
  │     → ベンチマーク上位の手法を確認
  │     → 分解戦略の論文を1-2本読む
  │
  ├── 標準問題に帰着できない（特殊制約が多い）
  │     → 最も近い問題クラスを探す
  │     → 同業界の事例論文で制約設計を参考にする
  │     → CP-SAT でカスタム定式化する
  │
  └── 全く新しい問題
        → まずCP-SATで素朴に定式化して解けるか試す
        → 解けなければメタヒューリスティクスの設計に移る
        → この場合、論文より実験の方が価値がある
```

---

## 調査が特に役立つケースと役立たないケース

### ★ 役立つ

| ケース | 理由 | 例 |
|--------|------|-----|
| 大規模問題 | 分解戦略の選択に先行研究が不可欠 | 10,000ノードVRP → LKH-3 or HGS |
| 業界特有の制約 | 同じ業界の論文で制約設計のヒントが見つかる | 介護スケジューリング → NSP派生研究 |
| 品質を極限まで追求 | 問題固有のムーブ設計に先行研究が参考になる | Kaggle Santa → double-bridge, k-opt |
| 既存OSSの性能比較 | 複数ソルバーの特性を知った上で選択できる | Gurobi vs CPLEX vs HiGHS vs OR-Tools |
| 近似解の品質保証 | 近似率や下界の計算方法が論文に載っている | 近似アルゴリズムの保証率 |

### × 役立たない（調べるより解いた方が速い）

| ケース | 理由 |
|--------|------|
| 小規模問題（~100変数） | CP-SATで数秒で最適解が出る |
| 標準的なVRP（~50ノード） | OR-Tools Routingのデフォルト設定で十分 |
| 制約が単純 | 教科書の定番手法で解ける |
| データが不完全 | 論文の手法を適用する前にデータの仮定を固める方が重要 |

---

## よく使うサーベイ論文（分野別）

後で詳しく読むための入口。Google Scholar で検索して最新版を確認すること。

| 分野 | 推奨サーベイ | ポイント |
|------|------------|---------|
| VRP全般 | Laporte (2009) "Fifty years of vehicle routing" | 歴史と主要手法の網羅 |
| VRPTW | Bräysy & Gendreau (2005) | メタヒューリスティクスの比較 |
| 看護師スケジューリング | Burke et al. (2004) "The state of the art of nurse rostering" | 制約分類と手法比較 |
| マッチング | Roth (2008) "Deferred acceptance algorithms" | ノーベル賞受賞者のサーベイ |
| ビンパッキング | Coffman, Csirik, Galambos et al. (2013) | オンライン/オフラインの整理 |
| メタヒューリスティクス | Gendreau & Potvin "Handbook of Metaheuristics" | SA, GA, LNS, ALNS等の網羅 |
| LLM × 最適化 | Romera-Paredes et al. (2024) "FunSearch" | LLMでヒューリスティクスを進化 |

---

## /opt-assess での活用

アセスメントの Phase 2（問題の理解）で、パターン認識（思考回路④）を行う際に本ガイドを参照する。

```
手順:
  1. 問題クラスを特定する（上の変換表を使う）
  2. 該当する問題クラスのセクションを確認する
  3. 規模に応じて調査の深さを決める
  4. 調査結果をアセスメントに記載:
     - 「既知の問題クラス: VRPTW」
     - 「定番手法: OR-Tools Routing + Guided Local Search」
     - 「参考: Solomon benchmarkでの性能上位はHGS, ALNS」
     - 「今回は50ノードなのでOR-Toolsで十分」
```
