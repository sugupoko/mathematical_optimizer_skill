# reference/ — 実装パターン集・ヒアリングガイド

スキルの中で「次にどうするか」が必要な時に参照する。
思考法（OPTIMIZATION_MINDSET.md）と手順（skills/）の間を埋める「引き出し」。

## ファイル一覧

### コード・実装系
| ファイル | 内容 | いつ参照するか |
|---------|------|-------------|
| `ortools_guide.md` | OR-Toolsの使い分けとコード雛形 | /opt-baseline でソルバーを選ぶ時 |
| `scheduling_template.py` | シフト/スケジューリングのCP-SAT定式化 | スケジューリング問題に着手する時 |
| `vrp_template.py` | 配送ルートのRouting Library定式化 | VRP/TSP問題に着手する時 |
| `evaluator_template.py` | 制約チェッカーと評価関数の雛形 | 評価器を作る時 |
| `data_preprocessing.md` | データ前処理の定石（住所→座標、距離マトリクス等） | /opt-assess でデータを整形する時 |
| `improvement_patterns.md` | 改善の定石パターン（AM/PM分割、Cluster+ソルバー等） | /opt-improve で対策を選ぶ時 |

### ヒアリング・コミュニケーション系
| ファイル | 内容 | いつ参照するか |
|---------|------|-------------|
| `hearing_templates.md` | ヒアリングガイド（質問の意図・暗黙知の引き出し方） | 質問の仕方を確認する時 |
| `hearing_sheet_shift.md` | **記入用** シフト調整業務ヒアリングシート | 現場でシフト担当者に聞く時 |
| `hearing_sheet_routing.md` | **記入用** 配送ルート業務ヒアリングシート | 現場でルート担当者/ドライバーに聞く時 |
