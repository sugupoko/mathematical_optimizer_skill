# OR-Tools 使い分けガイド

## いつどちらを使うか

OR-Toolsには2つの主要なソルバーがある。問題の種類で使い分ける。

```
問題の種類は？
  ├── 割当/スケジューリング → CP-SAT
  │     「誰を・いつ・何に」を決める
  │     シフト表、時間割、タスク割当、ジョブショップ
  │
  ├── 巡回/配送ルート → Routing Library
  │     「どの順番で・どう回るか」を決める
  │     TSP、VRP、配送計画、巡回セールスマン
  │
  └── 両方混ざっている → 分解してそれぞれに
        「誰がどの車でどの順番で」
        → Step 1: CP-SATで「誰がどの車か」を決める
        → Step 2: Routing Libraryで「どの順番で回るか」を決める
```

## CP-SAT（制約プログラミング + SAT）

### 得意なこと
- 離散変数の割当問題（0/1変数、整数変数）
- 複雑な制約の組合せ（「AならばB」「全て異なる」等）
- 目的関数のカスタマイズが自由

### 基本構造
```python
from ortools.sat.python import cp_model

model = cp_model.CpModel()

# 1. 変数を作る
x = {}
for i in range(N):
    for j in range(M):
        x[i, j] = model.new_bool_var(f'x_{i}_{j}')

# 2. 制約を追加する
for i in range(N):
    model.add(sum(x[i, j] for j in range(M)) == 1)  # 各iは1つのjに割当

# 3. 目的関数を設定する
model.maximize(sum(score[i][j] * x[i, j] for i in range(N) for j in range(M)))

# 4. 解く
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 60
status = solver.solve(model)

# 5. 結果を取り出す
if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
    for i in range(N):
        for j in range(M):
            if solver.value(x[i, j]) == 1:
                print(f'{i} → {j}')
```

### 重要なTips
- `max_time_in_seconds`: 長くするほど良い解が見つかる。実務なら60-300秒
- `num_workers`: CPUコア数を指定して並列化
- 目的関数は**評価関数と完全一致させる**（これだけで+15-27%改善）
- `add_hint()`: 既知の良い解をヒントとして渡すと収束が速い

## Routing Library（配車/巡回）

### 得意なこと
- TSP、VRP、CVRP、VRPTW
- 距離/時間の最小化
- 容量・時間枠・最大距離の制約

### 基本構造
```python
from ortools.constraint_solver import routing_enums_pb2, pywrapcp

# 1. マネージャーを作る
manager = pywrapcp.RoutingIndexManager(
    num_locations,   # ノード数（デポ含む）
    num_vehicles,    # 車両数
    depot_index      # デポのインデックス（通常0）
)
routing = pywrapcp.RoutingModel(manager)

# 2. 距離コールバックを登録
def distance_callback(from_index, to_index):
    from_node = manager.IndexToNode(from_index)
    to_node = manager.IndexToNode(to_index)
    return distance_matrix[from_node][to_node]

transit_callback_index = routing.RegisterTransitCallback(distance_callback)
routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

# 3. 制約を追加（容量、時間枠等）
# 容量制約
def demand_callback(from_index):
    from_node = manager.IndexToNode(from_index)
    return demands[from_node]

demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
routing.AddDimensionWithVehicleCapacity(
    demand_callback_index,
    0,          # slack（余裕）
    capacities, # 各車両の容量
    True,       # 0から開始
    'Capacity'
)

# 4. 探索パラメータを設定
search_parameters = pywrapcp.DefaultRoutingSearchParameters()
search_parameters.first_solution_strategy = (
    routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
)
search_parameters.local_search_metaheuristic = (
    routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
)
search_parameters.time_limit.FromSeconds(120)

# 5. 解く
solution = routing.SolveWithParameters(search_parameters)

# 6. 結果を取り出す
if solution:
    for vehicle_id in range(num_vehicles):
        index = routing.Start(vehicle_id)
        route = []
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            route.append(node)
            index = solution.Value(routing.NextVar(index))
        route.append(manager.IndexToNode(index))  # depot
        print(f'Vehicle {vehicle_id}: {route}')
```

### 重要なTips
- `first_solution_strategy`: 初期解の作り方。`PARALLEL_CHEAPEST_INSERTION`が安定
- `local_search_metaheuristic`: `GUIDED_LOCAL_SEARCH`がデフォルト推奨
- `time_limit`: 長くするほど改善。120秒が実用的
- 時間枠制約は `AddDimension` + `CumulVar().SetRange()` で設定

## どちらを選ぶか迷った場合

```
CP-SATを使う:
  - 目的関数を自由にカスタマイズしたい
  - 「評価関数と精密一致」させたい（発見2の適用）
  - 制約が複雑で「AならばB」のような論理制約がある
  - 変数が離散（0/1、整数）

Routing Libraryを使う:
  - 距離/時間の最小化がメイン
  - 標準的なVRP（容量、時間枠、最大距離）
  - 早く動くものを作りたい（テンプレートが豊富）

両方使う:
  - CP-SATで割当を決める → Routing Libraryで巡回順序を決める
  - Routing Libraryで初期解 → CP-SATで制約修復
```
