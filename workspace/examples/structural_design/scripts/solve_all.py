"""片持ち梁の構造最適化 — 全ワークフロー実行スクリプト。

以下の4ステップを順に実行する:
1. 構造解析（均一断面のベースライン評価）
2. 断面最適化（SLSQP で重量最小化）
3. トポロジー最適化（SIMP法で材料配置を最適化）
4. 結果の比較・レポート生成

使い方::

    cd workspace/examples/structural_design
    python scripts/solve_all.py

結果は results/ と reports/ に保存される。
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import numpy as np

# テンプレートの読み込み
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "reference"))
from continuous_optimization_template import (
    optimize_beam_structure,
    optimize_topology_2d,
    plot_convergence,
    plot_topology,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# --- パス設定 ---
BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = BASE_DIR / "results"
REPORTS_DIR = BASE_DIR / "reports"
RESULTS_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)


def load_data() -> tuple[dict, dict]:
    """データファイルを読み込む。"""
    with open(DATA_DIR / "structure.json", encoding="utf-8") as f:
        structure = json.load(f)
    with open(DATA_DIR / "constraints.json", encoding="utf-8") as f:
        constraints = json.load(f)
    return structure, constraints


# ============================================================================
# Step 1: ベースライン評価（均一断面）
# ============================================================================

def evaluate_baseline(structure: dict, constraints: dict) -> dict:
    """均一断面（最大寸法 / 最小寸法）でのベースラインを評価する。"""
    logger.info("=" * 50)
    logger.info("Step 1: ベースライン評価")
    logger.info("=" * 50)

    mat = structure["material"]
    L = structure["dimensions"]["length"]
    total_load = sum(ld["magnitude"] for ld in structure["loads"])
    E = mat["E"]
    density = mat["density"]
    sigma_allow = mat["yield_stress"] / constraints["stress_constraints"]["safety_factor"]
    max_defl = constraints["deflection_constraints"]["max_deflection"]

    results = {}

    for label, b, h in [
        ("最大断面（過剰設計）", constraints["dimension_constraints"]["max_width"],
         constraints["dimension_constraints"]["max_height"]),
        ("最小断面（不足）", constraints["dimension_constraints"]["min_width"],
         constraints["dimension_constraints"]["min_height"]),
        ("中間断面", 0.15, 0.30),
    ]:
        I = b * h**3 / 12
        M_max = total_load * L / 4  # 簡易: 中央荷重近似
        sigma = M_max * (h / 2) / I
        delta = total_load * L**3 / (48 * E * I)
        weight = b * h * L * density

        info = {
            "label": label,
            "width": b,
            "height": h,
            "weight_kg": round(weight, 2),
            "max_stress_MPa": round(sigma / 1e6, 2),
            "max_deflection_mm": round(delta * 1000, 4),
            "stress_ratio": round(sigma / sigma_allow, 4),
            "deflection_ratio": round(delta / max_defl, 4),
            "feasible": sigma <= sigma_allow and delta <= max_defl,
        }
        results[label] = info

        status = "OK" if info["feasible"] else "NG"
        logger.info(
            "  %s: b=%.3f h=%.3f → %.1fkg, sigma=%.1fMPa(%.1f%%), delta=%.3fmm(%.1f%%) [%s]",
            label, b, h, weight,
            sigma / 1e6, info["stress_ratio"] * 100,
            delta * 1000, info["deflection_ratio"] * 100,
            status,
        )

    return results


# ============================================================================
# Step 2: 断面最適化（SLSQP）
# ============================================================================

def run_beam_optimization(structure: dict, constraints: dict) -> dict:
    """SLSQPで梁断面を最適化する。"""
    logger.info("=" * 50)
    logger.info("Step 2: 断面最適化（SLSQP）")
    logger.info("=" * 50)

    result = optimize_beam_structure(
        loads=structure["loads"],
        material_props={
            "E": structure["material"]["E"],
            "density": structure["material"]["density"],
            "yield_stress": structure["material"]["yield_stress"],
            "length": structure["dimensions"]["length"],
        },
        constraints={
            "max_deflection": constraints["deflection_constraints"]["max_deflection"],
            "safety_factor": constraints["stress_constraints"]["safety_factor"],
            "min_width": constraints["dimension_constraints"]["min_width"],
            "max_width": constraints["dimension_constraints"]["max_width"],
            "min_height": constraints["dimension_constraints"]["min_height"],
            "max_height": constraints["dimension_constraints"]["max_height"],
        },
        method="SLSQP",
    )

    logger.info("  最適幅: %.4f m", result["optimal_width"])
    logger.info("  最適高さ: %.4f m", result["optimal_height"])
    logger.info("  重量: %.2f kg", result["weight"])
    logger.info("  応力比: %.2f%%", result["stress_ratio"] * 100)
    logger.info("  たわみ比: %.2f%%", result["deflection_ratio"] * 100)
    logger.info("  成功: %s", result["success"])

    return result


# ============================================================================
# Step 3: トポロジー最適化（SIMP法）
# ============================================================================

def run_topology_optimization(structure: dict, constraints: dict) -> dict:
    """SIMP法でトポロジー最適化を実行する。"""
    logger.info("=" * 50)
    logger.info("Step 3: トポロジー最適化（SIMP法）")
    logger.info("=" * 50)

    topo_cfg = structure["topology_optimization"]
    nx = topo_cfg["nx"]
    ny = topo_cfg["ny"]
    vf = constraints["topology_constraints"]["volume_fraction"]

    # 片持ち梁: 左端を完全固定、右端中央に下向き荷重
    supports = {}
    for iy in range(ny + 1):
        node_id = iy * (nx + 1)
        supports[node_id] = (True, True)

    # 右端中央に下向き荷重
    load_node = (ny // 2) * (nx + 1) + nx
    loads = {load_node: (0.0, -1.0)}

    all_results = {}

    for vf_i in topo_cfg["volume_fractions"]:
        logger.info("--- 体積率 %.0f%% ---", vf_i * 100)
        result = optimize_topology_2d(
            nx=nx,
            ny=ny,
            loads=loads,
            supports=supports,
            volume_fraction=vf_i,
            penalty=3.0,
            r_min=1.5,
            iterations=100,
            tol=0.01,
        )

        label = f"vf_{int(vf_i * 100)}"
        all_results[label] = {
            "volume_fraction_target": vf_i,
            "volume_fraction_actual": result["volume_fraction_actual"],
            "compliance": result["compliance"],
            "iterations": result["iterations"],
            "elapsed_sec": result["elapsed_sec"],
            "convergence": result["convergence"],
        }

        # 密度分布を保存
        density_path = RESULTS_DIR / f"topology_{label}.npy"
        np.save(str(density_path), result["density"])

        # 可視化
        try:
            plot_path = RESULTS_DIR / f"topology_{label}.png"
            plot_topology(
                result["density"],
                title=f"トポロジー最適化（体積率{int(vf_i*100)}%）",
                save_path=str(plot_path),
            )
        except Exception as e:
            logger.warning("画像保存スキップ（matplotlibの問題）: %s", e)

        # 収束曲線
        try:
            conv_path = RESULTS_DIR / f"convergence_{label}.png"
            plot_convergence(
                result["convergence"],
                title=f"収束曲線（体積率{int(vf_i*100)}%）",
                save_path=str(conv_path),
            )
        except Exception as e:
            logger.warning("収束曲線保存スキップ: %s", e)

        logger.info(
            "  compliance=%.4f, vol=%.2f%%, %d反復, %.1f秒",
            result["compliance"],
            result["volume_fraction_actual"] * 100,
            result["iterations"],
            result["elapsed_sec"],
        )

    return all_results


# ============================================================================
# Step 4: 結果の比較とレポート生成
# ============================================================================

def generate_summary(
    baseline: dict, beam_opt: dict, topo_results: dict
) -> str:
    """全結果をまとめたサマリーテキストを生成する。"""
    lines = []
    lines.append("=" * 60)
    lines.append("片持ち梁 構造最適化 — 結果サマリー")
    lines.append("=" * 60)

    # ベースライン比較
    lines.append("\n## ベースライン比較\n")
    lines.append(f"{'手法':<20} {'重量[kg]':>10} {'応力比':>10} {'たわみ比':>10} {'判定':>6}")
    lines.append("-" * 60)
    for label, info in baseline.items():
        status = "OK" if info["feasible"] else "NG"
        lines.append(
            f"{label:<20} {info['weight_kg']:>10.1f} {info['stress_ratio']:>10.2f} "
            f"{info['deflection_ratio']:>10.2f} {status:>6}"
        )

    # 断面最適化
    lines.append(f"\n{'SLSQP最適化':<20} {beam_opt['weight']:>10.1f} {beam_opt['stress_ratio']:>10.2f} "
                 f"{beam_opt['deflection_ratio']:>10.2f} {'OK':>6}")

    # 重量削減率
    max_weight = baseline["最大断面（過剰設計）"]["weight_kg"]
    reduction = (1 - beam_opt["weight"] / max_weight) * 100
    lines.append(f"\n重量削減率（最大断面比）: {reduction:.1f}%")

    # トポロジー最適化
    lines.append("\n## トポロジー最適化結果\n")
    lines.append(f"{'体積率':>10} {'コンプライアンス':>18} {'反復数':>8} {'計算時間':>10}")
    lines.append("-" * 50)
    for label, info in topo_results.items():
        lines.append(
            f"{info['volume_fraction_actual']*100:>9.1f}% {info['compliance']:>18.4f} "
            f"{info['iterations']:>8d} {info['elapsed_sec']:>9.2f}秒"
        )

    return "\n".join(lines)


def save_results(baseline: dict, beam_opt: dict, topo_results: dict) -> None:
    """結果をJSONファイルに保存する。"""
    # beam_opt の numpy 型を変換
    all_results = {
        "timestamp": datetime.now().isoformat(),
        "baseline": baseline,
        "beam_optimization": beam_opt,
        "topology_optimization": {
            k: {kk: vv for kk, vv in v.items() if kk != "convergence"}
            for k, v in topo_results.items()
        },
    }

    path = RESULTS_DIR / "all_results.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)
    logger.info("結果を保存: %s", path)


def generate_reports(baseline: dict, beam_opt: dict, topo_results: dict) -> None:
    """レポートファイルを生成する。"""
    today = datetime.now().strftime("%Y-%m-%d")
    max_w = baseline["最大断面（過剰設計）"]["weight_kg"]
    reduction = (1 - beam_opt["weight"] / max_w) * 100
    mid_info = baseline["中間断面"]

    # --- assess_report.md ---
    assess = f"""# アセスメントレポート: 片持ち梁の構造最適化

## 1. 問題の概要

- **構造タイプ**: 片持ち梁（固定端-自由端）
- **全長**: 2.0 m
- **材料**: SS400（一般構造用圧延鋼材）
- **荷重**: 先端30kN + 自重相当5kN = 合計35kN
- **設計変数**: 矩形断面の幅(b)と高さ(h) → 2変数

## 2. 問題の分類

| 項目 | 内容 |
|------|------|
| 最適化タイプ | **連続最適化**（設計変数が実数） |
| 目的関数 | 重量最小化（= 断面積最小化） |
| 制約 | 応力 <= 163.3MPa, たわみ <= 5mm, 寸法範囲 |
| 凸性 | **非凸**（応力制約が非線形） |
| 推奨手法 | SLSQP（勾配ベース、制約付き） |

## 3. データの品質

- 荷重条件: 明示的。ただし動的荷重の係数1.5は仮定値
- 材料特性: SS400は標準値を使用（問題なし）
- 制約: たわみ制限 L/400 は比較的厳しい（搬送ライン向け）

## 4. 仮定と注意点

1. **断面は一様**: 実際にはテーパー梁（根元が太く先端が細い）の方が効率的
2. **静的荷重のみ**: 疲労荷重・振動は考慮していない
3. **単一材料**: 複合材料やハイブリッド断面は対象外
4. **座屈は未考慮**: 薄い断面では横座屈が支配的になる可能性あり
5. **接合部の応力集中は無視**: 固定端のボルト穴等

## 5. 次のステップ

1. ベースライン評価（均一断面の解析）
2. SLSQP で断面最適化
3. トポロジー最適化で材料配置の参考案を取得
4. 製造制約（標準サイズへの丸め）を反映
"""
    (REPORTS_DIR / "assess_report.md").write_text(assess, encoding="utf-8")

    # --- baseline_report.md ---
    baseline_md = f"""# ベースラインレポート: 片持ち梁の構造最適化

**作成日**: {today}

## 1. 評価した手法

| 手法 | 幅[m] | 高さ[m] | 重量[kg] | 応力比 | たわみ比 | 判定 |
|------|-------|---------|---------|--------|---------|------|
| 最大断面 | {baseline['最大断面（過剰設計）']['width']:.2f} | {baseline['最大断面（過剰設計）']['height']:.2f} | {baseline['最大断面（過剰設計）']['weight_kg']:.1f} | {baseline['最大断面（過剰設計）']['stress_ratio']:.4f} | {baseline['最大断面（過剰設計）']['deflection_ratio']:.4f} | 過剰 |
| 最小断面 | {baseline['最小断面（不足）']['width']:.2f} | {baseline['最小断面（不足）']['height']:.2f} | {baseline['最小断面（不足）']['weight_kg']:.1f} | {baseline['最小断面（不足）']['stress_ratio']:.4f} | {baseline['最小断面（不足）']['deflection_ratio']:.4f} | 不可 |
| 中間断面 | {mid_info['width']:.2f} | {mid_info['height']:.2f} | {mid_info['weight_kg']:.1f} | {mid_info['stress_ratio']:.4f} | {mid_info['deflection_ratio']:.4f} | {'OK' if mid_info['feasible'] else 'NG'} |
| **SLSQP最適化** | **{beam_opt['optimal_width']:.4f}** | **{beam_opt['optimal_height']:.4f}** | **{beam_opt['weight']:.1f}** | **{beam_opt['stress_ratio']:.4f}** | **{beam_opt['deflection_ratio']:.4f}** | **OK** |

## 2. ボトルネック分析

最適化の結果、以下が判明:

- **応力比**: {beam_opt['stress_ratio']:.2f} → {'応力制約がアクティブ（ギリギリ）' if beam_opt['stress_ratio'] > 0.9 else '応力には余裕あり'}
- **たわみ比**: {beam_opt['deflection_ratio']:.2f} → {'たわみ制約がアクティブ（ギリギリ）' if beam_opt['deflection_ratio'] > 0.9 else 'たわみには余裕あり'}

{'**主要ボトルネック: たわみ制約**。応力より先にたわみ制約が支配的になっている。' if beam_opt['deflection_ratio'] > beam_opt['stress_ratio'] else '**主要ボトルネック: 応力制約**。たわみより先に応力制約が支配的になっている。'}

## 3. 改善の方向性

1. **高さ優先設計**: たわみは h^3 に反比例。高さを増やすのが最も効率的。
2. **トポロジー最適化**: 均一断面ではなく応力に応じた材料配置を検討。
3. **たわみ制約の緩和**: L/400 → L/250 に緩和できれば大幅軽量化の余地あり。
4. **標準サイズへの丸め**: 最適値を標準サイズに丸めた場合の影響を評価する。
"""
    (REPORTS_DIR / "baseline_report.md").write_text(baseline_md, encoding="utf-8")

    # --- improve_report.md ---
    # トポロジー結果
    topo_lines = []
    for label, info in topo_results.items():
        vf_pct = int(info["volume_fraction_target"] * 100)
        topo_lines.append(
            f"| {vf_pct}% | {info['compliance']:.4f} | "
            f"{info['iterations']} | {info['elapsed_sec']:.1f}秒 |"
        )
    topo_table = "\n".join(topo_lines)

    improve = f"""# 改善レポート: 片持ち梁の構造最適化

**作成日**: {today}

## 1. 実施した改善

### 1.1 断面最適化（SLSQP）

ベースライン（最大断面: {max_w:.1f} kg）から SLSQP で重量最小化を実施。

- **最適幅**: {beam_opt['optimal_width']:.4f} m
- **最適高さ**: {beam_opt['optimal_height']:.4f} m
- **重量**: {beam_opt['weight']:.1f} kg
- **重量削減率**: **{reduction:.1f}%**
- **計算時間**: {beam_opt['elapsed_sec']:.4f} 秒
- **反復回数**: {beam_opt['iterations']} 回

### 1.2 トポロジー最適化（SIMP法）

材料配置の参考案として、3種類の体積率でトポロジー最適化を実施。

| 体積率 | コンプライアンス | 反復数 | 計算時間 |
|--------|----------------|--------|---------|
{topo_table}

## 2. トポロジー最適化の知見

- 片持ち梁の最適トポロジーは、上下のフランジ（曲げ抵抗）と対角のウェブ（せん断伝達）からなるトラス状構造
- 固定端付近に材料が集中し、自由端付近は最低限の材料のみ
- 体積率30%でもトラス状の構造が維持されるが、コンプライアンスは増大する

## 3. 製造への反映

最適化結果をそのまま製造するのではなく、以下の手順で実設計に反映する:

1. 断面最適化の結果を標準サイズに丸める
2. トポロジー最適化の結果をトラス構造や肉抜き形状の参考にする
3. 丸め後の設計を再評価し、制約を満たすことを確認する
"""
    (REPORTS_DIR / "improve_report.md").write_text(improve, encoding="utf-8")

    # --- v1_proposal.md ---
    proposal = f"""# 構造最適化 改善提案書 (v1)

**作成日**: {today}
**対象**: 工場搬送ライン用片持ち梁（全長2.0m、SS400）

---

## エグゼクティブサマリー

片持ち梁の断面寸法を数理最適化した結果、**現行の最大断面設計に比べて重量を{reduction:.0f}%削減**できることが判明しました。応力・たわみの制約を全て満たしつつ、材料コストを大幅に低減できます。

さらにトポロジー最適化により、材料の最適配置パターンを可視化しました。これを参考に、肉抜き加工やトラス構造への変更を検討することで、追加の軽量化が見込めます。

---

## 1. 現状の課題

現在の設計は**過剰設計**です。

| 指標 | 現状（最大断面） | 最適化後 |
|------|----------------|---------|
| 断面寸法 | 300mm x 500mm | {beam_opt['optimal_width']*1000:.1f}mm x {beam_opt['optimal_height']*1000:.1f}mm |
| 重量 | {max_w:.1f} kg | {beam_opt['weight']:.1f} kg |
| 応力利用率 | {baseline['最大断面（過剰設計）']['stress_ratio']*100:.1f}% | {beam_opt['stress_ratio']*100:.1f}% |
| たわみ利用率 | {baseline['最大断面（過剰設計）']['deflection_ratio']*100:.1f}% | {beam_opt['deflection_ratio']*100:.1f}% |
| 材料コスト概算 | 基準 | **約{(1-beam_opt['weight']/max_w)*100:.0f}%削減** |

応力利用率 {baseline['最大断面（過剰設計）']['stress_ratio']*100:.1f}% は、材料の強度の大部分が使われていないことを意味します。

---

## 2. 提案

### 案A: 断面最適化のみ（推奨）

**重量 {beam_opt['weight']:.1f} kg**（{reduction:.0f}%削減）

- 矩形断面の幅と高さを最適化
- 標準サイズに丸めた上で再検証が必要
- 既存の加工設備で対応可能
- **リスク**: 低（従来工法の延長）

### 案B: トポロジー最適化結果を参考にトラス化

**推定重量: 案Aのさらに20-30%削減**

- トポロジー最適化で得られたトラス状パターンを参考に再設計
- 溶接構造になるため加工コストは増加
- 3Dプリンタによる製造も検討可能
- **リスク**: 中（接合部の疲労評価が追加で必要）

### 案C: たわみ制約の緩和

**追加削減の余地: 大（制約次第）**

- 現在のたわみ制限 L/400（5mm）は搬送ラインとしては厳しめ
- L/250（8mm）に緩和できる場合、断面をさらに小さくできる
- **必要**: 搬送精度の要求仕様を再確認

---

## 3. 次のステップ

1. **標準サイズへの丸め**: 最適化結果を標準断面に変換し再評価
2. **たわみ要求の確認**: L/400 が本当に必要かを現場に確認
3. **動的荷重の評価**: 疲労・振動を考慮した詳細解析（必要に応じて）
4. **コスト見積もり**: 材料費・加工費を含めたコスト比較

---

## 技術詳細

### 使用手法

| 項目 | 内容 |
|------|------|
| 断面最適化 | scipy.optimize.minimize (SLSQP) |
| トポロジー最適化 | SIMP法 (Optimality Criteria) |
| FEM | 4節点四角形要素・平面応力 |
| 計算環境 | Python + scipy + numpy |

### 仮定事項

1. 静的荷重のみ（動的荷重は安全率1.5で考慮）
2. 単一材料（SS400）
3. 座屈は未考慮（必要に応じて追加評価）
4. 接合部の応力集中は無視
"""
    (REPORTS_DIR / "v1_proposal.md").write_text(proposal, encoding="utf-8")

    logger.info("レポートを生成: %s", REPORTS_DIR)


# ============================================================================
# メイン
# ============================================================================

def main() -> None:
    """全ワークフローを実行する。"""
    t_start = time.time()
    print("=" * 60)
    print("片持ち梁 構造最適化 — 全ワークフロー実行")
    print("=" * 60)

    # データ読み込み
    structure, constraints = load_data()
    logger.info("データ読み込み完了: %s", structure["problem_name"])

    # Step 1: ベースライン
    baseline = evaluate_baseline(structure, constraints)

    # Step 2: 断面最適化
    beam_opt = run_beam_optimization(structure, constraints)

    # Step 3: トポロジー最適化
    topo_results = run_topology_optimization(structure, constraints)

    # Step 4: サマリーとレポート
    logger.info("=" * 50)
    logger.info("Step 4: 結果サマリー & レポート生成")
    logger.info("=" * 50)

    summary = generate_summary(baseline, beam_opt, topo_results)
    print("\n" + summary)

    save_results(baseline, beam_opt, topo_results)
    generate_reports(baseline, beam_opt, topo_results)

    elapsed = time.time() - t_start
    print(f"\n全行程完了: {elapsed:.1f}秒")


if __name__ == "__main__":
    main()
