from strategies.relative_value_lab.edge_chorus_harmony import (
    EdgeChorus,
    EdgeChorusObservation,
    EdgeChorusSpec,
)
from strategies.relative_value_lab.musical_cognition import (
    MusicalMotifAccumulator,
)
from strategies.relative_value_lab.polyphonic_entrainment import (
    PolyphonicEntrainment,
)
from strategies.relative_value_lab.polyphia_queen_assembly import (
    assemble_polyphia_channels,
)
from strategies.relative_value_lab.queen_input_assembly import (
    assemble_queen_inputs,
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


def music(frame):
    reg = LineageRegistry([
        BeeLineage(STRUCT, "structural", STRUCT),
        BeeLineage(STAT, "statistical", STAT),
    ])

    bus = WaggleProtocol(registry=reg)
    acc = MusicalMotifAccumulator(registry=reg)

    rows = (
        ("s", "structural", STRUCT, 1000, "WAGGLE"),
        ("t", "statistical", STAT, 2000, "FOLLOW"),
    )

    for bee, family, lineage, ts, kind in rows:
        msg = bus.build_message(
            bee_id=bee,
            family=family,
            lineage_digest=lineage,
            message_type=kind,
            scope="BTC/USD",
            hypothesis_id="motif-1",
            world_state_id=frame.world_state_id,
            world_state_hash=frame.world_state_hash,
            observed_at_ms=ts,
            evidence_root=(
                "sha256:" + ("3" if bee == "s" else "4") * 64
            ),
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

        acc.ingest(message=msg, receipt=receipt)

    notes = acc.notes("motif-1")
    motif = acc.score("motif-1")
    ent = PolyphonicEntrainment().score(
        hypothesis_id="motif-1",
        notes=notes,
    )

    return notes, motif, ent


def edge():
    spec = EdgeChorusSpec(
        edge_type="research_phrase",
        required_participants=("world_state_bind",),
        expected_sequence=("world_state_bind",),
    )

    obs = EdgeChorusObservation(
        action_id="edge-1",
        edge_type="research_phrase",
        observed_participants=("world_state_bind",),
        observed_sequence=("world_state_bind",),
        timestamps_ms={"world_state_bind": 1000},
    )

    return EdgeChorus().score(spec, obs)


def test_polyphia_channels_present_and_traceable():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    notes, motif, ent = music(measure.frame)

    base = graph.add_node(
        organ_id="test",
        family="TEST_SOURCE",
        created_at_ms=3000,
        evidence_roots=tuple(
            obs.evidence_root
            for obs in measure.frame.observations
        ),
        lineage_id="test",
        transformation_id="test.v1",
        payload={"ok": True},
    )

    channels, nodes = assemble_polyphia_channels(
        graph,
        notes=notes,
        motif=motif,
        entrainment=ent,
        edge_chorus=edge(),
        edge_source_nodes=(base,),
        created_at_ms=3100,
    )

    assembly = assemble_queen_inputs(
        queen_view=graph.queen_view(created_at_ms=3100),
        created_at_ms=3100,
        channels=channels,
    )

    expected = {
        "EDGE_CHORUS",
        "MOTIF_NOTES",
        "MOTIF_ACCUMULATOR",
        "POLYPHONIC_ENTRAINMENT",
    }

    assert expected.issubset(set(assembly.present_channels))
    assert len(nodes) == 4

    for name in expected:
        item = next(x for x in assembly.channels if x.name == name)
        assert item.source_node_ids
        assert item.source_receipt_ids


def test_motif_notes_preserve_waggle_receipt_provenance():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    notes, motif, ent = music(measure.frame)

    channels, _ = assemble_polyphia_channels(
        graph,
        notes=notes,
        motif=motif,
        entrainment=ent,
        edge_chorus=None,
        created_at_ms=3100,
    )

    item = channels["MOTIF_NOTES"]

    assert item.state == "PRESENT"
    assert set(item.source_receipt_ids) == {
        note.receipt_id for note in notes
    }


def test_shared_note_roots_do_not_become_extra_graph_roots():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    notes, motif, ent = music(measure.frame)

    assemble_polyphia_channels(
        graph,
        notes=notes,
        motif=motif,
        entrainment=ent,
        edge_chorus=None,
        created_at_ms=3100,
    )

    view = graph.queen_view(created_at_ms=3100)

    expected = {
        note.evidence_root
        for note in notes
    }

    assert expected.issubset({
        root
        for node in view.nodes
        for root in node.evidence_roots
    })


def test_missing_edge_chorus_is_not_applicable_not_zero():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    notes, motif, ent = music(measure.frame)

    channels, _ = assemble_polyphia_channels(
        graph,
        notes=notes,
        motif=motif,
        entrainment=ent,
        edge_chorus=None,
        created_at_ms=3100,
    )

    assert channels["EDGE_CHORUS"].state == "NOT_APPLICABLE"


def test_edge_chorus_without_provenance_is_error():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    notes, motif, ent = music(measure.frame)

    channels, _ = assemble_polyphia_channels(
        graph,
        notes=notes,
        motif=motif,
        entrainment=ent,
        edge_chorus=edge(),
        edge_source_nodes=(),
        created_at_ms=3100,
    )

    assert channels["EDGE_CHORUS"].state == "ERROR"


def test_disabling_entrainment_changes_only_entrainment():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    graph = WorldGraph(measure.frame)

    notes, motif, ent = music(measure.frame)

    channels, _ = assemble_polyphia_channels(
        graph,
        notes=notes,
        motif=motif,
        entrainment=ent,
        edge_chorus=None,
        created_at_ms=3100,
        disabled=frozenset({"POLYPHONIC_ENTRAINMENT"}),
    )

    assert (
        channels["POLYPHONIC_ENTRAINMENT"].state
        == "DISABLED_BY_MASK"
    )

    assert channels["MOTIF_NOTES"].state == "PRESENT"
    assert channels["MOTIF_ACCUMULATOR"].state == "PRESENT"


def test_note_world_mismatch_is_refused():
    first = VNSScoreConductor().conduct_cycle(cycle())
    notes, motif, ent = music(first.frame)

    payload = cycle()
    payload["run"]["run_id"] = "other"
    payload["run"]["completed_at_ms"] = 6000
    payload["candidates"][0]["timestamp_ms"] = 5900
    payload["candidates"][0]["price"] = 120.0

    second = VNSScoreConductor().conduct_cycle(payload)
    graph = WorldGraph(second.frame)

    try:
        assemble_polyphia_channels(
            graph,
            notes=notes,
            motif=motif,
            entrainment=ent,
            edge_chorus=None,
            created_at_ms=6100,
        )
    except ValueError as exc:
        assert "motif_note_world_state" in str(exc)
    else:
        raise AssertionError("expected motif world mismatch")
