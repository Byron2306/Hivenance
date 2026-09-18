from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from .venue_profiles import venue_profile


@dataclass(frozen=True)
class DerivativesTrendLabConfig:
    symbols: tuple[str, ...]
    horizons_seconds: tuple[int, ...]
    lookbacks_seconds: tuple[int, ...]
    min_history_points: int
    min_data_quality: float
    max_spread_bps: float
    min_momentum_bps: float
    breakout_lookback_multiplier: float
    min_vol_expansion_ratio: float
    vol_baseline_multiplier: float
    min_market_breadth: float
    slippage_bps: float
    stress_multiplier: float
    min_entries_per_slice: int
    min_lower_bound_net_bps: float
    post_only_fill_probability: float
    funding_drag_bps_per_8h: float
    max_concurrent_positions: int


def _get_float(cfg: Any, key: str, default: float) -> float:
    raw = getattr(cfg, key, default)
    return float(default if raw is None else raw)


def _get_int(cfg: Any, key: str, default: int) -> int:
    raw = getattr(cfg, key, default)
    return int(default if raw is None else raw)


def config_from_settings(cfg: Any) -> DerivativesTrendLabConfig:
    return DerivativesTrendLabConfig(
        symbols=tuple(getattr(cfg, "derivatives_trend_symbols", ["BTC/USD", "ETH/USD", "SOL/USD"]) or []),
        horizons_seconds=tuple(
            int(v) for v in (getattr(cfg, "derivatives_trend_horizons_seconds", [43200, 86400, 259200]) or [])
        ),
        lookbacks_seconds=tuple(
            int(v) for v in (getattr(cfg, "derivatives_trend_lookbacks_seconds", [3600, 14400]) or [])
        ),
        min_history_points=max(2, _get_int(cfg, "derivatives_trend_min_history_points", 12)),
        min_data_quality=_get_float(cfg, "derivatives_trend_min_data_quality", 0.99),
        max_spread_bps=_get_float(cfg, "derivatives_trend_max_spread_bps", 40.0),
        min_momentum_bps=_get_float(cfg, "derivatives_trend_min_momentum_bps", 25.0),
        breakout_lookback_multiplier=_get_float(cfg, "derivatives_trend_breakout_lookback_multiplier", 1.0),
        min_vol_expansion_ratio=_get_float(cfg, "derivatives_trend_min_vol_expansion_ratio", 1.15),
        vol_baseline_multiplier=_get_float(cfg, "derivatives_trend_vol_baseline_multiplier", 4.0),
        min_market_breadth=_get_float(cfg, "derivatives_trend_min_market_breadth", 0.50),
        slippage_bps=_get_float(cfg, "derivatives_trend_slippage_bps", 3.0),
        stress_multiplier=_get_float(cfg, "derivatives_trend_cost_stress_multiplier", 1.5),
        min_entries_per_slice=max(1, _get_int(cfg, "derivatives_trend_min_entries_per_slice", 8)),
        min_lower_bound_net_bps=_get_float(cfg, "derivatives_trend_min_lower_bound_net_bps", 10.0),
        post_only_fill_probability=max(
            0.0, min(1.0, _get_float(cfg, "derivatives_trend_post_only_fill_probability", 0.75))
        ),
        funding_drag_bps_per_8h=_get_float(cfg, "derivatives_trend_funding_drag_bps_per_8h", 1.0),
        max_concurrent_positions=max(1, _get_int(cfg, "derivatives_trend_max_concurrent_positions", 1)),
    )


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS derivatives_trend_runs (
            run_id TEXT PRIMARY KEY,
            created_ts REAL,
            venue TEXT,
            symbols TEXT,
            horizons_seconds TEXT,
            lookbacks_seconds TEXT,
            receipt_count INTEGER,
            accepted_slice_count INTEGER,
            payload TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS derivatives_trend_receipts (
            receipt_id TEXT PRIMARY KEY,
            run_id TEXT,
            created_ts REAL,
            venue TEXT,
            symbol TEXT,
            horizon_seconds INTEGER,
            lookback_seconds INTEGER,
            policy TEXT,
            direction TEXT,
            entries INTEGER,
            win_rate REAL,
            mean_gross_bps REAL,
            mean_net_bps REAL,
            lower_bound_net_bps REAL,
            stressed_mean_net_bps REAL,
            accepted INTEGER,
            payload TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_deriv_trend_run ON derivatives_trend_receipts(run_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_deriv_trend_slice "
        "ON derivatives_trend_receipts(symbol, horizon_seconds, lookback_seconds, policy, direction)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_deriv_trend_accept ON derivatives_trend_receipts(accepted, lower_bound_net_bps)")
    conn.commit()


def _rows_for_symbol(
    conn: sqlite3.Connection, symbol: str, *, lookback_limit: int, venue: str | None = None
) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    if venue:
        rows = conn.execute(
            """
            SELECT ts, venue, symbol, price, spread_bps, data_quality, payload
            FROM observation_snapshots
            WHERE symbol=? AND price IS NOT NULL AND venue=?
            ORDER BY ts ASC
            LIMIT ?
            """,
            (symbol, str(venue), int(lookback_limit)),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT ts, venue, symbol, price, spread_bps, data_quality, payload
            FROM observation_snapshots
            WHERE symbol=? AND price IS NOT NULL
            ORDER BY ts ASC
            LIMIT ?
            """,
            (symbol, int(lookback_limit)),
        ).fetchall()
    return [dict(row) for row in rows]


def _rows_and_price_data_source(
    conn: sqlite3.Connection, symbol: str, *, lookback_limit: int, venue: str
) -> tuple[list[dict[str, Any]], str]:
    """Prefer genuine live rows tagged with ``venue`` (e.g. a real Kraken
    Futures observer); fall back to the spot proxy (any venue) only when no
    live rows exist yet for this symbol. Never silently mislabels the source.
    """
    live_rows = _rows_for_symbol(conn, symbol, lookback_limit=lookback_limit, venue=venue)
    if live_rows:
        return live_rows, f"{venue}_live_perpetual_feed"
    return _rows_for_symbol(conn, symbol, lookback_limit=lookback_limit), "kraken_spot_price_proxy_pending_futures_feed"


def _at_or_before(rows: list[dict[str, Any]], index: int, target_ts: float) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for row in rows[: index + 1]:
        if float(row.get("ts") or 0.0) <= target_ts:
            best = row
        else:
            break
    return best


def _at_or_after(rows: list[dict[str, Any]], start_index: int, target_ts: float, tolerance_sec: float) -> dict[str, Any] | None:
    deadline = float(target_ts) + float(tolerance_sec)
    for row in rows[start_index:]:
        ts = float(row.get("ts") or 0.0)
        if ts >= target_ts and ts <= deadline:
            return row
        if ts > deadline:
            return None
    return None


def _window_prices(rows: list[dict[str, Any]], index: int, window_start_ts: float) -> list[float]:
    prices: list[float] = []
    for row in rows[: index + 1]:
        ts = float(row.get("ts") or 0.0)
        if ts < window_start_ts:
            continue
        price = float(row.get("price") or 0.0)
        if price > 0.0:
            prices.append(price)
    return prices


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * q))))
    return ordered[idx]


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    avg = sum(values) / len(values)
    return math.sqrt(sum((value - avg) ** 2 for value in values) / (len(values) - 1))


def _digest(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _deoverlap(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only a chronological sequence of non-overlapping holding periods.

    Trade candidates are generated once per observation row, so closely spaced
    signal bars (e.g. 1h bars feeding a 72h horizon) would otherwise produce
    many overlapping positions that are not independent samples.
    """
    kept: list[dict[str, Any]] = []
    next_allowed_entry_ts = float("-inf")
    for trade in trades:
        entry_ts = float(trade["entry_ts"])
        if entry_ts < next_allowed_entry_ts:
            continue
        kept.append(trade)
        next_allowed_entry_ts = float(trade["exit_ts"])
    return kept


def _chronological_holdout_stats(nets: list[float]) -> tuple[float | None, float | None, int, int]:
    """Split a chronologically ordered net-bps series into train/holdout halves.

    The acceptance gate must use the holdout (out-of-sample) figure rather than
    a percentile computed on the same data used to discover the edge.
    """
    if not nets:
        return (None, None, 0, 0)
    train_count = len(nets) // 2
    train = nets[:train_count]
    holdout = nets[train_count:]
    in_sample_lower_bound = _quantile(nets, 0.25)
    holdout_lower_bound = _quantile(holdout, 0.25)
    return (in_sample_lower_bound, holdout_lower_bound, len(train), len(holdout))


def _policy_cost_bps(
    policy: str,
    *,
    profile: Any,
    spread_bps: float,
    slippage_bps: float,
    horizon_seconds: int,
    post_only_fill_probability: float,
    funding_drag_bps_per_8h: float,
) -> tuple[float, float]:
    """Return (roundtrip_cost_bps, fill_penalty_bps) for one policy.

    ``post_only_then_bounded_taker`` blends maker/taker fees by an assumed
    post-only fill probability: try passive first, fall back to a bounded
    taker execution the rest of the time. This is the default execution
    policy requested for the derivatives trend engine.
    """
    funding_periods = max(0.0, float(horizon_seconds) / (8.0 * 3600.0))
    funding_drag_bps = funding_periods * max(0.0, funding_drag_bps_per_8h)
    if policy == "passive_post_only":
        roundtrip_fee_bps = profile.maker_fee_bps * 2.0
        spread_cost_bps = spread_bps * 0.35
        fill_penalty_bps = 3.0
    elif policy == "taker_market":
        roundtrip_fee_bps = profile.taker_fee_bps * 2.0
        spread_cost_bps = spread_bps * 1.0
        fill_penalty_bps = 0.0
    else:  # post_only_then_bounded_taker
        blended_fee_per_side = (
            profile.maker_fee_bps * post_only_fill_probability
            + profile.taker_fee_bps * (1.0 - post_only_fill_probability)
        )
        roundtrip_fee_bps = blended_fee_per_side * 2.0
        spread_cost_bps = spread_bps * (0.35 + 0.65 * (1.0 - post_only_fill_probability))
        fill_penalty_bps = 1.5 * (1.0 - post_only_fill_probability)
    total_cost_bps = roundtrip_fee_bps + spread_cost_bps + slippage_bps + fill_penalty_bps + funding_drag_bps
    return total_cost_bps, funding_drag_bps


def run_derivatives_trend_lab(
    conn: sqlite3.Connection,
    cfg: Any,
    *,
    venue: str = "kraken_futures",
    now_ts: float | None = None,
    lookback_limit: int = 100_000,
) -> dict[str, Any]:
    """Engine A: medium-horizon derivatives trend research lab.

    candidate trade = trend direction + breakout confirmation + volatility
    expansion + market-wide confirmation + conservative cost budget.

    This lab reads price history from the same ``observation_snapshots`` table
    Phase 1 already populates. No live Kraken Futures market-data feed (perp
    price, funding rate, or basis) exists yet in this codebase, so every
    receipt is explicitly tagged ``price_data_source:
    kraken_spot_price_proxy_pending_futures_feed`` -- economics (fees) reflect
    a derivatives venue profile, but price/momentum are a spot proxy until a
    real futures observer is wired in. Never claims live/verified.
    """
    lab_cfg = config_from_settings(cfg)
    profile = venue_profile(venue, cfg)
    created_ts = float(now_ts if now_ts is not None else time.time())
    run_seed = {
        "created_ts": round(created_ts, 3),
        "venue": str(venue),
        "symbols": lab_cfg.symbols,
        "horizons_seconds": lab_cfg.horizons_seconds,
        "lookbacks_seconds": lab_cfg.lookbacks_seconds,
        "fee_source": profile.fee_source,
        "fee_verified": profile.fee_verified,
        "economics_receipt_sha256": profile.economics_receipt_sha256,
    }
    run_id = "deriv-trend-" + _digest(run_seed)[:16]
    ensure_schema(conn)

    all_rows: dict[str, list[dict[str, Any]]] = {}
    price_data_source_by_symbol: dict[str, str] = {}
    for symbol in lab_cfg.symbols:
        rows, source = _rows_and_price_data_source(conn, symbol, lookback_limit=lookback_limit, venue=venue)
        all_rows[symbol] = rows
        price_data_source_by_symbol[symbol] = source
    breadth_cache: dict[tuple[str, int, float, str], float | None] = {}

    def _market_breadth(symbol: str, lookback: int, entry_ts: float, direction_word: str) -> float | None:
        """Fraction of the OTHER tracked symbols trending the same direction.

        None means breadth could not be evaluated (fewer than 2 tracked
        symbols); callers should treat that as "not applicable" rather than a
        failed gate.
        """
        cache_key = (symbol, lookback, entry_ts, direction_word)
        if cache_key in breadth_cache:
            return breadth_cache[cache_key]
        peers = [other for other in lab_cfg.symbols if other != symbol]
        if not peers:
            breadth_cache[cache_key] = None
            return None
        agree = 0
        evaluated = 0
        for peer in peers:
            peer_rows = all_rows.get(peer) or []
            if not peer_rows:
                continue
            peer_now = _at_or_before(peer_rows, len(peer_rows) - 1, entry_ts)
            peer_prior = _at_or_before(peer_rows, len(peer_rows) - 1, entry_ts - float(lookback))
            if not peer_now or not peer_prior:
                continue
            now_price = float(peer_now.get("price") or 0.0)
            prior_price = float(peer_prior.get("price") or 0.0)
            if now_price <= 0.0 or prior_price <= 0.0:
                continue
            peer_momentum = ((now_price - prior_price) / prior_price) * 10_000.0
            evaluated += 1
            if direction_word == "UP" and peer_momentum > 0.0:
                agree += 1
            elif direction_word == "DOWN" and peer_momentum < 0.0:
                agree += 1
        breadth = (agree / evaluated) if evaluated else None
        breadth_cache[cache_key] = breadth
        return breadth

    receipts: list[dict[str, Any]] = []
    tolerance_sec = max(600.0, max(lab_cfg.horizons_seconds or (600,)) * 0.08)
    policies = ("post_only_then_bounded_taker", "passive_post_only", "taker_market")
    for symbol in lab_cfg.symbols:
        rows = all_rows.get(symbol) or []
        if len(rows) < lab_cfg.min_history_points:
            continue
        for horizon in lab_cfg.horizons_seconds:
            for lookback in lab_cfg.lookbacks_seconds:
                breakout_window_sec = float(lookback) * max(1.0, lab_cfg.breakout_lookback_multiplier)
                vol_baseline_window = max(1, int(round(lab_cfg.min_history_points * lab_cfg.vol_baseline_multiplier)))
                for policy in policies:
                    up_candidates: list[dict[str, Any]] = []
                    down_candidates: list[dict[str, Any]] = []
                    for index, entry in enumerate(rows):
                        if index < lab_cfg.min_history_points:
                            continue
                        entry_ts = float(entry.get("ts") or 0.0)
                        entry_price = float(entry.get("price") or 0.0)
                        if entry_price <= 0.0:
                            continue
                        history = _at_or_before(rows, index, entry_ts - float(lookback))
                        target = _at_or_after(rows, index + 1, entry_ts + float(horizon), tolerance_sec)
                        if not history or not target:
                            continue
                        history_price = float(history.get("price") or 0.0)
                        exit_price = float(target.get("price") or 0.0)
                        if history_price <= 0.0 or exit_price <= 0.0:
                            continue
                        spread_bps = max(0.0, float(entry.get("spread_bps") or 0.0))
                        quality = float(entry.get("data_quality") or 0.0)
                        if quality < lab_cfg.min_data_quality or spread_bps > lab_cfg.max_spread_bps:
                            continue

                        momentum_bps = ((entry_price - history_price) / history_price) * 10_000.0
                        if abs(momentum_bps) < lab_cfg.min_momentum_bps:
                            continue
                        direction_word = "UP" if momentum_bps > 0.0 else "DOWN"

                        # Breakout confirmation: entry price must break the
                        # recent trading range, not merely have positive net
                        # momentum over the lookback.
                        window_prices = _window_prices(rows, index, entry_ts - breakout_window_sec)
                        if len(window_prices) < 2:
                            continue
                        if direction_word == "UP" and entry_price < max(window_prices):
                            continue
                        if direction_word == "DOWN" and entry_price > min(window_prices):
                            continue

                        # Volatility expansion confirmation: recent realized
                        # vol must be meaningfully above its own baseline.
                        recent_returns = []
                        for left, right in zip(
                            rows[max(0, index - lab_cfg.min_history_points):index],
                            rows[max(1, index - lab_cfg.min_history_points + 1): index + 1],
                        ):
                            left_price = float(left.get("price") or 0.0)
                            right_price = float(right.get("price") or 0.0)
                            if left_price > 0.0 and right_price > 0.0:
                                recent_returns.append(((right_price - left_price) / left_price) * 10_000.0)
                        baseline_returns = []
                        for left, right in zip(
                            rows[max(0, index - vol_baseline_window):index],
                            rows[max(1, index - vol_baseline_window + 1): index + 1],
                        ):
                            left_price = float(left.get("price") or 0.0)
                            right_price = float(right.get("price") or 0.0)
                            if left_price > 0.0 and right_price > 0.0:
                                baseline_returns.append(((right_price - left_price) / left_price) * 10_000.0)
                        realized_vol_bps = _stdev(recent_returns)
                        baseline_vol_bps = _stdev(baseline_returns)
                        if baseline_vol_bps <= 0.0:
                            continue
                        vol_expansion_ratio = realized_vol_bps / baseline_vol_bps
                        if vol_expansion_ratio < lab_cfg.min_vol_expansion_ratio:
                            continue

                        # Market-wide confirmation: a majority of the other
                        # tracked symbols must be trending the same direction.
                        breadth = _market_breadth(symbol, lookback, entry_ts, direction_word)
                        if breadth is not None and breadth < lab_cfg.min_market_breadth:
                            continue

                        total_cost_bps, funding_drag_bps = _policy_cost_bps(
                            policy,
                            profile=profile,
                            spread_bps=spread_bps,
                            slippage_bps=lab_cfg.slippage_bps,
                            horizon_seconds=horizon,
                            post_only_fill_probability=lab_cfg.post_only_fill_probability,
                            funding_drag_bps_per_8h=lab_cfg.funding_drag_bps_per_8h,
                        )
                        stressed_cost_bps = total_cost_bps * lab_cfg.stress_multiplier
                        price_move_bps = ((exit_price - entry_price) / entry_price) * 10_000.0
                        directional_gross_bps = price_move_bps if direction_word == "UP" else -price_move_bps

                        trade = {
                            "entry_ts": entry_ts,
                            "exit_ts": float(target.get("ts") or 0.0),
                            "entry_price": entry_price,
                            "exit_price": exit_price,
                            "momentum_bps": round(momentum_bps, 6),
                            "vol_expansion_ratio": round(vol_expansion_ratio, 6),
                            "market_breadth": round(breadth, 6) if breadth is not None else None,
                            "gross_bps": round(directional_gross_bps, 6),
                            "cost_bps": round(total_cost_bps, 6),
                            "funding_drag_bps": round(funding_drag_bps, 6),
                            "net_bps": round(directional_gross_bps - total_cost_bps, 6),
                            "stressed_net_bps": round(directional_gross_bps - stressed_cost_bps, 6),
                            "spread_bps": round(spread_bps, 6),
                        }
                        (up_candidates if direction_word == "UP" else down_candidates).append(trade)

                    for direction_word, candidates in (("UP", up_candidates), ("DOWN", down_candidates)):
                        trades = _deoverlap(candidates)
                        nets = [float(trade["net_bps"]) for trade in trades]
                        gross = [float(trade["gross_bps"]) for trade in trades]
                        stressed = [float(trade["stressed_net_bps"]) for trade in trades]
                        mean_net = _mean(nets)
                        in_sample_lower_bound, holdout_lower_bound, train_entries, holdout_entries = (
                            _chronological_holdout_stats(nets)
                        )
                        min_holdout_entries = max(1, lab_cfg.min_entries_per_slice // 2)
                        accepted = bool(
                            len(trades) >= lab_cfg.min_entries_per_slice
                            and holdout_entries >= min_holdout_entries
                            and holdout_lower_bound is not None
                            and holdout_lower_bound >= lab_cfg.min_lower_bound_net_bps
                            and (profile.fee_verified or bool(getattr(cfg, "derivatives_trend_allow_unverified_fees", False)))
                        )
                        payload = {
                            "schema": "hivenance_derivatives_trend_receipt_v1",
                            "authority": "research_only_no_execution",
                            "execution_authority": "none",
                            "run_id": run_id,
                            "venue": str(venue),
                            "symbol": symbol,
                            "horizon_seconds": int(horizon),
                            "lookback_seconds": int(lookback),
                            "policy": policy,
                            "direction": direction_word,
                            "spot_executable": False,
                            "product": "perpetual_future",
                            "leverage": 1,
                            "price_data_source": price_data_source_by_symbol.get(
                                symbol, "kraken_spot_price_proxy_pending_futures_feed"
                            ),
                            "entries": len(trades),
                            "raw_overlapping_entries": len(candidates),
                            "train_entries": train_entries,
                            "holdout_entries": holdout_entries,
                            "win_rate": round(sum(1 for value in nets if value > 0.0) / len(nets), 6) if nets else None,
                            "mean_gross_bps": round(_mean(gross), 6) if gross else None,
                            "mean_net_bps": round(mean_net, 6) if mean_net is not None else None,
                            "lower_bound_net_bps": round(holdout_lower_bound, 6) if holdout_lower_bound is not None else None,
                            "in_sample_lower_bound_net_bps": round(in_sample_lower_bound, 6) if in_sample_lower_bound is not None else None,
                            "stressed_mean_net_bps": round(_mean(stressed), 6) if stressed else None,
                            "fee_source": profile.fee_source,
                            "fee_verified": profile.fee_verified,
                            "economics_receipt_sha256": profile.economics_receipt_sha256,
                            "maker_fee_bps": profile.maker_fee_bps,
                            "taker_fee_bps": profile.taker_fee_bps,
                            "execution_policy": {
                                "post_only_fill_probability": lab_cfg.post_only_fill_probability,
                                "bounded_taker_fallback": True,
                                "max_concurrent_positions": lab_cfg.max_concurrent_positions,
                            },
                            "config": {**lab_cfg.__dict__, "symbols": list(lab_cfg.symbols)},
                            "sample_trades": trades[-25:],
                            "accepted": accepted,
                        }
                        payload["receipt_id"] = "dtrend-" + _digest(payload)[:24]
                        receipts.append(payload)

    receipts.sort(
        key=lambda row: (
            0 if row.get("accepted") else 1,
            -(float(row.get("lower_bound_net_bps") or -1_000_000.0)),
            str(row.get("symbol") or ""),
            int(row.get("horizon_seconds") or 0),
            int(row.get("lookback_seconds") or 0),
            str(row.get("policy") or ""),
            str(row.get("direction") or ""),
        )
    )
    _unique_sources = set(price_data_source_by_symbol.values())
    overall_price_data_source = (
        _unique_sources.pop()
        if len(_unique_sources) == 1
        else "mixed_see_price_data_source_by_symbol"
        if _unique_sources
        else "kraken_spot_price_proxy_pending_futures_feed"
    )
    summary = {
        "schema": "hivenance_derivatives_trend_run_v1",
        "run_id": run_id,
        "created_ts": created_ts,
        "venue": str(venue),
        "product": "perpetual_future",
        "leverage": 1,
        "price_data_source": overall_price_data_source,
        "price_data_source_by_symbol": price_data_source_by_symbol,
        "symbols": lab_cfg.symbols,
        "horizons_seconds": lab_cfg.horizons_seconds,
        "lookbacks_seconds": lab_cfg.lookbacks_seconds,
        "receipt_count": len(receipts),
        "accepted_slice_count": sum(1 for row in receipts if row.get("accepted")),
        "fee_source": profile.fee_source,
        "fee_verified": profile.fee_verified,
        "economics_receipt_sha256": profile.economics_receipt_sha256,
        "best_slices": receipts[:10],
        "execution_authority": "none",
    }
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO derivatives_trend_runs
            (run_id, created_ts, venue, symbols, horizons_seconds, lookbacks_seconds,
             receipt_count, accepted_slice_count, payload)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                created_ts,
                str(venue),
                json.dumps(list(lab_cfg.symbols)),
                json.dumps(list(lab_cfg.horizons_seconds)),
                json.dumps(list(lab_cfg.lookbacks_seconds)),
                len(receipts),
                int(summary["accepted_slice_count"]),
                json.dumps(summary, sort_keys=True),
            ),
        )
        for row in receipts:
            conn.execute(
                """
                INSERT OR REPLACE INTO derivatives_trend_receipts
                (receipt_id, run_id, created_ts, venue, symbol, horizon_seconds, lookback_seconds,
                 policy, direction, entries, win_rate, mean_gross_bps, mean_net_bps, lower_bound_net_bps,
                 stressed_mean_net_bps, accepted, payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    row["receipt_id"],
                    run_id,
                    created_ts,
                    str(venue),
                    row["symbol"],
                    int(row["horizon_seconds"]),
                    int(row["lookback_seconds"]),
                    row["policy"],
                    row["direction"],
                    int(row["entries"]),
                    row["win_rate"],
                    row["mean_gross_bps"],
                    row["mean_net_bps"],
                    row["lower_bound_net_bps"],
                    row["stressed_mean_net_bps"],
                    1 if row["accepted"] else 0,
                    json.dumps(row, sort_keys=True),
                ),
            )
    return summary
