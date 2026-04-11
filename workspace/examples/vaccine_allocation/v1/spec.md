# COVID-19 Vaccine Allocation — v1 Specification

**Project**: vaccine_allocation
**Version**: v1 (initial)
**Date**: 2026-04-11
**Audience**: Metropolitan health department director, public-health planner, logistics lead

## 1. Business Context

A metropolitan health authority must roll out COVID-19 vaccines across
6 vaccination sites over 10 weeks for 5 priority groups (total population
110,000). Three vaccine products are in play, with different cold-chain
requirements and dosing schedules:

- **VP** (Pfizer-equivalent): 2 doses, 3-week gap, ultracold storage
- **VM** (Moderna-equivalent): 2 doses, 4-week gap, standard freezer
- **VJ** (Janssen-equivalent): single dose, refrigerator

Supply ramps from week 1 through week 10. Site capacity and cold-chain
compatibility constrain where each product can be given. The planner must
also respect a priority-based rollout order (healthcare workers first,
elderly before at-risk adults, general population last).

This is a **multi-period capacitated allocation problem** with temporal
coupling (2nd-dose equality constraints at a fixed gap).

## 2. Sources (Ref Traceability)

### 内部ファイル
- **R1**: `data/priority_groups.csv` — 5 groups, ~108,500 total population (架空 M 市スケール)
- **R2**: `data/sites.csv` — 6 sites, weekly capacity, freezer flags, staffing tier
- **R3**: `data/vaccine_types.csv` — 3 vaccines with gap and storage metadata
- **R4**: `data/weekly_supply.csv` — 10-week supply ramp per vaccine
- **R5**: `data/constraints.csv` — 18 HCs / 6 SCs catalogue

### 外部公開データ (参考)
- **R6**: 総務省 2020 年国勢調査の年齢構成比
  - `https://www.stat.go.jp/data/kokusei/2020/`
  - 年齢ピラミッド (75 歳以上、65-74 歳、15-64 歳) の比率を中規模自治体想定に適用
- **R7**: 厚生労働省 新型コロナワクチン接種について (2021-2022)
  - `https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/vaccine_00184.html`
  - 優先順位: 医療従事者 → 65 歳以上 → 基礎疾患 → 60-64 歳 → 一般 16-59 歳
  - ワクチン規格: Pfizer 3 週間隔・超低温 −75℃、Moderna 4 週間隔・−20℃
  - 週次供給量ランプアップ: 2021 年 Q2-Q3 ロールアウトを参考にスケール
- **R8**: `scripts/staged_baseline.py::build_model` — reference implementation

**注: 本データは架空自治体の合成データです**。
- 自治体 (架空 M 市)、会場 (S1-S6)、人数・設備情報はすべて架空
- 実在の自治体・病院・会場とは関係ありません
- R6/R7 は「年齢構成比・ワクチン仕様・ロールアウトのタイミング」の現実感を出すための参考です
- 実務で使う際は各地域の最新の人口統計・会場情報で置き換えてください

## 3. Decision Variables

Core CP-SAT variables (see `scripts/staged_baseline.py::build_model`):

| Variable | Domain | Meaning |
|---|---|---|
| `dose1[g, s, w, v]` | int [0, 1500] | 1st doses of vaccine `v` given to group `g` at site `s` in week `w` |
| `dose2[g, s, w, v]` | int [0, 1500] | 2nd doses of same tuple (structurally 0 for VJ) |
| `total_people` | int | Sum of all 1st doses (= people reached) |

**Variable count** (after build_model, full HC set): 1,801 integer vars,
~2,398 constraints. Scenario models (`build_with_objective`) add ~14 metric
helper vars, ending at 1,815 vars.

Index sizes: |G|=5, |S|=6, |W|=10, |V|=3 → 5·6·10·3 = 900 cells × 2 doses = 1,800 core vars.

## 4. Hard Constraints (18) — see `data/constraints.csv`

| # | HC | Summary |
|---|---|---|
| HC1 | pop cap | Total people per group ≤ population |
| HC2 | site capacity | Σ(d1+d2) at (s,w) ≤ weekly_capacity |
| HC3 | weekly supply | Σ(d1+d2) of v at w ≤ doses_arriving(w,v) |
| HC4 | ultracold | VP only at sites with ultralow freezer |
| HC5 | standard cold | VM only at sites with standard or ultralow freezer |
| HC6 | VP gap | `dose2[g,s,w,VP] == dose1[g,s,w-3,VP]` |
| HC7 | VM gap | `dose2[g,s,w,VM] == dose1[g,s,w-4,VM]` |
| HC8 | VJ single | `dose2[*,*,*,VJ] == 0` |
| HC9 | no mixing | Implied by HC6/HC7 (2nd dose linked to 1st of same vaccine) |
| HC10 | horizon | 1st doses blocked when gap would run past week 10 |
| HC11 | G1→G2 gate | G2 may not receive 1st doses before week 3 (A1 simplification) |
| HC12 | G2→G4/G5 gate | G4 ≥ week 4, G5 ≥ week 5 (A2 simplification) |
| HC13 | monotonic | Cumulative coverage monotonic (trivial: doses ≥ 0) |
| HC14 | ≤100% | Same rule as HC1 (duplicated for audit trail) |
| HC15 | low-staffing | S5, S6 may only administer VJ (no 2-dose vaccines) |
| HC16 | d1↔d2 matching | Total d1 of VP/VM == total d2 of same vaccine |
| HC17 | non-negative int | Variable domain |
| HC18 | cumulative inventory | Σ(used v by week w) ≤ Σ(supply v by week w) |

## 5. Soft Constraints (6)

| # | SC | Direction | Notes |
|---|---|---|---|
| SC1 | total people vaccinated | maximize | Primary objective |
| SC2 | priority-weighted people | maximize | w_rank = {1:60, 2:30, 3:20, 4:15, 5:12} |
| SC3 | wasted doses | minimize | total supply − total used |
| SC4 | site balance | minimize | max_site_load − min_site_load |
| SC5 | early completion | minimize | Σ week × w_rank × dose1 (earlier weeks reward higher-priority groups) |
| SC6 | ultralow use | minimize | VP doses (cold chain is expensive) |

## 6. Assumptions (A1-A6)

- **A1**: HC11 is simplified from "G1 ≥ 80% before G2 starts" to a time
  gate "G2 may start at w ≥ 3". The gate captures the intent without
  requiring nonlinear chaining.
- **A2**: HC12 likewise simplified: G4 may start at w ≥ 4, G5 at w ≥ 5.
  Rationale: by w4 the pipeline has enough supply for multiple groups in
  parallel. Director sign-off needed to keep or tighten.
- **A3**: HC17 "minimum 100 doses per site-week if opened" simplified to
  `non-negative integer` only. A 100-dose minimum with opening indicators
  would add 60 Bool vars and ~120 implications; kept as v2 candidate.
- **A4**: Population counts are static for 10 weeks (no birth/death/in-migration).
- **A5**: No-show and wastage-per-vial factors are NOT modelled. Every
  administered dose is assumed to reach a person. Real-world wastage
  (~3-5%) should be applied as a post-hoc multiplier.
- **A6**: HC6/HC7 require the 2nd dose at the exact same (group, site) as
  the 1st dose. Real clinics allow site transfers — relaxing this is a
  straightforward v2 change (pair by (group) only, drop site index).

## 7. Solver Choice

OR-Tools **CP-SAT** (pure linear integer model — could also be solved with
PuLP + CBC/HiGHS, but CP-SAT parallelism and AddMaxEquality helpers make
scenario runs faster). Time limit 20s for feasibility phases, default for
optimization phases.
