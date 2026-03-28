# Mathematical Optimizer Skill Pack

Claude Code で数理最適化を行うためのスキルパック。

工場のシフト表作成、Amazonの配送ルート最適化、Kaggle Santaコンペ2025（クリスマスツリーパッキング）の上位解法を参考に、**最適化スペシャリストの思考パターンを7つに抽出してスキル化**した。

「シフト表を最適化して」「配送ルートを効率化して」と言われた時に、**データを受け取ってから改善提案を出すまで**を再現性のある手順で進められる。

## こういう人向け

- 「最適化やりたいけど何から始めれば？」という人
- OR-Toolsは知っているが、問題の分析→改善→提案の流れが定まっていない人
- 現場からデータを受け取って、経営に提案書を出す立場の人

## 何ができるか

1. **雑なデータを受け取って、問題の種類を分類**（シフト？配送ルート？割当？）
2. **5分でベースラインを構築**し、何がボトルネックかを特定
3. **ボトルネックに合った改善策を設計・検証**（コードテンプレート付き）
4. **経営向けの改善提案書を生成**（コスト・効果・導入難易度の比較表）
5. **追加データの依頼書を生成**（何が・なぜ・ないとどうなるかを説明）

さらに、現場のヒアリングシート（記入欄付き）で**データに載っていない暗黙の制約**を引き出せる。

## セットアップ

```bash
git clone https://github.com/xxx/mathematical_optimizer_skill.git
cd mathematical_optimizer_skill
pip install ortools omegaconf matplotlib numpy pandas
```

Claude Code でこのフォルダを開いて使う。

## 使い方

### 1. ヒアリング（データを受け取る前に）

`reference/` にヒアリングシートがある。印刷して現場で使う。

| シート | 対象 |
|--------|------|
| `hearing_sheet_shift.md` | シフト調整業務 |
| `hearing_sheet_routing.md` | 配送ルート・集配業務 |

### 2. データを受け取ったら

```bash
mkdir -p workspace/my_project/data
cp /path/to/client_data.xlsx workspace/my_project/data/
```

Claude Code で以下のスキルを順に実行する:

```
/opt-assess workspace/my_project/data/     → 問題の分類と仮説
/opt-baseline workspace/my_project/data/   → 3ベースライン + ボトルネック特定
/opt-improve workspace/my_project/data/    → 改善策の設計と検証（繰り返し）
/opt-report workspace/my_project/results/  → 経営向け提案書
```

途中でデータが足りなければ `/opt-request` で依頼書を生成。

## ディレクトリ構成

```
mathematical_optimizer_skill/
├── README.md                      ← このファイル
├── CLAUDE.md                      ← Claude Code 向けの詳細ガイド
├── OPTIMIZATION_MINDSET.md        ← 最適化スペシャリストの7つの思考回路
├── .claude/skills/                ← 5つのスキル
│   ├── opt-assess/                ← 問題アセスメント
│   ├── opt-baseline/              ← ベースライン構築
│   ├── opt-improve/               ← 改善策の設計・検証
│   ├── opt-report/                ← 提案書作成
│   └── opt-request/               ← 追加データ依頼書
├── reference/                     ← 実装テンプレート集
│   ├── ortools_guide.md           ← OR-Tools の使い分け（CP-SAT vs Routing）
│   ├── scheduling_template.py     ← シフト最適化のコード雛形
│   ├── vrp_template.py            ← 配送ルートのコード雛形
│   ├── evaluator_template.py      ← 評価関数の雛形
│   ├── data_preprocessing.md      ← データ前処理の定石
│   ├── improvement_patterns.md    ← 6つの改善定石パターン
│   ├── hearing_templates.md       ← ヒアリングガイド（質問の意図）
│   ├── hearing_sheet_shift.md     ← 記入用シート（シフト業務）
│   └── hearing_sheet_routing.md   ← 記入用シート（配送ルート）
└── workspace/                     ← ここで作業する
```

## 対応する問題

- **スケジューリング**: シフト表、タスク割当、時間割
- **巡回・配送**: 配送ルート、営業巡回、集配ルート
- **パッキング**: コンテナ積載、倉庫配置
- **割当**: マッチング、組合せ選択

## 5つの原則

1. **まずソルバーで解けるか試す** — 5分でベースラインを作る
2. **評価関数を先に読む** — 何を最適化するか理解してからコードを書く
3. **目的関数と評価関数を一致させる** — これだけで+15-27%改善
4. **仮定を常に明示する** — 仮定が間違えば結果も間違う
5. **不可能なら不可能と言う** — 最も価値のある提言になり得る

## ライセンス

MIT

## 謝辞

このスキルパックは Claude Code (Claude Opus 4.6) との協働で開発し、内容は人間がチェック・編集しています。
