# Hivenance Phase 12 Adaptive Organism Control Plane

Status: IMPLEMENTING
Branch: phase12-learning-causality-audit

## Core principle

The census is evidence, not a tombstone.

No organ is permanently deleted or permanently promoted because of one historical
classification. Every organ remains addressable and may move between reversible
research modes as new point-in-time evidence arrives.

Execution authority remains a separate downstream gate.

## Runtime modes

DORMANT
- not allowed to influence current research decisions;
- remains registered;
- periodic shadow probes are permitted;
- may wake when requested or when new evidence demands reevaluation.

SHADOW
- runs on live public observations;
- emits receipts and paired counterfactuals;
- cannot influence the current research decision;
- settles prospectively for causal prosecution.

ADVISORY
- visible to ResearchContext / Queen;
- may contribute explanation, dissent, uncertainty, or research requests;
- may not originate execution authority.

ACTIVE
- may exercise only the influence allowed by canonical organ topology;
- requires prospective evidence;
- still has execution_eligible=false and promotion_eligible=false.

QUARANTINED
- influence disabled after harmful/mixed/drift evidence;
- organ is not deleted;
- shadow probing remains enabled so it can rehabilitate.

## Reversibility

Every mode transition is reversible.

Examples:
- QUARANTINED -> SHADOW after redesign or new evidence window.
- SHADOW -> ADVISORY after reliable information contribution.
- ADVISORY -> ACTIVE after prospective causal utility.
- ACTIVE -> SHADOW/QUARANTINED when drift or harm appears.
- DORMANT -> SHADOW at any operator or research-policy request.

Historical evidence never creates a permanent hard lock.

## Phase 12 prospective gauntlet

Use the existing public-market G1 / Phase-5 shadow machinery rather than creating
another observation stack.

For every live public market cycle:

1. Observe current public market state.
2. Build canonical ResearchContext.
3. Resolve organ runtime modes.
4. Run ACTIVE/ADVISORY organs in the research path.
5. Run SHADOW/QUARANTINED/DORMANT-probe organs as non-influential twins.
6. Freeze all decisions and evidence roots before outcome knowledge.
7. Wait for the configured horizon.
8. Settle all twins against the same realized market move and costs.
9. Update rolling causal utility per organ and worker sub-organ.
10. Update Learning only from settled, point-in-time-safe evidence.
11. Create/refresh Crystals only after recurrence and transfer criteria.
12. Re-resolve runtime modes for the next independent world.

No step may submit a real order.

## Learning graduation

Learning is considered fully wired only when all of the following happen on
prospective worlds:

- prior evidence exists before the decision;
- the prior is actually consumed by the intended model;
- a paired NO_LEARNING twin is frozen at the same world;
- the world settles after the horizon;
- learning changes at least some decisions;
- helpful/harmful deltas are measured after costs;
- independent-world depth is sufficient;
- usefulness survives cohort/transfer checks;
- Crystal reuse, when present, is separately ablated;
- stale/future evidence is refused;
- execution remains separately gated.

Generated memories or Crystals without causal influence are not counted as useful
learning.

## Hysteresis

To prevent mode flapping:

- promotion and demotion use separate evidence thresholds;
- ACTIVE requires a minimum prospective depth;
- a single good/bad world cannot flip mode;
- harmful drift can force an immediate downgrade to SHADOW/QUARANTINED;
- reactivation requires a fresh prospective rehabilitation window;
- operator requests can always wake an organ into SHADOW.

## Current evidence interpretation

Statistics Bee:
- historically useful candidate;
- keep as the primary research-control organ under prospective shadow validation.

Strategy workers:
- mixed at federation level;
- manage individual worker modes separately.

Bayesian regime filter:
- information-rich but decision-inert at the current hypothesis boundary;
- retain context visibility; direct control remains demoted.

Learning memory:
- memory depth improving after worker-transfer repair;
- not yet causally influential;
- keep SHADOW until prospective influence is demonstrated.

Crystals:
- generation works;
- reuse has not yet occurred;
- remain SHADOW/downstream of learning.

Unmeasured organs:
- classify as SHADOW/measurement-needed, never as useless.

## Safety boundary

ACTIVE means active research influence only.
It never means order execution.

Execution, canary, and controlled growth remain governed by their own downstream
gates and cannot be unlocked by this control plane.
