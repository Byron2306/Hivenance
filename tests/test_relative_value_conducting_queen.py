from __future__ import annotations

from strategies.relative_value_lab.conducting_queen import ConductingQueen, VNSSensoryPulse
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


def pulses():
    return [
        VNSSensoryPulse(
            pulse_id="p1", observed_at_ms=1_000, scope="pair",
            pulse_class="flow", amplitude=.4, confidence=.8, freshness=1.0,
            evidence_root="sha256:"+"4"*64, world_state_id=WS_ID, world_state_hash=WS_HASH,
        ),
        VNSSensoryPulse(
            pulse_id="p2", observed_at_ms=6_000, scope="pair",
            pulse_class="depth", amplitude=.6, confidence=.9, freshness=.9,
            evidence_root="sha256:"+"5"*64, world_state_id=WS_ID, world_state_hash=WS_HASH,
        ),
        VNSSensoryPulse(
            pulse_id="p3", observed_at_ms=16_000, scope="pair",
            pulse_class="spread", amplitude=.5, confidence=.8, freshness=.8,
            evidence_root="sha256:"+"6"*64, world_state_id=WS_ID, world_state_hash=WS_HASH,
        ),
    ]


def test_epoch_binds_score_genre_strictness_and_world_state():
    e = epoch()
    assert e.score_id == "watchful_standard_v1"
    assert e.genre_mode == "watchful"
    assert e.strictness_level == "standard"
    assert e.world_state_hash == WS_HASH
    assert e.execution_eligible is False
    assert e.promotion_eligible is False


def test_queen_emits_three_triune_score_sheets_and_research_notation():
    acc, motif, entrainment = build_phrase()
    receipt = ConductingQueen().conduct(
        hypothesis_id="motif-q",
        notes=acc.notes("motif-q"),
        motif=motif,
        entrainment=entrainment,
        epoch=epoch(),
        vns_pulses=pulses(),
        harmonic_context={"resonance": .65, "discord": .2, "confidence": .7},
        now_ms=30_000,
        world_state_id=WS_ID,
        world_state_hash=WS_HASH,
    )
    assert {s.mind for s in receipt.triune_scores} == {"METATRON", "MICHAEL", "LOKI"}
    assert len(receipt.notation_tokens) >= 1
    assert all(t.execution_eligible is False for t in receipt.notation_tokens)
    assert all(t.promotion_eligible is False for t in receipt.notation_tokens)


def test_epoch_drift_changes_harmony_but_does_not_make_queen_deaf():
    acc, motif, entrainment = build_phrase()
    receipt = ConductingQueen().conduct(
        hypothesis_id="motif-q",
        notes=acc.notes("motif-q"),
        motif=motif,
        entrainment=entrainment,
        epoch=epoch(world_hash="sha256:"+"f"*64),
        vns_pulses=pulses(),
        now_ms=30_000,
        world_state_id=WS_ID,
        world_state_hash=WS_HASH,
    )
    assert receipt.epoch_consonance < 1.0
    assert receipt.world_state_tension > 0.0
    assert len(receipt.triune_scores) == 3
    assert any(t.notation == "REKEY_SCORE" for t in receipt.notation_tokens)
    assert "LISTEN_CONTINUOUSLY" in receipt.conducting_gestures
    assert receipt.execution_eligible is False


def test_vns_syncopation_and_energy_are_audible():
    acc, motif, entrainment = build_phrase()
    receipt = ConductingQueen().conduct(
        hypothesis_id="motif-q",
        notes=acc.notes("motif-q"),
        motif=motif,
        entrainment=entrainment,
        epoch=epoch(),
        vns_pulses=pulses(),
        now_ms=30_000,
        world_state_id=WS_ID,
        world_state_hash=WS_HASH,
    )
    assert receipt.vns_pulse_energy > 0.0
    assert receipt.vns_syncopation >= 0.0


def test_notation_tokens_are_epoch_world_state_and_triune_bound():
    acc, motif, entrainment = build_phrase()
    ep = epoch()
    receipt = ConductingQueen().conduct(
        hypothesis_id="motif-q",
        notes=acc.notes("motif-q"),
        motif=motif,
        entrainment=entrainment,
        epoch=ep,
        vns_pulses=pulses(),
        now_ms=30_000,
        world_state_id=WS_ID,
        world_state_hash=WS_HASH,
    )
    ids = {s.score_sheet_id for s in receipt.triune_scores}
    for token in receipt.notation_tokens:
        assert token.epoch_id == ep.epoch_id
        assert token.score_id == ep.score_id
        assert token.world_state_id == WS_ID
        assert token.world_state_hash == WS_HASH
        assert set(token.source_score_sheet_ids) == ids
        assert token.maximum_uses == 1


def test_queen_is_progressive_not_binary():
    acc, motif, entrainment = build_phrase()
    receipt = ConductingQueen().conduct(
        hypothesis_id="motif-q",
        notes=acc.notes("motif-q"),
        motif=motif,
        entrainment=entrainment,
        epoch=epoch(world_hash="sha256:"+"f"*64),
        vns_pulses=pulses(),
        harmonic_context={"resonance": .35, "discord": .55, "confidence": .4},
        now_ms=30_000,
        world_state_id=WS_ID,
        world_state_hash=WS_HASH,
    )
    payload = receipt.to_dict()
    assert "allowed" not in payload
    assert "blocked" not in payload
    assert 0.0 <= receipt.epoch_consonance <= 1.0
    assert 0.0 <= receipt.polyphonic_pressure <= 1.0
    assert len(receipt.conducting_gestures) >= 1


def test_subtle_pitch_timbre_shift_becomes_modulation_invitation():
    reg = registry()
    bus = WaggleProtocol(registry=reg)
    acc = MusicalMotifAccumulator(registry=reg)

    add(bus=bus, acc=acc, bee="struct", family="structural", lineage=STRUCT, kind="WAGGLE", ts=1_000, move=0.5, uncertainty=0.1)
    add(bus=bus, acc=acc, bee="stat", family="statistical", lineage=STAT, kind="FOLLOW", ts=6_000, move=0.6, uncertainty=0.1)
    add(bus=bus, acc=acc, bee="micro", family="microstructure", lineage=MICRO, kind="FOLLOW", ts=11_000, move=0.7, uncertainty=0.1)
    add(bus=bus, acc=acc, bee="struct2", family="structural", lineage=STRUCT, kind="FOLLOW", ts=16_000, move=3.0, uncertainty=0.8, pulse="DISCOVERY_PULSE")
    add(bus=bus, acc=acc, bee="stat2", family="statistical", lineage=STAT, kind="FOLLOW", ts=21_000, move=3.2, uncertainty=0.8, pulse="DISCOVERY_PULSE")
    add(bus=bus, acc=acc, bee="micro2", family="microstructure", lineage=MICRO, kind="FOLLOW", ts=26_000, move=3.4, uncertainty=0.8, pulse="DISCOVERY_PULSE")

    motif = acc.score("motif-q")
    entrainment = PolyphonicEntrainment().score(hypothesis_id="motif-q", notes=acc.notes("motif-q"))
    receipt = ConductingQueen().conduct(
        hypothesis_id="motif-q",
        notes=acc.notes("motif-q"),
        motif=motif,
        entrainment=entrainment,
        epoch=epoch(),
        vns_pulses=pulses(),
        now_ms=30_000,
        world_state_id=WS_ID,
        world_state_hash=WS_HASH,
    )
    assert receipt.subtle_shift_score > 0.0
    assert any(t.notation == "TRACE_MODULATION" for t in receipt.notation_tokens)


def test_false_unison_invites_countermelody_not_silence():
    reg = registry()
    bus = WaggleProtocol(registry=reg)
    acc = MusicalMotifAccumulator(registry=reg)
    shared = "sha256:" + "9" * 64

    add(bus=bus, acc=acc, bee="struct", family="structural", lineage=STRUCT, kind="WAGGLE", ts=1_000, evidence_root=shared)
    add(bus=bus, acc=acc, bee="stat", family="statistical", lineage=STAT, kind="FOLLOW", ts=6_000, evidence_root=shared)
    add(bus=bus, acc=acc, bee="micro", family="microstructure", lineage=MICRO, kind="FOLLOW", ts=11_000, evidence_root=shared)

    motif = acc.score("motif-q")
    entrainment = PolyphonicEntrainment().score(hypothesis_id="motif-q", notes=acc.notes("motif-q"))
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
    assert "INVITE_NEW_TIMBRE" in receipt.conducting_gestures or any(
        t.notation == "CHALLENGE_CADENCE" for t in receipt.notation_tokens
    )
    loki = next(s for s in receipt.triune_scores if s.mind == "LOKI")
    assert any("false_unison" in item for item in loki.cautions)
