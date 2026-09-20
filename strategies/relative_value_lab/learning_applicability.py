"""Exact applicability contract for HiveNance learning and crystal memory.

Memory may be stored broadly. Influence is narrower.

A learning/crystal item can affect a live research conclusion only after its
declared applicability is compared with the live research context. Missing or
mismatched scope never silently becomes a match.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY


def _digest(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


APPLICABILITY_STATES = {
    "SUPPORTED",
    "CONTRADICTED",
    "REGIME_DEPENDENT",
    "DECAYED",
    "SUPERSEDED",
    "INCOMPLETE",
    "NOT_APPLICABLE",
}


@dataclass(frozen=True)
class LearningApplicability:
    model_id: str | None
    symbol: str | None
    horizon_seconds: int | None
    forecast_id: str | None
    hypothesis_family: str | None
    direction: str | None
    regime: str | None

    world_state_ids: tuple[str, ...]
    evidence_roots: tuple[str, ...]

    observed_at_ms: int | None
    settled_at_ms: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LiveResearchContext:
    model_id: str
    symbol: str
    horizon_seconds: int
    forecast_id: str | None
    hypothesis_family: str | None
    direction: str
    regime: str | None

    world_state_id: str
    evidence_roots: tuple[str, ...]

    asof_ms: int

    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ApplicabilityDecision:
    schema: str
    decision_id: str

    learning_id: str
    applicable: bool
    state: str

    matched_fields: tuple[str, ...]
    mismatched_fields: tuple[str, ...]
    missing_fields: tuple[str, ...]

    lineage_overlap_count: int
    age_ms: int | None

    reasons: tuple[str, ...]

    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if self.state not in APPLICABILITY_STATES:
            raise ValueError(
                "unknown_learning_applicability_state"
            )

        if self.execution_eligible:
            raise ValueError(
                "learning_applicability_execution_forbidden"
            )

        if self.promotion_eligible:
            raise ValueError(
                "learning_applicability_promotion_forbidden"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _norm(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()

    return text.upper() if text else None


def applicability_from_receipt(
    receipt: Mapping[str, Any],
) -> LearningApplicability:
    """Extract declared applicability without inventing missing scope."""

    raw = receipt.get("applicability")

    scope = raw if isinstance(raw, Mapping) else receipt

    roots = scope.get(
        "evidence_roots",
        receipt.get("evidence_roots", ()),
    )

    if not roots:
        roots = tuple(
            (
                "sha256:" + str(row["sha256"])
                if not str(row["sha256"]).startswith(
                    "sha256:"
                )
                else str(row["sha256"])
            )
            for row in receipt.get(
                "source_artifacts",
                (),
            )
            if isinstance(row, Mapping)
            and row.get("sha256")
        )

    world_ids = scope.get(
        "world_state_ids",
        (),
    )

    if not world_ids and scope.get("world_state_id"):
        world_ids = (
            str(scope["world_state_id"]),
        )

    forecast_id = scope.get("forecast_id")

    hypothesis_family = (
        scope.get("hypothesis_family")
        or scope.get("hypothesis")
        or receipt.get("hypothesis_family")
    )

    return LearningApplicability(
        model_id=(
            None
            if scope.get("model_id") is None
            else str(scope.get("model_id"))
        ),
        symbol=(
            None
            if scope.get("symbol") is None
            else str(scope.get("symbol"))
        ),
        horizon_seconds=(
            None
            if scope.get("horizon_seconds") is None
            else int(scope.get("horizon_seconds"))
        ),
        forecast_id=(
            None
            if forecast_id is None
            else str(forecast_id)
        ),
        hypothesis_family=(
            None
            if hypothesis_family is None
            else str(hypothesis_family)
        ),
        direction=(
            None
            if scope.get("direction") is None
            else str(scope.get("direction"))
        ),
        regime=(
            None
            if scope.get("regime") is None
            else str(scope.get("regime"))
        ),
        world_state_ids=tuple(
            sorted(
                set(map(str, world_ids or ()))
            )
        ),
        evidence_roots=tuple(
            sorted(
                set(map(str, roots or ()))
            )
        ),
        observed_at_ms=(
            None
            if scope.get("observed_at_ms") is None
            else int(scope.get("observed_at_ms"))
        ),
        settled_at_ms=(
            None
            if scope.get("settled_at_ms") is None
            else int(scope.get("settled_at_ms"))
        ),
    )


def evaluate_learning_applicability(
    *,
    learning_id: str,
    applicability: LearningApplicability,
    context: LiveResearchContext,
    max_age_ms: int | None = None,
    superseded: bool = False,
    declared_state: str | None = None,
) -> ApplicabilityDecision:
    """Fail closed on scope mismatch or missing required applicability."""

    matched: list[str] = []
    mismatched: list[str] = []
    missing: list[str] = []
    reasons: list[str] = []

    def exact(
        name: str,
        memory_value: Any,
        live_value: Any,
        *,
        normalize: bool = False,
    ) -> None:
        if memory_value is None:
            missing.append(name)
            return

        left = (
            _norm(memory_value)
            if normalize
            else memory_value
        )

        right = (
            _norm(live_value)
            if normalize
            else live_value
        )

        if left == right:
            matched.append(name)
        else:
            mismatched.append(name)

    exact(
        "model_id",
        applicability.model_id,
        context.model_id,
    )

    exact(
        "symbol",
        applicability.symbol,
        context.symbol,
        normalize=True,
    )

    exact(
        "horizon_seconds",
        applicability.horizon_seconds,
        context.horizon_seconds,
    )

    exact(
        "direction",
        applicability.direction,
        context.direction,
        normalize=True,
    )

    # A receipt can be bound either to one forecast instance or to a reusable
    # hypothesis family. At least one must be declared.
    hypothesis_bound = False

    if applicability.forecast_id is not None:
        if (
            context.forecast_id is not None
            and applicability.forecast_id
            == context.forecast_id
        ):
            matched.append("forecast_id")
            hypothesis_bound = True
        else:
            mismatched.append("forecast_id")

    elif applicability.hypothesis_family is not None:
        if (
            context.hypothesis_family is not None
            and _norm(applicability.hypothesis_family)
            == _norm(context.hypothesis_family)
        ):
            matched.append("hypothesis_family")
            hypothesis_bound = True
        else:
            mismatched.append(
                "hypothesis_family"
            )

    else:
        missing.append(
            "forecast_id_or_hypothesis_family"
        )

    # Regime is required where the learning declared itself regime-specific.
    if applicability.regime is not None:
        if context.regime is None:
            mismatched.append("regime")
        elif (
            _norm(applicability.regime)
            == _norm(context.regime)
        ):
            matched.append("regime")
        else:
            mismatched.append("regime")

    # Memory cannot be settled in the future relative to the live decision.
    if applicability.settled_at_ms is None:
        missing.append("settled_at_ms")
        age_ms = None
    else:
        age_ms = int(
            context.asof_ms
            - applicability.settled_at_ms
        )

        if age_ms < 0:
            mismatched.append(
                "settled_at_ms_future"
            )
        else:
            matched.append("settled_at_ms")

    if applicability.observed_at_ms is None:
        missing.append("observed_at_ms")
    elif (
        applicability.settled_at_ms is not None
        and applicability.observed_at_ms
        > applicability.settled_at_ms
    ):
        mismatched.append(
            "observed_after_settlement"
        )
    else:
        matched.append("observed_at_ms")

    live_roots = set(context.evidence_roots)
    memory_roots = set(
        applicability.evidence_roots
    )

    lineage_overlap = len(
        live_roots & memory_roots
    )

    if applicability.world_state_ids:
        # Historical learning may apply across worlds, so an exact world id is
        # not mandatory. The binding must nevertheless be explicit.
        matched.append("world_state_lineage")
    elif memory_roots:
        matched.append("evidence_lineage")
    else:
        missing.append(
            "world_state_or_evidence_lineage"
        )

    if superseded:
        state = "SUPERSEDED"
        applicable_now = False
        reasons.append(
            "learning_superseded_by_newer_memory"
        )

    elif (
        max_age_ms is not None
        and age_ms is not None
        and age_ms > int(max_age_ms)
    ):
        state = "DECAYED"
        applicable_now = False
        reasons.append(
            "learning_exceeded_max_age"
        )

    elif mismatched:
        state = "NOT_APPLICABLE"
        applicable_now = False

        reasons.extend(
            f"mismatch:{field}"
            for field in sorted(
                set(mismatched)
            )
        )

    elif missing:
        state = "INCOMPLETE"
        applicable_now = False

        reasons.extend(
            f"missing:{field}"
            for field in sorted(
                set(missing)
            )
        )

    else:
        raw_state = _norm(
            declared_state or "SUPPORTED"
        )

        if raw_state in {
            "CONTRADICTED",
            "REGIME_DEPENDENT",
        }:
            state = raw_state
        else:
            state = "SUPPORTED"

        applicable_now = bool(
            hypothesis_bound
            and state
            in {
                "SUPPORTED",
                "CONTRADICTED",
                "REGIME_DEPENDENT",
            }
        )

    body = {
        "learning_id": learning_id,
        "applicable": applicable_now,
        "state": state,
        "matched": sorted(set(matched)),
        "mismatched": sorted(
            set(mismatched)
        ),
        "missing": sorted(set(missing)),
        "lineage_overlap_count": (
            lineage_overlap
        ),
        "age_ms": age_ms,
        "reasons": sorted(set(reasons)),
    }

    return ApplicabilityDecision(
        schema=(
            "hivenance_learning_applicability_decision_v1"
        ),
        decision_id=(
            "lapp_"
            + _digest(body).split(":", 1)[1][:24]
        ),
        learning_id=str(learning_id),
        applicable=applicable_now,
        state=state,
        matched_fields=tuple(
            sorted(set(matched))
        ),
        mismatched_fields=tuple(
            sorted(set(mismatched))
        ),
        missing_fields=tuple(
            sorted(set(missing))
        ),
        lineage_overlap_count=(
            lineage_overlap
        ),
        age_ms=age_ms,
        reasons=tuple(
            sorted(set(reasons))
        ),
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
        promotion_eligible=False,
    )
