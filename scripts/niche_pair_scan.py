"""Read-only scan of Kraken spot markets for niche/illiquid, high-volatility pairs
that may be uneconomical for large market makers/HFT firms to bother with, but
where a tiny ($1-2 notional) retail bot's absolute costs (spread + fees) could
still be small relative to the pair's realized volatility.

Public data only -- no API keys, no orders placed. Safe to run repeatedly.

Usage:
    .venv/bin/python scripts/niche_pair_scan.py [--quote USD] [--top 25]
"""
import argparse
import statistics
import sys
import time

import ccxt


CORE_MAJORS = {"BTC", "ETH", "USDT", "USDC", "SOL", "XRP", "DOGE", "ADA", "BNB"}

# Assumed round-trip cost model consistent with config/settings.yaml phase3 assumptions
# (maker 40bps / taker 80bps side). We use a conservative "taker both sides" estimate
# plus observed spread, since a niche/thin book may not always fill passively.
MAKER_FEE_BPS_PER_SIDE = 40.0
TAKER_FEE_BPS_PER_SIDE = 80.0


def quote_volume_usd(t: dict) -> float:
    try:
        if t.get("quoteVolume") is not None:
            return float(t["quoteVolume"])
        if t.get("baseVolume") is not None and t.get("last") is not None:
            return float(t["baseVolume"]) * float(t["last"])
    except Exception:
        pass
    return 0.0


def spread_pct(t: dict):
    try:
        bid, ask = t.get("bid"), t.get("ask")
        if bid and ask and bid > 0:
            return float(ask - bid) / float(bid)
    except Exception:
        pass
    return None


def realized_volatility(client, symbol: str, timeframe: str = "1h", limit: int = 72):
    try:
        ohlcv = client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        closes = [float(r[4]) for r in ohlcv if r and r[4]]
        if len(closes) < 10:
            return None
        rets = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1] > 0]
        if not rets:
            return None
        return float(statistics.pstdev(rets))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quote", default="USD")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--min-volume-usd", type=float, default=2000.0, help="floor so the pair is at least somewhat tradable")
    ap.add_argument("--max-volume-usd", type=float, default=2_000_000.0, help="ceiling to stay below where large firms bother competing")
    ap.add_argument("--max-spread-pct", type=float, default=0.02, help="drop pairs with an absurd spread")
    ap.add_argument("--ohlcv-sample", type=int, default=40, help="how many of the volume-filtered candidates to pull OHLCV for (rate-limit friendly)")
    args = ap.parse_args()

    client = ccxt.kraken({"enableRateLimit": True, "timeout": 20_000})
    print("Loading markets...", file=sys.stderr)
    client.load_markets()
    print("Fetching tickers (public)...", file=sys.stderr)
    tickers = client.fetch_tickers()

    candidates = []
    for symbol, t in tickers.items():
        if "/" not in symbol:
            continue
        base, quote = symbol.split("/")
        if quote.upper() != args.quote.upper():
            continue
        if base.upper() in CORE_MAJORS:
            continue
        vol = quote_volume_usd(t)
        if vol < args.min_volume_usd or vol > args.max_volume_usd:
            continue
        sp = spread_pct(t)
        if sp is not None and sp > args.max_spread_pct:
            continue
        candidates.append({"symbol": symbol, "quote_volume_usd": vol, "spread_pct": sp, "last": t.get("last")})

    candidates.sort(key=lambda c: c["quote_volume_usd"])
    sample = candidates[: args.ohlcv_sample] if len(candidates) > args.ohlcv_sample else candidates
    # Prefer a spread across the volume range rather than just the very bottom (some may be untradeable/stale).
    if len(candidates) > args.ohlcv_sample:
        step = max(1, len(candidates) // args.ohlcv_sample)
        sample = candidates[::step][: args.ohlcv_sample]

    print(f"{len(candidates)} candidates in volume band [{args.min_volume_usd:,.0f}, {args.max_volume_usd:,.0f}] USD, "
          f"sampling {len(sample)} for OHLCV volatility...", file=sys.stderr)

    results = []
    for c in sample:
        vola_1h = realized_volatility(client, c["symbol"], timeframe="1h", limit=72)
        time.sleep(client.rateLimit / 1000.0)
        if vola_1h is None:
            continue
        spread = c["spread_pct"] or 0.0
        round_trip_cost_maker = 2 * MAKER_FEE_BPS_PER_SIDE / 10000.0 + spread
        round_trip_cost_taker = 2 * TAKER_FEE_BPS_PER_SIDE / 10000.0 + spread
        edge_ratio_maker = vola_1h / round_trip_cost_maker if round_trip_cost_maker > 0 else 0.0
        results.append({
            **c,
            "hourly_volatility": vola_1h,
            "round_trip_cost_maker_pct": round_trip_cost_maker,
            "round_trip_cost_taker_pct": round_trip_cost_taker,
            "edge_ratio_maker": edge_ratio_maker,
        })

    results.sort(key=lambda r: r["edge_ratio_maker"], reverse=True)

    print()
    print(f"{'symbol':<14}{'24h_vol_usd':>14}{'spread%':>10}{'hourly_vol%':>13}{'rt_cost_mk%':>13}{'rt_cost_tk%':>13}{'edge_ratio':>12}")
    for r in results[: args.top]:
        print(
            f"{r['symbol']:<14}{r['quote_volume_usd']:>14,.0f}"
            f"{(r['spread_pct'] or 0.0)*100:>9.3f}%"
            f"{r['hourly_volatility']*100:>12.3f}%"
            f"{r['round_trip_cost_maker_pct']*100:>12.3f}%"
            f"{r['round_trip_cost_taker_pct']*100:>12.3f}%"
            f"{r['edge_ratio_maker']:>12.2f}"
        )
    print()
    print("edge_ratio_maker = hourly_volatility / round_trip_cost_at_maker_fees. >1 means a single hour's")
    print("typical move exceeds the assumed round-trip cost -- necessary (NOT sufficient) for a directional")
    print("or mean-reversion edge to be worth pursuing on that pair. Still requires real Phase1-4 validation.")


if __name__ == "__main__":
    main()
