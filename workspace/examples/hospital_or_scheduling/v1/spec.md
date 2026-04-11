# Hospital Operating Room Scheduling — v1 Specification

**Project**: hospital_or_scheduling
**Version**: v1 (initial)
**Date**: 2026-04-11
**Audience**: Hospital director, OR manager, chief surgeon

## 1. Business Context

A 6-OR tertiary hospital needs to schedule a one-week backlog of 50 patients across
15 surgeons, 10 anesthesiologists and 20 OR nurses, subject to specialty equipment,
staff qualification, daily/weekly capacity, ICU bed availability and urgency windows.

## 2. Sources (Ref Traceability)

- **R1**: `data/operating_rooms.csv` — 6 ORs with equipment flags and open minutes
- **R2**: `data/surgeons.csv` — 15 surgeons, 6 specialties, weekly caps
- **R3**: `data/anesthesiologists.csv` — 10 anesthesiologists, 4 pediatric-qualified
- **R4**: `data/nurses.csv` — 20 OR nurses, all scrub+circulator, 5 pediatric-qualified
- **R5**: `data/patients.csv` — 50 patients with priority/ICU/pediatric flags
- **R6**: `data/icu_beds.csv` — 4–6 post-op ICU beds per day (bottleneck)
- **R7**: `data/constraints.csv` — 22 HCs / 8 SCs catalog

## 3. Decision Variables

| Variable | Domain | Meaning |
|----------|--------|---------|
| `assign[p,r,d]` | {0,1} | Patient p in OR r on day d |
| `sched[p]` | {0,1} | Patient p is scheduled (= sum over r,d of assign) |
| `surgeon[p,s]` | {0,1} | Surgeon s operates on p |
| `anesth[p,a]` | {0,1} | Anesthesiologist a on p |
| `nurse_load[n,d]` | int | Aggregate minutes nurse n is loaded on day d |

Total vars ≈ 50·6·5 + 50·15 + 50·10 + 50 + 20·5 = 1500 + 750 + 500 + 50 + 100 ≈ **2900 binaries + aux**.

## 4. Hard Constraints (22) — see `data/constraints.csv`

HC1–HC22 as catalogued (Ref: R7). Encoded in `scripts/staged_baseline.py`.

## 5. Soft Objectives (8)

Weighted sum (balanced default):

```
maximize  10*SC1 - 1*SC2 - 1*SC3 - 1*SC4 - 0.5*SC5 + 2*SC6 + 3*SC7 - 1*SC8
```

## 6. A-rules (Documented Assumptions / Simplifications)

- **A1**: Time is modelled at **(OR, day) aggregate level**; no start_time per case.
  HC16 cleaning gap is absorbed as `+30 min overhead per case` in OR capacity (R1).
- **A2**: Nurse assignment is modelled as **aggregate load per day** (count and pediatric
  flag checked via constants). We do not enforce individual scrub/circulator identity
  per case — instead we require the daily pool to have sufficient qualified heads.
- **A3**: ICU stay is assumed 1 day (discharge next morning), so HC20 checks the day of surgery only.
- **A4**: Urgent window HC21 uses `[earliest_day, min(earliest_day+1, latest_day)]`.
- **A5**: `requested_surgeon` (HC22) is **hard** when specified; SC6 is ignored for those.
- **A6**: OR6 ("Urgent-Flex") has 600 min open instead of 480 to act as relief valve.
- **A7**: A patient is pediatric iff `is_pediatric = True`; such cases must go to an OR with
  `has_pediatric_eq = True` (only OR5, OR6).
- **A8**: Cardiac cases (specialty_required=cardiac) must use OR1 only (the sole bypass room).
- **A9**: Model does not enforce individual surgeon continuity across a day — a surgeon may
  operate on multiple patients as long as daily/weekly minute caps hold.

## 7. Known Tight Spots (Hypothesized)

1. **OR1 (cardiac)** — 5 cardiac cases totalling ~1400 min; 5 days × 480 = 2400 min capacity
   but surgeon S01 has only 2100 min/week and 4 of 5 cardiacs want S01 → **surgeon bottleneck**.
2. **Pediatric rooms (OR5/OR6)** — 9 pediatric cases but pediatric anesth only 4 and
   pediatric nurses only 5; daily caps may bite.
3. **ICU beds** — ~18 ICU-requiring patients vs 24 bed-days → feasible but tight, urgency constrains day choice.
4. **Neuro** — 5 long neuro cases, 2 surgeons, one has day-1 unavailability.

## 8. Change Log

- v1: initial model, assumptions A1–A9 applied.
