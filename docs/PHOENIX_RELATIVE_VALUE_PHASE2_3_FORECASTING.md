# Phoenix Relative-Value Laboratory — Phase 2/3 Pair Science and Forecasting

**Status:** IMPLEMENTED, runtime verification pending  
**Authority:** research evidence only; no execution or promotion authority

## Phase 2 — Pair Laboratory

Implemented modules:

- `strategies/relative_value_lab/pair_lab.py`
- `strategies/relative_value_lab/pair_graph.py`
- `strategies/relative_value_lab/dataset.py`

The pair laboratory now provides:

- synchronized log-price relationship estimation;
- rolling OLS hedge ratio;
- explicit spread construction;
- return correlation as a diagnostic;
- AR(1) spread dynamics;
- OU-style mean-reversion speed;
- mean-reversion half-life;
- structural-break proxy;
- composite relationship stability;
- N*(N-1)/2 basket pair graph;
- leakage-safe historical features under the *current frozen hedge relationship*.

Important boundary:

Pair stability is a research filter. It is not evidence of profitability.

## Phase 3 — Forward Forecast Engine

Implemented modules:

- `strategies/relative_value_lab/forecast.py`
- `strategies/relative_value_lab/settlement.py`
- `strategies/relative_value_lab/evaluation.py`

### Structural baseline

`relative_value_ou_mean_reversion_v1`

The OU-style baseline forecasts the future change in the fitted pair spread over a declared horizon.

It reports:

- signed expected relative move;
- direction;
- uncertainty when supplied;
- expected spread/route cost input;
- expected post-cost edge;
- abstention when relationship or economics fail.

It always remains `execution_eligible=false`.

### Prospective settlement

`ProspectiveForecastSettler` freezes:

- forecast timestamp;
- pair identity;
- hedge relationship represented by the entry state;
- declared horizon;
- expected cost.

It refuses settlement before the target timestamp.

### Leakage-safe dataset

The forecast dataset supports:

- 10s;
- 30s;
- 60s;
- 120s future labels.

For each example, relationship parameters use observations at or before t.

Future labels use the **frozen time-t alpha/beta**, not a relationship refit using future data.

Past spread-return features are also recomputed under the current frozen alpha/beta so changing hedge estimates cannot masquerade as market motion.

### Outcome-lag-aware walk-forward evaluation

The expanding ridge challenger obeys a stronger rule than an ordinary chronological train/test split:

> a historical training example is admitted only after its own target label timestamp is <= the current forecast timestamp.

This prevents overlapping high-frequency future labels from leaking into training.

## Baselines

Every walk-forward evaluation includes:

- `baseline_zero_v1`
- `baseline_continuation_v1`
- `baseline_reversal_v1`
- `relative_value_ou_mean_reversion_v1`
- `relative_value_expanding_ridge_v1`

A more complex Phoenix model must demonstrate incremental forecast value over these controls.

## Current cost fidelity

The dataset currently stores:

`pair_spread_cost_bps_proxy = 0.5 * (USD spread A + USD spread B)`

This approximates crossing two USD books from mid and is **not** a full fee, depth, latency, or direct-pair execution model.

Therefore:

- gross forecast skill is currently the primary scientific target;
- `directional_after_spread_proxy_bps` is diagnostic only;
- no final post-cost profitability claim may be made from this proxy.

Full route/fee/depth economics remain a later execution-realism phase.

## Local commands

Collect public microstructure evidence:

```bash
python scripts/run_relative_value_microstructure_observer.py \
  --duration-sec 1800 \
  --interval-sec 5
```

Build the forecast dataset:

```bash
python scripts/build_relative_value_forecast_dataset.py \
  --database data/relative_value_microstructure.db \
  --relationship-window-samples 120 \
  --minimum-relationship-samples 60 \
  --horizons 10 30 60 120
```

Run walk-forward evaluation:

```bash
python scripts/run_relative_value_walk_forward_evaluation.py \
  --dataset data/relative_value_forecast_dataset.jsonl \
  --horizons 10 30 60 120
```

## Runtime verification gate

Before any empirical interpretation:

```bash
python -m py_compile \
  strategies/relative_value_lab/contracts.py \
  strategies/relative_value_lab/microstructure.py \
  strategies/relative_value_lab/pair_lab.py \
  strategies/relative_value_lab/pair_graph.py \
  strategies/relative_value_lab/forecast.py \
  strategies/relative_value_lab/settlement.py \
  strategies/relative_value_lab/dataset.py \
  strategies/relative_value_lab/evaluation.py \
  strategies/relative_value_lab/research_council.py \
  scripts/run_relative_value_microstructure_observer.py \
  scripts/report_relative_value_microstructure.py \
  scripts/build_relative_value_forecast_dataset.py \
  scripts/run_relative_value_walk_forward_evaluation.py

python -m pytest -q \
  tests/test_relative_value_lab_authority.py \
  tests/test_relative_value_lab_math.py \
  tests/test_relative_value_forecast.py \
  tests/test_relative_value_settlement.py \
  tests/test_relative_value_research_council.py \
  tests/test_relative_value_dataset.py \
  tests/test_relative_value_walk_forward.py
```

No PASS is claimed until these execute in the repository runtime.

## Phase 2/3 acceptance checklist

- [x] pair relationship contract
- [x] hedge ratio and spread
- [x] OU-style dynamics
- [x] half-life
- [x] structural-break proxy
- [x] pair graph
- [x] frozen future labels
- [x] no-lookahead settlement
- [x] boring forecast baselines
- [x] expanding regularized linear challenger
- [x] outcome-lag-aware walk-forward rule
- [x] research-only authority
- [ ] local py_compile confirmed
- [ ] local pytest confirmed
- [ ] real public dataset collected
- [ ] first out-of-sample skill report generated

## Next phase

After runtime verification and initial data collection:

1. quantify whether OU or ridge predicts future relative movement above no-skill controls;
2. add flow-exhaustion/event features only if they add out-of-sample information;
3. calibrate prediction intervals and probability-positive estimates;
4. add route-aware direct-pair execution costs;
5. keep Ollama advisory evidence outside the numeric forecast target;
6. freeze a candidate before prospective Experiment E.
