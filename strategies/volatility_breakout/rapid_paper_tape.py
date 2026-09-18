from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.error
import urllib.request
from typing import Any, Mapping, Optional


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


class LocalLLMHypothesisCritic:
    """Optional local Ollama critic for paper-only forecast review.

    The critic has no execution authority. It can annotate or veto rapid paper
    tape entries when the runner explicitly enables vetoes.
    """

    def __init__(
        self,
        *,
        enabled: bool = False,
        ollama_url: str = "http://127.0.0.1:11434",
        model: str = "beast-crystal-qwen25-05b:latest",
        timeout_sec: float = 20.0,
        hard_veto: bool = False,
    ) -> None:
        self.enabled = bool(enabled)
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self.timeout_sec = max(1.0, float(timeout_sec or 20.0))
        self.hard_veto = bool(hard_veto)

    def review(self, forecast: Mapping[str, Any], *, recent_context: Mapping[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {"status": "DISABLED", "veto": False, "risks": [], "authority": "paper_annotation_only"}
        prompt = {
            "role": "paper-only market hypothesis critic",
            "rules": [
                "Use only supplied fields.",
                "Never invent prices, liquidity, news, or returns.",
                "Prefer veto when expected net is weak, cost is high, probability is weak, or reason is incoherent.",
                "Return compact JSON with keys veto, risks, confidence_adjustment_bps, note.",
            ],
            "authority": "paper_annotation_only_no_orders",
            "forecast": {
                "forecast_id": forecast.get("forecast_id"),
                "symbol": forecast.get("symbol"),
                "model_id": forecast.get("model_id"),
                "hypothesis": forecast.get("hypothesis"),
                "direction": forecast.get("direction"),
                "horizon_seconds": forecast.get("horizon_seconds"),
                "entry_price": forecast.get("entry_price"),
                "probability_positive_net": forecast.get("probability_positive_net"),
                "expected_move_bps": forecast.get("expected_move_bps"),
                "expected_cost_bps": forecast.get("expected_cost_bps"),
                "expected_net_bps": forecast.get("expected_net_bps"),
                "reason": forecast.get("reason"),
            },
            "recent_context": recent_context,
        }
        request = urllib.request.Request(
            f"{self.ollama_url}/api/generate",
            data=json.dumps({
                "model": self.model,
                "prompt": json.dumps(prompt, sort_keys=True),
                "format": "json",
                "stream": False,
                "options": {"temperature": 0, "seed": 42, "num_predict": 220},
            }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                envelope = json.loads(response.read().decode("utf-8"))
            body = json.loads(str(envelope.get("response") or "{}"))
            return {
                "status": "REVIEWED",
                "model": self.model,
                "veto": bool(body.get("veto")),
                "risks": [str(item) for item in (body.get("risks") or [])][:8],
                "confidence_adjustment_bps": _number(body.get("confidence_adjustment_bps"), 0.0),
                "note": str(body.get("note") or "")[:240],
                "hard_veto_enabled": self.hard_veto,
                "authority": "paper_annotation_only",
            }
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
            return {
                "status": "UNAVAILABLE",
                "model": self.model,
                "veto": False,
                "risks": [type(exc).__name__],
                "hard_veto_enabled": self.hard_veto,
                "authority": "paper_annotation_only",
            }


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _cfg_sequence(value: Any, default: tuple[Any, ...]) -> tuple[Any, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        items = tuple(item.strip() for item in value.split(",") if item.strip())
        return items or default
    if isinstance(value, (list, tuple, set)):
        items = tuple(item for item in value if str(item).strip())
        return items or default
    return default


class RapidPaperTape:
    """Fast paper-only tape that turns fresh forecasts into simulated trades."""

    def __init__(
        self,
        cfg: Any,
        data_store: Any,
        *,
        critic: Optional[LocalLLMHypothesisCritic] = None,
        now_fn: Any = time.time,
    ) -> None:
        self.cfg = cfg
        self.data_store = data_store
        self.conn = getattr(data_store, "conn", None)
        self._lock = getattr(data_store, "_lock", None)
        if self.conn is None:
            raise RuntimeError("Rapid paper tape requires an available data store")
        self.critic = critic or LocalLLMHypothesisCritic()
        self.now_fn = now_fn
        self.notional_usd = max(0.01, float(getattr(cfg, "phase2_rapid_paper_notional_usd", 5.0) or 5.0))
        self.max_open = max(1, int(getattr(cfg, "phase2_rapid_paper_max_open_trades", 12) or 12))
        self.max_open_per_symbol = max(0, int(getattr(cfg, "phase2_rapid_paper_max_open_per_symbol", 0) or 0))
        self.min_expected_net_bps = float(getattr(cfg, "phase2_rapid_paper_min_expected_net_bps", 0.0) or 0.0)
        self.min_probability = float(getattr(cfg, "phase2_rapid_paper_min_probability", 0.50) or 0.50)
        self.max_age_sec = max(10, int(getattr(cfg, "phase2_rapid_paper_max_forecast_age_sec", 180) or 180))
        self.max_observation_age_sec = max(
            10, int(getattr(cfg, "phase2_rapid_paper_max_observation_age_sec", 300) or 300)
        )
        min_cooldown_sec = max(1, int(getattr(cfg, "phase2_rapid_paper_min_cooldown_sec", 60) or 60))
        self.data_gap_cooldown_sec = max(
            min_cooldown_sec,
            int(getattr(cfg, "phase2_rapid_paper_data_gap_cooldown_sec", 3600) or 3600),
        )
        self.loss_cooldown_sec = max(
            min_cooldown_sec,
            int(getattr(cfg, "phase2_rapid_paper_loss_cooldown_sec", 3600) or 3600),
        )
        self.negative_memory_max_hits = max(
            1, int(getattr(cfg, "phase2_rapid_paper_negative_memory_max_hits", 2) or 2)
        )
        self.model_direction_gate_min_samples = max(
            1, int(getattr(cfg, "phase2_rapid_paper_model_direction_gate_min_samples", 5) or 5)
        )
        self.model_direction_min_win_rate = max(
            0.0, float(getattr(cfg, "phase2_rapid_paper_model_direction_min_win_rate", 0.35) or 0.35)
        )
        self.model_direction_min_mean_net_bps = float(
            getattr(cfg, "phase2_rapid_paper_model_direction_min_mean_net_bps", 0.0) or 0.0
        )
        self.champion_scout_enabled = bool(getattr(cfg, "phase2_rapid_paper_champion_scout_enabled", False))
        self.champion_scout_min_samples = max(
            1, int(getattr(cfg, "phase2_rapid_paper_champion_scout_min_samples", 3) or 3)
        )
        self.champion_scout_min_win_rate = max(
            0.0, float(getattr(cfg, "phase2_rapid_paper_champion_scout_min_win_rate", 0.50) or 0.50)
        )
        self.champion_scout_min_mean_net_bps = float(
            getattr(cfg, "phase2_rapid_paper_champion_scout_min_mean_net_bps", 5.0) or 5.0
        )
        self.champion_scout_min_total_net_bps = float(
            getattr(cfg, "phase2_rapid_paper_champion_scout_min_total_net_bps", 1.0) or 1.0
        )
        self.champion_scout_fetch_multiplier = max(
            1, int(getattr(cfg, "phase2_rapid_paper_champion_scout_fetch_multiplier", 8) or 8)
        )
        self.champion_scout_history_limit = max(
            100, int(getattr(cfg, "phase2_rapid_paper_champion_scout_history_limit", 10000) or 10000)
        )
        self._champion_slice_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
        configured_directions = getattr(cfg, "phase2_rapid_paper_allowed_directions", ["UP"]) or ["UP"]
        self.allowed_directions = tuple(
            str(item).strip().upper()
            for item in configured_directions
            if str(item).strip()
        ) or ("UP",)
        configured_small_window_directions = getattr(
            cfg, "phase2_small_window_allowed_directions", ("UP", "DOWN")
        ) or ("UP", "DOWN")
        self.small_window_allowed_directions = tuple(
            str(item).strip().upper()
            for item in configured_small_window_directions
            if str(item).strip()
        ) or ("UP", "DOWN")
        excluded_bases = _cfg_sequence(
            getattr(cfg, "phase2_small_window_excluded_bases", None),
            (
                "BTC", "ETH", "SOL", "XRP", "ADA", "BNB", "DOGE", "AVAX",
                "USD", "USDT", "USDC", "EUR", "GBP", "AUD", "CAD", "JPY",
            ),
        )
        self.small_window_excluded_bases = {
            str(item).strip().upper() for item in excluded_bases if str(item).strip()
        }
        configured_windows = _cfg_sequence(
            getattr(cfg, "phase2_small_window_trend_windows_sec", None),
            (int(getattr(cfg, "phase2_small_window_trend_window_sec", 900) or 900),),
        )
        windows = []
        for item in configured_windows:
            try:
                window = int(float(item))
                if window > 0:
                    windows.append(window)
            except (TypeError, ValueError):
                continue
        self.small_window_trend_windows_sec = tuple(sorted(set(windows))) or (900,)
        self.small_window_preserve_window_coverage = bool(
            getattr(cfg, "phase2_small_window_preserve_window_coverage", False)
        )
        self.small_window_hypothesis = str(
            getattr(cfg, "phase2_small_window_trend_hypothesis", "recent_delta_volatility")
            or "recent_delta_volatility"
        )
        self.small_window_signal_lanes = {
            str(item).strip().lower()
            for item in _cfg_sequence(
                getattr(cfg, "phase2_small_window_signal_lanes", None),
                ("continuation",),
            )
            if str(item).strip()
        } or {"continuation"}
        self.small_window_reversion_capture_ratio = max(
            0.01, float(getattr(cfg, "phase2_small_window_reversion_capture_ratio", 0.35) or 0.35)
        )
        self.small_window_reversion_max_capture_bps = max(
            1.0, float(getattr(cfg, "phase2_small_window_reversion_max_capture_bps", 80.0) or 80.0)
        )
        self.small_window_health_min_score = max(
            0.0, float(getattr(cfg, "phase2_small_window_healthy_min_score", 0.0) or 0.0)
        )
        self.small_window_health_min_cost_multiple = max(
            0.0, float(getattr(cfg, "phase2_small_window_health_min_cost_multiple", 1.20) or 1.20)
        )
        self.small_window_canary_memory_enabled = bool(
            getattr(cfg, "phase2_small_window_canary_memory_enabled", True)
        )
        self.small_window_canary_memory_limit = max(
            1, int(getattr(cfg, "phase2_small_window_canary_memory_limit", 20) or 20)
        )
        self.small_window_execution_policy_enabled = bool(
            getattr(cfg, "phase2_small_window_execution_policy_enabled", True)
        )
        self.small_window_execution_policies = tuple(
            str(item).strip().lower()
            for item in _cfg_sequence(
                getattr(cfg, "phase2_small_window_execution_policies", None),
                ("maker_probe", "taker_market", "dex_swap"),
            )
            if str(item).strip()
        ) or ("maker_probe", "taker_market")
        self.small_window_maker_fee_bps_per_side = max(
            0.0,
            float(
                getattr(
                    cfg,
                    "phase2_small_window_maker_fee_bps_per_side",
                    getattr(cfg, "phase3_maker_fee_bps", 10.0),
                )
                or 0.0
            ),
        )
        self.small_window_taker_fee_bps_per_side = max(
            0.0, float(getattr(cfg, "phase2_taker_fee_bps_per_side", 10.0) or 10.0)
        )
        self.small_window_safety_buffer_bps = max(
            0.0, float(getattr(cfg, "phase2_safety_buffer_bps", 5.0) or 5.0)
        )
        self.small_window_max_impact_bps = max(
            0.0, float(getattr(cfg, "phase2_small_window_max_impact_bps", 50.0) or 50.0)
        )
        self.small_window_dex_mev_buffer_bps = max(
            0.0, float(getattr(cfg, "phase2_small_window_dex_mev_buffer_bps", 12.0) or 12.0)
        )
        self.small_window_route_min_expected_fill_ratio = max(
            0.0,
            min(
                1.0,
                float(getattr(cfg, "phase2_small_window_route_min_expected_fill_ratio", 0.35) or 0.35),
            ),
        )
        self._canary_memory_cache: dict[tuple[str, str, int], dict[str, Any]] = {}
        self._create_tables()

    def _create_tables(self) -> None:
        lock = self._lock
        if lock:
            lock.acquire()
        try:
            self.conn.execute("""
            CREATE TABLE IF NOT EXISTS rapid_paper_tape_trades (
                trade_id TEXT PRIMARY KEY,
                source_forecast_id TEXT UNIQUE,
                run_id TEXT,
                venue TEXT,
                symbol TEXT,
                model_id TEXT,
                hypothesis TEXT,
                direction TEXT,
                status TEXT,
                entry_ts REAL,
                target_ts REAL,
                settled_ts REAL,
                updated_ts REAL,
                entry_price REAL,
                exit_price REAL,
                notional_usd REAL,
                expected_net_bps REAL,
                expected_cost_bps REAL,
                probability_positive_net REAL,
                gross_return_bps REAL,
                directional_return_bps REAL,
                net_return_bps REAL,
                positive_net INTEGER,
                llm_status TEXT,
                llm_veto INTEGER,
                llm_risks TEXT,
                failure_reason TEXT,
                payload TEXT
            )
            """)
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rapid_paper_status_updated "
                "ON rapid_paper_tape_trades(status, updated_ts)"
            )
            self.conn.commit()
        finally:
            if lock:
                lock.release()

    def _fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        c = self.conn.cursor()
        c.execute(query, params)
        cols = [item[0] for item in c.description]
        rows = []
        for row in c.fetchall():
            record = dict(zip(cols, row))
            try:
                payload = json.loads(record.get("payload") or "{}")
                if isinstance(payload, dict):
                    record.update({key: value for key, value in payload.items() if key not in record or record[key] is None})
            except Exception:
                pass
            rows.append(record)
        return rows

    @staticmethod
    def _payload_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if not value:
            return {}
        try:
            parsed = json.loads(str(value))
            return dict(parsed) if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def active_count(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM rapid_paper_tape_trades WHERE status='OPEN'"
        ).fetchone()
        return int((row or [0])[0] or 0)

    def _open_symbol_count(self, symbol: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM rapid_paper_tape_trades WHERE status='OPEN' AND symbol=?",
            (str(symbol or ""),),
        ).fetchone()
        return int((row or [0])[0] or 0)

    def _symbol_open_cap_reached(self, symbol: str) -> bool:
        return self.max_open_per_symbol > 0 and self._open_symbol_count(symbol) >= self.max_open_per_symbol

    def _recent_context(self, forecast: Mapping[str, Any]) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT price, spread_bps, depth_usd_25bps, quote_volume_24h, data_quality, ts
            FROM observation_snapshots
            WHERE symbol=? AND ts<=?
            ORDER BY ts DESC LIMIT 1
            """,
            (forecast.get("symbol"), _number(forecast.get("ts"), self.now_fn())),
        ).fetchone()
        if not row:
            return {}
        return {
            "price": row[0],
            "spread_bps": row[1],
            "depth_usd_25bps": row[2],
            "quote_volume_24h": row[3],
            "data_quality": row[4],
            "observation_ts": row[5],
        }

    def _recent_data_gap_expiry(self, symbol: str, now: float) -> bool:
        row = self.conn.execute(
            """
            SELECT COUNT(*) FROM rapid_paper_tape_trades
            WHERE symbol=? AND status='EXPIRED_NO_OBSERVATION' AND updated_ts>=?
            """,
            (str(symbol or ""), float(now) - float(self.data_gap_cooldown_sec)),
        ).fetchone()
        return int((row or [0])[0] or 0) > 0

    def _negative_scope_key(self, forecast: Mapping[str, Any]) -> str:
        model_id = str(forecast.get("model_id") or "unknown")
        hypothesis = str(forecast.get("hypothesis") or "unknown")
        direction = str(forecast.get("direction") or "unknown").upper()
        regime_hint = str(forecast.get("regime_hint") or "rapid_paper_unknown_regime")
        symbol = str(forecast.get("symbol") or "unknown")
        return f"{model_id}|{hypothesis}|{direction}|{regime_hint}|{symbol}"

    def _negative_memory_refusal(self, forecast: Mapping[str, Any]) -> bool:
        row = self.conn.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(evidence_strength), 0)
            FROM crystal_registry
            WHERE crystal_family='negative_capability'
              AND phase_scope=2
              AND drift_status='active_refusal_memory'
              AND scope_key=?
            """,
            (self._negative_scope_key(forecast),),
        ).fetchone()
        hits = int((row or [0])[0] or 0)
        return hits >= self.negative_memory_max_hits

    def _model_direction_probation_refusal(self, forecast: Mapping[str, Any]) -> bool:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS trades,
                   SUM(CASE WHEN net_return_bps>0 THEN 1 ELSE 0 END) AS wins,
                   COALESCE(AVG(net_return_bps), 0) AS mean_net_bps
            FROM rapid_paper_tape_trades
            WHERE status IN ('CLOSED_WIN','CLOSED_LOSS')
              AND model_id=?
              AND direction=?
            """,
            (
                str(forecast.get("model_id") or ""),
                str(forecast.get("direction") or "").upper(),
            ),
        ).fetchone()
        trades = int((row or [0])[0] or 0)
        if trades < self.model_direction_gate_min_samples:
            return False
        wins = int((row or [0, 0])[1] or 0)
        mean_net_bps = float((row or [0, 0, 0.0])[2] or 0.0)
        win_rate = wins / trades if trades else 0.0
        return win_rate < self.model_direction_min_win_rate or mean_net_bps < self.model_direction_min_mean_net_bps

    def _champion_slice_stats(self, forecast: Mapping[str, Any], now: float) -> dict[str, Any]:
        cache_key = (
            str(forecast.get("model_id") or ""),
            str(forecast.get("hypothesis") or ""),
            int(_number(forecast.get("horizon_seconds"))),
            str(forecast.get("direction") or "").upper(),
            str(forecast.get("symbol") or ""),
        )
        cached = self._champion_slice_cache.get(cache_key)
        if cached is not None:
            return dict(cached)
        params = (
            str(forecast.get("model_id") or ""),
            str(forecast.get("hypothesis") or ""),
            int(_number(forecast.get("horizon_seconds"))),
            str(forecast.get("direction") or "").upper(),
            str(forecast.get("forecast_id") or ""),
            int(self.champion_scout_history_limit),
        )
        family = self.conn.execute(
            """
            WITH slice_forecasts AS (
                SELECT forecast_id
                FROM hypothesis_forecasts
                WHERE model_id=?
                  AND hypothesis=?
                  AND horizon_seconds=?
                  AND UPPER(direction)=?
                  AND forecast_id<>?
                  AND ts<?
                ORDER BY ts DESC
                LIMIT ?
            )
            SELECT COUNT(*) AS samples,
                   SUM(CASE WHEN o.net_return_bps>0 THEN 1 ELSE 0 END) AS wins,
                   COALESCE(AVG(o.net_return_bps), 0) AS mean_net_bps,
                   COALESCE(SUM(o.net_return_bps), 0) AS total_net_bps
            FROM slice_forecasts h
            JOIN hypothesis_outcomes o ON o.forecast_id=h.forecast_id
            WHERE o.settled_ts<?
            """,
            (params[0], params[1], params[2], params[3], params[4], float(now), params[5], float(now)),
        ).fetchone()
        symbol_params = params[:4] + (str(forecast.get("symbol") or ""),) + params[4:]
        symbol = self.conn.execute(
            """
            WITH slice_forecasts AS (
                SELECT forecast_id
                FROM hypothesis_forecasts
                WHERE model_id=?
                  AND hypothesis=?
                  AND horizon_seconds=?
                  AND UPPER(direction)=?
                  AND symbol=?
                  AND forecast_id<>?
                  AND ts<?
                ORDER BY ts DESC
                LIMIT ?
            )
            SELECT COUNT(*) AS samples,
                   SUM(CASE WHEN o.net_return_bps>0 THEN 1 ELSE 0 END) AS wins,
                   COALESCE(AVG(o.net_return_bps), 0) AS mean_net_bps,
                   COALESCE(SUM(o.net_return_bps), 0) AS total_net_bps
            FROM slice_forecasts h
            JOIN hypothesis_outcomes o ON o.forecast_id=h.forecast_id
            WHERE o.settled_ts<?
            """,
            (
                symbol_params[0],
                symbol_params[1],
                symbol_params[2],
                symbol_params[3],
                symbol_params[4],
                symbol_params[5],
                float(now),
                symbol_params[6],
                float(now),
            ),
        ).fetchone()

        def pack(row: Any) -> dict[str, Any]:
            samples = int((row or [0])[0] or 0)
            wins = int((row or [0, 0])[1] or 0)
            mean_net = float((row or [0, 0, 0.0])[2] or 0.0)
            total_net = float((row or [0, 0, 0.0, 0.0])[3] or 0.0)
            return {
                "samples": samples,
                "wins": wins,
                "win_rate": (wins / samples) if samples else 0.0,
                "mean_net_bps": mean_net,
                "total_net_bps": total_net,
            }

        family_stats = pack(family)
        symbol_stats = pack(symbol)
        accepted = (
            family_stats["samples"] >= self.champion_scout_min_samples
            and family_stats["win_rate"] >= self.champion_scout_min_win_rate
            and family_stats["mean_net_bps"] >= self.champion_scout_min_mean_net_bps
            and family_stats["total_net_bps"] >= self.champion_scout_min_total_net_bps
        )
        score = 0.0
        if accepted:
            score = (
                family_stats["mean_net_bps"] * (0.5 + family_stats["win_rate"])
                + min(family_stats["samples"], 50) * 0.20
            )
            if symbol_stats["samples"] >= 2:
                score += symbol_stats["mean_net_bps"] * 0.25
                if symbol_stats["mean_net_bps"] < 0:
                    score -= abs(symbol_stats["mean_net_bps"]) * 0.50
        reasons = []
        if family_stats["samples"] < self.champion_scout_min_samples:
            reasons.append("insufficient_settled_slice_samples")
        if family_stats["win_rate"] < self.champion_scout_min_win_rate:
            reasons.append("slice_win_rate_below_floor")
        if family_stats["mean_net_bps"] < self.champion_scout_min_mean_net_bps:
            reasons.append("slice_mean_net_below_floor")
        if family_stats["total_net_bps"] < self.champion_scout_min_total_net_bps:
            reasons.append("slice_total_net_below_floor")
        receipt = {
            "schema": "rapid_champion_scout_receipt_v1",
            "authority": "paper_admission_only",
            "accepted": accepted,
            "score": score,
            "family": family_stats,
            "symbol": symbol_stats,
            "min_samples": self.champion_scout_min_samples,
            "min_win_rate": self.champion_scout_min_win_rate,
            "min_mean_net_bps": self.champion_scout_min_mean_net_bps,
            "min_total_net_bps": self.champion_scout_min_total_net_bps,
            "reasons": reasons,
        }
        self._champion_slice_cache[cache_key] = dict(receipt)
        return receipt

    def _has_duplicate_open_exposure(self, forecast: Mapping[str, Any]) -> bool:
        """Prevent stacking the same paper thesis while the first one is unresolved."""
        row = self.conn.execute(
            """
            SELECT COUNT(*) FROM rapid_paper_tape_trades
            WHERE status='OPEN'
              AND symbol=?
              AND model_id=?
              AND direction=?
            """,
            (
                str(forecast.get("symbol") or ""),
                str(forecast.get("model_id") or ""),
                str(forecast.get("direction") or "").upper(),
            ),
        ).fetchone()
        return int((row or [0])[0] or 0) > 0

    def _recent_loss_cooldown(self, forecast: Mapping[str, Any], now: float) -> bool:
        """Treat a fresh loss as refusal memory for the same symbol/model/direction."""
        row = self.conn.execute(
            """
            SELECT COUNT(*) FROM rapid_paper_tape_trades
            WHERE status='CLOSED_LOSS'
              AND symbol=?
              AND model_id=?
              AND direction=?
              AND updated_ts>=?
            """,
            (
                str(forecast.get("symbol") or ""),
                str(forecast.get("model_id") or ""),
                str(forecast.get("direction") or "").upper(),
                float(now) - float(self.loss_cooldown_sec),
            ),
        ).fetchone()
        return int((row or [0])[0] or 0) > 0

    def _insert_open_trade(
        self,
        *,
        source_id: str,
        run_id: str,
        venue: str,
        symbol: str,
        model_id: str,
        hypothesis: str,
        direction: str,
        entry_ts: float,
        target_ts: float,
        entry_price: float,
        expected_net_bps: float,
        expected_cost_bps: float,
        probability_positive_net: float,
        payload: Mapping[str, Any],
        review: Mapping[str, Any] | None = None,
        status: str = "OPEN",
        failure_reason: str | None = None,
    ) -> bool:
        trade_id = canonical_hash({
            "rapid_paper_tape": "v1",
            "source_id": source_id,
            "run_id": run_id,
        })
        review = dict(review or {"status": "DISABLED", "veto": False, "risks": []})
        with self._lock:
            cursor = self.conn.execute(
                """
                INSERT OR IGNORE INTO rapid_paper_tape_trades
                (trade_id,source_forecast_id,run_id,venue,symbol,model_id,hypothesis,direction,status,
                 entry_ts,target_ts,updated_ts,entry_price,notional_usd,expected_net_bps,
                 expected_cost_bps,probability_positive_net,llm_status,llm_veto,llm_risks,
                 failure_reason,payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    trade_id,
                    source_id,
                    run_id,
                    venue,
                    symbol,
                    model_id,
                    hypothesis,
                    direction,
                    status,
                    entry_ts,
                    target_ts,
                    float(self.now_fn()),
                    entry_price,
                    self.notional_usd,
                    expected_net_bps,
                    expected_cost_bps,
                    probability_positive_net,
                    review.get("status"),
                    int(bool(review.get("veto"))),
                    json.dumps(review.get("risks") or []),
                    failure_reason,
                    json.dumps(dict(payload), sort_keys=True, default=str),
                ),
            )
            self.conn.commit()
        return bool(cursor.rowcount)

    def _trend_comparison_candidates(
        self,
        *,
        window_sec: int,
        max_age_sec: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        now = float(self.now_fn())
        db_clock_row = self.conn.execute("SELECT MAX(ts) FROM observation_snapshots").fetchone()
        db_clock = float((db_clock_row or [0.0])[0] or now)
        lookback_sec = max(int(window_sec) * 3, int(max_age_sec) + int(window_sec) + 60)
        rows = self._fetchall(
            """
            SELECT ts, venue, symbol, price, quote_volume_24h, spread_bps, depth_usd_25bps,
                   volatility_expansion, volume_zscore, book_imbalance, data_quality, payload
            FROM observation_snapshots
            WHERE ts>=?
              AND price IS NOT NULL
              AND price>0
            ORDER BY symbol ASC, ts ASC
            """,
            (db_clock - float(lookback_sec),),
        )
        by_symbol: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            symbol = str(row.get("symbol") or "")
            base = symbol.split("/", 1)[0].upper()
            if not symbol or base in self.small_window_excluded_bases:
                continue
            by_symbol.setdefault(symbol, []).append(row)

        min_quality = float(getattr(self.cfg, "phase2_min_data_quality", 0.5) or 0.5)
        max_spread = float(getattr(self.cfg, "phase3_max_entry_spread_bps", 200.0) or 200.0)
        fee_bps = self.small_window_taker_fee_bps_per_side * 2.0
        latency_buffer = float(getattr(self.cfg, "phase2_latency_buffer_bps", 0.0) or 0.0)
        min_move_bps = float(getattr(self.cfg, "phase2_small_window_trend_min_abs_move_bps", 25.0) or 25.0)
        min_net_bps = float(getattr(self.cfg, "phase2_small_window_trend_min_net_bps", 5.0) or 5.0)
        candidates: list[dict[str, Any]] = []
        for symbol, symbol_rows in by_symbol.items():
            if len(symbol_rows) < 2:
                continue
            latest = symbol_rows[-1]
            latest_ts = _number(latest.get("ts"))
            if latest_ts <= 0 or latest_ts < db_clock - float(max_age_sec):
                continue
            if _number(latest.get("data_quality")) < min_quality:
                continue
            spread_bps = _number(latest.get("spread_bps"))
            if spread_bps > max_spread:
                continue
            anchor = None
            target_anchor_ts = latest_ts - float(window_sec)
            for item in reversed(symbol_rows[:-1]):
                if _number(item.get("ts")) <= target_anchor_ts:
                    anchor = item
                    break
            if anchor is None:
                anchor = symbol_rows[0]
            anchor_price = _number(anchor.get("price"))
            latest_price = _number(latest.get("price"))
            if anchor_price <= 0 or latest_price <= 0:
                continue
            elapsed = max(1.0, latest_ts - _number(anchor.get("ts")))
            return_bps = ((latest_price - anchor_price) / anchor_price) * 10_000.0
            abs_move_bps = abs(return_bps)
            cost_bps = max(0.0, spread_bps + fee_bps + latency_buffer)
            net_bps = abs_move_bps - cost_bps
            if abs_move_bps < min_move_bps or net_bps < min_net_bps:
                continue
            vol_expansion = _number(latest.get("volatility_expansion"))
            volume_zscore = _number(latest.get("volume_zscore"))
            book_imbalance = _number(latest.get("book_imbalance"))
            velocity_bps_per_min = abs_move_bps / max(elapsed / 60.0, 1e-9)
            volatility_weight = float(getattr(self.cfg, "phase2_small_window_volatility_score_weight", 1.0) or 1.0)
            velocity_weight = float(getattr(self.cfg, "phase2_small_window_velocity_score_weight", 0.5) or 0.5)
            liquidity_penalty = max(0.0, spread_bps - 40.0) * 0.2
            lanes: list[dict[str, Any]] = []
            if "continuation" in self.small_window_signal_lanes:
                lanes.append({
                    "signal_lane": "continuation",
                    "direction": "UP" if return_bps > 0 else "DOWN",
                    "expected_move_bps": abs_move_bps,
                    "lane_score_bias": 0.0,
                })
            if "micro_reversion" in self.small_window_signal_lanes:
                capture_bps = min(
                    abs_move_bps * self.small_window_reversion_capture_ratio,
                    self.small_window_reversion_max_capture_bps,
                )
                reversion_net_bps = capture_bps - cost_bps
                lanes.append({
                    "signal_lane": "micro_reversion",
                    "direction": "DOWN" if return_bps > 0 else "UP",
                    "expected_move_bps": capture_bps,
                    "lane_score_bias": 8.0,
                })
            for lane in lanes:
                direction = str(lane["direction"])
                if direction not in self.small_window_allowed_directions:
                    continue
                expected_move = _number(lane.get("expected_move_bps"))
                route_decision = self._execution_route_decision(
                    venue=str(latest.get("venue") or "kraken"),
                    direction=direction,
                    expected_move_bps=expected_move,
                    spread_bps=spread_bps,
                    depth_usd_25bps=_number(latest.get("depth_usd_25bps")),
                    quote_volume_24h=_number(latest.get("quote_volume_24h")),
                    volume_zscore=volume_zscore,
                    volatility_expansion=vol_expansion,
                    velocity_bps_per_min=velocity_bps_per_min,
                    book_imbalance=book_imbalance,
                    observation=latest,
                )
                route_cost_bps = _number(route_decision.get("total_cost_bps"), cost_bps)
                lane_net_bps = expected_move - route_cost_bps
                if lane_net_bps < min_net_bps:
                    continue
                fill_adjusted_net = _number(route_decision.get("expected_net_after_fill_bps"), lane_net_bps)
                score = (
                    fill_adjusted_net
                    + expected_move * volatility_weight
                    + min(velocity_bps_per_min, 250.0) * velocity_weight
                    + min(vol_expansion, 5.0) * 8.0
                    + max(volume_zscore, 0.0) * 4.0
                    + _number(lane.get("lane_score_bias"))
                    - liquidity_penalty
                )
                source_id = "trend:" + canonical_hash({
                    "model": "small_window_trend_comparison_v1",
                    "signal_lane": lane.get("signal_lane"),
                    "symbol": symbol,
                    "direction": direction,
                    "latest_ts": round(latest_ts, 3),
                    "anchor_ts": round(_number(anchor.get("ts")), 3),
                    "window_sec": int(window_sec),
                })
                candidates.append({
                    "source_id": source_id,
                    "run_id": f"trend-{int(latest_ts)}",
                    "venue": latest.get("venue") or "kraken",
                    "symbol": symbol,
                    "model_id": "small_window_trend_comparison_v1",
                    "hypothesis": self.small_window_hypothesis,
                    "signal_lane": lane.get("signal_lane"),
                    "direction": direction,
                    "entry_ts": latest_ts,
                    "entry_price": latest_price,
                    "anchor_ts": _number(anchor.get("ts")),
                    "anchor_price": anchor_price,
                    "window_sec": int(window_sec),
                    "elapsed_sec": elapsed,
                    "comparison_return_bps": return_bps,
                    "absolute_move_bps": abs_move_bps,
                    "expected_move_bps": expected_move,
                    "expected_cost_bps": route_cost_bps,
                    "expected_net_bps": lane_net_bps,
                    "expected_fill_adjusted_net_bps": fill_adjusted_net,
                    "probability_positive_net": min(0.74, 0.48 + min(max(fill_adjusted_net, 0.0), 240.0) / 1000.0),
                    "spread_bps": spread_bps,
                    "quote_volume_24h": latest.get("quote_volume_24h"),
                    "depth_usd_25bps": latest.get("depth_usd_25bps"),
                    "volatility_expansion": vol_expansion,
                    "volume_zscore": volume_zscore,
                    "book_imbalance": book_imbalance,
                    "score": score,
                    "execution_route": route_decision,
                    "route_policy": route_decision.get("selected_policy"),
                    "route_kind": route_decision.get("selected_route_kind"),
                    "expected_fill_ratio": route_decision.get("expected_fill_ratio"),
                    "microstructure": route_decision.get("microstructure"),
                    "window_label": {
                        60: "1m",
                        300: "5m",
                        1800: "30m",
                        3600: "1h",
                    }.get(int(window_sec), f"{int(window_sec)}s"),
                    "latest_observation": latest,
                    "anchor_observation": anchor,
                })
        candidates.sort(key=lambda item: (_number(item.get("score")), _number(item.get("expected_net_bps"))), reverse=True)
        return candidates[: max(1, int(limit or 1))]

    @staticmethod
    def _truthy(value: Any) -> Optional[bool]:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "allow", "allowed", "pass"}:
            return True
        if text in {"0", "false", "no", "deny", "denied", "fail", "blocked"}:
            return False
        return None

    @staticmethod
    def _nested_mapping(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, Mapping) else {}

    def _route_context(self, observation: Mapping[str, Any]) -> dict[str, Any]:
        exec_quality = self._nested_mapping(observation.get("exec_quality"))
        dex_quality = self._nested_mapping(observation.get("dex_quality"))
        route = self._nested_mapping(observation.get("dex_route") or observation.get("route"))
        allowed = self._truthy(
            observation.get("dex_exit_allowed")
            if observation.get("dex_exit_allowed") is not None
            else observation.get("dex_allowed")
        )
        roundtrip_ratio = (
            observation.get("roundtrip_ratio")
            or observation.get("dex_roundtrip_ratio")
            or observation.get("quote_output_ratio")
            or exec_quality.get("quote_output_ratio")
            or dex_quality.get("roundtrip_ratio")
            or route.get("roundtrip_ratio")
        )
        price_impact_pct = (
            observation.get("price_impact_pct")
            or observation.get("dex_price_impact_pct")
            or exec_quality.get("price_impact_pct")
            or dex_quality.get("price_impact_pct")
        )
        gas_drag_pct = (
            observation.get("gas_drag_pct")
            or observation.get("dex_gas_drag_pct")
            or exec_quality.get("gas_drag_pct")
            or dex_quality.get("gas_drag_pct")
        )
        known = any(
            item is not None
            for item in (
                allowed,
                roundtrip_ratio,
                price_impact_pct,
                gas_drag_pct,
                observation.get("dex_reason"),
                route.get("_provider"),
            )
        )
        return {
            "known": bool(known),
            "allowed": allowed,
            "reason": observation.get("dex_reason") or observation.get("dex_route_reason"),
            "provider": route.get("_provider") or observation.get("dex_provider"),
            "roundtrip_ratio": None if roundtrip_ratio is None else _number(roundtrip_ratio),
            "price_impact_pct": None if price_impact_pct is None else _number(price_impact_pct),
            "gas_drag_pct": None if gas_drag_pct is None else _number(gas_drag_pct),
        }

    def _microstructure_profile(
        self,
        *,
        spread_bps: float,
        depth_usd_25bps: float,
        quote_volume_24h: float,
        volume_zscore: float,
        volatility_expansion: float,
        velocity_bps_per_min: float,
        book_imbalance: float,
    ) -> dict[str, Any]:
        notional = max(0.01, float(self.notional_usd))
        depth = max(0.0, float(depth_usd_25bps or 0.0))
        participation = notional / max(depth, notional)
        hostile = []
        if spread_bps >= 80.0:
            hostile.append("wide_spread")
        if depth > 0.0 and depth < notional * 50.0:
            hostile.append("thin_depth")
        if velocity_bps_per_min >= 180.0:
            hostile.append("fast_tape")
        if abs(book_imbalance) >= 0.55:
            hostile.append("one_sided_book")
        quality = 100.0
        quality -= min(35.0, max(0.0, spread_bps - 20.0) * 0.35)
        quality -= min(25.0, participation * 150.0)
        quality -= min(18.0, max(0.0, velocity_bps_per_min - 90.0) * 0.06)
        quality += min(8.0, max(0.0, volume_zscore) * 2.0)
        quality += min(8.0, max(0.0, volatility_expansion - 1.0) * 2.5)
        return {
            "schema": "small_window_microstructure_profile_v1",
            "spread_bps": round(float(spread_bps), 6),
            "depth_usd_25bps": round(depth, 6),
            "quote_volume_24h": quote_volume_24h,
            "participation_ratio": round(participation, 8),
            "velocity_bps_per_min": round(float(velocity_bps_per_min), 6),
            "volume_zscore": round(float(volume_zscore), 6),
            "volatility_expansion": round(float(volatility_expansion), 6),
            "book_imbalance": round(float(book_imbalance), 6),
            "quality_score": round(max(0.0, min(100.0, quality)), 6),
            "hostile_flags": hostile,
        }

    def _execution_route_decision(
        self,
        *,
        venue: str,
        direction: str,
        expected_move_bps: float,
        spread_bps: float,
        depth_usd_25bps: float,
        quote_volume_24h: float,
        volume_zscore: float,
        volatility_expansion: float,
        velocity_bps_per_min: float,
        book_imbalance: float,
        observation: Mapping[str, Any],
    ) -> dict[str, Any]:
        latency = max(0.0, float(getattr(self.cfg, "phase2_latency_buffer_bps", 0.0) or 0.0))
        safety = float(self.small_window_safety_buffer_bps)
        notional = max(0.01, float(self.notional_usd))
        depth = max(0.0, float(depth_usd_25bps or 0.0))
        participation = notional / max(depth, notional)
        impact = min(self.small_window_max_impact_bps, 25.0 * (participation ** 0.5))
        microstructure = self._microstructure_profile(
            spread_bps=spread_bps,
            depth_usd_25bps=depth_usd_25bps,
            quote_volume_24h=quote_volume_24h,
            volume_zscore=volume_zscore,
            volatility_expansion=volatility_expansion,
            velocity_bps_per_min=velocity_bps_per_min,
            book_imbalance=book_imbalance,
        )

        if not self.small_window_execution_policy_enabled:
            total = (
                self.small_window_taker_fee_bps_per_side * 2.0
                + max(0.0, spread_bps)
                + impact
                + latency
                + safety
            )
            return {
                "schema": "small_window_execution_route_decision_v1",
                "selected_policy": "taker_market",
                "total_cost_bps": round(total, 6),
                "expected_fill_ratio": 1.0,
                "expected_net_after_fill_bps": round(float(expected_move_bps) - total, 6),
                "route_options": [],
                "microstructure": microstructure,
                "authority": "paper_execution_model_only",
            }

        policies = set(self.small_window_execution_policies)
        options: list[dict[str, Any]] = []

        def add_option(
            *,
            policy: str,
            total_cost_bps: float,
            expected_fill_ratio: float,
            reason: str,
            tradable: bool = True,
            route_kind: str = "cex",
            extra: Mapping[str, Any] | None = None,
        ) -> None:
            fill = max(0.0, min(1.0, float(expected_fill_ratio)))
            total_cost = max(0.0, float(total_cost_bps))
            missed_fill_drag = max(0.0, float(expected_move_bps)) * (1.0 - fill)
            expected_net = (float(expected_move_bps) * fill) - total_cost
            options.append({
                "policy": policy,
                "route_kind": route_kind,
                "tradable": bool(tradable) and fill >= self.small_window_route_min_expected_fill_ratio,
                "reason": reason,
                "fee_bps": (extra or {}).get("fee_bps"),
                "spread_bps": (extra or {}).get("spread_bps"),
                "impact_bps": (extra or {}).get("impact_bps"),
                "latency_bps": (extra or {}).get("latency_bps"),
                "safety_bps": (extra or {}).get("safety_bps"),
                "expected_fill_ratio": round(fill, 6),
                "missed_fill_drag_bps": round(missed_fill_drag, 6),
                "total_cost_bps": round(total_cost, 6),
                "expected_net_after_fill_bps": round(expected_net, 6),
                **dict(extra or {}),
            })

        if "taker_market" in policies:
            taker_cost = (
                self.small_window_taker_fee_bps_per_side * 2.0
                + max(0.0, spread_bps)
                + impact
                + latency
                + safety
            )
            add_option(
                policy="taker_market",
                total_cost_bps=taker_cost,
                expected_fill_ratio=0.98,
                reason="immediate_fill_high_cost",
                extra={
                    "fee_bps": round(self.small_window_taker_fee_bps_per_side * 2.0, 6),
                    "spread_bps": round(max(0.0, spread_bps), 6),
                    "impact_bps": round(impact, 6),
                    "latency_bps": round(latency, 6),
                    "safety_bps": round(safety, 6),
                },
            )

        if "maker_probe" in policies:
            fill = 0.78
            fill -= min(0.28, max(0.0, spread_bps - 25.0) / 350.0)
            fill -= min(0.22, max(0.0, velocity_bps_per_min - 80.0) / 600.0)
            fill -= min(0.12, abs(book_imbalance) * 0.16)
            if depth >= notional * 200.0:
                fill += 0.08
            if volume_zscore > 0.0:
                fill += min(0.05, volume_zscore * 0.015)
            maker_cost = (
                self.small_window_maker_fee_bps_per_side * 2.0
                + max(0.0, spread_bps) * 0.25
                + impact * 0.35
                + latency * 2.0
                + safety
            )
            add_option(
                policy="maker_probe",
                total_cost_bps=maker_cost,
                expected_fill_ratio=fill,
                reason="lower_cost_fill_not_guaranteed",
                extra={
                    "fee_bps": round(self.small_window_maker_fee_bps_per_side * 2.0, 6),
                    "spread_bps": round(max(0.0, spread_bps) * 0.25, 6),
                    "impact_bps": round(impact * 0.35, 6),
                    "latency_bps": round(latency * 2.0, 6),
                    "safety_bps": round(safety, 6),
                },
            )

        route_context = self._route_context(observation)
        if "dex_swap" in policies:
            dex_allowed = route_context.get("allowed")
            roundtrip = route_context.get("roundtrip_ratio")
            gas_drag_pct = route_context.get("gas_drag_pct")
            price_impact_pct = route_context.get("price_impact_pct")
            if route_context.get("known") and dex_allowed is not False and roundtrip:
                friction = max(0.0, (1.0 - float(roundtrip)) * 10_000.0)
                gas = max(0.0, _number(gas_drag_pct) * 10_000.0) if gas_drag_pct is not None else 0.0
                impact_proxy = max(0.0, _number(price_impact_pct) * 10_000.0) if price_impact_pct is not None else 0.0
                dex_cost = friction + gas + self.small_window_dex_mev_buffer_bps
                add_option(
                    policy="dex_swap",
                    route_kind="dex",
                    total_cost_bps=dex_cost,
                    expected_fill_ratio=0.92,
                    reason="aggregator_quote_plus_mev_buffer",
                    tradable=True,
                    extra={
                        "roundtrip_friction_bps": round(friction, 6),
                        "gas_bps": round(gas, 6),
                        "price_impact_proxy_bps": round(impact_proxy, 6),
                        "mev_buffer_bps": round(self.small_window_dex_mev_buffer_bps, 6),
                        "provider": route_context.get("provider"),
                    },
                )
            elif route_context.get("known"):
                add_option(
                    policy="dex_swap",
                    route_kind="dex",
                    total_cost_bps=1_000_000_000.0,
                    expected_fill_ratio=0.0,
                    reason=str(route_context.get("reason") or "dex_route_not_tradable"),
                    tradable=False,
                    extra={"provider": route_context.get("provider")},
                )

        tradable_options = [item for item in options if bool(item.get("tradable"))]
        selected = max(
            tradable_options or options,
            key=lambda item: (
                1 if bool(item.get("tradable")) else 0,
                _number(item.get("expected_net_after_fill_bps"), -1e9),
                -_number(item.get("total_cost_bps"), 1e9),
            ),
        ) if options else {}
        if not selected:
            selected = {
                "policy": "unroutable",
                "tradable": False,
                "reason": "no_execution_policy_options",
                "total_cost_bps": 1_000_000_000.0,
                "expected_fill_ratio": 0.0,
                "expected_net_after_fill_bps": -1e9,
            }
        return {
            "schema": "small_window_execution_route_decision_v1",
            "selected_policy": selected.get("policy"),
            "selected_route_kind": selected.get("route_kind", "cex"),
            "tradable": bool(selected.get("tradable")),
            "reason": selected.get("reason"),
            "total_cost_bps": selected.get("total_cost_bps"),
            "expected_fill_ratio": selected.get("expected_fill_ratio"),
            "expected_net_after_fill_bps": selected.get("expected_net_after_fill_bps"),
            "route_options": options,
            "dex_route_health": route_context,
            "microstructure": microstructure,
            "authority": "paper_execution_model_only",
        }

    def _small_window_canary_memory(self, symbol: str, direction: str, window_sec: int) -> dict[str, Any]:
        if not self.small_window_canary_memory_enabled or not getattr(self.data_store, "conn", None):
            return {"samples": 0}
        key = (str(symbol or ""), str(direction or "").upper(), int(window_sec or 0))
        cached = self._canary_memory_cache.get(key)
        if cached is not None:
            return dict(cached)
        scope_key = f"{key[0]}|{key[1]}|{key[2]}"
        lock = self._lock
        try:
            if lock:
                lock.acquire()
            rows = self.conn.execute(
                """
                SELECT payload
                FROM crystal_registry
                WHERE crystal_family='small_window_canary_memory'
                  AND scope_key=?
                ORDER BY updated_ts DESC
                LIMIT ?
                """,
                (scope_key, int(self.small_window_canary_memory_limit)),
            ).fetchall()
        except Exception:
            self._canary_memory_cache[key] = {"samples": 0, "error": "crystal_registry_unavailable"}
            return dict(self._canary_memory_cache[key])
        finally:
            if lock:
                lock.release()
        nets: list[float] = []
        gross: list[float] = []
        wins = 0
        latest_ts = 0.0
        latest_net = None
        for raw in rows:
            try:
                payload = json.loads((raw[0] if raw else "") or "{}")
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                continue
            if isinstance(payload.get("payload"), dict):
                payload = dict(payload["payload"])
            net = _number(payload.get("net_return_bps"))
            nets.append(net)
            if payload.get("gross_return_bps") is not None:
                gross.append(_number(payload.get("gross_return_bps")))
            wins += 1 if bool(payload.get("positive_net")) or net > 0 else 0
            ts = _number(payload.get("settled_ts"))
            if ts >= latest_ts:
                latest_ts = ts
                latest_net = net
        samples = len(nets)
        memory = {
            "schema": "small_window_canary_memory_summary_v1",
            "scope_key": scope_key,
            "samples": samples,
            "wins": wins,
            "losses": max(0, samples - wins),
            "win_rate": (wins / samples) if samples else None,
            "mean_net_bps": (sum(nets) / samples) if samples else None,
            "mean_gross_bps": (sum(gross) / len(gross)) if gross else None,
            "latest_net_bps": latest_net,
            "latest_settled_ts": latest_ts or None,
        }
        self._canary_memory_cache[key] = dict(memory)
        return memory

    def _annotate_healthy_candidate(
        self,
        candidate: Mapping[str, Any],
        *,
        peers: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        item = dict(candidate)
        symbol = str(item.get("symbol") or "")
        direction = str(item.get("direction") or "").upper()
        signal_lane = str(item.get("signal_lane") or "continuation")
        window = int(_number(item.get("window_sec"), 0.0) or 0)
        same_windows = {
            int(_number(peer.get("window_sec"), 0.0) or 0)
            for peer in peers
            if str(peer.get("symbol") or "") == symbol and str(peer.get("direction") or "").upper() == direction
            and str(peer.get("signal_lane") or "continuation") == signal_lane
        }
        opposing_windows = {
            int(_number(peer.get("window_sec"), 0.0) or 0)
            for peer in peers
            if str(peer.get("symbol") or "") == symbol and str(peer.get("direction") or "").upper()
            and str(peer.get("direction") or "").upper() != direction
            and str(peer.get("signal_lane") or "continuation") == signal_lane
        }
        same_windows.discard(0)
        opposing_windows.discard(0)
        expected_net = _number(item.get("expected_net_bps"))
        abs_move = _number(item.get("absolute_move_bps"))
        cost = max(1e-9, _number(item.get("expected_cost_bps"), 1.0))
        spread = _number(item.get("spread_bps"))
        depth = _number(item.get("depth_usd_25bps"))
        volume_z = _number(item.get("volume_zscore"))
        vol_expansion = _number(item.get("volatility_expansion"))
        cost_multiple = abs_move / cost if cost > 0 else 0.0
        execution_route = self._nested_mapping(item.get("execution_route"))
        microstructure = self._nested_mapping(item.get("microstructure") or execution_route.get("microstructure"))
        route_policy = str(item.get("route_policy") or execution_route.get("selected_policy") or "unknown")
        fill_ratio = _number(item.get("expected_fill_ratio"), _number(execution_route.get("expected_fill_ratio"), 1.0))
        fill_adjusted_net = _number(item.get("expected_fill_adjusted_net_bps"), expected_net)

        score = 15.0
        reasons: list[str] = []
        score += min(25.0, max(0.0, fill_adjusted_net) * 0.05)
        if cost_multiple >= self.small_window_health_min_cost_multiple:
            score += min(20.0, 8.0 + (cost_multiple - self.small_window_health_min_cost_multiple) * 4.0)
        else:
            score -= min(20.0, (self.small_window_health_min_cost_multiple - cost_multiple) * 12.0)
            reasons.append("weak_cost_headroom")
        if execution_route:
            if not bool(execution_route.get("tradable", True)):
                score -= 45.0
                reasons.append("execution_route_untradable")
            if fill_ratio < 0.50:
                score -= min(22.0, (0.50 - fill_ratio) * 80.0)
                reasons.append("low_expected_fill_ratio")
            elif route_policy == "maker_probe":
                score += 5.0
                reasons.append("maker_probe_cost_control")
            elif route_policy == "taker_market" and cost_multiple < 2.0:
                score -= 10.0
                reasons.append("taker_cost_needs_larger_move")
            elif route_policy == "dex_swap":
                score += 2.0
                reasons.append("swap_route_costed")
        hostile_flags = list(microstructure.get("hostile_flags") or []) if isinstance(microstructure, dict) else []
        if hostile_flags:
            score -= min(18.0, 5.0 * len(hostile_flags))
            reasons.extend([f"microstructure_{flag}" for flag in hostile_flags[:3]])
        micro_quality = _number(microstructure.get("quality_score"), 100.0) if isinstance(microstructure, dict) else 100.0
        if micro_quality < 45.0:
            score -= min(20.0, (45.0 - micro_quality) * 0.40)
            reasons.append("microstructure_quality_low")
        if len(same_windows) >= 2:
            score += 12.0
            reasons.append("cross_window_direction_support")
        if len(same_windows) >= 3:
            score += 8.0
        if opposing_windows:
            score -= min(30.0, 12.0 * len(opposing_windows))
            reasons.append("opposing_window_conflict")
        if window >= 3600 and len(same_windows) <= 1:
            score -= 10.0
            reasons.append("one_hour_move_without_shorter_support")
        if spread <= 40.0:
            score += 8.0
        elif spread >= 120.0:
            score -= min(20.0, (spread - 120.0) * 0.10)
            reasons.append("wide_spread")
        if depth >= max(self.notional_usd * 50.0, 25.0):
            score += 7.0
        elif depth > 0:
            score += 3.0
            reasons.append("thin_depth")
        else:
            reasons.append("depth_unknown")
        if volume_z > 0:
            score += min(6.0, volume_z * 2.0)
        if vol_expansion > 1.0:
            score += min(6.0, (vol_expansion - 1.0) * 3.0)
        if signal_lane == "micro_reversion":
            score += 6.0
            reasons.append("micro_reversion_trickle_lane")
            if spread > 80.0:
                score -= min(18.0, (spread - 80.0) * 0.15)
                reasons.append("micro_reversion_spread_drag")
            if window <= 300:
                score += 6.0
                reasons.append("short_window_swing_capture")
            elif window >= 3600 and len(same_windows) <= 1:
                score -= 8.0
                reasons.append("long_window_reversion_needs_short_support")

        route = self._route_context(self._nested_mapping(item.get("latest_observation")))
        if route["known"]:
            if route["allowed"] is False:
                score -= 45.0
                reasons.append("dex_exit_not_clear")
            roundtrip = route.get("roundtrip_ratio")
            gas_drag = route.get("gas_drag_pct")
            if roundtrip is not None and roundtrip > 0:
                route_loss_bps = max(0.0, (1.0 - float(roundtrip)) * 10_000.0)
                if gas_drag is not None:
                    route_loss_bps += max(0.0, float(gas_drag) * 10_000.0)
                route_headroom = expected_net - route_loss_bps
                item["dex_route_loss_bps"] = route_loss_bps
                item["dex_route_headroom_bps"] = route_headroom
                if route_headroom >= 0:
                    score += min(10.0, route_headroom * 0.08)
                    reasons.append("dex_route_headroom_clear")
                else:
                    score -= min(35.0, abs(route_headroom) * 0.10)
                    reasons.append("dex_route_cost_over_edge")
            price_impact = route.get("price_impact_pct")
            if price_impact is not None and price_impact > 0.02:
                score -= 15.0
                reasons.append("dex_price_impact_high")
        else:
            route = {"known": False}

        canary_memory = self._small_window_canary_memory(symbol, direction, window)
        memory_samples = int(canary_memory.get("samples") or 0)
        if memory_samples:
            mean_net = _number(canary_memory.get("mean_net_bps"))
            latest_net = _number(canary_memory.get("latest_net_bps"))
            win_rate = _number(canary_memory.get("win_rate"))
            sample_factor = min(1.0, memory_samples / 4.0)
            if mean_net > 0 and win_rate >= 0.5:
                score += min(24.0, 8.0 + mean_net * 0.08) * sample_factor
                reasons.append("canary_positive_memory")
            else:
                score -= min(32.0, 8.0 + abs(mean_net) * 0.15) * sample_factor
                reasons.append("canary_negative_memory")
            if latest_net < 0:
                score -= min(14.0, abs(latest_net) * 0.10)
                reasons.append("latest_canary_loss")
            elif latest_net > 0:
                score += min(10.0, latest_net * 0.06)
                reasons.append("latest_canary_win")
            if memory_samples >= 2 and win_rate <= 0.25:
                score -= 12.0
                reasons.append("repeat_canary_failure")

        health_score = max(0.0, min(100.0, score))
        if not reasons:
            reasons.append("healthy_small_window_candidate")
        item.update({
            "health_score": health_score,
            "health_state": "HEALTHY" if health_score >= max(1.0, self.small_window_health_min_score) else "WATCH",
            "health_reasons": reasons[:8],
            "signal_lane": signal_lane,
            "cost_multiple": cost_multiple,
            "same_direction_windows": sorted(same_windows),
            "opposing_direction_windows": sorted(opposing_windows),
            "dex_route_health": route,
            "execution_route": execution_route,
            "route_policy": route_policy,
            "expected_fill_ratio": fill_ratio,
            "microstructure": microstructure,
            "canary_memory": canary_memory,
        })
        return item

    def _trend_comparison_candidates_multi_window(
        self,
        *,
        windows_sec: tuple[int, ...],
        max_age_sec: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        per_window_limit = max(1, int(limit or 1) * 3)
        for window in windows_sec:
            candidates.extend(
                self._trend_comparison_candidates(
                    window_sec=max(30, int(window)),
                    max_age_sec=max(30, int(max_age_sec or 1_800)),
                    limit=per_window_limit,
                )
            )
        candidates = [
            self._annotate_healthy_candidate(candidate, peers=candidates)
            for candidate in candidates
        ]
        sort_key = lambda row: (
            _number(row.get("health_score")),
            _number(row.get("score")),
            _number(row.get("expected_net_bps")),
            _number(row.get("absolute_move_bps")),
        )
        if self.small_window_preserve_window_coverage:
            buckets: dict[int, list[dict[str, Any]]] = {}
            for item in candidates:
                buckets.setdefault(int(_number(item.get("window_sec"))), []).append(item)
            for items in buckets.values():
                items.sort(key=sort_key, reverse=True)
            seen: set[str] = set()
            unique: list[dict[str, Any]] = []
            ordered_windows = [int(window) for window in windows_sec if int(window) in buckets]
            while len(unique) < max(1, int(limit or 1)) and any(buckets.get(window) for window in ordered_windows):
                for window in ordered_windows:
                    if not buckets.get(window):
                        continue
                    item = buckets[window].pop(0)
                    key = "|".join([
                        str(item.get("symbol") or ""),
                        str(item.get("direction") or ""),
                        str(item.get("window_sec") or ""),
                        str(item.get("source_id") or ""),
                    ])
                    if key in seen:
                        continue
                    seen.add(key)
                    unique.append(item)
                    if len(unique) >= max(1, int(limit or 1)):
                        break
            return unique
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for item in sorted(
            candidates,
            key=sort_key,
            reverse=True,
        ):
            key = "|".join([
                str(item.get("symbol") or ""),
                str(item.get("direction") or ""),
                str(item.get("window_sec") or ""),
                str(item.get("source_id") or ""),
            ])
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
            if len(unique) >= max(1, int(limit or 1)):
                break
        return unique

    def open_from_trend_comparisons(
        self,
        *,
        limit: int = 5,
        window_sec: int = 900,
        windows_sec: Optional[tuple[int, ...]] = None,
        hold_sec: int = 300,
        max_age_sec: int = 1_800,
    ) -> dict[str, Any]:
        """Open paper-only trades from observed small-window trend comparisons."""
        result = {
            "examined": 0,
            "opened": 0,
            "skipped": 0,
            "skipped_duplicate_open": 0,
            "skipped_symbol_cap": 0,
            "skipped_capacity": 0,
            "skipped_unhealthy": 0,
            "candidates": [],
            "opened_candidates": [],
            "authority": "paper_only_no_private_exchange",
            "source": "small_window_multi_window_delta",
            "windows_sec": [],
            "allowed_directions": list(self.small_window_allowed_directions),
            "healthy_min_score": self.small_window_health_min_score,
        }
        if windows_sec is None:
            windows = self.small_window_trend_windows_sec or (max(30, int(window_sec or 900)),)
        else:
            windows = tuple(sorted({max(30, int(item)) for item in windows_sec if int(item) > 0}))
        candidates = self._trend_comparison_candidates_multi_window(
            windows_sec=windows,
            max_age_sec=max(30, int(max_age_sec or 1_800)),
            limit=max(1, int(limit or 1)),
        )
        result["windows_sec"] = list(windows)
        result["examined"] = len(candidates)
        result["candidates"] = [
            {key: item.get(key) for key in (
                "symbol", "direction", "score", "comparison_return_bps", "expected_net_bps",
                "expected_move_bps", "expected_cost_bps", "expected_fill_adjusted_net_bps",
                "spread_bps", "entry_price", "anchor_price", "window_sec",
                "window_label", "elapsed_sec", "health_score", "health_state", "health_reasons",
                "signal_lane", "cost_multiple", "same_direction_windows", "opposing_direction_windows",
                "dex_route_health", "dex_route_loss_bps", "dex_route_headroom_bps",
                "execution_route", "route_policy", "route_kind", "expected_fill_ratio", "microstructure",
                "canary_memory"
            )}
            for item in candidates
        ]
        for candidate in candidates:
            if self.small_window_health_min_score and _number(candidate.get("health_score")) < self.small_window_health_min_score:
                result["skipped"] += 1
                result["skipped_unhealthy"] += 1
                continue
            if self.active_count() >= self.max_open:
                result["skipped"] += 1
                result["skipped_capacity"] += 1
                continue
            if self._symbol_open_cap_reached(str(candidate.get("symbol") or "")):
                result["skipped"] += 1
                result["skipped_symbol_cap"] += 1
                continue
            if self._has_duplicate_open_exposure(candidate):
                result["skipped"] += 1
                result["skipped_duplicate_open"] += 1
                continue
            payload = {
                "schema": "rapid_paper_multi_window_delta_trade_v1",
                "authority": "paper_only_no_private_exchange",
                "source": "small_window_multi_window_delta",
                "candidate": candidate,
                "note": "Opened from observed multi-window price delta, not model forecast arbitration.",
            }
            opened = self._insert_open_trade(
                source_id=str(candidate.get("source_id")),
                run_id=str(candidate.get("run_id")),
                venue=str(candidate.get("venue") or "kraken"),
                symbol=str(candidate.get("symbol") or ""),
                model_id=str(candidate.get("model_id") or "small_window_trend_comparison_v1"),
                hypothesis=str(candidate.get("hypothesis") or self.small_window_hypothesis),
                direction=str(candidate.get("direction") or "UP"),
                entry_ts=float(self.now_fn()),
                target_ts=float(self.now_fn()) + max(30, int(hold_sec or 300)),
                entry_price=_number(candidate.get("entry_price")),
                expected_net_bps=_number(candidate.get("expected_net_bps")),
                expected_cost_bps=_number(candidate.get("expected_cost_bps")),
                probability_positive_net=_number(candidate.get("probability_positive_net"), 0.5),
                payload=payload,
            )
            if opened:
                result["opened"] += 1
                result["opened_candidates"].append({
                    key: candidate.get(key) for key in (
                        "symbol", "direction", "score", "comparison_return_bps", "expected_net_bps",
                        "expected_move_bps", "expected_cost_bps", "expected_fill_adjusted_net_bps",
                        "spread_bps", "entry_price", "anchor_price", "window_sec",
                        "window_label", "elapsed_sec", "health_score", "health_state", "health_reasons",
                        "signal_lane", "cost_multiple", "same_direction_windows", "opposing_direction_windows",
                        "dex_route_health", "dex_route_loss_bps", "dex_route_headroom_bps",
                        "execution_route", "route_policy", "route_kind", "expected_fill_ratio", "microstructure",
                        "canary_memory"
                    )
                })
            else:
                result["skipped"] += 1
                result["skipped_duplicate_open"] += 1
        return result

    def _persist_negative_crystal(self, row: Mapping[str, Any], *, net_bps: float, settled_ts: float) -> None:
        if net_bps >= 0 or not hasattr(self.data_store, "persist_crystal_registry_entry"):
            return
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        forecast = payload.get("forecast") if isinstance(payload.get("forecast"), dict) else {}
        recent_context = payload.get("recent_context") if isinstance(payload.get("recent_context"), dict) else {}
        model_id = str(row.get("model_id") or forecast.get("model_id") or "unknown")
        hypothesis = str(row.get("hypothesis") or forecast.get("hypothesis") or "unknown")
        direction = str(row.get("direction") or forecast.get("direction") or "unknown").upper()
        symbol = str(row.get("symbol") or forecast.get("symbol") or "unknown")
        regime_hint = str(forecast.get("regime_hint") or "rapid_paper_unknown_regime")
        scope_key = f"{model_id}|{hypothesis}|{direction}|{regime_hint}|{symbol}"
        crystal_payload = {
            "schema": "negative_capability_crystal_v1",
            "artifact_class": "negative_capability_crystal",
            "authority": "proposal_only",
            "source": "rapid_paper_tape",
            "source_forecast_id": row.get("source_forecast_id"),
            "trade_id": row.get("trade_id"),
            "model_id": model_id,
            "hypothesis": hypothesis,
            "direction": direction,
            "symbol": symbol,
            "regime_hint": regime_hint,
            "failure_state": ["rapid_paper_negative_net"],
            "expected_net_bps": row.get("expected_net_bps"),
            "actual_net_bps": net_bps,
            "entry_price": row.get("entry_price"),
            "exit_price": row.get("exit_price"),
            "settled_ts": settled_ts,
            "recent_context": recent_context,
        }
        crystal_id = canonical_hash({
            "family": "negative_capability",
            "source": "rapid_paper_tape",
            "trade_id": row.get("trade_id"),
            "actual_net_bps": round(float(net_bps), 8),
        })
        self.data_store.persist_crystal_registry_entry({
            "crystal_id": crystal_id,
            "created_ts": float(settled_ts),
            "updated_ts": float(self.now_fn()),
            "crystal_family": "negative_capability",
            "artifact_class": "negative_capability_crystal",
            "authority": "proposal_only",
            "verification_state": "candidate",
            "phase_scope": 2,
            "scope_key": scope_key,
            "symbol": symbol,
            "venue": row.get("venue"),
            "regime_hint": regime_hint,
            "hypothesis": hypothesis,
            "world_state_id": None,
            "applicability_hash": canonical_hash(scope_key),
            "evidence_strength": abs(float(net_bps)),
            "drift_status": "active_refusal_memory",
            "expires_ts": None,
            "payload": crystal_payload,
        })

    def open_from_recent_forecasts(self, *, limit: int = 25) -> dict[str, Any]:
        if not bool(getattr(self.cfg, "phase2_rapid_paper_forecast_lane_enabled", True)):
            return {
                "examined": 0,
                "opened": 0,
                "vetoed": 0,
                "skipped": 0,
                "skipped_duplicate_open": 0,
                "skipped_recent_loss": 0,
                "skipped_data_gap": 0,
                "skipped_negative_memory": 0,
                "skipped_model_direction_probation": 0,
                "skipped_champion_scout": 0,
                "skipped_symbol_cap": 0,
                "champion_scout_enabled": self.champion_scout_enabled,
                "remaining_capacity": max(0, self.max_open - self.active_count()),
                "disabled": True,
                "reason": "forecast_lane_disabled_small_window_overhaul",
            }
        now = float(self.now_fn())
        remaining = max(0, self.max_open - self.active_count())
        result = {
            "examined": 0,
            "opened": 0,
            "vetoed": 0,
            "skipped": 0,
            "skipped_duplicate_open": 0,
            "skipped_recent_loss": 0,
            "skipped_data_gap": 0,
            "skipped_negative_memory": 0,
            "skipped_model_direction_probation": 0,
            "skipped_champion_scout": 0,
            "skipped_symbol_cap": 0,
            "champion_scout_enabled": self.champion_scout_enabled,
            "remaining_capacity": remaining,
        }
        if remaining <= 0:
            result["reason"] = "max_open_rapid_paper_trades"
            return result
        direction_clause = ""
        params: list[Any] = [
            now - self.max_age_sec,
            now,
            self.min_expected_net_bps,
            self.min_probability,
        ]
        if "ANY" not in self.allowed_directions:
            placeholders = ",".join("?" for _ in self.allowed_directions)
            direction_clause = f" AND UPPER(f.direction) IN ({placeholders})"
            params.extend(self.allowed_directions)
        source_limit = int(limit)
        if self.champion_scout_enabled:
            self._champion_slice_cache = {}
            source_limit = max(source_limit, int(limit) * self.champion_scout_fetch_multiplier)
        params.append(source_limit)
        candidates = self._fetchall(
            f"""
            SELECT f.*
            FROM hypothesis_forecasts f
            LEFT JOIN rapid_paper_tape_trades t ON t.source_forecast_id=f.forecast_id
            WHERE f.abstain=0
              AND f.ts>=?
              AND f.target_ts>?
              AND COALESCE(f.expected_net_bps, 0)>=?
              AND COALESCE(f.probability_positive_net, 0)>=?
              {direction_clause}
              AND t.source_forecast_id IS NULL
            ORDER BY f.expected_net_bps DESC, f.probability_positive_net DESC, f.ts DESC
            LIMIT ?
            """,
            tuple(params),
        )
        if self.champion_scout_enabled:
            for forecast in candidates:
                forecast["champion_scout"] = self._champion_slice_stats(forecast, now)
            candidates.sort(
                key=lambda item: (
                    1 if (item.get("champion_scout") or {}).get("accepted") else 0,
                    float((item.get("champion_scout") or {}).get("score") or 0.0),
                    _number(item.get("expected_net_bps")),
                    _number(item.get("probability_positive_net")),
                ),
                reverse=True,
            )
        result["examined"] = len(candidates)
        for forecast in candidates:
            if self.active_count() >= self.max_open:
                result["skipped"] += 1
                continue
            champion_scout = forecast.get("champion_scout") if isinstance(forecast.get("champion_scout"), dict) else None
            if self.champion_scout_enabled and not bool((champion_scout or {}).get("accepted")):
                result["skipped"] += 1
                result["skipped_champion_scout"] += 1
                continue
            if self._has_duplicate_open_exposure(forecast):
                result["skipped"] += 1
                result["skipped_duplicate_open"] += 1
                continue
            if self._symbol_open_cap_reached(str(forecast.get("symbol") or "")):
                result["skipped"] += 1
                result["skipped_symbol_cap"] += 1
                continue
            if self._recent_loss_cooldown(forecast, now):
                result["skipped"] += 1
                result["skipped_recent_loss"] += 1
                continue
            if self._negative_memory_refusal(forecast):
                result["skipped"] += 1
                result["skipped_negative_memory"] += 1
                continue
            if self._model_direction_probation_refusal(forecast):
                result["skipped"] += 1
                result["skipped_model_direction_probation"] += 1
                continue
            context = self._recent_context(forecast)
            context_ts = _number(context.get("observation_ts"))
            forecast_ts = _number(forecast.get("ts"), now)
            if not context or context_ts <= 0 or abs(forecast_ts - context_ts) > self.max_observation_age_sec:
                result["skipped"] += 1
                continue
            if self._recent_data_gap_expiry(str(forecast.get("symbol") or ""), now):
                result["skipped"] += 1
                result["skipped_data_gap"] += 1
                continue
            review = self.critic.review(forecast, recent_context=context)
            llm_veto = bool(review.get("veto")) and bool(getattr(self.critic, "hard_veto", False))
            status = "VETOED" if llm_veto else "OPEN"
            if llm_veto:
                result["vetoed"] += 1
            else:
                result["opened"] += 1
            payload = {
                "schema": "rapid_paper_tape_trade_v1",
                "authority": "paper_only_no_private_exchange",
                "forecast": forecast,
                "llm_review": review,
                "recent_context": context,
                "champion_scout": champion_scout,
            }
            self._insert_open_trade(
                source_id=str(forecast.get("forecast_id") or ""),
                run_id=str(forecast.get("run_id") or ""),
                venue=str(forecast.get("venue") or ""),
                symbol=str(forecast.get("symbol") or ""),
                model_id=str(forecast.get("model_id") or ""),
                hypothesis=str(forecast.get("hypothesis") or ""),
                direction=str(forecast.get("direction") or ""),
                entry_ts=_number(forecast.get("ts")),
                target_ts=_number(forecast.get("target_ts")),
                entry_price=_number(forecast.get("entry_price")),
                expected_net_bps=_number(forecast.get("expected_net_bps")),
                expected_cost_bps=_number(forecast.get("expected_cost_bps")),
                probability_positive_net=_number(forecast.get("probability_positive_net"), 0.5),
                payload=payload,
                review=review,
                status=status,
                failure_reason="llm_veto" if llm_veto else None,
            )
        return result

    def repeatable_mover_scorecard(
        self,
        *,
        min_samples: int = 3,
        min_win_rate: float = 0.55,
        min_mean_net_bps: float = 5.0,
        min_total_net_bps: float = 10.0,
        limit: int = 25,
    ) -> dict[str, Any]:
        """Score closed small-window trend trades for research-only promotion."""
        rows = self._fetchall(
            """
            SELECT *
            FROM rapid_paper_tape_trades
            WHERE model_id='small_window_trend_comparison_v1'
              AND status IN ('CLOSED_WIN','CLOSED_LOSS')
            ORDER BY settled_ts DESC
            LIMIT ?
            """,
            (max(100, int(limit or 25) * 20),),
        )
        grouped: dict[tuple[str, str, int, str, str], dict[str, Any]] = {}
        for row in rows:
            payload = self._payload_dict(row.get("payload"))
            candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
            window = int(_number(candidate.get("window_sec"), _number(row.get("window_sec"), 0.0)) or 0)
            signal_lane = str(candidate.get("signal_lane") or "continuation")
            route_policy = str(candidate.get("route_policy") or "unknown")
            key = (str(row.get("symbol") or ""), str(row.get("direction") or ""), window, signal_lane, route_policy)
            item = grouped.setdefault(key, {
                "symbol": row.get("symbol"),
                "direction": row.get("direction"),
                "window_sec": window,
                "signal_lane": signal_lane,
                "route_policy": route_policy,
                "samples": 0,
                "wins": 0,
                "total_net_bps": 0.0,
                "worst_net_bps": None,
                "best_net_bps": None,
                "latest_settled_ts": 0.0,
            })
            net = _number(row.get("net_return_bps"))
            item["samples"] += 1
            item["wins"] += 1 if net > 0 else 0
            item["total_net_bps"] += net
            item["worst_net_bps"] = net if item["worst_net_bps"] is None else min(_number(item["worst_net_bps"]), net)
            item["best_net_bps"] = net if item["best_net_bps"] is None else max(_number(item["best_net_bps"]), net)
            item["latest_settled_ts"] = max(_number(item["latest_settled_ts"]), _number(row.get("settled_ts")))
        ranked = []
        promoted = []
        now = float(self.now_fn())
        grouped_rows = sorted(
            grouped.values(),
            key=lambda item: (
                _number(item.get("total_net_bps")),
                _number(item.get("total_net_bps")) / max(1, int(item.get("samples") or 0)),
                int(item.get("samples") or 0),
            ),
            reverse=True,
        )[: max(1, int(limit or 25))]
        for row in grouped_rows:
            samples = int(row.get("samples") or 0)
            wins = int(row.get("wins") or 0)
            win_rate = wins / samples if samples else 0.0
            mean_net = _number(row.get("total_net_bps")) / max(1, samples)
            total_net = _number(row.get("total_net_bps"))
            reasons = []
            if samples < int(min_samples):
                reasons.append("needs_more_small_window_samples")
            if win_rate < float(min_win_rate):
                reasons.append("small_window_win_rate_below_floor")
            if mean_net < float(min_mean_net_bps):
                reasons.append("small_window_mean_net_below_floor")
            if total_net < float(min_total_net_bps):
                reasons.append("small_window_total_net_below_floor")
            eligible = not reasons
            record = {
                "schema": "small_window_repeatable_mover_score_v1",
                "symbol": row.get("symbol"),
                "direction": row.get("direction"),
                "window_sec": int(row.get("window_sec") or 0),
                "signal_lane": row.get("signal_lane"),
                "route_policy": row.get("route_policy"),
                "window_label": {
                    60: "1m",
                    300: "5m",
                    1800: "30m",
                    3600: "1h",
                }.get(int(row.get("window_sec") or 0), f"{int(row.get('window_sec') or 0)}s"),
                "samples": samples,
                "wins": wins,
                "win_rate": win_rate,
                "mean_net_bps": mean_net,
                "total_net_bps": total_net,
                "worst_net_bps": row.get("worst_net_bps"),
                "best_net_bps": row.get("best_net_bps"),
                "latest_settled_ts": row.get("latest_settled_ts"),
                "eligible": eligible,
                "stage": "research_import" if eligible else "paper",
                "reason": "repeatable_small_window_mover" if eligible else ",".join(reasons),
                "promotion_authority": "none",
                "execution_authority": "none",
            }
            ranked.append(record)
            if eligible:
                promoted.append(record)
                if hasattr(self.data_store, "upsert_promotion_record"):
                    self.data_store.upsert_promotion_record(str(row.get("symbol") or ""), {
                        "stage": "research_import",
                        "eligible": True,
                        "reason": "repeatable_small_window_mover",
                        "paper_trades": samples,
                        "win_rate": win_rate,
                        "net_margin_sum": total_net / 10_000.0,
                        "max_drawdown_pct": abs(min(0.0, _number(row.get("worst_net_bps"))) / 100.0),
                        "clean_exits": wins,
                        "failed_exits": samples - wins,
                        "updated_ts": now,
                        "source": "small_window_repeatable_mover_scorecard",
                        "direction": row.get("direction"),
                        "window_sec": int(row.get("window_sec") or 0),
                        "signal_lane": row.get("signal_lane"),
                        "route_policy": row.get("route_policy"),
                        "mean_net_bps": mean_net,
                        "total_net_bps": total_net,
                        "promotion_authority": "none",
                        "execution_authority": "none",
                    })
        return {
            "schema": "small_window_repeatable_mover_scorecard_v1",
            "authority": "research_import_evidence_only",
            "promotion_authority": "none",
            "execution_authority": "none",
            "min_samples": int(min_samples),
            "min_win_rate": float(min_win_rate),
            "min_mean_net_bps": float(min_mean_net_bps),
            "min_total_net_bps": float(min_total_net_bps),
            "ranked": ranked,
            "promoted": promoted,
        }

    def close_settled(self) -> dict[str, Any]:
        now = float(self.now_fn())
        open_rows = self._fetchall(
            """
            SELECT t.*, o.settled_ts AS outcome_settled_ts, o.exit_price AS outcome_exit_price,
                   o.gross_return_bps AS outcome_gross_return_bps,
                   o.directional_return_bps AS outcome_directional_return_bps,
                   o.net_return_bps AS outcome_net_return_bps,
                   o.positive_net AS outcome_positive_net
            FROM rapid_paper_tape_trades t
            JOIN hypothesis_outcomes o ON o.forecast_id=t.source_forecast_id
            WHERE t.status='OPEN'
            ORDER BY o.settled_ts ASC
            """,
        )
        closed = 0
        for row in open_rows:
            net_bps = _number(row.get("outcome_net_return_bps"))
            status = "CLOSED_WIN" if net_bps > 0 else "CLOSED_LOSS"
            payload = self._payload_dict(row.get("payload"))
            payload.update({
                "settlement": {
                    "settled_ts": row.get("outcome_settled_ts"),
                    "exit_price": row.get("outcome_exit_price"),
                    "gross_return_bps": row.get("outcome_gross_return_bps"),
                    "directional_return_bps": row.get("outcome_directional_return_bps"),
                    "net_return_bps": net_bps,
                    "positive_net": bool(row.get("outcome_positive_net")),
                }
            })
            with self._lock:
                self.conn.execute(
                    """
                    UPDATE rapid_paper_tape_trades
                    SET status=?, settled_ts=?, updated_ts=?, exit_price=?, gross_return_bps=?,
                        directional_return_bps=?, net_return_bps=?, positive_net=?, payload=?
                    WHERE trade_id=?
                    """,
                    (
                        status,
                        row.get("outcome_settled_ts"),
                        now,
                        row.get("outcome_exit_price"),
                        row.get("outcome_gross_return_bps"),
                        row.get("outcome_directional_return_bps"),
                        net_bps,
                        int(bool(row.get("outcome_positive_net"))),
                        json.dumps(payload, sort_keys=True, default=str),
                        row.get("trade_id"),
                    ),
                )
                self.conn.commit()
            if hasattr(self.data_store, "store_paper_trade"):
                self.data_store.store_paper_trade({
                    "ts": row.get("outcome_settled_ts") or now,
                    "symbol": row.get("symbol"),
                    "side": "EXIT",
                    "qty": self.notional_usd / max(1e-9, _number(row.get("entry_price"), 1.0)),
                    "price": row.get("outcome_exit_price"),
                    "notional_usd": self.notional_usd,
                    "reason": f"RAPID_TAPE:{row.get('source_forecast_id')}:{status}",
                    "net_margin_pct": net_bps / 10_000.0,
                    "status": status,
                })
            self._persist_negative_crystal(row, net_bps=net_bps, settled_ts=float(row.get("outcome_settled_ts") or now))
            closed += 1
        return {"closed": closed, "examined": len(open_rows)}

    def settle_due_open_trades(self, *, tolerance_sec: float = 900.0) -> dict[str, Any]:
        """Settle this tape's open trades directly from public observations."""
        now = float(self.now_fn())
        open_rows = self._fetchall(
            """
            SELECT * FROM rapid_paper_tape_trades
            WHERE status='OPEN' AND target_ts<=?
            ORDER BY target_ts ASC
            LIMIT 250
            """,
            (now,),
        )
        result = {"examined": len(open_rows), "closed": 0, "pending_observation": 0}
        for row in open_rows:
            market = self.conn.execute(
                """
                SELECT ts, price FROM observation_snapshots
                WHERE symbol=? AND ts>=? AND ts<=? AND price IS NOT NULL
                ORDER BY ts ASC LIMIT 1
                """,
                (
                    row.get("symbol"),
                    float(row.get("target_ts") or 0.0),
                    float(row.get("target_ts") or 0.0) + float(tolerance_sec),
                ),
            ).fetchone()
            entry_price = _number(row.get("entry_price"))
            if not market or entry_price <= 0:
                result["pending_observation"] += 1
                continue
            settled_ts, exit_price = float(market[0]), float(market[1])
            gross_bps = ((exit_price - entry_price) / entry_price) * 10_000.0
            direction = str(row.get("direction") or "UP").upper()
            directional_bps = -gross_bps if direction == "DOWN" else gross_bps
            net_bps = directional_bps - _number(row.get("expected_cost_bps"))
            positive = net_bps > 0
            status = "CLOSED_WIN" if positive else "CLOSED_LOSS"
            payload = self._payload_dict(row.get("payload"))
            payload.update({
                "direct_rapid_settlement": {
                    "settled_ts": settled_ts,
                    "exit_price": exit_price,
                    "gross_return_bps": gross_bps,
                    "directional_return_bps": directional_bps,
                    "net_return_bps": net_bps,
                    "positive_net": positive,
                    "settlement_source": "public_observation_snapshot",
                }
            })
            with self._lock:
                self.conn.execute(
                    """
                    UPDATE rapid_paper_tape_trades
                    SET status=?, settled_ts=?, updated_ts=?, exit_price=?, gross_return_bps=?,
                        directional_return_bps=?, net_return_bps=?, positive_net=?, payload=?
                    WHERE trade_id=?
                    """,
                    (
                        status,
                        settled_ts,
                        now,
                        exit_price,
                        gross_bps,
                        directional_bps,
                        net_bps,
                        int(positive),
                        json.dumps(payload, sort_keys=True, default=str),
                        row.get("trade_id"),
                    ),
                )
                self.conn.commit()
            if hasattr(self.data_store, "store_paper_trade"):
                self.data_store.store_paper_trade({
                    "ts": settled_ts,
                    "symbol": row.get("symbol"),
                    "side": "EXIT",
                    "qty": self.notional_usd / max(1e-9, entry_price),
                    "price": exit_price,
                    "notional_usd": self.notional_usd,
                    "reason": f"RAPID_TAPE_DIRECT:{row.get('source_forecast_id')}:{status}",
                    "net_margin_pct": net_bps / 10_000.0,
                    "status": status,
                })
            enriched = dict(row)
            enriched["exit_price"] = exit_price
            self._persist_negative_crystal(enriched, net_bps=net_bps, settled_ts=settled_ts)
            result["closed"] += 1
        return result

    def expire_stale_open_trades(self, *, tolerance_sec: float = 900.0) -> dict[str, Any]:
        """Expire paper trades whose target window passed without settlement data."""
        now = float(self.now_fn())
        rows = self._fetchall(
            """
            SELECT * FROM rapid_paper_tape_trades
            WHERE status='OPEN' AND target_ts<?
            ORDER BY target_ts ASC LIMIT 250
            """,
            (now - float(tolerance_sec),),
        )
        expired = 0
        for row in rows:
            payload = self._payload_dict(row.get("payload"))
            payload.update({
                "expiry": {
                    "expired_ts": now,
                    "target_ts": row.get("target_ts"),
                    "reason": "no_public_observation_after_target_within_tolerance",
                    "tolerance_sec": float(tolerance_sec),
                }
            })
            with self._lock:
                cursor = self.conn.execute(
                    """
                    UPDATE rapid_paper_tape_trades
                    SET status='EXPIRED_NO_OBSERVATION', updated_ts=?, failure_reason=?, payload=?
                    WHERE trade_id=? AND status='OPEN'
                    """,
                    (
                        now,
                        "no_public_observation_after_target_within_tolerance",
                        json.dumps(payload, sort_keys=True, default=str),
                        row.get("trade_id"),
                    ),
                )
                if cursor.rowcount:
                    expired += 1
                self.conn.commit()
        return {"examined": len(rows), "expired": expired}

    def scorecard(self, *, limit: int = 50) -> dict[str, Any]:
        c = self.conn.cursor()
        counts = {
            str(row[0]): int(row[1])
            for row in c.execute("SELECT status, COUNT(*) FROM rapid_paper_tape_trades GROUP BY status").fetchall()
        }
        pnl = c.execute(
            """
            SELECT COUNT(*), SUM(net_return_bps), AVG(net_return_bps),
                   MIN(net_return_bps), MAX(net_return_bps)
            FROM rapid_paper_tape_trades
            WHERE status IN ('CLOSED_WIN','CLOSED_LOSS')
            """
        ).fetchone()
        by_model = self._fetchall(
            """
            SELECT model_id, COUNT(*) AS trades, SUM(CASE WHEN net_return_bps>0 THEN 1 ELSE 0 END) AS wins,
                   SUM(net_return_bps) AS net_bps
            FROM rapid_paper_tape_trades
            WHERE status IN ('CLOSED_WIN','CLOSED_LOSS')
            GROUP BY model_id
            ORDER BY net_bps DESC
            LIMIT 12
            """
        )
        recent = self._fetchall(
            "SELECT * FROM rapid_paper_tape_trades ORDER BY updated_ts DESC LIMIT ?",
            (int(limit),),
        )
        closed = int((pnl or [0])[0] or 0)
        wins = int(counts.get("CLOSED_WIN", 0))
        return {
            "schema": "rapid_paper_tape_scorecard_v1",
            "authority": "paper_only_no_private_exchange",
            "open": counts.get("OPEN", 0),
            "vetoed": counts.get("VETOED", 0),
            "closed": closed,
            "wins": wins,
            "losses": int(counts.get("CLOSED_LOSS", 0)),
            "win_rate": (wins / closed) if closed else 0.0,
            "total_net_bps": float((pnl or [0, 0])[1] or 0.0),
            "mean_net_bps": float((pnl or [0, 0, 0])[2] or 0.0),
            "worst_net_bps": float((pnl or [0, 0, 0, 0])[3] or 0.0),
            "best_net_bps": float((pnl or [0, 0, 0, 0, 0])[4] or 0.0),
            "by_model": by_model,
            "recent": recent,
        }

    def backfill_negative_crystals(self, *, limit: int = 500) -> dict[str, Any]:
        rows = self._fetchall(
            """
            SELECT * FROM rapid_paper_tape_trades
            WHERE status='CLOSED_LOSS' AND COALESCE(net_return_bps, 0)<0
            ORDER BY settled_ts DESC LIMIT ?
            """,
            (int(limit),),
        )
        before = 0
        try:
            before = int(
                self.conn.execute(
                    "SELECT COUNT(*) FROM crystal_registry WHERE crystal_family='negative_capability' AND phase_scope=2"
                ).fetchone()[0]
                or 0
            )
        except Exception:
            before = 0
        for row in rows:
            self._persist_negative_crystal(
                row,
                net_bps=_number(row.get("net_return_bps")),
                settled_ts=_number(row.get("settled_ts"), self.now_fn()),
            )
        after = before
        try:
            after = int(
                self.conn.execute(
                    "SELECT COUNT(*) FROM crystal_registry WHERE crystal_family='negative_capability' AND phase_scope=2"
                ).fetchone()[0]
                or 0
            )
        except Exception:
            after = before
        return {"examined": len(rows), "created_or_updated": max(0, after - before), "phase_scope": 2}

    def run_cycle(
        self,
        *,
        hypothesis_swarm: Any | None = None,
        settlement_tolerance_sec: float = 600.0,
        open_limit: int = 25,
    ) -> dict[str, Any]:
        phase2 = hypothesis_swarm.run_once() if hypothesis_swarm is not None else None
        settlement = self.data_store.settle_mature_hypothesis_forecasts(
            tolerance_sec=float(settlement_tolerance_sec)
        )
        closed = self.close_settled()
        direct_closed = self.settle_due_open_trades(tolerance_sec=float(settlement_tolerance_sec))
        expired = self.expire_stale_open_trades(tolerance_sec=float(settlement_tolerance_sec))
        backfilled = self.backfill_negative_crystals()
        opened = self.open_from_recent_forecasts(limit=open_limit)
        return {
            "phase": "rapid_paper_tape",
            "phase2": phase2,
            "settlement": settlement,
            "closed": closed,
            "direct_closed": direct_closed,
            "expired": expired,
            "negative_crystals": backfilled,
            "opened": opened,
            "scorecard": self.scorecard(limit=20),
        }
