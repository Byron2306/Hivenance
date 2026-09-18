from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from dataclasses import asdict, fields
from datetime import datetime, timezone
from typing import Any, Optional

from .hypothesis_competition import HypothesisCompetition
from .models import FeatureVector, HypothesisRunSummary
from .research_reuse import ResearchReuseGovernor
from .walk_forward_calibration import WalkForwardForecastCalibrator


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _prefix_upper_bound(prefix: str) -> str:
    if not prefix:
        return ""
    chars = list(prefix)
    chars[-1] = chr(ord(chars[-1]) + 1)
    return "".join(chars)


def _feature_from_payload(payload: dict[str, Any]) -> Optional[FeatureVector]:
    if not isinstance(payload, dict):
        return None
    allowed = {item.name for item in fields(FeatureVector)}
    values = {key: value for key, value in payload.items() if key in allowed}
    required = {
        "symbol", "timestamp_ms", "price", "realized_volatility_fast",
        "realized_volatility_baseline", "volatility_expansion", "volume_zscore",
        "trade_count_zscore", "order_flow_imbalance", "book_imbalance",
        "spread_bps", "depth_usd_25bps", "quote_volume_24h", "return_5",
        "freshness_sec", "continuity_ratio", "data_quality",
    }
    if not required.issubset(values):
        return None
    if not isinstance(values.get("values"), dict):
        values["values"] = {}
    return FeatureVector(**values)


def _feature_with_candidate_context(feature: FeatureVector, candidate_values: dict[str, Any]) -> FeatureVector:
    merged_values = dict(feature.values or {})
    if isinstance(candidate_values, dict):
        for key in (
            "cohort_bucket",
            "symbol_class",
            "tradable_opportunity_score",
            "research_richness_score",
            "opportunity_components",
            "phase2_profitability_frontier",
            "phase2_regime_suppression",
            "cex_market_oracle",
        ):
            if key in candidate_values and key not in merged_values:
                merged_values[key] = candidate_values.get(key)
    return FeatureVector(**{**asdict(feature), "values": merged_values})


def _feature_with_crystal_context(
    feature: FeatureVector,
    *,
    thesis_crystals: list[dict[str, Any]],
    negative_crystals: list[dict[str, Any]],
) -> FeatureVector:
    values = dict(feature.values or {})
    regime_inputs = values.get("regime_inputs") if isinstance(values.get("regime_inputs"), dict) else {}
    regime_hint = str(regime_inputs.get("regime_hint") or "unknown")
    symbol_class = str(values.get("symbol_class") or "unknown")
    symbol = str(feature.symbol or "unknown")
    positive_recent = [
        crystal for crystal in thesis_crystals
        if str(crystal.get("regime_hint") or "unknown") == regime_hint
        and str(crystal.get("symbol") or "") in {"", "unknown", symbol}
    ]
    negative_recent = [
        crystal for crystal in negative_crystals
        if str(crystal.get("regime_hint") or "unknown") == regime_hint
        and str(crystal.get("symbol_class") or "unknown") in {"unknown", "", symbol_class}
    ]
    values["phase2_crystal_memory"] = {
        "positive_recent": len(positive_recent),
        "negative_recent": len(negative_recent),
        "support_score": round(sum(float(item.get("evidence_strength") or 0.0) for item in positive_recent), 6),
        "warning_score": round(sum(float(item.get("evidence_strength") or 0.0) for item in negative_recent), 6),
        "regime_hint": regime_hint,
        "symbol_class": symbol_class,
        "symbol": symbol,
    }
    return FeatureVector(**{**asdict(feature), "values": values})


class CommonsPhase2Governor:
    """Issue and verify research-only Commons challenger work for Phase 2."""

    def __init__(self, cfg: Any, data_store: Any) -> None:
        self.cfg = cfg
        self.data_store = data_store
        self.enabled = bool(getattr(cfg, "phase2_commons_inference_enabled", True))
        self.ticket_ttl_sec = max(60, int(getattr(cfg, "phase2_commons_ticket_ttl_sec", 600) or 600))
        self.max_tickets_per_run = max(1, int(getattr(cfg, "phase2_commons_max_tickets_per_run", 12) or 12))
        self.max_packet_age_sec = max(60, int(getattr(cfg, "phase2_commons_max_packet_age_sec", 3600) or 3600))
        quarantined = getattr(cfg, "phase2_federation_quarantined_models", {}) or {}
        self.quarantined_models = {
            str(model_id).strip()
            for model_id in (quarantined.keys() if isinstance(quarantined, dict) else quarantined)
            if str(model_id).strip()
        }

    def _quarantined_source_model(self, inference: dict[str, Any]) -> str | None:
        summary = inference.get("result_summary") if isinstance(inference.get("result_summary"), dict) else {}
        wrapped_model_id = str(summary.get("model_id") or "")
        selected_model_id = wrapped_model_id.split("::", 1)[-1]
        if selected_model_id in self.quarantined_models:
            return selected_model_id
        return None

    @staticmethod
    def _signature_for(payload: dict[str, Any]) -> str:
        body = {k: v for k, v in payload.items() if k not in {"signature", "payload"}}
        return _canonical_hash(body)

    def issue_ticket(
        self,
        *,
        observation_run_id: str,
        venue: str,
        candidate: dict[str, Any],
        feature: FeatureVector,
        horizon_seconds: int,
        created_ts: float,
    ) -> dict[str, Any]:
        values = candidate.get("values") if isinstance(candidate.get("values"), dict) else {}
        world_state = values.get("market_world_state_crystal") if isinstance(values.get("market_world_state_crystal"), dict) else {}
        payload = {
            "schema": "hivenance_commons_pool_work_ticket_v1",
            "ticket_id": _canonical_hash({
                "type": "phase2_ticket",
                "observation_run_id": observation_run_id,
                "symbol": feature.symbol,
                "horizon_seconds": int(horizon_seconds),
                "created_ts": float(created_ts),
            }),
            "pool_type": "inference_pool",
            "task_class": "phase2_challenger_forecast",
            "phase_scope": 2,
            "created_ts": float(created_ts),
            "expires_ts": float(created_ts + self.ticket_ttl_sec),
            "lease_count": 1,
            "authority": "research_work_only",
            "world_state_digest": world_state.get("world_state_id") or _canonical_hash(world_state),
            "input_root": _canonical_hash({
                "symbol": feature.symbol,
                "timestamp_ms": feature.timestamp_ms,
                "price": feature.price,
                "horizon_seconds": int(horizon_seconds),
            }),
            "feature_schema_digest": _canonical_hash(asdict(feature)),
            "code_digest": _canonical_hash({
                "component": "hypothesis_swarm",
                "competition_models": list(getattr(self.cfg, "phase2_federation_models", []) or []),
                "quarantined_models": getattr(self.cfg, "phase2_federation_quarantined_models", {}) or {},
            }),
            "config_digest": _canonical_hash({
                "phase2_horizons_seconds": list(getattr(self.cfg, "phase2_horizons_seconds", []) or []),
                "phase2_minimum_edge_multiple": getattr(self.cfg, "phase2_minimum_edge_multiple", None),
                "walk_forward_calibration": {
                    "enabled": getattr(self.cfg, "phase2_walk_forward_calibration_enabled", True),
                    "stress_cost_multiple": getattr(self.cfg, "phase2_calibration_stress_cost_multiple", 1.5),
                    "minimum_probability_lower_bound": getattr(
                        self.cfg, "phase2_calibration_min_probability_lower_bound", 0.50
                    ),
                },
            }),
            "required_engine_profiles": ["python_cpu", "federated_forecaster"],
            "required_verifiers": ["manifest", "policy", "schema"],
            "privacy_class": "public_market_research",
            "challenge_nonce": _canonical_hash({
                "symbol": feature.symbol,
                "timestamp_ms": feature.timestamp_ms,
                "created_ts": float(created_ts),
            })[:24],
            "target_object": {
                "phase2_observation_id": observation_run_id,
                "symbol": feature.symbol,
                "venue": venue,
                "horizon_seconds": int(horizon_seconds),
                "regime_hint": (feature.values.get("regime_inputs") or {}).get("regime_hint") if isinstance(feature.values, dict) else None,
            },
            # Public-market research features travel with the ticket so an
            # independent worker can reproduce the bound digest exactly.
            "input_payload": {
                "feature_vector": asdict(feature),
            },
            "status": "ISSUED",
        }
        payload["signature"] = self._signature_for(payload)
        return payload

    def issue_tickets(
        self,
        *,
        observation_run_id: str,
        venue: str,
        candidates: list[tuple[dict[str, Any], FeatureVector]],
        horizons: tuple[int, ...],
        created_ts: float,
    ) -> list[dict[str, Any]]:
        if not self.enabled or self.data_store is None:
            return []
        issued: list[dict[str, Any]] = []
        for candidate, feature in candidates[: self.max_tickets_per_run]:
            horizon = int(horizons[0] if horizons else 900)
            ticket = self.issue_ticket(
                observation_run_id=observation_run_id,
                venue=venue,
                candidate=candidate,
                feature=feature,
                horizon_seconds=horizon,
                created_ts=created_ts,
            )
            if self.data_store.persist_commons_pool_work_ticket(ticket):
                issued.append(ticket)
        return issued

    def verify_adopted_packet(self, packet: dict[str, Any], now_ts: float) -> tuple[bool, list[str]]:
        adoption = packet.get("adoption_receipt") if isinstance(packet.get("adoption_receipt"), dict) else {}
        inference = packet.get("inference_receipt") if isinstance(packet.get("inference_receipt"), dict) else {}
        reasons: list[str] = []
        if adoption.get("authority_ceiling") != "proposal_only":
            reasons.append("authority_ceiling_not_proposal_only")
        if adoption.get("local_reproduction_verdict") != "PASS":
            reasons.append("local_reproduction_not_passed")
        if str(adoption.get("adoption_decision") or "") not in {"ACCEPTED_PROPOSAL_WEIGHT_ONLY", "ACCEPTED_CHALLENGER_FORECAST"}:
            reasons.append("adoption_decision_not_accepted")
        if str(inference.get("task_class") or "") != "phase2_challenger_forecast":
            reasons.append("wrong_task_class")
        if int(inference.get("phase_scope") or 0) != 2:
            reasons.append("wrong_phase_scope")
        quarantined_source = self._quarantined_source_model(inference)
        if quarantined_source:
            reasons.append(f"source_model_quarantined:{quarantined_source}")
        created_ts = float(inference.get("created_ts") or 0.0)
        if created_ts <= 0 or (now_ts - created_ts) > float(self.max_packet_age_sec):
            reasons.append("packet_too_old")
        ticket_id = inference.get("ticket_id")
        ticket = None
        if self.data_store is not None and hasattr(self.data_store, "get_commons_pool_work_ticket"):
            ticket = self.data_store.get_commons_pool_work_ticket(str(ticket_id or ""))
        elif self.data_store is not None:
            tickets = self.data_store.get_commons_pool_work_tickets(limit=250)
            ticket = next((row for row in tickets if row.get("ticket_id") == ticket_id), None)
        if not ticket:
            reasons.append("ticket_not_found")
        else:
            if float(ticket.get("expires_ts") or 0.0) < now_ts:
                reasons.append("ticket_expired")
            if str(ticket.get("challenge_nonce") or "") != str(inference.get("challenge_nonce") or ""):
                reasons.append("challenge_nonce_mismatch")
            if str(ticket.get("input_root") or "") != str(inference.get("input_root") or ""):
                reasons.append("input_root_mismatch")
        signature = str(inference.get("signature") or "")
        expected_signature = self._signature_for(inference)
        if signature and signature != expected_signature:
            reasons.append("signature_mismatch")
        if not signature:
            reasons.append("signature_missing")
        return (not reasons, reasons)


def _commons_forecast_row(
    *,
    run_id: str,
    observation_run_id: str,
    venue: str,
    packet: dict[str, Any],
) -> Optional[dict[str, Any]]:
    adoption = packet.get("adoption_receipt") if isinstance(packet.get("adoption_receipt"), dict) else {}
    inference = packet.get("inference_receipt") if isinstance(packet.get("inference_receipt"), dict) else {}
    summary = inference.get("result_summary") if isinstance(inference.get("result_summary"), dict) else {}
    target = inference.get("target_object") if isinstance(inference.get("target_object"), dict) else {}
    if not summary:
        return None
    symbol = str(summary.get("symbol") or target.get("symbol") or "")
    model_id = str(summary.get("model_id") or "commons_remote_challenger")
    horizon_seconds = int(summary.get("horizon_seconds") or target.get("horizon_seconds") or 0)
    direction = str(summary.get("direction") or "ABSTAIN").upper()
    if not symbol or horizon_seconds <= 0:
        return None
    created_ts = float(inference.get("created_ts") or time.time())
    timestamp_ms = int(created_ts * 1000)
    forecast_id = hashlib.sha256(
        f"{run_id}:commons:{inference.get('receipt_id')}:{model_id}:{symbol}:{horizon_seconds}".encode("utf-8")
    ).hexdigest()
    expected_cost_bps = summary.get("expected_cost_bps")
    expected_move_bps = summary.get("expected_move_bps")
    expected_net_bps = summary.get("expected_net_bps")
    row = {
        "forecast_id": forecast_id,
        "run_id": run_id,
        "observation_run_id": observation_run_id,
        "venue": str(summary.get("venue") or venue).lower(),
        "symbol": symbol,
        "model_id": model_id,
        "hypothesis": str(summary.get("hypothesis") or "commons_remote_challenger"),
        "horizon_seconds": horizon_seconds,
        "direction": direction,
        "entry_price": summary.get("entry_price"),
        "timestamp_ms": timestamp_ms,
        "target_timestamp_ms": int(timestamp_ms + (horizon_seconds * 1000)),
        "probability_positive_net": summary.get("probability_positive_net"),
        "expected_move_bps": expected_move_bps,
        "expected_cost_bps": expected_cost_bps,
        "expected_net_bps": expected_net_bps,
        "abstain": bool(direction == "ABSTAIN"),
        "reason": str(summary.get("reason") or "commons_inference_pool_adopted"),
        "raw_score": summary.get("raw_score"),
        "uncertainty": summary.get("uncertainty"),
        "calibration_state": str(summary.get("calibration_state") or "REMOTE_UNVERIFIED_UNTIL_LOCAL_ADOPTION"),
        "feature_version": str(summary.get("feature_version") or "commons_pool.v1"),
        "reasons": tuple(summary.get("reasons") or ()),
        "inputs": {
            **(summary.get("inputs") if isinstance(summary.get("inputs"), dict) else {}),
            "commons_pool": {
                "source_receipt_id": inference.get("receipt_id"),
                "adoption_receipt_id": adoption.get("receipt_id"),
                "authority_ceiling": adoption.get("authority_ceiling"),
                "task_class": inference.get("task_class"),
                "worker_id": inference.get("worker_id"),
                "pool_type": inference.get("pool_type"),
            },
        },
        "execution_eligible": False,
        "order_intent": None,
        "research_route": "commons_inference_pool",
        "research_route_priority": 3,
        "reuse_context": {
            "decision": "commons_adopted_challenger",
            "reason": "local_adoption_receipt_passed",
            "source_receipt_id": inference.get("receipt_id"),
            "adoption_receipt_id": adoption.get("receipt_id"),
        },
        "commons_source": {
            "inference_receipt_id": inference.get("receipt_id"),
            "adoption_receipt_id": adoption.get("receipt_id"),
            "worker_id": inference.get("worker_id"),
            "authority_ceiling": adoption.get("authority_ceiling"),
        },
    }
    return row


def _phase2_rung_row(row: dict[str, Any], *, run_id: str, created_ts: float) -> dict[str, Any]:
    inputs = row.get("inputs") if isinstance(row.get("inputs"), dict) else {}
    regime_inputs = inputs.get("regime_inputs") if isinstance(inputs.get("regime_inputs"), dict) else {}
    commons = inputs.get("commons_pool") if isinstance(inputs.get("commons_pool"), dict) else {}
    selected_rung = str(row.get("research_route") or "full_competition")
    candidate_rungs = [
        "abstain",
        "full_competition",
        "cohort_transform",
        "symbol_class_transform",
        "exact_reuse",
        "commons_inference_pool",
    ]
    authority_ceiling = str(commons.get("authority_ceiling") or "proposal_only")
    return {
        "rung_id": _canonical_hash({
            "phase_scope": 2,
            "run_id": run_id,
            "forecast_id": row.get("forecast_id"),
            "selected_rung": selected_rung,
        }),
        "created_ts": float(created_ts),
        "phase_scope": 2,
        "run_id": run_id,
        "forecast_id": row.get("forecast_id"),
        "simulation_id": None,
        "symbol": row.get("symbol"),
        "venue": row.get("venue"),
        "model_id": row.get("model_id"),
        "hypothesis": row.get("hypothesis"),
        "regime_hint": regime_inputs.get("regime_hint") or inputs.get("regime_hint"),
        "symbol_class": inputs.get("symbol_class"),
        "cohort_bucket": inputs.get("cohort_bucket"),
        "selected_rung": selected_rung,
        "candidate_rungs": candidate_rungs,
        "selected_priority": row.get("research_route_priority"),
        "expected_net_bps": row.get("expected_net_bps"),
        "probability_positive_net": row.get("probability_positive_net"),
        "cost_bps": row.get("expected_cost_bps"),
        "authority_ceiling": authority_ceiling,
        "outcome_status": "ABSTAIN" if row.get("abstain") else "PROPOSED",
        "outcome_net_bps": None,
    }


def _phase2_thesis_crystal(row: dict[str, Any], *, created_ts: float) -> dict[str, Any]:
    inputs = row.get("inputs") if isinstance(row.get("inputs"), dict) else {}
    regime_inputs = inputs.get("regime_inputs") if isinstance(inputs.get("regime_inputs"), dict) else {}
    regime_hint = str(regime_inputs.get("regime_hint") or inputs.get("regime_hint") or "unknown")
    symbol_class = str(inputs.get("symbol_class") or "unknown")
    cohort_bucket = str(inputs.get("cohort_bucket") or "unknown")
    hypothesis = str(row.get("hypothesis") or "unknown")
    model_id = str(row.get("model_id") or "unknown")
    horizon_seconds = int(row.get("horizon_seconds") or 0)
    scope_key = f"{hypothesis}|{regime_hint}|{symbol_class}|{cohort_bucket}|{horizon_seconds}|{row.get('venue')}"
    payload = {
        "schema": "phase2_thesis_capability_crystal_v1",
        "artifact_class": "thesis_capability_crystal",
        "authority": "proposal_only",
        "verification_state": "candidate",
        "symbol": row.get("symbol"),
        "venue": row.get("venue"),
        "hypothesis": hypothesis,
        "model_id": model_id,
        "regime_hint": regime_hint,
        "symbol_class": symbol_class,
        "cohort_bucket": cohort_bucket,
        "horizon_seconds": horizon_seconds,
        "forecast_id": row.get("forecast_id"),
        "expected_net_bps": row.get("expected_net_bps"),
        "probability_positive_net": row.get("probability_positive_net"),
        "abstain": bool(row.get("abstain")),
        "research_route": row.get("research_route"),
        "scope_key": scope_key,
    }
    crystal_id = _canonical_hash(payload)
    return {
        "crystal_id": crystal_id,
        "created_ts": float(created_ts),
        "updated_ts": float(created_ts),
        "crystal_family": "thesis_capability",
        "artifact_class": "thesis_capability_crystal",
        "authority": "proposal_only",
        "verification_state": "candidate",
        "phase_scope": 2,
        "scope_key": scope_key,
        "symbol": row.get("symbol"),
        "venue": row.get("venue"),
        "regime_hint": regime_hint,
        "hypothesis": hypothesis,
        "world_state_id": ((inputs.get("market_world_state_crystal") or {}).get("world_state_id") if isinstance(inputs.get("market_world_state_crystal"), dict) else None),
        "applicability_hash": _canonical_hash({
            "hypothesis": hypothesis,
            "regime_hint": regime_hint,
            "symbol_class": symbol_class,
            "cohort_bucket": cohort_bucket,
            "horizon_seconds": horizon_seconds,
            "model_id": model_id,
            "research_route": row.get("research_route"),
        }),
        "evidence_strength": row.get("probability_positive_net"),
        "drift_status": "unsettled_candidate",
        "expires_ts": float((int(row.get("target_timestamp_ms") or 0) / 1000.0) if row.get("target_timestamp_ms") else created_ts + 3600.0),
        "payload": {"crystal_id": crystal_id, **payload},
    }


class HypothesisSwarmAgent:
    """Phase-2 research runner.

    It drives the Phase-1 observer, evaluates two frozen primary hypotheses and
    four baselines, persists forecasts, and remains physically disconnected from
    every execution interface.
    """

    def __init__(self, cfg: Any, observer: Any, coordinator: Optional[Any] = None) -> None:
        self.cfg = cfg
        self.observer = observer
        self.coordinator = coordinator
        self.enabled = bool(getattr(cfg, "phase2_hypotheses_enabled", True))
        raw_interval = int(
            getattr(cfg, "phase2_interval_sec", getattr(cfg, "phase1_observation_interval_sec", 120))
            or 120
        )
        min_interval = max(1, int(getattr(cfg, "phase2_min_interval_sec", 30) or 30))
        self.interval_sec = max(min_interval, raw_interval)
        raw_horizons = getattr(cfg, "phase2_horizons_seconds", [300, 900, 3600]) or [300, 900, 3600]
        min_horizon = max(1, int(getattr(cfg, "phase2_min_horizon_seconds", 60) or 60))
        self.horizons = tuple(sorted({max(min_horizon, int(value)) for value in raw_horizons}))
        raw_medium_horizons = getattr(cfg, "medium_trend_horizons_seconds", [86400]) or [86400]
        self.medium_trend_horizons = tuple(sorted({max(3600, int(value)) for value in raw_medium_horizons}))
        raw_derivatives_trend_horizons = getattr(cfg, "derivatives_trend_horizons_seconds", [43200, 86400, 259200]) or [43200, 86400, 259200]
        self.derivatives_trend_horizons = tuple(sorted({max(3600, int(value)) for value in raw_derivatives_trend_horizons}))
        self.competition = HypothesisCompetition(cfg)
        store = getattr(coordinator, "store", None)
        self.reuse_governor = ResearchReuseGovernor(cfg, store) if store is not None else None
        self.commons_governor = CommonsPhase2Governor(cfg, store) if store is not None else None
        self.calibrator = WalkForwardForecastCalibrator(cfg, store) if store is not None else None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._run_count = 0
        self._last_error: Optional[str] = None
        self._latest: dict[str, Any] = {
            "phase": 2,
            "mode": "hypothesis_research_only",
            "status": "INITIALIZED" if self.enabled else "DISABLED",
            "execution_wired": False,
            "orders_submitted": 0,
            "forecasts": [],
        }

    def _scorecard_context(self) -> dict[str, Any]:
        if not self.coordinator:
            return {}
        store = getattr(self.coordinator, "store", None)
        if store is None or not hasattr(store, "get_hypothesis_scorecard"):
            return {}
        try:
            return store.get_hypothesis_scorecard()
        except Exception:
            return {}

    def _frontier_context_map(
        self, scorecard: Optional[dict[str, Any]] = None
    ) -> dict[tuple[str, str], dict[str, Any]]:
        scorecard = scorecard if isinstance(scorecard, dict) else self._scorecard_context()
        frontier_rows = scorecard.get("profitability_frontier") or []
        out: dict[tuple[str, str], dict[str, Any]] = {}
        for row in frontier_rows:
            if not isinstance(row, dict):
                continue
            hypothesis = str(row.get("hypothesis") or "unknown")
            regime_hint = str(row.get("regime_hint") or "unknown")
            out[(hypothesis, regime_hint)] = {
                "eligible": True,
                "mean_realized_net_bps": row.get("mean_realized_net_bps"),
                "settled_trades": row.get("settled_trades"),
                "model_id": row.get("model_id"),
                "promotion_hint": row.get("promotion_hint"),
            }
        return out

    def _feature_with_frontier_context(self, feature: FeatureVector, frontier_map: dict[tuple[str, str], dict[str, Any]]) -> FeatureVector:
        values = dict(feature.values or {})
        regime_inputs = values.get("regime_inputs") if isinstance(values.get("regime_inputs"), dict) else {}
        regime_hint = str(regime_inputs.get("regime_hint") or "unknown")
        frontier_context = {
            "breakout": frontier_map.get(("breakout_continuation", regime_hint), {"eligible": False, "regime_hint": regime_hint}),
            "reversion": frontier_map.get(("exhaustion_mean_reversion", regime_hint), {"eligible": False, "regime_hint": regime_hint}),
        }
        values["phase2_profitability_frontier"] = frontier_context
        return FeatureVector(**{**asdict(feature), "values": values})

    def _regime_suppression_map(
        self, scorecard: Optional[dict[str, Any]] = None
    ) -> dict[str, dict[str, Any]]:
        if not self.coordinator:
            return {}
        store = getattr(self.coordinator, "store", None)
        if store is None:
            return {}
        scorecard = scorecard if isinstance(scorecard, dict) else self._scorecard_context()
        rows = scorecard.get("regime_model_breakdown") or []
        out: dict[str, dict[str, Any]] = {}
        min_samples = max(3, int(getattr(self.cfg, "phase2_regime_suppression_min_samples", 6) or 6))
        max_mean = float(getattr(self.cfg, "phase2_regime_suppression_max_mean_net_bps", -2.5) or -2.5)
        reentry_window = max(2, int(getattr(self.cfg, "phase2_regime_reentry_recent_window", 6) or 6))
        reentry_min_samples = max(2, int(getattr(self.cfg, "phase2_regime_reentry_min_samples", 3) or 3))
        reentry_min_mean = float(getattr(self.cfg, "phase2_regime_reentry_min_mean_net_bps", 2.0) or 2.0)
        reentry_lookback_hours = max(
            1.0,
            float(getattr(self.cfg, "phase2_regime_reentry_lookback_hours", 6.0) or 6.0),
        )
        reentry_cutoff_ts = time.time() - reentry_lookback_hours * 3600.0
        release_map: dict[tuple[str, str], dict[str, Any]] = {}
        conn = getattr(store, "conn", None)
        if conn is not None:
            try:
                recent_rows = conn.execute(
                    """
                    SELECT
                        model_id,
                        regime_hint,
                        COUNT(*) AS sample_count,
                        AVG(net_return_bps) AS mean_realized_net_bps,
                        MAX(settled_ts) AS latest_settled_ts
                    FROM (
                        SELECT
                            f.model_id AS model_id,
                            COALESCE(
                                json_extract(f.payload, '$.inputs.regime_hint'),
                                json_extract(f.payload, '$.inputs.regime_inputs.regime_hint'),
                                'unknown'
                            ) AS regime_hint,
                            o.net_return_bps AS net_return_bps,
                            o.settled_ts AS settled_ts,
                            ROW_NUMBER() OVER (
                                PARTITION BY f.model_id,
                                COALESCE(
                                    json_extract(f.payload, '$.inputs.regime_hint'),
                                    json_extract(f.payload, '$.inputs.regime_inputs.regime_hint'),
                                    'unknown'
                                )
                                ORDER BY o.settled_ts DESC, f.ts DESC
                            ) AS rn
                        FROM hypothesis_forecasts f
                        JOIN hypothesis_outcomes o ON o.forecast_id = f.forecast_id
                        WHERE f.settled = 1
                          AND f.abstain = 0
                          AND f.ts >= ?
                          AND o.settled_ts >= ?
                    ) ranked
                    WHERE rn <= ?
                    GROUP BY model_id, regime_hint
                    HAVING COUNT(*) >= ? AND AVG(net_return_bps) >= ?
                    """,
                    (reentry_cutoff_ts, reentry_cutoff_ts, reentry_window, reentry_min_samples, reentry_min_mean),
                ).fetchall()
                release_map = {
                    (str(model_id or "unknown"), str(regime_hint or "unknown")): {
                        "released": True,
                        "recent_sample_count": int(sample_count or 0),
                        "recent_mean_realized_net_bps": round(float(mean_realized_net_bps or 0.0), 6),
                        "latest_settled_ts": latest_settled_ts,
                        "reason": "fresh_positive_regime_reentry",
                    }
                    for model_id, regime_hint, sample_count, mean_realized_net_bps, latest_settled_ts in recent_rows
                }
            except Exception:
                release_map = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            if int(row.get("settled_trades") or 0) < min_samples:
                continue
            mean_realized = row.get("mean_realized_net_bps")
            if mean_realized is None or float(mean_realized) > max_mean:
                continue
            regime_hint = str(row.get("regime_hint") or "unknown")
            model_id = str(row.get("model_id") or "unknown")
            release = release_map.get((model_id, regime_hint))
            if release:
                out.setdefault(regime_hint, {})[model_id] = {
                    "suppressed": False,
                    "released": True,
                    "mean_realized_net_bps": mean_realized,
                    "settled_trades": row.get("settled_trades"),
                    "hypothesis": row.get("hypothesis"),
                    "reason": release.get("reason"),
                    "recent_sample_count": release.get("recent_sample_count"),
                    "recent_mean_realized_net_bps": release.get("recent_mean_realized_net_bps"),
                    "latest_settled_ts": release.get("latest_settled_ts"),
                }
                continue
            out.setdefault(regime_hint, {})[model_id] = {
                "suppressed": True,
                "mean_realized_net_bps": mean_realized,
                "settled_trades": row.get("settled_trades"),
                "hypothesis": row.get("hypothesis"),
                "reason": "negative_regime_memory",
            }
        return out

    def _feature_with_regime_suppression(self, feature: FeatureVector, suppression_map: dict[str, dict[str, Any]]) -> FeatureVector:
        values = dict(feature.values or {})
        values["phase2_regime_suppression"] = suppression_map
        return FeatureVector(**{**asdict(feature), "values": values})

    def _worker_signal_memory_map(self) -> dict[str, dict[str, Any]]:
        if not self.coordinator:
            return {}
        if not bool(getattr(self.cfg, "phase2_worker_signal_negative_memory_enabled", True)):
            return {}
        store = getattr(self.coordinator, "store", None)
        conn = getattr(store, "conn", None)
        if conn is None:
            return {}
        lookback_hours = max(
            0.25,
            float(getattr(self.cfg, "phase2_worker_signal_memory_lookback_hours", 24.0) or 24.0),
        )
        cutoff_ts = time.time() - lookback_hours * 3600.0
        min_samples = max(1, int(getattr(self.cfg, "phase2_worker_signal_memory_min_samples", 2) or 2))
        worker_prefix = "worker_signal_"
        worker_prefix_upper = _prefix_upper_bound(worker_prefix)
        try:
            rows = conn.execute(
                """
                SELECT
                    f.symbol,
                    f.model_id,
                    f.horizon_seconds,
                    f.direction,
                    COUNT(*) AS samples,
                    AVG(o.directional_return_bps) AS mean_directional_bps,
                    AVG(o.net_return_bps) AS mean_net_bps,
                    AVG(CASE WHEN o.directional_return_bps > 0 THEN 1.0 ELSE 0.0 END) AS directional_hit_rate,
                    AVG(o.positive_net) AS net_win_rate,
                    MAX(o.settled_ts) AS latest_settled_ts
                FROM hypothesis_forecasts f
                JOIN hypothesis_outcomes o ON o.forecast_id=f.forecast_id
                WHERE f.settled=1
                  AND f.abstain=0
                  AND f.model_id>=?
                  AND f.model_id<?
                  AND o.settled_ts>=?
                GROUP BY f.symbol, f.model_id, f.horizon_seconds, f.direction
                HAVING COUNT(*)>=?
                """,
                (worker_prefix, worker_prefix_upper, cutoff_ts, min_samples),
            ).fetchall()
            model_rows = conn.execute(
                """
                SELECT
                    f.model_id,
                    f.horizon_seconds,
                    f.direction,
                    COUNT(*) AS samples,
                    AVG(o.directional_return_bps) AS mean_directional_bps,
                    AVG(o.net_return_bps) AS mean_net_bps,
                    AVG(CASE WHEN o.directional_return_bps > 0 THEN 1.0 ELSE 0.0 END) AS directional_hit_rate,
                    AVG(o.positive_net) AS net_win_rate,
                    MAX(o.settled_ts) AS latest_settled_ts
                FROM hypothesis_forecasts f
                JOIN hypothesis_outcomes o ON o.forecast_id=f.forecast_id
                WHERE f.settled=1
                  AND f.abstain=0
                  AND f.model_id>=?
                  AND f.model_id<?
                  AND o.settled_ts>=?
                GROUP BY f.model_id, f.horizon_seconds, f.direction
                HAVING COUNT(*)>=?
                """,
                (worker_prefix, worker_prefix_upper, cutoff_ts, min_samples),
            ).fetchall()
        except Exception:
            return {}
        exact: dict[str, dict[str, Any]] = {}
        model: dict[str, dict[str, Any]] = {}
        for symbol, model_id, horizon, direction, samples, mean_directional, mean_net, hit_rate, net_win_rate, latest in rows:
            key = f"{model_id}|{int(horizon or 0)}|{direction}"
            exact.setdefault(str(symbol or "unknown"), {})[key] = {
                "scope": "exact_symbol_worker_direction_horizon",
                "samples": int(samples or 0),
                "mean_directional_bps": round(float(mean_directional or 0.0), 6),
                "mean_net_bps": round(float(mean_net or 0.0), 6),
                "directional_hit_rate": round(float(hit_rate or 0.0), 6),
                "net_win_rate": round(float(net_win_rate or 0.0), 6),
                "latest_settled_ts": latest,
            }
        for model_id, horizon, direction, samples, mean_directional, mean_net, hit_rate, net_win_rate, latest in model_rows:
            key = f"{model_id}|{int(horizon or 0)}|{direction}"
            model[key] = {
                "scope": "model_direction_horizon",
                "samples": int(samples or 0),
                "mean_directional_bps": round(float(mean_directional or 0.0), 6),
                "mean_net_bps": round(float(mean_net or 0.0), 6),
                "directional_hit_rate": round(float(hit_rate or 0.0), 6),
                "net_win_rate": round(float(net_win_rate or 0.0), 6),
                "latest_settled_ts": latest,
            }
        return {"exact": exact, "model": model, "lookback_hours": lookback_hours}

    def _feature_with_worker_signal_memory(
        self,
        feature: FeatureVector,
        memory_map: dict[str, dict[str, Any]],
    ) -> FeatureVector:
        if not memory_map:
            return feature
        values = dict(feature.values or {})
        exact = memory_map.get("exact") if isinstance(memory_map.get("exact"), dict) else {}
        values["phase2_worker_signal_memory"] = {
            "exact": exact.get(str(feature.symbol or "unknown"), {}),
            "model": memory_map.get("model") if isinstance(memory_map.get("model"), dict) else {},
            "lookback_hours": memory_map.get("lookback_hours"),
            "authority": "research_memory_only",
        }
        return FeatureVector(**{**asdict(feature), "values": values})

    def _feature_with_cex_market_oracle(self, feature: FeatureVector, venue: str) -> FeatureVector:
        values = dict(feature.values or {})
        if "cex_market_oracle" in values:
            return feature
        if not self.coordinator:
            return feature
        store = getattr(self.coordinator, "store", None)
        if store is None or not hasattr(store, "cex_market_oracle_context"):
            return feature
        try:
            context = store.cex_market_oracle_context(
                str(feature.symbol or ""),
                venue=venue,
                as_of_ts=float(feature.timestamp_ms or 0) / 1000.0,
            )
            values["cex_market_oracle"] = context
            return FeatureVector(**{**asdict(feature), "values": values})
        except Exception:
            return feature

    def _medium_trend_context_map(self) -> dict[str, dict[str, Any]]:
        if not self.coordinator:
            return {}
        store = getattr(self.coordinator, "store", None)
        conn = getattr(store, "conn", None)
        if conn is None:
            return {}
        try:
            rows = conn.execute(
                """
                SELECT symbol, horizon_seconds, lookback_seconds, policy, entries,
                       mean_net_bps, lower_bound_net_bps, stressed_mean_net_bps,
                       buy_hold_mean_net_bps, payload
                FROM medium_horizon_trend_receipts
                WHERE accepted=1
                ORDER BY lower_bound_net_bps DESC, entries DESC
                """
            ).fetchall()
        except Exception:
            return {}
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            (
                symbol,
                horizon_seconds,
                lookback_seconds,
                policy,
                entries,
                mean_net,
                lower_bound,
                stressed_mean,
                buy_hold_mean,
                payload_raw,
            ) = row
            if str(policy or "") != "passive_post_only":
                continue
            payload: dict[str, Any] = {}
            try:
                payload = json.loads(payload_raw or "{}")
            except Exception:
                payload = {}
            symbol_key = str(symbol or "unknown")
            horizon_key = str(int(horizon_seconds or 0))
            direction_key = str(payload.get("direction") or "UP")
            slice_payload = {
                "symbol": symbol_key,
                "horizon_seconds": int(horizon_seconds or 0),
                "lookback_seconds": int(lookback_seconds or 0),
                "policy": str(policy or "unknown"),
                "direction": direction_key,
                "spot_executable": bool(payload.get("spot_executable", direction_key == "UP")),
                "entries": int(entries or 0),
                "mean_net_bps": round(float(mean_net or 0.0), 6),
                "lower_bound_net_bps": round(float(lower_bound or 0.0), 6),
                "stressed_mean_net_bps": round(float(stressed_mean or 0.0), 6),
                "buy_hold_mean_net_bps": round(float(buy_hold_mean or 0.0), 6),
                "receipt_id": payload.get("receipt_id"),
                "run_id": payload.get("run_id"),
                "economics_receipt_sha256": payload.get("economics_receipt_sha256"),
                "fee_source": payload.get("fee_source"),
                "authority": "research_only_no_execution",
            }
            # ORDER BY lower_bound_net_bps DESC means the first row seen per
            # symbol/horizon/direction is the strongest accepted slice; keep it
            # and ignore weaker duplicates rather than letting the last (worst)
            # row silently overwrite it.
            out.setdefault(symbol_key, {}).setdefault(horizon_key, {}).setdefault(direction_key, slice_payload)
        return out

    def _feature_with_medium_trend_context(
        self,
        feature: FeatureVector,
        trend_map: dict[str, dict[str, Any]],
    ) -> FeatureVector:
        accepted = trend_map.get(str(feature.symbol or "unknown"))
        if not accepted:
            return feature
        store = getattr(self.coordinator, "store", None) if self.coordinator else None
        conn = getattr(store, "conn", None)
        if conn is None:
            return feature
        all_slices = [
            direction_slice
            for horizon_slices in accepted.values()
            for direction_slice in horizon_slices.values()
        ]
        if not all_slices:
            return feature
        latest_lookback = max(int(row.get("lookback_seconds") or 0) for row in all_slices)
        as_of_ts = float(feature.timestamp_ms or 0) / 1000.0
        lookback_ts = as_of_ts - float(latest_lookback)
        momentum_bps = 0.0
        lookback_price = None
        try:
            row = conn.execute(
                """
                SELECT price FROM observation_snapshots
                WHERE symbol=? AND ts<=? AND price IS NOT NULL
                ORDER BY ts DESC LIMIT 1
                """,
                (feature.symbol, lookback_ts),
            ).fetchone()
            lookback_price = float(row[0]) if row and row[0] else None
        except Exception:
            lookback_price = None
        if lookback_price and feature.price and float(feature.price) > 0:
            momentum_bps = ((float(feature.price) - lookback_price) / lookback_price) * 10_000.0
        values = dict(feature.values or {})
        values["medium_horizon_trend"] = {
            "schema": "hivenance_medium_horizon_trend_phase2_context_v1",
            "accepted_slices": accepted,
            "lookback_seconds": latest_lookback,
            "lookback_price": lookback_price,
            "current_price": feature.price,
            "lookback_momentum_bps": round(momentum_bps, 6),
            "authority": "research_context_only",
        }
        return FeatureVector(**{**asdict(feature), "values": values})

    def _derivatives_trend_context_map(self) -> dict[str, dict[str, Any]]:
        """Engine A context map, mirroring ``_medium_trend_context_map`` exactly
        but sourced from ``derivatives_trend_receipts`` (see
        ``derivatives_trend_lab.py``).
        """
        if not self.coordinator:
            return {}
        store = getattr(self.coordinator, "store", None)
        conn = getattr(store, "conn", None)
        if conn is None:
            return {}
        try:
            rows = conn.execute(
                """
                SELECT symbol, horizon_seconds, lookback_seconds, policy, entries,
                       mean_net_bps, lower_bound_net_bps, stressed_mean_net_bps, payload
                FROM derivatives_trend_receipts
                WHERE accepted=1
                ORDER BY lower_bound_net_bps DESC, entries DESC
                """
            ).fetchall()
        except Exception:
            return {}
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            (
                symbol,
                horizon_seconds,
                lookback_seconds,
                policy,
                entries,
                mean_net,
                lower_bound,
                stressed_mean,
                payload_raw,
            ) = row
            if str(policy or "") != "post_only_then_bounded_taker":
                continue
            payload: dict[str, Any] = {}
            try:
                payload = json.loads(payload_raw or "{}")
            except Exception:
                payload = {}
            symbol_key = str(symbol or "unknown")
            horizon_key = str(int(horizon_seconds or 0))
            direction_key = str(payload.get("direction") or "UP")
            slice_payload = {
                "symbol": symbol_key,
                "horizon_seconds": int(horizon_seconds or 0),
                "lookback_seconds": int(lookback_seconds or 0),
                "policy": str(policy or "unknown"),
                "direction": direction_key,
                "product": "perpetual_future",
                "leverage": 1,
                "entries": int(entries or 0),
                "mean_net_bps": round(float(mean_net or 0.0), 6),
                "lower_bound_net_bps": round(float(lower_bound or 0.0), 6),
                "stressed_mean_net_bps": round(float(stressed_mean or 0.0), 6),
                "receipt_id": payload.get("receipt_id"),
                "run_id": payload.get("run_id"),
                "economics_receipt_sha256": payload.get("economics_receipt_sha256"),
                "fee_source": payload.get("fee_source"),
                "price_data_source": payload.get("price_data_source", "kraken_spot_price_proxy_pending_futures_feed"),
                "authority": "research_only_no_execution",
            }
            out.setdefault(symbol_key, {}).setdefault(horizon_key, {}).setdefault(direction_key, slice_payload)
        return out

    def _feature_with_derivatives_trend_context(
        self,
        feature: FeatureVector,
        trend_map: dict[str, dict[str, Any]],
    ) -> FeatureVector:
        accepted = trend_map.get(str(feature.symbol or "unknown"))
        if not accepted:
            return feature
        store = getattr(self.coordinator, "store", None) if self.coordinator else None
        conn = getattr(store, "conn", None)
        if conn is None:
            return feature
        all_slices = [
            direction_slice
            for horizon_slices in accepted.values()
            for direction_slice in horizon_slices.values()
        ]
        if not all_slices:
            return feature
        latest_lookback = max(int(row.get("lookback_seconds") or 0) for row in all_slices)
        as_of_ts = float(feature.timestamp_ms or 0) / 1000.0
        lookback_ts = as_of_ts - float(latest_lookback)
        momentum_bps = 0.0
        lookback_price = None
        try:
            row = conn.execute(
                """
                SELECT price FROM observation_snapshots
                WHERE symbol=? AND ts<=? AND price IS NOT NULL
                ORDER BY ts DESC LIMIT 1
                """,
                (feature.symbol, lookback_ts),
            ).fetchone()
            lookback_price = float(row[0]) if row and row[0] else None
        except Exception:
            lookback_price = None
        if lookback_price and feature.price and float(feature.price) > 0:
            momentum_bps = ((float(feature.price) - lookback_price) / lookback_price) * 10_000.0
        values = dict(feature.values or {})
        values["derivatives_trend"] = {
            "schema": "hivenance_derivatives_trend_phase2_context_v1",
            "accepted_slices": accepted,
            "lookback_seconds": latest_lookback,
            "lookback_price": lookback_price,
            "current_price": feature.price,
            "lookback_momentum_bps": round(momentum_bps, 6),
            "product": "perpetual_future",
            "leverage": 1,
            "authority": "research_context_only",
        }
        return FeatureVector(**{**asdict(feature), "values": values})

    def _crystal_context(self, feature: FeatureVector) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if not self.coordinator:
            return ([], [])
        store = getattr(self.coordinator, "store", None)
        if store is None or not hasattr(store, "get_crystal_registry_rows"):
            return ([], [])
        values = feature.values if isinstance(feature.values, dict) else {}
        regime_inputs = values.get("regime_inputs") if isinstance(values.get("regime_inputs"), dict) else {}
        regime_hint = str(regime_inputs.get("regime_hint") or "unknown")
        try:
            thesis = store.get_crystal_registry_rows(
                crystal_family="thesis_capability",
                symbol=str(feature.symbol or "unknown"),
                regime_hint=regime_hint,
                limit=64,
            )
            negative = store.get_crystal_registry_rows(
                crystal_family="negative_capability",
                regime_hint=regime_hint,
                limit=64,
            )
            return (thesis, negative)
        except Exception:
            return ([], [])

    def start(self) -> bool:
        if not self.enabled or self.observer is None:
            with self._lock:
                self._latest["status"] = "UNAVAILABLE" if self.observer is None else "DISABLED"
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="hivenance-hypothesis-swarm", daemon=True)
        self._thread.start()
        return True

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(0.0, timeout))

    def status(self) -> dict[str, Any]:
        with self._lock:
            snapshot = dict(self._latest)
        return {
            "phase": 2,
            "mode": "hypothesis_research_only",
            "enabled": self.enabled,
            "status": snapshot.get("status", "UNKNOWN"),
            "run_count": self._run_count,
            "last_error": self._last_error,
            "thread_alive": bool(self._thread and self._thread.is_alive()),
            "horizons_seconds": list(self.horizons),
            "primary_models": list(self.competition.primary_ids),
            "federated_models": list(self.competition.federated_ids),
            "baseline_models": list(self.competition.baseline_ids),
            "federation": self.competition.federation_manifest(),
            "walk_forward_calibration": self.calibrator.manifest() if self.calibrator else {"enabled": False},
            "execution_wired": False,
            "orders_submitted": 0,
        }

    def latest_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._latest, default=str))

    def _publish(self, key: str, payload: dict[str, Any]) -> None:
        if self.coordinator and hasattr(self.coordinator, "share_data"):
            self.coordinator.share_data(key, {
                "buzz": {
                    "type": key,
                    "source": "HYPOTHESIS_SWARM",
                    "ts": int(time.time() * 1000),
                },
                "payload": payload,
            })

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self.run_once()
                self._last_error = None
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                logging.exception("Hypothesis swarm cycle failed")
                with self._lock:
                    self._latest["status"] = "ERROR"
            elapsed = time.monotonic() - started
            self._stop.wait(max(1.0, self.interval_sec - elapsed))

    def run_once(self, *, scorecard_context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("phase2 hypotheses are disabled")
        if self.observer is None:
            raise RuntimeError("phase1 observer unavailable")

        started_ms = int(time.time() * 1000)
        observation = self.observer.run_once()
        observation_run = observation.get("run") or {}
        observation_run_id = str(observation_run.get("run_id") or "")
        venue = str(observation_run.get("venue") or getattr(self.cfg, "exchange", "unknown")).lower()
        run_id = f"hyp-{started_ms}-{uuid.uuid4().hex[:8]}"
        forecast_rows: list[dict[str, Any]] = []
        reuse_receipts: list[dict[str, Any]] = []
        commons_packets: list[dict[str, Any]] = []
        commons_admitted = 0
        commons_rejected = 0
        commons_rejection_reasons: dict[str, int] = {}
        commons_ticket_rows: list[dict[str, Any]] = []
        evaluated_symbols = 0
        scorecard_context = (
            scorecard_context
            if isinstance(scorecard_context, dict)
            else self._scorecard_context()
        )
        frontier_map = self._frontier_context_map(scorecard_context)
        suppression_map = self._regime_suppression_map(scorecard_context)
        worker_signal_memory_map = self._worker_signal_memory_map()
        medium_trend_map = self._medium_trend_context_map()
        derivatives_trend_map = self._derivatives_trend_context_map()
        commons_candidates: list[tuple[dict[str, Any], FeatureVector]] = []

        for candidate in observation.get("candidates") or []:
            values = candidate.get("values") or {}
            feature = _feature_from_payload(values.get("feature_vector") or {})
            if feature is None:
                continue
            feature = _feature_with_candidate_context(feature, values if isinstance(values, dict) else {})
            feature = self._feature_with_frontier_context(feature, frontier_map)
            feature = self._feature_with_regime_suppression(feature, suppression_map)
            feature = self._feature_with_worker_signal_memory(feature, worker_signal_memory_map)
            feature = self._feature_with_cex_market_oracle(feature, venue)
            feature = self._feature_with_medium_trend_context(feature, medium_trend_map)
            feature = self._feature_with_derivatives_trend_context(feature, derivatives_trend_map)
            thesis_crystals, negative_crystals = self._crystal_context(feature)
            feature = _feature_with_crystal_context(
                feature,
                thesis_crystals=thesis_crystals,
                negative_crystals=negative_crystals,
            )
            commons_candidates.append((candidate, feature))
            regime_inputs = values.get("regime_inputs") if isinstance(values.get("regime_inputs"), dict) else {}
            regime_hint = str(regime_inputs.get("regime_hint") or "unknown")
            cohort_bucket = str(values.get("cohort_bucket") or "unknown")
            symbol_class = str(values.get("symbol_class") or "unknown")
            evaluated_symbols += 1
            for forecast in self.competition.evaluate(feature, self.horizons):
                row = asdict(forecast)
                row["forecast_id"] = hashlib.sha256(
                    f"{run_id}:{forecast.model_id}:{forecast.symbol}:{forecast.horizon_seconds}".encode("utf-8")
                ).hexdigest()
                row["run_id"] = run_id
                row["observation_run_id"] = observation_run_id
                row["venue"] = venue
                row["entry_price"] = feature.price
                row["target_timestamp_ms"] = int(feature.timestamp_ms + forecast.horizon_seconds * 1000)
                row["execution_eligible"] = False
                row["order_intent"] = None
                row["research_route"] = "full_competition"
                row["research_route_priority"] = 0
                crystal_memory = (
                    ((feature.values or {}).get("phase2_crystal_memory"))
                    if isinstance(feature.values, dict)
                    else {}
                )
                if isinstance(crystal_memory, dict):
                    row["crystal_memory"] = crystal_memory
                    support_score = float(crystal_memory.get("support_score") or 0.0)
                    warning_score = float(crystal_memory.get("warning_score") or 0.0)
                    row["crystal_priority_adjustment"] = round(min(2.0, support_score * 0.5) - min(2.5, warning_score * 0.5), 6)
                    if row["crystal_priority_adjustment"] > 0:
                        row["research_route_priority"] += 1
                    elif row["crystal_priority_adjustment"] < 0:
                        row["research_route_priority"] -= 1
                if self.reuse_governor is not None and not row.get("abstain"):
                    reuse = self.reuse_governor.decide(
                        model_id=str(row.get("model_id") or ""),
                        symbol=str(row.get("symbol") or ""),
                        horizon_seconds=int(row.get("horizon_seconds") or 0),
                        regime_hint=regime_hint,
                        cohort_bucket=cohort_bucket,
                        symbol_class=symbol_class,
                    )
                    row["reuse_context"] = reuse
                    if str(reuse.get("decision") or "") == "exact_reuse_candidate":
                        row["research_route"] = "exact_reuse"
                        row["research_route_priority"] = 2
                    elif str(reuse.get("decision") or "") == "transformed_symbol_class_candidate":
                        row["research_route"] = "symbol_class_transform"
                        row["research_route_priority"] = 1
                    elif str(reuse.get("decision") or "") == "transformed_cohort_candidate":
                        row["research_route"] = "cohort_transform"
                        row["research_route_priority"] = 1
                    elif str(reuse.get("decision") or "") == "exact_reuse_too_weak":
                        row["research_route"] = "prior_evidence_rejected"
                        row["research_route_priority"] = -1
                    elif str(reuse.get("decision") or "") in {"transformed_symbol_class_too_weak", "transformed_cohort_too_weak"}:
                        row["research_route"] = "transform_evidence_rejected"
                        row["research_route_priority"] = -1
                    reuse_receipts.append(reuse)
                forecast_rows.append(row)
            medium_context = (
                (feature.values or {}).get("medium_horizon_trend")
                if isinstance(feature.values, dict)
                else {}
            )
            medium_forecasts = (
                self.competition.evaluate_medium_trend(feature, self.medium_trend_horizons)
                if isinstance(medium_context, dict) and bool(medium_context.get("accepted_slices"))
                else []
            )
            for forecast in medium_forecasts:
                row = asdict(forecast)
                row["forecast_id"] = hashlib.sha256(
                    f"{run_id}:{forecast.model_id}:{forecast.symbol}:{forecast.horizon_seconds}:medium_trend".encode("utf-8")
                ).hexdigest()
                row["run_id"] = run_id
                row["observation_run_id"] = observation_run_id
                row["venue"] = venue
                row["entry_price"] = feature.price
                row["target_timestamp_ms"] = int(feature.timestamp_ms + forecast.horizon_seconds * 1000)
                row["execution_eligible"] = False
                row["order_intent"] = None
                row["research_route"] = "medium_horizon_trend"
                row["research_route_priority"] = 3 if not row.get("abstain") else 0
                row["medium_horizon_trend_context"] = medium_context
                forecast_rows.append(row)
            derivatives_trend_context = (
                (feature.values or {}).get("derivatives_trend")
                if isinstance(feature.values, dict)
                else {}
            )
            derivatives_trend_forecasts = (
                self.competition.evaluate_derivatives_trend(feature, self.derivatives_trend_horizons)
                if isinstance(derivatives_trend_context, dict) and bool(derivatives_trend_context.get("accepted_slices"))
                else []
            )
            for forecast in derivatives_trend_forecasts:
                row = asdict(forecast)
                row["forecast_id"] = hashlib.sha256(
                    f"{run_id}:{forecast.model_id}:{forecast.symbol}:{forecast.horizon_seconds}:derivatives_trend".encode("utf-8")
                ).hexdigest()
                row["run_id"] = run_id
                row["observation_run_id"] = observation_run_id
                row["venue"] = venue
                row["entry_price"] = feature.price
                row["target_timestamp_ms"] = int(feature.timestamp_ms + forecast.horizon_seconds * 1000)
                row["execution_eligible"] = False
                row["order_intent"] = None
                row["research_route"] = "derivatives_trend"
                row["research_route_priority"] = 3 if not row.get("abstain") else 0
                row["derivatives_trend_context"] = derivatives_trend_context
                row["product"] = "perpetual_future"
                row["leverage"] = 1
                forecast_rows.append(row)

        if self.commons_governor is not None:
            commons_ticket_rows = self.commons_governor.issue_tickets(
                observation_run_id=observation_run_id,
                venue=venue,
                candidates=commons_candidates,
                horizons=self.horizons,
                created_ts=started_ms / 1000.0,
            )

        store = getattr(self.coordinator, "store", None) if self.coordinator is not None else None
        if store is not None and hasattr(store, "get_commons_phase2_adopted_challenger_packets"):
            try:
                commons_packets = store.get_commons_phase2_adopted_challenger_packets(limit=100)
            except Exception:
                commons_packets = []
            for packet in commons_packets:
                allowed = True
                rejection_reasons: list[str] = []
                if self.commons_governor is not None:
                    allowed, rejection_reasons = self.commons_governor.verify_adopted_packet(packet, completed_ms / 1000.0 if 'completed_ms' in locals() else time.time())
                if not allowed:
                    commons_rejected += 1
                    for reason in rejection_reasons:
                        commons_rejection_reasons[reason] = commons_rejection_reasons.get(reason, 0) + 1
                    continue
                row = _commons_forecast_row(
                    run_id=run_id,
                    observation_run_id=observation_run_id,
                    venue=venue,
                    packet=packet,
                )
                if row is not None:
                    forecast_rows.append(row)
                    commons_admitted += 1

        calibration_summary = (
            self.calibrator.calibrate_rows(forecast_rows, cutoff_ts=started_ms / 1000.0)
            if self.calibrator is not None
            else {"manifest": {"enabled": False}, "examined": 0, "allowed": 0, "refused": 0, "insufficient_evidence": 0}
        )
        completed_ms = int(time.time() * 1000)
        non_abstain = sum(1 for row in forecast_rows if not row.get("abstain"))
        summary = HypothesisRunSummary(
            run_id=run_id,
            observation_run_id=observation_run_id,
            venue=venue,
            started_at_ms=started_ms,
            completed_at_ms=completed_ms,
            symbols_evaluated=evaluated_symbols,
            forecasts_total=len(forecast_rows),
            non_abstain_forecasts=non_abstain,
            abstentions=len(forecast_rows) - non_abstain,
            primary_models=self.competition.primary_ids,
            federated_models=self.competition.federated_ids,
            baseline_models=self.competition.baseline_ids,
            execution_wired=False,
            orders_submitted=0,
        )
        payload: dict[str, Any] = {
            "phase": 2,
            "mode": "hypothesis_research_only",
            "status": "HEALTHY" if evaluated_symbols > 0 else "DEGRADED",
            "run": asdict(summary),
            "observation_dataset_hash": observation.get("dataset_hash"),
            "horizons_seconds": list(self.horizons),
            "medium_trend_horizons_seconds": list(self.medium_trend_horizons),
            "derivatives_trend_horizons_seconds": list(self.derivatives_trend_horizons),
            "federation": self.competition.federation_manifest(),
            "walk_forward_calibration": calibration_summary,
            "forecasts": forecast_rows,
            "research_reuse": {
                "receipts": reuse_receipts,
                "summary": {
                    "exact_reuse_candidate": sum(1 for row in reuse_receipts if row.get("decision") == "exact_reuse_candidate"),
                    "exact_reuse_too_weak": sum(1 for row in reuse_receipts if row.get("decision") == "exact_reuse_too_weak"),
                    "transformed_symbol_class_candidate": sum(1 for row in reuse_receipts if row.get("decision") == "transformed_symbol_class_candidate"),
                    "transformed_symbol_class_too_weak": sum(1 for row in reuse_receipts if row.get("decision") == "transformed_symbol_class_too_weak"),
                    "transformed_cohort_candidate": sum(1 for row in reuse_receipts if row.get("decision") == "transformed_cohort_candidate"),
                    "transformed_cohort_too_weak": sum(1 for row in reuse_receipts if row.get("decision") == "transformed_cohort_too_weak"),
                    "no_prior_evidence": sum(1 for row in reuse_receipts if row.get("decision") == "no_prior_evidence"),
                },
            },
            "commons_inference_pool": {
                "tickets_issued": len(commons_ticket_rows),
                "adopted_packets_examined": len(commons_packets),
                "adopted_forecasts": commons_admitted,
                "rejected_packets": commons_rejected,
                "rejection_reasons": commons_rejection_reasons,
                "forecast_rows_present": sum(
                    1 for row in forecast_rows if str(row.get("research_route") or "") == "commons_inference_pool"
                ),
                "authority": "proposal_only",
            },
            "execution_wired": False,
            "orders_submitted": 0,
            "observed_at": datetime.fromtimestamp(completed_ms / 1000.0, tz=timezone.utc).isoformat(),
        }
        payload["competition"] = {
            "forecasts_total": len(forecast_rows),
            "non_abstain_forecasts": non_abstain,
            "abstentions": len(forecast_rows) - non_abstain,
            "by_model": {
                model_id: {
                    "forecasts": sum(1 for row in forecast_rows if row.get("model_id") == model_id),
                    "non_abstain": sum(1 for row in forecast_rows if row.get("model_id") == model_id and not row.get("abstain")),
                }
                for model_id in self.competition.all_model_ids
            },
        }
        payload["dataset_hash"] = _canonical_hash({
            "run": payload["run"],
            "observation_dataset_hash": payload["observation_dataset_hash"],
            "forecasts": payload["forecasts"],
        })
        if store is not None:
            if hasattr(store, "persist_inference_rung"):
                for row in forecast_rows:
                    try:
                        store.persist_inference_rung(_phase2_rung_row(row, run_id=run_id, created_ts=completed_ms / 1000.0))
                    except Exception:
                        logging.exception("Failed to persist Phase-2 inference rung")
            if hasattr(store, "persist_crystal_registry_entry"):
                for row in forecast_rows:
                    if row.get("abstain"):
                        continue
                    try:
                        store.persist_crystal_registry_entry(_phase2_thesis_crystal(row, created_ts=completed_ms / 1000.0))
                    except Exception:
                        logging.exception("Failed to persist Phase-2 thesis crystal")

        with self._lock:
            self._latest = payload
            self._run_count += 1
        self._publish("buzz.hypothesis.snapshot", payload)
        self._publish("buzz.hypothesis.health", {
            "phase": 2,
            "status": payload["status"],
            "run_id": run_id,
            "forecasts_total": len(forecast_rows),
            "non_abstain_forecasts": non_abstain,
            "execution_wired": False,
            "orders_submitted": 0,
        })
        return payload
