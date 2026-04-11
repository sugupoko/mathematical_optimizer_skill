# Assess Report — worker_supervisor v1

**日付**: 2026-04-11
**対象データ**: `workspace/examples/worker_supervisor/data/`

---

## 1. 情報源 (Ref)

| Ref | ファイル | 行数 |
|---|---|---|
| R1 | workers.csv | 20 名 |
| R2 | supervisors.csv | 8 名 |
| R3 | shifts.csv | 42 シフト (2 週 × 7 日 × 3) |
| R4 | pair_constraints.csv | 9 件 (forbidden 2, mentorship 4, preferred 3) |
| R5 | constraints.csv | HC1-12, SC1-8 |
| R6 | アナリスト仮定 | A1-A10 (spec.md 参照) |

## 2. 問題分類

**拡張型 Nurse Scheduling Problem (NSP)** + **二者割当 (worker × supervisor) ペア制約**

- 単純な NSP と異なり、作業者と監督者の **2 リソース** を同時にスケジュールし、両者の組み合わせ自体に制約 (HC11 禁止 / HC12 メンタル) がかかる。
- このため、worker と supervisor を独立に解いて後で結合することは不可能。
- 目的関数は v1 では feasibility 確認に集中、改善フェーズで多目的化。

## 3. データ統計

| 項目 | 値 | Ref |
|---|---|---|
| 作業者総数 | 20 (senior 8 / mid 8 / junior 4) | R1 |
| 英語可作業者 | 8 (W002, W004, W008, W010, W013, W017, W018?) | R1 |
| 監督者総数 | 8 (general 3 / technical 2 / bilingual 3) | R2 |
| 英語可監督者 | 5 (S001, S003, S005, S008 + 多言語 S008) | R2 |
| 全シフト数 | 42 | R3 |
| 必要作業者総数 (Σ) | 約 168 人シフト | R3 |
| 必要監督者総数 (Σ) | 約 48 人シフト | R3 |
| 英語必須シフト | 6 | R3 |
| 禁止ペア | 2 | R4 |
| メンタルペア | 4 | R4 |

### 供給能力チェック (粗い概算, 仮定 8h/シフト)
- 作業者総供給上限: ≒ Σ max_hours × 2週 / 8h = (20 × 約 38h × 2) / 8 ≒ 190 人シフト
- 作業者総需要: 168 人シフト → **余裕 約 13%** (タイト)
- 監督者総供給上限: ≒ (8 × 約 38h × 2) / 8 ≒ 76 人シフト
- 監督者総需要: 48 人シフト → 余裕 58%

→ **作業者側の容量がボトルネックになりやすい**。HC5 (unavailable_days) や HC7 (skill) でさらに減ると HC1 が破綻する可能性あり。

## 4. 仮説 (実行前の予測)

| ID | 仮説 | 検証フェーズ |
|---|---|---|
| H1 | フェーズ 0-2 (需要のみ) は feasible | Phase 0-2 |
| H2 | フェーズ 3 (max_hours) で作業者がタイトになり、SC2 (公平性) が課題化 | Phase 3 |
| H3 | フェーズ 4 (unavailable) で特定日 (Sat/Sun) が薄くなる | Phase 4 |
| H4 | フェーズ 5 (skill, bilingual) で 6 つの bilingual シフトが課題に | Phase 5 |
| H5 | フェーズ 6 (rest) で night → 翌日制約により night 担当者が固定化 | Phase 6 |
| H6 | フェーズ 7 (pair) でメンタルペア HC12 が実現可能か微妙 (W016 は Fri/Sat 不可で機会少) | Phase 7 |

## 5. 複雑度評価 (5 軸)

| 軸 | レベル | 根拠 |
|---|---|---|
| 変数規模 | complex | 1,176 binary + pair 補助変数 |
| HC 数 | complex | 12 個 |
| 問題タイプ | complex | composite (scheduling + matching + multi-resource) |
| 制約相互作用 | strong | HC11/HC12 が worker と supervisor を結合 |
| ドメイン既知度 | medium | NSP 拡張、文献あり |

### **総合: COMPLEX**

## 6. 推奨戦略: 段階的ベースライン

12 個の HC を 7 フェーズに分割して逐次追加:

| Phase | 追加 HC | 狙い |
|---|---|---|
| 0 | (なし) | 変数のみ、構造確認 |
| 1 | HC1 | worker 需要 |
| 2 | HC2 | supervisor 需要 |
| 3 | HC3, HC4 | max hours (供給上限) |
| 4 | HC5, HC6 | unavailable days |
| 5 | HC7, HC8 | skill, bilingual |
| 6 | HC9, HC10 | rest |
| 7 | HC11, HC12 | pair |

各フェーズで feasible / objective / time を記録し、infeasible 発生フェーズで原因を切り分ける。

## 7. 不足情報

確認事項 Q1-Q6 (spec.md 参照) を `/opt-request` で発行することを推奨。
ただし v1 ベースラインはデフォルト解釈 (A1-A10) で進める。

## 8. 次ステップ

1. `/opt-baseline` (staged モード) を実行
2. infeasible 発生フェーズがあれば `/opt-improve` で緩和 or `/opt-request` で追加情報依頼
3. 全フェーズ feasible なら SC を加えた多目的最適化へ
