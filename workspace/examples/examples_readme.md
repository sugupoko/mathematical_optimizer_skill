# サンプルデータ & 実行結果

> **注意**: このフォルダのデータは全て**合成データ（架空）**です。実在の人物・組織・住所とは一切関係ありません。ワークフローの動作確認とスキルの体験を目的としています。

このフォルダには 8 つのサンプルプロジェクトが含まれています。
全スキル (assess → baseline → improve → report) の一連のワークフローを体験できます。

各サンプルは `data/` (入力) を持ち、`v1/` フォルダ (バージョン管理) の中に
`spec.md` / `scripts/` / `results/` / `reports/` を配置した構成です。

## 8 サンプルの早見表

| サンプル | 問題タイプ | 複雑度 | 特徴 |
|---|---|:---:|---|
| `shift_scheduling/` | スケジューリング | simple | 小規模シフト、需給不足の典型例 |
| `delivery_routing/` | VRP | simple | 配送ルート最適化、AM/PM 分割 |
| `care_matching/` | マッチング | medium | 介護利用者×ヘルパー、双方向選好 |
| `ticket_assignment/` | 動的割当 | medium | ITSM、滞留検知、LLM 推定 |
| `facility_location/` | 施設配置 | simple | UFL/CFL/P-median (MIP) |
| `structural_design/` | 連続最適化 | - | scipy + SIMP によるトポロジー最適化 |
| **`worker_supervisor/`** | **複合スケジューリング** | **complex** | **12 HC、段階的 baseline で infeasibility を特定** |
| **`clinic_nurse/`** | **複数施設スケジューリング** | **complex** | **1,296 変数、全 HC 充足可能な複合問題** |

---

## ワンショット体験

Claude Code でこれを打つだけで自動実行されます:

```
workspace/examples/shift_scheduling/data/ にあるデータで、最適化して
```

別の問題を試すには `shift_scheduling` を他の名前 (`worker_supervisor` 等) に置き換えるだけ。

---

## シフトスケジューリング (shift_scheduling/)

**10 人の従業員 × 7 日間 × 3 交代の小規模シフト最適化。**

### データ
- `data/employees.csv` — 従業員マスタ (スキル、勤務時間上限、休日)
- `data/shifts.csv` — シフト定義 (朝・昼・夜の 21 枠)
- `data/constraints.csv` — 制約条件 (ハード 5 + ソフト 5)

### 主要な発見
- **供給 46 シフト < 需要 48 シフト → 全充足は数学的に不可能**
- 1 名追加 (W011) で全シフト feasible
- 既存 10 名のまま運用するなら、週末シフトの需要調整が必要

### 見どころ
構造的な人手不足を数学的に証明する最小サンプル。

---

## 配送ルート最適化 (delivery_routing/)

**品川デポ → 東京都内 20 顧客 × 3 台の配送ルート最適化。**

### データ
- `data/depot.csv` — 品川配送センター
- `data/customers.csv` — 顧客 20 件 (座標、需要 kg、時間枠、サービス時間)
- `data/vehicles.csv` — 車両 3 台 (容量 300/250/200kg)

### 主要な発見
- **需要 815kg > 容量 750kg (1 便) → 1 便では全顧客配送不可能**
- AM/PM 分割で全 20 顧客を feasible にカバー (110.7km、¥12,961/日)
- V003 (200kg 小型車) は不要

### 見どころ
「時間で分割する」という改善パターンの実例。

---

## 介護マッチング (care_matching/)

**15 人の利用者 × 10 人のヘルパーの介護マッチング。**

### データ
- `data/care_receivers.csv` — 利用者 15 名 (要介護度、地域、希望曜日、性別希望、必要資格)
- `data/caregivers.csv` — ヘルパー 10 名 (資格、地域、対応曜日、最大担当数)
- `data/compatibility_history.csv` — 過去の相性履歴 (満足度 1-5)

### 問題の特徴
- **双方向の選好**: 利用者の希望とヘルパーの制約
- **資格要件**: 身体介護は介護福祉士が必須
- **地理的制約**: 同一区内 or 隣接区のみ
- Gale-Shapley (安定マッチング) と CP-SAT の両方を試せる

---

## チケットアサイン最適化 (ticket_assignment/)

**20 名のエンジニア × 80 件のチケットの動的アサイン。**

### データ
- `data/engineers.csv` — エンジニア 20 名 (L1×8, L2×8, L3×4)
- `data/tickets.csv` — チケット 80 件 (一部ブロック中)
- `data/resolution_history.csv` — 過去実績 300 件

### 問題の特徴
- **ティア階層**: L1→L2→L3
- **ブロック状態**: ベンダー待ち、顧客返答待ち等 5 種
- **滞留検知**: 進捗の遅れを自動検出して再アサイン
- **LLM 推定**: 過去実績から解決時間を推定

---

## 施設配置最適化 (facility_location/)

**関東 10 候補地 × 30 小売店の倉庫配置。**

### データ
- `data/candidates.csv` — 候補施設 10 箇所
- `data/customers.csv` — 小売店 30 店舗
- `data/constraints.csv` — 制約 (最大施設数 5、カバレッジ 50km、予算 500 万円/月)

### 主要な発見
- **UFL (容量制約なし) では 1 施設に全集約される**
- **CFL で 4 施設が最適**: W01, W06, W09, W10
- 月額 312 万円で全店舗カバー (全施設開設比 62% 削減)
- 水戸ショップ S21 が 50km 要件を満たさない

### 参照テンプレート
- `reference/facility_location_template.py`
- `reference/facility_location_guide.md`

---

## 構造最適化 (structural_design/)

**片持ち梁の断面最適化 + トポロジー最適化 (SIMP 法)。**

離散 (組合せ) 最適化ではなく、連続変数の最適化問題のサンプル。
scipy.optimize と numpy のみで構造設計の最適化ワークフローを体験できる。

### データ
- `data/structure.json` — 構造定義 (片持ち梁、SS400、荷重条件)
- `data/constraints.json` — 設計制約 (応力、たわみ、寸法範囲)

### 主要な発見
- **最大断面は過剰設計**: 応力利用率わずか 0.9%
- **SLSQP で重量 96.2% 削減**: 2,355kg → 89kg
- **トポロジー最適化**: 体積率 30-50% でトラス状構造が出現

### 参照テンプレート
- `reference/continuous_optimization_template.py`
- `reference/continuous_optimization_guide.md`

---

## worker_supervisor/ — complex 問題の実例 (infeasible)

**20 作業者 + 8 監督者 × 2 週 42 シフト = 1,176 変数の複合問題。**

v3.2.0 で追加された **段階的 baseline** の代表サンプル。HC 12 個、ペア制約 (forbidden/mentorship/preferred) あり、bilingual シフト (言語 × スキル制約) あり。

### データ
- `data/workers.csv` — 作業者 20 名 (senior 8 / mid 8 / junior 4、複数スキル、言語)
- `data/supervisors.csv` — 監督者 8 名 (general / bilingual / technical)
- `data/shifts.csv` — 42 シフト (bilingual 必須 8 件)
- `data/pair_constraints.csv` — forbidden 2, mentorship 4, preferred 3
- `data/constraints.csv` — HC×12, SC×8

### 主要な発見
- **Phase 5 (HC7+HC8) で壁に到達** — 段階的 baseline が 0.15 秒で特定
- **鳩の巣原理による構造的不可能性**:
  - en + reception を持つ作業者: 4 名
  - bilingual+reception シフトの需要: 5 名/シフト × 4 シフト
  - 4 < 5 → どんなアルゴリズムでも配置不可能
- **HC9-HC12 (休息・ペア) は無実** と証明される (段階的 baseline の価値)
- **1 名追加 (W021: en+reception)** で全 12 HC 充足可能

### 見どころ
- 段階的 baseline の **active / pending 分離** による壁 Phase の即特定
- **独立 HC 検証器** が B/C/D シナリオで違反を検知 (ソルバーの FEASIBLE フラグは信用しない)
- 「解けない」を数値で証明し、**入力変更 / 仕様変更 / 運用変更** の 3 案を提示する実例

---

## clinic_nurse/ — complex 問題の実例 (solvable)

**18 看護師 × 3 クリニック × 2 週 72 シフト = 1,296 変数の複合問題。**

v3.2.0 で追加。worker_supervisor と対照的に、**全 HC を満たす解が存在する** complex 問題。

### データ
- `data/nurses.csv` — 看護師 18 名 (senior 6 / mid 8 / junior 4、資格、home_clinic)
- `data/clinics.csv` — 3 クリニック (中央 / 北 / 南)
- `data/shifts.csv` — 72 シフト (クリニック別)
- `data/constraints.csv` — HC×8, SC×6

### 主要な発見
- **全 8 Phase feasible、Phase 7 で pending=0 達成**
- 需要 144 人・シフト / 供給 172 人・シフト = 84% (スラック 16%)
- シナリオ A (balanced) で overall SC = 90.0
- **home_clinic 最重視 (V3)** は逆効果: SC4 を +2.1 上げる代わりに SC2 が -52.5 悪化 (トレードオフの実例)

### 見どころ
- 段階的 baseline が「全 Phase 成功」を示す実例
- **本物の SC トレードオフ** が見られる (worker_supervisor は制約がタイトすぎてトレードオフが出ない)
- 解けた状態で「優先度の違いが結果にどう影響するか」を検証できる

---

## 期待される結果

- 各プロジェクトの `v1/results/` フォルダに数値結果 (JSON) があります
- `v1/reports/` フォルダに assess/baseline/improve/proposal の全レポートがあります
- `v1/scripts/` に再実行可能な Python コードがあります

実行環境や OR-Tools のバージョンにより多少の差異が出る場合があります。
