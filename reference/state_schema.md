# スキル間状態管理 — .opt_state.yaml

## 目的

各スキル（/opt-assess → /opt-baseline → /opt-improve → /opt-report）の出力を構造化し、次のスキルが自動的に前の結果を参照できるようにする。

## 使い方

各スキルは実行時に `workspace/<project>/.opt_state.yaml` を読み書きする。

```
/opt-assess  → .opt_state.yaml の assess セクションを書く
/opt-baseline → assess セクションを読み、baseline セクションを書く
/opt-improve → baseline セクションを読み、improve セクションを書く
/opt-report  → 全セクションを読み、レポートを生成
```

## スキーマ定義

```yaml
# workspace/<project>/.opt_state.yaml
version: 1
project_name: "プロジェクト名"
created_at: "2026-03-30T10:00:00"
updated_at: "2026-03-30T15:30:00"

# --- /opt-assess の出力 ---
assess:
  status: "completed"  # pending | in_progress | completed
  completed_at: "2026-03-30T10:30:00"
  problem_type: "scheduling"  # scheduling | vrp | packing | assignment | composite
  problem_subtype: "shift_scheduling"  # 具体的な問題の種類
  scale:
    variables: 500
    constraints: 120
    size_class: "medium"  # small | medium | large | huge
  entities:  # データに含まれる主要エンティティ
    - name: "employees"
      count: 30
      source_file: "employees.csv"
    - name: "shifts"
      count: 21
      source_file: "shifts.csv"
  objectives:
    primary: "スキルスコアの最大化"
    secondary: "公平性（バラつき最小化）"
  hard_constraints:
    - id: "HC1"
      description: "1日1シフトまで"
      source: "法律"
    - id: "HC2"
      description: "週40時間以内"
      source: "就業規則"
  soft_constraints:
    - id: "SC1"
      description: "希望シフトの尊重"
      weight: 5
  hypotheses:
    - "ボトルネックは夜勤の人員確保"
    - "スキル制約が割当の自由度を大幅に下げている"
  assumptions:
    - key: "service_time"
      value: 10
      unit: "minutes"
      confidence: "low"
      note: "実績データなし、仮の値"
    - key: "travel_speed"
      value: 30
      unit: "km/h"
      confidence: "medium"
      note: "市街地の平均"
  missing_data:
    - "従業員の希望シフト"
    - "過去3ヶ月の実績データ"
  data_quality:
    overall: "要クリーニング"  # 良好 | 要クリーニング | 要確認事項あり
    issues:
      - "日付列のフォーマットが不統一"
      - "スキル欄に表記ゆれあり"

# --- /opt-baseline の出力 ---
baseline:
  status: "completed"
  completed_at: "2026-03-30T12:00:00"
  results:
    random:
      feasible: false
      violations: 45
      violation_breakdown:
        HC1: 12
        HC2: 18
        HC3: 15
      score: 120
    greedy:
      feasible: false
      violations: 3
      violation_breakdown:
        HC3: 3
      score: 380
      method: "skill-first assignment"
    solver:
      feasible: true
      violations: 0
      score: 520
      solve_time_sec: 28.5
      method: "CP-SAT (time_limit=30s)"
  bottleneck:
    constraint_id: "HC3"
    description: "夜勤の最低人員制約"
    evidence: "違反の80%がHC3に集中"
    slack_ratio: 0.85  # 供給/需要の比率（1.0未満 = ボトルネック）
  improvement_potential:
    greedy_vs_solver_gap_pct: 36.8
    assessment: "large"  # small(<20%) | medium(20-50%) | large(>50%)
  scripts:
    - path: "scripts/baseline_random.py"
    - path: "scripts/baseline_greedy.py"
    - path: "scripts/baseline_solver.py"
    - path: "scripts/evaluator.py"

# --- /opt-improve の出力（繰り返し可能） ---
improve:
  status: "completed"
  iterations:
    - iteration: 1
      completed_at: "2026-03-30T14:00:00"
      strategy: "目的関数の精密一致"
      pattern_ref: "improvement_patterns.md#パターン1"
      result:
        feasible: true
        violations: 0
        score: 650
        vs_baseline_pct: "+25.0%"
      what_worked: "評価関数のSC1重みをソルバー目的関数に反映"
      remaining_issues: "公平性スコアが低い"
    - iteration: 2
      completed_at: "2026-03-30T15:00:00"
      strategy: "公平性制約の追加"
      pattern_ref: "multiobjective_guide.md#ε-制約法"
      result:
        feasible: true
        violations: 0
        score: 630
        vs_baseline_pct: "+21.2%"
        fairness_score: 0.92
      what_worked: "min-max制約で最悪ケースを改善"
      remaining_issues: null
  best:
    iteration: 2
    method: "CP-SAT + 目的関数精密一致 + 公平性制約"
    feasible: true
    score: 630
    vs_baseline_pct: "+21.2%"
  additional_data_needed: []

# --- /opt-report の出力 ---
report:
  status: "completed"
  completed_at: "2026-03-30T16:00:00"
  output_file: "reports/v1_proposal.md"
  proposals:
    - name: "運用変更（コストゼロ）"
      cost: 0
      effect: "+21.2%"
      difficulty: "すぐできる"
      recommended: true
    - name: "システム導入"
      cost: "300万円"
      effect: "+35%（推定）"
      difficulty: "中期（3ヶ月）"
      recommended: false
  impossibility_findings: []

# --- /opt-deploy の出力 ---
deploy:
  status: "pending"
  execution_frequency: null
  pipeline_steps: []
  monitoring_metrics: []
  fallback_plan: null
```

## ルール

### 読み書きのルール
1. 各スキルは自分のセクション**のみ**を書き込む
2. 前のスキルのセクションは**読み取り専用**
3. `.opt_state.yaml` がなければ新規作成（/opt-assess が最初に作る）
4. 既存のセクションがあれば上書き（同じスキルを再実行した場合）

### status の遷移
```
pending → in_progress → completed
                      → blocked（追加データ待ち）
```

### バージョン管理との連携
```
追加データや制約変更が来た場合:
  1. 新しいバージョンフォルダ（`v2/`）を作成
  2. 前バージョンの `spec.md` を複製して更新
  3. 新しい `.opt_state.yaml` で `/opt-assess` から開始
  → `v1/.opt_state.yaml` と `v2/.opt_state.yaml` で Before/After の比較が可能
```

## スキルでの参照方法

各スキルの SKILL.md に以下の指示を含める:

```
## 状態の読み込み
実行開始時に workspace/<project>/.opt_state.yaml を読み込む。
前のスキルの出力（assess, baseline 等）を参照して、コンテキストを引き継ぐ。

## 状態の書き込み
実行完了時に自分のセクションを .opt_state.yaml に書き込む。
```
