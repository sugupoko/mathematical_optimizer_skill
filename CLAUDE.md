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
pip install ortools omegaconf matplotlib numpy pandas

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
├── OPTIMIZATION_MINDSET.md        ← 7つの思考回路
├── .claude/skills/                ← 5つのスキル（/opt-xxx で呼び出し）
│   ├── opt-assess/                ← データ受領→問題分類→仮説
│   ├── opt-baseline/              ← 3ベースライン→ボトルネック特定
│   ├── opt-improve/               ← 改善策設計→検証（繰り返し可）
│   ├── opt-report/                ← 経営向け提案書作成
│   └── opt-request/               ← 追加データ依頼書生成
├── reference/                     ← 実装パターン集・ヒアリングガイド
│   ├── ortools_guide.md           ← CP-SAT vs Routing の使い分け
│   ├── scheduling_template.py     ← シフト最適化のコード雛形
│   ├── vrp_template.py            ← 配送ルートのコード雛形
│   ├── evaluator_template.py      ← 評価関数の雛形
│   ├── data_preprocessing.md      ← データ前処理の定石
│   ├── improvement_patterns.md    ← 6つの改善定石パターン
│   ├── hearing_templates.md       ← ヒアリングガイド
│   ├── hearing_sheet_shift.md     ← 記入用シート（シフト業務）
│   └── hearing_sheet_routing.md   ← 記入用シート（配送ルート）
└── workspace/                     ← ★ここで作業する
    └── my_project/                ← プロジェクトごとにフォルダを作成
        ├── data/                  ← クライアントから受け取ったデータ
        ├── scripts/               ← 作成したスクリプト
        ├── results/               ← 実験結果
        └── reports/               ← 提案書・レポート
```

## 使い方

### Step 0: ヒアリング（データを受け取る前に）
```
reference/hearing_sheet_shift.md   ← シフト業務の場合
reference/hearing_sheet_routing.md ← 配送ルートの場合
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

## スキル一覧

| スキル | コマンド | いつ使うか |
|--------|---------|----------|
| **opt-assess** | `/opt-assess [data]` | データを受け取った直後 |
| **opt-baseline** | `/opt-baseline [data]` | assessの後 |
| **opt-improve** | `/opt-improve [data]` | baselineの後（繰り返し可） |
| **opt-report** | `/opt-report [results]` | 改善が終わった後 |
| **opt-request** | `/opt-request` | 途中でデータが足りない時 |

## ワークフロー

```
ヒアリング → データ受領 → /opt-assess → /opt-baseline → /opt-improve → /opt-report
                                                          ↑    ↓
                                                          └── /opt-request
```

## 対応する問題の種類

- スケジューリング（シフト、タスク割当、ジョブショップ）
- 巡回・配送（TSP、VRP、配送ルート）
- パッキング（ビンパッキング、2Dカッティング）
- 割当（マッチング、集合被覆）
- 組合せ最適化全般

## 使用するツール

- **Google OR-Tools** (CP-SAT, Routing): 主力ソルバー（無料）
- **Python標準ライブラリ**: ヒューリスティクス実装
- **matplotlib**: 可視化
- **pandas**: データ前処理

## 5つの原則

1. **まずソルバーで解けるか試す**（5分でベースラインを作る）
2. **評価関数を先に読む**（何を最適化するか理解してからコードを書く）
3. **目的関数と評価関数を一致させる**（これだけで+15-27%改善した実績）
4. **仮定を常に明示する**（データがない部分の仮定が間違えば結果も間違う）
5. **不可能なら不可能と言う**（「車両を増やしてください」は最も価値のある提言）
