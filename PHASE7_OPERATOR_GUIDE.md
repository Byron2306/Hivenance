# Hivenance Phoenix Phase 7 Operator Guide

## Purpose

Phase 7 converts the USD 5 Phase-6 canary into a human-governed growth ladder. It does not grant Hivenance permission to scale itself.

The release ships locked:

```text
phase7_stage_activation_enabled: false
phase6_live_submission_enabled: false
HIVENANCE_PHASE7_CONTROLLED_GROWTH: absent
HIVENANCE_PHASE6_LIVE_SUBMISSION: absent
active growth proposal: none
active growth approval: none
```

## Growth ladder

| Stage | Notional cap | Allowlist | Open positions | Minimum fresh evidence |
|---|---:|---|---:|---|
| CANARY | USD 5.00 | ETH/USD | 1 | Existing Phase-6 canary |
| EMBER | USD 7.50 | ETH/USD | 1 | 50 new round trips, 14 days |
| FLAME | USD 10.00 | ETH/USD, BTC/USD | 1 | 50 new round trips, 14 days |
| WING | USD 15.00 | ETH/USD, BTC/USD | 1 | 50 new round trips, 14 days |
| CROWN | USD 20.00 | ETH/USD, BTC/USD, SOL/USD | 1 | 50 new round trips, 14 days |

Only one stage may be crossed at a time.

## Validate the lineage

```bash
python scripts/phase0_preflight.py
python scripts/phase1_preflight.py
python scripts/phase2_preflight.py
python scripts/phase3_preflight.py
python scripts/phase4_preflight.py
python scripts/phase5_preflight.py
python scripts/phase6_preflight.py
python scripts/phase7_preflight.py
python -m pytest -q
```

## Inspect status safely

No credentials are required:

```bash
python scripts/run_phase7_growth.py --status
```

The desktop **Growth Governor** page is also read-only.

## Proposal sequence

A proposal is possible only when genuine Phase-6 or current-stage evidence satisfies every gate.

```bash
python scripts/run_phase7_growth.py \
  --propose-next-stage \
  --proposed-by "Byron Bunt"
```

The default cooling-off period is 24 hours. The evidence and configuration are hashed into the proposal.

## Prepare a local activation profile

Never modify the packaged profile directly:

```bash
cp config/volatility_breakout_phase7.yaml \
   config/volatility_breakout_phase7.live.local.yaml
```

In the ignored local copy, change only:

```yaml
phase7_stage_activation_enabled: true
phase6_live_submission_enabled: true
```

The stage governor still caps the actual notional and symbol allowlist.

## Approve the proposal

After the cooling-off period:

```bash
python scripts/run_phase7_growth.py \
  --profile config/volatility_breakout_phase7.live.local.yaml \
  --approve-growth \
  --approved-by "Byron Bunt" \
  --ack-growth-risk "I AUTHORIZE ONE CONTROLLED HIVENANCE GROWTH STAGE"
```

Approval does not activate the stage.

## Activate the approved stage

```bash
export HIVENANCE_PHASE7_CONTROLLED_GROWTH=YES

python scripts/run_phase7_growth.py \
  --profile config/volatility_breakout_phase7.live.local.yaml \
  --activate-growth \
  --approved-by "Byron Bunt"
```

Activation changes only the growth envelope. It does not submit an order.

## Approve one entry

The Phase-6 per-entry lease remains mandatory:

```bash
python scripts/run_phase7_growth.py \
  --profile config/volatility_breakout_phase7.live.local.yaml \
  --approve-next-entry \
  --approved-by "Byron Bunt" \
  --ack-live-risk "I AUTHORIZE ONE TINY LIVE KRAKEN CANARY"
```

## Start supervised controlled growth

Load trade-only, no-withdrawal Kraken credentials:

```bash
export HIVENANCE_KRAKEN_API_KEY='...'
export HIVENANCE_KRAKEN_API_SECRET='...'
export HIVENANCE_PHASE6_LIVE_SUBMISSION=YES
export HIVENANCE_PHASE7_CONTROLLED_GROWTH=YES
```

Reconcile first:

```bash
python scripts/run_phase7_growth.py \
  --profile config/volatility_breakout_phase7.live.local.yaml \
  --reconcile-only
```

Then start the continuous operator:

```bash
python scripts/run_phase7_growth.py \
  --profile config/volatility_breakout_phase7.live.local.yaml \
  --live
```

Live mode cannot be combined with `--once`.

## Automatic demotion

The stage drops by one level and enters `DEMOTED` when a configured safety trigger appears. The canary is also HALTED. Promotion proposals and approvals are invalidated.

No automatic recovery exists.

## Incident recovery

First reconcile the exchange and resolve the Phase-6 cause. Then resolve the Phase-7 incident:

```bash
python scripts/run_phase7_growth.py \
  --resolve-growth-incident <INCIDENT_ID> \
  --resolution "Kraken query confirmed no live order; local state reconciled"
```

A fresh CLEAN Phase-6 reconciliation is required. Then resume only at the demoted stage:

```bash
export HIVENANCE_PHASE7_CONTROLLED_GROWTH=YES

python scripts/run_phase7_growth.py \
  --profile config/volatility_breakout_phase7.live.local.yaml \
  --resume-demoted-stage \
  --approved-by "Byron Bunt" \
  --ack-recovery-risk "I ACKNOWLEDGE THE PHASE7 INCIDENT AND RESUME AT THE DEMOTED STAGE"
```

Recovery resets the evidence block. The system cannot immediately re-promote itself.

## Emergency commands

Halt both growth and canary authority:

```bash
python scripts/run_phase7_growth.py --halt --reason "operator concern"
```

Attempt cancellation of every pending Kraken order:

```bash
python scripts/run_phase7_growth.py \
  --profile config/volatility_breakout_phase7.live.local.yaml \
  --emergency-cancel-all
```

Manual demotion:

```bash
python scripts/run_phase7_growth.py \
  --demote-now \
  --reason "execution quality deterioration"
```

## Residual risk

The dead-man cancellation lease cancels pending orders. It does not liquidate filled spot inventory. Stop, target and horizon exits remain supervised by the local operator process. Keep the process running until all inventory is closed and reconciled.

Do not increase the stage caps, add leverage, enable multiple simultaneous positions or add another venue until venue-native protective exits and real live evidence support that change.
