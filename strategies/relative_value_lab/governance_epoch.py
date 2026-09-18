from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional

from .contracts import RELATIVE_VALUE_AUTHORITY
from .world_score import CanonicalScoreFrame


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ResearchGovernanceEpoch:
    """Frozen musical governance context for Phoenix research.

    Adapted from Metatron GovernanceEpoch: score + genre + strictness +
    world-state binding + bounded lifetime. It narrows research context and
    never grants execution or promotion authority.
    """

    epoch_id: str
    score_id: str
    genre_mode: str
    strictness_level: str
    scope: str
    world_state_id: str
    world_state_hash: str
    started_at_ms: int
    expires_at_ms: int
    reason: str
    status: str = "active"
    previous_epoch_id: Optional[str] = None
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def active(self) -> bool:
        return self.status == "active"


@dataclass(frozen=True)
class EpochValidation:
    schema: str
    validation_id: str
    epoch_id: str
    valid: bool
    reasons: tuple[str, ...]
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResearchGovernanceEpochService:
    """Fail-closed research epoch service.

    The active epoch defines which score the hive is currently allowed to
    perform. World-state drift, expiry, scope mismatch, or epoch mismatch
    invalidates the passage.
    """

    version = "hivenance.research_governance_epoch.v1"

    @staticmethod
    def derive_score_id(
        *,
        genre_mode: str,
        strictness_level: str,
        version: str = "v1",
    ) -> str:
        genre = str(genre_mode or "watchful").strip().lower()
        strictness = str(strictness_level or "standard").strip().lower()
        ver = str(version or "v1").strip().lower()
        return f"{genre}_{strictness}_{ver}"

    @staticmethod
    def start_epoch(
        *,
        world_state_id: str,
        world_state_hash: str,
        started_at_ms: int,
        ttl_ms: int,
        genre_mode: str = "watchful",
        strictness_level: str = "standard",
        scope: str = "relative_value_lab",
        reason: str = "research_epoch_start",
        version: str = "v1",
        previous_epoch_id: Optional[str] = None,
    ) -> ResearchGovernanceEpoch:
        if not str(world_state_hash).startswith("sha256:"):
            raise ValueError("world_state_hash_must_be_sha256_bound")
        if ttl_ms <= 0:
            raise ValueError("epoch_ttl_must_be_positive")
        score_id = ResearchGovernanceEpochService.derive_score_id(
            genre_mode=genre_mode,
            strictness_level=strictness_level,
            version=version,
        )
        body = {
            "world_state_id": world_state_id,
            "world_state_hash": world_state_hash,
            "started_at_ms": int(started_at_ms),
            "expires_at_ms": int(started_at_ms + ttl_ms),
            "genre_mode": genre_mode,
            "strictness_level": strictness_level,
            "scope": scope,
            "score_id": score_id,
            "previous_epoch_id": previous_epoch_id,
        }
        epoch_id = "epoch_" + _digest(body).split(":", 1)[1][:24]
        return ResearchGovernanceEpoch(
            epoch_id=epoch_id,
            score_id=score_id,
            genre_mode=str(genre_mode),
            strictness_level=str(strictness_level),
            scope=str(scope),
            world_state_id=str(world_state_id),
            world_state_hash=str(world_state_hash),
            started_at_ms=int(started_at_ms),
            expires_at_ms=int(started_at_ms + ttl_ms),
            reason=str(reason),
            status="active",
            previous_epoch_id=previous_epoch_id,
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )

    @staticmethod
    def start_epoch_from_frame(
        frame: CanonicalScoreFrame,
        *,
        started_at_ms: int,
        ttl_ms: int,
        genre_mode: str = "watchful",
        strictness_level: str = "standard",
        scope: str = "relative_value_lab",
        reason: str = "research_epoch_start",
        version: str = "v1",
        previous_epoch_id: Optional[str] = None,
    ) -> ResearchGovernanceEpoch:
        if not frame.is_fresh(started_at_ms):
            raise ValueError("cannot_start_epoch_from_stale_score_frame")
        return ResearchGovernanceEpochService.start_epoch(
            world_state_id=frame.world_state_id,
            world_state_hash=frame.world_state_hash,
            started_at_ms=started_at_ms,
            ttl_ms=ttl_ms,
            genre_mode=genre_mode,
            strictness_level=strictness_level,
            scope=scope,
            reason=reason,
            version=version,
            previous_epoch_id=previous_epoch_id,
        )

    @staticmethod
    def rotate_epoch(
        current: ResearchGovernanceEpoch,
        *,
        world_state_id: str,
        world_state_hash: str,
        started_at_ms: int,
        ttl_ms: int,
        reason: str,
        genre_mode: Optional[str] = None,
        strictness_level: Optional[str] = None,
        version: str = "v1",
    ) -> ResearchGovernanceEpoch:
        return ResearchGovernanceEpochService.start_epoch(
            world_state_id=world_state_id,
            world_state_hash=world_state_hash,
            started_at_ms=started_at_ms,
            ttl_ms=ttl_ms,
            genre_mode=str(genre_mode or current.genre_mode),
            strictness_level=str(strictness_level or current.strictness_level),
            scope=current.scope,
            reason=reason,
            version=version,
            previous_epoch_id=current.epoch_id,
        )

    @staticmethod
    def validate(
        epoch: ResearchGovernanceEpoch,
        *,
        now_ms: int,
        world_state_id: str,
        world_state_hash: str,
        scope: Optional[str] = None,
        required_epoch_id: Optional[str] = None,
        required_score_id: Optional[str] = None,
    ) -> EpochValidation:
        reasons: list[str] = []
        if epoch.status != "active":
            reasons.append("epoch_not_active")
        if int(now_ms) < int(epoch.started_at_ms):
            reasons.append("epoch_not_started")
        if int(now_ms) >= int(epoch.expires_at_ms):
            reasons.append("epoch_expired")
        if epoch.world_state_id != world_state_id or epoch.world_state_hash != world_state_hash:
            reasons.append("epoch_world_state_drift")
        if scope is not None and epoch.scope != str(scope):
            reasons.append("epoch_scope_mismatch")
        if required_epoch_id is not None and epoch.epoch_id != str(required_epoch_id):
            reasons.append("epoch_id_mismatch")
        if required_score_id is not None and epoch.score_id != str(required_score_id):
            reasons.append("score_id_mismatch")
        if epoch.authority != RELATIVE_VALUE_AUTHORITY:
            reasons.append("epoch_authority_mismatch")
        if epoch.execution_eligible or epoch.promotion_eligible:
            reasons.append("epoch_authority_escalation_forbidden")

        body = {
            "epoch_id": epoch.epoch_id,
            "valid": not reasons,
            "reasons": sorted(set(reasons)),
            "now_ms": int(now_ms),
            "world_state_id": world_state_id,
            "world_state_hash": world_state_hash,
            "scope": scope,
        }
        return EpochValidation(
            schema="hivenance_epoch_validation_v1",
            validation_id="epv_" + _digest(body).split(":", 1)[1][:24],
            epoch_id=epoch.epoch_id,
            valid=not reasons,
            reasons=tuple(sorted(set(reasons))),
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )

def _validate_epoch_against_frame(
    epoch: ResearchGovernanceEpoch,
    *,
    frame: CanonicalScoreFrame,
    now_ms: int,
    scope: Optional[str] = None,
    required_epoch_id: Optional[str] = None,
    required_score_id: Optional[str] = None,
) -> EpochValidation:
    reasons = []
    if not frame.is_fresh(now_ms):
        reasons.append("canonical_score_frame_stale")
    base = ResearchGovernanceEpochService.validate(
        epoch,
        now_ms=now_ms,
        world_state_id=frame.world_state_id,
        world_state_hash=frame.world_state_hash,
        scope=scope,
        required_epoch_id=required_epoch_id,
        required_score_id=required_score_id,
    )
    reasons.extend(base.reasons)
    body = {
        "epoch_id": epoch.epoch_id,
        "frame_id": frame.world_state_id,
        "valid": not reasons,
        "reasons": sorted(set(reasons)),
        "now_ms": int(now_ms),
    }
    return EpochValidation(
        schema="hivenance_epoch_frame_validation_v1",
        validation_id="epf_" + _digest(body).split(":", 1)[1][:24],
        epoch_id=epoch.epoch_id,
        valid=not reasons,
        reasons=tuple(sorted(set(reasons))),
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
        promotion_eligible=False,
    )


ResearchGovernanceEpochService.validate_against_frame = staticmethod(_validate_epoch_against_frame)
