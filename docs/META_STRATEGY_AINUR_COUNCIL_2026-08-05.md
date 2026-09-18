# Meta-Strategy Ainur Council

## Source Pattern

This integration adapts the Arda/Integritas Ainur witness pattern observed in:

- `/home/byron/Integritas-Mechanicus/arda_os/backend/services/ainur/ainur_council.py`
- `/home/byron/Integritas-Mechanicus/arda_os/backend/services/ainur/manwe.py`
- `/home/byron/Integritas-Mechanicus/arda_os/backend/services/ainur/varda.py`
- `/home/byron/Integritas-Mechanicus/arda_os/backend/services/ainur/vaire.py`
- `/home/byron/Integritas-Mechanicus/arda_os/backend/services/ainur/mandos.py`
- `/home/byron/Integritas-Mechanicus/arda_os/backend/services/ainur/ulmo.py`
- `/home/byron/Integritas-Mechanicus/arda_os/backend/services/ainur/aule.py`

The useful pattern is independent bounded witness testimony, resonance summary,
discord accounting, and synthesis. Hivenance uses that pattern for market
strategy routing, not execution.

## Hivenance Mapping

- Manwe witnesses market cadence: freshness and continuity.
- Varda witnesses measured truth: data quality, spread, depth, and cost.
- Vaire witnesses regime chronology: which strategy families fit this regime.
- Mandos witnesses failure memory: families repeatedly negative after cost.
- Ulmo witnesses deep market current: liquidity, spread, volatility expansion.
- Aule synthesizes the eligible strategy-family budget.

## Receipt Object

Coalition forecasts may now carry:

```json
{
  "meta_strategy_council": {
    "schema": "hivenance_meta_strategy_council_v1",
    "source_pattern": "arda_ainur_witness_council",
    "allowed_families": ["breakout", "momentum", "trend"],
    "blocked_families": ["mean_reversion"],
    "harmony_index": 1.0,
    "canonical_runtime_state": "harmonic",
    "authority": "research_routing_only",
    "execution_authority": "none",
    "orders_submitted": 0
  }
}
```

## Profit Relevance

This is a meta-strategy layer. It decides which kind of strategy is allowed to
vote before a forecast is formed.

The first concrete improvement is regime-lane specialization:

- Trend expansion admits trend, momentum, and breakout workers.
- Quiet range and stretch exhaustion admit mean-reversion and trend context.
- Balanced transition can admit all families, but still records discord.

This prevents a strong trend-breakout setup from being diluted by mean-reversion
workers that are only appropriate in a different market lane.

## Authority Boundary

The council is `research_routing_only`.

- It cannot submit orders.
- It cannot grant execution eligibility.
- It cannot override Phase 3, Phase 4, Phase 5, DIO, or human approval.
- It can only mute or admit research strategy families before coalition voting.
