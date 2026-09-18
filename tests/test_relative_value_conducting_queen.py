from __future__ import annotations

from strategies.relative_value_lab.conducting_queen import ConductingQueen
from strategies.relative_value_lab.governance_epoch import ResearchGovernanceEpochService
from strategies.relative_value_lab.musical_cognition import MusicalMotifAccumulator
from strategies.relative_value_lab.polyphonic_entrainment import PolyphonicEntrainment
from strategies.relative_value_lab.waggle_protocol import BeeLineage, LineageRegistry, WaggleProtocol


WS_ID = "ws-queen"
WS_HASH = "sha256:" + "a" * 64
STRUCT = "sha256:" + "1" * 64
STAT = "sha256:" + "2" * 64
MICRO = "sha256:" + "3" * 64


def registry() -> LineageRegistry:
    return LineageRegistry([
        BeeLineage(STRUCT, "structural", STRUCT),
        BeeLineage(STAT, "statistical", STAT),
        BeeLineage(MICRO, "microstructure", MICRO),
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
    move=2.0,
    uncertainty=0.3,
    horizon=10,
    pulse=None,
    evidence_root=None,
):
    root = evidence_root or ("sha256:" + bee[0] * 64)
    msg = bus.build_message(
        bee_id=bee,
        family=family,
        lineage_digest=lineage,
        message_type=kind,
        scope="A/USD__B/USD",
        hypothesis_id="motif-q",
        world_state_id=WS_ID,
        world_state_hash=WS_HASH,
        observed_at_ms=ts,
        evidence_root=root,
        horizon_seconds=horizon,
        direction=direction,
        expected_move_bps=move,
        uncertainty=uncertainty,
        independent_claimed=True,
        pulse_type=pulse,
    )
    rec = bus.publish(
        msg,
        current_world_state_id=WS_ID,
        current_world_state_hash=WS_HASH,
        now_ms=ts,
    )
    acc.ingest(message=msg, receipt=rec)
    return msg, rec


def build_phrase():
    reg = registry()
    bus = WaggleProtocol(registry=reg)
    acc = MusicalMotifAccumulator(registry=reg)

    add(bus=bus, acc=acc, bee="struct", family="structural", lineage=STRUCT, kind="WAGGLE", ts=1_000, move=1.0)
    add(bus=bus, acc=acc, bee="stat", family="statistical", lineage=STAT, kind="FOLLOW", ts=6_000, move=1.4)
    add(bus=bus, acc=acc, bee="micro", family="microstructure", lineage=MICRO, kind="FOLLOW", ts=11_000, move=1.8)
    add(bus=bus, acc=acc, bee="struct2", family="structural", lineage=STRUCT, kind="FOLLOW", ts=16_000, move=2.2)
    add(bus=bus, acc=acc, bee="stat2", family="statistical", lineage=STAT, kind="FOLLOW", ts=21_000, move=2.4)
    add(bus=bus, acc=acc, bee="micro2", family="microstructure", lineage=MICRO, kind="FOLLOW", ts=26_000, move=2.6)

    motif = acc.score("motif-q")
    entrainment = PolyphonicEntrainment().score(
        hypothesis_id="motif-q",
        notes=acc.notes("motif-q"),
    )
    return acc, motif, entrainment


def epoch(*, started=0, ttl=60_000, world_hash=WS_HASH):
    return ResearchGovernanceEpochService.start_epoch(
        world_state_id=WS_ID,
        world_state_hash=world_hash,
        started_at_ms=started,
        ttl_ms=ttl,
        genre_mode="watchful",
        strictness_level="standard",
        scope="relative_value_lab",
        reason="test_score",
    )


def test_epoch_binds_score_genre_strictness_and_world_state():
    e = epoch()
    assert e.score_id == "watchful_standard_v1"
    assert e.genre_mode == "watchful"
    assert e.strictness_level == "standard"
    assert e.world_state_hash == WS_HASH
    assert e.execution_eligible is False
    assert e.promotion_eligible is False


def test_epoch_world_state_drift_fails_closed():
    e = epoch()
    check = ResearchGovernanceEpochService.validate(
        e,
        now_ms=10_000,
        world_state_id=WS_ID,
        world_state_hash="sha256:" + "f" * 64,
        scope="relative_value_lab",
    )
    assert check.valid is False
    assert "epoch_world_state_drift" in check.reasons


def test_epoch_expiry_fails_closed():
    e = epoch(ttl=10_000)
    check = ResearchGovernanceEpochService.validate(
        e,
        now_ms=10_000,
        world_state_id=WS_ID,
        world_state_hash=WS_HASH,
        scope="relative_value_lab",
    )
    assert check.valid is False
    assert "epoch_expired" in check.reasons


def test_rotated_epoch_keeps_previous_epoch_lineage():
    e1 = epoch()
    e2 = ResearchGovernanceEpochService.rotate_epoch(
        e1,
        world_state_id=WS_ID,
        world_state_hash=WS_HASH,
        started_at_ms=30_000,
        ttl_ms=60_000,
        reason="modulation",
        genre_mode="fortified",
    )
    assert e2.previous_epoch_id == e1.epoch_id
    assert e2.epoch_id != e1.epoch_id
    assert e2.score_id == "fortified_standard_v1"


def test_queen_obeys_valid_epoch_and_remains_research_only():
    acc, motif, entrainment = build_phrase()
    receipt = ConductingQueen().conduct(
        hypothesis_id="motif-q",
        notes=acc.notes("motif-q"),
        motif=motif,
        entrainment=entrainment,
        epoch=epoch(),
        now_ms=30_000,
        world_state_id=WS_ID,
        world_state_hash=WS_HASH,
    )
    assert receipt.epoch_valid is True
    assert receipt.execution_eligible is False
    assert receipt.promotion_eligible is False
    assert "epoch_in_tune" in receipt.triune.michael_validation


def test_queen_rests_and_rekeys_when_epoch_is_invalid():
    acc, motif, entrainment = build_phrase()
    receipt = ConductingQueen().conduct(
        hypothesis_id="motif-q",
        notes=acc.notes("motif-q"),
        motif=motif,
        entrainment=entrainment,
        epoch=epoch(world_hash="sha256:" + "f" * 64),
        now_ms=30_000,
        world_state_id=WS_ID,
        world_state_hash=WS_HASH,
    )
    assert receipt.epoch_valid is False
    assert receipt.conducting_cues == ("REST", "REKEY_EPOCH")
    assert "epoch_world_state_drift" in receipt.reasons


def test_queen_hears_voice_pitch_tone_and_timbre():
    acc, motif, entrainment = build_phrase()
    receipt = ConductingQueen().conduct(
        hypothesis_id="motif-q",
        notes=acc.notes("motif-q"),
        motif=motif,
        entrainment=entrainment,
        epoch=epoch(),
        now_ms=30_000,
        world_state_id=WS_ID,
        world_state_hash=WS_HASH,
    )
    assert len(receipt.voice_acoustics) == 3
    assert all(v.pitch_center_bps is not None for v in receipt.voice_acoustics)
    assert all(0.0 <= v.tone_stability <= 1.0 for v in receipt.voice_acoustics)
    assert all(0.0 <= v.timbre_evidence_diversity <= 1.0 for v in receipt.voice_acoustics)


def test_subtle_pitch_timbre_shift_is_audible():
    reg = registry()
    bus = WaggleProtocol(registry=reg)
    acc = MusicalMotifAccumulator(registry=reg)

    # Early phrase is soft and certain.
    add(bus=bus, acc=acc, bee="struct", family="structural", lineage=STRUCT, kind="WAGGLE", ts=1_000, move=0.5, uncertainty=0.1)
    add(bus=bus, acc=acc, bee="stat", family="statistical", lineage=STAT, kind="FOLLOW", ts=6_000, move=0.6, uncertainty=0.1)
    add(bus=bus, acc=acc, bee="micro", family="microstructure", lineage=MICRO, kind="FOLLOW", ts=11_000, move=0.7, uncertainty=0.1)

    # Later phrase shifts pitch and texture.
    add(bus=bus, acc=acc, bee="struct2", family="structural", lineage=STRUCT, kind="FOLLOW", ts=16_000, move=3.0, uncertainty=0.8, pulse="DISCOVERY_PULSE")
    add(bus=bus, acc=acc, bee="stat2", family="statistical", lineage=STAT, kind="FOLLOW", ts=21_000, move=3.2, uncertainty=0.8, pulse="DISCOVERY_PULSE")
    add(bus=bus, acc=acc, bee="micro2", family="microstructure", lineage=MICRO, kind="FOLLOW", ts=26_000, move=3.4, uncertainty=0.8, pulse="DISCOVERY_PULSE")

    motif = acc.score("motif-q")
    entrainment = PolyphonicEntrainment().score(
        hypothesis_id="motif-q",
        notes=acc.notes("motif-q"),
    )
    receipt = ConductingQueen().conduct(
        hypothesis_id="motif-q",
        notes=acc.notes("motif-q"),
        motif=motif,
        entrainment=entrainment,
        epoch=epoch(),
        now_ms=30_000,
        world_state_id=WS_ID,
        world_state_hash=WS_HASH,
    )
    assert receipt.subtle_shift_score >= 0.5
    assert "LISTEN_FOR_MODULATION" in receipt.conducting_cues
    assert "hidden_timbre_or_pitch_shift" in receipt.triune.loki_counterpoint


def test_false_unison_calls_for_counterpoint():
    reg = registry()
    bus = WaggleProtocol(registry=reg)
    acc = MusicalMotifAccumulator(registry=reg)
    shared = "sha256:" + "9" * 64

    add(bus=bus, acc=acc, bee="struct", family="structural", lineage=STRUCT, kind="WAGGLE", ts=1_000, evidence_root=shared)
    add(bus=bus, acc=acc, bee="stat", family="statistical", lineage=STAT, kind="FOLLOW", ts=6_000, evidence_root=shared)
    add(bus=bus, acc=acc, bee="micro", family="microstructure", lineage=MICRO, kind="FOLLOW", ts=11_000, evidence_root=shared)

    motif = acc.score("motif-q")
    entrainment = PolyphonicEntrainment().score(
        hypothesis_id="motif-q",
        notes=acc.notes("motif-q"),
    )
    receipt = ConductingQueen().conduct(
        hypothesis_id="motif-q",
        notes=acc.notes("motif-q"),
        motif=motif,
        entrainment=entrainment,
        epoch=epoch(),
        now_ms=20_000,
        world_state_id=WS_ID,
        world_state_hash=WS_HASH,
    )
    assert "DIMINUENDO_ECHO" in receipt.conducting_cues
    assert "INVITE_COUNTERPOINT" in receipt.conducting_cues
    assert "counterfeit_unison" in receipt.triune.loki_counterpoint
