from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .pollen_economy import (
    PollenBounty,
    PollenClaim,
    PollenSettlementReceipt,
    ProspectivePollenOutcome,
)
from .polyphonic_quorum import PolyphonicQuorumReceipt


def _digest(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class PollenCausalReceipt:
    schema: str
    causal_receipt_id: str

    bounty_id: str
    hypothesis_id: str
    world_state_id: str
    world_state_hash: str

    claim_ids: tuple[str, ...]
    independent_root_count: int
    family_count: int
    roles_present: tuple[str, ...]
    explicit_dissent_present: bool
    quorum_formed: bool

    outcome_id: str
    outcome_class: str
    prospective: bool
    settled_at_ms: int

    settlement_id: str
    rewarded_bees: tuple[str, ...]

    information_gain: float
    useful_claim_count: int
    harmful_claim_count: int
    unresolved_claim_count: int

    useful_dissent_count: int
    useful_support_count: int

    intervention_had_information_value: bool
    useful_dissent_preserved: bool
    clone_swarm_discounted: bool

    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_pollen_causal_receipt(
    *,
    bounty: PollenBounty,
    claims: Sequence[PollenClaim],
    quorum: PolyphonicQuorumReceipt,
    outcome: ProspectivePollenOutcome,
    settlement: PollenSettlementReceipt,
) -> PollenCausalReceipt:

    if not outcome.prospective:
        raise ValueError(
            "pollen_causal_receipt_requires_prospective_outcome"
        )

    if bounty.hypothesis_id != outcome.hypothesis_id:
        raise ValueError(
            "pollen_causal_hypothesis_mismatch"
        )

    if settlement.bounty_id != bounty.bounty_id:
        raise ValueError(
            "pollen_causal_settlement_bounty_mismatch"
        )

    if settlement.outcome_id != outcome.outcome_id:
        raise ValueError(
            "pollen_causal_settlement_outcome_mismatch"
        )

    eligible = [
        claim
        for claim in claims
        if claim.bounty_id == bounty.bounty_id
        and claim.hypothesis_id == bounty.hypothesis_id
        and claim.world_state_id == bounty.world_state_id
        and claim.world_state_hash == bounty.world_state_hash
    ]

    by_claim = {
        transfer.claim_id: transfer
        for transfer in settlement.transfers
    }

    useful = []
    harmful = []
    unresolved = []

    useful_dissent = []
    useful_support = []

    for claim in eligible:
        transfer = by_claim.get(claim.claim_id)

        if transfer is None:
            unresolved.append(claim)
            continue

        if transfer.correctness >= 1.0:
            useful.append(claim)

            if claim.stance in {"DISSENT", "FALSIFY"}:
                useful_dissent.append(claim)

            if claim.stance in {"SUPPORT", "CORROBORATE"}:
                useful_support.append(claim)

        elif outcome.outcome_class == "UNRESOLVED":
            unresolved.append(claim)

        else:
            harmful.append(claim)

    unique_roots = {
        claim.root_lineage_digest
        for claim in eligible
        if claim.independent
        and claim.root_lineage_digest
    }

    independent_claim_n = sum(
        1
        for claim in eligible
        if claim.independent
    )

    clone_swarm_discounted = (
        independent_claim_n > len(unique_roots)
        and quorum.independent_root_count
        == len(unique_roots)
    )

    information_value = bool(
        float(outcome.information_gain) > 0.0
        and len(useful) > 0
    )

    dissent_preserved = bool(
        useful_dissent
        and quorum.explicit_dissent_present
    )

    rewarded_bees = tuple(sorted({
        transfer.bee_id
        for transfer in settlement.transfers
        if transfer.reward > 0.0
    }))

    body = {
        "bounty_id": bounty.bounty_id,
        "claims": sorted(
            claim.claim_id
            for claim in eligible
        ),
        "quorum_id": quorum.quorum_id,
        "outcome_id": outcome.outcome_id,
        "settlement_id": settlement.settlement_id,
        "information_gain": outcome.information_gain,
        "useful_claims": sorted(
            claim.claim_id
            for claim in useful
        ),
        "harmful_claims": sorted(
            claim.claim_id
            for claim in harmful
        ),
        "unresolved_claims": sorted(
            claim.claim_id
            for claim in unresolved
        ),
    }

    return PollenCausalReceipt(
        schema="hivenance_pollen_causal_receipt_v1",
        causal_receipt_id=(
            "pcausal_"
            + _digest(body).split(":", 1)[1][:24]
        ),
        bounty_id=bounty.bounty_id,
        hypothesis_id=bounty.hypothesis_id,
        world_state_id=bounty.world_state_id,
        world_state_hash=bounty.world_state_hash,
        claim_ids=tuple(sorted(
            claim.claim_id
            for claim in eligible
        )),
        independent_root_count=(
            quorum.independent_root_count
        ),
        family_count=quorum.family_count,
        roles_present=quorum.roles_present,
        explicit_dissent_present=(
            quorum.explicit_dissent_present
        ),
        quorum_formed=quorum.quorum_formed,
        outcome_id=outcome.outcome_id,
        outcome_class=outcome.outcome_class,
        prospective=outcome.prospective,
        settled_at_ms=outcome.settled_at_ms,
        settlement_id=settlement.settlement_id,
        rewarded_bees=rewarded_bees,
        information_gain=round(
            float(outcome.information_gain),
            6,
        ),
        useful_claim_count=len(useful),
        harmful_claim_count=len(harmful),
        unresolved_claim_count=len(unresolved),
        useful_dissent_count=len(useful_dissent),
        useful_support_count=len(useful_support),
        intervention_had_information_value=(
            information_value
        ),
        useful_dissent_preserved=dissent_preserved,
        clone_swarm_discounted=clone_swarm_discounted,
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
        promotion_eligible=False,
    )
