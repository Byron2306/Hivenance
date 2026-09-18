import time
import statistics
import json
import os
from typing import Any, Dict, List, Optional

from agents.dex_margin_oracle import DexMarginOracle


class CoinSelector:
    """Phase 3 coin selection pipeline.

    Ranks symbols by liquid, tradable opportunity rather than raw volatility.
    """

    def __init__(self, cfg: Any, coordinator: Optional[Any] = None):
        self.cfg = cfg
        self.coordinator = coordinator
        self.dex_oracle = DexMarginOracle(cfg, coordinator=coordinator)

    def _quote_volume_usd(self, t: dict) -> float:
        try:
            if t.get("quoteVolume") is not None:
                return float(t.get("quoteVolume"))
            # fallback: baseVolume * last
            if t.get("baseVolume") is not None and t.get("last") is not None:
                return float(t.get("baseVolume")) * float(t.get("last"))
        except Exception:
            pass
        return 0.0

    def _spread_pct(self, t: dict) -> Optional[float]:
        try:
            bid = t.get("bid")
            ask = t.get("ask")
            if bid and ask and bid > 0:
                return float(ask - bid) / float(bid)
        except Exception:
            pass
        return None

    def _volatility(self, closes: List[float]) -> float:
        if len(closes) < 2:
            return 0.0
        rets = []
        for i in range(1, len(closes)):
            p0 = closes[i - 1]
            p1 = closes[i]
            if p0 <= 0:
                continue
            rets.append((p1 - p0) / p0)
        if not rets:
            return 0.0
        return float(statistics.pstdev(rets))

    def _load_symbol_memory(self) -> Dict[str, Any]:
        path = getattr(self.cfg, "symbol_memory_path", "data/symbol_memory.json")
        try:
            if path and os.path.exists(path):
                with open(path, "r") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            pass
        return {}

    def _stage_allowed(self, stage: str) -> bool:
        allowed = getattr(self.cfg, "promotion_allowed_stages", None) or ["paper", "research_import"]
        return str(stage or "paper") in set(str(s) for s in allowed)

    def _score_candidate(self, c: Dict[str, Any], memory: Dict[str, Any]) -> Dict[str, Any]:
        symbol = c.get("symbol") or ""
        base = symbol.split("/")[0].upper() if "/" in symbol else symbol.upper()
        mem = memory.get(symbol) or memory.get(base) or {}

        vol = max(0.0, float(c.get("quote_volume") or 0.0))
        spread = max(0.0, float(c.get("spread_pct") or 0.0))
        volatility = max(0.0, float(c.get("volatility") or 0.0))
        win_rate = float(mem.get("win_rate", 0.5) if mem.get("win_rate") is not None else 0.5)
        avg_slippage = max(0.0, float(mem.get("avg_slippage_pct") or 0.0))
        max_dd = max(0.0, float(mem.get("max_drawdown_pct") or 0.0))
        rejects = max(0.0, float(mem.get("rejects_24h") or 0.0))
        stage = str(mem.get("stage") or "paper")

        core_assets = set(str(x).upper() for x in (getattr(self.cfg, "core_assets", []) or []))
        experimental_assets = set(str(x).upper() for x in (getattr(self.cfg, "experimental_assets", []) or []))

        min_vol = max(1.0, float(getattr(self.cfg, "coin_selection_min_vol_usd", 100000) or 1.0))
        max_spread = max(1e-9, float(getattr(self.cfg, "coin_selection_spread_max", 0.03) or 0.03))
        target_vol = max(1e-9, float(getattr(self.cfg, "coin_selection_target_volatility", 0.006) or 0.006))
        max_vol = max(target_vol, float(getattr(self.cfg, "coin_selection_max_volatility", 0.025) or 0.025))
        harvest_mode = bool(getattr(self.cfg, "volatility_harvest_enabled", False))

        liquidity_score = min(1.0, vol / (min_vol * 10.0))
        spread_score = max(0.0, 1.0 - (spread / max_spread))
        if harvest_mode:
            volatility_score = min(1.0, volatility / max(1e-9, target_vol * 2.0))
        else:
            # Bell-shaped preference: enough movement to matter, not chaos.
            vol_distance = abs(volatility - target_vol) / max_vol
            volatility_score = max(0.0, 1.0 - vol_distance)
        dex_quality = c.get("dex_quality") or {}
        exit_score = 0.0
        if dex_quality:
            rr = dex_quality.get("roundtrip_ratio")
            if rr is not None:
                exit_score = max(0.0, min(1.0, (float(rr) - 0.85) / 0.14))
            liq = min(1.0, float(dex_quality.get("liquidity_usd") or 0.0) / max(1.0, float(getattr(self.cfg, "dex_min_liquidity_usd", 50000) or 50000) * 3.0))
            vol24 = min(1.0, float(dex_quality.get("volume_24h_usd") or 0.0) / max(1.0, float(getattr(self.cfg, "dex_min_volume_24h_usd", 25000) or 25000) * 4.0))
            dex_quality_score = 0.45 * exit_score + 0.30 * liq + 0.25 * vol24
        else:
            dex_quality_score = 0.0
        memory_score = max(0.0, min(1.0, 0.55 * win_rate + 0.25 * (1.0 - min(1.0, avg_slippage / max_spread)) + 0.20 * (1.0 - min(1.0, max_dd / 20.0))))
        reject_penalty = min(0.35, rejects * 0.03)
        core_bonus = 0.12 if base in core_assets else 0.0
        experimental_penalty = 0.10 if base in experimental_assets else 0.0
        stage_penalty = 0.0 if self._stage_allowed(stage) else 0.45

        if harvest_mode and dex_quality:
            score = (
                0.18 * liquidity_score
                + 0.12 * spread_score
                + 0.25 * volatility_score
                + 0.30 * dex_quality_score
                + 0.15 * memory_score
                + core_bonus
                - reject_penalty
                - stage_penalty
            )
        else:
            score = (
                0.30 * liquidity_score
                + 0.25 * spread_score
                + 0.20 * volatility_score
                + 0.20 * memory_score
                + core_bonus
                - experimental_penalty
                - reject_penalty
                - stage_penalty
            )
        c.update({
            "score": round(max(0.0, min(1.0, score)), 6),
            "memory": {
                "stage": stage,
                "win_rate": win_rate,
                "avg_slippage_pct": avg_slippage,
                "max_drawdown_pct": max_dd,
                "rejects_24h": rejects,
            },
            "score_components": {
                "liquidity": round(liquidity_score, 4),
                "spread": round(spread_score, 4),
                "volatility": round(volatility_score, 4),
                "dex_quality": round(dex_quality_score, 4),
                "exit": round(exit_score, 4),
                "memory": round(memory_score, 4),
                "core_bonus": core_bonus,
                "experimental_penalty": experimental_penalty,
                "reject_penalty": reject_penalty,
                "stage_penalty": stage_penalty,
            },
        })
        return c

    def select_onchain_candidates(self) -> List[Dict[str, Any]]:
        """Rank curated on-chain tokens by volatility plus DEX exit quality."""
        if not bool(getattr(self.cfg, "dex_margin_oracle_enabled", True)):
            return []
        quote = str(getattr(self.cfg, "volatility_harvest_quote_asset", "USD") or "USD").upper()
        include = set([s.upper() for s in (getattr(self.cfg, "coin_selection_include", []) or [])])
        exclude = set([s.upper() for s in (getattr(self.cfg, "coin_selection_exclude", []) or [])])
        amount_usd = float(getattr(self.cfg, "dex_probe_amount_usd", getattr(self.cfg, "quote_order_size", 1.0)) or 1.0)

        out = []
        memory = self._load_symbol_memory()
        for token in self.dex_oracle.token_universe():
            base = str(token.get("symbol") or "").upper()
            symbol = f"{base}/{quote}"
            if include and symbol.upper() not in include and base not in include:
                continue
            if symbol.upper() in exclude or base in exclude:
                continue
            analysis = self.dex_oracle.analyze_token(token, amount_usd=amount_usd, quote_symbol=quote)
            q = analysis.get("quality") or {}
            candidate = {
                "symbol": symbol,
                "source": "DEX_CURATED",
                "quote_volume": float(q.get("volume_24h_usd") or 0.0),
                "spread_pct": float(q.get("price_impact_pct") or 0.0),
                "volatility": abs(float(q.get("price_change_h1_pct") or 0.0)) / 100.0,
                "dex_allowed": bool(analysis.get("allowed")),
                "dex_reason": analysis.get("reason"),
                "dex_score": analysis.get("score"),
                "dex_quality": q,
                "dex_pool": analysis.get("pool"),
                "dex_route": analysis.get("route"),
            }
            if not candidate["dex_allowed"] and bool(getattr(self.cfg, "volatility_harvest_require_exit", True)):
                candidate["rejected"] = True
            out.append(self._score_candidate(candidate, memory))

        out = [c for c in out if not c.get("rejected")]
        top_n = int(getattr(self.cfg, "coin_selection_top_n", 3) or 3)
        return sorted(out, key=lambda x: x.get("score", 0.0), reverse=True)[:top_n]

    def select_candidates(self, client) -> List[Dict[str, Any]]:
        if bool(getattr(self.cfg, "volatility_harvest_enabled", False)) and bool(getattr(self.cfg, "onchain_enabled", False)):
            ranked = self.select_onchain_candidates()
            if ranked:
                return ranked
        if not client or not hasattr(client, "fetch_tickers"):
            return []
        quote_assets = [q.upper() for q in (getattr(self.cfg, "coin_selection_quote_assets", []) or ["USDT", "USDC", "USD"])]
        include = set([s.upper() for s in (getattr(self.cfg, "coin_selection_include", []) or [])])
        exclude = set([s.upper() for s in (getattr(self.cfg, "coin_selection_exclude", []) or [])])

        min_vol = float(getattr(self.cfg, "coin_selection_min_vol_usd", 100000) or 0.0)
        max_spread = float(getattr(self.cfg, "coin_selection_spread_max", 0.03) or 0.0)
        max_volatility = float(getattr(self.cfg, "coin_selection_max_volatility", 0.025) or 0.0)
        harvest_mode = bool(getattr(self.cfg, "volatility_harvest_enabled", False))
        lookback = int(getattr(self.cfg, "coin_selection_lookback", 60) or 60)
        max_symbols = int(getattr(self.cfg, "coin_selection_max_symbols", 25) or 25)
        tf = getattr(self.cfg, "interval", "1m")

        try:
            tickers = client.fetch_tickers()
        except Exception:
            return []

        candidates = []
        for symbol, t in tickers.items():
            if "/" not in symbol:
                continue
            base, quote = symbol.split("/")
            base_u = base.upper()
            quote_u = quote.upper()

            if include:
                if symbol.upper() not in include and base_u not in include:
                    continue
            if symbol.upper() in exclude or base_u in exclude:
                continue
            if quote_u not in quote_assets:
                continue

            vol = self._quote_volume_usd(t)
            if vol < min_vol:
                continue
            sp = self._spread_pct(t)
            if max_spread and sp is not None and sp > max_spread:
                continue

            candidates.append({
                "symbol": symbol,
                "quote_volume": vol,
                "spread_pct": sp or 0.0,
            })

        # limit to top by volume for OHLCV fetch
        candidates = sorted(candidates, key=lambda x: x["quote_volume"], reverse=True)[:max_symbols]

        for c in candidates:
            try:
                ohlcv = client.fetch_ohlcv(c["symbol"], timeframe=tf, limit=lookback)
                closes = [float(r[4]) for r in ohlcv]
                c["volatility"] = self._volatility(closes)
            except Exception:
                c["volatility"] = 0.0
            if max_volatility and c["volatility"] > max_volatility and not harvest_mode:
                c["too_volatile"] = True

        candidates = [c for c in candidates if not c.get("too_volatile")]
        memory = self._load_symbol_memory()
        candidates = [self._score_candidate(c, memory) for c in candidates]

        top_n = int(getattr(self.cfg, "coin_selection_top_n", 3) or 3)
        ranked = sorted(candidates, key=lambda x: x.get("score", 0.0), reverse=True)
        return ranked[:top_n]
