from __future__ import annotations

import pytest

from strategies.relative_value_lab.governance_epoch import ResearchGovernanceEpochService
from strategies.relative_value_lab.harmony_law import HarmonyBeeMessage, HarmonyLaw
from strategies.relative_value_lab.world_score import CanonicalWorldScore, ScoreObservation


def frame():
    return CanonicalWorldScore.assemble(
        observations=(
            ScoreObservation(
                observation_id="book-1",
                source_id="kraken-book:A/B",
                source_class="public_market",
                scope="pair:A/B",
                observed_at_ms=1000,
                received_at_ms=1005,
                evidence_root="sha256:"+"1"*64,
                payload={"bid":100.0,"ask":100.1},
            ),
        ),
        assembled_at_ms=1010,
        freshness_window_ms=15_000,
    )


def bee(f, *, world_state_id=None, world_state_hash=None):
    return HarmonyBeeMessage(
        message_id="bee-1",
        bee_id="structural-1",
        family="structural",
        lineage_digest="sha256:"+"2"*64,
        message_type="WAGGLE",
        scope="pair:A/B",
        hypothesis_id="motif-world-score",
        world_state_id=world_state_id or f.world_state_id,
        world_state_hash=world_state_hash or f.world_state_hash,
        observed_at_ms=1100,
        evidence_root="sha256:"+"3"*64,
        horizon_seconds=10,
        direction="LONG_A_SHORT_B",
        expected_move_bps=1.5,
        uncertainty=.2,
        independent_claimed=True,
    )


def test_harmony_law_can_validate_directly_against_canonical_frame():
    f=frame()
    law=HarmonyLaw(registered_lineages={"sha256:"+"2"*64:"structural"})
    decision=law.validate_message_against_frame(bee(f),frame=f,now_ms=1200)
    assert decision.accepted is True
    assert decision.independent_vote_eligible is True


def test_harmony_law_refuses_bee_on_different_score_page():
    f=frame()
    law=HarmonyLaw(registered_lineages={"sha256:"+"2"*64:"structural"})
    decision=law.validate_message_against_frame(
        bee(f,world_state_id="ws-other",world_state_hash="sha256:"+"f"*64),
        frame=f,
        now_ms=1200,
    )
    assert decision.accepted is False
    assert "world_state_drift" in decision.violations


def test_epoch_starts_from_fresh_score_frame():
    f=frame()
    epoch=ResearchGovernanceEpochService.start_epoch_from_frame(
        f,started_at_ms=1200,ttl_ms=20_000
    )
    assert epoch.world_state_id==f.world_state_id
    assert epoch.world_state_hash==f.world_state_hash
    assert epoch.execution_eligible is False
    assert epoch.promotion_eligible is False


def test_epoch_cannot_start_from_stale_score_frame():
    f=frame()
    with pytest.raises(ValueError,match="stale_score_frame"):
        ResearchGovernanceEpochService.start_epoch_from_frame(
            f,started_at_ms=f.expires_at_ms+1,ttl_ms=20_000
        )


def test_stale_score_frame_invalidates_epoch_even_before_epoch_ttl():
    f=frame()
    epoch=ResearchGovernanceEpochService.start_epoch_from_frame(
        f,started_at_ms=1200,ttl_ms=100_000
    )
    validation=ResearchGovernanceEpochService.validate_against_frame(
        epoch,frame=f,now_ms=f.expires_at_ms+1,scope="relative_value_lab"
    )
    assert validation.valid is False
    assert "canonical_score_frame_stale" in validation.reasons
