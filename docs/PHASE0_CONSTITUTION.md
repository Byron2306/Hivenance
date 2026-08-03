# Phase 0 Constitution

## Name

Phoenix Phase 0: Constitution and Authority Lock

## Intent

Phase 0 exists to prove that Hivenance can:

- observe markets
- persist research evidence
- run governance and diagnostics
- refuse live capital authority

before it is allowed to pursue profit with real execution.

This phase is not a profit phase.
It is a legitimacy phase.


## Constitutional Rules

### 1. No live order authority

The legacy coordinator may not:

- submit orders
- transmit orders
- promote live
- resume live
- scale capital
- activate live sidecars

These actions are constitutionally reserved for later dedicated operator phases.

### 2. Research is allowed, execution is not

Phase 0 allows:

- observation
- evidence import
- candidate scoring
- simulation
- diagnostics
- status rendering
- research configuration

Phase 0 forbids:

- real execution
- automatic promotion
- leverage escalation
- sidecar live activation
- wallet authority delegation

### 3. Quarantine is fail-closed

If `phase0_quarantine=true`, the system must force:

- `dry_run=true`
- `live_mode=false`
- `onchain_enabled=false`
- `public_bot_metrics_auto_promote=false`
- `hummingbot_sidecar_live_enabled=false`
- `market_making_quote_placement_enabled=false`
- `openclaw_autonomy_enabled=false`
- `coin_selection_auto_switch=false`
- `swarmguard_small_trade_bypass=false`
- `volatility_harvest_enabled=false`
- `hummingbot_v2_leverage=1`

### 4. Profit claims are provisional

During Phase 0:

- profit claims are untrusted
- backtests are importable but not promotable
- research models are informative but not authoritative
- governance may rank trust candidates but may not allocate real capital

### 5. Human sign-off is mandatory for exit

Phase 0 may only end when:

- the authority lock is verified
- the observation spine is healthy
- the evidence chain is auditable
- a dedicated future operator process is approved


## Phase 0 Deliverables

- authority map
- quarantine enforcement
- config write boundary
- audit trail
- local-only UI and service binding
- preflight validation
- machine-readable Phase 0 status snapshot


## Machine Surface

The Phase 0 state should be available from:

- `/phase0.json`
- `scripts/phase0_preflight.py`
- `agents/phoenix_authority.py`
- `main.apply_phase0_safety_policy`


## Exit Gate

Phase 0 is complete only when the system can prove:

1. it cannot cheat
2. it can observe reliably
3. it can preserve evidence
4. it can keep authority separated from research

Until then, the correct behavior is not boldness.
It is disciplined refusal.
