"""Vaccine allocation v1 improve run: 4 scenarios on top of the full HC set.

Reuses build_model from staged_baseline with ALL 18 HCs, then replaces the
baseline (maximize people) objective with a weighted SC composite.

Scenarios:
  - balanced:     compromise for health department director
  - max_coverage: maximize total people vaccinated
  - elderly_first: heavy priority weight on G1/G2/G3
  - min_waste:    penalize unused supply (wasted doses)
"""

from __future__ import annotations

import json
from pathlib import Path

from ortools.sat.python import cp_model

from staged_baseline import (
    TIME_LIMIT,
    WEEKS,
    WORKERS,
    build_model,
    extract_solution,
    load_data,
    verify_all_hcs,
)

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

ALL_HCS = {f"HC{i}" for i in range(1, 19)}


def build_with_objective(data, weights):
    groups, sites, vaccines, supply = data
    m, vb = build_model(groups, sites, vaccines, supply, ALL_HCS)

    d1 = vb["dose1"]
    d2 = vb["dose2"]
    G = vb["G"]
    S = vb["S"]
    V = vb["V"]
    pop = {g["group_id"]: g["population"] for g in groups}
    rank = {g["group_id"]: g["priority_rank"] for g in groups}

    BIG_OBJ = 10_000_000  # domain upper bound for derived helper vars

    # SC1: total people vaccinated (maximize -> enter negated)
    total_people = sum(
        d1[g, s, w, "VP"] + d1[g, s, w, "VM"] + d1[g, s, w, "VJ"]
        for g in G for s in S for w in WEEKS
    )
    people_var = m.NewIntVar(0, sum(pop.values()), "people")
    m.Add(people_var == total_people)

    # SC2: priority-weighted people (integer weights 1/rank scaled x60)
    # G1:60, G2:30, G3:20, G4:15, G5:12
    weight_by_rank = {1: 60, 2: 30, 3: 20, 4: 15, 5: 12}
    prio_weighted = m.NewIntVar(0, BIG_OBJ, "prio_weighted")
    m.Add(
        prio_weighted
        == sum(
            weight_by_rank[rank[g]] * (d1[g, s, w, "VP"] + d1[g, s, w, "VM"] + d1[g, s, w, "VJ"])
            for g in G for s in S for w in WEEKS
        )
    )

    # SC3: wasted doses = (total supply) - (total used of that vaccine)
    waste_var = m.NewIntVar(0, BIG_OBJ, "waste")
    total_supply = sum(supply.get((w, v), 0) for w in WEEKS for v in V)
    used_all = sum(
        d1[g, s, w, v] + d2[g, s, w, v]
        for g in G for s in S for w in WEEKS for v in V
    )
    m.Add(waste_var == total_supply - used_all)

    # SC4: site balance. max_load - min_load across sites.
    site_load = {}
    max_sload = m.NewIntVar(0, BIG_OBJ, "max_sload")
    min_sload = m.NewIntVar(0, BIG_OBJ, "min_sload")
    for s in S:
        sl = m.NewIntVar(0, BIG_OBJ, f"sload_{s}")
        m.Add(
            sl
            == sum(
                d1[g, s, w, v] + d2[g, s, w, v]
                for g in G for w in WEEKS for v in V
            )
        )
        site_load[s] = sl
        m.Add(max_sload >= sl)
        m.Add(min_sload <= sl)
    sload_spread = m.NewIntVar(0, BIG_OBJ, "sload_spread")
    m.Add(sload_spread == max_sload - min_sload)

    # SC5: early completion bonus — reward early doses for high-priority groups.
    # Penalty = sum over (g, s, w, v) of week * weight[rank[g]] * dose1
    # Lower is better (earlier weeks).
    early_penalty = m.NewIntVar(0, BIG_OBJ, "early_penalty")
    m.Add(
        early_penalty
        == sum(
            weight_by_rank[rank[g]] * w * (
                d1[g, s, w, "VP"] + d1[g, s, w, "VM"] + d1[g, s, w, "VJ"]
            )
            for g in G for s in S for w in WEEKS
        )
    )

    # SC6: ultralow usage — total VP doses given
    ultralow_use = m.NewIntVar(0, BIG_OBJ, "ultralow_use")
    m.Add(
        ultralow_use
        == sum(
            d1[g, s, w, "VP"] + d2[g, s, w, "VP"]
            for g in G for s in S for w in WEEKS
        )
    )

    w_people = weights.get("people", 1)
    w_prio = weights.get("priority", 1)
    w_waste = weights.get("waste", 1)
    w_balance = weights.get("balance", 1)
    w_early = weights.get("early", 1)
    w_ultralow = weights.get("ultralow", 1)

    # We MAXIMIZE the composite: + people + prio  - waste - balance - early - ultralow
    # (early_penalty is a "bigger week" penalty; negating it rewards early)
    m.Maximize(
        w_people * people_var
        + w_prio * prio_weighted
        - w_waste * waste_var
        - w_balance * sload_spread
        - w_early * early_penalty
        - w_ultralow * ultralow_use
    )

    return m, vb, {
        "people": people_var,
        "prio_weighted": prio_weighted,
        "waste": waste_var,
        "sload_spread": sload_spread,
        "early_penalty": early_penalty,
        "ultralow_use": ultralow_use,
    }


def _group_coverage(sol, groups):
    G = [g["group_id"] for g in groups]
    pop = {g["group_id"]: g["population"] for g in groups}
    cov = {}
    for g in G:
        people = sum(
            v for (gg, s, w, vv), v in sol["dose1"].items() if gg == g
        )
        cov[g] = {
            "people": people,
            "population": pop[g],
            "coverage_pct": round(100 * people / pop[g], 2),
        }
    return cov


def run_scenario(name, weights, data):
    print(f"\n=== SCENARIO {name}  w={weights} ===")
    m, vb, metrics = build_with_objective(data, weights)
    n_vars = len(m.Proto().variables)
    print(f"  vars={n_vars}")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TIME_LIMIT
    solver.parameters.num_search_workers = WORKERS
    st = solver.Solve(m)
    sn = solver.StatusName(st)
    obj = solver.ObjectiveValue() if st in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None
    print(f"  status={sn}  obj={obj}")
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"scenario": name, "status": sn, "weights": weights}

    groups, sites, vaccines, supply = data
    sol = extract_solution(solver, vb)
    verify = verify_all_hcs(sol, groups, sites, vaccines, supply)
    n_ok = sum(1 for v in verify.values() if v["ok"])
    cov = _group_coverage(sol, groups)

    out = {
        "scenario": name,
        "status": sn,
        "weights": weights,
        "objective": obj,
        "hc_ok": n_ok,
        "hc_total": len(verify),
        "metrics": {
            "people": solver.Value(metrics["people"]),
            "prio_weighted": solver.Value(metrics["prio_weighted"]),
            "waste": solver.Value(metrics["waste"]),
            "sload_spread": solver.Value(metrics["sload_spread"]),
            "early_penalty": solver.Value(metrics["early_penalty"]),
            "ultralow_use": solver.Value(metrics["ultralow_use"]),
        },
        "coverage_by_group": cov,
        "vars": n_vars,
    }
    print(f"  people={out['metrics']['people']}  waste={out['metrics']['waste']}  "
          f"ultralow={out['metrics']['ultralow_use']}  hc_ok={n_ok}/{len(verify)}")
    for g, c in cov.items():
        print(f"    {g}: {c['people']}/{c['population']} ({c['coverage_pct']}%)")
    return out


def main():
    data = load_data()
    scenarios = {
        "balanced":     {"people":10, "priority":1, "waste":2, "balance":1, "early":0, "ultralow":0},
        "max_coverage": {"people":20, "priority":0, "waste":0, "balance":0, "early":0, "ultralow":0},
        "elderly_first":{"people":3,  "priority":8, "waste":1, "balance":0, "early":1, "ultralow":0},
        "min_waste":    {"people":5,  "priority":1, "waste":20,"balance":1, "early":0, "ultralow":0},
    }
    out = []
    for name, w in scenarios.items():
        out.append(run_scenario(name, w, data))

    with open(RESULTS / "improve_results.json", "w", encoding="utf-8") as f:
        json.dump({"scenarios": out}, f, indent=2, default=str)
    print(f"\nSaved {RESULTS / 'improve_results.json'}")


if __name__ == "__main__":
    main()
