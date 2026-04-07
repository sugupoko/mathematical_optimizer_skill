**[日本語版はこちら (README.md)](./README.md)**

---

# Mathematical Optimizer Skill Pack

> **Note**: This was created while studying mathematical optimization. It has only been validated with synthetic data, and its real-world applicability is unverified. Please treat this as a reference for the general approach.

A skill pack for performing mathematical optimization with Claude Code.

Drawing on experiments with factory shift scheduling (25 methods compared) and delivery route optimization (5 difficulty levels x 9 methods), this pack distills **7 thinking patterns of optimization specialists into reusable skills**.

When asked to "optimize a shift schedule" or "improve delivery routes," these skills provide a **reproducible workflow from data intake to improvement proposals**.

## Who This Is For

- Anyone wondering "I want to do optimization, but where do I start?"
- People familiar with OR-Tools but lacking a structured analysis-to-proposal workflow
- Consultants who receive data from operations teams and deliver proposals to management

## What It Does

With your data and a single instruction like "optimize this," the following happens automatically:

1. Classifies the problem type (scheduling? routing? assignment?)
2. Builds a baseline and identifies the bottleneck
3. Designs and tests improvements
4. Generates a management-ready proposal
5. Produces data request documents if anything is missing

## Language

- **Documentation**: English (this file), Japanese (CLAUDE.md, reference/)
- **Skills and hearing sheets**: Written in Japanese, optimized for the Japanese consulting market
- CLAUDE.md project guide and all reference materials under `reference/` are in Japanese

## Setup

```bash
git clone https://github.com/xxx/mathematical_optimizer_skill.git
cd mathematical_optimizer_skill
pip install ortools omegaconf matplotlib numpy pandas pulp scipy
```

Open this folder in Claude Code to get started.

## Quick Start — 3 Steps

### 1. Place your data

Put your files in `workspace/my_project/data/`. Hearing notes, existing schedules, etc. Excel or CSV.
If you need to conduct hearings first, see `reference/hearing_templates.md`.

```bash
mkdir -p workspace/my_project/data
cp your_data.xlsx workspace/my_project/data/
```

### 2. Tell Claude Code

```
Optimize the data in workspace/my_project/data/
```

That's it. Claude will determine the problem type and run analysis → baseline → improvement.

> **For finer control**, call individual skills: `/opt-assess`, `/opt-baseline`, etc.

### 3. See results

```
workspace/my_project/
├── v1/                <- Each version is a complete snapshot
│   ├── spec.md        <- Specification (constraints & assumptions for this version)
│   ├── data/          <- Input data
│   ├── scripts/       <- Execution scripts
│   ├── results/       <- Numerical results
│   └── reports/       <- Proposals & reports (deliver these to clients)
├── v2/                <- New version when data/constraints change
│   ├── spec.md        <- Updated spec (with diff from previous version)
│   └── ...
└── ...
```

---

### Try with sample data

Sample data is included. Just type this in Claude Code:

```
Optimize the data in workspace/examples/shift_scheduling/data/
```

| Example | Description | One-liner |
|---------|-------------|-----------|
| `shift_scheduling/` | 10 employees x 7 days | Proves staffing shortage with math |
| `delivery_routing/` | 20 customers x 3 vehicles | AM/PM split covers all |
| `care_matching/` | 15 receivers x 10 caregivers | Maintains continuity while optimizing |
| `ticket_assignment/` | 20 engineers x 80 tickets | Auto-reassigns stagnant tickets |

See [workspace/examples/examples_readme.md](./workspace/examples/examples_readme.md) for details.

## Directory Structure

```
mathematical_optimizer_skill/
├── .claude/skills/    <- 6 skills (Claude references these automatically)
├── reference/         <- Templates, guides, hearing sheets
└── workspace/         <- Work here
    ├── examples/      <- Sample data (ready to try)
    └── my_project/    <- Create your project here
```

## Supported Problem Types

### Templates + Examples Available (ready to use)

| Domain | Real-World Problems | Method |
|--------|-------------------|--------|
| **Shift Scheduling** | Factory, hospital, call center shift tables | CP-SAT |
| **Delivery Routing** | Package delivery, sales visits, waste collection | OR-Tools Routing |
| **Matching** | Caregiver-patient, job placement, mentoring, organ transplant | Gale-Shapley / CP-SAT |
| **Ticket Assignment** | ITSM, bug tracking, customer support | CP-SAT + LLM estimation |
| **Facility Location** | Warehouse placement, retail stores, EV charging, base stations | PuLP (MIP) |
| **Continuous Optimization** | Structural design, shape optimization, parameter tuning | scipy.optimize |

### Guides Available (adaptable with existing templates)

| Domain | Real-World Problems | Template to Use |
|--------|-------------------|----------------|
| **Production Planning** | Product mix, raw material allocation | PuLP (LP/MIP) |
| **Job Shop Scheduling** | Machine x job sequencing in factories | scheduling_template |
| **Timetabling** | School class x room x teacher | scheduling_template |
| **Inventory Optimization** | Order quantities, safety stock | PuLP + simulation |
| **Packing** | Container loading, warehouse layout | CP-SAT / heuristics |
| **Transportation** | Inter-depot shipment allocation | PuLP (LP) |
| **Portfolio** | Investment allocation, risk minimization | scipy (quadratic) |

### Real-World Problem Map

```
┌─ Manufacturing ──────────────────────────────┐
│  Shift tables, production planning, job shop  │
│  Inventory management, quality parameter opt   │
├─ Logistics & Retail ─────────────────────────┤
│  Delivery routes, warehouse placement          │
│  Transportation planning, container loading    │
├─ IT & Telecom ───────────────────────────────┤
│  Ticket assignment, cloud resource allocation  │
│  Network design, base station placement        │
├─ Healthcare & Welfare ───────────────────────┤
│  Care matching, OR scheduling                  │
│  Vaccine distribution, ambulance placement     │
├─ Finance ────────────────────────────────────┤
│  Portfolio optimization, loan review assignment│
├─ Energy ─────────────────────────────────────┤
│  Power generation planning, EV charging sched  │
├─ Education ──────────────────────────────────┤
│  Timetabling, exam proctor assignment          │
├─ Engineering ────────────────────────────────┤
│  Structural design, shape optimization         │
│  Topology optimization, process parameters     │
└──────────────────────────────────────────────┘
```

## Five Principles

1. **Try a solver first** -- Build a baseline in 5 minutes
2. **Read the evaluation function first** -- Understand what you're optimizing before writing code
3. **Align the objective function with the evaluation function** -- This alone yielded +15-27% improvement
4. **Always state your assumptions explicitly** -- Wrong assumptions lead to wrong results
5. **Say "impossible" when it is** -- Sometimes the most valuable recommendation is "add more vehicles"

## For Beginners — Advice from Your AI Teacher (Claude)

> Templates and guides are ready. But **the real learning starts now.**

This skill pack is a **toolbox**, not an answer key.
When you run it on real data, you will inevitably encounter:

```
❶ "This constraint was actually soft"
   → The on-site team said "we'd prefer to follow it, but it's not mandatory"
   → Change from hard to soft constraint, adjust weights

❷ "This assumption was wrong"
   → Assumed 30 km/h travel speed, actual measurement was 22 km/h
   → Replace assumption with real data, re-run from /opt-baseline

❸ "The real scale is much larger"
   → Sample of 20 worked fine, but 2,000 real data points are too slow
   → Choose a decomposition strategy (clustering, AM/PM split, etc.)

❹ "The operations team won't use the optimized results"
   → Mathematically optimal, but missed an implicit rule
   → Use hearing sheets to surface tacit knowledge, add as constraints
```

This is not failure — it's the **normal optimization cycle**:

```
  Receive data → Make assumptions → Solve → Show results
       ↑                                       ↓
       └──── Revise assumptions ← Feedback ←───┘
```

The key to success is **spinning this cycle fast**.
The skill pack is your tool for "completing the first cycle in 5 minutes."
From the second cycle onward, on-site feedback becomes your best teacher.

**Start by running one of the 6 sample projects.** Each covers a different problem type.

## License

MIT

## Acknowledgment

This skill pack was developed in collaboration with Claude Code (Claude Opus 4.6). Content has been reviewed and edited by humans.
