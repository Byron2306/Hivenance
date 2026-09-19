# HiveNance S0.1 Queen / Triune / Epoch Call Graph

Date: 2026-09-19
Branch: hivenance-phoenix-edge-ecology
Status: VERIFIED FROM CURRENT CODE
Authority: research only; execution_eligible=false; promotion_eligible=false.

## Result

The triple brain is already real code and should not be redesigned.

`ConductingQueen.conduct_against_frame()` binds the Queen to one immutable `CanonicalScoreFrame` and prevents callers from overriding its world_state_id/hash. `conduct()` then listens to motif notes, entrainment, the active research epoch, VNS, harmonic context, TemporalTexture, EdgeChorus, motif hunting, colony correlations, causal cascade, HivePulse, polyphonic resonance, Mystique falsification, cognitive metabolism and learned challengers.

It writes exactly three `TriuneScoreSheet` objects:

### METATRON
Current code synthesizes the whole composition. It hears cadence, entrainment, polyphonic pressure, VNS energy/novelty/echo, temporal cadence, edge chorus, motif hunting, correlation harmony, cascade, resonance, Mystique survival/fragility, metabolic strain/breath and learned challenger health/dissent.

Standing invitations include `weave_full_score` and `listen_across_horizons`.

### MICHAEL
Current code is the tuning/governance brain. It watches epoch consonance, world-state tension, source diversity, timing jitter/drift/burstiness/entropy, edge mesh/settlement, dependent correlation, negative authority pulses, resonance drift, synthetic contamination, metabolic duplication/strain and learned-voice drift/dependence.

Its invitations already include narrowing notation, requesting new timbre, refreshing VNS, retuning cadence, discounting dependent correlation, sealing synthetic chambers, thinning orchestration and preserving ML dependence labels.

### LOKI
Current code is the adversarial brain. It watches false unison, discord, subtle shifts, burstiness, jitter and unresolved edge resolution. It explicitly seeks countermelody, challenges apparent resolution, attacks echo/novelty artifacts, preserves productive dissonance, challenges correlation-not-causation and propagation mechanisms, interrogates counterfactual failures, attacks critical dependencies and challenges learned voices.

## Current Queen output

The three minds feed:
1. `_conducting_gestures()`: continuous gestures such as LISTEN_CONTINUOUSLY, THIN_VNS_ECHO, HOLD_DISSONANCE_OPEN, INVITE_NEW_TIMBRE, REHEARSE_EDGE_CHORUS, AMPLIFY_SEARCH, WEAVE_COLONY_COUNTERPOINT, FOLLOW_CASCADE, CONDUCT_COUNTERPOINT, HOLD_SUSPENSION, THIN_ORCHESTRATION, RETUNE_LEARNED_VOICE and REKEY_PROGRESSIVELY.
2. `_issue_notation()`: bounded `QueenNotationToken` research requests, world/epoch bound, expiring, maximum-use limited and explicitly non-executable/non-promotable.
3. `QueenPolyphonicReceipt`: immutable receipt containing the three score sheets, notation, gestures and reasons.

## Epoch substrate

`ResearchGovernanceEpoch` already binds:
- epoch_id;
- score_id;
- genre_mode;
- strictness_level;
- scope;
- world_state_id/hash;
- start/expiry;
- reason;
- previous_epoch_id;
- research-only authority.

`ResearchGovernanceEpochService` already starts epochs from a fresh CanonicalScoreFrame, rotates epochs and validates fail-closed against world-state drift, expiry and scope.

Disposition: REUSE. Future LISTEN/SEARCH/CHALLENGE/etc. semantics must map onto this substrate, not replace it.

## Minimal synthesis decision

Do not add another reasoning brain.

Do not redesign the Queen.

Do not create a parallel orchestration engine.

The next implementation should be the smallest useful bridge:

**WorldGraph / QueenView -> existing ConductingQueen inputs.**

New Evidence Bees and Comparison outputs become lawful graph-bound testimony. The existing triple brain hears them through the current musical cognition stack. Existing Queen gestures/notation conduct what should be refreshed, challenged, compared, thinned or amplified.

This preserves the weird machinery while giving it richer market senses.

## S0.1 PASS criteria

PASS:
- triple brain exists and roles are explicit in code;
- Queen is bound to canonical observed world;
- epoch service exists and rotates/validates fail-closed;
- Queen emits bounded research notation and gestures;
- no execution/promotion authority is granted;
- WorldGraph can therefore be implemented as an input/view adapter rather than a Queen rewrite.

S0.1 STATUS: PASS.
