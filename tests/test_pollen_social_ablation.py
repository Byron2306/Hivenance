from strategies.relative_value_lab.contracts import (
    RELATIVE_VALUE_AUTHORITY,
)
from strategies.relative_value_lab.pollen_economy import (
    MetatronQuorumChamber,
    ProspectivePollenOutcome,
    QueenPollenEconomy,
)
from strategies.relative_value_lab.pollen_social_ablation import (
    SocialAblationArm,
    build_social_ablation_receipt,
)
from strategies.relative_value_lab.waggle_protocol import (
    WaggleReceipt,
)


R1 = "sha256:" + "1" * 64
R2 = "sha256:" + "2" * 64
E1 = "sha256:" + "a" * 64
E2 = "sha256:" + "b" * 64

WS = "ws-phase9-ablation"
WH = "sha256:" + "f" * 64
H = "phase9-ablation"


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


def run_arm(
    *,
    name,
    pollen_rewards_enabled,
    reputation_updates_enabled,
):
    economy = QueenPollenEconomy(
        initial_pollen=20,
    )

    bounty = economy.issue_bounty(
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

    economy.submit_claim(
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

    economy.submit_claim(
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

    claims = economy.claims(
        bounty.bounty_id
    )

    quorum = MetatronQuorumChamber(
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

    outcome = ProspectivePollenOutcome(
        schema=(
            "hivenance_prospective_pollen_outcome_v1"
        ),
        outcome_id="ablation-outcome",
        hypothesis_id=H,
        settled_at_ms=20000,
        outcome_class="REFUTED",
        information_gain=1.0,
        forecast_id="ablation-forecast",
        realized_net_bps=-5.0,
        prospective=True,
    )

    settlement = economy.settle(
        bounty=bounty,
        outcome=outcome,
        quorum=quorum,
        pollen_rewards_enabled=(
            pollen_rewards_enabled
        ),
        reputation_updates_enabled=(
            reputation_updates_enabled
        ),
    )

    transfers = {
        row.bee_id: row
        for row in settlement.transfers
    }

    dissent = transfers["dissent"]
    support = transfers["support"]

    return (
        SocialAblationArm(
            name=name,
            pollen_rewards_enabled=(
                pollen_rewards_enabled
            ),
            reputation_updates_enabled=(
                reputation_updates_enabled
            ),
            total_rewarded=(
                settlement.total_rewarded
            ),
            dissent_reward=dissent.reward,
            support_reward=support.reward,
            dissent_reputation_before=(
                dissent.reputation_before
            ),
            dissent_reputation_after=(
                dissent.reputation_after
            ),
            support_reputation_before=(
                support.reputation_before
            ),
            support_reputation_after=(
                support.reputation_after
            ),
        ),
        settlement,
        outcome,
    )


def test_pollen_reward_and_reputation_are_independent_ablation_organs():
    full, full_settlement, outcome = run_arm(
        name="FULL",
        pollen_rewards_enabled=True,
        reputation_updates_enabled=True,
    )

    no_pollen, _, _ = run_arm(
        name="NO_POLLEN_REWARD",
        pollen_rewards_enabled=False,
        reputation_updates_enabled=True,
    )

    no_rep, _, _ = run_arm(
        name="NO_REPUTATION",
        pollen_rewards_enabled=True,
        reputation_updates_enabled=False,
    )

    neither, _, _ = run_arm(
        name="NO_POLLEN_OR_REPUTATION",
        pollen_rewards_enabled=False,
        reputation_updates_enabled=False,
    )

    # Pollen reward is independently removed.
    assert full.total_rewarded > 0.0
    assert no_pollen.total_rewarded == 0.0

    # Removing reputation must not remove Pollen rewards.
    assert no_rep.total_rewarded == (
        full.total_rewarded
    )

    # Removing Pollen rewards must not remove reputation learning.
    assert (
        no_pollen.dissent_reputation_after
        > no_pollen.dissent_reputation_before
    )

    # Removing reputation freezes reputation only.
    assert (
        no_rep.dissent_reputation_after
        == no_rep.dissent_reputation_before
    )

    assert (
        neither.dissent_reputation_after
        == neither.dissent_reputation_before
    )

    receipt = build_social_ablation_receipt(
        hypothesis_id=H,
        outcome_id=outcome.outcome_id,
        arms=(
            full,
            no_pollen,
            no_rep,
            neither,
        ),
    )

    assert (
        receipt.pollen_reward_effect_observed
        is True
    )
    assert (
        receipt.reputation_effect_observed
        is True
    )
    assert (
        receipt.pollen_and_reputation_separately_ablatable
        is True
    )

    assert receipt.execution_eligible is False
    assert receipt.promotion_eligible is False

    assert full_settlement.execution_eligible is False
    assert full_settlement.promotion_eligible is False


def test_reward_ablation_does_not_change_claim_correctness():
    full, _, _ = run_arm(
        name="FULL",
        pollen_rewards_enabled=True,
        reputation_updates_enabled=True,
    )

    no_pollen, _, _ = run_arm(
        name="NO_POLLEN_REWARD",
        pollen_rewards_enabled=False,
        reputation_updates_enabled=True,
    )

    assert full.dissent_reward > 0.0
    assert no_pollen.dissent_reward == 0.0

    # The reward mechanism changed, not the prospective truth.
    assert (
        full.dissent_reputation_after
        == no_pollen.dissent_reputation_after
    )


def test_reputation_ablation_does_not_change_reward_allocation():
    full, _, _ = run_arm(
        name="FULL",
        pollen_rewards_enabled=True,
        reputation_updates_enabled=True,
    )

    no_rep, _, _ = run_arm(
        name="NO_REPUTATION",
        pollen_rewards_enabled=True,
        reputation_updates_enabled=False,
    )

    assert no_rep.total_rewarded == full.total_rewarded
    assert no_rep.dissent_reward == full.dissent_reward
    assert no_rep.support_reward == full.support_reward

    assert (
        no_rep.dissent_reputation_after
        == no_rep.dissent_reputation_before
    )
