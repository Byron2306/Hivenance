from __future__ import annotations

import hashlib
import json
import math
import os
import time
import uuid
from dataclasses import asdict, replace
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any, Callable, Mapping, Optional

from .canary_models import (
    CanaryApproval,
    CanaryCapabilityReceipt,
    CanaryIncident,
    CanaryIntent,
    CanaryOrder,
    CanaryPosition,
)
from .canary_store import CanaryStore
from .shadow_flight import canonical_hash, frozen_config_hash


PHASE6_ACKNOWLEDGEMENT = "I AUTHORIZE ONE TINY LIVE KRAKEN CANARY"
PHASE6_CLIENT_PREFIX = "hv6"
PHASE6_CONFIG_KEYS = (
    "exchange",
    "phase6_canary_enabled",
    "phase6_live_submission_enabled",
    "phase6_rapid_paper_canary_enabled",
    "phase6_allowed_directions",
    "phase6_rapid_dynamic_symbols_enabled",
    "phase6_rapid_min_health_score",
    "phase6_rapid_max_open_canaries",
    "phase6_rapid_block_negative_canary_memory_enabled",
    "phase6_rapid_negative_memory_min_samples",
    "phase6_rapid_min_remaining_horizon_sec",
    "phase6_rapid_tape_slice_edge_enabled",
    "phase6_rapid_tape_slice_min_samples",
    "phase6_rapid_tape_slice_min_win_rate",
    "phase6_rapid_tape_slice_min_mean_net_bps",
    "phase6_rapid_tape_slice_min_median_net_bps",
    "phase6_rapid_allow_exploratory_slices",
    "phase6_rapid_exploratory_max_cost_bps",
    "phase6_rapid_allowed_window_sec",
    "phase6_rapid_interval_transition_enabled",
    "phase6_rapid_interval_transition_pairs",
    "phase6_rapid_max_cost_bps",
    "phase6_rapid_min_expected_net_bps",
    "phase6_rapid_min_expected_net_to_cost_ratio",
    "phase6_rapid_lane_min_expected_net_to_cost_ratio",
    "phase6_rapid_micro_reversion_rank_bonus",
    "phase6_rapid_allowed_execution_policies",
    "phase6_rapid_min_expected_fill_ratio",
    "phase6_rapid_counterfactual_promotion_enabled",
    "phase6_rapid_counterfactual_min_samples",
    "phase6_rapid_counterfactual_min_win_rate",
    "phase6_rapid_counterfactual_min_median_net_bps",
    "phase6_rapid_candidate_max_age_sec",
    "phase6_rapid_settlement_tolerance_sec",
    "phase6_rapid_expire_after_sec",
    "phase6_allowed_symbols",
    "phase6_max_notional_usd",
    "phase6_max_entry_orders_per_approval",
    "phase6_approval_lease_sec",
    "phase6_candidate_max_age_sec",
    "phase6_market_data_max_age_sec",
    "phase6_min_data_quality",
    "phase6_max_spread_bps",
    "phase6_max_slippage_bps",
    "phase6_stop_distance_bps",
    "phase6_target_distance_bps",
    "phase6_deadman_timeout_sec",
    "phase6_require_isolated_account",
    "phase6_max_open_orders",
    "phase6_max_open_positions",
    "phase6_daily_loss_halt_usd",
    "phase6_min_phase7_round_trips",
)


def canary_config_payload(cfg: Any) -> dict[str, Any]:
    return {key: getattr(cfg, key, None) for key in PHASE6_CONFIG_KEYS}


def canary_config_hash(cfg: Any) -> str:
    return canonical_hash(canary_config_payload(cfg))


def _allowed_symbols(cfg: Any) -> tuple[str, ...]:
    raw = getattr(cfg, "phase6_allowed_symbols", None) or [getattr(cfg, "symbol", "ETH/USD")]
    symbols = tuple(sorted({str(item).strip() for item in raw if str(item).strip()}))
    if not symbols:
        raise ValueError("Phase-6 requires at least one allowlisted symbol")
    return symbols


def _allowed_directions(cfg: Any) -> tuple[str, ...]:
    raw = getattr(cfg, "phase6_allowed_directions", None) or ["UP"]
    directions = tuple(sorted({str(item).strip().upper() for item in raw if str(item).strip()}))
    return directions or ("UP",)


def _rapid_paper_canary_enabled(cfg: Any) -> bool:
    return bool(getattr(cfg, "phase6_rapid_paper_canary_enabled", False)) and not bool(
        getattr(cfg, "phase6_live_submission_enabled", False)
    )


def _freeze_phase6_metadata(freeze: Mapping[str, Any]) -> dict[str, str]:
    candidate_key = str(freeze.get("candidate_key") or "")
    parsed: dict[str, str] = {}
    for part in candidate_key.split("::"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        parsed[key.strip()] = value.strip()
    symbol = str(freeze.get("symbol") or parsed.get("symbol") or "").strip()
    direction = str(freeze.get("direction") or parsed.get("direction") or "").strip().upper()
    return {"symbol": symbol, "direction": direction}


def phase6_spot_freeze_compatibility(freeze: Mapping[str, Any], cfg: Any) -> dict[str, Any]:
    """Cheap compatibility check for the tiny Kraken spot canary.

    This does not run the expensive Phase-5 evidence scorecard. It answers one
    narrow question: can the active freeze ever produce a Phase-6 entry under
    the local canary authority?
    """
    reasons: list[str] = []
    allowed_symbols: tuple[str, ...] = ()
    try:
        allowed_symbols = _allowed_symbols(cfg)
    except Exception as exc:
        reasons.append(f"phase6_allowed_symbols_invalid:{exc}")
    if not freeze:
        reasons.append("no_active_phase5_freeze")
        metadata = {"symbol": "", "direction": ""}
    else:
        metadata = _freeze_phase6_metadata(freeze)
        model_id = str(freeze.get("model_id") or "")
        candidate_key = str(freeze.get("candidate_key") or "")
        small_window_freeze = model_id == "small_window_trend_comparison_v1" or candidate_key.startswith("small_window_trend_comparison_v1|")
        rapid_paper = small_window_freeze and _rapid_paper_canary_enabled(cfg)
        dynamic_rapid_symbols = rapid_paper and bool(getattr(cfg, "phase6_rapid_dynamic_symbols_enabled", True))
        allowed_directions = _allowed_directions(cfg) if rapid_paper else ("UP",)
        if not metadata["symbol"]:
            reasons.append("phase5_freeze_symbol_unavailable")
        elif not dynamic_rapid_symbols and allowed_symbols and metadata["symbol"] not in set(allowed_symbols):
            reasons.append("phase5_freeze_symbol_not_phase6_allowlisted")
        if not metadata["direction"]:
            reasons.append("phase5_freeze_direction_unavailable")
        elif metadata["direction"] not in set(allowed_directions):
            if rapid_paper:
                reasons.append("small_window_direction_not_phase6_paper_canary_allowlisted")
            elif small_window_freeze:
                reasons.append("small_window_down_slice_is_shadow_only_not_spot_canary")
            else:
                reasons.append("phase5_freeze_direction_not_spot_long_canary")
    freeze_model_id = str((freeze or {}).get("model_id") or "")
    freeze_candidate_key = str((freeze or {}).get("candidate_key") or "")
    rapid_authority = _rapid_paper_canary_enabled(cfg) and (
        freeze_model_id == "small_window_trend_comparison_v1"
        or freeze_candidate_key.startswith("small_window_trend_comparison_v1|")
    )
    return {
        "phase": 6,
        "canary_compatible": not reasons,
        "reasons": reasons,
        "freeze_id": str((freeze or {}).get("freeze_id") or ""),
        "candidate_key": str((freeze or {}).get("candidate_key") or ""),
        "model_id": str((freeze or {}).get("model_id") or ""),
        "symbol": metadata["symbol"],
        "direction": metadata["direction"],
        "required_direction": "UP_OR_DOWN" if rapid_authority else "UP",
        "allowed_directions": list(_allowed_directions(cfg) if rapid_authority else ("UP",)),
        "allowed_symbols": list(allowed_symbols),
        "authority": "paper_small_window_directional_canary" if rapid_authority else "kraken_spot_long_only_tiny_canary",
        "rapid_paper_canary": bool(rapid_authority),
    }


def build_canary_approval(
    data_store: Any,
    cfg: Any,
    *,
    approved_by: str,
    acknowledgement: str,
    approved_ts: Optional[float] = None,
) -> CanaryApproval:
    approved_by = str(approved_by or "").strip()
    if len(approved_by) < 2:
        raise ValueError("approved_by must identify the human operator")
    if acknowledgement != PHASE6_ACKNOWLEDGEMENT:
        raise ValueError("the exact Phase-6 live-risk acknowledgement is required")
    now = float(approved_ts or time.time())
    freeze = data_store.get_phase5_active_freeze()
    if not freeze:
        raise ValueError("no active Phase-5 frozen champion exists")
    compatibility = phase6_spot_freeze_compatibility(freeze, cfg)
    if not compatibility.get("canary_compatible"):
        raise ValueError(
            "Phase-5 freeze is not Phase-6 canary-compatible: "
            + ",".join(compatibility.get("reasons") or [])
        )
    readiness = data_store.get_phase5_readiness(
        min_distinct_days=int(getattr(cfg, "phase5_readiness_min_distinct_days", 30) or 30),
        min_settled=int(getattr(cfg, "phase5_readiness_min_settled", 100) or 100),
        max_cost_mae_bps=float(getattr(cfg, "phase5_readiness_max_cost_mae_bps", 20.0) or 20.0),
        min_fill_ratio=float(getattr(cfg, "phase5_readiness_min_fill_ratio", 0.50) or 0.50),
        require_positive_mean=bool(getattr(cfg, "phase5_readiness_require_positive_mean", True)),
        current_config_hash=frozen_config_hash(cfg),
        distinct_bucket_hours=int(getattr(cfg, "phase5_readiness_distinct_snapshot_bucket_hours", 24) or 24),
    )
    if not readiness.get("ready_for_phase6_review"):
        raise ValueError("Phase-5 evidence is not ready for Phase-6 human review")
    if str(freeze.get("config_hash") or "") != frozen_config_hash(cfg):
        raise ValueError("Phase-5 frozen parameters have drifted")
    lease = max(60, min(3600, int(getattr(cfg, "phase6_approval_lease_sec", 900) or 900)))
    symbols = _allowed_symbols(cfg)
    approval_id = canonical_hash({
        "freeze_id": freeze.get("freeze_id"),
        "approved_by": approved_by,
        "approved_ts": now,
        "expires_ts": now + lease,
        "symbols": symbols,
        "config_hash": canary_config_hash(cfg),
    })
    return CanaryApproval(
        approval_id=approval_id,
        freeze_id=str(freeze.get("freeze_id") or ""),
        phase4_run_id=str(freeze.get("phase4_run_id") or ""),
        candidate_key=str(freeze.get("candidate_key") or ""),
        model_id=str(freeze.get("model_id") or ""),
        order_policy=str(freeze.get("order_policy") or ""),
        approved_by=approved_by,
        approved_ts=now,
        expires_ts=now + lease,
        allowed_symbols=symbols,
        max_notional_usd=max(0.01, float(getattr(cfg, "phase6_max_notional_usd", 5.0) or 5.0)),
        max_entry_orders=max(1, int(getattr(cfg, "phase6_max_entry_orders_per_approval", 1) or 1)),
        config_hash=canary_config_hash(cfg),
        acknowledgement_hash=hashlib.sha256(acknowledgement.encode("utf-8")).hexdigest(),
        live_submission_authorized=True,
    )


class TinyLiveCanary:
    """Isolated Phase-6 canary authority.

    It never uses the legacy ExecutionAgent. Entries require a short-lived human
    approval, an exact environment interlock and a validate-only exchange probe.
    Risk-reducing exits may continue after the entry lease expires.
    """

    def __init__(
        self,
        cfg: Any,
        data_store: Any,
        exchange_client: Optional[Any],
        *,
        now_fn: Callable[[], float] = time.time,
        live_interlock: Optional[bool] = None,
    ) -> None:
        self.cfg = cfg
        self.data_store = data_store
        self.store = CanaryStore(data_store)
        self.exchange = exchange_client
        self.now_fn = now_fn
        self.enabled = bool(getattr(cfg, "phase6_canary_enabled", True))
        env_live = os.environ.get("HIVENANCE_PHASE6_LIVE_SUBMISSION", "").strip().upper() == "YES"
        self.live_interlock = env_live if live_interlock is None else bool(live_interlock)
        self.live_config_enabled = bool(getattr(cfg, "phase6_live_submission_enabled", False))
        self.allowed_symbols = _allowed_symbols(cfg)
        self.max_notional = max(0.01, float(getattr(cfg, "phase6_max_notional_usd", 5.0) or 5.0))
        self.max_spread_bps = max(0.1, float(getattr(cfg, "phase6_max_spread_bps", 30.0) or 30.0))
        self.max_slippage_bps = max(0.1, float(getattr(cfg, "phase6_max_slippage_bps", 40.0) or 40.0))
        self.min_quality = max(0.0, min(1.0, float(getattr(cfg, "phase6_min_data_quality", 0.99) or 0.99)))
        self.deadman_timeout = max(15, int(getattr(cfg, "phase6_deadman_timeout_sec", 60) or 60))
        self.current_hash = canary_config_hash(cfg)
        self.rapid_paper_canary_enabled = _rapid_paper_canary_enabled(cfg)

    @staticmethod
    def _num(value: Any, default: float = 0.0) -> float:
        try:
            result = float(value)
            return result if math.isfinite(result) else default
        except (TypeError, ValueError):
            return default

    def _rapid_interval_transition(self, candidate: Mapping[str, Any], window_sec: int) -> dict[str, Any]:
        if not bool(getattr(self.cfg, "phase6_rapid_interval_transition_enabled", False)):
            return {"accepted": False, "pair": None, "supported_windows": [int(window_sec or 0)]}
        raw_pairs = getattr(self.cfg, "phase6_rapid_interval_transition_pairs", None) or []
        pairs: list[tuple[int, int]] = []
        for item in raw_pairs:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                pairs.append((int(self._num(item[0])), int(self._num(item[1]))))
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

    def _incident(self, category: str, message: str, *, severity: str = "CRITICAL",
                  symbol: Optional[str] = None, client_order_id: Optional[str] = None,
                  payload: Optional[Mapping[str, Any]] = None) -> CanaryIncident:
        now = self.now_fn()
        incident = CanaryIncident(
            incident_id=canonical_hash({"ts": now, "category": category, "message": message,
                                        "symbol": symbol, "client_order_id": client_order_id}),
            ts=now,
            severity=severity,
            category=category,
            message=message,
            symbol=symbol,
            client_order_id=client_order_id,
            payload=dict(payload or {}),
        )
        self.store.persist_incident(incident.to_dict())
        self.store.set_state("HALTED", f"{category}:{message}", payload=incident.to_dict())
        return incident

    def _latest_observation(self, symbol: str) -> dict[str, Any]:
        rows = self.data_store.get_observation_snapshots(symbol=symbol, limit=1)
        return dict(rows[0]) if rows else {}

    def _rapid_paper_tape_candidate(self, freeze: Mapping[str, Any]) -> dict[str, Any]:
        if not getattr(self.data_store, "conn", None):
            return {}
        metadata = _freeze_phase6_metadata(freeze)
        freeze_symbol = metadata.get("symbol") or ""
        freeze_direction = metadata.get("direction") or ""
        dynamic_symbols = bool(getattr(self.cfg, "phase6_rapid_dynamic_symbols_enabled", True))
        allowed_directions = set(_allowed_directions(self.cfg))
        allowed_symbols = set(_allowed_symbols(self.cfg)) if not dynamic_symbols else set()
        excluded_bases = {
            str(item).strip().upper()
            for item in (getattr(self.cfg, "phase2_small_window_excluded_bases", []) or [])
            if str(item).strip()
        }
        min_health_score = max(
            0.0,
            float(
                getattr(
                    self.cfg,
                    "phase6_rapid_min_health_score",
                    getattr(self.cfg, "phase2_small_window_healthy_min_score", 0.0),
                )
                or 0.0
            ),
        )
        block_negative_memory = bool(getattr(self.cfg, "phase6_rapid_block_negative_canary_memory_enabled", True))
        negative_memory_min_samples = max(
            1, int(getattr(self.cfg, "phase6_rapid_negative_memory_min_samples", 1) or 1)
        )
        min_remaining_horizon = max(
            0.0, float(getattr(self.cfg, "phase6_rapid_min_remaining_horizon_sec", 15.0) or 15.0)
        )
        tape_slice_edge_enabled = bool(getattr(self.cfg, "phase6_rapid_tape_slice_edge_enabled", True))
        tape_slice_min_samples = max(1, int(getattr(self.cfg, "phase6_rapid_tape_slice_min_samples", 2) or 2))
        tape_slice_min_win_rate = max(
            0.0, float(getattr(self.cfg, "phase6_rapid_tape_slice_min_win_rate", 0.45) or 0.45)
        )
        tape_slice_min_mean_net = float(getattr(self.cfg, "phase6_rapid_tape_slice_min_mean_net_bps", 0.0) or 0.0)
        allow_exploratory_slices = bool(getattr(self.cfg, "phase6_rapid_allow_exploratory_slices", True))
        exploratory_max_cost_bps = max(
            0.0, float(getattr(self.cfg, "phase6_rapid_exploratory_max_cost_bps", 60.0) or 60.0)
        )
        allowed_window_raw = getattr(self.cfg, "phase6_rapid_allowed_window_sec", None) or []
        allowed_windows = {
            int(float(item))
            for item in allowed_window_raw
            if str(item).strip()
        }
        max_cost_bps = max(0.0, float(getattr(self.cfg, "phase6_rapid_max_cost_bps", 0.0) or 0.0))
        min_expected_net_bps = max(
            0.0, float(getattr(self.cfg, "phase6_rapid_min_expected_net_bps", 0.0) or 0.0)
        )
        min_net_to_cost = max(
            0.0, float(getattr(self.cfg, "phase6_rapid_min_expected_net_to_cost_ratio", 0.0) or 0.0)
        )
        lane_min_ratio_raw = getattr(self.cfg, "phase6_rapid_lane_min_expected_net_to_cost_ratio", None) or {}
        lane_min_ratio = dict(lane_min_ratio_raw) if isinstance(lane_min_ratio_raw, Mapping) else {}
        micro_reversion_rank_bonus = float(
            getattr(self.cfg, "phase6_rapid_micro_reversion_rank_bonus", 0.0) or 0.0
        )
        allowed_route_policies = {
            str(item).strip().lower()
            for item in (getattr(self.cfg, "phase6_rapid_allowed_execution_policies", None) or [])
            if str(item).strip()
        }
        min_expected_fill_ratio = max(
            0.0,
            min(
                1.0,
                float(getattr(self.cfg, "phase6_rapid_min_expected_fill_ratio", 0.0) or 0.0),
            ),
        )
        now = self.now_fn()
        max_age = max(1, int(getattr(self.cfg, "phase6_rapid_candidate_max_age_sec", 180) or 180))
        with self.data_store._lock:
            intent_columns = {
                str(row[1])
                for row in self.data_store.conn.execute("PRAGMA table_info(phase6_canary_intents)").fetchall()
            }
            consumed_trade_ids: set[str] = set()
            consumed_filter = ""
            if "source_trade_id" in intent_columns:
                consumed_filter = """
                  AND trade_id NOT IN (
                      SELECT COALESCE(source_trade_id, '')
                      FROM phase6_canary_intents
                  )
                """
            else:
                for payload_row in self.data_store.conn.execute(
                    "SELECT payload FROM phase6_canary_intents"
                ).fetchall():
                    try:
                        payload = json.loads((payload_row[0] if payload_row else "") or "{}")
                    except Exception:
                        payload = {}
                    if not isinstance(payload, dict):
                        continue
                    nested_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
                    nested_trade = nested_payload.get("rapid_paper_trade") if isinstance(nested_payload, dict) else {}
                    direct_trade = payload.get("rapid_paper_trade") if isinstance(payload.get("rapid_paper_trade"), dict) else {}
                    trade_id = (
                        payload.get("source_trade_id")
                        or direct_trade.get("trade_id")
                        or (nested_trade.get("trade_id") if isinstance(nested_trade, dict) else None)
                    )
                    if trade_id:
                        consumed_trade_ids.add(str(trade_id))
            cursor = self.data_store.conn.execute(
                f"""
                SELECT * FROM rapid_paper_tape_trades
                WHERE model_id='small_window_trend_comparison_v1'
                  AND entry_ts>=?
                  AND target_ts>=?
                  AND status='OPEN'
                  {consumed_filter}
                ORDER BY entry_ts DESC
                LIMIT 80
                """,
                (now - max_age, now + min_remaining_horizon),
            )
            rows = cursor.fetchall()
            columns = [item[0] for item in cursor.description]
        best: dict[str, Any] = {}
        best_rank = (-1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0, -1.0)
        for row in rows:
            record = dict(zip(columns, row))
            symbol = str(record.get("symbol") or "")
            direction = str(record.get("direction") or "").upper()
            base = symbol.split("/", 1)[0].upper()
            if not symbol or not direction:
                continue
            if str(record.get("trade_id") or "") in consumed_trade_ids:
                continue
            if excluded_bases and base in excluded_bases:
                continue
            if allowed_directions and direction not in allowed_directions:
                continue
            if not dynamic_symbols:
                if freeze_symbol and symbol != freeze_symbol:
                    continue
                if freeze_direction and direction != freeze_direction:
                    continue
                if allowed_symbols and symbol not in allowed_symbols:
                    continue
            try:
                payload = json.loads(record.get("payload") or "{}")
            except Exception:
                payload = {}
            if isinstance(payload, dict):
                record["payload_dict"] = payload
            tape_candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
            health_score = self._num(tape_candidate.get("health_score"))
            if min_health_score and health_score < min_health_score:
                continue
            window_sec = int(self._num(tape_candidate.get("window_sec")) or 0)
            interval_transition = self._rapid_interval_transition(tape_candidate, window_sec)
            if allowed_windows and window_sec not in allowed_windows and not interval_transition.get("accepted"):
                continue
            expected_cost = self._num(record.get("expected_cost_bps"))
            expected_net = self._num(record.get("expected_net_bps"))
            if max_cost_bps and expected_cost > max_cost_bps:
                continue
            if min_expected_net_bps and expected_net < min_expected_net_bps:
                continue
            signal_lane = str(tape_candidate.get("signal_lane") or "continuation")
            execution_route = tape_candidate.get("execution_route") if isinstance(tape_candidate.get("execution_route"), dict) else {}
            route_policy = str(
                tape_candidate.get("route_policy")
                or execution_route.get("selected_policy")
                or "unknown"
            ).lower()
            expected_fill_ratio = self._num(
                tape_candidate.get("expected_fill_ratio"),
                self._num(execution_route.get("expected_fill_ratio"), 1.0),
            )
            if allowed_route_policies and route_policy not in allowed_route_policies:
                continue
            if min_expected_fill_ratio and expected_fill_ratio < min_expected_fill_ratio:
                continue
            if execution_route and not bool(execution_route.get("tradable", True)):
                continue
            lane_ratio = self._num(lane_min_ratio.get(signal_lane), min_net_to_cost)
            if lane_ratio and expected_cost > 0.0 and (expected_net / expected_cost) < lane_ratio:
                continue
            canary_memory = self._rapid_canary_memory_summary(symbol, direction, window_sec, signal_lane=signal_lane)
            memory_samples = int(canary_memory.get("samples") or 0)
            mean_net = self._num(canary_memory.get("mean_net_bps"))
            win_rate = self._num(canary_memory.get("win_rate"))
            latest_net = self._num(canary_memory.get("latest_net_bps"))
            if (
                block_negative_memory
                and memory_samples >= negative_memory_min_samples
                and mean_net < 0.0
            ):
                continue
            tape_slice = self._rapid_tape_slice_summary(symbol, direction, window_sec, signal_lane=signal_lane)
            tape_samples = int(tape_slice.get("samples") or 0)
            tape_win_rate = self._num(tape_slice.get("win_rate"))
            tape_mean_net = self._num(tape_slice.get("mean_net_bps"))
            tape_median_net = self._num(tape_slice.get("median_net_bps"))
            tape_min_median_net = float(
                getattr(self.cfg, "phase6_rapid_tape_slice_min_median_net_bps", tape_slice_min_mean_net)
                or tape_slice_min_mean_net
            )
            counterfactual_edge = self._rapid_counterfactual_edge(
                symbol=symbol,
                direction=direction,
                window_sec=window_sec,
                signal_lane=signal_lane,
                interval_pair=interval_transition.get("pair"),
                route_policy=route_policy,
            )
            if counterfactual_edge.get("accepted"):
                ready_ts = self._num(record.get("entry_ts")) + self._num(counterfactual_edge.get("entry_delay_sec"))
                if now < ready_ts:
                    continue
            if tape_slice_edge_enabled:
                if not counterfactual_edge.get("accepted") and tape_samples >= tape_slice_min_samples and (
                    tape_win_rate < tape_slice_min_win_rate
                    or tape_mean_net < tape_slice_min_mean_net
                    or tape_median_net < tape_min_median_net
                ):
                    continue
                if not counterfactual_edge.get("accepted") and tape_samples < tape_slice_min_samples:
                    if not allow_exploratory_slices:
                        continue
                    if self._num(record.get("expected_cost_bps")) > exploratory_max_cost_bps:
                        continue
            memory_adjustment = 0.0
            if memory_samples:
                if mean_net > 0.0 and win_rate >= 0.5:
                    memory_adjustment += min(20.0, 6.0 + mean_net * 0.05)
                elif mean_net < 0.0:
                    memory_adjustment -= min(25.0, 6.0 + abs(mean_net) * 0.08)
                if latest_net > 0.0:
                    memory_adjustment += min(8.0, latest_net * 0.04)
                elif latest_net < 0.0:
                    memory_adjustment -= min(10.0, abs(latest_net) * 0.04)
            record["canary_memory"] = canary_memory
            record["tape_slice"] = tape_slice
            record["interval_transition"] = interval_transition
            record["counterfactual_edge"] = counterfactual_edge
            record["execution_route"] = execution_route
            record["route_policy"] = route_policy
            record["expected_fill_ratio"] = expected_fill_ratio
            lane_adjustment = micro_reversion_rank_bonus if signal_lane == "micro_reversion" else 0.0
            record["phase6_memory_adjusted_health_score"] = health_score + memory_adjustment + lane_adjustment
            rank = (
                health_score + memory_adjustment + lane_adjustment,
                expected_fill_ratio,
                self._num(counterfactual_edge.get("win_rate")) if counterfactual_edge.get("accepted") else 0.0,
                self._num(counterfactual_edge.get("median_net_bps")) if counterfactual_edge.get("accepted") else 0.0,
                tape_win_rate if tape_samples >= tape_slice_min_samples else 0.0,
                tape_median_net if tape_samples >= tape_slice_min_samples else 0.0,
                tape_mean_net if tape_samples >= tape_slice_min_samples else 0.0,
                self._num(record.get("entry_ts")),
                self._num(record.get("expected_net_bps")),
            )
            if rank > best_rank:
                best_rank = rank
                best = record
        return best

    def _settlement_observation(self, symbol: str, target_ts: float) -> dict[str, Any]:
        tolerance = max(1.0, float(getattr(self.cfg, "phase6_rapid_settlement_tolerance_sec", 600.0) or 600.0))
        with self.data_store._lock:
            cursor = self.data_store.conn.execute(
                """
                SELECT * FROM observation_snapshots
                WHERE symbol=? AND ts>=? AND ts<=?
                ORDER BY ts ASC
                LIMIT 1
                """,
                (symbol, float(target_ts), float(target_ts) + tolerance),
            )
            row = cursor.fetchone()
            if not row:
                return {}
            columns = [item[0] for item in cursor.description]
        return dict(zip(columns, row))

    @staticmethod
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

    def _rapid_paper_trade_row(self, trade_id: str) -> dict[str, Any]:
        if not trade_id or not getattr(self.data_store, "conn", None):
            return {}
        lock = getattr(self.data_store, "_lock", None)
        try:
            if lock:
                lock.acquire()
            cursor = self.data_store.conn.execute(
                "SELECT * FROM rapid_paper_tape_trades WHERE trade_id=? LIMIT 1",
                (str(trade_id),),
            )
            row = cursor.fetchone()
            if not row:
                return {}
            columns = [item[0] for item in cursor.description]
        except Exception:
            return {}
        finally:
            if lock:
                lock.release()
        record = dict(zip(columns, row))
        payload = self._json_mapping(record.get("payload"))
        if payload:
            record["payload_dict"] = payload
        return record

    def _rapid_canary_memory_summary(
        self,
        symbol: str,
        direction: str,
        window_sec: int,
        *,
        signal_lane: str = "continuation",
    ) -> dict[str, Any]:
        if not getattr(self.data_store, "conn", None):
            return {"samples": 0}
        legacy_scope_key = f"{str(symbol or '')}|{str(direction or '').upper()}|{int(window_sec or 0)}"
        scope_key = f"{legacy_scope_key}|{str(signal_lane or 'continuation')}"
        limit = max(1, int(getattr(self.cfg, "phase2_small_window_canary_memory_limit", 20) or 20))
        lock = getattr(self.data_store, "_lock", None)
        try:
            if lock:
                lock.acquire()
            rows = self.data_store.conn.execute(
                """
                SELECT payload
                FROM crystal_registry
                WHERE crystal_family='small_window_canary_memory'
                  AND scope_key IN (?, ?)
                ORDER BY updated_ts DESC
                LIMIT ?
                """,
                (scope_key, legacy_scope_key, limit),
            ).fetchall()
        except Exception:
            return {"samples": 0, "error": "crystal_registry_unavailable"}
        finally:
            if lock:
                lock.release()
        nets: list[float] = []
        wins = 0
        latest_ts = 0.0
        latest_net = None
        for raw in rows:
            payload = self._json_mapping(raw[0] if raw else "")
            if isinstance(payload.get("payload"), dict):
                payload = dict(payload["payload"])
            payload_lane = str(payload.get("signal_lane") or signal_lane or "continuation")
            if payload_lane != str(signal_lane or "continuation"):
                continue
            net = self._num(payload.get("net_return_bps"))
            nets.append(net)
            wins += 1 if bool(payload.get("positive_net")) or net > 0 else 0
            settled_ts = self._num(payload.get("settled_ts"))
            if settled_ts >= latest_ts:
                latest_ts = settled_ts
                latest_net = net
        samples = len(nets)
        return {
            "schema": "small_window_canary_memory_summary_v1",
            "scope_key": scope_key,
            "samples": samples,
            "wins": wins,
            "losses": max(0, samples - wins),
            "win_rate": (wins / samples) if samples else None,
            "mean_net_bps": (sum(nets) / samples) if samples else None,
            "latest_net_bps": latest_net,
            "latest_settled_ts": latest_ts or None,
        }

    def _rapid_tape_slice_summary(
        self,
        symbol: str,
        direction: str,
        window_sec: int,
        *,
        signal_lane: str = "continuation",
    ) -> dict[str, Any]:
        if not getattr(self.data_store, "conn", None):
            return {"samples": 0}
        history_limit = max(50, int(getattr(self.cfg, "phase6_rapid_tape_slice_history_limit", 500) or 500))
        lock = getattr(self.data_store, "_lock", None)
        try:
            if lock:
                lock.acquire()
            rows = self.data_store.conn.execute(
                """
                SELECT direction, net_return_bps, positive_net, payload
                FROM rapid_paper_tape_trades
                WHERE model_id='small_window_trend_comparison_v1'
                  AND symbol=?
                  AND direction=?
                  AND status IN ('CLOSED_WIN','CLOSED_LOSS')
                ORDER BY updated_ts DESC
                LIMIT ?
                """,
                (str(symbol or ""), str(direction or "").upper(), history_limit),
            ).fetchall()
        except Exception:
            return {"samples": 0, "error": "rapid_tape_unavailable"}
        finally:
            if lock:
                lock.release()
        nets: list[float] = []
        wins = 0
        lane = str(signal_lane or "continuation")
        for _direction, net_value, positive, raw_payload in rows:
            payload = self._json_mapping(raw_payload)
            candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
            candidate_window = int(self._num(candidate.get("window_sec")) or 0)
            candidate_lane = str(candidate.get("signal_lane") or "continuation")
            if candidate_window != int(window_sec or 0) or candidate_lane != lane:
                continue
            net = self._num(net_value)
            nets.append(net)
            wins += 1 if bool(positive) or net > 0.0 else 0
        samples = len(nets)
        ordered_nets = sorted(nets)
        median_net = None
        if samples:
            mid = samples // 2
            median_net = (
                ordered_nets[mid]
                if samples % 2
                else (ordered_nets[mid - 1] + ordered_nets[mid]) / 2.0
            )
        return {
            "schema": "small_window_tape_slice_summary_v1",
            "scope_key": f"{str(symbol or '')}|{str(direction or '').upper()}|{int(window_sec or 0)}|{lane}",
            "samples": samples,
            "wins": wins,
            "losses": max(0, samples - wins),
            "win_rate": (wins / samples) if samples else None,
            "mean_net_bps": (sum(nets) / samples) if samples else None,
            "median_net_bps": median_net,
            "total_net_bps": sum(nets) if samples else None,
        }

    def _rapid_counterfactual_edge(
        self,
        *,
        symbol: str,
        direction: str,
        window_sec: int,
        signal_lane: str,
        interval_pair: str | None,
        route_policy: str | None = None,
    ) -> dict[str, Any]:
        if not bool(getattr(self.cfg, "phase6_rapid_counterfactual_promotion_enabled", False)):
            return {"accepted": False, "samples": 0}
        if not getattr(self.data_store, "conn", None):
            return {"accepted": False, "samples": 0}
        min_samples = max(1, int(getattr(self.cfg, "phase6_rapid_counterfactual_min_samples", 3) or 3))
        min_win_rate = max(
            0.0, float(getattr(self.cfg, "phase6_rapid_counterfactual_min_win_rate", 0.5) or 0.5)
        )
        min_median = float(getattr(self.cfg, "phase6_rapid_counterfactual_min_median_net_bps", 0.0) or 0.0)
        interval_key = str(interval_pair or int(window_sec or 0))
        lock = getattr(self.data_store, "_lock", None)
        try:
            if lock:
                lock.acquire()
            table_exists = self.data_store.conn.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type='table' AND name='phase6_rapid_gate_audition_counterfactuals'
                LIMIT 1
                """
            ).fetchone()
            if not table_exists:
                return {"accepted": False, "samples": 0, "reason": "counterfactual_table_missing"}
            columns = {
                str(row[1])
                for row in self.data_store.conn.execute(
                    "PRAGMA table_info(phase6_rapid_gate_audition_counterfactuals)"
                ).fetchall()
            }
            route_clause = ""
            params: list[Any] = [
                str(symbol or ""),
                str(direction or "").upper(),
                str(signal_lane or "continuation"),
                interval_key,
            ]
            route_key = str(route_policy or "").lower()
            if route_key and "route_policy" in columns:
                route_clause = " AND COALESCE(route_policy, 'unknown')=?"
                params.append(route_key)
            rows = self.data_store.conn.execute(
                f"""
                SELECT entry_delay_sec, hold_sec, net_return_bps
                FROM phase6_rapid_gate_audition_counterfactuals
                WHERE symbol=?
                  AND direction=?
                  AND signal_lane=?
                  AND COALESCE(interval_pair, CAST(window_sec AS TEXT))=?
                  {route_clause}
                  AND status LIKE 'CLOSED%'
                """,
                tuple(params),
            ).fetchall()
        except Exception as exc:
            return {"accepted": False, "samples": 0, "error": str(exc)}
        finally:
            if lock:
                lock.release()
        buckets: dict[tuple[int, int], list[float]] = {}
        for delay, hold, net in rows:
            buckets.setdefault((int(delay or 0), int(hold or 0)), []).append(self._num(net))
        best: dict[str, Any] = {"accepted": False, "samples": 0}
        best_rank = (-1.0, -1.0, -1.0, -1.0)
        for (delay, hold), nets in buckets.items():
            samples = len(nets)
            if samples < min_samples:
                continue
            wins = sum(1 for value in nets if value > 0.0)
            win_rate = wins / samples
            ordered = sorted(nets)
            mid = samples // 2
            median = ordered[mid] if samples % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0
            mean = sum(nets) / samples
            accepted = win_rate >= min_win_rate and median >= min_median
            rank = (win_rate, median, mean, samples)
            if accepted and rank > best_rank:
                best_rank = rank
                best = {
                    "accepted": True,
                    "interval": interval_key,
                    "route_policy": str(route_policy or "unknown").lower() or None,
                    "entry_delay_sec": delay,
                    "hold_sec": hold,
                    "samples": samples,
                    "wins": wins,
                    "losses": max(0, samples - wins),
                    "win_rate": win_rate,
                    "mean_net_bps": mean,
                    "median_net_bps": median,
                }
        return best

    def _persist_rapid_canary_memory_crystal(
        self,
        receipt: Mapping[str, Any],
        *,
        intent_payload: Mapping[str, Any],
    ) -> None:
        if not hasattr(self.data_store, "persist_crystal_registry_entry"):
            return
        intent = receipt.get("payload", {}).get("intent") if isinstance(receipt.get("payload"), dict) else {}
        if not isinstance(intent, dict):
            intent = {}
        nested_payload = intent_payload.get("payload") if isinstance(intent_payload.get("payload"), dict) else {}
        rapid_trade = intent_payload.get("rapid_paper_trade") if isinstance(intent_payload.get("rapid_paper_trade"), dict) else {}
        if not rapid_trade and isinstance(nested_payload.get("rapid_paper_trade"), dict):
            rapid_trade = nested_payload["rapid_paper_trade"]
        trade_payload = (
            dict(rapid_trade.get("payload_dict"))
            if isinstance(rapid_trade.get("payload_dict"), dict)
            else self._json_mapping(rapid_trade.get("payload"))
        )
        candidate = trade_payload.get("candidate") if isinstance(trade_payload.get("candidate"), dict) else {}
        if not candidate:
            source_trade_id = str(receipt.get("source_trade_id") or intent_payload.get("source_trade_id") or "")
            fallback_trade = self._rapid_paper_trade_row(source_trade_id)
            if fallback_trade:
                rapid_trade = {**fallback_trade, **rapid_trade}
                trade_payload = (
                    dict(fallback_trade.get("payload_dict"))
                    if isinstance(fallback_trade.get("payload_dict"), dict)
                    else self._json_mapping(fallback_trade.get("payload"))
                )
                candidate = trade_payload.get("candidate") if isinstance(trade_payload.get("candidate"), dict) else {}
        symbol = str(receipt.get("symbol") or intent.get("symbol") or rapid_trade.get("symbol") or "")
        side = str(receipt.get("side") or intent.get("side") or "").lower()
        direction = str(rapid_trade.get("direction") or candidate.get("direction") or "").upper()
        if not direction:
            direction = "DOWN" if side in {"paper_sell", "sell"} else "UP"
        window_sec = int(self._num(candidate.get("window_sec")) or 0)
        if not symbol or direction not in {"UP", "DOWN"}:
            return
        signal_lane = str(candidate.get("signal_lane") or "continuation")
        execution_route = candidate.get("execution_route") if isinstance(candidate.get("execution_route"), dict) else {}
        route_policy = str(candidate.get("route_policy") or execution_route.get("selected_policy") or "unknown")
        scope_key = f"{symbol}|{direction}|{window_sec}|{signal_lane}"
        net_bps = self._num(receipt.get("net_return_bps"))
        gross_bps = self._num(receipt.get("gross_return_bps"))
        positive = bool(receipt.get("positive_net")) or net_bps > 0.0
        created_ts = self._num(receipt.get("settled_ts"), self.now_fn())
        payload = {
            "schema": "small_window_canary_memory_crystal_v1",
            "artifact_class": "small_window_canary_memory_crystal",
            "authority": "paper_research_only",
            "source": "phase6_rapid_paper_canary",
            "canary_intent_id": receipt.get("canary_intent_id"),
            "source_trade_id": receipt.get("source_trade_id"),
            "symbol": symbol,
            "direction": direction,
            "window_sec": window_sec,
            "window_label": candidate.get("window_label"),
            "status": receipt.get("status"),
            "positive_net": positive,
            "gross_return_bps": gross_bps,
            "net_return_bps": net_bps,
            "predicted_cost_bps": receipt.get("predicted_cost_bps"),
            "entry_price": receipt.get("entry_price"),
            "exit_price": receipt.get("exit_price"),
            "settled_ts": receipt.get("settled_ts"),
            "health_score_at_entry": candidate.get("health_score"),
            "health_reasons_at_entry": candidate.get("health_reasons"),
            "signal_lane": signal_lane,
            "route_policy": route_policy,
            "execution_route": execution_route,
        }
        crystal_id = canonical_hash({
            "family": "small_window_canary_memory",
            "canary_intent_id": receipt.get("canary_intent_id"),
            "source_trade_id": receipt.get("source_trade_id"),
            "net_return_bps": round(float(net_bps), 8),
        })
        self.data_store.persist_crystal_registry_entry({
            "crystal_id": crystal_id,
            "created_ts": created_ts,
            "updated_ts": float(self.now_fn()),
            "crystal_family": "small_window_canary_memory",
            "artifact_class": "small_window_canary_memory_crystal",
            "authority": "paper_research_only",
            "verification_state": "observed_settlement",
            "phase_scope": 6,
            "scope_key": scope_key,
            "symbol": symbol,
            "venue": intent.get("venue") or rapid_trade.get("venue"),
            "regime_hint": str(candidate.get("regime_hint") or "small_window_canary"),
            "hypothesis": str(rapid_trade.get("hypothesis") or candidate.get("hypothesis") or "recent_delta_volatility"),
            "world_state_id": None,
            "applicability_hash": canonical_hash(scope_key),
            "evidence_strength": abs(float(net_bps)),
            "drift_status": "positive_memory" if positive else "negative_memory",
            "expires_ts": None,
            "payload": payload,
        })

    def backfill_rapid_canary_memory(self, *, limit: int = 500) -> dict[str, Any]:
        if not getattr(self.data_store, "conn", None):
            return {"examined": 0, "persisted": 0}
        if not hasattr(self.data_store, "persist_crystal_registry_entry"):
            return {"examined": 0, "persisted": 0}
        receipts = self.store.paper_canary_settlements(limit=limit)
        persisted = 0
        for receipt in receipts:
            payload = receipt.get("payload") if isinstance(receipt.get("payload"), dict) else {}
            intent = payload.get("intent") if isinstance(payload.get("intent"), dict) else {}
            intent_payload = self._json_mapping(intent.get("payload"))
            before = self.data_store.conn.execute(
                "SELECT COUNT(*) FROM crystal_registry WHERE crystal_family='small_window_canary_memory'"
            ).fetchone()[0]
            self._persist_rapid_canary_memory_crystal(receipt, intent_payload=intent_payload)
            after = self.data_store.conn.execute(
                "SELECT COUNT(*) FROM crystal_registry WHERE crystal_family='small_window_canary_memory'"
            ).fetchone()[0]
            persisted += 1 if int(after or 0) > int(before or 0) else 0
        return {"examined": len(receipts), "persisted": persisted}

    def settle_rapid_paper_canaries(self, *, limit: int = 100) -> dict[str, Any]:
        now = self.now_fn()
        if not getattr(self.data_store, "conn", None):
            return {"examined": 0, "settled": 0, "pending": 0, "wins": 0, "losses": 0}
        with self.data_store._lock:
            cursor = self.data_store.conn.execute(
                """
                SELECT * FROM phase6_canary_intents
                WHERE status='PAPER_CANARY' AND horizon_ts<=?
                ORDER BY horizon_ts ASC
                LIMIT ?
                """,
                (now, int(limit)),
            )
            rows = cursor.fetchall()
            columns = [item[0] for item in cursor.description]
        expire_after = max(0.0, float(getattr(self.cfg, "phase6_rapid_expire_after_sec", 180.0) or 180.0))
        tolerance = max(1.0, float(getattr(self.cfg, "phase6_rapid_settlement_tolerance_sec", 600.0) or 600.0))
        examined = settled = pending = wins = losses = expired = 0
        receipts: list[dict[str, Any]] = []
        for raw in rows:
            examined += 1
            intent = dict(zip(columns, raw))
            try:
                payload = json.loads(intent.get("payload") or "{}")
            except Exception:
                payload = {}
            entry = self._num(intent.get("reference_price"))
            target_ts = self._num(intent.get("horizon_ts"))
            symbol = str(intent.get("symbol") or "")
            side = str(intent.get("side") or "").lower()
            if entry <= 0 or target_ts <= 0 or not symbol:
                pending += 1
                continue
            observation = self._settlement_observation(symbol, target_ts)
            exit_price = self._num(observation.get("price")) if observation else 0.0
            if exit_price <= 0:
                if now > target_ts + tolerance + expire_after:
                    self.store.mark_intent(
                        str(intent.get("canary_intent_id") or ""),
                        status="PAPER_CANARY_EXPIRED_NO_OBSERVATION",
                        validate_only_completed=True,
                    )
                    expired += 1
                    continue
                pending += 1
                continue
            if side in {"paper_sell", "sell"}:
                gross_bps = (entry - exit_price) / entry * 10000.0
            else:
                gross_bps = (exit_price - entry) / entry * 10000.0
            predicted_cost_bps = self._num(intent.get("predicted_cost_bps"))
            net_bps = gross_bps - predicted_cost_bps
            positive = net_bps > 0.0
            status = "PAPER_CANARY_WIN" if positive else "PAPER_CANARY_LOSS"
            receipt = {
                "schema": "phase6_rapid_paper_canary_settlement_v1",
                "evidence_receipt_id": canonical_hash({
                    "scope": "phase6_rapid_paper_canary_settlement",
                    "canary_intent_id": intent.get("canary_intent_id"),
                }),
                "created_ts": now,
                "evidence_scope": "phase6_rapid_paper_canary_settlement",
                "authority_ceiling": "paper_research_only",
                "stage_context": 6,
                "config_hash": self.current_hash,
                "canary_intent_id": intent.get("canary_intent_id"),
                "source_trade_id": (payload.get("source_trade_id") or payload.get("rapid_paper_trade", {}).get("trade_id"))
                if isinstance(payload, dict) else None,
                "symbol": symbol,
                "side": side,
                "entry_ts": intent.get("created_ts"),
                "target_ts": target_ts,
                "settled_ts": observation.get("ts"),
                "entry_price": entry,
                "exit_price": exit_price,
                "gross_return_bps": round(gross_bps, 6),
                "predicted_cost_bps": round(predicted_cost_bps, 6),
                "net_return_bps": round(net_bps, 6),
                "positive_net": positive,
                "status": status,
                "observation_run_id": observation.get("run_id"),
                "payload": {
                    "intent": intent,
                    "settlement_observation": observation,
                    "settlement_window": "phase6_rapid_same_slice_horizon",
                },
            }
            receipt["evidence_hash"] = canonical_hash({
                key: receipt.get(key)
                for key in (
                    "canary_intent_id", "symbol", "side", "entry_price", "exit_price",
                    "gross_return_bps", "net_return_bps", "settled_ts",
                )
            })
            self.store.persist_evidence_receipt(receipt)
            self.store.mark_intent(str(intent.get("canary_intent_id") or ""), status=status, validate_only_completed=True)
            self._persist_rapid_canary_memory_crystal(receipt, intent_payload=payload if isinstance(payload, dict) else {})
            receipts.append(receipt)
            settled += 1
            wins += 1 if positive else 0
            losses += 0 if positive else 1
        return {
            "examined": examined,
            "settled": settled,
            "pending": pending,
            "wins": wins,
            "losses": losses,
            "expired": expired,
            "receipts": receipts,
        }

    def _prune_excess_rapid_paper_canaries(self, max_open_canaries: int) -> dict[str, Any]:
        if not getattr(self.data_store, "conn", None):
            return {"examined": 0, "pruned": 0, "kept": 0}
        max_open = max(1, int(max_open_canaries or 1))
        with self.data_store._lock:
            cursor = self.data_store.conn.execute(
                """
                SELECT canary_intent_id
                FROM phase6_canary_intents
                WHERE status='PAPER_CANARY'
                ORDER BY horizon_ts ASC, created_ts ASC
                """
            )
            ids = [str(row[0] or "") for row in cursor.fetchall() if str(row[0] or "")]
        prune_ids = ids[max_open:]
        for canary_intent_id in prune_ids:
            self.store.mark_intent(
                canary_intent_id,
                status="PAPER_CANARY_PRUNED_BY_OPEN_CAP",
                validate_only_completed=True,
            )
        return {"examined": len(ids), "pruned": len(prune_ids), "kept": min(len(ids), max_open)}

    def _run_rapid_paper_once(self, report: dict[str, Any]) -> dict[str, Any]:
        freeze = self.data_store.get_phase5_active_freeze()
        compatibility = phase6_spot_freeze_compatibility(freeze or {}, self.cfg)
        max_open_canaries = max(1, int(getattr(self.cfg, "phase6_rapid_max_open_canaries", 2) or 2))
        settlement = self.settle_rapid_paper_canaries()
        open_cap_reconciliation = self._prune_excess_rapid_paper_canaries(max_open_canaries)
        report.update(
            mode="rapid_paper_canary",
            approval_id="rapid-paper-no-live-approval-required",
            reconciled=True,
            live_submission_attempts=0,
            live_orders_submitted=0,
            freeze_compatibility=compatibility,
            settlement=settlement,
            open_cap_reconciliation=open_cap_reconciliation,
        )
        if not compatibility.get("canary_compatible"):
            report.update(status="DISARMED", state="DISARMED", reasons=list(compatibility.get("reasons") or []))
            self.store.set_state("DISARMED", "rapid_paper_canary_incompatible_freeze", payload=compatibility)
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        scorecard = self.store.scorecard()
        if int(scorecard.get("paper_canary_open") or 0) >= max_open_canaries:
            report.update(
                status="ARMED_WAITING",
                state="ARMED",
                reasons=["rapid_paper_canary_open_cap_reached"],
                paper_canary_open=scorecard.get("paper_canary_open"),
                max_open_canaries=max_open_canaries,
            )
            self.store.set_state(
                "ARMED",
                "rapid_paper_canary_open_cap_reached",
                payload={"paper_canary_open": scorecard.get("paper_canary_open"), "max_open_canaries": max_open_canaries},
            )
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        candidate = self._rapid_paper_tape_candidate(freeze or {})
        if not candidate:
            if int(settlement.get("settled") or 0) > 0:
                report.update(status="PAPER_CANARY_SETTLED", state="ARMED", reasons=[])
                state_reason = "rapid_paper_canary_settled"
            else:
                report.update(status="ARMED_WAITING", state="ARMED", reasons=["no_fresh_matching_small_window_tape"])
                state_reason = "waiting_for_fresh_small_window_tape"
            self.store.set_state("ARMED", state_reason, payload=compatibility)
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        payload = candidate.get("payload_dict") if isinstance(candidate.get("payload_dict"), dict) else {}
        tape_candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
        latest = tape_candidate.get("latest_observation") if isinstance(tape_candidate.get("latest_observation"), dict) else {}
        quality = self._num(latest.get("data_quality"), 1.0)
        spread = max(0.0, self._num(latest.get("spread_bps")))
        if quality < self.min_quality:
            report.update(status="ARMED_WAITING", state="ARMED", reasons=["rapid_paper_candidate_quality_below_gate"])
            self.store.set_state("ARMED", "rapid_paper_candidate_quality_below_gate", payload=candidate)
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        if spread > self.max_spread_bps:
            report.update(status="ARMED_WAITING", state="ARMED", reasons=["rapid_paper_candidate_spread_above_gate"])
            self.store.set_state("ARMED", "rapid_paper_candidate_spread_above_gate", payload=candidate)
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        trade_id = str(candidate.get("trade_id") or "")
        direction = str(candidate.get("direction") or "").upper()
        side = "paper_buy" if direction == "UP" else "paper_sell"
        execution_route = candidate.get("execution_route") if isinstance(candidate.get("execution_route"), dict) else {}
        route_policy = str(candidate.get("route_policy") or execution_route.get("selected_policy") or "paper_observation")
        counterfactual_edge = (
            candidate.get("counterfactual_edge")
            if isinstance(candidate.get("counterfactual_edge"), dict)
            else {}
        )
        delayed_observation = self._latest_observation(str(candidate.get("symbol") or "")) if counterfactual_edge.get("accepted") else {}
        delayed_price = self._num(delayed_observation.get("price"))
        reference_price = float(candidate.get("entry_price") or latest.get("price") or 0.0)
        if counterfactual_edge.get("accepted") and delayed_price > 0.0:
            reference_price = delayed_price
        horizon_ts = float(candidate.get("target_ts") or self.now_fn())
        if counterfactual_edge.get("accepted") and self._num(counterfactual_edge.get("hold_sec")) > 0.0:
            horizon_ts = self.now_fn() + self._num(counterfactual_edge.get("hold_sec"))
        canary_intent_id = canonical_hash({
            "phase": 6,
            "mode": "rapid_paper_canary",
            "trade_id": trade_id,
            "freeze_id": (freeze or {}).get("freeze_id"),
            "counterfactual_edge": counterfactual_edge,
        })
        intent = {
            "canary_intent_id": canary_intent_id,
            "shadow_intent_id": f"rapid-paper:{trade_id}",
            "forecast_id": str(candidate.get("source_forecast_id") or f"rapid-paper:{trade_id}"),
            "approval_id": "rapid-paper-no-live-approval-required",
            "freeze_id": str((freeze or {}).get("freeze_id") or ""),
            "capability_receipt_id": "",
            "client_order_id": f"{PHASE6_CLIENT_PREFIX}paper{uuid.uuid4().hex[:10]}",
            "venue": str(candidate.get("venue") or "kraken"),
            "symbol": str(candidate.get("symbol") or ""),
            "side": side,
            "order_type": f"paper_{route_policy}",
            "time_in_force": "NONE",
            "quantity": 0.0,
            "notional_usd": float(candidate.get("notional_usd") or 0.0),
            "reference_price": reference_price,
            "limit_price": reference_price,
            "stop_price": 0.0,
            "target_price": 0.0,
            "horizon_ts": horizon_ts,
            "predicted_cost_bps": float(candidate.get("expected_cost_bps") or 0.0),
            "predicted_net_bps": float(candidate.get("expected_net_bps") or 0.0),
            "probability_positive_net": float(candidate.get("probability_positive_net") or 0.0),
            "data_quality": quality,
            "spread_bps": spread,
            "created_ts": self.now_fn(),
            "deadline_rfc3339": "",
            "config_hash": self.current_hash,
            "live_submission_requested": False,
            "validate_only_completed": True,
            "status": "PAPER_CANARY",
            "authority": "paper_small_window_directional_canary",
            "source_trade_id": trade_id,
            "payload": {
                "freeze": freeze,
                "rapid_paper_trade": candidate,
                "compatibility": compatibility,
                "delayed_entry_observation": delayed_observation,
                "counterfactual_edge": counterfactual_edge,
                "execution_route": execution_route,
                "route_policy": route_policy,
            },
        }
        persisted = self.store.persist_intent(intent)
        report.update(
            status="PAPER_CANARY_OBSERVED" if persisted else "PAPER_CANARY_ALREADY_SEEN",
            state="ARMED",
            validate_only_calls=1 if persisted else 0,
            canary_intent=intent,
            source_trade_id=trade_id,
            dataset_hash=canonical_hash({"intent": intent, "trade": candidate}),
            reasons=[] if persisted else ["rapid_paper_trade_already_consumed_by_phase6"],
        )
        self.store.set_state("ARMED", "rapid_paper_canary_observed", payload=intent)
        report["completed_ts"] = self.now_fn()
        self.store.persist_run(report)
        return report

    @staticmethod
    def _pair_id(symbol: str) -> str:
        pair = symbol.replace("/", "").replace("-", "").upper()
        return pair.replace("BTC", "XBT")

    def _instrument(self, symbol: str) -> dict[str, Any]:
        result = self.exchange.asset_pairs(self._pair_id(symbol))
        if not result:
            raise RuntimeError(f"Kraken returned no instrument metadata for {symbol}")
        key, details = next(iter(result.items()))
        status = str(details.get("status") or "online").lower()
        if status not in {"online", "post_only"}:
            raise RuntimeError(f"Kraken instrument status is {status}")
        return {
            "pair": str(details.get("altname") or key),
            "pair_decimals": int(details.get("pair_decimals", 5) or 5),
            "lot_decimals": int(details.get("lot_decimals", 8) or 8),
            "ordermin": self._num(details.get("ordermin"), 0.0),
            "costmin": self._num(details.get("costmin"), 0.0),
            "status": status,
        }

    @staticmethod
    def _round_down(value: float, decimals: int) -> float:
        quantum = Decimal("1").scaleb(-max(0, int(decimals)))
        return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_DOWN))

    def _build_intent(self, shadow: Mapping[str, Any], approval: Mapping[str, Any], observation: Mapping[str, Any]) -> CanaryIntent:
        symbol = str(shadow.get("symbol") or "")
        if symbol not in set(approval.get("allowed_symbols") or []):
            raise ValueError("symbol is not included in the human canary approval")
        if symbol not in self.allowed_symbols:
            raise ValueError("symbol is not included in the Phase-6 configuration allowlist")
        if str(shadow.get("venue") or "").lower() != "kraken":
            raise ValueError("Phase-6 supports Kraken only")
        if str(shadow.get("direction") or "").upper() != "UP" or str(shadow.get("side") or "").lower() != "buy":
            raise ValueError("Phase-6 spot canary accepts long-entry shadow intents only")
        quality = self._num(observation.get("data_quality"))
        if quality < self.min_quality:
            raise ValueError("latest public observation is below the data-quality gate")
        spread = max(0.0, self._num(observation.get("spread_bps")))
        if spread > self.max_spread_bps:
            raise ValueError("latest public spread exceeds the canary gate")
        now = self.now_fn()
        obs_ts = self._num(observation.get("ts") or observation.get("timestamp"))
        max_age = max(1, int(getattr(self.cfg, "phase6_market_data_max_age_sec", 10) or 10))
        if obs_ts <= 0 or now - obs_ts > max_age:
            raise ValueError("latest public observation is stale")
        reference = self._num(observation.get("price") or shadow.get("reference_price"))
        if reference <= 0:
            raise ValueError("reference price is unavailable")
        instrument = self._instrument(symbol)
        approval_cap = min(self.max_notional, self._num(approval.get("max_notional_usd"), self.max_notional))
        desired_notional = min(approval_cap, self._num(shadow.get("notional_usd"), approval_cap))
        quantity = self._round_down(desired_notional / reference, instrument["lot_decimals"])
        notional = quantity * reference
        if quantity <= 0 or quantity < instrument["ordermin"]:
            raise ValueError("canary quantity is below Kraken order minimum")
        if instrument["costmin"] > 0 and notional < instrument["costmin"]:
            raise ValueError("canary notional is below Kraken cost minimum")
        limit_price = self._round_down(reference * (1.0 + self.max_slippage_bps / 10000.0), instrument["pair_decimals"])
        stop_bps = max(1.0, self._num(getattr(self.cfg, "phase6_stop_distance_bps", 250.0), 250.0))
        target_bps = max(1.0, self._num(getattr(self.cfg, "phase6_target_distance_bps", 400.0), 400.0))
        stop_price = self._round_down(reference * (1.0 - stop_bps / 10000.0), instrument["pair_decimals"])
        target_price = self._round_down(reference * (1.0 + target_bps / 10000.0), instrument["pair_decimals"])
        client_id = PHASE6_CLIENT_PREFIX + uuid.uuid4().hex[:15]
        deadline = datetime.fromtimestamp(now + 5.0, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        canary_id = canonical_hash({"shadow": shadow.get("shadow_intent_id"), "approval": approval.get("approval_id"), "client": client_id})
        return CanaryIntent(
            canary_intent_id=canary_id,
            shadow_intent_id=str(shadow.get("shadow_intent_id") or ""),
            forecast_id=str(shadow.get("forecast_id") or ""),
            approval_id=str(approval.get("approval_id") or ""),
            freeze_id=str(approval.get("freeze_id") or ""),
            capability_receipt_id="",
            client_order_id=client_id,
            venue="kraken",
            symbol=symbol,
            side="buy",
            order_type="limit",
            time_in_force="IOC",
            quantity=quantity,
            notional_usd=notional,
            reference_price=reference,
            limit_price=limit_price,
            stop_price=stop_price,
            target_price=target_price,
            horizon_ts=max(now + 5.0, self._num(shadow.get("target_ts"), now + 300.0)),
            predicted_cost_bps=self._num(shadow.get("predicted_cost_bps")),
            predicted_net_bps=self._num(shadow.get("predicted_net_bps")),
            probability_positive_net=self._num(shadow.get("probability_positive_net")),
            data_quality=quality,
            spread_bps=spread,
            created_ts=now,
            deadline_rfc3339=deadline,
            config_hash=self.current_hash,
            live_submission_requested=self.live_interlock and self.live_config_enabled,
        )

    def _mint_capability_receipt(
        self,
        *,
        approval: Mapping[str, Any],
        shadow: Mapping[str, Any],
        intent: CanaryIntent,
    ) -> CanaryCapabilityReceipt:
        minted_ts = self.now_fn()
        receipt_id = canonical_hash(
            {
                "approval_id": approval.get("approval_id"),
                "shadow_intent_id": shadow.get("shadow_intent_id"),
                "symbol": intent.symbol,
                "client_order_id": intent.client_order_id,
                "minted_ts": minted_ts,
            }
        )
        expires_ts = min(
            float(approval.get("expires_ts") or minted_ts),
            minted_ts + max(5.0, float(getattr(self.cfg, "phase6_candidate_max_age_sec", 30) or 30)),
        )
        return CanaryCapabilityReceipt(
            capability_receipt_id=receipt_id,
            approval_id=str(approval.get("approval_id") or ""),
            freeze_id=str(approval.get("freeze_id") or ""),
            phase4_run_id=str(approval.get("phase4_run_id") or ""),
            candidate_key=str(approval.get("candidate_key") or ""),
            model_id=str(approval.get("model_id") or ""),
            order_policy=str(approval.get("order_policy") or ""),
            shadow_intent_id=str(shadow.get("shadow_intent_id") or ""),
            forecast_id=str(shadow.get("forecast_id") or ""),
            symbol=intent.symbol,
            side=intent.side,
            max_notional_usd=float(intent.notional_usd),
            config_hash=self.current_hash,
            authority_ceiling="single_tiny_phase6_entry_order",
            status="MINTED",
            minted_ts=minted_ts,
            expires_ts=expires_ts,
            payload={
                "approval_id": approval.get("approval_id"),
                "shadow_intent_id": shadow.get("shadow_intent_id"),
                "forecast_id": shadow.get("forecast_id"),
                "client_order_id": intent.client_order_id,
                "limit_price": intent.limit_price,
                "quantity": intent.quantity,
            },
        )

    def _order_payload(self, intent: Mapping[str, Any], *, side: Optional[str] = None,
                       quantity: Optional[float] = None, price: Optional[float] = None,
                       client_order_id: Optional[str] = None) -> dict[str, Any]:
        instrument = self._instrument(str(intent.get("symbol") or ""))
        return {
            "ordertype": "limit",
            "type": side or str(intent.get("side") or "buy"),
            "volume": f"{float(quantity if quantity is not None else intent.get('quantity')):.{instrument['lot_decimals']}f}",
            "pair": instrument["pair"],
            "price": f"{float(price if price is not None else intent.get('limit_price')):.{instrument['pair_decimals']}f}",
            "cl_ord_id": client_order_id or str(intent.get("client_order_id")),
            "timeinforce": "IOC",
            "deadline": datetime.fromtimestamp(self.now_fn() + 5.0, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "stptype": "cancel-newest",
        }

    @staticmethod
    def _permissions_safe(info: Mapping[str, Any]) -> tuple[bool, list[str]]:
        permissions = [str(item).lower() for item in (info.get("permissions") or [])]
        forbidden = [p for p in permissions if any(token in p for token in ("withdraw", "transfer", "earn funds"))]
        order_tokens = ("create-order", "create order", "modify-order", "modify order", "modify-trades", "close-trades")
        query_tokens = (
            "query",
            "open orders",
            "closed orders",
            "query-open-trades",
            "query-closed-trades",
            "query-funds",
            "query-ledger",
        )
        has_order = any(any(token in p for token in order_tokens) for p in permissions)
        has_query = any(any(token in p for token in query_tokens) for p in permissions)
        reasons = []
        if not permissions:
            reasons.append("api_key_permissions_unavailable")
        if forbidden:
            reasons.append("api_key_has_forbidden_funding_permission")
        if not has_order:
            reasons.append("api_key_missing_order_permission")
        if not has_query:
            reasons.append("api_key_missing_query_permission")
        return not reasons, reasons

    def _refresh_deadman(self) -> dict[str, Any]:
        result = self.exchange.cancel_all_after(self.deadman_timeout)
        record = {
            "heartbeat_id": canonical_hash({"ts": self.now_fn(), "timeout": self.deadman_timeout}),
            "ts": self.now_fn(), "timeout_sec": self.deadman_timeout,
            "status": "ARMED", "result": result,
        }
        self.store.persist_deadman(record)
        return record

    def _parse_order(self, client_order_id: str, canary_intent_id: str, symbol: str, side: str,
                     quantity: float, limit_price: float, raw: Mapping[str, Any], *,
                     exchange_order_id: Optional[str], live_submitted: bool) -> CanaryOrder:
        status_raw = str(raw.get("status") or "unknown").lower()
        status_map = {
            "pending": "ACKNOWLEDGED", "open": "OPEN", "closed": "FILLED",
            "canceled": "CANCELED", "cancelled": "CANCELED", "expired": "EXPIRED",
        }
        filled = self._num(raw.get("vol_exec"))
        cost = self._num(raw.get("cost"))
        fee = self._num(raw.get("fee"))
        avg = cost / filled if filled > 0 and cost > 0 else None
        status = status_map.get(status_raw, "UNKNOWN")
        if filled > 0 and status in {"CANCELED", "EXPIRED", "FILLED"}:
            status = "FILLED" if filled >= max(0.0, quantity * 0.999999) else "PARTIALLY_FILLED"
        return CanaryOrder(
            client_order_id=client_order_id,
            canary_intent_id=canary_intent_id,
            exchange_order_id=exchange_order_id,
            symbol=symbol,
            side=side,
            status=status,
            quantity=quantity,
            limit_price=limit_price,
            filled_quantity=filled,
            average_fill_price=avg,
            cost_quote=cost,
            fee_quote=fee,
            created_ts=self.now_fn(),
            updated_ts=self.now_fn(),
            raw_status=status_raw,
            live_submitted=live_submitted,
            reconciled=status != "UNKNOWN",
            payload=dict(raw),
        )

    def _create_position_from_entry(self, order: Mapping[str, Any], intent: Mapping[str, Any]) -> None:
        if self.store.get_open_position():
            return
        qty = self._num(order.get("filled_quantity"))
        price = self._num(order.get("average_fill_price"))
        if qty <= 0 or price <= 0:
            return
        position = CanaryPosition(
            position_id=canonical_hash({"entry": order.get("client_order_id"), "symbol": order.get("symbol")}),
            entry_client_order_id=str(order.get("client_order_id") or ""),
            symbol=str(order.get("symbol") or ""),
            quantity=qty,
            entry_price=price,
            entry_cost_quote=self._num(order.get("cost_quote")) + self._num(order.get("fee_quote")),
            opened_ts=self.now_fn(),
            stop_price=self._num(intent.get("stop_price")),
            target_price=self._num(intent.get("target_price")),
            horizon_ts=self._num(intent.get("horizon_ts"), self.now_fn() + 300.0),
            payload={"source_intent": intent.get("canary_intent_id")},
        )
        self.store.persist_position(position.to_dict())
        self.store.set_state("POSITION_OPEN", "entry_fill_reconciled", payload=position.to_dict())

    def reconcile(self) -> dict[str, Any]:
        if self.exchange is None:
            raise RuntimeError("private Kraken client unavailable")
        now = self.now_fn()
        key_info = self.exchange.api_key_info()
        safe, permission_reasons = self._permissions_safe(key_info)
        if not safe:
            raise RuntimeError(";".join(permission_reasons))
        system = self.exchange.system_status()
        system_status = str(system.get("status") or system.get("system") or "online").lower()
        if system_status not in {"online", "post_only"}:
            raise RuntimeError(f"Kraken system status is {system_status}")
        open_payload = self.exchange.open_orders()
        open_orders = dict(open_payload.get("open") or {})
        external = []
        canary_open = []
        for txid, raw in open_orders.items():
            client_id = str(raw.get("cl_ord_id") or raw.get("cl_ordid") or "")
            if client_id.startswith(PHASE6_CLIENT_PREFIX):
                canary_open.append((txid, raw))
            else:
                external.append((txid, raw))
        if external and bool(getattr(self.cfg, "phase6_require_isolated_account", True)):
            raise RuntimeError("non-canary open orders exist on the Kraken account")
        balances = self.exchange.balances()
        unknown = 0
        for local in self.store.get_active_orders():
            txid = str(local.get("exchange_order_id") or "")
            if not txid:
                if local.get("status") in {"SUBMITTED", "ACKNOWLEDGED", "OPEN", "PARTIALLY_FILLED", "UNKNOWN"}:
                    unknown += 1
                continue
            queried = self.exchange.query_orders([txid])
            raw = queried.get(txid)
            if not raw:
                unknown += 1
                order = dict(local)
                order.update({"status": "UNKNOWN", "raw_status": "missing_from_query", "updated_ts": now, "reconciled": False})
                self.store.persist_order(order)
                continue
            parsed = self._parse_order(
                str(local.get("client_order_id")), str(local.get("canary_intent_id")),
                str(local.get("symbol")), str(local.get("side")), self._num(local.get("quantity")),
                self._num(local.get("limit_price")), raw, exchange_order_id=txid,
                live_submitted=bool(local.get("live_submitted")),
            )
            self.store.persist_order(parsed.to_dict())
            if parsed.side == "buy" and parsed.filled_quantity > 0:
                intent = self.store._fetchone("SELECT * FROM phase6_canary_intents WHERE canary_intent_id=?", (parsed.canary_intent_id,))
                self._create_position_from_entry(parsed.to_dict(), intent)
            if parsed.side == "sell" and parsed.filled_quantity > 0:
                position = self.store.get_open_position()
                if position:
                    pnl = parsed.cost_quote - self._num(position.get("entry_cost_quote")) - parsed.fee_quote
                    position.update({
                        "status": "CLOSED", "exit_client_order_id": parsed.client_order_id,
                        "exit_price": parsed.average_fill_price, "closed_ts": now,
                        "realized_pnl_quote": pnl,
                    })
                    self.store.persist_position(position)
                    self.store.set_state("DISARMED", "canary_round_trip_closed", payload=position)
        record = {
            "reconciliation_id": canonical_hash({"ts": now, "open": sorted(open_orders), "local": len(self.store.get_active_orders())}),
            "ts": now,
            "status": "CLEAN" if unknown == 0 else "UNKNOWN",
            "open_orders_count": len(open_orders),
            "canary_open_orders_count": len(canary_open),
            "unknown_orders_count": unknown,
            "active_positions_count": 1 if self.store.get_open_position() else 0,
            "balance_snapshot": balances,
            "system_status": system_status,
            "api_key_permissions_checked": True,
        }
        self.store.persist_reconciliation(record)
        if unknown:
            self._incident("UNKNOWN_ORDER_STATE", "one or more canary orders could not be reconciled")
        return record

    def _submit_exit_if_triggered(self, *, live_requested: bool) -> dict[str, Any]:
        position = self.store.get_open_position()
        if not position:
            return {"triggered": False}
        observation = self._latest_observation(str(position.get("symbol")))
        price = self._num(observation.get("price"))
        now = self.now_fn()
        reason = None
        if price > 0 and price <= self._num(position.get("stop_price")):
            reason = "STOP"
        elif price > 0 and price >= self._num(position.get("target_price")):
            reason = "TARGET"
        elif now >= self._num(position.get("horizon_ts")):
            reason = "HORIZON"
        elif self.store.get_state().get("state") in {"HALTED", "EXIT_ONLY"}:
            reason = "HALT_REDUCTION"
        if not reason:
            return {"triggered": False}
        if not live_requested or not self.live_interlock or not self.live_config_enabled:
            self.store.set_state("EXIT_ONLY", f"exit_required_but_live_interlock_absent:{reason}")
            return {"triggered": True, "submitted": False, "reason": reason}
        if price <= 0:
            self._incident("EXIT_MARKET_DATA", "cannot construct risk-reducing exit without a valid public price",
                           symbol=str(position.get("symbol")))
            return {"triggered": True, "submitted": False, "reason": reason}
        instrument = self._instrument(str(position.get("symbol")))
        exit_price = self._round_down(price * (1.0 - self.max_slippage_bps / 10000.0), instrument["pair_decimals"])
        client_id = PHASE6_CLIENT_PREFIX + uuid.uuid4().hex[:15]
        payload = {
            "ordertype": "limit", "type": "sell",
            "volume": f"{self._num(position.get('quantity')):.{instrument['lot_decimals']}f}",
            "pair": instrument["pair"],
            "price": f"{exit_price:.{instrument['pair_decimals']}f}",
            "cl_ord_id": client_id, "timeinforce": "IOC",
            "deadline": datetime.fromtimestamp(now + 5.0, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "stptype": "cancel-newest",
        }
        self.exchange.validate_order(payload)
        self._refresh_deadman()
        try:
            response = self.exchange.add_order(payload)
        except Exception as exc:
            self._incident("EXIT_SUBMISSION_UNKNOWN", f"risk-reducing exit outcome is unknown: {type(exc).__name__}",
                           symbol=str(position.get("symbol")), client_order_id=client_id)
            return {"triggered": True, "submitted": False, "reason": reason, "error": str(exc)}
        txids = list(response.get("txid") or [])
        if not txids:
            self._incident("EXIT_REJECTED", "Kraken returned no transaction id for the risk-reducing exit",
                           symbol=str(position.get("symbol")), client_order_id=client_id, severity="HIGH")
            return {"triggered": True, "submitted": False, "reason": reason}
        order = CanaryOrder(
            client_order_id=client_id,
            canary_intent_id=f"exit:{position.get('position_id')}",
            exchange_order_id=str(txids[0]),
            symbol=str(position.get("symbol")), side="sell", status="SUBMITTED",
            quantity=self._num(position.get("quantity")), limit_price=exit_price,
            filled_quantity=0.0, average_fill_price=None, cost_quote=0.0, fee_quote=0.0,
            created_ts=now, updated_ts=now, raw_status="submitted", live_submitted=True,
            payload={"reason": reason, "response": response},
        )
        self.store.persist_order(order.to_dict())
        position.update({"status": "EXIT_PENDING", "exit_client_order_id": client_id})
        self.store.persist_position(position)
        self.store.set_state("EXIT_PENDING", f"risk_reducing_exit_submitted:{reason}")
        return {"triggered": True, "submitted": True, "reason": reason, "client_order_id": client_id}

    def run_once(self, *, live_requested: bool = False) -> dict[str, Any]:
        started = self.now_fn()
        run_id = f"canary-{int(started * 1000)}-{uuid.uuid4().hex[:8]}"
        report: dict[str, Any] = {
            "phase": 6, "mode": "tiny_live_canary", "run_id": run_id,
            "started_ts": started, "completed_ts": started, "status": "DISARMED",
            "state": self.store.get_state().get("state", "DISARMED"), "approval_id": None,
            "reconciled": False, "validate_only_calls": 0, "live_submission_attempts": 0,
            "live_orders_submitted": 0, "exits_submitted": 0, "incidents_created": 0,
            "automatic_scaling": False, "leverage": 1,
        }
        if not self.enabled:
            report.update(status="DISABLED", state="DISABLED")
            self.store.persist_run(report)
            return report
        if self.rapid_paper_canary_enabled:
            return self._run_rapid_paper_once(report)
        if self.exchange is None:
            report.update(status="DISARMED", state="DISARMED", reasons=["private_kraken_client_unavailable"])
            self.store.set_state("DISARMED", "private_kraken_client_unavailable")
            self.store.persist_run(report)
            return report
        approval = self.store.get_active_approval(self.now_fn())
        report["approval_id"] = approval.get("approval_id") if approval else None
        try:
            reconciliation = self.reconcile()
            report["reconciliation"] = reconciliation
            report["reconciled"] = reconciliation.get("status") == "CLEAN"
            if not report["reconciled"]:
                report.update(status="HALTED", state="HALTED", reasons=["reconciliation_not_clean"])
                report["completed_ts"] = self.now_fn()
                self.store.persist_run(report)
                return report
        except Exception as exc:
            self._incident("RECONCILIATION_FAILED", f"startup reconciliation failed: {type(exc).__name__}: {exc}")
            report.update(status="HALTED", state="HALTED", reasons=["reconciliation_failed"], incidents_created=1)
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report

        exit_result = self._submit_exit_if_triggered(live_requested=live_requested)
        report["exit"] = exit_result
        if exit_result.get("submitted"):
            report.update(status="EXIT_PENDING", state="EXIT_PENDING", exits_submitted=1, live_submission_attempts=1, live_orders_submitted=1)
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        active_positions = self.store.active_position_count()
        active_orders = self.store.active_order_count()
        max_positions = max(1, int(getattr(self.cfg, "phase6_max_open_positions", 1) or 1))
        max_orders = max(1, int(getattr(self.cfg, "phase6_max_open_orders", 1) or 1))
        if active_positions > max_positions:
            self._incident("POSITION_CAP_BREACH", "Phase-6 active-position cap was exceeded")
            report.update(status="HALTED", state="HALTED", reasons=["active_position_cap_exceeded"], incidents_created=1)
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        if active_orders > max_orders:
            self._incident("ORDER_CAP_BREACH", "Phase-6 active-order cap was exceeded")
            report.update(status="HALTED", state="HALTED", reasons=["active_order_cap_exceeded"], incidents_created=1)
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        if self.store.get_open_position():
            report.update(status="POSITION_OPEN", state=self.store.get_state().get("state", "POSITION_OPEN"))
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        if self.store.get_active_orders():
            if live_requested and self.live_interlock and self.live_config_enabled:
                self._refresh_deadman()
            report.update(status="ORDER_PENDING", state="ORDER_PENDING")
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        persisted_state = str(self.store.get_state().get("state") or "DISARMED").upper()
        if persisted_state in {"HALTED", "EXIT_ONLY", "RECOVERY_REVIEW"}:
            report.update(status="HALTED", state=persisted_state, reasons=["persistent_operator_or_safety_halt"])
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        daily_loss_limit = max(0.01, float(getattr(self.cfg, "phase6_daily_loss_halt_usd", 1.0) or 1.0))
        daily_pnl = self.store.realized_pnl_utc_day(self.now_fn())
        report["daily_realized_pnl_quote"] = daily_pnl
        if daily_pnl <= -daily_loss_limit:
            self._incident(
                "DAILY_LOSS_LIMIT",
                f"Phase-6 UTC-day realised loss {daily_pnl:.8f} breached {-daily_loss_limit:.8f}",
                severity="CRITICAL",
            )
            report.update(status="HALTED", state="HALTED", reasons=["daily_loss_limit_breached"], incidents_created=1)
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        if not approval:
            report.update(status="DISARMED", state="DISARMED", reasons=["no_active_short_lived_human_approval"])
            self.store.set_state("DISARMED", "no_active_short_lived_human_approval")
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        if approval.get("config_hash") != self.current_hash:
            self._incident("CANARY_CONFIG_DRIFT", "Phase-6 configuration changed after human approval")
            report.update(status="HALTED", state="HALTED", reasons=["canary_config_drift"], incidents_created=1)
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        freeze = self.data_store.get_phase5_active_freeze()
        if not freeze or str(freeze.get("freeze_id")) != str(approval.get("freeze_id")):
            self._incident("FREEZE_DRIFT", "Phase-5 frozen champion changed after canary approval")
            report.update(status="HALTED", state="HALTED", reasons=["phase5_freeze_changed"], incidents_created=1)
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        if int(approval.get("consumed_entry_orders") or 0) >= int(approval.get("max_entry_orders") or 1):
            report.update(status="DISARMED", state="DISARMED", reasons=["approval_entry_budget_consumed"])
            self.store.set_state("DISARMED", "approval_entry_budget_consumed")
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        candidate = self.store.next_shadow_candidate(
            model_id=str(approval.get("model_id") or ""), allowed_symbols=approval.get("allowed_symbols") or [],
            max_age_sec=int(getattr(self.cfg, "phase6_candidate_max_age_sec", 30) or 30), now_ts=self.now_fn(),
        )
        if not candidate:
            report.update(status="ARMED_WAITING", state="ARMED", reasons=["no_fresh_approved_shadow_intent"])
            self.store.set_state("ARMED", "waiting_for_fresh_approved_shadow_intent")
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        observation = self._latest_observation(str(candidate.get("symbol")))
        try:
            intent = self._build_intent(candidate, approval, observation)
        except Exception as exc:
            report.update(status="ARMED_WAITING", state="ARMED", reasons=[f"candidate_rejected:{exc}"])
            self.store.set_state("ARMED", f"candidate_rejected:{exc}")
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        capability_receipt = self._mint_capability_receipt(approval=approval, shadow=candidate, intent=intent)
        if not self.store.persist_capability_receipt(capability_receipt.to_dict()):
            report.update(status="IDEMPOTENT_REPLAY", state="ARMED", reasons=["capability_receipt_already_exists"])
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        intent = replace(intent, capability_receipt_id=capability_receipt.capability_receipt_id)
        if not self.store.persist_intent(intent.to_dict()):
            report.update(status="IDEMPOTENT_REPLAY", state="ARMED", reasons=["shadow_intent_already_consumed"])
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        payload = self._order_payload(intent.to_dict())
        try:
            validation = self.exchange.validate_order(payload)
            report["validate_only_calls"] = 1
            self.store.mark_intent(intent.canary_intent_id, status="VALIDATED", validate_only_completed=True)
        except Exception as exc:
            self.store.mark_intent(intent.canary_intent_id, status="VALIDATION_REJECTED")
            report.update(status="VALIDATION_REJECTED", state="ARMED", reasons=[str(exc)])
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        report["validation"] = validation
        live_authorized = bool(approval.get("live_submission_authorized"))
        if not live_requested or not self.live_interlock or not self.live_config_enabled or not live_authorized:
            report.update(
                status="VALIDATED_ONLY", state="ARMED",
                reasons=["live_submission_requires_cli_live_flag_config_enable_env_interlock_and_active_approval"],
                canary_intent=intent.to_dict(),
            )
            self.store.set_state("ARMED", "validate_only_probe_completed")
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        if not self.store.consume_entry_slot(str(approval.get("approval_id"))):
            report.update(status="DISARMED", state="DISARMED", reasons=["approval_entry_slot_unavailable"])
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        if not self.store.consume_capability_receipt(
            intent.capability_receipt_id,
            client_order_id=intent.client_order_id,
            canary_intent_id=intent.canary_intent_id,
            now_ts=self.now_fn(),
        ):
            self._incident("CAPABILITY_RECEIPT_INVALID", "Phase-6 entry receipt was unavailable, expired, or already consumed")
            report.update(status="HALTED", state="HALTED", incidents_created=1, reasons=["capability_receipt_unavailable"])
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        self._refresh_deadman()
        placeholder = CanaryOrder(
            client_order_id=intent.client_order_id, canary_intent_id=intent.canary_intent_id,
            exchange_order_id=None, symbol=intent.symbol, side="buy", status="PERSISTED",
            quantity=intent.quantity, limit_price=intent.limit_price, filled_quantity=0.0,
            average_fill_price=None, cost_quote=0.0, fee_quote=0.0,
            created_ts=self.now_fn(), updated_ts=self.now_fn(), raw_status="pre_submit",
            live_submitted=False, reconciled=False,
        )
        self.store.persist_order(placeholder.to_dict())
        report["live_submission_attempts"] = 1
        try:
            response = self.exchange.add_order(payload)
        except Exception as exc:
            unknown = replace(placeholder, status="UNKNOWN", updated_ts=self.now_fn(), raw_status="submit_exception",
                              live_submitted=True, payload={"error": f"{type(exc).__name__}: {exc}"})
            self.store.persist_order(unknown.to_dict())
            self._incident("ENTRY_SUBMISSION_UNKNOWN", "Kraken entry outcome is unknown after submission attempt",
                           symbol=intent.symbol, client_order_id=intent.client_order_id)
            report.update(status="HALTED", state="HALTED", incidents_created=1,
                          reasons=["entry_submission_outcome_unknown"])
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        txids = list(response.get("txid") or [])
        if not txids:
            rejected = replace(placeholder, status="REJECTED", updated_ts=self.now_fn(), raw_status="no_txid",
                               live_submitted=False, reconciled=True, payload={"response": response})
            self.store.persist_order(rejected.to_dict())
            report.update(status="REJECTED", state="DISARMED", reasons=["Kraken returned no order id"])
            self.store.set_state("DISARMED", "entry_rejected_without_txid")
            report["completed_ts"] = self.now_fn()
            self.store.persist_run(report)
            return report
        submitted = replace(
            placeholder, exchange_order_id=str(txids[0]), status="SUBMITTED", updated_ts=self.now_fn(),
            raw_status="submitted", live_submitted=True, payload={"response": response},
        )
        self.store.persist_order(submitted.to_dict())
        self.store.mark_intent(intent.canary_intent_id, status="SUBMITTED")
        self.store.set_state("ORDER_PENDING", "tiny_live_entry_submitted", payload=submitted.to_dict())
        report.update(
            status="ORDER_PENDING", state="ORDER_PENDING", live_orders_submitted=1,
            canary_intent=intent.to_dict(), order=submitted.to_dict(),
        )
        report["completed_ts"] = self.now_fn()
        report["dataset_hash"] = canonical_hash({"intent": intent.to_dict(), "order": submitted.to_dict()})
        self.store.persist_run(report)
        return report

    def preflight(self) -> dict[str, Any]:
        freeze = self.data_store.get_phase5_active_freeze()
        compatibility = phase6_spot_freeze_compatibility(freeze, self.cfg)
        approval = self.store.get_active_approval(self.now_fn())
        reasons = list(compatibility.get("reasons") or [])
        if not self.enabled:
            reasons.append("phase6_canary_disabled")
        if self.rapid_paper_canary_enabled:
            if not self._rapid_paper_tape_candidate(freeze or {}):
                reasons.append("no_fresh_matching_small_window_tape")
        else:
            if self.exchange is None:
                reasons.append("private_kraken_client_unavailable")
            if not approval:
                reasons.append("no_active_short_lived_human_approval")
            elif approval.get("config_hash") != self.current_hash:
                reasons.append("active_approval_config_drift")
            elif freeze and str(freeze.get("freeze_id") or "") != str(approval.get("freeze_id") or ""):
                reasons.append("active_approval_freeze_drift")
            if not self.live_config_enabled:
                reasons.append("phase6_live_submission_disabled_in_profile")
            if not self.live_interlock:
                reasons.append("phase6_live_environment_interlock_absent")
        return {
            "phase": 6,
            "ready_to_attempt_entry_probe": not reasons,
            "reasons": reasons,
            "freeze_compatibility": compatibility,
            "active_approval_id": str(approval.get("approval_id") or ""),
            "live_config_enabled": self.live_config_enabled,
            "live_environment_interlock": self.live_interlock,
            "exchange_client_available": self.exchange is not None,
            "allowed_symbols": list(self.allowed_symbols),
            "rapid_paper_canary_enabled": self.rapid_paper_canary_enabled,
            "authority": compatibility.get("authority") or "kraken_spot_long_only_tiny_canary",
        }

    def snapshot(self, limit: int = 100) -> dict[str, Any]:
        return {
            "phase": 6,
            "mode": "tiny_live_canary",
            "state": self.store.get_state(),
            "preflight": self.preflight(),
            "active_approval": self.store.get_active_approval(self.now_fn()),
            "approvals": self.store.approvals(limit=20),
            "runs": self.store.runs(limit=min(50, limit)),
            "orders": self.store.get_orders(limit=limit),
            "positions": self.store.get_positions(limit=limit),
            "capability_receipts": self.store.capability_receipts(limit=limit),
            "incidents": self.store.open_incidents(),
            "reconciliations": self.store.reconciliations(limit=20),
            "scorecard": self.store.scorecard(),
            "readiness": self.store.readiness(
                min_round_trips=int(getattr(self.cfg, "phase6_min_phase7_round_trips", 50) or 50)
            ),
            "live_config_enabled": self.live_config_enabled,
            "live_environment_interlock": self.live_interlock,
            "automatic_scaling": False,
            "leverage": 1,
        }
