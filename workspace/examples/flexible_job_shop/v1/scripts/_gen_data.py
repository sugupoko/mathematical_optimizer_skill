"""Deterministic data generator for the FJSP v1 example.

Creates CSV files under ../data/. Run once; checked-in CSVs are the source
of truth from there on.

    python _gen_data.py
"""

from __future__ import annotations

import csv
import os
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data"
TOP_DATA = HERE.parent.parent / "data"
DATA.mkdir(parents=True, exist_ok=True)
TOP_DATA.mkdir(parents=True, exist_ok=True)

rng = random.Random(20260411)

DAYS = [1, 2, 3, 4, 5]
DAY_START = 0
DAY_END = 480

# ---------- machines ----------
# 5 lathe, 4 milling, 3 drilling, 2 grinding, 1 cnc = 15
MACHINE_TYPES = (
    [("lathe", 5), ("milling", 4), ("drilling", 3), ("grinding", 2), ("cnc", 1)]
)

machines = []
mid = 1
for mtype, n in MACHINE_TYPES:
    for _ in range(n):
        machines.append({
            "machine_id": f"M{mid:02d}",
            "name": f"{mtype.title()}-{mid:02d}",
            "type": mtype,
            "daily_start_minute": DAY_START,
            "daily_end_minute": DAY_END,
            "unavailable_days": "",
            "maintenance_windows": "",
        })
        mid += 1

# Sprinkle a few unavailable days and maintenance windows
# (maintenance_windows format: day:start-end;day:start-end)
machines[0]["maintenance_windows"] = "3:120-180"      # M01 lathe: mid-day preventive
machines[3]["unavailable_days"] = "4"                  # M04 lathe off day 4
machines[6]["maintenance_windows"] = "2:60-120;5:300-360"  # M07 milling
machines[9]["unavailable_days"] = "5"                  # M10 drilling off day 5
machines[12]["maintenance_windows"] = "1:0-60"         # M13 grinding: morning cal
machines[14]["unavailable_days"] = "2"                 # M15 cnc off day 2

# ---------- operators ----------
# 12 operators; each has 1-3 skills from {lathe, milling, drilling, grinding, cnc}
SKILL_POOL = ["lathe", "milling", "drilling", "grinding", "cnc"]
operators = []
skill_defs = [
    ["lathe", "milling"],
    ["lathe", "drilling"],
    ["lathe", "grinding"],
    ["lathe"],
    ["milling", "drilling"],
    ["milling", "cnc"],
    ["milling", "grinding"],
    ["drilling", "grinding"],
    ["drilling"],
    ["grinding", "cnc"],
    ["cnc", "milling", "lathe"],
    ["lathe", "milling", "drilling"],
]
for i, skills in enumerate(skill_defs, start=1):
    operators.append({
        "operator_id": f"O{i:02d}",
        "name": f"Op-{i:02d}",
        "skills": ";".join(skills),
        "max_daily_minutes": 480,
        "unavailable_days": "",
    })
operators[1]["unavailable_days"] = "2"
operators[4]["unavailable_days"] = "5"
operators[7]["unavailable_days"] = "3"
operators[10]["unavailable_days"] = "1"

# ---------- jobs (40) ----------
# priority mix: urgent 5, high 10, normal 20, low 5
priorities = (["urgent"] * 5) + (["high"] * 10) + (["normal"] * 20) + (["low"] * 5)
rng.shuffle(priorities)

jobs = []
for i in range(1, 41):
    pr = priorities[i - 1]
    if pr == "urgent":
        # All urgent jobs share the 2-day window [1,2] so we always have
        # 960 min of headroom, well above the 600-max total we allow for
        # urgent ops below.
        due = 2
        earliest = 1
    elif pr == "high":
        due = rng.choice([2, 3])
        earliest = 1
    elif pr == "normal":
        due = rng.choice([3, 4, 5])
        earliest = rng.choice([1, 1, 2])
    else:
        due = 5
        earliest = rng.choice([1, 2, 3])
    jobs.append({
        "job_id": f"J{i:02d}",
        "name": f"Part-{i:02d}",
        "priority": pr,
        "due_day": due,
        "earliest_start_day": earliest,
    })

# ---------- operations ----------
# each job has 4-8 operations; sequence 1..n
OP_TYPES = ["lathe", "milling", "drilling", "grinding", "cnc"]
mach_by_type = {}
for m in machines:
    mach_by_type.setdefault(m["type"], []).append(m["machine_id"])

TOOLS_NEEDED_FOR_TYPES = {
    "cnc": ["T03", "T05"],    # T03 qty 1, T05 qty 1 (tightest)
    "grinding": ["T04"],       # T04 qty 2
    "milling": ["T01", "T02"],
    "lathe": ["T02"],
    "drilling": ["T01"],
}

operations = []
op_counter = 1
# Balance by type (capacity budget in minutes over 5 days):
#   lathe 12000, milling 9600, drilling 7200, grinding 4800, cnc 2400.
# We keep a per-type running load and bias choices so nothing over-commits.
TYPE_CAP = {"lathe": 11000, "milling": 8600, "drilling": 6400,
            "grinding": 4000, "cnc": 1800}
type_load = {k: 0 for k in TYPE_CAP}
NON_CNC = ["lathe", "milling", "drilling", "grinding"]

def pick_type(exclude: set = set()):
    # pick type with most remaining slack relative to cap
    cands = [t for t in NON_CNC if t not in exclude]
    cands.sort(key=lambda t: (type_load[t] / TYPE_CAP[t]))
    return cands[0]

for j in jobs:
    # Shorter routings for tight deadlines
    if j["priority"] == "urgent":
        n_ops = rng.randint(4, 5)
    elif j["priority"] == "high":
        n_ops = rng.randint(4, 6)
    else:
        n_ops = rng.randint(4, 8)
    seq = []
    remaining = n_ops
    if remaining >= 1:
        seq.append("lathe"); remaining -= 1
    if remaining >= 1:
        seq.append(rng.choice(["milling", "drilling"])); remaining -= 1
    while remaining > 0:
        seq.append(pick_type())
        remaining -= 1
    # Only urgent/high jobs may get a CNC finisher, and only if cnc budget
    # has slack. At most ~20 cnc ops total.
    if (j["priority"] in ("urgent", "high")
            and type_load["cnc"] < TYPE_CAP["cnc"] - 120
            and rng.random() < 0.35):
        seq[-1] = "cnc"

    for idx, op_type in enumerate(seq, start=1):
        eligible = list(mach_by_type[op_type])
        # pick 2-4 eligible machines of that type (or all if fewer)
        k = min(len(eligible), rng.randint(2, 4))
        elig = sorted(rng.sample(eligible, k))
        if j["priority"] in ("urgent", "high"):
            dur = rng.choice([30, 45, 60, 75, 90])
        else:
            dur = rng.choice([30, 45, 60, 75, 90, 120])
        type_load[op_type] += dur
        tool = ""
        if op_type in TOOLS_NEEDED_FOR_TYPES and rng.random() < 0.55:
            tool = rng.choice(TOOLS_NEEDED_FOR_TYPES[op_type])
        setup_change = rng.choice([15, 20, 25, 30])
        operations.append({
            "op_id": f"OP{op_counter:04d}",
            "job_id": j["job_id"],
            "sequence": idx,
            "op_type": op_type,
            "duration_minutes": dur,
            "eligible_machines": ";".join(elig),
            "required_tool": tool,
            "setup_time_if_type_change": setup_change,
        })
        op_counter += 1

# ---------- tools ----------
tools = [
    {"tool_id": "T01", "name": "Carbide Insert Set", "quantity": 2},
    {"tool_id": "T02", "name": "HSS Boring Bar", "quantity": 3},
    {"tool_id": "T03", "name": "Diamond Grinding Wheel", "quantity": 1},
    {"tool_id": "T04", "name": "Precision Grinder Jig", "quantity": 2},
    {"tool_id": "T05", "name": "CNC Probe Kit", "quantity": 1},
]

# ---------- constraints (20 HCs + 6 SCs) ----------
constraints = [
    ("HC1",  "hard", "Each operation assigned to exactly one eligible machine"),
    ("HC2",  "hard", "No two operations on the same machine overlap in time (AddNoOverlap)"),
    ("HC3",  "hard", "Operation precedence within a job (op N+1 starts after op N ends)"),
    ("HC4",  "hard", "Operation duration matches the machine's duration for that op"),
    ("HC5",  "hard", "Operation must fit within a machine's daily operating hours"),
    ("HC6",  "hard", "Machine maintenance windows are blocked"),
    ("HC7",  "hard", "Machine unavailable days are blocked"),
    ("HC8",  "hard", "Sequence-dependent setup time between different op_types on same machine"),
    ("HC9",  "hard", "An operator is required on the machine during the operation"),
    ("HC10", "hard", "Operator skill must match the machine type"),
    ("HC11", "hard", "Operator daily max minutes not exceeded"),
    ("HC12", "hard", "Operator unavailable days respected"),
    ("HC13", "hard", "Tool availability: simultaneous usage cannot exceed tool quantity"),
    ("HC14", "hard", "Job due day: all operations of a job finish by end of due_day"),
    ("HC15", "hard", "Earliest start day: no operation may start before job's earliest_start_day"),
    ("HC16", "hard", "Precedence across days: op N+1 day >= op N day"),
    ("HC17", "hard", "No operator runs two machines simultaneously"),
    ("HC18", "hard", "Machine type compatibility (op_type must match machine type)"),
    ("HC19", "hard", "Urgent jobs complete within first 2 days"),
    ("HC20", "hard", "At most 1 setup (op_type) change per machine per day"),
    ("SC1",  "soft", "Minimise makespan (total completion time)"),
    ("SC2",  "soft", "Minimise total tardiness (late jobs vs due date)"),
    ("SC3",  "soft", "Balance machine utilisation across the 15 machines"),
    ("SC4",  "soft", "Minimise total setup-time overhead"),
    ("SC5",  "soft", "Balance operator workload"),
    ("SC6",  "soft", "Prioritise high-priority jobs (earliness bonus)"),
]


def write_csv(path: Path, rows: list, fields: list):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    for target in (DATA, TOP_DATA):
        write_csv(target / "machines.csv", machines, list(machines[0].keys()))
        write_csv(target / "operators.csv", operators, list(operators[0].keys()))
        write_csv(target / "jobs.csv", jobs, list(jobs[0].keys()))
        write_csv(target / "operations.csv", operations, list(operations[0].keys()))
        write_csv(target / "tools.csv", tools, list(tools[0].keys()))
        with open(target / "constraints.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["id", "kind", "description"])
            for row in constraints:
                w.writerow(row)

    print(f"machines: {len(machines)}")
    print(f"operators: {len(operators)}")
    print(f"jobs: {len(jobs)}")
    print(f"operations: {len(operations)}")
    print(f"tools: {len(tools)}")
    print(f"constraints: {len(constraints)}")


if __name__ == "__main__":
    main()
