from strategies.relative_value_lab.contracts import (
    RELATIVE_VALUE_AUTHORITY,
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

WS = "ws-phase9"
WH = "sha256:" + "f" * 64


def waggle(
    *,
    bee,
    family,
    root,
    evidence,
    msg,
    seq,
):
    return WaggleReceipt(
        schema="hivenance_waggle_receipt_v1",
        receipt_id=f"wr-{bee}-{seq}",
        sequence_number=seq,
        message_id=f"m-{bee}-{seq}",
        hypothesis_id="h-phase9",
        message_type=msg,
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
            "sha256:"
            + str(seq % 10) * 64
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
        hypothesis_id="h-phase9",
        world_state_id=WS,
        world_state_hash=WH,
        horizon_band="micro",
        issued_at_ms=0,
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


def refuted_outcome():
    return ProspectivePollenOutcome(
        schema=(
            "hivenance_prospective_pollen_outcome_v1"
        ),
        outcome_id="out-phase9",
        hypothesis_id="h-phase9",
        settled_at_ms=20000,
        outcome_class="REFUTED",
        information_gain=1.0,
        forecast_id="f-phase9",
        realized_net_bps=-5.0,
        prospective=True,
    )


def test_useful_dissent_has_prospective_causal_receipt():
    eco, bounty = economy()

    eco.submit_claim(
        bounty=bounty,
        bee_id="support",
        receipt=waggle(
            bee="support",
            family="structural",
            root=R1,
            evidence=E1,
            msg="WAGGLE",
            seq=1,
        ),
        stance="SUPPORT",
        confidence=.8,
        stake=2,
        information_gain_claim=.4,
        submitted_at_ms=1000,
    )

    eco.submit_claim(
        bounty=bounty,
        bee_id="dissent",
        receipt=waggle(
            bee="dissent",
            family="microstructure",
            root=R2,
            evidence=E2,
            msg="DISSENT",
            seq=2,
        ),
        stance="DISSENT",
        confidence=.8,
        stake=2,
        information_gain_claim=.7,
        submitted_at_ms=1500,
    )

    claims = eco.claims(bounty.bounty_id)
    quorum = quorum_for(bounty, claims)
    outcome = refuted_outcome()

    settlement = eco.settle(
        bounty=bounty,
        outcome=outcome,
        quorum=quorum,
    )

    causal = build_pollen_causal_receipt(
        bounty=bounty,
        claims=claims,
        quorum=quorum,
        outcome=outcome,
        settlement=settlement,
    )

    assert causal.quorum_formed is True
    assert causal.explicit_dissent_present is True
    assert causal.useful_dissent_count == 1
    assert causal.useful_support_count == 0

    assert causal.intervention_had_information_value is True
    assert causal.useful_dissent_preserved is True

    assert causal.execution_eligible is False
    assert causal.promotion_eligible is False


def test_same_root_clone_swarm_does_not_increase_independence():
    eco, bounty = economy()

    for index, bee in enumerate(
        ("support", "clone1", "clone2"),
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
                msg=(
                    "WAGGLE"
                    if index == 1
                    else "FOLLOW"
                ),
                seq=index,
            ),
            stance="SUPPORT",
            confidence=.8,
            stake=1,
            information_gain_claim=.2,
            submitted_at_ms=1000 + index * 100,
        )

    eco.submit_claim(
        bounty=bounty,
        bee_id="dissent",
        receipt=waggle(
            bee="dissent",
            family="microstructure",
            root=R2,
            evidence=E2,
            msg="DISSENT",
            seq=9,
        ),
        stance="DISSENT",
        confidence=.8,
        stake=1,
        information_gain_claim=.7,
        submitted_at_ms=1600,
    )

    claims = eco.claims(bounty.bounty_id)
    quorum = quorum_for(bounty, claims)

    assert quorum.independent_root_count == 2

    outcome = refuted_outcome()

    settlement = eco.settle(
        bounty=bounty,
        outcome=outcome,
        quorum=quorum,
    )

    causal = build_pollen_causal_receipt(
        bounty=bounty,
        claims=claims,
        quorum=quorum,
        outcome=outcome,
        settlement=settlement,
    )

    assert causal.clone_swarm_discounted is True
    assert causal.independent_root_count == 2


def test_wrong_consensus_does_not_become_truth():
    eco, bounty = economy()

    eco.submit_claim(
        bounty=bounty,
        bee_id="a",
        receipt=waggle(
            bee="a",
            family="structural",
            root=R1,
            evidence=E1,
            msg="WAGGLE",
            seq=1,
        ),
        stance="SUPPORT",
        confidence=.95,
        stake=2,
        information_gain_claim=.8,
        submitted_at_ms=1000,
    )

    eco.submit_claim(
        bounty=bounty,
        bee_id="b",
        receipt=waggle(
            bee="b",
            family="microstructure",
            root=R2,
            evidence=E2,
            msg="FOLLOW",
            seq=2,
        ),
        stance="SUPPORT",
        confidence=.95,
        stake=2,
        information_gain_claim=.8,
        submitted_at_ms=1500,
    )

    claims = eco.claims(bounty.bounty_id)
    quorum = quorum_for(bounty, claims)

    outcome = refuted_outcome()

    settlement = eco.settle(
        bounty=bounty,
        outcome=outcome,
        quorum=quorum,
    )

    causal = build_pollen_causal_receipt(
        bounty=bounty,
        claims=claims,
        quorum=quorum,
        outcome=outcome,
        settlement=settlement,
    )

    assert causal.useful_support_count == 0
    assert causal.harmful_claim_count == 2
    assert causal.useful_dissent_count == 0

    assert causal.execution_eligible is False
    assert causal.promotion_eligible is False


def test_nonprospective_outcome_cannot_create_causal_receipt():
    eco, bounty = economy()

    claim = eco.submit_claim(
        bounty=bounty,
        bee_id="support",
        receipt=waggle(
            bee="support",
            family="structural",
            root=R1,
            evidence=E1,
            msg="WAGGLE",
            seq=1,
        ),
        stance="SUPPORT",
        confidence=.8,
        stake=1,
        information_gain_claim=.5,
        submitted_at_ms=1000,
    )

    # We only need a lawful quorum-shaped receipt here.
    quorum = quorum_for(
        bounty,
        (claim,),
    )

    outcome = ProspectivePollenOutcome(
        schema=(
            "hivenance_prospective_pollen_outcome_v1"
        ),
        outcome_id="not-prospective",
        hypothesis_id="h-phase9",
        settled_at_ms=20000,
        outcome_class="SUPPORTED",
        information_gain=1.0,
        forecast_id="f",
        realized_net_bps=5.0,
        prospective=False,
    )

    from strategies.relative_value_lab.pollen_economy import (
        PollenSettlementReceipt,
    )

    settlement = PollenSettlementReceipt(
        schema="hivenance_pollen_settlement_v1",
        settlement_id="fake",
        bounty_id=bounty.bounty_id,
        hypothesis_id=bounty.hypothesis_id,
        outcome_id=outcome.outcome_id,
        quorum_id=quorum.quorum_id,
        reward_pool=0.0,
        transfers=(),
        total_rewarded=0.0,
        total_stake_returned=0.0,
    )

    import pytest

    with pytest.raises(
        ValueError,
        match="requires_prospective",
    ):
        build_pollen_causal_receipt(
            bounty=bounty,
            claims=(claim,),
            quorum=quorum,
            outcome=outcome,
            settlement=settlement,
        )
