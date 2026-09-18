from __future__ import annotations

from strategies.relative_value_lab.waggle_protocol import (
    BeeLineage,
    LineageRegistry,
    WaggleProtocol,
)


WS_ID = "ws-1"
WS_HASH = "sha256:" + "a" * 64
EVIDENCE = "sha256:" + "b" * 64
NOW = 100_000

STRUCT = "sha256:" + "1" * 64
STRUCT_CHILD = "sha256:" + "2" * 64
STAT = "sha256:" + "3" * 64


def registry() -> LineageRegistry:
    return LineageRegistry(
        [
            BeeLineage(
                lineage_digest=STRUCT,
                family="structural",
                root_lineage_digest=STRUCT,
                description="OU structural family",
            ),
            BeeLineage(
                lineage_digest=STRUCT_CHILD,
                family="structural",
                root_lineage_digest=STRUCT,
                parent_lineage_digest=STRUCT,
                description="Structural descendant",
            ),
            BeeLineage(
                lineage_digest=STAT,
                family="statistical",
                root_lineage_digest=STAT,
                description="Ridge statistical family",
            ),
        ]
    )


def protocol() -> WaggleProtocol:
    return WaggleProtocol(registry=registry())


def message(
    bus: WaggleProtocol,
    *,
    bee_id: str = "structural-bee",
    family: str = "structural",
    lineage: str = STRUCT,
    message_type: str = "WAGGLE",
    horizon: int = 10,
    hypothesis_id: str = "hyp-1",
    world_state_id: str = WS_ID,
    world_state_hash: str = WS_HASH,
    observed_at_ms: int = NOW,
    pulse_type: str | None = None,
):
    return bus.build_message(
        bee_id=bee_id,
        family=family,
        lineage_digest=lineage,
        message_type=message_type,
        scope="A/USD__B/USD",
        hypothesis_id=hypothesis_id,
        world_state_id=world_state_id,
        world_state_hash=world_state_hash,
        observed_at_ms=observed_at_ms,
        evidence_root=EVIDENCE,
        horizon_seconds=horizon,
        direction="LONG_A_SHORT_B",
        expected_move_bps=2.0,
        uncertainty=0.4,
        independent_claimed=True,
        pulse_type=pulse_type,
    )


def publish(bus: WaggleProtocol, msg):
    return bus.publish(
        msg,
        current_world_state_id=WS_ID,
        current_world_state_hash=WS_HASH,
        now_ms=NOW,
    )


def test_build_message_is_deterministic_and_research_only():
    bus = protocol()
    a = message(bus)
    b = message(bus)
    assert a.message_id == b.message_id
    assert a.execution_eligible is False
    assert a.promotion_eligible is False


def test_publish_creates_append_only_hash_chain():
    bus = protocol()
    r1 = publish(bus, message(bus))
    r2 = publish(
        bus,
        message(
            bus,
            bee_id="stat-bee",
            family="statistical",
            lineage=STAT,
            message_type="FOLLOW",
        ),
    )
    assert r1.sequence_number == 1
    assert r1.previous_receipt_digest is None
    assert r2.sequence_number == 2
    assert r2.previous_receipt_digest == r1.receipt_digest


def test_duplicate_publish_is_idempotent():
    bus = protocol()
    msg = message(bus)
    r1 = publish(bus, msg)
    r2 = publish(bus, msg)
    assert r1 == r2
    assert len(bus.receipts()) == 1


def test_clone_descendant_remains_visible_but_loses_second_vote():
    bus = protocol()
    r1 = publish(bus, message(bus))
    r2 = publish(
        bus,
        message(
            bus,
            bee_id="struct-child",
            lineage=STRUCT_CHILD,
            message_type="FOLLOW",
        ),
    )
    assert r1.accepted is True
    assert r1.independent_vote_eligible is True
    assert r2.accepted is True
    assert r2.choir_eligible is True
    assert r2.independent_vote_eligible is False
    assert "clone_or_descendant_vote_collapsed" in r2.warnings


def test_independent_family_can_follow_same_hypothesis():
    bus = protocol()
    publish(bus, message(bus))
    r2 = publish(
        bus,
        message(
            bus,
            bee_id="stat-bee",
            family="statistical",
            lineage=STAT,
            message_type="FOLLOW",
        ),
    )
    assert r2.independent_vote_eligible is True
    snap = bus.chorus_snapshot(
        hypothesis_id="hyp-1",
        current_world_state_id=WS_ID,
        current_world_state_hash=WS_HASH,
        now_ms=NOW,
    )
    assert set(snap.independent_root_lineages) == {STRUCT, STAT}


def test_dissent_is_retained_in_chorus_snapshot():
    bus = protocol()
    publish(bus, message(bus))
    publish(
        bus,
        message(
            bus,
            bee_id="stat-bee",
            family="statistical",
            lineage=STAT,
            message_type="DISSENT",
        ),
    )
    snap = bus.chorus_snapshot(
        hypothesis_id="hyp-1",
        current_world_state_id=WS_ID,
        current_world_state_hash=WS_HASH,
        now_ms=NOW,
    )
    assert len(snap.dissent_message_ids) == 1
    assert "dissent_preserved" in snap.warnings


def test_stale_message_is_refused_and_not_admitted_to_choir():
    bus = protocol()
    receipt = publish(
        bus,
        message(bus, observed_at_ms=NOW - 20_000),
    )
    assert receipt.accepted is False
    assert receipt.choir_eligible is False
    assert "stale_world_state" in receipt.violations


def test_world_state_drift_is_refused():
    bus = protocol()
    receipt = publish(
        bus,
        message(bus, world_state_hash="sha256:" + "c" * 64),
    )
    assert receipt.accepted is False
    assert "world_state_drift" in receipt.violations


def test_alarm_forces_reduce_or_freeze_effect():
    bus = protocol()
    publish(
        bus,
        message(
            bus,
            message_type="ALARM",
            pulse_type="ALARM_PULSE",
        ),
    )
    snap = bus.chorus_snapshot(
        hypothesis_id="hyp-1",
        current_world_state_id=WS_ID,
        current_world_state_hash=WS_HASH,
        now_ms=NOW,
    )
    assert snap.alarmed is True
    assert snap.authority_effect == "REDUCE_OR_FREEZE_ONLY"
    assert snap.execution_eligible is False


def test_abandonment_is_preserved_as_hypothesis_state():
    bus = protocol()
    publish(bus, message(bus))
    publish(
        bus,
        message(
            bus,
            bee_id="stat-bee",
            family="statistical",
            lineage=STAT,
            message_type="ABANDON",
        ),
    )
    snap = bus.chorus_snapshot(
        hypothesis_id="hyp-1",
        current_world_state_id=WS_ID,
        current_world_state_hash=WS_HASH,
        now_ms=NOW,
    )
    assert snap.abandoned is True
    assert "hypothesis_abandoned" in snap.warnings


def test_cross_horizon_global_direction_request_is_rejected():
    bus = protocol()
    publish(bus, message(bus, horizon=10))
    publish(
        bus,
        message(
            bus,
            bee_id="stat-bee",
            family="statistical",
            lineage=STAT,
            message_type="FOLLOW",
            horizon=30,
        ),
    )
    snap = bus.chorus_snapshot(
        hypothesis_id="hyp-1",
        current_world_state_id=WS_ID,
        current_world_state_hash=WS_HASH,
        now_ms=NOW,
        requested_global_direction=True,
    )
    assert "cross_horizon_direction_collapse_forbidden" in snap.violations


def test_lineage_family_mismatch_fails_closed_even_without_vote_value():
    bus = protocol()
    bad = bus.build_message(
        bee_id="bad-bee",
        family="statistical",
        lineage_digest=STRUCT,
        message_type="SEARCH",
        scope="A/USD__B/USD",
        hypothesis_id="hyp-1",
        world_state_id=WS_ID,
        world_state_hash=WS_HASH,
        observed_at_ms=NOW,
        evidence_root=EVIDENCE,
        horizon_seconds=10,
        independent_claimed=False,
    )
    receipt = publish(bus, bad)
    assert receipt.accepted is False
    assert "lineage_family_mismatch" in receipt.violations
