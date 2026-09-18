from __future__ import annotations

from strategies.relative_value_lab.musical_cognition import MusicalMotifAccumulator
from strategies.relative_value_lab.polyphonic_entrainment import PolyphonicEntrainment
from strategies.relative_value_lab.waggle_protocol import BeeLineage, LineageRegistry, WaggleProtocol


WS_ID = "ws-1"
WS_HASH = "sha256:" + "a" * 64
STRUCT = "sha256:" + "1" * 64
STAT = "sha256:" + "2" * 64
MICRO = "sha256:" + "3" * 64
STRUCT_CHILD = "sha256:" + "4" * 64


def registry() -> LineageRegistry:
    return LineageRegistry([
        BeeLineage(STRUCT, "structural", STRUCT),
        BeeLineage(STAT, "statistical", STAT),
        BeeLineage(MICRO, "microstructure", MICRO),
        BeeLineage(STRUCT_CHILD, "structural", STRUCT, parent_lineage_digest=STRUCT),
    ])


def add(
    *,
    bus,
    acc,
    bee,
    family,
    lineage,
    kind,
    ts,
    direction="LONG_A_SHORT_B",
    horizon=10,
    evidence_root=None,
):
    evidence_root = evidence_root or ("sha256:" + bee[0] * 64)
    msg = bus.build_message(
        bee_id=bee,
        family=family,
        lineage_digest=lineage,
        message_type=kind,
        scope="A/USD__B/USD",
        hypothesis_id="motif-1",
        world_state_id=WS_ID,
        world_state_hash=WS_HASH,
        observed_at_ms=ts,
        evidence_root=evidence_root,
        horizon_seconds=horizon,
        direction=direction,
        expected_move_bps=2.0,
        uncertainty=0.3,
        independent_claimed=True,
    )
    rec = bus.publish(
        msg,
        current_world_state_id=WS_ID,
        current_world_state_hash=WS_HASH,
        now_ms=ts,
    )
    acc.ingest(message=msg, receipt=rec)
    return msg, rec


def test_independent_bees_can_entrain_without_becoming_one_lineage():
    reg = registry()
    bus = WaggleProtocol(registry=reg)
    acc = MusicalMotifAccumulator(registry=reg)

    # Early phrase: voices arrive irregularly and disagree.
    add(bus=bus, acc=acc, bee="struct", family="structural", lineage=STRUCT, kind="WAGGLE", ts=1_000)
    add(bus=bus, acc=acc, bee="stat", family="statistical", lineage=STAT, kind="DISSENT", ts=8_000, direction="LONG_B_SHORT_A")
    add(bus=bus, acc=acc, bee="micro", family="microstructure", lineage=MICRO, kind="FOLLOW", ts=14_000)

    # Later phrase: independent voices converge onto a common 5s pulse + direction.
    add(bus=bus, acc=acc, bee="struct2", family="structural", lineage=STRUCT, kind="FOLLOW", ts=20_000)
    add(bus=bus, acc=acc, bee="stat2", family="statistical", lineage=STAT, kind="FOLLOW", ts=25_000)
    add(bus=bus, acc=acc, bee="micro2", family="microstructure", lineage=MICRO, kind="FOLLOW", ts=30_000)

    receipt = PolyphonicEntrainment().score(
        hypothesis_id="motif-1",
        notes=acc.notes("motif-1"),
    )
    assert receipt.independent_voice_count == 3
    assert receipt.convergence_gain > 0.0
    assert receipt.entrainment_strength > 0.0
    assert receipt.execution_eligible is False


def test_clone_descendant_does_not_create_extra_independent_voice():
    reg = registry()
    bus = WaggleProtocol(registry=reg)
    acc = MusicalMotifAccumulator(registry=reg)

    add(bus=bus, acc=acc, bee="struct", family="structural", lineage=STRUCT, kind="WAGGLE", ts=1_000)
    add(bus=bus, acc=acc, bee="child", family="structural", lineage=STRUCT_CHILD, kind="FOLLOW", ts=6_000)

    receipt = PolyphonicEntrainment().score(
        hypothesis_id="motif-1",
        notes=acc.notes("motif-1"),
    )
    assert receipt.independent_voice_count == 1
    assert "insufficient_independent_voices" in receipt.warnings


def test_shared_evidence_root_raises_false_unison_risk():
    reg = registry()
    bus = WaggleProtocol(registry=reg)
    acc = MusicalMotifAccumulator(registry=reg)
    shared = "sha256:" + "9" * 64

    add(bus=bus, acc=acc, bee="struct", family="structural", lineage=STRUCT, kind="WAGGLE", ts=1_000, evidence_root=shared)
    add(bus=bus, acc=acc, bee="stat", family="statistical", lineage=STAT, kind="FOLLOW", ts=6_000, evidence_root=shared)
    add(bus=bus, acc=acc, bee="micro", family="microstructure", lineage=MICRO, kind="FOLLOW", ts=11_000, evidence_root=shared)

    receipt = PolyphonicEntrainment().score(
        hypothesis_id="motif-1",
        notes=acc.notes("motif-1"),
    )
    assert receipt.false_unison_risk >= 0.50
    assert "false_unison_risk" in receipt.warnings
    assert receipt.source_diversity < 0.50


def test_distinct_evidence_roots_reduce_false_unison_risk():
    reg = registry()
    bus = WaggleProtocol(registry=reg)
    acc = MusicalMotifAccumulator(registry=reg)

    add(bus=bus, acc=acc, bee="struct", family="structural", lineage=STRUCT, kind="WAGGLE", ts=1_000, evidence_root="sha256:" + "1" * 64)
    add(bus=bus, acc=acc, bee="stat", family="statistical", lineage=STAT, kind="FOLLOW", ts=6_000, evidence_root="sha256:" + "2" * 64)
    add(bus=bus, acc=acc, bee="micro", family="microstructure", lineage=MICRO, kind="FOLLOW", ts=11_000, evidence_root="sha256:" + "3" * 64)

    receipt = PolyphonicEntrainment().score(
        hypothesis_id="motif-1",
        notes=acc.notes("motif-1"),
    )
    assert receipt.source_diversity == 1.0
    assert receipt.false_unison_risk < 0.50


def test_cross_horizon_lines_remain_separate_band_entrainment():
    reg = registry()
    bus = WaggleProtocol(registry=reg)
    acc = MusicalMotifAccumulator(registry=reg)

    add(bus=bus, acc=acc, bee="struct", family="structural", lineage=STRUCT, kind="WAGGLE", ts=1_000, horizon=10, direction="LONG_A_SHORT_B")
    add(bus=bus, acc=acc, bee="stat", family="statistical", lineage=STAT, kind="FOLLOW", ts=6_000, horizon=30, direction="LONG_B_SHORT_A")
    add(bus=bus, acc=acc, bee="micro", family="microstructure", lineage=MICRO, kind="FOLLOW", ts=11_000, horizon=10, direction="LONG_A_SHORT_B")

    receipt = PolyphonicEntrainment().score(
        hypothesis_id="motif-1",
        notes=acc.notes("motif-1"),
    )
    band_names = {band.band for band in receipt.bands}
    assert band_names == {"micro", "meso"}
    assert receipt.directional_alignment >= 0.0
    assert receipt.execution_eligible is False


def test_recruitment_cascade_and_crescendo_are_descriptive_not_authority():
    reg = registry()
    bus = WaggleProtocol(registry=reg)
    acc = MusicalMotifAccumulator(registry=reg)

    add(bus=bus, acc=acc, bee="struct", family="structural", lineage=STRUCT, kind="WAGGLE", ts=1_000)
    add(bus=bus, acc=acc, bee="struct2", family="structural", lineage=STRUCT, kind="FOLLOW", ts=6_000)
    add(bus=bus, acc=acc, bee="stat", family="statistical", lineage=STAT, kind="FOLLOW", ts=11_000)
    add(bus=bus, acc=acc, bee="micro", family="microstructure", lineage=MICRO, kind="FOLLOW", ts=16_000)

    receipt = PolyphonicEntrainment().score(
        hypothesis_id="motif-1",
        notes=acc.notes("motif-1"),
    )
    assert receipt.recruitment_cascade > 0.0
    assert receipt.crescendo_strength >= 0.0
    assert receipt.promotion_eligible is False
    assert receipt.execution_eligible is False
