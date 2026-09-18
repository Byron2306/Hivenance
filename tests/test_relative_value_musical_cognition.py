from __future__ import annotations

from strategies.relative_value_lab.musical_cognition import MusicalMotifAccumulator
from strategies.relative_value_lab.waggle_protocol import BeeLineage, LineageRegistry, WaggleProtocol


WS_ID = "ws-1"
WS_HASH = "sha256:" + "a" * 64
EVIDENCE = "sha256:" + "b" * 64
STRUCT = "sha256:" + "1" * 64
STAT = "sha256:" + "2" * 64
MICRO = "sha256:" + "3" * 64


def registry() -> LineageRegistry:
    return LineageRegistry([
        BeeLineage(STRUCT, "structural", STRUCT),
        BeeLineage(STAT, "statistical", STAT),
        BeeLineage(MICRO, "microstructure", MICRO),
    ])


def publish(bus, *, bee, family, lineage, kind, ts, direction="LONG_A_SHORT_B", horizon=10, pulse=None):
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
        evidence_root=EVIDENCE,
        horizon_seconds=horizon,
        direction=direction,
        expected_move_bps=2.0,
        uncertainty=0.3,
        independent_claimed=True,
        pulse_type=pulse,
    )
    rec = bus.publish(
        msg,
        current_world_state_id=WS_ID,
        current_world_state_hash=WS_HASH,
        now_ms=ts,
    )
    return msg, rec


def test_musical_cognition_has_no_rigid_lifecycle_state():
    acc = MusicalMotifAccumulator(registry=registry())
    score = acc.score("motif-1")
    payload = score.to_dict()
    assert "state" not in payload
    assert "lifecycle" not in payload
    assert score.note_count == 0
    assert score.execution_eligible is False


def test_lawful_waggle_notes_form_a_phrase():
    reg = registry()
    bus = WaggleProtocol(registry=reg)
    acc = MusicalMotifAccumulator(registry=reg)

    for args in [
        dict(bee="s", family="structural", lineage=STRUCT, kind="WAGGLE", ts=1_000),
        dict(bee="t", family="statistical", lineage=STAT, kind="FOLLOW", ts=6_000),
        dict(bee="m", family="microstructure", lineage=MICRO, kind="FOLLOW", ts=11_000),
    ]:
        msg, rec = publish(bus, **args)
        assert acc.ingest(message=msg, receipt=rec) is not None

    score = acc.score("motif-1")
    assert score.note_count == 3
    assert score.independent_voice_count == 3
    assert score.phrase_duration_ms == 10_000
    assert score.median_inter_onset_ms == 5_000.0
    assert score.rhythmic_regularity == 1.0
    assert score.call_response_latency_ms == 5_000
    assert score.consonance > score.dissonance
    assert score.cadence_strength > 0.0


def test_dissonance_is_preserved_as_tension_not_failure():
    reg = registry()
    bus = WaggleProtocol(registry=reg)
    acc = MusicalMotifAccumulator(registry=reg)

    rows = [
        dict(bee="s", family="structural", lineage=STRUCT, kind="WAGGLE", ts=1_000, direction="LONG_A_SHORT_B"),
        dict(bee="t", family="statistical", lineage=STAT, kind="DISSENT", ts=6_000, direction="LONG_B_SHORT_A"),
    ]
    for args in rows:
        msg, rec = publish(bus, **args)
        acc.ingest(message=msg, receipt=rec)

    score = acc.score("motif-1")
    assert score.note_count == 2
    assert score.dissonance > 0.0
    assert score.tension > 0.0
    assert score.execution_eligible is False


def test_rest_and_syncopation_emerge_from_timing():
    reg = registry()
    bus = WaggleProtocol(registry=reg)
    acc = MusicalMotifAccumulator(registry=reg)

    times = [1_000, 6_000, 11_000, 41_000]
    families = [
        ("s", "structural", STRUCT, "WAGGLE"),
        ("t", "statistical", STAT, "FOLLOW"),
        ("m", "microstructure", MICRO, "FOLLOW"),
        ("t2", "statistical", STAT, "FOLLOW"),
    ]
    for ts, (bee, family, lineage, kind) in zip(times, families):
        msg, rec = publish(bus, bee=bee, family=family, lineage=lineage, kind=kind, ts=ts)
        acc.ingest(message=msg, receipt=rec)

    score = acc.score("motif-1")
    assert score.rest_density > 0.0
    assert score.syncopation > 0.0
    assert score.rhythmic_regularity < 1.0


def test_horizon_change_counts_as_modulation():
    reg = registry()
    bus = WaggleProtocol(registry=reg)
    acc = MusicalMotifAccumulator(registry=reg)

    a, ar = publish(bus, bee="s", family="structural", lineage=STRUCT, kind="WAGGLE", ts=1_000, horizon=10)
    b, br = publish(bus, bee="t", family="statistical", lineage=STAT, kind="FOLLOW", ts=6_000, horizon=30)
    acc.ingest(message=a, receipt=ar)
    acc.ingest(message=b, receipt=br)

    score = acc.score("motif-1")
    assert score.modulation_count >= 1
    assert set(score.bands) == {"micro", "meso"}


def test_alarm_becomes_tension_not_positive_authority():
    reg = registry()
    bus = WaggleProtocol(registry=reg)
    acc = MusicalMotifAccumulator(registry=reg)

    msg, rec = publish(
        bus,
        bee="s",
        family="structural",
        lineage=STRUCT,
        kind="ALARM",
        ts=1_000,
        pulse="ALARM_PULSE",
    )
    acc.ingest(message=msg, receipt=rec)
    score = acc.score("motif-1")
    assert score.tension > 0.0
    assert score.execution_eligible is False
    assert score.promotion_eligible is False


def test_refused_waggle_never_enters_the_score():
    reg = registry()
    bus = WaggleProtocol(registry=reg)
    acc = MusicalMotifAccumulator(registry=reg)

    msg = bus.build_message(
        bee_id="s",
        family="structural",
        lineage_digest=STRUCT,
        message_type="WAGGLE",
        scope="A/USD__B/USD",
        hypothesis_id="motif-1",
        world_state_id=WS_ID,
        world_state_hash="sha256:" + "c" * 64,
        observed_at_ms=1_000,
        evidence_root=EVIDENCE,
        horizon_seconds=10,
        direction="LONG_A_SHORT_B",
        independent_claimed=True,
    )
    rec = bus.publish(
        msg,
        current_world_state_id=WS_ID,
        current_world_state_hash=WS_HASH,
        now_ms=1_000,
    )
    assert rec.accepted is False
    assert acc.ingest(message=msg, receipt=rec) is None
    assert acc.score("motif-1").note_count == 0
