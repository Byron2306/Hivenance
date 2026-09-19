from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .settlement import SettledRelativeForecast
from .waggle_protocol import WaggleReceipt
from .musical_cognition import MotifNote
from .polyphonic_quorum import (
    PolyphonicQuorum,
    PolyphonicQuorumConfig,
    PolyphonicQuorumReceipt,
)


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


SUPPORT_STANCES = {"SUPPORT", "CORROBORATE"}
CHALLENGE_STANCES = {"DISSENT", "FALSIFY"}
ALL_STANCES = SUPPORT_STANCES | CHALLENGE_STANCES | {"ABSTAIN"}

BOUNTY_TYPES = {
    "POLLEN_SEARCH",
    "POLLEN_DISSENT",
    "POLLEN_FALSIFY",
    "POLLEN_CORROBORATE",
    "POLLEN_SETTLE",
    "POLLEN_NOVELTY",
    "POLLEN_EFFICIENCY",
}


@dataclass(frozen=True)
class PollenBounty:
    schema: str
    bounty_id: str
    bounty_type: str
    hypothesis_id: str
    world_state_id: str
    world_state_hash: str
    horizon_band: str
    issued_at_ms: int
    expires_at_ms: int
    reward_pool: float
    challenge_required: bool = True
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PollenClaim:
    schema: str
    claim_id: str
    bounty_id: str
    bee_id: str
    hypothesis_id: str
    stance: str
    message_type: str
    confidence: float
    stake: float
    information_gain_claim: float
    family: str
    lineage_digest: str
    root_lineage_digest: str
    evidence_root: str
    waggle_receipt_id: str
    world_state_id: str
    world_state_hash: str
    independent: bool
    submitted_at_ms: int
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProspectivePollenOutcome:
    schema: str
    outcome_id: str
    hypothesis_id: str
    settled_at_ms: int
    outcome_class: str
    information_gain: float
    forecast_id: str | None = None
    realized_net_bps: float | None = None
    prospective: bool = True
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    @classmethod
    def from_settled_forecast(
        cls,
        *,
        hypothesis_id: str,
        settlement: SettledRelativeForecast,
        information_gain: float = 1.0,
    ) -> "ProspectivePollenOutcome":
        net = settlement.realized_directional_net_bps
        if settlement.abstain or net is None:
            outcome_class = "UNRESOLVED"
        elif float(net) > 0.0:
            outcome_class = "SUPPORTED"
        else:
            outcome_class = "REFUTED"
        body = {
            "hypothesis_id": hypothesis_id,
            "forecast_id": settlement.forecast_id,
            "settled_at_ms": settlement.settled_timestamp_ms,
            "net_bps": net,
            "outcome_class": outcome_class,
        }
        return cls(
            schema="hivenance_prospective_pollen_outcome_v1",
            outcome_id="pout_" + _digest(body).split(":", 1)[1][:24],
            hypothesis_id=hypothesis_id,
            settled_at_ms=settlement.settled_timestamp_ms,
            outcome_class=outcome_class,
            information_gain=round(_clamp(information_gain), 6),
            forecast_id=settlement.forecast_id,
            realized_net_bps=None if net is None else round(float(net), 6),
            prospective=True,
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PollenTransfer:
    bee_id: str
    claim_id: str
    stake_returned: float
    reward: float
    net_pollen_change: float
    reputation_before: float
    reputation_after: float
    correctness: float
    calibration: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PollenSettlementReceipt:
    schema: str
    settlement_id: str
    bounty_id: str
    hypothesis_id: str
    outcome_id: str
    quorum_id: str | None
    reward_pool: float
    transfers: tuple[PollenTransfer, ...]
    total_rewarded: float
    total_stake_returned: float
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["transfers"] = tuple(t.to_dict() for t in self.transfers)
        return payload


class MetatronQuorumChamber:
    """Adapter from lawful Pollen claims into canonical Polyphonic Quorum.

    Quorum means synchronized, choreographed ensemble participation around one
    world-bound motif. It never means majority agreement and it never requires
    support to outweigh dissent.
    """

    version = "hivenance.metatron_quorum_chamber.v2"

    def __init__(
        self,
        *,
        min_independent_roots: int = 2,
        min_families: int = 2,
        min_roles: int = 2,
        phase_window_ms: int = 15_000,
        call_response_window_ms: int = 30_000,
        ensemble_lock_threshold: float = 0.58,
    ) -> None:
        self.engine = PolyphonicQuorum(
            PolyphonicQuorumConfig(
                minimum_independent_roots=max(1, int(min_independent_roots)),
                minimum_families=max(1, int(min_families)),
                minimum_roles=max(1, int(min_roles)),
                phase_window_ms=max(1, int(phase_window_ms)),
                call_response_window_ms=max(1, int(call_response_window_ms)),
                ensemble_lock_threshold=_clamp(ensemble_lock_threshold),
            )
        )

    def assess(
        self,
        *,
        bounty: PollenBounty,
        claims: Sequence[PollenClaim],
        reputations: Mapping[str, float] | None = None,
        challenge_survived: bool | None = None,
    ) -> PolyphonicQuorumReceipt:
        # reputations and challenge_survived are accepted for backward call-site
        # compatibility, but neither can manufacture quorum.
        del reputations, challenge_survived

        eligible = [
            claim for claim in claims
            if claim.bounty_id == bounty.bounty_id
            and claim.hypothesis_id == bounty.hypothesis_id
            and claim.world_state_id == bounty.world_state_id
            and claim.world_state_hash == bounty.world_state_hash
            and claim.independent
        ]

        # Collapse clones/descendants to one representative per independent root.
        by_root: dict[str, PollenClaim] = {}
        for claim in sorted(eligible, key=lambda row: (row.submitted_at_ms, row.claim_id)):
            by_root.setdefault(claim.root_lineage_digest, claim)

        notes = []
        for claim in by_root.values():
            notes.append(MotifNote(
                message_id=claim.claim_id,
                receipt_id=claim.waggle_receipt_id,
                hypothesis_id=claim.hypothesis_id,
                bee_id=claim.bee_id,
                family=claim.family,
                lineage_digest=claim.lineage_digest,
                root_lineage_digest=claim.root_lineage_digest,
                message_type=claim.message_type,
                observed_at_ms=claim.submitted_at_ms,
                horizon_band=bounty.horizon_band,
                direction="ABSTAIN",
                expected_move_bps=None,
                uncertainty=1.0-_clamp(claim.confidence),
                pulse_type=None,
                evidence_root=claim.evidence_root,
                world_state_id=claim.world_state_id,
                world_state_hash=claim.world_state_hash,
                independent_voice=True,
            ))
        return self.engine.score(notes)


class QueenPollenEconomy:
    """Research incentive economy governed by prospective settlement.

    Pollen changes research attention and budget only. It cannot create evidence,
    independence, execution authority, promotion authority, or prospective truth.
    """

    version = "hivenance.queen_pollen_economy.v1"

    def __init__(self, *, initial_pollen: float = 20.0) -> None:
        self.initial_pollen = max(0.0, float(initial_pollen))
        self._balances: dict[str, float] = {}
        self._reputations: dict[str, float] = {}
        self._bounties: dict[str, PollenBounty] = {}
        self._claims: dict[str, list[PollenClaim]] = {}
        self._settled_bounties: set[str] = set()

    def balance(self, bee_id: str) -> float:
        return round(self._balances.get(bee_id, self.initial_pollen), 6)

    def reputation(self, bee_id: str) -> float:
        return round(_clamp(self._reputations.get(bee_id, 0.5)), 6)

    def reputations(self) -> dict[str, float]:
        bees = set(self._balances) | set(self._reputations)
        return {bee: self.reputation(bee) for bee in sorted(bees)}

    def issue_bounty(
        self,
        *,
        bounty_type: str,
        hypothesis_id: str,
        world_state_id: str,
        world_state_hash: str,
        horizon_band: str,
        issued_at_ms: int,
        expires_at_ms: int,
        reward_pool: float,
        challenge_required: bool = True,
    ) -> PollenBounty:
        bounty_type = str(bounty_type).upper()
        if bounty_type not in BOUNTY_TYPES:
            raise ValueError("unknown_pollen_bounty_type")
        if expires_at_ms <= issued_at_ms:
            raise ValueError("pollen_bounty_expiry_invalid")
        if reward_pool <= 0:
            raise ValueError("pollen_bounty_reward_pool_must_be_positive")
        body = {
            "type": bounty_type,
            "hypothesis": hypothesis_id,
            "world_state_id": world_state_id,
            "world_state_hash": world_state_hash,
            "horizon_band": horizon_band,
            "issued_at_ms": int(issued_at_ms),
            "expires_at_ms": int(expires_at_ms),
            "reward_pool": round(float(reward_pool), 6),
        }
        bounty = PollenBounty(
            schema="hivenance_pollen_bounty_v1",
            bounty_id="pollen_" + _digest(body).split(":", 1)[1][:24],
            bounty_type=bounty_type,
            hypothesis_id=hypothesis_id,
            world_state_id=world_state_id,
            world_state_hash=world_state_hash,
            horizon_band=horizon_band,
            issued_at_ms=int(issued_at_ms),
            expires_at_ms=int(expires_at_ms),
            reward_pool=round(float(reward_pool), 6),
            challenge_required=bool(challenge_required),
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )
        self._bounties[bounty.bounty_id] = bounty
        self._claims.setdefault(bounty.bounty_id, [])
        return bounty

    def submit_claim(
        self,
        *,
        bounty: PollenBounty,
        bee_id: str,
        receipt: WaggleReceipt,
        stance: str,
        confidence: float,
        stake: float,
        information_gain_claim: float,
        submitted_at_ms: int,
    ) -> PollenClaim:
        if bounty.bounty_id not in self._bounties:
            raise ValueError("unknown_pollen_bounty")
        if bounty.bounty_id in self._settled_bounties:
            raise ValueError("pollen_bounty_already_settled")
        if submitted_at_ms > bounty.expires_at_ms:
            raise ValueError("pollen_bounty_expired")
        if receipt.hypothesis_id != bounty.hypothesis_id:
            raise ValueError("pollen_claim_hypothesis_mismatch")
        if receipt.world_state_id != bounty.world_state_id or receipt.world_state_hash != bounty.world_state_hash:
            raise ValueError("pollen_claim_world_state_mismatch")
        if not receipt.accepted or not receipt.choir_eligible:
            raise ValueError("pollen_claim_requires_lawful_waggle")
        if not receipt.root_lineage_digest:
            raise ValueError("pollen_claim_requires_registered_root_lineage")

        stance = str(stance).upper()
        if stance not in ALL_STANCES:
            raise ValueError("unknown_pollen_claim_stance")
        if stance in CHALLENGE_STANCES and receipt.message_type not in {"DISSENT", "SEARCH", "ALARM"}:
            raise ValueError("challenge_stance_requires_challenge_testimony")
        if stance in SUPPORT_STANCES and receipt.message_type not in {"WAGGLE", "FOLLOW", "SETTLE"}:
            raise ValueError("support_stance_requires_support_testimony")

        stake = max(0.0, float(stake))
        if stake > self.balance(bee_id):
            raise ValueError("insufficient_pollen_for_stake")

        confidence = _clamp(confidence)
        info_claim = _clamp(information_gain_claim)
        body = {
            "bounty": bounty.bounty_id,
            "bee": bee_id,
            "receipt": receipt.receipt_id,
            "stance": stance,
            "confidence": round(confidence, 6),
            "stake": round(stake, 6),
            "submitted_at_ms": int(submitted_at_ms),
        }
        claim = PollenClaim(
            schema="hivenance_pollen_claim_v1",
            claim_id="pclaim_" + _digest(body).split(":", 1)[1][:24],
            bounty_id=bounty.bounty_id,
            bee_id=bee_id,
            hypothesis_id=bounty.hypothesis_id,
            stance=stance,
            message_type=receipt.message_type,
            confidence=round(confidence, 6),
            stake=round(stake, 6),
            information_gain_claim=round(info_claim, 6),
            family=receipt.family,
            lineage_digest=receipt.lineage_digest,
            root_lineage_digest=str(receipt.root_lineage_digest),
            evidence_root=receipt.evidence_root,
            waggle_receipt_id=receipt.receipt_id,
            world_state_id=receipt.world_state_id,
            world_state_hash=receipt.world_state_hash,
            independent=bool(receipt.independent_vote_eligible),
            submitted_at_ms=int(submitted_at_ms),
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )
        self._balances[bee_id] = self.balance(bee_id) - stake
        self._claims[bounty.bounty_id].append(claim)
        return claim

    def claims(self, bounty_id: str) -> tuple[PollenClaim, ...]:
        return tuple(self._claims.get(bounty_id, ()))

    @staticmethod
    def _correctness(claim: PollenClaim, outcome: ProspectivePollenOutcome) -> float:
        if outcome.outcome_class == "UNRESOLVED":
            return 0.5 if claim.stance == "ABSTAIN" else 0.0
        if outcome.outcome_class == "SUPPORTED":
            return 1.0 if claim.stance in SUPPORT_STANCES else 0.0
        if outcome.outcome_class == "REFUTED":
            return 1.0 if claim.stance in CHALLENGE_STANCES else 0.0
        return 0.0

    def settle(
        self,
        *,
        bounty: PollenBounty,
        outcome: ProspectivePollenOutcome,
        quorum: PolyphonicQuorumReceipt | None = None,
    ) -> PollenSettlementReceipt:
        if bounty.bounty_id in self._settled_bounties:
            raise ValueError("pollen_bounty_already_settled")
        if outcome.hypothesis_id != bounty.hypothesis_id:
            raise ValueError("pollen_outcome_hypothesis_mismatch")
        if not outcome.prospective:
            raise ValueError("pollen_rewards_require_prospective_settlement")

        claims = list(self._claims.get(bounty.bounty_id, ()))
        scored: list[tuple[PollenClaim, float, float, float]] = []
        for claim in claims:
            correctness = self._correctness(claim, outcome)
            calibration = _clamp(1.0 - abs(claim.confidence - correctness))
            independence = 1.0 if claim.independent else 0.25
            novelty = _clamp(claim.information_gain_claim)
            falsification_bonus = 1.15 if claim.stance == "FALSIFY" and correctness == 1.0 else 1.0
            score = (
                correctness
                * (0.35 + 0.25 * calibration + 0.20 * independence + 0.20 * novelty)
                * (0.5 + 0.5 * outcome.information_gain)
                * falsification_bonus
            )
            scored.append((claim, correctness, calibration, max(0.0, score)))

        total_score = sum(row[3] for row in scored)
        transfers: list[PollenTransfer] = []
        total_rewarded = 0.0
        total_returned = 0.0

        for claim, correctness, calibration, score in scored:
            before = self.reputation(claim.bee_id)
            reward = (bounty.reward_pool * score / total_score) if total_score > 0.0 else 0.0
            stake_returned = claim.stake if correctness >= 1.0 else claim.stake * calibration * 0.5
            if outcome.outcome_class == "UNRESOLVED":
                stake_returned = claim.stake

            reputation_delta = (
                0.08 * (correctness - 0.5)
                + 0.05 * (calibration - 0.5)
                + 0.03 * (1.0 if claim.independent else -0.5)
            )
            after = _clamp(before + reputation_delta)
            self._reputations[claim.bee_id] = after
            self._balances[claim.bee_id] = self.balance(claim.bee_id) + stake_returned + reward

            total_rewarded += reward
            total_returned += stake_returned
            transfers.append(PollenTransfer(
                bee_id=claim.bee_id,
                claim_id=claim.claim_id,
                stake_returned=round(stake_returned, 6),
                reward=round(reward, 6),
                net_pollen_change=round(-claim.stake + stake_returned + reward, 6),
                reputation_before=round(before, 6),
                reputation_after=round(after, 6),
                correctness=round(correctness, 6),
                calibration=round(calibration, 6),
                reason=(
                    "prospective_claim_supported"
                    if correctness == 1.0
                    else "prospective_claim_unresolved"
                    if outcome.outcome_class == "UNRESOLVED"
                    else "prospective_claim_refuted"
                ),
            ))

        self._settled_bounties.add(bounty.bounty_id)
        body = {
            "bounty": bounty.bounty_id,
            "outcome": outcome.outcome_id,
            "quorum": quorum.quorum_id if quorum else None,
            "transfers": [t.to_dict() for t in transfers],
        }
        return PollenSettlementReceipt(
            schema="hivenance_pollen_settlement_v1",
            settlement_id="pset_" + _digest(body).split(":", 1)[1][:24],
            bounty_id=bounty.bounty_id,
            hypothesis_id=bounty.hypothesis_id,
            outcome_id=outcome.outcome_id,
            quorum_id=quorum.quorum_id if quorum else None,
            reward_pool=round(bounty.reward_pool, 6),
            transfers=tuple(transfers),
            total_rewarded=round(total_rewarded, 6),
            total_stake_returned=round(total_returned, 6),
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )

    def leaderboard(self) -> tuple[tuple[str, float, float], ...]:
        bees = set(self._balances) | set(self._reputations)
        return tuple(sorted(
            ((bee, self.balance(bee), self.reputation(bee)) for bee in bees),
            key=lambda row: (-row[2], -row[1], row[0]),
        ))