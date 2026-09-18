import time
from typing import Any, Dict, List, Optional


class PairProtectionEvaluator:
    """Clean-room pair protections inspired by public bot protection/pairlist patterns."""

    def __init__(self, cfg: Any):
        self.cfg = cfg

    def evaluate(
        self,
        row: Dict[str, Any],
        now: Optional[float] = None,
        paper_trades: Optional[List[Dict[str, Any]]] = None,
        market_history: Optional[List[Dict[str, Any]]] = None,
        paper_stats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = float(now or time.time())
        paper_trades = paper_trades or []
        market_history = market_history or []
        paper_stats = paper_stats or {}
        symbol = row.get("symbol")
        q = row.get("quality") or {}
        pool = row.get("pool") or {}

        rules = []
        reasons = []
        state = "ALLOW"
        cooldown_until = 0.0
        low_profit_until = 0.0

        route_loss = self._route_loss(q)
        daily_loss_pct = sum(float(t.get("net_margin_pct") or 0.0) for t in paper_trades)
        failed_quotes = len([h for h in market_history if "QUOTE_UNAVAILABLE" in str(h.get("reason") or "")])

        # Freqtrade-style protections.
        bad_exit_reasons = {"PAPER_QUALITY_COLLAPSE", "PAPER_HARD_STOP", "HARD_STOP", "QUALITY_COLLAPSE", "ROUTE_LOSS_SPIKE"}
        bad_exits = [t for t in paper_trades if str(t.get("reason") or "").upper() in bad_exit_reasons]
        if bad_exits:
            cooldown_sec = int(getattr(self.cfg, "pair_cooldown_after_bad_exit_sec", 3600) or 3600)
            cooldown_until = max(cooldown_until, float(bad_exits[-1].get("ts") or now) + cooldown_sec)
            if cooldown_until > now:
                self._trigger(rules, reasons, "COOLDOWN_AFTER_BAD_EXIT", "BLOCK", cooldown_until=cooldown_until)

        max_daily_loss = -abs(float(getattr(self.cfg, "pair_max_daily_loss_pct", 0.03) or 0.03))
        if daily_loss_pct <= max_daily_loss:
            self._trigger(rules, reasons, "MAX_DAILY_LOSS", "BLOCK", value=daily_loss_pct, threshold=max_daily_loss)

        max_drawdown = float(getattr(self.cfg, "pair_max_drawdown_pct", 0.05) or 0.05)
        dd = float(paper_stats.get("max_drawdown_pct") or 0.0)
        # Existing stats may be stored as ratio or percent depending on source.
        dd_ratio = dd / 100.0 if dd > 1.0 else dd
        if dd_ratio >= max_drawdown:
            self._trigger(rules, reasons, "MAX_DRAWDOWN", "BLOCK", value=dd_ratio, threshold=max_drawdown)

        min_profit = float(getattr(self.cfg, "pair_min_net_margin_sum_pct", 0.0) or 0.0)
        min_trades = int(getattr(self.cfg, "low_profit_min_trades", 4) or 4)
        if int(paper_stats.get("trades") or 0) >= min_trades and float(paper_stats.get("net_margin_sum") or 0.0) <= min_profit:
            low_profit_until = now + int(getattr(self.cfg, "low_profit_quarantine_sec", 7200) or 7200)
            self._trigger(rules, reasons, "LOW_PROFIT_QUARANTINE", "BLOCK", low_profit_until=low_profit_until)

        max_failed_quotes = int(getattr(self.cfg, "pair_max_failed_quotes_daily", 5) or 5)
        if failed_quotes >= max_failed_quotes:
            self._trigger(rules, reasons, "FAILED_QUOTES", "BLOCK", value=failed_quotes, threshold=max_failed_quotes)

        max_route_loss = float(getattr(self.cfg, "pair_max_route_loss_spike_pct", 0.04) or 0.04)
        if route_loss >= max_route_loss:
            self._trigger(rules, reasons, "ROUTE_LOSS_SPIKE", "BLOCK", value=route_loss, threshold=max_route_loss)

        # Freqtrade-style pairlist filters.
        min_volume = float(getattr(self.cfg, "pairlist_min_volume_24h_usd", 0.0) or 0.0)
        volume_24h = float(q.get("volume_24h_usd") or row.get("volume_24h_usd") or 0.0)
        if min_volume and volume_24h < min_volume:
            self._trigger(rules, reasons, "PAIRLIST_VOLUME_FILTER", "BLOCK", value=volume_24h, threshold=min_volume)

        max_spread = float(getattr(self.cfg, "pairlist_max_spread_pct", 0.0) or 0.0)
        spread = self._spread_pct(q, row)
        if max_spread and spread is not None and spread > max_spread:
            self._trigger(rules, reasons, "PAIRLIST_SPREAD_FILTER", "BLOCK", value=spread, threshold=max_spread)

        max_volatility = float(getattr(self.cfg, "pairlist_max_abs_change_24h_pct", 0.0) or 0.0)
        h24_change = q.get("h24_change_pct", row.get("h24_change_pct"))
        try:
            if max_volatility and h24_change is not None and abs(float(h24_change)) > max_volatility:
                self._trigger(rules, reasons, "PAIRLIST_VOLATILITY_FILTER", "WARN", value=float(h24_change), threshold=max_volatility)
        except Exception:
            pass

        min_age = int(getattr(self.cfg, "pairlist_min_age_sec", 0) or 0)
        first_seen = self._first_seen(row, market_history)
        age_sec = max(0.0, now - first_seen) if first_seen else None
        if min_age and age_sec is not None and age_sec < min_age:
            self._trigger(rules, reasons, "PAIRLIST_AGE_FILTER", "BLOCK", value=age_sec, threshold=min_age)

        if any(r.get("severity") == "BLOCK" for r in rules):
            state = "BLOCK"
        elif any(r.get("severity") == "WARN" for r in rules):
            state = "WARN"

        return {
            "symbol": symbol,
            "state": state,
            "allowed": state != "BLOCK",
            "reason": "OK" if not reasons else ",".join(reasons),
            "cooldown_until": cooldown_until,
            "daily_loss_pct": daily_loss_pct,
            "failed_quotes": failed_quotes,
            "route_loss_spike_pct": route_loss,
            "low_profit_until": low_profit_until,
            "updated_ts": now,
            "rules": rules,
            "pairlist": {
                "volume_24h_usd": volume_24h,
                "spread_pct": spread,
                "h24_change_pct": h24_change,
                "age_sec": age_sec,
                "liquidity_usd": q.get("liquidity_usd") or pool.get("liquidity_usd"),
            },
        }

    def _trigger(self, rules: List[Dict[str, Any]], reasons: List[str], rule: str, severity: str, **extra: Any) -> None:
        reasons.append(rule)
        item = {"rule": rule, "severity": severity}
        item.update(extra)
        rules.append(item)

    def _route_loss(self, quality: Dict[str, Any]) -> float:
        try:
            rr = quality.get("roundtrip_ratio")
            return max(0.0, 1.0 - float(rr)) if rr is not None else 0.0
        except Exception:
            return 0.0

    def _spread_pct(self, quality: Dict[str, Any], row: Dict[str, Any]) -> Optional[float]:
        for key in ("spread_pct", "bid_ask_spread_pct"):
            if quality.get(key) is not None:
                try:
                    return float(quality.get(key))
                except Exception:
                    return None
        if row.get("spread_pct") is not None:
            try:
                return float(row.get("spread_pct"))
            except Exception:
                return None
        return None

    def _first_seen(self, row: Dict[str, Any], market_history: List[Dict[str, Any]]) -> Optional[float]:
        for key in ("first_seen_ts", "created_ts", "pair_created_ts"):
            if row.get(key):
                try:
                    return float(row.get(key))
                except Exception:
                    pass
        times = []
        for h in market_history or []:
            try:
                times.append(float(h.get("ts") or 0.0))
            except Exception:
                pass
        return min(times) if times else None
