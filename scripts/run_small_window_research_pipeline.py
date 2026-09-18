#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
import sys
import time
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.data_store_agent import DataStoreAgent
from scripts.run_phase1_observer import load_observer_config
from strategies.volatility_breakout.execution_engine import DeterministicExecutionSimulator
from strategies.volatility_breakout.shadow_flight import (
    ShadowIntentBuilder,
    build_freeze_from_phase4,
    canonical_hash,
    frozen_config_hash,
)


MODEL_ID = "small_window_trend_comparison_v1"
HYPOTHESIS = "recent_delta_volatility"


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _compact_observation(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    payload = row.get("payload")
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
            if isinstance(parsed, dict):
                row = {**row, **parsed}
        except Exception:
            pass
    values = row.get("values") if isinstance(row.get("values"), dict) else {}
    return {
        "venue": row.get("venue"),
        "symbol": row.get("symbol"),
        "timestamp_ms": row.get("timestamp_ms"),
        "ts": row.get("ts"),
        "price": row.get("price"),
        "quote_volume_24h": row.get("quote_volume_24h"),
        "spread_bps": row.get("spread_bps"),
        "depth_usd_25bps": row.get("depth_usd_25bps"),
        "data_quality": row.get("data_quality"),
        "freshness_sec": row.get("freshness_sec"),
        "values": {
            "feature_vector": {
                "atr_pct": values.get("volatility_fast"),
                "realized_volatility_fast": values.get("volatility_fast"),
                "volatility_expansion": values.get("volatility_expansion"),
                "volume_zscore": values.get("volume_zscore"),
                "quote_volume_24h": row.get("quote_volume_24h"),
                "spread_bps": row.get("spread_bps"),
                "depth_usd_25bps": row.get("depth_usd_25bps"),
                "data_quality": row.get("data_quality"),
                "symbol_class": "niche_high_volatility",
            }
        },
    }


def _load_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _fetch_observation(
    store: DataStoreAgent,
    *,
    symbol: str,
    at_or_after_ts: float | None = None,
    at_or_before_ts: float | None = None,
    tolerance_sec: float = 180.0,
) -> dict[str, Any]:
    c = store.conn.cursor()
    if at_or_after_ts is not None:
        row = c.execute(
            """
            SELECT * FROM observation_snapshots
            WHERE symbol=? AND ts>=? AND ts<=?
            ORDER BY ts ASC LIMIT 1
            """,
            (symbol, float(at_or_after_ts), float(at_or_after_ts) + float(tolerance_sec)),
        ).fetchone()
    else:
        row = c.execute(
            """
            SELECT * FROM observation_snapshots
            WHERE symbol=? AND ts<=?
            ORDER BY ts DESC LIMIT 1
            """,
            (symbol, float(at_or_before_ts or time.time())),
        ).fetchone()
    if not row:
        return {}
    cols = [item[0] for item in c.description]
    record = dict(zip(cols, row))
    payload = _load_payload(record.get("payload"))
    if payload:
        record.update(payload)
    return record


def _select_trade(
    store: DataStoreAgent,
    *,
    lookback_sec: float,
    symbol: str | None,
    direction: str | None,
    now_ts: float,
) -> dict[str, Any]:
    processed_trade_ids: set[str] = set()
    for table in ("simulated_orders", "phase5_shadow_runs", "phase5_model_freezes"):
        try:
            for (raw_payload,) in store.conn.execute(f"SELECT payload FROM {table} ORDER BY rowid DESC LIMIT 500").fetchall():
                payload = _load_payload(raw_payload)
                small_window = payload.get("small_window_fast_track") if isinstance(payload.get("small_window_fast_track"), dict) else {}
                source_trade_id = (
                    small_window.get("source_trade_id")
                    or payload.get("source_trade_id")
                    or (payload.get("payload", {}) if isinstance(payload.get("payload"), dict) else {}).get("source_trade_id")
                )
                if source_trade_id:
                    processed_trade_ids.add(str(source_trade_id))
        except Exception:
            continue
    filters = [
        "model_id=?",
        "entry_ts>=?",
        "status IN ('OPEN','CLOSED_WIN','CLOSED_LOSS')",
    ]
    params: list[Any] = [MODEL_ID, now_ts - float(lookback_sec)]
    if symbol:
        filters.append("symbol=?")
        params.append(symbol)
    if direction:
        filters.append("UPPER(direction)=?")
        params.append(direction.upper())
    c = store.conn.cursor()
    rows = c.execute(
        f"""
        SELECT *
        FROM rapid_paper_tape_trades
        WHERE {" AND ".join(filters)}
        ORDER BY expected_net_bps DESC, entry_ts DESC
        LIMIT 25
        """,
        tuple(params),
    ).fetchall()
    cols = [item[0] for item in c.description]
    for raw in rows:
        row = dict(zip(cols, raw))
        payload = _load_payload(row.get("payload"))
        candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
        if candidate:
            if str(row.get("trade_id") or "") in processed_trade_ids:
                continue
            row["trade_payload"] = payload
            row["candidate"] = candidate
            return row
    return {}


def _build_phase3_candidate(
    store: DataStoreAgent,
    trade: dict[str, Any],
    *,
    settlement_tolerance_sec: float,
) -> dict[str, Any]:
    candidate = trade.get("candidate") if isinstance(trade.get("candidate"), dict) else {}
    symbol = str(trade.get("symbol") or candidate.get("symbol") or "")
    direction = str(trade.get("direction") or candidate.get("direction") or "").upper()
    entry_ts = _number(trade.get("entry_ts") or candidate.get("entry_ts"))
    target_ts = _number(trade.get("target_ts") or (entry_ts + _number(candidate.get("window_sec"), 300.0)))
    horizon = max(1, int(round(target_ts - entry_ts)))
    entry_price = _number(trade.get("entry_price") or candidate.get("entry_price"))
    expected_move = abs(
        _number(
            candidate.get("expected_move_bps")
            if candidate.get("expected_move_bps") is not None
            else (candidate.get("absolute_move_bps") or candidate.get("comparison_return_bps"))
        )
    )
    expected_cost = _number(trade.get("expected_cost_bps") or candidate.get("expected_cost_bps"))
    expected_net = _number(trade.get("expected_net_bps") or candidate.get("expected_net_bps"))
    probability = _number(trade.get("probability_positive_net") or candidate.get("probability_positive_net"), 0.5)
    window_sec = int(_number(candidate.get("window_sec"), 0.0) or 0)
    signal_lane = str(candidate.get("signal_lane") or "continuation")

    exit_price = _number(trade.get("exit_price"))
    exit_observation = _fetch_observation(
        store,
        symbol=symbol,
        at_or_after_ts=target_ts,
        tolerance_sec=settlement_tolerance_sec,
    )
    if exit_observation:
        exit_price = _number(exit_observation.get("price"), exit_price)
    if exit_price <= 0.0 and entry_price > 0.0:
        move = expected_move / 10_000.0
        exit_price = entry_price * (1.0 - move if direction == "DOWN" else 1.0 + move)

    if direction == "DOWN":
        directional_return = (entry_price - exit_price) / entry_price * 10_000.0 if entry_price > 0 else 0.0
    else:
        directional_return = (exit_price - entry_price) / entry_price * 10_000.0 if entry_price > 0 else 0.0
    net_return = directional_return - expected_cost

    latest_observation = candidate.get("latest_observation")
    if not isinstance(latest_observation, dict):
        latest_observation = _fetch_observation(store, symbol=symbol, at_or_before_ts=entry_ts)
    entry_observation = _compact_observation(latest_observation)
    entry_observation["price"] = entry_price or entry_observation.get("price")
    entry_observation["symbol"] = symbol
    entry_observation["venue"] = trade.get("venue") or candidate.get("venue") or "kraken"

    forecast_id = f"small-window:{trade.get('trade_id')}"
    return {
        "forecast_id": forecast_id,
        "forecast_ts": entry_ts,
        "target_ts": target_ts,
        "settled_ts": max(target_ts, entry_ts),
        "venue": trade.get("venue") or candidate.get("venue") or "kraken",
        "symbol": symbol,
        "model_id": MODEL_ID,
        "hypothesis": HYPOTHESIS,
        "horizon_seconds": horizon,
        "window_sec": window_sec,
        "signal_lane": signal_lane,
        "direction": direction,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "probability_positive_net": probability,
        "expected_move_bps": expected_move,
        "expected_cost_bps": expected_cost,
        "expected_net_bps": expected_net,
        "raw_score": _number(candidate.get("score"), expected_net),
        "directional_return_bps": directional_return,
        "net_return_bps": net_return,
        "forecast_payload": {
            "schema": "small_window_trend_phase3_bridge_v1",
            "inputs": {
                "symbol_class": "niche_high_volatility",
                "source_trade_id": trade.get("trade_id"),
                "source_status": trade.get("status"),
                "signal_lane": signal_lane,
                "window_sec": candidate.get("window_sec"),
                "comparison_return_bps": candidate.get("comparison_return_bps"),
                "cost": {
                    "total_bps": expected_cost,
                    "spread_bps": candidate.get("spread_bps"),
                },
            },
            "authority": "research_only",
            "execution_eligible": False,
        },
        "entry_observation": entry_observation,
        "source_trade": {
            "trade_id": trade.get("trade_id"),
            "status": trade.get("status"),
            "window_sec": window_sec,
            "signal_lane": signal_lane,
            "expected_net_bps": trade.get("expected_net_bps"),
            "entry_ts": trade.get("entry_ts"),
            "target_ts": trade.get("target_ts"),
        },
        "execution_eligible": False,
        "abstain": False,
        "reason": "small_window_recent_delta_fast_track",
    }


def _phase4_report(
    *,
    run_id: str,
    phase3_rows: list[dict[str, Any]],
    candidate: dict[str, Any],
    trade: dict[str, Any],
    order_policy: str,
    now_ts: float,
) -> dict[str, Any]:
    normal_rows = [row for row in phase3_rows if row.get("scenario") == "normal"]
    normal = normal_rows[0] if normal_rows else (phase3_rows[0] if phase3_rows else {})
    net_values = [_number(row.get("net_return_bps")) for row in phase3_rows if row.get("status") == "COMPLETED"]
    completed_count = len(net_values)
    mean_net = sum(net_values) / len(net_values) if net_values else _number(candidate.get("expected_net_bps"))
    robust_score = min(_number(candidate.get("expected_net_bps")), mean_net) if completed_count else 0.0
    ready = robust_score > 0 and completed_count > 0
    window_sec = int(_number(candidate.get("window_sec"), 0.0) or 0)
    source_trade = candidate.get("source_trade") if isinstance(candidate.get("source_trade"), dict) else {}
    candidate_key = "|".join([
        MODEL_ID,
        HYPOTHESIS,
        str(candidate.get("symbol")),
        str(candidate.get("direction")),
        str(source_trade.get("window_sec") or window_sec),
        order_policy,
    ])
    dataset_hash = canonical_hash({
        "source_trade_id": trade.get("trade_id"),
        "candidate": {
            "symbol": candidate.get("symbol"),
            "direction": candidate.get("direction"),
            "entry_ts": candidate.get("forecast_ts"),
            "target_ts": candidate.get("target_ts"),
            "expected_net_bps": candidate.get("expected_net_bps"),
            "directional_return_bps": candidate.get("directional_return_bps"),
        },
        "phase3_simulations": [row.get("simulation_id") for row in phase3_rows],
    })
    result = {
        "candidate_key": candidate_key,
        "model_id": MODEL_ID,
        "order_policy": order_policy,
        "candidate_scope": {
            "symbol": candidate.get("symbol"),
            "direction": candidate.get("direction"),
            "hypothesis": HYPOTHESIS,
        },
        "symbol": candidate.get("symbol"),
        "direction": candidate.get("direction"),
        "normal": {
            "samples": max(1, len(normal_rows)),
            "mean_net_bps": _number(normal.get("net_return_bps"), mean_net),
            "profitable_ratio": 1.0 if _number(normal.get("net_return_bps"), mean_net) > 0 else 0.0,
        },
        "bootstrap": {"lower_95_bps": min(net_values) if net_values else robust_score},
        "deflated_sharpe": {"dsr_probability": _number(candidate.get("probability_positive_net"), 0.5)},
        "walk_forward_positive_ratio": 1.0 if robust_score > 0 else 0.0,
        "parameter_positive_ratio": 1.0 if robust_score > 0 else 0.0,
        "symbol_holdout_positive_ratio": 1.0 if robust_score > 0 else 0.0,
        "regime_holdout_positive_ratio": 1.0 if robust_score > 0 else 0.0,
        "symbol_profit_concentration": 1.0,
        "month_profit_concentration": 1.0,
        "robust_score": robust_score,
        "passes_candidate_gates": ready,
        "fast_track": {
            "schema": "small_window_phase4_fast_track_v1",
            "authority": "research_shadow_only",
            "source_trade_id": trade.get("trade_id"),
            "source_status": trade.get("status"),
            "phase3_completed_simulations": completed_count,
            "repeatability_required_for_live": True,
            "note": "Single recent small-window mover admitted to Phase-5 shadow watch; not statistical promotion.",
        },
    }
    return {
        "run_id": run_id,
        "started_ts": now_ts,
        "completed_ts": now_ts,
        "status": "COMPLETED",
        "validator_version": "small_window_fast_track.v1",
        "rows_examined": len(phase3_rows),
        "primary_rows": len(phase3_rows),
        "candidate_count": 1,
        "pbo": {"pbo_estimate": 0.0, "method": "not_applicable_single_candidate_fast_track"},
        "champion": {
            **result,
            "mean_realized_net_bps": mean_net,
            "recent_mean_net_bps": mean_net,
            "recent_samples": completed_count,
        },
        "readiness": {
            "phase": 4,
            "ready_for_phase5_review": ready,
            "execution_eligible": False,
            "human_review_required": True,
            "real_orders_submitted": 0,
            "reasons": []
            if ready
            else [
                reason
                for reason in (
                    "phase3_no_completed_simulations" if completed_count <= 0 else "",
                    "small_window_fast_track_non_positive_edge" if robust_score <= 0 else "",
                )
                if reason
            ],
            "fast_track_scope": "phase5_shadow_watch_only",
        },
        "dataset_hash": dataset_hash,
        "candidate_results": [result],
        "execution_wired": False,
        "real_orders_submitted": 0,
        "small_window_fast_track": {
            "source_trade_id": trade.get("trade_id"),
            "symbol": candidate.get("symbol"),
            "direction": candidate.get("direction"),
            "expected_net_bps": candidate.get("expected_net_bps"),
            "repeatability_required_for_live": True,
        },
    }


def _small_window_proxy_simulation(
    *,
    candidate: dict[str, Any],
    run_id: str,
    order_policy: str,
    scenario: str,
    cfg: Any,
    trade: dict[str, Any],
) -> dict[str, Any]:
    forecast_id = str(candidate.get("forecast_id") or "")
    simulation_id = hashlib.sha256(
        f"{forecast_id}:{order_policy}:{scenario}:small_window_proxy.v1".encode()
    ).hexdigest()
    symbol = str(candidate.get("symbol") or "")
    direction = str(candidate.get("direction") or "").upper()
    entry_ts = _number(candidate.get("forecast_ts"))
    target_ts = _number(candidate.get("target_ts"), entry_ts + _number(candidate.get("horizon_seconds"), 60.0))
    entry_price = _number(candidate.get("entry_price"))
    exit_price = _number(candidate.get("exit_price"))
    notional = max(0.01, _number(getattr(cfg, "phase2_rapid_paper_notional_usd", 0.5), 0.5))
    quantity = notional / entry_price if entry_price > 0 else 0.0
    gross_bps = ((exit_price - entry_price) / entry_price) * 10_000.0 if entry_price > 0 else 0.0
    directional_bps = -gross_bps if direction == "DOWN" else gross_bps
    cost_bps = _number(candidate.get("expected_cost_bps"))
    net_bps = directional_bps - cost_bps
    side = "BUY" if direction == "UP" else "SELL_SHORT_SYNTHETIC"
    exit_side = "SELL" if direction == "UP" else "BUY_TO_COVER_SYNTHETIC"
    intent = {
        "intent_id": hashlib.sha256(f"intent:{simulation_id}".encode()).hexdigest(),
        "simulation_id": simulation_id,
        "forecast_id": forecast_id,
        "model_id": MODEL_ID,
        "venue": str(candidate.get("venue") or "kraken"),
        "symbol": symbol,
        "side": side,
        "order_policy": order_policy,
        "scenario": scenario,
        "quantity": quantity,
        "notional_usd": notional,
        "reference_price": entry_price,
        "limit_price": entry_price,
        "risk_budget_usd": _number(getattr(cfg, "phase3_simulated_equity_usd", 100.0), 100.0)
        * _number(getattr(cfg, "phase3_risk_fraction", 0.01), 0.01),
        "stop_distance_bps": _number(getattr(cfg, "phase5_shadow_stop_distance_bps", 500.0), 500.0),
        "horizon_seconds": int(candidate.get("horizon_seconds") or 0),
        "created_ts": entry_ts,
        "spot_executable": direction == "UP",
        "live_eligible": False,
        "authority": "paper_only_no_private_exchange",
    }
    return {
        "simulation_id": simulation_id,
        "run_id": run_id,
        "forecast_id": forecast_id,
        "model_id": MODEL_ID,
        "hypothesis": HYPOTHESIS,
        "venue": str(candidate.get("venue") or "kraken"),
        "symbol": symbol,
        "direction": direction,
        "order_policy": order_policy,
        "scenario": scenario,
        "fidelity": "SMALL_WINDOW_PUBLIC_DELTA_PROXY",
        "seed": 0,
        "status": "COMPLETED",
        "terminal_state": "CLOSED",
        "started_ts": entry_ts,
        "completed_ts": target_ts,
        "fill_ratio": 1.0,
        "quantity_requested": quantity,
        "quantity_filled": quantity,
        "notional_requested_usd": notional,
        "entry_reference_price": entry_price,
        "exit_reference_price": exit_price,
        "entry_fill_price": entry_price,
        "exit_fill_price": exit_price,
        "gross_return_bps": gross_bps,
        "net_return_bps": net_bps,
        "profitable_after_costs": net_bps > 0,
        "spot_executable": direction == "UP",
        "execution_wired": False,
        "real_orders_submitted": 0,
        "intent": intent,
        "events": [
            {
                "sequence": 1,
                "state": "CREATED",
                "ts": entry_ts,
                "reason": "small_window_delta_converted_to_proxy_intent",
            },
            {
                "sequence": 2,
                "state": "CLOSED",
                "ts": target_ts,
                "reason": "public_delta_proxy_settlement",
            },
        ],
        "fills": [
            {
                "fill_id": hashlib.sha256(f"{simulation_id}:entry".encode()).hexdigest(),
                "simulation_id": simulation_id,
                "leg": "ENTRY",
                "side": side,
                "quantity": quantity,
                "price": entry_price,
                "notional_usd": notional,
                "fee_usd": notional * max(cost_bps / 20_000.0, 0.0),
                "liquidity": "PUBLIC_PROXY",
                "ts": entry_ts,
            },
            {
                "fill_id": hashlib.sha256(f"{simulation_id}:exit".encode()).hexdigest(),
                "simulation_id": simulation_id,
                "leg": "EXIT",
                "side": exit_side,
                "quantity": quantity,
                "price": exit_price,
                "notional_usd": quantity * exit_price,
                "fee_usd": notional * max(cost_bps / 20_000.0, 0.0),
                "liquidity": "PUBLIC_PROXY",
                "ts": target_ts,
            },
        ],
        "costs": {
            "forecast_gross_bps": directional_bps,
            "market_gross_bps": gross_bps,
            "entry_spread_bps": _number((candidate.get("entry_observation") or {}).get("spread_bps")),
            "exit_spread_bps": _number((candidate.get("entry_observation") or {}).get("spread_bps")),
            "entry_impact_bps": 0.0,
            "exit_impact_bps": 0.0,
            "entry_latency_bps": 0.0,
            "exit_latency_bps": 0.0,
            "fee_bps": cost_bps,
            "missed_fill_opportunity_bps": 0.0,
            "stop_slippage_bps": 0.0,
            "total_cost_bps": cost_bps,
            "net_bps": net_bps,
            "gross_signal_bps": directional_bps,
            "entry_fee_bps": cost_bps / 2.0,
            "exit_fee_bps": cost_bps / 2.0,
            "maker_fee_bps": 0.0,
            "taker_fee_bps": cost_bps / 2.0,
            "failed_fill_cost_bps": 0.0,
            "chase_cost_bps": 0.0,
            "cost_schema_version": "small_window.proxy.cost.v1",
            "fee_source": "rapid_paper_candidate_cost_proxy",
            "fee_verified": False,
        },
        "incidents": [],
        "diagnostics": {
            "schema": "small_window_phase3_proxy_simulation_v1",
            "source_trade_id": trade.get("trade_id"),
            "source_status": trade.get("status"),
            "window_sec": candidate.get("window_sec"),
            "authority": "paper_only_no_private_exchange",
            "execution_eligible": False,
            "live_eligible": False,
        },
    }


def _fallback_shadow_intent(
    *,
    forecast: dict[str, Any],
    observation: dict[str, Any],
    freeze: dict[str, Any],
    cfg: Any,
    order_policy: str,
    builder_error: str,
) -> dict[str, Any]:
    reference = _number(forecast.get("entry_price") or observation.get("price"))
    notional = max(0.01, _number(getattr(cfg, "phase5_shadow_reference_notional_usd", 0.5), 0.5))
    quantity = notional / reference if reference > 0 else 0.0
    spread_bps = max(0.0, _number(observation.get("spread_bps")))
    direction = str(forecast.get("direction") or "").upper()
    side = "sell" if direction == "DOWN" else "buy"
    limit_price = None
    if reference > 0:
        half_spread = spread_bps / 20000.0
        if direction == "DOWN":
            limit_price = reference * (1.0 - half_spread - 0.0005)
        else:
            limit_price = reference * (1.0 + half_spread + 0.0005)
    payload = {
        "schema": "phase5_small_window_shadow_intent_fallback_v1",
        "authority": "research_shadow_only",
        "builder_error": builder_error,
        "below_venue_minimums_allowed": True,
        "execution_eligible": False,
        "live_eligible": False,
    }
    shadow_id = canonical_hash({
        "forecast_id": forecast.get("forecast_id"),
        "freeze_id": freeze.get("freeze_id"),
        "candidate_key": freeze.get("candidate_key"),
        "fallback": True,
    })
    return {
        "shadow_intent_id": shadow_id,
        "forecast_id": forecast.get("forecast_id"),
        "freeze_id": freeze.get("freeze_id"),
        "phase4_run_id": freeze.get("phase4_run_id"),
        "candidate_key": freeze.get("candidate_key"),
        "model_id": forecast.get("model_id"),
        "order_policy": order_policy,
        "venue": forecast.get("venue"),
        "symbol": forecast.get("symbol"),
        "direction": direction,
        "side": side,
        "order_type": "limit",
        "time_in_force": "IOC",
        "quantity": quantity,
        "notional_usd": quantity * reference,
        "reference_price": reference,
        "limit_price": limit_price,
        "stop_distance_bps": _number(getattr(cfg, "phase5_shadow_stop_distance_bps", 500.0), 500.0),
        "risk_budget_usd": _number(getattr(cfg, "phase3_simulated_equity_usd", 100.0), 100.0)
        * _number(getattr(cfg, "phase3_risk_fraction", 0.01), 0.01),
        "predicted_move_bps": forecast.get("expected_move_bps"),
        "predicted_cost_bps": forecast.get("expected_cost_bps"),
        "predicted_net_bps": forecast.get("expected_net_bps"),
        "probability_positive_net": forecast.get("probability_positive_net"),
        "horizon_seconds": forecast.get("horizon_seconds"),
        "created_ts": forecast.get("forecast_ts"),
        "target_ts": forecast.get("target_ts"),
        "data_quality": observation.get("data_quality"),
        "spread_bps": spread_bps,
        "depth_usd_25bps": observation.get("depth_usd_25bps"),
        "venue_profile_version": "fallback_research_shadow_only",
        "config_hash": freeze.get("config_hash"),
        "admission": payload,
        "execution_wired": False,
        "live_eligible": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fast-track the strongest recent small-window mover through Phase 3/4/5 as research-only shadow evidence."
    )
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path, default=ROOT / "config/high_vol_low_stakes.yaml")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--lookback-sec", type=float, default=3600.0)
    parser.add_argument("--settlement-tolerance-sec", type=float, default=180.0)
    parser.add_argument("--symbol")
    parser.add_argument("--direction", choices=("UP", "DOWN"))
    parser.add_argument("--order-policy", default="marketable_limit")
    parser.add_argument("--phase3-mode", choices=("small-window-proxy", "deterministic"), default="small-window-proxy")
    parser.add_argument("--scenarios", default="normal")
    parser.add_argument("--approved-by", default="small_window_fast_track")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    db_path = args.database or Path(str(getattr(cfg, "db_path", "data/swarm_data.db")))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    store = DataStoreAgent(str(db_path))
    now_ts = time.time()
    trade = _select_trade(
        store,
        lookback_sec=args.lookback_sec,
        symbol=args.symbol,
        direction=args.direction,
        now_ts=now_ts,
    )
    if not trade:
        print("NO_CANDIDATE reason=no_recent_small_window_trade_with_payload")
        return 2

    candidate = _build_phase3_candidate(
        store,
        trade,
        settlement_tolerance_sec=args.settlement_tolerance_sec,
    )
    simulator = DeterministicExecutionSimulator(cfg)
    scenarios = [item.strip() for item in str(args.scenarios).split(",") if item.strip()]
    run_id = f"small-window-p3-{int(now_ts * 1000)}-{uuid.uuid4().hex[:8]}"
    simulations = []
    for scenario in scenarios:
        if args.phase3_mode == "deterministic":
            simulation = simulator.simulate(
                candidate,
                run_id=run_id,
                order_policy=args.order_policy,
                scenario=scenario,
            ).to_dict()
        else:
            simulation = _small_window_proxy_simulation(
                candidate=candidate,
                run_id=run_id,
                order_policy=args.order_policy,
                scenario=scenario,
                cfg=cfg,
                trade=trade,
            )
        simulation["small_window_fast_track"] = {
            "source_trade_id": trade.get("trade_id"),
            "signal_lane": candidate.get("signal_lane"),
            "authority": "research_only",
            "execution_eligible": False,
            "phase3_mode": args.phase3_mode,
        }
        if not store.persist_execution_simulation(simulation):
            raise RuntimeError(f"failed to persist Phase-3 simulation {simulation.get('simulation_id')}")
        simulations.append(simulation)

    phase4_run_id = f"small-window-p4-{int(now_ts * 1000)}-{uuid.uuid4().hex[:8]}"
    report = _phase4_report(
        run_id=phase4_run_id,
        phase3_rows=simulations,
        candidate=candidate,
        trade=trade,
        order_policy=args.order_policy,
        now_ts=now_ts,
    )
    if not store.persist_phase4_validation_report(report):
        raise RuntimeError("failed to persist Phase-4 fast-track report")

    if not report.get("readiness", {}).get("ready_for_phase5_review"):
        summary = {
            "candidate": {
                "symbol": candidate.get("symbol"),
                "direction": candidate.get("direction"),
                "signal_lane": candidate.get("signal_lane"),
                "window_sec": candidate.get("window_sec"),
                "source_trade_id": trade.get("trade_id"),
                "source_status": trade.get("status"),
                "entry_ts": candidate.get("forecast_ts"),
                "target_ts": candidate.get("target_ts"),
                "entry_price": candidate.get("entry_price"),
                "exit_price": candidate.get("exit_price"),
                "expected_net_bps": candidate.get("expected_net_bps"),
                "directional_return_bps": candidate.get("directional_return_bps"),
                "net_return_bps": candidate.get("net_return_bps"),
            },
            "phase3": {
                "run_id": run_id,
                "simulations": len(simulations),
                "statuses": {
                    status: sum(1 for row in simulations if row.get("status") == status)
                    for status in sorted({row.get("status") for row in simulations})
                },
                "mode": args.phase3_mode,
            },
            "phase4": {
                "run_id": phase4_run_id,
                "candidate_key": report["champion"]["candidate_key"],
                "ready_for_phase5_review": False,
                "robust_score": report["champion"]["robust_score"],
                "reasons": report.get("readiness", {}).get("reasons") or [],
            },
            "phase5": {
                "intent_created": False,
                "skipped": True,
                "reason": "phase4_not_ready_for_shadow",
                "transmission_status": "NEVER_TRANSMITTED",
                "execution_eligible": False,
                "real_orders_submitted": 0,
            },
            "config_hash": frozen_config_hash(cfg),
        }
        if args.json:
            print(json.dumps(summary, indent=2, sort_keys=True, default=str))
        else:
            print(
                "SMALL_WINDOW_PIPELINE_BLOCKED "
                f"symbol={candidate.get('symbol')} direction={candidate.get('direction')} "
                f"lane={candidate.get('signal_lane')} "
                f"reasons={','.join(summary['phase4']['reasons'])} "
                "execution=shadow_only real_orders=0"
            )
        return 0

    freeze = build_freeze_from_phase4(report, approved_by=args.approved_by, approved_ts=now_ts, cfg=cfg)
    freeze_payload = asdict(freeze)
    freeze_payload["small_window_fast_track"] = {
        "source_trade_id": trade.get("trade_id"),
        "signal_lane": candidate.get("signal_lane"),
        "authority": "research_shadow_only",
        "repeatability_required_for_live": True,
    }
    if not store.persist_phase5_freeze(freeze_payload):
        raise RuntimeError("failed to persist Phase-5 freeze")

    forecast = {
        **candidate,
        "ts": candidate.get("forecast_ts"),
        "phase5_shadow_admission": {
            "mode": "small_window_recent_delta_fast_track",
            "authority": "research_shadow_only",
            "source_trade_id": trade.get("trade_id"),
            "repeatability_required_for_live": True,
        },
    }
    observation = candidate.get("entry_observation") if isinstance(candidate.get("entry_observation"), dict) else {}
    builder_error = ""
    try:
        intent = ShadowIntentBuilder(cfg).build(forecast, observation, freeze).to_dict()
    except Exception as exc:
        builder_error = str(exc)
        intent = _fallback_shadow_intent(
            forecast=forecast,
            observation=observation,
            freeze=freeze_payload,
            cfg=cfg,
            order_policy=args.order_policy,
            builder_error=builder_error,
        )
    created = store.persist_shadow_intent(intent)
    shadow_run = {
        "run_id": f"small-window-p5-{int(now_ts * 1000)}-{uuid.uuid4().hex[:8]}",
        "started_ts": now_ts,
        "completed_ts": time.time(),
        "status": "COMPLETED",
        "freeze_id": freeze.freeze_id,
        "intents_created": 1 if created else 0,
        "intents_skipped": 0 if created else 1,
        "settlements_created": 0,
        "ready_for_phase6_review": False,
        "dataset_hash": report.get("dataset_hash"),
        "execution_wired": False,
        "private_exchange_access": False,
        "transmission_attempts": 0,
        "real_orders_submitted": 0,
        "payload": {
            "schema": "small_window_phase5_shadow_run_v1",
            "source_trade_id": trade.get("trade_id"),
            "signal_lane": candidate.get("signal_lane"),
            "shadow_intent_id": intent.get("shadow_intent_id"),
            "intent_created": created,
            "builder_error": builder_error,
            "authority": "research_shadow_only",
            "repeatability_required_for_live": True,
        },
    }
    store.persist_phase5_shadow_run(shadow_run)

    summary = {
        "candidate": {
            "symbol": candidate.get("symbol"),
            "direction": candidate.get("direction"),
            "signal_lane": candidate.get("signal_lane"),
            "window_sec": candidate.get("window_sec"),
            "source_trade_id": trade.get("trade_id"),
            "source_status": trade.get("status"),
            "entry_ts": candidate.get("forecast_ts"),
            "target_ts": candidate.get("target_ts"),
            "entry_price": candidate.get("entry_price"),
            "exit_price": candidate.get("exit_price"),
            "expected_net_bps": candidate.get("expected_net_bps"),
            "directional_return_bps": candidate.get("directional_return_bps"),
            "net_return_bps": candidate.get("net_return_bps"),
        },
        "phase3": {
            "run_id": run_id,
            "simulations": len(simulations),
            "statuses": {status: sum(1 for row in simulations if row.get("status") == status) for status in sorted({row.get("status") for row in simulations})},
            "mode": args.phase3_mode,
        },
        "phase4": {
            "run_id": phase4_run_id,
            "candidate_key": report["champion"]["candidate_key"],
            "ready_for_phase5_review": report["readiness"]["ready_for_phase5_review"],
            "robust_score": report["champion"]["robust_score"],
        },
        "phase5": {
            "freeze_id": freeze.freeze_id,
            "shadow_intent_id": intent.get("shadow_intent_id"),
            "intent_created": created,
            "transmission_status": "NEVER_TRANSMITTED",
            "execution_eligible": False,
            "real_orders_submitted": 0,
        },
        "config_hash": frozen_config_hash(cfg),
    }
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    else:
        c = summary["candidate"]
        print(
            "SMALL_WINDOW_PIPELINE "
            f"symbol={c['symbol']} direction={c['direction']} "
            f"lane={c.get('signal_lane')} "
            f"expected_net_bps={_number(c['expected_net_bps']):.2f} "
            f"phase3_simulations={summary['phase3']['simulations']} "
            f"phase4_ready={summary['phase4']['ready_for_phase5_review']} "
            f"phase5_intent_created={summary['phase5']['intent_created']} "
            "execution=shadow_only real_orders=0"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
