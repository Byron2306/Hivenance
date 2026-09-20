import pytest

from strategies.relative_value_lab.contracts import (
    RELATIVE_VALUE_AUTHORITY,
)
from strategies.relative_value_lab.musical_cognition import (
    MotifNote,
)
from strategies.relative_value_lab.polyphonic_quorum import (
    PolyphonicQuorum,
    PolyphonicQuorumConfig,
)
from strategies.relative_value_lab.pollen_adversarial_gauntlet import (
    SocialAttackResult,
    build_adversarial_gauntlet_receipt,
)
from strategies.relative_value_lab.pollen_causal_receipt import (
    build_pollen_causal_receipt,
)
from strategies.relative_value_lab.pollen_economy import (
    MetatronQuorumChamber,
    ProspectivePollenOutcome,
    QueenPollenEconomy,
)
from strategies.relative_value_lab.waggle_protocol import (
    WaggleReceipt,
)


R1 = "sha256:" + "1" * 64
R2 = "sha256:" + "2" * 64
E1 = "sha256:" + "a" * 64
E2 = "sha256:" + "b" * 64

WS = "ws-phase9-gauntlet"
WH = "sha256:" + "f" * 64
H = "phase9-gauntlet"


def note(
    *,
    bee,
    family,
    root,
    evidence,
    message,
    ts,
):
    return MotifNote(
        message_id=f"{bee}-{message}-{ts}",
        receipt_id=f"receipt-{bee}-{ts}",
        hypothesis_id=H,
        bee_id=bee,
        family=family,
        lineage_digest=root,
        root_lineage_digest=root,
        message_type=message,
        observed_at_ms=ts,
        horizon_band="micro",
        direction="LONG_A_SHORT_B",
        expected_move_bps=1.0,
        uncertainty=.2,
        pulse_type=None,
        evidence_root=evidence,
        world_state_id=WS,
        world_state_hash=WH,
        independent_voice=True,
    )


def waggle(
    *,
    bee,
    family,
    root,
    evidence,
    message,
    seq,
):
    return WaggleReceipt(
        schema="hivenance_waggle_receipt_v1",
        receipt_id=f"wr-{bee}-{seq}",
        sequence_number=seq,
        message_id=f"msg-{bee}-{seq}",
        hypothesis_id=H,
        message_type=message,
        family=family,
        lineage_digest=root,
        root_lineage_digest=root,
        horizon_band="micro",
        accepted=True,
        choir_eligible=True,
        independent_vote_eligible=True,
        authority_effect="NONE",
        law_decision_id=f"law-{bee}-{seq}",
        violations=(),
        warnings=(),
        previous_receipt_digest=None,
        receipt_digest=(
            "sha256:" + str(seq % 10) * 64
        ),
        world_state_id=WS,
        world_state_hash=WH,
        evidence_root=evidence,
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
        promotion_eligible=False,
    )


def economy():
    eco = QueenPollenEconomy(initial_pollen=20)

    bounty = eco.issue_bounty(
        bounty_type="POLLEN_DISSENT",
        hypothesis_id=H,
        world_state_id=WS,
        world_state_hash=WH,
        horizon_band="micro",
        issued_at_ms=1000,
        expires_at_ms=10000,
        reward_pool=12.0,
        challenge_required=True,
    )

    return eco, bounty


def quorum_for(bounty, claims):
    return MetatronQuorumChamber(
        min_independent_roots=2,
        min_families=2,
        min_roles=2,
        phase_window_ms=10000,
        call_response_window_ms=10000,
        ensemble_lock_threshold=.50,
    ).assess(
        bounty=bounty,
        claims=claims,
    )


def refuted():
    return ProspectivePollenOutcome(
        schema=(
            "hivenance_prospective_pollen_outcome_v1"
        ),
        outcome_id="future-refutation",
        hypothesis_id=H,
        settled_at_ms=20000,
        outcome_class="REFUTED",
        information_gain=1.0,
        forecast_id="forecast-phase9",
        realized_net_bps=-5.0,
        prospective=True,
    )


def test_duplicate_lineage_false_unison_cannot_form_independence():
    engine = PolyphonicQuorum(
        PolyphonicQuorumConfig(
            minimum_independent_roots=2,
            minimum_families=2,
            minimum_roles=2,
            phase_window_ms=10000,
            call_response_window_ms=10000,
            ensemble_lock_threshold=.50,
        )
    )

    receipt = engine.score((
        note(
            bee="a",
            family="structural",
            root=R1,
            evidence=E1,
            message="WAGGLE",
            ts=1000,
        ),
        note(
            bee="clone",
            family="microstructure",
            root=R1,
            evidence=E1,
            message="FOLLOW",
            ts=1200,
        ),
    ))

    assert receipt.independent_root_count == 1
    assert receipt.quorum_formed is False


def test_same_root_clone_swarm_does_not_multiply_quorum():
    eco, bounty = economy()

    for seq, bee in enumerate(
        ("a", "clone1", "clone2"),
        start=1,
    ):
        eco.submit_claim(
            bounty=bounty,
            bee_id=bee,
            receipt=waggle(
                bee=bee,
                family="structural",
                root=R1,
                evidence=E1,
                message=(
                    "WAGGLE"
                    if seq == 1
                    else "FOLLOW"
                ),
                seq=seq,
            ),
            stance="SUPPORT",
            confidence=.8,
            stake=1,
            information_gain_claim=.2,
            submitted_at_ms=1100 + seq * 100,
        )

    q = quorum_for(
        bounty,
        eco.claims(bounty.bounty_id),
    )

    assert q.independent_root_count == 1
    assert q.quorum_formed is False


def test_delayed_response_fails_call_response_gate():
    engine = PolyphonicQuorum(
        PolyphonicQuorumConfig(
            minimum_independent_roots=2,
            minimum_families=2,
            minimum_roles=2,
            phase_window_ms=1000,
            call_response_window_ms=1000,
            ensemble_lock_threshold=.50,
        )
    )

    q = engine.score((
        note(
            bee="call",
            family="structural",
            root=R1,
            evidence=E1,
            message="WAGGLE",
            ts=1000,
        ),
        note(
            bee="late",
            family="microstructure",
            root=R2,
            evidence=E2,
            message="FOLLOW",
            ts=5000,
        ),
    ))

    assert q.quorum_formed is False
    assert "voices_out_of_phase" in q.reasons


def test_stale_or_temporally_impossible_claim_is_refused():
    eco, bounty = economy()

    with pytest.raises(
        ValueError,
        match="pollen_claim_predates_bounty",
    ):
        eco.submit_claim(
            bounty=bounty,
            bee_id="time-traveller",
            receipt=waggle(
                bee="time-traveller",
                family="structural",
                root=R1,
                evidence=E1,
                message="WAGGLE",
                seq=1,
            ),
            stance="SUPPORT",
            confidence=.8,
            stake=1,
            information_gain_claim=.5,
            submitted_at_ms=999,
        )

    with pytest.raises(
        ValueError,
        match="pollen_bounty_expired",
    ):
        eco.submit_claim(
            bounty=bounty,
            bee_id="stale",
            receipt=waggle(
                bee="stale",
                family="structural",
                root=R1,
                evidence=E1,
                message="WAGGLE",
                seq=2,
            ),
            stance="SUPPORT",
            confidence=.8,
            stake=1,
            information_gain_claim=.5,
            submitted_at_ms=10001,
        )


def test_coordinated_wrong_agreement_is_punished_by_future_truth():
    eco, bounty = economy()

    for seq, (bee, family, root, evidence, msg) in enumerate(
        (
            (
                "a",
                "structural",
                R1,
                E1,
                "WAGGLE",
            ),
            (
                "b",
                "microstructure",
                R2,
                E2,
                "FOLLOW",
            ),
        ),
        start=1,
    ):
        eco.submit_claim(
            bounty=bounty,
            bee_id=bee,
            receipt=waggle(
                bee=bee,
                family=family,
                root=root,
                evidence=evidence,
                message=msg,
                seq=seq,
            ),
            stance="SUPPORT",
            confidence=.95,
            stake=2,
            information_gain_claim=.8,
            submitted_at_ms=1200 + seq * 100,
        )

    claims = eco.claims(bounty.bounty_id)
    q = quorum_for(bounty, claims)

    assert q.quorum_formed is True

    outcome = refuted()

    settlement = eco.settle(
        bounty=bounty,
        outcome=outcome,
        quorum=q,
    )

    causal = build_pollen_causal_receipt(
        bounty=bounty,
        claims=claims,
        quorum=q,
        outcome=outcome,
        settlement=settlement,
    )

    assert causal.harmful_claim_count == 2
    assert causal.useful_support_count == 0

    assert all(
        transfer.correctness == 0.0
        for transfer in settlement.transfers
    )


def test_useful_dissent_survives_and_is_rewarded():
    eco, bounty = economy()

    eco.submit_claim(
        bounty=bounty,
        bee_id="support",
        receipt=waggle(
            bee="support",
            family="structural",
            root=R1,
            evidence=E1,
            message="WAGGLE",
            seq=1,
        ),
        stance="SUPPORT",
        confidence=.8,
        stake=2,
        information_gain_claim=.4,
        submitted_at_ms=1200,
    )

    eco.submit_claim(
        bounty=bounty,
        bee_id="dissent",
        receipt=waggle(
            bee="dissent",
            family="microstructure",
            root=R2,
            evidence=E2,
            message="DISSENT",
            seq=2,
        ),
        stance="DISSENT",
        confidence=.8,
        stake=2,
        information_gain_claim=.8,
        submitted_at_ms=1400,
    )

    claims = eco.claims(bounty.bounty_id)
    q = quorum_for(bounty, claims)

    outcome = refuted()

    settlement = eco.settle(
        bounty=bounty,
        outcome=outcome,
        quorum=q,
    )

    causal = build_pollen_causal_receipt(
        bounty=bounty,
        claims=claims,
        quorum=q,
        outcome=outcome,
        settlement=settlement,
    )

    by_bee = {
        row.bee_id: row
        for row in settlement.transfers
    }

    assert q.explicit_dissent_present is True
    assert causal.useful_dissent_preserved is True
    assert causal.useful_dissent_count == 1

    assert (
        by_bee["dissent"].reward
        > by_bee["support"].reward
    )

    assert (
        by_bee["dissent"].reputation_after
        > by_bee["dissent"].reputation_before
    )


def test_complete_phase9_adversarial_receipt():
    results = (
        SocialAttackResult(
            "DUPLICATE_LINEAGE_FALSE_UNISON",
            True,
            "same_root_did_not_create_independent_voice",
            {"independent_roots": 1},
        ),
        SocialAttackResult(
            "SAME_ROOT_CLONE_SWARM",
            True,
            "clone_swarm_collapsed_to_one_root",
            {"clone_n": 3},
        ),
        SocialAttackResult(
            "DELAYED_RESPONSE",
            True,
            "late_response_failed_quorum_timing",
            {"call_response_window_ms": 1000},
        ),
        SocialAttackResult(
            "STALE_TESTIMONY",
            True,
            "out_of_window_testimony_refused",
            {},
        ),
        SocialAttackResult(
            "COORDINATED_WRONG_AGREEMENT",
            True,
            "future_outcome_refuted_consensus",
            {},
        ),
        SocialAttackResult(
            "USEFUL_DISSENT",
            True,
            "prospectively_correct_dissent_rewarded",
            {},
        ),
    )

    receipt = build_adversarial_gauntlet_receipt(
        hypothesis_id=H,
        results=results,
    )

    assert receipt.total_attack_count == 6
    assert receipt.passed_attack_count == 6
    assert receipt.all_attacks_passed is True

    assert receipt.clone_independence_preserved is True
    assert (
        receipt.delayed_testimony_rejected_as_quorum
        is True
    )
    assert receipt.stale_testimony_rejected is True
    assert receipt.wrong_consensus_denied_truth is True
    assert receipt.useful_dissent_rewarded is True

    assert receipt.execution_eligible is False
    assert receipt.promotion_eligible is False
