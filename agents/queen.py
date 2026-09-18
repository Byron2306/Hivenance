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

        protection_block = any(
            ((p.get("protection") or {}).get("state") == "BLOCK")
            for p in proposals
            if isinstance(p.get("protection"), dict)
        )
        latency_block = any(
            ((p.get("latency") or {}).get("state") == "BLOCK")
            for p in proposals
            if isinstance(p.get("latency"), dict)
        )

        # Filter out HOLDs. Protection blocks suppress new entries but still
        # allow exit-risk SELL proposals through.
        active = [p for p in proposals if p.get("action") in ("BUY", "SELL")]
        if protection_block or latency_block:
            active = [p for p in active if p.get("action") == "SELL"]
        if not active:
            reason = "Protection block" if protection_block else ("Latency block" if latency_block else "No actionable proposals")
            return self._decision("HOLD", None, 0.0, reason, ts)

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
        elif "BREAKOUT" in strategy and regime in ("BREAKOUT", "PANIC_VOLATILE", "VOL_EXPANSION", "PUMP"):
            rf = 0.85
        elif "MOMENTUM" in strategy and (regime.startswith("TREND") or regime in ("VOL_EXPANSION", "PUMP")):
            rf = 0.85
        elif "BOLLINGER" in strategy and regime in ("CHOP_RANGE", "MEAN_REVERT_HIGH_VOL", "RANGING"):
            rf = 0.9
        elif "SUPERTREND" in strategy and (regime.startswith("TREND") or regime in ("BREAKOUT", "VOL_EXPANSION", "PUMP", "TREND_UP")):
            rf = 0.9
        elif "SMA" in strategy and regime.startswith("TREND"):
            rf = 0.8
        elif "VOL-EXPANSION" in strategy and regime in ("VOL_EXPANSION", "BREAKOUT", "PUMP", "TREND_UP"):
            rf = 0.92
        elif "EXIT-RISK" in strategy and proposal.get("action") == "SELL":
            rf = 0.95

        rp = float(perf.get("win_rate", 0.5)) if isinstance(perf, dict) else 0.5
        sq = float(proposal.get("signal_strength") or 0.0)
        spread = float(exec_quality.get("spread_pct", 0.0) or 0.0)
        price_impact = float(exec_quality.get("price_impact_pct", 0.0) or 0.0)
        gas_drag = float(exec_quality.get("gas_drag_pct", 0.0) or 0.0)
        min_output_ratio = exec_quality.get("min_output_ratio")
        quote_ratio = exec_quality.get("quote_output_ratio")
        ef = 1.0 - spread - price_impact - gas_drag
        try:
            if min_output_ratio is not None and quote_ratio is not None:
                if float(quote_ratio) < float(min_output_ratio):
                    ef *= 0.25
        except Exception:
            pass
        ef = max(0.0, min(1.0, ef))
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
