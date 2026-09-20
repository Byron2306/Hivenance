import pytest

from strategies.relative_value_lab.pollen_economy import (
    QueenPollenEconomy,
)
from strategies.relative_value_lab.queen_pollen_bridge import (
    bounty_type_for_request,
    issue_bounty_from_queen_request,
)
from strategies.relative_value_lab.recursive_queen_loop import (
    QueenResearchRequest,
)


WS = "ws-phase9"
WH = "sha256:" + "f" * 64
ROOT = "sha256:" + "a" * 64


def request(kind: str) -> QueenResearchRequest:
    return QueenResearchRequest(
        schema="hivenance_queen_research_request_v1",
        request_id="request-" + kind.lower(),
        recurrence_index=1,
        request_kind=kind,
        target="test-target",
        reason="test",
        notation_token_id="token-1",
        source_receipt_id="queen-1",
        world_state_id=WS,
        world_state_hash=WH,
        observed_root_digest=ROOT,
        required_inputs=("world_graph",),
    )


@pytest.mark.parametrize(
    ("kind", "bounty"),
    (
        ("CHALLENGE", "POLLEN_DISSENT"),
        (
            "INVITE_INDEPENDENT_CORROBORATION",
            "POLLEN_CORROBORATE",
        ),
        ("AMPLIFY", "POLLEN_SEARCH"),
        ("REFRESH", "POLLEN_SEARCH"),
        ("COMPARE", "POLLEN_NOVELTY"),
        (
            "REHEARSE_EDGE_RESOLUTION",
            "POLLEN_EFFICIENCY",
        ),
        (
            "PRESERVE_COUNTERPOINT",
            "POLLEN_DISSENT",
        ),
    ),
)
def test_research_request_maps_to_bounty(kind, bounty):
    assert bounty_type_for_request(kind) == bounty


@pytest.mark.parametrize(
    "kind",
    (
        "THIN",
        "RETIRE_FROM_ACTIVE_SCORE",
        "CHANGE_EPOCH",
        "WAIT_REST",
    ),
)
def test_governance_requests_do_not_issue_pollen(kind):
    assert bounty_type_for_request(kind) is None


def test_challenge_request_issues_world_bound_bounty():
    eco = QueenPollenEconomy()

    req = request("CHALLENGE")

    result = issue_bounty_from_queen_request(
        economy=eco,
        request=req,
        hypothesis_id="h-phase9",
        horizon_band="micro",
        issued_at_ms=1000,
        ttl_ms=5000,
        reward_pool=7.0,
    )

    assert result.state == "ISSUED"

    bounty = result.bounty
    receipt = result.receipt

    assert bounty is not None
    assert receipt is not None

    assert bounty.bounty_type == "POLLEN_DISSENT"
    assert bounty.world_state_id == req.world_state_id
    assert bounty.world_state_hash == req.world_state_hash

    assert receipt.request_id == req.request_id
    assert receipt.bounty_id == bounty.bounty_id

    assert receipt.source_queen_receipt_id == (
        req.source_receipt_id
    )

    assert receipt.recurrence_index == 1

    assert receipt.execution_eligible is False
    assert receipt.promotion_eligible is False


def test_same_request_is_deterministic():
    first = issue_bounty_from_queen_request(
        economy=QueenPollenEconomy(),
        request=request("AMPLIFY"),
        hypothesis_id="h-phase9",
        horizon_band="micro",
        issued_at_ms=1000,
        ttl_ms=5000,
        reward_pool=5.0,
    )

    second = issue_bounty_from_queen_request(
        economy=QueenPollenEconomy(),
        request=request("AMPLIFY"),
        hypothesis_id="h-phase9",
        horizon_band="micro",
        issued_at_ms=1000,
        ttl_ms=5000,
        reward_pool=5.0,
    )

    assert first.bounty == second.bounty
    assert first.receipt == second.receipt


def test_wait_rest_does_not_create_bounty():
    eco = QueenPollenEconomy()

    result = issue_bounty_from_queen_request(
        economy=eco,
        request=request("WAIT_REST"),
        hypothesis_id="h-phase9",
        horizon_band="micro",
        issued_at_ms=1000,
    )

    assert result.state == "NOT_APPLICABLE"
    assert result.bounty is None
    assert result.receipt is None
    assert eco.bounties() == ()


def test_unknown_request_fails_closed():
    with pytest.raises(
        ValueError,
        match="no_pollen_policy",
    ):
        bounty_type_for_request(
            "INVENT_MONEY_FROM_NOWHERE"
        )


def test_invalid_reward_pool_refused():
    with pytest.raises(
        ValueError,
        match="reward_pool_must_be_positive",
    ):
        issue_bounty_from_queen_request(
            economy=QueenPollenEconomy(),
            request=request("CHALLENGE"),
            hypothesis_id="h-phase9",
            horizon_band="micro",
            issued_at_ms=1000,
            reward_pool=0.0,
        )
