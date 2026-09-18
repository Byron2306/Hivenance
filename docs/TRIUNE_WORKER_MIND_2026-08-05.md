# Triune Worker Mind

## Source Pattern

This integration adapts the Metatron/Michael/Loki triune pattern observed in:

- `/home/byron/Downloads/Metatron-triune-outbound-gate/backend/triune/metatron.py`
- `/home/byron/Downloads/Metatron-triune-outbound-gate/backend/triune/michael.py`
- `/home/byron/Downloads/Metatron-triune-outbound-gate/backend/triune/loki.py`
- `/home/byron/Downloads/Metatron-triune-outbound-gate/docs/triune_cognition_feature_summary.md`
- `/home/byron/Integritas-Mechanicus-clean/Integritas-Mechanicus/arda_os/triune_orchestrator.py`

The borrowed architecture is:

- Metatron: synthesize strategic truth from the current world state.
- Michael: validate and rank candidate actions.
- Loki: challenge the selected plan with adversarial alternatives, uncertainty, and vetoes.

## Hivenance Mapping

Each legacy strategy worker now passes through a deterministic triune assessment before its Phase-2 forecast is admitted.

- Metatron becomes worker-signal synthesis: harmony between validation, cost survival, expected edge, and Loki risk.
- Michael becomes worker-signal validation: data quality, freshness, liquidity, spread, cost survival, signal strength, and memory quality.
- Loki becomes worker-signal adversary: challenges spread traps, cost-dominated projections, micro-move noise, bad recent worker memory, stable-pair chop, and regime mismatch.

## Authority Boundary

The triune worker mind is `research_admission_only`.

- It cannot place orders.
- It cannot mark a forecast execution-eligible.
- It cannot override human approval.
- It can only allow, challenge, or veto research forecasts.

## Receipt Objects

Worker forecast payloads may now include:

```json
{
  "triune_worker_mind": {
    "schema": "hivenance_triune_worker_mind_v1",
    "metatron": {"role": "METATRON_SYNTHESIS"},
    "michael": {"role": "MICHAEL_VALIDATOR"},
    "loki": {"role": "LOKI_ADVERSARY"},
    "final_verdict": "ALLOW_RESEARCH | CHALLENGE_RESEARCH | VETO",
    "authority": "research_admission_only",
    "execution_authority": "none",
    "orders_submitted": 0
  }
}
```

## Profit Relevance

This does not create profit by itself. It improves the profit path by preventing weak indicator triggers from becoming noisy Phase-3 simulations.

The first live evidence after activation showed Loki challenging or vetoing worker signals for:

- cost-dominated projections
- micro-move noise traps
- negative worker memory
- stable-pair spread traps

This is exactly the missing adversarial layer: workers can still scout, but Loki forces them to survive cost, regime, and deception checks before they matter.

## Coalition Meta-Model

The next layer is now in code as `worker_coalition_meta_v1`.

- ~~Treat legacy workers as research voters, not isolated strategies.~~
- ~~Run each admitted vote through Metatron/Michael/Loki before aggregation.~~
- ~~Emit `hivenance_worker_coalition_receipt_v1` with voter lineage, agreement, cost hurdle, Loki challenges, and zero execution authority.~~
- ~~Register the coalition as a normal Phase-2 research model so Phase 3 can simulate it and Phase 4 can judge it.~~
- Specialize coalition pools by symbol class and regime next, so trend workers do not fight mean-reversion workers in the wrong context.

The coalition does not loosen governance. It increases selectivity: a lone worker
can create evidence, but only a governed coalition can become a candidate slice.
