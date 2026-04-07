# CLAUDE.md — Mathematical Optimizer Skill Pack

## 概要

数理最適化の問題を受け取ってから改善提案を出すまでのワークフローをスキル化したもの。
シフト最適化（25手法比較）と配送ルート最適化（5難易度×9手法）の実験から得た知見を凝縮している。

**核心**: LLMは「問題を解く」のではなく「問題の解き方を設計する」ために使う。

## セットアップ

```bash
# 1. クローン
git clone https://github.com/xxx/mathematical_optimizer_skill.git
cd mathematical_optimizer_skill

# 2. 依存パッケージ
pip install ortools omegaconf matplotlib numpy pandas pulp scipy

# 3. このフォルダでClaude Codeを起動
claude

# 4. データを workspace/ に置いて作業開始
mkdir -p workspace/my_project
cp /path/to/client_data.xlsx workspace/my_project/
```

## ディレクトリ構成

```
mathematical_optimizer_skill/
├── CLAUDE.md                      ← このファイル（プロジェクトガイド）
├── OPTIMIZATION_MINDSET.md        ← 7つの思考回路 + LLM向けチェックリスト
├── README.md                      ← 日本語版README（メイン）
├── README_en.md                   ← 英語版README
├── .claude/skills/                ← 6つのスキル（/opt-xxx で呼び出し）
│   ├── opt-assess/                ← データ受領→問題分類→仮説
│   ├── opt-baseline/              ← 3ベースライン→ボトルネック特定
│   ├── opt-improve/               ← 改善策設計→検証（繰り返し可）
│   ├── opt-report/                ← 経営向け提案書作成
│   ├── opt-request/               ← 追加データ依頼書生成
│   └── opt-deploy/               ← 運用設計（自動化・監視・フォールバック）
├── reference/                     ← 実装パターン集・ヒアリングガイド
│   ├── ortools_guide.md           ← CP-SAT vs Routing の使い分け
│   ├── pulp_highs_guide.md        ← PuLP + HiGHS（LP/MIP向け）
│   ├── multiobjective_guide.md    ← 多目的最適化（パレートフロント等）
│   ├── scheduling_template.py     ← シフト最適化のコード雛形
│   ├── vrp_template.py            ← 配送ルートのコード雛形
│   ├── evaluator_template.py      ← 評価関数の雛形 + 一致検証
│   ├── data_preprocessing.md      ← データ前処理の定石 + 大規模距離行列
│   ├── improvement_patterns.md    ← 6つの改善定石パターン
│   ├── state_schema.md            ← スキル間状態管理スキーマ
│   ├── hearing_templates.md       ← ヒアリングガイド
│   ├── matching_template.py        ← マッチング問題のコード雛形（Gale-Shapley + CP-SAT）
│   ├── matching_guide.md           ← マッチング問題ガイド（安定マッチング、介護等）
│   ├── ticket_assignment_template.py ← チケットアサイン最適化テンプレート（LLM推定+滞留検知+再アサイン）
│   ├── ticket_assignment_guide.md  ← チケットアサイン最適化ガイド（ITIL、ティア階層、動的再最適化）
│   ├── ml_optimization_guide.md    ← ML×最適化の組合せガイド（4パターン+実装例）
│   ├── awesome_optimization_cases.md ← 世界の数理最適化 実務事例集（UPS/Amazon/日本製鉄等）
│   ├── literature_guide.md         ← 文献・既存手法の調査ガイド（問題クラス別）
│   ├── facility_location_template.py ← 施設配置問題のコード雛形（UFL/CFL/P-median）
│   ├── facility_location_guide.md  ← 施設配置問題ガイド（倉庫配置、EV充電等）
│   ├── continuous_optimization_template.py ← 連続最適化テンプレート（構造設計・形状・トポロジー）
│   ├── continuous_optimization_guide.md ← 連続最適化ガイド（scipy.optimize・SIMP法）
│   ├── hearing_sheet_shift.md     ← 記入用シート（シフト業務）
│   ├── hearing_sheet_routing.md   ← 記入用シート（配送ルート）
│   ├── hearing_sheet_matching.md  ← 記入用シート（マッチング問題）
│   ├── hearing_sheet_ticket.md   ← 記入用シート（チケットアサイン）
│   └── spec_template.md          ← 仕様書テンプレート（プロジェクトの「今の正」）
└── workspace/                     ← ★ここで作業する
    ├── examples/                  ← サンプルデータ（E2Eデモ用）
    │   ├── shift_scheduling/      ← シフト最適化サンプル（10人×7日）
    │   ├── delivery_routing/      ← 配送ルートサンプル（20地点×3台）
    │   ├── care_matching/         ← 介護マッチングサンプル（15利用者×10ヘルパー）
    │   ├── ticket_assignment/    ← チケットアサインサンプル（20エンジニア×80チケット）
    │   ├── facility_location/    ← 施設配置サンプル（10候補×30小売店）
    │   └── structural_design/    ← 構造最適化サンプル（片持ち梁・トポロジー）
    └── my_project/                ← プロジェクトごとにフォルダを作成
        ├── v1/                    ← バージョンごとに一式まとまる
        │   ├── spec.md            ← ★ 仕様書（このバージョンの条件）
        │   ├── data/              ← 入力データ
        │   ├── .opt_state.yaml    ← スキル間の状態管理ファイル
        │   ├── scripts/           ← 作成したスクリプト
        │   ├── results/           ← 実験結果
        │   └── reports/           ← 提案書・レポート
        └── v2/                    ← 追加データや制約変更で新バージョン
            ├── spec.md            ← 更新された仕様書
            └── ...
```

## 使い方

### Step 0: ヒアリング（データを受け取る前に）
```
reference/hearing_sheet_shift.md     ← シフト業務の場合
reference/hearing_sheet_routing.md   ← 配送ルートの場合
reference/hearing_sheet_matching.md  ← マッチング問題の場合
reference/hearing_sheet_ticket.md   ← チケットアサインの場合
→ 印刷して現場で記入。暗黙の制約を引き出す。
```

### Step 1: データを受け取ったら
```
/opt-assess workspace/my_project/data/
→ 問題の分類、仮説、不足情報の特定
```

### Step 2: ベースラインを作る
```
/opt-baseline workspace/my_project/data/
→ ランダム/貪欲法/ソルバーの3ベースライン
→ ボトルネック制約の特定
```

### Step 3: 改善する（繰り返し）
```
/opt-improve workspace/my_project/data/
→ ボトルネックに合った改善策を設計・検証
→ 足りなければ /opt-request で追加データ依頼
```

### Step 4: 報告する
```
/opt-report workspace/my_project/results/
→ 経営向けの改善提案書を生成
```

## 出力ルール（全スキル共通）

**全成果物はバージョンフォルダ（`v1/`, `v2/`, ...）内に出力する。**
最新バージョンの `spec.md` が「今の正」。テンプレートは `reference/spec_template.md` を参照。

| スキル | 出力ファイル（vN/ 内） |
|--------|-----------|
| opt-assess | `spec.md`（初版生成） + `reports/assess_report.md` |
| opt-baseline | `reports/baseline_report.md` + `scripts/baseline.py` + `results/baseline_results.json` |
| opt-improve | `spec.md`（変更があれば更新） + `reports/improve_report.md` + `scripts/improve.py` + `results/improve_results.json` |
| opt-report | `reports/proposal.md` |
| opt-request | `reports/data_request.md` |
| opt-deploy | `reports/deploy_design.md` + `scripts/run_*.py`（本番パイプライン） |

これにより:
- **spec.md を見れば「今どの条件で動いているか」が常にわかる**
- バージョン間の spec.md を比較すれば変更点がわかる
- 各バージョンが独立しているので、いつでも再実行できる
- クライアントに成果物として渡せる

## スキル一覧

| スキル | コマンド | いつ使うか |
|--------|---------|----------|
| **opt-assess** | `/opt-assess [data]` | データを受け取った直後 |
| **opt-baseline** | `/opt-baseline [data]` | assessの後 |
| **opt-improve** | `/opt-improve [data]` | baselineの後（繰り返し可） |
| **opt-report** | `/opt-report [results]` | 改善が終わった後 |
| **opt-request** | `/opt-request` | 途中でデータが足りない時 |
| **opt-deploy** | `/opt-deploy [project]` | 提案承認後、運用設計する時 |

## ワークフロー

```
ヒアリング → データ受領 → /opt-assess → /opt-baseline → /opt-improve → /opt-report → /opt-deploy
                                                          ↑    ↓
                                                          └── /opt-request
```

## 追加情報が来た時の進め方

最適化は1回で終わらない。追加データやフィードバックが来るたびにサイクルを回す。

### 何が来たかによる分岐

```
追加情報が来た
  ├── A. ヒアリングの回答
  │     「この制約は緩和できます」「実際は20分かかります」
  │     → 仮定を修正 → /opt-improve をもう1周
  │
  ├── B. 追加データ（GPSログ、実績データ等）
  │     → /opt-assess で追加データを分析
  │     → 仮定を実データで置き換え
  │     → /opt-baseline からやり直し
  │
  ├── C. 制約の変更
  │     「夜勤は週2回までに変更」
  │     → 制約を修正 → /opt-baseline からやり直し
  │
  └── D. 優先度の変更
        「コストより公平性を重視して」
        → 目的関数の重みを変更 → /opt-improve をもう1周
```

### workspace のバージョン管理

バージョンごとに一式をまとめる。spec.md が各バージョンの仕様書。

```
workspace/my_project/
├── v1/
│   ├── spec.md                ← v1 の仕様書
│   ├── data/                  ← 最初にもらったデータ
│   ├── scripts/
│   ├── results/
│   └── reports/
├── v2/
│   ├── spec.md                ← v2 の仕様書（v1 からの変更点を記載）
│   ├── data/                  ← 追加で来たデータ
│   ├── scripts/
│   ├── results/
│   └── reports/
└── ...
```

前のバージョンを残す理由:
- v1 と v2 の spec.md を比較すれば「何が変わったか」がわかる
- 各バージョンの results/ を比較すれば Before/After が出せる
- クライアントに変化の経緯を説明できる

### Git ベースのバージョン管理（推奨）

フォルダの `v1/`, `v2/` 管理は小規模なら問題ないが、ファイルが増えると破綻する。
Git ブランチとタグを使う方が再現性が高く、差分管理も容易。

```bash
# プロジェクト開始時: ブランチを作成
git checkout -b opt/client-name/v1-initial

# 作業が一段落したら: タグで結果を記録
git tag opt/client-name/v1 -m "初回ベースライン: ソルバーfeasible, score=520"

# 追加データが来た時: 新しいブランチを作成
git checkout -b opt/client-name/v2-with-gps

# 作業が完了したら: タグを打つ
git tag opt/client-name/v2 -m "GPSログ追加: 違反5件→2件, score=650"

# Before/After の確認
git diff opt/client-name/v1..opt/client-name/v2 -- workspace/
```

**命名規則:**
- ブランチ: `opt/<client>/<version>-<description>`
- タグ: `opt/<client>/<version>`
- タグメッセージ: 主要な結果の数値を含める

**注意:**
- クライアントデータを Git に入れる場合は `.gitignore` でセンシティブなデータを除外
- 大きなファイル（GPS ログ等）は Git LFS を検討
- 社内リポジトリを使う場合はアクセス権限に注意

---

## 対応する問題の種類

- スケジューリング（シフト、タスク割当、ジョブショップ）
- 巡回・配送（TSP、VRP、配送ルート）
- パッキング（ビンパッキング、2Dカッティング）
- マッチング（介護×ヘルパー、求人、メンタリング等の双方向選好付き割当）
- チケットアサイン（ITSM、バグトラッカー、カスタマーサポート等の動的タスク割当）
- 施設配置（倉庫配置、店舗立地、EV充電ステーション、病院配置）
- 割当（集合被覆、リソース配分）
- 組合せ最適化全般

## 使用するツール

- **Google OR-Tools** (CP-SAT, Routing): 主力ソルバー（無料）
- **PuLP + HiGHS**: LP/MIP ソルバー（無料、連続変数に強い）
- **Python標準ライブラリ**: ヒューリスティクス実装
- **matplotlib**: 可視化
- **pandas**: データ前処理
- **scipy**: 疎行列、クラスタリング補助

## 5つの原則

1. **まずソルバーで解けるか試す**（5分でベースラインを作る）
2. **評価関数を先に読む**（何を最適化するか理解してからコードを書く）
3. **目的関数と評価関数を一致させる**（これだけで+15-27%改善した実績）
4. **仮定を常に明示する**（データがない部分の仮定が間違えば結果も間違う）
5. **不可能なら不可能と言う**（「車両を増やしてください」は最も価値のある提言）
