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


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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
            "tradable_opportunity_score",
            "research_richness_score",
            "opportunity_components",
            "phase2_profitability_frontier",
            "phase2_regime_suppression",
        ):
            if key in candidate_values and key not in merged_values:
                merged_values[key] = candidate_values.get(key)
    return FeatureVector(**{**asdict(feature), "values": merged_values})


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
        self.interval_sec = max(30, int(getattr(cfg, "phase1_observation_interval_sec", 120) or 120))
        raw_horizons = getattr(cfg, "phase2_horizons_seconds", [300, 900, 3600]) or [300, 900, 3600]
        self.horizons = tuple(sorted({max(60, int(value)) for value in raw_horizons}))
        self.competition = HypothesisCompetition(cfg)
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

    def _frontier_context_map(self) -> dict[tuple[str, str], dict[str, Any]]:
        if not self.coordinator:
            return {}
        store = getattr(self.coordinator, "store", None)
        if store is None or not hasattr(store, "get_hypothesis_scorecard"):
            return {}
        try:
            scorecard = store.get_hypothesis_scorecard()
        except Exception:
            return {}
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

    def _regime_suppression_map(self) -> dict[str, dict[str, Any]]:
        if not self.coordinator:
            return {}
        store = getattr(self.coordinator, "store", None)
        if store is None or not hasattr(store, "get_hypothesis_scorecard"):
            return {}
        try:
            scorecard = store.get_hypothesis_scorecard()
        except Exception:
            return {}
        rows = scorecard.get("regime_model_breakdown") or []
        out: dict[str, dict[str, Any]] = {}
        min_samples = max(3, int(getattr(self.cfg, "phase2_regime_suppression_min_samples", 6) or 6))
        max_mean = float(getattr(self.cfg, "phase2_regime_suppression_max_mean_net_bps", -2.5) or -2.5)
        reentry_window = max(2, int(getattr(self.cfg, "phase2_regime_reentry_recent_window", 6) or 6))
        reentry_min_samples = max(2, int(getattr(self.cfg, "phase2_regime_reentry_min_samples", 3) or 3))
        reentry_min_mean = float(getattr(self.cfg, "phase2_regime_reentry_min_mean_net_bps", 2.0) or 2.0)
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
                        WHERE COALESCE(f.abstain, 0) = 0
                    ) ranked
                    WHERE rn <= ?
                    GROUP BY model_id, regime_hint
                    HAVING COUNT(*) >= ? AND AVG(net_return_bps) >= ?
                    """,
                    (reentry_window, reentry_min_samples, reentry_min_mean),
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

    def run_once(self) -> dict[str, Any]:
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
        evaluated_symbols = 0
        frontier_map = self._frontier_context_map()
        suppression_map = self._regime_suppression_map()

        for candidate in observation.get("candidates") or []:
            values = candidate.get("values") or {}
            feature = _feature_from_payload(values.get("feature_vector") or {})
            if feature is None:
                continue
            feature = _feature_with_candidate_context(feature, values if isinstance(values, dict) else {})
            feature = self._feature_with_frontier_context(feature, frontier_map)
            feature = self._feature_with_regime_suppression(feature, suppression_map)
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
                forecast_rows.append(row)

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
            "federation": self.competition.federation_manifest(),
            "forecasts": forecast_rows,
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
