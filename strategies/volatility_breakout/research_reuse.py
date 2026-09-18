from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, asdict
from typing import Any, Mapping


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class ResearchReuseDecision:
    receipt_id: str
    decision: str
    model_id: str
    symbol: str
    regime_hint: str
    horizon_seconds: int
    config_hash: str
    sample_count: int
    mean_realized_net_bps: float | None
    win_rate: float | None
    latest_settled_ts: float | None
    reason: str
    created_ts: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResearchReuseGovernor:
    """Advisory exact and deterministic-slice research reuse for Hivenance phases 2 and 3."""

    def __init__(self, cfg: Any, data_store: Any) -> None:
        self.cfg = cfg
        self.data_store = data_store
        self._decision_cache: dict[tuple[str, str, int, str, str, str], dict[str, Any]] = {}
        self.min_samples = max(1, int(getattr(cfg, "phase2_reuse_min_samples", 5) or 5))
        self.min_mean_net_bps = float(getattr(cfg, "phase2_reuse_min_mean_net_bps", 2.0) or 2.0)
        self.min_win_rate = float(getattr(cfg, "phase2_reuse_min_win_rate", 0.50) or 0.50)
        self.transform_min_samples = max(
            self.min_samples,
            int(getattr(cfg, "phase2_transform_reuse_min_samples", 8) or 8),
        )
        self.transform_min_mean_net_bps = float(
            getattr(cfg, "phase2_transform_reuse_min_mean_net_bps", self.min_mean_net_bps) or self.min_mean_net_bps
        )
        self.transform_min_win_rate = float(
            getattr(cfg, "phase2_transform_reuse_min_win_rate", self.min_win_rate) or self.min_win_rate
        )
        self.transform_reuse_enabled = bool(getattr(cfg, "phase2_transform_reuse_enabled", False))

    def config_hash(self) -> str:
        payload = {
            "phase2_federation_models": getattr(self.cfg, "phase2_federation_models", []),
            "phase2_federation_quarantined_models": getattr(
                self.cfg, "phase2_federation_quarantined_models", {}
            ),
            "phase2_walk_forward_calibration": {
                key: getattr(self.cfg, key, None)
                for key in (
                    "phase2_walk_forward_calibration_enabled",
                    "phase2_calibration_max_samples",
                    "phase2_calibration_min_slice_samples",
                    "phase2_calibration_min_regime_samples",
                    "phase2_calibration_min_model_samples",
                    "phase2_calibration_stress_cost_multiple",
                    "phase2_calibration_prior_strength",
                    "phase2_calibration_one_sided_z",
                    "phase2_calibration_min_stressed_lower_bound_bps",
                    "phase2_calibration_min_probability_lower_bound",
                )
            },
            "phase2_horizons_seconds": getattr(self.cfg, "phase2_horizons_seconds", []),
            "phase2_minimum_edge_multiple": getattr(self.cfg, "phase2_minimum_edge_multiple", None),
            "phase2_federation_minimum_edge_multiple": getattr(self.cfg, "phase2_federation_minimum_edge_multiple", None),
            "phase2_reuse_min_samples": self.min_samples,
            "phase2_reuse_min_mean_net_bps": self.min_mean_net_bps,
            "phase2_reuse_min_win_rate": self.min_win_rate,
            "phase2_transform_reuse_min_samples": self.transform_min_samples,
            "phase2_transform_reuse_min_mean_net_bps": self.transform_min_mean_net_bps,
            "phase2_transform_reuse_min_win_rate": self.transform_min_win_rate,
            "phase2_transform_reuse_enabled": self.transform_reuse_enabled,
        }
        return _canonical_hash(payload)

    @staticmethod
    def _decision_payload(stats: Mapping[str, Any]) -> tuple[int, float | None, float | None, float | None]:
        return (
            int(stats.get("sample_count") or 0),
            stats.get("mean_realized_net_bps"),
            stats.get("win_rate"),
            stats.get("latest_settled_ts"),
        )

    @staticmethod
    def _passes_gate(
        sample_count: int,
        mean_realized_net_bps: float | None,
        win_rate: float | None,
        *,
        min_samples: int,
        min_mean_net_bps: float,
        min_win_rate: float,
    ) -> bool:
        return (
            sample_count >= int(min_samples)
            and mean_realized_net_bps is not None
            and float(mean_realized_net_bps) >= float(min_mean_net_bps)
            and win_rate is not None
            and float(win_rate) >= float(min_win_rate)
        )

    def decide(
        self,
        *,
        model_id: str,
        symbol: str,
        horizon_seconds: int,
        regime_hint: str,
        cohort_bucket: str,
        symbol_class: str,
    ) -> dict[str, Any]:
        cache_key = (
            str(model_id),
            str(symbol),
            int(horizon_seconds or 0),
            str(regime_hint or "unknown"),
            str(cohort_bucket or "unknown"),
            str(symbol_class or "unknown"),
        )
        if cache_key in self._decision_cache:
            return dict(self._decision_cache[cache_key])
        exact_stats = self.data_store.get_research_reuse_stats(
            model_id=model_id,
            symbol=symbol,
            horizon_seconds=horizon_seconds,
            regime_hint=regime_hint,
            limit=max(25, self.min_samples * 4),
        )
        sample_count, mean_realized_net_bps, win_rate, latest_settled_ts = self._decision_payload(exact_stats)
        if self._passes_gate(
            sample_count,
            mean_realized_net_bps,
            win_rate,
            min_samples=self.min_samples,
            min_mean_net_bps=self.min_mean_net_bps,
            min_win_rate=self.min_win_rate,
        ):
            decision = "exact_reuse_candidate"
            reason = "exact_match_prior_evidence_is_positive"
        elif sample_count > 0:
            decision = "exact_reuse_too_weak"
            reason = "exact_match_prior_evidence_below_gate"
        else:
            if str(model_id).startswith("worker_signal_") or not self.transform_reuse_enabled:
                transform_stats = {
                    "match_type": "none",
                    "sample_count": 0,
                    "mean_realized_net_bps": None,
                    "win_rate": None,
                    "latest_settled_ts": None,
                }
            else:
                transform_stats = self.data_store.get_research_transform_reuse_stats(
                    model_id=model_id,
                    horizon_seconds=horizon_seconds,
                    regime_hint=regime_hint,
                    cohort_bucket=cohort_bucket,
                    symbol_class=symbol_class,
                    limit=max(50, self.transform_min_samples * 6),
                )
            transform_match_type = str(transform_stats.get("match_type") or "none")
            sample_count, mean_realized_net_bps, win_rate, latest_settled_ts = self._decision_payload(transform_stats)
            if transform_match_type == "symbol_class":
                if self._passes_gate(
                    sample_count,
                    mean_realized_net_bps,
                    win_rate,
                    min_samples=self.transform_min_samples,
                    min_mean_net_bps=self.transform_min_mean_net_bps,
                    min_win_rate=self.transform_min_win_rate,
                ):
                    decision = "transformed_symbol_class_candidate"
                    reason = "symbol_class_regime_prior_evidence_is_positive"
                elif sample_count > 0:
                    decision = "transformed_symbol_class_too_weak"
                    reason = "symbol_class_regime_prior_evidence_below_gate"
                else:
                    decision = "no_prior_evidence"
                    reason = "no_transform_research_reuse_match"
            elif transform_match_type == "cohort":
                if self._passes_gate(
                    sample_count,
                    mean_realized_net_bps,
                    win_rate,
                    min_samples=self.transform_min_samples,
                    min_mean_net_bps=self.transform_min_mean_net_bps,
                    min_win_rate=self.transform_min_win_rate,
                ):
                    decision = "transformed_cohort_candidate"
                    reason = "cohort_regime_prior_evidence_is_positive"
                elif sample_count > 0:
                    decision = "transformed_cohort_too_weak"
                    reason = "cohort_regime_prior_evidence_below_gate"
                else:
                    decision = "no_prior_evidence"
                    reason = "no_transform_research_reuse_match"
            else:
                decision = "no_prior_evidence"
                reason = "no_exact_or_transform_research_reuse_match"
        created_ts = time.time()
        config_hash = self.config_hash()
        receipt = ResearchReuseDecision(
            receipt_id=_canonical_hash(
                {
                    "model_id": model_id,
                    "symbol": symbol,
                    "horizon_seconds": horizon_seconds,
                    "regime_hint": regime_hint,
                    "config_hash": config_hash,
                    "decision": decision,
                    "created_ts": created_ts,
                }
            ),
            decision=decision,
            model_id=model_id,
            symbol=symbol,
            regime_hint=regime_hint,
            horizon_seconds=int(horizon_seconds or 0),
            config_hash=config_hash,
            sample_count=sample_count,
            mean_realized_net_bps=(round(float(mean_realized_net_bps), 8) if mean_realized_net_bps is not None else None),
            win_rate=(round(float(win_rate), 8) if win_rate is not None else None),
            latest_settled_ts=(float(latest_settled_ts) if latest_settled_ts is not None else None),
            reason=reason,
            created_ts=created_ts,
        )
        self.data_store.persist_research_reuse_receipt(receipt.to_dict())
        payload = receipt.to_dict()
        self._decision_cache[cache_key] = dict(payload)
        return payload
