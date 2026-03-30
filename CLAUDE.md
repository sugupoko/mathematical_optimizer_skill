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
│   ├── literature_guide.md         ← 文献・既存手法の調査ガイド（問題クラス別）
│   ├── hearing_sheet_shift.md     ← 記入用シート（シフト業務）
│   ├── hearing_sheet_routing.md   ← 記入用シート（配送ルート）
│   └── hearing_sheet_matching.md  ← 記入用シート（マッチング問題）
└── workspace/                     ← ★ここで作業する
    ├── examples/                  ← サンプルデータ（E2Eデモ用）
    │   ├── shift_scheduling/      ← シフト最適化サンプル（10人×7日）
    │   ├── delivery_routing/      ← 配送ルートサンプル（20地点×3台）
    │   └── care_matching/         ← 介護マッチングサンプル（15利用者×10ヘルパー）
    └── my_project/                ← プロジェクトごとにフォルダを作成
        ├── data/                  ← クライアントから受け取ったデータ
        ├── .opt_state.yaml        ← スキル間の状態管理ファイル
        ├── scripts/               ← 作成したスクリプト
        ├── results/               ← 実験結果
        └── reports/               ← 提案書・レポート
```

## 使い方

### Step 0: ヒアリング（データを受け取る前に）
```
reference/hearing_sheet_shift.md     ← シフト業務の場合
reference/hearing_sheet_routing.md   ← 配送ルートの場合
reference/hearing_sheet_matching.md  ← マッチング問題の場合
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

**各スキルは結果をMarkdownドキュメントとして `reports/` に保存すること。**
スクリプトは `scripts/`、数値結果は `results/` に保存する。

| スキル | 出力ファイル |
|--------|-----------|
| opt-assess | `reports/assess_report.md` |
| opt-baseline | `reports/baseline_report.md` + `scripts/baseline.py` + `results/baseline_results.json` |
| opt-improve | `reports/improve_report.md` + `scripts/improve.py` + `results/improve_results.json` |
| opt-report | `reports/v1_proposal.md`（バージョン連番） |
| opt-request | `reports/data_request.md` |
| opt-deploy | `reports/deploy_design.md` + `scripts/run_*.py`（本番パイプライン） |

これにより:
- 後続スキルが前のスキルの結果を参照できる
- クライアントに成果物として渡せる
- Git で変更履歴を追跡できる

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

前の結果は消さない。追加が来るたびにバージョンを分けて、Before/Afterを出せるようにする。

```
workspace/my_project/
├── data/
│   ├── v1_initial/            ← 最初にもらったデータ
│   ├── v2_with_gps/           ← 追加で来たGPSログ
│   └── v3_constraint_change/  ← 制約変更後
├── results/
│   ├── v1/                    ← 初回の結果
│   ├── v2/                    ← 追加データ反映後
│   └── v3/                    ← 制約変更後
├── reports/
│   ├── v1_proposal.md         ← 初回提案
│   ├── v2_update.md           ← 「データ追加で精度向上」
│   └── v3_final.md            ← 最終提案
└── changelog.md               ← 何が変わって何をやり直したか
```

### changelog.md の書き方

```markdown
## v2 (日付) — GPSログ追加
- 追加データ: gps_log.csv（直近3ヶ月の走行実績）
- 修正した仮定: 移動速度 30km/h → 実測22km/h
- やり直した範囲: /opt-baseline からやり直し
- 結果: 違反5件→2件に改善
- 新たにわかったこと: 朝の渋滞が想定以上
```

前の結果を残す理由:
- 「追加データでどれだけ改善したか」のBefore/Afterが出せる
- 「制約変更で何が犠牲になったか」のトレードオフが見える
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
