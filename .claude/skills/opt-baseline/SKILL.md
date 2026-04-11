---
name: opt-baseline
description: 実行可能性（feasibility）を確認する。問題の複雑度に応じて一発解きor段階的解法を選ぶ
user_invocable: true
---

# Skill: opt-baseline（ベースライン構築+ボトルネック分析）

`/opt-baseline [data_path]` で実行。
**役割: この問題が解けるか？どこが壁か？を特定する。**
品質の最適化は opt-improve に任せる。baseline は feasibility に集中する。

## いつ使うか
- /opt-assess で問題の分類と複雑度判定が済んだ後
- 「この制約で本当に解けるのか？」を知りたい時

---

## 解法戦略の選択（assess の complexity を参照）

assess で判定された complexity に応じて戦略を切り替える:

```
complexity: simple
  → 一発解き（random + greedy + solver の3手法）
  → shift_scheduling のような小規模問題

complexity: medium
  → まず一発解き
  → infeasible なら段階的解法にフォールバック

complexity: complex
  → 段階的解法（必須）
  → 制約を1つずつ追加して、どこで壁にぶつかるか特定
```

---

## 戦略A: 一発解き（simple / medium）

### 1. データ読込みと前処理
- assessで特定したデータ形式に合わせてパース
- 欠損値の処理

### 2. 3つのベースラインを作る

**ランダム**: 下限の確認（「何もしないとこれだけ悪い」）
**貪欲法**: 常識的な解（最近傍法、優先順位ソート等）
**ソルバー**: 性能の上限（CP-SAT、time_limit=30秒）

### 3. エラー分析と比較

```
              ランダム    貪欲法    ソルバー
feasible?     x(50違反)   x(5違反)  o(0違反)
違反内訳      HC1:30 ...  HC3:5    -
```

→ ボトルネック制約を特定

---

## 戦略B: 段階的解法（complex、または medium で infeasible のとき）

**目的: 全HCを一度に満たそうとするのではなく、1つずつ追加して壁を特定する。**

### 手順

```
Phase 0: 変数定義のみ、制約なし
  → 必ず feasible。「上限値」の確認

Phase 1: HC1 追加
  → まだ feasible のはず（充足条件のみ）

Phase 2: +HC2
  → infeasible になったら → HC1+HC2 が両立不可

Phase 3: +HC3
  → ...

...

Phase N: 全HC
  → ここまで feasible なら成功
  → どこかで infeasible になったら、そこが壁
```

### 各Phaseで記録すること

- feasible / infeasible
- 目的関数値（feasible の場合）
- 解の統計（割当数、各エンティティの負荷等）
- どの制約が追加で効いたか
- 計算時間

### 段階化の順序

**重要: 制約を追加する順番は意図的に設計する。**

```
推奨順序:
  1. 需要充足系（HC1: 各シフトの必要人数）
     → まず「需要が満たせるか」を確認
  2. 供給上限系（HC2: 最大勤務時間、最大積載量）
     → 需要 vs 供給のギャップが見える
  3. 可用性系（HC3: 利用不可日、時間枠）
     → さらに供給が絞られる
  4. 適合性系（HC4: スキル、ライセンス）
     → どの組合せが許されるか
  5. 連鎖系（HC5: 休息時間、連続勤務）
     → 時間的制約
  6. 特殊系（ペア、優先、優先順位）
     → 最後に入れる

この順序だと「どのレイヤーで壁にぶつかったか」が明確になる:
  - Phase 2 で infeasible → 需給バランスの問題（人員不足）
  - Phase 3 で infeasible → 可用性の問題（不可日が多すぎる）
  - Phase 4 で infeasible → スキル分布の問題
  - Phase 5 で infeasible → 休息制約が厳しすぎる
  - Phase 6 で infeasible → ペア制約が矛盾
```

### 実装パターン

```python
def staged_baseline(data):
    phases = [
        ("phase0_no_constraints", []),
        ("phase1_hc1", ["HC1"]),
        ("phase2_add_hc2", ["HC1", "HC2"]),
        ("phase3_add_hc3", ["HC1", "HC2", "HC3"]),
        ("phase4_add_hc4", ["HC1", "HC2", "HC3", "HC4"]),
        ("phase5_add_hc5", ["HC1", "HC2", "HC3", "HC4", "HC5"]),
    ]
    results = []
    first_infeasible = None
    for name, constraints in phases:
        result = solve_with_constraints(data, constraints)
        results.append({
            "phase": name,
            "constraints": constraints,
            "feasible": result.feasible,
            "objective": result.obj,
            "stats": result.stats,
        })
        if not result.feasible and first_infeasible is None:
            first_infeasible = name
    return results, first_infeasible
```

---

## ボトルネック診断

### 一発解きの場合
- 違反が1種類に集中 → その制約がボトルネック
- 複数制約 → 制約緩和分析（1つずつ外して効果を測定）

### 段階的解法の場合
- **最初に infeasible になった Phase が壁**
- その Phase で追加した制約と、それ以前の制約の組合せが矛盾している
- 診断例:
  - Phase 2 (+HC2) で infeasible → 需給構造の問題。人員追加か HC2 緩和が必要
  - Phase 4 (+HC4) で infeasible → スキル分布の問題。研修か採用が必要

### 根本原因分析（必須）

**infeasible を検出したら、「どの制約が組合せで壁を作っているか」を数値で特定すること。**
レポートに以下を必ず書く:

1. **データから該当リソースを数える** — 制約を満たす候補の数 vs 需要の数
   ```
   例: HC7 (skill) + HC8 (bilingual) の場合
   - en + reception の両方を持つ作業者 = 4 名 (データから計数)
   - bilingual_required + reception 指定のシフト = 4 シフト、各 5 名必要
   - → 5 必要 vs プール 4 → 鳩の巣原理による不可能性
   ```

2. **鳩の巣原理 or 需給ギャップの形で示す**
   ```
   必要人数 N > 候補プール P → 不可能
   または
   総需要 D h > 総供給 S h → 構造的不足 (D-S) h
   ```

3. **無実の制約を明示する** — 段階化で分かったこと
   ```
   Phase 5 で壁 → HC9-12 (休息・ペア) は無実（容疑から外す）
   ```

### 解決策の選択肢（必須）

**原因が分かったら、どうすれば解決できるかを複数案で提示すること。**
提案は opt-improve や opt-report で検証するので、ここでは候補リストを出す。

- **A. 入力を変える**（データ側の修正）
  - 人員/車両/リソースを追加する
  - 需要を削減する（シフト数・訪問先を減らす）
  - 既存リソースの能力を拡張する（研修でスキル追加）

- **B. 仕様を変える**（HC の緩和）
  - 特定の HC を soft 化（penalty 許容）
  - 特定のパラメータを緩和（5名 → 4名、8h → 10h 等）
  - HC を SC に格下げ（破ってもいいが重みで抑制）

- **C. 運用で回避**（プロセス変更）
  - シフト時間の再設計
  - 需要のピーク分散
  - 手動の例外処理で補う

各選択肢に:
- 追加コスト (円、人日、0円)
- 影響範囲
- 導入難易度
- この選択肢を採った場合の次ステップ

**重要**: 「解けません」で終わらない。必ず対案を複数出す。これが不可能性の証明を「価値ある提言」に変える。

---

## 出力

バージョンフォルダ内に以下を保存する:
- `reports/baseline_report.md`（ベースライン結果・ボトルネック分析・次のステップ）
- `scripts/baseline.py`（一発解きの場合）または `scripts/staged_baseline.py`（段階化の場合）
- `results/baseline_results.json`

### 出力テンプレート（一発解き）

```markdown
## ベースライン結果（一発解き）

| 手法 | Feasible | 違反数 | スコア |
|------|----------|--------|--------|
| ランダム | ... | ... | ... |
| 貪欲法 | ... | ... | ... |
| ソルバー | ... | ... | ... |

## ボトルネック分析
- 最もきつい制約: [XX]（違反の80%を占める）
- 改善余地: [大/中/小]

## 次のステップ
→ /opt-improve でボトルネックに対策
```

### 出力テンプレート（段階的解法）

```markdown
## ベースライン結果（段階的解法）

### Phase 別の実行結果

| Phase | 追加制約 | Feasible | 解の統計 | 時間 | 備考 |
|-------|---------|----------|---------|------|------|
| 0 | （制約なし） | ✓ | 全セル配置可 | 0.1s | |
| 1 | HC1 | ✓ | 48/48 | 0.2s | 需要は満たせる |
| 2 | +HC2 | ✗ | 46/48 (不足2) | 0.3s | **★供給上限で不足** |
| 3 | +HC3 | ✗ | 43/48 (不足5) | 0.3s | |
| 4 | +HC4 | ✗ | 43/48 | 0.4s | |
| 5 | +HC5 | ✗ | 42/48 | 0.5s | |

### 壁にぶつかった Phase: **Phase 2 (+HC2)**

### 根本原因分析

**なぜ infeasible なのか、数値で示す:**

- データから候補/需要を計数:
  - 総需要: 48 人・シフト × 8h = **384 時間/週**
  - 総供給上限（全員フル稼働）: 10人 × max_hours 合計 = **368 時間/週**
- ギャップ: 需要 384 > 供給 368 → **16時間（= 2シフト）不足**
- → **構造的な人手不足。アルゴリズム改善では解決不可能**

**無実の制約:**
- HC3 以降は未評価。HC2 の時点で壁に到達しているので、HC3-5 の影響は「あったとしても追加で悪化する方向」と言える

### 解決策の選択肢

| 案 | 内容 | コスト | 導入難易度 |
|---|---|---|---|
| A. 入力変更 | パート1名追加 (週24h以上) | 人件費 | 採用次第 |
| B. 仕様変更 | 夜勤必要人数を2→1に緩和 | 0円 | 要安全検討 |
| C. 運用変更 | 一部シフトを統合・削減 | 0円 | 要業務再設計 |

→ **推奨**: 案 A（恒久対策） + 採用まで案 B で暫定運用

### ボトルネック制約: HC2 + HC1 の組合せ

## 次のステップ
→ /opt-improve で以下を検討:
1. 何人追加すれば feasible になるか（不可能性の定量化）
2. HC2 を緩和した場合のスコア
3. 需要（HC1）を削減した場合のスコア
```

---

## 状態管理

### 読み込み
- バージョンフォルダ内の `.opt_state.yaml` の `assess` セクション
- `assess.complexity` を参照して戦略を決定

### 書き込み
- 実行完了時にバージョンフォルダ内の `.opt_state.yaml` の `baseline` セクション
- 戦略 (`strategy: single_shot | staged`)
- Phase 別結果（段階化の場合）
- ボトルネック制約・壁 Phase
- スキーマは `reference/state_schema.md` を参照

---

## トラブルシューティング

### Phase 0 で既に infeasible
```
症状: 制約なしで解こうとしているのに feasible にならない
原因と対策:
  ├── 変数定義にバグ（domain が不正、依存関係の欠落）
  ├── データの整合性（空の集合、参照先なし）
  └── ソルバーのバグ → モデルを print して確認
```

### 段階的解法で計算時間が長い
```
症状: 各 Phase が遅い
対策:
  ├── time_limit を Phase ごとに調整（Phase 1-2 は短く、最終 Phase は長く）
  ├── Phase N-1 の解を warm start として Phase N に渡す
  ├── infeasible 検知を早める（solver.parameters.enumerate_all_solutions = False）
  └── 並列実行: 全 Phase を独立に並列で走らせる（依存がないので可能）
```

### 段階化の順序がわからない
```
推奨: assess の hard_constraints の順序に従う
or 「需要→供給→可用性→適合→連鎖→特殊」の一般順序を使う
or 制約の種類を以下で判定:
  ├── 「各XXに必ずN個」→ 需要充足
  ├── 「XXの合計が上限以下」→ 供給上限
  ├── 「XXはこの日に使えない」→ 可用性
  ├── 「XXはこのスキルが必要」→ 適合性
  ├── 「XXの後にYYは禁止」→ 連鎖
  └── 「XXとYYは同時」→ ペア/特殊
```

### OR-Tools がインストールできない
```
対策:
  ├── 企業プロキシ → pip install --proxy http://proxy:port ortools
  ├── Python バージョン（3.8-3.12 対応）
  └── 代替: PuLP + HiGHS
```

### ソルバーが時間内に解を返さない
```
対策:
  ├── time_limit 延長（30s → 120s → 300s）
  ├── 問題分解（AM/PM分割、クラスタ分割）
  ├── 変数削減（明らかな割当を先に固定）
  └── num_workers を増やす
```
