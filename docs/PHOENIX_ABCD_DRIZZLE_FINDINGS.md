# Phoenix Drizzle A-D Findings — Negative Capability Seed

**Purpose:** preserve the falsification record that motivates the Relative-Value Laboratory.

These findings are research evidence, not execution authority.

## Experiment A — fast streak

Key result:
- raw streak showed a small positive gross contribution before modeled fees, but costs overwhelmed it;
- stricter variants reduced churn;
- this established that tiny short-lived motion may exist but did not establish harvestable net edge.

Lesson:
**gross motion is not executable edge.**

## Experiment B — absolute cross-asset rotation

Key result:
- naive rotation losses were overwhelmingly friction/churn;
- hysteresis materially reduced activity;
- abstention preserved capital.

Lesson:
**absolute "best coin now" rotation is not the drizzle formulation.**

## Experiment C — relative full-switch rotation

Key result:
- relative naive and relative streak were negative even before modeled costs in aggregate;
- full switching paid excessive friction;
- mature persistence did not improve outcomes;
- hysteresis suppressed almost all switching.

Lesson:
**relative-value framing was better conceptually, but complete sleeve migration is mechanically wrong.**

## Experiment D — inventory drizzle

Key result:
- naive small-slice rebalancing underperformed equal-weight hold;
- direct pair routes were materially less costly than USD-routed transitions;
- gated inventory variants produced no executed rebalances in the observed run;
- retrospective candidate analysis did not show that simply removing batching would rescue the strategy.

Raw statistical autopsy findings:
- D naive 30s mean gross relative capture was approximately -0.75 bps;
- D naive 30s mean net relative capture was approximately -6.82 bps;
- block-bootstrap 95% interval for net capture was approximately [-7.45, -6.22] bps;
- positive 30s net outcomes were approximately 3.1%;
- higher predicted current "gross edge" was associated with worse realized future 30s relative capture;
- Spearman association between predicted gross edge and realized 30s capture was approximately -0.309 with FDR-adjusted significance;
- direct-pair outcomes were materially less negative than USD-routed outcomes;
- mature streak persistence was repeatedly associated with worse subsequent outcomes;
- relative cheapness had a weak directional relationship with later outcome but not enough to establish positive expectancy.

Lesson:
**the current score is primarily a description of recent motion, not a calibrated forecast of future relative return.**

## Research conclusion

The following implementations are not supported by A-D:

- high-turnover short-horizon chasing;
- absolute cross-asset rotation;
- full relative sleeve switching;
- current-motion score treated as expected future edge;
- mature-streak confirmation as the main entry criterion;
- route-cost-blind relative trading.

The following hypothesis remains legitimately open:

> A stable pair relationship may exhibit forecastable relative reversion after a statistically meaningful spread displacement when the flow causing the displacement is exhausting, provided the future move is forecast prospectively and clears actual route/spread/fee uncertainty.

## Mandatory falsification cases for new models

Every Relative-Value Laboratory model family must be challenged against:

1. **late-entry/chasing case**  
   High recent acceleration/persistence must not mechanically imply high future expected return.

2. **cost domination case**  
   Positive gross forecast that cannot clear direct or routed cost must abstain.

3. **route split case**  
   Direct and routed execution cohorts must remain separately measurable.

4. **mature persistence case**  
   Models must demonstrate prospectively whether persistence adds or destroys forecast value.

5. **hold baseline case**  
   Inventory experiments must beat matched equal-weight hold, not merely finish positive.

6. **zero-exposure case**  
   A strategy producing no admissible events is unobserved, not successful.

7. **Horizon warmup case**  
   Macro/meso context is not treated as evidence before its own time horizon has actually warmed.

8. **current-score inversion case**  
   Any model whose forecast ranking is negatively associated with settled outcomes must be demoted/refused regardless of attractive backtest PnL.

## Programme implication

Experiment E must be forecast-first:

```text
pair structure
+ microstructure
+ regime/context
        ->
future relative-return forecast
        ->
calibration / uncertainty
        ->
execution cost
        ->
abstain or paper candidate
```

No threshold tuning on A-D may be presented as prospective validation.
