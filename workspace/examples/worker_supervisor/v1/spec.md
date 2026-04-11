# spec.md — worker_supervisor v1

**バージョン**: v1 (初版 / 2026-04-11)
**問題タイプ**: 拡張シフトスケジューリング (Nurse Scheduling Problem の拡張) + ペア制約 (マッチング要素)
**期間**: 2 weeks × 7 days × 3 shifts = 42 シフト

---

## 情報源 (Ref)

| Ref | ソース | 内容 |
|-----|------|----|
| R1 | `data/workers.csv` | 作業者20名: skills, level, max/min hours, unavailable_days, languages |
| R2 | `data/supervisors.csv` | 監督者8名: role, max/min hours, unavailable_days, languages, specialties |
| R3 | `data/shifts.csv` | 42シフトの需要 (worker_required, supervisor_required, required_skills, bilingual_required) |
| R4 | `data/pair_constraints.csv` | 禁止/メンタル/推奨ペア (各3件) |
| R5 | `data/constraints.csv` | HC1-HC12, SC1-SC8 の定義 |
| R6 | アナリスト仮定 | データに直接記載のない解釈・前提 |

---

## エンティティ

| 種類 | 件数 | 備考 |
|---|---|---|
| 作業者 (W) | 20 | senior 8 / mid 8 / junior 4 [R1] |
| 監督者 (V) | 8 | general 3 / technical 2 / bilingual 3 [R2] |
| シフト (S) | 42 | 2週 × 7日 × 3 (morning/afternoon/night) [R3] |
| 英語必須シフト | 6 | bilingual_required=yes [R3] |
| 禁止ペア | 2 | W003-S002, W009-S006 [R4] |
| メンタルペア | 4 | W008-S001, W011-S004, W012-S007, W016-S001 [R4] |
| 推奨ペア | 3 | [R4] |

---

## 決定変数

- `worker_x[w, s] ∈ {0,1}`  作業者 w がシフト s に入る  → 20×42 = **840 変数**
- `supervisor_x[v, s] ∈ {0,1}` 監督者 v がシフト s に入る → 8×42 = **336 変数**
- `pair[w, v, s]` (HC11/HC12 のため必要な相互作用変数, sparse, 後述)

**合計バイナリ変数 ≒ 1,176** (+ pair 変数で実装上は数千)

---

## 目的関数 (v1)

ベースライン段階では **feasibility 確認のみ** → objective = 0 (または SC を後段で重み付け加算)
本番改善フェーズで以下を最小化:
- α·SC2 (作業者労働時間の標準偏差)
- β·SC3 (監督者労働時間の標準偏差)
- γ·(SC4/SC5 違反夜勤回数)
- δ·(SC6 最低時間未達分)
- −ε·(SC8 推奨ペア成立回数)

---

## 制約一覧 (Hard)

| ID | 内容 | Ref | 実装メモ |
|---|---|---|---|
| HC1 | 各シフト s で `Σ_w worker_x[w,s] == worker_required[s]` | R3,R5 | = 制約 (== にするか ≥ にするかは確認事項Q1) |
| HC2 | 各シフト s で `Σ_v supervisor_x[v,s] == supervisor_required[s]` | R3,R5 | 同上 |
| HC3 | 各週 wk, 各 w で `Σ_{s ∈ wk} hours(s)·worker_x[w,s] ≤ max_hours[w]` | R1,R5 | morning/afternoon=8h, night=8h と仮定 [R6] |
| HC4 | 各週 wk, 各 v で同様 ≤ max_hours[v] | R2,R5 | |
| HC5 | `worker_x[w,s] = 0` if day(s) ∈ unavailable_days[w] | R1,R5 | 変数固定で実装 |
| HC6 | `supervisor_x[v,s] = 0` if day(s) ∈ unavailable_days[v] | R2,R5 | |
| HC7 | required_skills[s] ⊆ skills[w] でなければ `worker_x[w,s] = 0` | R1,R3,R5 | 1スキルのみ要求 (reception or phone) [R3] |
| HC8 | bilingual_required=yes のシフトは `'en' ∈ languages` のみ可 | R1,R2,R3,R5 | 作業者と監督者の両方に適用 |
| HC9 | 作業者: night(s) → 翌日 morning(s+1) は不可 (11h休息) | R5,R6 | 連続日のみ対象 |
| HC10 | 監督者: night → 翌 morning も afternoon も不可 (12h休息) | R5,R6 | より厳しい解釈 [R6] |
| HC11 | 禁止ペア (w,v) は同一 s で両方=1 にならない: `worker_x[w,s] + supervisor_x[v,s] ≤ 1` | R4,R5 | 線形制約で十分 |
| HC12 | メンタルペア (w,v) は2週間で同一シフト ≥ 2 回: `Σ_s pair[w,v,s] ≥ 2` | R4,R5 | `pair = AddBoolAnd` で実装 |

## 制約一覧 (Soft) — v1 ベースラインでは未実装、改善フェーズで追加

| ID | 内容 | Ref |
|---|---|---|
| SC1 | 作業者の連続勤務 ≤ 5 日 | R5 |
| SC2 | 作業者労働時間の標準偏差最小化 | R5 |
| SC3 | 監督者労働時間の標準偏差最小化 | R5 |
| SC4 | 作業者夜勤 ≤ 4 回 / 2週 | R5 |
| SC5 | 監督者夜勤 ≤ 3 回 / 2週 | R5 |
| SC6 | 最低勤務時間 (min_hours) を確保 | R1,R2,R5 |
| SC7 | 各日 senior 作業者を ≥ 1 名 | R1,R5 |
| SC8 | 推奨ペアをなるべく同一シフトに | R4,R5 |

---

## 仮定 (R6)

| ID | 仮定 | 理由 | 確認要否 |
|---|---|---|---|
| A1 | 1 シフトの労働時間 = 8 時間 (morning/afternoon/night とも) | shifts.csv の時刻差から [R3] | 確認不要 |
| A2 | HC1/HC2 は厳密に等号 (== required) | 「必要人数」の自然な解釈 | Q1 |
| A3 | night は当日扱い (21:00-05:00 は開始日に紐付け) | スケジューリング慣例 | Q2 |
| A4 | HC9 の「翌日朝勤」= 翌カレンダー日の morning シフトのみ禁止 | 11h 休息で afternoon は OK | Q3 |
| A5 | HC10 の「12h休息」= 翌日 morning + afternoon も禁止 | 12h なので 13:00 開始も微妙 | Q4 |
| A6 | bilingual_required では 作業者・監督者の **両方** が en 必須 | "・" の自然解釈 | Q5 |
| A7 | HC7 required_skills は CSV では単一スキルのみ → 含むかどうかで判定 | [R3] 複数指定例なし | 確認不要 |
| A8 | HC12 メンタル「同一シフト」= 同じ (week,day,shift) の作業者と監督者の同時アサイン | 自然解釈 | 確認不要 |
| A9 | 評価期間 = 2週間。週単位の max_hours は週ごとに別々に課す | max_hours_per_week カラム名から | 確認不要 |
| A10 | preferred ペア (SC8) は v1 ベースラインでは未考慮 | ベースライン段階のため | 確認不要 |

---

## 複雑度評価 (5 軸)

| 軸 | 評価 | 根拠 |
|---|---|---|
| 1. 変数規模 | **complex** | バイナリ ≒ 1,176 (+ pair 補助変数) |
| 2. ハード制約数 | **complex** | HC 12 個 |
| 3. 問題タイプ | **complex** | composite: スケジューリング + マッチング (ペア制約) + 多リソース (W と V 同時) |
| 4. 制約相互作用 | **strong** | HC11/HC12 が worker と supervisor のスケジュールを結合し、別々に解けない |
| 5. ドメイン既知度 | **medium** | NSP (Nurse Scheduling) の拡張で文献あり、ただしペア制約は固有 |

### 総合: **COMPLEX**

→ 推奨戦略: **段階的ベースライン (staged baseline)**
理由:
- 一発解きで infeasible が出ると、HC1〜HC12 のどれが原因か切り分け不能
- ペア制約 (HC11/HC12) は供給制約と干渉しやすく、最後に追加して影響を観察したい
- 12 制約を 7 フェーズで段階追加 → infeasible 発生フェーズが特定できる

---

## 確認事項 (5 questions, A/B/C 形式)

**Q1. HC1/HC2 の必要人数は厳密一致 (==) ですか?**
- A) 厳密に == required (デフォルト, 過剰人員も不可)
- B) ≥ required (過剰人員は許容)
- C) [required, required+1] (1名までの余剰OK)

**Q2. 夜勤シフト (21:00-05:00) はどちらの日に紐付けますか?**
- A) 開始日 (21:00 の側) [デフォルト]
- B) 終了日 (05:00 の側)
- C) 両日にまたがるとして両日扱い

**Q3. HC9「夜勤翌日の朝勤禁止 (11h休息)」の解釈は?**
- A) 翌カレンダー日の morning のみ禁止 [デフォルト, afternoon=13:00 開始は OK]
- B) 翌日 morning + afternoon 両方禁止
- C) 24h 完全休息

**Q4. HC10「監督者 12h 休息」の解釈は?**
- A) 翌日 morning + afternoon 両方禁止 [デフォルト, より厳しい]
- B) 翌日 morning のみ禁止 (HC9 と同じ)
- C) 24h 完全休息

**Q5. bilingual_required シフトで en 必須なのは?**
- A) 作業者と監督者の **両方** [デフォルト]
- B) 監督者のみ (作業者は誰でもよい)
- C) 作業者のみ

**Q6. メンタルペア (HC12) の「2週間で2回」が達成不可能な場合、優先順位は?**
- A) HC12 を緩和してでも他の HC を優先 (HC12 を soft 化)
- B) HC12 厳守 (infeasible なら追加データを依頼)
- C) パラメータ (2回 → 1回) を緩めて再試行

---

## 推奨戦略

1. **段階的ベースライン** (`/opt-baseline`) でフェーズごとに HC を追加 → infeasible 切り分け
2. ボトルネック特定後、`/opt-improve` で SC を加えた最適化
3. 必要なら `/opt-request` で確認事項 Q1-Q6 を依頼
