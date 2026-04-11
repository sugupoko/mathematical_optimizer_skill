# Baseline Report — clinic_nurse v1

**日付**: 2026-04-11
**戦略**: 段階的解法（complexity=complex のため）
**ソルバー**: OR-Tools CP-SAT, time_limit=60s, num_workers=4

## 概要

18 看護師 × 72 シフト = **1,296 バイナリ変数** の複合スケジューリング問題。
assess の complexity 判定に従い、HC1 から HC8 まで1つずつ追加する段階的解法を実行。

## Phase 別結果

各 Phase でソルバーが解を返した後、**独立 HC 検証器**で全 8 個の HC を再チェック。
「Active」欄はその Phase でモデルに入れた制約、「違反内訳」は independent verifier が全 HC に対して検出した違反数。

| Phase | Active | 状態 | 割当数 | 独立検証の違反 | 時間 |
|-------|--------|:---:|------:|---|------:|
| 0. 制約なし | - | OPTIMAL | 0 | HC1:72, HC7:36 (計 108) | 0.04s |
| 1. +HC1 | HC1 | OPTIMAL | 144 | HC2:4, HC3:4, HC4:12, HC5:126, HC6:28, HC8:24 (計 198) | 0.01s |
| 2. +HC2 | HC1,HC2 | OPTIMAL | 144 | HC3:5, HC4:14, HC5:13, HC6:29, HC7:17, HC8:22 (計 100) | 0.06s |
| 3. +HC3 | HC1-3 | OPTIMAL | 144 | HC4:12, HC5:11, HC6:28, HC7:16, HC8:20 (計 87) | 0.04s |
| 4. +HC4 | HC1-4 | OPTIMAL | 144 | HC5:13, HC6:25, HC7:12, HC8:19 (計 69) | 0.03s |
| 5. +HC5 | HC1-5 | OPTIMAL | 144 | HC6:26, HC7:11, HC8:22 (計 59) | 0.04s |
| 6. +HC6 | HC1-6 | OPTIMAL | 144 | HC7:11 (計 11) | 0.04s |
| **7. +HC7** | HC1-7 | **OPTIMAL** | 144 | **0 ✅** | **0.04s** |
| 8. +HC8 | HC1-8 | OPTIMAL | 144 | 0 ✅ | 0.04s |

## 診断

### ✅ 全 Phase で feasible を達成

**Phase 7 で全 HC を満たす解に到達**。Phase 8 (HC8) は HC6 (1 shift/day) と論理的に等価なので実質的に Phase 7 が最終 Phase。

### Phase 別の解釈

- **Phase 0**: 割当ゼロ。HC1 未充足 (72件) と HC7 未充足 (36件) が初期状態
- **Phase 1 (+HC1)**: 需要 144 を割当するが、他の制約を考慮しないため副次的違反 198 件発生
- **Phase 2-5**: 制約を追加するたびに違反数が段階的に減少（198→100→87→69→59）
- **Phase 6 (+HC6)**: 1日1シフト制約を追加すると違反が一気に 11 件まで減少
- **Phase 7 (+HC7)**: senior 配置制約を追加して **全 HC 充足達成**
- **Phase 8 (+HC8)**: HC6 と重複しているため追加効果なし

### ボトルネック分析

この問題には**ボトルネック制約なし**。段階的に制約を追加していっても、どの Phase でも infeasible にならずに全 HC を満たす解に到達できる。

対照的な worker_supervisor 問題では Phase 5 (HC7+HC8) で infeasible となり、
HC1 ∩ HC7 ∩ HC8 の鳩の巣原理による構造的不可能性を検出していた。
今回は設計通り、需給バランス（144/172=83.7%）+ 資格分布 + senior 配分がすべて十分な余裕を持っている。

### 計算時間

全 Phase 合わせて 0.3 秒未満。OR-Tools CP-SAT は 1,296 変数の問題を瞬時に解ける規模。

## ソフト制約は未評価

Phase 8 で feasibility が確立されたが、ソフト制約 (SC1-SC6) はまだ最適化されていない。
以下は参考値として Phase 8 の解における看護師別の割当状況:

（詳細は `results/staged_baseline_results.json` 参照）

## 次のステップ

→ `/opt-improve` で以下を実行:
1. SC の重み配分を調整した複数シナリオで再最適化
2. SC1-SC6 の各スコアを 0-100 で算出
3. SC 重みバリエーション 5 種類の比較
4. 独立 HC 検証器で全シナリオの HC 充足を再確認
5. QA チェックリスト
