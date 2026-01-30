import time
import statistics
from typing import Any, Dict, List, Optional


class CoinSelector:
    """Phase 3 coin selection pipeline (volatility + liquidity filters)."""

    def __init__(self, cfg: Any, coordinator: Optional[Any] = None):
        self.cfg = cfg
        self.coordinator = coordinator

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

    def select_candidates(self, client) -> List[Dict[str, Any]]:
        if not client or not hasattr(client, "fetch_tickers"):
            return []
        quote_assets = [q.upper() for q in (getattr(self.cfg, "coin_selection_quote_assets", []) or ["USDT", "USDC", "USD"])]
        include = set([s.upper() for s in (getattr(self.cfg, "coin_selection_include", []) or [])])
        exclude = set([s.upper() for s in (getattr(self.cfg, "coin_selection_exclude", []) or [])])

        min_vol = float(getattr(self.cfg, "coin_selection_min_vol_usd", 100000) or 0.0)
        max_spread = float(getattr(self.cfg, "coin_selection_spread_max", 0.03) or 0.0)
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

        top_n = int(getattr(self.cfg, "coin_selection_top_n", 3) or 3)
        ranked = sorted(candidates, key=lambda x: x.get("volatility", 0.0), reverse=True)
        return ranked[:top_n]
