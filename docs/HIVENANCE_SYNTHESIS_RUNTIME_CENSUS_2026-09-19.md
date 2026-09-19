# HiveNance Synthesis Runtime Census — 2026-09-19

## Verdict
The repository contains two substantial living systems that are not yet one runtime organism.

1. **Coordinator/Phoenix spine — INVOKED**
   - ObservationSwarmAgent and HypothesisSwarmAgent are instantiated by `agents/coordinator.py`.
   - RegimeOracle, StrategyCouncil and GovernanceQueen are instantiated and participate in the legacy governance path.
   - Phase-5 Shadow Flight now automatically prosecutes settled candidates through the adversarial Shadow Court and stores receipts in the canonical Phoenix datastore.
   - Crystal registry is durable and actively read/written by ObservationSwarm, HypothesisSwarm, ExecutionLab, rapid paper tape and canary machinery.

2. **Relative Value cognition organism — IMPLEMENTED, mostly not invoked by Coordinator**
   - WorldGraph, ConductingQueen, Horizon adapters, EdgeEcology, TemporalParticipationBee, ComparisonEngine, LearningMemory/retrieval/attention, VNS score/stream, TemporalTexture, Mystique, PolyphonicQuorum/Pollen, MetatronMLChallenger and related cognition exist.
   - Direct inspection of `agents/coordinator.py` on this branch finds no references to `relative_value_lab`, `ConductingQueen`, `WorldGraph`, `HorizonContext`, `TemporalParticipationBee`, `PolyphonicQuorum`, `ProspectivePollenPaperRuntime` or `EdgeEcology`.
   - Therefore these organs must not be described as runtime-synthesized merely because their unit/integration tests pass.

## Runtime status matrix

| Organ/family | Implemented | Runtime evidence | Current classification | G0 requirement |
|---|---:|---|---|---|
| ObservationSwarm | yes | Coordinator instantiates | INVOKED | trace causal outputs |
| HypothesisSwarm | yes | Coordinator instantiates | INVOKED | trace selection effects |
| RegimeOracle | yes | Coordinator instantiates | INVOKED | ablate |
| StrategyCouncil | yes | Coordinator instantiates | INVOKED | ablate |
| GovernanceQueen | yes | Coordinator instantiates | INVOKED | distinguish from ConductingQueen |
| Crystal registry | yes | canonical datastore producers/consumers | INFLUENTIAL candidate | ON/OFF ablation |
| Shadow Flight | yes | canonical Phase-5 runtime | INVOKED | prospective court |
| Adversarial Shadow Court | yes | automatic mature-intent prosecution | INVOKED | verify durable receipts |
| WorldGraph | yes | adapters/tests | NOT COORDINATOR-WIRED | bridge into synthesis runtime |
| HorizonContext | yes | WorldState + graph adapter | AVAILABLE / partial path | bridge canonical world graph |
| EdgeEcology | yes | custodied interpreter/tests | AVAILABLE / partial path | bridge canonical world graph |
| TemporalParticipationBee | yes | graph adapter | AVAILABLE | bridge + ablate |
| ComparisonEngine | yes | graph-native | AVAILABLE | bridge + ablate |
| LearningMemory/retrieval | yes | graph-native | AVAILABLE | ingest court learning automatically |
| Research obligations | yes | evidence-bound lifecycle | AVAILABLE | runtime recurrence |
| ConductingQueen | yes | rich cognition implementation | NOT COORDINATOR-WIRED | synthesis conductor |
| VNS score/stream | yes | Queen-compatible | AVAILABLE | synthesis conductor input |
| TemporalTexture | yes | Queen/VNS-compatible | AVAILABLE | synthesis conductor input |
| Mystique | yes | Queen-compatible synthetic falsification | AVAILABLE | keep synthetic/non-root |
| PolyphonicQuorum/Pollen | yes | prospective paper runtime exists | AVAILABLE / isolated runtime | bridge as attention only + ablate |
| MetatronMLChallenger | yes | relative-value implementation | AVAILABLE | challenger only + ablate |

## Critical synthesis gap
The remaining gap is not missing organs. It is **runtime composition**.

Do not merge the legacy GovernanceQueen and ConductingQueen semantically. GovernanceQueen remains the legacy safety/governance decision component. ConductingQueen becomes the research-cognition conductor over the canonical WorldGraph. Its outputs are research attention/proposals only and cannot grant execution authority.

## Synthesis bridge target
Create one research-only `SynthesisRuntime`:

```
canonical public observations / MarketMemory
        |
        +--> HorizonContext
        +--> custodied Edge FLOW + LIQUIDITY
        +--> TemporalParticipation
        +--> ComparisonEngine
        +--> LearningMemory / adversarial scars
        |
      WorldGraph
        |
  ConductingQueen
   /    |     \
 VNS  Texture  counterpoint/quorum
        |
 research attention + obligations
        |
 Phoenix hypothesis/research surfaces
```

The bridge must be observational/research-only. It may change research attention only after explicit causal receipts are emitted. It must not bypass Phoenix freezes, safety controls, or execution authority.

## G0 admission gates
1. One canonical observed-world root per cycle.
2. Every graph node exposes lineage and evidence roots.
3. Same-root transformations do not count as independent witnesses.
4. Synthetic Mystique/VNS counterfactuals never become observed roots.
5. Court learning automatically reaches LearningMemory.
6. Queen-generated recurrence becomes an evidence-bound research obligation.
7. Organ invocation and influence receipts are emitted for every participating organ.
8. Ablation can disable each organ without changing the observation tape.
9. Configuration is frozen before evaluation.
10. Execution and promotion remain false throughout G0.

When these gates pass, freeze the organism and begin **HIVENANCE SYNTHESIS GAUNTLET G0 — THE HIVE ON TRIAL**.
