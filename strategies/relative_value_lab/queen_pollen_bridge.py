from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from .contracts import RELATIVE_VALUE_AUTHORITY
from .pollen_economy import PollenBounty, QueenPollenEconomy
from .recursive_queen_loop import QueenResearchRequest


def _digest(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


REQUEST_TO_BOUNTY = {
    "CHALLENGE": "POLLEN_DISSENT",
    "INVITE_INDEPENDENT_CORROBORATION": "POLLEN_CORROBORATE",
    "AMPLIFY": "POLLEN_SEARCH",
    "REFRESH": "POLLEN_SEARCH",
    "COMPARE": "POLLEN_NOVELTY",
    "REHEARSE_EDGE_RESOLUTION": "POLLEN_EFFICIENCY",
    "PRESERVE_COUNTERPOINT": "POLLEN_DISSENT",
}


NON_ECONOMIC_REQUESTS = {
    "THIN",
    "RETIRE_FROM_ACTIVE_SCORE",
    "CHANGE_EPOCH",
    "WAIT_REST",
}


@dataclass(frozen=True)
class QueenPollenBountyReceipt:
    schema: str
    bridge_receipt_id: str

    request_id: str
    request_kind: str
    source_queen_receipt_id: str

    bounty_id: str
    bounty_type: str
    hypothesis_id: str

    world_state_id: str
    world_state_hash: str
    recurrence_index: int

    reward_pool: float
    issued_at_ms: int
    expires_at_ms: int

    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QueenPollenIssueResult:
    bounty: PollenBounty | None
    receipt: QueenPollenBountyReceipt | None
    state: str
    reason: str

    execution_eligible: bool = False
    promotion_eligible: bool = False


def bounty_type_for_request(
    request_kind: str,
) -> str | None:
    kind = str(request_kind).upper()

    if kind in NON_ECONOMIC_REQUESTS:
        return None

    try:
        return REQUEST_TO_BOUNTY[kind]
    except KeyError as exc:
        raise ValueError(
            f"queen_request_has_no_pollen_policy:{kind}"
        ) from exc


def issue_bounty_from_queen_request(
    *,
    economy: QueenPollenEconomy,
    request: QueenResearchRequest,
    hypothesis_id: str,
    horizon_band: str,
    issued_at_ms: int,
    ttl_ms: int = 30_000,
    reward_pool: float = 5.0,
) -> QueenPollenIssueResult:

    if ttl_ms <= 0:
        raise ValueError("queen_pollen_ttl_must_be_positive")

    if reward_pool <= 0:
        raise ValueError(
            "queen_pollen_reward_pool_must_be_positive"
        )

    bounty_type = bounty_type_for_request(
        request.request_kind
    )

    if bounty_type is None:
        return QueenPollenIssueResult(
            bounty=None,
            receipt=None,
            state="NOT_APPLICABLE",
            reason="queen_request_is_non_economic",
        )

    bounty = economy.issue_bounty(
        bounty_type=bounty_type,
        hypothesis_id=str(hypothesis_id),
        world_state_id=request.world_state_id,
        world_state_hash=request.world_state_hash,
        horizon_band=str(horizon_band),
        issued_at_ms=int(issued_at_ms),
        expires_at_ms=int(issued_at_ms + ttl_ms),
        reward_pool=float(reward_pool),
        challenge_required=(
            bounty_type
            in {
                "POLLEN_DISSENT",
                "POLLEN_FALSIFY",
            }
        ),
    )

    body = {
        "request_id": request.request_id,
        "request_kind": request.request_kind,
        "source_queen_receipt_id": (
            request.source_receipt_id
        ),
        "bounty_id": bounty.bounty_id,
        "bounty_type": bounty.bounty_type,
        "hypothesis_id": hypothesis_id,
        "world_state_id": request.world_state_id,
        "world_state_hash": request.world_state_hash,
        "recurrence_index": request.recurrence_index,
        "reward_pool": bounty.reward_pool,
        "issued_at_ms": bounty.issued_at_ms,
        "expires_at_ms": bounty.expires_at_ms,
    }

    receipt = QueenPollenBountyReceipt(
        schema="hivenance_queen_pollen_bounty_receipt_v1",
        bridge_receipt_id=(
            "qpb_"
            + _digest(body).split(":", 1)[1][:24]
        ),
        request_id=request.request_id,
        request_kind=request.request_kind,
        source_queen_receipt_id=(
            request.source_receipt_id
        ),
        bounty_id=bounty.bounty_id,
        bounty_type=bounty.bounty_type,
        hypothesis_id=str(hypothesis_id),
        world_state_id=request.world_state_id,
        world_state_hash=request.world_state_hash,
        recurrence_index=request.recurrence_index,
        reward_pool=bounty.reward_pool,
        issued_at_ms=bounty.issued_at_ms,
        expires_at_ms=bounty.expires_at_ms,
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
        promotion_eligible=False,
    )

    return QueenPollenIssueResult(
        bounty=bounty,
        receipt=receipt,
        state="ISSUED",
        reason="queen_research_request_funded",
        execution_eligible=False,
        promotion_eligible=False,
    )
