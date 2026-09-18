from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _setting(cfg: Any, name: str, default: Any) -> Any:
    value = getattr(cfg, name, default)
    return default if value is None else value


def _positive_posteriors(rows: Any, *, normal_only: bool = False) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if normal_only and str(row.get("scenario") or "normal") != "normal":
            continue
        lower = row.get("lower_bound_net_bps")
        if lower is not None and float(lower) > 0.0:
            out.append(row)
    return out


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _order_table_rows(store: Any) -> int:
    conn = getattr(store, "conn", None)
    if conn is None:
        return -1
    try:
        row = conn.execute("SELECT COUNT(*) FROM orders").fetchone()
        return int((row or [0])[0] or 0)
    except Exception:
        return -1


def _rows(store: Any, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    conn = getattr(store, "conn", None)
    if conn is None:
        return []
    cursor = conn.execute(query, params)
    cols = [item[0] for item in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _one(store: Any, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    rows = _rows(store, query, params)
    return rows[0] if rows else {}


def _forecast_rows_by_id(store: Any, forecast_ids: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    unique_ids = [item for item in dict.fromkeys(str(value) for value in forecast_ids if value)]
    for index in range(0, len(unique_ids), 500):
        chunk = unique_ids[index:index + 500]
        if not chunk:
            continue
        placeholders = ",".join("?" for _ in chunk)
        for row in _rows(
            store,
            f"""
            SELECT forecast_id, model_id, hypothesis, horizon_seconds, direction, venue, abstain, payload
            FROM hypothesis_forecasts
            WHERE forecast_id IN ({placeholders})
            """,
            tuple(chunk),
        ):
            out[str(row.get("forecast_id"))] = row
    return out


def _distribution(samples: list[float]) -> dict[str, Any]:
    values = sorted(float(item) for item in samples if item is not None)
    if not values:
        return {"sample_count": 0}
    def pick(q: float) -> float:
        index = min(len(values) - 1, max(0, int(round((len(values) - 1) * q))))
        return round(values[index], 6)
    return {
        "sample_count": len(values),
        "mean_bps": round(sum(values) / len(values), 6),
        "p10_bps": pick(0.10),
        "p25_bps": pick(0.25),
        "p50_bps": pick(0.50),
        "p75_bps": pick(0.75),
        "p90_bps": pick(0.90),
    }


def _compact_phase2_scorecard(store: Any, *, limit: int = 20000) -> dict[str, Any]:
    """Fast recent-evidence scorecard for operational truth rendering."""
    result: dict[str, Any] = {
        "phase": 2,
        "mode": "compact_recent_hypothesis_research_only",
        "models": [],
        "profitability_slice_posteriors": [],
        "worker_triune_mind_breakdown": [],
        "worker_loki_challenge_breakdown": [],
        "champion_research_model_by_mean_net_bps": None,
        "orders_submitted": 0,
        "compact": True,
        "sample_limit": int(limit),
    }
    latest = _rows(store, """
        WITH latest AS (
            SELECT model_id, hypothesis, abstain, expected_net_bps, expected_cost_bps
            FROM hypothesis_forecasts
            ORDER BY rowid DESC
            LIMIT ?
        )
        SELECT model_id, hypothesis,
               COUNT(*) AS forecasts,
               SUM(CASE WHEN abstain=0 THEN 1 ELSE 0 END) AS non_abstain,
               AVG(CASE WHEN abstain=0 THEN expected_net_bps END) AS mean_expected_net_bps,
               AVG(CASE WHEN abstain=0 THEN expected_cost_bps END) AS mean_expected_cost_bps
        FROM latest
        GROUP BY model_id, hypothesis
    """, (int(limit),))
    recent_outcomes = _rows(store, """
        SELECT forecast_id, net_return_bps, positive_net, settled_ts
        FROM hypothesis_outcomes
        ORDER BY rowid DESC
        LIMIT ?
    """, (int(limit),))
    forecast_map = _forecast_rows_by_id(store, [str(row.get("forecast_id") or "") for row in recent_outcomes])
    settled_buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for outcome in recent_outcomes:
        forecast = forecast_map.get(str(outcome.get("forecast_id") or ""))
        if not forecast or int(forecast.get("abstain") or 0):
            continue
        key = (str(forecast.get("model_id") or "unknown"), str(forecast.get("hypothesis") or "unknown"))
        bucket = settled_buckets.setdefault(key, {
            "model_id": key[0],
            "hypothesis": key[1],
            "settled_trades": 0,
            "net_sum": 0.0,
            "wins": 0,
        })
        bucket["settled_trades"] += 1
        bucket["net_sum"] += float(outcome.get("net_return_bps") or 0.0)
        bucket["wins"] += 1 if int(outcome.get("positive_net") or 0) else 0
    settled = [
        {
            "model_id": bucket["model_id"],
            "hypothesis": bucket["hypothesis"],
            "settled_trades": int(bucket["settled_trades"]),
            "mean_net_bps": bucket["net_sum"] / max(1, int(bucket["settled_trades"])),
            "win_rate": bucket["wins"] / max(1, int(bucket["settled_trades"])),
            "cumulative_net_bps": bucket["net_sum"],
        }
        for bucket in settled_buckets.values()
    ]
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in latest:
        key = (str(row.get("model_id") or "unknown"), str(row.get("hypothesis") or "unknown"))
        by_key[key] = dict(row)
    for row in settled:
        key = (str(row.get("model_id") or "unknown"), str(row.get("hypothesis") or "unknown"))
        bucket = by_key.setdefault(key, {"model_id": key[0], "hypothesis": key[1], "forecasts": 0, "non_abstain": 0})
        bucket.update(row)
    models = []
    for row in by_key.values():
        model_id = str(row.get("model_id") or "unknown")
        forecasts = int(row.get("forecasts") or 0)
        non_abstain = int(row.get("non_abstain") or 0)
        settled_trades = int(row.get("settled_trades") or 0)
        record = {
            "model_id": model_id,
            "hypothesis": row.get("hypothesis"),
            "forecasts": forecasts,
            "non_abstain": non_abstain,
            "settled_trades": settled_trades,
            "activation_rate": round(non_abstain / max(1, forecasts), 6),
            "mean_expected_net_bps": round(float(row["mean_expected_net_bps"]), 6) if row.get("mean_expected_net_bps") is not None else None,
            "mean_expected_cost_bps": round(float(row["mean_expected_cost_bps"]), 6) if row.get("mean_expected_cost_bps") is not None else None,
            "mean_net_bps": round(float(row["mean_net_bps"]), 6) if row.get("mean_net_bps") is not None else None,
            "win_rate": round(float(row["win_rate"]), 6) if row.get("win_rate") is not None else None,
            "cumulative_net_bps": round(float(row["cumulative_net_bps"]), 6) if row.get("cumulative_net_bps") is not None else None,
            "is_baseline": model_id.startswith("baseline_"),
        }
        models.append(record)
    result["models"] = sorted(
        models,
        key=lambda item: (
            float(item.get("mean_net_bps") if item.get("mean_net_bps") is not None else -1e18),
            int(item.get("settled_trades") or 0),
        ),
        reverse=True,
    )
    research_eligible = [m for m in models if not m.get("is_baseline") and m.get("mean_net_bps") is not None]
    if research_eligible:
        result["champion_research_model_by_mean_net_bps"] = max(
            research_eligible, key=lambda item: float(item.get("mean_net_bps") or -1e18)
        ).get("model_id")

    buckets: dict[tuple[str, str, int, str, str], list[float]] = {}
    wins: dict[tuple[str, str, int, str, str], int] = {}
    for row in recent_outcomes:
        forecast = forecast_map.get(str(row.get("forecast_id") or ""))
        if not forecast or int(forecast.get("abstain") or 0):
            continue
        key = (
            str(forecast.get("model_id") or "unknown"),
            str(forecast.get("hypothesis") or "unknown"),
            int(forecast.get("horizon_seconds") or 0),
            str(forecast.get("direction") or "unknown"),
            str(forecast.get("venue") or "unknown"),
        )
        buckets.setdefault(key, []).append(float(row.get("net_return_bps") or 0.0))
        wins[key] = wins.get(key, 0) + (1 if int(row.get("positive_net") or 0) else 0)
    posteriors = []
    for key, values in buckets.items():
        if len(values) < 3:
            continue
        dist = _distribution(values)
        mean = float(dist.get("mean_bps") or 0.0)
        stderr = math.sqrt(sum((item - mean) ** 2 for item in values) / max(1, len(values) - 1)) / math.sqrt(len(values)) if len(values) > 1 else 0.0
        lower = min(mean - 1.0 * stderr, float(dist.get("p25_bps") if dist.get("p25_bps") is not None else mean))
        model_id, hypothesis, horizon_seconds, direction, venue = key
        posteriors.append({
            "schema": "profitability_slice_posterior_v1",
            "slice_key": f"{model_id}|{hypothesis}|{horizon_seconds}|{direction}|{venue}",
            "model_id": model_id,
            "thesis_family": hypothesis,
            "horizon_seconds": horizon_seconds,
            "direction": direction,
            "venue": venue,
            "posterior_net_return_distribution_bps": dist,
            "posterior_mean_net_bps": round(mean, 6),
            "lower_bound_net_bps": round(lower, 6),
            "probability_positive_net": round(wins.get(key, 0) / max(1, len(values)), 6),
            "evidence_strength": round(min(1.0, len(values) / 24.0), 6),
        })
    result["profitability_slice_posteriors"] = sorted(
        posteriors,
        key=lambda item: (
            float(item.get("lower_bound_net_bps") if item.get("lower_bound_net_bps") is not None else -1e18),
            float(item.get("evidence_strength") or 0.0),
        ),
        reverse=True,
    )
    triune_rows = _rows(store, """
        SELECT model_id, payload
        FROM hypothesis_forecasts
        WHERE model_id >= ? AND model_id < ?
        ORDER BY rowid DESC
        LIMIT ?
    """, ("worker_signal_", "worker_signal`", int(min(max(limit, 1000), 20000))))
    triune_buckets: dict[tuple[str, str], dict[str, Any]] = {}
    challenge_buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for row in triune_rows:
        model_id = str(row.get("model_id") or "unknown")
        try:
            payload = json.loads(row.get("payload") or "{}")
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            continue
        inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
        triune = inputs.get("triune_worker_mind") if isinstance(inputs.get("triune_worker_mind"), dict) else {}
        if not triune:
            continue
        verdict = str(triune.get("final_verdict") or "UNKNOWN")
        key = (model_id, verdict)
        bucket = triune_buckets.setdefault(key, {
            "model_id": model_id,
            "final_verdict": verdict,
            "forecasts": 0,
            "non_abstain": 0,
            "michael_sum": 0.0,
            "michael_n": 0,
            "metatron_sum": 0.0,
            "metatron_n": 0,
            "loki_sum": 0.0,
            "loki_n": 0,
        })
        bucket["forecasts"] += 1
        if not payload.get("abstain"):
            bucket["non_abstain"] += 1
        michael = triune.get("michael") if isinstance(triune.get("michael"), dict) else {}
        metatron = triune.get("metatron") if isinstance(triune.get("metatron"), dict) else {}
        loki = triune.get("loki") if isinstance(triune.get("loki"), dict) else {}
        if michael.get("validation_score") is not None:
            bucket["michael_sum"] += float(michael.get("validation_score") or 0.0)
            bucket["michael_n"] += 1
        if metatron.get("harmony_score") is not None:
            bucket["metatron_sum"] += float(metatron.get("harmony_score") or 0.0)
            bucket["metatron_n"] += 1
        if loki.get("risk_score") is not None:
            bucket["loki_sum"] += float(loki.get("risk_score") or 0.0)
            bucket["loki_n"] += 1
        for challenge in (loki.get("challenges") or [])[:8]:
            if not isinstance(challenge, dict):
                continue
            name = str(challenge.get("challenge") or "unknown")
            ckey = (model_id, name)
            cbucket = challenge_buckets.setdefault(ckey, {
                "model_id": model_id,
                "challenge": name,
                "count": 0,
                "max_risk": 0.0,
            })
            cbucket["count"] += 1
            cbucket["max_risk"] = max(float(cbucket.get("max_risk") or 0.0), float(challenge.get("risk") or 0.0))
    result["worker_triune_mind_breakdown"] = sorted(
        [
            {
                "model_id": bucket["model_id"],
                "final_verdict": bucket["final_verdict"],
                "forecasts": int(bucket["forecasts"]),
                "non_abstain": int(bucket["non_abstain"]),
                "activation_rate": round(int(bucket["non_abstain"]) / max(1, int(bucket["forecasts"])), 6),
                "mean_michael_validation_score": (
                    round(float(bucket["michael_sum"]) / max(1, int(bucket["michael_n"])), 6)
                    if int(bucket["michael_n"]) else None
                ),
                "mean_metatron_harmony_score": (
                    round(float(bucket["metatron_sum"]) / max(1, int(bucket["metatron_n"])), 6)
                    if int(bucket["metatron_n"]) else None
                ),
                "mean_loki_risk_score": (
                    round(float(bucket["loki_sum"]) / max(1, int(bucket["loki_n"])), 6)
                    if int(bucket["loki_n"]) else None
                ),
            }
            for bucket in triune_buckets.values()
        ],
        key=lambda item: (str(item.get("model_id") or ""), str(item.get("final_verdict") or "")),
    )
    result["worker_loki_challenge_breakdown"] = sorted(
        [
            {
                "model_id": bucket["model_id"],
                "challenge": bucket["challenge"],
                "count": int(bucket["count"]),
                "max_risk": round(float(bucket["max_risk"] or 0.0), 6),
            }
            for bucket in challenge_buckets.values()
        ],
        key=lambda item: (-int(item.get("count") or 0), str(item.get("model_id") or ""), str(item.get("challenge") or "")),
    )[:50]
    return result


def _phase2_research_allocation_queue(scorecard: dict[str, Any], *, limit: int = 24) -> list[dict[str, Any]]:
    """Rank research slices by executable information value, not model-wide prestige."""
    queue: list[dict[str, Any]] = []
    for row in scorecard.get("profitability_slice_posteriors") or []:
        if not isinstance(row, dict):
            continue
        evidence = max(0.0, min(1.0, float(row.get("evidence_strength") or 0.0)))
        mean = float(row.get("posterior_mean_net_bps") or 0.0)
        lower = float(row.get("lower_bound_net_bps") or 0.0)
        probability = float(row.get("probability_positive_net") or 0.0)
        sample_count = int(((row.get("posterior_net_return_distribution_bps") or {}).get("sample_count")) or 0)
        uncertainty_bonus = max(0.0, 1.0 - evidence) * min(1.0, max(0.0, probability - 0.45))
        edge_score = max(0.0, lower) + max(0.0, mean) * 0.25
        information_value = (edge_score * (0.35 + evidence)) + (uncertainty_bonus * 10.0)
        queue.append({
            "schema": "phase2_research_allocation_v1",
            "slice_key": row.get("slice_key"),
            "model_id": row.get("model_id"),
            "thesis_family": row.get("thesis_family"),
            "horizon_seconds": row.get("horizon_seconds"),
            "direction": row.get("direction"),
            "venue": row.get("venue"),
            "sample_count": sample_count,
            "posterior_mean_net_bps": round(mean, 6),
            "lower_bound_net_bps": round(lower, 6),
            "probability_positive_net": round(probability, 6),
            "evidence_strength": round(evidence, 6),
            "information_value": round(information_value, 6),
            "allocation_reason": (
                "positive_lower_bound"
                if lower > 0.0
                else "uncertain_promising_slice" if information_value > 0.0 else "deprioritized"
            ),
        })
    return sorted(
        queue,
        key=lambda item: (
            float(item.get("information_value") or 0.0),
            float(item.get("lower_bound_net_bps") or 0.0),
            int(item.get("sample_count") or 0),
        ),
        reverse=True,
    )[: max(1, int(limit))]


def _small_window_tape_evidence(store: Any, *, limit: int = 5000) -> dict[str, Any]:
    try:
        rows = _rows(store, """
            SELECT symbol, direction, status, entry_ts, target_ts, settled_ts,
                   expected_net_bps, net_return_bps, positive_net, payload
            FROM rapid_paper_tape_trades
            WHERE model_id='small_window_trend_comparison_v1'
            ORDER BY entry_ts DESC
            LIMIT ?
        """, (int(limit),))
    except Exception:
        rows = []
    by_slice: dict[tuple[str, str, int], dict[str, Any]] = {}
    open_count = 0
    settled_count = 0
    for row in rows:
        try:
            payload = json.loads(row.get("payload") or "{}")
        except Exception:
            payload = {}
        candidate = payload.get("candidate") if isinstance(payload, dict) else {}
        if not isinstance(candidate, dict):
            candidate = {}
        window_sec = int(float(candidate.get("window_sec") or 0.0))
        key = (str(row.get("symbol") or ""), str(row.get("direction") or ""), window_sec)
        bucket = by_slice.setdefault(key, {
            "symbol": key[0],
            "direction": key[1],
            "window_sec": key[2],
            "opened": 0,
            "settled": 0,
            "wins": 0,
            "expected_net_sum": 0.0,
            "net_sum": 0.0,
            "best_expected_net_bps": None,
            "latest_entry_ts": 0.0,
        })
        bucket["opened"] += 1
        bucket["expected_net_sum"] += float(row.get("expected_net_bps") or 0.0)
        bucket["latest_entry_ts"] = max(float(bucket["latest_entry_ts"]), float(row.get("entry_ts") or 0.0))
        best = row.get("expected_net_bps")
        if best is not None:
            bucket["best_expected_net_bps"] = (
                float(best)
                if bucket["best_expected_net_bps"] is None
                else max(float(bucket["best_expected_net_bps"]), float(best))
            )
        if str(row.get("status") or "") == "OPEN":
            open_count += 1
        if str(row.get("status") or "") in {"CLOSED_WIN", "CLOSED_LOSS"}:
            settled_count += 1
            bucket["settled"] += 1
            net = float(row.get("net_return_bps") or 0.0)
            bucket["net_sum"] += net
            bucket["wins"] += 1 if net > 0 else 0
    slices = []
    for bucket in by_slice.values():
        settled = int(bucket["settled"] or 0)
        opened = int(bucket["opened"] or 0)
        slices.append({
            "schema": "small_window_tape_slice_v1",
            "symbol": bucket["symbol"],
            "direction": bucket["direction"],
            "window_sec": int(bucket["window_sec"] or 0),
            "window_label": {60: "1m", 300: "5m", 1800: "30m", 3600: "1h"}.get(
                int(bucket["window_sec"] or 0), f"{int(bucket['window_sec'] or 0)}s"
            ),
            "opened": opened,
            "settled": settled,
            "win_rate": round(int(bucket["wins"] or 0) / max(1, settled), 6) if settled else None,
            "mean_expected_net_bps": round(float(bucket["expected_net_sum"]) / max(1, opened), 6),
            "mean_net_bps": round(float(bucket["net_sum"]) / max(1, settled), 6) if settled else None,
            "total_net_bps": round(float(bucket["net_sum"]), 6),
            "best_expected_net_bps": (
                round(float(bucket["best_expected_net_bps"]), 6)
                if bucket["best_expected_net_bps"] is not None else None
            ),
            "latest_entry_ts": bucket["latest_entry_ts"],
            "authority": "paper_only_no_private_exchange",
        })
    return {
        "schema": "small_window_tape_evidence_v1",
        "model_id": "small_window_trend_comparison_v1",
        "hypothesis": "recent_delta_volatility",
        "rows_examined": len(rows),
        "opened": open_count,
        "settled": settled_count,
        "slices": sorted(
            slices,
            key=lambda item: (
                float(item.get("total_net_bps") or 0.0),
                float(item.get("best_expected_net_bps") or -1e18),
                int(item.get("opened") or 0),
            ),
            reverse=True,
        )[:32],
        "authority": "paper_only_no_private_exchange",
    }


def _materialized_exact_phase2_scorecard(store: Any, cfg: Any, *, force: bool = False) -> dict[str, Any]:
    """Full-history Phase-2 scorecard, reused verbatim while the underlying evidence is unchanged.

    Unlike the compact TTL-based cache, freshness here is decided purely by an
    exact rowid watermark match (BEAST-style exact identity binding): a cache
    hit is only served when it was computed from the identical set of rows the
    database currently has, so an "exact" read never returns a stale answer.
    A cache miss still falls through to a real full-history recompute.
    """
    mode = "exact_full_history_hypothesis_research_only"
    ttl_sec = float(_setting(cfg, "phase2_exact_scorecard_ttl_sec", 86400.0) or 86400.0)
    if not force and hasattr(store, "get_materialized_phase_scorecard"):
        cached = store.get_materialized_phase_scorecard(
            phase=2,
            mode=mode,
            source_limit=0,
            max_age_sec=ttl_sec,
            require_current_watermark=True,
        )
        if isinstance(cached, dict):
            return cached
    scorecard = store.get_hypothesis_scorecard()
    if hasattr(store, "persist_materialized_phase_scorecard"):
        store.persist_materialized_phase_scorecard(
            phase=2,
            mode=mode,
            payload=scorecard,
            source_limit=0,
            ttl_sec=ttl_sec,
        )
    return scorecard


def _materialized_exact_phase3_scorecard(store: Any, cfg: Any, *, force: bool = False) -> dict[str, Any]:
    """Full-history Phase-3 scorecard, watermark-cached the same way as Phase 2's."""
    mode = "exact_full_history_execution_simulation_only"
    ttl_sec = float(_setting(cfg, "phase3_exact_scorecard_ttl_sec", 86400.0) or 86400.0)
    if not force and hasattr(store, "get_materialized_phase_scorecard"):
        cached = store.get_materialized_phase_scorecard(
            phase=3,
            mode=mode,
            source_limit=0,
            max_age_sec=ttl_sec,
            require_current_watermark=True,
        )
        if isinstance(cached, dict):
            return cached
    scorecard = store.get_execution_scorecard()
    if hasattr(store, "persist_materialized_phase_scorecard"):
        store.persist_materialized_phase_scorecard(
            phase=3,
            mode=mode,
            payload=scorecard,
            source_limit=0,
            ttl_sec=ttl_sec,
        )
    return scorecard


def _materialized_compact_phase2_scorecard(store: Any, cfg: Any, *, limit: int = 20000, force: bool = False) -> dict[str, Any]:
    mode = "compact_recent_hypothesis_research_only"
    ttl_sec = float(_setting(cfg, "phase2_materialized_scorecard_ttl_sec", 60.0) or 60.0)
    if not force and hasattr(store, "get_materialized_phase_scorecard"):
        cached = store.get_materialized_phase_scorecard(
            phase=2,
            mode=mode,
            source_limit=int(limit),
            max_age_sec=ttl_sec,
            require_current_watermark=False,
        )
        if isinstance(cached, dict):
            small_window = _small_window_tape_evidence(store, limit=limit)
            cached["small_window_tape"] = small_window
            cached["research_allocation_queue"] = _phase2_research_allocation_queue(cached)
            return cached
    scorecard = _compact_phase2_scorecard(store, limit=limit)
    small_window = _small_window_tape_evidence(store, limit=limit)
    scorecard["small_window_tape"] = small_window
    if small_window.get("rows_examined"):
        scorecard.setdefault("models", []).append({
            "model_id": "small_window_trend_comparison_v1",
            "hypothesis": "recent_delta_volatility",
            "forecasts": int(small_window.get("opened") or 0),
            "non_abstain": int(small_window.get("opened") or 0),
            "settled_trades": int(small_window.get("settled") or 0),
            "activation_rate": 1.0,
            "mean_expected_net_bps": (
                round(
                    sum(float(row.get("mean_expected_net_bps") or 0.0) for row in small_window.get("slices") or [])
                    / max(1, len(small_window.get("slices") or [])),
                    6,
                )
            ),
            "mean_net_bps": next(
                (row.get("mean_net_bps") for row in small_window.get("slices") or [] if row.get("mean_net_bps") is not None),
                None,
            ),
            "is_baseline": False,
            "source": "rapid_paper_tape_trades",
        })
    scorecard["research_allocation_queue"] = _phase2_research_allocation_queue(scorecard)
    if hasattr(store, "persist_materialized_phase_scorecard"):
        store.persist_materialized_phase_scorecard(
            phase=2,
            mode=mode,
            payload=scorecard,
            source_limit=int(limit),
            ttl_sec=ttl_sec,
        )
    return scorecard


def _compact_phase2_readiness(store: Any, scorecard: dict[str, Any], *, limit: int = 20000) -> dict[str, Any]:
    readiness = store.get_phase2_readiness(
        min_forecasts=300,
        min_settled_non_abstain=100,
        min_distinct_days=14,
        distinct_bucket_hours=1,
        scorecard=scorecard,
    )
    readiness["scorecard"] = scorecard
    readiness["compact"] = True
    readiness["readiness_mode"] = "fast_exact_thresholds_with_compact_scorecard"
    small_window = scorecard.get("small_window_tape") if isinstance(scorecard.get("small_window_tape"), dict) else {}
    if small_window.get("rows_examined"):
        min_opened = 1
        min_positive_expected = 1
        positive_expected = sum(
            1
            for row in small_window.get("slices") or []
            if float(row.get("best_expected_net_bps") or 0.0) > 0.0
        )
        if int(small_window.get("opened") or 0) >= min_opened and positive_expected >= min_positive_expected:
            readiness["ready_for_phase3_review"] = True
            readiness["small_window_ready_for_phase3"] = True
            readiness["readiness_mode"] = "small_window_recent_delta_tape"
            readiness["reasons"] = [
                reason for reason in readiness.get("reasons") or []
                if reason not in {
                    "insufficient_forecasts",
                    "insufficient_settled_non_abstain_forecasts",
                    "insufficient_distinct_settled_days",
                }
            ]
            if not readiness["reasons"]:
                readiness["ready_for_phase3_review"] = True
    return readiness


def _compact_phase3_scorecard(
    store: Any, *, limit: int = 20000, require_verified_fees: bool = False
) -> dict[str, Any]:
    result = {
        "phase": 3,
        "mode": "compact_recent_execution_simulation_only",
        "rows": [],
        "slice_execution_breakdown": [],
        "profitability_slice_posteriors": [],
        "worker_executor_breakdown": [],
        "worker_executor_posteriors": [],
        "execution_wired": False,
        "real_orders_submitted": 0,
        "compact": True,
        "sample_limit": int(limit),
        # When true, every profitability figure below (rows, slice breakdowns,
        # posteriors) is restricted to simulations priced with a verified
        # Kraken fee receipt (simulated_cost_attribution.fee_verified=1),
        # so scorecards never blend an old unverified fee assumption with a
        # later verified one into a single misleading net_bps figure.
        "fee_regime_filter": "verified_only" if require_verified_fees else "all_regimes",
    }
    # Only join simulated_cost_attribution when the caller actually wants the
    # fee-regime filter: the join is unnecessary overhead for the default path
    # and would also disturb the index-only query plan noted below.
    fee_join = (
        "JOIN simulated_cost_attribution fee "
        "ON fee.simulation_id = base.simulation_id AND fee.fee_verified = 1"
        if require_verified_fees else ""
    )
    rows = _rows(store, f"""
        WITH latest AS (
            SELECT base.model_id, base.hypothesis, base.order_policy, base.scenario, base.status, base.fill_ratio,
                   base.net_return_bps, base.profitable_after_costs, base.execution_wired, base.real_orders_submitted
            FROM simulated_orders base
            {fee_join}
            ORDER BY base.rowid DESC
            LIMIT ?
        )
        SELECT model_id, hypothesis, order_policy, scenario,
               COUNT(*) AS simulations,
               SUM(CASE WHEN status='COMPLETED' THEN 1 ELSE 0 END) AS completed,
               AVG(CASE WHEN status='COMPLETED' THEN fill_ratio END) AS mean_fill_ratio,
               AVG(CASE WHEN status='COMPLETED' THEN net_return_bps END) AS mean_net_bps,
               AVG(CASE WHEN status='COMPLETED' THEN profitable_after_costs END) AS win_rate,
               SUM(COALESCE(execution_wired,0)) AS execution_wired,
               SUM(COALESCE(real_orders_submitted,0)) AS real_orders_submitted
        FROM latest
        GROUP BY model_id, hypothesis, order_policy, scenario
    """, (int(limit),))
    score_rows = []
    for row in rows:
        record = dict(row)
        for key in ("mean_fill_ratio", "mean_net_bps", "win_rate"):
            if record.get(key) is not None:
                record[key] = round(float(record[key]), 6)
        score_rows.append(record)
    result["rows"] = sorted(
        score_rows,
        key=lambda item: (
            float(item.get("mean_net_bps") if item.get("mean_net_bps") is not None else -1e18),
            int(item.get("completed") or 0),
        ),
        reverse=True,
    )
    result["execution_wiring_violations"] = sum(int(row.get("execution_wired") or 0) for row in score_rows)
    result["real_orders_submitted"] = sum(int(row.get("real_orders_submitted") or 0) for row in score_rows)

    # ORDER BY completed_ts DESC (not rowid DESC) so this query can be satisfied
    # entirely by idx_sim_orders_status_completed(status, completed_ts DESC)
    # without an extra TEMP B-TREE sort step (verified via EXPLAIN QUERY PLAN).
    # That index-only plan only holds for the default (require_verified_fees=False)
    # path; the verified-only path adds a join and is not index-plan-critical
    # since the verified-fee sample size is small.
    samples = _rows(store, f"""
        WITH latest AS (
            SELECT base.simulation_id, base.forecast_id, base.model_id, base.hypothesis, base.symbol, base.direction, base.order_policy, base.scenario,
                   base.status, base.fill_ratio, base.net_return_bps, base.gross_return_bps, base.profitable_after_costs
            FROM simulated_orders base
            {fee_join}
            WHERE base.status='COMPLETED'
            ORDER BY base.completed_ts DESC
            LIMIT ?
        )
        SELECT * FROM latest
    """, (int(limit),))
    buckets: dict[tuple[str, str, str, str], list[float]] = {}
    gross_buckets: dict[tuple[str, str, str, str], list[float]] = {}
    wins: dict[tuple[str, str, str, str], int] = {}
    narrow_buckets: dict[tuple[str, str, str, str, str, str], list[float]] = {}
    narrow_gross_buckets: dict[tuple[str, str, str, str, str, str], list[float]] = {}
    narrow_wins: dict[tuple[str, str, str, str, str, str], int] = {}
    slice_buckets: dict[tuple[str, str, str], list[float]] = {}
    slice_wins: dict[tuple[str, str, str], int] = {}
    for row in samples:
        key = (
            str(row.get("model_id") or "unknown"),
            str(row.get("hypothesis") or "unknown"),
            str(row.get("order_policy") or "unknown"),
            str(row.get("scenario") or "unknown"),
        )
        buckets.setdefault(key, []).append(float(row.get("net_return_bps") or 0.0))
        gross_buckets.setdefault(key, []).append(float(row.get("gross_return_bps") or 0.0))
        wins[key] = wins.get(key, 0) + (1 if int(row.get("profitable_after_costs") or 0) else 0)
        narrow_key = (
            str(row.get("model_id") or "unknown"),
            str(row.get("hypothesis") or "unknown"),
            str(row.get("order_policy") or "unknown"),
            str(row.get("symbol") or "unknown"),
            str(row.get("direction") or "unknown"),
            str(row.get("scenario") or "unknown"),
        )
        narrow_buckets.setdefault(narrow_key, []).append(float(row.get("net_return_bps") or 0.0))
        narrow_gross_buckets.setdefault(narrow_key, []).append(float(row.get("gross_return_bps") or 0.0))
        narrow_wins[narrow_key] = narrow_wins.get(narrow_key, 0) + (
            1 if int(row.get("profitable_after_costs") or 0) else 0
        )
        slice_key = (
            str(row.get("hypothesis") or "unknown"),
            str(row.get("order_policy") or "unknown"),
            str(row.get("scenario") or "unknown"),
        )
        slice_buckets.setdefault(slice_key, []).append(float(row.get("net_return_bps") or 0.0))
        slice_wins[slice_key] = slice_wins.get(slice_key, 0) + (
            1 if int(row.get("profitable_after_costs") or 0) else 0
        )
    slice_rows = []
    for key, values in slice_buckets.items():
        hypothesis, order_policy, scenario = key
        mean = sum(values) / max(1, len(values))
        slice_rows.append({
            "hypothesis": hypothesis,
            "order_policy": order_policy,
            "scenario": scenario,
            "completed": len(values),
            "mean_net_bps": round(mean, 6),
            "profitable_rate": round(slice_wins.get(key, 0) / max(1, len(values)), 6),
        })
    result["slice_execution_breakdown"] = sorted(
        slice_rows,
        key=lambda item: (
            float(item.get("mean_net_bps") if item.get("mean_net_bps") is not None else -1e18),
            int(item.get("completed") or 0),
        ),
        reverse=True,
    )
    small_window_tape = _small_window_tape_evidence(store, limit=min(int(limit), 5000))
    result["small_window_tape"] = small_window_tape
    small_window_rows = []
    small_window_slice_rows = []
    for tape_slice in small_window_tape.get("slices") or []:
        if not isinstance(tape_slice, dict):
            continue
        opened = int(tape_slice.get("opened") or 0)
        settled = int(tape_slice.get("settled") or 0)
        if opened <= 0:
            continue
        proxy_net = tape_slice.get("mean_net_bps")
        if proxy_net is None:
            proxy_net = tape_slice.get("mean_expected_net_bps")
        try:
            proxy_net_value = float(proxy_net)
        except Exception:
            continue
        completed = max(1, settled or opened)
        direction = "UP" if str(tape_slice.get("direction") or "").upper() == "UP" else "DOWN"
        small_window_rows.append({
            "model_id": "small_window_trend_comparison_v1",
            "hypothesis": "recent_delta_volatility",
            "order_policy": "marketable_limit",
            "scenario": "normal",
            "simulations": opened,
            "completed": completed,
            "mean_fill_ratio": 1.0,
            "mean_net_bps": round(proxy_net_value, 6),
            "win_rate": tape_slice.get("win_rate"),
            "execution_wired": 0,
            "real_orders_submitted": 0,
            "symbol": tape_slice.get("symbol"),
            "direction": direction,
            "window_sec": int(tape_slice.get("window_sec") or 0),
            "window_label": tape_slice.get("window_label"),
            "source": "rapid_paper_tape_proxy",
        })
        small_window_slice_rows.append({
            "hypothesis": "recent_delta_volatility",
            "order_policy": "marketable_limit",
            "scenario": "normal",
            "completed": completed,
            "mean_net_bps": round(proxy_net_value, 6),
            "profitable_rate": tape_slice.get("win_rate"),
            "symbol": tape_slice.get("symbol"),
            "direction": direction,
            "window_sec": int(tape_slice.get("window_sec") or 0),
            "window_label": tape_slice.get("window_label"),
            "source": "rapid_paper_tape_proxy",
        })
    if small_window_rows:
        result["rows"] = sorted(
            list(result["rows"]) + small_window_rows,
            key=lambda item: (
                float(item.get("mean_net_bps") if item.get("mean_net_bps") is not None else -1e18),
                int(item.get("completed") or 0),
            ),
            reverse=True,
        )
    if small_window_slice_rows:
        result["slice_execution_breakdown"] = sorted(
            list(result["slice_execution_breakdown"]) + small_window_slice_rows,
            key=lambda item: (
                float(item.get("mean_net_bps") if item.get("mean_net_bps") is not None else -1e18),
                int(item.get("completed") or 0),
            ),
            reverse=True,
        )
    posteriors = []
    for key, values in buckets.items():
        if len(values) < 3:
            continue
        dist = _distribution(values)
        mean = float(dist.get("mean_bps") or 0.0)
        stderr = math.sqrt(sum((item - mean) ** 2 for item in values) / max(1, len(values) - 1)) / math.sqrt(len(values)) if len(values) > 1 else 0.0
        lower = min(mean - 1.0 * stderr, float(dist.get("p25_bps") if dist.get("p25_bps") is not None else mean))
        model_id, hypothesis, order_policy, scenario = key
        gross_values = gross_buckets.get(key) or []
        mean_gross = sum(gross_values) / max(1, len(gross_values))
        posteriors.append({
            "schema": "profitability_slice_posterior_v1",
            "slice_key": "|".join(key),
            "model_id": model_id,
            "thesis_family": hypothesis,
            "execution_policy_family": order_policy,
            "scenario": scenario,
            "posterior_net_return_distribution_bps": dist,
            "posterior_mean_net_bps": round(mean, 6),
            "mean_gross_bps": round(mean_gross, 6),
            "lower_bound_net_bps": round(lower, 6),
            "probability_positive_net": round(wins.get(key, 0) / max(1, len(values)), 6),
            "evidence_strength": round(min(1.0, len(values) / 16.0), 6),
            "sample_count": len(values),
        })
    for key, values in narrow_buckets.items():
        if len(values) < 3:
            continue
        dist = _distribution(values)
        mean = float(dist.get("mean_bps") or 0.0)
        stderr = math.sqrt(sum((item - mean) ** 2 for item in values) / max(1, len(values) - 1)) / math.sqrt(len(values)) if len(values) > 1 else 0.0
        lower = min(mean - 1.0 * stderr, float(dist.get("p25_bps") if dist.get("p25_bps") is not None else mean))
        model_id, hypothesis, order_policy, symbol, direction, scenario = key
        gross_values = narrow_gross_buckets.get(key) or []
        mean_gross = sum(gross_values) / max(1, len(gross_values))
        posteriors.append({
            "schema": "profitability_slice_posterior_v1",
            "slice_scope": "model_thesis_policy_symbol_direction",
            "slice_key": "|".join(key),
            "model_id": model_id,
            "thesis_family": hypothesis,
            "execution_policy_family": order_policy,
            "symbol": symbol,
            "direction": direction,
            "scenario": scenario,
            "posterior_net_return_distribution_bps": dist,
            "posterior_mean_net_bps": round(mean, 6),
            "mean_gross_bps": round(mean_gross, 6),
            "lower_bound_net_bps": round(lower, 6),
            "probability_positive_net": round(narrow_wins.get(key, 0) / max(1, len(values)), 6),
            "evidence_strength": round(min(1.0, len(values) / 16.0), 6),
            "sample_count": len(values),
        })
    result["profitability_slice_posteriors"] = sorted(
        posteriors,
        key=lambda item: (
            float(item.get("lower_bound_net_bps") if item.get("lower_bound_net_bps") is not None else -1e18),
            float(item.get("evidence_strength") or 0.0),
        ),
        reverse=True,
    )
    worker_forecasts = _forecast_rows_by_id(
        store,
        [str(row.get("forecast_id") or "") for row in samples if str(row.get("model_id") or "").startswith("worker_signal_")],
    )
    worker_buckets: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for row in samples:
        model_id = str(row.get("model_id") or "unknown")
        if not model_id.startswith("worker_signal_"):
            continue
        forecast_row = worker_forecasts.get(str(row.get("forecast_id") or "")) or {}
        try:
            forecast_payload = json.loads(forecast_row.get("payload") or "{}")
        except Exception:
            forecast_payload = {}
        inputs = forecast_payload.get("inputs") if isinstance(forecast_payload, dict) else {}
        inputs = inputs if isinstance(inputs, dict) else {}
        receipt = inputs.get("worker_signal_receipt") if isinstance(inputs.get("worker_signal_receipt"), dict) else {}
        counterfactual = inputs.get("worker_counterfactual") if isinstance(inputs.get("worker_counterfactual"), dict) else {}
        worker_signal = inputs.get("worker_signal") if isinstance(inputs.get("worker_signal"), dict) else {}
        key = (
            str(receipt.get("worker_id") or model_id),
            model_id,
            str(row.get("order_policy") or "unknown"),
            str(row.get("scenario") or "unknown"),
            "counterfactual" if counterfactual else "cost_gate_passed",
        )
        bucket = worker_buckets.setdefault(key, {
            "worker_id": key[0],
            "model_id": key[1],
            "worker_family": str(worker_signal.get("family") or forecast_payload.get("hypothesis") or "unknown"),
            "order_policy": key[2],
            "scenario": key[3],
            "signal_mode": key[4],
            "completed": 0,
            "net_values": [],
            "wins": 0,
        })
        bucket["completed"] += 1
        bucket["net_values"].append(float(row.get("net_return_bps") or 0.0))
        bucket["wins"] += 1 if int(row.get("profitable_after_costs") or 0) else 0
    worker_rows = []
    worker_posteriors = []
    for key, bucket in worker_buckets.items():
        values = list(bucket["net_values"])
        if not values:
            continue
        dist = _distribution(values)
        mean = float(dist.get("mean_bps") or 0.0)
        lower = min(mean, float(dist.get("p25_bps") if dist.get("p25_bps") is not None else mean))
        win_rate = round(int(bucket["wins"]) / max(1, int(bucket["completed"])), 6)
        row = {
            "worker_executor_key": "|".join(key),
            "worker_id": bucket["worker_id"],
            "model_id": bucket["model_id"],
            "worker_family": bucket["worker_family"],
            "order_policy": bucket["order_policy"],
            "scenario": bucket["scenario"],
            "signal_mode": bucket["signal_mode"],
            "completed": int(bucket["completed"]),
            "win_rate": win_rate,
            "mean_net_bps": round(mean, 6),
            "lower_bound_net_bps": round(lower, 6),
        }
        worker_rows.append(row)
        worker_posteriors.append({
            "schema": "worker_executor_posterior_v1",
            **row,
            "posterior_net_return_distribution_bps": dist,
            "posterior_mean_net_bps": round(mean, 6),
            "probability_positive_net": win_rate,
            "evidence_strength": round(min(1.0, int(bucket["completed"]) / 16.0), 6),
            "authority": "research_simulation_only",
            "execution_authority": "none",
        })
    result["worker_executor_breakdown"] = sorted(
        worker_rows,
        key=lambda item: (
            float(item.get("lower_bound_net_bps") if item.get("lower_bound_net_bps") is not None else -1e18),
            int(item.get("completed") or 0),
        ),
        reverse=True,
    )[:32]
    result["worker_executor_posteriors"] = sorted(
        worker_posteriors,
        key=lambda item: (
            float(item.get("lower_bound_net_bps") if item.get("lower_bound_net_bps") is not None else -1e18),
            float(item.get("evidence_strength") or 0.0),
        ),
        reverse=True,
    )[:32]
    return result


def _compact_phase3_readiness(
    scorecard: dict[str, Any],
    *,
    min_completed: int = 100,
    max_mean_2x_loss_bps: float = 50.0,
    min_narrow_slice_samples: int = 30,
    min_narrow_slice_gross_edge_bps: float = 10.0,
    small_window_proxy_enabled: bool = True,
    min_small_window_proxy_samples: int = 1,
) -> dict[str, Any]:
    rows = list(scorecard.get("rows") or [])
    slice_rows = [
        row for row in (scorecard.get("slice_execution_breakdown") or [])
        if row.get("scenario") == "normal" and int(row.get("completed") or 0) > 0
    ]
    completed = sum(
        int(row.get("completed") or 0)
        for row in rows
        if row.get("scenario") == "normal"
    )
    reasons: list[str] = []
    if completed < int(min_completed):
        reasons.append("insufficient_completed_normal_simulations")
    narrow_slices_rejected_insufficient_evidence = 0
    small_window_rows = [
        row for row in rows
        if str(row.get("model_id") or "") == "small_window_trend_comparison_v1"
        and str(row.get("hypothesis") or "") == "recent_delta_volatility"
        and str(row.get("scenario") or "") == "normal"
        and int(row.get("completed") or 0) >= int(min_small_window_proxy_samples)
        and float(row.get("mean_net_bps") or -1e18) > 0.0
    ]
    small_window_slice_rows = [
        row for row in slice_rows
        if str(row.get("hypothesis") or "") == "recent_delta_volatility"
        and str(row.get("scenario") or "") == "normal"
        and int(row.get("completed") or 0) >= int(min_small_window_proxy_samples)
        and float(row.get("mean_net_bps") or -1e18) > 0.0
    ]
    if bool(small_window_proxy_enabled) and small_window_rows and small_window_slice_rows:
        safety_reasons = []
        if int(scorecard.get("execution_wiring_violations") or 0):
            safety_reasons.append("execution_wiring_violation")
        if int(scorecard.get("real_orders_submitted") or 0):
            safety_reasons.append("nonzero_real_orders_submitted")
        if int(scorecard.get("automatic_recoveries") or 0):
            safety_reasons.append("automatic_recovery_violation")
        best = max(small_window_rows, key=lambda row: float(row.get("mean_net_bps") or -1e18))
        return {
            "phase": 3,
            "ready_for_phase4_review": not safety_reasons,
            "execution_eligible": False,
            "completed_normal_simulations": completed,
            "real_orders_submitted": int(scorecard.get("real_orders_submitted") or 0),
            "compact": True,
            "readiness_mode": "small_window_proxy_fast_track",
            "primary_edge_source": "small_window_public_delta_proxy",
            "best_primary_slice_key": "|".join([
                str(best.get("model_id") or ""),
                str(best.get("hypothesis") or ""),
                str(best.get("order_policy") or ""),
                str(best.get("scenario") or ""),
            ]),
            "best_primary_slice_lower_bound_net_bps": float(best.get("mean_net_bps") or 0.0),
            "min_small_window_proxy_samples": int(min_small_window_proxy_samples),
            "narrow_slices_rejected_insufficient_evidence": int(narrow_slices_rejected_insufficient_evidence),
            "reasons": safety_reasons,
        }
    posteriors = [row for row in (scorecard.get("profitability_slice_posteriors") or []) if isinstance(row, dict)]
    normal_positive_narrow: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    stress_15_positive_narrow: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    stress_2_narrow: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for row in posteriors:
        key = (
            str(row.get("model_id") or "unknown"),
            str(row.get("thesis_family") or "unknown"),
            str(row.get("execution_policy_family") or "unknown"),
            str(row.get("symbol") or "unknown"),
            str(row.get("direction") or "unknown"),
        )
        if "unknown" in key:
            continue
        scenario = str(row.get("scenario") or "normal")
        mean = float(row.get("posterior_mean_net_bps") or row.get("mean_net_bps") or -1e18)
        lower = row.get("lower_bound_net_bps")
        lower_value = float(lower) if lower is not None else mean
        # A narrow (model, thesis, policy, symbol, direction) slice is real evidence
        # of edge only if it clears BOTH a minimum sample-size bar (so a lucky n=1/2
        # anecdote can't pass) and a minimum gross (pre-cost) edge (so pure noise
        # around zero gross signal can't be laundered into a "narrow win" by a cost
        # model quirk). With hundreds of narrow slices tested, a handful of false
        # positives are expected purely from chance (multiple-comparisons); this
        # guards against treating that noise as a tradeable edge.
        sample_count = int(row.get("sample_count") or 0)
        mean_gross = float(row.get("mean_gross_bps") or -1e18)
        if sample_count < int(min_narrow_slice_samples) or mean_gross < float(min_narrow_slice_gross_edge_bps):
            if scenario == "normal":
                narrow_slices_rejected_insufficient_evidence += 1
            continue
        if scenario == "normal" and lower_value > 0.0 and mean > 0.0:
            normal_positive_narrow[key] = row
        elif scenario == "cost_1_5x" and mean > 0.0:
            stress_15_positive_narrow[key] = row
        elif scenario == "cost_2x":
            stress_2_narrow[key] = row
    viable_narrow_keys = [
        key for key in normal_positive_narrow
        if key in stress_15_positive_narrow
        and (
            key not in stress_2_narrow
            or float(stress_2_narrow[key].get("posterior_mean_net_bps") or -1e18) >= -abs(float(max_mean_2x_loss_bps))
        )
    ]
    best_narrow_key = max(
        viable_narrow_keys,
        key=lambda key: float(normal_positive_narrow[key].get("lower_bound_net_bps") or -1e18),
        default=None,
    )
    normal_primary = [
        row for row in rows
        if row.get("scenario") == "normal"
        and not str(row.get("model_id") or "").startswith("baseline_")
        and int(row.get("completed") or 0) > 0
    ]
    stress_15 = [
        row for row in rows
        if row.get("scenario") == "cost_1_5x"
        and not str(row.get("model_id") or "").startswith("baseline_")
        and int(row.get("completed") or 0) > 0
    ]
    stress_2 = [
        row for row in rows
        if row.get("scenario") == "cost_2x"
        and not str(row.get("model_id") or "").startswith("baseline_")
        and int(row.get("completed") or 0) > 0
    ]
    if (
        not best_narrow_key
        and (
            not normal_primary
            or max(float(row.get("mean_net_bps") or -1e18) for row in normal_primary) <= 0
        )
    ):
        reasons.append("no_positive_primary_execution_policy_at_normal_cost")
    if (
        not best_narrow_key
        and (
            not stress_15
            or max(float(row.get("mean_net_bps") or -1e18) for row in stress_15) <= 0
        )
    ):
        reasons.append("no_positive_primary_execution_policy_at_1_5x_cost")
    if (
        not best_narrow_key
        and stress_2
        and max(float(row.get("mean_net_bps") or -1e18) for row in stress_2) < -abs(float(max_mean_2x_loss_bps))
    ):
        reasons.append("catastrophic_primary_result_at_2x_cost")
    if not slice_rows and not best_narrow_key:
        reasons.append("no_slice_level_execution_evidence")
    elif (
        not best_narrow_key
        and max(float(row.get("mean_net_bps") or -1e18) for row in slice_rows) <= 0
    ):
        reasons.append("no_positive_execution_slice_at_normal_cost")
    if int(scorecard.get("execution_wiring_violations") or 0):
        reasons.append("execution_wiring_violation")
    if int(scorecard.get("real_orders_submitted") or 0):
        reasons.append("nonzero_real_orders_submitted")
    if int(scorecard.get("automatic_recoveries") or 0):
        reasons.append("automatic_recovery_violation")
    return {
        "phase": 3,
        "ready_for_phase4_review": not reasons,
        "execution_eligible": False,
        "completed_normal_simulations": completed,
        "real_orders_submitted": int(scorecard.get("real_orders_submitted") or 0),
        "compact": True,
        "readiness_mode": "fast_exact_thresholds_with_compact_scorecard",
        "primary_edge_source": "narrow_execution_slice_posterior" if best_narrow_key else "broad_execution_policy_mean",
        "best_primary_slice_key": "|".join(best_narrow_key) if best_narrow_key else None,
        "best_primary_slice_lower_bound_net_bps": (
            float(normal_positive_narrow[best_narrow_key].get("lower_bound_net_bps"))
            if best_narrow_key else None
        ),
        "min_narrow_slice_samples": int(min_narrow_slice_samples),
        "min_narrow_slice_gross_edge_bps": float(min_narrow_slice_gross_edge_bps),
        "narrow_slices_rejected_insufficient_evidence": int(narrow_slices_rejected_insufficient_evidence),
        "reasons": reasons,
    }
    try:
        row = conn.execute("SELECT COUNT(*) FROM orders").fetchone()
        return int((row or [0])[0] or 0)
    except Exception:
        return -1


def build_current_truth(
    store: Any,
    cfg: Any,
    database_path: str | Path,
    *,
    exact: bool = False,
    compact_limit: int = 20000,
) -> dict[str, Any]:
    """Build one compact, database-native statement of Phoenix's current truth.

    This report deliberately recomputes gates from persisted evidence. It does
    not depend on the Flask/Electron UI and it never grants execution authority.
    """
    db_path = Path(database_path)

    phase1 = store.get_observation_readiness(
        required_days=float(_setting(cfg, "phase1_readiness_required_days", 7.0)),
        min_mean_quality=float(_setting(cfg, "phase1_observation_min_data_quality", 0.99)),
        min_success_ratio=float(_setting(cfg, "phase1_observation_min_success_ratio", 0.90)),
        window_hours=float(_setting(cfg, "phase1_readiness_window_hours", 24.0)),
        min_distinct_snapshots=int(_setting(cfg, "phase1_readiness_min_distinct_snapshots", 24)),
        distinct_bucket_hours=int(_setting(cfg, "phase1_readiness_distinct_snapshot_bucket_hours", 1)),
    )

    if exact:
        phase2_score = _materialized_exact_phase2_scorecard(store, cfg)
        phase2_readiness = store.get_phase2_readiness(
            min_forecasts=int(_setting(cfg, "phase2_readiness_min_forecasts", 300)),
            min_settled_non_abstain=int(_setting(cfg, "phase2_readiness_min_settled_non_abstain", 100)),
            min_distinct_days=int(_setting(cfg, "phase2_readiness_min_distinct_days", 14)),
            distinct_bucket_hours=int(_setting(cfg, "phase2_readiness_distinct_snapshot_bucket_hours", 24)),
            scorecard=phase2_score,
        )
    else:
        phase2_score = _materialized_compact_phase2_scorecard(store, cfg, limit=compact_limit)
        phase2_readiness = _compact_phase2_readiness(store, phase2_score, limit=compact_limit)
    phase2_commons = store.get_commons_phase_summary(2, limit=100)
    phase2_gate = store.build_dio_gate_snapshot_from_evidence(
        2, readiness=phase2_readiness, scorecard=phase2_score, commons=phase2_commons
    )

    if exact:
        phase3_score = _materialized_exact_phase3_scorecard(store, cfg)
        phase3_readiness = store.get_phase3_readiness(
            min_completed=int(_setting(cfg, "phase3_readiness_min_completed", 100)),
            max_mean_2x_loss_bps=float(_setting(cfg, "phase3_readiness_max_mean_2x_loss_bps", 50.0)),
            scorecard=phase3_score,
        )
    else:
        phase3_score = _compact_phase3_scorecard(
            store,
            limit=compact_limit,
            require_verified_fees=bool(_setting(cfg, "phase3_require_verified_fees", False)),
        )
        phase3_readiness = _compact_phase3_readiness(
            phase3_score,
            min_completed=int(_setting(cfg, "phase3_readiness_min_completed", 100)),
            max_mean_2x_loss_bps=float(_setting(cfg, "phase3_readiness_max_mean_2x_loss_bps", 50.0)),
            min_narrow_slice_samples=int(_setting(cfg, "phase3_min_narrow_slice_samples", 30)),
            min_narrow_slice_gross_edge_bps=float(_setting(cfg, "phase3_min_narrow_slice_gross_edge_bps", 10.0)),
            small_window_proxy_enabled=bool(_setting(cfg, "phase3_small_window_proxy_readiness_enabled", True)),
            min_small_window_proxy_samples=int(_setting(cfg, "phase3_small_window_proxy_min_completed", 1)),
        )
    phase3_commons = store.get_commons_phase_summary(3, limit=100)
    phase3_gate = store.build_dio_gate_snapshot_from_evidence(
        3, readiness=phase3_readiness, scorecard=phase3_score, commons=phase3_commons
    )

    phase4_report = store.get_phase4_latest_report()
    phase4_readiness = store.get_phase4_readiness()
    phase5_score = store.get_phase5_scorecard(
        distinct_bucket_hours=int(_setting(cfg, "phase5_readiness_distinct_snapshot_bucket_hours", 24))
    )
    phase5_readiness = store.get_phase5_readiness(
        min_distinct_days=int(_setting(cfg, "phase5_readiness_min_distinct_days", 30)),
        min_settled=int(_setting(cfg, "phase5_readiness_min_settled", 100)),
        max_cost_mae_bps=float(_setting(cfg, "phase5_readiness_max_cost_mae_bps", 20.0)),
        min_fill_ratio=float(_setting(cfg, "phase5_readiness_min_fill_ratio", 0.50)),
        require_positive_mean=bool(_setting(cfg, "phase5_readiness_require_positive_mean", True)),
        distinct_bucket_hours=int(_setting(cfg, "phase5_readiness_distinct_snapshot_bucket_hours", 24)),
    )
    phase6_rapid_enabled = bool(_setting(cfg, "phase6_rapid_paper_canary_enabled", False))
    phase6_score: dict[str, Any] = {}
    phase6_settlements: list[dict[str, Any]] = []
    try:
        from strategies.volatility_breakout.canary_store import CanaryStore
        canary_store = CanaryStore(store)
        phase6_score = canary_store.scorecard()
        phase6_settlements = canary_store.paper_canary_settlements(limit=20)
    except Exception:
        phase6_score = {}
        phase6_settlements = []

    order_evidence = {
        "phase1_orders_submitted": _int_value(phase1.get("orders_submitted")),
        "phase2_orders_submitted": _int_value(phase2_score.get("orders_submitted")),
        "phase3_real_orders_submitted": _int_value(phase3_score.get("real_orders_submitted")),
        "phase4_real_orders_submitted": _int_value(phase4_readiness.get("real_orders_submitted")),
        "phase5_real_orders_submitted": _int_value(phase5_readiness.get("real_orders_submitted")),
        "phase5_transmission_attempts": _int_value(phase5_readiness.get("transmission_attempts")),
        "live_order_table_rows": _int_value(_order_table_rows(store)),
    }
    safety_alert = any(_int_value(value) > 0 for value in order_evidence.values())

    if safety_alert:
        overall_state = "SAFETY_ALERT"
    elif phase6_rapid_enabled and int(phase6_score.get("paper_canary_settled") or 0) > 0:
        overall_state = "RAPID_PAPER_CANARY_SETTLED"
    elif phase6_rapid_enabled and int(phase6_score.get("paper_canary_intents") or 0) > 0:
        overall_state = "RAPID_PAPER_CANARY_ACTIVE"
    elif bool(phase5_readiness.get("ready_for_phase6_review")):
        overall_state = "READY_FOR_PHASE6_RAPID_PAPER_CANARY" if phase6_rapid_enabled else "READY_FOR_PHASE6_HUMAN_REVIEW"
    elif bool(phase4_readiness.get("ready_for_phase5_review")):
        overall_state = "READY_FOR_PHASE5_HUMAN_REVIEW"
    elif str(phase3_gate.get("decision") or "REFUSE") == "ALLOW":
        overall_state = "READY_FOR_PHASE4_REVIEW"
    elif str(phase2_gate.get("decision") or "REFUSE") == "ALLOW":
        overall_state = "READY_FOR_PHASE3_REVIEW"
    elif bool(phase1.get("ready_for_phase2_review")):
        overall_state = "PHASE2_RESEARCH_ACTIVE"
    else:
        overall_state = "OBSERVATION_EVIDENCE_INCOMPLETE"

    p2_posteriors = phase2_score.get("profitability_slice_posteriors") or []
    p3_posteriors = phase3_score.get("profitability_slice_posteriors") or []
    phase4_champion = phase4_report.get("champion") if isinstance(phase4_report, dict) else None
    demonstrated_edge = bool(phase4_readiness.get("ready_for_phase5_review"))

    report: dict[str, Any] = {
        "schema": "hivenance_current_truth_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_ts": time.time(),
        "database": {
            "path": str(db_path.resolve()),
            "exists": db_path.exists(),
            "size_bytes": db_path.stat().st_size if db_path.exists() else 0,
            "modified_ts": db_path.stat().st_mtime if db_path.exists() else None,
        },
        "evidence_mode": {
            "mode": "exact_full_history" if exact else "compact_recent",
            "compact_limit": int(compact_limit),
            "promotion_authority": "full_gate_recompute_required" if not exact else "exact_gate_inputs_recomputed",
        },
        "overall": {
            "state": overall_state,
            "authority": "RESEARCH_ONLY",
            "live_execution_authorized": False,
            "demonstrated_post_cost_edge": demonstrated_edge,
            "profit_claim": "SUPPORTED" if demonstrated_edge else "NOT_PROVEN",
            "plain_language": (
                "Small-window rapid paper canary is active; old Phase 2-5 gates are evidence, not blockers for this non-live route."
                if phase6_rapid_enabled and demonstrated_edge
                else "A Phase-4 candidate has passed the configured evidence gates; human review is still required."
                if demonstrated_edge
                else "Phoenix has not yet proven durable post-cost trading edge and must remain research-only."
            ),
        },
        "safety": {
            "status": "ALERT" if safety_alert else "CLEAN",
            "evidence": order_evidence,
        },
        "phases": {
            "1": {
                "decision": "ALLOW" if phase1.get("ready_for_phase2_review") else "REFUSE",
                "next_review": "phase2",
                "reasons": list(phase1.get("reasons") or []),
                "metrics": {
                    "runs": int(phase1.get("runs") or 0),
                    "healthy_runs": int(phase1.get("healthy_runs") or 0),
                    "snapshots": int(phase1.get("snapshots") or 0),
                    "distinct_snapshot_buckets": int(phase1.get("distinct_snapshot_buckets") or 0),
                    "mean_data_quality": float(phase1.get("mean_data_quality") or 0.0),
                    "run_success_ratio": float(phase1.get("run_success_ratio") or 0.0),
                },
            },
            "2": {
                "decision": str(phase2_gate.get("decision") or "REFUSE"),
                "next_review": "phase3",
                "reasons": list(phase2_gate.get("reasons") or []),
                "metrics": {
                    "forecasts": int(phase2_readiness.get("forecasts") or 0),
                    "settled_non_abstain_forecasts": int(phase2_readiness.get("settled_non_abstain_forecasts") or 0),
                    "distinct_research_snapshots": int(phase2_readiness.get("distinct_research_snapshots") or 0),
                    "positive_slice_posteriors": len(_positive_posteriors(p2_posteriors)),
                    "slice_posteriors": len(p2_posteriors),
                    "champion_research_model": phase2_score.get("champion_research_model_by_mean_net_bps"),
                },
            },
            "3": {
                "decision": str(phase3_gate.get("decision") or "REFUSE"),
                "next_review": "phase4",
                "reasons": list(phase3_gate.get("reasons") or []),
                "metrics": {
                    "completed_normal_simulations": int(phase3_readiness.get("completed_normal_simulations") or 0),
                    "positive_normal_slice_posteriors": len(_positive_posteriors(p3_posteriors, normal_only=True)),
                    "slice_posteriors": len(p3_posteriors),
                    "incidents": int(phase3_score.get("incident_count") or 0),
                    "symbol_halts": int(phase3_score.get("symbol_halts") or 0),
                },
            },
            "4": {
                "decision": "ALLOW" if phase4_readiness.get("ready_for_phase5_review") else "REFUSE",
                "next_review": "phase5",
                "reasons": list(phase4_readiness.get("reasons") or []),
                "metrics": {
                    "latest_run_id": phase4_report.get("run_id") if isinstance(phase4_report, dict) else None,
                    "candidate_count": int((phase4_report or {}).get("candidate_count") or 0),
                    "champion": phase4_champion,
                    "pbo_estimate": ((phase4_report or {}).get("pbo") or {}).get("pbo_estimate"),
                },
            },
            "5": {
                "decision": "ALLOW" if phase5_readiness.get("ready_for_phase6_review") else "REFUSE",
                "next_review": "phase6_rapid_paper_canary" if phase6_rapid_enabled else "phase6_human_review",
                "reasons": list(phase5_readiness.get("reasons") or []),
                "metrics": {
                    "settled_shadow_intents": int(phase5_score.get("settled") or 0),
                    "distinct_time_buckets": int(phase5_score.get("distinct_time_buckets") or 0),
                    "mean_fill_ratio": phase5_score.get("mean_fill_ratio"),
                    "mean_net_bps": phase5_score.get("mean_net_bps"),
                    "cost_mae_bps": phase5_score.get("cost_mae_bps"),
                    "active_freeze": bool(phase5_readiness.get("freeze")),
                },
            },
            "6": {
                "decision": "ALLOW" if phase6_rapid_enabled and int(phase6_score.get("paper_canary_intents") or 0) > 0 else "REFUSE",
                "next_review": "same_slice_paper_settlement",
                "reasons": [] if phase6_rapid_enabled and int(phase6_score.get("paper_canary_intents") or 0) > 0 else ["no_phase6_paper_canary_intent"],
                "metrics": {
                    "mode": "rapid_paper_canary" if phase6_rapid_enabled else "tiny_live_canary",
                    "paper_canary_intents": int(phase6_score.get("paper_canary_intents") or 0),
                    "paper_canary_open": int(phase6_score.get("paper_canary_open") or 0),
                    "paper_canary_settled": int(phase6_score.get("paper_canary_settled") or 0),
                    "paper_canary_wins": int(phase6_score.get("paper_canary_wins") or 0),
                    "paper_canary_losses": int(phase6_score.get("paper_canary_losses") or 0),
                    "paper_canary_mean_net_bps": phase6_score.get("paper_canary_mean_net_bps"),
                    "latest_settlement": phase6_settlements[0] if phase6_settlements else None,
                    "live_orders_submitted": int(phase6_score.get("live_orders_submitted") or 0),
                },
            },
        },
    }
    digest_payload = json.dumps(report, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    report["truth_digest"] = f"sha256:{hashlib.sha256(digest_payload).hexdigest()}"
    return report


def format_current_truth(report: dict[str, Any]) -> str:
    overall = report.get("overall") or {}
    safety = report.get("safety") or {}
    lines = [
        f"CURRENT TRUTH: {overall.get('state', 'UNKNOWN')}",
        f"Authority: {overall.get('authority', 'RESEARCH_ONLY')} | Live execution authorized: NO",
        f"Profit claim: {overall.get('profit_claim', 'NOT_PROVEN')}",
        str(overall.get("plain_language") or ""),
        f"Safety: {safety.get('status', 'UNKNOWN')}",
    ]
    for phase in range(1, 7):
        payload = (report.get("phases") or {}).get(str(phase), {})
        reasons = payload.get("reasons") or []
        reason_text = "; ".join(str(item).replace("_", " ") for item in reasons[:4]) or "all predicates passed"
        lines.append(f"Phase {phase}: {payload.get('decision', 'REFUSE')} | {reason_text}")
    lines.append(f"Truth digest: {report.get('truth_digest', 'unavailable')}")
    return "\n".join(lines)
