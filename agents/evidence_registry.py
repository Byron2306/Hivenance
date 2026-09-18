from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, Optional


class EvidenceRegistryAgent:
    """Normalize external backtest evidence as a Phoenix research import only."""

    def __init__(self, cfg: Any):
        self.cfg = cfg
        self.records_seen = 0
        self.last_evidence_id = ""
        self.last_verdict = ""

    def status(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "name": "EVIDENCE_REGISTRY",
            "records_seen": self.records_seen,
            "last_evidence_id": self.last_evidence_id,
            "last_verdict": self.last_verdict,
            "policy": self.policy(),
        }

    def policy(self) -> Dict[str, Any]:
        return {
            "min_trades": int(getattr(self.cfg, "promotion_min_paper_trades", 25) or 25),
            "min_win_rate": float(getattr(self.cfg, "promotion_min_win_rate", 0.52) or 0.52),
            "max_drawdown_pct": float(getattr(self.cfg, "promotion_max_drawdown_pct", 5.0) or 5.0),
            "requires_review": True,
            "requires_fee_model": True,
            "requires_slippage_model": True,
            "requires_walk_forward": True,
            "promotion_authority": "none",
            "phoenix_next_required_phase": 2,
        }

    def from_public_bot(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        payload = payload or {}
        metrics = dict(payload.get("metrics") or {})
        symbol = payload.get("symbol") or metrics.get("symbol")
        return self.normalize(
            source="public_bot_backtest",
            engine=payload.get("engine") or metrics.get("engine") or "unknown",
            run_id=payload.get("run_id"),
            symbol=symbol,
            strategy=metrics.get("strategy") or metrics.get("strategy_name"),
            metrics=metrics,
            artifact_path=payload.get("export_path"),
            raw=payload,
        )

    def from_replay(self, result: Dict[str, Any]) -> Dict[str, Any]:
        result = result or {}
        metrics = dict(result)
        symbol = result.get("symbol")
        run_id = result.get("run_id") or f"hivenance-replay-{symbol or 'all'}-{int(time.time())}"
        return self.normalize(
            source="hivenance_replay",
            engine="hivenance_replay",
            run_id=run_id,
            symbol=symbol,
            strategy=result.get("strategy") or "market_bee_replay",
            metrics=metrics,
            artifact_path=None,
            raw=result,
        )

    def normalize(
        self,
        source: str,
        engine: str,
        run_id: Optional[str],
        symbol: Optional[str],
        strategy: Optional[str],
        metrics: Dict[str, Any],
        artifact_path: Optional[str] = None,
        raw: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        metrics = metrics or {}
        safe_raw = self._json_copy(raw or {})
        safe_raw_metrics = self._json_copy(metrics)
        normalized = {
            "trades": self._int(metrics, "trades", "total_trades", "trade_count"),
            "wins": self._int(metrics, "wins", "winning_trades"),
            "losses": self._int(metrics, "losses", "losing_trades"),
            "win_rate": self._float(metrics, "win_rate", "winrate"),
            "net_profit_pct": self._float(metrics, "net_profit_pct", "profit_total_pct", "net_margin_pct", "net_margin_sum"),
            "max_drawdown_pct": self._float(metrics, "max_drawdown_pct", "drawdown_pct", "max_drawdown"),
            "exposure_pct": self._float(metrics, "exposure_pct", "market_exposure_pct"),
            "fee_pct": self._float(metrics, "fee_pct", "fees_pct", "fee_assumption_pct"),
            "slippage_pct": self._float(metrics, "slippage_pct", "slippage_assumption_pct"),
        }
        if normalized["win_rate"] is None and normalized["trades"]:
            normalized["win_rate"] = (normalized["wins"] or 0) / max(1, normalized["trades"])
        if normalized["wins"] is None and normalized["trades"] and normalized["win_rate"] is not None:
            normalized["wins"] = int(round(normalized["trades"] * normalized["win_rate"]))
        if normalized["losses"] is None and normalized["trades"] and normalized["wins"] is not None:
            normalized["losses"] = max(0, normalized["trades"] - normalized["wins"])

        gates = self.evaluate(normalized, metrics)
        verdict = self.verdict(gates)
        now = time.time()
        record = {
            "evidence_id": self._evidence_id(source, engine, run_id, symbol, strategy, normalized),
            "source": source,
            "engine": engine,
            "run_id": run_id,
            "symbol": symbol,
            "strategy": strategy,
            "created_ts": now,
            "updated_ts": now,
            "metrics": normalized,
            "raw_metrics": safe_raw_metrics,
            "gates": gates,
            "verdict": verdict,
            "external_verdict": verdict,
            "phoenix_status": "UNVALIDATED_IMPORT",
            "next_required_phase": 2,
            "promotion_stage": "research_import",
            "execution_authority": "none",
            "promotion_authority": "none",
            "live_allowed": False,
            "artifact_path": artifact_path,
            "raw": safe_raw,
        }
        self.records_seen += 1
        self.last_evidence_id = record["evidence_id"]
        self.last_verdict = verdict
        return record

    def evaluate(self, metrics: Dict[str, Any], raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        policy = self.policy()
        trades = int(metrics.get("trades") or 0)
        win_rate = metrics.get("win_rate")
        net = float(metrics.get("net_profit_pct") or 0.0)
        drawdown = float(metrics.get("max_drawdown_pct") or 0.0)
        fee_present = metrics.get("fee_pct") is not None or any(k in raw for k in ("fees", "fee_model", "fee_assumption"))
        slippage_present = metrics.get("slippage_pct") is not None or any(k in raw for k in ("slippage", "slippage_model", "slippage_assumption"))
        walk_forward = bool(raw.get("walk_forward") or raw.get("walk_forward_passed") or raw.get("out_of_sample"))
        return {
            "minimum_trades": {"pass": trades >= policy["min_trades"], "value": trades, "required": policy["min_trades"]},
            "win_rate": {"pass": win_rate is not None and float(win_rate) >= policy["min_win_rate"], "value": win_rate, "required": policy["min_win_rate"]},
            "positive_net": {"pass": net > 0.0, "value": net, "required": "> 0"},
            "max_drawdown": {"pass": drawdown <= policy["max_drawdown_pct"], "value": drawdown, "required": policy["max_drawdown_pct"]},
            "fee_model": {"pass": fee_present, "value": metrics.get("fee_pct"), "required": "explicit_fee_model"},
            "slippage_model": {"pass": slippage_present, "value": metrics.get("slippage_pct"), "required": "explicit_slippage_model"},
            "walk_forward": {"pass": walk_forward, "value": walk_forward, "required": "walk_forward_or_out_of_sample"},
        }

    def verdict(self, gates: Dict[str, Dict[str, Any]]) -> str:
        core = ("minimum_trades", "win_rate", "positive_net", "max_drawdown")
        if not all(bool(gates.get(name, {}).get("pass")) for name in core):
            return "external_research_rejected"
        research = ("fee_model", "slippage_model", "walk_forward")
        if not all(bool(gates.get(name, {}).get("pass")) for name in research):
            return "external_research_incomplete"
        return "external_research_passed"

    def _evidence_id(self, source: str, engine: str, run_id: Optional[str], symbol: Optional[str], strategy: Optional[str], metrics: Dict[str, Any]) -> str:
        raw = json.dumps({
            "source": source,
            "engine": engine,
            "run_id": run_id,
            "symbol": symbol,
            "strategy": strategy,
            "metrics": metrics,
        }, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _float(self, data: Dict[str, Any], *keys: str) -> Optional[float]:
        for key in keys:
            value = data.get(key)
            if value is None or value == "":
                continue
            try:
                return float(value)
            except Exception:
                continue
        return None

    def _int(self, data: Dict[str, Any], *keys: str) -> Optional[int]:
        value = self._float(data, *keys)
        return int(value) if value is not None else None

    def _json_copy(self, value: Any) -> Any:
        try:
            return json.loads(json.dumps(value, default=str))
        except Exception:
            return {}
