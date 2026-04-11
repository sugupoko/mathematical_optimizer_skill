# Assessment Report — Hospital OR Scheduling v1

## Problem Classification

- **Class**: Resource-constrained scheduling with multi-resource coupling
- **Complexity**: **complex** (tightest example in the skill pack)
- **Coupling dimensions**: patient × OR × day × surgeon × anesth × nurse-pool × ICU-bed
- **Variables**: ~2,900 binaries + auxiliary integers
- **HC count**: 22, **SC count**: 8

## Why "complex"

1. 6 resource classes coupled per surgical case (not just staff-vs-time)
2. Specialty–equipment–qualification interlocks (cardiac↔bypass, pediatric↔ped-anesth↔ped-nurse)
3. Urgency windows on top of capacity
4. Day-level ICU capacity creates a cross-room coupling that prevents greedy per-OR solving
5. Surgeon weekly cap (HC13) is a global constraint that defeats day-by-day decomposition

## Staged approach is mandatory

One-shot CP-SAT on full (p,r,d,s,a,n) product is tractable at this size (50 patients)
but convergence is slow because SC1 (coverage) and SC2–SC8 are cheap to overshoot
and hard to prove optimal. We therefore use a staged baseline.

## Confirmation Questions (to the hospital director)

| # | Question | Why it matters |
|---|----------|----------------|
| Q1 | Can OR6 accept any surgery type, or is it reserved for urgent only? | Affects A6 relief valve |
| Q2 | Is HC16's 30-min cleaning always 30, or 60 for cardiac? | Affects OR1 capacity by ~150 min/week |
| Q3 | Can a pediatric anesthesiologist cover adult cases freely? | Changes pool-based HC14 modelling |
| Q4 | Is surgeon request (HC22) truly hard, or "strongly preferred"? | If soft, +5–10% coverage expected |
| Q5 | ICU bed count — is it post-op day-1 only, or multi-day occupancy? | A3 assumption confirmation |
| Q6 | If weekly surgeon cap is hit, can overtime be approved? | Affects HC13 relaxation options |

## Hypothesized Bottlenecks (pre-solve)

- **B1**: Surgeon S01 (cardiac) — 4 patients request them, total ~1170 min, fits within 2100 min but crowds single OR1.
- **B2**: OR5 pediatric room daily cap — 9 pediatric cases in 5 days ≈ 1.8/day avg, OK on average, tight on day 1–2 due to urgent P30, P34.
- **B3**: Neuro day-1 — P38 urgent + S13 unavailable day 1 → forces S12 on day 1 for P38 (300 min).
- **B4**: Vascular urgent P44 (260 min, ICU, day 1–2).

## Recommended next step

Run `/opt-baseline` with the 13-phase staged script below.
