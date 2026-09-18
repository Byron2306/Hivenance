# Hivenance Commons Pool Integration Plan

Date: Wednesday, August 5, 2026

## Purpose

This document turns the Commons-style mining-pool note into a concrete Hivenance integration plan.

The design target is not:

`remote compute -> remote answer -> live trust`

The design target is:

`remote compute -> signed evidence -> local verification -> bounded Hivenance receipt -> optional local adoption`

That keeps Hivenance aligned with the Phoenix authority chain already enforced in this repo:

- Phase 2 and Phase 3 may propose and simulate.
- Phase 4 and Phase 5 may validate and shadow.
- Phase 6 alone may submit live orders.
- Phase 7 alone may scale capital.

## Core Thesis

The Commons pool can help Hivenance in two high-value places:

1. `Inference Pool -> Phase 2/3`
   Remote workers generate challenger forecasts, feature transforms, execution-policy variants, and replay bundles.

2. `Verifier Pool -> Phase 4/5`
   Remote workers reproduce, audit, challenge, and verify Hivenance evidence packets before promotion or shadow continuation.

The Commons pool must not directly help Hivenance in one forbidden place:

- live order authority

No Commons worker, remote verifier, or federation node may:

- place a live order
- approve a Phase 6 canary
- activate a Phase 7 stage
- mutate a frozen Phase 4 or Phase 5 object after approval
- bypass `agents/phoenix_authority.py`

## Repo-Native Placement

This plan maps directly onto existing Hivenance phases and files.

### Inference Pool landing zones

- Phase 2 hypothesis competition
  - `strategies/volatility_breakout/hypothesis_competition.py`
  - `strategies/volatility_breakout/research_model_federation.py`
  - `strategies/volatility_breakout/hypothesis_swarm.py`
- Phase 3 execution lab
  - `strategies/volatility_breakout/execution_lab.py`
  - `strategies/volatility_breakout/execution_engine.py`

### Verifier Pool landing zones

- Phase 4 adversarial validation
  - `strategies/volatility_breakout/adversarial_validation.py`
  - `strategies/volatility_breakout/validation_lab.py`
- Phase 5 shadow governance
  - `strategies/volatility_breakout/shadow_lab.py`
  - `strategies/volatility_breakout/shadow_flight.py`

### Existing authority and evidence rails to reuse

- `agents/phoenix_authority.py`
- `agents/research_architecture.py`
- `agents/evidence_registry.py`
- `agents/data_store_agent.py`
- `agents/ml_research_lab.py`

## Architectural Split

### Pool A: Inference Pool for Phase 2 and Phase 3

Purpose:

- generate external challenger forecasts
- generate alternate execution-policy proposals
- generate structured negative cases
- run remote research-only feature or model transformations

Allowed outputs:

- forecast proposals
- model cards
- feature receipts
- execution-policy candidate packets
- replay candidate bundles

Forbidden outputs:

- live intents
- live orders
- promotion decisions
- frozen champion mutation
- capital allocation mutation

### Pool B: Verifier Pool for Phase 4 and Phase 5

Purpose:

- reproduce Phase 3 simulation claims
- verify Phase 4 candidate validation packets
- independently replay negative cases
- verify shadow settlements and drift evidence

Allowed outputs:

- validation receipts
- replay verification receipts
- disagreement receipts
- shadow integrity receipts
- reproduction failure receipts

Forbidden outputs:

- direct approval of Phase 5
- direct approval of Phase 6
- override of human review
- override of Phoenix authority

## New Core Objects

These are the exact objects Hivenance should introduce for Commons-style pool work.

## 1. Pool Work Ticket

This is the only object that a remote worker may claim.

```json
{
  "schema": "hivenance_commons_pool_work_ticket_v1",
  "ticket_id": "poolwork_...",
  "pool_type": "inference_pool",
  "task_class": "phase2_challenger_forecast",
  "phase_scope": 2,
  "created_ts": 1785945600.0,
  "expires_ts": 1785946200.0,
  "lease_count": 1,
  "authority": "research_work_only",
  "world_state_digest": "sha256:...",
  "input_root": "sha256:...",
  "feature_schema_digest": "sha256:...",
  "code_digest": "sha256:...",
  "config_digest": "sha256:...",
  "required_engine_profiles": ["python_cpu", "federated_forecaster"],
  "required_verifiers": ["manifest", "policy", "schema"],
  "privacy_class": "public_market_research",
  "challenge_nonce": "nonce_...",
  "target_object": {
    "phase2_observation_id": "obs_...",
    "symbol": "ETH/USD",
    "horizon_seconds": 900,
    "regime_hint": "trend_expansion"
  }
}
```

Rules:

- one ticket represents one bounded remote job
- ticket authority is always `research_work_only` or `verification_work_only`
- no ticket may carry any live execution capability

## 2. Worker Claim Lease

This binds one worker to one ticket for one attempt.

```json
{
  "schema": "hivenance_commons_claim_lease_v1",
  "lease_id": "lease_...",
  "ticket_id": "poolwork_...",
  "worker_id": "node_remote_a",
  "worker_advertisement_digest": "sha256:...",
  "issued_ts": 1785945612.0,
  "expires_ts": 1785945912.0,
  "challenge_nonce": "nonce_...",
  "authority": "research_work_only",
  "max_result_bytes": 25000000,
  "signature": {}
}
```

Rules:

- exactly one lease per accepted claim
- expired leases are invalid evidence
- duplicate claims on the same ticket require explicit multi-worker mode

## 3. Inference Result Receipt

This is the Phase 2 and Phase 3 remote result object.

```json
{
  "schema": "hivenance_inference_pool_result_receipt_v1",
  "receipt_id": "infer_...",
  "ticket_id": "poolwork_...",
  "lease_id": "lease_...",
  "worker_id": "node_remote_a",
  "task_class": "phase2_challenger_forecast",
  "phase_scope": 2,
  "created_ts": 1785945660.0,
  "challenge_nonce": "nonce_...",
  "input_root": "sha256:...",
  "output_root": "sha256:...",
  "world_state_digest": "sha256:...",
  "feature_schema_digest": "sha256:...",
  "code_digest": "sha256:...",
  "config_digest": "sha256:...",
  "container_digest": "sha256:...",
  "result_kind": "forecast_packet",
  "result_summary": {
    "model_id": "commons_freqai_remote_v1",
    "symbol": "ETH/USD",
    "direction": "UP",
    "expected_move_bps": 34.2,
    "expected_cost_bps": 17.6,
    "expected_net_bps": 16.6,
    "probability_positive_net": 0.58
  },
  "verifier_results": [],
  "signature": {}
}
```

Authority boundary:

- may enter Phase 2 only as `proposal weight`
- may enter Phase 3 only as `simulation candidate`
- may never enter Phase 6 as an executable intent

## 4. Verifier Result Receipt

This is the Phase 4 and Phase 5 remote verification object.

```json
{
  "schema": "hivenance_verifier_pool_result_receipt_v1",
  "receipt_id": "verify_...",
  "ticket_id": "poolwork_...",
  "lease_id": "lease_...",
  "worker_id": "node_remote_b",
  "task_class": "phase4_candidate_replay_verification",
  "phase_scope": 4,
  "created_ts": 1785945800.0,
  "challenge_nonce": "nonce_...",
  "subject_digest": "sha256:...",
  "world_state_digest": "sha256:...",
  "code_digest": "sha256:...",
  "config_digest": "sha256:...",
  "container_digest": "sha256:...",
  "verification_verdict": "PASS",
  "verification_summary": {
    "reproduced": true,
    "metric_deltas": {
      "mean_net_bps_delta": -0.4,
      "drawdown_bps_delta": 3.2
    },
    "negative_case_replay": "PASS",
    "leakage_check": "PASS",
    "pbo_check": "PASS"
  },
  "signature": {}
}
```

Authority boundary:

- may strengthen or weaken validation confidence
- may block promotion by producing verified contradiction
- may never promote by itself

## 5. Local Adoption Receipt

This is the most important object. It is the bridge from remote work to local Hivenance evidence.

```json
{
  "schema": "hivenance_commons_local_adoption_receipt_v1",
  "receipt_id": "adopt_...",
  "source_receipt_id": "infer_... or verify_...",
  "pool_type": "inference_pool",
  "phase_scope": 2,
  "adopted_ts": 1785945860.0,
  "adopted_by": "hivenance_local_verifier",
  "local_reproduction_required": true,
  "local_reproduction_verdict": "PASS",
  "adoption_decision": "ACCEPTED_PROPOSAL_WEIGHT_ONLY",
  "target_object": {
    "phase2_observation_id": "obs_...",
    "forecast_id": null,
    "phase4_run_id": null
  },
  "authority_ceiling": "proposal_only",
  "reasons": [
    "signature_valid",
    "nonce_valid",
    "digest_match",
    "local_reproduction_passed"
  ],
  "signature": {}
}
```

This is the object the repo should persist and trust.

Not the remote receipt by itself.

## Task-Class Mapping

## Inference Pool -> Phase 2 / 3

### Phase 2 task classes

- `phase2_challenger_forecast`
- `phase2_feature_transform_candidate`
- `phase2_regime_tag_candidate`
- `phase2_negative_case_search`
- `phase2_baseline_counterexample`

### Phase 3 task classes

- `phase3_execution_policy_candidate`
- `phase3_replay_bundle_candidate`
- `phase3_stress_scenario_candidate`
- `phase3_cost_model_variant_candidate`

### Phase 2/3 local adoption rules

- remote forecast may become a challenger row in `hypothesis_swarm`
- remote replay candidate may become a simulation candidate only after local digest and schema checks
- remote stress scenario may add a diagnostic scenario class
- remote outputs may not skip:
  - Phase 3 admission receipts
  - abstention-beat receipts
  - local allocation logic

## Verifier Pool -> Phase 4 / 5

### Phase 4 task classes

- `phase4_candidate_replay_verification`
- `phase4_negative_case_replay`
- `phase4_leakage_audit`
- `phase4_walk_forward_reproduction`
- `phase4_pbo_confirmation`

### Phase 5 task classes

- `phase5_shadow_integrity_verification`
- `phase5_frozen_config_replay`
- `phase5_shadow_settlement_audit`
- `phase5_drift_confirmation`

### Phase 4/5 local adoption rules

- verifier receipts may add evidence to candidate reports
- verifier disagreement may add rejection reasons
- verifier agreement may improve confidence but does not produce auto-promotion
- Phase 5 remains locked behind human review even if verifier pool consensus is strong

## Exact Authority Boundaries For This Repo

These are the contracts Hivenance should enforce.

## Boundary 1: Remote pools have no live authority

All Commons workers and pool coordinators must map to:

- `execution_authority: none`
- `promotion_authority: none`
- `resume_authority: none`
- `scaling_authority: none`

This matches `PhoenixAuthorityGuard.component_contract(...)`.

## Boundary 2: Remote receipts are untrusted until local adoption

The repo should never treat:

- `hivenance_inference_pool_result_receipt_v1`
- `hivenance_verifier_pool_result_receipt_v1`

as sufficient authority.

Only `hivenance_commons_local_adoption_receipt_v1` may influence downstream Hivenance decisions.

## Boundary 3: Phase ceilings stay fixed

- Inference Pool may enter at Phase 2 and Phase 3 only
- Verifier Pool may enter at Phase 4 and Phase 5 only
- neither pool may write Phase 6 order objects
- neither pool may write Phase 7 activation or scaling objects

## Boundary 4: Contradiction lowers trust

If two verifier workers disagree, Hivenance must not average away the contradiction.

Instead it should create:

- a disagreement receipt
- a demotion of confidence
- an explicit reason in the relevant Phase 4 or Phase 5 readiness record

## Boundary 5: Remote work can widen research, not loosen gates

The expected benefit is:

- more candidate diversity
- more reproduction coverage
- more negative-case discovery
- more robust adversarial pressure

The forbidden misuse is:

- replacing local gates with remote confidence

## Implementation Plan

This is the practical build order for this repo.

## Slice 1: Receipt models and persistence

Status as of Wednesday, August 5, 2026: completed.

Implemented in:

- `agents/data_store_agent.py`

Completed artifacts:

- `commons_pool_work_tickets`
- `commons_pool_claim_leases`
- `commons_inference_receipts`
- `commons_verifier_receipts`
- `commons_local_adoption_receipts`
- typed persist helpers for each family
- read APIs for each family
- `get_commons_pool_snapshot(...)`

Likely homes:

- `agents/data_store_agent.py`
- new typed models under `strategies/volatility_breakout/` or `agents/`

## Slice 2: Inference Pool adapter for Phase 2

Status as of Wednesday, August 5, 2026: governed intake and ticketing slice completed.

Implemented in:

- `agents/data_store_agent.py`
- `strategies/volatility_breakout/hypothesis_swarm.py`

Completed artifacts:

- adopted Phase-2 Commons inference packets can now be queried from the store
- adopted packets are translated into research-only challenger forecast rows
- imported challenger rows are marked with Commons provenance
- imported challenger rows remain `execution_eligible: false`
- imported challenger rows remain `authority_ceiling: proposal_only`
- imported challenger rows enter Phase 2 competition only through local adoption receipts
- outbound `phase2_challenger_forecast` tickets are issued from the swarm
- inbound adopted packets are checked for signature, nonce, expiry, ticket existence, and input-root match before acceptance

Remaining work:

- ~~add a dedicated adapter service instead of store-driven intake alone~~

Implemented by `scripts/run_sovereign_pool_worker.py` and
`agents/sovereign_pool_worker.py`. The worker leases Phase-2 tickets, reproduces
input digests locally, emits governed inference receipts, and creates local
adoption receipts without execution or promotion authority.

Build a research-only adapter that:

- issues `phase2_challenger_forecast` tickets
- imports remote result receipts
- verifies signatures, nonce, digests, and schema
- creates local adoption receipts
- injects accepted challenger packets into `hypothesis_swarm`

No direct mutation of Phase 6 or Phase 7 objects.

## Slice 3: Inference Pool adapter for Phase 3

Status as of Wednesday, August 5, 2026: first governed execution-policy slice completed.

Implemented in:

- `agents/data_store_agent.py`
- `strategies/volatility_breakout/execution_lab.py`

Completed artifacts:

- adopted Phase-3 Commons execution packets can now be queried from the store
- Phase 3 now issues outbound `phase3_execution_policy_candidate` tickets
- inbound adopted packets are checked for signature, nonce, expiry, ticket existence, input-root match, and local forecast presence
- accepted packets can add simulation plans only for already-admitted local candidates
- Commons proposals remain under `proposal_only` authority and cannot bypass Phase 3 admission, abstention, or allocation logic

Remaining work:

- add dedicated `phase3_stress_scenario_candidate` issuance alongside execution-policy issuance
- add replay bundle candidate intake
- add a dedicated adapter service instead of store-driven intake alone

Extend the adapter to produce:

- execution-policy candidate packets
- stress-scenario candidate packets
- replay bundle candidates

Then require all adopted candidates to pass:

- existing Phase 3 admission receipts
- existing abstention-beat receipts
- existing allocation logic

## Slice 4: Verifier Pool adapter for Phase 4

Status as of Wednesday, August 5, 2026: first governed verification slice completed.

Implemented in:

- `agents/data_store_agent.py`
- `strategies/volatility_breakout/validation_lab.py`

Completed artifacts:

- adopted Phase-4 Commons verifier packets can now be queried from the store
- Phase 4 now issues outbound `phase4_candidate_replay_verification` verifier tickets
- inbound adopted verifier packets are checked for signature, nonce, expiry, ticket existence, subject digest, and local candidate presence
- accepted verifier packets are attached to local candidate results as verifier annotations
- contradiction receipts can now explicitly reduce Phase 4 readiness and candidate promotability
- Commons verifier confirmations remain evidence only and do not create promotion authority

Remaining work:

- ~~create the dedicated local adoption creator path for verifier receipts~~
- broaden verifier task issuance beyond replay verification into leakage, PBO, and walk-forward ticket classes
- ~~add a dedicated adapter service instead of store-driven intake alone~~

The sovereign pool worker now performs the replay-verification adapter path and
persists local adoption receipts. Broader Phase-4 task classes remain open.

Build a verifier-only adapter that:

- emits replay and validation tickets from `validation_lab`
- ingests remote verifier receipts
- binds them to Phase 4 candidate results
- creates local adoption receipts
- records contradiction explicitly in readiness and candidate reports

## Slice 5: Verifier Pool adapter for Phase 5

Status as of Wednesday, August 5, 2026: first governed shadow-verification slice completed.

Implemented in:

- `agents/data_store_agent.py`
- `strategies/volatility_breakout/shadow_lab.py`

Completed artifacts:

- adopted Phase-5 Commons verifier packets can now be queried from the store
- Phase 5 now issues outbound `phase5_shadow_integrity_verification` verifier tickets
- inbound adopted verifier packets are checked for signature, nonce, expiry, ticket existence, subject digest, and local freeze presence
- contradiction receipts can now explicitly reduce `ready_for_phase6_review`
- verifier confirmations remain evidence only and cannot open Phase 6 review

Remaining work:

- create the dedicated local adoption creator path for Phase-5 verifier receipts
- broaden verifier task issuance beyond shadow integrity into frozen-config replay, settlement audit, and drift-specialized ticket classes
- add a dedicated adapter service instead of store-driven intake alone

Build a shadow verification adapter that:

- emits tickets for frozen-config replay
- audits shadow settlement packets
- verifies drift and consistency
- attaches local adoption receipts to Phase 5 readiness

Verifier results may close a gate.
They may never open one by themselves.

## Slice 6: UI and operator surfaces

Status as of Wednesday, August 5, 2026: implemented as read-only backend/UI surfaces.

Implemented in:

- `agents/coordinator.py`
- `agents/ui_agent.py`

Completed artifacts:

- read-only Commons snapshot aggregation in the coordinator
- read-only DIO gate snapshot aggregation for Phases 2, 3, 4, and 5
- `/commons.json`
- `/commons/inference.json`
- `/commons/verifier.json`
- `/commons/adoption.json`
- phase-specific counts for adopted inference and verifier packets
- contradiction visibility for Phase 4 and Phase 5 Commons verifier intake
- phase snapshots now expose `dio_gate` and per-phase `commons_pool` summaries for deterministic eligibility review

Remaining work:

- ~~wire these JSON surfaces into a dedicated dashboard panel~~
- ~~add richer visual summaries for rejection causes, contradiction counts, and ticket backlog~~
- ~~expose worker and lease drill-down cards in the desktop UI~~
- ~~add dedicated adapter services for receipt ingestion instead of relying only on store-driven intake~~

Expose read-only views for:

- active pool tickets
- remote worker receipts
- local adoption receipts
- disagreement counts
- verification failures by cause

Likely route additions:

- `/commons/inference.json`
- `/commons/verifier.json`
- `/commons/adoption.json`

### Runtime hardening completion record

Status as of Wednesday, August 5, 2026:

- ~~preserve the structured Commons authority boundary in every dashboard response~~
- ~~separate active, expired, completed, and actively leased ticket counts~~
- ~~run a governed local inference/verifier worker with no execution authority~~
- ~~revoke baseline-generated challenger receipts that falsely represented external inference~~
- ~~remove the hard-coded compact Phase-2 refusal and report non-recomputed readiness as pending~~
- ~~isolate Commons and compact phase projections from long-running analytics database locks~~
- ~~make the configured-symbol price series lock-independent and prevent cross-symbol chart mixing~~
- ~~make the Electron launcher robust when `ELECTRON_RUN_AS_NODE` is inherited~~
- ~~verify the clean desktop runtime through repeated refresh cycles without renderer errors~~
- ~~persist Phase-2 and Phase-3 DIO acceptance decisions with each completed evidence cycle~~
- ~~replace permanent compact-mode `PENDING` placeholders with the latest persisted gate decision~~
- ~~run continuous Phase-4 validation over persisted Phase-3 evidence~~
- ~~provide a live tmux acceptance watcher for Phases 1 through 5~~
- ~~scope contradiction gating to the current validation report instead of permanent historical counts~~
- ~~correct Phase-1 health accounting so the ranked-output cap is not misreported as failed observation work~~
- ~~evaluate Phase-1 readiness on configurable one-hour evidence buckets instead of a hard-coded seven-day lifetime aggregate~~
- ~~serialize Phase-2 hypothesis settlement, Phase-3 execution replay, and Phase-4 validation into one coherent hourly acceptance cycle~~
- ~~surface each sequential cycle step, elapsed time, failure, and timeout directly in the tmux research pane~~
- ~~restore compact Phase-3 and Phase-4 payload parsing by importing the JSON decoder used by the coordinator~~
- ~~regression-test compact persisted execution and validation projections~~
- ~~replace misleading generic `inactive` cards with explicit external-active, research-standby, disabled, and not-applicable states~~
- ~~show rolling Phase-1 acceptance progress and a periodic heartbeat in the tmux watcher~~
- ~~bound Phase-3 candidate expansion and reusable-history scans to prevent repeated unbounded reads of the 16 GB evidence database~~
- ~~complete a serialized Phase-2/3/4 cycle with persisted DIO decisions and zero real orders~~
- ~~run outcome-blind, symbol- and time-bounded evidence expansion across all four execution policies for the apparent FreqAI leader~~
- ~~demonstrate that the apparent FreqAI edge collapses under broader post-cost evidence rather than weakening Phase-4 gates~~
- ~~add a machine-enforced, reason-bearing federation quarantine so a falsified model cannot consume new research budget~~
- ~~bind the quarantine set into research-reuse and Commons task digests so stale positive evidence cannot cross the model boundary~~
- ~~materialize Phase-4 verifier subjects before ticket issuance and scope adopted verifier receipts to their exact validation run~~
- ~~remove stale cross-run Commons contradictions without weakening the local adversarial profitability gate~~
- ~~add leakage-safe walk-forward forecast calibration using only outcomes settled before the research-cycle cutoff~~
- ~~calibrate by model, horizon, regime, and symbol class with conservative hierarchical fallback and zero-edge shrinkage~~
- ~~require positive stressed return and probability lower bounds with symbol/time breadth before assigning the calibrated route~~
- ~~refuse sufficiently sampled failed calibrations before Phase-3 simulation while retaining under-sampled research exploration~~
- ~~persist immutable calibration receipts inside forecast evidence and bind calibration configuration into reuse and Commons digests~~
- ~~reuse one immutable Phase-2 scorecard snapshot for frontier and suppression context instead of recomputing the 16 GB evidence view twice~~
- ~~run the first persisted calibrated Phase-2/3/4 cycle with Phase 1 at 34/34 healthy runs and zero real orders~~
- ~~separate baseline activity from non-baseline `research_active` throughput in runtime reporting~~
- ~~expand the under-sampled Freqtrade pocket across four execution policies and five stress scenarios~~
- ~~confirm that every Freqtrade policy remains negative at normal and 1.5x costs, with no Phase-4 promotion~~

Current evidence is operational, not profitable authority. Phase 4 remains a
real refusal until a candidate passes every adversarial gate.

## Minimal Data Model Additions

The smallest safe field set per receipt family is:

### Common fields

- `receipt_id`
- `ticket_id`
- `lease_id`
- `worker_id`
- `created_ts`
- `challenge_nonce`
- `world_state_digest`
- `code_digest`
- `config_digest`
- `signature`

### Inference-specific fields

- `result_kind`
- `result_summary`
- `feature_schema_digest`
- `output_root`

### Verifier-specific fields

- `subject_digest`
- `verification_verdict`
- `verification_summary`

### Adoption-specific fields

- `source_receipt_id`
- `local_reproduction_verdict`
- `adoption_decision`
- `authority_ceiling`
- `reasons`

## Readiness Effects

This is how the new pool evidence should affect phase readiness.

### Phase 2

- adopted remote challenger receipts may increase candidate diversity
- no readiness gate change by themselves

### Phase 3

- adopted remote execution candidates may widen simulation search
- no execution eligibility change by themselves

### Phase 4

- adopted verifier receipts may add:
  - confirmation support
  - contradiction support
  - negative-case support
- verified contradiction should directly hurt `ready_for_phase5_review`

### Phase 5

- adopted verifier receipts may help detect frozen-config drift, settlement mismatch, and shadow instability
- they may block Phase 6 review readiness
- they may not approve Phase 6 review readiness by themselves

## Honest Risks

### Complexity risk

This can become a second architecture inside Hivenance if we overbuild it.

The cure is:

- keep pools phase-scoped
- keep receipts typed
- keep authority ceilings hard

### Fake decentralization risk

If the same machine, same operator, or same key material produces all receipts, the pool adds theater, not truth.

The launch bar should require:

- physically distinct workers
- independent keys
- fresh nonce enforcement
- real digest verification
- local reproduction before adoption

### Profit illusion risk

Remote compute breadth does not equal edge.

The pool improves:

- search quality
- replay coverage
- contradiction detection

It does not guarantee:

- positive expectancy
- executable edge
- live profit

## Final Recommendation

For Hivenance, the best first integration is not a general mining pool.

It is:

1. an `Inference Pool` that widens Phase 2 and Phase 3 challenger search without gaining any authority
2. a `Verifier Pool` that hardens Phase 4 and Phase 5 by forcing independent reproduction and contradiction handling
3. a strict local-adoption receipt that remains the only bridge from remote work to Hivenance trust

That gives the repo more research breadth and more validation pressure while preserving the core Phoenix rule:

`remote work may increase evidence, but only local governed verification may increase trust`
