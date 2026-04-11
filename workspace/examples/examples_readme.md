# サンプルデータ & 実行結果

> **注意**: このフォルダのデータは全て**合成データ（架空）**です。実在の人物・組織・住所とは一切関係ありません。ワークフローの動作確認とスキルの体験を目的としています。

このフォルダには 14 個のサンプルプロジェクトが含まれています。
全スキル (assess → baseline → improve → report) の一連のワークフローを体験できます。

各サンプルは `data/` (入力) を持ち、`v1/` フォルダ (バージョン管理) の中に
`spec.md` / `scripts/` / `results/` / `reports/` を配置した構成です。

## 14 サンプルの早見表

| サンプル | 問題タイプ | 複雑度 | 変数数 | HC | SC | 特徴 |
|---|---|:---:|---:|---:|---:|---|
| `shift_scheduling/` | スケジューリング | simple | 210 | 5 | 5 | 小規模シフト、需給不足の典型例 |
| `delivery_routing/` | VRP | simple | ~100 | 5 | 4 | AM/PM 分割で全顧客カバー |
| `care_matching/` | マッチング | medium | ~150 | 4 | 4 | 介護利用者×ヘルパー、双方向選好 |
| `ticket_assignment/` | 動的割当 | medium | ~500 | 6 | 5 | ITSM、滞留検知、LLM 推定 |
| `facility_location/` | 施設配置 | simple | ~40 | 3 | 3 | UFL/CFL/P-median (MIP) |
| `structural_design/` | 連続最適化 | - | 連続 | - | - | scipy + SIMP、トポロジー最適化 |
| **`worker_supervisor/`** | **複合スケジューリング** | **complex** | **1,176** | **12** | **8** | **段階的 baseline で infeasibility を特定** |
| **`clinic_nurse/`** | **複数施設スケジューリング** | **complex** | **1,296** | **8** | **6** | **全 HC 充足可能、SC トレードオフ** |
| **`multi_depot_routing/`** | **マルチデポ VRP** | **complex** | **1,680** | **13** | **6** | **6台 vs 5台の車両数トレードオフ** |
| **`hospital_or_scheduling/`** | **手術室スケジューリング** | **complex** | **~2,900** | **22** | **8** | **50 患者・6 OR・全 22 HC 充足** |
| 🏆 **`flexible_job_shop/`** | **柔軟ジョブショップ (FJSP)** | **complex** | **9,283** | **20** | **6** | **最大規模: 40 ジョブ×15 機械、製造業** |
| 💉 **`vaccine_allocation/`** | **COVID-19 ワクチン配分** | **complex** | **1,801** | **18** | **6** | **2 回接種の時系列連動、コロナ禍題材** |
| 🔥 **`gpu_cluster_scheduling/`** | **GPU クラスタスケジューリング** | **complex** | **4,166** | **22** | **8** | **LLM 時代の最重要: 75 ジョブ × 44 GPU、19 Phase 段階化** |
| 🤖 **`inventory_ml_hybrid/`** | **ML×最適化ハイブリッド (在庫)** | **complex** | **~2,100** | **18** | **8** | **146k 行の履歴 → sklearn 予測 → CP-SAT 発注計画 (廃棄 −31%)** |

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

## multi_depot_routing/ — complex VRP (solvable)

**3 デポ × 8 車両 × 12 ドライバー × 30 顧客 × 5 日間の配送計画。**

関東圏 (東京/さいたま/横浜) を対象としたマルチデポ VRP with Time Windows + Heterogeneous Fleet。
1,680 変数、13 HCs、6 SCs。

### データ
- `data/depots.csv` — 3 デポ
- `data/vehicles.csv` — 8 車両 (標準小/中/大 + 冷蔵 3 台、不可日あり)
- `data/drivers.csv` — 12 ドライバー (認定: standard / refrigerated / dangerous_goods)
- `data/customers.csv` — 30 顧客 (冷蔵必須 8、危険物必須 7、時間枠要求あり)
- `data/constraints.csv` — HC×13, SC×6

### 主要な発見
- **全 12 Phase feasible、0.52 秒で完了**
- 需給 27% でゆとりあり → 将来 2-3 倍の需要増にも対応可能
- **SC トレードオフ発見**: 6 車両運用 (1,694 km) vs 5 車両運用 (1,727 km, +33 km)
  - 車両固定費 > 燃料費 なら 5 台で週 **¥95,050 削減**

### 見どころ
- 配送ルート問題での段階的 baseline の実例
- 車両固定費 vs 走行距離という古典的トレードオフの数値化
- multi-depot VRPTW を CP-SAT assignment で近似した実装

---

## 🏆 hospital_or_scheduling/ — 最難関サンプル

**病院手術室スケジューリング: 50 患者 × 6 OR × 5 日間、HC×22 + SC×8。**

このスキルパックで**最も複雑なサンプル**。外科医の専門性・麻酔科医・看護師・機材 (心肺装置/小児用)・ICU 床・緊急/待機患者が絡み合う実際の手術室割当問題。

### データ
- `data/operating_rooms.csv` — 6 OR (心肺装置/小児用/C-arm 等)
- `data/surgeons.csv` — 15 外科医 (心臓/一般/整形/小児/脳神経/血管)
- `data/anesthesiologists.csv` — 10 麻酔科医 (一部 小児対応可)
- `data/nurses.csv` — 20 OR 看護師 (scrub/circulator/小児対応)
- `data/patients.csv` — 50 患者 (手術・優先度・ICU 必要性・希望医師)
- `data/icu_beds.csv` — 日ごとの ICU 病床容量 (タイト)
- `data/constraints.csv` — **HC×22, SC×8**

### HC (22 個)
HC1-2: 患者訪問・OR 時間 / HC3-5: 外科医専門性・麻酔科医・看護師 / HC6-7: 看護師人数・長時間手術特例 / HC8-11: 心臓室・小児室・小児麻酔科医・小児看護師 / HC12-15: スタッフ時間上限 / HC16: 掃除時間 / HC17-19: 休暇 / HC20: ICU 床容量 / HC21: 緊急患者 48h 以内 / HC22: 希望医師

### 主要な発見
- **全 11 Phase で 50/50 患者スケジュール可能** (大規模複合問題でも feasible)
- **明確なトレードオフ**:
  - coverage 重視: 50/50 患者 / 外科医 spread 775 分
  - fairness 重視: 34/50 患者 / spread 175 分
  - **balanced が Pareto 最適**: 49/50 患者 / spread 375 分
- **HC22 (希望外科医) が最大のカバレッジ制約** — 緩和すれば 50/50 達成
- **ICU day-2 が最タイト日** (4 床 vs 4 ICU 症例) → 他の日に分散で解決
- **小児麻酔科医プール 4 名が脆弱** — クロストレーニング提案の材料

### 見どころ
- **全例の中で HC 数最多 (22)** → 段階的 baseline の真価を発揮
- **命に関わるストーリー** → 提案書が強力 (ICU 床不足のリスク明示等)
- **真の多層最適化**: 患者 × OR × 日 × 外科医 × 麻酔科医 × 看護師 × 機材 が全部同時に絡む
- 現実の大学病院で使えるレベルの定式化

---

## 🏆 flexible_job_shop/ — 最大規模サンプル (製造業 FJSP)

**柔軟ジョブショップスケジューリング: 40 ジョブ × 15 機械 × 12 オペレーター、変数 9,283 個。**

日本製鉄の出鋼スケジューリング事例 (工数 70% 削減) で知られる製造業の古典問題。
CP-SAT の `NewIntervalVar` + `AddNoOverlap` パターンを活用した本格的なスケジューラ実装。

### データ
- `data/machines.csv` — 15 機械 (lathe 5, milling 4, drilling 3, grinding 2, cnc 1)
- `data/operators.csv` — 12 オペレーター (機械種別スキル、勤務時間)
- `data/jobs.csv` — 40 ジョブ (優先度: urgent/high/normal/low、納期、開始可能日)
- `data/operations.csv` — 227 操作 (ジョブ内シーケンス、所要時間、適格機械、段取り時間)
- `data/tools.csv` — 5 種類の工具 (数量制限あり: T03×1, T05×1 などタイト)
- `data/constraints.csv` — **HC×20, SC×6**

### HC (20 個)
機械割当・NoOverlap・ジョブ内順序・日次営業時間・保守窓・段取り時間・オペレーター割当・スキルマッチ・工具数量・納期・最早開始・緊急ジョブ期限・機械互換性・段取り切替上限 等

### 主要な発見
- **全 11 Phase feasible** — 20 HCs すべて段階的に追加可能
- **4 シナリオすべてで 20/20 HC 充足** (独立検証器で確認)
- **Pareto トレードオフが明確**:
  - `throughput` 重視: makespan 1740 分 (23%短縮) だが機械負荷 spread 2400 分 → 現場拒否レベル
  - `smooth`: makespan のわずか 8% 損失で operator spread 164 分 (最良) → 実務で採用しやすい
  - `balanced`: 非劣解の中間点 → 提案書で推奨
- **発見されたデータ不整合**: 緊急ジョブの納期 day=1 + 総所要時間 > 480 分で Phase 5 infeasible になった → 生成データを修正 (2 日枠 + 所要時間制限)

### 見どころ
- **本パック最大規模 (9,283 変数、21,721 制約)**
- **製造業ドメイン** → 既存の service sector サンプル (シフト・配送・医療) と差別化
- **CP-SAT の真価**: `NewOptionalIntervalVar` による「機械が複数候補の操作」をエレガントに表現
- **実際の段階的 baseline のバグ発見**: データ生成の甘さを Phase 5 で検出 → 実務でもよくあるパターンの教訓

### 参照
- OR-Tools チュートリアル: Flexible Job-Shop Scheduling
- 日本製鉄 圧延スケジューリング: 週次計画業務 70% 削減 (エデルマン賞 2022)

---

## 期待される結果

- 各プロジェクトの `v1/results/` フォルダに数値結果 (JSON) があります
- `v1/reports/` フォルダに assess/baseline/improve/proposal の全レポートがあります
- `v1/scripts/` に再実行可能な Python コードがあります

実行環境や OR-Tools のバージョンにより多少の差異が出る場合があります。
