# Changelog / 変更履歴

All notable changes to this project will be documented in this file.
全ての注目すべき変更はこのファイルに記録する。

---

## [v2.0.0] - 2026-03-30

### Added / 新規追加

#### Sample Data & E2E Demo / サンプルデータ & E2Eデモ
- `workspace/examples/shift_scheduling/` — Synthetic shift scheduling (10 employees x 7 days) / シフト最適化サンプル
- `workspace/examples/delivery_routing/` — Synthetic delivery routing (20 locations x 3 vehicles in Tokyo) / 配送ルートサンプル
- Each example includes `expected/baseline_summary.md` / 期待される結果のスナップショット

#### New Skill / 新スキル
- `/opt-deploy` — Operations design: automation, monitoring, fallback / 運用設計スキル

#### New Reference Guides / 新リファレンスガイド
- `reference/pulp_highs_guide.md` — PuLP + HiGHS for LP/MIP problems / LP/MIP向けガイド
- `reference/multiobjective_guide.md` — Multi-objective optimization (Pareto front, epsilon-constraint) / 多目的最適化
- `reference/state_schema.md` — Inter-skill state management (.opt_state.yaml) / スキル間状態管理スキーマ

#### Internationalization / 英語対応
- `README.md` は日本語メイン、上部に英語版リンク
- `README_en.md` に英語版を追加
- `CHANGELOG.md` を日英バイリンガル化

### Changed / 改善

#### All Skills Enhanced / 全スキルの強化
- Added **Troubleshooting** section to all 5 existing skills / トラブルシューティング追加
- Added **State Management** section to all skills (.opt_state.yaml integration) / 状態管理追加

#### OPTIMIZATION_MINDSET.md
- Added **LLM checklist prompts** for all 7 thinking patterns / LLM向けチェックリスト判断プロンプト追加

#### Code Templates / コードテンプレート
- `scheduling_template.py` — Added type hints + docstrings / 型ヒント+docstring追加
- `vrp_template.py` — Added type hints + docstrings / 型ヒント+docstring追加
- `evaluator_template.py` — Added type hints + docstrings + `verify_objective_evaluation_alignment()` / 目的関数と評価関数の乖離を自動検証

#### Data Preprocessing / データ前処理
- `data_preprocessing.md` — Added **Large-scale distance matrix** section / 大規模距離行列の扱いを追加
  - int16 scaling, sparse matrix (k-NN), on-demand computation / 3手法

#### CLAUDE.md
- Added **Git-based versioning strategy** (branch + tag) / Gitベースバージョニング戦略追加
- Updated directory structure for new files / ディレクトリ構成更新
- Added opt-deploy to skill list / スキル一覧更新
- Added `pulp`, `scipy` to dependencies / 依存パッケージ追加

---

## [v1.0.0] - 2026-03-29

### Added / 新規追加
- Initial release / 初回リリース
- 5 skills: opt-assess, opt-baseline, opt-improve, opt-report, opt-request / 5つのスキル
- 7 optimization thinking patterns (OPTIMIZATION_MINDSET.md) / 7つの思考回路
- Reference collection: OR-Tools guide, code templates, hearing sheets / リファレンス集
- 6 proven improvement patterns / 6つの改善定石パターン
