from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Any

from .venue_profiles import venue_profile


def _get_float(cfg: Any, key: str, default: float) -> float:
    raw = getattr(cfg, key, default)
    return float(default if raw is None else raw)


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS delta_neutral_carry_receipts (
            receipt_id TEXT PRIMARY KEY,
            created_ts REAL,
            symbol TEXT,
            spot_venue TEXT,
            futures_venue TEXT,
            holding_period_hours REAL,
            funding_income_bps REAL,
            net_edge_bps REAL,
            required_net_return_bps REAL,
            accepted INTEGER,
            payload TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_carry_symbol ON delta_neutral_carry_receipts(symbol, created_ts)"
    )
    conn.commit()


def default_cost_assumptions(cfg: Any) -> dict[str, float]:
    """Conservative default cost terms for the carry economics gate.

    These are configured research defaults, not verified account-tier
    figures (mirrors the same trust model as the rest of Phase 2/3: nothing
    here becomes "verified" without an explicit receipt). Callers should
    override any term they have better evidence for.
    """
    spot_profile = venue_profile(str(getattr(cfg, "exchange", "kraken") or "kraken"), cfg)
    futures_profile = venue_profile("kraken_futures", cfg)
    return {
        "spot_fees_bps": (spot_profile.maker_fee_bps + spot_profile.taker_fee_bps),
        "futures_fees_bps": (futures_profile.maker_fee_bps + futures_profile.taker_fee_bps),
        "spread_slippage_bps": _get_float(cfg, "delta_neutral_carry_spread_slippage_bps", 6.0),
        "collateral_cost_bps": _get_float(cfg, "delta_neutral_carry_collateral_cost_bps", 2.0),
        "funding_uncertainty_bps": _get_float(cfg, "delta_neutral_carry_funding_uncertainty_bps", 3.0),
        "rebalance_reserve_bps": _get_float(cfg, "delta_neutral_carry_rebalance_reserve_bps", 2.0),
        "safety_buffer_bps": _get_float(cfg, "delta_neutral_carry_safety_buffer_bps", 3.0),
    }


def evaluate_carry_opportunity(
    *,
    symbol: str,
    funding_income_bps: float,
    spot_fees_bps: float,
    futures_fees_bps: float,
    spread_slippage_bps: float,
    collateral_cost_bps: float,
    funding_uncertainty_bps: float,
    rebalance_reserve_bps: float,
    safety_buffer_bps: float,
    required_net_return_bps: float,
    holding_period_hours: float = 8.0,
    spot_venue: str = "kraken",
    futures_venue: str = "kraken_futures",
    funding_income_source: str = "manual_input_no_live_feed",
    now_ts: float | None = None,
) -> dict[str, Any]:
    """Engine B: delta-neutral carry economics gate.

    long spot + short perpetual (or dated future), collect funding/basis,
    stay approximately delta-neutral. This is a pure, testable calculator
    implementing exactly the formula the strategy spec requires:

        net_edge_bps = funding_or_basis_income_bps
                       - spot_fees_bps - futures_fees_bps
                       - spread_slippage_bps - collateral_cost_bps
                       - funding_uncertainty_bps - rebalance_reserve_bps
                       - safety_buffer_bps
        accepted = net_edge_bps > required_net_return_bps

    IMPORTANT: no live Kraken Futures funding-rate or basis feed exists
    anywhere in this codebase yet. ``funding_income_bps`` must be supplied by
    the caller (manual research input, backtest replay, or a future live
    feed once one is built) -- this function never fabricates that number,
    and every receipt records ``funding_income_source`` so downstream
    consumers can tell a real feed apart from a manual assumption.

    Like every other component in this codebase, this remains 100%
    research-only: ``execution_authority`` is always ``"none"`` and no order
    is ever placed. Leverage on the perpetual leg is fixed at 1x, matching
    the hard-locked ``hummingbot_v2_leverage`` invariant enforced elsewhere.
    """
    created_ts = float(now_ts if now_ts is not None else time.time())
    cost_terms = {
        "spot_fees_bps": float(spot_fees_bps),
        "futures_fees_bps": float(futures_fees_bps),
        "spread_slippage_bps": float(spread_slippage_bps),
        "collateral_cost_bps": float(collateral_cost_bps),
        "funding_uncertainty_bps": float(funding_uncertainty_bps),
        "rebalance_reserve_bps": float(rebalance_reserve_bps),
        "safety_buffer_bps": float(safety_buffer_bps),
    }
    total_cost_bps = sum(cost_terms.values())
    net_edge_bps = float(funding_income_bps) - total_cost_bps
    accepted = bool(net_edge_bps > float(required_net_return_bps))
    reasons: list[str] = []
    if funding_income_source == "manual_input_no_live_feed":
        reasons.append("funding_income_is_a_manual_research_input_not_a_live_feed")
    if not accepted:
        reasons.append("net_edge_below_required_return")

    payload: dict[str, Any] = {
        "schema": "hivenance_delta_neutral_carry_receipt_v1",
        "authority": "research_only_no_execution",
        "execution_authority": "none",
        "product": "delta_neutral_carry",
        "structure": "long_spot_short_perpetual",
        "leverage": 1,
        "symbol": symbol,
        "spot_venue": spot_venue,
        "futures_venue": futures_venue,
        "holding_period_hours": round(float(holding_period_hours), 6),
        "funding_income_bps": round(float(funding_income_bps), 6),
        "funding_income_source": funding_income_source,
        "cost_terms_bps": {key: round(value, 6) for key, value in cost_terms.items()},
        "total_cost_bps": round(total_cost_bps, 6),
        "net_edge_bps": round(net_edge_bps, 6),
        "required_net_return_bps": round(float(required_net_return_bps), 6),
        "accepted": accepted,
        "reasons": reasons,
        "created_ts": round(created_ts, 3),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload["receipt_id"] = "carry-" + hashlib.sha256(raw).hexdigest()[:24]
    return payload


def run_delta_neutral_carry_lab(
    conn: sqlite3.Connection,
    cfg: Any,
    *,
    symbol: str,
    funding_income_bps: float,
    required_net_return_bps: float | None = None,
    holding_period_hours: float = 8.0,
    funding_income_source: str = "manual_input_no_live_feed",
    now_ts: float | None = None,
    **cost_overrides: float,
) -> dict[str, Any]:
    """Persist a delta-neutral carry receipt using config-defaulted cost
    assumptions, with any term overridable via ``cost_overrides``.
    """
    ensure_schema(conn)
    defaults = default_cost_assumptions(cfg)
    defaults.update({key: float(value) for key, value in cost_overrides.items() if key in defaults})
    required = (
        float(required_net_return_bps)
        if required_net_return_bps is not None
        else _get_float(cfg, "delta_neutral_carry_min_required_net_return_bps", 15.0)
    )
    payload = evaluate_carry_opportunity(
        symbol=symbol,
        funding_income_bps=funding_income_bps,
        required_net_return_bps=required,
        holding_period_hours=holding_period_hours,
        funding_income_source=funding_income_source,
        now_ts=now_ts,
        **defaults,
    )
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO delta_neutral_carry_receipts
            (receipt_id, created_ts, symbol, spot_venue, futures_venue, holding_period_hours,
             funding_income_bps, net_edge_bps, required_net_return_bps, accepted, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                payload["receipt_id"],
                payload["created_ts"],
                payload["symbol"],
                payload["spot_venue"],
                payload["futures_venue"],
                payload["holding_period_hours"],
                payload["funding_income_bps"],
                payload["net_edge_bps"],
                payload["required_net_return_bps"],
                1 if payload["accepted"] else 0,
                json.dumps(payload, sort_keys=True),
            ),
        )
    return payload
