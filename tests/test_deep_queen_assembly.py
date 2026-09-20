from dataclasses import dataclass

from strategies.relative_value_lab.deep_queen_assembly import (
    assemble_deep_channels,
)
from strategies.relative_value_lab.governance_epoch import (
    ResearchGovernanceEpochService,
)
from strategies.relative_value_lab.mystique_variations import (
    CounterfactualVariation,
    MystiqueCounterfactualVariations,
    MystiqueObservedScore,
)
from strategies.relative_value_lab.queen_input_assembly import (
    assemble_queen_inputs,
)
from strategies.relative_value_lab.vns_score_conductor import (
    VNSScoreConductor,
)
from strategies.relative_value_lab.world_graph import WorldGraph


def cycle():
    return {
        "run": {
            "run_id": "r1",
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
        "dataset_hash": "dataset-r1",
    }


def source(graph):
    roots = tuple(
        obs.evidence_root
        for obs in graph.frame.observations
    )

    return graph.add_node(
        organ_id="source",
        family="SOURCE",
        created_at_ms=3000,
        evidence_roots=roots,
        lineage_id="source",
        transformation_id="source.v1",
        payload={"ok": True},
    )


def mystique(frame):
    parent = MystiqueObservedScore(
        score_id="observed-1",
        hypothesis_id="h1",
        world_state_id=frame.world_state_id,
        world_state_hash=frame.world_state_hash,
        observed_at_ms=3000,
        metrics={
            "motif_strength": .9,
            "relationship_stability": .9,
            "flow_support": .9,
            "depth_recovery": .9,
            "timing_coherence": .9,
            "lineage_diversity": .9,
            "horizon_compatibility": .9,
            "cost_clearance": .9,
        },
        evidence_roots=tuple(
            obs.evidence_root
            for obs in frame.observations
        ),
        lineage_roots=("l1",),
    )

    return MystiqueCounterfactualVariations().challenge(
        parent,
        variations=(
            CounterfactualVariation(
                "timing",
                "PERTURB_TIMING",
                "timing_coherence",
                .2,
                "test timing",
            ),
        ),
    )


def test_synthetic_mystique_roots_do_not_increase_graph_diversity():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)
    src = source(graph)

    before = graph.queen_view(
        created_at_ms=3001
    ).independent_evidence_root_count

    receipt = mystique(measure.frame)

    channels, nodes = assemble_deep_channels(
        graph,
        mystique=receipt,
        mystique_sources=(src,),
        created_at_ms=3100,
    )

    after = graph.queen_view(
        created_at_ms=3100
    ).independent_evidence_root_count

    assert channels["MYSTIQUE_CHALLENGE"].state == "PRESENT"
    assert before == after

    node = next(
        n for n in nodes
        if n.family == "MYSTIQUE_CHALLENGE"
    )

    for synthetic_root in receipt.synthetic_evidence_roots:
        assert synthetic_root not in node.evidence_roots

    assert (
        node.payload["synthetic_roots_are_observed_evidence"]
        is False
    )


def test_valid_governance_epoch_is_present():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    epoch = ResearchGovernanceEpochService.start_epoch_from_frame(
        measure.frame,
        started_at_ms=3000,
        ttl_ms=10000,
    )

    validation = (
        ResearchGovernanceEpochService.validate_against_frame(
            epoch,
            frame=measure.frame,
            now_ms=3100,
        )
    )

    channels, _ = assemble_deep_channels(
        graph,
        epoch=epoch,
        epoch_validation=validation,
        created_at_ms=3100,
    )

    assert channels["GOVERNANCE_EPOCH"].state == "PRESENT"


def test_missing_mystique_is_not_applicable():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    channels, _ = assemble_deep_channels(
        graph,
        created_at_ms=3100,
    )

    assert (
        channels["MYSTIQUE_CHALLENGE"].state
        == "NOT_APPLICABLE"
    )


def test_derived_channel_without_sources_is_error():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    @dataclass
    class Harmonic:
        receipt_id: str = "harm-1"
        state: str = "MIXED"
        resonance_score: float = .5
        discord_score: float = .4

        def to_dict(self):
            return {
                "receipt_id": self.receipt_id,
                "state": self.state,
                "resonance_score": self.resonance_score,
                "discord_score": self.discord_score,
            }

    channels, _ = assemble_deep_channels(
        graph,
        harmonic=Harmonic(),
        harmonic_sources=(),
        created_at_ms=3100,
    )

    assert channels["HARMONIC_CONTEXT"].state == "ERROR"


def test_channel_mask_isolated_to_one_deep_channel():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    epoch = ResearchGovernanceEpochService.start_epoch_from_frame(
        measure.frame,
        started_at_ms=3000,
        ttl_ms=10000,
    )

    validation = (
        ResearchGovernanceEpochService.validate_against_frame(
            epoch,
            frame=measure.frame,
            now_ms=3100,
        )
    )

    channels, _ = assemble_deep_channels(
        graph,
        epoch=epoch,
        epoch_validation=validation,
        created_at_ms=3100,
        disabled=frozenset({"MYSTIQUE_CHALLENGE"}),
    )

    assert (
        channels["MYSTIQUE_CHALLENGE"].state
        == "DISABLED_BY_MASK"
    )
    assert channels["GOVERNANCE_EPOCH"].state == "PRESENT"


def test_full_assembly_keeps_unsupplied_channels_explicit():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    epoch = ResearchGovernanceEpochService.start_epoch_from_frame(
        measure.frame,
        started_at_ms=3000,
        ttl_ms=10000,
    )

    validation = (
        ResearchGovernanceEpochService.validate_against_frame(
            epoch,
            frame=measure.frame,
            now_ms=3100,
        )
    )

    deep, _ = assemble_deep_channels(
        graph,
        epoch=epoch,
        epoch_validation=validation,
        created_at_ms=3100,
    )

    assembly = assemble_queen_inputs(
        queen_view=graph.queen_view(created_at_ms=3100),
        created_at_ms=3100,
        channels=deep,
    )

    assert "GOVERNANCE_EPOCH" in assembly.present_channels
    assert "VNS_SCORE_STREAM" in assembly.absent_channels
    assert "POLYPHONIC_RESONANCE" in assembly.absent_channels
