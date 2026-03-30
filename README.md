**[English version here (README_en.md)](./README_en.md)**

---

# Mathematical Optimizer Skill Pack

> **注意**: これは数理最適化を勉強しながら作成したものです。合成データでの検証のみで、実務で使えるかはわかりません。「こういうアプローチがあるんだな」程度の参考としてご覧ください。

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
6. **運用設計**（自動化・監視・フォールバック）

さらに、現場のヒアリングシート（記入欄付き）で**データに載っていない暗黙の制約**を引き出せる。

## セットアップ

```bash
git clone https://github.com/xxx/mathematical_optimizer_skill.git
cd mathematical_optimizer_skill
pip install ortools omegaconf matplotlib numpy pandas pulp scipy
```

Claude Code でこのフォルダを開いて使う。

## クイックスタート（サンプルデータで体験）

`workspace/examples/` にサンプルデータがあります。30分で一連のフローを体験できます。

```
/opt-assess workspace/examples/shift_scheduling/data/
/opt-baseline workspace/examples/shift_scheduling/data/
```

詳しくは [workspace/examples/README.md](./workspace/examples/README.md) を参照。

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
/opt-deploy workspace/my_project/          → 運用設計（自動化・監視）
```

途中でデータが足りなければ `/opt-request` で依頼書を生成。

## ディレクトリ構成

```
mathematical_optimizer_skill/
├── README.md                      ← このファイル（日本語）
├── README_en.md                   ← 英語版README
├── CHANGELOG.md                   ← 変更履歴（日英バイリンガル）
├── CLAUDE.md                      ← Claude Code 向けの詳細ガイド
├── OPTIMIZATION_MINDSET.md        ← 7つの思考回路 + LLM向けチェックリスト
├── .claude/skills/                ← 6つのスキル
│   ├── opt-assess/                ← 問題アセスメント
│   ├── opt-baseline/              ← ベースライン構築
│   ├── opt-improve/               ← 改善策の設計・検証
│   ├── opt-report/                ← 提案書作成
│   ├── opt-request/               ← 追加データ依頼書
│   └── opt-deploy/               ← 運用設計（自動化・監視・フォールバック）
├── reference/                     ← 実装テンプレート集
│   ├── ortools_guide.md           ← OR-Tools の使い分け（CP-SAT vs Routing）
│   ├── pulp_highs_guide.md        ← PuLP + HiGHS（LP/MIP向け）
│   ├── multiobjective_guide.md    ← 多目的最適化（パレートフロント等）
│   ├── scheduling_template.py     ← シフト最適化のコード雛形
│   ├── vrp_template.py            ← 配送ルートのコード雛形
│   ├── matching_template.py        ← マッチング問題の雛形（Gale-Shapley + CP-SAT）
│   ├── matching_guide.md           ← マッチング問題ガイド
│   ├── evaluator_template.py      ← 評価関数の雛形 + 一致検証
│   ├── data_preprocessing.md      ← データ前処理の定石 + 大規模距離行列
│   ├── improvement_patterns.md    ← 6つの改善定石パターン
│   ├── state_schema.md            ← スキル間状態管理スキーマ
│   ├── hearing_templates.md       ← ヒアリングガイド（質問の意図）
│   ├── hearing_sheet_shift.md     ← 記入用シート（シフト業務）
│   ├── hearing_sheet_routing.md   ← 記入用シート（配送ルート）
│   └── hearing_sheet_matching.md  ← 記入用シート（マッチング問題）
└── workspace/                     ← ここで作業する
    ├── examples/                  ← サンプルデータ（E2Eデモ用）
    │   ├── shift_scheduling/      ← シフト最適化サンプル（10人×7日）
    │   ├── delivery_routing/      ← 配送ルートサンプル（20地点×3台）
    │   └── care_matching/         ← 介護マッチングサンプル（15利用者×10ヘルパー）
    └── my_project/                ← プロジェクトごとにフォルダを作成
```

## 対応する問題

- **スケジューリング**: シフト表、タスク割当、時間割
- **巡回・配送**: 配送ルート、営業巡回、集配ルート
- **パッキング**: コンテナ積載、倉庫配置
- **マッチング**: 介護×ヘルパー、求人、メンタリング（双方向選好付き）
- **割当**: リソース配分、組合せ選択

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
