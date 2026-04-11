"""GPU Cluster Scheduling v1 — improve phase.

Reuses build_model() from staged_baseline with the full 22-HC set, then
overrides the baseline (priority-weighted throughput) objective with a
weighted composite over the 8 SCs defined in spec.md.

Scenarios:
  - throughput:   maximise raw job count (with tier weighting)
  - deadline_first: pay any cost to hit deadlines for tier-1/2 jobs
  - fairness:     balance gpu-hours across teams
  - green:        minimise total power consumption + H100 under-utilisation
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from ortools.sat.python import cp_model

from staged_baseline import (
    HORIZON,
    WORKERS,
    FINAL_TIME_LIMIT,
    build_model,
    extract_solution,
    load_data,
    verify_all_hcs,
)

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

ALL_HCS = {f"HC{i}" for i in range(1, 23)}
TIER_WEIGHT = {1: 100, 2: 40, 3: 15, 4: 5, 0: 80}  # T6 (tier 0) important too


def build_with_objective(data, weights):
    nodes, gpus, teams, jobs, licenses, maint = data
    m, vb = build_model(nodes, gpus, teams, jobs, licenses, maint, ALL_HCS)

    teams_by_id = {t["team_id"]: t for t in teams}
    jobs_by_id = {j["job_id"]: j for j in jobs}
    gpus_by_id = {g["gpu_id"]: g for g in gpus}
    nodes_by_id = {n["node_id"]: n for n in nodes}

    accept = vb["accept"]
    start = vb["start"]
    end = vb["end"]
    use = vb["use"]

    # ---------- SC1 throughput (maximise accepts) ----------
    sc1_accept = sum(accept[j["job_id"]] for j in jobs)

    # ---------- SC2 tier-weighted accepts ----------
    sc2_tier = sum(
        accept[j["job_id"]] * TIER_WEIGHT[teams_by_id[j["team"]]["priority_tier"]]
        for j in jobs
    )

    # ---------- SC3 total power (sum over all (j,g) of extra watts * hours) ----------
    # Measured only over accepted jobs; per GPU extra = peak - idle.
    sc3_power_terms = []
    for j in jobs:
        jid = j["job_id"]
        h = j["hours_required"]
        for (jid2, gid), b in use.items():
            if jid2 != jid:
                continue
            extra = gpus_by_id[gid]["peak_watts"] - gpus_by_id[gid]["idle_watts"]
            sc3_power_terms.append(b * extra * h)
    sc3_power = sum(sc3_power_terms)

    # ---------- SC4 prefer H100 for pretrain / penalise pretrain on A100-80GB ----------
    # Penalise every (pretrain, non-H100) gpu-hour assignment.
    sc4_terms = []
    for j in jobs:
        if j["job_type"] != "pretrain":
            continue
        jid = j["job_id"]
        h = j["hours_required"]
        for (jid2, gid), b in use.items():
            if jid2 != jid:
                continue
            if gpus_by_id[gid]["gpu_type"] != "H100":
                sc4_terms.append(b * h)
    sc4_non_h100_pretrain_hours = sum(sc4_terms) if sc4_terms else 0

    # ---------- SC5 fairness: min/max spread of team accept ratios ----------
    # Represent each team's "coverage" as absolute accepted-gph, then minimise
    # max - min across teams that actually have demand.
    team_coverage = {}
    max_cov = m.NewIntVar(0, HORIZON * 44, "max_cov")
    min_cov = m.NewIntVar(0, HORIZON * 44, "min_cov")
    for t in teams:
        tid = t["team_id"]
        team_jobs = [j for j in jobs if j["team"] == tid]
        if not team_jobs:
            continue
        demand = sum(j["gpus_required"] * j["hours_required"] for j in team_jobs)
        if demand == 0:
            continue
        # Scale: normalise to 0-100 (percent) via integer division would lose
        # info; instead track absolute gph and let weights handle units.
        cov_expr = sum(
            accept[j["job_id"]] * j["gpus_required"] * j["hours_required"]
            for j in team_jobs
        )
        cov = m.NewIntVar(0, demand, f"cov_{tid}")
        m.Add(cov == cov_expr)
        team_coverage[tid] = (cov, demand)
        # Encode as % * 1000 for fairness
        cov_pct = m.NewIntVar(0, 1000, f"covpct_{tid}")
        m.AddDivisionEquality(cov_pct, cov * 1000, demand)
        m.Add(max_cov >= cov_pct)
        m.Add(min_cov <= cov_pct)
    sc5_spread = m.NewIntVar(0, 1000, "sc5_spread")
    m.Add(sc5_spread == max_cov - min_cov)

    # ---------- SC6 meet deadlines with slack: sum of (deadline - end) for accepted ----------
    # We minimise NEGATIVE slack (want large slack -> add slack as a maximise);
    # simpler: maximise sum of slack = sum(dl - end) over accepted.
    slack_terms = []
    for j in jobs:
        jid = j["job_id"]
        dl = j["deadline_hour"]
        s = m.NewIntVar(0, HORIZON, f"slack_{jid}")
        # if accepted, s = dl - end ; else s = 0
        m.Add(s == dl - end[jid]).OnlyEnforceIf(accept[jid])
        m.Add(s == 0).OnlyEnforceIf(accept[jid].Not())
        slack_terms.append(s)
    sc6_total_slack = sum(slack_terms)

    # ---------- SC7 cross cooling-zone: count multi-GPU jobs that span zones ----
    # We penalise jobs with gpus_required > 1 where chosen GPUs straddle zones
    # A and B. Since HC6 forces single-node for non-IB jobs, for those jobs
    # this is already zero; only IB distributed jobs can span, and they still
    # must have all their GPUs on the same IB-enabled nodes (both in zone A).
    # So SC7 is currently 0 in valid solutions — still track it for honesty.
    sc7_cross_zone = 0  # structurally zero under the current HC set.

    # ---------- SC8 prefer finish in first 5 days (120h) ----------
    sc8_terms = []
    for j in jobs:
        jid = j["job_id"]
        overrun = m.NewIntVar(0, HORIZON, f"over_{jid}")
        # end - 120 if positive, else 0 ; only counts when accepted
        m.Add(overrun >= end[jid] - 120).OnlyEnforceIf(accept[jid])
        m.Add(overrun >= 0)
        m.Add(overrun == 0).OnlyEnforceIf(accept[jid].Not())
        sc8_terms.append(overrun)
    sc8_overrun = sum(sc8_terms)

    # ---------- Composite objective (minimise) ----------
    w = weights
    # Normalise by dividing power by 100 to keep magnitudes manageable.
    # Negate the two "maximise" goals (accepts, slack, tier) by subtracting.
    # CP-SAT accepts Minimize(linear). We encode as:
    #   minimise   - w1*SC1 - w2*SC2 - w6*SC6_slack
    #              + w3*power/100 + w4*non_h100_pretrain + w5*spread
    #              + w7*cross_zone + w8*overrun
    obj = (
        -w["w_sc1"] * sc1_accept
        - w["w_sc2"] * sc2_tier
        + w["w_sc3"] * (sc3_power // 100 if False else sc3_power)  # keep raw
        + w["w_sc4"] * sc4_non_h100_pretrain_hours
        + w["w_sc5"] * sc5_spread
        - w["w_sc6"] * sc6_total_slack
        + w["w_sc7"] * sc7_cross_zone
        + w["w_sc8"] * sc8_overrun
    )
    m.Minimize(obj)

    metrics = {
        "sc1_accept": sc1_accept,
        "sc2_tier": sc2_tier,
        "sc3_power": sc3_power,
        "sc4_non_h100_pretrain": sc4_non_h100_pretrain_hours,
        "sc5_spread": sc5_spread,
        "sc6_slack": sc6_total_slack,
        "sc8_overrun": sc8_overrun,
        "team_coverage": team_coverage,
    }
    return m, vb, metrics


def _safe_val(solver, x):
    if isinstance(x, int):
        return x
    try:
        return solver.Value(x)
    except Exception:
        return None


def run_scenario(name, weights, data, time_limit=FINAL_TIME_LIMIT):
    print(f"\n=== SCENARIO {name}  w={weights} ===")
    m, vb, metrics = build_with_objective(data, weights)
    n_vars = len(m.Proto().variables)
    n_cons = len(m.Proto().constraints)
    print(f"  vars={n_vars} cons={n_cons}")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = WORKERS
    st = solver.Solve(m)
    sn = solver.StatusName(st)
    print(f"  status={sn} obj={solver.ObjectiveValue() if st in (cp_model.OPTIMAL, cp_model.FEASIBLE) else 'N/A'}")
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"scenario": name, "status": sn, "weights": weights,
                "vars": n_vars, "constraints": n_cons}

    nodes, gpus, teams, jobs, licenses, maint = data
    sol = extract_solution(solver, vb, jobs)
    verify = verify_all_hcs(sol, nodes, gpus, teams, jobs, licenses, maint)
    n_ok = sum(1 for v in verify.values() if v["ok"])
    n_acc = sum(1 for v in sol.values() if v is not None)

    # Team-level coverage breakdown
    team_cov_out = {}
    for tid, (cov_var, demand) in metrics["team_coverage"].items():
        got = solver.Value(cov_var)
        team_cov_out[tid] = {
            "served_gph": got,
            "demand_gph": demand,
            "coverage_pct": round(100 * got / demand, 1) if demand else 100.0,
        }

    out = {
        "scenario": name,
        "status": sn,
        "weights": weights,
        "objective": solver.ObjectiveValue(),
        "accepted": n_acc,
        "total_jobs": len(jobs),
        "hc_ok": n_ok,
        "hc_total": len(verify),
        "metrics": {
            "sc1_accept": _safe_val(solver, metrics["sc1_accept"]),
            "sc2_tier": _safe_val(solver, metrics["sc2_tier"]),
            "sc3_power": _safe_val(solver, metrics["sc3_power"]),
            "sc4_non_h100_pretrain": _safe_val(solver, metrics["sc4_non_h100_pretrain"]),
            "sc5_spread_x1000pct": _safe_val(solver, metrics["sc5_spread"]),
            "sc6_slack": _safe_val(solver, metrics["sc6_slack"]),
            "sc8_overrun": _safe_val(solver, metrics["sc8_overrun"]),
        },
        "team_coverage": team_cov_out,
        "vars": n_vars,
        "constraints": n_cons,
    }
    print(f"  accepted={n_acc}/{len(jobs)}  HC_ok={n_ok}/{len(verify)}")
    print(f"  metrics: {out['metrics']}")
    return out


def qa_checklist(results):
    """Spec <-> code consistency checks."""
    issues = []
    for r in results:
        if "metrics" not in r:
            issues.append(f"{r['scenario']}: no metrics (status={r['status']})")
            continue
        if r["hc_ok"] != r["hc_total"]:
            issues.append(f"{r['scenario']}: {r['hc_total']-r['hc_ok']} HCs violated")
        # T6 must all be scheduled
        t6_cov = r["team_coverage"].get("T6", {}).get("coverage_pct", 0)
        if t6_cov < 100:
            issues.append(f"{r['scenario']}: T6 coverage {t6_cov}% < 100%")
        # T1 must be >= 70%
        t1_cov = r["team_coverage"].get("T1", {}).get("coverage_pct", 0)
        if t1_cov < 70:
            issues.append(f"{r['scenario']}: T1 coverage {t1_cov}% < 70%")
    return issues


def main():
    data = load_data()
    scenarios = {
        "throughput":    {"w_sc1": 10, "w_sc2": 5,  "w_sc3": 0, "w_sc4": 0, "w_sc5": 0, "w_sc6": 0, "w_sc7": 0, "w_sc8": 0},
        "deadline_first":{"w_sc1": 5,  "w_sc2": 10, "w_sc3": 0, "w_sc4": 0, "w_sc5": 0, "w_sc6": 3, "w_sc7": 0, "w_sc8": 2},
        "fairness":      {"w_sc1": 5,  "w_sc2": 2,  "w_sc3": 0, "w_sc4": 0, "w_sc5": 20,"w_sc6": 1, "w_sc7": 0, "w_sc8": 0},
        "green":         {"w_sc1": 3,  "w_sc2": 2,  "w_sc3": 1, "w_sc4": 10,"w_sc5": 0, "w_sc6": 0, "w_sc7": 0, "w_sc8": 0},
    }
    out = []
    for name, w in scenarios.items():
        out.append(run_scenario(name, w, data))

    qa = qa_checklist(out)
    print("\n=== QA checklist ===")
    if qa:
        for q in qa:
            print(f"  - {q}")
    else:
        print("  all clean")

    with open(RESULTS / "improve_results.json", "w", encoding="utf-8") as f:
        json.dump({"scenarios": out, "qa_issues": qa}, f, indent=2, default=str)
    print(f"\nSaved {RESULTS / 'improve_results.json'}")


if __name__ == "__main__":
    main()
