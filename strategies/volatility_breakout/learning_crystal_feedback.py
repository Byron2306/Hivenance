from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from typing import Any, Iterable, Mapping

from .models import FeatureVector, Forecast


AUTHORITY = "RESEARCH_PRIOR_ONLY"
SCHEMA = "hivenance_phase12_learning_crystal_feedback_v1"


def _clip(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def _hash(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _feature_scope(feature: FeatureVector) -> dict[str, Any]:
    values = feature.values if isinstance(feature.values, Mapping) else {}
    regime = values.get("regime_inputs") if isinstance(values.get("regime_inputs"), Mapping) else {}
    return {
        "symbol": str(feature.symbol or "unknown"),
        "symbol_class": str(values.get("symbol_class") or "unknown"),
        "cohort_bucket": str(values.get("cohort_bucket") or "unknown"),
        "regime_hint": str(regime.get("regime_hint") or "unknown"),
        "liquidity_state": str(regime.get("liquidity_state") or "unknown"),
        "participation_state": str(regime.get("participation_state") or "unknown"),
        "feature_version": str(values.get("feature_version") or "phase2.v1"),
    }


def _quality_support(
    *,
    decision: str,
    sample_count: int,
    mean_net_bps: float | None,
    win_rate: float | None,
    min_samples: int,
) -> float:
    if decision not in {
        "exact_reuse_candidate",
        "transformed_symbol_class_candidate",
        "transformed_cohort_candidate",
    }:
        return 0.0
    match_weight = {
        "exact_reuse_candidate": 1.0,
        "transformed_symbol_class_candidate": 0.78,
        "transformed_cohort_candidate": 0.64,
    }[decision]
    sample_strength = _clip(sample_count / max(1.0, float(min_samples)))
    net_strength = _clip((float(mean_net_bps or 0.0) + 2.0) / 20.0)
    win_strength = _clip((float(win_rate or 0.0) - 0.45) / 0.30)
    return round(match_weight * (0.35 * sample_strength + 0.35 * net_strength + 0.30 * win_strength), 6)


def _quality_warning(
    *,
    sample_count: int,
    mean_net_bps: float | None,
    win_rate: float | None,
    min_samples: int,
) -> float:
    if sample_count <= 0:
        return 0.0
    sample_strength = _clip(sample_count / max(1.0, float(min_samples)))
    net_harm = _clip((-float(mean_net_bps or 0.0)) / 30.0) if mean_net_bps is not None else 0.0
    win_harm = _clip((0.50 - float(win_rate or 0.0)) / 0.25) if win_rate is not None else 0.0
    return round(sample_strength * max(net_harm, win_harm), 6)


def compile_learning_feedback(
    feature: FeatureVector,
    *,
    model_ids: Iterable[str],
    horizons: Iterable[int],
    reuse_governor: Any | None,
    max_age_sec: float = 86400.0,
    min_samples_for_reuse: int = 5,
    reusable_crystals: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Compile settled evidence into bounded, point-in-time research priors.

    The compiler may influence hypothesis research behavior but can never create
    execution authority. When an as-of timestamp is supplied through the feature,
    the reuse governor is required to use only evidence settled by that time.
    """
    scope = _feature_scope(feature)
    as_of_ts = float(feature.timestamp_ms or 0) / 1000.0
    priors: dict[str, dict[str, Any]] = {}
    crystal_by_key: dict[str, dict[str, Any]] = {}
    for item in reusable_crystals:
        if not isinstance(item, Mapping):
            continue
        key = str(item.get("applicability_key") or item.get("applicability_hash") or "")
        if key:
            crystal_by_key[key] = dict(item)

    if reuse_governor is None:
        return {
            "schema": SCHEMA,
            "authority": AUTHORITY,
            "as_of_ts": as_of_ts,
            "applicability_scope": scope,
            "priors": {},
            "support_score": 0.0,
            "warning_score": 0.0,
            "positive_priors": 0,
            "negative_priors": 0,
            "execution_eligible": False,
            "promotion_eligible": False,
        }

    for model_id in sorted({str(x) for x in model_ids if str(x)}):
        for horizon in sorted({int(x) for x in horizons if int(x) > 0}):
            decision = reuse_governor.decide(
                model_id=model_id,
                symbol=scope["symbol"],
                horizon_seconds=horizon,
                regime_hint=scope["regime_hint"],
                cohort_bucket=scope["cohort_bucket"],
                symbol_class=scope["symbol_class"],
                as_of_ts=as_of_ts,
            )
            sample_count = int(decision.get("sample_count") or 0)
            mean_net = decision.get("mean_realized_net_bps")
            win_rate = decision.get("win_rate")
            latest = decision.get("latest_settled_ts")
            future_evidence = bool(latest is not None and float(latest) > as_of_ts + 1e-9)
            age_sec = None if latest is None else max(0.0, as_of_ts - float(latest))
            stale = bool(age_sec is not None and age_sec > float(max_age_sec))

            support = 0.0 if stale or future_evidence else _quality_support(
                decision=str(decision.get("decision") or ""),
                sample_count=sample_count,
                mean_net_bps=mean_net,
                win_rate=win_rate,
                min_samples=min_samples_for_reuse,
            )
            warning = 0.0 if future_evidence else _quality_warning(
                sample_count=sample_count,
                mean_net_bps=mean_net,
                win_rate=win_rate,
                min_samples=min_samples_for_reuse,
            )

            if future_evidence:
                lifecycle = "REFUSED_FUTURE_EVIDENCE"
            elif stale:
                lifecycle = "CHALLENGED_STALE"
            elif support > 0 and sample_count >= min_samples_for_reuse:
                lifecycle = "DETERMINISTIC_RESEARCH_REUSE_CANDIDATE"
            elif sample_count >= 3:
                lifecycle = "SCAFFOLDED"
            elif sample_count > 0:
                lifecycle = "ADVISORY"
            else:
                lifecycle = "NO_PRIOR_EVIDENCE"

            applicability = {
                **scope,
                "model_id": model_id,
                "horizon_seconds": horizon,
                "config_hash": decision.get("config_hash"),
            }
            key = f"{model_id}|{horizon}"
            reusable_crystal = crystal_by_key.get(_hash(applicability))
            crystal_expiry = reusable_crystal.get("expires_ts") if reusable_crystal else None
            crystal_fresh = bool(
                reusable_crystal
                and (crystal_expiry is None or float(crystal_expiry) >= as_of_ts)
                and str(reusable_crystal.get("authority") or "").lower() in {"research_prior_only", "research_prior_only".lower()}
            )
            crystal_reused = bool(
                crystal_fresh
                and lifecycle == "DETERMINISTIC_RESEARCH_REUSE_CANDIDATE"
                and str(reusable_crystal.get("lifecycle") or "") == "DETERMINISTIC_RESEARCH_REUSE_CANDIDATE"
            )

            priors[key] = {
                "schema": "hivenance_market_learning_prior_v1",
                "model_id": model_id,
                "horizon_seconds": horizon,
                "decision": decision.get("decision"),
                "reason": decision.get("reason"),
                "sample_count": sample_count,
                "mean_realized_net_bps": mean_net,
                "win_rate": win_rate,
                "latest_settled_ts": latest,
                "age_sec": age_sec,
                "stale": stale,
                "future_evidence_refused": future_evidence,
                "support_score": support,
                "warning_score": warning,
                "lifecycle": lifecycle,
                "applicability_key": _hash(applicability),
                "applicability": applicability,
                "crystal_reused": crystal_reused,
                "crystal_id": reusable_crystal.get("crystal_id") if crystal_reused else None,
                "reuse_mode": "DETERMINISTIC_CRYSTAL_REUSE" if crystal_reused else "EVIDENCE_COMPILED",
                "authority": AUTHORITY,
                "execution_eligible": False,
                "promotion_eligible": False,
            }

    support_score = max([float(x.get("support_score") or 0.0) for x in priors.values()] or [0.0])
    warning_score = max([float(x.get("warning_score") or 0.0) for x in priors.values()] or [0.0])
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "as_of_ts": as_of_ts,
        "applicability_scope": scope,
        "priors": priors,
        "support_score": round(support_score, 6),
        "warning_score": round(warning_score, 6),
        "positive_priors": sum(1 for x in priors.values() if float(x.get("support_score") or 0.0) > 0),
        "negative_priors": sum(1 for x in priors.values() if float(x.get("warning_score") or 0.0) > 0),
        "crystal_reuse_count": sum(1 for x in priors.values() if bool(x.get("crystal_reused"))),
        "execution_eligible": False,
        "promotion_eligible": False,
    }


def attach_learning_feedback(feature: FeatureVector, feedback: Mapping[str, Any]) -> FeatureVector:
    values = dict(feature.values or {})
    values["phase2_learning_feedback"] = dict(feedback)
    return replace(feature, values=values)


def prior_for_forecast(feature: FeatureVector, forecast: Forecast) -> dict[str, Any]:
    values = feature.values if isinstance(feature.values, Mapping) else {}
    root = values.get("phase2_learning_feedback") if isinstance(values.get("phase2_learning_feedback"), Mapping) else {}
    priors = root.get("priors") if isinstance(root.get("priors"), Mapping) else {}
    row = priors.get(f"{forecast.model_id}|{int(forecast.horizon_seconds)}")
    return dict(row) if isinstance(row, Mapping) else {}


def apply_learning_prior_to_forecast(
    forecast: Forecast,
    feature: FeatureVector,
    *,
    negative_veto_threshold: float = 0.60,
    positive_probability_cap: float = 0.08,
    positive_uncertainty_reduction_cap: float = 0.12,
) -> Forecast:
    """Apply bounded learned research prior without fabricating price evidence.

    Positive reuse may increase confidence in an already non-abstaining forecast.
    Negative reuse may veto an otherwise active forecast. Direction and expected
    market move are never created or flipped by memory alone.
    """
    prior = prior_for_forecast(feature, forecast)
    if not prior:
        return forecast

    support = _clip(float(prior.get("support_score") or 0.0))
    warning = _clip(float(prior.get("warning_score") or 0.0))
    inputs = dict(forecast.inputs or {})
    inputs["learning_prior"] = prior

    if not forecast.abstain and warning >= float(negative_veto_threshold):
        reason = "learning_prior_negative_reuse_veto"
        return replace(
            forecast,
            direction="ABSTAIN",
            probability_positive_net=None,
            expected_move_bps=None,
            expected_net_bps=None,
            abstain=True,
            reason=reason,
            reasons=(*forecast.reasons, reason),
            inputs=inputs,
            execution_eligible=False,
        )

    if forecast.abstain or support <= 0:
        return replace(forecast, inputs=inputs, execution_eligible=False)

    probability = forecast.probability_positive_net
    if probability is not None:
        probability = _clip(float(probability) + min(float(positive_probability_cap), support * float(positive_probability_cap)), 0.01, 0.99)

    uncertainty = forecast.uncertainty
    if uncertainty is not None:
        uncertainty = _clip(
            float(uncertainty) - min(float(positive_uncertainty_reduction_cap), support * float(positive_uncertainty_reduction_cap))
        )

    raw_score = forecast.raw_score
    if raw_score is not None:
        raw_score = _clip(float(raw_score) + min(0.08, support * 0.08), 0.0, 1.25)

    return replace(
        forecast,
        probability_positive_net=None if probability is None else round(probability, 6),
        uncertainty=None if uncertainty is None else round(uncertainty, 6),
        raw_score=None if raw_score is None else round(raw_score, 6),
        inputs=inputs,
        execution_eligible=False,
    )


def learning_crystal_rows(
    feature: FeatureVector,
    feedback: Mapping[str, Any],
    *,
    venue: str,
    expiry_sec: float = 86400.0,
) -> list[dict[str, Any]]:
    """Materialize deterministic research-reuse candidates in the crystal registry."""
    rows: list[dict[str, Any]] = []
    as_of_ts = float(feature.timestamp_ms or 0) / 1000.0
    priors = feedback.get("priors") if isinstance(feedback.get("priors"), Mapping) else {}
    for key, prior in sorted(priors.items()):
        if not isinstance(prior, Mapping):
            continue
        lifecycle = str(prior.get("lifecycle") or "")
        if lifecycle not in {
            "ADVISORY",
            "SCAFFOLDED",
            "DETERMINISTIC_RESEARCH_REUSE_CANDIDATE",
            "CHALLENGED_STALE",
        }:
            continue
        applicability_key = str(prior.get("applicability_key") or "")
        if not applicability_key:
            continue
        payload = {
            "schema": "hivenance_market_learning_crystal_v1",
            "model_id": prior.get("model_id"),
            "horizon_seconds": prior.get("horizon_seconds"),
            "symbol": feature.symbol,
            "venue": venue,
            "lifecycle": lifecycle,
            "support_score": prior.get("support_score"),
            "warning_score": prior.get("warning_score"),
            "sample_count": prior.get("sample_count"),
            "mean_realized_net_bps": prior.get("mean_realized_net_bps"),
            "win_rate": prior.get("win_rate"),
            "applicability_key": applicability_key,
            "authority": AUTHORITY,
            "expires_ts": as_of_ts + max(60.0, float(expiry_sec)),
            "execution_eligible": False,
            "promotion_eligible": False,
        }
        crystal_id = _hash({"family": "learning_reuse", "applicability_key": applicability_key})
        rows.append({
            "crystal_id": crystal_id,
            "created_ts": as_of_ts,
            "updated_ts": as_of_ts,
            "crystal_family": "learning_reuse",
            "artifact_class": "market_learning_crystal",
            "authority": "research_prior_only",
            "verification_state": "reusable_candidate" if lifecycle == "DETERMINISTIC_RESEARCH_REUSE_CANDIDATE" else "candidate",
            "phase_scope": 2,
            "scope_key": str(key),
            "symbol": feature.symbol,
            "venue": venue,
            "regime_hint": ((feature.values or {}).get("regime_inputs") or {}).get("regime_hint") if isinstance(feature.values, Mapping) else None,
            "hypothesis": None,
            "world_state_id": None,
            "applicability_hash": applicability_key,
            "evidence_strength": max(float(prior.get("support_score") or 0.0), float(prior.get("warning_score") or 0.0)),
            "drift_status": "stale_challenged" if lifecycle == "CHALLENGED_STALE" else "fresh",
            "expires_ts": as_of_ts + max(60.0, float(expiry_sec)),
            "payload": {"crystal_id": crystal_id, **payload},
        })
    return rows
