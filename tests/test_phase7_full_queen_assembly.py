from strategies.relative_value_lab.conducting_queen import ConductingQueen
from strategies.relative_value_lab.governance_epoch import (
    ResearchGovernanceEpochService,
)
from strategies.relative_value_lab.musical_cognition import (
    MusicalMotifAccumulator,
)
from strategies.relative_value_lab.polyphonic_entrainment import (
    PolyphonicEntrainment,
)
from strategies.relative_value_lab.queen_input_assembly import (
    REQUIRED_CHANNELS,
    assemble_queen_inputs,
    channel,
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


def cycle():
    return {
        "run": {
            "run_id": "phase7-full",
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
        "world_state_summary": {"fresh_candidate_count": 1},
        "dataset_hash": "phase7-full",
    }


def music(frame):
    reg = LineageRegistry([
        BeeLineage(STRUCT, "structural", STRUCT),
        BeeLineage(STAT, "statistical", STAT),
    ])

    bus = WaggleProtocol(registry=reg)
    acc = MusicalMotifAccumulator(registry=reg)

    for bee, family, lineage, ts, kind in (
        ("s", "structural", STRUCT, 1000, "WAGGLE"),
        ("t", "statistical", STAT, 2000, "FOLLOW"),
    ):
        msg = bus.build_message(
            bee_id=bee,
            family=family,
            lineage_digest=lineage,
            message_type=kind,
            scope="BTC/USD",
            hypothesis_id="phase7-full",
            world_state_id=frame.world_state_id,
            world_state_hash=frame.world_state_hash,
            observed_at_ms=ts,
            evidence_root="sha256:" + (
                "3" if bee == "s" else "4"
            ) * 64,
            horizon_seconds=10,
            direction="LONG_A_SHORT_B",
            expected_move_bps=1.0,
            uncertainty=.2,
            independent_claimed=True,
        )

        rec = bus.publish(
            msg,
            current_world_state_id=frame.world_state_id,
            current_world_state_hash=frame.world_state_hash,
            now_ms=ts,
        )

        acc.ingest(message=msg, receipt=rec)

    return (
        acc,
        acc.score("phase7-full"),
        PolyphonicEntrainment().score(
            hypothesis_id="phase7-full",
            notes=acc.notes("phase7-full"),
        ),
    )


def full_channels(graph):
    node = graph.add_node(
        organ_id="phase7-test",
        family="PHASE7_SOURCE",
        created_at_ms=3000,
        evidence_roots=tuple(
            obs.evidence_root
            for obs in graph.frame.observations
        ),
        lineage_id="phase7-test",
        transformation_id="phase7-test.v1",
        payload={"ok": True},
    )

    return {
        name: channel(
            name=name,
            state="PRESENT",
            source_nodes=(node,),
            source_receipt_ids=("receipt-" + name.lower(),),
            payload={"test": True},
        )
        for name in REQUIRED_CHANNELS
    }


def test_full_17_channel_assembly_is_complete():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    assembly = assemble_queen_inputs(
        queen_view=graph.queen_view(created_at_ms=3100),
        created_at_ms=3100,
        channels=full_channels(graph),
    )

    assert len(assembly.channels) == 17
    assert assembly.completeness_ratio == 1.0
    assert set(assembly.present_channels) == set(REQUIRED_CHANNELS)
    assert assembly.absent_channels == ()
    assert assembly.disabled_channels == ()
    assert assembly.error_channels == ()


def test_queen_receipt_carries_explicit_channel_completeness():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    assembly = assemble_queen_inputs(
        queen_view=graph.queen_view(created_at_ms=3100),
        created_at_ms=3100,
        channels=full_channels(graph),
    )

    acc, motif, ent = music(measure.frame)

    epoch = ResearchGovernanceEpochService.start_epoch_from_frame(
        measure.frame,
        started_at_ms=3000,
        ttl_ms=10000,
    )

    receipt = ConductingQueen().conduct_against_frame(
        frame=measure.frame,
        now_ms=3200,
        hypothesis_id="phase7-full",
        notes=acc.notes("phase7-full"),
        motif=motif,
        entrainment=ent,
        epoch=epoch,
        queen_input_assembly=assembly,
    )

    assert receipt.input_assembly_id == assembly.assembly_id
    assert receipt.input_completeness_ratio == 1.0
    assert len(receipt.input_channel_states) == 17
    assert set(receipt.input_present_channels) == set(REQUIRED_CHANNELS)
    assert receipt.input_absent_channels == ()
    assert receipt.input_disabled_channels == ()
    assert receipt.input_error_channels == ()

    assert receipt.execution_eligible is False
    assert receipt.promotion_eligible is False


def test_one_channel_mask_changes_only_that_channel():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    channels = full_channels(graph)

    channels["MYSTIQUE_CHALLENGE"] = channel(
        name="MYSTIQUE_CHALLENGE",
        state="DISABLED_BY_MASK",
        reason="phase7_exit_mask_test",
    )

    assembly = assemble_queen_inputs(
        queen_view=graph.queen_view(created_at_ms=3100),
        created_at_ms=3100,
        channels=channels,
    )

    assert assembly.disabled_channels == (
        "MYSTIQUE_CHALLENGE",
    )

    assert len(assembly.present_channels) == 16

    for name in REQUIRED_CHANNELS:
        state = next(
            item.state
            for item in assembly.channels
            if item.name == name
        )

        if name == "MYSTIQUE_CHALLENGE":
            assert state == "DISABLED_BY_MASK"
        else:
            assert state == "PRESENT"


def test_missing_channel_is_explicit_not_fake_zero():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    channels = full_channels(graph)
    del channels["COGNITIVE_METABOLISM"]

    assembly = assemble_queen_inputs(
        queen_view=graph.queen_view(created_at_ms=3100),
        created_at_ms=3100,
        channels=channels,
    )

    item = next(
        x
        for x in assembly.channels
        if x.name == "COGNITIVE_METABOLISM"
    )

    assert item.state == "ABSENT_DATA"
    assert "COGNITIVE_METABOLISM" in assembly.absent_channels
    assert assembly.completeness_ratio == round(16 / 17, 6)


def test_queen_rejects_assembly_from_other_world():
    first = VNSScoreConductor().conduct_cycle(cycle())
    first_graph = WorldGraph(first.frame)

    assembly = assemble_queen_inputs(
        queen_view=first_graph.queen_view(created_at_ms=3100),
        created_at_ms=3100,
        channels=full_channels(first_graph),
    )

    payload = cycle()
    payload["run"]["run_id"] = "other"
    payload["run"]["completed_at_ms"] = 6000
    payload["candidates"][0]["timestamp_ms"] = 5900
    payload["candidates"][0]["price"] = 150.0

    second = VNSScoreConductor().conduct_cycle(payload)

    acc, motif, ent = music(second.frame)

    epoch = ResearchGovernanceEpochService.start_epoch_from_frame(
        second.frame,
        started_at_ms=6000,
        ttl_ms=10000,
    )

    try:
        ConductingQueen().conduct_against_frame(
            frame=second.frame,
            now_ms=6100,
            hypothesis_id="phase7-full",
            notes=acc.notes("phase7-full"),
            motif=motif,
            entrainment=ent,
            epoch=epoch,
            queen_input_assembly=assembly,
        )
    except ValueError as exc:
        assert "queen_input_assembly_world_state_mismatch" in str(exc)
    else:
        raise AssertionError(
            "expected mismatched assembly refusal"
        )
