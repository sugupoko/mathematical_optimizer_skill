# Baseline Report — worker_supervisor v1 (Staged)

**日付**: 2026-04-11
**戦略**: 段階的ベースライン (staged)
**ソルバー**: OR-Tools CP-SAT (time_limit=30s, num_workers=4)

---

## 1. 規模

| 項目 | 値 |
|---|---|
| 作業者 | 20 |
| 監督者 | 8 |
| シフト | 42 |
| バイナリ変数 (worker_x + supervisor_x) | **1,176** |
| 補助変数 (HC12 pair) | +33 (1ペアあたり42、4ペア中3が有効) |
| 最終フェーズの追加 hard 制約 | 1,040 |

## 2. フェーズ別結果

| Phase | 追加内容 | 累積制約 | 状態 | 時間 | objective |
|---|---|---:|:---:|---:|---|
| 0 | (なし) 変数のみ | 0 | OPTIMAL | 0.09s | — |
| 1 | +HC1 worker 需要 (==) | 42 | OPTIMAL | 0.01s | — |
| 2 | +HC2 supervisor 需要 (==) | 84 | OPTIMAL | 0.01s | — |
| 3 | +HC3,HC4 max_hours/週 | 140 | OPTIMAL | 0.05s | — |
| 4 | +HC5,HC6 unavailable_days | 242 | OPTIMAL | 0.03s | — |
| **5** | **+HC7,HC8 skills/bilingual** | **484** | **INFEASIBLE** | **0.00s** | **—** |
| 6 | +HC9,HC10 rest | 952 | INFEASIBLE | 0.01s | — |
| 7 | +HC11,HC12 pair | 1,040 | INFEASIBLE | 0.01s | — |

→ **Phase 5 で初めて infeasible**。Phase 6/7 はそれを引き継いだだけなので原因は HC7+HC8 にある。

## 3. ボトルネック診断

### ルートコーズ: 英語可 × reception スキル所持の作業者が構造的に不足

**事実 (R1, R3 から):**
- 英語 (`en`) を話せる作業者: **6 名** (W002, W004, W008, W010, W013, W017)
- うち `reception` スキルを持つ者: **4 名** (W002, W004, W008, W010)
- bilingual_required=yes かつ required_skills=reception のシフト: **4 シフト** (Tue/Thu morning × 2 週)
- 各シフトは worker_required = **5 名**

→ 5 名必要 vs 候補プール 4 名 → **HC1 (==5) を満たすことが不可能**

これは時間配分や休暇の問題ではなく、**プール自体が足りない構造的不可能性**。

### 補強事実
- bilingual + phone のシフト (Thu/Fri afternoon × 2 週 = 4 シフト, 各 5 名) は EN+phone 作業者 6 名で何とか回るが、reception 側の不足が先に効く
- bilingual シフト全体の総需要: 8 シフト × 5 = **40 worker-slot**
- 6 名 × 14 日 max ≒ 70 slot (理論上限) はあるが、reception 制約 + max_hours で実効プールはずっと少ない
- W008 は max_hours=24 (週) でかつ Wed unavailable → 寄与度低い

## 4. 仮説検証 (assess_report.md より)

| 仮説 | 結果 |
|---|---|
| H1 Phase 0-2 feasible | OK |
| H2 Phase 3 タイト化 | OK (feasible は維持) |
| H3 Phase 4 で薄くなる | OK |
| **H4 Phase 5 で bilingual が課題** | **的中** (infeasible) |
| H5 Phase 6 で night 固定化 | 未確認 (Phase 5 で停止) |
| H6 Phase 7 で HC12 微妙 | 未確認 |

## 5. 段階的ベースラインの価値

**もし一発解きなら:** Phase 7 まで全部入れて INFEASIBLE しか出ず、12 個の HC のどれが原因か分からない。HC11/HC12 (ペア) を疑って時間を浪費する可能性が高い。

**段階的にしたことで判明したこと:**
1. HC1-HC6 だけなら **完全に feasible** (基礎需要・供給・休暇は問題ない)
2. infeasible は **HC7 (skill) + HC8 (bilingual)** の組み合わせから発生
3. ペア制約 (HC11/HC12) や 休息制約 (HC9/HC10) は **無罪** (この時点ではまだ評価できないが、原因ではない)
4. 切り分け時間: 1 秒未満 × 8 フェーズ ≒ 0.2 秒で原因特定

## 6. 推奨アクション

### 短期 (緩和案 — `/opt-improve` で検証)
- **A) パラメータ Q1 を == から ≥ に変える**: 厳密一致 (==) を ≥ required に緩めても、プールは 4 名しかないので **解消しない**
- **B) HC1 を soft 化**: 「reception+bilingual シフトは 4 名でも可」と認める
- **C) HC7 緩和**: bilingual + reception シフトでは reception スキル要件を外す (phone のみで OK)

### 中期 (追加データ依頼 — `/opt-request`)
- D) 英語可 + reception の作業者を **最低 1 名追加採用** (推奨案)
- E) bilingual_required の運用見直し: 本当に「全員」英語必須か、それとも「最低 1 名」で十分か (確認事項 Q5 の派生)

### 推奨: D + B の組み合わせ
- 採用が間に合わない期間は B で運用、長期的には D で恒久対策

## 7. 次ステップ

1. `/opt-request` で client に Q5 (bilingual の本当の意味) と D (採用) を確認
2. `/opt-improve` で B/C の緩和シナリオを試行 → Phase 5 突破後に Phase 6/7 を評価
3. 全 HC が feasible になったら SC を加えた最適化へ
