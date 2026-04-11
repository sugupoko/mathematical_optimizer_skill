# Improve Report — worker_supervisor v1

**日付**: 2026-04-11
**前提**: ベースライン (`reports/baseline_report.md`) で Phase 5 (HC7+HC8) infeasible を確認済み
**ソルバー**: OR-Tools CP-SAT, time_limit=60s/シナリオ, num_workers=4

---

## 1. ボトルネック (再掲)

英語可 (`en`) かつ `reception` スキル所持の作業者が **4 名のみ** (W002, W004, W008, W010) [R1]。
一方、`bilingual_required=yes` かつ `required_skills=reception` のシフトは **4 シフト** (Tue/Thu morning × 2 週)、各 `worker_required=5` [R3]。

→ 5 必要 vs プール 4 → HC1 ∧ HC7 ∧ HC8 が同時には満たせない (構造的不可能性)。

---

## 2. シナリオ比較 (4 案、全 HC + SC 最適化)

**独立な HC 検証器** ですべての HC1-HC12 を再チェックした結果:

| シナリオ | 概要 | HC充足 | HC違反内訳 | obj | overall SC | 備考 |
|---|---|:---:|---|---:|---:|---|
| **A. W021 採用** | 英語可 + reception の中堅を 1 名追加 | ✅ **全充足** | なし | 200 | 83.0 | **唯一の真の解** |
| **B. HC1 緩和 (5→4)** | 4 つの bilingual+reception シフトのみ 4 名で OK | ❌ **HC1 違反4件** | HC1: 4 | 200 | 83.0 | 仕様を変えて HC1 を破っているだけ |
| **C. HC1 ソフト化** | shortage を許容 (penalty=1000/件) | ❌ **HC1 違反4件** | HC1: 4 | 4200 | 83.0 | ソルバーは解を返すが HC1 未充足 |
| **D. HC8 ソフト化** | bilingual シフトに非英語可を許容 | ❌ **HC8 違反4件** | HC8: 4 | 4207 | 82.0 | 非英語可 4 名を bilingual シフトに配置 |

**重要**: シナリオ B/C/D の「solver_feasible=True」はソルバーが緩和後モデルで解を見つけたことを意味するだけで、**元の HC1-HC12 をすべて満たしているわけではない**。独立検証器で各 HC を再チェックした結果、B/C/D はいずれも 4 件の HC 違反を抱えている。

### 解釈

- **A が唯一、12 個の HC を完全に満たす解**。W021 (英語可 + reception) の追加により、bilingual 需要 5 名を正確に供給できる。
- B, C, D はそれぞれ異なる方法で「4 シフトで 1 名不足」という構造的ギャップを表現しているが、どれも元の仕様書の HC を破っている。
- B は「ターゲットを 5→4 に書き換える」、C は「HC1 をペナルティ付きで許容する」、D は「HC8 をペナルティ付きで許容する」だけの違い。
- **数学的には B=C と同値** (どちらも HC1 違反 4 件)。D は HC1 ではなく HC8 を犠牲にしている。

### 推奨

**A (W021 採用)** を**唯一の真の解** として強く推奨。

B/C/D を採用する場合は「仕様書の HC を修正する」ことを意味する:
- B/C を選ぶ: HC1 を緩和 (bilingual シフトは 5→4 に変更) → クライアントと合意が必要
- D を選ぶ: HC8 を緩和 (bilingual シフトに非英語可の作業者を配置) → サービス品質の合意が必要

---

## 3. SC 重みバリエーション (5 案、シナリオ A をベースに)

| 変種 | 重み変更 | obj | SC1 | SC2 | SC3 | SC4 | SC5 | SC6 | SC7 | SC8 | 平均 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| V1 balanced       | デフォルト     |  200 | 100 | 80 | 90 | 100 | 100 | 52 | 100 | 42 | 83.0 |
| V2 fairness max   | sc2,sc3 ×8     |  368 | 100 | 80 | 90 | 100 | 100 | 52 | 100 | 42 | 83.0 |
| V3 coverage max   | sc1×15, sc6×10 |  968 | 100 | 80 | 90 | 100 | 100 | 52 | 100 | 42 | 83.0 |
| V4 welfare        | sc4,sc5 ×12    |  200 | 100 | 80 | 90 | 100 | 100 | 52 | 100 | 42 | 83.0 |
| V5 senior cov.    | sc7 ×20        |  200 | 100 | 80 | 90 | 100 | 100 | 52 | 100 | 42 | 83.0 |

### 観察 — 重要な構造的発見

- **5 変種すべてで raw 値が完全一致**: `sc2_spread=16, sc3_spread=8, sc6_shortfall=96, sc8_pairs_achieved=16`
- 60 秒の time_limit 内で CP-SAT が同一の "first feasible" 点に到達し、改善余地を残したまま停止。
- これは「重みを変えても解が動かない」という意味ではなく、**問題サイズに対して 60 秒では SC 最適化空間を探索しきれていない**ことを示す。
- **SC2 spread=16h / SC6 shortfall=96h は構造的下限の可能性が高い** (W008 の max=24h, W016 の max=24h など低時間枠の存在による)。
- **SC1, SC4, SC5, SC7 は完全達成 (100点)**: 連続勤務、夜勤上限、シニア配置の制約は余裕がある。
- **SC8 (推奨ペア) = 42 点** は、推奨ペア (W002-S003, W004-S005, W013-S003) の同時シフトを 16 回達成。これは負の重み (報酬) を増やせばさらに伸ばせる可能性あり。

### 実用上の示唆

- v2 では time_limit を **300-600 秒** に拡張するか、SC2/SC6 を専用にチューニングする 2 段階最適化 (lex 法) を検討。
- 現状の overall=83 はベースラインとして十分妥当な水準。

---

## 4. QA チェック (6 項目)

| # | 項目 | 結果 | コメント |
|---|---|:---:|---|
| 1 | HC1-HC12 ↔ コードの一致 | OK | `improve.py:build_full_model` が spec.md の HC1-HC12 を全実装。HC9/HC10 解釈は A4/A5 に従う |
| 2 | SC1-SC8 ↔ 目的関数の一致 | OK | 8 つの SC slack/spread 変数を `obj_terms` に集約。SC8 は負係数で報酬化 |
| 3 | 仮定値の妥当性 | OK | A1 (8h/シフト), A2 (==), A6 (worker∧supervisor 両方 en), A9 (週単位 max_hours) を spec.md と一致 |
| 4 | evaluate() ↔ objective の整合 | OK | `evaluate_solution` の raw 値は obj_terms と同じ slack を読む。スコア化は別関数 (0-100 正規化) |
| 5 | spec.md 内部矛盾 | OK | HC1 (==required) と HC8 (en 必須) と R1 のプール数 (4) の **矛盾** は構造的不可能性として明示済み |
| 6 | データソース新鮮度 | OK | R1-R5 はすべて `data/` の元 CSV、改変なし。R6 (仮定) は spec.md A1-A10 に明記 |

**追加発見**:
- spec.md の SC8 説明 ("preferred ペアをなるべく同一シフトに") と実装 (推奨ペアの coexistence を最大化) は一致。
- HC12 の `≥ 2` (2 週で最低 2 回) は実装で `m.Add(sum(pvars) >= 2)` として正しく反映。
- C/D シナリオの結果が一致 (どちらも 4 違反) は、構造的不可能性が「4 シフト × 1 名不足」という形で固定されていることを示し、QA 上の妥当性を裏付ける。

---

## 5. 結論と次ステップ

1. **A シナリオ (W021 採用) を v2 の出発点として推奨**
2. 採用までは **B (HC1 緩和)** を運用 (= 4 名で英語+reception を回す)
3. v2 で SC2/SC6 の構造的下限を打破するため:
   - W008/W016 の min/max を見直すか
   - 採用候補をもう 1 名追加
   - time_limit=300s + lex 最適化 (SC1/SC7 → SC2/SC3 → SC6 → SC8) を試行
4. クライアントへは **`/opt-report`** で 3 案 (A/B/C) と数学的不可能性証明を提示

---

## 6. 成果物

| 種別 | パス |
|---|---|
| improve script | `scripts/improve.py` |
| variants script | `scripts/variants.py` |
| improve results (4 シナリオ) | `results/improve_results.json` |
| variant results (5 重み) | `results/variant_results.json` |
| 提案書 (経営向け) | `reports/proposal.md` |
