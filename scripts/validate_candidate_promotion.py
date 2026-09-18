#!/usr/bin/env python3
"""CLI: run the candidate promotion gate against real settled-forecast evidence.

Usage:
    python scripts/validate_candidate_promotion.py \\
        --database data/swarm_data.db \\
        --out data/candidate_promotion_ledger.json

Reads (symbol, model_id, direction) triples from --pairs, discovers current
settled research candidates from the database, or uses a legacy liquid-pair
default list when explicitly requested,
loads their settled, non-abstain forecast/outcome evidence read-only, runs
the full statistical promotion gate (strategies/volatility_breakout/
candidate_promotion_gate.py), attaches a best-effort market-regime tag per
contributing hourly bucket, and writes a JSON ledger.

This script is read-only against the database (opens with mode=ro) and does
not modify any trading state, config, or authority. It is a research/
diagnostic tool only.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.run_phase1_observer import load_observer_config  # noqa: E402
from strategies.volatility_breakout.candidate_promotion_gate import (  # noqa: E402
    SettledForecast,
    evaluate_candidate,
    hour_bucket,
)

LEGACY_LIQUID_PAIRS = [
    ("SOL/USD", "candidate_finrl_conservative_policy_proxy_v1", "DOWN"),
    ("SOL/USD", "candidate_freqai_transparent_linear_v1", "DOWN"),
    ("AVAX/USD", "candidate_finrl_conservative_policy_proxy_v1", "DOWN"),
    ("AVAX/USD", "candidate_freqai_transparent_linear_v1", "DOWN"),
    ("ETH/USD", "candidate_finrl_conservative_policy_proxy_v1", "DOWN"),
    ("ETH/USD", "candidate_freqai_transparent_linear_v1", "DOWN"),
]
MAJOR_BASES = {"BTC", "ETH", "SOL", "AVAX", "XRP", "DOGE", "ADA", "BNB", "USDT", "USDC"}

# Heuristic regime-tagging thresholds (bps unless noted). These are
# best-effort classifications for operator context, not a validated regime
# model -- treat as descriptive labels, not additional promotion evidence.
BROAD_SELLOFF_BPS = -50.0
SYMBOL_WEAKNESS_BPS = -50.0
VOL_EXPANSION_Z = 1.5
LIQUIDITY_DETERIORATION_RATIO = 0.5  # depth vs symbol's trailing median
NEWS_SHOCK_BPS = 150.0


def load_settled_forecasts(con: sqlite3.Connection, symbol: str, model_id: str, direction: str):
    rows = con.execute(
        """
        SELECT f.ts, o.directional_return_bps, o.net_return_bps
        FROM hypothesis_forecasts f
        JOIN hypothesis_outcomes o ON o.forecast_id = f.forecast_id
        WHERE f.abstain=0 AND f.symbol=? AND f.model_id=? AND f.direction=?
        ORDER BY f.ts ASC
        """,
        (symbol, model_id, direction),
    ).fetchall()
    return [
        SettledForecast(ts=float(ts), directional_return_bps=float(d or 0.0), net_return_bps=float(n or 0.0))
        for ts, d, n in rows
    ]


def _symbol_base(symbol: str) -> str:
    return str(symbol or "").split("/", 1)[0].split(":", 1)[0].upper()


def load_pair_file(path: Path) -> list[tuple[str, str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    pairs = []
    for item in payload:
        if isinstance(item, dict):
            symbol = item.get("symbol")
            model_id = item.get("model_id")
            direction = item.get("direction")
        else:
            symbol, model_id, direction = item
        pairs.append((str(symbol), str(model_id), str(direction).upper()))
    return pairs


def discover_candidate_pairs(con: sqlite3.Connection, cfg: object, *, limit: int) -> list[tuple[str, str, str]]:
    high_vol_profile = str(getattr(cfg, "profile_name", "") or "") == "high_vol_low_stakes"
    max_niche_volume = float(getattr(cfg, "phase1_observation_niche_max_volume_usd", 2_000_000.0) or 2_000_000.0)
    rows = con.execute(
        """
        SELECT
            f.symbol,
            f.model_id,
            f.direction,
            COUNT(*) AS settled,
            MAX(f.ts) AS latest_ts,
            AVG(ABS(o.net_return_bps)) AS mean_abs_net_bps,
            AVG(o.net_return_bps) AS mean_net_bps,
            (
                SELECT s.quote_volume_24h
                FROM observation_snapshots s
                WHERE s.symbol=f.symbol AND s.quote_volume_24h IS NOT NULL
                ORDER BY s.ts DESC LIMIT 1
            ) AS latest_quote_volume_24h
        FROM hypothesis_forecasts f
        JOIN hypothesis_outcomes o ON o.forecast_id=f.forecast_id
        WHERE f.abstain=0
          AND f.direction IN ('UP', 'DOWN')
          AND f.model_id NOT LIKE 'baseline_%'
        GROUP BY f.symbol, f.model_id, f.direction
        ORDER BY latest_ts DESC, settled DESC, mean_abs_net_bps DESC
        LIMIT ?
        """,
        (max(int(limit) * 12, int(limit)),),
    ).fetchall()
    out: list[tuple[str, str, str]] = []
    for symbol, model_id, direction, _settled, _latest, _abs_net, _mean_net, quote_volume in rows:
        symbol = str(symbol or "")
        if high_vol_profile:
            if _symbol_base(symbol) in MAJOR_BASES:
                continue
            if quote_volume is not None and float(quote_volume) > max_niche_volume:
                continue
        out.append((symbol, str(model_id or ""), str(direction or "").upper()))
        if len(out) >= int(limit):
            break
    return out


def _hourly_price_return(con: sqlite3.Connection, symbol: str, ts: float):
    """Best-effort ~1h return for `symbol` ending near `ts`, using the
    nearest observation_snapshots rows within a loose window. Returns None
    if insufficient coverage."""
    row_end = con.execute(
        "SELECT price FROM observation_snapshots WHERE symbol=? AND ts<=? ORDER BY ts DESC LIMIT 1",
        (symbol, ts),
    ).fetchone()
    row_start = con.execute(
        "SELECT price FROM observation_snapshots WHERE symbol=? AND ts<=? ORDER BY ts DESC LIMIT 1",
        (symbol, ts - 3600.0),
    ).fetchone()
    if not row_end or not row_start or not row_start[0]:
        return None
    return (float(row_end[0]) - float(row_start[0])) / float(row_start[0]) * 10000.0


def tag_regime(con: sqlite3.Connection, symbol: str, ts: float) -> dict:
    """Best-effort, heuristic regime classification for a single hour bucket.
    Multiple tags may apply simultaneously; returns the list of tags that
    matched plus the raw signals used, so an operator can sanity-check it."""
    tags = []
    symbol_ret = _hourly_price_return(con, symbol, ts)
    broad_ret = _hourly_price_return(con, "BTC/USD", ts)

    snap = con.execute(
        """
        SELECT volatility_expansion, depth_usd_25bps, spread_bps
        FROM observation_snapshots WHERE symbol=? AND ts<=? ORDER BY ts DESC LIMIT 1
        """,
        (symbol, ts),
    ).fetchone()
    vol_expansion, depth, spread = (snap or (None, None, None))

    median_depth_row = con.execute(
        "SELECT AVG(depth_usd_25bps) FROM observation_snapshots WHERE symbol=? AND depth_usd_25bps IS NOT NULL",
        (symbol,),
    ).fetchone()
    median_depth = median_depth_row[0] if median_depth_row else None

    if broad_ret is not None and broad_ret <= BROAD_SELLOFF_BPS:
        tags.append("broad_market_selloff")
    if (
        symbol_ret is not None
        and symbol_ret <= SYMBOL_WEAKNESS_BPS
        and (broad_ret is None or broad_ret > BROAD_SELLOFF_BPS)
    ):
        tags.append("symbol_specific_weakness")
    if vol_expansion is not None and float(vol_expansion) >= VOL_EXPANSION_Z:
        tags.append("volatility_expansion")
    if depth is not None and median_depth and float(depth) < LIQUIDITY_DETERIORATION_RATIO * float(median_depth):
        tags.append("liquidity_deterioration")
    if symbol_ret is not None and abs(symbol_ret) >= NEWS_SHOCK_BPS:
        tags.append("news_or_event_shock")
    if not tags and symbol_ret is not None and broad_ret is not None and abs(symbol_ret - broad_ret) < 20.0:
        tags.append("trend_continuation")

    return {
        "symbol_return_1h_bps": symbol_ret,
        "broad_market_return_1h_bps": broad_ret,
        "volatility_expansion": vol_expansion,
        "depth_usd_25bps": depth,
        "spread_bps": spread,
        "tags": tags or ["unclassified"],
    }


def regime_summary(con: sqlite3.Connection, symbol: str, rows) -> list[dict]:
    """One regime tag per distinct contributing hourly bucket (not per row)."""
    seen_hours = sorted({hour_bucket(r.ts) for r in rows})
    out = []
    for h in seen_hours:
        ts = h * 3600.0
        entry = {"hour_bucket": h, "hour_start_iso": datetime.fromtimestamp(ts, UTC).isoformat()}
        entry.update(tag_regime(con, symbol, ts))
        out.append(entry)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=ROOT / "config" / "settings.yaml")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--database", default=str(ROOT / "data" / "swarm_data.db"))
    parser.add_argument("--out", default=str(ROOT / "data" / "candidate_promotion_ledger.json"))
    parser.add_argument("--pairs", type=Path, help="JSON list of [symbol, model_id, direction] rows or objects")
    parser.add_argument("--candidate-limit", type=int, default=12)
    parser.add_argument("--legacy-liquid-defaults", action="store_true")
    parser.add_argument("--holdout-frac", type=float, default=0.4)
    parser.add_argument("--min-hourly-buckets", type=int, default=24)
    parser.add_argument("--min-days", type=int, default=3)
    parser.add_argument("--min-settled", type=int, default=100)
    parser.add_argument("--max-episode-share", type=float, default=0.30)
    parser.add_argument("--cost-stress-multiplier", type=float, default=1.5)
    parser.add_argument("--n-boot", type=int, default=2000)
    parser.add_argument("--skip-regime", action="store_true", help="Skip per-hour regime tagging (faster)")
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    con = sqlite3.connect(f"file:{args.database}?mode=ro", uri=True)
    if args.pairs:
        pair_rows = load_pair_file(args.pairs)
        pair_source = str(args.pairs)
    elif args.legacy_liquid_defaults:
        pair_rows = list(LEGACY_LIQUID_PAIRS)
        pair_source = "legacy_liquid_defaults"
    else:
        pair_rows = discover_candidate_pairs(con, cfg, limit=max(1, int(args.candidate_limit)))
        pair_source = "database_discovery"

    ledger = {
        "schema": "hivenance_candidate_promotion_ledger_v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "gate_params": {
            "holdout_frac": args.holdout_frac,
            "min_hourly_buckets": args.min_hourly_buckets,
            "min_days": args.min_days,
            "min_settled": args.min_settled,
            "max_episode_share": args.max_episode_share,
            "cost_stress_multiplier": args.cost_stress_multiplier,
            "n_boot": args.n_boot,
        },
        "candidate_source": pair_source,
        "profile_name": getattr(cfg, "profile_name", None),
        "candidates": [],
    }

    for symbol, model_id, direction in pair_rows:
        rows = load_settled_forecasts(con, symbol, model_id, direction)
        verdict = evaluate_candidate(
            rows,
            holdout_frac=args.holdout_frac,
            min_hourly_buckets=args.min_hourly_buckets,
            min_days=args.min_days,
            min_settled=args.min_settled,
            max_episode_share=args.max_episode_share,
            cost_stress_multiplier=args.cost_stress_multiplier,
            n_boot=args.n_boot,
        )
        entry = {
            "symbol": symbol,
            "model_id": model_id,
            "direction": direction,
            **verdict,
        }
        if not args.skip_regime and rows:
            entry["regime_by_hour"] = regime_summary(con, symbol, rows)
        ledger["candidates"].append(entry)
        print(f"{symbol} {model_id} {direction}: {verdict['status']} / {verdict['promotion']} -- {verdict['reason']}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(ledger, indent=2, sort_keys=True, default=str))
    print(f"\nWrote ledger to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
