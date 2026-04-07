# Changelog / 変更履歴

All notable changes to this project will be documented in this file.
全ての注目すべき変更はこのファイルに記録する。

---

## [v3.0.0] - 2026-04-07

### Changed / 大幅変更

#### Versioned Folder Structure / バージョンフォルダ構成
- All project outputs now live under `v1/`, `v2/`, etc. / 全成果物をバージョンフォルダ（v1/, v2/, ...）に格納
- Each version is a complete snapshot: spec.md + data + scripts + results + reports / 各バージョンが独立した一式
- `spec.md` in the latest version folder is the single source of truth for constraints / 最新版の spec.md が「今の正」

#### Specification Document / 仕様書（spec.md）導入
- `reference/spec_template.md` — New template for per-version specs / バージョンごとの仕様書テンプレート
- opt-assess generates initial spec.md; opt-improve updates it on changes / assess で初版生成、improve で変更時に更新
- Tracks objectives, hard/soft constraints, assumptions, and change diffs / 目的・制約・仮定・変更差分を一元管理

#### README Simplified / README 簡素化
- Quick start rewritten as 3 clear steps: place data, give instruction, see results / クイックスタートを3ステップに
- Removed redundant "使い方" section / 重複セクション削除
- Directory tree condensed to essentials / ディレクトリ構成を簡潔化

#### Examples Re-run / サンプル再実行
- Deleted old flat outputs from all 6 examples / 旧フラット出力を全削除
- Re-ran shift_scheduling through full workflow under v1/ structure / shift_scheduling を v1/ 構成で再実行
- Key finding: 1 additional staff member resolves all shortages / 1名追加で全シフト充足

#### All Skills Updated / 全スキル更新
- All 6 skills now output to versioned folders / 全6スキルがバージョンフォルダに出力
- State management (.opt_state.yaml) scoped to version folder / 状態管理もバージョンフォルダ内に
- opt-report output changed: `v1_proposal.md` → `proposal.md` (folder handles versioning) / フォルダでバージョン管理

---

## [v2.4.0] - 2026-04-01

### Added / 新規追加

#### Facility Location / 施設配置問題
- `reference/facility_location_template.py` (606行) — UFL/CFL/P-medianの3手法
- `reference/facility_location_guide.md` — 倉庫配置、EV充電、基地局の使い分けガイド
- `workspace/examples/facility_location/` — 関東圏10候補×30店舗のサンプル+結果

#### Continuous Optimization / 連続最適化
- `reference/continuous_optimization_template.py` (886行) — 構造設計、形状最適化、トポロジー最適化(SIMP法)
- `reference/continuous_optimization_guide.md` — scipy.optimize、FEM接続、商用ツールとの使い分け
- `workspace/examples/structural_design/` — 片持ち梁の断面設計+2Dトポロジー最適化サンプル+結果

#### README大幅拡充
- 実社会の課題マップ（製造/物流/IT/医療/金融/エネルギー/教育/エンジニアリング）
- テンプレート+サンプルあり/ガイドのみの対応状況表

---

## [v2.2.0] - 2026-04-01

### Added / 新規追加

#### Ticket Assignment Support / チケットアサイン問題対応
- `reference/ticket_assignment_template.py` — CP-SAT + LLM推定 + 滞留検知 + 再アサインの統合テンプレート (937行)
- `reference/ticket_assignment_guide.md` — チケットアサイン最適化ガイド（ITIL、ティア階層、動的再最適化、ブロック状態）
- `reference/hearing_sheet_ticket.md` — チケットアサイン固有のヒアリングシート

#### Ticket Assignment Example / チケットアサインサンプル
- `workspace/examples/ticket_assignment/` — 20エンジニア×80チケットのサンプルデータ
- L1/L2/L3ティア階層、8種スキル、ブロック状態、ITIL分類

#### Skill Output Rules / スキル出力ルール
- 全6スキルに結果ドキュメント保存の指示を追加
- CLAUDE.md に「出力ルール（全スキル共通）」セクション追加

---

## [v2.1.0] - 2026-03-30

### Added / 新規追加

#### Matching Problem Support / マッチング問題対応
- `reference/matching_template.py` — Gale-Shapley + CP-SAT マッチングテンプレート
- `reference/matching_guide.md` — マッチング問題ガイド（安定マッチング、使い分け、評価指標）
- `reference/hearing_sheet_matching.md` — マッチング問題のヒアリングシート

#### Care Matching Example / 介護マッチングサンプル
- `workspace/examples/care_matching/` — 15利用者×10ヘルパーの介護マッチングサンプル
- 利用者データ（要介護度、地域、希望曜日、性別希望、必要資格）
- ヘルパーデータ（資格、対応地域、対応曜日、最大担当数）
- 過去の相性履歴データ

#### E2E Sample Results / サンプル実行結果
- `workspace/examples/shift_scheduling/` — 全スキル実行結果（スクリプト+提案書+運用設計+本番パイプライン）
- `workspace/examples/delivery_routing/` — 全スキル実行結果（スクリプト+提案書+配送指示書+本番パイプライン）

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
