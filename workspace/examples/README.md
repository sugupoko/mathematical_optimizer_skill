# サンプルデータ & 実行結果

このフォルダには2つのサンプルプロジェクトが含まれています。
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

## 期待される結果

各プロジェクトの `expected/` フォルダに、初期のベースライン結果のサンプルがあります。
`results/` フォルダには、全ワークフロー実行後の実際の結果が含まれています。
実行環境やソルバーのバージョンにより多少の差異が出る場合があります。
