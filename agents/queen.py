import time
from typing import Dict, Any, List


class GovernanceQueen:
    """Meta-strategy governance (SVS scoring)."""

    def __init__(self, min_svs: float = 0.35):
        self.min_svs = min_svs
        self._last_decision = None

    def decide(
        self,
        regime: Dict[str, Any],
        proposals: List[Dict[str, Any]],
        portfolio: Dict[str, Any],
        exec_quality: Dict[str, Any],
        perf: Dict[str, Any],
        cfg: Any,
    ) -> Dict[str, Any]:
        ts = int(time.time() * 1000)
        if not proposals:
            return self._decision("HOLD", None, 0.0, "No proposals", ts)

        # Filter out HOLDs
        active = [p for p in proposals if p.get("action") in ("BUY", "SELL")]
        if not active:
            return self._decision("HOLD", None, 0.0, "No actionable proposals", ts)

        regime_label = (regime or {}).get("regime") or "CHOP_RANGE"
        regime_conf = float((regime or {}).get("confidence") or 0.0)

        best = None
        for p in active:
            svs = self._svs_score(p, regime_label, exec_quality, perf)
            p["_svs"] = svs
            if not best or svs > best["_svs"]:
                best = p

        if not best or best["_svs"] < self.min_svs:
            return self._decision("HOLD", best.get("strategy") if best else None, best.get("_svs") if best else 0.0, "SVS below threshold", ts)

        # Position sizing: risk_pct * regime confidence, action-aware
        latest_price = float(portfolio.get("latest_price") or 0.0)
        quote_free = float(portfolio.get("quote_free") or 0.0)
        base_free = float(portfolio.get("base_free") or 0.0)
        risk_pct = float(getattr(cfg, "risk_pct", 0.01))
        max_position_base = float(getattr(cfg, "max_position_base", 0.0))

        if best.get("action") == "BUY":
            base_size = (quote_free * risk_pct) / latest_price if latest_price > 0 else 0.0
        elif best.get("action") == "SELL":
            # Sell a risk-based fraction of current base balance
            base_size = base_free * risk_pct
        else:
            base_size = 0.0
        size_mult = 0.5 + min(0.5, regime_conf)
        position_size = base_size * size_mult
        if max_position_base > 0:
            if best.get("action") == "BUY":
                position_size = min(position_size, max_position_base - base_free)
            elif best.get("action") == "SELL":
                position_size = min(position_size, base_free)

        rationale = f"{regime_label} ({regime_conf:.2f}). {best.get('notes') or 'Selected best SVS proposal'}"
        return {
            "approved": True,
            "action": best.get("action"),
            "strategy": best.get("strategy"),
            "position_size": max(0.0, position_size),
            "rationale": rationale,
            "signal_id": best.get("signal_id"),
            "svs": best.get("_svs"),
            "ts": ts,
        }

    def _svs_score(self, proposal: Dict[str, Any], regime: str, exec_quality: Dict[str, Any], perf: Dict[str, Any]) -> float:
        # regime fit
        strategy = proposal.get("strategy") or ""
        rf = 0.5
        if "RSI" in strategy and regime in ("CHOP_RANGE", "MEAN_REVERT_HIGH_VOL"):
            rf = 0.9
        elif "BREAKOUT" in strategy and regime in ("BREAKOUT", "PANIC_VOLATILE"):
            rf = 0.85
        elif "MOMENTUM" in strategy and regime.startswith("TREND"):
            rf = 0.85
        elif "SMA" in strategy and regime.startswith("TREND"):
            rf = 0.8

        rp = float(perf.get("win_rate", 0.5)) if isinstance(perf, dict) else 0.5
        sq = float(proposal.get("signal_strength") or 0.0)
        ef = 1.0 - float(exec_quality.get("spread_pct", 0.0))
        ra = 1.0 - float(proposal.get("risk") or 0.0) * 0.5

        svs = 0.30 * rf + 0.25 * rp + 0.20 * sq + 0.15 * ef + 0.10 * ra
        return max(0.0, min(1.0, svs))

    def _decision(self, action: str, strategy: str, score: float, reason: str, ts: int) -> Dict[str, Any]:
        return {
            "approved": False if action == "HOLD" else True,
            "action": action,
            "strategy": strategy,
            "position_size": 0.0,
            "rationale": reason,
            "signal_id": None,
            "svs": score,
            "ts": ts,
        }
