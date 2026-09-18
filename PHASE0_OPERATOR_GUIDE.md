# Phase 0 Operator Guide

## Purpose

Phase 0 is the constitutional safety shell for the governed-profit system.

Its job is to ensure the current runtime is:

- research-only
- authority-locked
- audit-friendly
- incapable of quietly becoming live


## What Operators Should Check

### 1. Quarantine is enabled

Expected:

- `phase0_quarantine: true`
- `dry_run: true`
- `live_mode: false`

### 2. Protected toggles remain suppressed

Expected:

- `onchain_enabled: false`
- `public_bot_metrics_auto_promote: false`
- `hummingbot_sidecar_live_enabled: false`
- `market_making_quote_placement_enabled: false`
- `openclaw_autonomy_enabled: false`
- `coin_selection_auto_switch: false`
- `swarmguard_small_trade_bypass: false`
- `volatility_harvest_enabled: false`

### 3. Leverage remains fixed

Expected:

- `hummingbot_v2_leverage: 1`

### 4. Authority remains locked

Expected:

- live orders denied
- live promotion denied
- live resume denied
- capital scaling denied
- live sidecar activation denied


## Runtime Checks

### HTTP

- `GET /phase0.json`
- `GET /phoenix/authority.json`
- `GET /api/status`

### Preflight

```bash
python3 scripts/phase0_preflight.py --strict-source
```


## Healthy State

A healthy Phase 0 state reports:

- `status: LOCKED`
- no violations
- `live_capital_permitted: false`
- `profit_mode: research_governance_only`


## Unhealthy State

Treat these as constitutional violations:

- any protected field becomes live-enabled
- any protected action reports allowed
- leverage drifts above `1`
- quarantine is disabled in ordinary runtime
- a sidecar gains wallet or execution authority


## Operator Response

If Phase 0 is violated:

1. stop trusting all profit-related output
2. reassert safe config
3. rerun Phase 0 preflight
4. inspect config audit and authority snapshot
5. do not proceed to later phases until the lock is restored
