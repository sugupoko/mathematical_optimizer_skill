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

## Usage

### 1. Hearing (before receiving data)

Hearing sheets are available under `reference/`. Print them out and use them on-site.

| Sheet | Target |
|-------|--------|
| `hearing_sheet_shift.md` | Shift scheduling operations |
| `hearing_sheet_routing.md` | Delivery routes and collection operations |

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
├── README.md                      <- This file
├── README_ja.md                   <- Japanese README
├── CLAUDE.md                      <- Detailed guide for Claude Code (Japanese)
├── OPTIMIZATION_MINDSET.md        <- 7 thinking patterns of optimization specialists (Japanese)
├── .claude/skills/                <- 6 skills
│   ├── opt-assess/                <- Problem assessment
│   ├── opt-baseline/              <- Baseline construction
│   ├── opt-improve/               <- Improvement design and testing
│   ├── opt-report/                <- Proposal generation
│   ├── opt-request/               <- Additional data request
│   └── opt-deploy/               <- Operations design (automation, monitoring, fallback)
├── reference/                     <- Implementation templates (Japanese)
│   ├── ortools_guide.md           <- OR-Tools guide (CP-SAT vs Routing)
│   ├── pulp_highs_guide.md        <- PuLP + HiGHS guide (LP/MIP)
│   ├── multiobjective_guide.md    <- Multi-objective optimization (Pareto front, epsilon-constraint)
│   ├── scheduling_template.py     <- Shift optimization code template
│   ├── vrp_template.py            <- Delivery route code template
│   ├── evaluator_template.py      <- Evaluation function template + alignment verification
│   ├── data_preprocessing.md      <- Data preprocessing (incl. large-scale distance matrices)
│   ├── improvement_patterns.md    <- 6 proven improvement patterns
│   ├── state_schema.md            <- Inter-skill state management schema
│   ├── hearing_templates.md       <- Hearing guide (intent behind each question)
│   ├── matching_template.py        <- Matching problem template (Gale-Shapley + CP-SAT)
│   ├── matching_guide.md           <- Matching problem guide
│   ├── ticket_assignment_template.py <- Ticket assignment template (LLM estimation + stagnation)
│   ├── ticket_assignment_guide.md <- Ticket assignment guide (ITSM, tiers, dynamic)
│   ├── hearing_sheet_shift.md     <- Fill-in sheet (shift scheduling)
│   ├── hearing_sheet_routing.md   <- Fill-in sheet (delivery routing)
│   ├── hearing_sheet_matching.md  <- Fill-in sheet (matching problems)
│   └── hearing_sheet_ticket.md    <- Fill-in sheet (ticket assignment)
└── workspace/                     <- Working directory
    └── examples/                  <- Sample data for E2E demos (shift, routing, matching)
```

## Supported Problem Types

- **Scheduling**: Shift tables, task assignment, timetabling
- **Routing**: Delivery routes, sales visits, pickup/delivery
- **Packing**: Container loading, warehouse layout
- **Matching**: Caregiver-patient, job placement, mentoring (bilateral preferences)
- **Ticket Assignment**: ITSM, bug tracking, customer support (dynamic task allocation)
- **Assignment**: Set cover, resource allocation, combinatorial selection

## Five Principles

1. **Try a solver first** -- Build a baseline in 5 minutes
2. **Read the evaluation function first** -- Understand what you're optimizing before writing code
3. **Align the objective function with the evaluation function** -- This alone yielded +15-27% improvement
4. **Always state your assumptions explicitly** -- Wrong assumptions lead to wrong results
5. **Say "impossible" when it is** -- Sometimes the most valuable recommendation is "add more vehicles"

## License

MIT

## Acknowledgment

This skill pack was developed in collaboration with Claude Code (Claude Opus 4.6). Content has been reviewed and edited by humans.
