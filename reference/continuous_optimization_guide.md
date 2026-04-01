# 連続最適化ガイド

構造設計・形状最適化・パラメータチューニング・トポロジー最適化など、
設計変数が連続値である最適化問題の考え方・手法選択・実装パターンをまとめたガイド。
`continuous_optimization_template.py` と合わせて使う。

---

## 離散最適化との違い

このスキルパックが主に扱うシフト・配送・マッチングは**離散（組合せ）最適化**だが、
現実の設計問題では**連続最適化**が必要になる場面も多い。

| 特徴 | 離散最適化 | 連続最適化 |
|------|----------|----------|
| 設計変数 | 整数・バイナリ（誰をどこに割り当てるか） | 実数（寸法・角度・密度） |
| 典型手法 | CP-SAT, MIP, ヒューリスティクス | SLSQP, L-BFGS-B, 遺伝的アルゴリズム |
| 勾配 | 使えない（離散） | 使える（連続なので微分可能） |
| 代表問題 | シフト、VRP、マッチング | 構造設計、形状最適化、パラメータ推定 |
| ツール | OR-Tools, PuLP | scipy.optimize, COMSOL, Ansys |

**重要**: 現実の問題は離散と連続が混在することが多い。
例えば「梁の断面は連続値だが、使える材料は3種類（離散）」など。
その場合は連続最適化で解いた後、離散値に丸めるか、
Mixed-Integer Nonlinear Programming (MINLP) を検討する。

---

## どんな問題に使うか

### 1. 構造設計（Structural Design）

部材の断面寸法・板厚を変数として、重量を最小化しつつ
応力・たわみ・座屈などの制約を満たす設計を求める。

**典型例:**
- 梁の幅と高さを決めて重量最小化
- トラス構造の各部材の断面積を最適化
- 板厚の分布を決めてパネル重量を削減

**特徴:**
- 制約が物理法則（応力 <= 許容応力）で明確
- 目的関数・制約の勾配が解析的に計算できることが多い
- → 勾配ベースの手法（SLSQP）が高速

### 2. 形状最適化（Shape Optimization）

構造の外形（境界形状）を変数として、性能指標を最適化する。

**典型例:**
- 航空機翼の断面形状
- 自動車ボディの空力形状
- 射出成形金型のゲート位置

**特徴:**
- 制御点やスプラインパラメータで形状を記述
- メッシュの再生成が必要な場合がある
- 局所解が多い → マルチスタートが有効

### 3. トポロジー最適化（Topology Optimization）

材料をどこに配置するか（存在/非存在）を最適化する。
形状最適化よりも自由度が高く、設計の根本的な見直しが可能。

**典型例:**
- 3Dプリンタ用の軽量構造
- 建築の構造レイアウト
- 熱伝導経路の最適化

**手法:**
- **SIMP法** (Solid Isotropic Material with Penalization): 各要素の密度を連続変数 [0,1] として扱い、ペナルティで 0/1 に近づける。最も普及した手法。
- **Level Set法**: 境界を陰関数で表現。境界がシャープだが実装が複雑。
- **ESO/BESO**: 要素の追加/除去を繰り返す進化的手法。

### 4. パラメータチューニング

プロセスパラメータや制御パラメータを最適化する。

**典型例:**
- 製造プロセスの温度・圧力・速度の最適化
- PID制御のゲイン調整
- 機械学習のハイパーパラメータ（ベイズ最適化）

**特徴:**
- 目的関数がブラックボックス（解析的な勾配なし）のことが多い
- → 微分不要な手法（Nelder-Mead, 遺伝的アルゴリズム）が適する
- シミュレーションの評価コストが高い場合はサロゲートモデルを検討

---

## scipy.optimize の手法一覧

### 局所探索（勾配ベース）

| 手法 | 制約 | 勾配 | 特徴 | 推奨場面 |
|------|------|------|------|---------|
| **SLSQP** | 等式/不等式 | 数値微分可 | 逐次二次計画法。制約付き問題の第一選択 | 構造最適化、制約あり |
| **L-BFGS-B** | 境界のみ | 数値微分可 | 低メモリ準ニュートン法。大規模問題に強い | 制約なし高次元 |
| **trust-constr** | 等式/不等式 | 数値微分可 | 信頼領域法。SLSQP より大規模に対応 | 大規模制約付き |
| **Nelder-Mead** | なし | 不要 | シンプレックス法（微分不要） | ブラックボックス低次元 |

### 大域探索（メタヒューリスティクス）

| 手法 | 制約 | 特徴 | 推奨場面 |
|------|------|------|---------|
| **differential_evolution** | 境界 + 非線形 | 差分進化。非凸問題に強い | 多峰性・ブラックボックス |
| **dual_annealing** | 境界のみ | 模擬アニーリング。大域最適を探索 | 極端に多峰性な問題 |
| **shgo** | 境界 + 非線形 | 準大域探索。Lipschitz条件を利用 | 中程度の非凸問題 |
| **basinhopping** | なし | マルチスタート＋局所探索 | 滑らかだが多峰性 |

### 手法選択のフローチャート

```
制約があるか?
├── YES → 等式/不等式制約
│   ├── 勾配が計算できるか?
│   │   ├── YES → SLSQP（小〜中規模）or trust-constr（大規模）
│   │   └── NO  → SLSQP（数値微分）or differential_evolution
│   └── 非凸（局所解が多い）か?
│       ├── YES → differential_evolution → SLSQP で磨き
│       └── NO  → SLSQP で十分
└── NO  → 境界制約のみ
    ├── 凸か?
    │   ├── YES → L-BFGS-B
    │   └── NO  → differential_evolution or basinhopping
    └── 変数が多いか (>100)?
        ├── YES → L-BFGS-B（勾配必須）
        └── NO  → Nelder-Mead or differential_evolution
```

---

## SIMP法によるトポロジー最適化

### 基本原理

1. 設計領域を有限要素メッシュで離散化する
2. 各要素に密度変数 rho_e (0 <= rho_e <= 1) を割り当てる
3. 要素のヤング率を `E_e = E_min + rho_e^p * (E_0 - E_min)` で定義する
   - p: ペナルティ係数（通常3.0）。中間密度にペナルティを課す
4. コンプライアンス（ひずみエネルギー）を最小化する
5. 体積制約: `sum(rho_e) / N <= volume_fraction`

### 密度フィルタ

チェッカーボードパターン（隣接要素が交互に 0/1 になる非物理的パターン）を
防ぐために、密度フィルタを適用する。

```
rho_filtered[e] = sum(w_ij * rho[j]) / sum(w_ij)
w_ij = max(0, r_min - dist(e, j))
```

r_min はフィルタ半径で、メッシュ幅の1.5倍程度が標準。

### OC法（Optimality Criteria）

ラグランジュの最適性条件から導かれる更新式で密度を更新する。
SLSQPなどの汎用最適化手法より高速。

```
rho_new[e] = rho[e] * sqrt(-dc[e] / lambda)
```

lambda はラグランジュ乗数（体積制約を満たすように二分法で決定）。

### FEMとの接続

トポロジー最適化にはFEM（有限要素法）が不可欠。最適化ループの中で
毎回FEMを解いて変位を求め、コンプライアンスと感度を計算する。

```
最適化ループ:
  1. 密度フィルタ適用
  2. 剛性行列を組み立て（密度に依存）
  3. FEM求解: K * U = F
  4. コンプライアンスと感度を計算
  5. OC法で密度を更新
  6. 収束判定
```

テンプレートでは4節点四角形要素・平面応力を使った簡易FEMを内蔵している。
実務では外部FEMソルバー（Calculix, OpenFOAM等）と連携する。

---

## scipyで扱える規模の目安

| 問題タイプ | 変数数 | 計算時間 | scipy で実用的か |
|-----------|--------|---------|----------------|
| 梁断面最適化 | 2-20 | < 1秒 | 十分 |
| トラス断面最適化 | 10-100 | < 10秒 | 十分 |
| 形状最適化（制御点） | 10-50 | < 30秒 | 十分 |
| トポロジー最適化 2D | 1,000-10,000要素 | 1-60秒 | プロトタイプ向け |
| トポロジー最適化 3D | 100,000+ 要素 | 数時間 | 厳しい（商用推奨） |
| パラメータチューニング | 3-20 | 評価関数依存 | 十分（評価が軽ければ） |

### scipy で足りない場合の選択肢

| ツール | 特徴 | ライセンス |
|--------|------|----------|
| **OpenMDAO** | NASA開発の多領域最適化フレームワーク | 無料 (Apache 2.0) |
| **FEniCS + dolfin-adjoint** | FEM + 自動微分。形状/トポロジー最適化 | 無料 (LGPL) |
| **Optistruct (Altair)** | 産業用トポロジー最適化 | 商用 |
| **ANSYS Topology** | 産業用、3Dプリント連携あり | 商用 |
| **COMSOL** | マルチフィジクス連成最適化 | 商用 |
| **TOSCA (Dassault)** | Abaqus連携のトポロジー最適化 | 商用 |

---

## 実装のコツ

### 1. 変数のスケーリング

変数のオーダーが大きく異なると収束が悪化する。

```python
# 悪い例: 幅 0.1m と応力 250MPa を同じ変数として扱う
x = [0.1, 250e6]  # オーダーが10^9違う

# 良い例: 正規化する
x_normalized = [width / width_ref, stress / stress_ref]
```

### 2. 制約の正規化

制約も同じオーダーに揃える。

```python
# 悪い例
constraints = [{"type": "ineq", "fun": lambda x: 250e6 - stress(x)}]

# 良い例: 相対値にする
constraints = [{"type": "ineq", "fun": lambda x: 1.0 - stress(x) / 250e6}]
```

### 3. マルチスタート（非凸問題）

局所解が多い場合、初期値を変えて複数回実行し最良解を選ぶ。

```python
best = None
for _ in range(10):
    x0 = np.random.uniform(lo, hi, n_vars)
    result = optimize.minimize(obj, x0, method="SLSQP", ...)
    if best is None or result.fun < best.fun:
        best = result
```

### 4. 勾配の提供

解析的な勾配を提供すると収束が大幅に改善する。

```python
def objective_and_grad(x):
    b, h = x
    weight = b * h * L * density
    grad = np.array([h * L * density, b * L * density])
    return weight, grad

result = optimize.minimize(
    objective_and_grad, x0, method="SLSQP", jac=True, ...
)
```

### 5. トポロジー最適化の注意点

- **ペナルティ係数 p**: 小さく始めて徐々に上げる（continuation法）と収束改善
- **フィルタ半径 r_min**: 小さいとチェッカーボード、大きいと解像度低下
- **体積率**: 0.3-0.5 が一般的。0.1以下は収束困難
- **メッシュ依存性**: メッシュが粗いと解も粗い。最終設計には十分な解像度が必要

---

## 離散最適化との組み合わせパターン

実務では離散変数と連続変数が混在することが多い。

### パターン1: 二段階最適化

1. 連続変数を最適化（梁の断面を連続値で求解）
2. 離散化（標準部材に丸める: 100mm → H-100x100）
3. 離散化後の解を再評価

### パターン2: 外側離散・内側連続

- 外側ループ: 部材の種類を列挙（離散）
- 内側ループ: 各種類の中で寸法を最適化（連続）

### パターン3: Mixed-Integer Nonlinear Programming

```python
# PuLP + scipy の組み合わせ
# 整数変数: 材料の選択 (0/1)
# 連続変数: 寸法
# → 分枝限定法で整数変数を固定 → 各枝で連続最適化
```

---

## このテンプレートの使い方

### 構造設計問題が来たら

```python
from continuous_optimization_template import optimize_beam_structure

result = optimize_beam_structure(
    loads=[{"position": 0.5, "magnitude": 50000, "type": "point"}],
    material_props={"E": 210e9, "density": 7850, "yield_stress": 250e6, "length": 3.0},
    constraints={"max_deflection": 0.01, "safety_factor": 1.5, ...},
)
```

### トポロジー最適化を試したいとき

```python
from continuous_optimization_template import optimize_topology_2d, plot_topology

result = optimize_topology_2d(
    nx=60, ny=20,
    loads={load_node: (0.0, -1.0)},
    supports=support_dict,
    volume_fraction=0.5,
)
plot_topology(result["density"], save_path="topology.png")
```

### パラメータチューニングに使うとき

```python
from continuous_optimization_template import optimize_parameters

result = optimize_parameters(
    objective_fn=my_simulation,
    bounds=[(0, 100), (0, 50), (200, 800)],
    method="differential_evolution",
)
```
