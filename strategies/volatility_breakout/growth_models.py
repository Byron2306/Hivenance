from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class GrowthStage:
    stage_id: int
    name: str
    max_notional_usd: float
    allowed_symbols: tuple[str, ...]
    max_open_orders: int
    max_open_positions: int
    daily_loss_halt_usd: float
    min_new_round_trips: int
    min_distinct_days: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_symbols"] = list(self.allowed_symbols)
        return payload


@dataclass(frozen=True)
class GrowthProposal:
    proposal_id: str
    from_stage: int
    to_stage: int
    proposed_by: str
    created_ts: float
    cooldown_until_ts: float
    expires_ts: float
    evidence_hash: str
    config_hash: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    status: str = "PROPOSED"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload


@dataclass(frozen=True)
class GrowthApproval:
    approval_id: str
    proposal_id: str
    approved_by: str
    approved_ts: float
    expires_ts: float
    acknowledgement_hash: str
    status: str = "ACTIVE"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GrowthIncident:
    incident_id: str
    ts: float
    severity: str
    category: str
    message: str
    stage_id: int
    requires_human_review: bool = True
    payload: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
