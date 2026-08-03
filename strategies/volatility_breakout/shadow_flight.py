from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from typing import Any, Mapping, Optional, Sequence

from .shadow_models import ShadowFreeze, ShadowOrderIntent, ShadowSettlement
from .venue_profiles import venue_profile


PHASE5_CONFIG_KEYS = (
    "exchange",
    "phase2_horizons_seconds",
    "phase2_min_data_quality",
    "phase2_minimum_edge_multiple",
    "phase2_federation_enabled",
    "phase2_federation_min_data_quality",
    "phase2_federation_minimum_edge_multiple",
    "phase2_federation_score_scale",
    "phase2_federation_freqai_confidence_floor",
    "phase2_breakout_min_expansion",
    "phase2_breakout_min_volume_zscore",
    "phase2_breakout_min_return_zscore",
    "phase2_reversion_min_stretch_zscore",
    "phase2_reversion_min_range_extreme",
    "phase3_simulated_equity_usd",
    "phase3_risk_fraction",
    "phase3_sleeve_fraction",
    "phase3_max_notional_usd",
    "phase3_max_depth_participation",
    "phase3_min_notional_usd",
    "phase3_maker_fee_bps",
    "phase3_taker_fee_bps",
    "phase3_max_entry_spread_bps",
    "phase5_shadow_reference_notional_usd",
    "phase5_shadow_stop_distance_bps",
    "phase5_shadow_max_intents_per_cycle",
    "phase5_shadow_chase_timeout_sec",
    "phase5_shadow_entry_latency_ms",
)


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def frozen_config_payload(cfg: Any) -> dict[str, Any]:
    return {key: getattr(cfg, key, None) for key in PHASE5_CONFIG_KEYS}


def frozen_config_hash(cfg: Any) -> str:
    return canonical_hash(frozen_config_payload(cfg))


def build_freeze_from_phase4(
    report: Mapping[str, Any],
    *,
    approved_by: str,
    approved_ts: float,
    cfg: Any,
) -> ShadowFreeze:
    readiness = report.get("readiness") or {}
    champion = report.get("champion") or {}
    if not readiness.get("ready_for_phase5_review"):
        raise ValueError("latest Phase-4 report is not ready for Phase-5 review")
    candidate_key = str(champion.get("candidate_key") or "")
    model_id = str(champion.get("model_id") or "")
    order_policy = str(champion.get("order_policy") or "")
    if not candidate_key or not model_id or not order_policy:
        raise ValueError("Phase-4 champion is incomplete")
    if model_id.startswith("baseline_"):
        raise ValueError("a baseline model cannot be approved for shadow flight")
    if order_policy not in {"market", "marketable_limit", "passive_post_only", "passive_then_chase"}:
        raise ValueError(f"unsupported champion order policy: {order_policy}")
    approved_by = str(approved_by or "").strip()
    if len(approved_by) < 2:
        raise ValueError("approved_by must identify the human reviewer")
    run_id = str(report.get("run_id") or "")
    dataset_hash = str(report.get("dataset_hash") or "")
    config_hash = frozen_config_hash(cfg)
    freeze_id = canonical_hash({
        "phase4_run_id": run_id,
        "candidate_key": candidate_key,
        "approved_by": approved_by,
        "approved_ts": float(approved_ts),
        "phase4_dataset_hash": dataset_hash,
        "config_hash": config_hash,
    })
    return ShadowFreeze(
        freeze_id=freeze_id,
        phase4_run_id=run_id,
        candidate_key=candidate_key,
        model_id=model_id,
        order_policy=order_policy,
        approved_by=approved_by,
        approved_ts=float(approved_ts),
        phase4_dataset_hash=dataset_hash,
        config_hash=config_hash,
    )


class ShadowIntentBuilder:
    """Converts approved primary forecasts into never-transmitted order intents."""

    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg
        self.reference_notional = max(
            0.01, float(getattr(cfg, "phase5_shadow_reference_notional_usd", 10.0) or 10.0)
        )
        self.stop_bps = max(
            1.0, float(getattr(cfg, "phase5_shadow_stop_distance_bps", 250.0) or 250.0)
        )
        self.max_depth_participation = max(
            0.000001, min(0.10, float(getattr(cfg, "phase3_max_depth_participation", 0.01) or 0.01))
        )

    @staticmethod
    def _number(value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
            return number if math.isfinite(number) else default
        except (TypeError, ValueError):
            return default

    def _sizing(self, forecast: Mapping[str, Any], observation: Mapping[str, Any], profile: Any) -> dict[str, float]:
        price = self._number(forecast.get("entry_price") or observation.get("price"))
        equity = max(0.0, self._number(getattr(self.cfg, "phase3_simulated_equity_usd", 1000.0), 1000.0))
        risk_fraction = max(0.0, self._number(getattr(self.cfg, "phase3_risk_fraction", 0.0005), 0.0005))
        sleeve_fraction = max(0.0, self._number(getattr(self.cfg, "phase3_sleeve_fraction", 0.02), 0.02))
        max_notional = max(0.0, self._number(getattr(self.cfg, "phase3_max_notional_usd", 25.0), 25.0))
        depth = max(0.0, self._number(observation.get("depth_usd_25bps")))
        risk_budget = equity * risk_fraction
        risk_based_notional = risk_budget / max(self.stop_bps / 10000.0, 0.000001)
        notional = min(
            self.reference_notional,
            risk_based_notional,
            equity * sleeve_fraction,
            max_notional,
            depth * self.max_depth_participation if depth > 0 else max_notional,
        )
        notional = max(0.0, notional)
        quantity = profile.round_quantity(notional / price) if price > 0 else 0.0
        notional = quantity * price
        return {"price": price, "quantity": quantity, "notional": notional, "risk_budget": risk_budget}

    def build(
        self,
        forecast: Mapping[str, Any],
        observation: Mapping[str, Any],
        freeze: ShadowFreeze,
    ) -> ShadowOrderIntent:
        if str(forecast.get("model_id") or "") != freeze.model_id:
            raise ValueError("forecast model does not match frozen champion")
        if bool(forecast.get("abstain")):
            raise ValueError("abstaining forecasts cannot create shadow intents")
        direction = str(forecast.get("direction") or "").upper()
        if direction != "UP":
            raise ValueError("Phase-5 spot shadow flight only accepts UP forecasts")
        venue = str(forecast.get("venue") or getattr(self.cfg, "exchange", "kraken") or "kraken").lower()
        profile = venue_profile(venue, self.cfg)
        if freeze.order_policy not in profile.supported_policies:
            raise ValueError("frozen order policy is unsupported by venue profile")
        data_quality = self._number(observation.get("data_quality"))
        min_quality = self._number(getattr(self.cfg, "phase5_shadow_min_data_quality", 0.99), 0.99)
        if data_quality < min_quality:
            raise ValueError("observation data quality is below the shadow gate")
        spread_bps = max(0.0, self._number(observation.get("spread_bps")))
        max_spread = self._number(getattr(self.cfg, "phase5_shadow_max_spread_bps", 60.0), 60.0)
        if spread_bps > max_spread:
            raise ValueError("spread is above the shadow gate")
        sizing = self._sizing(forecast, observation, profile)
        if sizing["quantity"] < profile.min_quantity or sizing["notional"] < profile.min_notional_usd:
            raise ValueError("shadow intent is below venue minimums")
        reference = sizing["price"]
        half_spread = spread_bps / 20000.0
        policy = freeze.order_policy
        if policy == "market":
            order_type, tif, limit_price = "market", "IOC", None
        elif policy == "marketable_limit":
            order_type, tif = "limit", "IOC"
            limit_price = profile.round_price(reference * (1.0 + half_spread + 0.0005))
        else:
            order_type, tif = "limit", "GTC"
            limit_price = profile.round_price(reference * (1.0 - half_spread))
        created_ts = self._number(forecast.get("ts") or forecast.get("timestamp_ms") / 1000.0)
        target_ts = self._number(forecast.get("target_ts") or forecast.get("target_timestamp_ms") / 1000.0)
        if created_ts <= 0 or target_ts <= created_ts:
            raise ValueError("forecast timestamps are invalid")
        forecast_id = str(forecast.get("forecast_id") or "")
        shadow_id = canonical_hash({
            "forecast_id": forecast_id,
            "freeze_id": freeze.freeze_id,
            "candidate_key": freeze.candidate_key,
            "policy": policy,
        })
        return ShadowOrderIntent(
            shadow_intent_id=shadow_id,
            forecast_id=forecast_id,
            freeze_id=freeze.freeze_id,
            phase4_run_id=freeze.phase4_run_id,
            candidate_key=freeze.candidate_key,
            model_id=freeze.model_id,
            order_policy=policy,
            venue=venue,
            symbol=str(forecast.get("symbol") or ""),
            direction=direction,
            side="buy",
            order_type=order_type,
            time_in_force=tif,
            quantity=sizing["quantity"],
            notional_usd=sizing["notional"],
            reference_price=reference,
            limit_price=limit_price,
            stop_distance_bps=self.stop_bps,
            risk_budget_usd=sizing["risk_budget"],
            predicted_move_bps=self._number(forecast.get("expected_move_bps")),
            predicted_cost_bps=self._number(forecast.get("expected_cost_bps")),
            predicted_net_bps=self._number(forecast.get("expected_net_bps")),
            probability_positive_net=self._number(forecast.get("probability_positive_net")),
            horizon_seconds=int(forecast.get("horizon_seconds") or 0),
            created_ts=created_ts,
            target_ts=target_ts,
            data_quality=data_quality,
            spread_bps=spread_bps,
            depth_usd_25bps=max(0.0, self._number(observation.get("depth_usd_25bps"))),
            venue_profile_version=profile.profile_version,
            config_hash=freeze.config_hash,
        )


class ShadowSettlementEngine:
    """Settles a shadow intent from later public observations only."""

    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg
        self.entry_latency_sec = max(
            0.0, float(getattr(cfg, "phase5_shadow_entry_latency_ms", 250.0) or 250.0) / 1000.0
        )
        self.chase_timeout_sec = max(
            1.0, float(getattr(cfg, "phase5_shadow_chase_timeout_sec", 30.0) or 30.0)
        )
        self.max_impact_bps = max(
            0.0, float(getattr(cfg, "phase3_max_slippage_bps", 75.0) or 75.0)
        )

    @staticmethod
    def _number(value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
            return number if math.isfinite(number) else default
        except (TypeError, ValueError):
            return default

    def settle(
        self,
        intent: Mapping[str, Any],
        observations: Sequence[Mapping[str, Any]],
        *,
        settled_ts: float,
    ) -> Optional[ShadowSettlement]:
        if not observations:
            return None
        ordered = sorted(observations, key=lambda item: self._number(item.get("ts")))
        created = self._number(intent.get("created_ts"))
        target = self._number(intent.get("target_ts"))
        entry_ready = created + self.entry_latency_sec
        entry_candidates = [row for row in ordered if self._number(row.get("ts")) >= entry_ready and self._number(row.get("ts")) <= target]
        exit_candidates = [row for row in ordered if self._number(row.get("ts")) >= target]
        if not exit_candidates:
            return None
        policy = str(intent.get("order_policy") or "")
        reference = self._number(intent.get("reference_price"))
        limit_price = intent.get("limit_price")
        limit_value = self._number(limit_price) if limit_price is not None else None
        fill_row: Optional[Mapping[str, Any]] = None
        fill_model = "PUBLIC_SNAPSHOT_PROXY"
        if policy in {"market", "marketable_limit"}:
            fill_row = entry_candidates[0] if entry_candidates else None
            if policy == "marketable_limit" and fill_row is not None and limit_value is not None:
                mid = self._number(fill_row.get("price"))
                spread = max(0.0, self._number(fill_row.get("spread_bps")))
                ask = mid * (1.0 + spread / 20000.0)
                if ask > limit_value:
                    fill_row = None
        elif policy == "passive_post_only":
            if limit_value is not None:
                fill_row = next((row for row in entry_candidates if self._number(row.get("price")) <= limit_value), None)
            fill_model = "CONSERVATIVE_PASSIVE_TOUCH_PROXY"
        elif policy == "passive_then_chase":
            passive_window = created + self.chase_timeout_sec
            if limit_value is not None:
                fill_row = next(
                    (row for row in entry_candidates if self._number(row.get("ts")) <= passive_window and self._number(row.get("price")) <= limit_value),
                    None,
                )
            if fill_row is None:
                fill_row = next((row for row in entry_candidates if self._number(row.get("ts")) >= passive_window), None)
                fill_model = "PASSIVE_THEN_MARKETABLE_PROXY"
        exit_row = exit_candidates[0]
        if fill_row is None:
            settlement_id = canonical_hash({"intent": intent.get("shadow_intent_id"), "status": "MISSED_FILL", "target": target})
            return ShadowSettlement(
                settlement_id=settlement_id,
                shadow_intent_id=str(intent.get("shadow_intent_id") or ""),
                forecast_id=str(intent.get("forecast_id") or ""),
                settled_ts=float(settled_ts),
                status="MISSED_FILL",
                fill_model=fill_model,
                fill_ratio=0.0,
                intended_entry_price=limit_value or reference,
                hypothetical_entry_price=None,
                reference_exit_price=self._number(exit_row.get("price")),
                hypothetical_exit_price=None,
                entry_slippage_bps=0.0,
                exit_slippage_bps=0.0,
                fee_bps=0.0,
                impact_bps=0.0,
                observed_total_cost_bps=0.0,
                predicted_cost_bps=self._number(intent.get("predicted_cost_bps")),
                cost_error_bps=abs(self._number(intent.get("predicted_cost_bps"))),
                gross_directional_return_bps=0.0,
                net_return_bps=0.0,
                profitable_after_costs=False,
                data_quality=min(self._number(exit_row.get("data_quality"), 0.0), self._number(intent.get("data_quality"), 0.0)),
                diagnostics={"reason": "order_not_hypothetically_filled_before_horizon"},
            )
        profile = venue_profile(str(intent.get("venue") or "kraken"), self.cfg)
        entry_mid = self._number(fill_row.get("price"))
        exit_mid = self._number(exit_row.get("price"))
        entry_spread = max(0.0, self._number(fill_row.get("spread_bps")))
        exit_spread = max(0.0, self._number(exit_row.get("spread_bps")))
        depth = max(self._number(fill_row.get("depth_usd_25bps")), self._number(intent.get("notional_usd")), 0.000001)
        participation = self._number(intent.get("notional_usd")) / depth
        impact_bps = min(self.max_impact_bps, 25.0 * math.sqrt(max(0.0, participation)))
        passive_fill = policy == "passive_post_only" or (policy == "passive_then_chase" and self._number(fill_row.get("ts")) <= created + self.chase_timeout_sec)
        if passive_fill:
            entry_price = limit_value or entry_mid * (1.0 - entry_spread / 20000.0)
            entry_liquidity = "maker"
            entry_slippage_bps = ((entry_price / reference) - 1.0) * 10000.0
        else:
            entry_price = entry_mid * (1.0 + (entry_spread / 2.0 + impact_bps) / 10000.0)
            entry_liquidity = "taker"
            entry_slippage_bps = ((entry_price / reference) - 1.0) * 10000.0
        exit_price = exit_mid * (1.0 - (exit_spread / 2.0 + impact_bps) / 10000.0)
        exit_slippage_bps = ((exit_mid - exit_price) / exit_mid) * 10000.0 if exit_mid > 0 else 0.0
        entry_fee = profile.maker_fee_bps if entry_liquidity == "maker" else profile.taker_fee_bps
        exit_fee = profile.taker_fee_bps
        fee_bps = entry_fee + exit_fee
        gross = ((exit_mid / entry_mid) - 1.0) * 10000.0 if entry_mid > 0 else 0.0
        net = ((exit_price / entry_price) - 1.0) * 10000.0 - fee_bps if entry_price > 0 else 0.0
        total_cost = gross - net
        predicted_cost = self._number(intent.get("predicted_cost_bps"))
        settlement_id = canonical_hash({"intent": intent.get("shadow_intent_id"), "entry_ts": fill_row.get("ts"), "exit_ts": exit_row.get("ts")})
        return ShadowSettlement(
            settlement_id=settlement_id,
            shadow_intent_id=str(intent.get("shadow_intent_id") or ""),
            forecast_id=str(intent.get("forecast_id") or ""),
            settled_ts=float(settled_ts),
            status="SETTLED",
            fill_model=fill_model,
            fill_ratio=1.0,
            intended_entry_price=limit_value or reference,
            hypothetical_entry_price=entry_price,
            reference_exit_price=exit_mid,
            hypothetical_exit_price=exit_price,
            entry_slippage_bps=entry_slippage_bps,
            exit_slippage_bps=exit_slippage_bps,
            fee_bps=fee_bps,
            impact_bps=impact_bps * 2.0,
            observed_total_cost_bps=total_cost,
            predicted_cost_bps=predicted_cost,
            cost_error_bps=abs(total_cost - predicted_cost),
            gross_directional_return_bps=gross,
            net_return_bps=net,
            profitable_after_costs=net > 0,
            data_quality=min(self._number(fill_row.get("data_quality")), self._number(exit_row.get("data_quality"))),
            diagnostics={
                "entry_observation_ts": self._number(fill_row.get("ts")),
                "exit_observation_ts": self._number(exit_row.get("ts")),
                "entry_liquidity": entry_liquidity,
                "reference_entry_mid": entry_mid,
                "reference_exit_mid": exit_mid,
            },
        )
