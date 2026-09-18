import sqlite3
import json
import logging
import time
import os
import threading
import shutil
import hashlib
import math
from typing import Any, Dict, Optional
from datetime import datetime

from agents.commons_authority import build_authority_boundary, validate_artifact_contract

_PHASE3_REGIME_FALLBACK = "unknown"
_DB_QUICK_CHECK_MAX_BYTES = 512 * 1024 * 1024


def _model_family(model_id: Any) -> str:
    raw = str(model_id or "unknown")
    if raw.startswith("baseline_"):
        return "baseline"
    if raw.startswith("adapter_freqtrade"):
        return "freqtrade"
    if raw.startswith("adapter_jesse"):
        return "jesse"
    if raw.startswith("candidate_freqai"):
        return "freqai"
    if raw.startswith("candidate_finrl"):
        return "finrl"
    if raw.startswith("candidate_macrohft"):
        return "macrohft"
    if raw.startswith("candidate_webcrypto"):
        return "webcrypto"
    if raw.startswith("candidate_cex_multi_horizon_oracle"):
        return "cex_market_oracle"
    if raw.startswith("candidate_"):
        return "candidate_other"
    if raw.startswith("adapter_"):
        return "adapter_other"
    return "phoenix_native"


def _prefix_upper_bound(prefix: str) -> str:
    """Return the exclusive upper bound for a lexicographic prefix scan."""
    if not prefix:
        return ""
    chars = list(prefix)
    chars[-1] = chr(ord(chars[-1]) + 1)
    return "".join(chars)


def _distinct_bucket_sql(ts_expr: str, bucket_hours: int) -> str:
    hours = max(1, int(bucket_hours or 1))
    if hours == 24:
        return f"COUNT(DISTINCT date({ts_expr}, 'unixepoch'))"
    return f"COUNT(DISTINCT CAST(({ts_expr}) / {float(hours * 3600):.1f} AS INTEGER))"


def _shrunk_mean(
    sample_mean: Optional[float],
    sample_count: int,
    parent_mean: Optional[float],
    prior_strength: float,
) -> Optional[float]:
    if sample_mean is None:
        return parent_mean
    n = max(0, int(sample_count or 0))
    strength = max(0.0, float(prior_strength or 0.0))
    if parent_mean is None or strength <= 0.0:
        return float(sample_mean)
    return ((float(sample_mean) * n) + (float(parent_mean) * strength)) / (n + strength)


def _drift_state(
    long_run_mean: Optional[float],
    recent_mean: Optional[float],
    *,
    recent_samples: int,
    drift_threshold_bps: float,
    min_recent_samples: int,
) -> Dict[str, Any]:
    divergence = None
    if long_run_mean is not None and recent_mean is not None:
        divergence = float(recent_mean) - float(long_run_mean)
    drifted = bool(
        divergence is not None
        and int(recent_samples or 0) >= int(min_recent_samples)
        and float(divergence) <= -abs(float(drift_threshold_bps))
    )
    return {
        "long_run_mean_net_bps": long_run_mean,
        "recent_mean_net_bps": recent_mean,
        "recent_samples": int(recent_samples or 0),
        "divergence_bps": round(float(divergence), 6) if divergence is not None else None,
        "drift_threshold_bps": float(drift_threshold_bps),
        "min_recent_samples": int(min_recent_samples),
        "drifted": drifted,
    }


def _expected_log_growth_for_fraction(
    fraction: float,
    *,
    win_probability: float,
    win_return: float,
    loss_return: float,
) -> float:
    f = max(0.0, min(1.0, float(fraction or 0.0)))
    p = max(0.0, min(1.0, float(win_probability or 0.0)))
    win = max(-0.95, float(win_return or 0.0))
    loss = max(0.0, float(loss_return or 0.0))
    up = max(1e-9, 1.0 + (f * win))
    down = max(1e-9, 1.0 - (f * loss))
    return (p * math.log(up)) + ((1.0 - p) * math.log(down))


def _summarize_distribution(samples: list[float]) -> Dict[str, Any]:
    values = sorted(float(sample) for sample in samples if sample is not None)
    if not values:
        return {
            "sample_count": 0,
            "mean_bps": None,
            "median_bps": None,
            "p25_bps": None,
            "p75_bps": None,
            "p10_bps": None,
            "p90_bps": None,
            "min_bps": None,
            "max_bps": None,
        }

    def _pick(frac: float) -> float:
        idx = max(0, min(len(values) - 1, int(round((len(values) - 1) * frac))))
        return values[idx]

    return {
        "sample_count": len(values),
        "mean_bps": round(sum(values) / len(values), 6),
        "median_bps": round(_pick(0.50), 6),
        "p25_bps": round(_pick(0.25), 6),
        "p75_bps": round(_pick(0.75), 6),
        "p10_bps": round(_pick(0.10), 6),
        "p90_bps": round(_pick(0.90), 6),
        "min_bps": round(values[0], 6),
        "max_bps": round(values[-1], 6),
    }


def _phase3_growth_allocator(
    candidates: list[Dict[str, Any]],
    *,
    reserve_cash_pct: float,
    max_candidate_fraction: float,
    min_expected_growth_bps: float,
) -> Dict[str, Any]:
    def _provenance_tokens(candidate: Dict[str, Any]) -> Dict[str, str]:
        return {
            "model_family": _model_family(candidate.get("model_id")),
            "hypothesis": str(candidate.get("hypothesis") or "unknown"),
            "research_route": str(candidate.get("research_route") or "unknown"),
            "regime_hint": str(candidate.get("regime_hint") or "unknown"),
            "cohort_bucket": str(candidate.get("cohort_bucket") or "unknown"),
            "symbol_class": str(candidate.get("symbol_class") or "unknown"),
            "symbol": str(candidate.get("symbol") or "unknown"),
        }

    reserve = max(0.0, min(0.99, float(reserve_cash_pct or 0.0)))
    investable = max(0.0, 1.0 - reserve)
    per_candidate_cap = max(0.0, min(1.0, float(max_candidate_fraction or 0.0)))
    reference_equity_usd = 100.0
    depth_participation_cap = 0.01
    sleeves: list[Dict[str, Any]] = []
    positive_candidates = 0
    rejected_for_cash = 0
    total_requested_fraction = 0.0
    total_allocated_fraction = 0.0
    total_expected_log_growth = 0.0
    provenance_counts: Dict[str, Dict[str, int]] = {
        "model_family": {},
        "hypothesis": {},
        "research_route": {},
        "regime_hint": {},
        "cohort_bucket": {},
        "symbol_class": {},
        "symbol": {},
    }

    for candidate in candidates:
        for key, value in _provenance_tokens(candidate).items():
            bucket = provenance_counts.setdefault(key, {})
            bucket[value] = bucket.get(value, 0) + 1

    for candidate in candidates:
        provenance = _provenance_tokens(candidate)
        expected_net_bps = float(candidate.get("expected_net_bps") or 0.0)
        shrunk_slice_bps = float(candidate.get("shrunk_slice_historical_mean_net_bps") or 0.0)
        shrunk_recent_slice_bps = float(candidate.get("shrunk_recent_slice_historical_mean_net_bps") or 0.0)
        shrunk_regime_bps = float(candidate.get("shrunk_regime_historical_mean_net_bps") or 0.0)
        shrunk_frontier_bps = float(candidate.get("shrunk_frontier_regime_mean_net_bps") or 0.0)
        cost_bps = max(0.01, float(candidate.get("expected_cost_bps") or 0.0))
        cost_survival_ratio = max(0.0, float(candidate.get("cost_survival_ratio") or 0.0))
        failure_penalty_bps = max(0.0, float(candidate.get("failure_feedback_penalty_bps_equiv") or 0.0))
        depth_usd = max(
            0.0,
            float(
                candidate.get("depth_usd_25bps")
                or ((candidate.get("entry_observation") or {}).get("depth_usd_25bps") if isinstance(candidate.get("entry_observation"), dict) else 0.0)
                or 0.0
            ),
        )
        historical_samples = max(0, int(candidate.get("historical_samples") or 0))
        regime_samples = max(0, int(candidate.get("regime_historical_samples") or 0))
        slice_samples = max(0, int(candidate.get("slice_historical_samples") or 0))
        win_probability = max(0.0, min(1.0, float(candidate.get("probability_positive_net") or 0.0)))

        conservative_edge_bps = min(
            expected_net_bps,
            shrunk_slice_bps if slice_samples else expected_net_bps,
            shrunk_recent_slice_bps if int(candidate.get("recent_slice_historical_samples") or 0) else shrunk_slice_bps,
            shrunk_regime_bps if regime_samples else expected_net_bps,
            shrunk_frontier_bps if int(candidate.get("frontier_regime_samples") or 0) else expected_net_bps,
        ) - failure_penalty_bps
        evidence_strength = min(1.0, (historical_samples / 24.0) + (regime_samples / 16.0) + (slice_samples / 12.0))
        uncertainty_haircut = max(0.15, min(1.0, evidence_strength)) * max(
            0.25,
            min(1.25, win_probability + (0.20 * min(1.0, cost_survival_ratio / 2.0))),
        )
        overlap_components = {
            "model_family": max(0, provenance_counts["model_family"].get(provenance["model_family"], 0) - 1) * 0.18,
            "hypothesis": max(0, provenance_counts["hypothesis"].get(provenance["hypothesis"], 0) - 1) * 0.16,
            "research_route": max(0, provenance_counts["research_route"].get(provenance["research_route"], 0) - 1) * 0.10,
            "regime_hint": max(0, provenance_counts["regime_hint"].get(provenance["regime_hint"], 0) - 1) * 0.08,
            "cohort_bucket": max(0, provenance_counts["cohort_bucket"].get(provenance["cohort_bucket"], 0) - 1) * 0.06,
            "symbol_class": max(0, provenance_counts["symbol_class"].get(provenance["symbol_class"], 0) - 1) * 0.08,
            "symbol": max(0, provenance_counts["symbol"].get(provenance["symbol"], 0) - 1) * 0.20,
        }
        overlap_penalty = min(0.80, sum(overlap_components.values()))
        diversification_multiplier = max(0.20, 1.0 - overlap_penalty)
        robust_edge_bps = conservative_edge_bps * uncertainty_haircut * diversification_multiplier
        capacity_curve = []
        marginal_limit_fraction = 0.0
        effective_fraction_cap = 0.0
        if depth_usd > 0.0:
            depth_cap_fraction = min(1.0, (depth_usd * depth_participation_cap) / max(reference_equity_usd, 1.0))
        else:
            depth_cap_fraction = 0.0
        effective_fraction_cap = min(investable, per_candidate_cap, depth_cap_fraction if depth_cap_fraction > 0.0 else per_candidate_cap)
        if effective_fraction_cap > 0.0:
            ladder = [0.20, 0.40, 0.60, 0.80, 1.00]
            for level in ladder:
                fraction = effective_fraction_cap * level
                notional_usd = reference_equity_usd * fraction
                participation = notional_usd / max(depth_usd, notional_usd, 0.000001) if depth_usd > 0.0 else 1.0
                impact_bps = min(75.0, 25.0 * math.sqrt(max(0.0, participation)))
                scaled_cost_bps = cost_bps + impact_bps
                scaled_net_bps = robust_edge_bps - impact_bps
                curve_point = {
                    "fraction_total_capital": round(fraction, 6),
                    "notional_usd": round(notional_usd, 6),
                    "participation_rate": round(participation, 8),
                    "incremental_impact_bps": round(impact_bps, 6),
                    "scaled_cost_bps": round(scaled_cost_bps, 6),
                    "scaled_net_bps": round(scaled_net_bps, 6),
                }
                capacity_curve.append(curve_point)
                if scaled_net_bps >= float(min_expected_growth_bps):
                    marginal_limit_fraction = fraction
            if marginal_limit_fraction > 0.0:
                effective_fraction_cap = min(effective_fraction_cap, marginal_limit_fraction)
        win_return = max(0.0, robust_edge_bps / 10_000.0)
        loss_return = max(cost_bps / 10_000.0, abs(min(0.0, conservative_edge_bps)) / 10_000.0)

        best_fraction = 0.0
        best_log_growth = 0.0
        best_fraction_of_investable = 0.0
        best_growth_bps = 0.0
        if investable > 0.0 and effective_fraction_cap > 0.0 and robust_edge_bps >= float(min_expected_growth_bps):
            positive_candidates += 1
            max_fraction = effective_fraction_cap
            for step in range(1, 21):
                fraction = max_fraction * (step / 20.0)
                growth = _expected_log_growth_for_fraction(
                    fraction,
                    win_probability=win_probability,
                    win_return=win_return,
                    loss_return=loss_return,
                )
                if growth > best_log_growth:
                    best_log_growth = growth
                    best_fraction = fraction
            best_fraction_of_investable = (best_fraction / investable) if investable > 0 else 0.0
            best_growth_bps = best_log_growth * 10_000.0
        else:
            rejected_for_cash += 1

        information_value = max(0.0, robust_edge_bps) * (0.40 + evidence_strength) + max(0.0, 1.0 - evidence_strength) * 8.0
        total_requested_fraction += best_fraction
        sleeves.append({
            "forecast_id": candidate.get("forecast_id"),
            "symbol": candidate.get("symbol"),
            "model_id": candidate.get("model_id"),
            "hypothesis": candidate.get("hypothesis"),
            "regime_hint": candidate.get("regime_hint"),
            "expected_net_bps": round(expected_net_bps, 6),
            "robust_edge_bps": round(robust_edge_bps, 6),
            "conservative_edge_bps": round(conservative_edge_bps, 6),
            "cost_bps": round(cost_bps, 6),
            "depth_usd_25bps": round(depth_usd, 6),
            "win_probability": round(win_probability, 6),
            "evidence_strength": round(evidence_strength, 6),
            "information_value": round(information_value, 6),
            "research_priority": (
                "allocate_profit_research"
                if best_fraction > 0.0 and best_growth_bps > 0.0
                else "explore_uncertain_slice"
                if information_value > 6.0 and evidence_strength < 0.75
                else "deprioritize"
            ),
            "uncertainty_haircut": round(uncertainty_haircut, 6),
            "provenance": provenance,
            "provenance_overlap_penalty": round(overlap_penalty, 6),
            "diversification_multiplier": round(diversification_multiplier, 6),
            "provenance_overlap_components": {key: round(value, 6) for key, value in overlap_components.items()},
            "capacity_curve": capacity_curve,
            "capacity_curve_points": len(capacity_curve),
            "capacity_fraction_cap": round(effective_fraction_cap, 6),
            "marginal_size_limit_fraction": round(marginal_limit_fraction, 6),
            "depth_participation_cap": round(depth_participation_cap, 6),
            "cash_competes": bool(best_fraction <= 0.0 or best_growth_bps <= 0.0),
            "recommended_fraction_total_capital": round(best_fraction, 6),
            "recommended_fraction_of_investable": round(best_fraction_of_investable, 6),
            "expected_log_growth_bps": round(best_growth_bps, 6),
            "loss_assumption_pct": round(loss_return, 6),
            "sample_support": {
                "historical_samples": historical_samples,
                "regime_samples": regime_samples,
                "slice_samples": slice_samples,
            },
        })

    scale = min(1.0, investable / total_requested_fraction) if total_requested_fraction > 0 else 0.0
    for sleeve in sleeves:
        scaled_fraction = float(sleeve.get("recommended_fraction_total_capital") or 0.0) * scale
        sleeve["recommended_fraction_total_capital"] = round(scaled_fraction, 6)
        sleeve["recommended_fraction_of_investable"] = round((scaled_fraction / investable), 6) if investable > 0 else 0.0
        sleeve["cash_competes"] = bool(
            scaled_fraction <= 0.0 or float(sleeve.get("expected_log_growth_bps") or 0.0) <= 0.0
        )
        total_allocated_fraction += scaled_fraction
        if scaled_fraction > 0.0 and float(sleeve.get("expected_log_growth_bps") or 0.0) > 0.0:
            total_expected_log_growth += (float(sleeve.get("expected_log_growth_bps") or 0.0) / 10_000.0)

    sleeves.sort(
        key=lambda item: (
            float(item.get("recommended_fraction_total_capital") or 0.0),
            float(item.get("information_value") or 0.0),
            float(item.get("expected_log_growth_bps") or 0.0),
            float(item.get("robust_edge_bps") or 0.0),
        ),
        reverse=True,
    )
    return {
        "schema": "phase3_growth_allocation_v1",
        "reserve_cash_pct": round(reserve, 6),
        "investable_cash_pct": round(investable, 6),
        "max_candidate_fraction_total_capital": round(per_candidate_cap, 6),
        "min_expected_growth_bps": round(float(min_expected_growth_bps or 0.0), 6),
        "candidates_considered": len(candidates),
        "positive_growth_candidates": positive_candidates,
        "candidates_rejected_for_cash": rejected_for_cash,
        "allocated_candidates": sum(
            1 for sleeve in sleeves if float(sleeve.get("recommended_fraction_total_capital") or 0.0) > 0.0
        ),
        "allocated_total_capital_pct": round(total_allocated_fraction, 6),
        "cash_retain_pct": round(max(reserve, 1.0 - total_allocated_fraction), 6),
        "portfolio_expected_log_growth_bps": round(total_expected_log_growth * 10_000.0, 6),
        "provenance_crowding": provenance_counts,
        "sleeves": sleeves[:12],
    }


class DataStoreAgent:
    """
    Data Store Agent: SQLite-backed authoritative store for intents, orders, fills,
    balances, kill-switch transitions, and config versions. It accepts buzz events
    via `handle_event` and responds to `buzz.store.query` by publishing
    `buzz.store.result` via the coordinator when available.
    """

    def __init__(self, db_path: str = "swarm_data.db", coordinator: Optional[Any] = None):
        self.db_path = db_path
        self.conn = None
        self.coordinator = coordinator
        self._lock = threading.RLock()
        self._recovering = False
        self._last_phase3_candidate_meta: Dict[str, Any] = {}
        self._connect()
        self._create_tables()

    def _connect(self, check_integrity: bool = True):
        """Establish SQLite connection."""
        try:
            if os.getenv("HIVENANCE_SKIP_DB_QUICK_CHECK", "0") == "1":
                check_integrity = False
            elif check_integrity and self.db_path not in {":memory:", ""}:
                try:
                    db_size = os.path.getsize(self.db_path)
                except OSError:
                    db_size = 0
                if db_size >= _DB_QUICK_CHECK_MAX_BYTES:
                    logging.info(
                        "Skipping SQLite quick_check for large database %s (%.2f GiB)",
                        self.db_path,
                        db_size / float(1024 ** 3),
                    )
                    check_integrity = False
            self.conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
            try:
                self.conn.execute("PRAGMA journal_mode=WAL")
                self.conn.execute("PRAGMA synchronous=NORMAL")
                self.conn.execute("PRAGMA busy_timeout=30000")
            except Exception:
                pass
            if check_integrity and not self._check_integrity():
                self._recover_db("quick_check failed")
                return
            logging.info(f"Data Store Agent connected to {self.db_path}")
        except Exception as e:
            logging.error(f"Failed to connect to database: {e}")
            self.conn = None

    def open_dashboard_reader(self) -> "DataStoreAgent":
        """Create an isolated query-only view for a single UI projection."""
        if not self.db_path or self.db_path == ":memory:":
            return self
        view = object.__new__(type(self))
        view.__dict__ = dict(self.__dict__)
        db_uri = f"file:{os.path.abspath(self.db_path)}?mode=ro"
        view.conn = sqlite3.connect(db_uri, uri=True, timeout=2.0, check_same_thread=False)
        view.conn.execute("PRAGMA query_only=ON")
        view.conn.execute("PRAGMA busy_timeout=2000")
        view._lock = threading.RLock()
        view._dashboard_reader = True
        return view

    def close_dashboard_reader(self) -> None:
        if getattr(self, "_dashboard_reader", False) and self.conn:
            self.conn.close()
            self.conn = None

    def _check_integrity(self) -> bool:
        if not self.conn:
            return False
        try:
            cur = self.conn.cursor()
            cur.execute("PRAGMA quick_check")
            row = cur.fetchone()
            return bool(row and row[0] == "ok")
        except Exception:
            return False

    def _create_tables(self):
        """Create necessary tables."""
        if not self.conn:
            return
        try:
            c = self.conn.cursor()
            # raw events (optional)
            c.execute("""
            CREATE TABLE IF NOT EXISTS raw_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                type TEXT,
                source TEXT,
                payload TEXT
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS event_envelopes (
                event_id TEXT PRIMARY KEY,
                ts REAL,
                type TEXT,
                source TEXT,
                severity TEXT,
                correlation_id TEXT,
                seq INTEGER,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_event_envelopes_type_ts ON event_envelopes(type, ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_event_envelopes_correlation ON event_envelopes(correlation_id)")
            # intents
            c.execute("""
            CREATE TABLE IF NOT EXISTS intents (
                intent_id TEXT PRIMARY KEY,
                symbol TEXT,
                action TEXT,
                origin_strategy TEXT,
                created_ts REAL,
                state TEXT,
                final_outcome TEXT,
                final_reason TEXT,
                position_size_pct REAL,
                qty REAL,
                order_type TEXT
            )
            """)
            # orders
            c.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                client_order_id TEXT PRIMARY KEY,
                intent_id TEXT,
                venue TEXT,
                symbol TEXT,
                side TEXT,
                order_type TEXT,
                order_id TEXT,
                status TEXT,
                placed_ts REAL,
                final_ts REAL
            )
            """)
            # fills
            c.execute("""
            CREATE TABLE IF NOT EXISTS fills (
                fill_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT,
                client_order_id TEXT,
                filled_qty REAL,
                avg_price REAL,
                fee REAL,
                slippage_pct REAL,
                ts REAL
            )
            """)
            # balances
            c.execute("""
            CREATE TABLE IF NOT EXISTS balances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                venue TEXT,
                eth_free REAL,
                eth_locked REAL,
                usdt_free REAL,
                usdt_locked REAL,
                equity_usd_est REAL
            )
            """)
            # killswitch transitions
            c.execute("""
            CREATE TABLE IF NOT EXISTS killswitch (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                state TEXT,
                reason TEXT,
                metrics_json TEXT
            )
            """)
            # swarmguard decisions
            c.execute("""
            CREATE TABLE IF NOT EXISTS swarmguard (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                decision TEXT,
                reason TEXT,
                position_size REAL,
                strategy TEXT,
                symbol TEXT,
                weight REAL,
                consensus_mult REAL
            )
            """)
            # config versions
            c.execute("""
            CREATE TABLE IF NOT EXISTS config_versions (
                version_id TEXT PRIMARY KEY,
                ts REAL,
                config_json TEXT,
                changed_by TEXT
            )
            """)
            # security audit
            c.execute("""
            CREATE TABLE IF NOT EXISTS security_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                severity TEXT,
                event_type TEXT,
                details TEXT,
                recommended_action TEXT
            )
            """)
            # trades table (used by store_trade and UI)
            c.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                symbol TEXT,
                side TEXT,
                quantity REAL,
                price REAL,
                status TEXT,
                intent_id TEXT,
                order_id TEXT,
                venue TEXT
            )
            """)
            # market data snapshots
            c.execute("""
            CREATE TABLE IF NOT EXISTS market_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                symbol TEXT,
                price REAL,
                volume REAL,
                source TEXT
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS market_bee_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                symbol TEXT,
                score REAL,
                allowed INTEGER,
                reason TEXT,
                price_usd REAL,
                liquidity_usd REAL,
                volume_24h_usd REAL,
                h1_change_pct REAL,
                h24_change_pct REAL,
                roundtrip_ratio REAL,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_market_bee_symbol_ts ON market_bee_snapshots(symbol, ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS orderbook_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                symbol TEXT,
                venue TEXT,
                bid REAL,
                ask REAL,
                spread_pct REAL,
                mid_price REAL,
                top_of_book_depth_usd REAL,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_orderbook_symbol_ts ON orderbook_snapshots(symbol, ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS observation_runs (
                run_id TEXT PRIMARY KEY,
                started_ts REAL,
                completed_ts REAL,
                venue TEXT,
                status TEXT,
                symbols_attempted INTEGER,
                symbols_successful INTEGER,
                symbols_eligible INTEGER,
                mean_data_quality REAL,
                error_count INTEGER,
                dataset_hash TEXT,
                execution_wired INTEGER DEFAULT 0,
                orders_submitted INTEGER DEFAULT 0,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_observation_runs_completed ON observation_runs(completed_ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS observation_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                ts REAL,
                venue TEXT,
                symbol TEXT,
                price REAL,
                quote_volume_24h REAL,
                spread_bps REAL,
                depth_usd_25bps REAL,
                volatility_expansion REAL,
                volume_zscore REAL,
                book_imbalance REAL,
                data_quality REAL,
                observation_eligible INTEGER,
                execution_eligible INTEGER DEFAULT 0,
                rejection_reasons TEXT,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_observation_symbol_ts ON observation_snapshots(symbol, ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_observation_ts_desc ON observation_snapshots(ts DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_observation_run ON observation_snapshots(run_id)")
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_observation_run_symbol ON observation_snapshots(run_id, symbol)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS hypothesis_runs (
                run_id TEXT PRIMARY KEY,
                observation_run_id TEXT,
                started_ts REAL,
                completed_ts REAL,
                venue TEXT,
                status TEXT,
                symbols_evaluated INTEGER,
                forecasts_total INTEGER,
                non_abstain_forecasts INTEGER,
                abstentions INTEGER,
                dataset_hash TEXT,
                execution_wired INTEGER DEFAULT 0,
                orders_submitted INTEGER DEFAULT 0,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_runs_completed ON hypothesis_runs(completed_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_runs_status_completed ON hypothesis_runs(status, completed_ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS hypothesis_forecasts (
                forecast_id TEXT PRIMARY KEY,
                run_id TEXT,
                observation_run_id TEXT,
                ts REAL,
                target_ts REAL,
                venue TEXT,
                symbol TEXT,
                model_id TEXT,
                hypothesis TEXT,
                horizon_seconds INTEGER,
                direction TEXT,
                entry_price REAL,
                probability_positive_net REAL,
                expected_move_bps REAL,
                expected_cost_bps REAL,
                expected_net_bps REAL,
                raw_score REAL,
                abstain INTEGER,
                reason TEXT,
                settled INTEGER DEFAULT 0,
                execution_eligible INTEGER DEFAULT 0,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_forecast_model_ts ON hypothesis_forecasts(model_id, ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_forecast_symbol_target ON hypothesis_forecasts(symbol, target_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_forecast_ts_desc ON hypothesis_forecasts(ts DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_forecast_run_ts ON hypothesis_forecasts(run_id, ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_forecast_settled_target ON hypothesis_forecasts(settled, target_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_forecast_settled_abstain_ts ON hypothesis_forecasts(settled, abstain, ts DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_forecast_settled_model_symbol_ts ON hypothesis_forecasts(settled, abstain, model_id, symbol, ts DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_forecast_settle_scan ON hypothesis_forecasts(settled, target_ts, model_id, symbol, forecast_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_forecast_readiness ON hypothesis_forecasts(settled, abstain, model_id, hypothesis)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_forecast_execution_eligible ON hypothesis_forecasts(execution_eligible)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_forecast_model_settled_target ON hypothesis_forecasts(model_id, settled, abstain, target_ts, symbol, horizon_seconds, direction)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_forecast_settled_hypothesis_ts ON hypothesis_forecasts(settled, abstain, hypothesis, ts DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_forecast_slice_ts ON hypothesis_forecasts(model_id, hypothesis, horizon_seconds, direction, ts DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_forecast_symbol_slice_ts ON hypothesis_forecasts(symbol, model_id, hypothesis, horizon_seconds, direction, ts DESC)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS hypothesis_outcomes (
                forecast_id TEXT PRIMARY KEY,
                settled_ts REAL,
                exit_price REAL,
                gross_return_bps REAL,
                directional_return_bps REAL,
                net_return_bps REAL,
                positive_net INTEGER,
                brier_score REAL,
                absolute_error_bps REAL,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_outcomes_settled ON hypothesis_outcomes(settled_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_outcomes_positive_settled ON hypothesis_outcomes(positive_net, settled_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_outcomes_forecast ON hypothesis_outcomes(forecast_id)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS phase_scorecard_snapshots (
                snapshot_key TEXT PRIMARY KEY,
                phase INTEGER,
                mode TEXT,
                created_ts REAL,
                high_watermark_forecast_rowid INTEGER,
                high_watermark_outcome_rowid INTEGER,
                high_watermark_simulated_order_rowid INTEGER,
                source_limit INTEGER,
                ttl_sec REAL,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase_scorecard_snapshots_phase_created ON phase_scorecard_snapshots(phase, created_ts DESC)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS research_reuse_receipts (
                receipt_id TEXT PRIMARY KEY,
                created_ts REAL,
                decision TEXT,
                model_id TEXT,
                symbol TEXT,
                regime_hint TEXT,
                horizon_seconds INTEGER,
                config_hash TEXT,
                sample_count INTEGER,
                mean_realized_net_bps REAL,
                win_rate REAL,
                latest_settled_ts REAL,
                reason TEXT,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_research_reuse_created ON research_reuse_receipts(created_ts DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_research_reuse_lookup ON research_reuse_receipts(model_id, symbol, regime_hint, horizon_seconds, created_ts DESC)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS commons_pool_work_tickets (
                ticket_id TEXT PRIMARY KEY,
                created_ts REAL,
                expires_ts REAL,
                pool_type TEXT,
                task_class TEXT,
                phase_scope INTEGER,
                authority TEXT,
                challenge_nonce TEXT,
                world_state_digest TEXT,
                input_root TEXT,
                feature_schema_digest TEXT,
                code_digest TEXT,
                config_digest TEXT,
                status TEXT,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_commons_tickets_created ON commons_pool_work_tickets(created_ts DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_commons_tickets_pool_phase ON commons_pool_work_tickets(pool_type, phase_scope, created_ts DESC)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS commons_pool_claim_leases (
                lease_id TEXT PRIMARY KEY,
                ticket_id TEXT,
                worker_id TEXT,
                issued_ts REAL,
                expires_ts REAL,
                worker_advertisement_digest TEXT,
                challenge_nonce TEXT,
                authority TEXT,
                max_result_bytes INTEGER,
                status TEXT,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_commons_leases_ticket ON commons_pool_claim_leases(ticket_id, issued_ts DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_commons_leases_worker ON commons_pool_claim_leases(worker_id, issued_ts DESC)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS commons_inference_receipts (
                receipt_id TEXT PRIMARY KEY,
                ticket_id TEXT,
                lease_id TEXT,
                worker_id TEXT,
                created_ts REAL,
                pool_type TEXT,
                task_class TEXT,
                phase_scope INTEGER,
                challenge_nonce TEXT,
                input_root TEXT,
                output_root TEXT,
                world_state_digest TEXT,
                feature_schema_digest TEXT,
                code_digest TEXT,
                config_digest TEXT,
                container_digest TEXT,
                result_kind TEXT,
                status TEXT,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_commons_inference_created ON commons_inference_receipts(created_ts DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_commons_inference_phase_task ON commons_inference_receipts(phase_scope, task_class, created_ts DESC)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS commons_verifier_receipts (
                receipt_id TEXT PRIMARY KEY,
                ticket_id TEXT,
                lease_id TEXT,
                worker_id TEXT,
                created_ts REAL,
                pool_type TEXT,
                task_class TEXT,
                phase_scope INTEGER,
                challenge_nonce TEXT,
                subject_digest TEXT,
                world_state_digest TEXT,
                code_digest TEXT,
                config_digest TEXT,
                container_digest TEXT,
                verification_verdict TEXT,
                status TEXT,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_commons_verifier_created ON commons_verifier_receipts(created_ts DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_commons_verifier_phase_task ON commons_verifier_receipts(phase_scope, task_class, created_ts DESC)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS commons_local_adoption_receipts (
                receipt_id TEXT PRIMARY KEY,
                source_receipt_id TEXT,
                source_family TEXT,
                pool_type TEXT,
                phase_scope INTEGER,
                adopted_ts REAL,
                adopted_by TEXT,
                local_reproduction_required INTEGER,
                local_reproduction_verdict TEXT,
                adoption_decision TEXT,
                authority_ceiling TEXT,
                status TEXT,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_commons_adoption_adopted ON commons_local_adoption_receipts(adopted_ts DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_commons_adoption_source ON commons_local_adoption_receipts(source_receipt_id, adopted_ts DESC)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS crystal_registry (
                crystal_id TEXT PRIMARY KEY,
                created_ts REAL,
                updated_ts REAL,
                crystal_family TEXT,
                artifact_class TEXT,
                authority TEXT,
                verification_state TEXT,
                phase_scope INTEGER,
                scope_key TEXT,
                symbol TEXT,
                venue TEXT,
                regime_hint TEXT,
                hypothesis TEXT,
                world_state_id TEXT,
                applicability_hash TEXT,
                evidence_strength REAL,
                drift_status TEXT,
                expires_ts REAL,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_crystal_registry_family_updated ON crystal_registry(crystal_family, updated_ts DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_crystal_registry_scope ON crystal_registry(scope_key, updated_ts DESC)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS inference_rung_ledger (
                rung_id TEXT PRIMARY KEY,
                created_ts REAL,
                phase_scope INTEGER,
                run_id TEXT,
                forecast_id TEXT,
                simulation_id TEXT,
                symbol TEXT,
                venue TEXT,
                model_id TEXT,
                hypothesis TEXT,
                regime_hint TEXT,
                symbol_class TEXT,
                cohort_bucket TEXT,
                selected_rung TEXT,
                candidate_rungs TEXT,
                selected_priority REAL,
                expected_net_bps REAL,
                probability_positive_net REAL,
                cost_bps REAL,
                authority_ceiling TEXT,
                outcome_status TEXT,
                outcome_net_bps REAL,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_inference_rung_phase_created ON inference_rung_ledger(phase_scope, created_ts DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_inference_rung_forecast ON inference_rung_ledger(forecast_id, created_ts DESC)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS simulation_runs (
                run_id TEXT PRIMARY KEY,
                started_ts REAL,
                completed_ts REAL,
                status TEXT,
                forecasts_examined INTEGER,
                simulations_created INTEGER,
                simulations_skipped_existing INTEGER,
                completed INTEGER,
                rejected INTEGER,
                expired INTEGER,
                partial_fills INTEGER,
                unknown_incidents INTEGER,
                dataset_hash TEXT,
                execution_wired INTEGER DEFAULT 0,
                real_orders_submitted INTEGER DEFAULT 0,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_simulation_runs_completed ON simulation_runs(completed_ts)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS simulated_order_intents (
                intent_id TEXT PRIMARY KEY,
                simulation_id TEXT UNIQUE,
                forecast_id TEXT,
                model_id TEXT,
                venue TEXT,
                symbol TEXT,
                side TEXT,
                order_policy TEXT,
                scenario TEXT,
                quantity REAL,
                notional_usd REAL,
                reference_price REAL,
                limit_price REAL,
                risk_budget_usd REAL,
                stop_distance_bps REAL,
                horizon_seconds INTEGER,
                created_ts REAL,
                spot_executable INTEGER,
                live_eligible INTEGER DEFAULT 0,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_sim_intent_forecast ON simulated_order_intents(forecast_id)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS simulated_orders (
                simulation_id TEXT PRIMARY KEY,
                run_id TEXT,
                forecast_id TEXT,
                model_id TEXT,
                hypothesis TEXT,
                venue TEXT,
                symbol TEXT,
                direction TEXT,
                order_policy TEXT,
                scenario TEXT,
                fidelity TEXT,
                seed INTEGER,
                status TEXT,
                terminal_state TEXT,
                started_ts REAL,
                completed_ts REAL,
                fill_ratio REAL,
                quantity_requested REAL,
                quantity_filled REAL,
                notional_requested_usd REAL,
                entry_reference_price REAL,
                exit_reference_price REAL,
                entry_fill_price REAL,
                exit_fill_price REAL,
                gross_return_bps REAL,
                net_return_bps REAL,
                profitable_after_costs INTEGER,
                spot_executable INTEGER,
                execution_wired INTEGER DEFAULT 0,
                real_orders_submitted INTEGER DEFAULT 0,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_sim_orders_model_policy ON simulated_orders(model_id, order_policy, scenario)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_sim_orders_symbol_ts ON simulated_orders(symbol, completed_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_sim_orders_status_completed ON simulated_orders(status, completed_ts DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_sim_orders_forecast ON simulated_orders(forecast_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_sim_orders_model_symbol_completed ON simulated_orders(model_id, symbol, completed_ts DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_sim_orders_readiness ON simulated_orders(status, scenario, model_id, order_policy)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS simulated_order_events (
                simulation_id TEXT,
                sequence INTEGER,
                state TEXT,
                ts REAL,
                reason TEXT,
                payload TEXT,
                PRIMARY KEY(simulation_id, sequence)
            )
            ''')
            c.execute('''
            CREATE TABLE IF NOT EXISTS simulated_fills (
                fill_id TEXT PRIMARY KEY,
                simulation_id TEXT,
                leg TEXT,
                side TEXT,
                quantity REAL,
                price REAL,
                notional_usd REAL,
                fee_usd REAL,
                liquidity TEXT,
                ts REAL,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_sim_fills_simulation ON simulated_fills(simulation_id)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS simulated_positions (
                simulation_id TEXT PRIMARY KEY,
                symbol TEXT,
                direction TEXT,
                quantity REAL,
                entry_price REAL,
                exit_price REAL,
                status TEXT,
                gross_return_bps REAL,
                net_return_bps REAL,
                opened_ts REAL,
                closed_ts REAL,
                payload TEXT
            )
            ''')
            c.execute('''
            CREATE TABLE IF NOT EXISTS simulated_cost_attribution (
                simulation_id TEXT PRIMARY KEY,
                forecast_gross_bps REAL,
                market_gross_bps REAL,
                entry_spread_bps REAL,
                exit_spread_bps REAL,
                entry_impact_bps REAL,
                exit_impact_bps REAL,
                entry_latency_bps REAL,
                exit_latency_bps REAL,
                fee_bps REAL,
                missed_fill_opportunity_bps REAL,
                stop_slippage_bps REAL,
                total_cost_bps REAL,
                net_bps REAL,
                payload TEXT
            )
            ''')
            for column, ddl in (
                ("gross_signal_bps", "REAL"),
                ("entry_fee_bps", "REAL"),
                ("exit_fee_bps", "REAL"),
                ("maker_fee_bps", "REAL"),
                ("taker_fee_bps", "REAL"),
                ("failed_fill_cost_bps", "REAL"),
                ("chase_cost_bps", "REAL"),
                ("cost_schema_version", "TEXT"),
                ("fee_source", "TEXT"),
                ("fee_verified", "INTEGER DEFAULT 0"),
            ):
                try:
                    c.execute(f"ALTER TABLE simulated_cost_attribution ADD COLUMN {column} {ddl}")
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise
            c.execute('''
            CREATE TABLE IF NOT EXISTS simulation_incidents (
                incident_id TEXT PRIMARY KEY,
                simulation_id TEXT,
                incident_type TEXT,
                severity TEXT,
                symbol_halted INTEGER,
                automatic_recovery INTEGER,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_sim_incidents_simulation ON simulation_incidents(simulation_id)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase4_validation_runs (
                run_id TEXT PRIMARY KEY,
                started_ts REAL,
                completed_ts REAL,
                status TEXT,
                validator_version TEXT,
                rows_examined INTEGER,
                primary_rows INTEGER,
                candidate_count INTEGER,
                pbo_estimate REAL,
                champion_key TEXT,
                ready_for_phase5_review INTEGER,
                dataset_hash TEXT,
                execution_wired INTEGER DEFAULT 0,
                real_orders_submitted INTEGER DEFAULT 0,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase4_runs_completed ON phase4_validation_runs(completed_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase4_runs_status_completed ON phase4_validation_runs(status, completed_ts)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase4_candidate_results (
                run_id TEXT,
                candidate_key TEXT,
                model_id TEXT,
                order_policy TEXT,
                normal_samples INTEGER,
                mean_net_bps REAL,
                bootstrap_lower_95_bps REAL,
                dsr_probability REAL,
                walk_forward_positive_ratio REAL,
                parameter_positive_ratio REAL,
                symbol_holdout_positive_ratio REAL,
                regime_holdout_positive_ratio REAL,
                symbol_profit_concentration REAL,
                month_profit_concentration REAL,
                robust_score REAL,
                passes_candidate_gates INTEGER,
                payload TEXT,
                PRIMARY KEY(run_id, candidate_key)
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase4_candidates_run_pass ON phase4_candidate_results(run_id, passes_candidate_gates)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase4_candidates_model_policy ON phase4_candidate_results(model_id, order_policy)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase4_fold_results (
                run_id TEXT,
                candidate_key TEXT,
                fold_index INTEGER,
                test_start_ts REAL,
                test_end_ts REAL,
                test_samples INTEGER,
                test_mean_net_bps REAL,
                test_positive INTEGER,
                payload TEXT,
                PRIMARY KEY(run_id, candidate_key, fold_index)
            )
            ''')
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase4_holdout_results (
                run_id TEXT,
                candidate_key TEXT,
                holdout_type TEXT,
                holdout_value TEXT,
                test_samples INTEGER,
                test_mean_net_bps REAL,
                test_positive INTEGER,
                payload TEXT,
                PRIMARY KEY(run_id, candidate_key, holdout_type, holdout_value)
            )
            ''')
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase4_perturbation_results (
                run_id TEXT,
                candidate_key TEXT,
                probability_gate REAL,
                expected_net_gate_bps REAL,
                selected_samples INTEGER,
                mean_net_bps REAL,
                positive INTEGER,
                payload TEXT,
                PRIMARY KEY(run_id, candidate_key, probability_gate, expected_net_gate_bps)
            )
            ''')
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase5_model_freezes (
                freeze_id TEXT PRIMARY KEY,
                phase4_run_id TEXT,
                candidate_key TEXT,
                model_id TEXT,
                order_policy TEXT,
                approved_by TEXT,
                approved_ts REAL,
                phase4_dataset_hash TEXT,
                config_hash TEXT,
                status TEXT,
                shadow_only INTEGER DEFAULT 1,
                execution_eligible INTEGER DEFAULT 0,
                revoked_ts REAL,
                revoke_reason TEXT,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase5_freeze_status_ts ON phase5_model_freezes(status, approved_ts)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase5_shadow_runs (
                run_id TEXT PRIMARY KEY,
                started_ts REAL,
                completed_ts REAL,
                status TEXT,
                freeze_id TEXT,
                intents_created INTEGER,
                intents_skipped INTEGER,
                settlements_created INTEGER,
                ready_for_phase6_review INTEGER,
                dataset_hash TEXT,
                execution_wired INTEGER DEFAULT 0,
                private_exchange_access INTEGER DEFAULT 0,
                transmission_attempts INTEGER DEFAULT 0,
                real_orders_submitted INTEGER DEFAULT 0,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase5_runs_completed ON phase5_shadow_runs(completed_ts)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase5_shadow_intents (
                shadow_intent_id TEXT PRIMARY KEY,
                forecast_id TEXT UNIQUE,
                freeze_id TEXT,
                phase4_run_id TEXT,
                candidate_key TEXT,
                model_id TEXT,
                order_policy TEXT,
                venue TEXT,
                symbol TEXT,
                direction TEXT,
                side TEXT,
                order_type TEXT,
                time_in_force TEXT,
                quantity REAL,
                notional_usd REAL,
                reference_price REAL,
                limit_price REAL,
                stop_distance_bps REAL,
                risk_budget_usd REAL,
                predicted_move_bps REAL,
                predicted_cost_bps REAL,
                predicted_net_bps REAL,
                probability_positive_net REAL,
                horizon_seconds INTEGER,
                created_ts REAL,
                target_ts REAL,
                data_quality REAL,
                spread_bps REAL,
                depth_usd_25bps REAL,
                venue_profile_version TEXT,
                config_hash TEXT,
                status TEXT,
                transmission_status TEXT,
                private_endpoint_called INTEGER DEFAULT 0,
                credentials_used INTEGER DEFAULT 0,
                transmission_attempted INTEGER DEFAULT 0,
                settled INTEGER DEFAULT 0,
                execution_wired INTEGER DEFAULT 0,
                live_eligible INTEGER DEFAULT 0,
                real_orders_submitted INTEGER DEFAULT 0,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase5_intents_target ON phase5_shadow_intents(settled, target_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase5_intents_model_ts ON phase5_shadow_intents(model_id, created_ts)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase5_shadow_settlements (
                settlement_id TEXT PRIMARY KEY,
                shadow_intent_id TEXT UNIQUE,
                forecast_id TEXT,
                settled_ts REAL,
                status TEXT,
                fill_model TEXT,
                fill_ratio REAL,
                intended_entry_price REAL,
                hypothetical_entry_price REAL,
                reference_exit_price REAL,
                hypothetical_exit_price REAL,
                entry_slippage_bps REAL,
                exit_slippage_bps REAL,
                fee_bps REAL,
                impact_bps REAL,
                observed_total_cost_bps REAL,
                predicted_cost_bps REAL,
                cost_error_bps REAL,
                gross_directional_return_bps REAL,
                net_return_bps REAL,
                profitable_after_costs INTEGER,
                data_quality REAL,
                transmission_attempted INTEGER DEFAULT 0,
                real_orders_submitted INTEGER DEFAULT 0,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase5_settlements_ts ON phase5_shadow_settlements(settled_ts)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS paper_trades (

                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                symbol TEXT,
                side TEXT,
                qty REAL,
                price REAL,
                notional_usd REAL,
                reason TEXT,
                net_margin_pct REAL,
                status TEXT
            )
            ''')
            c.execute("""
            CREATE TABLE IF NOT EXISTS position_memory (
                symbol TEXT PRIMARY KEY,
                qty REAL,
                entry_price REAL,
                highest_price REAL,
                opened_ts REAL,
                updated_ts REAL,
                status TEXT,
                payload TEXT
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS paper_positions (
                symbol TEXT PRIMARY KEY,
                qty REAL,
                entry_price REAL,
                highest_price REAL,
                opened_ts REAL,
                updated_ts REAL,
                status TEXT,
                payload TEXT
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS executor_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                executor TEXT,
                symbol TEXT,
                side TEXT,
                status TEXT,
                qty REAL,
                price REAL,
                notional_usd REAL,
                net_margin_pct REAL,
                route_loss_pct REAL,
                reason TEXT,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_executor_events_symbol_ts ON executor_events(symbol, ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS hummingbot_executor_lifecycle (
                executor_id TEXT PRIMARY KEY,
                executor_type TEXT,
                symbol TEXT,
                side TEXT,
                state TEXT,
                attempts INTEGER,
                created_ts REAL,
                updated_ts REAL,
                stopped_ts REAL,
                reason TEXT,
                config TEXT,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_hb_lifecycle_state_ts ON hummingbot_executor_lifecycle(state, updated_ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS replay_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                symbol TEXT,
                days REAL,
                trades INTEGER,
                wins INTEGER,
                losses INTEGER,
                net_margin_pct REAL,
                max_drawdown_pct REAL,
                clean_exits INTEGER,
                failed_exits INTEGER,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_replay_results_symbol_ts ON replay_results(symbol, ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS public_bot_backtests (
                run_id TEXT PRIMARY KEY,
                engine TEXT,
                symbol TEXT,
                status TEXT,
                export_path TEXT,
                metrics TEXT,
                created_ts REAL,
                updated_ts REAL,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_public_bot_backtests_engine_ts ON public_bot_backtests(engine, updated_ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS evidence_records (
                evidence_id TEXT PRIMARY KEY,
                source TEXT,
                engine TEXT,
                run_id TEXT,
                symbol TEXT,
                strategy TEXT,
                verdict TEXT,
                promotion_stage TEXT,
                trades INTEGER,
                win_rate REAL,
                net_profit_pct REAL,
                max_drawdown_pct REAL,
                created_ts REAL,
                updated_ts REAL,
                gates TEXT,
                metrics TEXT,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_evidence_symbol_ts ON evidence_records(symbol, updated_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_evidence_verdict_ts ON evidence_records(verdict, updated_ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS ml_model_candidates (
                candidate_id TEXT PRIMARY KEY,
                family TEXT,
                symbol TEXT,
                objective TEXT,
                status TEXT,
                verdict TEXT,
                created_ts REAL,
                updated_ts REAL,
                model_card_path TEXT,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_ml_candidates_family_ts ON ml_model_candidates(family, updated_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_ml_candidates_symbol_ts ON ml_model_candidates(symbol, updated_ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS execution_parity_diagnostics (
                parity_id TEXT PRIMARY KEY,
                source TEXT,
                symbol TEXT,
                run_id TEXT,
                evidence_id TEXT,
                verdict TEXT,
                created_ts REAL,
                updated_ts REAL,
                metrics TEXT,
                gates TEXT,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_execution_parity_symbol_ts ON execution_parity_diagnostics(symbol, updated_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_execution_parity_verdict_ts ON execution_parity_diagnostics(verdict, updated_ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS signal_marketplace_rounds (
                round_id TEXT PRIMARY KEY,
                source TEXT,
                symbol TEXT,
                status TEXT,
                verdict TEXT,
                submitted INTEGER,
                eligible INTEGER,
                total_simulated_reward REAL,
                created_ts REAL,
                updated_ts REAL,
                gates TEXT,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_signal_marketplace_symbol_ts ON signal_marketplace_rounds(symbol, updated_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_signal_marketplace_verdict_ts ON signal_marketplace_rounds(verdict, updated_ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS worker_performance (
                worker TEXT PRIMARY KEY,
                total INTEGER,
                wins INTEGER,
                losses INTEGER,
                recent TEXT,
                updated_ts REAL,
                payload TEXT
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS pair_protections (
                symbol TEXT PRIMARY KEY,
                state TEXT,
                reason TEXT,
                cooldown_until REAL,
                daily_loss_pct REAL,
                failed_quotes INTEGER,
                route_loss_spike_pct REAL,
                low_profit_until REAL,
                updated_ts REAL,
                payload TEXT
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS promotion_records (
                symbol TEXT PRIMARY KEY,
                stage TEXT,
                eligible INTEGER,
                reason TEXT,
                paper_trades INTEGER,
                win_rate REAL,
                net_margin_sum REAL,
                max_drawdown_pct REAL,
                clean_exits INTEGER,
                failed_exits INTEGER,
                updated_ts REAL,
                payload TEXT
            )
            """)
            # simple logs table for UI/activity
            c.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                level TEXT,
                message TEXT,
                agent TEXT
            )
            """)
            # wallet balances table
            c.execute("""
            CREATE TABLE IF NOT EXISTS wallet_balances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                address TEXT,
                asset TEXT,
                balance REAL
            )
            """)
            self.conn.commit()
            logging.info("Data Store tables created/verified")
        except sqlite3.DatabaseError as e:
            if self._is_corrupt_error(e):
                logging.error("Error creating data store tables due to corruption; triggering recovery")
                self._recover_db(str(e))
            else:
                logging.exception("Error creating data store tables")
        except Exception:
            logging.exception("Error creating data store tables")

    def _is_corrupt_error(self, err: Exception) -> bool:
        msg = str(err).lower()
        return ("malformed" in msg) or ("disk image" in msg) or ("file is not a database" in msg)

    def _recover_db(self, reason: str = "database corruption"):
        """Recover from a malformed SQLite DB by backing it up and recreating."""
        if self._recovering:
            return
        self._recovering = True
        try:
            logging.error(f"Data Store DB recovery triggered: {reason}")
            try:
                if self.conn:
                    self.conn.close()
            except Exception:
                pass
            ts = int(time.time())
            base = self.db_path
            wal = f"{base}-wal"
            shm = f"{base}-shm"
            # best-effort backups for base + WAL/SHM
            for path in (wal, shm, base):
                try:
                    if os.path.exists(path):
                        backup = f"{path}.corrupt.{ts}"
                        try:
                            os.replace(path, backup)
                            logging.error(f"Backed up corrupt file to {backup}")
                        except Exception:
                            try:
                                shutil.copy2(path, backup)
                                os.remove(path)
                                logging.error(f"Copied corrupt file to {backup} and removed original")
                            except Exception:
                                pass
                except Exception:
                    pass
            self._connect(check_integrity=False)
            self._create_tables()
        except Exception:
            logging.exception("Failed to recover data store DB")
        finally:
            self._recovering = False

    def store_trade(self, trade_data: Dict[str, Any]):
        """Store a trade record."""
        if not self.conn:
            return
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("""
                    INSERT INTO trades (timestamp, symbol, side, quantity, price, status)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    trade_data.get('timestamp', datetime.now().isoformat()),
                    trade_data.get('symbol'),
                    trade_data.get('side'),
                    trade_data.get('quantity'),
                    trade_data.get('price'),
                    trade_data.get('status', 'pending')
                ))
                self.conn.commit()
                logging.debug(f"Stored trade: {trade_data}")
        except sqlite3.DatabaseError as e:
            if self._is_corrupt_error(e):
                self._recover_db(str(e))
            else:
                logging.error(f"Error storing trade: {e}")
        except Exception as e:
            logging.error(f"Error storing trade: {e}")

    # ------------------ event ingestion / projection ------------------
    def handle_event(self, evt: Dict[str, Any]):
        """Handle incoming buzz events for durable storage. Idempotent where applicable."""
        try:
            if not self.conn:
                return
            buzz = evt.get('buzz', {})
            typ = buzz.get('type')
            payload = evt.get('payload') or {}
            ts = int(buzz.get('ts', int(time.time() * 1000))) / 1000.0
            publish_result = None
            with self._lock:
                c = self.conn.cursor()
                # record raw event
                try:
                    c.execute('INSERT INTO raw_events (ts, type, source, payload) VALUES (?,?,?,?)', (ts, typ, buzz.get('source'), json.dumps(payload)))
                    if typ and buzz.get('id'):
                        c.execute(
                            """
                            INSERT OR IGNORE INTO event_envelopes
                            (event_id, ts, type, source, severity, correlation_id, seq, payload)
                            VALUES (?,?,?,?,?,?,?,?)
                            """,
                            (
                                buzz.get('id'),
                                ts,
                                typ,
                                buzz.get('source'),
                                buzz.get('severity'),
                                buzz.get('correlation_id'),
                                buzz.get('seq'),
                                json.dumps(payload),
                            )
                        )
                    # Mirror a lightweight activity log entry for UI convenience so the dashboard can show buzzes.
                    # NOTE: intentionally bounded/truncated -- the full payload is already durably stored in
                    # raw_events/event_envelopes, so this must stay lightweight (it previously fell back to a full
                    # json.dumps(payload) for any event lacking an explicit 'message' key, which silently duplicated
                    # the entire event payload a third time and was a major contributor to unbounded DB growth).
                    try:
                        if isinstance(payload, dict) and 'message' in payload:
                            msg = payload.get('message')
                        elif payload:
                            msg = f"{typ}: {json.dumps(payload, default=str)[:400]}"
                        else:
                            msg = typ
                        c.execute('INSERT INTO logs (timestamp, level, message, agent) VALUES (?,?,?,?)', (ts, 'INFO', msg, buzz.get('source') or 'DATA_STORE'))
                    except Exception:
                        pass
                except Exception:
                    pass

                if typ in ('buzz.intent.state', 'buzz.coordinator.decision'):
                    intent_id = payload.get('intent_id') or payload.get('id')
                    if intent_id:
                        # upsert intent
                        c.execute('SELECT intent_id FROM intents WHERE intent_id=?', (intent_id,))
                        exists = c.fetchone()
                        if exists:
                            c.execute('UPDATE intents SET state=?, final_outcome=?, final_reason=?, qty=?, action=? WHERE intent_id=?', (payload.get('state') or payload.get('status'), payload.get('final_outcome'), payload.get('reason'), payload.get('qty'), payload.get('action'), intent_id))
                        else:
                            c.execute('INSERT INTO intents (intent_id, symbol, action, origin_strategy, created_ts, state, final_outcome, final_reason, position_size_pct, qty, order_type) VALUES (?,?,?,?,?,?,?,?,?,?,?)', (
                                intent_id, payload.get('symbol'), payload.get('action') or payload.get('type'), payload.get('strategy'), ts, payload.get('state') or payload.get('status'), payload.get('final_outcome'), payload.get('reason'), payload.get('position_size_pct'), payload.get('qty'), payload.get('order_type')
                            ))

                elif typ in ('buzz.trade.request', 'buzz.trade.order'):
                    # create or update order record
                    client_order_id = payload.get('client_order_id') or payload.get('clientId')
                    if client_order_id:
                        c.execute('SELECT client_order_id FROM orders WHERE client_order_id=?', (client_order_id,))
                        if c.fetchone():
                            c.execute('UPDATE orders SET status=?, order_id=?, placed_ts=? WHERE client_order_id=?', (payload.get('status') or 'REQUESTED', payload.get('order_id'), ts, client_order_id))
                        else:
                            c.execute('INSERT INTO orders (client_order_id, intent_id, venue, symbol, side, order_type, order_id, status, placed_ts, final_ts) VALUES (?,?,?,?,?,?,?,?,?,?)', (
                                client_order_id, payload.get('intent_id'), payload.get('venue'), payload.get('symbol'), payload.get('side'), payload.get('order_type'), payload.get('order_id'), payload.get('status') or 'REQUESTED', ts, None
                            ))

                elif typ in ('buzz.trade.execution',):
                    # update order and insert fills
                    client_order_id = payload.get('client_order_id')
                    order_id = payload.get('order_id')
                    status = payload.get('status')
                    filled = float(payload.get('filled_qty') or 0)
                    avg_price = payload.get('avg_price')
                    fees = payload.get('fees') or 0.0
                    slippage = payload.get('slippage_pct') or 0.0
                    # upsert order
                    if client_order_id:
                        c.execute('SELECT client_order_id FROM orders WHERE client_order_id=?', (client_order_id,))
                        if c.fetchone():
                            c.execute(
                                """
                                UPDATE orders
                                SET status=?,
                                    order_id=COALESCE(?, order_id),
                                    venue=COALESCE(?, venue),
                                    symbol=COALESCE(?, symbol),
                                    side=COALESCE(?, side),
                                    order_type=COALESCE(?, order_type),
                                    final_ts=?
                                WHERE client_order_id=?
                                """,
                                (
                                    status,
                                    order_id,
                                    payload.get('venue'),
                                    payload.get('symbol'),
                                    payload.get('side'),
                                    payload.get('order_type'),
                                    ts,
                                    client_order_id,
                                ),
                            )
                        else:
                            c.execute('INSERT OR IGNORE INTO orders (client_order_id, intent_id, venue, symbol, side, order_type, order_id, status, placed_ts, final_ts) VALUES (?,?,?,?,?,?,?,?,?,?)', (
                                client_order_id, payload.get('intent_id'), payload.get('venue'), payload.get('symbol'), payload.get('side'), payload.get('order_type'), order_id, status, payload.get('placed_ts') or ts, ts
                            ))
                    # record fill
                    if filled > 0:
                        try:
                            c.execute('INSERT INTO fills (order_id, client_order_id, filled_qty, avg_price, fee, slippage_pct, ts) VALUES (?,?,?,?,?,?,?)', (order_id, client_order_id, filled, avg_price, fees, slippage, ts))
                        except Exception:
                            logging.exception('Failed to insert fill')

                elif typ in ('buzz.wallet.balance',):
                    balances = payload.get('balances') or []
                    equity = payload.get('equity_usd_est') or payload.get('equity_est') or 0.0
                    venue = payload.get('venue') or 'wallet'
                    eth_free = eth_locked = usdt_free = usdt_locked = 0.0
                    for b in balances:
                        a = (b.get('asset') or '').upper()
                        if a == 'ETH':
                            eth_free = float(b.get('free') or 0)
                            eth_locked = float(b.get('locked') or 0)
                        if a in ('USDT', 'USDC'):
                            usdt_free = float(b.get('free') or 0)
                            usdt_locked = float(b.get('locked') or 0)
                    c.execute('INSERT INTO balances (ts, venue, eth_free, eth_locked, usdt_free, usdt_locked, equity_usd_est) VALUES (?,?,?,?,?,?,?)', (ts, venue, eth_free, eth_locked, usdt_free, usdt_locked, equity))

                elif typ in ('buzz.kill.check', 'buzz.kill.trigger'):
                    payload_json = json.dumps(payload)
                    state = payload.get('risk_state') or payload.get('state') or payload.get('risk')
                    c.execute('INSERT INTO killswitch (ts, state, reason, metrics_json) VALUES (?,?,?,?)', (ts, state, payload.get('reason'), payload_json))

                elif typ == 'buzz.swarmguard.decision':
                    try:
                        c.execute(
                            'INSERT INTO swarmguard (ts, decision, reason, position_size, strategy, symbol, weight, consensus_mult) VALUES (?,?,?,?,?,?,?,?)',
                            (
                                ts,
                                payload.get('decision'),
                                payload.get('reason'),
                                payload.get('position_size'),
                                payload.get('strategy'),
                                payload.get('symbol'),
                                payload.get('weight'),
                                payload.get('consensus_mult'),
                            )
                        )
                    except Exception:
                        logging.exception('Failed to insert swarmguard row')

                elif typ == 'buzz.market.bee':
                    try:
                        rows = payload.get('all') or payload.get('top') or []
                        for row in rows:
                            q = row.get('quality') or {}
                            h = row.get('horizons') or {}
                            hour = h.get('hour') or {}
                            day = h.get('day') or {}
                            pool = row.get('pool') or {}
                            c.execute(
                                """
                                INSERT INTO market_bee_snapshots
                                (ts, symbol, score, allowed, reason, price_usd, liquidity_usd, volume_24h_usd,
                                 h1_change_pct, h24_change_pct, roundtrip_ratio, payload)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                                """,
                                (
                                    ts,
                                    row.get('symbol'),
                                    row.get('score'),
                                    1 if row.get('allowed') else 0,
                                    row.get('reason'),
                                    pool.get('price_usd'),
                                    q.get('liquidity_usd'),
                                    q.get('volume_24h_usd'),
                                    hour.get('price_change_pct'),
                                    day.get('price_change_pct'),
                                    q.get('roundtrip_ratio'),
                                    json.dumps(row),
                                )
                            )
                    except Exception:
                        logging.exception('Failed to insert market bee snapshots')

                elif typ == 'buzz.observation.snapshot':
                    try:
                        run = payload.get('run') or {}
                        run_id = run.get('run_id')
                        if run_id:
                            c.execute(
                                """
                                INSERT INTO observation_runs
                                (run_id, started_ts, completed_ts, venue, status, symbols_attempted,
                                 symbols_successful, symbols_eligible, mean_data_quality, error_count,
                                 dataset_hash, execution_wired, orders_submitted, payload)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                                ON CONFLICT(run_id) DO UPDATE SET
                                  completed_ts=excluded.completed_ts,
                                  status=excluded.status,
                                  symbols_attempted=excluded.symbols_attempted,
                                  symbols_successful=excluded.symbols_successful,
                                  symbols_eligible=excluded.symbols_eligible,
                                  mean_data_quality=excluded.mean_data_quality,
                                  error_count=excluded.error_count,
                                  dataset_hash=excluded.dataset_hash,
                                  execution_wired=0,
                                  orders_submitted=0,
                                  payload=excluded.payload
                                """,
                                (
                                    run_id,
                                    float(run.get('started_at_ms') or 0) / 1000.0,
                                    float(run.get('completed_at_ms') or 0) / 1000.0,
                                    run.get('venue'),
                                    payload.get('status'),
                                    int(run.get('symbols_attempted') or 0),
                                    int(run.get('symbols_successful') or 0),
                                    int(run.get('symbols_eligible') or 0),
                                    float(run.get('mean_data_quality') or 0.0),
                                    len(run.get('errors') or []),
                                    payload.get('dataset_hash'),
                                    0,
                                    0,
                                    json.dumps(payload),
                                ),
                            )
                            for row in payload.get('candidates') or []:
                                values = row.get('values') or {}
                                c.execute(
                                    """
                                    INSERT OR REPLACE INTO observation_snapshots
                                    (run_id, ts, venue, symbol, price, quote_volume_24h, spread_bps,
                                     depth_usd_25bps, volatility_expansion, volume_zscore, book_imbalance,
                                     data_quality, observation_eligible, execution_eligible,
                                     rejection_reasons, payload)
                                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                                    """,
                                    (
                                        run_id,
                                        float(row.get('timestamp_ms') or 0) / 1000.0,
                                        row.get('venue'),
                                        row.get('symbol'),
                                        row.get('price'),
                                        row.get('quote_volume_24h'),
                                        row.get('spread_bps'),
                                        row.get('depth_usd_25bps'),
                                        values.get('volatility_expansion'),
                                        values.get('volume_zscore'),
                                        values.get('book_imbalance'),
                                        row.get('data_quality'),
                                        1 if row.get('observation_eligible') else 0,
                                        0,
                                        json.dumps(row.get('rejection_reasons') or []),
                                        json.dumps(row),
                                    ),
                                )
                    except Exception:
                        logging.exception('Failed to insert observation snapshot')

                elif typ == 'buzz.hypothesis.snapshot':
                    try:
                        run = payload.get('run') or {}
                        run_id = run.get('run_id')
                        if run_id:
                            c.execute(
                                """
                                INSERT INTO hypothesis_runs
                                (run_id, observation_run_id, started_ts, completed_ts, venue, status,
                                 symbols_evaluated, forecasts_total, non_abstain_forecasts, abstentions,
                                 dataset_hash, execution_wired, orders_submitted, payload)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                                ON CONFLICT(run_id) DO UPDATE SET
                                  completed_ts=excluded.completed_ts, status=excluded.status,
                                  symbols_evaluated=excluded.symbols_evaluated, forecasts_total=excluded.forecasts_total,
                                  non_abstain_forecasts=excluded.non_abstain_forecasts, abstentions=excluded.abstentions,
                                  dataset_hash=excluded.dataset_hash, execution_wired=0, orders_submitted=0,
                                  payload=excluded.payload
                                """,
                                (
                                    run_id, run.get('observation_run_id'),
                                    float(run.get('started_at_ms') or 0) / 1000.0,
                                    float(run.get('completed_at_ms') or 0) / 1000.0,
                                    run.get('venue'), payload.get('status'),
                                    int(run.get('symbols_evaluated') or 0),
                                    int(run.get('forecasts_total') or 0),
                                    int(run.get('non_abstain_forecasts') or 0),
                                    int(run.get('abstentions') or 0),
                                    # NOTE: 'forecasts' is intentionally excluded from the persisted run payload --
                                    # every forecast is already individually inserted below into hypothesis_forecasts,
                                    # so embedding the full list again here was pure duplication (~1MB+/run at scale).
                                    payload.get('dataset_hash'), 0, 0,
                                    json.dumps({k: v for k, v in payload.items() if k != 'forecasts'}),
                                ),
                            )
                            for row in payload.get('forecasts') or []:
                                forecast_id = row.get('forecast_id')
                                if not forecast_id:
                                    continue
                                c.execute(
                                    """
                                    INSERT OR REPLACE INTO hypothesis_forecasts
                                    (forecast_id, run_id, observation_run_id, ts, target_ts, venue, symbol,
                                     model_id, hypothesis, horizon_seconds, direction, entry_price,
                                     probability_positive_net, expected_move_bps, expected_cost_bps,
                                     expected_net_bps, raw_score, abstain, reason, settled,
                                     execution_eligible, payload)
                                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                                    """,
                                    (
                                        forecast_id, run_id, row.get('observation_run_id'),
                                        float(row.get('timestamp_ms') or 0) / 1000.0,
                                        float(row.get('target_timestamp_ms') or 0) / 1000.0,
                                        row.get('venue'), row.get('symbol'), row.get('model_id'),
                                        row.get('hypothesis'), int(row.get('horizon_seconds') or 0),
                                        row.get('direction'), row.get('entry_price'),
                                        row.get('probability_positive_net'), row.get('expected_move_bps'),
                                        row.get('expected_cost_bps'), row.get('expected_net_bps'),
                                        row.get('raw_score'), 1 if row.get('abstain') else 0,
                                        row.get('reason'), 0, 0, json.dumps(row),
                                    ),
                                )
                    except Exception:
                        logging.exception('Failed to insert hypothesis snapshot')

                elif typ == 'buzz.market.orderbook':
                    try:
                        c.execute(
                            """
                            INSERT INTO orderbook_snapshots
                            (ts, symbol, venue, bid, ask, spread_pct, mid_price, top_of_book_depth_usd, payload)
                            VALUES (?,?,?,?,?,?,?,?,?)
                            """,
                            (
                                ts,
                                payload.get('symbol'),
                                payload.get('venue'),
                                payload.get('bid'),
                                payload.get('ask'),
                                payload.get('spread_pct'),
                                payload.get('mid_price'),
                                payload.get('top_of_book_depth_usd'),
                                json.dumps(payload),
                            )
                        )
                    except Exception:
                        logging.exception('Failed to insert orderbook snapshot')

                elif typ == 'buzz.store.query':
                    # perform query and publish result over coordinator
                    q = payload or {}
                    query_id = q.get('query_id')
                    name = q.get('name')
                    params = q.get('params') or {}
                    rows = []
                    ok = True
                    try:
                        rows = self._execute_named_query(name, params)
                    except Exception as e:
                        ok = False
                        rows = {'error': str(e)}
                    publish_result = {'buzz': {'type': 'buzz.store.result', 'source': 'DATA_STORE', 'ts': int(time.time()*1000)}, 'payload': {'query_id': query_id, 'ok': ok, 'rows': rows}}

                # commit at end
                try:
                    self.conn.commit()
                except Exception:
                    pass
        except sqlite3.DatabaseError as e:
            if self._is_corrupt_error(e):
                self._recover_db(str(e))
            else:
                logging.exception('DataStoreAgent.handle_event failed')
        except Exception:
            logging.exception('DataStoreAgent.handle_event failed')
        # publish store.query result outside lock
        try:
            if publish_result and self.coordinator:
                self.coordinator.share_data('buzz.store.result', publish_result)
        except Exception:
            logging.exception('Failed to publish store.query result')

    def _execute_named_query(self, name: str, params: Dict[str, Any]):
        if not self.conn:
            return []
        with self._lock:
            c = self.conn.cursor()
        if name == 'get_recent_intents':
            limit = int(params.get('limit', 50))
            c.execute('SELECT intent_id, symbol, action, state, final_outcome, final_reason, qty FROM intents ORDER BY created_ts DESC LIMIT ?', (limit,))
            rows = [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]
            return rows
        if name == 'get_open_intents':
            c.execute("SELECT intent_id, symbol, action, state, qty FROM intents WHERE state NOT IN ('DONE','CANCELED') ORDER BY created_ts ASC")
            rows = [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]
            return rows
        if name == 'get_recent_fills':
            limit = int(params.get('limit', 100))
            c.execute('SELECT * FROM fills ORDER BY ts DESC LIMIT ?', (limit,))
            rows = [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]
            return rows
        # fallback: simple raw SQL if provided (dangerous but useful for debugging)
        if name == 'raw_sql' and params.get('sql'):
            sql = params.get('sql')
            c.execute(sql)
            rows = [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]
            return rows
        raise ValueError('Unknown query name')

    def get_trades(self, symbol: Optional[str] = None, limit: int = 100) -> list:
        """Retrieve trade records."""
        if not self.conn:
            return []
        try:
            with self._lock:
                cursor = self.conn.cursor()
                if symbol:
                    cursor.execute("SELECT * FROM trades WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?",
                                 (symbol, limit))
                else:
                    cursor.execute("SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,))
                return cursor.fetchall()
        except sqlite3.DatabaseError as e:
            if self._is_corrupt_error(e):
                self._recover_db(str(e))
            else:
                logging.error(f"Error retrieving trades: {e}")
            return []
        except Exception as e:
            logging.error(f"Error retrieving trades: {e}")
            return []

    def get_recent_trades(self, limit: int = 100) -> list:
        """Convenience wrapper for most recent trades."""
        return self.get_trades(symbol=None, limit=limit)

    def store_market_data(self, symbol_or_data, data: Optional[Dict[str, Any]] = None):
        """Store market data.

        Can be called as store_market_data(data_dict) or store_market_data(symbol, data_dict).
        """
        if not self.conn:
            return
        try:
            if data is None and isinstance(symbol_or_data, dict):
                payload = symbol_or_data
            else:
                payload = data or {}
                payload.setdefault('symbol', symbol_or_data)

            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("""
                    INSERT INTO market_data (timestamp, symbol, price, volume, source)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    payload.get('timestamp', datetime.now().isoformat()),
                    payload.get('symbol'),
                    payload.get('price'),
                    payload.get('volume'),
                    payload.get('source', 'unknown')
                ))
                self.conn.commit()
                logging.debug(f"Stored market data: {payload}")
        except sqlite3.DatabaseError as e:
            if self._is_corrupt_error(e):
                self._recover_db(str(e))
            else:
                logging.error(f"Error storing market data: {e}")
        except Exception as e:
            logging.error(f"Error storing market data: {e}")

    def market_bee_history(self, symbol: str, days: int = 30) -> list:
        if not self.conn:
            return []
        try:
            cutoff = time.time() - (float(days) * 86400.0)
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute(
                        "SELECT * FROM market_bee_snapshots WHERE symbol=? AND ts>=? ORDER BY ts ASC",
                        (symbol, cutoff),
                    )
                else:
                    c.execute(
                        "SELECT * FROM market_bee_snapshots WHERE ts>=? ORDER BY ts ASC",
                        (cutoff,),
                    )
                cols = [d[0] for d in c.description]
                return [dict(zip(cols, row)) for row in c.fetchall()]
        except Exception:
            return []

    def cex_market_oracle_context(
        self,
        symbol: str,
        *,
        venue: Optional[str] = None,
        as_of_ts: Optional[float] = None,
        horizons_sec: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """Build a bounded multi-horizon CEX oracle context from Phase-1 snapshots."""
        if not self.conn or not symbol:
            return {"schema": "cex_market_oracle_context_v1", "available_horizons": 0, "horizons": {}}
        as_of = float(as_of_ts or time.time())
        horizons = horizons_sec or {
            "1h": 3600,
            "5h": 5 * 3600,
            "24h": 24 * 3600,
            "7d": 7 * 24 * 3600,
            "30d": 30 * 24 * 3600,
        }

        def to_float(value: Any) -> Optional[float]:
            try:
                result = float(value)
                return result if math.isfinite(result) else None
            except (TypeError, ValueError):
                return None

        try:
            with self._lock:
                c = self.conn.cursor()
                latest_params: list[Any] = [symbol, as_of]
                latest_venue_clause = ""
                if venue:
                    latest_venue_clause = " AND venue=?"
                    latest_params.append(venue)
                c.execute(
                    f"""
                    SELECT ts, venue, price, spread_bps, depth_usd_25bps, quote_volume_24h,
                           data_quality, observation_eligible
                    FROM observation_snapshots
                    WHERE symbol=? AND ts<=?{latest_venue_clause}
                    ORDER BY ts DESC
                    LIMIT 1
                    """,
                    tuple(latest_params),
                )
                latest = c.fetchone()
                if not latest:
                    return {
                        "schema": "cex_market_oracle_context_v1",
                        "symbol": symbol,
                        "venue": venue,
                        "as_of_ts": as_of,
                        "available_horizons": 0,
                        "horizons": {},
                        "reason": "no_phase1_snapshot_history",
                    }
                cols = [d[0] for d in c.description]
                latest_row = dict(zip(cols, latest))
                latest_price = to_float(latest_row.get("price"))
                horizon_rows: Dict[str, Any] = {}
                for label, seconds in horizons.items():
                    target_ts = as_of - max(1, int(seconds))
                    params: list[Any] = [symbol, target_ts]
                    venue_clause = ""
                    if venue:
                        venue_clause = " AND venue=?"
                        params.append(venue)
                    c.execute(
                        f"""
                        SELECT ts, venue, price, spread_bps, depth_usd_25bps, quote_volume_24h,
                               data_quality, observation_eligible
                        FROM observation_snapshots
                        WHERE symbol=? AND ts<=?{venue_clause}
                        ORDER BY ts DESC
                        LIMIT 1
                        """,
                        tuple(params),
                    )
                    row = c.fetchone()
                    if not row:
                        horizon_rows[str(label)] = {
                            "seconds": int(seconds),
                            "available": False,
                            "reason": "insufficient_history",
                        }
                        continue
                    prior = dict(zip([d[0] for d in c.description], row))
                    prior_price = to_float(prior.get("price"))
                    change_bps = None
                    if latest_price and prior_price and prior_price > 0:
                        change_bps = ((latest_price - prior_price) / prior_price) * 10_000.0
                    horizon_rows[str(label)] = {
                        "seconds": int(seconds),
                        "available": change_bps is not None,
                        "target_ts": round(target_ts, 3),
                        "prior_ts": prior.get("ts"),
                        "age_error_sec": round(abs(float(prior.get("ts") or 0.0) - target_ts), 3),
                        "prior_price": prior_price,
                        "change_bps": round(change_bps, 6) if change_bps is not None else None,
                        "prior_spread_bps": to_float(prior.get("spread_bps")),
                        "prior_depth_usd_25bps": to_float(prior.get("depth_usd_25bps")),
                        "prior_data_quality": to_float(prior.get("data_quality")),
                    }

                stability_cutoff = as_of - min(max(horizons.values()), 24 * 3600)
                params = [symbol, stability_cutoff, as_of]
                venue_clause = ""
                if venue:
                    venue_clause = " AND venue=?"
                    params.append(venue)
                c.execute(
                    f"""
                    SELECT ts, price, spread_bps, depth_usd_25bps, data_quality
                    FROM observation_snapshots
                    WHERE symbol=? AND ts>=? AND ts<=?{venue_clause}
                    ORDER BY ts ASC
                    LIMIT 500
                    """,
                    tuple(params),
                )
                sample_cols = [d[0] for d in c.description]
                samples = [dict(zip(sample_cols, row)) for row in c.fetchall()]

            spreads = [float(v) for row in samples if (v := to_float(row.get("spread_bps"))) is not None]
            depths = [float(v) for row in samples if (v := to_float(row.get("depth_usd_25bps"))) is not None]
            qualities = [float(v) for row in samples if (v := to_float(row.get("data_quality"))) is not None]
            spread_mean = sum(spreads) / len(spreads) if spreads else None
            spread_max = max(spreads) if spreads else None
            spread_stability = None
            if spread_mean and spread_mean > 0 and spread_max is not None:
                spread_stability = spread_max / spread_mean
            depth_min = min(depths) if depths else None
            quality_mean = sum(qualities) / len(qualities) if qualities else None
            return {
                "schema": "cex_market_oracle_context_v1",
                "source": "phase1_observation_snapshots",
                "symbol": symbol,
                "venue": latest_row.get("venue") or venue,
                "as_of_ts": as_of,
                "latest": {
                    "ts": latest_row.get("ts"),
                    "price": latest_price,
                    "spread_bps": to_float(latest_row.get("spread_bps")),
                    "depth_usd_25bps": to_float(latest_row.get("depth_usd_25bps")),
                    "quote_volume_24h": to_float(latest_row.get("quote_volume_24h")),
                    "data_quality": to_float(latest_row.get("data_quality")),
                    "observation_eligible": bool(latest_row.get("observation_eligible")),
                },
                "horizons": horizon_rows,
                "available_horizons": sum(1 for row in horizon_rows.values() if row.get("available")),
                "stability": {
                    "sample_count": len(samples),
                    "spread_mean_bps": round(spread_mean, 6) if spread_mean is not None else None,
                    "spread_max_bps": round(spread_max, 6) if spread_max is not None else None,
                    "spread_stability_ratio": round(spread_stability, 6) if spread_stability is not None else None,
                    "depth_min_usd_25bps": round(depth_min, 6) if depth_min is not None else None,
                    "data_quality_mean": round(quality_mean, 6) if quality_mean is not None else None,
                },
                "authority": "research_context_only",
                "execution_eligible": False,
                "orders_submitted": 0,
            }
        except Exception:
            logging.exception("Error building CEX market oracle context")
            return {"schema": "cex_market_oracle_context_v1", "available_horizons": 0, "horizons": {}, "reason": "oracle_context_error"}

    def get_orderbook_snapshots(self, symbol: Optional[str] = None, limit: int = 100) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute("SELECT * FROM orderbook_snapshots WHERE symbol=? ORDER BY ts DESC LIMIT ?", (symbol, int(limit or 100)))
                else:
                    c.execute("SELECT * FROM orderbook_snapshots ORDER BY ts DESC LIMIT ?", (int(limit or 100),))
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = []
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    payload = json.loads(d.get("payload") or "{}")
                    if isinstance(payload, dict):
                        d.update(payload)
                except Exception:
                    pass
                out.append(d)
            return out
        except Exception:
            logging.exception("Error fetching orderbook snapshots")
            return []

    def get_observation_runs(self, limit: int = 100) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute("SELECT * FROM observation_runs ORDER BY completed_ts DESC LIMIT ?", (int(limit or 100),))
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            out = []
            for row in rows:
                record = dict(zip(cols, row))
                try:
                    payload = json.loads(record.get("payload") or "{}")
                    record["payload"] = payload
                except Exception:
                    record["payload"] = {}
                record["execution_wired"] = False
                record["orders_submitted"] = 0
                out.append(record)
            return out
        except Exception:
            logging.exception("Error fetching observation runs")
            return []

    def get_observation_snapshots(self, symbol: Optional[str] = None, limit: int = 100) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute("SELECT * FROM observation_snapshots WHERE symbol=? ORDER BY ts DESC LIMIT ?", (symbol, int(limit or 100)))
                else:
                    c.execute("SELECT * FROM observation_snapshots ORDER BY ts DESC LIMIT ?", (int(limit or 100),))
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            out = []
            for row in rows:
                record = dict(zip(cols, row))
                try:
                    payload = json.loads(record.get("payload") or "{}")
                    if isinstance(payload, dict):
                        record.update(payload)
                except Exception:
                    pass
                reasons = record.get("rejection_reasons")
                if isinstance(reasons, str):
                    try:
                        record["rejection_reasons"] = json.loads(reasons or "[]")
                    except Exception:
                        record["rejection_reasons"] = []
                elif isinstance(reasons, (list, tuple)):
                    record["rejection_reasons"] = list(reasons)
                else:
                    record["rejection_reasons"] = []
                record["execution_eligible"] = False
                out.append(record)
            return out
        except Exception:
            logging.exception("Error fetching observation snapshots")
            return []

    def get_observation_price_series(self, symbol: str, limit: int = 120) -> list:
        """Return one symbol's recent prices without waiting on analytics locks."""
        if not self.db_path or self.db_path == ":memory:" or not str(symbol or "").strip():
            return []
        bounded_limit = max(1, min(1000, int(limit or 120)))
        db_uri = f"file:{os.path.abspath(self.db_path)}?mode=ro"
        try:
            conn = sqlite3.connect(db_uri, uri=True, timeout=2.0)
            try:
                conn.execute("PRAGMA query_only=ON")
                conn.execute("PRAGMA busy_timeout=2000")
                rows = conn.execute(
                    """
                    SELECT ts, price
                    FROM observation_snapshots
                    WHERE symbol=? AND ts IS NOT NULL AND price IS NOT NULL
                    ORDER BY ts DESC LIMIT ?
                    """,
                    (str(symbol).strip(), bounded_limit),
                ).fetchall()
                return [
                    {"ts": float(ts), "price": float(price)}
                    for ts, price in reversed(rows)
                ]
            finally:
                conn.close()
        except Exception:
            logging.exception("Error fetching observation price series")
            return []

    def get_observation_readiness(
        self,
        *,
        required_days: float = 7.0,
        min_mean_quality: float = 0.99,
        min_success_ratio: float = 0.90,
        window_hours: Optional[float] = None,
        min_distinct_snapshots: Optional[int] = None,
        distinct_bucket_hours: int = 1,
    ) -> Dict[str, Any]:
        """Summarize whether Phase-1 has accumulated enough clean observation evidence.

        This is an evidence-age gate only. It never grants execution eligibility.
        """
        result: Dict[str, Any] = {
            "phase": 1,
            "mode": "observation_only",
            "ready_for_phase2_review": False,
            "execution_eligible": False,
            "required_days": float(required_days),
            "evidence_window_hours": float(window_hours) if window_hours is not None else None,
            "required_distinct_snapshots": int(min_distinct_snapshots) if min_distinct_snapshots is not None else None,
            "distinct_snapshot_bucket_hours": max(1, int(distinct_bucket_hours or 1)),
            "distinct_snapshot_buckets": 0,
            "observed_days": 0,
            "calendar_span_days": 0.0,
            "runs": 0,
            "healthy_runs": 0,
            "run_success_ratio": 0.0,
            "snapshots": 0,
            "mean_data_quality": 0.0,
            "execution_wired_violations": 0,
            "orders_submitted": 0,
            "reasons": [],
        }
        if not self.conn:
            result["reasons"] = ["data_store_unavailable"]
            return result
        try:
            with self._lock:
                c = self.conn.cursor()
                cutoff = None
                latest_completed = None
                where_sql = ""
                params: tuple[Any, ...] = ()
                if window_hours is not None:
                    c.execute("SELECT MAX(completed_ts) FROM observation_runs")
                    latest_completed = (c.fetchone() or [None])[0]
                    if latest_completed is not None:
                        cutoff = float(latest_completed) - (max(1.0 / 60.0, float(window_hours)) * 3600.0)
                        where_sql = "WHERE completed_ts>=?"
                        params = (cutoff,)
                bucket_seconds = max(1, int(distinct_bucket_hours or 1)) * 3600
                c.execute(
                    f"""
                    SELECT COUNT(*), MIN(started_ts), MAX(completed_ts),
                           SUM(CASE WHEN status='HEALTHY' THEN 1 ELSE 0 END),
                           AVG(mean_data_quality),
                           SUM(CASE WHEN execution_wired != 0 THEN 1 ELSE 0 END),
                           SUM(COALESCE(orders_submitted, 0)),
                           COUNT(DISTINCT date(completed_ts, 'unixepoch')),
                           COUNT(DISTINCT CAST(completed_ts / {bucket_seconds} AS INTEGER))
                    FROM observation_runs
                    {where_sql}
                    """,
                    params,
                )
                row = c.fetchone() or (0, None, None, 0, 0.0, 0, 0, 0, 0)
                if cutoff is None:
                    c.execute("SELECT COUNT(*) FROM observation_snapshots")
                else:
                    c.execute("SELECT COUNT(*) FROM observation_snapshots WHERE ts>=?", (cutoff,))
                snapshots = int((c.fetchone() or [0])[0] or 0)
            runs = int(row[0] or 0)
            started = row[1]
            completed = row[2]
            healthy = int(row[3] or 0)
            calendar_span_days = 0.0
            if started is not None and completed is not None and completed >= started:
                calendar_span_days = (float(completed) - float(started)) / 86_400.0
            observed_days = int(row[7] or 0)
            distinct_snapshots = int(row[8] or 0)
            quality = float(row[4] or 0.0)
            execution_violations = int(row[5] or 0)
            orders = int(row[6] or 0)
            success_ratio = healthy / runs if runs else 0.0
            reasons = []
            if runs <= 0:
                reasons.append("no_observation_runs")
            if min_distinct_snapshots is not None:
                if distinct_snapshots < max(1, int(min_distinct_snapshots)):
                    reasons.append("insufficient_distinct_observation_snapshots")
            elif observed_days < int(required_days):
                reasons.append("insufficient_observation_days")
            if snapshots <= 0:
                reasons.append("no_observation_snapshots")
            if quality < float(min_mean_quality):
                reasons.append("mean_data_quality_below_gate")
            if success_ratio < float(min_success_ratio):
                reasons.append("healthy_run_ratio_below_gate")
            if execution_violations:
                reasons.append("execution_wired_violation")
            if orders:
                reasons.append("nonzero_orders_submitted")
            result.update({
                "ready_for_phase2_review": not reasons,
                "observed_days": max(0, observed_days),
                "distinct_snapshot_buckets": max(0, distinct_snapshots),
                "evidence_window_start_ts": cutoff,
                "evidence_window_end_ts": float(latest_completed) if latest_completed is not None else completed,
                "calendar_span_days": round(max(0.0, calendar_span_days), 6),
                "runs": runs,
                "healthy_runs": healthy,
                "run_success_ratio": round(success_ratio, 6),
                "snapshots": snapshots,
                "mean_data_quality": round(quality, 6),
                "execution_wired_violations": execution_violations,
                "orders_submitted": orders,
                "reasons": reasons,
            })
            return result
        except Exception:
            logging.exception("Error computing Phase-1 observation readiness")
            result["reasons"] = ["readiness_query_failed"]
            return result

    def get_observation_universe(self, *, days: float = 7.0, limit_per_cohort: int = 8) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "days": float(days),
            "cohorts": {},
            "symbols": {},
        }
        if not self.conn:
            result["error"] = "data_store_unavailable"
            return result
        cutoff = time.time() - (max(0.25, float(days)) * 86400.0)
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    "SELECT symbol, observation_eligible, spread_bps, depth_usd_25bps, data_quality, payload FROM observation_snapshots WHERE ts>=? ORDER BY ts DESC",
                    (cutoff,),
                )
                rows = c.fetchall()
            cohorts: Dict[str, list[Dict[str, Any]]] = {}
            symbols: Dict[str, Dict[str, Any]] = {}
            for symbol, observation_eligible, spread_bps, depth_usd_25bps, data_quality, payload in rows:
                try:
                    record = json.loads(payload or "{}")
                except Exception:
                    record = {}
                if not isinstance(record, dict):
                    record = {}
                values = record.get("values") if isinstance(record.get("values"), dict) else {}
                cohort = str(values.get("cohort_bucket") or "research_bench")
                tradable_score = float(values.get("tradable_opportunity_score") or 0.0)
                entry = symbols.setdefault(str(symbol), {
                    "symbol": str(symbol),
                    "cohort_bucket": cohort,
                    "latest_data_quality": float(data_quality or 0.0),
                    "latest_spread_bps": spread_bps,
                    "latest_depth_usd_25bps": depth_usd_25bps,
                    "eligible_hits": 0,
                    "bench_hits": 0,
                    "observations": 0,
                    "best_tradable_opportunity_score": tradable_score,
                })
                entry["observations"] += 1
                if observation_eligible:
                    entry["eligible_hits"] += 1
                else:
                    entry["bench_hits"] += 1
                entry["best_tradable_opportunity_score"] = max(entry["best_tradable_opportunity_score"], tradable_score)
                entry["cohort_bucket"] = cohort
            for item in symbols.values():
                item["eligibility_ratio"] = round(int(item["eligible_hits"]) / max(1, int(item["observations"])), 6)
                cohorts.setdefault(str(item["cohort_bucket"]), []).append(item)
            result["symbols"] = symbols
            result["cohorts"] = {
                cohort: sorted(
                    rows,
                    key=lambda item: (
                        -float(item.get("eligibility_ratio") or 0.0),
                        -float(item.get("best_tradable_opportunity_score") or 0.0),
                        -int(item.get("observations") or 0),
                    ),
                )[: max(1, int(limit_per_cohort or 8))]
                for cohort, rows in cohorts.items()
            }
            return result
        except Exception:
            logging.exception("Error computing observation universe")
            result["error"] = "observation_universe_failed"
            return result

    def get_hypothesis_runs(self, limit: int = 100) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute("SELECT * FROM hypothesis_runs ORDER BY completed_ts DESC LIMIT ?", (int(limit or 100),))
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            out = []
            for row in rows:
                record = dict(zip(cols, row))
                try:
                    record["payload"] = json.loads(record.get("payload") or "{}")
                except Exception:
                    record["payload"] = {}
                record["execution_wired"] = False
                record["orders_submitted"] = 0
                out.append(record)
            return out
        except Exception:
            logging.exception("Error fetching hypothesis runs")
            return []

    def get_hypothesis_forecasts(
        self,
        model_id: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 250,
    ) -> list:
        if not self.conn:
            return []
        try:
            clauses = []
            params: list[Any] = []
            if model_id:
                clauses.append("model_id=?")
                params.append(model_id)
            if symbol:
                clauses.append("symbol=?")
                params.append(symbol)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            params.append(int(limit or 250))
            with self._lock:
                c = self.conn.cursor()
                c.execute(f"SELECT * FROM hypothesis_forecasts {where} ORDER BY ts DESC LIMIT ?", tuple(params))
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            out = []
            for row in rows:
                record = dict(zip(cols, row))
                try:
                    payload = json.loads(record.get("payload") or "{}")
                    if isinstance(payload, dict):
                        record.update(payload)
                except Exception:
                    pass
                record["execution_eligible"] = False
                out.append(record)
            return out
        except Exception:
            logging.exception("Error fetching hypothesis forecasts")
            return []

    def get_hypothesis_outcomes(self, model_id: Optional[str] = None, limit: int = 250) -> list:
        if not self.conn:
            return []
        try:
            params: list[Any] = []
            where = ""
            if model_id:
                where = "WHERE f.model_id=?"
                params.append(model_id)
            params.append(int(limit or 250))
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    f"""
                    SELECT o.*, f.model_id, f.hypothesis, f.symbol, f.horizon_seconds,
                           f.direction, f.entry_price, f.probability_positive_net,
                           f.expected_move_bps, f.expected_cost_bps, f.abstain
                    FROM hypothesis_outcomes o
                    JOIN hypothesis_forecasts f ON f.forecast_id=o.forecast_id
                    {where}
                    ORDER BY o.settled_ts DESC LIMIT ?
                    """,
                    tuple(params),
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            logging.exception("Error fetching hypothesis outcomes")
            return []

    def get_research_reuse_stats(
        self,
        *,
        model_id: str,
        symbol: str,
        horizon_seconds: int,
        regime_hint: str,
        limit: int = 25,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "sample_count": 0,
            "mean_realized_net_bps": None,
            "win_rate": None,
            "latest_settled_ts": None,
        }
        if not self.conn:
            return result

        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    SELECT net_return_bps, positive_net, settled_ts
                    FROM (
                        SELECT
                            o.net_return_bps AS net_return_bps,
                            o.positive_net AS positive_net,
                            o.settled_ts AS settled_ts
                        FROM hypothesis_outcomes o
                        JOIN hypothesis_forecasts f ON f.forecast_id = o.forecast_id
                        WHERE f.model_id = ?
                          AND f.symbol = ?
                          AND f.horizon_seconds = ?
                          AND f.settled = 1
                          AND f.abstain = 0
                          AND COALESCE(
                                json_extract(f.payload, '$.inputs.regime_hint'),
                                json_extract(f.payload, '$.inputs.regime_inputs.regime_hint'),
                                'unknown'
                              ) = ?
                        ORDER BY o.settled_ts DESC
                        LIMIT ?
                    ) recent
                    """,
                    (str(model_id), str(symbol), int(horizon_seconds or 0), str(regime_hint or "unknown"), int(limit or 25)),
                )
                rows = c.fetchall()
            if not rows:
                return result
            net_values = [float(row[0]) for row in rows if row[0] is not None]
            positives = [int(row[1] or 0) for row in rows]
            settled = [float(row[2]) for row in rows if row[2] is not None]
            result["sample_count"] = len(rows)
            result["mean_realized_net_bps"] = (sum(net_values) / len(net_values)) if net_values else None
            result["win_rate"] = (sum(positives) / len(positives)) if positives else None
            result["latest_settled_ts"] = max(settled) if settled else None
            return result
        except Exception:
            logging.exception("Error computing research reuse stats")
            return result

    def get_walk_forward_calibration_samples(
        self,
        *,
        model_id: str,
        horizon_seconds: int,
        cutoff_ts: float,
        limit: int = 250,
    ) -> list[Dict[str, Any]]:
        """Return only evidence settled before the forecast calibration cutoff."""
        if not self.conn:
            return []
        try:
            with self._lock:
                rows = self.conn.execute(
                    """
                    SELECT f.forecast_id, f.ts, o.settled_ts, f.symbol,
                           f.expected_cost_bps, o.directional_return_bps, f.payload
                    FROM hypothesis_forecasts f
                    JOIN hypothesis_outcomes o ON o.forecast_id=f.forecast_id
                    WHERE f.model_id=?
                      AND f.horizon_seconds=?
                      AND f.settled=1
                      AND f.abstain=0
                      AND f.ts < ?
                      AND o.settled_ts <= ?
                    ORDER BY o.settled_ts DESC, f.ts DESC
                    LIMIT ?
                    """,
                    (
                        str(model_id),
                        int(horizon_seconds),
                        float(cutoff_ts),
                        float(cutoff_ts),
                        max(1, int(limit or 250)),
                    ),
                ).fetchall()
            samples = []
            for forecast_id, forecast_ts, settled_ts, symbol, expected_cost_bps, directional_return_bps, raw in rows:
                try:
                    payload = json.loads(raw or "{}")
                except Exception:
                    payload = {}
                inputs = payload.get("inputs") if isinstance(payload, dict) else {}
                inputs = inputs if isinstance(inputs, dict) else {}
                regime_inputs = inputs.get("regime_inputs") if isinstance(inputs.get("regime_inputs"), dict) else {}
                samples.append({
                    "forecast_id": forecast_id,
                    "forecast_ts": forecast_ts,
                    "settled_ts": settled_ts,
                    "symbol": symbol,
                    "expected_cost_bps": expected_cost_bps,
                    "directional_return_bps": directional_return_bps,
                    "regime_hint": str(regime_inputs.get("regime_hint") or inputs.get("regime_hint") or "unknown"),
                    "symbol_class": str(inputs.get("symbol_class") or "unknown"),
                })
            return samples
        except Exception:
            logging.exception("Error fetching walk-forward calibration samples")
            return []

    def get_research_transform_reuse_stats(
        self,
        *,
        model_id: str,
        horizon_seconds: int,
        regime_hint: str,
        cohort_bucket: str,
        symbol_class: str,
        limit: int = 50,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "match_type": "none",
            "sample_count": 0,
            "mean_realized_net_bps": None,
            "win_rate": None,
            "latest_settled_ts": None,
        }
        if not self.conn:
            return result
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    SELECT net_return_bps, positive_net, settled_ts
                    FROM (
                        SELECT
                            o.net_return_bps AS net_return_bps,
                            o.positive_net AS positive_net,
                            o.settled_ts AS settled_ts
                        FROM hypothesis_outcomes o
                        JOIN hypothesis_forecasts f ON f.forecast_id = o.forecast_id
                        WHERE f.model_id = ?
                          AND f.horizon_seconds = ?
                          AND COALESCE(
                                json_extract(f.payload, '$.inputs.regime_hint'),
                                json_extract(f.payload, '$.inputs.regime_inputs.regime_hint'),
                                'unknown'
                              ) = ?
                          AND COALESCE(json_extract(f.payload, '$.inputs.symbol_class'), 'unknown') = ?
                          AND COALESCE(f.abstain, 0) = 0
                        ORDER BY o.settled_ts DESC
                        LIMIT ?
                    ) recent
                    """,
                    (
                        str(model_id),
                        int(horizon_seconds or 0),
                        str(regime_hint or "unknown"),
                        str(symbol_class or "unknown"),
                        int(limit or 50),
                    ),
                )
                rows = c.fetchall()
                if rows:
                    net_values = [float(row[0]) for row in rows if row[0] is not None]
                    positives = [int(row[1] or 0) for row in rows]
                    settled = [float(row[2]) for row in rows if row[2] is not None]
                    result["match_type"] = "symbol_class"
                    result["sample_count"] = len(rows)
                    result["mean_realized_net_bps"] = (sum(net_values) / len(net_values)) if net_values else None
                    result["win_rate"] = (sum(positives) / len(positives)) if positives else None
                    result["latest_settled_ts"] = max(settled) if settled else None
                    return result
                c.execute(
                    """
                    SELECT net_return_bps, positive_net, settled_ts
                    FROM (
                        SELECT
                            o.net_return_bps AS net_return_bps,
                            o.positive_net AS positive_net,
                            o.settled_ts AS settled_ts
                        FROM hypothesis_outcomes o
                        JOIN hypothesis_forecasts f ON f.forecast_id = o.forecast_id
                        WHERE f.model_id = ?
                          AND f.horizon_seconds = ?
                          AND COALESCE(
                                json_extract(f.payload, '$.inputs.regime_hint'),
                                json_extract(f.payload, '$.inputs.regime_inputs.regime_hint'),
                                'unknown'
                              ) = ?
                          AND COALESCE(json_extract(f.payload, '$.inputs.cohort_bucket'), 'unknown') = ?
                          AND COALESCE(f.abstain, 0) = 0
                        ORDER BY o.settled_ts DESC
                        LIMIT ?
                    ) recent
                    """,
                    (
                        str(model_id),
                        int(horizon_seconds or 0),
                        str(regime_hint or "unknown"),
                        str(cohort_bucket or "unknown"),
                        int(limit or 50),
                    ),
                )
                rows = c.fetchall()
            if not rows:
                return result
            net_values = [float(row[0]) for row in rows if row[0] is not None]
            positives = [int(row[1] or 0) for row in rows]
            settled = [float(row[2]) for row in rows if row[2] is not None]
            result["match_type"] = "cohort"
            result["sample_count"] = len(rows)
            result["mean_realized_net_bps"] = (sum(net_values) / len(net_values)) if net_values else None
            result["win_rate"] = (sum(positives) / len(positives)) if positives else None
            result["latest_settled_ts"] = max(settled) if settled else None
            return result
        except Exception:
            logging.exception("Error computing research transform reuse stats")
            return result

    def persist_research_reuse_receipt(self, payload: Dict[str, Any]) -> bool:
        if not self.conn:
            return False
        try:
            with self._lock:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO research_reuse_receipts
                    (receipt_id, created_ts, decision, model_id, symbol, regime_hint, horizon_seconds,
                     config_hash, sample_count, mean_realized_net_bps, win_rate, latest_settled_ts,
                     reason, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        payload.get("receipt_id"),
                        payload.get("created_ts"),
                        payload.get("decision"),
                        payload.get("model_id"),
                        payload.get("symbol"),
                        payload.get("regime_hint"),
                        int(payload.get("horizon_seconds") or 0),
                        payload.get("config_hash"),
                        int(payload.get("sample_count") or 0),
                        payload.get("mean_realized_net_bps"),
                        payload.get("win_rate"),
                        payload.get("latest_settled_ts"),
                        payload.get("reason"),
                        json.dumps(payload, sort_keys=True, default=str),
                    ),
                )
                self.conn.commit()
            return True
        except Exception:
            logging.exception("Error persisting research reuse receipt")
            return False

    def persist_commons_pool_work_ticket(self, payload: Dict[str, Any]) -> bool:
        if not self.conn:
            return False
        try:
            with self._lock:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO commons_pool_work_tickets
                    (ticket_id, created_ts, expires_ts, pool_type, task_class, phase_scope, authority,
                     challenge_nonce, world_state_digest, input_root, feature_schema_digest, code_digest,
                     config_digest, status, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        payload.get("ticket_id"),
                        payload.get("created_ts"),
                        payload.get("expires_ts"),
                        payload.get("pool_type"),
                        payload.get("task_class"),
                        int(payload.get("phase_scope") or 0),
                        payload.get("authority"),
                        payload.get("challenge_nonce"),
                        payload.get("world_state_digest"),
                        payload.get("input_root"),
                        payload.get("feature_schema_digest"),
                        payload.get("code_digest"),
                        payload.get("config_digest"),
                        payload.get("status") or "ISSUED",
                        json.dumps(payload, sort_keys=True, default=str),
                    ),
                )
                self.conn.commit()
            return True
        except Exception:
            logging.exception("Error persisting Commons pool work ticket")
            return False

    def persist_commons_pool_claim_lease(self, payload: Dict[str, Any]) -> bool:
        if not self.conn:
            return False
        try:
            with self._lock:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO commons_pool_claim_leases
                    (lease_id, ticket_id, worker_id, issued_ts, expires_ts, worker_advertisement_digest,
                     challenge_nonce, authority, max_result_bytes, status, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        payload.get("lease_id"),
                        payload.get("ticket_id"),
                        payload.get("worker_id"),
                        payload.get("issued_ts"),
                        payload.get("expires_ts"),
                        payload.get("worker_advertisement_digest"),
                        payload.get("challenge_nonce"),
                        payload.get("authority"),
                        int(payload.get("max_result_bytes") or 0),
                        payload.get("status") or "ACTIVE",
                        json.dumps(payload, sort_keys=True, default=str),
                    ),
                )
                self.conn.commit()
            return True
        except Exception:
            logging.exception("Error persisting Commons pool claim lease")
            return False

    def persist_commons_inference_receipt(self, payload: Dict[str, Any]) -> bool:
        if not self.conn:
            return False
        try:
            with self._lock:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO commons_inference_receipts
                    (receipt_id, ticket_id, lease_id, worker_id, created_ts, pool_type, task_class, phase_scope,
                     challenge_nonce, input_root, output_root, world_state_digest, feature_schema_digest,
                     code_digest, config_digest, container_digest, result_kind, status, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        payload.get("receipt_id"),
                        payload.get("ticket_id"),
                        payload.get("lease_id"),
                        payload.get("worker_id"),
                        payload.get("created_ts"),
                        payload.get("pool_type") or "inference_pool",
                        payload.get("task_class"),
                        int(payload.get("phase_scope") or 0),
                        payload.get("challenge_nonce"),
                        payload.get("input_root"),
                        payload.get("output_root"),
                        payload.get("world_state_digest"),
                        payload.get("feature_schema_digest"),
                        payload.get("code_digest"),
                        payload.get("config_digest"),
                        payload.get("container_digest"),
                        payload.get("result_kind"),
                        payload.get("status") or "RECEIVED",
                        json.dumps(payload, sort_keys=True, default=str),
                    ),
                )
                self.conn.commit()
            return True
        except Exception:
            logging.exception("Error persisting Commons inference receipt")
            return False

    def persist_commons_verifier_receipt(self, payload: Dict[str, Any]) -> bool:
        if not self.conn:
            return False
        try:
            with self._lock:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO commons_verifier_receipts
                    (receipt_id, ticket_id, lease_id, worker_id, created_ts, pool_type, task_class, phase_scope,
                     challenge_nonce, subject_digest, world_state_digest, code_digest, config_digest,
                     container_digest, verification_verdict, status, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        payload.get("receipt_id"),
                        payload.get("ticket_id"),
                        payload.get("lease_id"),
                        payload.get("worker_id"),
                        payload.get("created_ts"),
                        payload.get("pool_type") or "verifier_pool",
                        payload.get("task_class"),
                        int(payload.get("phase_scope") or 0),
                        payload.get("challenge_nonce"),
                        payload.get("subject_digest"),
                        payload.get("world_state_digest"),
                        payload.get("code_digest"),
                        payload.get("config_digest"),
                        payload.get("container_digest"),
                        payload.get("verification_verdict"),
                        payload.get("status") or "RECEIVED",
                        json.dumps(payload, sort_keys=True, default=str),
                    ),
                )
                self.conn.commit()
            return True
        except Exception:
            logging.exception("Error persisting Commons verifier receipt")
            return False

    def persist_commons_local_adoption_receipt(self, payload: Dict[str, Any]) -> bool:
        if not self.conn:
            return False
        try:
            with self._lock:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO commons_local_adoption_receipts
                    (receipt_id, source_receipt_id, source_family, pool_type, phase_scope, adopted_ts, adopted_by,
                     local_reproduction_required, local_reproduction_verdict, adoption_decision, authority_ceiling,
                     status, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        payload.get("receipt_id"),
                        payload.get("source_receipt_id"),
                        payload.get("source_family"),
                        payload.get("pool_type"),
                        int(payload.get("phase_scope") or 0),
                        payload.get("adopted_ts"),
                        payload.get("adopted_by"),
                        1 if payload.get("local_reproduction_required") else 0,
                        payload.get("local_reproduction_verdict"),
                        payload.get("adoption_decision"),
                        payload.get("authority_ceiling"),
                        payload.get("status") or "ADOPTED",
                        json.dumps(payload, sort_keys=True, default=str),
                    ),
                )
                self.conn.commit()
            return True
        except Exception:
            logging.exception("Error persisting Commons local adoption receipt")
            return False

    def revoke_commons_local_adoption(self, source_receipt_id: str, *, reason: str) -> bool:
        """Fail closed while retaining the original receipt as corrected evidence."""
        if not self.conn or not source_receipt_id:
            return False
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    "SELECT receipt_id, payload FROM commons_local_adoption_receipts WHERE source_receipt_id=?",
                    (str(source_receipt_id),),
                )
                rows = c.fetchall()
                for receipt_id, raw_payload in rows:
                    try:
                        payload = json.loads(raw_payload or "{}")
                    except Exception:
                        payload = {}
                    payload["status"] = "REVOKED"
                    payload["adoption_decision"] = "REJECTED_INVALID_CHALLENGER_SELECTION"
                    payload["authority_ceiling"] = "none"
                    payload["revocation_reason"] = str(reason)
                    body = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
                    boundary = body.get("authority_boundary") if isinstance(body.get("authority_boundary"), dict) else {}
                    boundary.update({"allowed": False, "authority_granted": "none"})
                    boundary.setdefault("reasons", []).append(str(reason))
                    body["authority_boundary"] = boundary
                    payload["payload"] = body
                    c.execute(
                        """
                        UPDATE commons_local_adoption_receipts
                        SET adoption_decision='REJECTED_INVALID_CHALLENGER_SELECTION',
                            authority_ceiling='none', status='REVOKED', payload=?
                        WHERE receipt_id=?
                        """,
                        (json.dumps(payload, sort_keys=True, default=str), receipt_id),
                    )
                self.conn.commit()
            return True
        except Exception:
            logging.exception("Error revoking Commons local adoption")
            return False

    def build_commons_local_adoption_receipt(
        self,
        *,
        source_payload: Optional[Dict[str, Any]] = None,
        source_receipt_id: str,
        source_family: str,
        pool_type: str,
        phase_scope: int,
        adopted_by: str,
        adoption_decision: str,
        authority_ceiling: str = "proposal_only",
        local_reproduction_verdict: str = "PASS",
        local_reproduction_required: bool = True,
        reasons: Optional[list[str]] = None,
        status: str = "ADOPTED",
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        adopted_ts = time.time()
        boundary = build_authority_boundary(
            source_payload=dict(source_payload or {}),
            source_family=source_family,
            phase_scope=phase_scope,
            requested_authority=authority_ceiling,
            decision=adoption_decision,
            local_reproduction_verdict=local_reproduction_verdict,
            reasons=reasons,
        ) if source_payload else {
            "schema": "hivenance_authority_boundary_v1",
            "source_family": str(source_family or "unknown"),
            "phase_scope": int(phase_scope or 0),
            "requested_authority": str(authority_ceiling or "proposal_only"),
            "authority_granted": str(authority_ceiling or "proposal_only")
            if str(local_reproduction_verdict or "").upper() == "PASS" and str(adoption_decision or "").upper().startswith("ACCEPTED")
            else "none",
            "allowed": str(local_reproduction_verdict or "").upper() == "PASS" and str(adoption_decision or "").upper().startswith("ACCEPTED"),
            "reasons": list(reasons or []),
        }
        body = {
            "source_receipt_id": str(source_receipt_id or ""),
            "source_family": str(source_family or ""),
            "pool_type": str(pool_type or "unknown"),
            "phase_scope": int(phase_scope or 0),
            "adopted_ts": float(adopted_ts),
            "adopted_by": str(adopted_by or "local_adapter"),
            "local_reproduction_required": bool(local_reproduction_required),
            "local_reproduction_verdict": str(local_reproduction_verdict or "UNKNOWN"),
            "adoption_decision": str(adoption_decision or "REJECTED"),
            "authority_ceiling": str(authority_ceiling or "proposal_only"),
            "reasons": list(reasons or []),
            "status": str(status or "ADOPTED"),
            "payload": {
                **dict(payload or {}),
                "authority_boundary": boundary,
            },
        }
        receipt_id = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        return {
            "schema": "hivenance_local_adoption_receipt_v1",
            "receipt_id": receipt_id,
            **body,
        }

    def ingest_commons_inference_packet(
        self,
        inference_receipt: Dict[str, Any],
        *,
        adopted_by: str = "commons_inference_adapter",
        adoption_decision: str = "ACCEPTED_PROPOSAL_WEIGHT_ONLY",
        authority_ceiling: str = "proposal_only",
        reasons: Optional[list[str]] = None,
        adoption_payload: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not self.persist_commons_inference_receipt(inference_receipt):
            return False
        contract = validate_artifact_contract(
            inference_receipt,
            expected_schema="hivenance_inference_pool_result_receipt_v1",
            requested_authority=authority_ceiling,
        )
        effective_decision = adoption_decision
        effective_status = "ADOPTED"
        effective_verdict = "PASS"
        effective_reasons = list(reasons or [])
        if not contract.get("ok"):
            effective_decision = "REJECTED_INVALID_INFERENCE_RECEIPT"
            effective_status = "REJECTED"
            effective_verdict = "FAIL"
            effective_reasons.extend(list(contract.get("reasons") or []))
        adoption = self.build_commons_local_adoption_receipt(
            source_payload=inference_receipt,
            source_receipt_id=str(inference_receipt.get("receipt_id") or ""),
            source_family="inference_receipt",
            pool_type=str(inference_receipt.get("pool_type") or "inference_pool"),
            phase_scope=int(inference_receipt.get("phase_scope") or 0),
            adopted_by=adopted_by,
            adoption_decision=effective_decision,
            authority_ceiling=authority_ceiling,
            local_reproduction_verdict=effective_verdict,
            local_reproduction_required=True,
            reasons=effective_reasons,
            status=effective_status,
            payload=adoption_payload,
        )
        return self.persist_commons_local_adoption_receipt(adoption)

    def ingest_commons_verifier_packet(
        self,
        verifier_receipt: Dict[str, Any],
        *,
        adopted_by: str = "commons_verifier_adapter",
        adoption_decision: str = "ACCEPTED_VALIDATION_EVIDENCE",
        authority_ceiling: str = "proposal_only",
        reasons: Optional[list[str]] = None,
        adoption_payload: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if not self.persist_commons_verifier_receipt(verifier_receipt):
            return False
        contract = validate_artifact_contract(
            verifier_receipt,
            expected_schema="hivenance_verifier_pool_result_receipt_v1",
            requested_authority=authority_ceiling,
        )
        verdict = str(verifier_receipt.get("verification_verdict") or "").upper()
        effective_decision = adoption_decision
        effective_status = "ADOPTED"
        effective_verdict = "PASS"
        effective_reasons = list(reasons or [])
        if verdict in {"FAIL", "CONTRADICT"} and effective_decision == "ACCEPTED_VALIDATION_EVIDENCE":
            effective_decision = "ACCEPTED_CONTRADICTION_EVIDENCE"
        if not contract.get("ok"):
            effective_decision = "REJECTED_INVALID_VERIFIER_RECEIPT"
            effective_status = "REJECTED"
            effective_verdict = "FAIL"
            effective_reasons.extend(list(contract.get("reasons") or []))
        adoption = self.build_commons_local_adoption_receipt(
            source_payload=verifier_receipt,
            source_receipt_id=str(verifier_receipt.get("receipt_id") or ""),
            source_family="verifier_receipt",
            pool_type=str(verifier_receipt.get("pool_type") or "verifier_pool"),
            phase_scope=int(verifier_receipt.get("phase_scope") or 0),
            adopted_by=adopted_by,
            adoption_decision=effective_decision,
            authority_ceiling=authority_ceiling,
            local_reproduction_verdict=effective_verdict,
            local_reproduction_required=True,
            reasons=effective_reasons,
            status=effective_status,
            payload=adoption_payload,
        )
        return self.persist_commons_local_adoption_receipt(adoption)

    def get_research_reuse_receipts(self, limit: int = 250) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute("SELECT * FROM research_reuse_receipts ORDER BY created_ts DESC LIMIT ?", (int(limit or 250),))
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            logging.exception("Error fetching research reuse receipts")
            return []

    def get_commons_pool_work_tickets(self, limit: int = 250, *, pool_type: Optional[str] = None) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                if pool_type:
                    c.execute(
                        "SELECT * FROM commons_pool_work_tickets WHERE pool_type=? ORDER BY created_ts DESC LIMIT ?",
                        (str(pool_type), int(limit or 250)),
                    )
                else:
                    c.execute("SELECT * FROM commons_pool_work_tickets ORDER BY created_ts DESC LIMIT ?", (int(limit or 250),))
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            logging.exception("Error fetching Commons pool work tickets")
            return []

    def get_commons_pool_work_ticket(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """Resolve one ticket exactly instead of relying on a recent-list window."""
        if not self.conn or not str(ticket_id or "").strip():
            return None
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute("SELECT * FROM commons_pool_work_tickets WHERE ticket_id=? LIMIT 1", (str(ticket_id),))
                row = c.fetchone()
                if row is None:
                    return None
                cols = [item[0] for item in c.description]
            return dict(zip(cols, row))
        except Exception:
            logging.exception("Error fetching exact Commons pool work ticket")
            return None

    def get_commons_pool_claim_leases(self, limit: int = 250, *, ticket_id: Optional[str] = None) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                if ticket_id:
                    c.execute(
                        "SELECT * FROM commons_pool_claim_leases WHERE ticket_id=? ORDER BY issued_ts DESC LIMIT ?",
                        (str(ticket_id), int(limit or 250)),
                    )
                else:
                    c.execute("SELECT * FROM commons_pool_claim_leases ORDER BY issued_ts DESC LIMIT ?", (int(limit or 250),))
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            logging.exception("Error fetching Commons pool claim leases")
            return []

    def get_commons_inference_receipts(self, limit: int = 250, *, phase_scope: Optional[int] = None) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                if phase_scope is not None:
                    c.execute(
                        "SELECT * FROM commons_inference_receipts WHERE phase_scope=? ORDER BY created_ts DESC LIMIT ?",
                        (int(phase_scope), int(limit or 250)),
                    )
                else:
                    c.execute("SELECT * FROM commons_inference_receipts ORDER BY created_ts DESC LIMIT ?", (int(limit or 250),))
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            logging.exception("Error fetching Commons inference receipts")
            return []

    def get_commons_verifier_receipts(self, limit: int = 250, *, phase_scope: Optional[int] = None) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                if phase_scope is not None:
                    c.execute(
                        "SELECT * FROM commons_verifier_receipts WHERE phase_scope=? ORDER BY created_ts DESC LIMIT ?",
                        (int(phase_scope), int(limit or 250)),
                    )
                else:
                    c.execute("SELECT * FROM commons_verifier_receipts ORDER BY created_ts DESC LIMIT ?", (int(limit or 250),))
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            logging.exception("Error fetching Commons verifier receipts")
            return []

    def get_commons_local_adoption_receipts(self, limit: int = 250, *, phase_scope: Optional[int] = None) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                if phase_scope is not None:
                    c.execute(
                        "SELECT * FROM commons_local_adoption_receipts WHERE phase_scope=? ORDER BY adopted_ts DESC LIMIT ?",
                        (int(phase_scope), int(limit or 250)),
                    )
                else:
                    c.execute("SELECT * FROM commons_local_adoption_receipts ORDER BY adopted_ts DESC LIMIT ?", (int(limit or 250),))
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            logging.exception("Error fetching Commons local adoption receipts")
            return []

    def get_commons_pool_snapshot(self, limit: int = 50) -> Dict[str, Any]:
        return {
            "commons_pool_enabled": True,
            "authority": "research_and_verification_only",
            "tickets": self.get_commons_pool_work_tickets(limit=limit),
            "leases": self.get_commons_pool_claim_leases(limit=limit),
            "inference_receipts": self.get_commons_inference_receipts(limit=limit),
            "verifier_receipts": self.get_commons_verifier_receipts(limit=limit),
            "local_adoption_receipts": self.get_commons_local_adoption_receipts(limit=limit),
        }

    def get_commons_dashboard_snapshot(self, limit: int = 50) -> Dict[str, Any]:
        """Read the bounded Commons projection without waiting on analytics work.

        The primary connection lock can be held by long Phase 2/3 queries. A dedicated
        read-only connection keeps the operational UI responsive without granting the
        dashboard any write or execution authority.
        """
        if not self.db_path or self.db_path == ":memory:":
            return self.get_commons_pool_snapshot(limit=limit)
        bounded_limit = max(1, min(250, int(limit or 50)))
        db_uri = f"file:{os.path.abspath(self.db_path)}?mode=ro"
        conn = sqlite3.connect(db_uri, uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA query_only=ON")
            conn.execute("PRAGMA busy_timeout=2000")

            def rows(sql: str, params: tuple = ()) -> list:
                return [dict(row) for row in conn.execute(sql, params).fetchall()]

            snapshot = {
                "commons_pool_enabled": True,
                "authority": "research_and_verification_only",
                "tickets": rows(
                    "SELECT * FROM commons_pool_work_tickets ORDER BY created_ts DESC LIMIT ?",
                    (bounded_limit,),
                ),
                "leases": rows(
                    "SELECT * FROM commons_pool_claim_leases ORDER BY issued_ts DESC LIMIT ?",
                    (bounded_limit,),
                ),
                "inference_receipts": rows(
                    "SELECT * FROM commons_inference_receipts ORDER BY created_ts DESC LIMIT ?",
                    (bounded_limit,),
                ),
                "verifier_receipts": rows(
                    "SELECT * FROM commons_verifier_receipts ORDER BY created_ts DESC LIMIT ?",
                    (bounded_limit,),
                ),
                "local_adoption_receipts": rows(
                    "SELECT * FROM commons_local_adoption_receipts ORDER BY adopted_ts DESC LIMIT ?",
                    (bounded_limit,),
                ),
            }
            packet_specs = {
                "phase2_packets": (
                    "commons_inference_receipts", "i", 2,
                    "i.phase_scope=2 AND i.task_class='phase2_challenger_forecast'",
                    "inference_receipt",
                ),
                "phase3_packets": (
                    "commons_inference_receipts", "i", 3,
                    "i.phase_scope=3 AND i.task_class IN "
                    "('phase3_execution_policy_candidate','phase3_stress_scenario_candidate')",
                    "inference_receipt",
                ),
                "phase4_packets": (
                    "commons_verifier_receipts", "v", 4,
                    "v.phase_scope=4 AND v.task_class IN "
                    "('phase4_candidate_replay_verification','phase4_negative_case_replay',"
                    "'phase4_leakage_audit','phase4_walk_forward_reproduction','phase4_pbo_confirmation')",
                    "verifier_receipt",
                ),
                "phase5_packets": (
                    "commons_verifier_receipts", "v", 5,
                    "v.phase_scope=5 AND v.task_class IN "
                    "('phase5_shadow_integrity_verification','phase5_frozen_config_replay',"
                    "'phase5_shadow_settlement_audit','phase5_drift_confirmation')",
                    "verifier_receipt",
                ),
            }
            for key, (table, alias, phase, receipt_filter, receipt_key) in packet_specs.items():
                packet_rows = rows(
                    f"""
                    SELECT a.payload AS adoption_payload, {alias}.payload AS source_payload
                    FROM commons_local_adoption_receipts a
                    JOIN {table} {alias} ON {alias}.receipt_id=a.source_receipt_id
                    WHERE a.phase_scope=? AND a.status IN ('ADOPTED','ACTIVE')
                      AND a.authority_ceiling='proposal_only' AND {receipt_filter}
                    ORDER BY a.adopted_ts DESC LIMIT ?
                    """,
                    (phase, bounded_limit),
                )
                packets = []
                for row in packet_rows:
                    try:
                        adoption = json.loads(row.get("adoption_payload") or "{}")
                        source = json.loads(row.get("source_payload") or "{}")
                    except (TypeError, ValueError):
                        continue
                    if isinstance(adoption, dict) and isinstance(source, dict):
                        packets.append({"adoption_receipt": adoption, receipt_key: source})
                snapshot[key] = packets
            return snapshot
        finally:
            conn.close()

    def get_commons_phase2_adopted_challenger_packets(self, limit: int = 100) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    SELECT a.payload AS adoption_payload, i.payload AS inference_payload
                    FROM commons_local_adoption_receipts a
                    JOIN commons_inference_receipts i ON i.receipt_id = a.source_receipt_id
                    WHERE a.phase_scope=2
                      AND i.phase_scope=2
                      AND a.status IN ('ADOPTED', 'ACTIVE')
                      AND a.adoption_decision IN ('ACCEPTED_PROPOSAL_WEIGHT_ONLY', 'ACCEPTED_CHALLENGER_FORECAST')
                      AND a.authority_ceiling='proposal_only'
                      AND i.task_class='phase2_challenger_forecast'
                    ORDER BY a.adopted_ts DESC
                    LIMIT ?
                    """,
                    (int(limit or 100),),
                )
                rows = c.fetchall()
            packets = []
            for adoption_raw, inference_raw in rows:
                try:
                    adoption = json.loads(adoption_raw or "{}")
                except Exception:
                    adoption = {}
                try:
                    inference = json.loads(inference_raw or "{}")
                except Exception:
                    inference = {}
                if not isinstance(adoption, dict) or not isinstance(inference, dict):
                    continue
                packets.append({
                    "adoption_receipt": adoption,
                    "inference_receipt": inference,
                })
            return packets
        except Exception:
            logging.exception("Error fetching Commons Phase-2 adopted challenger packets")
            return []

    def get_commons_phase3_adopted_execution_packets(self, limit: int = 100) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    SELECT a.payload AS adoption_payload, i.payload AS inference_payload
                    FROM commons_local_adoption_receipts a
                    JOIN commons_inference_receipts i ON i.receipt_id = a.source_receipt_id
                    WHERE a.phase_scope=3
                      AND i.phase_scope=3
                      AND a.status IN ('ADOPTED', 'ACTIVE')
                      AND a.adoption_decision IN ('ACCEPTED_PROPOSAL_WEIGHT_ONLY', 'ACCEPTED_EXECUTION_POLICY_CANDIDATE')
                      AND a.authority_ceiling='proposal_only'
                      AND i.task_class IN ('phase3_execution_policy_candidate', 'phase3_stress_scenario_candidate')
                    ORDER BY a.adopted_ts DESC
                    LIMIT ?
                    """,
                    (int(limit or 100),),
                )
                rows = c.fetchall()
            packets = []
            for adoption_raw, inference_raw in rows:
                try:
                    adoption = json.loads(adoption_raw or "{}")
                except Exception:
                    adoption = {}
                try:
                    inference = json.loads(inference_raw or "{}")
                except Exception:
                    inference = {}
                if not isinstance(adoption, dict) or not isinstance(inference, dict):
                    continue
                packets.append({
                    "adoption_receipt": adoption,
                    "inference_receipt": inference,
                })
            return packets
        except Exception:
            logging.exception("Error fetching Commons Phase-3 adopted execution packets")
            return []

    def get_commons_phase4_adopted_verifier_packets(
        self, limit: int = 100, *, run_id: Optional[str] = None
    ) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    SELECT a.payload AS adoption_payload, v.payload AS verifier_payload
                    FROM commons_local_adoption_receipts a
                    JOIN commons_verifier_receipts v ON v.receipt_id = a.source_receipt_id
                    WHERE a.phase_scope=4
                      AND v.phase_scope=4
                      AND a.status IN ('ADOPTED', 'ACTIVE')
                      AND a.adoption_decision IN ('ACCEPTED_VALIDATION_EVIDENCE', 'ACCEPTED_CONTRADICTION_EVIDENCE')
                      AND a.authority_ceiling='proposal_only'
                      AND v.task_class IN ('phase4_candidate_replay_verification', 'phase4_negative_case_replay', 'phase4_leakage_audit', 'phase4_walk_forward_reproduction', 'phase4_pbo_confirmation')
                    ORDER BY a.adopted_ts DESC
                    LIMIT ?
                    """,
                    (int(limit or 100),),
                )
                rows = c.fetchall()
            packets = []
            for adoption_raw, verifier_raw in rows:
                try:
                    adoption = json.loads(adoption_raw or "{}")
                except Exception:
                    adoption = {}
                try:
                    verifier = json.loads(verifier_raw or "{}")
                except Exception:
                    verifier = {}
                if not isinstance(adoption, dict) or not isinstance(verifier, dict):
                    continue
                if run_id:
                    target = verifier.get("target_object") if isinstance(verifier.get("target_object"), dict) else {}
                    summary = verifier.get("verification_summary") if isinstance(verifier.get("verification_summary"), dict) else {}
                    packet_run_id = str(
                        target.get("phase4_run_id") or summary.get("phase4_run_id") or ""
                    )
                    if packet_run_id != str(run_id):
                        continue
                packets.append({
                    "adoption_receipt": adoption,
                    "verifier_receipt": verifier,
                })
            return packets
        except Exception:
            logging.exception("Error fetching Commons Phase-4 adopted verifier packets")
            return []

    def get_commons_phase5_adopted_verifier_packets(self, limit: int = 100) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    SELECT a.payload AS adoption_payload, v.payload AS verifier_payload
                    FROM commons_local_adoption_receipts a
                    JOIN commons_verifier_receipts v ON v.receipt_id = a.source_receipt_id
                    WHERE a.phase_scope=5
                      AND v.phase_scope=5
                      AND a.status IN ('ADOPTED', 'ACTIVE')
                      AND a.adoption_decision IN ('ACCEPTED_SHADOW_EVIDENCE', 'ACCEPTED_SHADOW_CONTRADICTION')
                      AND a.authority_ceiling='proposal_only'
                      AND v.task_class IN ('phase5_shadow_integrity_verification', 'phase5_frozen_config_replay', 'phase5_shadow_settlement_audit', 'phase5_drift_confirmation')
                    ORDER BY a.adopted_ts DESC
                    LIMIT ?
                    """,
                    (int(limit or 100),),
                )
                rows = c.fetchall()
            packets = []
            for adoption_raw, verifier_raw in rows:
                try:
                    adoption = json.loads(adoption_raw or "{}")
                except Exception:
                    adoption = {}
                try:
                    verifier = json.loads(verifier_raw or "{}")
                except Exception:
                    verifier = {}
                if not isinstance(adoption, dict) or not isinstance(verifier, dict):
                    continue
                packets.append({
                    "adoption_receipt": adoption,
                    "verifier_receipt": verifier,
                })
            return packets
        except Exception:
            logging.exception("Error fetching Commons Phase-5 adopted verifier packets")
            return []

    def get_commons_phase_summary(self, phase_scope: int, limit: int = 100) -> Dict[str, Any]:
        phase = int(phase_scope or 0)
        tickets = [
            row for row in self.get_commons_pool_work_tickets(limit=min(500, int(limit or 100) * 4))
            if int(row.get("phase_scope") or 0) == phase
        ]
        leases = [
            row for row in self.get_commons_pool_claim_leases(limit=min(500, int(limit or 100) * 4))
            if any(str(row.get("ticket_id") or "") == str(ticket.get("ticket_id") or "") for ticket in tickets)
        ]
        inference_receipts = [
            row for row in self.get_commons_inference_receipts(limit=min(500, int(limit or 100) * 4), phase_scope=phase)
        ]
        verifier_receipts = [
            row for row in self.get_commons_verifier_receipts(limit=min(500, int(limit or 100) * 4), phase_scope=phase)
        ]
        adoptions = [
            row for row in self.get_commons_local_adoption_receipts(limit=min(500, int(limit or 100) * 4), phase_scope=phase)
        ]
        accepted = [
            row for row in adoptions
            if str(row.get("status") or "").upper() in {"ADOPTED", "ACTIVE"}
        ]
        contradictions = [
            row for row in accepted
            if "CONTRADICT" in str(row.get("adoption_decision") or "").upper()
        ]
        proposal_only = [
            row for row in accepted
            if str(row.get("authority_ceiling") or "") == "proposal_only"
        ]
        by_pool: Dict[str, int] = {}
        for row in accepted:
            pool = str(row.get("pool_type") or "unknown")
            by_pool[pool] = by_pool.get(pool, 0) + 1
        return {
            "phase_scope": phase,
            "tickets_issued": len(tickets),
            "leases_issued": len(leases),
            "inference_receipts_received": len(inference_receipts),
            "verifier_receipts_received": len(verifier_receipts),
            "adoption_receipts_total": len(adoptions),
            "adoption_receipts_accepted": len(accepted),
            "adoption_receipts_proposal_only": len(proposal_only),
            "contradiction_receipts": len(contradictions),
            "pool_breakdown": by_pool,
            "recent_tickets": tickets[:10],
            "recent_adoptions": accepted[:10],
        }

    def build_dio_gate_snapshot_from_evidence(
        self,
        phase_scope: int,
        *,
        readiness: Dict[str, Any],
        scorecard: Dict[str, Any],
        commons: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build a deterministic Phase 2/3 gate from one completed evidence pass."""
        phase = int(phase_scope or 0)
        commons = dict(commons or {})
        base = {
            "schema": "dio_gate_snapshot_v1",
            "phase_scope": phase,
            "eligible": False,
            "next_phase": phase + 1 if phase in {2, 3} else None,
            "authority_ceiling": "proposal_only",
            "decision": "REFUSE",
            "reasons": ["unsupported_phase_scope"],
            "predicates": {},
            "commons_pool": commons,
            "computed_ts": time.time(),
        }
        if phase == 2:
            posteriors = [
                row for row in (scorecard.get("profitability_slice_posteriors") or [])
                if isinstance(row, dict)
            ]
            positive_slices = [
                row for row in posteriors
                if row.get("lower_bound_net_bps") is not None
                and float(row.get("lower_bound_net_bps") or 0.0) > 0.0
            ]
            small_window_proxy_slice = bool(readiness.get("small_window_ready_for_phase3"))
            reasons = list(readiness.get("reasons") or [])
            if not positive_slices and not small_window_proxy_slice:
                reasons.append("no_positive_slice_posterior")
            predicates = {
                "readiness_passed": bool(readiness.get("ready_for_phase3_review")),
                "positive_slice_posterior_present": bool(positive_slices) or small_window_proxy_slice,
                "small_window_recent_delta_slice_present": small_window_proxy_slice,
                "commons_authority_bounded": commons.get("adoption_receipts_accepted", 0) == commons.get("adoption_receipts_proposal_only", 0),
                "commons_inference_available": int(commons.get("adoption_receipts_accepted") or 0) > 0,
            }
        elif phase == 3:
            posteriors = [
                row for row in (scorecard.get("profitability_slice_posteriors") or [])
                if isinstance(row, dict) and str(row.get("scenario") or "normal") == "normal"
            ]
            coalition_posteriors = [
                row for row in (scorecard.get("coalition_slice_posteriors") or [])
                if isinstance(row, dict) and str(row.get("scenario") or "normal") == "normal"
            ]
            coalition_dominant = [
                row for row in coalition_posteriors
                if bool(row.get("beats_primary_federated_challenger_oos"))
            ]
            positive_slices = [
                row for row in posteriors
                if row.get("lower_bound_net_bps") is not None
                and float(row.get("lower_bound_net_bps") or 0.0) > 0.0
            ]
            small_window_proxy_slice = str(readiness.get("readiness_mode") or "") == "small_window_proxy_fast_track"
            reasons = list(readiness.get("reasons") or [])
            if not positive_slices and not small_window_proxy_slice:
                reasons.append("no_positive_execution_slice_posterior")
            if coalition_posteriors and not coalition_dominant:
                reasons.append("no_coalition_slice_beats_challenger_oos")
            predicates = {
                "readiness_passed": bool(readiness.get("ready_for_phase4_review")),
                "positive_slice_posterior_present": bool(positive_slices) or small_window_proxy_slice,
                "small_window_execution_proxy_present": small_window_proxy_slice,
                "coalition_challenger_dominance": bool(coalition_dominant) if coalition_posteriors else True,
                "execution_wiring_clean": int(scorecard.get("execution_wiring_violations") or 0) == 0,
                "commons_authority_bounded": commons.get("adoption_receipts_accepted", 0) == commons.get("adoption_receipts_proposal_only", 0),
            }
        else:
            return base
        if not predicates["commons_authority_bounded"]:
            reasons.append("commons_authority_not_bounded")
        reasons = list(dict.fromkeys(str(reason) for reason in reasons if reason))
        base.update({
            "eligible": not reasons,
            "decision": "ALLOW" if not reasons else "REFUSE",
            "reasons": reasons,
            "predicates": predicates,
        })
        return base

    def get_dio_gate_snapshot(self, phase_scope: int) -> Dict[str, Any]:
        phase = int(phase_scope or 0)
        base = {
            "schema": "dio_gate_snapshot_v1",
            "phase_scope": phase,
            "eligible": False,
            "next_phase": None,
            "authority_ceiling": "proposal_only",
            "decision": "REFUSE",
            "reasons": ["unsupported_phase_scope"],
            "predicates": {},
            "commons_pool": {},
        }
        commons = self.get_commons_phase_summary(phase, limit=50)
        if phase == 2:
            readiness = self.get_phase2_readiness()
            scorecard = self.get_hypothesis_scorecard()
            posteriors = [row for row in (scorecard.get("profitability_slice_posteriors") or []) if isinstance(row, dict)]
            positive_slices = [
                row for row in posteriors
                if row.get("lower_bound_net_bps") is not None and float(row.get("lower_bound_net_bps") or 0.0) > 0.0
            ]
            small_window_proxy_slice = bool(readiness.get("small_window_ready_for_phase3"))
            reasons = list(readiness.get("reasons") or [])
            if not positive_slices and not small_window_proxy_slice:
                reasons.append("no_positive_slice_posterior")
            predicates = {
                "readiness_passed": bool(readiness.get("ready_for_phase3_review")),
                "positive_slice_posterior_present": bool(positive_slices) or small_window_proxy_slice,
                "small_window_recent_delta_slice_present": small_window_proxy_slice,
                "commons_authority_bounded": commons.get("adoption_receipts_accepted", 0) == commons.get("adoption_receipts_proposal_only", 0),
                "commons_inference_available": int(commons.get("adoption_receipts_accepted") or 0) > 0,
            }
            if not predicates["commons_authority_bounded"]:
                reasons.append("commons_authority_not_bounded")
            base.update({
                "eligible": not reasons,
                "next_phase": 3,
                "decision": "ALLOW" if not reasons else "REFUSE",
                "reasons": reasons,
                "predicates": predicates,
                "commons_pool": commons,
            })
            return base
        if phase == 3:
            readiness = self.get_phase3_readiness()
            scorecard = self.get_execution_scorecard()
            posteriors = [
                row for row in (scorecard.get("profitability_slice_posteriors") or [])
                if isinstance(row, dict) and str(row.get("scenario") or "normal") == "normal"
            ]
            coalition_posteriors = [
                row for row in (scorecard.get("coalition_slice_posteriors") or [])
                if isinstance(row, dict) and str(row.get("scenario") or "normal") == "normal"
            ]
            coalition_dominant = [
                row for row in coalition_posteriors
                if bool(row.get("beats_primary_federated_challenger_oos"))
            ]
            positive_slices = [
                row for row in posteriors
                if row.get("lower_bound_net_bps") is not None and float(row.get("lower_bound_net_bps") or 0.0) > 0.0
            ]
            small_window_proxy_slice = str(readiness.get("readiness_mode") or "") == "small_window_proxy_fast_track"
            reasons = list(readiness.get("reasons") or [])
            if not positive_slices and not small_window_proxy_slice:
                reasons.append("no_positive_execution_slice_posterior")
            if coalition_posteriors and not coalition_dominant:
                reasons.append("no_coalition_slice_beats_challenger_oos")
            predicates = {
                "readiness_passed": bool(readiness.get("ready_for_phase4_review")),
                "positive_slice_posterior_present": bool(positive_slices) or small_window_proxy_slice,
                "small_window_execution_proxy_present": small_window_proxy_slice,
                "coalition_challenger_dominance": bool(coalition_dominant) if coalition_posteriors else True,
                "execution_wiring_clean": int(scorecard.get("execution_wiring_violations") or 0) == 0,
                "commons_authority_bounded": commons.get("adoption_receipts_accepted", 0) == commons.get("adoption_receipts_proposal_only", 0),
            }
            if not predicates["commons_authority_bounded"]:
                reasons.append("commons_authority_not_bounded")
            base.update({
                "eligible": not reasons,
                "next_phase": 4,
                "decision": "ALLOW" if not reasons else "REFUSE",
                "reasons": reasons,
                "predicates": predicates,
                "commons_pool": commons,
            })
            return base
        if phase == 4:
            readiness = self.get_phase4_readiness()
            scorecard = self.get_phase4_latest_report()
            reasons = list(readiness.get("reasons") or [])
            contradictions = int(
                ((scorecard.get("commons_verifier_pool") or {}).get("contradiction_receipts") or 0)
            )
            predicates = {
                "readiness_passed": bool(readiness.get("ready_for_phase5_review")),
                "verifier_contradiction_free": contradictions == 0,
                "commons_authority_bounded": commons.get("adoption_receipts_accepted", 0) == commons.get("adoption_receipts_proposal_only", 0),
                "phase4_candidate_report_present": bool(scorecard),
            }
            if not predicates["commons_authority_bounded"]:
                reasons.append("commons_authority_not_bounded")
            reasons = list(dict.fromkeys(str(reason) for reason in reasons if reason))
            base.update({
                "eligible": not reasons,
                "next_phase": 5,
                "decision": "ALLOW" if not reasons else "REFUSE",
                "reasons": reasons,
                "predicates": predicates,
                "commons_pool": commons,
            })
            return base
        if phase == 5:
            readiness = self.get_phase5_readiness()
            freeze = self.get_phase5_active_freeze()
            reasons = list(readiness.get("reasons") or [])
            contradictions = 1 if "commons_shadow_contradiction_present" in reasons else 0
            predicates = {
                "readiness_passed": bool(readiness.get("ready_for_phase6_review")),
                "active_freeze_present": bool(freeze),
                "verifier_contradiction_free": contradictions == 0,
                "commons_authority_bounded": commons.get("adoption_receipts_accepted", 0) == commons.get("adoption_receipts_proposal_only", 0),
            }
            if not predicates["commons_authority_bounded"]:
                reasons.append("commons_authority_not_bounded")
            reasons = list(dict.fromkeys(str(reason) for reason in reasons if reason))
            base.update({
                "eligible": not reasons,
                "next_phase": 6,
                "decision": "ALLOW" if not reasons else "REFUSE",
                "reasons": reasons,
                "predicates": predicates,
                "commons_pool": commons,
                "authority_ceiling": "human_review_only",
            })
            return base
        return base

    def settle_mature_hypothesis_forecasts(
        self,
        *,
        now_ts: Optional[float] = None,
        tolerance_sec: float = 600.0,
        limit: int = 5000,
        min_target_ts: Optional[float] = None,
        model_id: Optional[str] = None,
        model_prefix: Optional[str] = None,
        abandon_after_sec: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Settle forecasts against the first persisted observation after target time.

        DOWN forecasts are evaluated synthetically for research parity. This method
        does not create orders, positions, balances, or execution intents.

        Forecasts whose settlement window (target_ts..target_ts+tolerance_sec) has no
        matching observation_snapshots row are normally left pending so a later cycle
        can retry once ingestion catches up. But because forecasts are always examined
        oldest-target_ts-first (bounded by `limit`), a batch of permanently-unmatchable
        forecasts (e.g. from a historical data-recording gap/outage) would otherwise be
        re-selected and re-fail on every single cycle forever, blocking all newer,
        settleable forecasts from ever being reached. If `abandon_after_sec` is given,
        forecasts whose settlement window closed more than that long ago and still have
        no matching observation are marked settled=2 ("abandoned", distinct from the
        real settled=1 outcome state) so they stop being re-selected. No
        hypothesis_outcomes row is written for them, so they are excluded from every
        scorecard/statistic that requires settled=1.
        """
        result = {
            "examined": 0,
            "settled": 0,
            "pending": 0,
            "abandoned": 0,
            "execution_wired": False,
            "orders_submitted": 0,
            "filters": {
                "min_target_ts": float(min_target_ts) if min_target_ts is not None else None,
                "model_id": str(model_id).strip() if model_id else None,
                "model_prefix": str(model_prefix).strip() if model_prefix else None,
            },
        }
        if not self.conn:
            result["error"] = "data_store_unavailable"
            return result
        cutoff = float(now_ts if now_ts is not None else time.time())
        try:
            with self._lock:
                c = self.conn.cursor()
                clauses = ["settled=0", "target_ts<=?"]
                params: list[Any] = [cutoff]
                if min_target_ts is not None:
                    clauses.append("target_ts>=?")
                    params.append(float(min_target_ts))
                clean_model_id = str(model_id or "").strip()
                clean_model_prefix = str(model_prefix or "").strip()
                if clean_model_id:
                    clauses.append("model_id=?")
                    params.append(clean_model_id)
                elif clean_model_prefix:
                    clauses.append("model_id>=?")
                    clauses.append("model_id<?")
                    params.extend([clean_model_prefix, _prefix_upper_bound(clean_model_prefix)])
                params.append(int(limit or 5000))
                c.execute(
                    f"""
                    SELECT forecast_id, symbol, target_ts, direction, entry_price,
                           probability_positive_net, expected_move_bps, expected_cost_bps, abstain
                    FROM hypothesis_forecasts
                    WHERE {' AND '.join(clauses)}
                    ORDER BY target_ts ASC LIMIT ?
                    """,
                    tuple(params),
                )
                forecasts = c.fetchall()
                result["examined"] = len(forecasts)
                for row in forecasts:
                    (forecast_id, symbol, target_ts, direction, entry_price, probability,
                     expected_move, expected_cost, abstain) = row
                    c.execute(
                        """
                        SELECT ts, price FROM observation_snapshots
                        WHERE symbol=? AND ts>=? AND ts<=? AND price IS NOT NULL
                        ORDER BY ts ASC LIMIT 1
                        """,
                        (symbol, float(target_ts), float(target_ts) + float(tolerance_sec)),
                    )
                    market_row = c.fetchone()
                    if not entry_price or float(entry_price) <= 0:
                        result["pending"] += 1
                        continue
                    if not market_row:
                        window_closed_ago = cutoff - (float(target_ts) + float(tolerance_sec))
                        if abandon_after_sec is not None and window_closed_ago > float(abandon_after_sec):
                            c.execute(
                                "UPDATE hypothesis_forecasts SET settled=2 WHERE forecast_id=?",
                                (forecast_id,),
                            )
                            result["abandoned"] += 1
                        else:
                            result["pending"] += 1
                        continue
                    settled_ts, exit_price = market_row
                    raw_return_bps = ((float(exit_price) - float(entry_price)) / float(entry_price)) * 10_000.0
                    if direction == "UP":
                        directional_bps = raw_return_bps
                    elif direction == "DOWN":
                        directional_bps = -raw_return_bps
                    else:
                        directional_bps = 0.0
                    cost_bps = float(expected_cost or 0.0) if not abstain else 0.0
                    net_bps = directional_bps - cost_bps if not abstain else 0.0
                    positive = 1 if net_bps > 0 else 0
                    brier = None
                    if probability is not None:
                        brier = (float(probability) - float(positive)) ** 2
                    absolute_error = None
                    if expected_move is not None and not abstain:
                        absolute_error = abs(abs(directional_bps) - float(expected_move))
                    payload = {
                        "forecast_id": forecast_id,
                        "target_ts": target_ts,
                        "settled_ts": settled_ts,
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "market_return_bps": raw_return_bps,
                        "directional_return_bps": directional_bps,
                        "expected_cost_bps": cost_bps,
                        "net_return_bps": net_bps,
                        "positive_net": bool(positive),
                        "research_only": True,
                    }
                    c.execute(
                        """
                        INSERT OR REPLACE INTO hypothesis_outcomes
                        (forecast_id, settled_ts, exit_price, gross_return_bps,
                         directional_return_bps, net_return_bps, positive_net,
                         brier_score, absolute_error_bps, payload)
                        VALUES (?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            forecast_id, settled_ts, exit_price, raw_return_bps,
                            directional_bps, net_bps, positive, brier,
                            absolute_error, json.dumps(payload),
                        ),
                    )
                    c.execute("UPDATE hypothesis_forecasts SET settled=1 WHERE forecast_id=?", (forecast_id,))
                    result["settled"] += 1
                self.conn.commit()
            return result
        except Exception:
            logging.exception("Error settling hypothesis forecasts")
            result["error"] = "settlement_failed"
            return result

    def get_hypothesis_scorecard(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "phase": 2,
            "mode": "hypothesis_research_only",
            "models": [],
            "native_model_diagnostics": [],
            "expectancy_breakdown": {},
            "demotion_recommendations": [],
            "cohort_breakdown": {},
            "slice_breakdown": [],
            "profitability_slice_posteriors": [],
            "regime_model_breakdown": [],
            "profitability_frontier": [],
            "worker_triune_mind_breakdown": [],
            "worker_loki_challenge_breakdown": [],
            "abstention_reason_breakdown": [],
            "near_miss_recovery_candidates": [],
            "negative_capability_crystals": [],
            "execution_eligible": False,
            "orders_submitted": 0,
        }
        if not self.conn:
            result["error"] = "data_store_unavailable"
            return result
        try:
            shrinkage_prior_strength = 12.0
            try:
                if self.coordinator and hasattr(self.coordinator, "cfg"):
                    shrinkage_prior_strength = float(
                        getattr(self.coordinator.cfg, "phase2_shrinkage_prior_strength", 12.0) or 12.0
                    )
            except Exception:
                pass
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    SELECT f.model_id, f.hypothesis,
                           COUNT(*) AS forecasts,
                           SUM(CASE WHEN f.abstain=0 THEN 1 ELSE 0 END) AS non_abstain,
                           SUM(CASE WHEN f.settled=1 THEN 1 ELSE 0 END) AS settled,
                           SUM(CASE WHEN f.settled=1 AND f.abstain=0 THEN 1 ELSE 0 END) AS settled_trades,
                           AVG(CASE WHEN f.abstain=0 THEN f.expected_net_bps END) AS mean_expected_net_bps,
                           AVG(CASE WHEN f.abstain=0 THEN f.expected_cost_bps END) AS mean_expected_cost_bps,
                           AVG(CASE WHEN f.settled=1 AND f.abstain=0 THEN o.net_return_bps END) AS mean_net_bps,
                           AVG(CASE WHEN f.settled=1 AND f.abstain=0 THEN o.directional_return_bps END) AS mean_directional_bps,
                           AVG(CASE WHEN f.settled=1 AND f.abstain=0 THEN o.positive_net END) AS win_rate,
                           AVG(CASE WHEN f.settled=1 AND f.probability_positive_net IS NOT NULL THEN o.brier_score END) AS brier_score,
                           AVG(CASE WHEN f.settled=1 AND f.abstain=0 THEN o.absolute_error_bps END) AS mean_abs_error_bps,
                           SUM(CASE WHEN f.settled=1 AND f.abstain=0 THEN o.net_return_bps ELSE 0 END) AS cumulative_net_bps
                    FROM hypothesis_forecasts f
                    LEFT JOIN hypothesis_outcomes o ON o.forecast_id=f.forecast_id
                    GROUP BY f.model_id, f.hypothesis
                    ORDER BY f.model_id
                    """
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            models = []
            global_realized_means = [
                float(dict(zip(cols, row)).get("mean_net_bps"))
                for row in rows
                if dict(zip(cols, row)).get("mean_net_bps") is not None and int(dict(zip(cols, row)).get("settled_trades") or 0) > 0
            ]
            global_prior_mean = (
                sum(global_realized_means) / len(global_realized_means)
                if global_realized_means else 0.0
            )
            for row in rows:
                record = dict(zip(cols, row))
                for key in (
                    "mean_expected_net_bps",
                    "mean_expected_cost_bps",
                    "mean_net_bps",
                    "mean_directional_bps",
                    "win_rate",
                    "brier_score",
                    "mean_abs_error_bps",
                    "cumulative_net_bps",
                ):
                    if record.get(key) is not None:
                        record[key] = round(float(record[key]), 6)
                model_id = str(record.get("model_id") or "")
                forecasts = int(record.get("forecasts") or 0)
                non_abstain = int(record.get("non_abstain") or 0)
                settled_trades = int(record.get("settled_trades") or 0)
                record["activation_rate"] = round(non_abstain / max(1, forecasts), 6)
                record["abstain_rate"] = round(1.0 - record["activation_rate"], 6)
                record["settled_trade_rate"] = round(settled_trades / max(1, non_abstain), 6) if non_abstain else 0.0
                expected = float(record.get("mean_expected_net_bps") or 0.0)
                realized = float(record.get("mean_net_bps") or 0.0) if record.get("mean_net_bps") is not None else None
                realized_move = float(record.get("mean_directional_bps") or 0.0) if record.get("mean_directional_bps") is not None else None
                expected_cost = float(record.get("mean_expected_cost_bps") or 0.0)
                record["cost_drag_bps"] = round((realized_move - realized) if realized is not None and realized_move is not None else expected_cost, 6)
                record["shrunk_mean_net_bps"] = (
                    round(
                        _shrunk_mean(
                            realized,
                            settled_trades,
                            global_prior_mean,
                            shrinkage_prior_strength,
                        ),
                        6,
                    )
                    if realized is not None else None
                )
                if settled_trades <= 0:
                    record["diagnostic_label"] = "inactive_or_unsettled"
                elif record["shrunk_mean_net_bps"] is not None and float(record["shrunk_mean_net_bps"]) > 0:
                    record["diagnostic_label"] = "profitable_so_far"
                elif expected > 0 and realized is not None and realized <= 0:
                    record["diagnostic_label"] = "active_but_expectancy_failing"
                elif record["activation_rate"] < 0.05:
                    record["diagnostic_label"] = "too_strict_or_untriggered"
                else:
                    record["diagnostic_label"] = "active_but_unprofitable"
                record["is_baseline"] = model_id.startswith("baseline_")
                if record["is_baseline"]:
                    record["model_role"] = "BASELINE"
                    record["model_family"] = "phoenix_baseline"
                elif model_id.startswith("adapter_freqtrade"):
                    record["model_role"] = "FEDERATED"
                    record["model_family"] = "freqtrade"
                elif model_id.startswith("adapter_jesse"):
                    record["model_role"] = "FEDERATED"
                    record["model_family"] = "jesse"
                elif model_id.startswith("candidate_freqai"):
                    record["model_role"] = "FEDERATED"
                    record["model_family"] = "freqai"
                elif model_id.startswith("candidate_finrl"):
                    record["model_role"] = "FEDERATED"
                    record["model_family"] = "finrl_crypto"
                elif model_id.startswith("candidate_macrohft"):
                    record["model_role"] = "FEDERATED"
                    record["model_family"] = "macrohft"
                elif model_id.startswith("candidate_webcrypto"):
                    record["model_role"] = "FEDERATED"
                    record["model_family"] = "webcryptoagent"
                elif model_id.startswith("candidate_triune_polyphonic"):
                    record["model_role"] = "FEDERATED"
                    record["model_family"] = "phoenix_advanced_synthesis"
                else:
                    record["model_role"] = "PRIMARY"
                    record["model_family"] = "phoenix_native"
                models.append(record)
            result["models"] = models
            result["champion_by_mean_net_bps"] = None
            result["champion_research_model_by_mean_net_bps"] = None
            eligible = [m for m in models if int(m.get("settled_trades") or 0) > 0 and m.get("mean_net_bps") is not None]
            if eligible:
                result["champion_by_mean_net_bps"] = max(eligible, key=lambda item: float(item["mean_net_bps"]))["model_id"]
            research_eligible = [m for m in eligible if not m.get("is_baseline")]
            if research_eligible:
                result["champion_research_model_by_mean_net_bps"] = max(
                    research_eligible, key=lambda item: float(item["mean_net_bps"])
                )["model_id"]
            native_models = [m for m in models if m.get("model_family") == "phoenix_native"]
            result["native_model_diagnostics"] = [
                {
                    "model_id": row.get("model_id"),
                    "hypothesis": row.get("hypothesis"),
                    "activation_rate": row.get("activation_rate"),
                    "settled_trades": int(row.get("settled_trades") or 0),
                    "mean_expected_net_bps": row.get("mean_expected_net_bps"),
                    "mean_net_bps": row.get("mean_net_bps"),
                    "shrunk_mean_net_bps": row.get("shrunk_mean_net_bps"),
                    "cost_drag_bps": row.get("cost_drag_bps"),
                    "diagnostic_label": row.get("diagnostic_label"),
                }
                for row in sorted(
                    native_models,
                    key=lambda item: (
                        int(item.get("settled_trades") or 0),
                        float(item.get("activation_rate") or 0.0),
                        float(item.get("mean_net_bps") if item.get("mean_net_bps") is not None else -10**9),
                    ),
                    reverse=True,
                )
            ]
            def _aggregate(group: list[Dict[str, Any]]) -> Dict[str, Any]:
                forecasts = sum(int(item.get("forecasts") or 0) for item in group)
                non_abstain = sum(int(item.get("non_abstain") or 0) for item in group)
                settled_trades = sum(int(item.get("settled_trades") or 0) for item in group)
                expected_weighted_sum = sum(
                    float(item.get("mean_expected_net_bps") or 0.0) * int(item.get("non_abstain") or 0)
                    for item in group
                    if item.get("mean_expected_net_bps") is not None
                )
                realized_weighted_sum = sum(
                    float(item.get("mean_net_bps") or 0.0) * int(item.get("settled_trades") or 0)
                    for item in group
                    if item.get("mean_net_bps") is not None
                )
                cost_weighted_sum = sum(
                    float(item.get("cost_drag_bps") or 0.0) * int(item.get("settled_trades") or 0)
                    for item in group
                    if item.get("cost_drag_bps") is not None
                )
                return {
                    "models": len(group),
                    "forecasts": forecasts,
                    "non_abstain": non_abstain,
                    "settled_trades": settled_trades,
                    "activation_rate": round(non_abstain / max(1, forecasts), 6),
                    "mean_expected_net_bps": round(expected_weighted_sum / max(1, non_abstain), 6) if non_abstain else None,
                    "mean_realized_net_bps": round(realized_weighted_sum / max(1, settled_trades), 6) if settled_trades else None,
                    "mean_cost_drag_bps": round(cost_weighted_sum / max(1, settled_trades), 6) if settled_trades else None,
                }
            result["expectancy_breakdown"] = {
                "native": _aggregate([m for m in models if m.get("model_family") == "phoenix_native"]),
                "federated": _aggregate([m for m in models if m.get("model_role") == "FEDERATED"]),
                "baseline": _aggregate([m for m in models if m.get("is_baseline")]),
            }
            with self._lock:
                c = self.conn.cursor()
                c.execute("SELECT payload FROM hypothesis_forecasts ORDER BY ts DESC LIMIT 10000")
                payload_rows = [row[0] for row in c.fetchall()]
            cohort_stats: Dict[str, Dict[str, Any]] = {}
            worker_triune_stats: Dict[tuple[str, str], Dict[str, Any]] = {}
            worker_loki_challenges: Dict[tuple[str, str], Dict[str, Any]] = {}
            for raw_payload in payload_rows:
                try:
                    payload = json.loads(raw_payload or "{}")
                except Exception:
                    payload = {}
                if not isinstance(payload, dict):
                    continue
                inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
                model_id = str(payload.get("model_id") or "unknown")
                triune = inputs.get("triune_worker_mind") if isinstance(inputs.get("triune_worker_mind"), dict) else {}
                if model_id.startswith("worker_signal_") and triune:
                    verdict = str(triune.get("final_verdict") or "UNKNOWN")
                    triune_key = (model_id, verdict)
                    triune_bucket = worker_triune_stats.setdefault(triune_key, {
                        "model_id": model_id,
                        "final_verdict": verdict,
                        "forecasts": 0,
                        "non_abstain": 0,
                        "michael_validation_sum": 0.0,
                        "michael_validation_n": 0,
                        "metatron_harmony_sum": 0.0,
                        "metatron_harmony_n": 0,
                        "loki_risk_sum": 0.0,
                        "loki_risk_n": 0,
                    })
                    triune_bucket["forecasts"] += 1
                    if not payload.get("abstain"):
                        triune_bucket["non_abstain"] += 1
                    michael = triune.get("michael") if isinstance(triune.get("michael"), dict) else {}
                    metatron = triune.get("metatron") if isinstance(triune.get("metatron"), dict) else {}
                    loki = triune.get("loki") if isinstance(triune.get("loki"), dict) else {}
                    if michael.get("validation_score") is not None:
                        triune_bucket["michael_validation_sum"] += float(michael.get("validation_score") or 0.0)
                        triune_bucket["michael_validation_n"] += 1
                    if metatron.get("harmony_score") is not None:
                        triune_bucket["metatron_harmony_sum"] += float(metatron.get("harmony_score") or 0.0)
                        triune_bucket["metatron_harmony_n"] += 1
                    if loki.get("risk_score") is not None:
                        triune_bucket["loki_risk_sum"] += float(loki.get("risk_score") or 0.0)
                        triune_bucket["loki_risk_n"] += 1
                    for challenge in (loki.get("challenges") or [])[:8]:
                        if not isinstance(challenge, dict):
                            continue
                        challenge_name = str(challenge.get("challenge") or "unknown")
                        challenge_key = (model_id, challenge_name)
                        challenge_bucket = worker_loki_challenges.setdefault(challenge_key, {
                            "model_id": model_id,
                            "challenge": challenge_name,
                            "count": 0,
                            "max_risk": 0.0,
                        })
                        challenge_bucket["count"] += 1
                        challenge_bucket["max_risk"] = max(
                            float(challenge_bucket.get("max_risk") or 0.0),
                            float(challenge.get("risk") or 0.0),
                        )
                cohort = str(inputs.get("cohort_bucket") or "unknown")
                bucket = cohort_stats.setdefault(cohort, {
                    "cohort_bucket": cohort,
                    "forecasts": 0,
                    "non_abstain": 0,
                    "settled_trades": 0,
                    "expected_sum": 0.0,
                    "expected_n": 0,
                    "realized_sum": 0.0,
                    "realized_n": 0,
                    "top_models": {},
                })
                bucket["forecasts"] += 1
                if not payload.get("abstain"):
                    bucket["non_abstain"] += 1
                exp = payload.get("expected_net_bps")
                if exp is not None:
                    bucket["expected_sum"] += float(exp)
                    bucket["expected_n"] += 1
                bucket["top_models"][model_id] = bucket["top_models"].get(model_id, 0) + (0 if payload.get("abstain") else 1)
            result["worker_triune_mind_breakdown"] = sorted(
                [
                    {
                        "model_id": bucket["model_id"],
                        "final_verdict": bucket["final_verdict"],
                        "forecasts": int(bucket["forecasts"]),
                        "non_abstain": int(bucket["non_abstain"]),
                        "activation_rate": round(int(bucket["non_abstain"]) / max(1, int(bucket["forecasts"])), 6),
                        "mean_michael_validation_score": (
                            round(float(bucket["michael_validation_sum"]) / max(1, int(bucket["michael_validation_n"])), 6)
                            if int(bucket["michael_validation_n"]) else None
                        ),
                        "mean_metatron_harmony_score": (
                            round(float(bucket["metatron_harmony_sum"]) / max(1, int(bucket["metatron_harmony_n"])), 6)
                            if int(bucket["metatron_harmony_n"]) else None
                        ),
                        "mean_loki_risk_score": (
                            round(float(bucket["loki_risk_sum"]) / max(1, int(bucket["loki_risk_n"])), 6)
                            if int(bucket["loki_risk_n"]) else None
                        ),
                    }
                    for bucket in worker_triune_stats.values()
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
                    for bucket in worker_loki_challenges.values()
                ],
                key=lambda item: (-int(item.get("count") or 0), str(item.get("model_id") or ""), str(item.get("challenge") or "")),
            )[:50]
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    SELECT f.payload, o.net_return_bps
                    FROM hypothesis_outcomes o
                    JOIN hypothesis_forecasts f ON f.forecast_id=o.forecast_id
                    ORDER BY o.settled_ts DESC LIMIT 10000
                    """
                )
                outcome_rows = c.fetchall()
            for raw_payload, net_return_bps in outcome_rows:
                try:
                    payload = json.loads(raw_payload or "{}")
                except Exception:
                    payload = {}
                if not isinstance(payload, dict) or payload.get("abstain"):
                    continue
                inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
                cohort = str(inputs.get("cohort_bucket") or "unknown")
                bucket = cohort_stats.setdefault(cohort, {
                    "cohort_bucket": cohort,
                    "forecasts": 0,
                    "non_abstain": 0,
                    "settled_trades": 0,
                    "expected_sum": 0.0,
                    "expected_n": 0,
                    "realized_sum": 0.0,
                    "realized_n": 0,
                    "top_models": {},
                })
                bucket["settled_trades"] += 1
                if net_return_bps is not None:
                    bucket["realized_sum"] += float(net_return_bps)
                    bucket["realized_n"] += 1
            result["cohort_breakdown"] = {
                cohort: {
                    "cohort_bucket": cohort,
                    "forecasts": int(bucket["forecasts"]),
                    "non_abstain": int(bucket["non_abstain"]),
                    "activation_rate": round(int(bucket["non_abstain"]) / max(1, int(bucket["forecasts"])), 6),
                    "settled_trades": int(bucket["settled_trades"]),
                    "mean_expected_net_bps": round(bucket["expected_sum"] / max(1, int(bucket["expected_n"])), 6) if bucket["expected_n"] else None,
                    "mean_realized_net_bps": round(bucket["realized_sum"] / max(1, int(bucket["realized_n"])), 6) if bucket["realized_n"] else None,
                    "shrunk_mean_realized_net_bps": round(
                        _shrunk_mean(
                            (bucket["realized_sum"] / max(1, int(bucket["realized_n"]))) if bucket["realized_n"] else None,
                            int(bucket["realized_n"]),
                            global_prior_mean,
                            shrinkage_prior_strength,
                        ),
                        6,
                    ) if bucket["realized_n"] else None,
                    "top_models": [
                        {"model_id": model_id, "non_abstain": count}
                        for model_id, count in sorted(bucket["top_models"].items(), key=lambda item: (-item[1], item[0]))[:4]
                    ],
                }
                for cohort, bucket in cohort_stats.items()
            }
            slice_stats: Dict[tuple[str, str, str, str], Dict[str, Any]] = {}
            for raw_payload in payload_rows:
                try:
                    payload = json.loads(raw_payload or "{}")
                except Exception:
                    payload = {}
                if not isinstance(payload, dict):
                    continue
                inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
                regime_hint = str(inputs.get("regime_hint") or ((inputs.get("regime_inputs") or {}).get("regime_hint")) or "unknown")
                cohort_bucket = str(inputs.get("cohort_bucket") or "unknown")
                symbol_class = str(inputs.get("symbol_class") or "unknown")
                hypothesis = str(payload.get("hypothesis") or "unknown")
                key = (hypothesis, regime_hint, cohort_bucket, symbol_class)
                bucket = slice_stats.setdefault(key, {
                    "hypothesis": hypothesis,
                    "regime_hint": regime_hint,
                    "cohort_bucket": cohort_bucket,
                    "symbol_class": symbol_class,
                    "forecasts": 0,
                    "non_abstain": 0,
                    "settled_trades": 0,
                    "expected_sum": 0.0,
                    "expected_n": 0,
                    "expected_samples": [],
                    "realized_sum": 0.0,
                    "realized_n": 0,
                    "realized_samples": [],
                    "venue": "unknown",
                    "horizon_bucket": "unknown",
                    "top_models": {},
                })
                bucket["forecasts"] += 1
                if not payload.get("abstain"):
                    bucket["non_abstain"] += 1
                    model_id = str(payload.get("model_id") or "unknown")
                    bucket["top_models"][model_id] = bucket["top_models"].get(model_id, 0) + 1
                exp = payload.get("expected_net_bps")
                if exp is not None and not payload.get("abstain"):
                    bucket["expected_sum"] += float(exp)
                    bucket["expected_n"] += 1
                    bucket["expected_samples"].append(float(exp))
                horizon_seconds = int(payload.get("horizon_seconds") or 0)
                if horizon_seconds >= 3600:
                    bucket["horizon_bucket"] = "long"
                elif horizon_seconds >= 900:
                    bucket["horizon_bucket"] = "medium"
                else:
                    bucket["horizon_bucket"] = "short"
                bucket["venue"] = str(payload.get("venue") or bucket.get("venue") or "unknown")
            for raw_payload, net_return_bps in outcome_rows:
                try:
                    payload = json.loads(raw_payload or "{}")
                except Exception:
                    payload = {}
                if not isinstance(payload, dict) or payload.get("abstain"):
                    continue
                inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
                regime_hint = str(inputs.get("regime_hint") or ((inputs.get("regime_inputs") or {}).get("regime_hint")) or "unknown")
                cohort_bucket = str(inputs.get("cohort_bucket") or "unknown")
                symbol_class = str(inputs.get("symbol_class") or "unknown")
                hypothesis = str(payload.get("hypothesis") or "unknown")
                key = (hypothesis, regime_hint, cohort_bucket, symbol_class)
                bucket = slice_stats.setdefault(key, {
                    "hypothesis": hypothesis,
                    "regime_hint": regime_hint,
                    "cohort_bucket": cohort_bucket,
                    "symbol_class": symbol_class,
                    "forecasts": 0,
                    "non_abstain": 0,
                    "settled_trades": 0,
                    "expected_sum": 0.0,
                    "expected_n": 0,
                    "expected_samples": [],
                    "realized_sum": 0.0,
                    "realized_n": 0,
                    "realized_samples": [],
                    "venue": str(payload.get("venue") or "unknown"),
                    "horizon_bucket": "unknown",
                    "top_models": {},
                })
                bucket["settled_trades"] += 1
                if net_return_bps is not None:
                    bucket["realized_sum"] += float(net_return_bps)
                    bucket["realized_n"] += 1
                    bucket["realized_samples"].append(float(net_return_bps))
            slice_rows = []
            posterior_rows = []
            for (hypothesis, regime_hint, cohort_bucket, symbol_class), bucket in slice_stats.items():
                activation_rate = round(int(bucket["non_abstain"]) / max(1, int(bucket["forecasts"])), 6)
                mean_expected = round(bucket["expected_sum"] / max(1, int(bucket["expected_n"])), 6) if bucket["expected_n"] else None
                mean_realized = round(bucket["realized_sum"] / max(1, int(bucket["realized_n"])), 6) if bucket["realized_n"] else None
                shrunk_realized = round(
                    _shrunk_mean(
                        (bucket["realized_sum"] / max(1, int(bucket["realized_n"]))) if bucket["realized_n"] else None,
                        int(bucket["realized_n"]),
                        global_prior_mean,
                        shrinkage_prior_strength,
                    ),
                    6,
                ) if bucket["realized_n"] else None
                slice_rows.append(
                    {
                        "slice_key": f"{hypothesis}|{regime_hint}|{cohort_bucket}|{symbol_class}",
                        "hypothesis": hypothesis,
                        "regime_hint": regime_hint,
                        "cohort_bucket": cohort_bucket,
                        "symbol_class": symbol_class,
                        "forecasts": int(bucket["forecasts"]),
                        "non_abstain": int(bucket["non_abstain"]),
                        "settled_trades": int(bucket["settled_trades"]),
                        "activation_rate": activation_rate,
                        "mean_expected_net_bps": mean_expected,
                        "mean_realized_net_bps": mean_realized,
                        "shrunk_mean_realized_net_bps": shrunk_realized,
                        "top_models": [
                            {"model_id": model_id, "non_abstain": count}
                            for model_id, count in sorted(bucket["top_models"].items(), key=lambda item: (-item[1], item[0]))[:3]
                        ],
                    }
                )
                realized_distribution = _summarize_distribution(list(bucket.get("realized_samples") or []))
                expected_distribution = _summarize_distribution(list(bucket.get("expected_samples") or []))
                lower_bound_candidates = [
                    value for value in (
                        shrunk_realized,
                        realized_distribution.get("p25_bps"),
                        mean_expected,
                    )
                    if value is not None
                ]
                posterior_rows.append(
                    {
                        "schema": "profitability_slice_posterior_v1",
                        "slice_key": f"{hypothesis}|{regime_hint}|{symbol_class}|forecast_only|{bucket.get('horizon_bucket') or 'unknown'}|{bucket.get('venue') or 'unknown'}",
                        "thesis_family": hypothesis,
                        "regime_hint": regime_hint,
                        "cohort_bucket": cohort_bucket,
                        "symbol_class": symbol_class,
                        "execution_policy_family": "forecast_only",
                        "horizon_bucket": bucket.get("horizon_bucket") or "unknown",
                        "venue": bucket.get("venue") or "unknown",
                        "model_family_mix": sorted({_model_family(model_id) for model_id in bucket["top_models"].keys()}),
                        "posterior_net_return_distribution_bps": realized_distribution,
                        "expected_net_distribution_bps": expected_distribution,
                        "posterior_mean_net_bps": shrunk_realized if shrunk_realized is not None else mean_expected,
                        "lower_bound_net_bps": round(min(lower_bound_candidates), 6) if lower_bound_candidates else None,
                        "probability_positive_net": round(
                            sum(1 for sample in (bucket.get("realized_samples") or []) if float(sample) > 0.0)
                            / max(1, len(bucket.get("realized_samples") or [])),
                            6,
                        ) if bucket.get("realized_samples") else None,
                        "tail_risk_estimate_bps": realized_distribution.get("p10_bps"),
                        "execution_success_distribution": {
                            "activation_rate": activation_rate,
                            "non_abstain": int(bucket["non_abstain"]),
                            "forecasts": int(bucket["forecasts"]),
                        },
                        "capacity_curve_status": "unproven_in_phase2",
                        "drift_state": _drift_state(
                            mean_realized,
                            round(
                                sum((bucket.get("realized_samples") or [])[-6:]) / len((bucket.get("realized_samples") or [])[-6:]),
                                6,
                            ) if len(bucket.get("realized_samples") or []) >= 2 else mean_realized,
                            recent_samples=min(len(bucket.get("realized_samples") or []), 6),
                            drift_threshold_bps=5.0,
                            min_recent_samples=4,
                        ),
                        "evidence_strength": round(
                            min(
                                1.0,
                                (int(bucket["realized_n"]) / 24.0)
                                + (int(bucket["non_abstain"]) / 48.0)
                                + activation_rate,
                            ),
                            6,
                        ),
                    }
                )
            result["slice_breakdown"] = sorted(
                slice_rows,
                key=lambda item: (
                    float(item.get("shrunk_mean_realized_net_bps") if item.get("shrunk_mean_realized_net_bps") is not None else -10**9),
                    int(item.get("settled_trades") or 0),
                    float(item.get("mean_expected_net_bps") if item.get("mean_expected_net_bps") is not None else -10**9),
                ),
                reverse=True,
            )[:24]
            result["profitability_slice_posteriors"] = sorted(
                posterior_rows,
                key=lambda item: (
                    float(item.get("lower_bound_net_bps") if item.get("lower_bound_net_bps") is not None else -10**9),
                    float(item.get("evidence_strength") or 0.0),
                    int((item.get("posterior_net_return_distribution_bps") or {}).get("sample_count") or 0),
                ),
                reverse=True,
            )[:24]
            regime_model_stats: Dict[tuple[str, str], Dict[str, Any]] = {}
            for raw_payload in payload_rows:
                try:
                    payload = json.loads(raw_payload or "{}")
                except Exception:
                    payload = {}
                if not isinstance(payload, dict):
                    continue
                inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
                regime_hint = str(inputs.get("regime_hint") or ((inputs.get("regime_inputs") or {}).get("regime_hint")) or "unknown")
                model_id = str(payload.get("model_id") or "unknown")
                key = (model_id, regime_hint)
                bucket = regime_model_stats.setdefault(key, {
                    "model_id": model_id,
                    "hypothesis": str(payload.get("hypothesis") or "unknown"),
                    "regime_hint": regime_hint,
                    "forecasts": 0,
                    "non_abstain": 0,
                    "settled_trades": 0,
                    "expected_sum": 0.0,
                    "expected_n": 0,
                    "realized_sum": 0.0,
                    "realized_n": 0,
                    "symbols": set(),
                })
                bucket["forecasts"] += 1
                symbol = payload.get("symbol")
                if symbol:
                    bucket["symbols"].add(str(symbol))
                if not payload.get("abstain"):
                    bucket["non_abstain"] += 1
                    exp = payload.get("expected_net_bps")
                    if exp is not None:
                        bucket["expected_sum"] += float(exp)
                        bucket["expected_n"] += 1
            for raw_payload, net_return_bps in outcome_rows:
                try:
                    payload = json.loads(raw_payload or "{}")
                except Exception:
                    payload = {}
                if not isinstance(payload, dict) or payload.get("abstain"):
                    continue
                inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
                regime_hint = str(inputs.get("regime_hint") or ((inputs.get("regime_inputs") or {}).get("regime_hint")) or "unknown")
                model_id = str(payload.get("model_id") or "unknown")
                key = (model_id, regime_hint)
                bucket = regime_model_stats.setdefault(key, {
                    "model_id": model_id,
                    "hypothesis": str(payload.get("hypothesis") or "unknown"),
                    "regime_hint": regime_hint,
                    "forecasts": 0,
                    "non_abstain": 0,
                    "settled_trades": 0,
                    "expected_sum": 0.0,
                    "expected_n": 0,
                    "realized_sum": 0.0,
                    "realized_n": 0,
                    "symbols": set(),
                })
                bucket["settled_trades"] += 1
                if net_return_bps is not None:
                    bucket["realized_sum"] += float(net_return_bps)
                    bucket["realized_n"] += 1
            result["regime_model_breakdown"] = sorted(
                [
                    {
                        "model_id": bucket["model_id"],
                        "hypothesis": bucket["hypothesis"],
                        "regime_hint": bucket["regime_hint"],
                        "forecasts": int(bucket["forecasts"]),
                        "non_abstain": int(bucket["non_abstain"]),
                        "settled_trades": int(bucket["settled_trades"]),
                        "activation_rate": round(int(bucket["non_abstain"]) / max(1, int(bucket["forecasts"])), 6),
                        "mean_expected_net_bps": round(bucket["expected_sum"] / max(1, int(bucket["expected_n"])), 6) if bucket["expected_n"] else None,
                        "mean_realized_net_bps": round(bucket["realized_sum"] / max(1, int(bucket["realized_n"])), 6) if bucket["realized_n"] else None,
                        "shrunk_mean_realized_net_bps": round(
                            _shrunk_mean(
                                (bucket["realized_sum"] / max(1, int(bucket["realized_n"]))) if bucket["realized_n"] else None,
                                int(bucket["realized_n"]),
                                global_prior_mean,
                                shrinkage_prior_strength,
                            ),
                            6,
                        ) if bucket["realized_n"] else None,
                        "symbol_count": len(bucket["symbols"]),
                    }
                    for bucket in regime_model_stats.values()
                ],
                key=lambda item: (
                    float(item.get("shrunk_mean_realized_net_bps") if item.get("shrunk_mean_realized_net_bps") is not None else -10**9),
                    int(item.get("settled_trades") or 0),
                    float(item.get("mean_expected_net_bps") if item.get("mean_expected_net_bps") is not None else -10**9),
                    int(item.get("non_abstain") or 0),
                ),
                reverse=True,
            )[:40]
            frontier = []
            for row in result["regime_model_breakdown"]:
                if int(row.get("settled_trades") or 0) < 5:
                    continue
                realized = row.get("shrunk_mean_realized_net_bps")
                expected = row.get("mean_expected_net_bps")
                if realized is None or expected is None:
                    continue
                if float(realized) <= 0:
                    continue
                frontier.append({
                    **row,
                    "expectation_realization_gap_bps": round(float(realized) - float(expected), 6),
                    "promotion_hint": (
                        "credible_positive_slice"
                        if int(row.get("settled_trades") or 0) >= 12 and float(realized) >= 5.0
                        else "promising_but_small_sample"
                    ),
                })
            result["profitability_frontier"] = frontier[:12]
            reason_counts: Dict[str, int] = {}
            recovery_candidates: list[Dict[str, Any]] = []
            for raw_payload in payload_rows:
                try:
                    payload = json.loads(raw_payload or "{}")
                except Exception:
                    payload = {}
                if not isinstance(payload, dict) or not payload.get("abstain"):
                    continue
                reasons = payload.get("reasons")
                if isinstance(reasons, (list, tuple)):
                    reason_list = [str(item) for item in reasons if item]
                else:
                    primary_reason = payload.get("reason")
                    reason_list = [str(primary_reason)] if primary_reason else []
                for reason in reason_list:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
                inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
                near_miss = inputs.get("near_miss") if isinstance(inputs.get("near_miss"), dict) else {}
                near_miss_score = float(near_miss.get("score") or 0.0)
                tradability = inputs.get("tradability") if isinstance(inputs.get("tradability"), dict) else {}
                tradability_score = float(tradability.get("tradability_score") or 0.0)
                if near_miss_score < 0.72 or tradability_score < 0.45:
                    continue
                recovery_candidates.append({
                    "forecast_id": payload.get("forecast_id"),
                    "symbol": payload.get("symbol"),
                    "model_id": payload.get("model_id"),
                    "hypothesis": payload.get("hypothesis"),
                    "cohort_bucket": inputs.get("cohort_bucket") or "unknown",
                    "reason": reason_list[0] if reason_list else "abstain",
                    "reasons": reason_list[:4],
                    "near_miss_score": round(near_miss_score, 6),
                    "tradability_score": round(tradability_score, 6),
                    "regime_hint": inputs.get("regime_hint") or ((inputs.get("regime_inputs") or {}).get("regime_hint")),
                    "closest_passes": near_miss.get("closest_passes") if isinstance(near_miss.get("closest_passes"), list) else [],
                    "largest_gaps": near_miss.get("largest_gaps") if isinstance(near_miss.get("largest_gaps"), list) else [],
                    "expected_cost_bps": payload.get("expected_cost_bps"),
                    "raw_score": payload.get("raw_score"),
                })
            result["abstention_reason_breakdown"] = [
                {"reason": reason, "count": count}
                for reason, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))[:12]
            ]
            result["negative_capability_crystals"] = [
                {
                    "schema": "negative_capability_crystal_v1",
                    "crystal_id": hashlib.sha256(f"phase2:{reason}".encode("utf-8")).hexdigest(),
                    "scope": "phase2_research_refusal",
                    "failure_state": reason,
                    "evidence_count": int(count),
                    "dominance_rate": round(float(count) / max(1, len(payload_rows)), 6),
                    "authority_effect": "prune_before_simulation",
                    "affected_hypotheses": sorted(
                        {
                            str(candidate.get("hypothesis") or "unknown")
                            for candidate in recovery_candidates
                            if str(candidate.get("reason") or "") == reason
                        }
                    )[:6],
                    "affected_regimes": sorted(
                        {
                            str(candidate.get("regime_hint") or "unknown")
                            for candidate in recovery_candidates
                            if str(candidate.get("reason") or "") == reason
                        }
                    )[:6],
                }
                for reason, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))[:12]
            ]
            recovery_candidates.sort(
                key=lambda item: (
                    float(item.get("near_miss_score") or 0.0),
                    float(item.get("tradability_score") or 0.0),
                    -len(item.get("largest_gaps") or []),
                ),
                reverse=True,
            )
            result["near_miss_recovery_candidates"] = recovery_candidates[:12]
            demotions: list[Dict[str, Any]] = []
            for row in models:
                if row.get("is_baseline"):
                    continue
                settled_trades = int(row.get("settled_trades") or 0)
                activation_rate = float(row.get("activation_rate") or 0.0)
                mean_net = row.get("mean_net_bps")
                if settled_trades < 25 or mean_net is None:
                    continue
                reasons: list[str] = []
                if float(mean_net) <= -20.0:
                    reasons.append("mean_net_bps_below_minus_20")
                if activation_rate >= 0.10 and float(mean_net) < 0.0:
                    reasons.append("active_but_negative")
                if row.get("diagnostic_label") in {"active_but_unprofitable", "active_but_expectancy_failing"}:
                    reasons.append(str(row.get("diagnostic_label")))
                if reasons:
                    demotions.append({
                        "model_id": row.get("model_id"),
                        "model_role": row.get("model_role"),
                        "model_family": row.get("model_family"),
                        "settled_trades": settled_trades,
                        "activation_rate": round(activation_rate, 6),
                        "mean_expected_net_bps": row.get("mean_expected_net_bps"),
                        "mean_net_bps": row.get("mean_net_bps"),
                        "cost_drag_bps": row.get("cost_drag_bps"),
                        "reasons": reasons,
                    })
            result["demotion_recommendations"] = sorted(
                demotions,
                key=lambda item: (
                    float(item.get("mean_net_bps") if item.get("mean_net_bps") is not None else 10**9),
                    -int(item.get("settled_trades") or 0),
                ),
            )
            return result
        except Exception:
            logging.exception("Error computing hypothesis scorecard")
            result["error"] = "scorecard_failed"
            return result

    def _phase_scorecard_snapshot_key(self, phase: int, mode: str, source_limit: int) -> str:
        return f"phase:{int(phase)}:{str(mode or 'unknown')}:{int(source_limit or 0)}"

    def get_phase_scorecard_watermarks(self) -> Dict[str, int]:
        """Return cheap rowid watermarks for materialized scorecard freshness checks."""
        watermarks = {
            "forecast_rowid": 0,
            "outcome_rowid": 0,
            "simulated_order_rowid": 0,
        }
        if not self.conn:
            return watermarks
        try:
            with self._lock:
                c = self.conn.cursor()
                for table, key in (
                    ("hypothesis_forecasts", "forecast_rowid"),
                    ("hypothesis_outcomes", "outcome_rowid"),
                    ("simulated_orders", "simulated_order_rowid"),
                ):
                    try:
                        c.execute(f"SELECT COALESCE(MAX(rowid), 0) FROM {table}")
                        watermarks[key] = int((c.fetchone() or [0])[0] or 0)
                    except sqlite3.OperationalError:
                        watermarks[key] = 0
        except Exception:
            logging.exception("Error reading phase scorecard watermarks")
        return watermarks

    def get_materialized_phase_scorecard(
        self,
        *,
        phase: int,
        mode: str,
        source_limit: int = 20000,
        max_age_sec: float = 60.0,
        require_current_watermark: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Fetch a bounded materialized scorecard if it is still operationally fresh."""
        if not self.conn:
            return None
        key = self._phase_scorecard_snapshot_key(phase, mode, source_limit)
        now_ts = time.time()
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    SELECT created_ts, high_watermark_forecast_rowid,
                           high_watermark_outcome_rowid, high_watermark_simulated_order_rowid,
                           ttl_sec, payload
                    FROM phase_scorecard_snapshots
                    WHERE snapshot_key=?
                    LIMIT 1
                    """,
                    (key,),
                )
                row = c.fetchone()
            if not row:
                return None
            created_ts, forecast_wm, outcome_wm, simulated_wm, ttl_sec, payload_json = row
            age_sec = max(0.0, now_ts - float(created_ts or 0.0))
            ttl = float(max_age_sec if max_age_sec is not None else ttl_sec or 60.0)
            ttl = min(ttl, float(ttl_sec or ttl))
            if age_sec > max(1.0, ttl):
                return None
            if require_current_watermark:
                current = self.get_phase_scorecard_watermarks()
                if (
                    int(forecast_wm or 0) < int(current.get("forecast_rowid") or 0)
                    or int(outcome_wm or 0) < int(current.get("outcome_rowid") or 0)
                    or int(simulated_wm or 0) < int(current.get("simulated_order_rowid") or 0)
                ):
                    return None
            payload = json.loads(payload_json or "{}")
            if not isinstance(payload, dict):
                return None
            payload["materialized_snapshot"] = {
                "snapshot_key": key,
                "created_ts": float(created_ts or 0.0),
                "age_sec": round(age_sec, 3),
                "ttl_sec": round(float(ttl_sec or ttl), 3),
                "high_watermark_forecast_rowid": int(forecast_wm or 0),
                "high_watermark_outcome_rowid": int(outcome_wm or 0),
                "high_watermark_simulated_order_rowid": int(simulated_wm or 0),
                "fresh": True,
            }
            return payload
        except Exception:
            logging.exception("Error reading materialized phase scorecard")
            return None

    def persist_materialized_phase_scorecard(
        self,
        *,
        phase: int,
        mode: str,
        payload: Dict[str, Any],
        source_limit: int = 20000,
        ttl_sec: float = 60.0,
    ) -> bool:
        if not self.conn or not isinstance(payload, dict):
            return False
        key = self._phase_scorecard_snapshot_key(phase, mode, source_limit)
        watermarks = self.get_phase_scorecard_watermarks()
        created_ts = time.time()
        snapshot = dict(payload)
        snapshot.pop("materialized_snapshot", None)
        snapshot["materialized"] = True
        snapshot["materialized_created_ts"] = created_ts
        try:
            with self._lock:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO phase_scorecard_snapshots
                    (snapshot_key, phase, mode, created_ts, high_watermark_forecast_rowid,
                     high_watermark_outcome_rowid, high_watermark_simulated_order_rowid,
                     source_limit, ttl_sec, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        key,
                        int(phase),
                        str(mode or "unknown"),
                        created_ts,
                        int(watermarks.get("forecast_rowid") or 0),
                        int(watermarks.get("outcome_rowid") or 0),
                        int(watermarks.get("simulated_order_rowid") or 0),
                        int(source_limit or 0),
                        float(ttl_sec or 60.0),
                        json.dumps(snapshot),
                    ),
                )
                self.conn.commit()
            return True
        except Exception:
            logging.exception("Error persisting materialized phase scorecard")
            return False

    def get_database_pressure_snapshot(self) -> Dict[str, Any]:
        db_path = getattr(self, "db_path", None) or getattr(self, "database_path", None)
        if db_path is None:
            try:
                row = self.conn.execute("PRAGMA database_list").fetchone() if self.conn else None
                db_path = row[2] if row and len(row) > 2 else None
            except Exception:
                db_path = None
        path = str(db_path or "")
        base_size = os.path.getsize(path) if path and os.path.exists(path) else 0
        wal_path = f"{path}-wal" if path else ""
        shm_path = f"{path}-shm" if path else ""
        snapshot: Dict[str, Any] = {
            "database_path": path,
            "database_size_bytes": int(base_size),
            "wal_size_bytes": int(os.path.getsize(wal_path)) if wal_path and os.path.exists(wal_path) else 0,
            "shm_size_bytes": int(os.path.getsize(shm_path)) if shm_path and os.path.exists(shm_path) else 0,
            "page_count": None,
            "freelist_count": None,
            "page_size": None,
            "estimated_free_bytes": None,
            "hot_store_policy": {
                "mode": "governed_compaction_required",
                "destructive_deletes": "disabled_without_explicit_apply_flag",
            },
        }
        try:
            if self.conn:
                with self._lock:
                    page_count = int((self.conn.execute("PRAGMA page_count").fetchone() or [0])[0] or 0)
                    freelist_count = int((self.conn.execute("PRAGMA freelist_count").fetchone() or [0])[0] or 0)
                    page_size = int((self.conn.execute("PRAGMA page_size").fetchone() or [0])[0] or 0)
                snapshot.update({
                    "page_count": page_count,
                    "freelist_count": freelist_count,
                    "page_size": page_size,
                    "estimated_free_bytes": int(freelist_count * page_size),
                })
        except Exception:
            logging.exception("Error building database pressure snapshot")
        return snapshot

    def checkpoint_database_wal(self, *, truncate: bool = False) -> Dict[str, Any]:
        if not self.conn:
            return {"ok": False, "reason": "database_unavailable"}
        mode = "TRUNCATE" if truncate else "PASSIVE"
        try:
            with self._lock:
                row = self.conn.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
            return {
                "ok": True,
                "mode": mode,
                "busy": int((row or [0, 0, 0])[0] or 0),
                "log_frames": int((row or [0, 0, 0])[1] or 0),
                "checkpointed_frames": int((row or [0, 0, 0])[2] or 0),
            }
        except Exception as exc:
            logging.exception("Error checkpointing database WAL")
            return {"ok": False, "mode": mode, "reason": str(exc)}

    def get_phase2_readiness(
        self,
        *,
        min_forecasts: int = 300,
        min_settled_non_abstain: int = 100,
        min_distinct_days: int = 14,
        distinct_bucket_hours: int = 24,
        scorecard: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "phase": 2,
            "ready_for_phase3_review": False,
            "execution_eligible": False,
            "orders_submitted": 0,
            "reasons": [],
        }
        if not self.conn:
            result["reasons"] = ["data_store_unavailable"]
            return result
        try:
            bucket_hours = max(1, int(distinct_bucket_hours or 1))
            if bucket_hours == 24:
                bucket_expr_sql = "date(ts, 'unixepoch')"
            else:
                bucket_expr_sql = f"CAST(ts / {float(bucket_hours * 3600):.1f} AS INTEGER)"
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    "SELECT COUNT(*) FROM (SELECT 1 FROM hypothesis_forecasts LIMIT ?)",
                    (int(min_forecasts),),
                )
                forecasts = (c.fetchone() or (0,))[0]
                c.execute(
                    "SELECT COUNT(*) FROM (SELECT 1 FROM hypothesis_forecasts WHERE settled=1 AND abstain=0 LIMIT ?)",
                    (int(min_settled_non_abstain),),
                )
                settled_non_abstain = (c.fetchone() or (0,))[0]
                c.execute(
                    f"SELECT COUNT(*) FROM (SELECT DISTINCT {bucket_expr_sql} AS bucket FROM hypothesis_forecasts LIMIT ?)",
                    (int(min_distinct_days),),
                )
                time_buckets = (c.fetchone() or (0,))[0]
                c.execute("SELECT COUNT(*) FROM (SELECT 1 FROM hypothesis_forecasts WHERE execution_eligible=1 LIMIT 1)")
                execution_violations = (c.fetchone() or (0,))[0]
                c.execute("SELECT COALESCE(SUM(orders_submitted),0), COALESCE(SUM(execution_wired),0) FROM hypothesis_runs")
                orders, execution_wired = c.fetchone() or (0, 0)
            reasons = []
            if int(forecasts or 0) < int(min_forecasts):
                reasons.append("insufficient_forecasts")
            if int(settled_non_abstain or 0) < int(min_settled_non_abstain):
                reasons.append("insufficient_settled_non_abstain_forecasts")
            if int(time_buckets or 0) < int(min_distinct_days):
                reasons.append("insufficient_distinct_research_snapshots")
            if int(execution_violations or 0) or int(execution_wired or 0):
                reasons.append("execution_wiring_violation")
            if int(orders or 0):
                reasons.append("nonzero_orders_submitted")
            if scorecard is None:
                with self._lock:
                    c = self.conn.cursor()
                    c.execute(
                        """
                        SELECT f.model_id, f.hypothesis,
                               COUNT(*) AS settled_trades,
                               AVG(o.net_return_bps) AS mean_net_bps,
                               AVG(o.positive_net) AS win_rate,
                               SUM(o.net_return_bps) AS cumulative_net_bps
                        FROM hypothesis_forecasts f
                        JOIN hypothesis_outcomes o ON o.forecast_id=f.forecast_id
                        WHERE f.settled=1 AND f.abstain=0
                        GROUP BY f.model_id, f.hypothesis
                        """
                    )
                    model_rows = c.fetchall()
                    model_cols = [item[0] for item in c.description]
                models = []
                for row in model_rows:
                    record = dict(zip(model_cols, row))
                    for key in ("mean_net_bps", "win_rate", "cumulative_net_bps"):
                        if record.get(key) is not None:
                            record[key] = round(float(record[key]), 6)
                    record["settled_trades"] = int(record.get("settled_trades") or 0)
                    record["is_baseline"] = str(record.get("model_id") or "").startswith("baseline_")
                    models.append(record)
                scorecard = {
                    "phase": 2,
                    "mode": "hypothesis_research_only_fast_readiness",
                    "models": models,
                    "execution_eligible": False,
                    "orders_submitted": 0,
                }
            primary = [m for m in scorecard.get("models", []) if not m.get("is_baseline") and int(m.get("settled_trades") or 0) > 0]
            baselines = [m for m in scorecard.get("models", []) if m.get("is_baseline") and int(m.get("settled_trades") or 0) > 0]
            best_primary = max((float(m.get("mean_net_bps") or -1e18) for m in primary), default=None)
            best_baseline = max((float(m.get("mean_net_bps") or -1e18) for m in baselines), default=None)
            positive_primary_slices = [
                row for row in (scorecard.get("profitability_slice_posteriors") or [])
                if isinstance(row, dict)
                and not str(row.get("model_id") or "").startswith("baseline_")
                and row.get("lower_bound_net_bps") is not None
                and float(row.get("lower_bound_net_bps") or 0.0) > 0.0
            ]
            best_primary_slice = max(
                (float(row.get("lower_bound_net_bps") or -1e18) for row in positive_primary_slices),
                default=None,
            )
            effective_primary_edge = best_primary
            if best_primary_slice is not None:
                effective_primary_edge = max(
                    float(effective_primary_edge if effective_primary_edge is not None else -1e18),
                    float(best_primary_slice),
                )
            if best_primary is None:
                reasons.append("no_settled_primary_model")
            elif (effective_primary_edge is None or effective_primary_edge <= 0):
                reasons.append("primary_models_not_positive_after_costs")
            if best_baseline is not None and effective_primary_edge is not None and effective_primary_edge <= best_baseline:
                reasons.append("primary_models_do_not_beat_baselines")
            result.update({
                "ready_for_phase3_review": not reasons,
                "forecasts": int(forecasts or 0),
                "settled_non_abstain_forecasts": int(settled_non_abstain or 0),
                "distinct_research_snapshots": int(time_buckets or 0),
                "distinct_snapshot_bucket_hours": int(distinct_bucket_hours or 24),
                "execution_wiring_violations": int(execution_violations or 0) + int(execution_wired or 0),
                "orders_submitted": int(orders or 0),
                "best_primary_model_mean_net_bps": round(float(best_primary), 6) if best_primary is not None else None,
                "best_primary_slice_lower_bound_net_bps": round(float(best_primary_slice), 6) if best_primary_slice is not None else None,
                "primary_edge_source": (
                    "positive_slice_posterior"
                    if best_primary_slice is not None and (best_primary is None or float(best_primary_slice) > float(best_primary))
                    else "model_mean"
                    if best_primary is not None
                    else None
                ),
                "scorecard": scorecard,
                "reasons": reasons,
            })
            return result
        except Exception:
            logging.exception("Error computing Phase-2 readiness")
            result["reasons"] = ["readiness_query_failed"]
            return result

    def simulation_exists(self, simulation_id: str) -> bool:
        if not self.conn or not simulation_id:
            return False
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute("SELECT 1 FROM simulated_orders WHERE simulation_id=? LIMIT 1", (simulation_id,))
                return c.fetchone() is not None
        except Exception:
            logging.exception("Error checking simulation idempotency")
            return False

    def persist_simulation_run(self, payload: Dict[str, Any]) -> bool:
        if not self.conn:
            return False
        run = payload.get("run") or {}
        run_id = run.get("run_id")
        if not run_id:
            return False
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO simulation_runs
                    (run_id, started_ts, completed_ts, status, forecasts_examined,
                     simulations_created, simulations_skipped_existing, completed,
                     rejected, expired, partial_fills, unknown_incidents, dataset_hash,
                     execution_wired, real_orders_submitted, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(run_id) DO UPDATE SET
                      completed_ts=excluded.completed_ts,
                      status=excluded.status,
                      forecasts_examined=excluded.forecasts_examined,
                      simulations_created=excluded.simulations_created,
                      simulations_skipped_existing=excluded.simulations_skipped_existing,
                      completed=excluded.completed,
                      rejected=excluded.rejected,
                      expired=excluded.expired,
                      partial_fills=excluded.partial_fills,
                      unknown_incidents=excluded.unknown_incidents,
                      dataset_hash=excluded.dataset_hash,
                      execution_wired=0,
                      real_orders_submitted=0,
                      payload=excluded.payload
                    """,
                    (
                        run_id,
                        float(run.get("started_at_ms") or 0) / 1000.0,
                        float(run.get("completed_at_ms") or 0) / 1000.0,
                        payload.get("status"),
                        int(run.get("forecasts_examined") or 0),
                        int(run.get("simulations_created") or 0),
                        int(run.get("simulations_skipped_existing") or 0),
                        int(run.get("completed") or 0),
                        int(run.get("rejected") or 0),
                        int(run.get("expired") or 0),
                        int(run.get("partial_fills") or 0),
                        int(run.get("unknown_incidents") or 0),
                        # NOTE: 'simulations' and 'phase2_cycle' are intentionally excluded from the persisted
                        # run payload. Every simulated order is already individually inserted into
                        # simulated_orders/simulated_order_intents/simulated_order_events, and 'phase2_cycle' is a
                        # full verbatim copy of the upstream hypothesis_runs payload (already durably stored there
                        # and reachable via run_id) -- both were pure duplication at the ~500KB-2.5MB/run scale.
                        payload.get("dataset_hash"), 0, 0,
                        json.dumps({k: v for k, v in payload.items() if k not in ("simulations", "phase2_cycle")}),
                    ),
                )
                self.conn.commit()
            return True
        except Exception:
            logging.exception("Error persisting simulation run")
            return False

    def persist_crystal_registry_entry(self, row: Dict[str, Any]) -> bool:
        if not self.conn:
            return False
        crystal_id = str(row.get("crystal_id") or "")
        if not crystal_id:
            return False
        now_ts = float(row.get("updated_ts") or time.time())
        try:
            with self._lock:
                self.conn.execute(
                    """
                    INSERT INTO crystal_registry
                    (crystal_id, created_ts, updated_ts, crystal_family, artifact_class, authority,
                     verification_state, phase_scope, scope_key, symbol, venue, regime_hint, hypothesis,
                     world_state_id, applicability_hash, evidence_strength, drift_status, expires_ts, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(crystal_id) DO UPDATE SET
                      updated_ts=excluded.updated_ts,
                      crystal_family=excluded.crystal_family,
                      artifact_class=excluded.artifact_class,
                      authority=excluded.authority,
                      verification_state=excluded.verification_state,
                      phase_scope=excluded.phase_scope,
                      scope_key=excluded.scope_key,
                      symbol=excluded.symbol,
                      venue=excluded.venue,
                      regime_hint=excluded.regime_hint,
                      hypothesis=excluded.hypothesis,
                      world_state_id=excluded.world_state_id,
                      applicability_hash=excluded.applicability_hash,
                      evidence_strength=excluded.evidence_strength,
                      drift_status=excluded.drift_status,
                      expires_ts=excluded.expires_ts,
                      payload=excluded.payload
                    """,
                    (
                        crystal_id,
                        float(row.get("created_ts") or now_ts),
                        now_ts,
                        row.get("crystal_family"),
                        row.get("artifact_class"),
                        row.get("authority"),
                        row.get("verification_state"),
                        int(row.get("phase_scope") or 0),
                        row.get("scope_key"),
                        row.get("symbol"),
                        row.get("venue"),
                        row.get("regime_hint"),
                        row.get("hypothesis"),
                        row.get("world_state_id"),
                        row.get("applicability_hash"),
                        row.get("evidence_strength"),
                        row.get("drift_status"),
                        row.get("expires_ts"),
                        json.dumps(row, sort_keys=True, default=str),
                    ),
                )
                self.conn.commit()
            return True
        except Exception:
            logging.exception("Error persisting crystal registry entry")
            return False

    def persist_inference_rung(self, row: Dict[str, Any]) -> bool:
        if not self.conn:
            return False
        rung_id = str(row.get("rung_id") or "")
        if not rung_id:
            return False
        try:
            with self._lock:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO inference_rung_ledger
                    (rung_id, created_ts, phase_scope, run_id, forecast_id, simulation_id, symbol, venue,
                     model_id, hypothesis, regime_hint, symbol_class, cohort_bucket, selected_rung,
                     candidate_rungs, selected_priority, expected_net_bps, probability_positive_net,
                     cost_bps, authority_ceiling, outcome_status, outcome_net_bps, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        rung_id,
                        float(row.get("created_ts") or time.time()),
                        int(row.get("phase_scope") or 0),
                        row.get("run_id"),
                        row.get("forecast_id"),
                        row.get("simulation_id"),
                        row.get("symbol"),
                        row.get("venue"),
                        row.get("model_id"),
                        row.get("hypothesis"),
                        row.get("regime_hint"),
                        row.get("symbol_class"),
                        row.get("cohort_bucket"),
                        row.get("selected_rung"),
                        json.dumps(row.get("candidate_rungs") or []),
                        row.get("selected_priority"),
                        row.get("expected_net_bps"),
                        row.get("probability_positive_net"),
                        row.get("cost_bps"),
                        row.get("authority_ceiling"),
                        row.get("outcome_status"),
                        row.get("outcome_net_bps"),
                        json.dumps(row, sort_keys=True, default=str),
                    ),
                )
                self.conn.commit()
            return True
        except Exception:
            logging.exception("Error persisting inference rung")
            return False

    def get_crystal_registry_snapshot(self, limit: int = 100, *, crystal_family: Optional[str] = None) -> Dict[str, Any]:
        if not self.conn:
            return {"crystals": [], "counts": {}}
        try:
            with self._lock:
                c = self.conn.cursor()
                if crystal_family:
                    c.execute(
                        "SELECT payload FROM crystal_registry WHERE crystal_family=? ORDER BY updated_ts DESC LIMIT ?",
                        (str(crystal_family), int(limit or 100)),
                    )
                else:
                    c.execute("SELECT payload FROM crystal_registry ORDER BY updated_ts DESC LIMIT ?", (int(limit or 100),))
                rows = [json.loads(item[0]) for item in c.fetchall()]
                c.execute(
                    "SELECT crystal_family, COUNT(*) FROM crystal_registry GROUP BY crystal_family ORDER BY crystal_family ASC"
                )
                counts = {str(family or "unknown"): int(count or 0) for family, count in c.fetchall()}
            return {"crystals": rows, "counts": counts, "total": sum(counts.values())}
        except Exception:
            logging.exception("Error reading crystal registry snapshot")
            return {"crystals": [], "counts": {}, "error": "snapshot_failed"}

    def get_crystal_registry_overview(self, *, phase_scope: Optional[int] = None) -> Dict[str, Any]:
        if not self.conn:
            return {"counts": {}, "total": 0, "latest_updated_ts": None}
        try:
            with self._lock:
                c = self.conn.cursor()
                params: list[Any] = []
                where = ""
                if phase_scope is not None:
                    where = "WHERE phase_scope=?"
                    params.append(int(phase_scope))
                c.execute(
                    f"SELECT crystal_family, COUNT(*) FROM crystal_registry {where} GROUP BY crystal_family ORDER BY crystal_family ASC",
                    tuple(params),
                )
                counts = {str(family or "unknown"): int(count or 0) for family, count in c.fetchall()}
                c.execute(f"SELECT MAX(updated_ts) FROM crystal_registry {where}", tuple(params))
                latest_updated_ts = c.fetchone()[0]
            return {
                "counts": counts,
                "total": sum(counts.values()),
                "latest_updated_ts": float(latest_updated_ts) if latest_updated_ts is not None else None,
            }
        except Exception:
            logging.exception("Error reading crystal registry overview")
            return {"counts": {}, "total": 0, "latest_updated_ts": None, "error": "overview_failed"}

    def get_inference_rung_summary(self, limit: int = 200, *, phase_scope: Optional[int] = None) -> Dict[str, Any]:
        if not self.conn:
            return {"rows": [], "by_rung": {}, "by_outcome": {}}
        try:
            with self._lock:
                c = self.conn.cursor()
                if phase_scope is not None:
                    c.execute(
                        "SELECT payload FROM inference_rung_ledger WHERE phase_scope=? ORDER BY created_ts DESC LIMIT ?",
                        (int(phase_scope), int(limit or 200)),
                    )
                else:
                    c.execute("SELECT payload FROM inference_rung_ledger ORDER BY created_ts DESC LIMIT ?", (int(limit or 200),))
                rows = [json.loads(item[0]) for item in c.fetchall()]
            by_rung: Dict[str, int] = {}
            by_outcome: Dict[str, int] = {}
            for row in rows:
                by_rung[str(row.get("selected_rung") or "unknown")] = by_rung.get(str(row.get("selected_rung") or "unknown"), 0) + 1
                by_outcome[str(row.get("outcome_status") or "unknown")] = by_outcome.get(str(row.get("outcome_status") or "unknown"), 0) + 1
            return {"rows": rows, "by_rung": by_rung, "by_outcome": by_outcome, "total": len(rows)}
        except Exception:
            logging.exception("Error reading inference rung summary")
            return {"rows": [], "by_rung": {}, "by_outcome": {}, "error": "summary_failed"}

    def get_inference_rung_overview(self, *, phase_scope: Optional[int] = None) -> Dict[str, Any]:
        if not self.conn:
            return {"total": 0, "by_rung": {}, "by_outcome": {}, "latest_created_ts": None}
        try:
            with self._lock:
                c = self.conn.cursor()
                params: list[Any] = []
                where = ""
                if phase_scope is not None:
                    where = "WHERE phase_scope=?"
                    params.append(int(phase_scope))
                c.execute(
                    f"SELECT selected_rung, COUNT(*) FROM inference_rung_ledger {where} GROUP BY selected_rung ORDER BY selected_rung ASC",
                    tuple(params),
                )
                by_rung = {str(rung or "unknown"): int(count or 0) for rung, count in c.fetchall()}
                c.execute(
                    f"SELECT outcome_status, COUNT(*) FROM inference_rung_ledger {where} GROUP BY outcome_status ORDER BY outcome_status ASC",
                    tuple(params),
                )
                by_outcome = {str(outcome or "unknown"): int(count or 0) for outcome, count in c.fetchall()}
                c.execute(f"SELECT MAX(created_ts) FROM inference_rung_ledger {where}", tuple(params))
                latest_created_ts = c.fetchone()[0]
            return {
                "total": int(sum(by_outcome.values()) or sum(by_rung.values()) or 0),
                "by_rung": by_rung,
                "by_outcome": by_outcome,
                "latest_created_ts": float(latest_created_ts) if latest_created_ts is not None else None,
            }
        except Exception:
            logging.exception("Error reading inference rung overview")
            return {"total": 0, "by_rung": {}, "by_outcome": {}, "latest_created_ts": None, "error": "overview_failed"}

    def get_crystal_registry_rows(
        self,
        *,
        crystal_family: Optional[str] = None,
        symbol: Optional[str] = None,
        regime_hint: Optional[str] = None,
        limit: int = 250,
    ) -> list[Dict[str, Any]]:
        if not self.conn:
            return []
        try:
            clauses = []
            params: list[Any] = []
            if crystal_family:
                clauses.append("crystal_family=?")
                params.append(str(crystal_family))
            if symbol:
                clauses.append("symbol=?")
                params.append(str(symbol))
            if regime_hint:
                clauses.append("regime_hint=?")
                params.append(str(regime_hint))
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            params.append(int(limit or 250))
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    f"SELECT payload FROM crystal_registry {where} ORDER BY updated_ts DESC LIMIT ?",
                    tuple(params),
                )
                rows = [json.loads(item[0]) for item in c.fetchall()]
            return rows
        except Exception:
            logging.exception("Error reading crystal registry rows")
            return []

    def persist_execution_simulation(self, row: Dict[str, Any]) -> bool:
        """Persist a Phase-3 simulation without touching live order tables."""
        if not self.conn:
            return False
        simulation_id = row.get("simulation_id")
        intent = row.get("intent") or {}
        if not simulation_id or not intent.get("intent_id"):
            return False
        if row.get("execution_wired") or int(row.get("real_orders_submitted") or 0):
            raise ValueError("Phase-3 simulation attempted to claim live execution")
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT OR IGNORE INTO simulated_order_intents
                    (intent_id, simulation_id, forecast_id, model_id, venue, symbol, side,
                     order_policy, scenario, quantity, notional_usd, reference_price,
                     limit_price, risk_budget_usd, stop_distance_bps, horizon_seconds,
                     created_ts, spot_executable, live_eligible, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        intent.get("intent_id"), simulation_id, row.get("forecast_id"),
                        row.get("model_id"), row.get("venue"), row.get("symbol"), intent.get("side"),
                        row.get("order_policy"), row.get("scenario"), intent.get("quantity"),
                        intent.get("notional_usd"), intent.get("reference_price"), intent.get("limit_price"),
                        intent.get("risk_budget_usd"), intent.get("stop_distance_bps"),
                        intent.get("horizon_seconds"), intent.get("created_ts"),
                        1 if intent.get("spot_executable") else 0, 0, json.dumps(intent),
                    ),
                )
                c.execute(
                    """
                    INSERT OR IGNORE INTO simulated_orders
                    (simulation_id, run_id, forecast_id, model_id, hypothesis, venue, symbol,
                     direction, order_policy, scenario, fidelity, seed, status, terminal_state,
                     started_ts, completed_ts, fill_ratio, quantity_requested, quantity_filled,
                     notional_requested_usd, entry_reference_price, exit_reference_price,
                     entry_fill_price, exit_fill_price, gross_return_bps, net_return_bps,
                     profitable_after_costs, spot_executable, execution_wired,
                     real_orders_submitted, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        simulation_id, row.get("run_id"), row.get("forecast_id"), row.get("model_id"),
                        row.get("hypothesis"), row.get("venue"), row.get("symbol"), row.get("direction"),
                        row.get("order_policy"), row.get("scenario"), row.get("fidelity"), row.get("seed"),
                        row.get("status"), row.get("terminal_state"), row.get("started_ts"), row.get("completed_ts"),
                        row.get("fill_ratio"), row.get("quantity_requested"), row.get("quantity_filled"),
                        row.get("notional_requested_usd"), row.get("entry_reference_price"), row.get("exit_reference_price"),
                        row.get("entry_fill_price"), row.get("exit_fill_price"), row.get("gross_return_bps"),
                        row.get("net_return_bps"), 1 if row.get("profitable_after_costs") else 0,
                        1 if row.get("spot_executable") else 0, 0, 0, json.dumps(row),
                    ),
                )
                if c.rowcount == 0:
                    self.conn.commit()
                    return True
                for event in row.get("events") or []:
                    c.execute(
                        """
                        INSERT OR IGNORE INTO simulated_order_events
                        (simulation_id, sequence, state, ts, reason, payload)
                        VALUES (?,?,?,?,?,?)
                        """,
                        (simulation_id, int(event.get("sequence") or 0), event.get("state"),
                         event.get("ts"), event.get("reason"), json.dumps(event)),
                    )
                for fill in row.get("fills") or []:
                    c.execute(
                        """
                        INSERT OR IGNORE INTO simulated_fills
                        (fill_id, simulation_id, leg, side, quantity, price, notional_usd,
                         fee_usd, liquidity, ts, payload)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (fill.get("fill_id"), simulation_id, fill.get("leg"), fill.get("side"),
                         fill.get("quantity"), fill.get("price"), fill.get("notional_usd"),
                         fill.get("fee_usd"), fill.get("liquidity"), fill.get("ts"), json.dumps(fill)),
                    )
                costs = row.get("costs") or {}
                c.execute(
                    """
                    INSERT OR REPLACE INTO simulated_cost_attribution
                    (simulation_id, forecast_gross_bps, market_gross_bps, entry_spread_bps,
                     exit_spread_bps, entry_impact_bps, exit_impact_bps, entry_latency_bps,
                     exit_latency_bps, fee_bps, missed_fill_opportunity_bps,
                     stop_slippage_bps, total_cost_bps, net_bps, gross_signal_bps,
                     entry_fee_bps, exit_fee_bps, maker_fee_bps, taker_fee_bps,
                     failed_fill_cost_bps, chase_cost_bps, cost_schema_version,
                     fee_source, fee_verified, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (simulation_id, costs.get("forecast_gross_bps"), costs.get("market_gross_bps"),
                     costs.get("entry_spread_bps"), costs.get("exit_spread_bps"), costs.get("entry_impact_bps"),
                     costs.get("exit_impact_bps"), costs.get("entry_latency_bps"), costs.get("exit_latency_bps"),
                     costs.get("fee_bps"), costs.get("missed_fill_opportunity_bps"), costs.get("stop_slippage_bps"),
                     costs.get("total_cost_bps"), costs.get("net_bps"), costs.get("gross_signal_bps"),
                     costs.get("entry_fee_bps"), costs.get("exit_fee_bps"), costs.get("maker_fee_bps"),
                     costs.get("taker_fee_bps"), costs.get("failed_fill_cost_bps"), costs.get("chase_cost_bps"),
                     costs.get("cost_schema_version"), costs.get("fee_source"),
                     1 if costs.get("fee_verified") else 0, json.dumps(costs)),
                )
                c.execute(
                    """
                    INSERT OR REPLACE INTO simulated_positions
                    (simulation_id, symbol, direction, quantity, entry_price, exit_price,
                     status, gross_return_bps, net_return_bps, opened_ts, closed_ts, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (simulation_id, row.get("symbol"), row.get("direction"), row.get("quantity_filled"),
                     row.get("entry_fill_price"), row.get("exit_fill_price"), row.get("terminal_state"),
                     row.get("gross_return_bps"), row.get("net_return_bps"), row.get("started_ts"),
                     row.get("completed_ts"), json.dumps({"fidelity": row.get("fidelity")})),
                )
                for index, incident in enumerate(row.get("incidents") or []):
                    incident_id = hashlib.sha256(
                        f"{simulation_id}:{index}:{incident.get('type')}".encode()
                    ).hexdigest()
                    c.execute(
                        """
                        INSERT OR IGNORE INTO simulation_incidents
                        (incident_id, simulation_id, incident_type, severity, symbol_halted,
                         automatic_recovery, payload)
                        VALUES (?,?,?,?,?,?,?)
                        """,
                        (incident_id, simulation_id, incident.get("type"), incident.get("severity"),
                         1 if incident.get("symbol_halted") else 0,
                         1 if incident.get("automatic_recovery") else 0, json.dumps(incident)),
                    )
                self.conn.commit()
            return True
        except Exception:
            try:
                self.conn.rollback()
            except Exception:
                pass
            logging.exception("Error persisting execution simulation")
            return False

    def get_phase3_forecast_candidates(self, limit: int = 100) -> list:
        if not self.conn:
            return []

        try:
            min_expected_net_bps = 0.0
            min_probability = 0.0
            min_historical_realized_net_bps = float("-inf")
            min_historical_samples = 0
            prefer_research_only = False
            max_simulations_per_forecast = 20
            min_regime_historical_realized_net_bps = float("-inf")
            min_regime_historical_samples = 0
            prefer_regime_alignment = True
            min_cost_survival_ratio = 1.0
            unique_per_symbol_cohort = True
            recency_window = 8
            failure_feedback_enabled = True
            failure_feedback_lookback = 12
            failure_feedback_penalty_scale = 1.0
            frontier_min_settled_trades = 5
            frontier_min_mean_realized_net_bps = 2.5
            prefer_profitability_frontier = True
            prefer_exact_reuse_candidates = True
            exact_reuse_priority_boost = 4.0
            prefer_symbol_class_specialization = True
            min_symbol_class_historical_realized_net_bps = float("-inf")
            min_symbol_class_historical_samples = 0
            regime_reentry_recent_window = 4
            regime_reentry_min_samples = 3
            regime_reentry_min_mean_realized_net_bps = 2.0
            shrinkage_prior_strength = 12.0
            reserve_cash_pct = 0.70
            max_candidate_fraction = 0.15
            min_expected_growth_bps = 0.25
            failure_veto_enabled = True
            failure_veto_min_matched_simulations = 4
            failure_veto_dominant_cause_rate = 0.50
            failure_veto_max_recent_slice_bps = 1.0
            crystal_prior_enabled = True
            crystal_recent_window_hours = 48.0
            crystal_positive_priority_boost = 2.5
            crystal_negative_penalty_scale = 3.0
            candidate_pool_multiplier = 8
            candidate_history_limit = 1000
            worker_counterfactual_simulation_enabled = True
            candidate_model_id = ""
            candidate_model_prefix = ""
            try:
                if self.coordinator and hasattr(self.coordinator, "cfg"):
                    cfg = self.coordinator.cfg
                    min_expected_net_bps = float(getattr(cfg, "phase3_min_expected_net_bps", 0.0) or 0.0)
                    min_probability = float(getattr(cfg, "phase3_min_probability_positive_net", 0.0) or 0.0)
                    min_historical_realized_net_bps = float(
                        getattr(cfg, "phase3_min_historical_realized_net_bps", float("-inf")) or float("-inf")
                    )
                    min_historical_samples = max(
                        0,
                        int(getattr(cfg, "phase3_min_historical_samples", 0) or 0),
                    )
                    prefer_research_only = bool(getattr(cfg, "phase3_prefer_research_candidates", False))
                    max_simulations_per_forecast = max(
                        1,
                        int(getattr(cfg, "phase3_max_simulations_per_forecast", 20) or 20),
                    )
                    min_regime_historical_realized_net_bps = float(
                        getattr(
                            cfg,
                            "phase3_min_regime_historical_realized_net_bps",
                            min_historical_realized_net_bps,
                        ) or min_historical_realized_net_bps
                    )
                    min_regime_historical_samples = max(
                        0,
                        int(getattr(cfg, "phase3_min_regime_historical_samples", min_historical_samples) or min_historical_samples),
                    )
                    prefer_regime_alignment = bool(getattr(cfg, "phase3_prefer_regime_alignment", True))
                    frontier_min_settled_trades = max(
                        1,
                        int(getattr(cfg, "phase3_frontier_min_settled_trades", 5) or 5),
                    )
                    frontier_min_mean_realized_net_bps = float(
                        getattr(cfg, "phase3_frontier_min_mean_realized_net_bps", 2.5) or 2.5
                    )
                    prefer_profitability_frontier = bool(getattr(cfg, "phase3_prefer_profitability_frontier", True))
                    prefer_exact_reuse_candidates = bool(
                        getattr(cfg, "phase3_prefer_exact_reuse_candidates", True)
                    )
                    exact_reuse_priority_boost = float(
                        getattr(cfg, "phase3_exact_reuse_priority_boost", 4.0) or 4.0
                    )
                    prefer_symbol_class_specialization = bool(
                        getattr(cfg, "phase3_prefer_symbol_class_specialization", True)
                    )
                    min_symbol_class_historical_realized_net_bps = float(
                        getattr(
                            cfg,
                            "phase3_min_symbol_class_historical_realized_net_bps",
                            float("-inf"),
                        ) or float("-inf")
                    )
                    min_symbol_class_historical_samples = max(
                        0,
                        int(getattr(cfg, "phase3_min_symbol_class_historical_samples", 0) or 0),
                    )
                    min_cost_survival_ratio = float(getattr(cfg, "phase3_min_cost_survival_ratio", 1.0) or 1.0)
                    unique_per_symbol_cohort = bool(getattr(cfg, "phase3_unique_per_symbol_cohort", True))
                    recency_window = max(1, int(getattr(cfg, "phase3_recency_window", 8) or 8))
                    failure_feedback_enabled = bool(getattr(cfg, "phase3_failure_feedback_enabled", True))
                    failure_feedback_lookback = max(1, int(getattr(cfg, "phase3_failure_feedback_lookback", 12) or 12))
                    failure_feedback_penalty_scale = float(getattr(cfg, "phase3_failure_feedback_penalty_scale", 1.0) or 1.0)
                    failure_veto_enabled = bool(getattr(cfg, "phase3_failure_veto_enabled", True))
                    failure_veto_min_matched_simulations = max(
                        1,
                        int(getattr(cfg, "phase3_failure_veto_min_matched_simulations", 4) or 4),
                    )
                    failure_veto_dominant_cause_rate = float(
                        getattr(cfg, "phase3_failure_veto_dominant_cause_rate", 0.50) or 0.50
                    )
                    failure_veto_max_recent_slice_bps = float(
                        getattr(cfg, "phase3_failure_veto_max_recent_slice_bps", 1.0) or 1.0
                    )
                    crystal_prior_enabled = bool(getattr(cfg, "phase3_crystal_prior_enabled", True))
                    crystal_recent_window_hours = float(
                        getattr(cfg, "phase3_crystal_recent_window_hours", 48.0) or 48.0
                    )
                    crystal_positive_priority_boost = float(
                        getattr(cfg, "phase3_crystal_positive_priority_boost", 2.5) or 2.5
                    )
                    crystal_negative_penalty_scale = float(
                        getattr(cfg, "phase3_crystal_negative_penalty_scale", 3.0) or 3.0
                    )
                    candidate_pool_multiplier = max(
                        1, int(getattr(cfg, "phase3_candidate_pool_multiplier", 8) or 8)
                    )
                    candidate_history_limit = max(
                        100, int(getattr(cfg, "phase3_candidate_history_limit", 1000) or 1000)
                    )
                    worker_counterfactual_simulation_enabled = bool(
                        getattr(cfg, "phase3_worker_counterfactual_simulation_enabled", True)
                    )
                    candidate_model_id = str(getattr(cfg, "phase3_candidate_model_id", "") or "").strip()
                    candidate_model_prefix = str(getattr(cfg, "phase3_candidate_model_prefix", "") or "").strip()
                    regime_reentry_recent_window = max(
                        2,
                        int(getattr(cfg, "phase3_regime_reentry_recent_window", 4) or 4),
                    )
                    regime_reentry_min_samples = max(
                        2,
                        int(getattr(cfg, "phase3_regime_reentry_min_samples", 3) or 3),
                    )
                    regime_reentry_min_mean_realized_net_bps = float(
                        getattr(cfg, "phase3_regime_reentry_min_mean_realized_net_bps", 2.0) or 2.0
                    )
                    shrinkage_prior_strength = float(
                        getattr(cfg, "phase3_shrinkage_prior_strength", 12.0) or 12.0
                    )
                    reserve_cash_pct = float(
                        getattr(cfg, "phase3_allocator_reserve_cash_pct", 0.70) or 0.70
                    )
                    max_candidate_fraction = float(
                        getattr(cfg, "phase3_allocator_max_candidate_fraction", 0.15) or 0.15
                    )
                    min_expected_growth_bps = float(
                        getattr(cfg, "phase3_allocator_min_expected_growth_bps", 0.25) or 0.25
                    )
            except Exception:
                pass
            meta = {
                "requested_limit": int(limit or 100),
                "raw_pool_size": 0,
                "selected_count": 0,
                "filters": {
                    "min_expected_net_bps": float(min_expected_net_bps),
                    "min_probability_positive_net": float(min_probability),
                    "min_historical_realized_net_bps": (
                        None if math.isinf(min_historical_realized_net_bps) else float(min_historical_realized_net_bps)
                    ),
                    "min_historical_samples": int(min_historical_samples),
                    "min_regime_historical_realized_net_bps": (
                        None
                        if math.isinf(min_regime_historical_realized_net_bps)
                        else float(min_regime_historical_realized_net_bps)
                    ),
                    "min_regime_historical_samples": int(min_regime_historical_samples),
                    "prefer_research_candidates": bool(prefer_research_only),
                    "prefer_regime_alignment": bool(prefer_regime_alignment),
                    "frontier_min_settled_trades": int(frontier_min_settled_trades),
                    "frontier_min_mean_realized_net_bps": float(frontier_min_mean_realized_net_bps),
                    "prefer_profitability_frontier": bool(prefer_profitability_frontier),
                    "prefer_exact_reuse_candidates": bool(prefer_exact_reuse_candidates),
                    "exact_reuse_priority_boost": float(exact_reuse_priority_boost),
                    "prefer_symbol_class_specialization": bool(prefer_symbol_class_specialization),
                    "min_symbol_class_historical_realized_net_bps": (
                        None
                        if math.isinf(min_symbol_class_historical_realized_net_bps)
                        else float(min_symbol_class_historical_realized_net_bps)
                    ),
                    "min_symbol_class_historical_samples": int(min_symbol_class_historical_samples),
                    "regime_reentry_recent_window": int(regime_reentry_recent_window),
                    "regime_reentry_min_samples": int(regime_reentry_min_samples),
                    "regime_reentry_min_mean_realized_net_bps": float(regime_reentry_min_mean_realized_net_bps),
                    "shrinkage_prior_strength": float(shrinkage_prior_strength),
                    "min_cost_survival_ratio": float(min_cost_survival_ratio),
                    "unique_per_symbol_cohort": bool(unique_per_symbol_cohort),
                    "max_simulations_per_forecast": int(max_simulations_per_forecast),
                    "recency_window": int(recency_window),
                    "failure_feedback_enabled": bool(failure_feedback_enabled),
                    "failure_feedback_lookback": int(failure_feedback_lookback),
                    "failure_feedback_penalty_scale": float(failure_feedback_penalty_scale),
                    "failure_veto_enabled": bool(failure_veto_enabled),
                    "failure_veto_min_matched_simulations": int(failure_veto_min_matched_simulations),
                    "failure_veto_dominant_cause_rate": float(failure_veto_dominant_cause_rate),
                    "failure_veto_max_recent_slice_bps": float(failure_veto_max_recent_slice_bps),
                    "crystal_prior_enabled": bool(crystal_prior_enabled),
                    "crystal_recent_window_hours": float(crystal_recent_window_hours),
                    "crystal_positive_priority_boost": float(crystal_positive_priority_boost),
                    "crystal_negative_penalty_scale": float(crystal_negative_penalty_scale),
                    "candidate_pool_multiplier": int(candidate_pool_multiplier),
                    "candidate_history_limit": int(candidate_history_limit),
                    "allocator_reserve_cash_pct": float(reserve_cash_pct),
                    "allocator_max_candidate_fraction": float(max_candidate_fraction),
                    "allocator_min_expected_growth_bps": float(min_expected_growth_bps),
                    "worker_counterfactual_simulation_enabled": bool(worker_counterfactual_simulation_enabled),
                    "candidate_model_id": candidate_model_id or None,
                    "candidate_model_prefix": candidate_model_prefix or None,
                },
                "rejections": {
                    "expected_net_below_gate": 0,
                    "probability_below_gate": 0,
                    "historical_edge_below_gate": 0,
                    "insufficient_history": 0,
                    "regime_edge_below_gate": 0,
                    "insufficient_regime_history": 0,
                    "symbol_class_edge_below_gate": 0,
                    "insufficient_symbol_class_history": 0,
                    "cost_survival_below_gate": 0,
                    "failure_cause_veto": 0,
                    "walk_forward_calibration_refused": 0,
                    "worker_counterfactual_disabled": 0,
                },
            }
            with self._lock:
                c = self.conn.cursor()
                candidate_clauses = [
                    "f.settled=1",
                    "f.abstain=0",
                    """
                      (
                          SELECT COUNT(*) FROM simulated_orders s
                          WHERE s.forecast_id=f.forecast_id
                      ) < ?
                    """,
                ]
                candidate_params: list[Any] = [int(max_simulations_per_forecast)]
                if candidate_model_id:
                    candidate_clauses.append("f.model_id=?")
                    candidate_params.append(candidate_model_id)
                elif candidate_model_prefix:
                    candidate_clauses.append("f.model_id>=?")
                    candidate_clauses.append("f.model_id<?")
                    candidate_params.extend([candidate_model_prefix, _prefix_upper_bound(candidate_model_prefix)])
                candidate_params.append(
                    max(int(limit or 100) * int(candidate_pool_multiplier), int(limit or 100))
                )
                c.execute(
                    f"""
                    SELECT f.forecast_id, f.ts, f.target_ts, f.venue, f.symbol, f.model_id,
                           f.hypothesis, f.horizon_seconds, f.direction, f.entry_price,
                           f.probability_positive_net, f.expected_move_bps, f.expected_cost_bps,
                           f.expected_net_bps, f.raw_score, f.payload,
                           o.settled_ts, o.exit_price, o.directional_return_bps, o.net_return_bps
                    FROM hypothesis_forecasts f
                    JOIN hypothesis_outcomes o ON o.forecast_id=f.forecast_id
                    WHERE {' AND '.join(candidate_clauses)}
                    ORDER BY o.settled_ts DESC LIMIT ?
                    """,
                    tuple(candidate_params),
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
                meta["raw_pool_size"] = len(rows)
                crystal_cutoff_ts = time.time() - max(1.0, float(crystal_recent_window_hours)) * 3600.0
                thesis_crystals = self.get_crystal_registry_rows(
                    crystal_family="thesis_capability",
                    limit=max(int(limit or 100) * 6, 250),
                ) if crystal_prior_enabled else []
                negative_crystals = self.get_crystal_registry_rows(
                    crystal_family="negative_capability",
                    limit=max(int(limit or 100) * 6, 250),
                ) if crystal_prior_enabled else []
                global_realized_prior = (
                    sum(float(row[19]) for row in rows if row[19] is not None) / max(1, sum(1 for row in rows if row[19] is not None))
                    if rows else 0.0
                )
                out = []
                for raw in rows:
                    record = dict(zip(cols, raw))
                    try:
                        record["forecast_payload"] = json.loads(record.pop("payload") or "{}")
                    except Exception:
                        record["forecast_payload"] = {}
                    record["forecast_ts"] = record.pop("ts", None)
                    reuse_context = (
                        record.get("forecast_payload", {}).get("reuse_context")
                        if isinstance(record.get("forecast_payload"), dict)
                        else {}
                    )
                    if not isinstance(reuse_context, dict):
                        reuse_context = {}
                    record["reuse_context"] = reuse_context
                    record["research_route"] = str(
                        (
                            record.get("forecast_payload", {}).get("research_route")
                            if isinstance(record.get("forecast_payload"), dict)
                            else ""
                        )
                        or "full_competition"
                    )
                    record["research_route_priority"] = int(
                        (
                            record.get("forecast_payload", {}).get("research_route_priority")
                            if isinstance(record.get("forecast_payload"), dict)
                            else 0
                        )
                        or 0
                    )
                    calibration = (
                        record.get("forecast_payload", {}).get("walk_forward_calibration")
                        if isinstance(record.get("forecast_payload"), dict)
                        else {}
                    )
                    record["walk_forward_calibration"] = calibration if isinstance(calibration, dict) else {}
                    record["reuse_candidate"] = bool(
                        str(reuse_context.get("decision") or "") == "exact_reuse_candidate"
                    )
                    record["reuse_mean_realized_net_bps"] = (
                        float(reuse_context.get("mean_realized_net_bps"))
                        if reuse_context.get("mean_realized_net_bps") is not None
                        else None
                    )
                    record["reuse_sample_count"] = int(reuse_context.get("sample_count") or 0)
                    c.execute(
                        """
                        SELECT payload FROM observation_snapshots
                        WHERE symbol=? AND ts<=? ORDER BY ts DESC LIMIT 1
                        """,
                        (record.get("symbol"), record.get("forecast_ts")),
                    )
                    obs = c.fetchone()
                    try:
                        record["entry_observation"] = json.loads(obs[0]) if obs and obs[0] else {}
                    except Exception:
                        record["entry_observation"] = {}
                    record["regime_hint"] = self._phase3_regime_hint(record)
                    c.execute(
                        """
                        SELECT COUNT(*), AVG(COALESCE(o2.net_return_bps, 0.0))
                        FROM hypothesis_forecasts f2
                        JOIN hypothesis_outcomes o2 ON o2.forecast_id=f2.forecast_id
                        WHERE f2.model_id=?
                          AND f2.symbol=?
                          AND f2.abstain=0
                          AND f2.settled=1
                          AND f2.forecast_id<>?
                          AND f2.ts < ?
                          AND o2.settled_ts <= ?
                        ORDER BY o2.settled_ts ASC
                        """,
                        (
                            record.get("model_id"),
                            record.get("symbol"),
                            record.get("forecast_id"),
                            record.get("forecast_ts"),
                            record.get("forecast_ts"),
                        ),
                    )
                    history = c.fetchone() or (0, None)
                    record["historical_samples"] = int(history[0] or 0)
                    record["historical_mean_net_bps"] = (
                        float(history[1]) if history[1] is not None else None
                    )
                    record["shrunk_historical_mean_net_bps"] = _shrunk_mean(
                        record["historical_mean_net_bps"],
                        record["historical_samples"],
                        global_realized_prior,
                        shrinkage_prior_strength,
                    )
                    c.execute(
                        """
                        SELECT o2.net_return_bps
                        FROM hypothesis_forecasts f2
                        JOIN hypothesis_outcomes o2 ON o2.forecast_id=f2.forecast_id
                        WHERE f2.model_id=?
                          AND f2.symbol=?
                          AND f2.abstain=0
                          AND f2.settled=1
                          AND f2.forecast_id<>?
                          AND f2.ts < ?
                          AND o2.settled_ts <= ?
                        ORDER BY o2.settled_ts DESC
                        LIMIT ?
                        """,
                        (
                            record.get("model_id"),
                            record.get("symbol"),
                            record.get("forecast_id"),
                            record.get("forecast_ts"),
                            record.get("forecast_ts"),
                            int(recency_window),
                        ),
                    )
                    recent_history_samples = [float(item[0] or 0.0) for item in c.fetchall()]
                    record["recent_historical_samples"] = len(recent_history_samples)
                    record["recent_historical_mean_net_bps"] = (
                        sum(recent_history_samples) / len(recent_history_samples) if recent_history_samples else None
                    )
                    target_regime = record.get("regime_hint") or _PHASE3_REGIME_FALLBACK
                    c.execute(
                        """
                        SELECT f2.payload, o2.net_return_bps
                        FROM hypothesis_forecasts f2
                        JOIN hypothesis_outcomes o2 ON o2.forecast_id=f2.forecast_id
                        WHERE f2.model_id=?
                          AND f2.symbol=?
                          AND f2.abstain=0
                          AND f2.settled=1
                          AND f2.forecast_id<>?
                          AND f2.ts < ?
                          AND o2.settled_ts <= ?
                        ORDER BY o2.settled_ts ASC
                        """,
                        (
                            record.get("model_id"),
                            record.get("symbol"),
                            record.get("forecast_id"),
                            record.get("forecast_ts"),
                            record.get("forecast_ts"),
                        ),
                    )
                    regime_samples = []
                    for payload_raw, net_bps in c.fetchall():
                        sample_regime = self._phase3_regime_hint_from_payload(payload_raw)
                        if sample_regime == target_regime:
                            regime_samples.append(float(net_bps or 0.0))
                    record["regime_historical_samples"] = len(regime_samples)
                    record["regime_historical_mean_net_bps"] = (
                        sum(regime_samples) / len(regime_samples) if regime_samples else None
                    )
                    record["shrunk_regime_historical_mean_net_bps"] = _shrunk_mean(
                        record["regime_historical_mean_net_bps"],
                        record["regime_historical_samples"],
                        record["shrunk_historical_mean_net_bps"],
                        shrinkage_prior_strength,
                    )
                    recent_regime_samples = regime_samples[-int(regime_reentry_recent_window):]
                    record["recent_regime_historical_samples"] = len(recent_regime_samples)
                    record["recent_regime_historical_mean_net_bps"] = (
                        sum(recent_regime_samples) / len(recent_regime_samples) if recent_regime_samples else None
                    )
                    record["shrunk_recent_regime_historical_mean_net_bps"] = _shrunk_mean(
                        record["recent_regime_historical_mean_net_bps"],
                        record["recent_regime_historical_samples"],
                        record["shrunk_regime_historical_mean_net_bps"],
                        max(1.0, shrinkage_prior_strength * 0.5),
                    )
                    record["regime_reentry_eligible"] = bool(
                        recent_regime_samples
                        and len(recent_regime_samples) >= int(regime_reentry_min_samples)
                        and (sum(recent_regime_samples) / len(recent_regime_samples))
                        >= float(regime_reentry_min_mean_realized_net_bps)
                    )
                    c.execute(
                        """
                        SELECT f2.payload, o2.net_return_bps
                        FROM hypothesis_forecasts f2
                        JOIN hypothesis_outcomes o2 ON o2.forecast_id=f2.forecast_id
                        WHERE f2.model_id=?
                          AND f2.abstain=0
                          AND f2.settled=1
                          AND f2.forecast_id<>?
                          AND f2.ts < ?
                          AND o2.settled_ts <= ?
                        ORDER BY o2.settled_ts DESC
                        LIMIT ?
                        """,
                        (
                            record.get("model_id"),
                            record.get("forecast_id"),
                            record.get("forecast_ts"),
                            record.get("forecast_ts"),
                            int(candidate_history_limit),
                        ),
                    )
                    frontier_samples = []
                    for payload_raw, net_bps in c.fetchall():
                        sample_regime = self._phase3_regime_hint_from_payload(payload_raw)
                        if sample_regime == target_regime:
                            frontier_samples.append(float(net_bps or 0.0))
                    frontier_samples.reverse()
                    record["frontier_regime_samples"] = len(frontier_samples)
                    record["frontier_regime_mean_net_bps"] = (
                        sum(frontier_samples) / len(frontier_samples) if frontier_samples else None
                    )
                    record["shrunk_frontier_regime_mean_net_bps"] = _shrunk_mean(
                        record["frontier_regime_mean_net_bps"],
                        record["frontier_regime_samples"],
                        record["shrunk_regime_historical_mean_net_bps"],
                        shrinkage_prior_strength,
                    )
                    record["frontier_eligible"] = bool(
                        frontier_samples
                        and len(frontier_samples) >= int(frontier_min_settled_trades)
                        and (sum(frontier_samples) / len(frontier_samples)) >= float(frontier_min_mean_realized_net_bps)
                    )
                    payload_inputs = (
                        record.get("forecast_payload", {}).get("inputs")
                        if isinstance(record.get("forecast_payload"), dict)
                        else {}
                    )
                    if not isinstance(payload_inputs, dict):
                        payload_inputs = {}
                    worker_counterfactual = (
                        payload_inputs.get("worker_counterfactual")
                        if isinstance(payload_inputs.get("worker_counterfactual"), dict)
                        else {}
                    )
                    record["worker_counterfactual_candidate"] = bool(
                        str(record.get("model_id") or "").startswith("worker_signal_")
                        and worker_counterfactual
                    )
                    adaptive_policy = payload_inputs.get("adaptive_policy") if isinstance(payload_inputs.get("adaptive_policy"), dict) else {}
                    record["adaptation_active"] = bool(adaptive_policy)
                    record["adaptation_reason"] = str(adaptive_policy.get("adaptation_reason") or "")
                    record["cohort_bucket"] = str(payload_inputs.get("cohort_bucket") or "unknown")
                    record["symbol_class"] = str(payload_inputs.get("symbol_class") or "unknown")
                    if record["symbol_class"] == "unknown":
                        record["symbol_class"] = self._phase3_symbol_class_from_observation(
                            record.get("entry_observation") if isinstance(record.get("entry_observation"), dict) else {}
                        )
                    c.execute(
                        """
                        SELECT f2.payload, o2.net_return_bps
                        FROM hypothesis_forecasts f2
                        JOIN hypothesis_outcomes o2 ON o2.forecast_id=f2.forecast_id
                        WHERE f2.hypothesis=?
                          AND f2.abstain=0
                          AND f2.settled=1
                          AND f2.forecast_id<>?
                          AND f2.ts < ?
                          AND o2.settled_ts <= ?
                        ORDER BY o2.settled_ts DESC
                        LIMIT ?
                        """,
                        (
                            record.get("hypothesis"),
                            record.get("forecast_id"),
                            record.get("forecast_ts"),
                            record.get("forecast_ts"),
                            int(candidate_history_limit),
                        ),
                    )
                    slice_samples = []
                    symbol_class_samples = []
                    target_cohort = str(record.get("cohort_bucket") or "unknown")
                    target_symbol_class = str(record.get("symbol_class") or "unknown")
                    for payload_raw, net_bps in c.fetchall():
                        payload = {}
                        try:
                            payload = json.loads(payload_raw or "{}")
                        except Exception:
                            payload = {}
                        inputs = payload.get("inputs") if isinstance(payload, dict) else {}
                        if not isinstance(inputs, dict):
                            inputs = {}
                        sample_regime = self._phase3_regime_hint_from_payload(payload_raw)
                        sample_cohort = str(inputs.get("cohort_bucket") or "unknown")
                        sample_symbol_class = str(inputs.get("symbol_class") or "unknown")
                        if sample_symbol_class == target_symbol_class:
                            symbol_class_samples.append(float(net_bps or 0.0))
                        if (
                            sample_regime == target_regime
                            and sample_cohort == target_cohort
                            and sample_symbol_class == target_symbol_class
                        ):
                            slice_samples.append(float(net_bps or 0.0))
                    symbol_class_samples.reverse()
                    slice_samples.reverse()
                    record["symbol_class_historical_samples"] = len(symbol_class_samples)
                    record["symbol_class_historical_mean_net_bps"] = (
                        sum(symbol_class_samples) / len(symbol_class_samples) if symbol_class_samples else None
                    )
                    record["shrunk_symbol_class_historical_mean_net_bps"] = _shrunk_mean(
                        record["symbol_class_historical_mean_net_bps"],
                        record["symbol_class_historical_samples"],
                        record["shrunk_historical_mean_net_bps"],
                        shrinkage_prior_strength,
                    )
                    record["slice_historical_samples"] = len(slice_samples)
                    record["slice_historical_mean_net_bps"] = (
                        sum(slice_samples) / len(slice_samples) if slice_samples else None
                    )
                    record["shrunk_slice_historical_mean_net_bps"] = _shrunk_mean(
                        record["slice_historical_mean_net_bps"],
                        record["slice_historical_samples"],
                        record["shrunk_regime_historical_mean_net_bps"],
                        shrinkage_prior_strength,
                    )
                    record["recent_slice_historical_samples"] = min(len(slice_samples), int(recency_window))
                    record["recent_slice_historical_mean_net_bps"] = (
                        sum(slice_samples[-int(recency_window):]) / min(len(slice_samples), int(recency_window))
                        if slice_samples else None
                    )
                    record["shrunk_recent_slice_historical_mean_net_bps"] = _shrunk_mean(
                        record["recent_slice_historical_mean_net_bps"],
                        record["recent_slice_historical_samples"],
                        record["shrunk_slice_historical_mean_net_bps"],
                        max(1.0, shrinkage_prior_strength * 0.5),
                    )
                    record["failure_feedback_penalty_bps_equiv"] = 0.0
                    record["failure_feedback_top_causes"] = []
                    record["failure_feedback_matched_simulations"] = 0
                    record["failure_feedback_dominant_cause"] = None
                    record["failure_feedback_dominant_cause_rate"] = 0.0
                    record["failure_veto_active"] = False
                    if failure_feedback_enabled:
                        c.execute(
                            """
                            SELECT o.payload, f.payload
                            FROM simulated_orders o
                            LEFT JOIN hypothesis_forecasts f ON f.forecast_id=o.forecast_id
                            WHERE o.hypothesis=?
                              AND o.completed_ts <= ?
                            ORDER BY o.completed_ts DESC
                            LIMIT ?
                            """,
                            (
                                record.get("hypothesis"),
                                record.get("forecast_ts"),
                                max(int(failure_feedback_lookback) * 8, int(failure_feedback_lookback)),
                            ),
                        )
                        cause_counts: Dict[str, int] = {}
                        matched_simulations = 0
                        target_symbol_class = str(record.get("symbol_class") or "unknown")
                        for sim_payload_raw, forecast_payload_raw in c.fetchall():
                            sim_payload = {}
                            try:
                                sim_payload = json.loads(sim_payload_raw or "{}")
                            except Exception:
                                sim_payload = {}
                            forecast_payload = {}
                            try:
                                forecast_payload = json.loads(forecast_payload_raw or "{}") if isinstance(forecast_payload_raw, str) else (forecast_payload_raw or {})
                            except Exception:
                                forecast_payload = {}
                            sim_inputs = forecast_payload.get("inputs") if isinstance(forecast_payload, dict) else {}
                            if not isinstance(sim_inputs, dict):
                                sim_inputs = {}
                            sim_regime = self._phase3_regime_hint_from_payload(forecast_payload)
                            sim_cohort = str(sim_inputs.get("cohort_bucket") or "unknown")
                            sim_symbol_class = str(sim_inputs.get("symbol_class") or "unknown")
                            if (
                                sim_regime != target_regime
                                or sim_cohort != target_cohort
                                or sim_symbol_class != target_symbol_class
                            ):
                                continue
                            matched_simulations += 1
                            diagnostics = sim_payload.get("diagnostics") if isinstance(sim_payload.get("diagnostics"), dict) else {}
                            for cause in diagnostics.get("failure_causes") or []:
                                label = str(cause or "").strip()
                                if label:
                                    cause_counts[label] = cause_counts.get(label, 0) + 1
                            if matched_simulations >= int(failure_feedback_lookback):
                                break
                        if matched_simulations:
                            record["failure_feedback_matched_simulations"] = int(matched_simulations)
                            cause_weights = {
                                "wrong_regime": 6.0,
                                "false_breakout": 5.0,
                                "spread_too_wide": 4.5,
                                "late_entry": 4.0,
                                "late_entry_or_missed_fill": 4.5,
                                "partial_fill_drag": 3.0,
                                "cost_drag": 3.5,
                                "no_follow_through": 3.0,
                                "stale_or_low_quality_data": 3.5,
                                "venue_rejection": 2.5,
                                "unknown_order_state": 2.0,
                                "insufficient_size_for_execution": 1.5,
                                "quantity_rounded_below_minimum": 1.5,
                            }
                            penalty = 0.0
                            for cause, count in cause_counts.items():
                                rate = float(count) / max(1, matched_simulations)
                                penalty += float(cause_weights.get(cause, 2.0)) * rate
                            record["failure_feedback_penalty_bps_equiv"] = round(
                                float(penalty) * float(failure_feedback_penalty_scale), 6
                            )
                            record["failure_feedback_top_causes"] = [
                                {"cause": cause, "count": count}
                                for cause, count in sorted(cause_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
                            ]
                            if cause_counts:
                                dominant_cause, dominant_count = max(
                                    cause_counts.items(),
                                    key=lambda item: (item[1], item[0]),
                                )
                                dominant_rate = float(dominant_count) / max(1, matched_simulations)
                                record["failure_feedback_dominant_cause"] = dominant_cause
                                record["failure_feedback_dominant_cause_rate"] = round(dominant_rate, 6)
                                recent_slice_bps = float(record.get("shrunk_recent_slice_historical_mean_net_bps") or 0.0)
                                if (
                                    failure_veto_enabled
                                    and matched_simulations >= int(failure_veto_min_matched_simulations)
                                    and dominant_rate >= float(failure_veto_dominant_cause_rate)
                                    and recent_slice_bps <= float(failure_veto_max_recent_slice_bps)
                                ):
                                    record["failure_veto_active"] = True
                    expected_move = float(record.get("expected_move_bps") or 0.0)
                    expected_cost = max(0.000001, float(record.get("expected_cost_bps") or 0.0))
                    expected_net = float(record.get("expected_net_bps") or 0.0)
                    record["cost_survival_ratio"] = expected_move / expected_cost if expected_cost > 0 else 0.0
                    record["edge_quality_score"] = (
                        0.34 * expected_net
                        + 0.22 * float(record.get("probability_positive_net") or 0.0) * 100.0
                        + 0.24 * float(record.get("shrunk_frontier_regime_mean_net_bps") or 0.0)
                        + 0.24 * float(record.get("shrunk_recent_regime_historical_mean_net_bps") or 0.0)
                        + 0.26 * float(record.get("shrunk_recent_slice_historical_mean_net_bps") or 0.0)
                        + 0.22 * float(record.get("shrunk_slice_historical_mean_net_bps") or 0.0)
                        + 0.14 * float(record.get("shrunk_regime_historical_mean_net_bps") or 0.0)
                        + 0.10 * float(record.get("recent_historical_mean_net_bps") or 0.0)
                        + 0.08 * float(record.get("shrunk_historical_mean_net_bps") or 0.0)
                        + 0.06 * float(record.get("cost_survival_ratio") or 0.0)
                    )
                    recent_positive_crystals = []
                    recent_negative_crystals = []
                    if crystal_prior_enabled:
                        record_scope_hypothesis = str(record.get("hypothesis") or "unknown")
                        record_scope_symbol_class = str(record.get("symbol_class") or "unknown")
                        record_scope_regime = str(record.get("regime_hint") or "unknown")
                        record_scope_symbol = str(record.get("symbol") or "unknown")
                        for crystal in thesis_crystals:
                            if float(crystal.get("updated_ts") or 0.0) < crystal_cutoff_ts:
                                continue
                            if str(crystal.get("hypothesis") or "unknown") != record_scope_hypothesis:
                                continue
                            if str(crystal.get("regime_hint") or "unknown") != record_scope_regime:
                                continue
                            if str(crystal.get("symbol") or "unknown") not in {record_scope_symbol, "unknown", ""}:
                                continue
                            recent_positive_crystals.append(crystal)
                        for crystal in negative_crystals:
                            if float(crystal.get("updated_ts") or 0.0) < crystal_cutoff_ts:
                                continue
                            if str(crystal.get("hypothesis") or "unknown") != record_scope_hypothesis:
                                continue
                            if str(crystal.get("regime_hint") or "unknown") != record_scope_regime:
                                continue
                            if str(crystal.get("symbol_class") or "unknown") not in {record_scope_symbol_class, "unknown", ""}:
                                continue
                            recent_negative_crystals.append(crystal)
                    record["crystal_support_count"] = len(recent_positive_crystals)
                    record["crystal_warning_count"] = len(recent_negative_crystals)
                    record["crystal_support_score"] = round(
                        sum(float(item.get("evidence_strength") or 0.0) for item in recent_positive_crystals),
                        6,
                    )
                    record["crystal_warning_score"] = round(
                        sum(float(item.get("evidence_strength") or 0.0) for item in recent_negative_crystals),
                        6,
                    )
                    record["crystal_priority_adjustment"] = round(
                        min(float(crystal_positive_priority_boost), float(record["crystal_support_score"] or 0.0) * 0.75)
                        - min(float(crystal_negative_penalty_scale), float(record["crystal_warning_score"] or 0.0) * 0.50),
                        6,
                    )
                    record["crystal_memory"] = {
                        "positive_recent": len(recent_positive_crystals),
                        "negative_recent": len(recent_negative_crystals),
                        "recent_window_hours": float(crystal_recent_window_hours),
                        "support_scope": {
                            "hypothesis": record.get("hypothesis"),
                            "regime_hint": record.get("regime_hint"),
                            "symbol_class": record.get("symbol_class"),
                            "symbol": record.get("symbol"),
                        },
                    }
                    record["adjusted_edge_quality_score"] = (
                        float(record.get("edge_quality_score") or 0.0)
                        - float(record.get("failure_feedback_penalty_bps_equiv") or 0.0)
                        + float(record.get("crystal_priority_adjustment") or 0.0)
                        + (
                            float(exact_reuse_priority_boost)
                            if prefer_exact_reuse_candidates and bool(record.get("reuse_candidate"))
                            else 0.0
                        )
                    )
                    lower_bound_candidates = [
                        value for value in (
                            record.get("shrunk_recent_slice_historical_mean_net_bps"),
                            record.get("shrunk_slice_historical_mean_net_bps"),
                            record.get("shrunk_regime_historical_mean_net_bps"),
                            record.get("expected_net_bps"),
                        )
                        if value is not None
                    ]
                    record["profitability_slice_posterior"] = {
                        "schema": "profitability_slice_posterior_v1",
                        "slice_key": "|".join([
                            str(record.get("hypothesis") or "unknown"),
                            str(record.get("regime_hint") or "unknown"),
                            str(record.get("symbol_class") or "unknown"),
                            "execution_policy_pending",
                            str(record.get("horizon_seconds") or 0),
                            str(record.get("venue") or "unknown"),
                        ]),
                        "thesis_family": str(record.get("hypothesis") or "unknown"),
                        "regime_hint": str(record.get("regime_hint") or "unknown"),
                        "cohort_bucket": str(record.get("cohort_bucket") or "unknown"),
                        "symbol_class": str(record.get("symbol_class") or "unknown"),
                        "execution_policy_family": "execution_policy_pending",
                        "horizon_seconds": int(record.get("horizon_seconds") or 0),
                        "venue": str(record.get("venue") or "unknown"),
                        "posterior_mean_net_bps": record.get("shrunk_recent_slice_historical_mean_net_bps"),
                        "lower_bound_net_bps": round(min(lower_bound_candidates), 6) if lower_bound_candidates else None,
                        "probability_positive_net": record.get("probability_positive_net"),
                        "tail_risk_estimate_bps": record.get("failure_feedback_penalty_bps_equiv"),
                        "evidence_strength": round(
                            min(
                                1.0,
                                (int(record.get("historical_samples") or 0) / 24.0)
                                + (int(record.get("slice_historical_samples") or 0) / 12.0)
                                + (int(record.get("regime_historical_samples") or 0) / 16.0),
                            ),
                            6,
                        ),
                    }
                    if int(record.get("failure_feedback_matched_simulations") or 0) > 0:
                        record["negative_capability_crystal"] = {
                            "schema": "negative_capability_crystal_v1",
                            "crystal_id": hashlib.sha256(
                                f"phase3-candidate:{record.get('forecast_id')}:{record.get('failure_feedback_dominant_cause')}".encode("utf-8")
                            ).hexdigest(),
                            "scope": "phase3_candidate_intake",
                            "failure_state": record.get("failure_feedback_dominant_cause") or "mixed_failure_state",
                            "evidence_count": int(record.get("failure_feedback_matched_simulations") or 0),
                            "dominance_rate": float(record.get("failure_feedback_dominant_cause_rate") or 0.0),
                            "authority_effect": "veto_or_penalize_candidate" if bool(record.get("failure_veto_active")) else "penalize_candidate",
                            "top_failure_states": list(record.get("failure_feedback_top_causes") or [])[:4],
                        }
                    out.append(record)
            filtered = []
            for record in out:
                worker_counterfactual_candidate = bool(record.get("worker_counterfactual_candidate"))
                calibration = record.get("walk_forward_calibration") or {}
                if bool(calibration.get("evidence_sufficient")) and str(calibration.get("decision") or "") != "ALLOW":
                    meta["rejections"]["walk_forward_calibration_refused"] += 1
                    continue
                if worker_counterfactual_candidate and not worker_counterfactual_simulation_enabled:
                    meta["rejections"]["worker_counterfactual_disabled"] += 1
                    continue
                expected_net = record.get("expected_net_bps")
                probability = record.get("probability_positive_net")
                if (
                    not worker_counterfactual_candidate
                    and expected_net is not None
                    and float(expected_net) < float(min_expected_net_bps)
                ):
                    meta["rejections"]["expected_net_below_gate"] += 1
                    continue
                if (
                    not worker_counterfactual_candidate
                    and probability is not None
                    and float(probability) < float(min_probability)
                ):
                    meta["rejections"]["probability_below_gate"] += 1
                    continue
                if (
                    not worker_counterfactual_candidate
                    and float(record.get("cost_survival_ratio") or 0.0) < float(min_cost_survival_ratio)
                ):
                    meta["rejections"]["cost_survival_below_gate"] += 1
                    continue
                historical_samples = int(record.get("historical_samples") or 0)
                historical_mean = record.get("shrunk_historical_mean_net_bps")
                if not worker_counterfactual_candidate and historical_samples < int(min_historical_samples):
                    meta["rejections"]["insufficient_history"] += 1
                    continue
                if (
                    not worker_counterfactual_candidate
                    and historical_mean is not None
                    and historical_mean < float(min_historical_realized_net_bps)
                ):
                    meta["rejections"]["historical_edge_below_gate"] += 1
                    continue
                regime_historical_samples = int(record.get("regime_historical_samples") or 0)
                regime_historical_mean = record.get("shrunk_regime_historical_mean_net_bps")
                recent_regime_historical_samples = int(record.get("recent_regime_historical_samples") or 0)
                recent_regime_historical_mean = record.get("shrunk_recent_regime_historical_mean_net_bps")
                regime_reentry_eligible = bool(record.get("regime_reentry_eligible"))
                if not worker_counterfactual_candidate and regime_historical_samples < int(min_regime_historical_samples):
                    meta["rejections"]["insufficient_regime_history"] += 1
                    continue
                if (
                    not worker_counterfactual_candidate
                    and
                    regime_historical_mean is not None
                    and regime_historical_mean < float(min_regime_historical_realized_net_bps)
                    and not (
                        regime_reentry_eligible
                        and recent_regime_historical_samples >= int(regime_reentry_min_samples)
                        and recent_regime_historical_mean is not None
                        and recent_regime_historical_mean >= float(regime_reentry_min_mean_realized_net_bps)
                    )
                ):
                    meta["rejections"]["regime_edge_below_gate"] += 1
                    continue
                symbol_class_historical_samples = int(record.get("symbol_class_historical_samples") or 0)
                symbol_class_historical_mean = record.get("shrunk_symbol_class_historical_mean_net_bps")
                if not worker_counterfactual_candidate and symbol_class_historical_samples < int(min_symbol_class_historical_samples):
                    meta["rejections"]["insufficient_symbol_class_history"] += 1
                    continue
                if (
                    not worker_counterfactual_candidate
                    and
                    symbol_class_historical_mean is not None
                    and symbol_class_historical_mean < float(min_symbol_class_historical_realized_net_bps)
                ):
                    meta["rejections"]["symbol_class_edge_below_gate"] += 1
                    continue
                if bool(record.get("failure_veto_active")):
                    meta["rejections"]["failure_cause_veto"] += 1
                    continue
                filtered.append(record)
            filtered.sort(
                key=lambda row: (
                    1 if prefer_research_only and not str(row.get("model_id") or "").startswith("baseline_") else 0,
                    1 if bool(row.get("worker_counterfactual_candidate")) else 0,
                    1 if prefer_exact_reuse_candidates and bool(row.get("reuse_candidate")) else 0,
                    int(row.get("research_route_priority") or 0),
                    float(row.get("reuse_mean_realized_net_bps") or -10**9),
                    int(row.get("reuse_sample_count") or 0),
                    1
                    if int(row.get("slice_historical_samples") or 0) > 0
                    and (row.get("shrunk_slice_historical_mean_net_bps") is not None)
                    else 0,
                    float(row.get("shrunk_recent_slice_historical_mean_net_bps") or -10**9),
                    int(row.get("recent_slice_historical_samples") or 0),
                    float(row.get("shrunk_slice_historical_mean_net_bps") or -10**9),
                    int(row.get("slice_historical_samples") or 0),
                    1
                    if prefer_symbol_class_specialization
                    and int(row.get("symbol_class_historical_samples") or 0) > 0
                    and (row.get("shrunk_symbol_class_historical_mean_net_bps") is not None)
                    else 0,
                    float(row.get("shrunk_symbol_class_historical_mean_net_bps") or -10**9),
                    int(row.get("symbol_class_historical_samples") or 0),
                    1 if bool(row.get("regime_reentry_eligible")) else 0,
                    float(row.get("shrunk_recent_regime_historical_mean_net_bps") or -10**9),
                    int(row.get("recent_regime_historical_samples") or 0),
                    1 if prefer_profitability_frontier and bool(row.get("frontier_eligible")) else 0,
                    float(row.get("shrunk_frontier_regime_mean_net_bps") or -10**9),
                    int(row.get("frontier_regime_samples") or 0),
                    1
                    if prefer_regime_alignment
                    and int(row.get("regime_historical_samples") or 0) > 0
                    and (row.get("shrunk_regime_historical_mean_net_bps") is not None)
                    else 0,
                    float(row.get("settled_ts") or row.get("forecast_ts") or 0.0),
                    float(row.get("expected_net_bps") or -10**9),
                    float(row.get("cost_survival_ratio") or -10**9),
                    float(row.get("probability_positive_net") or 0.0),
                    float(row.get("adjusted_edge_quality_score") or row.get("edge_quality_score") or -10**9),
                    -float(row.get("failure_feedback_penalty_bps_equiv") or 0.0),
                    -sum(int(item.get("count") or 0) for item in (row.get("failure_feedback_top_causes") or [])),
                    float(row.get("shrunk_regime_historical_mean_net_bps") or -10**9),
                    float(row.get("shrunk_historical_mean_net_bps") or -10**9),
                    float(row.get("net_return_bps") or -10**9),
                ),
                reverse=True,
            )
            if unique_per_symbol_cohort:
                deduped = []
                seen_keys = set()
                for row in filtered:
                    key = (str(row.get("symbol") or ""), str(row.get("cohort_bucket") or "unknown"))
                    if key in seen_keys:
                        continue
                    deduped.append(row)
                    seen_keys.add(key)
                filtered = deduped
            selected = filtered[: int(limit or 100)]
            meta["selected_count"] = len(selected)
            meta["allocation"] = _phase3_growth_allocator(
                selected,
                reserve_cash_pct=reserve_cash_pct,
                max_candidate_fraction=max_candidate_fraction,
                min_expected_growth_bps=min_expected_growth_bps,
            )
            meta["sample"] = [
                {
                    "forecast_id": row.get("forecast_id"),
                    "model_id": row.get("model_id"),
                    "symbol": row.get("symbol"),
                    "cohort_bucket": row.get("cohort_bucket"),
                    "symbol_class": row.get("symbol_class"),
                    "adaptation_active": row.get("adaptation_active"),
                    "adaptation_reason": row.get("adaptation_reason"),
                    "regime_hint": row.get("regime_hint"),
                    "expected_net_bps": row.get("expected_net_bps"),
                    "cost_survival_ratio": row.get("cost_survival_ratio"),
                    "edge_quality_score": row.get("edge_quality_score"),
                    "adjusted_edge_quality_score": row.get("adjusted_edge_quality_score"),
                    "failure_feedback_penalty_bps_equiv": row.get("failure_feedback_penalty_bps_equiv"),
                    "failure_feedback_top_causes": row.get("failure_feedback_top_causes"),
                    "failure_feedback_matched_simulations": row.get("failure_feedback_matched_simulations"),
                    "failure_feedback_dominant_cause": row.get("failure_feedback_dominant_cause"),
                    "failure_feedback_dominant_cause_rate": row.get("failure_feedback_dominant_cause_rate"),
                    "failure_veto_active": bool(row.get("failure_veto_active")),
                    "crystal_support_count": int(row.get("crystal_support_count") or 0),
                    "crystal_warning_count": int(row.get("crystal_warning_count") or 0),
                    "crystal_support_score": row.get("crystal_support_score"),
                    "crystal_warning_score": row.get("crystal_warning_score"),
                    "crystal_priority_adjustment": row.get("crystal_priority_adjustment"),
                    "crystal_memory": row.get("crystal_memory"),
                    "probability_positive_net": row.get("probability_positive_net"),
                    "worker_counterfactual_candidate": bool(row.get("worker_counterfactual_candidate")),
                    "frontier_eligible": bool(row.get("frontier_eligible")),
                    "frontier_regime_mean_net_bps": row.get("frontier_regime_mean_net_bps"),
                    "shrunk_frontier_regime_mean_net_bps": row.get("shrunk_frontier_regime_mean_net_bps"),
                    "frontier_regime_samples": row.get("frontier_regime_samples"),
                    "research_route": row.get("research_route"),
                    "research_route_priority": row.get("research_route_priority"),
                    "reuse_candidate": bool(row.get("reuse_candidate")),
                    "reuse_mean_realized_net_bps": row.get("reuse_mean_realized_net_bps"),
                    "reuse_sample_count": row.get("reuse_sample_count"),
                    "recent_slice_historical_mean_net_bps": row.get("recent_slice_historical_mean_net_bps"),
                    "shrunk_recent_slice_historical_mean_net_bps": row.get("shrunk_recent_slice_historical_mean_net_bps"),
                    "recent_slice_historical_samples": row.get("recent_slice_historical_samples"),
                    "slice_historical_mean_net_bps": row.get("slice_historical_mean_net_bps"),
                    "shrunk_slice_historical_mean_net_bps": row.get("shrunk_slice_historical_mean_net_bps"),
                    "slice_historical_samples": row.get("slice_historical_samples"),
                    "symbol_class_historical_mean_net_bps": row.get("symbol_class_historical_mean_net_bps"),
                    "shrunk_symbol_class_historical_mean_net_bps": row.get("shrunk_symbol_class_historical_mean_net_bps"),
                    "symbol_class_historical_samples": row.get("symbol_class_historical_samples"),
                    "recent_historical_mean_net_bps": row.get("recent_historical_mean_net_bps"),
                    "recent_historical_samples": row.get("recent_historical_samples"),
                    "historical_mean_net_bps": row.get("historical_mean_net_bps"),
                    "shrunk_historical_mean_net_bps": row.get("shrunk_historical_mean_net_bps"),
                    "historical_samples": row.get("historical_samples"),
                    "regime_historical_mean_net_bps": row.get("regime_historical_mean_net_bps"),
                    "shrunk_regime_historical_mean_net_bps": row.get("shrunk_regime_historical_mean_net_bps"),
                    "regime_historical_samples": row.get("regime_historical_samples"),
                    "recent_regime_historical_mean_net_bps": row.get("recent_regime_historical_mean_net_bps"),
                    "shrunk_recent_regime_historical_mean_net_bps": row.get("shrunk_recent_regime_historical_mean_net_bps"),
                    "recent_regime_historical_samples": row.get("recent_regime_historical_samples"),
                    "regime_reentry_eligible": bool(row.get("regime_reentry_eligible")),
                    "profitability_slice_posterior": row.get("profitability_slice_posterior"),
                    "negative_capability_crystal": row.get("negative_capability_crystal"),
                }
                for row in selected[:5]
            ]
            self._last_phase3_candidate_meta = meta
            return selected
        except Exception:
            logging.exception("Error fetching Phase-3 forecast candidates")
            return []

    def get_phase3_evidence_expansion_candidates(
        self,
        *,
        model_id: str,
        order_policy: str,
        limit: int = 80,
        min_expected_net_bps: float = 10.0,
        min_probability_positive_net: float = 0.58,
        max_per_symbol: int = 10,
        max_per_hour_bucket: int = 4,
    ) -> list:
        """Select an outcome-blind, stratified replay sample for an under-tested model.

        Selection uses only fields frozen at forecast time. Settled outcomes are joined
        after selection because the deterministic simulator needs an exit reference.
        """
        if not self.conn or not str(model_id or "").strip():
            return []
        bounded_limit = max(1, min(500, int(limit or 80)))
        pool_limit = max(1000, bounded_limit * 50)
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    SELECT f.forecast_id, f.ts, f.target_ts, f.venue, f.symbol, f.model_id,
                           f.hypothesis, f.horizon_seconds, f.direction, f.entry_price,
                           f.probability_positive_net, f.expected_move_bps, f.expected_cost_bps,
                           f.expected_net_bps, f.raw_score, f.payload,
                           o.settled_ts, o.exit_price, o.directional_return_bps, o.net_return_bps
                    FROM hypothesis_forecasts f
                    JOIN hypothesis_outcomes o ON o.forecast_id=f.forecast_id
                    WHERE f.model_id=? AND f.settled=1 AND f.abstain=0
                      AND f.expected_net_bps>=?
                      AND f.probability_positive_net>=?
                      AND NOT EXISTS (
                          SELECT 1 FROM simulated_orders s
                          WHERE s.forecast_id=f.forecast_id
                            AND s.order_policy=? AND s.scenario='normal'
                      )
                    ORDER BY
                        CASE WHEN UPPER(COALESCE(f.direction,''))='UP' THEN 1 ELSE 0 END DESC,
                        COALESCE(f.expected_net_bps, -1000000000.0) DESC,
                        COALESCE(f.expected_move_bps, -1000000000.0) DESC,
                        COALESCE(f.probability_positive_net, 0.0) DESC,
                        f.ts ASC,
                        f.forecast_id ASC
                    LIMIT ?
                    """,
                    (
                        str(model_id),
                        float(min_expected_net_bps),
                        float(min_probability_positive_net),
                        str(order_policy),
                        pool_limit,
                    ),
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
                selected: list[Dict[str, Any]] = []
                symbol_counts: Dict[str, int] = {}
                hour_counts: Dict[int, int] = {}
                for raw in rows:
                    record = dict(zip(cols, raw))
                    symbol = str(record.get("symbol") or "")
                    forecast_ts = float(record.get("ts") or 0.0)
                    hour_bucket = int(forecast_ts // 3600)
                    if symbol_counts.get(symbol, 0) >= max(1, int(max_per_symbol or 1)):
                        continue
                    if hour_counts.get(hour_bucket, 0) >= max(1, int(max_per_hour_bucket or 1)):
                        continue
                    try:
                        record["forecast_payload"] = json.loads(record.pop("payload") or "{}")
                    except Exception:
                        record["forecast_payload"] = {}
                    record["forecast_ts"] = record.pop("ts", None)
                    c.execute(
                        """
                        SELECT payload FROM observation_snapshots
                        WHERE symbol=? AND ts<=? ORDER BY ts DESC LIMIT 1
                        """,
                        (symbol, forecast_ts),
                    )
                    observation = c.fetchone()
                    try:
                        record["entry_observation"] = json.loads(observation[0]) if observation and observation[0] else {}
                    except Exception:
                        record["entry_observation"] = {}
                    record["regime_hint"] = self._phase3_regime_hint(record)
                    record["symbol_class"] = self._phase3_symbol_class_from_payload(record["forecast_payload"])
                    if record["symbol_class"] == "unknown":
                        record["symbol_class"] = self._phase3_symbol_class_from_observation(record["entry_observation"])
                    expected_cost = max(0.000001, float(record.get("expected_cost_bps") or 0.0))
                    record["cost_survival_ratio"] = float(record.get("expected_move_bps") or 0.0) / expected_cost
                    record["research_route"] = "deterministic_evidence_expansion"
                    record["research_route_priority"] = 0
                    record["evidence_expansion"] = True
                    record["execution_eligible"] = False
                    selected.append(record)
                    symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
                    hour_counts[hour_bucket] = hour_counts.get(hour_bucket, 0) + 1
                    if len(selected) >= bounded_limit:
                        break
            return selected
        except Exception:
            logging.exception("Error fetching Phase-3 evidence-expansion candidates")
            return []

    def get_phase3_candidate_meta(self) -> Dict[str, Any]:
        return dict(self._last_phase3_candidate_meta or {})

    @staticmethod
    def _phase3_regime_hint_from_payload(payload_raw: Any) -> str:
        payload: Dict[str, Any] = {}
        if isinstance(payload_raw, str):
            try:
                payload = json.loads(payload_raw) or {}
            except Exception:
                payload = {}
        elif isinstance(payload_raw, dict):
            payload = payload_raw
        inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
        regime_inputs = inputs.get("regime_inputs") if isinstance(inputs.get("regime_inputs"), dict) else {}
        regime_hint = inputs.get("regime_hint") or regime_inputs.get("regime_hint")
        return str(regime_hint or _PHASE3_REGIME_FALLBACK)

    @staticmethod
    def _phase3_symbol_class_from_payload(payload_raw: Any) -> str:
        payload: Dict[str, Any] = {}
        if isinstance(payload_raw, str):
            try:
                payload = json.loads(payload_raw) or {}
            except Exception:
                payload = {}
        elif isinstance(payload_raw, dict):
            payload = payload_raw
        inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
        return str(inputs.get("symbol_class") or "unknown")

    @staticmethod
    def _phase3_symbol_class_from_observation(entry_observation: Dict[str, Any]) -> str:
        values = entry_observation.get("values") if isinstance(entry_observation.get("values"), dict) else {}
        explicit = values.get("symbol_class")
        if explicit:
            return str(explicit)
        feature = values.get("feature_vector") if isinstance(values.get("feature_vector"), dict) else {}
        spread_bps = max(0.0, float(entry_observation.get("spread_bps") or feature.get("spread_bps") or 0.0))
        depth_usd = max(0.0, float(entry_observation.get("depth_usd_25bps") or feature.get("depth_usd_25bps") or 0.0))
        volume_24h = max(0.0, float(entry_observation.get("quote_volume_24h") or feature.get("quote_volume_24h") or 0.0))
        vol_fast = max(0.0, float(feature.get("realized_volatility_fast") or 0.0))
        if depth_usd >= 400_000.0 and spread_bps <= 8.0 and volume_24h >= 75_000_000.0:
            return "ultra_liquid_major"
        if depth_usd >= 150_000.0 and spread_bps <= 18.0 and volume_24h >= 20_000_000.0:
            return "general_liquid"
        if vol_fast >= 0.015 and volume_24h <= 2_000_000.0 and spread_bps <= 200.0:
            return "niche_high_volatility"
        if spread_bps >= 30.0 or depth_usd <= 80_000.0:
            return "hostile_liquidity"
        if vol_fast >= 0.02 and volume_24h >= 5_000_000.0:
            return "event_spike_alt"
        return "mean_reverting_liquid"

    @classmethod
    def _phase3_regime_hint(cls, record: Dict[str, Any]) -> str:
        forecast_payload = record.get("forecast_payload") if isinstance(record.get("forecast_payload"), dict) else {}
        hint = cls._phase3_regime_hint_from_payload(forecast_payload)
        if hint != _PHASE3_REGIME_FALLBACK:
            return hint
        entry_observation = record.get("entry_observation") if isinstance(record.get("entry_observation"), dict) else {}
        values = entry_observation.get("values") if isinstance(entry_observation.get("values"), dict) else {}
        regime_inputs = values.get("regime_inputs") if isinstance(values.get("regime_inputs"), dict) else {}
        return str(regime_inputs.get("regime_hint") or _PHASE3_REGIME_FALLBACK)

    def get_simulation_runs(self, limit: int = 50) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    "SELECT * FROM simulation_runs ORDER BY completed_ts DESC LIMIT ?",
                    (int(limit or 50),),
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            logging.exception("Error fetching simulation runs")
            return []

    def get_simulated_orders(
        self,
        model_id: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 250,
    ) -> list:
        if not self.conn:
            return []
        try:
            clauses, params = [], []
            if model_id:
                clauses.append("model_id=?")
                params.append(model_id)
            if symbol:
                clauses.append("symbol=?")
                params.append(symbol)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            params.append(int(limit or 250))
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    f"SELECT * FROM simulated_orders {where} ORDER BY completed_ts DESC LIMIT ?",
                    tuple(params),
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            logging.exception("Error fetching simulated orders")
            return []

    def get_execution_scorecard(self) -> Dict[str, Any]:
        result = {
            "phase": 3,
            "mode": "execution_simulation_only",
            "rows": [],
            "slice_execution_breakdown": [],
            "profitability_slice_posteriors": [],
            "worker_executor_breakdown": [],
            "worker_executor_posteriors": [],
            "coalition_execution_breakdown": [],
            "coalition_slice_posteriors": [],
            "coalition_challenger_comparison": {},
            "negative_capability_crystals": [],
            "coalition_negative_capability_crystals": [],
            "execution_wired": False,
            "real_orders_submitted": 0,
        }
        if not self.conn:
            result["error"] = "data_store_unavailable"
            return result
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    SELECT o.model_id, o.order_policy, o.scenario,
                           CASE
                               WHEN json_extract(f.payload, '$.inputs.adaptive_policy.adaptation_reason') IS NOT NULL
                               THEN 1 ELSE 0
                           END AS adaptation_active,
                           COALESCE(json_extract(f.payload, '$.inputs.adaptive_policy.adaptation_reason'), '') AS adaptation_reason,
                           COUNT(*) AS simulations,
                           SUM(CASE WHEN o.status='COMPLETED' THEN 1 ELSE 0 END) AS completed,
                           SUM(CASE WHEN o.status='REJECTED' THEN 1 ELSE 0 END) AS rejected,
                           SUM(CASE WHEN o.status='EXPIRED' THEN 1 ELSE 0 END) AS expired,
                           AVG(CASE WHEN o.status='COMPLETED' THEN o.fill_ratio END) AS mean_fill_ratio,
                           AVG(CASE WHEN o.status='COMPLETED' THEN o.net_return_bps END) AS mean_net_bps,
                           AVG(CASE WHEN o.status='COMPLETED' THEN o.profitable_after_costs END) AS win_rate,
                           AVG(CASE WHEN o.status='COMPLETED' THEN c.total_cost_bps END) AS mean_total_cost_bps,
                           AVG(CASE WHEN o.status='COMPLETED' THEN c.fee_bps END) AS mean_fee_bps,
                           AVG(CASE WHEN o.status='COMPLETED' THEN c.entry_spread_bps+c.exit_spread_bps END) AS mean_spread_bps,
                           AVG(CASE WHEN o.status='COMPLETED' THEN c.entry_impact_bps+c.exit_impact_bps END) AS mean_impact_bps,
                           AVG(CASE WHEN o.status='COMPLETED' THEN c.entry_latency_bps+c.exit_latency_bps END) AS mean_latency_bps,
                           SUM(CASE WHEN o.spot_executable=1 AND o.status='COMPLETED' THEN 1 ELSE 0 END) AS spot_completed
                    FROM simulated_orders o
                    LEFT JOIN hypothesis_forecasts f ON f.forecast_id=o.forecast_id
                    LEFT JOIN simulated_cost_attribution c ON c.simulation_id=o.simulation_id
                    GROUP BY o.model_id, o.order_policy, o.scenario, adaptation_active, adaptation_reason
                    ORDER BY o.model_id, o.order_policy, o.scenario, adaptation_active DESC, adaptation_reason
                    """
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
                c.execute(
                    """
                    SELECT o.model_id, o.hypothesis, o.symbol, o.order_policy, o.scenario,
                           o.payload, f.payload AS forecast_payload, o.status, o.fill_ratio, o.net_return_bps,
                           o.profitable_after_costs, c.total_cost_bps
                    FROM simulated_orders o
                    LEFT JOIN hypothesis_forecasts f ON f.forecast_id=o.forecast_id
                    LEFT JOIN simulated_cost_attribution c ON c.simulation_id=o.simulation_id
                    """
                )
                slice_rows = c.fetchall()
                slice_cols = [item[0] for item in c.description]
                c.execute(
                    "SELECT COUNT(*), COALESCE(SUM(symbol_halted),0), "
                    "COALESCE(SUM(automatic_recovery),0) FROM simulation_incidents"
                )
                incident_count, symbol_halts, auto_recoveries = c.fetchone() or (0, 0, 0)
                c.execute(
                    "SELECT COALESCE(SUM(real_orders_submitted),0), "
                    "COALESCE(SUM(execution_wired),0) FROM simulated_orders"
                )
                orders, wired = c.fetchone() or (0, 0)
            score_rows = []
            for raw in rows:
                record = dict(zip(cols, raw))
                record["adaptation_active"] = bool(record.get("adaptation_active"))
                for key in (
                    "mean_fill_ratio", "mean_net_bps", "win_rate",
                    "mean_total_cost_bps", "mean_fee_bps", "mean_spread_bps",
                    "mean_impact_bps", "mean_latency_bps",
                ):
                    if record.get(key) is not None:
                        record[key] = round(float(record[key]), 6)
                score_rows.append(record)
            adaptation_groups: Dict[str, Dict[str, Any]] = {}
            for row in score_rows:
                key = "adapted" if row.get("adaptation_active") else "standard"
                bucket = adaptation_groups.setdefault(key, {
                    "segment": key,
                    "policies": 0,
                    "completed": 0,
                    "profitable_proxy": 0.0,
                    "mean_net_sum": 0.0,
                    "mean_net_n": 0,
                    "adaptation_reasons": {},
                })
                bucket["policies"] += 1
                completed = int(row.get("completed") or 0)
                bucket["completed"] += completed
                bucket["profitable_proxy"] += completed * float(row.get("win_rate") or 0.0)
                if row.get("mean_net_bps") is not None:
                    bucket["mean_net_sum"] += float(row.get("mean_net_bps") or 0.0) * completed
                    bucket["mean_net_n"] += completed
                reason = str(row.get("adaptation_reason") or "")
                if reason:
                    bucket["adaptation_reasons"][reason] = bucket["adaptation_reasons"].get(reason, 0) + completed
            slice_buckets: Dict[tuple[str, str, str, str, str, str], Dict[str, Any]] = {}
            worker_executor_buckets: Dict[tuple[str, str, str, str, str], Dict[str, Any]] = {}
            coalition_buckets: Dict[tuple[str, str, str, str, str, str, str], Dict[str, Any]] = {}
            for raw in slice_rows:
                record = dict(zip(slice_cols, raw))
                try:
                    payload = json.loads(record.get("payload") or "{}")
                except Exception:
                    payload = {}
                forecast_payload = record.get("forecast_payload")
                try:
                    forecast_payload = json.loads(forecast_payload or "{}") if isinstance(forecast_payload, str) else (forecast_payload or {})
                except Exception:
                    forecast_payload = {}
                inputs = forecast_payload.get("inputs") if isinstance(forecast_payload, dict) else {}
                if not isinstance(inputs, dict):
                    inputs = {}
                worker_receipt = inputs.get("worker_signal_receipt") if isinstance(inputs.get("worker_signal_receipt"), dict) else {}
                worker_counterfactual = inputs.get("worker_counterfactual") if isinstance(inputs.get("worker_counterfactual"), dict) else {}
                coalition_receipt = inputs.get("worker_coalition_receipt") if isinstance(inputs.get("worker_coalition_receipt"), dict) else {}
                coalition_body = coalition_receipt.get("coalition") if isinstance(coalition_receipt.get("coalition"), dict) else {}
                coalition_budget = coalition_receipt.get("symbol_class_budget") if isinstance(coalition_receipt.get("symbol_class_budget"), dict) else {}
                coalition_counterfactual = inputs.get("worker_coalition_counterfactual") if isinstance(inputs.get("worker_coalition_counterfactual"), dict) else {}
                regime_inputs = inputs.get("regime_inputs") if isinstance(inputs.get("regime_inputs"), dict) else {}
                regime_hint = str(inputs.get("regime_hint") or regime_inputs.get("regime_hint") or _PHASE3_REGIME_FALLBACK)
                cohort_bucket = str(inputs.get("cohort_bucket") or "unknown")
                symbol_class = str(inputs.get("symbol_class") or "unknown")
                if symbol_class == "unknown":
                    diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
                    symbol_class = str(diagnostics.get("symbol_class") or "unknown")
                key = (
                    str(record.get("hypothesis") or "unknown"),
                    regime_hint,
                    cohort_bucket,
                    symbol_class,
                    str(record.get("order_policy") or "unknown"),
                    str(record.get("scenario") or "unknown"),
                )
                bucket = slice_buckets.setdefault(key, {
                    "hypothesis": key[0],
                    "regime_hint": key[1],
                    "cohort_bucket": key[2],
                    "symbol_class": key[3],
                    "order_policy": key[4],
                    "scenario": key[5],
                    "simulations": 0,
                    "completed": 0,
                    "profitable_proxy": 0.0,
                    "fill_ratio_sum": 0.0,
                    "fill_ratio_n": 0,
                    "net_sum": 0.0,
                    "net_n": 0,
                    "net_samples": [],
                    "cost_sum": 0.0,
                    "cost_n": 0,
                    "horizon_bucket": "unknown",
                    "venue": str((forecast_payload or {}).get("venue") or "unknown"),
                    "failure_causes": {},
                    "symbols": {},
                    "models": {},
                })
                bucket["simulations"] += 1
                symbol = str(record.get("symbol") or "unknown")
                model_id = str(record.get("model_id") or "unknown")
                bucket["symbols"][symbol] = bucket["symbols"].get(symbol, 0) + 1
                bucket["models"][model_id] = bucket["models"].get(model_id, 0) + 1
                horizon_seconds = int((forecast_payload or {}).get("horizon_seconds") or 0)
                if horizon_seconds >= 3600:
                    bucket["horizon_bucket"] = "long"
                elif horizon_seconds >= 900:
                    bucket["horizon_bucket"] = "medium"
                else:
                    bucket["horizon_bucket"] = "short"
                diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
                for cause in diagnostics.get("failure_causes") or []:
                    label = str(cause or "").strip()
                    if label:
                        bucket["failure_causes"][label] = bucket["failure_causes"].get(label, 0) + 1
                if record.get("status") == "COMPLETED":
                    bucket["completed"] += 1
                    bucket["profitable_proxy"] += float(record.get("profitable_after_costs") or 0.0)
                    if record.get("fill_ratio") is not None:
                        bucket["fill_ratio_sum"] += float(record.get("fill_ratio") or 0.0)
                        bucket["fill_ratio_n"] += 1
                    if record.get("net_return_bps") is not None:
                        bucket["net_sum"] += float(record.get("net_return_bps") or 0.0)
                        bucket["net_n"] += 1
                        bucket["net_samples"].append(float(record.get("net_return_bps") or 0.0))
                    if record.get("total_cost_bps") is not None:
                        bucket["cost_sum"] += float(record.get("total_cost_bps") or 0.0)
                        bucket["cost_n"] += 1
                if str(record.get("model_id") or "").startswith("worker_signal_"):
                    worker_id = str(worker_receipt.get("worker_id") or record.get("model_id") or "unknown")
                    worker_family = str((inputs.get("worker_signal") or {}).get("family") if isinstance(inputs.get("worker_signal"), dict) else "")
                    if not worker_family:
                        worker_family = str(record.get("hypothesis") or "unknown")
                    worker_key = (
                        worker_id,
                        str(record.get("model_id") or "unknown"),
                        str(record.get("order_policy") or "unknown"),
                        str(record.get("scenario") or "unknown"),
                        "counterfactual" if worker_counterfactual else "cost_gate_passed",
                    )
                    worker_bucket = worker_executor_buckets.setdefault(worker_key, {
                        "worker_id": worker_key[0],
                        "model_id": worker_key[1],
                        "worker_family": worker_family,
                        "order_policy": worker_key[2],
                        "scenario": worker_key[3],
                        "signal_mode": worker_key[4],
                        "simulations": 0,
                        "completed": 0,
                        "profitable_proxy": 0.0,
                        "net_sum": 0.0,
                        "net_n": 0,
                        "net_samples": [],
                        "fill_ratio_sum": 0.0,
                        "fill_ratio_n": 0,
                        "cost_sum": 0.0,
                        "cost_n": 0,
                        "symbols": {},
                        "directions": {},
                        "failure_causes": {},
                    })
                    worker_bucket["simulations"] += 1
                    worker_bucket["symbols"][symbol] = worker_bucket["symbols"].get(symbol, 0) + 1
                    direction = str((forecast_payload or {}).get("direction") or record.get("direction") or "unknown")
                    worker_bucket["directions"][direction] = worker_bucket["directions"].get(direction, 0) + 1
                    diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
                    for cause in diagnostics.get("failure_causes") or []:
                        label = str(cause or "").strip()
                        if label:
                            worker_bucket["failure_causes"][label] = worker_bucket["failure_causes"].get(label, 0) + 1
                    if record.get("status") == "COMPLETED":
                        worker_bucket["completed"] += 1
                        worker_bucket["profitable_proxy"] += float(record.get("profitable_after_costs") or 0.0)
                        if record.get("net_return_bps") is not None:
                            worker_bucket["net_sum"] += float(record.get("net_return_bps") or 0.0)
                            worker_bucket["net_n"] += 1
                            worker_bucket["net_samples"].append(float(record.get("net_return_bps") or 0.0))
                        if record.get("fill_ratio") is not None:
                            worker_bucket["fill_ratio_sum"] += float(record.get("fill_ratio") or 0.0)
                            worker_bucket["fill_ratio_n"] += 1
                        if record.get("total_cost_bps") is not None:
                            worker_bucket["cost_sum"] += float(record.get("total_cost_bps") or 0.0)
                            worker_bucket["cost_n"] += 1
                if str(record.get("model_id") or "") == "worker_coalition_meta_v1" or coalition_receipt:
                    coalition_body_budget = (
                        coalition_body.get("symbol_class_budget")
                        if isinstance(coalition_body.get("symbol_class_budget"), dict)
                        else {}
                    )
                    budget_name = str(coalition_budget.get("budget_name") or coalition_body_budget.get("budget_name") or "unknown")
                    if not budget_name or budget_name == "None":
                        budget_name = "unknown"
                    coalition_key = (
                        str(record.get("hypothesis") or "worker_coalition_meta"),
                        regime_hint,
                        cohort_bucket,
                        symbol_class,
                        budget_name,
                        str(record.get("order_policy") or "unknown"),
                        str(record.get("scenario") or "unknown"),
                    )
                    coalition_bucket = coalition_buckets.setdefault(coalition_key, {
                        "slice_key": "|".join(coalition_key),
                        "hypothesis": coalition_key[0],
                        "regime_hint": coalition_key[1],
                        "cohort_bucket": coalition_key[2],
                        "symbol_class": coalition_key[3],
                        "budget_name": coalition_key[4],
                        "order_policy": coalition_key[5],
                        "scenario": coalition_key[6],
                        "budget_families": list(coalition_budget.get("families") or []),
                        "signal_mode": "counterfactual" if coalition_counterfactual else "coalition_passed",
                        "simulations": 0,
                        "completed": 0,
                        "profitable_proxy": 0.0,
                        "fill_ratio_sum": 0.0,
                        "fill_ratio_n": 0,
                        "net_sum": 0.0,
                        "net_n": 0,
                        "net_samples": [],
                        "cost_sum": 0.0,
                        "cost_n": 0,
                        "symbols": {},
                        "directions": {},
                        "failure_causes": {},
                        "allowed_voters_sum": 0.0,
                        "agreement_sum": 0.0,
                        "coalition_n": 0,
                    })
                    coalition_bucket["simulations"] += 1
                    coalition_bucket["symbols"][symbol] = coalition_bucket["symbols"].get(symbol, 0) + 1
                    direction = str((forecast_payload or {}).get("direction") or "unknown")
                    coalition_bucket["directions"][direction] = coalition_bucket["directions"].get(direction, 0) + 1
                    coalition_bucket["allowed_voters_sum"] += float(coalition_body.get("allowed_voters") or 0.0)
                    coalition_bucket["agreement_sum"] += float(coalition_body.get("agreement") or 0.0)
                    coalition_bucket["coalition_n"] += 1
                    for cause in diagnostics.get("failure_causes") or []:
                        label = str(cause or "").strip()
                        if label:
                            coalition_bucket["failure_causes"][label] = coalition_bucket["failure_causes"].get(label, 0) + 1
                    if record.get("status") == "COMPLETED":
                        coalition_bucket["completed"] += 1
                        coalition_bucket["profitable_proxy"] += float(record.get("profitable_after_costs") or 0.0)
                        if record.get("fill_ratio") is not None:
                            coalition_bucket["fill_ratio_sum"] += float(record.get("fill_ratio") or 0.0)
                            coalition_bucket["fill_ratio_n"] += 1
                        if record.get("net_return_bps") is not None:
                            coalition_bucket["net_sum"] += float(record.get("net_return_bps") or 0.0)
                            coalition_bucket["net_n"] += 1
                            coalition_bucket["net_samples"].append(float(record.get("net_return_bps") or 0.0))
                        if record.get("total_cost_bps") is not None:
                            coalition_bucket["cost_sum"] += float(record.get("total_cost_bps") or 0.0)
                            coalition_bucket["cost_n"] += 1
            failure_cause_buckets: Dict[str, int] = {}
            symbol_class_buckets: Dict[str, Dict[str, Any]] = {}
            for raw in slice_rows:
                record = dict(zip(slice_cols, raw))
                payload = {}
                try:
                    payload = json.loads(record.get("payload") or "{}")
                except Exception:
                    payload = {}
                diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
                for cause in diagnostics.get("failure_causes") or []:
                    label = str(cause or "").strip()
                    if label:
                        failure_cause_buckets[label] = failure_cause_buckets.get(label, 0) + 1
                symbol_class = str(
                    diagnostics.get("symbol_class")
                    or self._phase3_symbol_class_from_payload(record.get("payload"))
                    or "unknown"
                )
                bucket = symbol_class_buckets.setdefault(symbol_class, {
                    "symbol_class": symbol_class,
                    "simulations": 0,
                    "completed": 0,
                    "net_sum": 0.0,
                    "net_n": 0,
                    "cost_sum": 0.0,
                    "cost_n": 0,
                })
                bucket["simulations"] += 1
                if record.get("status") == "COMPLETED":
                    bucket["completed"] += 1
                    if record.get("net_return_bps") is not None:
                        bucket["net_sum"] += float(record.get("net_return_bps") or 0.0)
                        bucket["net_n"] += 1
                    if record.get("total_cost_bps") is not None:
                        bucket["cost_sum"] += float(record.get("total_cost_bps") or 0.0)
                        bucket["cost_n"] += 1
            slice_execution_rows = []
            execution_slice_posteriors = []
            worker_executor_rows = []
            worker_executor_posteriors = []
            coalition_execution_rows = []
            coalition_slice_posteriors = []
            for key, bucket in slice_buckets.items():
                mean_net_bps = round(bucket["net_sum"] / max(1, int(bucket["net_n"])), 6) if bucket["net_n"] else None
                profitable_rate = round(bucket["profitable_proxy"] / max(1, int(bucket["completed"])), 6)
                slice_execution_rows.append(
                    {
                        "slice_key": "|".join(key),
                        "hypothesis": bucket["hypothesis"],
                        "regime_hint": bucket["regime_hint"],
                        "cohort_bucket": bucket["cohort_bucket"],
                        "symbol_class": bucket["symbol_class"],
                        "order_policy": bucket["order_policy"],
                        "scenario": bucket["scenario"],
                        "simulations": int(bucket["simulations"]),
                        "completed": int(bucket["completed"]),
                        "profitable_outcomes": int(round(bucket["profitable_proxy"])),
                        "profitable_rate": profitable_rate,
                        "mean_fill_ratio": round(bucket["fill_ratio_sum"] / max(1, int(bucket["fill_ratio_n"])), 6) if bucket["fill_ratio_n"] else None,
                        "mean_net_bps": mean_net_bps,
                        "mean_total_cost_bps": round(bucket["cost_sum"] / max(1, int(bucket["cost_n"])), 6) if bucket["cost_n"] else None,
                        "symbol_count": len(bucket["symbols"]),
                        "top_symbols": [
                            {"symbol": symbol, "count": count}
                            for symbol, count in sorted(bucket["symbols"].items(), key=lambda item: (-item[1], item[0]))[:3]
                        ],
                        "top_models": [
                            {"model_id": model_id, "count": count}
                            for model_id, count in sorted(bucket["models"].items(), key=lambda item: (-item[1], item[0]))[:3]
                        ],
                    }
                )
                realized_distribution = _summarize_distribution(list(bucket.get("net_samples") or []))
                lower_bound_candidates = [
                    value for value in (mean_net_bps, realized_distribution.get("p25_bps"))
                    if value is not None
                ]
                execution_slice_posteriors.append(
                    {
                        "schema": "profitability_slice_posterior_v1",
                        "slice_key": "|".join(key),
                        "thesis_family": bucket["hypothesis"],
                        "regime_hint": bucket["regime_hint"],
                        "cohort_bucket": bucket["cohort_bucket"],
                        "symbol_class": bucket["symbol_class"],
                        "execution_policy_family": bucket["order_policy"],
                        "horizon_bucket": bucket["horizon_bucket"],
                        "venue": bucket["venue"],
                        "scenario": bucket["scenario"],
                        "posterior_net_return_distribution_bps": realized_distribution,
                        "posterior_mean_net_bps": mean_net_bps,
                        "lower_bound_net_bps": round(min(lower_bound_candidates), 6) if lower_bound_candidates else None,
                        "probability_positive_net": profitable_rate if bucket["completed"] else None,
                        "tail_risk_estimate_bps": realized_distribution.get("p10_bps"),
                        "execution_success_distribution": {
                            "completed": int(bucket["completed"]),
                            "simulations": int(bucket["simulations"]),
                            "mean_fill_ratio": round(bucket["fill_ratio_sum"] / max(1, int(bucket["fill_ratio_n"])), 6) if bucket["fill_ratio_n"] else None,
                        },
                        "capacity_curve_status": "simulated_only",
                        "drift_state": _drift_state(
                            mean_net_bps,
                            round(sum((bucket.get("net_samples") or [])[-6:]) / len((bucket.get("net_samples") or [])[-6:]), 6)
                            if len(bucket.get("net_samples") or []) >= 2 else mean_net_bps,
                            recent_samples=min(len(bucket.get("net_samples") or []), 6),
                            drift_threshold_bps=5.0,
                            min_recent_samples=4,
                        ),
                        "evidence_strength": round(
                            min(1.0, (int(bucket["completed"]) / 16.0) + profitable_rate),
                            6,
                        ),
                        "negative_capability_pressure": [
                            {"failure_state": cause, "count": count}
                            for cause, count in sorted(bucket["failure_causes"].items(), key=lambda item: (-item[1], item[0]))[:4]
                        ],
                    }
                )
            for key, bucket in worker_executor_buckets.items():
                mean_net_bps = round(bucket["net_sum"] / max(1, int(bucket["net_n"])), 6) if bucket["net_n"] else None
                win_rate = round(bucket["profitable_proxy"] / max(1, int(bucket["completed"])), 6) if bucket["completed"] else None
                dist = _summarize_distribution(list(bucket.get("net_samples") or []))
                lower_candidates = [
                    value for value in (mean_net_bps, dist.get("p25_bps"))
                    if value is not None
                ]
                worker_executor_rows.append({
                    "worker_executor_key": "|".join(key),
                    "worker_id": bucket["worker_id"],
                    "model_id": bucket["model_id"],
                    "worker_family": bucket["worker_family"],
                    "order_policy": bucket["order_policy"],
                    "scenario": bucket["scenario"],
                    "signal_mode": bucket["signal_mode"],
                    "simulations": int(bucket["simulations"]),
                    "completed": int(bucket["completed"]),
                    "profitable_outcomes": int(round(bucket["profitable_proxy"])),
                    "win_rate": win_rate,
                    "mean_net_bps": mean_net_bps,
                    "lower_bound_net_bps": round(min(lower_candidates), 6) if lower_candidates else None,
                    "mean_fill_ratio": round(bucket["fill_ratio_sum"] / max(1, int(bucket["fill_ratio_n"])), 6) if bucket["fill_ratio_n"] else None,
                    "mean_total_cost_bps": round(bucket["cost_sum"] / max(1, int(bucket["cost_n"])), 6) if bucket["cost_n"] else None,
                    "top_symbols": [
                        {"symbol": symbol, "count": count}
                        for symbol, count in sorted(bucket["symbols"].items(), key=lambda item: (-item[1], item[0]))[:5]
                    ],
                    "directions": [
                        {"direction": direction, "count": count}
                        for direction, count in sorted(bucket["directions"].items(), key=lambda item: (-item[1], item[0]))
                    ],
                    "failure_causes": [
                        {"cause": cause, "count": count}
                        for cause, count in sorted(bucket["failure_causes"].items(), key=lambda item: (-item[1], item[0]))[:5]
                    ],
                })
                if bucket["completed"]:
                    worker_executor_posteriors.append({
                        "schema": "worker_executor_posterior_v1",
                        "worker_executor_key": "|".join(key),
                        "worker_id": bucket["worker_id"],
                        "model_id": bucket["model_id"],
                        "worker_family": bucket["worker_family"],
                        "execution_policy_family": bucket["order_policy"],
                        "scenario": bucket["scenario"],
                        "signal_mode": bucket["signal_mode"],
                        "posterior_net_return_distribution_bps": dist,
                        "posterior_mean_net_bps": mean_net_bps,
                        "lower_bound_net_bps": round(min(lower_candidates), 6) if lower_candidates else None,
                        "probability_positive_net": win_rate,
                        "evidence_strength": round(min(1.0, int(bucket["completed"]) / 16.0), 6),
                        "authority": "research_simulation_only",
                        "execution_authority": "none",
                    })
            for key, bucket in coalition_buckets.items():
                mean_net_bps = round(bucket["net_sum"] / max(1, int(bucket["net_n"])), 6) if bucket["net_n"] else None
                win_rate = round(bucket["profitable_proxy"] / max(1, int(bucket["completed"])), 6) if bucket["completed"] else None
                dist = _summarize_distribution(list(bucket.get("net_samples") or []))
                lower_candidates = [
                    value for value in (mean_net_bps, dist.get("p25_bps"))
                    if value is not None
                ]
                lower_bound = round(min(lower_candidates), 6) if lower_candidates else None
                recent_samples = list(bucket.get("net_samples") or [])[-6:]
                coalition_execution_rows.append({
                    "coalition_slice_key": bucket["slice_key"],
                    "hypothesis": bucket["hypothesis"],
                    "regime_hint": bucket["regime_hint"],
                    "cohort_bucket": bucket["cohort_bucket"],
                    "symbol_class": bucket["symbol_class"],
                    "budget_name": bucket["budget_name"],
                    "budget_families": bucket["budget_families"],
                    "order_policy": bucket["order_policy"],
                    "scenario": bucket["scenario"],
                    "signal_mode": bucket["signal_mode"],
                    "simulations": int(bucket["simulations"]),
                    "completed": int(bucket["completed"]),
                    "profitable_outcomes": int(round(bucket["profitable_proxy"])),
                    "win_rate": win_rate,
                    "mean_net_bps": mean_net_bps,
                    "lower_bound_net_bps": lower_bound,
                    "mean_fill_ratio": round(bucket["fill_ratio_sum"] / max(1, int(bucket["fill_ratio_n"])), 6) if bucket["fill_ratio_n"] else None,
                    "mean_total_cost_bps": round(bucket["cost_sum"] / max(1, int(bucket["cost_n"])), 6) if bucket["cost_n"] else None,
                    "mean_allowed_voters": round(bucket["allowed_voters_sum"] / max(1, int(bucket["coalition_n"])), 6),
                    "mean_agreement": round(bucket["agreement_sum"] / max(1, int(bucket["coalition_n"])), 6),
                    "top_symbols": [
                        {"symbol": symbol, "count": count}
                        for symbol, count in sorted(bucket["symbols"].items(), key=lambda item: (-item[1], item[0]))[:5]
                    ],
                    "directions": [
                        {"direction": direction, "count": count}
                        for direction, count in sorted(bucket["directions"].items(), key=lambda item: (-item[1], item[0]))
                    ],
                    "failure_causes": [
                        {"cause": cause, "count": count}
                        for cause, count in sorted(bucket["failure_causes"].items(), key=lambda item: (-item[1], item[0]))[:5]
                    ],
                })
                if bucket["completed"]:
                    coalition_slice_posteriors.append({
                        "schema": "coalition_execution_slice_posterior_v1",
                        "coalition_slice_key": bucket["slice_key"],
                        "thesis_family": bucket["hypothesis"],
                        "regime_hint": bucket["regime_hint"],
                        "cohort_bucket": bucket["cohort_bucket"],
                        "symbol_class": bucket["symbol_class"],
                        "budget_name": bucket["budget_name"],
                        "budget_families": bucket["budget_families"],
                        "execution_policy_family": bucket["order_policy"],
                        "scenario": bucket["scenario"],
                        "signal_mode": bucket["signal_mode"],
                        "posterior_net_return_distribution_bps": dist,
                        "posterior_mean_net_bps": mean_net_bps,
                        "lower_bound_net_bps": lower_bound,
                        "probability_positive_net": win_rate,
                        "execution_success_distribution": {
                            "completed": int(bucket["completed"]),
                            "simulations": int(bucket["simulations"]),
                            "mean_fill_ratio": round(bucket["fill_ratio_sum"] / max(1, int(bucket["fill_ratio_n"])), 6) if bucket["fill_ratio_n"] else None,
                        },
                        "drift_state": _drift_state(
                            mean_net_bps,
                            round(sum(recent_samples) / len(recent_samples), 6) if recent_samples else mean_net_bps,
                            recent_samples=len(recent_samples),
                            drift_threshold_bps=5.0,
                            min_recent_samples=4,
                        ),
                        "evidence_strength": round(min(1.0, int(bucket["completed"]) / 24.0), 6),
                        "negative_capability_pressure": [
                            {"failure_state": cause, "count": count}
                            for cause, count in sorted(bucket["failure_causes"].items(), key=lambda item: (-item[1], item[0]))[:5]
                        ],
                        "authority": "research_simulation_only",
                        "execution_authority": "none",
                    })
            challenger_posteriors = [
                row for row in execution_slice_posteriors
                if isinstance(row, dict) and str(row.get("thesis_family") or "") != "worker_coalition_meta"
            ]
            best_challenger = next(
                (
                    row for row in sorted(
                        challenger_posteriors,
                        key=lambda item: (
                            float(item.get("lower_bound_net_bps") if item.get("lower_bound_net_bps") is not None else -10**9),
                            float(item.get("evidence_strength") or 0.0),
                        ),
                        reverse=True,
                    )
                    if row.get("lower_bound_net_bps") is not None
                ),
                None,
            )
            challenger_lower = (
                float(best_challenger.get("lower_bound_net_bps"))
                if isinstance(best_challenger, dict) and best_challenger.get("lower_bound_net_bps") is not None
                else None
            )
            for row in coalition_slice_posteriors:
                lower = row.get("lower_bound_net_bps")
                row["beats_primary_federated_challenger_oos"] = bool(
                    lower is not None
                    and challenger_lower is not None
                    and float(lower) > challenger_lower
                    and float(lower) > 0.0
                )
                row["challenger_lower_bound_net_bps"] = challenger_lower
            negative_crystals = [
                {
                    "schema": "negative_capability_crystal_v1",
                    "crystal_id": hashlib.sha256(f"phase3:{cause}".encode("utf-8")).hexdigest(),
                    "scope": "phase3_execution_refusal",
                    "failure_state": cause,
                    "evidence_count": int(count),
                    "dominance_rate": round(float(count) / max(1, len(slice_rows)), 6),
                    "authority_effect": "veto_or_penalize_candidate",
                }
                for cause, count in sorted(failure_cause_buckets.items(), key=lambda item: (-item[1], item[0]))[:12]
            ]
            coalition_negative_crystals = []
            for row in coalition_execution_rows:
                completed = int(row.get("completed") or 0)
                failures = row.get("failure_causes") if isinstance(row.get("failure_causes"), list) else []
                if completed < 4 or not failures:
                    continue
                total_failures = sum(int(item.get("count") or 0) for item in failures if isinstance(item, dict))
                if total_failures <= 0:
                    continue
                for item in failures[:3]:
                    cause = str(item.get("cause") or "").strip()
                    count = int(item.get("count") or 0)
                    if not cause or count <= 0:
                        continue
                    dominance_rate = float(count) / max(1, total_failures)
                    if dominance_rate < 0.30:
                        continue
                    crystal_body = {
                        "scope": "phase3_coalition_execution_refusal",
                        "coalition_slice_key": row.get("coalition_slice_key"),
                        "failure_state": cause,
                        "symbol_class": row.get("symbol_class"),
                        "budget_name": row.get("budget_name"),
                        "order_policy": row.get("order_policy"),
                        "scenario": row.get("scenario"),
                    }
                    coalition_negative_crystals.append({
                        "schema": "negative_capability_crystal_v1",
                        "crystal_id": hashlib.sha256(json.dumps(crystal_body, sort_keys=True).encode("utf-8")).hexdigest(),
                        **crystal_body,
                        "evidence_count": count,
                        "completed": completed,
                        "dominance_rate": round(dominance_rate, 6),
                        "authority_effect": "veto_or_penalize_coalition_slice",
                        "execution_authority": "none",
                    })
            result.update({
                "rows": score_rows,
                "slice_execution_breakdown": sorted(
                    slice_execution_rows,
                    key=lambda item: (
                        float(item.get("mean_net_bps") if item.get("mean_net_bps") is not None else -10**9),
                        int(item.get("completed") or 0),
                        float(item.get("profitable_rate") or 0.0),
                    ),
                    reverse=True,
                )[:24],
                "profitability_slice_posteriors": sorted(
                    execution_slice_posteriors,
                    key=lambda item: (
                        float(item.get("lower_bound_net_bps") if item.get("lower_bound_net_bps") is not None else -10**9),
                        float(item.get("evidence_strength") or 0.0),
                        int((item.get("posterior_net_return_distribution_bps") or {}).get("sample_count") or 0),
                    ),
                    reverse=True,
                )[:24],
                "adaptation_breakdown": {
                    key: {
                        "segment": bucket["segment"],
                        "policies": int(bucket["policies"]),
                        "completed": int(bucket["completed"]),
                        "profitable_outcomes": int(round(bucket["profitable_proxy"])),
                        "profitable_rate": round(bucket["profitable_proxy"] / max(1, int(bucket["completed"])), 6),
                        "mean_net_bps": round(bucket["mean_net_sum"] / max(1, int(bucket["mean_net_n"])), 6) if bucket["mean_net_n"] else None,
                        "adaptation_reasons": [
                            {"reason": reason, "completed": count}
                            for reason, count in sorted(bucket["adaptation_reasons"].items(), key=lambda item: (-item[1], item[0]))[:6]
                        ],
                    }
                    for key, bucket in adaptation_groups.items()
                },
                "failure_cause_breakdown": [
                    {"cause": cause, "count": count}
                    for cause, count in sorted(failure_cause_buckets.items(), key=lambda item: (-item[1], item[0]))[:12]
                ],
                "negative_capability_crystals": negative_crystals,
                "worker_executor_breakdown": sorted(
                    worker_executor_rows,
                    key=lambda item: (
                        float(item.get("lower_bound_net_bps") if item.get("lower_bound_net_bps") is not None else -10**9),
                        int(item.get("completed") or 0),
                        float(item.get("win_rate") or 0.0),
                    ),
                    reverse=True,
                )[:32],
                "worker_executor_posteriors": sorted(
                    worker_executor_posteriors,
                    key=lambda item: (
                        float(item.get("lower_bound_net_bps") if item.get("lower_bound_net_bps") is not None else -10**9),
                        float(item.get("evidence_strength") or 0.0),
                    ),
                    reverse=True,
                )[:32],
                "coalition_execution_breakdown": sorted(
                    coalition_execution_rows,
                    key=lambda item: (
                        float(item.get("lower_bound_net_bps") if item.get("lower_bound_net_bps") is not None else -10**9),
                        int(item.get("completed") or 0),
                        float(item.get("win_rate") or 0.0),
                    ),
                    reverse=True,
                )[:32],
                "coalition_slice_posteriors": sorted(
                    coalition_slice_posteriors,
                    key=lambda item: (
                        1 if bool(item.get("beats_primary_federated_challenger_oos")) else 0,
                        float(item.get("lower_bound_net_bps") if item.get("lower_bound_net_bps") is not None else -10**9),
                        float(item.get("evidence_strength") or 0.0),
                    ),
                    reverse=True,
                )[:32],
                "coalition_challenger_comparison": {
                    "schema": "phase3_coalition_challenger_comparison_v1",
                    "promotion_rule": "coalition_lower_bound_must_exceed_primary_federated_challenger_and_zero",
                    "best_challenger": best_challenger,
                    "coalition_candidates": len(coalition_slice_posteriors),
                    "coalition_candidates_beating_challenger": sum(
                        1 for row in coalition_slice_posteriors
                        if bool(row.get("beats_primary_federated_challenger_oos"))
                    ),
                    "authority": "research_promotion_evidence_only",
                },
                "coalition_negative_capability_crystals": coalition_negative_crystals[:24],
                "symbol_class_breakdown": [
                    {
                        "symbol_class": bucket["symbol_class"],
                        "simulations": int(bucket["simulations"]),
                        "completed": int(bucket["completed"]),
                        "mean_net_bps": round(bucket["net_sum"] / max(1, int(bucket["net_n"])), 6) if bucket["net_n"] else None,
                        "mean_total_cost_bps": round(bucket["cost_sum"] / max(1, int(bucket["cost_n"])), 6) if bucket["cost_n"] else None,
                    }
                    for bucket in sorted(
                        symbol_class_buckets.values(),
                        key=lambda item: (
                            float((item["net_sum"] / max(1, int(item["net_n"]))) if item["net_n"] else -10**9),
                            int(item["completed"]),
                        ),
                        reverse=True,
                    )
                ],
                "incident_count": int(incident_count or 0),
                "symbol_halts": int(symbol_halts or 0),
                "automatic_recoveries": int(auto_recoveries or 0),
                "execution_wiring_violations": int(wired or 0),
                "real_orders_submitted": int(orders or 0),
            })
            return result
        except Exception:
            logging.exception("Error computing execution scorecard")
            result["error"] = "scorecard_failed"
            return result

    def get_phase3_readiness(
        self,
        min_completed: int = 100,
        max_mean_2x_loss_bps: float = 50.0,
        scorecard: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        result = {
            "phase": 3,
            "ready_for_phase4_review": False,
            "execution_eligible": False,
            "real_orders_submitted": 0,
            "reasons": [],
        }
        if not self.conn:
            result["reasons"] = ["data_store_unavailable"]
            return result
        if scorecard is None:
            try:
                with self._lock:
                    c = self.conn.cursor()
                    c.execute(
                        """
                        SELECT model_id, order_policy, scenario,
                               COUNT(*) AS completed,
                               AVG(net_return_bps) AS mean_net_bps,
                               AVG(profitable_after_costs) AS win_rate
                        FROM simulated_orders
                        WHERE status='COMPLETED'
                        GROUP BY model_id, order_policy, scenario
                        """
                    )
                    rows = [
                        {
                            "model_id": row[0],
                            "order_policy": row[1],
                            "scenario": row[2],
                            "completed": int(row[3] or 0),
                            "mean_net_bps": round(float(row[4]), 6) if row[4] is not None else None,
                            "win_rate": round(float(row[5]), 6) if row[5] is not None else None,
                        }
                        for row in c.fetchall()
                    ]
                    c.execute(
                        """
                        SELECT hypothesis, order_policy, scenario,
                               COUNT(*) AS completed,
                               AVG(net_return_bps) AS mean_net_bps,
                               AVG(profitable_after_costs) AS profitable_rate
                        FROM simulated_orders
                        WHERE status='COMPLETED'
                        GROUP BY hypothesis, order_policy, scenario
                        """
                    )
                    slice_rows = [
                        {
                            "hypothesis": row[0],
                            "order_policy": row[1],
                            "scenario": row[2],
                            "completed": int(row[3] or 0),
                            "mean_net_bps": round(float(row[4]), 6) if row[4] is not None else None,
                            "profitable_rate": round(float(row[5]), 6) if row[5] is not None else None,
                        }
                        for row in c.fetchall()
                    ]
                    c.execute(
                        "SELECT COALESCE(SUM(real_orders_submitted),0), "
                        "COALESCE(SUM(execution_wired),0) FROM simulated_orders"
                    )
                    orders, wired = c.fetchone() or (0, 0)
                    c.execute(
                        "SELECT COALESCE(SUM(automatic_recovery),0) FROM simulation_incidents"
                    )
                    auto_recoveries = (c.fetchone() or (0,))[0]
                scorecard = {
                    "phase": 3,
                    "mode": "execution_simulation_only_fast_readiness",
                    "rows": rows,
                    "slice_execution_breakdown": slice_rows,
                    "execution_wiring_violations": int(wired or 0),
                    "real_orders_submitted": int(orders or 0),
                    "automatic_recoveries": int(auto_recoveries or 0),
                    "execution_eligible": False,
                }
            except Exception:
                logging.exception("Error computing fast Phase-3 readiness scorecard")
                scorecard = self.get_execution_scorecard()
        rows = scorecard.get("rows") or []
        slice_rows = [
            row for row in (scorecard.get("slice_execution_breakdown") or [])
            if row.get("scenario") == "normal" and int(row.get("completed") or 0) > 0
        ]
        reasons = []
        completed = sum(
            int(row.get("completed") or 0)
            for row in rows
            if row.get("scenario") == "normal"
        )
        if completed < int(min_completed):
            reasons.append("insufficient_completed_normal_simulations")
        small_window_rows = [
            row for row in rows
            if str(row.get("model_id") or "") == "small_window_trend_comparison_v1"
            and str(row.get("scenario") or "") == "normal"
            and int(row.get("completed") or 0) > 0
            and float(row.get("mean_net_bps") or -1e18) > 0.0
        ]
        small_window_slice_rows = [
            row for row in slice_rows
            if str(row.get("hypothesis") or "") == "recent_delta_volatility"
            and str(row.get("scenario") or "") == "normal"
            and int(row.get("completed") or 0) > 0
            and float(row.get("mean_net_bps") or -1e18) > 0.0
        ]
        if small_window_rows and small_window_slice_rows:
            safety_reasons = []
            if int(scorecard.get("execution_wiring_violations") or 0):
                safety_reasons.append("execution_wiring_violation")
            if int(scorecard.get("real_orders_submitted") or 0):
                safety_reasons.append("nonzero_real_orders_submitted")
            if int(scorecard.get("automatic_recoveries") or 0):
                safety_reasons.append("automatic_recovery_violation")
            result.update({
                "ready_for_phase4_review": not safety_reasons,
                "completed_normal_simulations": completed,
                "scorecard": scorecard,
                "readiness_mode": "small_window_proxy_fast_track",
                "primary_edge_source": "small_window_public_delta_proxy",
                "reasons": safety_reasons,
            })
            return result
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
        if not normal_primary or max(
            float(row.get("mean_net_bps") or -1e18) for row in normal_primary
        ) <= 0:
            reasons.append("no_positive_primary_execution_policy_at_normal_cost")
        if not stress_15 or max(
            float(row.get("mean_net_bps") or -1e18) for row in stress_15
        ) <= 0:
            reasons.append("no_positive_primary_execution_policy_at_1_5x_cost")
        if stress_2 and max(
            float(row.get("mean_net_bps") or -1e18) for row in stress_2
        ) < -abs(float(max_mean_2x_loss_bps)):
            reasons.append("catastrophic_primary_result_at_2x_cost")
        if not slice_rows:
            reasons.append("no_slice_level_execution_evidence")
        elif max(float(row.get("mean_net_bps") or -1e18) for row in slice_rows) <= 0:
            reasons.append("no_positive_execution_slice_at_normal_cost")
        if int(scorecard.get("execution_wiring_violations") or 0):
            reasons.append("execution_wiring_violation")
        if int(scorecard.get("real_orders_submitted") or 0):
            reasons.append("nonzero_real_orders_submitted")
        if int(scorecard.get("automatic_recoveries") or 0):
            reasons.append("automatic_recovery_violation")
        result.update({
            "ready_for_phase4_review": not reasons,
            "completed_normal_simulations": completed,
            "scorecard": scorecard,
            "reasons": reasons,
        })
        return result

    def get_phase4_validation_dataset(self, limit: int = 100000) -> list:
        """Return balanced immutable Phase-3 evidence joined to its source forecasts."""
        if not self.conn:
            return []
        try:
            per_candidate_scenario = 400
            try:
                if self.coordinator and hasattr(self.coordinator, "cfg"):
                    cfg = self.coordinator.cfg
                    per_candidate_scenario = max(
                        1,
                        int(getattr(cfg, "phase4_max_rows_per_candidate_scenario", 400) or 400),
                    )
            except Exception:
                pass
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    WITH ranked_completed AS (
                        SELECT simulation_id, forecast_id, model_id, hypothesis,
                               venue, symbol, direction, order_policy, scenario,
                               status, terminal_state, completed_ts, net_return_bps,
                               gross_return_bps, fill_ratio, profitable_after_costs,
                               execution_wired, real_orders_submitted,
                               ROW_NUMBER() OVER (
                                   PARTITION BY model_id, order_policy, scenario
                                   ORDER BY completed_ts DESC
                               ) AS rn
                        FROM simulated_orders
                        WHERE status='COMPLETED'
                    )
                    SELECT o.simulation_id, o.forecast_id, o.model_id, o.hypothesis,
                           o.venue, o.symbol, o.direction, o.order_policy, o.scenario,
                           o.status, o.terminal_state, o.completed_ts, o.net_return_bps,
                           o.gross_return_bps, o.fill_ratio, o.profitable_after_costs,
                           o.execution_wired, o.real_orders_submitted,
                           f.ts AS forecast_ts, f.target_ts, f.horizon_seconds,
                           f.probability_positive_net, f.expected_move_bps,
                           f.expected_cost_bps, f.expected_net_bps, f.raw_score,
                           f.payload AS forecast_payload,
                           ca.total_cost_bps, ca.fee_bps, ca.entry_spread_bps,
                           ca.exit_spread_bps, ca.entry_impact_bps, ca.exit_impact_bps,
                           ca.entry_latency_bps, ca.exit_latency_bps
                    FROM ranked_completed o
                    JOIN hypothesis_forecasts f ON f.forecast_id=o.forecast_id
                    LEFT JOIN simulated_cost_attribution ca ON ca.simulation_id=o.simulation_id
                    WHERE o.rn <= ?
                    ORDER BY o.completed_ts DESC, o.model_id, o.order_policy, o.scenario
                    LIMIT ?
                    """,
                    (int(per_candidate_scenario), int(limit or 100000)),
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            out = []
            for raw in rows:
                row = dict(zip(cols, raw))
                try:
                    payload = json.loads(row.pop("forecast_payload") or "{}")
                except Exception:
                    payload = {}
                inputs = payload.get("inputs") if isinstance(payload, dict) else {}
                inputs = inputs if isinstance(inputs, dict) else {}
                row["volatility_expansion"] = inputs.get("volatility_expansion")
                row["return_zscore"] = inputs.get("return_zscore", inputs.get("stretch_zscore"))
                row["volume_zscore"] = inputs.get("volume_zscore")
                row["range_position"] = inputs.get("range_position")
                row["forecast_payload"] = payload
                out.append(row)
            return out
        except Exception:
            logging.exception("Error fetching Phase-4 validation dataset")
            return []

    def persist_phase4_validation_report(self, report: Dict[str, Any]) -> bool:
        if not self.conn or not report.get("run_id"):
            return False
        if report.get("execution_wired") or int(report.get("real_orders_submitted") or 0):
            raise ValueError("Phase-4 report attempted to claim live execution")
        run_id = str(report.get("run_id"))
        readiness = report.get("readiness") or {}
        pbo = report.get("pbo") or {}
        champion = report.get("champion") or {}
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT OR REPLACE INTO phase4_validation_runs
                    (run_id, started_ts, completed_ts, status, validator_version,
                     rows_examined, primary_rows, candidate_count, pbo_estimate,
                     champion_key, ready_for_phase5_review, dataset_hash,
                     execution_wired, real_orders_submitted, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        run_id, report.get("started_ts"), report.get("completed_ts"),
                        report.get("status"), report.get("validator_version"),
                        int(report.get("rows_examined") or 0), int(report.get("primary_rows") or 0),
                        int(report.get("candidate_count") or 0), float(pbo.get("pbo_estimate") or 0.0),
                        champion.get("candidate_key"),
                        1 if readiness.get("ready_for_phase5_review") else 0,
                        # NOTE: 'candidate_results' and 'phase3_cycle' are intentionally excluded from the
                        # persisted run payload. Every candidate result is already individually inserted below
                        # into phase4_candidate_results, and 'phase3_cycle' is a full verbatim copy of the upstream
                        # simulation_runs payload (already durably stored there and reachable via run_id) -- both
                        # were pure duplication (this was the single largest per-row payload in the database,
                        # ~2.8MB/run before this fix).
                        report.get("dataset_hash"), 0, 0,
                        json.dumps({k: v for k, v in report.items() if k not in ("candidate_results", "phase3_cycle")}),
                    ),
                )
                for item in report.get("candidate_results") or []:
                    normal = item.get("normal") or {}
                    bootstrap = item.get("bootstrap") or {}
                    dsr = item.get("deflated_sharpe") or {}
                    c.execute(
                        """
                        INSERT OR REPLACE INTO phase4_candidate_results
                        (run_id, candidate_key, model_id, order_policy, normal_samples,
                         mean_net_bps, bootstrap_lower_95_bps, dsr_probability,
                         walk_forward_positive_ratio, parameter_positive_ratio,
                         symbol_holdout_positive_ratio, regime_holdout_positive_ratio,
                         symbol_profit_concentration, month_profit_concentration,
                         robust_score, passes_candidate_gates, payload)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            run_id, item.get("candidate_key"), item.get("model_id"), item.get("order_policy"),
                            int(normal.get("samples") or 0), normal.get("mean_net_bps"),
                            bootstrap.get("lower_95_bps"), dsr.get("dsr_probability"),
                            item.get("walk_forward_positive_ratio"), item.get("parameter_positive_ratio"),
                            item.get("symbol_holdout_positive_ratio"), item.get("regime_holdout_positive_ratio"),
                            item.get("symbol_profit_concentration"), item.get("month_profit_concentration"),
                            item.get("robust_score"), 1 if item.get("passes_candidate_gates") else 0,
                            json.dumps(item),
                        ),
                    )
                for item in report.get("fold_results") or []:
                    test = item.get("test") or {}
                    c.execute(
                        """
                        INSERT OR REPLACE INTO phase4_fold_results
                        (run_id, candidate_key, fold_index, test_start_ts, test_end_ts,
                         test_samples, test_mean_net_bps, test_positive, payload)
                        VALUES (?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            run_id, item.get("candidate_key"), int(item.get("fold_index") or 0),
                            item.get("test_start_ts"), item.get("test_end_ts"),
                            int(test.get("samples") or 0), test.get("mean_net_bps"),
                            1 if item.get("test_positive") else 0, json.dumps(item),
                        ),
                    )
                for item in report.get("holdout_results") or []:
                    test = item.get("test") or {}
                    c.execute(
                        """
                        INSERT OR REPLACE INTO phase4_holdout_results
                        (run_id, candidate_key, holdout_type, holdout_value,
                         test_samples, test_mean_net_bps, test_positive, payload)
                        VALUES (?,?,?,?,?,?,?,?)
                        """,
                        (
                            run_id, item.get("candidate_key"), item.get("holdout_type"),
                            item.get("holdout_value"), int(test.get("samples") or 0),
                            test.get("mean_net_bps"), 1 if item.get("test_positive") else 0,
                            json.dumps(item),
                        ),
                    )
                for item in report.get("perturbation_results") or []:
                    metrics = item.get("metrics") or {}
                    c.execute(
                        """
                        INSERT OR REPLACE INTO phase4_perturbation_results
                        (run_id, candidate_key, probability_gate, expected_net_gate_bps,
                         selected_samples, mean_net_bps, positive, payload)
                        VALUES (?,?,?,?,?,?,?,?)
                        """,
                        (
                            run_id, item.get("candidate_key"), item.get("probability_gate"),
                            item.get("expected_net_gate_bps"), int(item.get("selected_samples") or 0),
                            metrics.get("mean_net_bps"), 1 if item.get("positive") else 0,
                            json.dumps(item),
                        ),
                    )
                self.conn.commit()
            return True
        except Exception:
            try:
                self.conn.rollback()
            except Exception:
                pass
            logging.exception("Error persisting Phase-4 validation report")
            return False

    def get_phase4_validation_runs(self, limit: int = 50) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute("SELECT * FROM phase4_validation_runs ORDER BY completed_ts DESC LIMIT ?", (int(limit or 50),))
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            logging.exception("Error fetching Phase-4 validation runs")
            return []

    def get_phase4_candidate_results(self, run_id: Optional[str] = None, limit: int = 100) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                if not run_id:
                    row = c.execute("SELECT run_id FROM phase4_validation_runs ORDER BY completed_ts DESC LIMIT 1").fetchone()
                    run_id = row[0] if row else None
                if not run_id:
                    return []
                c.execute(
                    "SELECT * FROM phase4_candidate_results WHERE run_id=? ORDER BY robust_score DESC LIMIT ?",
                    (run_id, int(limit or 100)),
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            logging.exception("Error fetching Phase-4 candidate results")
            return []

    def get_phase4_latest_report(self) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                row = self.conn.execute(
                    "SELECT payload FROM phase4_validation_runs ORDER BY completed_ts DESC LIMIT 1"
                ).fetchone()
            return json.loads(row[0]) if row and row[0] else {}
        except Exception:
            return {}

    def get_phase4_readiness(self) -> Dict[str, Any]:
        report = self.get_phase4_latest_report()
        if not report:
            return {
                "phase": 4, "ready_for_phase5_review": False,
                "execution_eligible": False, "human_review_required": True,
                "real_orders_submitted": 0, "reasons": ["no_phase4_validation_report"],
            }
        readiness = dict(report.get("readiness") or {})
        champion = report.get("champion") or {}
        drift_threshold_bps = 5.0
        min_recent_samples = 12
        try:
            if self.coordinator and hasattr(self.coordinator, "cfg"):
                drift_threshold_bps = float(getattr(self.coordinator.cfg, "phase4_drift_threshold_bps", 5.0) or 5.0)
                min_recent_samples = int(getattr(self.coordinator.cfg, "phase4_drift_min_recent_samples", 12) or 12)
        except Exception:
            pass
        drift = _drift_state(
            champion.get("mean_realized_net_bps"),
            champion.get("recent_mean_net_bps"),
            recent_samples=int(champion.get("recent_samples") or 0),
            drift_threshold_bps=drift_threshold_bps,
            min_recent_samples=min_recent_samples,
        )
        reasons = list(readiness.get("reasons") or [])
        if drift.get("drifted"):
            reasons.append("phase4_recent_edge_drift")
        readiness["reasons"] = reasons
        readiness["ready_for_phase5_review"] = not reasons
        readiness["drift_state"] = drift
        readiness.setdefault("phase", 4)
        readiness["execution_eligible"] = False
        readiness["human_review_required"] = True
        readiness["real_orders_submitted"] = 0
        return readiness

    def persist_phase5_freeze(self, freeze: Dict[str, Any]) -> bool:
        if not self.conn:
            return False
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute("UPDATE phase5_model_freezes SET status='SUPERSEDED' WHERE status='ACTIVE'")
                c.execute(
                    """
                    INSERT OR REPLACE INTO phase5_model_freezes
                    (freeze_id, phase4_run_id, candidate_key, model_id, order_policy,
                     approved_by, approved_ts, phase4_dataset_hash, config_hash, status,
                     shadow_only, execution_eligible, revoked_ts, revoke_reason, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        freeze.get("freeze_id"), freeze.get("phase4_run_id"), freeze.get("candidate_key"),
                        freeze.get("model_id"), freeze.get("order_policy"), freeze.get("approved_by"),
                        freeze.get("approved_ts"), freeze.get("phase4_dataset_hash"), freeze.get("config_hash"),
                        freeze.get("status", "ACTIVE"), 1, 0, None, None, json.dumps(freeze),
                    ),
                )
                self.conn.commit()
            return True
        except Exception:
            logging.exception("Error persisting Phase-5 model freeze")
            return False

    def revoke_phase5_freeze(self, reason: str, revoked_ts: Optional[float] = None) -> bool:
        if not self.conn:
            return False
        try:
            with self._lock:
                self.conn.execute(
                    "UPDATE phase5_model_freezes SET status='REVOKED', revoked_ts=?, revoke_reason=? WHERE status='ACTIVE'",
                    (float(revoked_ts or time.time()), str(reason or "human_revocation")),
                )
                self.conn.commit()
            return True
        except Exception:
            logging.exception("Error revoking Phase-5 model freeze")
            return False

    def get_phase5_active_freeze(self) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                row = c.execute(
                    "SELECT * FROM phase5_model_freezes WHERE status='ACTIVE' ORDER BY approved_ts DESC LIMIT 1"
                ).fetchone()
                if not row:
                    return {}
                cols = [item[0] for item in c.description]
            record = dict(zip(cols, row))
            try:
                payload = json.loads(record.get("payload") or "{}")
                if isinstance(payload, dict):
                    record.update(payload)
            except Exception:
                pass
            record["execution_eligible"] = False
            record["shadow_only"] = True
            return record
        except Exception:
            logging.exception("Error fetching Phase-5 active freeze")
            return {}

    def get_phase5_forecast_candidates(
        self,
        *,
        model_id: str,
        symbol: Optional[str] = None,
        direction: Optional[str] = None,
        approved_after_ts: float,
        limit: int = 25,
        now_ts: Optional[float] = None,
    ) -> list:
        if not self.conn:
            return []
        try:
            now_ts = float(now_ts if now_ts is not None else time.time())
            with self._lock:
                c = self.conn.cursor()
                filters = [
                    "f.model_id=?",
                    "f.abstain=0",
                    "f.ts>=?",
                    "f.settled=0",
                    "f.target_ts>?",
                    """
                      NOT EXISTS (
                          SELECT 1 FROM phase5_shadow_intents s WHERE s.forecast_id=f.forecast_id
                      )
                    """,
                ]
                params: list[Any] = [str(model_id), float(approved_after_ts), now_ts]
                if symbol:
                    filters.append("f.symbol=?")
                    params.append(str(symbol))
                if direction:
                    filters.append("UPPER(f.direction)=?")
                    params.append(str(direction).upper())
                params.append(int(limit or 25))
                c.execute(
                    f"""
                    SELECT f.*
                    FROM hypothesis_forecasts f
                    WHERE {" AND ".join(filters)}
                    ORDER BY f.ts ASC LIMIT ?
                    """,
                    tuple(params),
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
                out = []
                for raw in rows:
                    record = dict(zip(cols, raw))
                    try:
                        payload = json.loads(record.get("payload") or "{}")
                        if isinstance(payload, dict):
                            record.update(payload)
                    except Exception:
                        pass
                    obs = c.execute(
                        "SELECT * FROM observation_snapshots WHERE symbol=? AND ts<=? ORDER BY ts DESC LIMIT 1",
                        (record.get("symbol"), record.get("ts")),
                    ).fetchone()
                    if obs:
                        obs_cols = [item[0] for item in c.description]
                        observation = dict(zip(obs_cols, obs))
                        try:
                            payload = json.loads(observation.get("payload") or "{}")
                            if isinstance(payload, dict):
                                observation.update(payload)
                        except Exception:
                            pass
                    else:
                        observation = {}
                    record["entry_observation"] = observation
                    record["execution_eligible"] = False
                    out.append(record)
            return out
        except Exception:
            logging.exception("Error fetching Phase-5 forecast candidates")
            return []

    def get_phase5_frozen_shadow_admission_candidates(
        self,
        *,
        model_id: str,
        symbol: Optional[str],
        direction: Optional[str],
        approved_after_ts: float,
        limit: int = 25,
        now_ts: Optional[float] = None,
        min_utility: float = 0.30,
    ) -> list:
        """Return Path-A research-only candidates for a frozen Phase-4 slice.

        These are not executable forecasts. They are abstaining Phase-2 rows whose
        raw frozen-model directional utility matches the approved Phase-4 slice,
        but whose generic Phase-2 cost/edge gate abstained. Phase 5 may shadow
        them as paper-only directional economics while keeping live authority at
        zero.
        """
        if not self.conn or not symbol or not direction:
            return []
        frozen_direction = str(direction or "").upper()
        if frozen_direction not in {"UP", "DOWN"}:
            return []
        allowed_abstain_reasons = {
            "insufficient_cost_adjusted_edge",
            "cost_above_research_ceiling",
        }
        try:
            now_ts = float(now_ts if now_ts is not None else time.time())
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    SELECT f.*
                    FROM hypothesis_forecasts f
                    WHERE f.model_id=? AND f.symbol=? AND f.abstain=1 AND f.ts>=?
                      AND f.settled=0
                      AND f.target_ts>?
                      AND NOT EXISTS (
                          SELECT 1 FROM phase5_shadow_intents s WHERE s.forecast_id=f.forecast_id
                      )
                    ORDER BY f.ts ASC LIMIT ?
                    """,
                    (str(model_id), str(symbol), float(approved_after_ts), now_ts, int(max(1, limit or 25) * 4)),
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
                out = []
                for raw in rows:
                    record = dict(zip(cols, raw))
                    try:
                        payload = json.loads(record.get("payload") or "{}")
                        if isinstance(payload, dict):
                            record.update(payload)
                    except Exception:
                        payload = {}
                    reason_values = {
                        str(item)
                        for item in (
                            record.get("reasons")
                            or (payload.get("reasons") if isinstance(payload, dict) else None)
                            or [record.get("reason")]
                        )
                        if item
                    }
                    if not reason_values or not reason_values.issubset(allowed_abstain_reasons):
                        continue
                    inputs = record.get("inputs") if isinstance(record.get("inputs"), dict) else {}
                    try:
                        utility = float(inputs.get("directional_utility"))
                    except (TypeError, ValueError):
                        try:
                            utility = float(record.get("raw_score"))
                        except (TypeError, ValueError):
                            continue
                    if not math.isfinite(utility):
                        continue
                    if frozen_direction == "DOWN" and utility > -abs(float(min_utility)):
                        continue
                    if frozen_direction == "UP" and utility < abs(float(min_utility)):
                        continue
                    move_components = inputs.get("move_components_bps") if isinstance(inputs.get("move_components_bps"), dict) else {}
                    component_values = []
                    for value in move_components.values():
                        try:
                            number = float(value)
                            if math.isfinite(number):
                                component_values.append(abs(number))
                        except (TypeError, ValueError):
                            pass
                    expected_move = max(component_values) if component_values else abs(utility) * 25.0
                    try:
                        expected_cost = float(record.get("expected_cost_bps") or (inputs.get("cost") or {}).get("total_bps") or 0.0)
                    except (TypeError, ValueError):
                        expected_cost = 0.0
                    expected_net = expected_move - expected_cost
                    probability = 0.50 if expected_net <= 0 else min(0.74, 0.50 + min(0.24, abs(utility) * 0.12))
                    record.update({
                        "direction": frozen_direction,
                        "abstain": False,
                        "phase5_shadow_admission": {
                            "mode": "frozen_champion_directional_probe",
                            "authority": "research_shadow_only",
                            "reason": "phase5_frozen_champion_shadow_admission",
                            "source_abstain": True,
                            "source_reasons": sorted(reason_values),
                            "directional_utility": round(utility, 8),
                            "min_utility": abs(float(min_utility)),
                        },
                        "reason": "phase5_frozen_champion_shadow_admission",
                        "reasons": ["phase5_frozen_champion_shadow_admission", *sorted(reason_values)],
                        "expected_move_bps": round(expected_move, 6),
                        "expected_cost_bps": round(expected_cost, 6),
                        "expected_net_bps": round(expected_net, 6),
                        "probability_positive_net": round(probability, 6),
                        "execution_eligible": False,
                    })
                    obs = c.execute(
                        "SELECT * FROM observation_snapshots WHERE symbol=? AND ts<=? ORDER BY ts DESC LIMIT 1",
                        (record.get("symbol"), record.get("ts")),
                    ).fetchone()
                    if obs:
                        obs_cols = [item[0] for item in c.description]
                        observation = dict(zip(obs_cols, obs))
                        try:
                            obs_payload = json.loads(observation.get("payload") or "{}")
                            if isinstance(obs_payload, dict):
                                observation.update(obs_payload)
                        except Exception:
                            pass
                    else:
                        observation = {}
                    record["entry_observation"] = observation
                    out.append(record)
                    if len(out) >= int(limit or 25):
                        break
            return out
        except Exception:
            logging.exception("Error fetching Phase-5 frozen shadow admission candidates")
            return []

    def get_phase5_small_window_shadow_candidates(
        self,
        *,
        model_id: str,
        symbol: Optional[str],
        direction: Optional[str],
        approved_after_ts: float,
        limit: int = 25,
        now_ts: Optional[float] = None,
    ) -> list:
        """Return fresh small-window paper candidates for a frozen shadow slice.

        This is the direct adapter for the high-volatility route: Phase 5 can
        shadow a rapid paper tape trade without requiring a hypothesis_forecasts
        row. It still creates only never-transmitted shadow intents.
        """
        if not self.conn or str(model_id or "") != "small_window_trend_comparison_v1":
            return []
        frozen_direction = str(direction or "").upper().strip()
        if frozen_direction and frozen_direction not in {"UP", "DOWN"}:
            return []
        try:
            now_ts = float(now_ts if now_ts is not None else time.time())
            with self._lock:
                c = self.conn.cursor()
                filters = [
                    "t.model_id=?",
                    "t.status='OPEN'",
                    "t.entry_ts>=?",
                    "t.target_ts>?",
                    """
                      NOT EXISTS (
                          SELECT 1 FROM phase5_shadow_intents s
                          WHERE s.forecast_id='small-window:' || t.trade_id
                      )
                    """,
                ]
                params: list[Any] = [str(model_id), float(approved_after_ts), now_ts]
                if symbol:
                    filters.append("t.symbol=?")
                    params.append(str(symbol))
                if frozen_direction:
                    filters.append("UPPER(t.direction)=?")
                    params.append(frozen_direction)
                params.append(int(limit or 25))
                c.execute(
                    f"""
                    SELECT t.*
                    FROM rapid_paper_tape_trades t
                    WHERE {" AND ".join(filters)}
                    ORDER BY t.expected_net_bps DESC, t.entry_ts DESC
                    LIMIT ?
                    """,
                    tuple(params),
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
                out = []
                for raw in rows:
                    trade = dict(zip(cols, raw))
                    try:
                        payload = json.loads(trade.get("payload") or "{}")
                    except Exception:
                        payload = {}
                    candidate_payload = payload.get("candidate") if isinstance(payload, dict) else {}
                    if not isinstance(candidate_payload, dict):
                        candidate_payload = {}
                    latest_observation = (
                        candidate_payload.get("latest_observation")
                        if isinstance(candidate_payload.get("latest_observation"), dict)
                        else {}
                    )
                    observation = dict(latest_observation)
                    if observation and isinstance(observation.get("payload"), str):
                        try:
                            obs_payload = json.loads(observation.get("payload") or "{}")
                            if isinstance(obs_payload, dict):
                                observation.update(obs_payload)
                        except Exception:
                            pass
                    forecast = {
                        "forecast_id": f"small-window:{trade.get('trade_id')}",
                        "run_id": trade.get("run_id"),
                        "ts": float(trade.get("entry_ts") or 0.0),
                        "forecast_ts": float(trade.get("entry_ts") or 0.0),
                        "target_ts": float(trade.get("target_ts") or 0.0),
                        "venue": trade.get("venue") or candidate_payload.get("venue") or "kraken",
                        "symbol": trade.get("symbol"),
                        "model_id": trade.get("model_id"),
                        "hypothesis": trade.get("hypothesis") or candidate_payload.get("hypothesis") or "recent_delta_volatility",
                        "horizon_seconds": max(
                            1,
                            int(round(float(trade.get("target_ts") or 0.0) - float(trade.get("entry_ts") or 0.0))),
                        ),
                        "direction": str(trade.get("direction") or "").upper(),
                        "entry_price": trade.get("entry_price"),
                        "probability_positive_net": trade.get("probability_positive_net"),
                        "expected_move_bps": candidate_payload.get("absolute_move_bps"),
                        "expected_cost_bps": trade.get("expected_cost_bps"),
                        "expected_net_bps": trade.get("expected_net_bps"),
                        "raw_score": candidate_payload.get("score") or trade.get("expected_net_bps"),
                        "abstain": False,
                        "reason": "phase5_small_window_shadow_candidate",
                        "entry_observation": observation,
                        "phase5_shadow_admission": {
                            "mode": "small_window_recent_delta_shadow",
                            "authority": "research_shadow_only",
                            "source_trade_id": trade.get("trade_id"),
                            "source_status": trade.get("status"),
                            "window_sec": candidate_payload.get("window_sec"),
                            "window_label": candidate_payload.get("window_label"),
                            "repeatability_required_for_live": True,
                        },
                        "execution_eligible": False,
                    }
                    out.append(forecast)
            return out
        except Exception:
            logging.exception("Error fetching Phase-5 small-window shadow candidates")
            return []

    def persist_shadow_intent(self, intent: Dict[str, Any]) -> bool:
        if not self.conn:
            return False
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT OR IGNORE INTO phase5_shadow_intents
                    (shadow_intent_id, forecast_id, freeze_id, phase4_run_id, candidate_key,
                     model_id, order_policy, venue, symbol, direction, side, order_type,
                     time_in_force, quantity, notional_usd, reference_price, limit_price,
                     stop_distance_bps, risk_budget_usd, predicted_move_bps, predicted_cost_bps,
                     predicted_net_bps, probability_positive_net, horizon_seconds, created_ts,
                     target_ts, data_quality, spread_bps, depth_usd_25bps, venue_profile_version,
                     config_hash, status, transmission_status, private_endpoint_called,
                     credentials_used, transmission_attempted, settled, execution_wired,
                     live_eligible, real_orders_submitted, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        intent.get("shadow_intent_id"), intent.get("forecast_id"), intent.get("freeze_id"),
                        intent.get("phase4_run_id"), intent.get("candidate_key"), intent.get("model_id"),
                        intent.get("order_policy"), intent.get("venue"), intent.get("symbol"),
                        intent.get("direction"), intent.get("side"), intent.get("order_type"),
                        intent.get("time_in_force"), intent.get("quantity"), intent.get("notional_usd"),
                        intent.get("reference_price"), intent.get("limit_price"), intent.get("stop_distance_bps"),
                        intent.get("risk_budget_usd"), intent.get("predicted_move_bps"), intent.get("predicted_cost_bps"),
                        intent.get("predicted_net_bps"), intent.get("probability_positive_net"),
                        int(intent.get("horizon_seconds") or 0), intent.get("created_ts"), intent.get("target_ts"),
                        intent.get("data_quality"), intent.get("spread_bps"), intent.get("depth_usd_25bps"),
                        intent.get("venue_profile_version"), intent.get("config_hash"), "READY_NOT_TRANSMITTED",
                        "NEVER_TRANSMITTED", 0, 0, 0, 0, 0, 0, 0, json.dumps(intent),
                    ),
                )
                created = c.rowcount > 0
                self.conn.commit()
            return created
        except Exception:
            logging.exception("Error persisting Phase-5 shadow intent")
            return False

    def settle_mature_shadow_intents(self, settler: Any, *, now_ts: Optional[float] = None, tolerance_sec: int = 900) -> Dict[str, Any]:
        result = {"phase": 5, "examined": 0, "settled": 0, "missed_fills": 0,
                  "transmission_attempts": 0, "real_orders_submitted": 0}
        if not self.conn:
            result["error"] = "data_store_unavailable"
            return result
        now = float(now_ts or time.time())
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    "SELECT * FROM phase5_shadow_intents WHERE settled=0 AND target_ts<=? ORDER BY target_ts ASC",
                    (now,),
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
                for raw in rows:
                    intent = dict(zip(cols, raw))
                    result["examined"] += 1
                    observations_raw = c.execute(
                        """
                        SELECT * FROM observation_snapshots
                        WHERE symbol=? AND ts>=? AND ts<=?
                        ORDER BY ts ASC
                        """,
                        (intent.get("symbol"), float(intent.get("created_ts") or 0.0),
                         float(intent.get("target_ts") or 0.0) + float(tolerance_sec)),
                    ).fetchall()
                    obs_cols = [item[0] for item in c.description]
                    observations = []
                    for obs_raw in observations_raw:
                        obs = dict(zip(obs_cols, obs_raw))
                        try:
                            payload = json.loads(obs.get("payload") or "{}")
                            if isinstance(payload, dict):
                                obs.update(payload)
                        except Exception:
                            pass
                        observations.append(obs)
                    settlement = settler.settle(intent, observations, settled_ts=now)
                    if settlement is None:
                        continue
                    payload = settlement.to_dict() if hasattr(settlement, "to_dict") else dict(settlement)
                    c.execute(
                        """
                        INSERT OR IGNORE INTO phase5_shadow_settlements
                        (settlement_id, shadow_intent_id, forecast_id, settled_ts, status,
                         fill_model, fill_ratio, intended_entry_price, hypothetical_entry_price,
                         reference_exit_price, hypothetical_exit_price, entry_slippage_bps,
                         exit_slippage_bps, fee_bps, impact_bps, observed_total_cost_bps,
                         predicted_cost_bps, cost_error_bps, gross_directional_return_bps,
                         net_return_bps, profitable_after_costs, data_quality,
                         transmission_attempted, real_orders_submitted, payload)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            payload.get("settlement_id"), payload.get("shadow_intent_id"), payload.get("forecast_id"),
                            payload.get("settled_ts"), payload.get("status"), payload.get("fill_model"),
                            payload.get("fill_ratio"), payload.get("intended_entry_price"),
                            payload.get("hypothetical_entry_price"), payload.get("reference_exit_price"),
                            payload.get("hypothetical_exit_price"), payload.get("entry_slippage_bps"),
                            payload.get("exit_slippage_bps"), payload.get("fee_bps"), payload.get("impact_bps"),
                            payload.get("observed_total_cost_bps"), payload.get("predicted_cost_bps"),
                            payload.get("cost_error_bps"), payload.get("gross_directional_return_bps"),
                            payload.get("net_return_bps"), 1 if payload.get("profitable_after_costs") else 0,
                            payload.get("data_quality"), 0, 0, json.dumps(payload),
                        ),
                    )
                    c.execute(
                        "UPDATE phase5_shadow_intents SET settled=1, status=? WHERE shadow_intent_id=?",
                        (payload.get("status"), intent.get("shadow_intent_id")),
                    )
                    result["settled"] += 1
                    if payload.get("status") == "MISSED_FILL":
                        result["missed_fills"] += 1
                self.conn.commit()
            return result
        except Exception:
            logging.exception("Error settling Phase-5 shadow intents")
            result["error"] = "settlement_failed"
            return result

    def persist_phase5_shadow_run(self, report: Dict[str, Any]) -> bool:
        if not self.conn:
            return False
        try:
            with self._lock:
                readiness = report.get("readiness") or {}
                settlement = report.get("settlement") or {}
                freeze = report.get("freeze") or {}
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO phase5_shadow_runs
                    (run_id, started_ts, completed_ts, status, freeze_id, intents_created,
                     intents_skipped, settlements_created, ready_for_phase6_review, dataset_hash,
                     execution_wired, private_exchange_access, transmission_attempts,
                     real_orders_submitted, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        report.get("run_id"), report.get("started_ts"), report.get("completed_ts"),
                        report.get("status"), freeze.get("freeze_id"), int(report.get("intents_created") or 0),
                        int(report.get("intents_skipped") or 0), int(settlement.get("settled") or 0),
                        1 if readiness.get("ready_for_phase6_review") else 0, report.get("dataset_hash"),
                        0, 0, 0, 0, json.dumps(report),
                    ),
                )
                self.conn.commit()
            return True
        except Exception:
            logging.exception("Error persisting Phase-5 shadow run")
            return False

    def get_phase5_shadow_runs(self, limit: int = 50) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute("SELECT * FROM phase5_shadow_runs ORDER BY completed_ts DESC LIMIT ?", (int(limit or 50),))
                rows = c.fetchall(); cols = [item[0] for item in c.description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            return []

    def get_phase5_shadow_intents(self, limit: int = 250) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute("SELECT * FROM phase5_shadow_intents ORDER BY created_ts DESC LIMIT ?", (int(limit or 250),))
                rows = c.fetchall(); cols = [item[0] for item in c.description]
            out = []
            for row in rows:
                record = dict(zip(cols, row))
                record["execution_wired"] = False
                record["live_eligible"] = False
                record["real_orders_submitted"] = 0
                out.append(record)
            return out
        except Exception:
            return []

    def get_phase5_shadow_settlements(self, limit: int = 250) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute("SELECT * FROM phase5_shadow_settlements ORDER BY settled_ts DESC LIMIT ?", (int(limit or 250),))
                rows = c.fetchall(); cols = [item[0] for item in c.description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            return []

    def get_phase5_scorecard(self, *, distinct_bucket_hours: int = 24) -> Dict[str, Any]:
        result = {"phase": 5, "mode": "public_shadow_only", "execution_eligible": False,
                  "transmission_attempts": 0, "real_orders_submitted": 0}
        if not self.conn:
            result["error"] = "data_store_unavailable"
            return result
        try:
            bucket_sql = _distinct_bucket_sql("i.target_ts", distinct_bucket_hours)
            recent_window = 24
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    f"""
                    SELECT COUNT(*) AS settled,
                           SUM(CASE WHEN s.status='SETTLED' THEN 1 ELSE 0 END) AS filled,
                           AVG(s.fill_ratio) AS mean_fill_ratio,
                           AVG(CASE WHEN s.status='SETTLED' THEN s.net_return_bps END) AS mean_net_bps,
                           AVG(CASE WHEN s.status='SETTLED' THEN s.profitable_after_costs END) AS win_rate,
                           AVG(CASE WHEN s.status='SETTLED' THEN s.cost_error_bps END) AS cost_mae_bps,
                           AVG(s.data_quality) AS mean_data_quality,
                           {bucket_sql} AS distinct_time_buckets,
                           SUM(s.transmission_attempted) AS transmission_attempts,
                           SUM(s.real_orders_submitted) AS real_orders_submitted
                    FROM phase5_shadow_settlements s
                    JOIN phase5_shadow_intents i ON i.shadow_intent_id=s.shadow_intent_id
                    """
                )
                row = c.fetchone()
                cols = [item[0] for item in c.description]
                c.execute(
                    """
                    SELECT s.net_return_bps
                    FROM phase5_shadow_settlements s
                    JOIN phase5_shadow_intents i ON i.shadow_intent_id=s.shadow_intent_id
                    WHERE s.status='SETTLED'
                    ORDER BY i.target_ts DESC, s.settled_ts DESC
                    LIMIT ?
                    """,
                    (int(recent_window),),
                )
                recent_rows = c.fetchall()
            metrics = dict(zip(cols, row)) if row else {}
            for key in ("mean_fill_ratio", "mean_net_bps", "win_rate", "cost_mae_bps", "mean_data_quality"):
                if metrics.get(key) is not None:
                    metrics[key] = round(float(metrics[key]), 8)
            recent_returns = [float(item[0]) for item in recent_rows if item and item[0] is not None]
            metrics["recent_settled"] = len(recent_returns)
            metrics["recent_mean_net_bps"] = (
                round(sum(recent_returns) / len(recent_returns), 8)
                if recent_returns else None
            )
            result.update(metrics)
            result["distinct_snapshot_bucket_hours"] = int(distinct_bucket_hours or 24)
            result["transmission_attempts"] = int(result.get("transmission_attempts") or 0)
            result["real_orders_submitted"] = int(result.get("real_orders_submitted") or 0)
            return result
        except Exception:
            logging.exception("Error computing Phase-5 scorecard")
            result["error"] = "scorecard_failed"
            return result

    def get_phase5_readiness(self, *, min_distinct_days: int = 30, min_settled: int = 100,
                             max_cost_mae_bps: float = 20.0, min_fill_ratio: float = 0.50,
                             require_positive_mean: bool = True, current_config_hash: Optional[str] = None,
                             distinct_bucket_hours: int = 24) -> Dict[str, Any]:
        score = self.get_phase5_scorecard(distinct_bucket_hours=distinct_bucket_hours)
        freeze = self.get_phase5_active_freeze()
        reasons = []
        if not freeze:
            reasons.append("no_active_human_approved_freeze")
        if freeze and current_config_hash and freeze.get("config_hash") != current_config_hash:
            reasons.append("frozen_parameter_drift")
        if int(score.get("settled") or 0) < int(min_settled):
            reasons.append("insufficient_settled_shadow_intents")
        if int(score.get("distinct_time_buckets") or 0) < int(min_distinct_days):
            reasons.append("insufficient_distinct_shadow_snapshots")
        if float(score.get("mean_fill_ratio") or 0.0) < float(min_fill_ratio):
            reasons.append("hypothetical_fill_ratio_below_gate")
        if score.get("cost_mae_bps") is None or float(score.get("cost_mae_bps") or 0.0) > float(max_cost_mae_bps):
            reasons.append("cost_model_error_above_gate")
        if require_positive_mean and (score.get("mean_net_bps") is None or float(score.get("mean_net_bps") or 0.0) <= 0.0):
            reasons.append("shadow_mean_net_not_positive")
        if int(score.get("transmission_attempts") or 0) != 0:
            reasons.append("transmission_attempt_detected")
        if int(score.get("real_orders_submitted") or 0) != 0:
            reasons.append("real_order_submission_detected")
        drift_threshold_bps = 5.0
        min_recent_samples = 12
        try:
            if self.coordinator and hasattr(self.coordinator, "cfg"):
                drift_threshold_bps = float(getattr(self.coordinator.cfg, "phase5_drift_threshold_bps", 5.0) or 5.0)
                min_recent_samples = int(getattr(self.coordinator.cfg, "phase5_drift_min_recent_samples", 12) or 12)
        except Exception:
            pass
        drift = _drift_state(
            score.get("mean_net_bps"),
            score.get("recent_mean_net_bps"),
            recent_samples=int(score.get("recent_settled") or 0),
            drift_threshold_bps=drift_threshold_bps,
            min_recent_samples=min_recent_samples,
        )
        if drift.get("drifted"):
            reasons.append("phase5_recent_shadow_drift")
        live_order_rows = 0
        try:
            live_order_rows = int(self.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0])
        except Exception:
            live_order_rows = -1
        if live_order_rows != 0:
            reasons.append("live_order_table_not_empty")
        return {
            "phase": 5,
            "ready_for_phase6_review": not reasons,
            "execution_eligible": False,
            "human_review_required": True,
            "automatic_promotion": False,
            "reasons": reasons,
            "scorecard": score,
            "drift_state": drift,
            "freeze": freeze,
            "live_order_rows": live_order_rows,
            "transmission_attempts": int(score.get("transmission_attempts") or 0),
            "real_orders_submitted": 0,
        }

    def store_executor_event(self, payload: Dict[str, Any]):
        if not self.conn:
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO executor_events
                    (ts, executor, symbol, side, status, qty, price, notional_usd,
                     net_margin_pct, route_loss_pct, reason, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        payload.get("ts", time.time()),
                        payload.get("executor"),
                        payload.get("symbol"),
                        payload.get("side"),
                        payload.get("status"),
                        payload.get("qty"),
                        payload.get("price"),
                        payload.get("notional_usd"),
                        payload.get("net_margin_pct"),
                        payload.get("route_loss_pct"),
                        payload.get("reason"),
                        json.dumps(payload),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error storing executor event")

    def get_executor_events(self, symbol: Optional[str] = None, days: int = 30) -> list:
        if not self.conn:
            return []
        try:
            cutoff = time.time() - float(days) * 86400.0
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute("SELECT * FROM executor_events WHERE symbol=? AND ts>=? ORDER BY ts ASC", (symbol, cutoff))
                else:
                    c.execute("SELECT * FROM executor_events WHERE ts>=? ORDER BY ts ASC", (cutoff,))
                cols = [d[0] for d in c.description]
                return [dict(zip(cols, row)) for row in c.fetchall()]
        except Exception:
            return []

    def upsert_hummingbot_lifecycle(self, payload: Dict[str, Any]):
        if not self.conn or not payload.get("executor_id"):
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO hummingbot_executor_lifecycle
                    (executor_id, executor_type, symbol, side, state, attempts, created_ts,
                     updated_ts, stopped_ts, reason, config, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(executor_id) DO UPDATE SET
                      executor_type=excluded.executor_type,
                      symbol=excluded.symbol,
                      side=excluded.side,
                      state=excluded.state,
                      attempts=excluded.attempts,
                      updated_ts=excluded.updated_ts,
                      stopped_ts=excluded.stopped_ts,
                      reason=excluded.reason,
                      config=excluded.config,
                      payload=excluded.payload
                    """,
                    (
                        payload.get("executor_id"),
                        payload.get("executor_type"),
                        payload.get("symbol"),
                        payload.get("side"),
                        payload.get("state"),
                        int(payload.get("attempts") or 0),
                        payload.get("created_ts", time.time()),
                        payload.get("updated_ts", time.time()),
                        payload.get("stopped_ts"),
                        payload.get("reason"),
                        json.dumps(payload.get("config") or {}),
                        json.dumps(payload),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error upserting Hummingbot lifecycle")

    def get_hummingbot_lifecycle(self, executor_id: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                if executor_id:
                    c.execute("SELECT * FROM hummingbot_executor_lifecycle WHERE executor_id=?", (executor_id,))
                else:
                    c.execute("SELECT * FROM hummingbot_executor_lifecycle ORDER BY updated_ts DESC LIMIT ?", (int(limit or 100),))
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = {}
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    d.update(json.loads(d.get("payload") or "{}"))
                except Exception:
                    pass
                out[d.get("executor_id")] = d
            return out
        except Exception:
            return {}

    def upsert_worker_performance(self, worker: str, payload: Dict[str, Any]):
        if not self.conn or not worker:
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO worker_performance
                    (worker, total, wins, losses, recent, updated_ts, payload)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(worker) DO UPDATE SET
                      total=excluded.total,
                      wins=excluded.wins,
                      losses=excluded.losses,
                      recent=excluded.recent,
                      updated_ts=excluded.updated_ts,
                      payload=excluded.payload
                    """,
                    (
                        worker,
                        int(payload.get("total") or 0),
                        int(payload.get("wins") or 0),
                        int(payload.get("losses") or 0),
                        json.dumps(payload.get("recent") or []),
                        payload.get("updated_ts", time.time()),
                        json.dumps(payload),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error upserting worker performance")

    def get_worker_performance(self) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute("SELECT * FROM worker_performance")
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = {}
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    payload = json.loads(d.get("payload") or "{}")
                    d.update(payload)
                except Exception:
                    try:
                        d["recent"] = json.loads(d.get("recent") or "[]")
                    except Exception:
                        d["recent"] = []
                out[d.get("worker")] = d
            return out
        except Exception:
            return {}

    def upsert_public_bot_backtest(self, run_id: str, payload: Dict[str, Any]):
        if not self.conn or not run_id:
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO public_bot_backtests
                    (run_id, engine, symbol, status, export_path, metrics, created_ts, updated_ts, payload)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(run_id) DO UPDATE SET
                      engine=excluded.engine,
                      symbol=excluded.symbol,
                      status=excluded.status,
                      export_path=excluded.export_path,
                      metrics=excluded.metrics,
                      updated_ts=excluded.updated_ts,
                      payload=excluded.payload
                    """,
                    (
                        run_id,
                        payload.get("engine"),
                        payload.get("symbol"),
                        payload.get("status"),
                        payload.get("export_path"),
                        json.dumps(payload.get("metrics") or {}),
                        payload.get("created_ts", time.time()),
                        payload.get("updated_ts", time.time()),
                        json.dumps(payload),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error upserting public bot backtest")

    def get_public_bot_backtests(self, run_id: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                if run_id:
                    c.execute("SELECT * FROM public_bot_backtests WHERE run_id=?", (run_id,))
                else:
                    c.execute("SELECT * FROM public_bot_backtests ORDER BY updated_ts DESC LIMIT ?", (int(limit or 100),))
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = {}
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    d.update(json.loads(d.get("payload") or "{}"))
                except Exception:
                    pass
                out[d.get("run_id")] = d
            return out
        except Exception:
            return {}

    def upsert_evidence_record(self, record: Dict[str, Any]):
        if not self.conn or not record or not record.get("evidence_id"):
            return
        try:
            metrics = record.get("metrics") or {}
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO evidence_records
                    (evidence_id, source, engine, run_id, symbol, strategy, verdict, promotion_stage,
                     trades, win_rate, net_profit_pct, max_drawdown_pct, created_ts, updated_ts,
                     gates, metrics, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(evidence_id) DO UPDATE SET
                      source=excluded.source,
                      engine=excluded.engine,
                      run_id=excluded.run_id,
                      symbol=excluded.symbol,
                      strategy=excluded.strategy,
                      verdict=excluded.verdict,
                      promotion_stage=excluded.promotion_stage,
                      trades=excluded.trades,
                      win_rate=excluded.win_rate,
                      net_profit_pct=excluded.net_profit_pct,
                      max_drawdown_pct=excluded.max_drawdown_pct,
                      updated_ts=excluded.updated_ts,
                      gates=excluded.gates,
                      metrics=excluded.metrics,
                      payload=excluded.payload
                    """,
                    (
                        record.get("evidence_id"),
                        record.get("source"),
                        record.get("engine"),
                        record.get("run_id"),
                        record.get("symbol"),
                        record.get("strategy"),
                        record.get("verdict"),
                        record.get("promotion_stage"),
                        metrics.get("trades"),
                        metrics.get("win_rate"),
                        metrics.get("net_profit_pct"),
                        metrics.get("max_drawdown_pct"),
                        record.get("created_ts", time.time()),
                        record.get("updated_ts", time.time()),
                        json.dumps(record.get("gates") or {}),
                        json.dumps(metrics),
                        json.dumps(record),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error upserting evidence record")

    def get_evidence_records(self, symbol: Optional[str] = None, run_id: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                if run_id:
                    c.execute("SELECT * FROM evidence_records WHERE run_id=? ORDER BY updated_ts DESC LIMIT ?", (run_id, int(limit or 100)))
                elif symbol:
                    c.execute("SELECT * FROM evidence_records WHERE symbol=? ORDER BY updated_ts DESC LIMIT ?", (symbol, int(limit or 100)))
                else:
                    c.execute("SELECT * FROM evidence_records ORDER BY updated_ts DESC LIMIT ?", (int(limit or 100),))
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = {}
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    payload = json.loads(d.get("payload") or "{}")
                    if isinstance(payload, dict):
                        d.update(payload)
                except Exception:
                    for key in ("gates", "metrics"):
                        try:
                            d[key] = json.loads(d.get(key) or "{}")
                        except Exception:
                            d[key] = {}
                out[d.get("evidence_id")] = d
            return out
        except Exception:
            logging.exception("Error fetching evidence records")
            return {}

    def upsert_ml_model_candidate(self, candidate: Dict[str, Any]):
        if not self.conn or not candidate or not candidate.get("candidate_id"):
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO ml_model_candidates
                    (candidate_id, family, symbol, objective, status, verdict, created_ts,
                     updated_ts, model_card_path, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(candidate_id) DO UPDATE SET
                      family=excluded.family,
                      symbol=excluded.symbol,
                      objective=excluded.objective,
                      status=excluded.status,
                      verdict=excluded.verdict,
                      updated_ts=excluded.updated_ts,
                      model_card_path=excluded.model_card_path,
                      payload=excluded.payload
                    """,
                    (
                        candidate.get("candidate_id"),
                        candidate.get("family"),
                        candidate.get("symbol"),
                        candidate.get("objective"),
                        candidate.get("status"),
                        candidate.get("verdict"),
                        candidate.get("created_ts", time.time()),
                        candidate.get("updated_ts", time.time()),
                        candidate.get("model_card_path"),
                        json.dumps(candidate),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error upserting ML model candidate")

    def get_ml_model_candidates(self, family: Optional[str] = None, symbol: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                if family:
                    c.execute("SELECT * FROM ml_model_candidates WHERE family=? ORDER BY updated_ts DESC LIMIT ?", (family, int(limit or 100)))
                elif symbol:
                    c.execute("SELECT * FROM ml_model_candidates WHERE symbol=? ORDER BY updated_ts DESC LIMIT ?", (symbol, int(limit or 100)))
                else:
                    c.execute("SELECT * FROM ml_model_candidates ORDER BY updated_ts DESC LIMIT ?", (int(limit or 100),))
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = {}
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    payload = json.loads(d.get("payload") or "{}")
                    if isinstance(payload, dict):
                        d.update(payload)
                except Exception:
                    pass
                out[d.get("candidate_id")] = d
            return out
        except Exception:
            logging.exception("Error fetching ML model candidates")
            return {}

    def upsert_execution_parity_diagnostic(self, diagnostic: Dict[str, Any]):
        if not self.conn or not diagnostic or not diagnostic.get("parity_id"):
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO execution_parity_diagnostics
                    (parity_id, source, symbol, run_id, evidence_id, verdict, created_ts,
                     updated_ts, metrics, gates, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(parity_id) DO UPDATE SET
                      source=excluded.source,
                      symbol=excluded.symbol,
                      run_id=excluded.run_id,
                      evidence_id=excluded.evidence_id,
                      verdict=excluded.verdict,
                      updated_ts=excluded.updated_ts,
                      metrics=excluded.metrics,
                      gates=excluded.gates,
                      payload=excluded.payload
                    """,
                    (
                        diagnostic.get("parity_id"),
                        diagnostic.get("source"),
                        diagnostic.get("symbol"),
                        diagnostic.get("run_id"),
                        diagnostic.get("evidence_id"),
                        diagnostic.get("verdict"),
                        diagnostic.get("created_ts", time.time()),
                        diagnostic.get("updated_ts", time.time()),
                        json.dumps(diagnostic.get("metrics") or {}),
                        json.dumps(diagnostic.get("gates") or {}),
                        json.dumps(diagnostic),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error upserting execution parity diagnostic")

    def get_execution_parity_diagnostics(self, symbol: Optional[str] = None, run_id: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                if run_id:
                    c.execute("SELECT * FROM execution_parity_diagnostics WHERE run_id=? ORDER BY updated_ts DESC LIMIT ?", (run_id, int(limit or 100)))
                elif symbol:
                    c.execute("SELECT * FROM execution_parity_diagnostics WHERE symbol=? ORDER BY updated_ts DESC LIMIT ?", (symbol, int(limit or 100)))
                else:
                    c.execute("SELECT * FROM execution_parity_diagnostics ORDER BY updated_ts DESC LIMIT ?", (int(limit or 100),))
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = {}
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    payload = json.loads(d.get("payload") or "{}")
                    if isinstance(payload, dict):
                        d.update(payload)
                except Exception:
                    for key in ("metrics", "gates"):
                        try:
                            d[key] = json.loads(d.get(key) or "{}")
                        except Exception:
                            d[key] = {}
                out[d.get("parity_id")] = d
            return out
        except Exception:
            logging.exception("Error fetching execution parity diagnostics")
            return {}

    def upsert_signal_marketplace_round(self, round_record: Dict[str, Any]):
        if not self.conn or not round_record or not round_record.get("round_id"):
            return
        try:
            summary = round_record.get("summary") or {}
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO signal_marketplace_rounds
                    (round_id, source, symbol, status, verdict, submitted, eligible,
                     total_simulated_reward, created_ts, updated_ts, gates, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(round_id) DO UPDATE SET
                      source=excluded.source,
                      symbol=excluded.symbol,
                      status=excluded.status,
                      verdict=excluded.verdict,
                      submitted=excluded.submitted,
                      eligible=excluded.eligible,
                      total_simulated_reward=excluded.total_simulated_reward,
                      updated_ts=excluded.updated_ts,
                      gates=excluded.gates,
                      payload=excluded.payload
                    """,
                    (
                        round_record.get("round_id"),
                        round_record.get("source"),
                        round_record.get("symbol"),
                        round_record.get("status"),
                        round_record.get("verdict"),
                        int(summary.get("submitted") or 0),
                        int(summary.get("eligible") or 0),
                        float(summary.get("total_simulated_reward") or 0.0),
                        round_record.get("created_ts", time.time()),
                        round_record.get("updated_ts", time.time()),
                        json.dumps(round_record.get("gates") or {}),
                        json.dumps(round_record),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error upserting signal marketplace round")

    def get_signal_marketplace_rounds(self, symbol: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute("SELECT * FROM signal_marketplace_rounds WHERE symbol=? ORDER BY updated_ts DESC LIMIT ?", (symbol, int(limit or 100)))
                else:
                    c.execute("SELECT * FROM signal_marketplace_rounds ORDER BY updated_ts DESC LIMIT ?", (int(limit or 100),))
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = {}
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    payload = json.loads(d.get("payload") or "{}")
                    if isinstance(payload, dict):
                        d.update(payload)
                except Exception:
                    try:
                        d["gates"] = json.loads(d.get("gates") or "{}")
                    except Exception:
                        d["gates"] = {}
                out[d.get("round_id")] = d
            return out
        except Exception:
            logging.exception("Error fetching signal marketplace rounds")
            return {}

    def get_execution_observations(self, symbol: Optional[str] = None, limit: int = 500) -> Dict[str, Any]:
        if not self.conn:
            return {"orders": [], "fills": [], "latencies_ms": []}
        try:
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute(
                        """
                        SELECT client_order_id, intent_id, venue, symbol, side, order_type, order_id,
                               status, placed_ts, final_ts
                        FROM orders
                        WHERE symbol=?
                        ORDER BY COALESCE(final_ts, placed_ts, 0) DESC
                        LIMIT ?
                        """,
                        (symbol, int(limit or 500)),
                    )
                else:
                    c.execute(
                        """
                        SELECT client_order_id, intent_id, venue, symbol, side, order_type, order_id,
                               status, placed_ts, final_ts
                        FROM orders
                        ORDER BY COALESCE(final_ts, placed_ts, 0) DESC
                        LIMIT ?
                        """,
                        (int(limit or 500),),
                    )
                orders = [dict(zip([d[0] for d in c.description], row)) for row in c.fetchall()]
                client_ids = [o.get("client_order_id") for o in orders if o.get("client_order_id")]
                fills = []
                if client_ids:
                    placeholders = ",".join(["?"] * len(client_ids))
                    c.execute(
                        f"""
                        SELECT order_id, client_order_id, filled_qty, avg_price, fee, slippage_pct, ts
                        FROM fills
                        WHERE client_order_id IN ({placeholders})
                        ORDER BY ts DESC
                        """,
                        tuple(client_ids),
                    )
                    fills = [dict(zip([d[0] for d in c.description], row)) for row in c.fetchall()]
            latencies = []
            for order in orders:
                placed = order.get("placed_ts")
                final = order.get("final_ts")
                try:
                    if placed is not None and final is not None:
                        latencies.append(max(0.0, (float(final) - float(placed)) * 1000.0))
                except Exception:
                    continue
            return {"orders": orders, "fills": fills, "latencies_ms": latencies}
        except Exception:
            logging.exception("Error fetching execution observations")
            return {"orders": [], "fills": [], "latencies_ms": []}

    def store_replay_result(self, payload: Dict[str, Any]):
        if not self.conn:
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO replay_results
                    (ts, symbol, days, trades, wins, losses, net_margin_pct,
                     max_drawdown_pct, clean_exits, failed_exits, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        payload.get("ts", time.time()),
                        payload.get("symbol"),
                        payload.get("days"),
                        payload.get("trades"),
                        payload.get("wins"),
                        payload.get("losses"),
                        payload.get("net_margin_pct"),
                        payload.get("max_drawdown_pct"),
                        payload.get("clean_exits"),
                        payload.get("failed_exits"),
                        json.dumps(payload),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error storing replay result")

    def upsert_pair_protection(self, symbol: str, payload: Dict[str, Any]):
        if not self.conn or not symbol:
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO pair_protections
                    (symbol, state, reason, cooldown_until, daily_loss_pct, failed_quotes,
                     route_loss_spike_pct, low_profit_until, updated_ts, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(symbol) DO UPDATE SET
                      state=excluded.state,
                      reason=excluded.reason,
                      cooldown_until=excluded.cooldown_until,
                      daily_loss_pct=excluded.daily_loss_pct,
                      failed_quotes=excluded.failed_quotes,
                      route_loss_spike_pct=excluded.route_loss_spike_pct,
                      low_profit_until=excluded.low_profit_until,
                      updated_ts=excluded.updated_ts,
                      payload=excluded.payload
                    """,
                    (
                        symbol,
                        payload.get("state"),
                        payload.get("reason"),
                        payload.get("cooldown_until"),
                        payload.get("daily_loss_pct"),
                        payload.get("failed_quotes"),
                        payload.get("route_loss_spike_pct"),
                        payload.get("low_profit_until"),
                        payload.get("updated_ts", time.time()),
                        json.dumps(payload),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error upserting pair protection")

    def get_pair_protections(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute("SELECT * FROM pair_protections WHERE symbol=?", (symbol,))
                else:
                    c.execute("SELECT * FROM pair_protections")
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = {}
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    d.update(json.loads(d.get("payload") or "{}"))
                except Exception:
                    pass
                out[d.get("symbol")] = d
            return out
        except Exception:
            return {}

    def upsert_promotion_record(self, symbol: str, payload: Dict[str, Any]):
        if not self.conn or not symbol:
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO promotion_records
                    (symbol, stage, eligible, reason, paper_trades, win_rate, net_margin_sum,
                     max_drawdown_pct, clean_exits, failed_exits, updated_ts, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(symbol) DO UPDATE SET
                      stage=excluded.stage,
                      eligible=excluded.eligible,
                      reason=excluded.reason,
                      paper_trades=excluded.paper_trades,
                      win_rate=excluded.win_rate,
                      net_margin_sum=excluded.net_margin_sum,
                      max_drawdown_pct=excluded.max_drawdown_pct,
                      clean_exits=excluded.clean_exits,
                      failed_exits=excluded.failed_exits,
                      updated_ts=excluded.updated_ts,
                      payload=excluded.payload
                    """,
                    (
                        symbol,
                        payload.get("stage"),
                        1 if payload.get("eligible") else 0,
                        payload.get("reason"),
                        payload.get("paper_trades"),
                        payload.get("win_rate"),
                        payload.get("net_margin_sum"),
                        payload.get("max_drawdown_pct"),
                        payload.get("clean_exits"),
                        payload.get("failed_exits"),
                        payload.get("updated_ts", time.time()),
                        json.dumps(payload),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error upserting promotion record")

    def get_promotion_records(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute("SELECT * FROM promotion_records WHERE symbol=?", (symbol,))
                else:
                    c.execute("SELECT * FROM promotion_records")
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = {}
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    d.update(json.loads(d.get("payload") or "{}"))
                except Exception:
                    pass
                out[d.get("symbol")] = d
            return out
        except Exception:
            return {}

    def store_paper_trade(self, payload: Dict[str, Any]):
        if not self.conn:
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO paper_trades
                    (ts, symbol, side, qty, price, notional_usd, reason, net_margin_pct, status)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        payload.get("ts", time.time()),
                        payload.get("symbol"),
                        payload.get("side"),
                        payload.get("qty"),
                        payload.get("price"),
                        payload.get("notional_usd"),
                        payload.get("reason"),
                        payload.get("net_margin_pct"),
                        payload.get("status", "PAPER"),
                    )
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error storing paper trade")

    def get_paper_stats(self, symbol: Optional[str] = None, days: int = 30) -> Dict[str, Any]:
        out = {"trades": 0, "wins": 0, "losses": 0, "net_margin_sum": 0.0, "max_drawdown_pct": 0.0}
        if not self.conn:
            return out
        try:
            cutoff = time.time() - float(days) * 86400.0
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute("SELECT * FROM paper_trades WHERE symbol=? AND ts>=? ORDER BY ts ASC", (symbol, cutoff))
                else:
                    c.execute("SELECT * FROM paper_trades WHERE ts>=? ORDER BY ts ASC", (cutoff,))
                rows = [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]
            margins = [float(r.get("net_margin_pct") or 0.0) for r in rows]
            out["trades"] = len(rows)
            out["wins"] = len([m for m in margins if m > 0])
            out["losses"] = len([m for m in margins if m <= 0])
            out["net_margin_sum"] = sum(margins)
            out["win_rate"] = (out["wins"] / len(rows)) if rows else 0.0
            running = 0.0
            peak = 0.0
            max_dd = 0.0
            for m in margins:
                running += m
                peak = max(peak, running)
                max_dd = min(max_dd, running - peak)
            out["max_drawdown_pct"] = abs(max_dd)
            return out
        except Exception:
            return out

    def get_paper_trades(self, symbol: Optional[str] = None, days: int = 30) -> list:
        if not self.conn:
            return []
        try:
            cutoff = time.time() - float(days) * 86400.0
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute("SELECT * FROM paper_trades WHERE symbol=? AND ts>=? ORDER BY ts ASC", (symbol, cutoff))
                else:
                    c.execute("SELECT * FROM paper_trades WHERE ts>=? ORDER BY ts ASC", (cutoff,))
                cols = [d[0] for d in c.description]
                return [dict(zip(cols, row)) for row in c.fetchall()]
        except Exception:
            return []

    def upsert_paper_position(self, symbol: str, payload: Dict[str, Any]):
        if not self.conn or not symbol:
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO paper_positions
                    (symbol, qty, entry_price, highest_price, opened_ts, updated_ts, status, payload)
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(symbol) DO UPDATE SET
                      qty=excluded.qty,
                      entry_price=excluded.entry_price,
                      highest_price=excluded.highest_price,
                      updated_ts=excluded.updated_ts,
                      status=excluded.status,
                      payload=excluded.payload
                    """,
                    (
                        symbol,
                        payload.get("qty"),
                        payload.get("entry_price"),
                        payload.get("highest_price"),
                        payload.get("opened_ts"),
                        payload.get("updated_ts", time.time()),
                        payload.get("status", "OPEN"),
                        json.dumps(payload),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error upserting paper position")

    def get_paper_position(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute("SELECT * FROM paper_positions WHERE symbol=?", (symbol,))
                else:
                    c.execute("SELECT * FROM paper_positions")
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = {}
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    payload = json.loads(d.get("payload") or "{}")
                    d.update(payload)
                except Exception:
                    pass
                out[d.get("symbol")] = d
            return out
        except Exception:
            return {}

    def upsert_position_memory(self, symbol: str, payload: Dict[str, Any]):
        if not self.conn or not symbol:
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO position_memory
                    (symbol, qty, entry_price, highest_price, opened_ts, updated_ts, status, payload)
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(symbol) DO UPDATE SET
                      qty=excluded.qty,
                      entry_price=excluded.entry_price,
                      highest_price=excluded.highest_price,
                      updated_ts=excluded.updated_ts,
                      status=excluded.status,
                      payload=excluded.payload
                    """,
                    (
                        symbol,
                        payload.get("qty"),
                        payload.get("entry_price"),
                        payload.get("highest_price"),
                        payload.get("opened_ts"),
                        payload.get("updated_ts", time.time()),
                        payload.get("status", "OPEN"),
                        json.dumps(payload),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error upserting position memory")

    def get_position_memory(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute("SELECT * FROM position_memory WHERE symbol=?", (symbol,))
                else:
                    c.execute("SELECT * FROM position_memory")
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = {}
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    payload = json.loads(d.get("payload") or "{}")
                    d.update(payload)
                except Exception:
                    pass
                out[d.get("symbol")] = d
            return out
        except Exception:
            return {}

    def get_market_data(self, symbol: str, limit: int = 100) -> list:
        """Retrieve market data for a symbol."""
        if not self.conn:
            return []
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("SELECT * FROM market_data WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?",
                             (symbol, limit))
                return cursor.fetchall()
        except sqlite3.DatabaseError as e:
            if self._is_corrupt_error(e):
                self._recover_db(str(e))
            return []
        except Exception as e:
            logging.error(f"Error retrieving market data: {e}")
            return []

    def store_log(self, level: str, message: str, agent: str = "unknown"):
        """Store a log entry."""
        if not self.conn:
            return
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("""
                    INSERT INTO logs (timestamp, level, message, agent)
                    VALUES (?, ?, ?, ?)
                """, (datetime.now().isoformat(), level, message, agent))
                self.conn.commit()
        except sqlite3.DatabaseError as e:
            if self._is_corrupt_error(e):
                self._recover_db(str(e))
            else:
                logging.error(f"Error storing log: {e}")
        except Exception as e:
            logging.error(f"Error storing log: {e}")

    def get_logs(self, level: Optional[str] = None, limit: int = 100) -> list:
        """Retrieve log entries."""
        if not self.conn:
            return []
        try:
            with self._lock:
                cursor = self.conn.cursor()
                if level:
                    cursor.execute("SELECT * FROM logs WHERE level = ? ORDER BY timestamp DESC LIMIT ?",
                                 (level, limit))
                else:
                    cursor.execute("SELECT * FROM logs ORDER BY timestamp DESC LIMIT ?", (limit,))
                return cursor.fetchall()
        except sqlite3.DatabaseError as e:
            if self._is_corrupt_error(e):
                self._recover_db(str(e))
            return []
        except Exception as e:
            logging.error(f"Error retrieving logs: {e}")
            return []

    def store_wallet_balance(self, address: str, asset: str, balance: float):
        """Store wallet balance snapshot."""
        if not self.conn:
            return
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("""
                    INSERT INTO wallet_balances (timestamp, address, asset, balance)
                    VALUES (?, ?, ?, ?)
                """, (datetime.now().isoformat(), address, asset, balance))
                self.conn.commit()
        except sqlite3.DatabaseError as e:
            if self._is_corrupt_error(e):
                self._recover_db(str(e))
            else:
                logging.error(f"Error storing wallet balance: {e}")
        except Exception as e:
            logging.error(f"Error storing wallet balance: {e}")

    def store_security_audit(self, payload: Dict[str, Any]):
        """Persist a security audit record into the DB."""
        if not self.conn:
            return
        try:
            with self._lock:
                cursor = self.conn.cursor()
                ts = int(time.time() * 1000)
                severity = payload.get('severity')
                etype = payload.get('type')
                details = json.dumps(payload.get('details') or {})
                rec = payload.get('recommended_action')
                cursor.execute('INSERT INTO security_audit (ts, severity, event_type, details, recommended_action) VALUES (?,?,?,?,?)', (ts, severity, etype, details, rec))
                self.conn.commit()
        except sqlite3.DatabaseError as e:
            if self._is_corrupt_error(e):
                self._recover_db(str(e))
            else:
                logging.exception('Failed to insert security audit')
        except Exception:
            logging.exception('Failed to insert security audit')

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            logging.info("Data Store Agent closed")
