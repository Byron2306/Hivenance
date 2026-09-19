from __future__ import annotations

from strategies.relative_value_lab.musical_cognition import MotifNote
from strategies.relative_value_lab.polyphonic_quorum import PolyphonicQuorum, PolyphonicQuorumConfig
from strategies.relative_value_lab.pollen_economy import PollenBounty
from strategies.relative_value_lab.pollen_economy import (
    MetatronQuorumChamber,
    PollenClaim,
    ProspectivePollenOutcome,
    QueenPollenEconomy,
)
from strategies.relative_value_lab.waggle_protocol import WaggleReceipt
from strategies.relative_value_lab.contracts import RELATIVE_VALUE_AUTHORITY


R1="sha256:"+"1"*64
R2="sha256:"+"2"*64
E1="sha256:"+"a"*64
E2="sha256:"+"b"*64
WS="ws-q"
WH="sha256:"+"f"*64


def note(*,bee,family,root,evidence,msg,ts,direction):
    return MotifNote(
        message_id=f"{bee}-{msg}-{ts}",
        receipt_id=f"r-{bee}-{ts}",
        hypothesis_id="h1",
        bee_id=bee,
        family=family,
        lineage_digest=root,
        root_lineage_digest=root,
        message_type=msg,
        observed_at_ms=ts,
        horizon_band="micro",
        direction=direction,
        expected_move_bps=1.0,
        uncertainty=.2,
        pulse_type=None,
        evidence_root=evidence,
        world_state_id=WS,
        world_state_hash=WH,
        independent_voice=True,
    )


def waggle_receipt(*,bee,family,root,evidence,msg,seq):
    return WaggleReceipt(
        schema="hivenance_waggle_receipt_v1",
        receipt_id=f"wr-{bee}",
        sequence_number=seq,
        message_id=f"m-{bee}",
        hypothesis_id="h1",
        message_type=msg,
        family=family,
        lineage_digest=root,
        root_lineage_digest=root,
        horizon_band="micro",
        accepted=True,
        choir_eligible=True,
        independent_vote_eligible=True,
        authority_effect="NONE",
        law_decision_id=f"law-{bee}",
        violations=(),
        warnings=(),
        previous_receipt_digest=None,
        receipt_digest="sha256:"+"c"*64,
        world_state_id=WS,
        world_state_hash=WH,
        evidence_root=evidence,
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
        promotion_eligible=False,
    )


def test_quorum_is_alignment_not_directional_agreement():
    q=PolyphonicQuorum(PolyphonicQuorumConfig(
        minimum_independent_roots=2,
        minimum_families=2,
        minimum_roles=2,
        phase_window_ms=10_000,
        call_response_window_ms=10_000,
        ensemble_lock_threshold=.50,
    )).score([
        note(bee="a",family="structural",root=R1,evidence=E1,msg="WAGGLE",ts=1000,direction="LONG_A_SHORT_B"),
        note(bee="b",family="microstructure",root=R2,evidence=E2,msg="DISSENT",ts=1500,direction="LONG_B_SHORT_A"),
    ])
    assert q.directional_counterpoint_present is True
    assert q.explicit_dissent_present is True
    assert q.quorum_formed is True
    assert q.ensemble_lock >= .50
    assert "counterpoint_preserved" in q.reasons


def test_same_direction_does_not_rescue_bad_choreography():
    q=PolyphonicQuorum(PolyphonicQuorumConfig(
        minimum_independent_roots=2,
        minimum_families=2,
        minimum_roles=2,
        phase_window_ms=1_000,
        call_response_window_ms=1_000,
        ensemble_lock_threshold=.70,
    )).score([
        note(bee="a",family="structural",root=R1,evidence=E1,msg="WAGGLE",ts=1000,direction="LONG_A_SHORT_B"),
        note(bee="b",family="microstructure",root=R2,evidence=E2,msg="FOLLOW",ts=20_000,direction="LONG_A_SHORT_B"),
    ])
    assert q.quorum_formed is False
    assert "voices_out_of_phase" in q.reasons


def test_metatron_chamber_collapses_clone_roots_but_keeps_dissent():
    bounty=PollenBounty(
        schema="hivenance_pollen_bounty_v1",
        bounty_id="b1",bounty_type="POLLEN_DISSENT",
        hypothesis_id="h1",world_state_id=WS,world_state_hash=WH,
        horizon_band="micro",issued_at_ms=0,expires_at_ms=10_000,
        reward_pool=10.0,challenge_required=True,
    )
    claims=[
        PollenClaim(
            schema="hivenance_pollen_claim_v1",claim_id="c1",bounty_id="b1",
            bee_id="a",hypothesis_id="h1",stance="SUPPORT",message_type="WAGGLE",
            confidence=.7,stake=1,information_gain_claim=.4,family="structural",
            lineage_digest=R1,root_lineage_digest=R1,evidence_root=E1,
            waggle_receipt_id="w1",world_state_id=WS,world_state_hash=WH,
            independent=True,submitted_at_ms=1000,
        ),
        PollenClaim(
            schema="hivenance_pollen_claim_v1",claim_id="c2",bounty_id="b1",
            bee_id="clone",hypothesis_id="h1",stance="SUPPORT",message_type="FOLLOW",
            confidence=.9,stake=1,information_gain_claim=.4,family="structural",
            lineage_digest="sha256:"+"3"*64,root_lineage_digest=R1,evidence_root=E1,
            waggle_receipt_id="w2",world_state_id=WS,world_state_hash=WH,
            independent=True,submitted_at_ms=1100,
        ),
        PollenClaim(
            schema="hivenance_pollen_claim_v1",claim_id="c3",bounty_id="b1",
            bee_id="b",hypothesis_id="h1",stance="DISSENT",message_type="DISSENT",
            confidence=.8,stake=1,information_gain_claim=.6,family="microstructure",
            lineage_digest=R2,root_lineage_digest=R2,evidence_root=E2,
            waggle_receipt_id="w3",world_state_id=WS,world_state_hash=WH,
            independent=True,submitted_at_ms=1400,
        ),
    ]
    q=MetatronQuorumChamber(
        min_independent_roots=2,min_families=2,min_roles=2,
        phase_window_ms=10_000,call_response_window_ms=10_000,
        ensemble_lock_threshold=.50,
    ).assess(bounty=bounty,claims=claims)
    assert q.independent_root_count == 2
    assert q.explicit_dissent_present is True
    assert q.quorum_formed is True


def test_pollen_rewards_useful_dissent_after_prospective_refutation():
    economy=QueenPollenEconomy(initial_pollen=20)
    bounty=economy.issue_bounty(
        bounty_type="POLLEN_DISSENT",
        hypothesis_id="h1",world_state_id=WS,world_state_hash=WH,
        horizon_band="micro",issued_at_ms=0,expires_at_ms=10_000,
        reward_pool=12.0,challenge_required=True,
    )
    support=economy.submit_claim(
        bounty=bounty,bee_id="support",
        receipt=waggle_receipt(bee="support",family="structural",root=R1,evidence=E1,msg="WAGGLE",seq=1),
        stance="SUPPORT",confidence=.8,stake=2,information_gain_claim=.4,submitted_at_ms=1000,
    )
    dissent=economy.submit_claim(
        bounty=bounty,bee_id="dissent",
        receipt=waggle_receipt(bee="dissent",family="microstructure",root=R2,evidence=E2,msg="DISSENT",seq=2),
        stance="DISSENT",confidence=.8,stake=2,information_gain_claim=.7,submitted_at_ms=1500,
    )
    q=MetatronQuorumChamber(
        min_independent_roots=2,min_families=2,min_roles=2,
        phase_window_ms=10_000,call_response_window_ms=10_000,
        ensemble_lock_threshold=.50,
    ).assess(bounty=bounty,claims=economy.claims(bounty.bounty_id))
    outcome=ProspectivePollenOutcome(
        schema="hivenance_prospective_pollen_outcome_v1",
        outcome_id="o1",hypothesis_id="h1",settled_at_ms=20_000,
        outcome_class="REFUTED",information_gain=1.0,
        forecast_id="f1",realized_net_bps=-5.0,prospective=True,
    )
    receipt=economy.settle(bounty=bounty,outcome=outcome,quorum=q)
    by_bee={t.bee_id:t for t in receipt.transfers}
    assert by_bee["dissent"].reward > by_bee["support"].reward
    assert by_bee["dissent"].correctness == 1.0
    assert receipt.execution_eligible is False
