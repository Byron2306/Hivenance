from strategies.relative_value_lab.conducting_queen import (
    ConductingQueen,
)
from strategies.relative_value_lab.governance_epoch import (
    ResearchGovernanceEpochService,
)
from strategies.relative_value_lab.musical_cognition import (
    MusicalMotifAccumulator,
)
from strategies.relative_value_lab.polyphonic_entrainment import (
    PolyphonicEntrainment,
)
from strategies.relative_value_lab.recursive_queen_dispatch import (
    dispatch_challenge,
)
from strategies.relative_value_lab.recursive_queen_loop import (
    build_recurrence_step,
    observed_root_digest,
    request_from_notation,
)
from strategies.relative_value_lab.vns_score_conductor import (
    VNSScoreConductor,
)
from strategies.relative_value_lab.waggle_protocol import (
    BeeLineage,
    LineageRegistry,
    WaggleProtocol,
)
from strategies.relative_value_lab.world_graph import WorldGraph


STRUCT = "sha256:" + "1" * 64
STAT = "sha256:" + "2" * 64
MICRO = "sha256:" + "3" * 64


def cycle():
    return {
        "run": {
            "run_id": "recursive-r1",
            "venue": "kraken",
            "completed_at_ms": 3000,
        },
        "candidates": [{
            "symbol": "BTC/USD",
            "venue": "kraken",
            "timestamp_ms": 2900,
            "price": 100.0,
            "spread_bps": 5.0,
            "depth_usd_25bps": 100000.0,
            "quote_volume_24h": 50000000.0,
            "data_quality": 1.0,
            "freshness_sec": 1.0,
            "continuity_ratio": 1.0,
            "observation_eligible": True,
        }],
        "world_state_summary": {
            "fresh_candidate_count": 1,
        },
        "dataset_hash": "recursive-r1",
    }


def build_music(frame):
    registry = LineageRegistry([
        BeeLineage(STRUCT, "structural", STRUCT),
        BeeLineage(STAT, "statistical", STAT),
        BeeLineage(MICRO, "microstructure", MICRO),
    ])

    bus = WaggleProtocol(registry=registry)
    acc = MusicalMotifAccumulator(registry=registry)

    rows = (
        ("s", "structural", STRUCT, 1000),
        ("t", "statistical", STAT, 6000),
        ("m", "microstructure", MICRO, 11000),
    )

    for bee, family, lineage, ts in rows:
        msg = bus.build_message(
            bee_id=bee,
            family=family,
            lineage_digest=lineage,
            message_type=(
                "WAGGLE"
                if ts == 1000
                else "FOLLOW"
            ),
            scope="BTC/USD",
            hypothesis_id="recursive-motif",
            world_state_id=frame.world_state_id,
            world_state_hash=frame.world_state_hash,
            observed_at_ms=ts,
            evidence_root="sha256:" + bee[0] * 64,
            horizon_seconds=10,
            direction="LONG_A_SHORT_B",
            expected_move_bps=2.0,
            uncertainty=.2,
            independent_claimed=True,
        )

        receipt = bus.publish(
            msg,
            current_world_state_id=frame.world_state_id,
            current_world_state_hash=frame.world_state_hash,
            now_ms=ts,
        )

        acc.ingest(
            message=msg,
            receipt=receipt,
        )

    motif = acc.score("recursive-motif")

    entrainment = PolyphonicEntrainment().score(
        hypothesis_id="recursive-motif",
        notes=acc.notes("recursive-motif"),
    )

    return acc, motif, entrainment


def test_queen_request_response_reconduct_changes_interpretation_same_root():
    measure = VNSScoreConductor().conduct_cycle(
        cycle()
    )

    graph = WorldGraph(measure.frame)

    source = graph.add_node(
        organ_id="recursive_source",
        family="RECURSIVE_SOURCE",
        created_at_ms=3000,
        evidence_roots=tuple(
            obs.evidence_root
            for obs in graph.frame.observations
        ),
        lineage_id="recursive.source.v1",
        transformation_id="recursive.source.v1",
        payload={
            "observed": True,
        },
    )

    acc, motif, entrainment = build_music(
        measure.frame
    )

    epoch = (
        ResearchGovernanceEpochService
        .start_epoch_from_frame(
            measure.frame,
            started_at_ms=3000,
            ttl_ms=60000,
        )
    )

    root_before = observed_root_digest(graph)

    queen_before = ConductingQueen().conduct_against_frame(
        frame=measure.frame,
        now_ms=12000,
        hypothesis_id="recursive-motif",
        notes=acc.notes("recursive-motif"),
        motif=motif,
        entrainment=entrainment,
        epoch=epoch,
        vns_pulses=measure.pulses,
    )

    token = next(
        item
        for item in queen_before.notation_tokens
        if item.notation == "RUN_MYSTIQUE_VARIATIONS"
    )

    request = request_from_notation(
        graph=graph,
        recurrence_index=0,
        queen_receipt=queen_before,
        notation_token=token,
    )

    assert request.request_kind == "CHALLENGE"

    node_count_before = len(
        graph.queen_view(
            created_at_ms=12000
        ).nodes
    )

    response, challenge_node, mystique = (
        dispatch_challenge(
            graph=graph,
            request=request,
            queen_receipt=queen_before,
            source_nodes=(source,),
            created_at_ms=12001,
        )
    )

    node_count_after = len(
        graph.queen_view(
            created_at_ms=12001
        ).nodes
    )

    root_after_response = observed_root_digest(graph)

    queen_after = ConductingQueen().conduct_against_frame(
        frame=measure.frame,
        now_ms=12002,
        hypothesis_id="recursive-motif",
        notes=acc.notes("recursive-motif"),
        motif=motif,
        entrainment=entrainment,
        epoch=epoch,
        vns_pulses=measure.pulses,
        mystique=mystique,
    )

    root_after_queen = observed_root_digest(graph)

    step = build_recurrence_step(
        graph=graph,
        recurrence_index=0,
        queen_before=queen_before,
        queen_after=queen_after,
        request=request,
        response=response,
        graph_node_count_before=node_count_before,
        graph_node_count_after=node_count_after,
    )

    # Immutable observed world throughout recurrence.
    assert root_before == root_after_response
    assert root_before == root_after_queen

    assert (
        graph.frame.world_state_id
        == request.world_state_id
        == response.world_state_id
        == step.world_state_id
    )

    assert (
        graph.frame.world_state_hash
        == request.world_state_hash
        == response.world_state_hash
        == step.world_state_hash
    )

    # Lawful derived challenge entered the graph.
    assert response.graph_changed is True
    assert challenge_node.family == "MYSTIQUE_CHALLENGE"
    assert node_count_after == node_count_before + 1

    # Synthetic challenge never became observed evidence.
    for root in mystique.synthetic_evidence_roots:
        assert root not in challenge_node.evidence_roots

    assert mystique.prospective_evidence_eligible is False

    # Queen now hears the challenge.
    assert queen_before.mystique_fragility == 0.0
    assert queen_after.mystique_fragility == (
        mystique.fragility_score
    )

    assert queen_after.mystique_survival_rate == (
        mystique.survival_rate
    )

    # The interpretation really changed.
    assert step.interpretation_changed is True

    assert (
        step.queen_receipt_id_before
        == queen_before.receipt_id
    )

    assert (
        step.queen_receipt_id_after
        == queen_after.receipt_id
    )

    assert (
        step.queen_receipt_id_before
        != step.queen_receipt_id_after
    )

    # Still research only.
    assert queen_before.execution_eligible is False
    assert queen_after.execution_eligible is False
    assert response.execution_eligible is False
    assert step.execution_eligible is False

    assert queen_before.promotion_eligible is False
    assert queen_after.promotion_eligible is False
    assert response.promotion_eligible is False
    assert step.promotion_eligible is False


def test_recursive_challenge_is_deterministic_on_same_frozen_world():
    measure = VNSScoreConductor().conduct_cycle(
        cycle()
    )

    def run_once():
        graph = WorldGraph(measure.frame)

        source = graph.add_node(
            organ_id="recursive_source",
            family="RECURSIVE_SOURCE",
            created_at_ms=3000,
            evidence_roots=tuple(
                obs.evidence_root
                for obs in graph.frame.observations
            ),
            lineage_id="recursive.source.v1",
            transformation_id="recursive.source.v1",
            payload={"observed": True},
        )

        acc, motif, entrainment = build_music(
            measure.frame
        )

        epoch = (
            ResearchGovernanceEpochService
            .start_epoch_from_frame(
                measure.frame,
                started_at_ms=3000,
                ttl_ms=60000,
            )
        )

        before = ConductingQueen().conduct_against_frame(
            frame=measure.frame,
            now_ms=12000,
            hypothesis_id="recursive-motif",
            notes=acc.notes("recursive-motif"),
            motif=motif,
            entrainment=entrainment,
            epoch=epoch,
            vns_pulses=measure.pulses,
        )

        token = next(
            item
            for item in before.notation_tokens
            if item.notation
            == "RUN_MYSTIQUE_VARIATIONS"
        )

        request = request_from_notation(
            graph=graph,
            recurrence_index=0,
            queen_receipt=before,
            notation_token=token,
        )

        response, _, mystique = dispatch_challenge(
            graph=graph,
            request=request,
            queen_receipt=before,
            source_nodes=(source,),
            created_at_ms=12001,
        )

        after = ConductingQueen().conduct_against_frame(
            frame=measure.frame,
            now_ms=12002,
            hypothesis_id="recursive-motif",
            notes=acc.notes("recursive-motif"),
            motif=motif,
            entrainment=entrainment,
            epoch=epoch,
            vns_pulses=measure.pulses,
            mystique=mystique,
        )

        return (
            request.request_id,
            response.response_id,
            mystique.receipt_id,
            before.receipt_id,
            after.receipt_id,
            observed_root_digest(graph),
        )

    assert run_once() == run_once()
