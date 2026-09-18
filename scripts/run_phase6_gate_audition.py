#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import signal
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_phase1_observer import load_observer_config


def _json_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
        return dict(parsed) if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _audit_id(trade_id: str) -> str:
    return hashlib.sha256(f"phase6_gate_audition_v1:{trade_id}".encode("utf-8")).hexdigest()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS phase6_rapid_gate_auditions (
            audit_id TEXT PRIMARY KEY,
            trade_id TEXT UNIQUE,
            source_forecast_id TEXT,
            first_seen_ts REAL,
            updated_ts REAL,
            symbol TEXT,
            direction TEXT,
            window_sec INTEGER,
            signal_lane TEXT,
            route_policy TEXT,
            expected_fill_ratio REAL,
            gate_pass INTEGER,
            fail_reasons TEXT,
            candidate_status TEXT,
            expected_cost_bps REAL,
            expected_net_bps REAL,
            tape_slice_samples INTEGER,
            tape_slice_win_rate REAL,
            tape_slice_mean_net_bps REAL,
            outcome_status TEXT,
            outcome_net_bps REAL,
            outcome_positive_net INTEGER,
            outcome_settled_ts REAL,
            payload TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_phase6_gate_auditions_updated
        ON phase6_rapid_gate_auditions(updated_ts)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_phase6_gate_auditions_slice
        ON phase6_rapid_gate_auditions(symbol, direction, window_sec, signal_lane, outcome_status)
        """
    )
    columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(phase6_rapid_gate_auditions)").fetchall()}
    if "interval_pair" not in columns:
        conn.execute("ALTER TABLE phase6_rapid_gate_auditions ADD COLUMN interval_pair TEXT")
    if "supported_windows" not in columns:
        conn.execute("ALTER TABLE phase6_rapid_gate_auditions ADD COLUMN supported_windows TEXT")
    if "tape_slice_median_net_bps" not in columns:
        conn.execute("ALTER TABLE phase6_rapid_gate_auditions ADD COLUMN tape_slice_median_net_bps REAL")
    if "route_policy" not in columns:
        conn.execute("ALTER TABLE phase6_rapid_gate_auditions ADD COLUMN route_policy TEXT")
    if "expected_fill_ratio" not in columns:
        conn.execute("ALTER TABLE phase6_rapid_gate_auditions ADD COLUMN expected_fill_ratio REAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS phase6_rapid_gate_audition_counterfactuals (
            counterfactual_id TEXT PRIMARY KEY,
            audit_id TEXT,
            trade_id TEXT,
            symbol TEXT,
            direction TEXT,
            window_sec INTEGER,
            signal_lane TEXT,
            route_policy TEXT,
            interval_pair TEXT,
            entry_delay_sec INTEGER,
            hold_sec INTEGER,
            entry_ts REAL,
            exit_ts REAL,
            entry_price REAL,
            exit_price REAL,
            expected_cost_bps REAL,
            gross_return_bps REAL,
            net_return_bps REAL,
            positive_net INTEGER,
            status TEXT,
            updated_ts REAL,
            payload TEXT,
            UNIQUE(trade_id, entry_delay_sec, hold_sec)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_phase6_gate_counterfactuals_slice
        ON phase6_rapid_gate_audition_counterfactuals(interval_pair, signal_lane, entry_delay_sec, hold_sec, status)
        """
    )
    cf_columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(phase6_rapid_gate_audition_counterfactuals)").fetchall()
    }
    if "route_policy" not in cf_columns:
        conn.execute("ALTER TABLE phase6_rapid_gate_audition_counterfactuals ADD COLUMN route_policy TEXT")
    conn.commit()


def _interval_transition(cfg: Any, candidate: dict[str, Any], window_sec: int) -> dict[str, Any]:
    if not bool(getattr(cfg, "phase6_rapid_interval_transition_enabled", False)):
        return {"accepted": False, "pair": None, "supported_windows": [int(window_sec or 0)]}
    raw_pairs = getattr(cfg, "phase6_rapid_interval_transition_pairs", None) or []
    pairs: list[tuple[int, int]] = []
    for item in raw_pairs:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            pairs.append((int(_num(item[0])), int(_num(item[1]))))
    if not pairs:
        pairs = [(60, 300), (300, 1800), (1800, 3600)]
    supported = {int(window_sec or 0)}
    for value in candidate.get("same_direction_windows") or []:
        try:
            supported.add(int(float(value)))
        except Exception:
            continue
    matched = [pair for pair in pairs if pair[0] in supported and pair[1] in supported]
    best = matched[-1] if matched else None
    return {
        "accepted": bool(best),
        "pair": f"{best[0]}->{best[1]}" if best else None,
        "supported_windows": sorted(supported),
    }


def _slice_summary(
    conn: sqlite3.Connection,
    *,
    symbol: str,
    direction: str,
    window_sec: int,
    signal_lane: str,
    limit: int = 100,
) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT net_return_bps, payload
        FROM rapid_paper_tape_trades
        WHERE symbol=? AND direction=? AND status LIKE 'CLOSED%'
        ORDER BY updated_ts DESC
        LIMIT ?
        """,
        (symbol, direction, int(limit)),
    ).fetchall()
    values: list[float] = []
    for row in rows:
        payload = _json_mapping(row["payload"])
        candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
        row_window = int(_num(candidate.get("window_sec")))
        row_lane = str(candidate.get("signal_lane") or "continuation")
        if row_window == int(window_sec) and row_lane == signal_lane:
            values.append(_num(row["net_return_bps"]))
    if not values:
        return {"samples": 0, "win_rate": None, "mean_net_bps": None, "median_net_bps": None}
    wins = sum(1 for value in values if value > 0.0)
    ordered = sorted(values)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0
    return {
        "samples": len(values),
        "win_rate": round(wins / len(values), 6),
        "mean_net_bps": round(sum(values) / len(values), 6),
        "median_net_bps": round(median, 6),
    }


def _gate_reasons(cfg: Any, conn: sqlite3.Connection, row: sqlite3.Row, now: float) -> dict[str, Any]:
    payload = _json_mapping(row["payload"])
    candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
    symbol = str(row["symbol"] or "")
    direction = str(row["direction"] or "").upper()
    window_sec = int(_num(candidate.get("window_sec")))
    signal_lane = str(candidate.get("signal_lane") or "continuation")
    execution_route = candidate.get("execution_route") if isinstance(candidate.get("execution_route"), dict) else {}
    route_policy = str(candidate.get("route_policy") or execution_route.get("selected_policy") or "unknown").lower()
    expected_fill_ratio = _num(candidate.get("expected_fill_ratio"), _num(execution_route.get("expected_fill_ratio"), 1.0))
    expected_cost = _num(row["expected_cost_bps"])
    expected_net = _num(row["expected_net_bps"])
    entry_age = now - _num(row["entry_ts"], now)
    remaining = _num(row["target_ts"]) - now
    health_score = _num(candidate.get("health_score"))

    allowed_windows = {
        int(_num(item))
        for item in (getattr(cfg, "phase6_rapid_allowed_window_sec", None) or [])
        if str(item).strip()
    }
    max_age = max(1.0, _num(getattr(cfg, "phase6_rapid_candidate_max_age_sec", 45), 45.0))
    min_remaining = max(0.0, _num(getattr(cfg, "phase6_rapid_min_remaining_horizon_sec", 15), 15.0))
    max_cost = max(0.0, _num(getattr(cfg, "phase6_rapid_max_cost_bps", 45), 45.0))
    min_net = max(0.0, _num(getattr(cfg, "phase6_rapid_min_expected_net_bps", 35), 35.0))
    min_ratio = max(0.0, _num(getattr(cfg, "phase6_rapid_min_expected_net_to_cost_ratio", 1.75), 1.75))
    lane_min_ratio_raw = getattr(cfg, "phase6_rapid_lane_min_expected_net_to_cost_ratio", None) or {}
    lane_min_ratio = dict(lane_min_ratio_raw) if isinstance(lane_min_ratio_raw, dict) else {}
    lane_ratio = max(0.0, _num(lane_min_ratio.get(signal_lane), min_ratio))
    min_health = max(0.0, _num(getattr(cfg, "phase6_rapid_min_health_score", 45), 45.0))
    min_samples = max(1, int(_num(getattr(cfg, "phase6_rapid_tape_slice_min_samples", 2), 2)))
    min_win_rate = max(0.0, _num(getattr(cfg, "phase6_rapid_tape_slice_min_win_rate", 0.5), 0.5))
    min_mean = _num(getattr(cfg, "phase6_rapid_tape_slice_min_mean_net_bps", 15), 15.0)
    min_median = _num(getattr(cfg, "phase6_rapid_tape_slice_min_median_net_bps", 0), 0.0)
    allow_exploratory = bool(getattr(cfg, "phase6_rapid_allow_exploratory_slices", False))
    allowed_route_policies = {
        str(item).strip().lower()
        for item in (getattr(cfg, "phase6_rapid_allowed_execution_policies", None) or [])
        if str(item).strip()
    }
    min_fill_ratio = max(0.0, _num(getattr(cfg, "phase6_rapid_min_expected_fill_ratio", 0.0), 0.0))

    slice_score = _slice_summary(
        conn,
        symbol=symbol,
        direction=direction,
        window_sec=window_sec,
        signal_lane=signal_lane,
    )
    interval = _interval_transition(cfg, candidate, window_sec)
    reasons: list[str] = []
    if entry_age > max_age:
        reasons.append(f"age>{max_age:.0f}s")
    if remaining < min_remaining:
        reasons.append(f"horizon_remaining<{min_remaining:.0f}s")
    if allowed_windows and window_sec not in allowed_windows and not interval.get("accepted"):
        reasons.append(f"interval_transition_missing:{window_sec}")
    if min_health and health_score < min_health:
        reasons.append(f"health<{min_health:.0f}:{health_score:.1f}")
    if allowed_route_policies and route_policy not in allowed_route_policies:
        reasons.append(f"route_policy_not_allowed:{route_policy}")
    if min_fill_ratio and expected_fill_ratio < min_fill_ratio:
        reasons.append(f"fill<{min_fill_ratio:.2f}:{expected_fill_ratio:.2f}")
    if execution_route and not bool(execution_route.get("tradable", True)):
        reasons.append(f"route_untradable:{route_policy}")
    if max_cost and expected_cost > max_cost:
        reasons.append(f"cost>{max_cost:.0f}bps:{expected_cost:.1f}")
    if min_net and expected_net < min_net:
        reasons.append(f"net<{min_net:.0f}bps:{expected_net:.1f}")
    if lane_ratio and expected_cost > 0.0 and (expected_net / expected_cost) < lane_ratio:
        reasons.append(f"net_cost_ratio<{lane_ratio:.2f}:{expected_net / expected_cost:.2f}")
    samples = int(slice_score.get("samples") or 0)
    win_rate = slice_score.get("win_rate")
    mean_net = slice_score.get("mean_net_bps")
    median_net = slice_score.get("median_net_bps")
    if not allow_exploratory and samples < min_samples:
        reasons.append(f"slice_samples<{min_samples}:{samples}")
    elif samples >= min_samples:
        if _num(win_rate) < min_win_rate:
            reasons.append(f"slice_wr<{min_win_rate:.2f}:{_num(win_rate):.2f}")
        if _num(mean_net) < min_mean:
            reasons.append(f"slice_mean<{min_mean:.0f}bps:{_num(mean_net):.1f}")
        if _num(median_net) < min_median:
            reasons.append(f"slice_median<{min_median:.0f}bps:{_num(median_net):.1f}")
    return {
        "symbol": symbol,
        "direction": direction,
        "window_sec": window_sec,
        "signal_lane": signal_lane,
        "route_policy": route_policy,
        "expected_fill_ratio": expected_fill_ratio,
        "expected_cost_bps": expected_cost,
        "expected_net_bps": expected_net,
        "entry_age_sec": round(entry_age, 3),
        "remaining_horizon_sec": round(remaining, 3),
        "health_score": health_score,
        "slice": slice_score,
        "interval_transition": interval,
        "fail_reasons": reasons,
        "gate_pass": not reasons,
    }


def _record_auditions(conn: sqlite3.Connection, cfg: Any, *, limit: int) -> dict[str, Any]:
    now = time.time()
    rows = conn.execute(
        """
        SELECT *
        FROM rapid_paper_tape_trades
        WHERE model_id='small_window_trend_comparison_v1'
          AND status='OPEN'
        ORDER BY entry_ts DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    recorded = passed = failed = 0
    reason_counts: dict[str, int] = {}
    for row in rows:
        trade_id = str(row["trade_id"] or "")
        if not trade_id:
            continue
        gate = _gate_reasons(cfg, conn, row, now)
        fail_reasons = list(gate.get("fail_reasons") or [])
        for reason in fail_reasons:
            reason_counts[reason.split(":", 1)[0]] = reason_counts.get(reason.split(":", 1)[0], 0) + 1
        payload = {
            "schema": "phase6_rapid_gate_audition_v1",
            "gate": gate,
            "candidate_payload": _json_mapping(row["payload"]),
            "authority": "paper_research_only_no_private_exchange",
        }
        conn.execute(
            """
            INSERT INTO phase6_rapid_gate_auditions
            (audit_id, trade_id, source_forecast_id, first_seen_ts, updated_ts, symbol, direction,
             window_sec, signal_lane, route_policy, expected_fill_ratio, gate_pass, fail_reasons, candidate_status, expected_cost_bps,
             expected_net_bps, tape_slice_samples, tape_slice_win_rate, tape_slice_mean_net_bps,
             tape_slice_median_net_bps, interval_pair, supported_windows, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(trade_id) DO UPDATE SET
                updated_ts=excluded.updated_ts,
                gate_pass=excluded.gate_pass,
                fail_reasons=excluded.fail_reasons,
                candidate_status=excluded.candidate_status,
                route_policy=excluded.route_policy,
                expected_fill_ratio=excluded.expected_fill_ratio,
                expected_cost_bps=excluded.expected_cost_bps,
                expected_net_bps=excluded.expected_net_bps,
                tape_slice_samples=excluded.tape_slice_samples,
                tape_slice_win_rate=excluded.tape_slice_win_rate,
                tape_slice_mean_net_bps=excluded.tape_slice_mean_net_bps,
                tape_slice_median_net_bps=excluded.tape_slice_median_net_bps,
                interval_pair=excluded.interval_pair,
                supported_windows=excluded.supported_windows,
                payload=excluded.payload
            """,
            (
                _audit_id(trade_id),
                trade_id,
                row["source_forecast_id"],
                now,
                now,
                gate["symbol"],
                gate["direction"],
                gate["window_sec"],
                gate["signal_lane"],
                gate["route_policy"],
                gate["expected_fill_ratio"],
                int(bool(gate["gate_pass"])),
                json.dumps(fail_reasons, sort_keys=True),
                row["status"],
                gate["expected_cost_bps"],
                gate["expected_net_bps"],
                int(gate["slice"].get("samples") or 0),
                gate["slice"].get("win_rate"),
                gate["slice"].get("mean_net_bps"),
                gate["slice"].get("median_net_bps"),
                gate.get("interval_transition", {}).get("pair"),
                json.dumps(gate.get("interval_transition", {}).get("supported_windows") or []),
                json.dumps(payload, sort_keys=True, default=str),
            ),
        )
        recorded += 1
        passed += 1 if gate["gate_pass"] else 0
        failed += 0 if gate["gate_pass"] else 1
    conn.commit()
    top_reasons = sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))[:6]
    return {"examined": len(rows), "recorded": recorded, "passed": passed, "failed": failed, "top_reasons": top_reasons}


def _settle_auditions(conn: sqlite3.Connection, *, limit: int) -> dict[str, Any]:
    now = time.time()
    rows = conn.execute(
        """
        SELECT a.trade_id, t.status, t.net_return_bps, t.positive_net, t.settled_ts
        FROM phase6_rapid_gate_auditions a
        JOIN rapid_paper_tape_trades t ON t.trade_id=a.trade_id
        WHERE a.outcome_status IS NULL
          AND t.status!='OPEN'
        ORDER BY t.updated_ts ASC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    settled = wins = losses = expired = 0
    for row in rows:
        status = str(row["status"] or "")
        net = row["net_return_bps"]
        positive = row["positive_net"]
        conn.execute(
            """
            UPDATE phase6_rapid_gate_auditions
            SET updated_ts=?, outcome_status=?, outcome_net_bps=?, outcome_positive_net=?, outcome_settled_ts=?
            WHERE trade_id=?
            """,
            (now, status, net, positive, row["settled_ts"], row["trade_id"]),
        )
        if status.startswith("CLOSED"):
            settled += 1
            wins += 1 if _num(net) > 0.0 else 0
            losses += 0 if _num(net) > 0.0 else 1
        elif status.startswith("EXPIRED"):
            expired += 1
    conn.commit()
    return {"settled": settled, "wins": wins, "losses": losses, "expired": expired}


def _configured_ints(cfg: Any, key: str, fallback: list[int]) -> list[int]:
    raw = getattr(cfg, key, None) or fallback
    values: list[int] = []
    for item in raw:
        try:
            value = int(float(item))
            if value >= 0:
                values.append(value)
        except Exception:
            continue
    return sorted(set(values)) or fallback


def _observation_price(
    conn: sqlite3.Connection,
    *,
    symbol: str,
    target_ts: float,
    tolerance_sec: float,
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT ts, price, run_id
        FROM observation_snapshots
        WHERE symbol=?
          AND ts>=?
          AND ts<=?
          AND price>0
        ORDER BY ts ASC
        LIMIT 1
        """,
        (symbol, float(target_ts), float(target_ts) + float(tolerance_sec)),
    ).fetchone()
    if not row:
        return {}
    return {"ts": float(row["ts"]), "price": _num(row["price"]), "run_id": row["run_id"]}


def _counterfactual_id(trade_id: str, entry_delay_sec: int, hold_sec: int) -> str:
    payload = f"phase6_gate_counterfactual_v1:{trade_id}:{int(entry_delay_sec)}:{int(hold_sec)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _record_counterfactuals(conn: sqlite3.Connection, cfg: Any, *, limit: int) -> dict[str, Any]:
    now = time.time()
    delays = _configured_ints(cfg, "phase6_rapid_audition_entry_delays_sec", [0, 10, 20, 30])
    holds = [item for item in _configured_ints(cfg, "phase6_rapid_audition_hold_sec", [30, 60, 120, 300]) if item > 0]
    tolerance = max(1.0, _num(getattr(cfg, "phase6_rapid_audition_observation_tolerance_sec", 20), 20.0))
    rows = conn.execute(
        """
        SELECT a.*, t.entry_ts AS tape_entry_ts, t.entry_price AS tape_entry_price, t.payload AS tape_payload
        FROM phase6_rapid_gate_auditions a
        JOIN rapid_paper_tape_trades t ON t.trade_id=a.trade_id
        ORDER BY a.updated_ts DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    examined = recorded = pending = wins = losses = 0
    for row in rows:
        trade_id = str(row["trade_id"] or "")
        symbol = str(row["symbol"] or "")
        direction = str(row["direction"] or "").upper()
        if not trade_id or not symbol or direction not in {"UP", "DOWN"}:
            continue
        base_ts = _num(row["tape_entry_ts"])
        expected_cost = _num(row["expected_cost_bps"])
        if base_ts <= 0:
            continue
        for delay in delays:
            entry_target = base_ts + float(delay)
            entry_obs = _observation_price(conn, symbol=symbol, target_ts=entry_target, tolerance_sec=tolerance)
            for hold in holds:
                examined += 1
                exit_target = entry_target + float(hold)
                exit_obs = _observation_price(conn, symbol=symbol, target_ts=exit_target, tolerance_sec=tolerance)
                status = "PENDING_OBSERVATION"
                entry_price = _num(entry_obs.get("price"))
                exit_price = _num(exit_obs.get("price"))
                gross = net = None
                positive = None
                if entry_price > 0 and exit_price > 0:
                    if direction == "DOWN":
                        gross = (entry_price - exit_price) / entry_price * 10000.0
                    else:
                        gross = (exit_price - entry_price) / entry_price * 10000.0
                    net = gross - expected_cost
                    positive = int(net > 0.0)
                    status = "CLOSED_WIN" if net > 0.0 else "CLOSED_LOSS"
                    wins += 1 if net > 0.0 else 0
                    losses += 0 if net > 0.0 else 1
                else:
                    pending += 1
                payload = {
                    "schema": "phase6_rapid_gate_counterfactual_v1",
                    "entry_observation": entry_obs,
                    "exit_observation": exit_obs,
                    "tape_payload": _json_mapping(row["tape_payload"]),
                    "authority": "paper_research_only_no_private_exchange",
                }
                conn.execute(
                    """
                    INSERT INTO phase6_rapid_gate_audition_counterfactuals
                    (counterfactual_id, audit_id, trade_id, symbol, direction, window_sec, signal_lane,
                     interval_pair, entry_delay_sec, hold_sec, entry_ts, exit_ts, entry_price, exit_price,
                     expected_cost_bps, gross_return_bps, net_return_bps, positive_net, status, updated_ts, payload,
                     route_policy)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(trade_id, entry_delay_sec, hold_sec) DO UPDATE SET
                        audit_id=excluded.audit_id,
                        symbol=excluded.symbol,
                        direction=excluded.direction,
                        window_sec=excluded.window_sec,
                        signal_lane=excluded.signal_lane,
                        route_policy=excluded.route_policy,
                        interval_pair=excluded.interval_pair,
                        entry_ts=excluded.entry_ts,
                        exit_ts=excluded.exit_ts,
                        entry_price=excluded.entry_price,
                        exit_price=excluded.exit_price,
                        expected_cost_bps=excluded.expected_cost_bps,
                        gross_return_bps=excluded.gross_return_bps,
                        net_return_bps=excluded.net_return_bps,
                        positive_net=excluded.positive_net,
                        status=excluded.status,
                        updated_ts=excluded.updated_ts,
                        payload=excluded.payload
                    """,
                    (
                        _counterfactual_id(trade_id, delay, hold),
                        row["audit_id"],
                        trade_id,
                        symbol,
                        direction,
                        int(row["window_sec"] or 0),
                        row["signal_lane"],
                        row["interval_pair"],
                        int(delay),
                        int(hold),
                        entry_obs.get("ts"),
                        exit_obs.get("ts"),
                        entry_price or None,
                        exit_price or None,
                        expected_cost,
                        gross,
                        net,
                        positive,
                        status,
                        now,
                        json.dumps(payload, sort_keys=True, default=str),
                        row["route_policy"],
                    ),
                )
                recorded += 1
    conn.commit()
    return {"examined": examined, "recorded": recorded, "pending": pending, "wins": wins, "losses": losses}


def _scorecard(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS audits,
            SUM(CASE WHEN gate_pass=1 THEN 1 ELSE 0 END) AS gate_passed,
            SUM(CASE WHEN gate_pass=0 THEN 1 ELSE 0 END) AS gate_failed,
            SUM(CASE WHEN outcome_status LIKE 'CLOSED%' THEN 1 ELSE 0 END) AS settled,
            SUM(CASE WHEN outcome_status LIKE 'CLOSED%' AND outcome_net_bps>0 THEN 1 ELSE 0 END) AS wins,
            AVG(CASE WHEN outcome_status LIKE 'CLOSED%' THEN outcome_net_bps ELSE NULL END) AS mean_net_bps
        FROM phase6_rapid_gate_auditions
        """
    ).fetchone()
    settled = int(row["settled"] or 0)
    wins = int(row["wins"] or 0)
    return {
        "audits": int(row["audits"] or 0),
        "gate_passed": int(row["gate_passed"] or 0),
        "gate_failed": int(row["gate_failed"] or 0),
        "settled": settled,
        "wins": wins,
        "losses": settled - wins,
        "win_rate": round(wins / settled, 6) if settled else None,
        "mean_net_bps": round(_num(row["mean_net_bps"]), 6) if row["mean_net_bps"] is not None else None,
    }


def _interval_scorecard(conn: sqlite3.Connection, *, limit: int = 8) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            COALESCE(interval_pair, CAST(window_sec AS TEXT)) AS interval_key,
            signal_lane,
            COALESCE(route_policy, 'unknown') AS route_policy,
            COUNT(*) AS audits,
            SUM(CASE WHEN gate_pass=1 THEN 1 ELSE 0 END) AS gate_passed,
            SUM(CASE WHEN outcome_status LIKE 'CLOSED%' THEN 1 ELSE 0 END) AS settled,
            SUM(CASE WHEN outcome_status LIKE 'CLOSED%' AND outcome_net_bps>0 THEN 1 ELSE 0 END) AS wins,
            AVG(CASE WHEN outcome_status LIKE 'CLOSED%' THEN outcome_net_bps ELSE NULL END) AS mean_net_bps
        FROM phase6_rapid_gate_auditions
        GROUP BY interval_key, signal_lane, route_policy
        ORDER BY settled DESC, mean_net_bps DESC, audits DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        settled = int(row["settled"] or 0)
        wins = int(row["wins"] or 0)
        result.append(
            {
                "interval": row["interval_key"],
                "lane": row["signal_lane"],
                "route_policy": row["route_policy"],
                "audits": int(row["audits"] or 0),
                "gate_passed": int(row["gate_passed"] or 0),
                "settled": settled,
                "wins": wins,
                "losses": settled - wins,
                "win_rate": round(wins / settled, 6) if settled else None,
                "mean_net_bps": round(_num(row["mean_net_bps"]), 6) if row["mean_net_bps"] is not None else None,
            }
        )
    return result


def _counterfactual_scorecard(conn: sqlite3.Connection, *, limit: int = 10) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            COALESCE(interval_pair, CAST(window_sec AS TEXT)) AS interval_key,
            signal_lane,
            COALESCE(route_policy, 'unknown') AS route_policy,
            entry_delay_sec,
            hold_sec,
            COUNT(*) AS samples,
            SUM(CASE WHEN status='CLOSED_WIN' THEN 1 ELSE 0 END) AS wins,
            AVG(CASE WHEN status LIKE 'CLOSED%' THEN net_return_bps ELSE NULL END) AS mean_net_bps
        FROM phase6_rapid_gate_audition_counterfactuals
        WHERE status LIKE 'CLOSED%'
        GROUP BY interval_key, signal_lane, route_policy, entry_delay_sec, hold_sec
        ORDER BY samples DESC, mean_net_bps DESC
        LIMIT ?
        """,
        (max(1, int(limit)) * 5,),
    ).fetchall()
    scored: list[dict[str, Any]] = []
    for row in rows:
        interval_key = str(row["interval_key"] or "")
        lane = str(row["signal_lane"] or "continuation")
        route_policy = str(row["route_policy"] or "unknown")
        delay = int(row["entry_delay_sec"] or 0)
        hold = int(row["hold_sec"] or 0)
        values = [
            _num(item[0])
            for item in conn.execute(
                """
                SELECT net_return_bps
                FROM phase6_rapid_gate_audition_counterfactuals
                WHERE status LIKE 'CLOSED%'
                  AND COALESCE(interval_pair, CAST(window_sec AS TEXT))=?
                  AND signal_lane=?
                  AND COALESCE(route_policy, 'unknown')=?
                  AND entry_delay_sec=?
                  AND hold_sec=?
                """,
                (interval_key, lane, route_policy, delay, hold),
            ).fetchall()
        ]
        if not values:
            continue
        samples = len(values)
        wins = sum(1 for value in values if value > 0.0)
        ordered = sorted(values)
        mid = samples // 2
        median = ordered[mid] if samples % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0
        scored.append(
            {
                "interval": interval_key,
                "lane": lane,
                "route_policy": route_policy,
                "entry_delay_sec": delay,
                "hold_sec": hold,
                "samples": samples,
                "wins": wins,
                "losses": samples - wins,
                "win_rate": round(wins / samples, 6),
                "mean_net_bps": round(sum(values) / samples, 6),
                "median_net_bps": round(median, 6),
            }
        )
    scored.sort(
        key=lambda item: (
            item["win_rate"],
            item["median_net_bps"],
            item["mean_net_bps"],
            item["samples"],
        ),
        reverse=True,
    )
    return scored[: max(1, int(limit))]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record paper-only Phase-6 gate refusals and settle them as counterfactual learning."
    )
    parser.add_argument("--settings", type=Path, default=ROOT / "config/settings.yaml")
    parser.add_argument("--profile", type=Path, default=ROOT / "config/high_vol_low_stakes.yaml")
    parser.add_argument("--database", type=Path, default=ROOT / "data/swarm_data.db")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--settlement-limit", type=int, default=500)
    parser.add_argument("--duration-sec", type=int, default=0)
    parser.add_argument("--interval-sec", type=int, default=20)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = load_observer_config(args.settings, args.profile)
    db_path = args.database
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    _ensure_schema(conn)

    stopping = False

    def stop_handler(_signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    started = time.monotonic()
    cycle = 0
    try:
        while not stopping:
            cycle += 1
            try:
                settlement = _settle_auditions(conn, limit=max(1, int(args.settlement_limit)))
                audit = _record_auditions(conn, cfg, limit=max(1, int(args.limit)))
                counterfactuals = _record_counterfactuals(conn, cfg, limit=max(1, int(args.limit)))
                scorecard = _scorecard(conn)
                counterfactual_scorecard = _counterfactual_scorecard(conn)
            except sqlite3.OperationalError as exc:
                if "database is locked" not in str(exc).lower():
                    raise
                try:
                    conn.rollback()
                except Exception:
                    pass
                print(
                    f"GATE_AUDITION cycle={cycle} status=DB_BUSY retrying=true error=database_is_locked",
                    flush=True,
                )
                time.sleep(min(5.0, max(1.0, float(args.interval_sec or 20))))
                continue
            payload = {
                "schema": "phase6_rapid_gate_audition_loop_v1",
                "cycle": cycle,
                "audit": audit,
                "settlement": settlement,
                "counterfactuals": counterfactuals,
                "scorecard": scorecard,
                "interval_scorecard": _interval_scorecard(conn),
                "counterfactual_scorecard": counterfactual_scorecard,
                "authority": "paper_research_only_no_private_exchange",
            }
            if args.json:
                print(json.dumps(payload, sort_keys=True, default=str), flush=True)
            else:
                top = ",".join(f"{name}={count}" for name, count in audit.get("top_reasons", [])[:4])
                intervals = ",".join(
                    f"{row['interval']}:{row['lane']}:{row['route_policy']}:{row['settled']}/{row['wins']}@{row['mean_net_bps']}"
                    for row in payload["interval_scorecard"][:3]
                )
                best_cf = ",".join(
                    f"{row['interval']}:{row['lane']}:{row['route_policy']}:d{row['entry_delay_sec']}h{row['hold_sec']}="
                    f"{row['wins']}/{row['samples']}@{row['median_net_bps']}"
                    for row in counterfactual_scorecard[:2]
                )
                print(
                    f"GATE_AUDITION cycle={cycle} examined={audit['examined']} recorded={audit['recorded']} "
                    f"passed={audit['passed']} failed={audit['failed']} settled={settlement['settled']} "
                    f"wins={settlement['wins']} losses={settlement['losses']} "
                    f"cf={counterfactuals['recorded']} "
                    f"audits={scorecard['audits']} win_rate={scorecard['win_rate']} "
                    f"mean_net={scorecard['mean_net_bps']} intervals={intervals or '-'} "
                    f"best_cf={best_cf or '-'} "
                    f"top_reasons={top or '-'}",
                    flush=True,
                )
            if int(args.duration_sec or 0) > 0 and time.monotonic() - started >= int(args.duration_sec):
                break
            deadline = time.monotonic() + max(1, int(args.interval_sec or 20))
            while not stopping and time.monotonic() < deadline:
                time.sleep(min(0.5, deadline - time.monotonic()))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
