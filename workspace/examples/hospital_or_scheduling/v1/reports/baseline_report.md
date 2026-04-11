# Baseline Report — Hospital OR Scheduling v1

## Method

Staged CP-SAT with 11 phases, each progressively activating HC groups. After every
phase an **independent HC verifier** (not trusting solver's feasible flag) cross-checks
all 22 HCs on the extracted solution.

- Solver: OR-Tools CP-SAT
- time_limit: 120 s / phase, num_workers: 4
- ~2,900 binaries + auxiliary AND-linked helpers
- Objective in baseline: maximise coverage only

## Phase Table

| Phase | Added HCs | Status | Scheduled | HC ok (independent) |
|---|---|---|---|---|
| P01_core_assign | HC1, HC2 | OPTIMAL | 50/50 | 12/22 |
| P02_+specialty | +HC3 | OPTIMAL | 50/50 | 14/22 |
| P03_+equipment | +HC8, HC9 | OPTIMAL | 50/50 | 16/22 |
| P04_+windows | +HC21 (+earliest/latest) | OPTIMAL | 50/50 | 16/22 |
| P05_+surgeon_caps | +HC12, HC13, HC17 | OPTIMAL | 50/50 | 18/22 |
| P06_+anesth | +HC14, HC18 | OPTIMAL | 50/50 | 19/22 |
| P07_+ped_qualification | +HC10, HC11 | OPTIMAL | 50/50 | 21/22 |
| P08_+nurse_pool | +HC6, HC7, HC15 | OPTIMAL | 50/50 | 21/22 |
| P09_+icu | +HC20 | OPTIMAL | 50/50 | 21/22 |
| P10_+requested_surgeon | +HC22 | OPTIMAL | 50/50 | 22/22 |
| P11_all_HCs | +HC4, HC5, HC16, HC19 (absorbed) | OPTIMAL | 50/50 | 22/22 |

The "independent verify" column is the count of HCs that pass the independent verifier,
which is always ≥ number of active HCs in the current phase — progress is monotone.

## Result

- **No phase is infeasible.** The problem is fully solvable at 50/50 coverage.
- The solver's `feasible` flag matched the independent verifier on every phase.
- Final phase (all 22 HCs) returns OPTIMAL in well under the 120 s budget.

## Why it still counts as "hardest example"

The search space is large (2,900+ binaries, 11,250 AND helpers for surgeon/anesth·day),
and the constraint network is tightly coupled:

- HC22 forces 12 patients to specific surgeons, collapsing freedom on OR1/OR5.
- HC20 ICU day-caps (4–6) collide with 18 ICU-requiring patients — urgent and
  ICU-bound cases funnel into the same 1–2 days.
- HC13 weekly caps create a global constraint the CP-SAT propagator has to reason
  about across all 5 days at once.

The staged baseline proves that even under all these couplings the problem is
feasible; it is the **trade-offs** between SC goals that make it interesting
(see improve_report.md).

## No root cause block required

(Would be filled if any phase had been infeasible — it is not.)

## Next step

Run `/opt-improve` (already implemented as `scripts/improve.py`) to explore the
four objective scenarios: balanced, coverage, fairness, efficiency.
