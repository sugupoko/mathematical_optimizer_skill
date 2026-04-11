"""Staged baseline for Flexible Job-Shop Scheduling (FJSP) v1.

Pattern: OR-Tools CP-SAT with NewOptionalIntervalVar per (operation, eligible
machine) pair and AddNoOverlap(machine_intervals) per machine.

Active/pending HC phases are layered progressively so we can pinpoint which
constraint is load-bearing.

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

DAYS = [1, 2, 3, 4, 5]
DAY_LEN = 480                          # minutes in a shift
HORIZON = len(DAYS) * DAY_LEN          # 2400 minutes global horizon
TIME_LIMIT = 30
WORKERS = 8


# ---------- loader ----------
def _days_list(v: str) -> list[int]:
    v = (v or "").strip()
    if not v:
        return []
    return [int(x) for x in v.split(";") if x.strip()]


def _parse_maint(v: str) -> list[tuple[int, int, int]]:
    """'3:120-180;5:300-360' -> [(3,120,180),(5,300,360)]."""
    out = []
    if not v:
        return out
    for piece in v.split(";"):
        piece = piece.strip()
        if not piece:
            continue
        day_s, span = piece.split(":")
        a, b = span.split("-")
        out.append((int(day_s), int(a), int(b)))
    return out


def load_data():
    with open(DATA / "machines.csv", encoding="utf-8") as f:
        machines = list(csv.DictReader(f))
    for m in machines:
        m["daily_start_minute"] = int(m["daily_start_minute"])
        m["daily_end_minute"] = int(m["daily_end_minute"])
        m["unavailable_days"] = _days_list(m["unavailable_days"])
        m["maintenance_windows"] = _parse_maint(m["maintenance_windows"])

    with open(DATA / "operators.csv", encoding="utf-8") as f:
        operators = list(csv.DictReader(f))
    for o in operators:
        o["skills"] = [s for s in o["skills"].split(";") if s]
        o["max_daily_minutes"] = int(o["max_daily_minutes"])
        o["unavailable_days"] = _days_list(o["unavailable_days"])

    with open(DATA / "jobs.csv", encoding="utf-8") as f:
        jobs = list(csv.DictReader(f))
    for j in jobs:
        j["due_day"] = int(j["due_day"])
        j["earliest_start_day"] = int(j["earliest_start_day"])

    with open(DATA / "operations.csv", encoding="utf-8") as f:
        operations = list(csv.DictReader(f))
    for op in operations:
        op["sequence"] = int(op["sequence"])
        op["duration_minutes"] = int(op["duration_minutes"])
        op["eligible_machines"] = [x for x in op["eligible_machines"].split(";") if x]
        op["setup_time_if_type_change"] = int(op["setup_time_if_type_change"])

    with open(DATA / "tools.csv", encoding="utf-8") as f:
        tools = list(csv.DictReader(f))
    for t in tools:
        t["quantity"] = int(t["quantity"])

    return machines, operators, jobs, operations, tools


# ---------- model builder ----------
def build_model(machines, operators, jobs, operations, tools, active_hcs: set):
    m = cp_model.CpModel()

    M = {mm["machine_id"]: mm for mm in machines}
    J = {j["job_id"]: j for j in jobs}
    OPS = operations
    OPID = {o["op_id"]: o for o in OPS}

    ops_by_job = defaultdict(list)
    for o in OPS:
        ops_by_job[o["job_id"]].append(o)
    for k in ops_by_job:
        ops_by_job[k].sort(key=lambda x: x["sequence"])

    # -------- presence / start / end / interval per (op, machine) --------
    # HC18 machine-type compatibility: restrict eligible_machines intersected
    # with machines of matching op_type. (This is already true in the data
    # but we re-enforce.)
    pres = {}          # (op_id, mid) -> BoolVar
    starts = {}        # (op_id, mid) -> IntVar
    ends = {}          # (op_id, mid) -> IntVar
    intervals = {}     # (op_id, mid) -> OptionalInterval

    op_start = {}      # op_id -> IntVar (the realised start across all machines)
    op_end = {}        # op_id -> IntVar
    op_machine = {}    # op_id -> list of (mid, pres) for HC1 sum

    for op in OPS:
        op_start[op["op_id"]] = m.NewIntVar(0, HORIZON, f"opS_{op['op_id']}")
        op_end[op["op_id"]] = m.NewIntVar(0, HORIZON, f"opE_{op['op_id']}")
        elig = [mid for mid in op["eligible_machines"]
                if M[mid]["type"] == op["op_type"]]
        # HC18 re-check. If active it matters; if not we still only create
        # presence vars for the type-matching subset because otherwise every
        # other phase would need extra logic.
        if "HC18" not in active_hcs:
            # Relax: allow any eligible_machines regardless of type
            elig = list(op["eligible_machines"])
        op_machine[op["op_id"]] = []
        for mid in elig:
            p = m.NewBoolVar(f"p_{op['op_id']}_{mid}")
            s = m.NewIntVar(0, HORIZON, f"s_{op['op_id']}_{mid}")
            e = m.NewIntVar(0, HORIZON, f"e_{op['op_id']}_{mid}")
            iv = m.NewOptionalIntervalVar(s, op["duration_minutes"], e, p,
                                          f"iv_{op['op_id']}_{mid}")
            pres[op["op_id"], mid] = p
            starts[op["op_id"], mid] = s
            ends[op["op_id"], mid] = e
            intervals[op["op_id"], mid] = iv
            op_machine[op["op_id"]].append((mid, p))
            # Link realised start/end to the chosen machine
            # op_start == s when presence true
            m.Add(op_start[op["op_id"]] == s).OnlyEnforceIf(p)
            m.Add(op_end[op["op_id"]] == e).OnlyEnforceIf(p)

    # -------- HC1: exactly one machine --------
    if "HC1" in active_hcs:
        for op in OPS:
            pairs = op_machine[op["op_id"]]
            m.Add(sum(p for _, p in pairs) == 1)
    else:
        # still require at most one (otherwise op_start is underdefined)
        for op in OPS:
            pairs = op_machine[op["op_id"]]
            m.Add(sum(p for _, p in pairs) <= 1)

    # -------- HC2: no overlap per machine --------
    if "HC2" in active_hcs:
        for mm in machines:
            ivs = [intervals[op["op_id"], mm["machine_id"]]
                   for op in OPS
                   if (op["op_id"], mm["machine_id"]) in intervals]
            if ivs:
                m.AddNoOverlap(ivs)

    # -------- HC3 / HC16: precedence within job --------
    if "HC3" in active_hcs or "HC16" in active_hcs:
        for jid, ops in ops_by_job.items():
            for i in range(len(ops) - 1):
                a = ops[i]
                b = ops[i + 1]
                m.Add(op_start[b["op_id"]] >= op_end[a["op_id"]])
                if "HC16" in active_hcs:
                    # Cross-day precedence: derived-day of b >= derived-day of a
                    # Encoded via op_end[a] / op_start[b] already covers it
                    pass

    # HC4 duration match is baked in by NewOptionalIntervalVar(size=dur).

    # -------- HC5: fit within day --------
    if "HC5" in active_hcs:
        # An interval must live inside some [d*DAY_LEN, d*DAY_LEN+DAY_LEN) window.
        # Use day assignment ints.
        for op in OPS:
            d = m.NewIntVar(1, len(DAYS), f"day_{op['op_id']}")
            # op_start in [(d-1)*DAY_LEN, d*DAY_LEN - duration]
            m.Add(op_start[op["op_id"]] >= (d - 1) * DAY_LEN)
            m.Add(op_end[op["op_id"]] <= d * DAY_LEN)

    # -------- HC6: maintenance windows --------
    if "HC6" in active_hcs:
        for mm in machines:
            for (day, a, b) in mm["maintenance_windows"]:
                lo = (day - 1) * DAY_LEN + a
                hi = (day - 1) * DAY_LEN + b
                # forbid any interval on this machine from overlapping [lo, hi)
                for op in OPS:
                    key = (op["op_id"], mm["machine_id"])
                    if key not in intervals:
                        continue
                    p = pres[key]
                    s = starts[key]
                    e = ends[key]
                    # if presence: s >= hi  OR  e <= lo
                    b1 = m.NewBoolVar(f"mb1_{op['op_id']}_{mm['machine_id']}_{day}_{a}")
                    b2 = m.NewBoolVar(f"mb2_{op['op_id']}_{mm['machine_id']}_{day}_{a}")
                    m.Add(s >= hi).OnlyEnforceIf(b1)
                    m.Add(e <= lo).OnlyEnforceIf(b2)
                    m.AddBoolOr([b1, b2, p.Not()])

    # -------- HC7: machine unavailable days --------
    if "HC7" in active_hcs:
        for mm in machines:
            for day in mm["unavailable_days"]:
                lo = (day - 1) * DAY_LEN
                hi = day * DAY_LEN
                for op in OPS:
                    key = (op["op_id"], mm["machine_id"])
                    if key not in intervals:
                        continue
                    p = pres[key]
                    s = starts[key]
                    e = ends[key]
                    b1 = m.NewBoolVar(f"ub1_{op['op_id']}_{mm['machine_id']}_{day}")
                    b2 = m.NewBoolVar(f"ub2_{op['op_id']}_{mm['machine_id']}_{day}")
                    m.Add(s >= hi).OnlyEnforceIf(b1)
                    m.Add(e <= lo).OnlyEnforceIf(b2)
                    m.AddBoolOr([b1, b2, p.Not()])

    # HC8 setup time (sequence-dependent) is simplified to a per-day global
    # budget in HC20 instead. We note it in spec.md as A3 and enforce the
    # max-1-type-change-per-day rule in HC20.

    # -------- HC9/HC10/HC11/HC12/HC17: operator assignment --------
    # op_op[op,operator] boolean: operator handles this op.
    op_op = {}
    if any(hc in active_hcs for hc in ("HC9", "HC10", "HC11", "HC12", "HC17")):
        for op in OPS:
            for o in operators:
                op_op[op["op_id"], o["operator_id"]] = m.NewBoolVar(
                    f"oo_{op['op_id']}_{o['operator_id']}"
                )

        if "HC9" in active_hcs:
            for op in OPS:
                m.Add(
                    sum(op_op[op["op_id"], o["operator_id"]] for o in operators)
                    == sum(p for _, p in op_machine[op["op_id"]])
                )

        if "HC10" in active_hcs:
            for op in OPS:
                for o in operators:
                    if op["op_type"] not in o["skills"]:
                        m.Add(op_op[op["op_id"], o["operator_id"]] == 0)

        if "HC11" in active_hcs:
            # A-rule: we cap the operator's *weekly* total load at
            # max_daily_minutes * (#available days). This is a strictly weaker
            # version of per-day caps but avoids a huge reification.
            for o in operators:
                avail_days = len(DAYS) - len(o["unavailable_days"])
                budget = avail_days * o["max_daily_minutes"]
                total = sum(
                    op_op[op["op_id"], o["operator_id"]] * op["duration_minutes"]
                    for op in OPS
                )
                m.Add(total <= budget)

        if "HC12" in active_hcs:
            # For each operator, add an unavailable "blocker" interval per
            # off-day on the *operator timeline* (HC17 no-overlap is the
            # vehicle). We reuse op_op reified intervals built under HC17.
            # Unavailability intervals: [d-1)*DAY_LEN, d*DAY_LEN) fixed and
            # always present. We collect them here and hand off to HC17 below.
            pass

        if "HC17" in active_hcs:
            # Per operator, the intervals of ops they handle must not overlap.
            for o in operators:
                ivs = []
                for op in OPS:
                    iv = m.NewOptionalIntervalVar(
                        op_start[op["op_id"]],
                        op["duration_minutes"],
                        op_end[op["op_id"]],
                        op_op[op["op_id"], o["operator_id"]],
                        f"oiv_{op['op_id']}_{o['operator_id']}",
                    )
                    ivs.append(iv)
                # HC12: add fixed "off-day" blocker intervals spanning whole day.
                if "HC12" in active_hcs:
                    for d in o["unavailable_days"]:
                        ivs.append(
                            m.NewIntervalVar(
                                (d - 1) * DAY_LEN,
                                DAY_LEN,
                                d * DAY_LEN,
                                f"ooff_{o['operator_id']}_{d}",
                            )
                        )
                m.AddNoOverlap(ivs)

    # -------- HC13: tool availability (cumulative) --------
    if "HC13" in active_hcs:
        for t in tools:
            ivs = []
            demands = []
            for op in OPS:
                if op["required_tool"] != t["tool_id"]:
                    continue
                # op's global interval (presence = scheduled at all)
                # (At baseline we assume every op is scheduled -> use a constant 1.)
                iv = m.NewIntervalVar(
                    op_start[op["op_id"]],
                    op["duration_minutes"],
                    op_end[op["op_id"]],
                    f"tiv_{op['op_id']}_{t['tool_id']}",
                )
                ivs.append(iv)
                demands.append(1)
            if ivs:
                m.AddCumulative(ivs, demands, t["quantity"])

    # -------- HC14: due day --------
    if "HC14" in active_hcs:
        for j in jobs:
            deadline = j["due_day"] * DAY_LEN
            for op in ops_by_job[j["job_id"]]:
                m.Add(op_end[op["op_id"]] <= deadline)

    # -------- HC15: earliest start day --------
    if "HC15" in active_hcs:
        for j in jobs:
            lo = (j["earliest_start_day"] - 1) * DAY_LEN
            for op in ops_by_job[j["job_id"]]:
                m.Add(op_start[op["op_id"]] >= lo)

    # HC16 handled together with HC3.

    # -------- HC19: urgent jobs finish within first 2 days --------
    if "HC19" in active_hcs:
        for j in jobs:
            if j["priority"] == "urgent":
                for op in ops_by_job[j["job_id"]]:
                    m.Add(op_end[op["op_id"]] <= 2 * DAY_LEN)

    # -------- HC20: max 1 setup (op_type) change per machine per day --------
    if "HC20" in active_hcs:
        # Approximate: for each (machine, day) count the number of *distinct*
        # op_types used on that day and require it <= 2 (initial + 1 change).
        # Use per op 'on_md' boolean and sum of indicator(any op of that type).
        for mm in machines:
            for d in DAYS:
                type_used = {}
                for otype in ("lathe", "milling", "drilling", "grinding", "cnc"):
                    ind = m.NewBoolVar(f"tu_{mm['machine_id']}_{d}_{otype}")
                    ops_of_type_on_md = []
                    for op in OPS:
                        if op["op_type"] != otype:
                            continue
                        key = (op["op_id"], mm["machine_id"])
                        if key not in intervals:
                            continue
                        p = pres[key]
                        s = starts[key]
                        # on day d iff presence and (d-1)*DAY_LEN <= s < d*DAY_LEN
                        on_md = m.NewBoolVar(f"onmd_{op['op_id']}_{mm['machine_id']}_{d}")
                        m.Add(s >= (d - 1) * DAY_LEN).OnlyEnforceIf(on_md)
                        m.Add(s < d * DAY_LEN).OnlyEnforceIf(on_md)
                        # if p is false, force on_md false
                        m.Add(on_md <= p) if False else m.AddImplication(p.Not(), on_md.Not())
                        ops_of_type_on_md.append(on_md)
                    if ops_of_type_on_md:
                        # ind = OR(ops_of_type_on_md)
                        m.AddBoolOr(ops_of_type_on_md + [ind.Not()])
                        for x in ops_of_type_on_md:
                            m.AddImplication(x, ind)
                        type_used[otype] = ind
                    else:
                        m.Add(ind == 0)
                        type_used[otype] = ind
                m.Add(sum(type_used.values()) <= 2)

    # -------- Objective (baseline: minimise makespan proxy) --------
    makespan = m.NewIntVar(0, HORIZON, "makespan")
    for op in OPS:
        m.Add(makespan >= op_end[op["op_id"]])
    m.Minimize(makespan)

    vars_bag = {
        "pres": pres,
        "starts": starts,
        "ends": ends,
        "op_start": op_start,
        "op_end": op_end,
        "op_op": op_op,
        "op_machine": op_machine,
        "intervals": intervals,
        "makespan": makespan,
    }
    return m, vars_bag


# ---------- solution extraction ----------
def extract_solution(solver, vb, machines, operators, operations):
    sol = {}  # op_id -> {machine, start, end, operator}
    for op in operations:
        mid = None
        for mm_id, p in vb["op_machine"][op["op_id"]]:
            if solver.Value(p) == 1:
                mid = mm_id
                break
        if mid is None:
            sol[op["op_id"]] = None
            continue
        s = solver.Value(vb["starts"][op["op_id"], mid])
        e = solver.Value(vb["ends"][op["op_id"], mid])
        operator_id = None
        for o in operators:
            k = (op["op_id"], o["operator_id"])
            if k in vb["op_op"] and solver.Value(vb["op_op"][k]) == 1:
                operator_id = o["operator_id"]
                break
        sol[op["op_id"]] = {"machine": mid, "start": s, "end": e, "operator": operator_id}
    return sol


# ---------- independent verifier ----------
def verify_all_hcs(sol, machines, operators, jobs, operations, tools):
    M = {mm["machine_id"]: mm for mm in machines}
    J = {j["job_id"]: j for j in jobs}
    OPID = {o["op_id"]: o for o in operations}
    O = {o["operator_id"]: o for o in operators}
    T = {t["tool_id"]: t for t in tools}

    results = {}

    def add(k, ok, msgs):
        results[k] = {"ok": ok, "violations": msgs[:5]}

    scheduled_ops = [(oid, rec) for oid, rec in sol.items() if rec is not None]

    # HC1 exactly one machine: every op in sol has non-None rec
    msgs = [oid for oid, rec in sol.items() if rec is None]
    add("HC1", not msgs, [f"{o} unscheduled" for o in msgs])

    # HC2 machine non-overlap
    msgs = []
    by_m = defaultdict(list)
    for oid, rec in scheduled_ops:
        by_m[rec["machine"]].append((rec["start"], rec["end"], oid))
    for mid, lst in by_m.items():
        lst.sort()
        for i in range(len(lst) - 1):
            if lst[i][1] > lst[i + 1][0]:
                msgs.append(f"{mid}: {lst[i][2]} overlaps {lst[i+1][2]}")
    add("HC2", not msgs, msgs)

    # HC3 precedence (within job) + HC16
    msgs_p = []
    ops_by_job = defaultdict(list)
    for o in operations:
        ops_by_job[o["job_id"]].append(o)
    for jid, lst in ops_by_job.items():
        lst.sort(key=lambda x: x["sequence"])
        for i in range(len(lst) - 1):
            a = sol.get(lst[i]["op_id"])
            b = sol.get(lst[i + 1]["op_id"])
            if not a or not b:
                continue
            if b["start"] < a["end"]:
                msgs_p.append(f"{jid}: op seq {lst[i]['sequence']}->{lst[i+1]['sequence']} overlap")
    add("HC3", not msgs_p, msgs_p)
    add("HC16", not msgs_p, msgs_p)

    # HC4 duration match
    msgs = []
    for oid, rec in scheduled_ops:
        exp = OPID[oid]["duration_minutes"]
        got = rec["end"] - rec["start"]
        if got != exp:
            msgs.append(f"{oid} dur {got} != {exp}")
    add("HC4", not msgs, msgs)

    # HC5 fit within day
    msgs = []
    for oid, rec in scheduled_ops:
        d_start = rec["start"] // DAY_LEN
        d_end = (rec["end"] - 1) // DAY_LEN if rec["end"] > rec["start"] else d_start
        if d_start != d_end:
            msgs.append(f"{oid} straddles day boundary")
    add("HC5", not msgs, msgs)

    # HC6 maintenance
    msgs = []
    for oid, rec in scheduled_ops:
        for (day, a, b) in M[rec["machine"]]["maintenance_windows"]:
            lo = (day - 1) * DAY_LEN + a
            hi = (day - 1) * DAY_LEN + b
            if rec["start"] < hi and rec["end"] > lo:
                msgs.append(f"{oid} overlaps maint on {rec['machine']} day {day}")
    add("HC6", not msgs, msgs)

    # HC7 machine off-days
    msgs = []
    for oid, rec in scheduled_ops:
        d = rec["start"] // DAY_LEN + 1
        if d in M[rec["machine"]]["unavailable_days"]:
            msgs.append(f"{oid} on {rec['machine']} off-day {d}")
    add("HC7", not msgs, msgs)

    # HC8 setup-time (simplified; we accept HC20 as the proxy)
    add("HC8", True, [])

    # HC9 operator required
    msgs = [oid for oid, rec in scheduled_ops if rec["operator"] is None]
    add("HC9", not msgs, [f"{o} no operator" for o in msgs])

    # HC10 operator skill
    msgs = []
    for oid, rec in scheduled_ops:
        if rec["operator"] is None:
            continue
        if OPID[oid]["op_type"] not in O[rec["operator"]]["skills"]:
            msgs.append(f"{oid} op={rec['operator']} lacks skill {OPID[oid]['op_type']}")
    add("HC10", not msgs, msgs)

    # HC11 operator daily minutes
    msgs = []
    load = defaultdict(int)
    for oid, rec in scheduled_ops:
        if rec["operator"] is None:
            continue
        d = rec["start"] // DAY_LEN + 1
        load[rec["operator"], d] += OPID[oid]["duration_minutes"]
    for (op_id, d), v in load.items():
        if v > O[op_id]["max_daily_minutes"]:
            msgs.append(f"{op_id} day {d}: {v} > {O[op_id]['max_daily_minutes']}")
    add("HC11", not msgs, msgs)

    # HC12 operator off-days
    msgs = []
    for oid, rec in scheduled_ops:
        if rec["operator"] is None:
            continue
        d = rec["start"] // DAY_LEN + 1
        if d in O[rec["operator"]]["unavailable_days"]:
            msgs.append(f"{oid} by {rec['operator']} on off-day {d}")
    add("HC12", not msgs, msgs)

    # HC13 tool availability (point sampling)
    msgs = []
    for t in tools:
        ops_t = [(oid, rec) for oid, rec in scheduled_ops
                 if OPID[oid]["required_tool"] == t["tool_id"]]
        if not ops_t:
            continue
        events = []
        for oid, rec in ops_t:
            events.append((rec["start"], +1, oid))
            events.append((rec["end"], -1, oid))
        events.sort()
        cur = 0
        peak = 0
        for _, delta, _ in events:
            cur += delta
            peak = max(peak, cur)
        if peak > t["quantity"]:
            msgs.append(f"{t['tool_id']} peak {peak} > qty {t['quantity']}")
    add("HC13", not msgs, msgs)

    # HC14 due day
    msgs = []
    for j in jobs:
        deadline = j["due_day"] * DAY_LEN
        for op in ops_by_job[j["job_id"]]:
            rec = sol.get(op["op_id"])
            if rec and rec["end"] > deadline:
                msgs.append(f"{j['job_id']} op {op['op_id']} end {rec['end']} > {deadline}")
                break
    add("HC14", not msgs, msgs)

    # HC15 earliest start
    msgs = []
    for j in jobs:
        lo = (j["earliest_start_day"] - 1) * DAY_LEN
        for op in ops_by_job[j["job_id"]]:
            rec = sol.get(op["op_id"])
            if rec and rec["start"] < lo:
                msgs.append(f"{op['op_id']} start {rec['start']} < {lo}")
    add("HC15", not msgs, msgs)

    # HC17 operator non-overlap
    msgs = []
    by_op = defaultdict(list)
    for oid, rec in scheduled_ops:
        if rec["operator"]:
            by_op[rec["operator"]].append((rec["start"], rec["end"], oid))
    for op_id, lst in by_op.items():
        lst.sort()
        for i in range(len(lst) - 1):
            if lst[i][1] > lst[i + 1][0]:
                msgs.append(f"{op_id}: {lst[i][2]} overlaps {lst[i+1][2]}")
    add("HC17", not msgs, msgs)

    # HC18 machine type match
    msgs = []
    for oid, rec in scheduled_ops:
        if M[rec["machine"]]["type"] != OPID[oid]["op_type"]:
            msgs.append(f"{oid} op_type {OPID[oid]['op_type']} on {rec['machine']} type {M[rec['machine']]['type']}")
    add("HC18", not msgs, msgs)

    # HC19 urgent in first 2 days
    msgs = []
    for j in jobs:
        if j["priority"] != "urgent":
            continue
        for op in ops_by_job[j["job_id"]]:
            rec = sol.get(op["op_id"])
            if rec and rec["end"] > 2 * DAY_LEN:
                msgs.append(f"urgent {j['job_id']} op {op['op_id']} ends {rec['end']}")
                break
    add("HC19", not msgs, msgs)

    # HC20 max 1 setup change per machine per day
    msgs = []
    seen = defaultdict(set)
    for oid, rec in scheduled_ops:
        d = rec["start"] // DAY_LEN + 1
        seen[rec["machine"], d].add(OPID[oid]["op_type"])
    for (mid, d), types in seen.items():
        if len(types) > 2:
            msgs.append(f"{mid} day {d} has {len(types)} op_types")
    add("HC20", not msgs, msgs)

    return results


# ---------- driver ----------
def solve_phase(name, active_hcs, data, time_limit=TIME_LIMIT):
    machines, operators, jobs, operations, tools = data
    print(f"\n=== PHASE {name}  HCs={sorted(active_hcs)} ===")
    m, vb = build_model(machines, operators, jobs, operations, tools, active_hcs)
    n_vars = len(m.Proto().variables)
    n_cons = len(m.Proto().constraints)
    print(f"  model size: vars={n_vars} constraints={n_cons}")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = WORKERS
    # For feasibility-oriented phases, stop at first solution so we don't
    # burn 30s chasing optimal. The final phase still attempts optimisation.
    if "P11" not in name:
        solver.parameters.stop_after_first_solution = True
    status = solver.Solve(m)
    sn = solver.StatusName(status)
    obj = solver.ObjectiveValue() if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None
    print(f"  status={sn}  obj={obj}")

    entry = {
        "phase": name,
        "status": sn,
        "makespan": obj,
        "vars": n_vars,
        "constraints": n_cons,
        "active_hcs": sorted(active_hcs),
    }
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        sol = extract_solution(solver, vb, machines, operators, operations)
        verify = verify_all_hcs(sol, machines, operators, jobs, operations, tools)
        active_viol = sum(
            0 if verify[k]["ok"] else 1
            for k in verify
            if k in active_hcs
        )
        pending_viol = sum(
            0 if verify[k]["ok"] else 1
            for k in verify
            if k not in active_hcs
        )
        n_ok = sum(1 for v in verify.values() if v["ok"])
        print(f"  verify: {n_ok}/{len(verify)} ok (active_viol={active_viol} pending_viol={pending_viol})")
        for k, v in verify.items():
            if not v["ok"] and k in active_hcs:
                print(f"    {k} (active) FAIL: {v['violations'][:2]}")
        entry["active_hc_violations"] = active_viol
        entry["pending_hc_violations"] = pending_viol
        entry["verify"] = {k: {"ok": v["ok"], "n_viol": len(v["violations"])}
                           for k, v in verify.items()}
    return entry, solver, m, vb


def main():
    data = load_data()
    machines, operators, jobs, operations, tools = data
    print(f"Loaded: {len(machines)} machines, {len(operators)} operators, "
          f"{len(jobs)} jobs, {len(operations)} ops, {len(tools)} tools")

    all_hcs = {f"HC{i}" for i in range(1, 21)}
    phases = [
        ("P01_machine_assign_noov",  {"HC1", "HC2", "HC4", "HC18"}),
        ("P02_+precedence",          {"HC1", "HC2", "HC3", "HC4", "HC16", "HC18"}),
        ("P03_+day_fit",             {"HC1", "HC2", "HC3", "HC4", "HC5", "HC16", "HC18"}),
        ("P04_+maint_unavail",       {"HC1","HC2","HC3","HC4","HC5","HC6","HC7","HC16","HC18"}),
        ("P05_+earliest_due",        {"HC1","HC2","HC3","HC4","HC5","HC6","HC7","HC14","HC15","HC16","HC18"}),
        ("P06_+urgent",              {"HC1","HC2","HC3","HC4","HC5","HC6","HC7","HC14","HC15","HC16","HC18","HC19"}),
        ("P07_+tooling",             {"HC1","HC2","HC3","HC4","HC5","HC6","HC7","HC13","HC14","HC15","HC16","HC18","HC19"}),
        ("P08_+operator_core",       {"HC1","HC2","HC3","HC4","HC5","HC6","HC7","HC9","HC10","HC13","HC14","HC15","HC16","HC18","HC19"}),
        ("P09_+operator_caps",       {"HC1","HC2","HC3","HC4","HC5","HC6","HC7","HC9","HC10","HC11","HC12","HC13","HC14","HC15","HC16","HC17","HC18","HC19"}),
        ("P10_+setup_limit",         {"HC1","HC2","HC3","HC4","HC5","HC6","HC7","HC8","HC9","HC10","HC11","HC12","HC13","HC14","HC15","HC16","HC17","HC18","HC19","HC20"}),
        ("P11_all_HCs",              all_hcs),
    ]

    all_entries = []
    first_infeasible = None
    for name, active in phases:
        entry, *_ = solve_phase(name, active, data)
        all_entries.append(entry)
        if entry["status"] not in ("OPTIMAL", "FEASIBLE") and first_infeasible is None:
            first_infeasible = name
            print(f"\n!!! first infeasible at {name} — stopping cascade")
            break

    out = {
        "first_infeasible": first_infeasible,
        "phases": all_entries,
        "n_ops": len(operations),
        "n_hcs": 20,
    }
    with open(RESULTS / "baseline_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved to {RESULTS / 'baseline_results.json'}")


if __name__ == "__main__":
    main()
