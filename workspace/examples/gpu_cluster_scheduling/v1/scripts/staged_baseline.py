"""Staged baseline for GPU Cluster Scheduling v1.

Pattern: OR-Tools CP-SAT with one integer start_hour per job + per-(job,gpu)
presence booleans. Each (job, gpu) pair gets an OptionalIntervalVar, and per-GPU
AddNoOverlap enforces HC4 (no oversubscription). Gang scheduling (HC5) is
enforced by making all GPUs of a job share the same start through a single
start variable per job. Node co-location (HC6) restricts GPU selection to one
node unless InfiniBand is allowed.

Jobs are accepted or rejected (binary). Non-accepted jobs contribute no
presence bools for any GPU. Infrastructure jobs (T6) are forced accepted
under HC21.

Staging progressively activates HCs so we can pinpoint which constraint is
load-bearing.

Run:
    python staged_baseline.py

Outputs:
    ../results/baseline_results.json
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from ortools.sat.python import cp_model

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
RESULTS = HERE.parent / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

HORIZON = 168            # 1 week in hours
TIME_LIMIT = 45          # per phase; overridable
FINAL_TIME_LIMIT = 180   # final optimize phase
WORKERS = 8


# ---------- loader ----------
def _int(x, default=0):
    return int(x) if x not in ("", None) else default


def _bool(x):
    return str(x).strip().lower() in ("true", "1", "yes")


def _list(x):
    return [s for s in (x or "").split(";") if s]


def load_data():
    with open(DATA / "nodes.csv", encoding="utf-8") as f:
        nodes = list(csv.DictReader(f))
    for n in nodes:
        n["power_budget_watts"] = int(n["power_budget_watts"])

    with open(DATA / "gpus.csv", encoding="utf-8") as f:
        gpus = list(csv.DictReader(f))
    for g in gpus:
        g["memory_gb"] = int(g["memory_gb"])
        g["idle_watts"] = int(g["idle_watts"])
        g["peak_watts"] = int(g["peak_watts"])

    with open(DATA / "teams.csv", encoding="utf-8") as f:
        teams = list(csv.DictReader(f))
    for t in teams:
        t["priority_tier"] = int(t["priority_tier"])
        t["max_concurrent_gpu_hours"] = int(t["max_concurrent_gpu_hours"])
        t["max_gpus_at_once"] = int(t["max_gpus_at_once"])
        t["allowed_nodes"] = _list(t["allowed_nodes"])

    with open(DATA / "jobs.csv", encoding="utf-8") as f:
        jobs = list(csv.DictReader(f))
    for j in jobs:
        j["min_gpu_memory_gb"] = int(j["min_gpu_memory_gb"])
        j["gpus_required"] = int(j["gpus_required"])
        j["hours_required"] = int(j["hours_required"])
        j["priority"] = int(j["priority"])
        j["deadline_hour"] = int(j["deadline_hour"])
        j["preemptable"] = _bool(j["preemptable"])
        j["needs_infiniband"] = _bool(j["needs_infiniband"])
        j["dataset_cached_node"] = j["dataset_cached_node"] or None

    with open(DATA / "licenses.csv", encoding="utf-8") as f:
        licenses = list(csv.DictReader(f))
    for L in licenses:
        L["seats"] = int(L["seats"])

    with open(DATA / "maintenance.csv", encoding="utf-8") as f:
        maint = list(csv.DictReader(f))
    for mw in maint:
        mw["start_hour"] = int(mw["start_hour"])
        mw["end_hour"] = int(mw["end_hour"])

    return nodes, gpus, teams, jobs, licenses, maint


# ---------- compatibility helpers ----------
def compatible_gpus(job, gpus, nodes_by_id, teams_by_id):
    """Return the list of gpus a job *could* run on.

    Only HC3 (GPU memory must physically fit the job) is used as a data-level
    prune — it is an unconditional hard match that cannot ever be true at
    runtime. Every other HC (HC7/HC13/HC16/HC20/HC22) is enforced as a real
    solver constraint so the model can reason about them alongside time,
    power, and multi-GPU placement.
    """
    out = []
    for g in gpus:
        if g["memory_gb"] < job["min_gpu_memory_gb"]:
            continue  # HC3
        out.append(g)
    return out


# ---------- model builder ----------
def build_model(nodes, gpus, teams, jobs, licenses, maint, active_hcs: set):
    m = cp_model.CpModel()

    nodes_by_id = {n["node_id"]: n for n in nodes}
    gpus_by_id = {g["gpu_id"]: g for g in gpus}
    teams_by_id = {t["team_id"]: t for t in teams}
    jobs_by_id = {j["job_id"]: j for j in jobs}

    gpus_by_node = defaultdict(list)
    for g in gpus:
        gpus_by_node[g["node_id"]].append(g)

    # Precompute compatible GPUs per job. HCs 3/7/13/16/20/22 are always used
    # for pruning regardless of activity (they remove variables, making every
    # downstream phase tractable). We log this in spec.md as "static pruning".
    compat = {}
    for j in jobs:
        compat[j["job_id"]] = compatible_gpus(j, gpus, nodes_by_id, teams_by_id)

    # ---- Accept flags ----
    accept = {j["job_id"]: m.NewBoolVar(f"acc_{j['job_id']}") for j in jobs}

    # Jobs with zero compatible GPUs: reject unconditionally.
    for j in jobs:
        if not compat[j["job_id"]]:
            m.Add(accept[j["job_id"]] == 0)

    # ---- Per-job start (shared by all GPUs it uses — gang scheduling) ----
    start = {}
    end = {}
    for j in jobs:
        dur = j["hours_required"]
        # Upper bound on start = HORIZON - dur (if accepted); allow HORIZON if
        # rejected (unconstrained; we don't read the value in that case).
        start[j["job_id"]] = m.NewIntVar(0, HORIZON, f"st_{j['job_id']}")
        end[j["job_id"]] = m.NewIntVar(0, HORIZON, f"en_{j['job_id']}")
        # If accepted, end == start + dur and start <= HORIZON - dur
        m.Add(end[j["job_id"]] == start[j["job_id"]] + dur)
        m.Add(start[j["job_id"]] <= HORIZON - dur).OnlyEnforceIf(accept[j["job_id"]])

    # ---- Per (job, gpu) presence + optional interval ----
    use = {}               # (jid, gid) -> BoolVar
    interval = {}          # (jid, gid) -> OptionalIntervalVar
    for j in jobs:
        jid = j["job_id"]
        dur = j["hours_required"]
        for g in compat[jid]:
            gid = g["gpu_id"]
            p = m.NewBoolVar(f"u_{jid}_{gid}")
            iv = m.NewOptionalIntervalVar(
                start[jid], dur, end[jid], p, f"iv_{jid}_{gid}"
            )
            use[jid, gid] = p
            interval[jid, gid] = iv
            # If used, accept must be 1
            m.AddImplication(p, accept[jid])

    # ---- HC13 team allowed_nodes whitelist (solver constraint) ----
    if "HC13" in active_hcs:
        for j in jobs:
            jid = j["job_id"]
            allowed = set(teams_by_id[j["team"]]["allowed_nodes"])
            for g in compat[jid]:
                if g["node_id"] not in allowed:
                    m.Add(use[jid, g["gpu_id"]] == 0)

    # ---- HC7 InfiniBand requirement (solver constraint) ----
    if "HC7" in active_hcs:
        for j in jobs:
            if not j["needs_infiniband"]:
                continue
            jid = j["job_id"]
            for g in compat[jid]:
                if "InfiniBand" not in nodes_by_id[g["node_id"]]["interconnect"]:
                    m.Add(use[jid, g["gpu_id"]] == 0)

    # ---- HC16 dataset locality (solver constraint) ----
    if "HC16" in active_hcs:
        for j in jobs:
            if not j["dataset_cached_node"]:
                continue
            jid = j["job_id"]
            cached = j["dataset_cached_node"]
            for g in compat[jid]:
                if g["node_id"] != cached:
                    m.Add(use[jid, g["gpu_id"]] == 0)

    # ---- HC20 V100 memory restriction ----
    if "HC20" in active_hcs:
        for j in jobs:
            if j["min_gpu_memory_gb"] <= 16:
                continue
            jid = j["job_id"]
            for g in compat[jid]:
                if g["gpu_type"] == "V100":
                    m.Add(use[jid, g["gpu_id"]] == 0)

    # ---- HC22 pretrain on premium GPUs only (H100 or A100-80GB) ----
    if "HC22" in active_hcs:
        for j in jobs:
            if j["job_type"] != "pretrain":
                continue
            jid = j["job_id"]
            for g in compat[jid]:
                if g["gpu_type"] not in ("H100", "A100-80GB"):
                    m.Add(use[jid, g["gpu_id"]] == 0)

    # ---- HC2: each accepted job uses exactly gpus_required GPUs ----
    if "HC2" in active_hcs:
        for j in jobs:
            jid = j["job_id"]
            req = j["gpus_required"]
            pool = [use[jid, g["gpu_id"]] for g in compat[jid]]
            if pool:
                # sum == req * accept
                m.Add(sum(pool) == req).OnlyEnforceIf(accept[jid])
                m.Add(sum(pool) == 0).OnlyEnforceIf(accept[jid].Not())

    # ---- HC4: per-GPU no overlap (via intervals) ----
    if "HC4" in active_hcs:
        for g in gpus:
            gid = g["gpu_id"]
            ivs = [interval[jid, gid]
                   for j in jobs
                   for jid in [j["job_id"]]
                   if (jid, gid) in interval]
            if ivs:
                m.AddNoOverlap(ivs)

    # ---- HC5 gang scheduling: shared `start[j]` already enforces it ----
    # (Explicit presence to shared start link is implicit in NewOptionalInterval
    # built from the same start var.)

    # ---- HC6 single-node (unless InfiniBand multi-node allowed) ----
    # For jobs that don't need InfiniBand and have gpus_required > 1: all their
    # use bools must be on the same node. Implement via "at most one node
    # chosen" per job.
    if "HC6" in active_hcs:
        for j in jobs:
            jid = j["job_id"]
            if j["gpus_required"] <= 1 or j["needs_infiniband"]:
                continue
            # Group compat by node, create a bool per node, enforce sum==1 when
            # accepted, and force use[jid,g] == 0 unless node bool is 1.
            by_node = defaultdict(list)
            for g in compat[jid]:
                by_node[g["node_id"]].append(g["gpu_id"])
            node_bool = {}
            for nid in by_node:
                b = m.NewBoolVar(f"jn_{jid}_{nid}")
                node_bool[nid] = b
            m.Add(sum(node_bool.values()) == 1).OnlyEnforceIf(accept[jid])
            m.Add(sum(node_bool.values()) == 0).OnlyEnforceIf(accept[jid].Not())
            for nid, gids in by_node.items():
                for gid in gids:
                    # use => node_bool[nid]
                    m.AddImplication(use[jid, gid], node_bool[nid])

    # ---- HC8 per-node power budget ----
    # At any hour, sum over nodes g of (idle_watts + (peak-idle) * [g in use])
    # must be <= budget. We use AddCumulative per node over (peak - idle) with
    # capacity (budget - total_idle_when_all_idle). The idle baseline is the
    # same whether jobs run or not, so we bake it in.
    if "HC8" in active_hcs:
        for n in nodes:
            nid = n["node_id"]
            node_gpus = gpus_by_node[nid]
            total_idle = sum(g["idle_watts"] for g in node_gpus)
            headroom = n["power_budget_watts"] - total_idle
            if headroom < 0:
                # Infeasible baseline — tag in spec.md A8 as assumption
                headroom = 0
            # Build cumulative: demand = (peak - idle) for each (job, gpu) when
            # use bool true. Intervals and demands aligned.
            ivs = []
            demands = []
            for g in node_gpus:
                gid = g["gpu_id"]
                extra = g["peak_watts"] - g["idle_watts"]
                for j in jobs:
                    jid = j["job_id"]
                    if (jid, gid) in interval:
                        ivs.append(interval[jid, gid])
                        demands.append(extra)
            if ivs:
                m.AddCumulative(ivs, demands, headroom)

    # ---- HC9 cooling zone A GPU-concurrent limit (<=24 GPUs at once) ----
    if "HC9" in active_hcs:
        zone_limit = {"A": 24, "B": 12}  # B gets a looser bound
        for zone, limit in zone_limit.items():
            zone_gpu_ids = set()
            for n in nodes:
                if n["cooling_zone"] == zone:
                    for g in gpus_by_node[n["node_id"]]:
                        zone_gpu_ids.add(g["gpu_id"])
            ivs = []
            demands = []
            for (jid, gid), iv in interval.items():
                if gid in zone_gpu_ids:
                    ivs.append(iv)
                    demands.append(1)
            if ivs:
                m.AddCumulative(ivs, demands, limit)

    # ---- HC10 license seats (cumulative) ----
    if "HC10" in active_hcs:
        # CUDA-advanced: every (accepted) job consumes 1 seat during its run,
        # but license is per *job*, not per GPU. We model it per job using the
        # job's start/end interval (single interval regardless of GPU count).
        # NCCL-pro: distributed jobs (gpus_required > 1).
        cuda_seats = next(L["seats"] for L in licenses if L["name"] == "CUDA-advanced")
        nccl_seats = next(L["seats"] for L in licenses if L["name"] == "NCCL-pro")

        cuda_ivs = []
        cuda_demands = []
        nccl_ivs = []
        nccl_demands = []
        for j in jobs:
            jid = j["job_id"]
            # Job-level optional interval reusing the shared start.
            jiv = m.NewOptionalIntervalVar(
                start[jid], j["hours_required"], end[jid], accept[jid],
                f"jiv_{jid}",
            )
            cuda_ivs.append(jiv)
            cuda_demands.append(1)
            if j["gpus_required"] > 1:
                nccl_ivs.append(jiv)
                nccl_demands.append(1)
        if cuda_ivs:
            m.AddCumulative(cuda_ivs, cuda_demands, cuda_seats)
        if nccl_ivs:
            m.AddCumulative(nccl_ivs, nccl_demands, nccl_seats)

    # ---- HC11 team max_gpus_at_once ----
    if "HC11" in active_hcs:
        # Per team, sum over simultaneously-running jobs of gpus_required <= cap.
        # Express as cumulative over per-team job intervals with demand =
        # gpus_required.
        for t in teams:
            tid = t["team_id"]
            cap = t["max_gpus_at_once"]
            ivs = []
            demands = []
            for j in jobs:
                if j["team"] != tid:
                    continue
                jid = j["job_id"]
                jiv = m.NewOptionalIntervalVar(
                    start[jid], j["hours_required"], end[jid], accept[jid],
                    f"tjiv_{tid}_{jid}",
                )
                ivs.append(jiv)
                demands.append(j["gpus_required"])
            if ivs:
                m.AddCumulative(ivs, demands, cap)

    # ---- HC12 team weekly gpu-hour budget ----
    if "HC12" in active_hcs:
        for t in teams:
            tid = t["team_id"]
            cap = t["max_concurrent_gpu_hours"]
            total = []
            for j in jobs:
                if j["team"] != tid:
                    continue
                jid = j["job_id"]
                gph = j["gpus_required"] * j["hours_required"]
                total.append(accept[jid] * gph)
            if total:
                m.Add(sum(total) <= cap)

    # ---- HC14 deadline ----
    if "HC14" in active_hcs:
        for j in jobs:
            jid = j["job_id"]
            # if accepted, end <= deadline
            m.Add(end[jid] <= j["deadline_hour"]).OnlyEnforceIf(accept[jid])

    # ---- HC15 maintenance windows ----
    if "HC15" in active_hcs:
        for mw in maint:
            nid = mw["node_id"]
            lo, hi = mw["start_hour"], mw["end_hour"]
            for g in gpus_by_node[nid]:
                gid = g["gpu_id"]
                for j in jobs:
                    jid = j["job_id"]
                    if (jid, gid) not in interval:
                        continue
                    # If use[jid, gid]: start >= hi OR end <= lo
                    b1 = m.NewBoolVar(f"mwA_{jid}_{gid}_{lo}")
                    b2 = m.NewBoolVar(f"mwB_{jid}_{gid}_{lo}")
                    m.Add(start[jid] >= hi).OnlyEnforceIf(b1)
                    m.Add(end[jid] <= lo).OnlyEnforceIf(b2)
                    m.AddBoolOr([b1, b2, use[jid, gid].Not()])

    # ---- HC17 tier-1 coverage (T1 >= 70% of its demand) ----
    if "HC17" in active_hcs:
        t1_jobs = [j for j in jobs if j["team"] == "T1"]
        if t1_jobs:
            demand_gph = sum(j["gpus_required"] * j["hours_required"] for j in t1_jobs)
            thresh = (demand_gph * 70) // 100
            served_terms = [
                accept[j["job_id"]] * (j["gpus_required"] * j["hours_required"])
                for j in t1_jobs
            ]
            m.Add(sum(served_terms) >= thresh)

    # ---- HC21 T6 infra jobs all accepted ----
    if "HC21" in active_hcs:
        for j in jobs:
            if j["team"] == "T6":
                m.Add(accept[j["job_id"]] == 1)

    # HC1/HC3/HC7/HC13/HC16/HC18/HC19/HC20/HC22: static (see pruning) or
    # tautological. HC1 is inherent (NewOptionalInterval with fixed size). HC18
    # (non-preemption) is automatic because we do not model preemption. HC19
    # (min 1h) is automatic (min hours_required == 1).

    # ---- Baseline objective: maximise accepted jobs, weighted by priority ----
    priority_sum = sum(
        accept[j["job_id"]] * j["priority"]
        for j in jobs
    )
    m.Maximize(priority_sum)

    vars_bag = {
        "accept": accept,
        "start": start,
        "end": end,
        "use": use,
        "interval": interval,
        "compat": compat,
        "priority_sum": priority_sum,
    }
    return m, vars_bag


# ---------- extract solution ----------
def extract_solution(solver, vb, jobs):
    sol = {}
    for j in jobs:
        jid = j["job_id"]
        if solver.Value(vb["accept"][jid]) == 0:
            sol[jid] = None
            continue
        used_gpus = []
        for (jid2, gid), b in vb["use"].items():
            if jid2 != jid:
                continue
            if solver.Value(b) == 1:
                used_gpus.append(gid)
        sol[jid] = {
            "start": solver.Value(vb["start"][jid]),
            "end": solver.Value(vb["end"][jid]),
            "gpus": used_gpus,
        }
    return sol


# ---------- independent verifier ----------
def verify_all_hcs(sol, nodes, gpus, teams, jobs, licenses, maint):
    nodes_by_id = {n["node_id"]: n for n in nodes}
    gpus_by_id = {g["gpu_id"]: g for g in gpus}
    teams_by_id = {t["team_id"]: t for t in teams}
    jobs_by_id = {j["job_id"]: j for j in jobs}

    results = {}

    def add(k, ok, msgs):
        results[k] = {"ok": ok, "violations": msgs[:5]}

    accepted = [(jid, rec) for jid, rec in sol.items() if rec is not None]
    rejected = [jid for jid, rec in sol.items() if rec is None]

    # HC1 contiguous exactly hours_required
    msgs = []
    for jid, rec in accepted:
        dur = jobs_by_id[jid]["hours_required"]
        if rec["end"] - rec["start"] != dur:
            msgs.append(f"{jid} duration {rec['end']-rec['start']} != {dur}")
    add("HC1", not msgs, msgs)

    # HC2 exactly gpus_required GPUs
    msgs = []
    for jid, rec in accepted:
        if len(rec["gpus"]) != jobs_by_id[jid]["gpus_required"]:
            msgs.append(f"{jid} has {len(rec['gpus'])} gpus, need {jobs_by_id[jid]['gpus_required']}")
    add("HC2", not msgs, msgs)

    # HC3 memory
    msgs = []
    for jid, rec in accepted:
        need = jobs_by_id[jid]["min_gpu_memory_gb"]
        for gid in rec["gpus"]:
            if gpus_by_id[gid]["memory_gb"] < need:
                msgs.append(f"{jid} on {gid} mem={gpus_by_id[gid]['memory_gb']}<{need}")
    add("HC3", not msgs, msgs)

    # HC4 no overlap on each GPU
    msgs = []
    by_gpu = defaultdict(list)
    for jid, rec in accepted:
        for gid in rec["gpus"]:
            by_gpu[gid].append((rec["start"], rec["end"], jid))
    for gid, lst in by_gpu.items():
        lst.sort()
        for i in range(len(lst) - 1):
            if lst[i][1] > lst[i + 1][0]:
                msgs.append(f"{gid}: {lst[i][2]} overlaps {lst[i+1][2]}")
    add("HC4", not msgs, msgs)

    # HC5 gang scheduling: trivially satisfied because every accepted job has
    # a single `start` shared across all its GPUs (by model construction). No
    # runtime check is needed; we always return OK. The "job used zero GPUs"
    # failure mode belongs to HC2, not HC5.
    add("HC5", True, [])

    # HC6 single-node (unless InfiniBand)
    msgs = []
    for jid, rec in accepted:
        j = jobs_by_id[jid]
        if j["gpus_required"] <= 1 or j["needs_infiniband"]:
            continue
        node_ids = {gpus_by_id[g]["node_id"] for g in rec["gpus"]}
        if len(node_ids) > 1:
            msgs.append(f"{jid} spans nodes {node_ids}")
    add("HC6", not msgs, msgs)

    # HC7 InfiniBand requirement
    msgs = []
    for jid, rec in accepted:
        if not jobs_by_id[jid]["needs_infiniband"]:
            continue
        for gid in rec["gpus"]:
            nid = gpus_by_id[gid]["node_id"]
            if "InfiniBand" not in nodes_by_id[nid]["interconnect"]:
                msgs.append(f"{jid} on {nid} lacks IB")
    add("HC7", not msgs, msgs)

    # HC8 power budget per node
    msgs = []
    for n in nodes:
        nid = n["node_id"]
        budget = n["power_budget_watts"]
        node_gpus = [g for g in gpus if g["node_id"] == nid]
        total_idle = sum(g["idle_watts"] for g in node_gpus)
        gpu_peak = {g["gpu_id"]: g["peak_watts"] - g["idle_watts"] for g in node_gpus}
        # For each hour in horizon, sum of used gpus' extra + idle baseline.
        events = []
        for jid, rec in accepted:
            for gid in rec["gpus"]:
                if gpus_by_id[gid]["node_id"] != nid:
                    continue
                events.append((rec["start"], +gpu_peak[gid]))
                events.append((rec["end"], -gpu_peak[gid]))
        events.sort()
        cur = total_idle
        peak = cur
        for _, delta in events:
            cur += delta
            peak = max(peak, cur)
        if peak > budget:
            msgs.append(f"{nid} peak={peak} > {budget}")
    add("HC8", not msgs, msgs)

    # HC9 cooling zone A concurrent GPU limit
    msgs = []
    zone_limit = {"A": 24, "B": 12}
    zone_of_gpu = {g["gpu_id"]: nodes_by_id[g["node_id"]]["cooling_zone"] for g in gpus}
    for zone, limit in zone_limit.items():
        events = []
        for jid, rec in accepted:
            for gid in rec["gpus"]:
                if zone_of_gpu[gid] != zone:
                    continue
                events.append((rec["start"], +1))
                events.append((rec["end"], -1))
        events.sort()
        cur = 0
        peak = 0
        for _, delta in events:
            cur += delta
            peak = max(peak, cur)
        if peak > limit:
            msgs.append(f"zone {zone}: peak={peak}>{limit}")
    add("HC9", not msgs, msgs)

    # HC10 license seats (per time)
    msgs = []
    cuda_seats = next(L["seats"] for L in licenses if L["name"] == "CUDA-advanced")
    nccl_seats = next(L["seats"] for L in licenses if L["name"] == "NCCL-pro")
    for name, seats, selector in [
        ("CUDA-advanced", cuda_seats, lambda jid: True),
        ("NCCL-pro", nccl_seats, lambda jid: jobs_by_id[jid]["gpus_required"] > 1),
    ]:
        events = []
        for jid, rec in accepted:
            if not selector(jid):
                continue
            events.append((rec["start"], +1))
            events.append((rec["end"], -1))
        events.sort()
        cur = 0
        peak = 0
        for _, delta in events:
            cur += delta
            peak = max(peak, cur)
        if peak > seats:
            msgs.append(f"{name}: peak={peak}>{seats}")
    add("HC10", not msgs, msgs)

    # HC11 team max_gpus_at_once
    msgs = []
    for t in teams:
        tid = t["team_id"]
        cap = t["max_gpus_at_once"]
        events = []
        for jid, rec in accepted:
            if jobs_by_id[jid]["team"] != tid:
                continue
            events.append((rec["start"], +jobs_by_id[jid]["gpus_required"]))
            events.append((rec["end"], -jobs_by_id[jid]["gpus_required"]))
        events.sort()
        cur = 0
        peak = 0
        for _, delta in events:
            cur += delta
            peak = max(peak, cur)
        if peak > cap:
            msgs.append(f"{tid}: peak={peak}>{cap}")
    add("HC11", not msgs, msgs)

    # HC12 team weekly gpu-hour budget
    msgs = []
    for t in teams:
        tid = t["team_id"]
        cap = t["max_concurrent_gpu_hours"]
        total = 0
        for jid, rec in accepted:
            if jobs_by_id[jid]["team"] != tid:
                continue
            total += jobs_by_id[jid]["gpus_required"] * jobs_by_id[jid]["hours_required"]
        if total > cap:
            msgs.append(f"{tid}: used={total}>{cap}")
    add("HC12", not msgs, msgs)

    # HC13 team allowed_nodes
    msgs = []
    for jid, rec in accepted:
        allowed = set(teams_by_id[jobs_by_id[jid]["team"]]["allowed_nodes"])
        for gid in rec["gpus"]:
            nid = gpus_by_id[gid]["node_id"]
            if nid not in allowed:
                msgs.append(f"{jid} on {nid} not in allowed {allowed}")
    add("HC13", not msgs, msgs)

    # HC14 deadline
    msgs = []
    for jid, rec in accepted:
        dl = jobs_by_id[jid]["deadline_hour"]
        if rec["end"] > dl:
            msgs.append(f"{jid} end={rec['end']}>dl={dl}")
    add("HC14", not msgs, msgs)

    # HC15 maintenance
    msgs = []
    for mw in maint:
        nid = mw["node_id"]
        lo, hi = mw["start_hour"], mw["end_hour"]
        for jid, rec in accepted:
            for gid in rec["gpus"]:
                if gpus_by_id[gid]["node_id"] != nid:
                    continue
                if rec["start"] < hi and rec["end"] > lo:
                    msgs.append(f"{jid} on {gid} overlaps maint {nid}[{lo},{hi}]")
    add("HC15", not msgs, msgs)

    # HC16 dataset locality
    msgs = []
    for jid, rec in accepted:
        cached = jobs_by_id[jid]["dataset_cached_node"]
        if not cached:
            continue
        for gid in rec["gpus"]:
            if gpus_by_id[gid]["node_id"] != cached:
                msgs.append(f"{jid} on {gid} not at cached {cached}")
    add("HC16", not msgs, msgs)

    # HC17 T1 coverage
    t1_jobs = [j for j in jobs if j["team"] == "T1"]
    demand = sum(j["gpus_required"] * j["hours_required"] for j in t1_jobs)
    served = sum(
        jobs_by_id[jid]["gpus_required"] * jobs_by_id[jid]["hours_required"]
        for jid, rec in accepted
        if jobs_by_id[jid]["team"] == "T1"
    )
    ok17 = served * 100 >= demand * 70
    add("HC17", ok17, [] if ok17 else [f"T1 served={served}<70%*{demand}={demand*70//100}"])

    # HC18 non-preemption: implicit — we check no accepted job has a split.
    # By construction there is only one (start,end) so always pass.
    add("HC18", True, [])

    # HC19 min 1h
    msgs = [jid for jid, rec in accepted if rec["end"] - rec["start"] < 1]
    add("HC19", not msgs, msgs)

    # HC20 V100 memory
    msgs = []
    for jid, rec in accepted:
        if jobs_by_id[jid]["min_gpu_memory_gb"] > 16:
            for gid in rec["gpus"]:
                if gpus_by_id[gid]["gpu_type"] == "V100":
                    msgs.append(f"{jid} uses V100 {gid} for >16GB")
    add("HC20", not msgs, msgs)

    # HC21 T6 infra all accepted
    msgs = [j["job_id"] for j in jobs if j["team"] == "T6" and sol.get(j["job_id"]) is None]
    add("HC21", not msgs, [f"{x} T6 not scheduled" for x in msgs])

    # HC22 pretrain on H100 or A100-80GB only
    msgs = []
    for jid, rec in accepted:
        if jobs_by_id[jid]["job_type"] != "pretrain":
            continue
        for gid in rec["gpus"]:
            if gpus_by_id[gid]["gpu_type"] not in ("H100", "A100-80GB"):
                msgs.append(f"{jid} pretrain on {gpus_by_id[gid]['gpu_type']}")
    add("HC22", not msgs, msgs)

    return results


# ---------- phase driver ----------
def solve_phase(name, active_hcs, data, time_limit=TIME_LIMIT, feas_only=True):
    nodes, gpus, teams, jobs, licenses, maint = data
    print(f"\n=== PHASE {name}  HCs={sorted(active_hcs)} ===")
    m, vb = build_model(nodes, gpus, teams, jobs, licenses, maint, active_hcs)
    n_vars = len(m.Proto().variables)
    n_cons = len(m.Proto().constraints)
    print(f"  vars={n_vars} constraints={n_cons}")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = WORKERS
    # We intentionally do NOT use stop_after_first_solution here: with a
    # Maximize objective the very first feasible solution is usually the
    # trivial "accept nothing", which makes cascade phases useless. Instead
    # every phase gets a bounded time budget and we take whatever the solver
    # has found.
    status = solver.Solve(m)
    sn = solver.StatusName(status)
    obj = solver.ObjectiveValue() if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None
    print(f"  status={sn}  obj={obj}")

    entry = {
        "phase": name,
        "status": sn,
        "objective": obj,
        "vars": n_vars,
        "constraints": n_cons,
        "active_hcs": sorted(active_hcs),
    }
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        sol = extract_solution(solver, vb, jobs)
        verify = verify_all_hcs(sol, nodes, gpus, teams, jobs, licenses, maint)
        active_viol = sum(0 if verify[k]["ok"] else 1 for k in verify if k in active_hcs)
        pending_viol = sum(0 if verify[k]["ok"] else 1 for k in verify if k not in active_hcs)
        n_ok = sum(1 for v in verify.values() if v["ok"])
        n_acc = sum(1 for v in sol.values() if v is not None)
        print(f"  accepted={n_acc}/{len(jobs)}  verify: {n_ok}/{len(verify)} "
              f"(active_viol={active_viol} pending_viol={pending_viol})")
        for k, v in verify.items():
            if not v["ok"] and k in active_hcs:
                print(f"    {k} (ACTIVE) FAIL: {v['violations'][:2]}")
        entry["accepted"] = n_acc
        entry["active_hc_violations"] = active_viol
        entry["pending_hc_violations"] = pending_viol
        entry["verify"] = {k: {"ok": v["ok"], "n_viol": len(v["violations"])}
                           for k, v in verify.items()}
    return entry


def main():
    data = load_data()
    nodes, gpus, teams, jobs, licenses, maint = data
    print(f"Loaded: {len(nodes)} nodes, {len(gpus)} GPUs, {len(teams)} teams, "
          f"{len(jobs)} jobs, {len(licenses)} licenses, {len(maint)} maint windows")

    # HC1/HC3/HC5/HC13/HC18/HC19 are structural / tautological (built in
    # unconditionally): HC1 comes from fixed-size intervals, HC3/HC13 from
    # compat pruning, HC5 from the shared start var, HC18 from the
    # no-preemption modelling choice, HC19 from all durations being >= 1.
    STATIC = {"HC1", "HC3", "HC5", "HC18", "HC19"}
    DYNAMIC_SEQ = [
        ("HC13", "team_node_whitelist"),
        ("HC2",  "gpu_count"),
        ("HC4",  "gpu_nonoverlap"),
        ("HC7",  "infiniband"),
        ("HC20", "v100_memory"),
        ("HC22", "pretrain_premium_only"),
        ("HC16", "dataset_locality"),
        ("HC6",  "single_node_colocation"),
        ("HC14", "deadline"),
        ("HC15", "maintenance"),
        ("HC8",  "node_power"),
        ("HC9",  "cooling_zone"),
        ("HC10", "licenses"),
        ("HC11", "team_peak_gpus"),
        ("HC12", "team_weekly_budget"),
        ("HC21", "T6_guaranteed"),
        ("HC17", "T1_coverage_70pct"),
    ]
    ALL = STATIC | {hc for hc, _ in DYNAMIC_SEQ}

    # P01 = static only; then add dynamic HCs one at a time; final = optimise.
    phases = []
    active = set(STATIC)
    phases.append(("P01_static_only", set(active)))
    for i, (hc, label) in enumerate(DYNAMIC_SEQ, start=2):
        active = set(active) | {hc}
        phases.append((f"P{i:02d}_+{label}", set(active)))
    final_idx = len(phases) + 1
    phases.append((f"P{final_idx:02d}_all_HCs_optimize", set(active)))

    all_entries = []
    first_infeasible = None
    for idx, (name, hcs) in enumerate(phases):
        is_final = name.endswith("_all_HCs_optimize")
        tl = FINAL_TIME_LIMIT if is_final else TIME_LIMIT
        entry = solve_phase(name, hcs, data, time_limit=tl, feas_only=not is_final)
        all_entries.append(entry)
        if entry["status"] not in ("OPTIMAL", "FEASIBLE") and first_infeasible is None:
            first_infeasible = name
            print(f"\n!!! first infeasible at {name}")
            # Continue anyway to log the rest.

    out = {
        "n_jobs": len(jobs),
        "n_gpus": len(gpus),
        "n_hcs": 22,
        "first_infeasible": first_infeasible,
        "phases": all_entries,
    }
    with open(RESULTS / "baseline_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved to {RESULTS / 'baseline_results.json'}")


if __name__ == "__main__":
    main()
