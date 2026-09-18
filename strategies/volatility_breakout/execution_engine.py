from __future__ import annotations

import hashlib
import math
import random
import time
from dataclasses import asdict
from typing import Any, Mapping, Optional

from .execution_models import (
    CostAttribution,
    SimulatedFill,
    SimulatedOrderEvent,
    SimulatedOrderIntent,
    SimulationResult,
)
from .venue_profiles import VenueProfile, venue_profile


SCENARIOS: dict[str, dict[str, float]] = {
    "normal": {
        "fee": 1.0, "spread": 1.0, "depth": 1.0, "latency": 1.0,
        "fill": 1.0, "reject": 0.0, "unknown": 0.0, "stale": 0.0,
    },
    "cost_1_5x": {
        "fee": 1.5, "spread": 1.5, "depth": 0.85, "latency": 1.25,
        "fill": 0.95, "reject": 0.0, "unknown": 0.0, "stale": 0.0,
    },
    "cost_2x": {
        "fee": 2.0, "spread": 2.0, "depth": 0.70, "latency": 1.5,
        "fill": 0.90, "reject": 0.0, "unknown": 0.0, "stale": 0.0,
    },
    "liquidity_stress": {
        "fee": 1.0, "spread": 2.25, "depth": 0.45, "latency": 1.75,
        "fill": 0.65, "reject": 0.02, "unknown": 0.0, "stale": 0.03,
    },
    "infrastructure_stress": {
        "fee": 1.0, "spread": 1.4, "depth": 0.75, "latency": 5.0,
        "fill": 0.75, "reject": 0.08, "unknown": 0.08, "stale": 0.08,
    },
}


class DeterministicExecutionSimulator:
    """Execution-aware, replay-deterministic research simulator.

    This component cannot import or invoke a private exchange client. It consumes
    persisted Phase-2 forecasts and market observations only. DOWN forecasts are
    retained for hypothesis comparison but explicitly marked non-executable for
    the spot-only Ember sleeve.
    """

    simulator_version = "phase3.execution.v2"

    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg
        self.simulated_equity_usd = max(1.0, float(getattr(cfg, "phase3_simulated_equity_usd", 1000.0) or 1000.0))
        self.risk_fraction = max(0.00001, float(getattr(cfg, "phase3_risk_fraction", 0.0005) or 0.0005))
        self.sleeve_fraction = max(0.001, float(getattr(cfg, "phase3_sleeve_fraction", 0.02) or 0.02))
        self.max_notional_usd = max(1.0, float(getattr(cfg, "phase3_max_notional_usd", 25.0) or 25.0))
        self.max_depth_participation = max(0.0001, min(0.10, float(getattr(cfg, "phase3_max_depth_participation", 0.01) or 0.01)))
        self.base_latency_ms = max(1.0, float(getattr(cfg, "phase3_base_latency_ms", 180.0) or 180.0))
        self.max_slippage_bps = max(1.0, float(getattr(cfg, "phase3_max_slippage_bps", 75.0) or 75.0))

    @staticmethod
    def _seed(*parts: Any) -> int:
        digest = hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big", signed=False) % ((1 << 63) - 1)

    @staticmethod
    def _clip(value: float, low: float, high: float) -> float:
        return max(low, min(high, float(value)))

    @staticmethod
    def _feature_payload(candidate: Mapping[str, Any]) -> dict[str, Any]:
        forecast_payload = candidate.get("forecast_payload") or {}
        observation = candidate.get("entry_observation") or {}
        values = observation.get("values") or {}
        feature = values.get("feature_vector") or {}
        return {
            **feature,
            "spread_bps": observation.get("spread_bps", feature.get("spread_bps")),
            "depth_usd_25bps": observation.get("depth_usd_25bps", feature.get("depth_usd_25bps")),
            "quote_volume_24h": observation.get("quote_volume_24h", feature.get("quote_volume_24h")),
            "data_quality": observation.get("data_quality", feature.get("data_quality")),
            "forecast_inputs": forecast_payload.get("inputs") or {},
        }

    @staticmethod
    def _symbol_class(candidate: Mapping[str, Any], features: Mapping[str, Any]) -> str:
        forecast_payload = candidate.get("forecast_payload") if isinstance(candidate.get("forecast_payload"), dict) else {}
        inputs = forecast_payload.get("inputs") if isinstance(forecast_payload.get("inputs"), dict) else {}
        explicit = inputs.get("symbol_class") or features.get("symbol_class")
        if explicit:
            return str(explicit)
        spread_bps = max(0.0, float(features.get("spread_bps") or 0.0))
        depth_usd = max(0.0, float(features.get("depth_usd_25bps") or 0.0))
        volume_24h = max(0.0, float(features.get("quote_volume_24h") or 0.0))
        vol_fast = max(0.0, float(features.get("realized_volatility_fast") or 0.0))
        if depth_usd >= 400_000.0 and spread_bps <= 8.0 and volume_24h >= 75_000_000.0:
            return "ultra_liquid_major"
        if depth_usd >= 150_000.0 and spread_bps <= 18.0 and volume_24h >= 20_000_000.0:
            return "general_liquid"
        if vol_fast >= 0.015 and volume_24h <= 2_000_000.0 and spread_bps <= 200.0:
            return "niche_high_volatility"
        if spread_bps >= 30.0 or depth_usd <= 80_000.0:
            return "hostile_liquidity"
        if vol_fast >= 0.02 and volume_24h >= 5_000_000.0:
            return "event_spike_alt"
        return "mean_reverting_liquid"

    @staticmethod
    def _failure_causes(
        *,
        status: str,
        direction: str,
        spread_bps: float,
        latency_ms: float,
        fill_ratio: float,
        gross_bps: float,
        net_bps: float,
        stop_bps: float,
        exit_reason: Optional[str],
        rejection_reason: Optional[str] = None,
        incidents: tuple[Mapping[str, Any], ...] = (),
    ) -> list[str]:
        causes: list[str] = []
        if rejection_reason == "SPREAD_ABOVE_GATE":
            causes.append("spread_too_wide")
        elif rejection_reason == "DATA_QUALITY_BELOW_GATE":
            causes.append("stale_or_low_quality_data")
        elif rejection_reason == "BELOW_MIN_NOTIONAL":
            causes.append("insufficient_size_for_execution")
        elif rejection_reason == "BELOW_MIN_QUANTITY":
            causes.append("quantity_rounded_below_minimum")
        elif rejection_reason == "SIMULATED_VENUE_REJECTION":
            causes.append("venue_rejection")
        elif rejection_reason == "STALE_MARKET_DATA":
            causes.append("stale_or_low_quality_data")

        if status == "EXPIRED":
            causes.append("late_entry_or_missed_fill")
        if any(str(item.get("type") or "") == "UNKNOWN_ORDER_STATE" for item in incidents):
            causes.append("unknown_order_state")
        if status == "COMPLETED":
            if fill_ratio < 0.85:
                causes.append("partial_fill_drag")
            if spread_bps >= 20.0:
                causes.append("spread_too_wide")
            if latency_ms >= 600.0:
                causes.append("late_entry")
            if exit_reason == "STOP_LOSS_PROXY":
                causes.append("wrong_regime")
                if gross_bps <= -max(stop_bps, 1.0):
                    causes.append("false_breakout")
            if net_bps <= 0.0 and direction == "UP" and exit_reason == "HORIZON_EXIT_PROXY":
                causes.append("no_follow_through")
            if net_bps <= 0.0 and gross_bps > 0.0:
                causes.append("cost_drag")
        deduped: list[str] = []
        seen = set()
        for cause in causes:
            if cause not in seen:
                deduped.append(cause)
                seen.add(cause)
        return deduped

    def _sizing(self, candidate: Mapping[str, Any], profile: VenueProfile, depth_usd: float) -> dict[str, float]:
        features = self._feature_payload(candidate)
        expected_move = abs(float(candidate.get("expected_move_bps") or 0.0))
        atr_pct = float(features.get("atr_pct") or features.get("realized_volatility_fast") or 0.0)
        stop_bps = self._clip(max(expected_move * 0.75, atr_pct * 10_000.0 * 1.25, 35.0), 35.0, 350.0)
        target_bps = self._clip(max(expected_move * 1.25, stop_bps * 1.5, 50.0), 50.0, 600.0)
        risk_budget = self.simulated_equity_usd * self.risk_fraction
        risk_sized_notional = risk_budget / max(stop_bps / 10_000.0, 0.000001)
        sleeve_cap = self.simulated_equity_usd * self.sleeve_fraction
        depth_cap = max(0.0, depth_usd) * self.max_depth_participation
        notional = min(risk_sized_notional, sleeve_cap, depth_cap, self.max_notional_usd)
        price = float(candidate.get("entry_price") or 0.0)
        quantity = profile.round_quantity(notional / price) if price > 0 else 0.0
        notional = quantity * price
        return {
            "stop_bps": stop_bps,
            "target_bps": target_bps,
            "risk_budget_usd": risk_budget,
            "quantity": quantity,
            "notional_usd": notional,
        }

    def simulate(
        self,
        candidate: Mapping[str, Any],
        *,
        run_id: str,
        order_policy: str,
        scenario: str,
    ) -> SimulationResult:
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario: {scenario}")
        if order_policy not in {"market", "marketable_limit", "passive_post_only", "passive_then_chase"}:
            raise ValueError(f"unknown order policy: {order_policy}")

        forecast_id = str(candidate.get("forecast_id") or "")
        direction = str(candidate.get("direction") or "ABSTAIN").upper()
        venue = str(candidate.get("venue") or "kraken").lower()
        symbol = str(candidate.get("symbol") or "")
        profile = venue_profile(venue, self.cfg)
        seed = self._seed(forecast_id, order_policy, scenario, self.simulator_version)
        rng = random.Random(seed)
        scenario_cfg = SCENARIOS[scenario]
        simulation_id = hashlib.sha256(f"{forecast_id}:{order_policy}:{scenario}:{self.simulator_version}".encode()).hexdigest()
        started_ts = float(candidate.get("forecast_ts") or time.time())
        completed_ts = float(candidate.get("settled_ts") or started_ts)
        entry_mid = float(candidate.get("entry_price") or 0.0)
        exit_mid = float(candidate.get("exit_price") or 0.0)
        features = self._feature_payload(candidate)
        symbol_class = self._symbol_class(candidate, features)
        spread_bps = max(0.0, float(features.get("spread_bps") or 0.0)) * scenario_cfg["spread"]
        depth_usd = max(0.0, float(features.get("depth_usd_25bps") or 0.0)) * scenario_cfg["depth"]
        data_quality = float(features.get("data_quality") or 0.0)
        sizing = self._sizing(candidate, profile, depth_usd)
        quantity = sizing["quantity"]
        notional = sizing["notional_usd"]
        spot_executable = direction == "UP"
        intent_id = hashlib.sha256(f"intent:{simulation_id}".encode()).hexdigest()
        side = "BUY" if direction == "UP" else "SELL_SHORT_SYNTHETIC"
        limit_price: Optional[float] = None
        if order_policy in {"marketable_limit", "passive_post_only", "passive_then_chase"} and entry_mid > 0:
            offset = spread_bps / 20_000.0
            if direction == "UP":
                limit_price = entry_mid * (1.0 + (offset if order_policy == "marketable_limit" else -offset))
            else:
                limit_price = entry_mid * (1.0 - (offset if order_policy == "marketable_limit" else -offset))
            limit_price = profile.round_price(limit_price)

        intent = SimulatedOrderIntent(
            intent_id=intent_id,
            simulation_id=simulation_id,
            forecast_id=forecast_id,
            model_id=str(candidate.get("model_id") or ""),
            venue=venue,
            symbol=symbol,
            side=side,
            order_policy=order_policy,
            scenario=scenario,
            quantity=quantity,
            notional_usd=notional,
            reference_price=entry_mid,
            limit_price=limit_price,
            risk_budget_usd=sizing["risk_budget_usd"],
            stop_distance_bps=sizing["stop_bps"],
            horizon_seconds=int(candidate.get("horizon_seconds") or 0),
            created_ts=started_ts,
            spot_executable=spot_executable,
            live_eligible=False,
        )

        events: list[SimulatedOrderEvent] = []
        fills: list[SimulatedFill] = []
        incidents: list[Mapping[str, Any]] = []
        seq = 0

        def event(state: str, reason: str, **details: Any) -> None:
            nonlocal seq
            seq += 1
            events.append(SimulatedOrderEvent(seq, state, started_ts + seq * 0.001, reason, details))

        event("CREATED", "forecast_converted_to_simulated_intent")
        invalid_reason = None
        if not forecast_id or direction not in {"UP", "DOWN"}:
            invalid_reason = "INVALID_FORECAST"
        elif entry_mid <= 0 or exit_mid <= 0:
            invalid_reason = "PRICE_UNAVAILABLE"
        elif data_quality < float(getattr(self.cfg, "phase3_min_data_quality", 0.99) or 0.99):
            invalid_reason = "DATA_QUALITY_BELOW_GATE"
        elif quantity < profile.min_quantity:
            invalid_reason = "BELOW_MIN_QUANTITY"
        elif notional < profile.min_notional_usd:
            invalid_reason = "BELOW_MIN_NOTIONAL"
        elif spread_bps > float(getattr(self.cfg, "phase3_max_entry_spread_bps", 60.0) or 60.0):
            invalid_reason = "SPREAD_ABOVE_GATE"

        zero_costs = CostAttribution(
            forecast_gross_bps=float(candidate.get("directional_return_bps") or 0.0),
            market_gross_bps=0.0,
            entry_spread_bps=0.0,
            exit_spread_bps=0.0,
            entry_impact_bps=0.0,
            exit_impact_bps=0.0,
            entry_latency_bps=0.0,
            exit_latency_bps=0.0,
            fee_bps=0.0,
            missed_fill_opportunity_bps=0.0,
            stop_slippage_bps=0.0,
            total_cost_bps=0.0,
            net_bps=0.0,
        )

        if invalid_reason:
            event("REJECTED", invalid_reason)
            failure_causes = self._failure_causes(
                status="REJECTED",
                direction=direction,
                spread_bps=spread_bps,
                latency_ms=0.0,
                fill_ratio=0.0,
                gross_bps=0.0,
                net_bps=0.0,
                stop_bps=sizing["stop_bps"],
                exit_reason=None,
                rejection_reason=invalid_reason,
                incidents=tuple(incidents),
            )
            return SimulationResult(
                simulation_id, run_id, forecast_id, str(candidate.get("model_id") or ""),
                str(candidate.get("hypothesis") or ""), venue, symbol, direction,
                order_policy, scenario, "OBSERVATION_PROXY", seed, "REJECTED", "REJECTED",
                started_ts, completed_ts, 0.0, quantity, 0.0, notional, entry_mid, exit_mid,
                None, None, 0.0, 0.0, False, spot_executable, False, 0, intent,
                tuple(events), tuple(), zero_costs, tuple(incidents),
                {
                    "rejection_reason": invalid_reason,
                    "venue_profile": asdict(profile),
                    "symbol_class": symbol_class,
                    "failure_causes": failure_causes,
                },
            )

        event("VALIDATED", "venue_and_risk_rules_passed", venue_profile=profile.profile_version)
        event("PERSISTED", "intent_persisted_before_submission")

        if rng.random() < scenario_cfg["stale"]:
            event("REJECTED", "STALE_MARKET_DATA")
            incidents.append({"type": "STALE_MARKET_DATA", "severity": "HIGH", "symbol_halted": True})
            failure_causes = self._failure_causes(
                status="REJECTED",
                direction=direction,
                spread_bps=spread_bps,
                latency_ms=0.0,
                fill_ratio=0.0,
                gross_bps=0.0,
                net_bps=0.0,
                stop_bps=sizing["stop_bps"],
                exit_reason=None,
                rejection_reason="STALE_MARKET_DATA",
                incidents=tuple(incidents),
            )
            return SimulationResult(
                simulation_id, run_id, forecast_id, str(candidate.get("model_id") or ""),
                str(candidate.get("hypothesis") or ""), venue, symbol, direction,
                order_policy, scenario, "OBSERVATION_PROXY", seed, "REJECTED", "REJECTED",
                started_ts, completed_ts, 0.0, quantity, 0.0, notional, entry_mid, exit_mid,
                None, None, 0.0, 0.0, False, spot_executable, False, 0, intent,
                tuple(events), tuple(), zero_costs, tuple(incidents),
                {
                    "rejection_reason": "STALE_MARKET_DATA",
                    "venue_profile": asdict(profile),
                    "symbol_class": symbol_class,
                    "failure_causes": failure_causes,
                },
            )

        event("SUBMITTED_SIMULATED", "private_exchange_call_prohibited")
        if rng.random() < scenario_cfg["reject"]:
            event("REJECTED", "SIMULATED_VENUE_REJECTION")
            failure_causes = self._failure_causes(
                status="REJECTED",
                direction=direction,
                spread_bps=spread_bps,
                latency_ms=0.0,
                fill_ratio=0.0,
                gross_bps=0.0,
                net_bps=0.0,
                stop_bps=sizing["stop_bps"],
                exit_reason=None,
                rejection_reason="SIMULATED_VENUE_REJECTION",
                incidents=tuple(incidents),
            )
            return SimulationResult(
                simulation_id, run_id, forecast_id, str(candidate.get("model_id") or ""),
                str(candidate.get("hypothesis") or ""), venue, symbol, direction,
                order_policy, scenario, "OBSERVATION_PROXY", seed, "REJECTED", "REJECTED",
                started_ts, completed_ts, 0.0, quantity, 0.0, notional, entry_mid, exit_mid,
                None, None, 0.0, 0.0, False, spot_executable, False, 0, intent,
                tuple(events), tuple(), zero_costs, tuple(incidents),
                {
                    "rejection_reason": "SIMULATED_VENUE_REJECTION",
                    "venue_profile": asdict(profile),
                    "symbol_class": symbol_class,
                    "failure_causes": failure_causes,
                },
            )

        latency_ms = self.base_latency_ms * scenario_cfg["latency"] * rng.uniform(0.65, 1.45)
        if rng.random() < scenario_cfg["unknown"]:
            event("UNKNOWN", "ACKNOWLEDGEMENT_TIMEOUT", latency_ms=latency_ms)
            incidents.append({
                "type": "UNKNOWN_ORDER_STATE", "severity": "CRITICAL",
                "symbol_halted": True, "automatic_recovery": False,
            })
            event("RECONCILIATION_PENDING", "symbol_halted_until_evidence_reconciled")
            event("RECONCILED", "simulation_truth_recovered_from_persisted_evidence")
        else:
            event("ACKNOWLEDGED", "simulated_venue_acknowledgement", latency_ms=latency_ms)

        participation = notional / max(depth_usd, notional, 0.000001)
        impact_bps = min(self.max_slippage_bps, 25.0 * math.sqrt(max(0.0, participation)))
        latency_bps = min(self.max_slippage_bps, (latency_ms / 1000.0) * max(1.0, abs(float(candidate.get("expected_move_bps") or 0.0)) / max(int(candidate.get("horizon_seconds") or 60), 60)) * 4.0)
        base_fill_probability = {
            "market": 1.0,
            "marketable_limit": 0.98,
            "passive_post_only": 0.58,
            "passive_then_chase": 0.90,
        }[order_policy]
        directional_market_bps = float(candidate.get("directional_return_bps") or 0.0)
        if order_policy == "passive_post_only":
            base_fill_probability -= min(0.30, max(0.0, directional_market_bps) / 1000.0)
        fill_probability = self._clip(base_fill_probability * scenario_cfg["fill"], 0.05, 1.0)
        filled = rng.random() <= fill_probability
        if not filled:
            event("OPEN", "passive_order_waiting")
            event("EXPIRED", "signal_horizon_reached_without_fill")
            missed = max(0.0, directional_market_bps)
            costs = CostAttribution(
                float(candidate.get("directional_return_bps") or 0.0), 0.0, 0.0, 0.0,
                0.0, 0.0, 0.0, 0.0, 0.0, missed, 0.0, missed, 0.0,
                gross_signal_bps=float(candidate.get("directional_return_bps") or 0.0),
                failed_fill_cost_bps=round(missed, 6),
                cost_schema_version="phase3.cost_attribution.v2",
                fee_source="configured_research_profile_unverified",
                fee_verified=False,
            )
            failure_causes = self._failure_causes(
                status="EXPIRED",
                direction=direction,
                spread_bps=spread_bps,
                latency_ms=latency_ms,
                fill_ratio=0.0,
                gross_bps=0.0,
                net_bps=0.0,
                stop_bps=sizing["stop_bps"],
                exit_reason=None,
                incidents=tuple(incidents),
            )
            return SimulationResult(
                simulation_id, run_id, forecast_id, str(candidate.get("model_id") or ""),
                str(candidate.get("hypothesis") or ""), venue, symbol, direction,
                order_policy, scenario, "OBSERVATION_PROXY", seed, "EXPIRED", "EXPIRED",
                started_ts, completed_ts, 0.0, quantity, 0.0, notional, entry_mid, exit_mid,
                None, None, 0.0, 0.0, False, spot_executable, False, 0, intent,
                tuple(events), tuple(), costs, tuple(incidents),
                {
                    "fill_probability": fill_probability,
                    "venue_profile": asdict(profile),
                    "symbol_class": symbol_class,
                    "failure_causes": failure_causes,
                },
            )

        fill_ratio_base = {
            "market": 1.0,
            "marketable_limit": 0.96,
            "passive_post_only": 0.72,
            "passive_then_chase": 0.92,
        }[order_policy]
        fill_ratio = self._clip(fill_ratio_base * scenario_cfg["fill"] * rng.uniform(0.88, 1.05), 0.10, 1.0)
        if order_policy == "market":
            fill_ratio = 1.0
        quantity_filled = profile.round_quantity(quantity * fill_ratio)
        if quantity_filled <= 0:
            event("EXPIRED", "rounded_fill_below_minimum")
            failure_causes = self._failure_causes(
                status="EXPIRED",
                direction=direction,
                spread_bps=spread_bps,
                latency_ms=latency_ms,
                fill_ratio=0.0,
                gross_bps=0.0,
                net_bps=0.0,
                stop_bps=sizing["stop_bps"],
                exit_reason=None,
                rejection_reason="BELOW_MIN_QUANTITY",
                incidents=tuple(incidents),
            )
            return SimulationResult(
                simulation_id, run_id, forecast_id, str(candidate.get("model_id") or ""),
                str(candidate.get("hypothesis") or ""), venue, symbol, direction,
                order_policy, scenario, "OBSERVATION_PROXY", seed, "EXPIRED", "EXPIRED",
                started_ts, completed_ts, 0.0, quantity, 0.0, notional, entry_mid, exit_mid,
                None, None, 0.0, 0.0, False, spot_executable, False, 0, intent,
                tuple(events), tuple(), zero_costs, tuple(incidents),
                {
                    "fill_probability": fill_probability,
                    "venue_profile": asdict(profile),
                    "symbol_class": symbol_class,
                    "failure_causes": failure_causes,
                },
            )

        entry_spread_factor = {
            "market": 0.50,
            "marketable_limit": 0.38,
            "passive_post_only": -0.20,
            "passive_then_chase": 0.18,
        }[order_policy]
        entry_impact_factor = {
            "market": 1.0,
            "marketable_limit": 0.72,
            "passive_post_only": 0.05,
            "passive_then_chase": 0.42,
        }[order_policy]
        entry_latency_factor = {
            "market": 1.0,
            "marketable_limit": 0.75,
            "passive_post_only": 0.10,
            "passive_then_chase": 0.55,
        }[order_policy]
        entry_spread = spread_bps * entry_spread_factor
        exit_spread = spread_bps * 0.50
        entry_impact = impact_bps * entry_impact_factor
        exit_impact = impact_bps * 0.80
        entry_latency = latency_bps * entry_latency_factor
        exit_latency = latency_bps * 0.80
        maker_fraction = 1.0 if order_policy == "passive_post_only" else (0.50 if order_policy == "passive_then_chase" else 0.0)
        fee_per_side = profile.taker_fee_bps * (1.0 - maker_fraction) + profile.maker_fee_bps * maker_fraction
        entry_fee_bps = fee_per_side * scenario_cfg["fee"]
        exit_fee_bps = profile.taker_fee_bps * scenario_cfg["fee"]
        maker_fee_bps = (profile.maker_fee_bps * maker_fraction) * scenario_cfg["fee"]
        taker_fee_bps = (profile.taker_fee_bps * (1.0 - maker_fraction) + profile.taker_fee_bps) * scenario_cfg["fee"]
        fee_bps = entry_fee_bps + exit_fee_bps
        chase_cost_bps = 0.0
        if order_policy == "passive_then_chase":
            chase_cost_bps = max(0.0, spread_bps * 0.20 + entry_latency * 0.35)
            fee_bps += chase_cost_bps

        entry_penalty = entry_spread + entry_impact + entry_latency
        exit_penalty = exit_spread + exit_impact + exit_latency
        if direction == "UP":
            entry_fill = entry_mid * (1.0 + entry_penalty / 10_000.0)
            exit_fill = exit_mid * (1.0 - exit_penalty / 10_000.0)
            gross_bps = ((exit_fill - entry_fill) / entry_fill) * 10_000.0
            entry_side, exit_side = "BUY", "SELL"
        else:
            entry_fill = entry_mid * (1.0 - entry_penalty / 10_000.0)
            exit_fill = exit_mid * (1.0 + exit_penalty / 10_000.0)
            gross_bps = ((entry_fill - exit_fill) / entry_fill) * 10_000.0
            entry_side, exit_side = "SELL_SHORT_SYNTHETIC", "BUY_TO_COVER_SYNTHETIC"
        entry_fill = profile.round_price(entry_fill)
        exit_fill = profile.round_price(exit_fill)
        filled_notional = quantity_filled * entry_fill
        fee_entry_usd = filled_notional * (fee_per_side * scenario_cfg["fee"] / 10_000.0)
        fee_exit_usd = quantity_filled * exit_fill * (profile.taker_fee_bps * scenario_cfg["fee"] / 10_000.0)

        event("OPEN", "simulated_order_entered_book")
        if fill_ratio < 0.999:
            event("PARTIALLY_FILLED", "available_proxy_liquidity_consumed", fill_ratio=fill_ratio)
        else:
            event("FILLED", "entry_fully_filled")
        fills.append(SimulatedFill(
            hashlib.sha256(f"entry:{simulation_id}".encode()).hexdigest(), "ENTRY", entry_side,
            quantity_filled, entry_fill, filled_notional, fee_entry_usd,
            "MAKER" if maker_fraction >= 1.0 else ("MIXED" if maker_fraction > 0 else "TAKER"),
            started_ts + latency_ms / 1000.0,
        ))
        if gross_bps <= -sizing["stop_bps"]:
            exit_reason = "STOP_LOSS_PROXY"
        elif gross_bps >= sizing["target_bps"]:
            exit_reason = "TARGET_HIT_PROXY"
        else:
            exit_reason = "HORIZON_EXIT_PROXY"
        event(
            "EXIT_TRIGGERED",
            exit_reason,
            stop_bps=round(sizing["stop_bps"], 6),
            target_bps=round(sizing["target_bps"], 6),
        )
        fills.append(SimulatedFill(
            hashlib.sha256(f"exit:{simulation_id}".encode()).hexdigest(), "EXIT", exit_side,
            quantity_filled, exit_fill, quantity_filled * exit_fill, fee_exit_usd, "TAKER", completed_ts,
        ))
        event("CLOSED", "round_trip_simulation_complete")

        net_bps = gross_bps - fee_bps
        total_cost = entry_spread + exit_spread + entry_impact + exit_impact + entry_latency + exit_latency + fee_bps
        stop_slippage = max(0.0, -gross_bps - sizing["stop_bps"])
        fee_verified = profile.fee_verified
        fee_source = profile.fee_source
        costs = CostAttribution(
            forecast_gross_bps=float(candidate.get("directional_return_bps") or 0.0),
            market_gross_bps=round(gross_bps + fee_bps, 6),
            entry_spread_bps=round(entry_spread, 6),
            exit_spread_bps=round(exit_spread, 6),
            entry_impact_bps=round(entry_impact, 6),
            exit_impact_bps=round(exit_impact, 6),
            entry_latency_bps=round(entry_latency, 6),
            exit_latency_bps=round(exit_latency, 6),
            fee_bps=round(fee_bps, 6),
            missed_fill_opportunity_bps=0.0,
            stop_slippage_bps=round(stop_slippage, 6),
            total_cost_bps=round(total_cost, 6),
            net_bps=round(net_bps, 6),
            gross_signal_bps=round(float(candidate.get("directional_return_bps") or 0.0), 6),
            entry_fee_bps=round(entry_fee_bps, 6),
            exit_fee_bps=round(exit_fee_bps, 6),
            maker_fee_bps=round(maker_fee_bps, 6),
            taker_fee_bps=round(taker_fee_bps, 6),
            failed_fill_cost_bps=0.0,
            chase_cost_bps=round(chase_cost_bps, 6),
            cost_schema_version="phase3.cost_attribution.v2",
            fee_source=fee_source if fee_verified else f"{fee_source}:unverified",
            fee_verified=fee_verified,
        )
        terminal_state = "RECONCILED" if incidents else "CLOSED"
        failure_causes = self._failure_causes(
            status="COMPLETED",
            direction=direction,
            spread_bps=spread_bps,
            latency_ms=latency_ms,
            fill_ratio=fill_ratio,
            gross_bps=gross_bps,
            net_bps=net_bps,
            stop_bps=sizing["stop_bps"],
            exit_reason=exit_reason,
            incidents=tuple(incidents),
        )
        return SimulationResult(
            simulation_id=simulation_id,
            run_id=run_id,
            forecast_id=forecast_id,
            model_id=str(candidate.get("model_id") or ""),
            hypothesis=str(candidate.get("hypothesis") or ""),
            venue=venue,
            symbol=symbol,
            direction=direction,
            order_policy=order_policy,
            scenario=scenario,
            fidelity="OBSERVATION_PROXY",
            seed=seed,
            status="COMPLETED",
            terminal_state=terminal_state,
            started_ts=started_ts,
            completed_ts=completed_ts,
            fill_ratio=round(fill_ratio, 6),
            quantity_requested=quantity,
            quantity_filled=quantity_filled,
            notional_requested_usd=notional,
            entry_reference_price=entry_mid,
            exit_reference_price=exit_mid,
            entry_fill_price=entry_fill,
            exit_fill_price=exit_fill,
            gross_return_bps=round(gross_bps, 6),
            net_return_bps=round(net_bps, 6),
            profitable_after_costs=net_bps > 0,
            spot_executable=spot_executable,
            execution_wired=False,
            real_orders_submitted=0,
            intent=intent,
            events=tuple(events),
            fills=tuple(fills),
            costs=costs,
            incidents=tuple(incidents),
            diagnostics={
                "simulator_version": self.simulator_version,
                "venue_profile": asdict(profile),
                "symbol_class": symbol_class,
                "failure_causes": failure_causes,
                "fee_verification": {
                    "verified": fee_verified,
                    "source": fee_source,
                    "economics_receipt_sha256": profile.economics_receipt_sha256,
                    "execution_edge_treatment": "research_only_until_account_fee_tier_verified",
                },
                "cost_components": {
                    "gross_signal_bps": round(float(candidate.get("directional_return_bps") or 0.0), 6),
                    "entry_fee_bps": round(entry_fee_bps, 6),
                    "exit_fee_bps": round(exit_fee_bps, 6),
                    "maker_fee_bps": round(maker_fee_bps, 6),
                    "taker_fee_bps": round(taker_fee_bps, 6),
                    "chase_cost_bps": round(chase_cost_bps, 6),
                    "spread_bps": round(entry_spread + exit_spread, 6),
                    "impact_bps": round(entry_impact + exit_impact, 6),
                    "latency_bps": round(entry_latency + exit_latency, 6),
                },
                "fill_probability": round(fill_probability, 6),
                "latency_ms": round(latency_ms, 6),
                "data_quality": data_quality,
                "participation_rate": round(participation, 8),
                "depth_usd_25bps_stressed": depth_usd,
                "spread_bps_stressed": spread_bps,
                "stop_bps": round(sizing["stop_bps"], 6),
                "target_bps": round(sizing["target_bps"], 6),
                "exit_reason": exit_reason,
                "spot_note": "DOWN forecasts are synthetic research only" if not spot_executable else "spot-long compatible",
            },
        )
