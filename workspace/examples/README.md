# サンプルデータ

このフォルダには2つのサンプルプロジェクトが含まれています。
30分以内に一連のワークフローを体験できます。

## シフトスケジューリング（shift_scheduling/）

10人の従業員 × 7日間の小規模シフト最適化問題。
- 従業員マスタ（スキル、勤務時間上限）
- シフト定義（朝・昼・夜の3交代）
- 制約条件（連勤制限、休息時間、公平性）

### 実行手順
```
/opt-assess workspace/examples/shift_scheduling/data/
/opt-baseline workspace/examples/shift_scheduling/data/
/opt-improve workspace/examples/shift_scheduling/data/
/opt-report workspace/examples/shift_scheduling/results/
```

## 配送ルート最適化（delivery_routing/）

東京都内20地点 × 3台の配送ルート最適化問題。
- デポ（品川）
- 顧客20件（渋谷、新宿、池袋、上野、浅草など）
- 車両3台（容量・稼働時間制限あり）

### 実行手順
```
/opt-assess workspace/examples/delivery_routing/data/
/opt-baseline workspace/examples/delivery_routing/data/
/opt-improve workspace/examples/delivery_routing/data/
/opt-report workspace/examples/delivery_routing/results/
```

## 期待される結果

各プロジェクトの `expected/` フォルダに、ベースライン結果のサンプルがあります。
実際の出力は実行環境やソルバーのバージョンにより多少異なります。
