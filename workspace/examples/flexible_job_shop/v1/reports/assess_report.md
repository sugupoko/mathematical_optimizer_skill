# Assessment Report — Flexible Job-Shop Scheduling v1

## 1. Problem Classification

| Field | Value |
|---|---|
| Problem class | Resource-constrained production scheduling |
| Sub-class | **Flexible Job-Shop (FJSP)** with multi-resource (machine + operator + tool) |
| Complexity | **complex** (≥15 HCs, multi-resource, precedence + calendar) |
| Scale | 40 jobs, ~240 operations, 15 machines, 12 operators, 5 tools, 5 days |
| Horizon | 2400 minutes (5 × 480 single-shift) |
| Approx variables | ~9,000 CP-SAT vars when all HCs active |
| HC count | 20 |
| SC count | 6 |

## 2. Why It Is Complex

- **Flexibility**: each operation has 2-4 eligible machines, not 1 — gives
  ~720 presence booleans alone.
- **Multi-resource**: machine + operator + tool must all be free
  simultaneously (three cumulative constraints per op).
- **Precedence chains** of length 4-8 per job, spanning multiple days.
- **Calendar effects**: maintenance windows, machine/operator off-days.
- **Tool scarcity**: T03, T05 quantity=1 → forced serialisation of any two
  ops that share them.
- **Urgency window** (HC19) couples the scheduling problem with the calendar
  before any makespan optimisation kicks in.

Single-phase solve was judged risky (many reification helpers, ~21k
constraints) so we use a **staged baseline** with active/pending HC split.

## 3. Hypothesised Bottlenecks

| # | Hypothesis | Why |
|---|---|---|
| B1 | CNC machine (M15) becomes the makespan driver | 1 machine, ~450 min of workload, + day-2 off |
| B2 | Urgent jobs crowd day 1 lathes | HC19 forces urgent ops into days 1-2; M01 has day-3 maintenance only but urgent lathe ops pile up early |
| B3 | Tool T05 serialises CNC | T05 qty 1; every cnc op that needs T05 cannot run in parallel with another T05 op |
| B4 | Operator O11 (cnc+milling+lathe) is overloaded | Only operator with cnc skill shared with others; HC11 weekly cap may bind |

Priority order for deeper investigation: **B3 > B1 > B4 > B2**.

## 4. Confirmation Questions (6)

Before committing to v1, please confirm or correct:

1. **Single shift?** The model assumes 1×8h shift/day, no overtime, no
   weekend. If the director wants a second shift, HORIZON doubles and the
   bottleneck structure changes dramatically.
2. **Setup time**: HC8 is approximated via HC20 ("max 1 type change per
   machine per day"). Is that acceptable for v1, or do we need explicit
   sequence-dependent setup times? (A3 in spec.)
3. **Operator daily cap**: A4 treats operator capacity as weekly aggregate,
   not strictly per-day. Is it OK if an operator runs 10h one day and 6h
   the next, as long as total ≤ 40h?
4. **Tool handling**: We assume a tool is held for the full op duration and
   release is instant. If actual changeover time is >5 min we under-count.
5. **Cross-day precedence**: HC16 assumes an op may start on a day strictly
   after the previous op finishes (no same-machine continuation). Is that
   preferred vs. "machine remembers setup"?
6. **Urgent window (HC19)**: strictly ≤ day 2, or "≤ day 3 but prefer day 2"?
   The strict version is modelled; the soft version would be an SC.

## 5. Data Health

- `operations.csv` has 249 rows, every op has 2-4 eligible machines and a
  non-empty duration.
- `jobs.csv` priority mix: 5 urgent / 10 high / 20 normal / 5 low
  (sum = 40 ✓).
- Capacity sanity check (total op minutes vs total machine minutes):
  lathe 5775 / 12000, milling 4650 / 9600, drilling 3600 / 7200,
  grinding 2490 / 4800, cnc 420 / 2400 — all within cap.
  → Feasibility is plausible modulo calendar + tool effects.

## 6. Next Step

Run `python scripts/staged_baseline.py` → generates
`results/baseline_results.json` and fills `reports/baseline_report.md`.
