"""FJSP v1 improve run: 4 scenarios on top of the full HC set.

Reuses build_model from staged_baseline with ALL 20 HCs, then replaces the
baseline makespan-only objective with a weighted SC composite.

Scenarios:
  - balanced:    compromise profile recommended to manufacturing director
  - throughput:  all-out minimise makespan
  - on_time:     minimise tardiness, respect priorities
  - smooth:      balance machine / operator loads, minimise setup
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from ortools.sat.python import cp_model

from staged_baseline import (
    DAY_LEN,
    DAYS,
    HORIZON,
    TIME_LIMIT,
    WORKERS,
    build_model,
    extract_solution,
    load_data,
    verify_all_hcs,
)

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

ALL_HCS = {f"HC{i}" for i in range(1, 21)}


def build_with_objective(data, weights):
    machines, operators, jobs, operations, tools = data
    m, vb = build_model(machines, operators, jobs, operations, tools, ALL_HCS)

    # Drop the baseline (makespan-only) objective by adding an overriding one.
    # CP-SAT's last Minimize/Maximize wins.

    # SC1: makespan already in vb
    makespan = vb["makespan"]

    # SC2: total tardiness
    tardy_vars = []
    job_end = {}
    for j in jobs:
        # job end = max over its ops of op_end
        je = m.NewIntVar(0, HORIZON, f"je_{j['job_id']}")
        for op in operations:
            if op["job_id"] == j["job_id"]:
                m.Add(je >= vb["op_end"][op["op_id"]])
        job_end[j["job_id"]] = je
        due = j["due_day"] * DAY_LEN
        tv = m.NewIntVar(0, HORIZON, f"tardy_{j['job_id']}")
        m.Add(tv >= je - due)
        m.Add(tv >= 0)
        # priority weight
        w = {"urgent": 20, "high": 10, "normal": 3, "low": 1}[j["priority"]]
        tardy_vars.append(tv * w)
    total_tardiness = sum(tardy_vars)

    # SC3: machine utilisation balance -- min/max spread of machine loads
    mach_load = {}
    max_mload = m.NewIntVar(0, HORIZON, "max_mload")
    min_mload = m.NewIntVar(0, HORIZON, "min_mload")
    for mm in machines:
        contribs = []
        for op in operations:
            key = (op["op_id"], mm["machine_id"])
            if key not in vb["pres"]:
                continue
            contribs.append(vb["pres"][key] * op["duration_minutes"])
        ml = m.NewIntVar(0, HORIZON, f"mload_{mm['machine_id']}")
        if contribs:
            m.Add(ml == sum(contribs))
        else:
            m.Add(ml == 0)
        m.Add(max_mload >= ml)
        m.Add(min_mload <= ml)
        mach_load[mm["machine_id"]] = ml
    mload_spread = m.NewIntVar(0, HORIZON, "mload_spread")
    m.Add(mload_spread == max_mload - min_mload)

    # SC4: setup-time proxy = number of (machine, day, op_type) bands used.
    # Reuse HC20's implicit 'type_used' structure by rebuilding a cheap proxy:
    # for each (machine, day), count distinct op_types (at most 2 under HC20).
    # We approximate SC4 by counting the total of those 2-type-flags — higher
    # == more setup-prone days.
    # To keep the model lean we recreate per-(m,d,type) boolean here.
    setup_indicators = []
    for mm in machines:
        for d in DAYS:
            for otype in ("lathe", "milling", "drilling", "grinding", "cnc"):
                ind = m.NewBoolVar(f"sc4_{mm['machine_id']}_{d}_{otype}")
                contribs = []
                for op in operations:
                    if op["op_type"] != otype:
                        continue
                    key = (op["op_id"], mm["machine_id"])
                    if key not in vb["pres"]:
                        continue
                    # Fully reify "op runs on (mm, d)": on iff pres AND
                    # start in [lo, hi). We use auxiliary ge/lt bools.
                    lo = (d - 1) * DAY_LEN
                    hi = d * DAY_LEN
                    on = m.NewBoolVar(f"sc4on_{op['op_id']}_{mm['machine_id']}_{d}")
                    ge = m.NewBoolVar(f"sc4ge_{op['op_id']}_{mm['machine_id']}_{d}")
                    lt = m.NewBoolVar(f"sc4lt_{op['op_id']}_{mm['machine_id']}_{d}")
                    m.Add(vb["starts"][key] >= lo).OnlyEnforceIf(ge)
                    m.Add(vb["starts"][key] < lo).OnlyEnforceIf(ge.Not())
                    m.Add(vb["starts"][key] < hi).OnlyEnforceIf(lt)
                    m.Add(vb["starts"][key] >= hi).OnlyEnforceIf(lt.Not())
                    # on == pres AND ge AND lt
                    m.AddBoolAnd([vb["pres"][key], ge, lt]).OnlyEnforceIf(on)
                    m.AddBoolOr([vb["pres"][key].Not(), ge.Not(), lt.Not()]).OnlyEnforceIf(on.Not())
                    contribs.append(on)
                if contribs:
                    for c in contribs:
                        m.AddImplication(c, ind)
                    m.AddBoolOr(contribs + [ind.Not()])
                else:
                    m.Add(ind == 0)
                setup_indicators.append(ind)
    total_setup = sum(setup_indicators)

    # SC5: operator load balance. op_op might be empty if HC9 not active, but
    # we run with ALL_HCS so it exists.
    max_oload = m.NewIntVar(0, HORIZON, "max_oload")
    min_oload = m.NewIntVar(0, HORIZON, "min_oload")
    for o in operators:
        contribs = []
        for op in operations:
            k = (op["op_id"], o["operator_id"])
            if k not in vb["op_op"]:
                continue
            contribs.append(vb["op_op"][k] * op["duration_minutes"])
        ol = m.NewIntVar(0, HORIZON, f"oload_{o['operator_id']}")
        if contribs:
            m.Add(ol == sum(contribs))
        else:
            m.Add(ol == 0)
        m.Add(max_oload >= ol)
        m.Add(min_oload <= ol)
    oload_spread = m.NewIntVar(0, HORIZON, "oload_spread")
    m.Add(oload_spread == max_oload - min_oload)

    # SC6: priority early completion bonus (reward urgent/high jobs finishing early)
    prio_penalty_terms = []
    for j in jobs:
        w = {"urgent": 10, "high": 5, "normal": 1, "low": 0}[j["priority"]]
        if w == 0:
            continue
        prio_penalty_terms.append(w * job_end[j["job_id"]])
    prio_penalty = sum(prio_penalty_terms)

    w1 = weights.get("makespan", 1)
    w2 = weights.get("tardiness", 1)
    w3 = weights.get("m_balance", 1)
    w4 = weights.get("setup", 1)
    w5 = weights.get("o_balance", 1)
    w6 = weights.get("prio_early", 1)

    # All minimised. The old (baseline) Minimize(makespan) is superseded by
    # the last Minimize() below.
    m.Minimize(
        w1 * makespan
        + w2 * total_tardiness
        + w3 * mload_spread
        + w4 * total_setup
        + w5 * oload_spread
        + w6 * prio_penalty
    )

    return m, vb, {
        "makespan": makespan,
        "total_tardiness": total_tardiness,
        "mload_spread": mload_spread,
        "total_setup": total_setup,
        "oload_spread": oload_spread,
        "prio_penalty": prio_penalty,
    }


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
    print(f"  status={sn} obj={solver.ObjectiveValue() if st in (cp_model.OPTIMAL, cp_model.FEASIBLE) else 'N/A'}")
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"scenario": name, "status": sn, "weights": weights}

    machines, operators, jobs, operations, tools = data
    sol = extract_solution(solver, vb, machines, operators, operations)
    verify = verify_all_hcs(sol, machines, operators, jobs, operations, tools)
    n_ok = sum(1 for v in verify.values() if v["ok"])

    out = {
        "scenario": name,
        "status": sn,
        "weights": weights,
        "objective": solver.ObjectiveValue(),
        "hc_ok": n_ok,
        "hc_total": len(verify),
        "metrics": {
            "makespan": solver.Value(metrics["makespan"]),
            "total_tardiness": solver.Value(metrics["total_tardiness"]),
            "mload_spread": solver.Value(metrics["mload_spread"]),
            "total_setup": solver.Value(metrics["total_setup"]),
            "oload_spread": solver.Value(metrics["oload_spread"]),
            "prio_penalty": solver.Value(metrics["prio_penalty"]),
        },
        "vars": n_vars,
    }
    print(f"  metrics: {out['metrics']}")
    print(f"  verify: {n_ok}/{len(verify)} HCs ok")
    return out


def main():
    data = load_data()
    scenarios = {
        "balanced":   {"makespan":3, "tardiness":5, "m_balance":1, "setup":1, "o_balance":1, "prio_early":1},
        "throughput": {"makespan":10,"tardiness":1, "m_balance":0, "setup":0, "o_balance":0, "prio_early":0},
        "on_time":    {"makespan":1, "tardiness":20,"m_balance":0, "setup":1, "o_balance":0, "prio_early":3},
        "smooth":     {"makespan":1, "tardiness":2, "m_balance":5, "setup":3, "o_balance":5, "prio_early":1},
    }
    out = []
    for name, w in scenarios.items():
        out.append(run_scenario(name, w, data))

    with open(RESULTS / "improve_results.json", "w", encoding="utf-8") as f:
        json.dump({"scenarios": out}, f, indent=2, default=str)
    print(f"\nSaved {RESULTS / 'improve_results.json'}")


if __name__ == "__main__":
    main()
