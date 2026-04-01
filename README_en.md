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

1. **Classifies messy input data** into problem types (scheduling? routing? assignment?)
2. **Builds a baseline in 5 minutes** and identifies the bottleneck
3. **Designs and tests improvements** matched to the bottleneck (with code templates)
4. **Generates management-ready proposals** (cost, impact, and implementation difficulty comparisons)
5. **Produces data request documents** explaining what's needed, why, and the consequences of not having it
6. **Designs operations** (automation, monitoring, fallback procedures)

Additionally, on-site hearing sheets (with fill-in fields) help **surface implicit constraints not captured in the data**.

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

## Quick Start (try with sample data)

`workspace/examples/` contains 6 sample projects (synthetic data). Each includes `solve_all.py` (single script) and `reports/` (full documentation).

| Example | Description | Key Finding |
|---------|-------------|-------------|
| `shift_scheduling/` | 10 employees x 7 days | Supply < demand: structural shortage proven |
| `delivery_routing/` | 20 customers x 3 vehicles | AM/PM split covers all customers |
| `care_matching/` | 15 receivers x 10 caregivers | 7/7 continuity maintained, 100% same-district |
| `ticket_assignment/` | 20 engineers x 80 tickets | Blocked slot release + stagnation detection |
| `facility_location/` | 10 candidates x 30 stores | CFL optimal: 4 warehouses, 62% cost reduction |
| `structural_design/` | Cantilever beam + topology | 96.2% weight reduction via SLSQP + SIMP |

```bash
# Run skills sequentially
/opt-assess workspace/examples/shift_scheduling/data/
/opt-baseline workspace/examples/shift_scheduling/data/

# Or run the all-in-one script
python workspace/examples/shift_scheduling/scripts/solve_all.py
```

See [workspace/examples/examples_readme.md](./workspace/examples/examples_readme.md) for details.

## Usage

### 1. Hearing (before receiving data)

Hearing sheets are available under `reference/`. Print them out and use them on-site.

| Sheet | Target |
|-------|--------|
| `hearing_sheet_shift.md` | Shift scheduling operations |
| `hearing_sheet_routing.md` | Delivery routes and collection operations |
| `hearing_sheet_matching.md` | Matching problems (caregiving, hiring, etc.) |
| `hearing_sheet_ticket.md` | Ticket assignment (ITSM, support, etc.) |

### 2. Once you receive the data

```bash
mkdir -p workspace/my_project/data
cp /path/to/client_data.xlsx workspace/my_project/data/
```

Run the following skills in order within Claude Code:

```
/opt-assess workspace/my_project/data/     -> Problem classification and hypotheses
/opt-baseline workspace/my_project/data/   -> 3 baselines + bottleneck identification
/opt-improve workspace/my_project/data/    -> Design and test improvements (iterative)
/opt-report workspace/my_project/results/  -> Management-ready proposal
/opt-deploy workspace/my_project/          -> Operations design (automation, monitoring)
```

If data is missing along the way, use `/opt-request` to generate a request document.

## Directory Structure

```
mathematical_optimizer_skill/
├── README.md                      <- Japanese README (main)
├── README_en.md                   <- This file (English)
├── CHANGELOG.md                   <- Changelog (bilingual)
├── CLAUDE.md                      <- Detailed guide for Claude Code (Japanese)
├── OPTIMIZATION_MINDSET.md        <- 7 thinking patterns (Japanese + LLM checklists)
├── .claude/skills/                <- 6 skills
│   ├── opt-assess/                <- Problem assessment
│   ├── opt-baseline/              <- Baseline construction
│   ├── opt-improve/               <- Improvement design and testing
│   ├── opt-report/                <- Proposal generation
│   ├── opt-request/               <- Additional data request
│   └── opt-deploy/               <- Operations design
├── reference/                     <- Templates and guides (Japanese)
│   ├── scheduling_template.py     <- Shift optimization (CP-SAT)
│   ├── vrp_template.py            <- Delivery routing (OR-Tools Routing)
│   ├── matching_template.py       <- Matching (Gale-Shapley + CP-SAT)
│   ├── ticket_assignment_template.py <- Ticket assignment (LLM + stagnation)
│   ├── facility_location_template.py <- Facility location (UFL/CFL/P-median)
│   ├── continuous_optimization_template.py <- Structural design (scipy + SIMP)
│   ├── evaluator_template.py      <- Evaluation function + alignment verification
│   ├── ortools_guide.md           <- OR-Tools (CP-SAT vs Routing)
│   ├── pulp_highs_guide.md        <- PuLP + HiGHS (LP/MIP)
│   ├── multiobjective_guide.md    <- Multi-objective (Pareto, epsilon-constraint)
│   ├── matching_guide.md          <- Matching problem guide
│   ├── ticket_assignment_guide.md <- Ticket assignment guide
│   ├── facility_location_guide.md <- Facility location guide
│   ├── continuous_optimization_guide.md <- Continuous optimization guide
│   ├── literature_guide.md        <- Literature survey guide (by problem class)
│   ├── data_preprocessing.md      <- Data preprocessing + large-scale matrices
│   ├── improvement_patterns.md    <- 6 proven improvement patterns
│   ├── state_schema.md            <- Inter-skill state management
│   ├── hearing_templates.md       <- Hearing guide
│   └── hearing_sheet_*.md         <- Fill-in sheets (shift/routing/matching/ticket)
└── workspace/
    ├── examples/                  <- 6 E2E sample projects
    │   ├── shift_scheduling/      <- 10 employees x 7 days
    │   ├── delivery_routing/      <- 20 customers x 3 vehicles
    │   ├── care_matching/         <- 15 receivers x 10 caregivers
    │   ├── ticket_assignment/     <- 20 engineers x 80 tickets
    │   ├── facility_location/     <- 10 candidates x 30 stores
    │   └── structural_design/     <- Beam design + topology optimization
    └── my_project/                <- Your project folder
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
