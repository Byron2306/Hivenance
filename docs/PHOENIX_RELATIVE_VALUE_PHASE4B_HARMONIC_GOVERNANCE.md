# Phoenix Relative-Value Laboratory — Phase 4B Harmonic Forecast Governance

**Status:** IMPLEMENTED, runtime verification pending  
**Authority:** research filter only; no execution or promotion authority

## Origin

This layer adapts the concepts of Metatron's Harmonic Governance Layer to Phoenix forecasting.

Metatron source concepts inspected:

- `backend/services/harmonic_engine.py`
  - online cadence windows
  - resonance
  - discord
  - confidence
  - drift
  - jitter
  - burstiness
  - entropy
  - scoped baselines
- `docs/HARMONIC_ONTOLOGY.md`
  - harmonic fields are descriptive control signals
  - they are not identity proofs
  - they are not stand-alone verdicts
  - low confidence must not greenlight sensitive action

Phoenix preserves those semantic boundaries.

Phoenix does **not** copy Metatron's action-cadence timing thresholds. Market forecasts use their own forecast history and cadence.

## Purpose

Phoenix now has several forecast voices:

- structural mean reversion / OU
- expanding statistical ridge
- control reversal / continuation baselines
- future flow-exhaustion models
- future Horizon-conditioned models
- future worker/federated challengers

A simple average can conceal useful dissent.

Harmonic Forecast Governance asks a different question:

> Is the current forecast choir coherent, temporally stable, sufficiently diverse, and supported by enough evidence to be treated as a meaningful research state?

It never asks:

> May a live order be sent?

## New module

`strategies/relative_value_lab/harmonic_governance.py`

Core objects:

- `HarmonicForecastVoice`
- `HarmonicSpectrum`
- `HarmonicForecastReceipt`
- `HarmonicGovernanceConfig`
- `HarmonicForecastGovernance`

## Anti-clone rule

Global resonance allows **one vote per registered independent model family**.

Current registered families:

| Model | Family | Global vote |
|---|---|---|
| relative_value_ou_mean_reversion_v1 | structural | yes |
| relative_value_expanding_ridge_v1 | statistical | yes |
| baseline_zero_v1 | control | no |
| baseline_continuation_v1 | control | no |
| baseline_reversal_v1 | control | no |

A family emitting 10s, 30s, 60s and 120s predictions still receives one global family vote.

Unknown challenger models are explicit but receive no independent vote until registered.

This prevents clone amplification.

## Forecast spectrum

Horizon bands:

- **micro:** <= 10s
- **meso:** >10s and <=60s
- **macro:** >60s

Each band computes family-deduplicated resonance when at least two independent families are available.

The receipt therefore exposes:

- micro resonance
- meso resonance
- macro resonance
- global resonance

## Harmonic features

### Cross-family agreement

Directional agreement after one-vote-per-family de-duplication.

### Forecast entropy

Binary directional entropy among active independent families.

High entropy means the choir is split.

### Magnitude dispersion

Normalized disagreement in predicted move magnitude.

### Forecast jitter

Volatility of changes in the pair's aggregate forecast through time.

### Direction flip rate

How frequently the aggregate forecast direction changes sign.

### Forecast drift

Difference between early and later forecast levels in the rolling history.

### Confidence burstiness

Detects clusters of unusually high agreement relative to the pair's own recent agreement baseline.

This is intended to catch short-lived apparent consensus that may be unstable.

## States

The deterministic harmonic state is one of:

- `RESONANT`
- `MIXED`
- `DISCORDANT`
- `DRIFTING`
- `INSUFFICIENT`

A `RESONANT` state requires:

- enough independent registered families;
- resonance above the configured floor;
- discord below the configured ceiling;
- confidence above the configured floor;
- a non-abstaining harmonic direction.

These are research classifications only.

## Control dissent

Zero/continuation/reversal baselines are retained inside the receipt as control testimony.

They do not vote.

The receipt records whether each directional control agrees with the harmonic direction.

## Authority boundary

Phoenix authority component:

`relative_value_harmonic_governance`

Role:

`forecast_coherence_and_dissent_governor`

Mode:

`research_filter_only`

It has:

- execution authority: none
- promotion authority: none
- resume authority: none
- scaling authority: none
- live allowed: false

Its receipts also carry:

- `execution_eligible=false`
- `promotion_eligible=false`

## Retrospective discovery CLI

Existing walk-forward prediction artifacts can be passed through the harmonic governor:

```bash
python scripts/run_relative_value_harmonic_governance.py
```

Inputs:

`data/relative_value_walk_forward_predictions.jsonl`

Outputs:

- `data/relative_value_harmonic_receipts.jsonl`
- `data/relative_value_harmonic_governance_report.json`

The report includes descriptive realized gross outcomes for forecasts that would have been labelled `RESONANT`.

### Scientific boundary

Running Harmonic Governance on the existing one-hour dataset is **retrospective discovery**.

If the harmonic subset looks better, that does not validate the gate.

Any thresholds or model-family definitions selected from this run must be frozen and faced against a fresh prospective public-market run before a research-support verdict.

## Tests

`tests/test_relative_value_harmonic_governance.py`

Tests cover:

- controls cannot become independent voices;
- one family cannot earn multiple global votes through multiple horizons;
- registered independent family agreement can produce resonance;
- forecast sign-flipping creates cadence risk;
- an unregistered challenger cannot silently gain an independent vote;
- receipts remain execution/promotion ineligible.

The central Phoenix authority test also includes the harmonic component.

## Phase 4 programme

### Phase 4A — Exhaustion-Reversion Event Study

Test whether large spread displacement plus microstructure exhaustion selects materially larger reversals than unconditional reversal.

### Phase 4B — Harmonic Forecast Governance

**Implemented.**

Determine whether forecast-family coherence and temporal stability contain incremental information.

### Phase 4C — Forecast Choir and Dissent Receipts

Extend receipts with:

- flow-exhaustion voice
- Horizon-conditioned voice
- worker/federated challenger voice
- optional Ollama research critique as non-voting testimony

### Phase 4D — Prospective Gate

Freeze:

- independent family registry
- harmonic thresholds
- event-study trigger
- forecast models
- horizons

Then face unseen public-market evidence.

## Success criterion

Harmonic Governance is useful only if prospective `RESONANT` states produce better calibrated and/or economically larger future relative movement than:

- the ungated candidate forecasts;
- simple reversal;
- matched random events;
- abstention/no-action controls.

If it merely makes existing results look prettier retrospectively, it fails.
