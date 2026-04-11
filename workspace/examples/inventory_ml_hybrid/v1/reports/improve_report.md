# Improve Report — Four Scenarios Over Phase-10 Baseline

The full 18-constraint CP-SAT model was solved under four objective-weighting
scenarios (trips / waste / stockout). The optimiser is free to choose the case
mix; the service level (HC01) is always met.

## Weights

| Scenario | trips | waste | stockout |
|---|---|---|---|
| cost_min     | 100 |  10 |  50 |
| service_max  |  10 |   5 | 500 |
| waste_min    |  20 | 200 |  30 |
| balanced     |  60 |  60 |  60 |

## Results

| Scenario     | Status | Time | Trips | Cases | Inv cost | Waste cost | Stockout cost | Total | SL |
|---|---|---|---|---|---|---|---|---|---|
| cost_min     | OPTIMAL  | 0.4s | 5 | 3,483 | 7,424k | 105k |   0k | 7,580k | 100% |
| service_max  | OPTIMAL  | 1.0s | 5 | 3,487 | 7,428k | 105k |   0k | 7,584k | 100% |
| waste_min    | FEASIBLE | 30s  | 5 | 3,353 | 7,214k |   0k | 481k | 7,744k | 100% |
| balanced     | OPTIMAL  | 0.4s | 5 | 3,406 | 7,284k |  35k | 285k | 7,654k | 100% |

- **cost_min** yields the lowest headline total cost by pushing inventory to the
  minimum feasible level. It tolerates 1,202 units of perishable waste.
- **waste_min** eliminates waste entirely by ordering *below* the safety buffer
  (it swaps waste for stockout cost). Useful when the supplier can do an
  emergency run, not for v1.
- **service_max** is cost-equivalent to cost_min here because the safety stock
  requirement already forces SL=100% against the model's own requirement.
- **balanced** is the recommended default: it spreads the risk evenly.

## Trip count collapsed from 15 to 5

The baseline returned 15 trips because it had no objective. Adding a `trips *
weight` term in the improve scenarios drops the solver to 5 consolidated trips
— a 3x improvement achieved by letting the solver pack more SKUs per supplier
per delivery day and reusing trucks across suppliers where allowed.

## Bottleneck analysis

After improve, the binding constraints are:
1. **HC01 (service level)** — hits the floor for the cheapest scenarios.
2. **HC11 (fresh shelf life)** — caps fresh orders per store per day to 50% of
   storage. Active during waste_min (solver tries to spread fresh across days).
3. **HC13 (refrig truck requirement)** — forces dairy/deli to T04/T05 only.

Storage capacity (HC03) and dock window (HC17) are never active — plenty of
headroom at this scale.

## Artefacts

- `scripts/improve.py`
- `results/improve_results.json`
