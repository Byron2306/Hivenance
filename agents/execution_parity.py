from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Optional


class ExecutionParityAgent:
    """Offline execution-realism diagnostics for replay and paper/live drift."""

    def __init__(self, cfg: Any):
        self.cfg = cfg
        self.diagnostics_seen = 0
        self.last_parity_id = ""
        self.last_verdict = ""

    def status(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "name": "EXECUTION_PARITY",
            "mode": "diagnostics_only",
            "diagnostics_seen": self.diagnostics_seen,
            "last_parity_id": self.last_parity_id,
            "last_verdict": self.last_verdict,
            "policy": self.policy(),
        }

    def policy(self) -> Dict[str, Any]:
        return {
            "live_execution_authority": "none",
            "promotion_authority": "none",
            "phoenix_role": "phase3_phase5_phase6_model_vs_reality_auditor",
            "max_latency_ms": int(getattr(self.cfg, "execution_parity_max_latency_ms", 1500) or 1500),
            "max_slippage_pct": float(
                getattr(self.cfg, "execution_parity_max_slippage_pct", getattr(self.cfg, "slippage_threshold", 0.01)) or 0.01
            ),
            "min_fill_ratio": float(getattr(self.cfg, "execution_parity_min_fill_ratio", 0.98) or 0.98),
            "max_queue_position_risk": float(getattr(self.cfg, "execution_parity_max_queue_position_risk", 0.35) or 0.35),
            "requires_fill_model_audit": True,
        }

    def from_replay(
        self,
        result: Dict[str, Any],
        evidence: Optional[Dict[str, Any]] = None,
        execution_observations: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        result = result or {}
        evidence = evidence or {}
        execution_observations = execution_observations or {}
        metrics = self._metrics_from_replay(result, execution_observations=execution_observations)
        gates = self.evaluate(metrics)
        verdict = self.verdict(gates)
        now = time.time()
        diagnostic = {
            "parity_id": self._parity_id("hivenance_replay", result.get("run_id"), result.get("symbol"), metrics),
            "source": "hivenance_replay",
            "symbol": result.get("symbol"),
            "run_id": result.get("run_id"),
            "evidence_id": evidence.get("evidence_id") or (result.get("evidence") or {}).get("evidence_id"),
            "created_ts": now,
            "updated_ts": now,
            "status": "diagnostic_only",
            "verdict": verdict,
            "metrics": metrics,
            "gates": gates,
            "latency_model": self._latency_model(result, execution_observations),
            "slippage_model": self._slippage_model(result, metrics),
            "queue_position_model": self._queue_position_model(metrics),
            "fill_model_audit": self._fill_model_audit(result, metrics),
            "drift_diagnostics": self._drift_diagnostics(result, execution_observations),
            "execution_authority": "none",
            "live_allowed": False,
            "promotion_authority": "none",
            "next_authoritative_phase": 3,
        }
        self.diagnostics_seen += 1
        self.last_parity_id = diagnostic["parity_id"]
        self.last_verdict = verdict
        return diagnostic

    def evaluate(self, metrics: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        policy = self.policy()
        latency = self._float(metrics.get("p95_latency_ms"), default=None)
        slippage = self._float(metrics.get("slippage_pct"), default=None)
        fill_ratio = self._float(metrics.get("fill_ratio"), default=0.0)
        queue_risk = self._float(metrics.get("queue_position_risk"), default=1.0)
        audit = bool(metrics.get("fill_model_audit_passed"))
        return {
            "latency_budget": {"pass": latency is not None and latency <= policy["max_latency_ms"], "value": latency, "required": policy["max_latency_ms"]},
            "slippage_budget": {"pass": slippage is not None and slippage <= policy["max_slippage_pct"], "value": slippage, "required": policy["max_slippage_pct"]},
            "fill_ratio": {"pass": fill_ratio >= policy["min_fill_ratio"], "value": fill_ratio, "required": policy["min_fill_ratio"]},
            "queue_position": {"pass": queue_risk <= policy["max_queue_position_risk"], "value": queue_risk, "required": policy["max_queue_position_risk"]},
            "fill_model_audit": {"pass": audit, "value": audit, "required": True},
            "diagnostic_only": {"pass": True, "value": True, "required": True},
        }

    def verdict(self, gates: Dict[str, Dict[str, Any]]) -> str:
        required = ("latency_budget", "slippage_budget", "fill_ratio", "queue_position", "fill_model_audit", "diagnostic_only")
        if all(bool(gates.get(name, {}).get("pass")) for name in required):
            return "diagnostic_pass"
        if any(bool(gates.get(name, {}).get("pass")) for name in ("latency_budget", "slippage_budget", "fill_model_audit")):
            return "diagnostic_collecting"
        return "diagnostic_failed"

    def _metrics_from_replay(self, result: Dict[str, Any], execution_observations: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        execution_observations = execution_observations or {}
        trades = max(0, self._int(result.get("trades"), default=0))
        failed = max(0, self._int(result.get("failed_exits"), default=0))
        open_position = bool(result.get("open_position"))
        filled = max(0, trades - failed - (1 if open_position else 0))
        fill_ratio = (filled / trades) if trades else 0.0
        slippage = self._float(result.get("slippage_pct"), default=None)
        observed = self._observed_execution_metrics(execution_observations)
        if observed.get("orders"):
            trades = int(observed.get("orders") or trades)
            filled = int(observed.get("fills") or filled)
            fill_ratio = float(observed.get("fill_ratio") or 0.0)
        if observed.get("avg_slippage_pct") is not None:
            slippage = observed.get("avg_slippage_pct")
        p95_latency_ms = self._float(result.get("p95_latency_ms"), default=None)
        latency_source = "replay_payload"
        if observed.get("p95_latency_ms") is not None:
            p95_latency_ms = observed.get("p95_latency_ms")
            latency_source = "order_fill_timestamps"
        if p95_latency_ms is None:
            p95_latency_ms = self._latency_proxy_ms(result)
            latency_source = "replay_proxy"
        queue_risk = self._queue_risk(slippage, result)
        return {
            "trades": trades,
            "filled_trades": filled,
            "failed_exits": failed,
            "fill_ratio": fill_ratio,
            "p95_latency_ms": p95_latency_ms,
            "latency_source": latency_source,
            "slippage_pct": slippage,
            "fee_pct": self._float(result.get("fee_pct"), default=0.0),
            "exposure_pct": self._float(result.get("exposure_pct"), default=0.0),
            "queue_position_risk": queue_risk,
            "top_of_book_depth_usd": self._float(result.get("top_of_book_depth_usd"), default=None),
            "order_size_pct_of_depth": self._float(result.get("order_size_pct_of_depth"), default=None),
            "spread_pct": self._float(result.get("spread_pct"), default=None),
            "fill_model_audit_passed": trades > 0 and slippage is not None and not open_position and (observed.get("orders", 0) > 0 or bool(result.get("fill_model_audit_passed"))),
            "open_position": open_position,
            "observed_orders": observed.get("orders", 0),
            "observed_fills": observed.get("fills", 0),
        }

    def _observed_execution_metrics(self, observations: Dict[str, Any]) -> Dict[str, Any]:
        orders = observations.get("orders") or []
        fills = observations.get("fills") or []
        latencies = sorted([float(v) for v in (observations.get("latencies_ms") or []) if v is not None])
        p95 = None
        if latencies:
            idx = min(len(latencies) - 1, int(round((len(latencies) - 1) * 0.95)))
            p95 = latencies[idx]
        slips = []
        for fill in fills:
            try:
                if fill.get("slippage_pct") is not None:
                    slips.append(float(fill.get("slippage_pct") or 0.0))
            except Exception:
                continue
        return {
            "orders": len(orders),
            "fills": len(fills),
            "fill_ratio": (len(fills) / len(orders)) if orders else None,
            "p95_latency_ms": p95,
            "avg_slippage_pct": (sum(slips) / len(slips)) if slips else None,
        }

    def _latency_proxy_ms(self, result: Dict[str, Any]) -> float:
        trades = max(1, self._int(result.get("trades"), default=0))
        exposure = max(0.0, self._float(result.get("exposure_pct"), default=0.0) or 0.0)
        slippage = max(0.0, self._float(result.get("slippage_pct"), default=0.0) or 0.0)
        return round(250.0 + (exposure * 500.0) + (slippage * 10000.0) + min(750.0, trades * 5.0), 3)

    def _queue_risk(self, slippage: Optional[float], result: Dict[str, Any]) -> float:
        slippage = max(0.0, float(slippage or 0.0))
        exposure = max(0.0, self._float(result.get("exposure_pct"), default=0.0) or 0.0)
        failed = max(0.0, float(self._int(result.get("failed_exits"), default=0) or 0))
        trades = max(1.0, float(self._int(result.get("trades"), default=0) or 0))
        order_depth_pct = self._float(result.get("order_size_pct_of_depth"), default=None)
        depth_penalty = max(0.0, float(order_depth_pct or 0.0)) if order_depth_pct is not None else 0.0
        return round(min(1.0, (slippage * 20.0) + (exposure * 0.20) + ((failed / trades) * 0.45) + (depth_penalty * 0.35)), 6)

    def _latency_model(self, result: Dict[str, Any], observations: Dict[str, Any]) -> Dict[str, Any]:
        observed = self._observed_execution_metrics(observations or {})
        if observed.get("p95_latency_ms") is not None:
            return {
                "source": "order_fill_timestamps",
                "p95_latency_ms": observed.get("p95_latency_ms"),
                "observed_orders": observed.get("orders"),
                "observed_fills": observed.get("fills"),
            }
        return {
            "source": "replay_proxy",
            "p95_latency_ms": self._latency_proxy_ms(result),
            "note": "Proxy until tick/orderbook timestamps are available.",
        }

    def _slippage_model(self, result: Dict[str, Any], metrics: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "source": "route_loss_proxy",
            "slippage_pct": metrics.get("slippage_pct"),
            "fee_pct": metrics.get("fee_pct"),
            "net_includes_costs": True,
        }

    def _queue_position_model(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "source": "orderbook_depth" if metrics.get("top_of_book_depth_usd") is not None else "slippage_exposure_failed_exit_proxy",
            "queue_position_risk": metrics.get("queue_position_risk"),
            "top_of_book_depth_usd": metrics.get("top_of_book_depth_usd"),
            "order_size_pct_of_depth": metrics.get("order_size_pct_of_depth"),
            "requires_orderbook_for_live_parity": metrics.get("top_of_book_depth_usd") is None,
        }

    def _fill_model_audit(self, result: Dict[str, Any], metrics: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "pass": bool(metrics.get("fill_model_audit_passed")),
            "checks": {
                "has_trades": int(metrics.get("trades") or 0) > 0,
                "has_slippage_model": metrics.get("slippage_pct") is not None,
                "no_open_position": not bool(result.get("open_position")),
                "has_fee_model": metrics.get("fee_pct") is not None,
                "has_timestamp_observations_or_explicit_audit": int(metrics.get("observed_orders") or 0) > 0 or bool(result.get("fill_model_audit_passed")),
            },
        }

    def _drift_diagnostics(self, result: Dict[str, Any], observations: Dict[str, Any]) -> Dict[str, Any]:
        observed = self._observed_execution_metrics(observations or {})
        has_timestamps = observed.get("p95_latency_ms") is not None
        has_orderbook = result.get("top_of_book_depth_usd") is not None or result.get("spread_pct") is not None
        return {
            "paper_vs_live": "timestamp_observed" if has_timestamps else "not_available",
            "replay_vs_fill": "observed_fill_overlay" if observed.get("orders") else "proxy_only",
            "orderbook": "observed" if has_orderbook else "missing",
            "next_required_data": [
                item for item in ["orderbook_snapshots", "submitted_order_ts", "ack_ts", "fill_ts", "requested_price", "average_fill_price"]
                if not ((item in ("submitted_order_ts", "ack_ts", "fill_ts") and has_timestamps) or (item == "orderbook_snapshots" and has_orderbook))
            ],
            "live_claim_allowed": False,
        }

    def _parity_id(self, source: str, run_id: Optional[str], symbol: Optional[str], metrics: Dict[str, Any]) -> str:
        raw = json.dumps({"source": source, "run_id": run_id, "symbol": symbol, "metrics": metrics}, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _float(self, value: Any, default: Optional[float] = 0.0) -> Optional[float]:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except Exception:
            return default

    def _int(self, value: Any, default: int = 0) -> int:
        try:
            return int(float(value))
        except Exception:
            return default
