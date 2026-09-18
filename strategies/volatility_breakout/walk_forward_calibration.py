from __future__ import annotations

import hashlib
import json
import math
from statistics import stdev
from typing import Any


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _wilson_lower(successes: int, samples: int, z_score: float) -> float:
    if samples <= 0:
        return 0.0
    probability = float(successes) / float(samples)
    z2 = z_score * z_score
    denominator = 1.0 + z2 / samples
    centre = probability + z2 / (2.0 * samples)
    margin = z_score * math.sqrt(
        (probability * (1.0 - probability) / samples) + (z2 / (4.0 * samples * samples))
    )
    return max(0.0, (centre - margin) / denominator)


def _winsorized(values: list[float], tail_fraction: float) -> list[float]:
    if len(values) < 10 or tail_fraction <= 0.0:
        return list(values)
    ordered = sorted(float(value) for value in values)
    tail = min((len(ordered) - 1) // 2, max(1, int(len(ordered) * tail_fraction)))
    low = ordered[tail]
    high = ordered[-tail - 1]
    return [max(low, min(high, value)) for value in values]


class WalkForwardForecastCalibrator:
    """Leakage-safe empirical selector for Phase-2 research forecasts."""

    version = "phase2.walk_forward_calibration.v1"

    def __init__(self, cfg: Any, data_store: Any) -> None:
        self.cfg = cfg
        self.data_store = data_store
        self.enabled = bool(getattr(cfg, "phase2_walk_forward_calibration_enabled", True))
        self.max_samples = max(30, int(getattr(cfg, "phase2_calibration_max_samples", 250) or 250))
        self.min_slice_samples = max(5, int(getattr(cfg, "phase2_calibration_min_slice_samples", 12) or 12))
        self.min_regime_samples = max(
            self.min_slice_samples,
            int(getattr(cfg, "phase2_calibration_min_regime_samples", 18) or 18),
        )
        self.min_model_samples = max(
            self.min_regime_samples,
            int(getattr(cfg, "phase2_calibration_min_model_samples", 30) or 30),
        )
        self.min_distinct_symbols = max(
            1, int(getattr(cfg, "phase2_calibration_min_distinct_symbols", 3) or 3)
        )
        self.min_distinct_time_buckets = max(
            1, int(getattr(cfg, "phase2_calibration_min_distinct_time_buckets", 3) or 3)
        )
        self.stress_cost_multiple = max(
            1.0, float(getattr(cfg, "phase2_calibration_stress_cost_multiple", 1.5) or 1.5)
        )
        self.prior_strength = max(
            0.0, float(getattr(cfg, "phase2_calibration_prior_strength", 12.0) or 12.0)
        )
        self.z_score = max(0.0, float(getattr(cfg, "phase2_calibration_one_sided_z", 1.645) or 1.645))
        self.winsor_tail_fraction = max(
            0.0,
            min(0.20, float(getattr(cfg, "phase2_calibration_winsor_tail_fraction", 0.05) or 0.05)),
        )
        self.min_stressed_lower_bound_bps = float(
            getattr(cfg, "phase2_calibration_min_stressed_lower_bound_bps", 0.0) or 0.0
        )
        self.min_probability_lower_bound = max(
            0.0,
            min(
                1.0,
                float(getattr(cfg, "phase2_calibration_min_probability_lower_bound", 0.50) or 0.50),
            ),
        )
        self.config_hash = _canonical_hash(self.manifest())

    def manifest(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "enabled": self.enabled,
            "max_samples": self.max_samples,
            "minimum_samples": {
                "model_horizon_regime_symbol_class": self.min_slice_samples,
                "model_horizon_regime": self.min_regime_samples,
                "model_horizon": self.min_model_samples,
            },
            "minimum_distinct_symbols": self.min_distinct_symbols,
            "minimum_distinct_time_buckets": self.min_distinct_time_buckets,
            "stress_cost_multiple": self.stress_cost_multiple,
            "prior_strength": self.prior_strength,
            "one_sided_z": self.z_score,
            "winsor_tail_fraction": self.winsor_tail_fraction,
            "minimum_stressed_lower_bound_bps": self.min_stressed_lower_bound_bps,
            "minimum_probability_lower_bound": self.min_probability_lower_bound,
            "authority": "research_filter_only",
            "execution_authority": "none",
        }

    @staticmethod
    def _scope(row: dict[str, Any]) -> tuple[str, str]:
        inputs = row.get("inputs") if isinstance(row.get("inputs"), dict) else {}
        regime_inputs = inputs.get("regime_inputs") if isinstance(inputs.get("regime_inputs"), dict) else {}
        return (
            str(regime_inputs.get("regime_hint") or inputs.get("regime_hint") or "unknown"),
            str(inputs.get("symbol_class") or "unknown"),
        )

    def _select_samples(
        self,
        samples: list[dict[str, Any]],
        *,
        regime_hint: str,
        symbol_class: str,
    ) -> tuple[str | None, list[dict[str, Any]]]:
        exact = []
        if regime_hint != "unknown" and symbol_class != "unknown":
            exact = [
                sample for sample in samples
                if sample.get("regime_hint") == regime_hint and sample.get("symbol_class") == symbol_class
            ]
        if len(exact) >= self.min_slice_samples:
            return "model_horizon_regime_symbol_class", exact
        regime = []
        if regime_hint != "unknown":
            regime = [sample for sample in samples if sample.get("regime_hint") == regime_hint]
        if len(regime) >= self.min_regime_samples:
            return "model_horizon_regime", regime
        if len(samples) >= self.min_model_samples:
            return "model_horizon", samples
        return None, []

    def _distribution(self, values: list[float]) -> dict[str, Any]:
        winsorized = _winsorized(values, self.winsor_tail_fraction)
        samples = len(winsorized)
        raw_mean = sum(winsorized) / samples
        shrinkage_weight = samples / (samples + self.prior_strength) if samples else 0.0
        posterior_mean = raw_mean * shrinkage_weight
        standard_error = (stdev(winsorized) / math.sqrt(samples)) if samples > 1 else float("inf")
        lower_bound = posterior_mean - self.z_score * standard_error
        successes = sum(1 for value in values if value > 0.0)
        return {
            "samples": samples,
            "raw_winsorized_mean_bps": round(raw_mean, 6),
            "posterior_mean_bps": round(posterior_mean, 6),
            "standard_error_bps": round(standard_error, 6) if math.isfinite(standard_error) else None,
            "lower_bound_bps": round(lower_bound, 6) if math.isfinite(lower_bound) else None,
            "win_rate": round(successes / samples, 6),
            "probability_positive_lower_bound": round(_wilson_lower(successes, samples, self.z_score), 6),
        }

    def _receipt(
        self,
        row: dict[str, Any],
        samples: list[dict[str, Any]],
        *,
        cutoff_ts: float,
    ) -> dict[str, Any]:
        regime_hint, symbol_class = self._scope(row)
        selected_scope, selected = self._select_samples(
            samples, regime_hint=regime_hint, symbol_class=symbol_class
        )
        base = None
        stressed = None
        reasons: list[str] = []
        decision = "INSUFFICIENT_EVIDENCE"
        distinct_symbols = 0
        distinct_time_buckets = 0
        if selected:
            base_values = [
                float(sample.get("directional_return_bps") or 0.0)
                - float(sample.get("expected_cost_bps") or 0.0)
                for sample in selected
            ]
            stressed_values = [
                float(sample.get("directional_return_bps") or 0.0)
                - self.stress_cost_multiple * float(sample.get("expected_cost_bps") or 0.0)
                for sample in selected
            ]
            base = self._distribution(base_values)
            stressed = self._distribution(stressed_values)
            distinct_symbols = len({str(sample.get("symbol") or "unknown") for sample in selected})
            distinct_time_buckets = len(
                {int(float(sample.get("forecast_ts") or 0.0) // 3600) for sample in selected}
            )
            if distinct_symbols < self.min_distinct_symbols:
                reasons.append("insufficient_symbol_breadth")
            if distinct_time_buckets < self.min_distinct_time_buckets:
                reasons.append("insufficient_time_breadth")
            if float(stressed.get("lower_bound_bps") or float("-inf")) < self.min_stressed_lower_bound_bps:
                reasons.append("stressed_return_lower_bound_below_gate")
            if (
                float(stressed.get("probability_positive_lower_bound") or 0.0)
                < self.min_probability_lower_bound
            ):
                reasons.append("stressed_probability_lower_bound_below_gate")
            decision = "ALLOW" if not reasons else "REFUSE"
        else:
            reasons.append("minimum_walk_forward_samples_not_met")
        evidence_ids = sorted(str(sample.get("forecast_id") or "") for sample in selected)
        body = {
            "schema": "phase2_walk_forward_calibration_receipt_v1",
            "version": self.version,
            "model_id": row.get("model_id"),
            "horizon_seconds": int(row.get("horizon_seconds") or 0),
            "regime_hint": regime_hint,
            "symbol_class": symbol_class,
            "cutoff_ts": float(cutoff_ts),
            "selected_scope": selected_scope,
            "sample_count": len(selected),
            "distinct_symbols": distinct_symbols,
            "distinct_time_buckets": distinct_time_buckets,
            "latest_settled_ts": max((float(sample.get("settled_ts") or 0.0) for sample in selected), default=None),
            "history_root": _canonical_hash(evidence_ids),
            "config_hash": self.config_hash,
            "base_cost_distribution": base,
            "stressed_cost_distribution": stressed,
            "stress_cost_multiple": self.stress_cost_multiple,
            "evidence_sufficient": bool(selected),
            "decision": decision,
            "reasons": reasons,
            "authority": "research_filter_only",
            "execution_eligible": False,
        }
        body["receipt_id"] = _canonical_hash(body)
        return body

    def calibrate_rows(self, rows: list[dict[str, Any]], *, cutoff_ts: float) -> dict[str, Any]:
        summary = {
            "manifest": self.manifest(),
            "examined": 0,
            "allowed": 0,
            "refused": 0,
            "insufficient_evidence": 0,
            "history_queries": 0,
        }
        if not self.enabled or self.data_store is None:
            return summary
        cache: dict[tuple[str, int], list[dict[str, Any]]] = {}
        for row in rows:
            model_id = str(row.get("model_id") or "")
            if row.get("abstain") or model_id.startswith("baseline_"):
                continue
            key = (model_id, int(row.get("horizon_seconds") or 0))
            if key not in cache:
                cache[key] = self.data_store.get_walk_forward_calibration_samples(
                    model_id=key[0],
                    horizon_seconds=key[1],
                    cutoff_ts=cutoff_ts,
                    limit=self.max_samples,
                )
                summary["history_queries"] += 1
            receipt = self._receipt(row, cache[key], cutoff_ts=cutoff_ts)
            row["walk_forward_calibration"] = receipt
            summary["examined"] += 1
            decision = str(receipt.get("decision") or "INSUFFICIENT_EVIDENCE")
            if decision == "ALLOW":
                base = receipt.get("base_cost_distribution") or {}
                stressed = receipt.get("stressed_cost_distribution") or {}
                calibrated_net = max(0.0, float(base.get("lower_bound_bps") or 0.0))
                expected_cost = max(0.0, float(row.get("expected_cost_bps") or 0.0))
                row["probability_positive_net"] = stressed.get("probability_positive_lower_bound")
                row["expected_net_bps"] = round(calibrated_net, 6)
                row["expected_move_bps"] = round(expected_cost + calibrated_net, 6)
                row["calibration_state"] = "WALK_FORWARD_STRESSED_ALLOW"
                row["research_route"] = "walk_forward_calibrated"
                row["research_route_priority"] = max(3, int(row.get("research_route_priority") or 0))
                summary["allowed"] += 1
            elif decision == "REFUSE":
                row["calibration_state"] = "WALK_FORWARD_STRESSED_REFUSE"
                row["research_route"] = "walk_forward_calibration_refused"
                row["research_route_priority"] = min(-3, int(row.get("research_route_priority") or 0))
                summary["refused"] += 1
            else:
                row["calibration_state"] = "WALK_FORWARD_INSUFFICIENT_EVIDENCE"
                summary["insufficient_evidence"] += 1
        return summary
