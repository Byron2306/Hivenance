from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


VALID_MODEL_AUTHORITY_MODES = ("ACTIVE", "ADVISORY", "SHADOW", "QUARANTINED")


@dataclass(frozen=True)
class ModelAuthorityDecision:
    model_id: str
    horizon_seconds: int | None
    regime: str
    cohort_bucket: str
    mode: str | None
    matched: bool
    matched_rule_index: int | None
    specificity: int
    source: str
    reason: str

    @property
    def influence_enabled(self) -> bool:
        return self.mode == "ACTIVE"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["influence_enabled"] = self.influence_enabled
        payload["authority"] = "RESEARCH_MODEL_AUTHORITY_ONLY"
        payload["execution_eligible"] = False
        payload["promotion_eligible"] = False
        return payload


def _norm_mode(value: Any) -> str | None:
    mode = str(value or "").strip().upper()
    return mode if mode in VALID_MODEL_AUTHORITY_MODES else None


def _norm_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def resolve_model_authority(
    *,
    model_id: str,
    horizon_seconds: int | None,
    regime: str,
    cohort_bucket: str,
    rules: Iterable[Mapping[str, Any]] | None,
) -> ModelAuthorityDecision:
    """Resolve the most-specific research authority rule for one model/world.

    Rules are intentionally declarative and do not infer authority from historical
    performance. A rule may constrain model_id plus any of horizon_seconds,
    regime, or cohort_bucket. Highest specificity wins; list order breaks ties.
    Invalid modes never grant influence.
    """

    model_id = str(model_id or "")
    regime = str(regime or "unknown")
    cohort_bucket = str(cohort_bucket or "unknown")
    horizon = None if horizon_seconds is None else int(horizon_seconds)

    best: tuple[int, int, Mapping[str, Any], str] | None = None
    for index, raw in enumerate(tuple(rules or ())):
        if not isinstance(raw, Mapping):
            continue
        if str(raw.get("model_id") or "") != model_id:
            continue
        mode = _norm_mode(raw.get("mode"))
        if mode is None:
            continue

        specificity = 1
        rule_horizon = _norm_optional_int(raw.get("horizon_seconds"))
        if raw.get("horizon_seconds") not in (None, ""):
            if horizon is None or rule_horizon != horizon:
                continue
            specificity += 1

        rule_regime = str(raw.get("regime") or "").strip()
        if rule_regime:
            if rule_regime != regime:
                continue
            specificity += 1

        rule_cohort = str(raw.get("cohort_bucket") or "").strip()
        if rule_cohort:
            if rule_cohort != cohort_bucket:
                continue
            specificity += 1

        candidate = (specificity, -index, raw, mode)
        if best is None or candidate[:2] > best[:2]:
            best = candidate

    if best is None:
        return ModelAuthorityDecision(
            model_id=model_id,
            horizon_seconds=horizon,
            regime=regime,
            cohort_bucket=cohort_bucket,
            mode=None,
            matched=False,
            matched_rule_index=None,
            specificity=0,
            source="coarse_organ_authority_fallback",
            reason="no_granular_rule_matched",
        )

    specificity, neg_index, raw, mode = best
    index = -neg_index
    return ModelAuthorityDecision(
        model_id=model_id,
        horizon_seconds=horizon,
        regime=regime,
        cohort_bucket=cohort_bucket,
        mode=mode,
        matched=True,
        matched_rule_index=index,
        specificity=specificity,
        source=str(raw.get("source") or "configured_model_authority_rule"),
        reason=str(raw.get("reason") or "granular_model_authority_rule_matched"),
    )


def model_authority_manifest(rules: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(tuple(rules or ())):
        if not isinstance(raw, Mapping):
            continue
        mode = _norm_mode(raw.get("mode"))
        if mode is None or not str(raw.get("model_id") or ""):
            continue
        normalized.append(
            {
                "rule_index": index,
                "model_id": str(raw.get("model_id")),
                "horizon_seconds": _norm_optional_int(raw.get("horizon_seconds")),
                "regime": str(raw.get("regime") or "") or None,
                "cohort_bucket": str(raw.get("cohort_bucket") or "") or None,
                "mode": mode,
                "source": str(raw.get("source") or "configured_model_authority_rule"),
                "reason": str(raw.get("reason") or "granular_model_authority_rule"),
            }
        )
    return {
        "schema": "hivenance_model_horizon_regime_authority_v1",
        "rules": normalized,
        "authority": "RESEARCH_MODEL_AUTHORITY_ONLY",
        "execution_eligible": False,
        "promotion_eligible": False,
    }
