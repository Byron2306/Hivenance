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
class TrendLabConfig:
    symbols: tuple[str, ...]
    horizons_seconds: tuple[int, ...]
    lookbacks_seconds: tuple[int, ...]
    min_history_points: int
    min_data_quality: float
    max_spread_bps: float
    min_momentum_bps: float
    slippage_bps: float
    stress_multiplier: float
    min_entries_per_slice: int
    min_lower_bound_net_bps: float


def config_from_settings(cfg: Any) -> TrendLabConfig:
    return TrendLabConfig(
        symbols=tuple(getattr(cfg, "medium_trend_symbols", ["BTC/USD", "ETH/USD", "SOL/USD"]) or []),
        horizons_seconds=tuple(int(v) for v in (getattr(cfg, "medium_trend_horizons_seconds", [14400, 21600, 43200, 86400]) or [])),
        lookbacks_seconds=tuple(int(v) for v in (getattr(cfg, "medium_trend_lookbacks_seconds", [3600, 14400, 86400]) or [])),
        min_history_points=max(2, int(getattr(cfg, "medium_trend_min_history_points", 12) or 12)),
        min_data_quality=float(getattr(cfg, "medium_trend_min_data_quality", 0.99) or 0.99),
        max_spread_bps=float(getattr(cfg, "medium_trend_max_spread_bps", 40.0) or 40.0),
        min_momentum_bps=float(getattr(cfg, "medium_trend_min_momentum_bps", 35.0) or 35.0),
        slippage_bps=float(getattr(cfg, "medium_trend_slippage_bps", 10.0) or 10.0),
        stress_multiplier=float(getattr(cfg, "medium_trend_cost_stress_multiplier", 1.5) or 1.5),
        min_entries_per_slice=max(1, int(getattr(cfg, "medium_trend_min_entries_per_slice", 8) or 8)),
        min_lower_bound_net_bps=float(getattr(cfg, "medium_trend_min_lower_bound_net_bps", 5.0) or 5.0),
    )


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS medium_horizon_trend_runs (
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
        CREATE TABLE IF NOT EXISTS medium_horizon_trend_receipts (
            receipt_id TEXT PRIMARY KEY,
            run_id TEXT,
            created_ts REAL,
            venue TEXT,
            symbol TEXT,
            horizon_seconds INTEGER,
            lookback_seconds INTEGER,
            policy TEXT,
            entries INTEGER,
            win_rate REAL,
            mean_gross_bps REAL,
            mean_net_bps REAL,
            lower_bound_net_bps REAL,
            stressed_mean_net_bps REAL,
            buy_hold_mean_net_bps REAL,
            accepted INTEGER,
            payload TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_medium_trend_run ON medium_horizon_trend_receipts(run_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_medium_trend_slice ON medium_horizon_trend_receipts(symbol, horizon_seconds, lookback_seconds, policy)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_medium_trend_accept ON medium_horizon_trend_receipts(accepted, lower_bound_net_bps)")
    conn.commit()


def _rows_for_symbol(conn: sqlite3.Connection, symbol: str, *, lookback_limit: int) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
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
    """Greedily drop trades whose entry falls before the prior kept trade's exit.

    Trade candidates are generated once per observation row, so closely spaced
    observations (e.g. hourly snapshots feeding a 24h horizon) would otherwise
    yield many overlapping positions that are not independent samples. This
    keeps only a chronological sequence of non-overlapping holding periods.
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


def _chronological_holdout_stats(
    nets: list[float],
) -> tuple[float | None, float | None, int, int]:
    """Split a chronologically ordered net-bps series into train/holdout halves.

    Returns (in_sample_lower_bound, holdout_lower_bound, train_entries, holdout_entries).
    The acceptance gate must use the holdout figure so it reflects genuine
    out-of-sample evidence rather than a percentile computed on the same data
    used to discover the edge.
    """
    if not nets:
        return (None, None, 0, 0)
    train_count = len(nets) // 2
    train = nets[:train_count]
    holdout = nets[train_count:]
    in_sample_lower_bound = _quantile(nets, 0.25)
    holdout_lower_bound = _quantile(holdout, 0.25)
    return (in_sample_lower_bound, holdout_lower_bound, len(train), len(holdout))


def run_medium_horizon_trend_lab(
    conn: sqlite3.Connection,
    cfg: Any,
    *,
    venue: str = "kraken",
    now_ts: float | None = None,
    lookback_limit: int = 100_000,
) -> dict[str, Any]:
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
    run_id = "medium-trend-" + _digest(run_seed)[:16]
    ensure_schema(conn)

    receipts: list[dict[str, Any]] = []
    tolerance_sec = max(600.0, max(lab_cfg.horizons_seconds or (600,)) * 0.08)
    for symbol in lab_cfg.symbols:
        rows = _rows_for_symbol(conn, symbol, lookback_limit=lookback_limit)
        if len(rows) < lab_cfg.min_history_points:
            continue
        for horizon in lab_cfg.horizons_seconds:
            for lookback in lab_cfg.lookbacks_seconds:
                for policy in ("passive_post_only", "taker_market"):
                    up_candidates: list[dict[str, Any]] = []
                    down_candidates: list[dict[str, Any]] = []
                    buy_hold: list[float] = []
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
                        price_move_bps = ((exit_price - entry_price) / entry_price) * 10_000.0
                        roundtrip_fee_bps = (
                            profile.maker_fee_bps * 2.0
                            if policy == "passive_post_only"
                            else profile.taker_fee_bps * 2.0
                        )
                        spread_cost_bps = spread_bps * (0.35 if policy == "passive_post_only" else 1.0)
                        fill_penalty_bps = 5.0 if policy == "passive_post_only" else 0.0
                        total_cost_bps = roundtrip_fee_bps + spread_cost_bps + lab_cfg.slippage_bps + fill_penalty_bps
                        stressed_cost_bps = total_cost_bps * lab_cfg.stress_multiplier
                        # buy_hold benchmark is always long-only (spot buy-and-hold).
                        buy_hold.append(price_move_bps - total_cost_bps)
                        if abs(momentum_bps) < lab_cfg.min_momentum_bps:
                            continue
                        recent_returns = []
                        for left, right in zip(rows[max(0, index - 12):index], rows[max(1, index - 11): index + 1]):
                            left_price = float(left.get("price") or 0.0)
                            right_price = float(right.get("price") or 0.0)
                            if left_price > 0.0 and right_price > 0.0:
                                recent_returns.append(((right_price - left_price) / left_price) * 10_000.0)
                        realized_vol_bps = _stdev(recent_returns)
                        # Long ("UP") gains when price rises; short ("DOWN") gains when it falls.
                        # Costs (fees/spread/slippage) are symmetric round-trip charges either way.
                        direction_word = "UP" if momentum_bps > 0.0 else "DOWN"
                        directional_gross_bps = price_move_bps if direction_word == "UP" else -price_move_bps
                        trade = {
                            "entry_ts": entry_ts,
                            "exit_ts": float(target.get("ts") or 0.0),
                            "entry_price": entry_price,
                            "exit_price": exit_price,
                            "momentum_bps": round(momentum_bps, 6),
                            "realized_vol_bps": round(realized_vol_bps, 6),
                            "gross_bps": round(directional_gross_bps, 6),
                            "cost_bps": round(total_cost_bps, 6),
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
                            and (profile.fee_verified or bool(getattr(cfg, "medium_trend_allow_unverified_fees", False)))
                        )
                        payload = {
                            "schema": "hivenance_medium_horizon_trend_receipt_v1",
                            "authority": "research_only_no_execution",
                            "execution_authority": "none",
                            "run_id": run_id,
                            "venue": str(venue),
                            "symbol": symbol,
                            "horizon_seconds": int(horizon),
                            "lookback_seconds": int(lookback),
                            "policy": policy,
                            "direction": direction_word,
                            "spot_executable": direction_word == "UP",
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
                            "buy_hold_mean_net_bps": round(_mean(buy_hold), 6) if buy_hold else None,
                            "fee_source": profile.fee_source,
                            "fee_verified": profile.fee_verified,
                            "economics_receipt_sha256": profile.economics_receipt_sha256,
                            "maker_fee_bps": profile.maker_fee_bps,
                            "taker_fee_bps": profile.taker_fee_bps,
                            "config": lab_cfg.__dict__,
                            "sample_trades": trades[-25:],
                            "accepted": accepted,
                        }
                        payload["receipt_id"] = "mtrend-" + _digest(payload)[:24]
                        receipts.append(payload)

    receipts.sort(
        key=lambda row: (
            0 if row.get("accepted") else 1,
            -(float(row.get("lower_bound_net_bps") or -1_000_000.0)),
            str(row.get("symbol") or ""),
            int(row.get("horizon_seconds") or 0),
            int(row.get("lookback_seconds") or 0),
            str(row.get("policy") or ""),
        )
    )
    summary = {
        "schema": "hivenance_medium_horizon_trend_run_v1",
        "run_id": run_id,
        "created_ts": created_ts,
        "venue": str(venue),
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
            INSERT OR REPLACE INTO medium_horizon_trend_runs
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
                INSERT OR REPLACE INTO medium_horizon_trend_receipts
                (receipt_id, run_id, created_ts, venue, symbol, horizon_seconds, lookback_seconds,
                 policy, entries, win_rate, mean_gross_bps, mean_net_bps, lower_bound_net_bps,
                 stressed_mean_net_bps, buy_hold_mean_net_bps, accepted, payload)
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
                    int(row["entries"]),
                    row["win_rate"],
                    row["mean_gross_bps"],
                    row["mean_net_bps"],
                    row["lower_bound_net_bps"],
                    row["stressed_mean_net_bps"],
                    row["buy_hold_mean_net_bps"],
                    1 if row["accepted"] else 0,
                    json.dumps(row, sort_keys=True),
                ),
            )
    return summary
