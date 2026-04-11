# Changelog / 変更履歴

All notable changes to this project will be documented in this file.
全ての注目すべき変更はこのファイルに記録する。

---

## [v3.4.0] - 2026-04-11

### Added / 新規追加

#### New Example: flexible_job_shop (largest) / 柔軟ジョブショップ (最大規模)
- 40 jobs × 15 machines × 12 operators × 227 operations / 40 ジョブ × 15 機械 × 12 オペレーター
- **9,283 variables, 21,721 constraints** (via model.Proto())
- **20 HCs + 6 SCs** — machine non-overlap, precedence, setup time, tool constraints, operator skills
- Uses CP-SAT `NewOptionalIntervalVar` + `AddNoOverlap` pattern for true scheduling
- All 11 phases feasible, all 4 improve scenarios satisfy 20/20 HCs
- Clear Pareto tradeoff: throughput (1740min makespan, heavy imbalance) vs smooth (fair workload, +8% makespan)
- **Largest example in the skill pack** — manufacturing domain for contrast with service-sector samples

#### examples_readme.md Enhanced / サンプル README 拡充
- Summary table now includes variable count, HC count, and SC count / 早見表に変数数・HC 数・SC 数を追加
- 11 examples total / 全 11 サンプル

---

## [v3.3.0] - 2026-04-11

### Added / 新規追加

#### New Example: multi_depot_routing / マルチデポ配送VRP
- 3 depots × 8 vehicles × 12 drivers × 30 customers × 5 days = 1,680 vars / 関東圏 MD-VRPTW
- **13 HCs** (capacity, time window, vehicle type, driver cert, rest, etc.)
- All 12 phases feasible (0.52s total) / 全 Phase feasible
- SC tradeoff discovered: 6 vehicles/1694km vs 5 vehicles/1727km / 車両数 vs 距離のトレードオフ

#### New Example: hospital_or_scheduling (hardest example) / 手術室スケジューリング (最難関)
- 50 patients × 6 ORs × 5 days, **22 HCs + 8 SCs**, ~2,900 binary vars
- Surgeons (15) × anesthesiologists (10) × nurses (20) with specialty and certification requirements
- Cardiac/pediatric room equipment constraints, ICU bed capacity, urgent patient windows
- Fully solvable: 50/50 patients scheduled with all 22 HCs satisfied
- Clear tradeoff: coverage (50/50 + surgeon spread 775min) vs fairness (34/50 + spread 175min)
- **Hardest example in the skill pack** — demonstrates staged baseline on 22 HCs

#### examples_readme.md Updated / サンプル README 更新
- Now lists 10 examples with HC counts / 10 サンプルと HC 数を一覧化
- hospital_or_scheduling 🏆 highlighted as flagship complex example

---

## [v3.2.0] - 2026-04-11

### Added / 新規追加

#### Complexity-Driven Baseline Strategy / 複雑度判定によるbaseline戦略
- `opt-assess` adds a 5-axis complexity evaluation (simple/medium/complex) / 5軸の複雑度評価を追加
- `opt-baseline` branches strategy based on complexity / 複雑度に応じて戦略を切り替え
  - simple: single-shot (random + greedy + solver)
  - medium: single-shot first, staged as fallback
  - complex: **staged baseline mandatory** / 段階的解法必須

#### Staged Baseline with Active/Pending Split / 段階的baselineとactive/pending分離
- HCs added incrementally phase-by-phase / HCを1つずつ段階的に追加
- Independent HC verifier splits violations into: / 独立検証器が違反を2分類:
  - **active**: HCs enforced in this phase (should be 0) / 強制中のHC違反 (0であるべき)
  - **pending**: HCs not yet added (ok if > 0) / 未追加のHC違反 (許容)
- Delta (Δ) between phases shows constraint interaction effects / Phase間の差分で制約追加の副作用を可視化

#### Root Cause Analysis + Solution Options / 根本原因分析+解決策
- When infeasibility is detected, opt-baseline mandates: / infeasibility検出時に必須:
  - Numerical root cause via pigeonhole or supply-demand gap / 数値的な根本原因
  - Exoneration of innocent constraints / 無実の制約の明示
  - 3-category solution options (A input / B spec / C operations) / 3カテゴリの解決策

#### Independent HC Verifier in opt-improve / opt-improveの独立HC検証器
- `verify_hard_constraints()` re-checks all HCs from raw assignment / rawから全HCを再チェック
- Does not trust solver's FEASIBLE flag for softened models / 緩和モデルのfeasibleは信用しない
- Distinguishes `solver_feasible` from `hc_all_satisfied` / 両者を明確に区別

#### New Example: clinic_nurse / 新サンプル: clinic_nurse
- Multi-clinic nurse scheduling (18 nurses × 3 clinics × 2 weeks, 1,296 vars) / 複数クリニック看護師配置
- Designed as solvable complex problem (16% slack) / 解ける複合問題として設計
- All 8 phases feasible, Phase 7 reaches pending=0 / 全Phase feasible、Phase7で全HC充足
- Complements worker_supervisor (unsolvable case) for contrast / worker_supervisorとの対比用

### Fixed / 修正
- Baseline phase output now clearly distinguishes correctness (active) from progress (pending) / Phase出力が明確に

---

## [v3.1.0] - 2026-04-08

### Added / 新規追加

#### Source Traceability / 情報源トレーサビリティ
- `spec_template.md` now includes a **情報源 (Ref) table** / 仕様書に情報源テーブルを追加
- Every constraint, assumption, and change has a Ref column linking to its source / 全制約・仮定に参照番号（Ref）
- Sources: data files, hearing notes, emails, regulations, analyst assumptions / データ・ヒアリング・メール・規則・仮定

#### Confirmation-Style Questionnaire / 確認型質問書
- opt-request rewritten: "we understand X — is this correct? A/B/C" format / 「こう理解していますが合っていますか？」形式に改訂
- 4 question patterns: hard/soft, value, priority, operations / 4つの質問パターン
- opt-assess also updated to use confirmation-style questions / opt-assess も同形式に統一

#### QA Process / QA プロセス
- opt-improve now includes 6 QA checks after spec updates / spec 更新後に6項目の QA チェック
- Checks: HC↔code, SC↔objective, assumption values, eval↔objective, contradictions, source freshness / HC・SC・仮定・評価関数・矛盾・情報鮮度
- Contradictions auto-generate confirmation-style questions / 矛盾検出時に確認型質問を自動生成

#### SC Variant Comparison / ソフト制約バリエーション比較
- opt-improve generates 3-5 weight variants and scores each SC 0-100 / SC 重み配分を変えた複数案を生成
- opt-report includes variant comparison table for client decision / 提案書にバリエーション比較テーブル
- shift_scheduling example: all 5 variants identical (proves zero slack) / 全5案同一＝余裕ゼロの証明

#### shift_scheduling Example Re-run / シフト最適化サンプル再実行
- Full workflow with all new features (Ref, confirmation questions, QA, variants, delivery) / 全新機能を反映して再実行

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

### Added / 新規追加（実験的）

#### Delivery Guide / 結果の届け方ガイド
- `reference/delivery_guide.md` — Delivery format selection guide (5 dimensions, 7 formats) / 納品形態の選び方ガイド
- `reference/hearing_templates.md` — Added shared acceptance/operations hearing template / 受け入れ・運用ヒアリングテンプレート追加
- `reference/spec_template.md` — Added acceptance requirements section / 受け入れ要件セクション追加
- `workspace/examples/shift_scheduling/v1/delivery/` — Excel delivery sample with constraint checker / Excel 納品サンプル

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
