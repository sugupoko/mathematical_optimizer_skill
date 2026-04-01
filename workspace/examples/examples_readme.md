# サンプルデータ & 実行結果

> **注意**: このフォルダのデータは全て**合成データ（架空）**です。実在の人物・組織・住所とは一切関係ありません。ワークフローの動作確認とスキルの体験を目的としています。

このフォルダには6つのサンプルプロジェクトが含まれています。
全スキル（assess → baseline → improve → report → deploy）の一連のワークフローを体験できます。

---

## シフトスケジューリング（shift_scheduling/）

**10人の従業員 × 7日間 × 3交代の小規模シフト最適化問題。**

### データ
- `data/employees.csv` — 従業員マスタ（スキル、勤務時間上限、休日）
- `data/shifts.csv` — シフト定義（朝・昼・夜の21枠）
- `data/constraints.csv` — 制約条件（ハード5個 + ソフト5個）

### 実行手順
```
/opt-assess workspace/examples/shift_scheduling/data/
/opt-baseline workspace/examples/shift_scheduling/data/
/opt-improve workspace/examples/shift_scheduling/data/
/opt-report workspace/examples/shift_scheduling/results/
/opt-deploy workspace/examples/shift_scheduling/
```

### 主要な発見
- **供給46シフト < 需要48シフト → 全充足は数学的に不可能**
- 水曜朝勤(3→2名)と日曜午後勤(2→1名)の需要調整で feasible 達成
- 全ソフト制約を高水準で充足（スコア89.4/100）
- 0.02秒で最適解を生成

### サンプル結果
- `results/` — ベースライン・改善策の実験結果（JSON）、生成されたシフト表（CSV）
- `reports/v1_proposal.md` — 経営向け改善提案書（3案比較）
- `reports/deploy_design.md` — 運用設計書
- `scripts/run_weekly.py` — **本番パイプライン**（毎週金曜17:00実行）

---

## 配送ルート最適化（delivery_routing/）

**品川デポ → 東京都内20顧客 × 3台の配送ルート最適化問題。**

### データ
- `data/depot.csv` — 品川配送センター
- `data/customers.csv` — 顧客20件（座標、需要kg、時間枠、サービス時間）
- `data/vehicles.csv` — 車両3台（容量300/250/200kg、稼働8/8/6時間）

### 実行手順
```
/opt-assess workspace/examples/delivery_routing/data/
/opt-baseline workspace/examples/delivery_routing/data/
/opt-improve workspace/examples/delivery_routing/data/
/opt-report workspace/examples/delivery_routing/results/
/opt-deploy workspace/examples/delivery_routing/
```

### 主要な発見
- **需要815kg > 容量750kg（1便） → 1便では全顧客配送不可能**
- AM/PM分割で全20顧客をfeasibleにカバー（110.7km、¥12,961/日）
- V003（200kg小型車）は不要 → V001+V002の2台×2便で全顧客カバー
- 時間枠違反ゼロ、容量違反ゼロ

### サンプル結果
- `results/` — ベースライン・改善策の実験結果（JSON）、配送指示書（txt）
- `reports/v1_proposal.md` — 改善提案書（3案比較：AM/PM分割/車両入替/現状維持）
- `reports/deploy_design.md` — 運用設計書
- `scripts/run_daily.py` — **本番パイプライン**（毎朝6:00実行）

---

## 介護マッチング（care_matching/）

**15人の利用者 × 10人のヘルパーの介護マッチング問題。**

### データ
- `data/care_receivers.csv` — 利用者15名（要介護度、地域、希望曜日、性別希望、必要資格）
- `data/caregivers.csv` — ヘルパー10名（資格、地域、対応曜日、最大担当数）
- `data/compatibility_history.csv` — 過去の相性履歴（満足度1-5）
- `data/constraints.csv` — 制約条件（ハード4個 + ソフト4個）

### 実行手順
```
/opt-assess workspace/examples/care_matching/data/
/opt-baseline workspace/examples/care_matching/data/
/opt-improve workspace/examples/care_matching/data/
/opt-report workspace/examples/care_matching/results/
/opt-deploy workspace/examples/care_matching/
```

### 問題の特徴
- **双方向の選好**: 利用者の希望（性別、曜日）とヘルパーの制約（対応曜日、最大担当数）
- **資格要件**: 身体介護は介護福祉士が必須
- **地理的制約**: 同一区内 or 隣接区のみ
- **相性の考慮**: 過去のフィードバックデータで互換性スコアを計算
- Gale-Shapley（安定マッチング）と CP-SAT（制約付き最適化）の両方を試せるサンプル

---

## チケットアサイン最適化（ticket_assignment/）

**20名のエンジニア × 80件のチケットの動的チケットアサイン問題。**

### データ
- `data/engineers.csv` — エンジニア20名（L1×8, L2×8, L3×4、8種スキル）
- `data/tickets.csv` — チケット80件（25件未アサイン、55件アサイン済み、一部ブロック中）
- `data/resolution_history.csv` — 過去の解決実績300件
- `data/constraints.csv` — 制約条件

### 実行手順
```
/opt-assess workspace/examples/ticket_assignment/data/
/opt-baseline workspace/examples/ticket_assignment/data/
/opt-improve workspace/examples/ticket_assignment/data/
/opt-report workspace/examples/ticket_assignment/results/
/opt-deploy workspace/examples/ticket_assignment/
```

### 問題の特徴
- **ティア階層制約**: L1(ヘルプデスク)→L2(運用)→L3(スペシャリスト)
- **ブロック状態**: ベンダー待ち、顧客返答待ち、承認待ちなど5種
- **滞留検知**: 進捗が遅れているチケットを自動検出し再アサイン提案
- **LLM推定**: 過去実績から解決時間を推定（少量データでも動作）
- **動的再最適化**: 15分ごとに状態変化を反映して再計算

---

## 施設配置最適化（facility_location/）

**関東エリア10候補地 × 30小売店の倉庫配置最適化問題。**

### データ
- `data/candidates.csv` — 候補施設10箇所（埼玉2、千葉2、神奈川2、東京西部2、茨城1、群馬1）
- `data/customers.csv` — 小売店30店舗（関東広域に分布、需要50-250 units/月）
- `data/constraints.csv` — 制約条件（最大施設数5、カバレッジ50km以内、予算上限500万円/月）

### 実行手順
```bash
python workspace/examples/facility_location/scripts/solve_all.py
```

またはスキルを使って:
```
/opt-assess workspace/examples/facility_location/data/
/opt-baseline workspace/examples/facility_location/data/
/opt-improve workspace/examples/facility_location/data/
/opt-report workspace/examples/facility_location/results/
```

### 主要な発見
- **UFL（容量制約なし）では1施設に全集約される**: 固定費が支配的で施設増加のコストが輸送費削減を上回る
- **CFL（容量制約付き）で4施設が最適**: W01(さいたま)、W06(厚木)、W09(土浦)、W10(太田)
- **月額312万円で全30店舗をカバー**: 全施設開設（819万円）から62%削減
- **水戸ショップ（S21）が50km要件を満たさない**: 追加候補地 or 要件緩和が必要
- PuLP + CBC で全手法0.1秒以内に求解

### サンプル結果
- `results/all_results.json` — 全7手法の数値結果
- `reports/v1_proposal.md` — 改善提案書（4施設体制推奨）
- `expected/baseline_summary.md` — ベースライン比較サマリ

### 参照テンプレート
- `reference/facility_location_template.py` — 施設配置テンプレート（UFL/CFL/P-median）
- `reference/facility_location_guide.md` — 施設配置ガイド

---

## 構造最適化（structural_design/）

**片持ち梁の断面最適化 + トポロジー最適化（SIMP法）。**

離散（組合せ）最適化ではなく、連続変数の最適化問題のサンプル。
scipy.optimize と numpy のみで構造設計の最適化ワークフローを体験できる。

### データ
- `data/structure.json` — 構造定義（片持ち梁、SS400、荷重条件）
- `data/constraints.json` — 設計制約（応力、たわみ、寸法範囲）

### 実行手順
```bash
python workspace/examples/structural_design/scripts/solve_all.py
```

### 主要な発見
- **最大断面（300x500mm）は過剰設計**: 応力利用率わずか0.9%
- **SLSQP最適化で重量96.2%削減**: 2,355kg → 89kg
- **応力制約がアクティブ**（応力比1.00）、たわみには余裕あり
- **トポロジー最適化**: 体積率30-50%で典型的なトラス状構造が出現
- 全計算が約20秒で完了（scipy + numpy のみ）

### サンプル結果
- `results/all_results.json` — 全手法の数値結果
- `results/topology_vf_*.png` — トポロジー最適化の密度分布画像
- `results/convergence_vf_*.png` — 収束曲線
- `reports/v1_proposal.md` — 改善提案書（3案比較）

### 参照テンプレート
- `reference/continuous_optimization_template.py` — 連続最適化テンプレート
- `reference/continuous_optimization_guide.md` — 連続最適化ガイド

---

## 期待される結果

各プロジェクトの `expected/` フォルダに、初期のベースライン結果のサンプルがあります。
`results/` フォルダには、全ワークフロー実行後の実際の結果が含まれています。
実行環境やソルバーのバージョンにより多少の差異が出る場合があります。

---

## 施設配置最適化（facility_location/）

**関東圏10候補地 × 30小売店の倉庫配置問題。**

### データ
- `data/candidates.csv` — 候補地10箇所（埼玉、千葉、神奈川、東京西部、茨城、群馬）
- `data/customers.csv` — 小売店30店舗（関東圏に分散）
- `data/constraints.csv` — 制約条件

### 実行手順
```
python workspace/examples/facility_location/scripts/solve_all.py
```

### 問題の特徴
- **非容量制約付き施設配置（UFL）**: 固定費+輸送費の最小化
- **容量制約付き施設配置（CFL）**: 倉庫容量の制限あり
- **P-median**: 開設数を固定して距離最小化
- PuLP + HiGHS で解くMIP問題

---

## 構造最適化（structural_design/）

**片持ち梁の断面設計 + 2Dトポロジー最適化。**

### データ
- `data/structure.json` — 構造定義（荷重、材料、境界条件）
- `data/constraints.json` — 設計制約（応力、変位、寸法）

### 実行手順
```
python workspace/examples/structural_design/scripts/solve_all.py
```

### 問題の特徴
- **連続最適化**: scipy.optimizeによるビーム断面の最適設計
- **トポロジー最適化**: SIMP法による材料配置の最適化
- 離散最適化（CP-SAT/MIP）ではなく、連続変数の非線形最適化
- NumPyによる簡易FEM（有限要素法）実装
