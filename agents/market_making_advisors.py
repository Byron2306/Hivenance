import time
from typing import Any, Dict, List, Optional


class MarketMakingAdvisor:
    name = "PMM_ADVISOR"

    def __init__(self, cfg: Any):
        self.cfg = cfg

    def advise(self, row: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def _quality(self, row: Dict[str, Any]) -> Dict[str, float]:
        quality = row.get("quality") or {}
        pool = row.get("pool") or {}
        roundtrip = float(quality.get("roundtrip_ratio") or row.get("roundtrip_ratio") or 0.0)
        spread_pct = max(0.0, 1.0 - roundtrip) if roundtrip else float(quality.get("spread_pct") or 0.0)
        liquidity = float(quality.get("liquidity_usd") or pool.get("liquidity_usd") or row.get("liquidity_usd") or 0.0)
        volume = float(quality.get("volume_24h_usd") or pool.get("volume_24h_usd") or row.get("volume_24h_usd") or 0.0)
        h24 = abs(float(pool.get("h24_change_pct") or row.get("h24_change_pct") or 0.0))
        price = float(pool.get("price_usd") or row.get("price_usd") or row.get("price") or 0.0)
        return {
            "price": price,
            "roundtrip_ratio": roundtrip,
            "spread_pct": spread_pct,
            "liquidity_usd": liquidity,
            "volume_24h_usd": volume,
            "abs_change_24h_pct": h24,
        }

    def _quote_plan(self, q: Dict[str, float], target_spread: float) -> Dict[str, Any]:
        price = float(q.get("price") or 0.0)
        if price <= 0:
            return {"mode": "watch_only", "target_spread_pct": target_spread}
        half = target_spread / 2.0
        return {
            "mode": "watch_only",
            "target_spread_pct": target_spread,
            "bid_price": price * (1.0 - half),
            "ask_price": price * (1.0 + half),
        }


class PmmSimpleAdvisor(MarketMakingAdvisor):
    name = "PMM_SIMPLE_ADVISOR"

    def advise(self, row: Dict[str, Any]) -> Dict[str, Any]:
        q = self._quality(row)
        min_liq = float(getattr(self.cfg, "pmm_simple_min_liquidity_usd", 25000.0) or 25000.0)
        max_spread = float(getattr(self.cfg, "pmm_simple_max_spread_pct", 0.015) or 0.015)
        ok = q["liquidity_usd"] >= min_liq and q["spread_pct"] <= max_spread
        score = min(1.0, q["liquidity_usd"] / max(1.0, min_liq)) * max(0.0, 1.0 - q["spread_pct"] / max(1e-9, max_spread))
        target_spread = max(q["spread_pct"] * 1.25, float(getattr(self.cfg, "pmm_simple_min_quote_spread_pct", 0.003) or 0.003))
        return {
            "advisor": self.name,
            "symbol": row.get("symbol"),
            "state": "CLEAR" if ok else "WARN",
            "quote_quality_score": max(0.0, min(1.0, score)),
            "recommended": bool(ok),
            "reason": "simple_quote_quality_clear" if ok else "liquidity_or_spread_not_clean",
            "metrics": q,
            "quote_plan": self._quote_plan(q, target_spread),
            "ts": int(time.time() * 1000),
        }


class PmmDynamicAdvisor(MarketMakingAdvisor):
    name = "PMM_DYNAMIC_ADVISOR"

    def advise(self, row: Dict[str, Any]) -> Dict[str, Any]:
        q = self._quality(row)
        min_volume = float(getattr(self.cfg, "pmm_dynamic_min_volume_24h_usd", 50000.0) or 50000.0)
        max_spread = float(getattr(self.cfg, "pmm_dynamic_max_spread_pct", 0.02) or 0.02)
        max_vol = float(getattr(self.cfg, "pmm_dynamic_max_abs_change_24h_pct", 0.25) or 0.25)
        spread_score = max(0.0, 1.0 - q["spread_pct"] / max(1e-9, max_spread))
        volume_score = min(1.0, q["volume_24h_usd"] / max(1.0, min_volume))
        volatility_penalty = min(0.75, q["abs_change_24h_pct"] / max(1e-9, max_vol) * 0.35) if max_vol > 0 else 0.0
        score = max(0.0, min(1.0, 0.45 * spread_score + 0.40 * volume_score + 0.15 * min(1.0, q["liquidity_usd"] / max(1.0, min_volume)) - volatility_penalty))
        state = "CLEAR" if score >= 0.6 else ("WARN" if score >= 0.35 else "BLOCK")
        target_spread = max(q["spread_pct"] * (1.0 + q["abs_change_24h_pct"]), float(getattr(self.cfg, "pmm_dynamic_min_quote_spread_pct", 0.004) or 0.004))
        return {
            "advisor": self.name,
            "symbol": row.get("symbol"),
            "state": state,
            "quote_quality_score": score,
            "recommended": state == "CLEAR",
            "reason": "dynamic_quote_quality_clear" if state == "CLEAR" else "dynamic_quote_quality_degraded",
            "metrics": q,
            "quote_plan": self._quote_plan(q, target_spread),
            "ts": int(time.time() * 1000),
        }

    def _quote_plan(self, q: Dict[str, float], target_spread: float) -> Dict[str, Any]:
        price = float(q.get("price") or 0.0)
        if price <= 0:
            return {"mode": "watch_only", "target_spread_pct": target_spread}
        half = target_spread / 2.0
        return {
            "mode": "watch_only",
            "target_spread_pct": target_spread,
            "bid_price": price * (1.0 - half),
            "ask_price": price * (1.0 + half),
        }


class MarketMakingAdvisorSet:
    def __init__(self, cfg: Any):
        self.cfg = cfg
        self.advisors = [PmmSimpleAdvisor(cfg), PmmDynamicAdvisor(cfg)]

    def status(self) -> Dict[str, Any]:
        return {
            "name": "MARKET_MAKING_ADVISORS",
            "enabled": bool(getattr(self.cfg, "market_making_advisors_enabled", True)),
            "mode": "watch_only_quote_quality",
            "quote_placement_enabled": bool(getattr(self.cfg, "market_making_quote_placement_enabled", False)),
            "advisors": [a.name for a in self.advisors],
        }

    def advise(self, row: Dict[str, Any]) -> Dict[str, Any]:
        if not bool(getattr(self.cfg, "market_making_advisors_enabled", True)):
            return {"enabled": False, "advices": []}
        advices = [advisor.advise(row) for advisor in self.advisors]
        score_values = [float(a.get("quote_quality_score") or 0.0) for a in advices]
        states = [a.get("state") for a in advices]
        state = "BLOCK" if "BLOCK" in states else ("WARN" if "WARN" in states else "CLEAR")
        return {
            "enabled": True,
            "symbol": row.get("symbol"),
            "state": state,
            "quote_quality_score": sum(score_values) / max(1, len(score_values)),
            "advices": advices,
            "requires_quote_quality": True,
            "quote_placement_enabled": bool(getattr(self.cfg, "market_making_quote_placement_enabled", False)),
        }

    def advise_many(self, rows: Optional[List[Dict[str, Any]]] = None, limit: int = 25) -> Dict[str, Any]:
        rows = rows or []
        out = {}
        for row in rows[: int(limit or 25)]:
            sym = row.get("symbol")
            if sym:
                out[sym] = self.advise(row)
        return out
