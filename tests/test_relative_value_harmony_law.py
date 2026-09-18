from __future__ import annotations

from strategies.relative_value_lab.contracts import RELATIVE_VALUE_AUTHORITY
from strategies.relative_value_lab.harmony_law import (
    HarmonyBeeMessage,
    HarmonyLaw,
)


WS_ID = "ws-1"
WS_HASH = "sha256:" + "a" * 64
EVIDENCE = "sha256:" + "b" * 64
NOW = 100_000


def bee(
    *,
    message_id: str = "m1",
    bee_id: str = "bee-structural",
    family: str = "structural",
    lineage: str = "sha256:structural",
    message_type: str = "WAGGLE",
    horizon: int | None = 10,
    independent: bool = True,
    control: bool = False,
    world_state_id: str = WS_ID,
    world_state_hash: str = WS_HASH,
    observed_at_ms: int = NOW,
    evidence_root: str = EVIDENCE,
    pulse_type: str | None = None,
    execution_eligible: bool = False,
    promotion_eligible: bool = False,
) -> HarmonyBeeMessage:
    return HarmonyBeeMessage(
        message_id=message_id,
        bee_id=bee_id,
        family=family,
        lineage_digest=lineage,
        message_type=message_type,
        scope="A/USD__B/USD",
        hypothesis_id="hyp-1",
        world_state_id=world_state_id,
        world_state_hash=world_state_hash,
        observed_at_ms=observed_at_ms,
        evidence_root=evidence_root,
        horizon_seconds=horizon,
        direction="LONG_A_SHORT_B",
        expected_move_bps=2.0,
        uncertainty=0.4,
        independent_claimed=independent,
        control=control,
        pulse_type=pulse_type,
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=execution_eligible,
        promotion_eligible=promotion_eligible,
    )


def law() -> HarmonyLaw:
    return HarmonyLaw(
        registered_lineages={
            "sha256:structural": "structural",
            "sha256:statistical": "statistical",
            "sha256:micro": "microstructure",
        }
    )


def test_registered_world_state_bound_bee_is_choir_eligible():
    decision = law().validate_message(
        bee(),
        current_world_state_id=WS_ID,
        current_world_state_hash=WS_HASH,
        now_ms=NOW,
    )
    assert decision.accepted is True
    assert decision.choir_eligible is True
    assert decision.independent_vote_eligible is True
    assert decision.execution_eligible is False
    assert decision.promotion_eligible is False


def test_world_state_drift_fails_closed():
    decision = law().validate_message(
        bee(world_state_hash="sha256:" + "c" * 64),
        current_world_state_id=WS_ID,
        current_world_state_hash=WS_HASH,
        now_ms=NOW,
    )
    assert decision.accepted is False
    assert "world_state_drift" in decision.violations


def test_stale_bee_fails_closed():
    decision = law().validate_message(
        bee(observed_at_ms=NOW - 20_000),
        current_world_state_id=WS_ID,
        current_world_state_hash=WS_HASH,
        now_ms=NOW,
    )
    assert decision.accepted is False
    assert "stale_world_state" in decision.violations


def test_unregistered_lineage_cannot_counterfeit_independence():
    decision = law().validate_message(
        bee(lineage="sha256:mystery", family="mystery"),
        current_world_state_id=WS_ID,
        current_world_state_hash=WS_HASH,
        now_ms=NOW,
    )
    assert decision.accepted is True
    assert decision.independent_vote_eligible is False
    assert "independence_stripped_unregistered_lineage" in decision.warnings


def test_clone_votes_collapse_to_one_lineage_per_band():
    chorus = law().validate_chorus(
        [
            bee(message_id="m1"),
            bee(message_id="m2", bee_id="bee-structural-clone"),
            bee(
                message_id="m3",
                bee_id="bee-statistical",
                family="statistical",
                lineage="sha256:statistical",
            ),
        ],
        current_world_state_id=WS_ID,
        current_world_state_hash=WS_HASH,
        now_ms=NOW,
    )
    assert set(chorus.independent_lineages) == {
        "sha256:structural",
        "sha256:statistical",
    }
    assert "clone_vote_collapsed" in chorus.warnings


def test_cross_horizon_global_direction_is_forbidden():
    chorus = law().validate_chorus(
        [
            bee(message_id="micro", horizon=10),
            bee(
                message_id="meso",
                bee_id="bee-statistical",
                family="statistical",
                lineage="sha256:statistical",
                horizon=30,
            ),
        ],
        current_world_state_id=WS_ID,
        current_world_state_hash=WS_HASH,
        now_ms=NOW,
        requested_global_direction=True,
    )
    assert chorus.cross_horizon_direction_allowed is False
    assert "cross_horizon_direction_collapse_forbidden" in chorus.violations


def test_dissent_is_preserved_not_silenced():
    chorus = law().validate_chorus(
        [
            bee(message_id="support"),
            bee(
                message_id="dissent",
                bee_id="bee-statistical",
                family="statistical",
                lineage="sha256:statistical",
                message_type="DISSENT",
            ),
        ],
        current_world_state_id=WS_ID,
        current_world_state_hash=WS_HASH,
        now_ms=NOW,
    )
    assert chorus.dissent_message_ids == ("dissent",)
    assert "dissent_preserved" in chorus.warnings


def test_positive_pulse_can_only_increase_attention():
    decision = law().validate_message(
        bee(pulse_type="DISCOVERY_PULSE"),
        current_world_state_id=WS_ID,
        current_world_state_hash=WS_HASH,
        now_ms=NOW,
    )
    assert decision.authority_effect == "ATTENTION_ONLY"
    assert decision.execution_eligible is False


def test_alarm_pulse_can_only_reduce_or_freeze_authority():
    decision = law().validate_message(
        bee(pulse_type="ALARM_PULSE", message_type="ALARM"),
        current_world_state_id=WS_ID,
        current_world_state_hash=WS_HASH,
        now_ms=NOW,
    )
    assert decision.authority_effect == "REDUCE_OR_FREEZE_ONLY"
    assert decision.execution_eligible is False


def test_bee_cannot_bootstrap_execution_or_promotion_authority():
    decision = law().validate_message(
        bee(execution_eligible=True, promotion_eligible=True),
        current_world_state_id=WS_ID,
        current_world_state_hash=WS_HASH,
        now_ms=NOW,
    )
    assert decision.accepted is False
    assert "execution_authority_forbidden" in decision.violations
    assert "promotion_authority_forbidden" in decision.violations
