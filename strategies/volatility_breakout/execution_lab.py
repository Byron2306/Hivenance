from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import threading
import time
import uuid
from typing import Any, Optional

from .beast_route_damping import HivenanceRouteDampener
from .execution_engine import SCENARIOS, DeterministicExecutionSimulator
from .venue_profiles import POLICIES


class ExecutionLabAgent:
    """Phase-3 execution-aware research lab.

    It may drive Phase 2, settle matured forecasts, and simulate order lifecycles.
    It is structurally unable to submit a private exchange order.
    """

    def __init__(
        self,
        cfg: Any,
        hypothesis_swarm: Any,
        data_store: Any,
        coordinator: Optional[Any] = None,
    ) -> None:
        self.cfg = cfg
        self.hypothesis_swarm = hypothesis_swarm
        self.data_store = data_store
        self.coordinator = coordinator
        self.enabled = bool(getattr(cfg, "phase3_execution_lab_enabled", True))
        min_interval = max(1, int(getattr(cfg, "phase3_min_interval_sec", 30) or 30))
        self.interval_sec = max(min_interval, int(getattr(cfg, "phase3_interval_sec", 120) or 120))
        self.max_forecasts_per_cycle = max(1, int(getattr(cfg, "phase3_max_forecasts_per_cycle", 50) or 50))
        self.simulator = DeterministicExecutionSimulator(cfg)
        self.policies = tuple(POLICIES)
        self.scenarios = tuple(SCENARIOS)
        damping_path = str(getattr(cfg, "phase3_route_damping_path", "") or "")
        if not damping_path:
            db_path = str(getattr(data_store, "db_path", "") or "")
            root = Path(db_path).parent if db_path else Path("data")
            damping_path = str(root / "phase3_route_damping.json")
        self.route_dampener = HivenanceRouteDampener(
            path=damping_path,
            suppress_at=float(getattr(cfg, "phase3_route_damping_suppress_at", 1000.0) or 1000.0),
            half_life_seconds=float(getattr(cfg, "phase3_route_damping_half_life_sec", 900.0) or 900.0),
        )
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._run_count = 0
        self._last_error: Optional[str] = None
        self._latest: dict[str, Any] = {
            "phase": 3,
            "mode": "execution_simulation_only",
            "status": "INITIALIZED" if self.enabled else "DISABLED",
            "execution_wired": False,
            "real_orders_submitted": 0,
            "simulations": [],
        }

    @staticmethod
    def _canonical_hash(payload: Any) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _cfg_sequence(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
        if value is None:
            return default
        if isinstance(value, str):
            items = tuple(item.strip() for item in value.split(",") if item.strip())
            return items or default
        if isinstance(value, (list, tuple, set)):
            items = tuple(str(item).strip() for item in value if str(item).strip())
            return items or default
        return default

    def _phase3_exploration_fallback_candidates(self, *, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Outcome-blind replay lane for calibration-starved Phase-3 research."""
        if not bool(getattr(self.cfg, "phase3_calibration_exploration_fallback_enabled", True)):
            return [], {"enabled": False, "reason": "disabled"}
        if not hasattr(self.data_store, "get_phase3_evidence_expansion_candidates"):
            return [], {"enabled": False, "reason": "store_missing_evidence_expansion"}
        model_ids = self._cfg_sequence(
            getattr(self.cfg, "phase3_calibration_exploration_model_ids", None),
            (
                "worker_coalition_meta_v1",
                "candidate_freqai_transparent_linear_v1",
                "candidate_finrl_conservative_policy_proxy_v1",
                "worker_signal_bollinger_v1",
                "worker_signal_rsi_v1",
                "worker_signal_rsi2_v1",
            ),
        )
        policies = self._cfg_sequence(
            getattr(self.cfg, "phase3_calibration_exploration_order_policies", None),
            ("passive_then_chase", "marketable_limit", "passive_post_only"),
        )
        bounded_limit = max(1, int(limit or self.max_forecasts_per_cycle))
        per_query_limit = max(1, min(20, bounded_limit))
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        attempts: list[dict[str, Any]] = []
        for model_id in model_ids:
            for policy in policies:
                if policy not in self.policies:
                    attempts.append({"model_id": model_id, "order_policy": policy, "selected": 0, "reason": "unsupported_policy"})
                    continue
                rows = self.data_store.get_phase3_evidence_expansion_candidates(
                    model_id=model_id,
                    order_policy=policy,
                    limit=per_query_limit,
                    min_expected_net_bps=float(getattr(self.cfg, "phase3_min_expected_net_bps", 10.0) or 10.0),
                    min_probability_positive_net=float(
                        getattr(self.cfg, "phase3_min_probability_positive_net", 0.58) or 0.58
                    ),
                    max_per_symbol=max(1, int(getattr(self.cfg, "phase3_calibration_exploration_max_per_symbol", 4) or 4)),
                    max_per_hour_bucket=max(1, int(getattr(self.cfg, "phase3_calibration_exploration_max_per_hour_bucket", 2) or 2)),
                )
                added = 0
                for row in rows:
                    forecast_id = str(row.get("forecast_id") or "")
                    if not forecast_id or forecast_id in seen:
                        continue
                    row["research_route"] = "calibration_exploration_fallback"
                    row["research_route_priority"] = -25
                    row["evidence_expansion"] = True
                    row["execution_eligible"] = False
                    row["calibration_exploration_fallback"] = {
                        "schema": "phase3_calibration_exploration_fallback_v1",
                        "authority": "research_replay_only",
                        "execution_eligible": False,
                        "source_model_id": model_id,
                        "selection_order_policy": policy,
                        "reason": "formal_candidate_gate_returned_zero",
                    }
                    selected.append(row)
                    seen.add(forecast_id)
                    added += 1
                    if len(selected) >= bounded_limit:
                        break
                attempts.append({"model_id": model_id, "order_policy": policy, "selected": added})
                if len(selected) >= bounded_limit:
                    break
            if len(selected) >= bounded_limit:
                break
        return selected, {
            "enabled": True,
            "authority": "research_replay_only",
            "execution_eligible": False,
            "reason": "formal_candidate_gate_returned_zero",
            "models": list(model_ids),
            "order_policies": list(policies),
            "attempts": attempts,
            "selected_count": len(selected),
        }

    def _phase3_admission_receipt(self, candidate: dict[str, Any], now_ms: int) -> dict[str, Any]:
        observation = candidate.get("entry_observation") if isinstance(candidate.get("entry_observation"), dict) else {}
        values = observation.get("values") if isinstance(observation.get("values"), dict) else {}
        crystal = values.get("market_world_state_crystal") if isinstance(values.get("market_world_state_crystal"), dict) else {}
        rejection_causes: list[str] = []
        forecast_time_ms = int(float(candidate.get("forecast_ts") or 0.0) * 1000.0)
        observation_time_ms = int(observation.get("timestamp_ms") or forecast_time_ms or 0)
        if not crystal and observation and observation_time_ms > 0:
            legacy_body = {
                "venue": observation.get("venue") or candidate.get("venue"),
                "symbol": observation.get("symbol") or candidate.get("symbol"),
                "observation_time_ms": observation_time_ms,
                "price": observation.get("price"),
                "spread_bps": observation.get("spread_bps"),
                "depth_usd_25bps": observation.get("depth_usd_25bps"),
                "data_quality": observation.get("data_quality"),
            }
            crystal = {
                "schema": "market_world_state_crystal_v1",
                "world_state_id": self._canonical_hash(legacy_body),
                **legacy_body,
                "fresh_until_ms": observation_time_ms + 60_000,
                "symbol_class": candidate.get("symbol_class") or values.get("symbol_class") or "unknown",
                "execution_environment": "research_only",
                "authority": "context_only",
                "reconstruction_state": "legacy_snapshot_reconstructed",
            }
        if not crystal:
            rejection_causes.append("missing_world_state_crystal")
        fresh_until_ms = float(crystal.get("fresh_until_ms") or 0.0) if crystal else 0.0
        replay_boundary_ms = float(forecast_time_ms or observation_time_ms or now_ms)
        if crystal and fresh_until_ms < replay_boundary_ms:
            rejection_causes.append("world_state_stale")
        spread_bps = float(observation.get("spread_bps") or 0.0)
        max_entry_spread = float(getattr(self.cfg, "phase3_max_entry_spread_bps", 60.0) or 60.0)
        if spread_bps > max_entry_spread:
            rejection_causes.append("hostile_spread")
        data_quality = float(observation.get("data_quality") or 0.0)
        min_quality = float(getattr(self.cfg, "phase3_min_data_quality", 0.99) or 0.99)
        if data_quality < min_quality:
            rejection_causes.append("low_data_quality")
        depth_usd = float(observation.get("depth_usd_25bps") or 0.0)
        min_depth = float(getattr(self.cfg, "phase1_observation_min_depth_usd_25bps", 25000.0) or 25000.0)
        if depth_usd < min_depth:
            rejection_causes.append("insufficient_depth")
        symbol_class = str((crystal.get("symbol_class") if crystal else None) or values.get("symbol_class") or "unknown")
        allow_hostile_niche = bool(
            getattr(self.cfg, "phase3_allow_niche_hostile_liquidity", False)
            or str(getattr(self.cfg, "profile_name", "") or "") == "high_vol_low_stakes"
        )
        if symbol_class == "hostile_liquidity" and not allow_hostile_niche:
            rejection_causes.append("hostile_liquidity_class")
        admitted = not rejection_causes
        receipt = {
            "schema": "phase3_admission_receipt_v1",
            "forecast_id": candidate.get("forecast_id"),
            "symbol": candidate.get("symbol"),
            "model_id": candidate.get("model_id"),
            "venue": candidate.get("venue"),
            "world_state_id": crystal.get("world_state_id") if crystal else None,
            "research_route": candidate.get("research_route"),
            "regime_hint": candidate.get("regime_hint"),
            "symbol_class": symbol_class,
            "admitted": admitted,
            "rejection_causes": rejection_causes,
            "checked_at_ms": int(now_ms),
            "market_state_evaluated_at_ms": int(replay_boundary_ms),
            "world_state_reconstruction": crystal.get("reconstruction_state") or "native",
        }
        receipt["receipt_id"] = self._canonical_hash(receipt)
        return receipt

    @staticmethod
    def _negative_capability_receipt(candidate: dict[str, Any], admission: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": "negative_capability_crystal_v1",
            "forecast_id": candidate.get("forecast_id"),
            "symbol": candidate.get("symbol"),
            "model_id": candidate.get("model_id"),
            "thesis": candidate.get("hypothesis"),
            "research_route": candidate.get("research_route"),
            "regime_hint": candidate.get("regime_hint"),
            "symbol_class": admission.get("symbol_class"),
            "failure_state": tuple(admission.get("rejection_causes") or ()),
            "reason": "phase3_admission_refusal",
            "world_state_id": admission.get("world_state_id"),
            "receipt_id": admission.get("receipt_id"),
        }

    @staticmethod
    def _negative_capability_crystal_row(receipt: dict[str, Any], *, created_ts: float) -> dict[str, Any]:
        symbol = str(receipt.get("symbol") or "unknown")
        hypothesis = str(receipt.get("thesis") or "unknown")
        regime_hint = str(receipt.get("regime_hint") or "unknown")
        symbol_class = str(receipt.get("symbol_class") or "unknown")
        scope_key = f"{hypothesis}|{regime_hint}|{symbol_class}|{symbol}"
        crystal_id = str(
            receipt.get("crystal_id")
            or hashlib.sha256(
                json.dumps(
                    {
                        "phase_scope": 3,
                        "symbol": symbol,
                        "hypothesis": hypothesis,
                        "failure_state": list(receipt.get("failure_state") or []),
                        "world_state_id": receipt.get("world_state_id"),
                    },
                    sort_keys=True,
                    default=str,
                ).encode("utf-8")
            ).hexdigest()
        )
        payload = dict(receipt)
        payload.setdefault("crystal_id", crystal_id)
        payload.setdefault("artifact_class", "negative_capability_crystal")
        payload.setdefault("authority", "proposal_only")
        payload.setdefault("verification_state", "candidate")
        return {
            "crystal_id": crystal_id,
            "created_ts": float(created_ts),
            "updated_ts": float(created_ts),
            "crystal_family": "negative_capability",
            "artifact_class": "negative_capability_crystal",
            "authority": "proposal_only",
            "verification_state": "candidate",
            "phase_scope": 3,
            "scope_key": scope_key,
            "symbol": symbol,
            "venue": None,
            "regime_hint": regime_hint,
            "hypothesis": hypothesis,
            "world_state_id": receipt.get("world_state_id"),
            "applicability_hash": hashlib.sha256(scope_key.encode("utf-8")).hexdigest(),
            "evidence_strength": float(len(receipt.get("failure_state") or [])),
            "drift_status": "active_refusal_memory",
            "expires_ts": None,
            "payload": payload,
        }

    def _abstention_beat_receipt(self, candidate: dict[str, Any], admission: dict[str, Any]) -> dict[str, Any]:
        expected_net_bps = float(candidate.get("expected_net_bps") or 0.0)
        expected_cost_bps = float(candidate.get("expected_cost_bps") or 0.0)
        probability_positive_net = float(candidate.get("probability_positive_net") or 0.0)
        cost_survival_ratio = float(candidate.get("cost_survival_ratio") or 0.0)
        adjusted_edge_quality_score = float(
            candidate.get("adjusted_edge_quality_score")
            or candidate.get("edge_quality_score")
            or 0.0
        )
        recent_slice_mean = candidate.get("recent_slice_historical_mean_net_bps")
        frontier_mean = candidate.get("frontier_regime_mean_net_bps")
        min_expected_net_bps = float(getattr(self.cfg, "phase3_min_expected_net_bps", 0.0) or 0.0)
        min_probability = float(getattr(self.cfg, "phase3_min_probability_positive_net", 0.0) or 0.0)
        min_cost_survival_ratio = float(getattr(self.cfg, "phase3_min_cost_survival_ratio", 1.0) or 1.0)
        beats_abstention = bool(
            admission.get("admitted")
            and expected_net_bps >= min_expected_net_bps
            and probability_positive_net >= min_probability
            and cost_survival_ratio >= min_cost_survival_ratio
            and adjusted_edge_quality_score > 0.0
            and (
                (recent_slice_mean is not None and float(recent_slice_mean) > 0.0)
                or (frontier_mean is not None and float(frontier_mean) > 0.0)
                or expected_net_bps > expected_cost_bps
            )
        )
        reasons = []
        if expected_net_bps < min_expected_net_bps:
            reasons.append("expected_net_not_above_cash_hurdle")
        if probability_positive_net < min_probability:
            reasons.append("probability_not_above_cash_hurdle")
        if cost_survival_ratio < min_cost_survival_ratio:
            reasons.append("cost_survival_not_above_cash_hurdle")
        if adjusted_edge_quality_score <= 0.0:
            reasons.append("edge_quality_not_above_cash_hurdle")
        if not reasons and not beats_abstention:
            reasons.append("insufficient_slice_or_frontier_support")
        receipt = {
            "schema": "abstention_beat_receipt_v1",
            "forecast_id": candidate.get("forecast_id"),
            "symbol": candidate.get("symbol"),
            "model_id": candidate.get("model_id"),
            "thesis": candidate.get("hypothesis"),
            "research_route": candidate.get("research_route"),
            "regime_hint": candidate.get("regime_hint"),
            "symbol_class": admission.get("symbol_class"),
            "world_state_id": admission.get("world_state_id"),
            "beats_abstention": beats_abstention,
            "expected_net_bps": expected_net_bps,
            "expected_cost_bps": expected_cost_bps,
            "probability_positive_net": probability_positive_net,
            "cost_survival_ratio": cost_survival_ratio,
            "adjusted_edge_quality_score": adjusted_edge_quality_score,
            "recent_slice_historical_mean_net_bps": recent_slice_mean,
            "frontier_regime_mean_net_bps": frontier_mean,
            "reasons": reasons if not beats_abstention else ["expected_action_superior_to_cash"],
            "checked_at_ms": int(admission.get("checked_at_ms") or 0),
        }
        receipt["receipt_id"] = self._canonical_hash(receipt)
        return receipt

    def _commons_signature_for(self, payload: dict[str, Any]) -> str:
        body = {k: v for k, v in payload.items() if k not in {"signature", "payload"}}
        return self._canonical_hash(body)

    def _issue_phase3_commons_ticket(self, candidate: dict[str, Any], now_ts: float, *, task_class: str = "phase3_execution_policy_candidate") -> dict[str, Any]:
        observation = candidate.get("entry_observation") if isinstance(candidate.get("entry_observation"), dict) else {}
        values = observation.get("values") if isinstance(observation.get("values"), dict) else {}
        crystal = values.get("market_world_state_crystal") if isinstance(values.get("market_world_state_crystal"), dict) else {}
        payload = {
            "schema": "hivenance_commons_pool_work_ticket_v1",
            "ticket_id": self._canonical_hash({
                "type": "phase3_ticket",
                "forecast_id": candidate.get("forecast_id"),
                "created_ts": float(now_ts),
            }),
            "pool_type": "inference_pool",
            "task_class": str(task_class or "phase3_execution_policy_candidate"),
            "phase_scope": 3,
            "created_ts": float(now_ts),
            "expires_ts": float(now_ts + max(60, int(getattr(self.cfg, "phase3_commons_ticket_ttl_sec", 900) or 900))),
            "lease_count": 1,
            "authority": "research_work_only",
            "world_state_digest": crystal.get("world_state_id") if crystal else None,
            "input_root": self._canonical_hash({
                "forecast_id": candidate.get("forecast_id"),
                "symbol": candidate.get("symbol"),
                "entry_price": candidate.get("entry_price"),
                "expected_net_bps": candidate.get("expected_net_bps"),
            }),
            "feature_schema_digest": self._canonical_hash({
                "symbol": candidate.get("symbol"),
                "regime_hint": candidate.get("regime_hint"),
                "symbol_class": candidate.get("symbol_class"),
            }),
            "code_digest": self._canonical_hash({
                "component": "execution_lab",
                "simulator_version": self.simulator.simulator_version,
                "policies": list(self.policies),
                "scenarios": list(self.scenarios),
            }),
            "config_digest": self._canonical_hash({
                "phase3_max_entry_spread_bps": getattr(self.cfg, "phase3_max_entry_spread_bps", None),
                "phase3_min_probability_positive_net": getattr(self.cfg, "phase3_min_probability_positive_net", None),
                "phase3_min_cost_survival_ratio": getattr(self.cfg, "phase3_min_cost_survival_ratio", None),
            }),
            "required_engine_profiles": ["python_cpu", "execution_policy_search"],
            "required_verifiers": ["manifest", "policy", "schema"],
            "privacy_class": "public_market_research",
            "challenge_nonce": self._canonical_hash({
                "forecast_id": candidate.get("forecast_id"),
                "checked_at": float(now_ts),
            })[:24],
            "target_object": {
                "forecast_id": candidate.get("forecast_id"),
                "symbol": candidate.get("symbol"),
                "regime_hint": candidate.get("regime_hint"),
                "symbol_class": candidate.get("symbol_class"),
            },
            "status": "ISSUED",
        }
        payload["signature"] = self._commons_signature_for(payload)
        return payload

    @staticmethod
    def _phase3_rung_row(candidate: dict[str, Any], *, run_id: str, created_ts: float, outcome_status: str) -> dict[str, Any]:
        selected_rung = "commons_execution_policy" if str(candidate.get("research_route") or "") == "commons_inference_pool" else "local_execution_policy"
        return {
            "rung_id": hashlib.sha256(
                json.dumps(
                    {
                        "phase_scope": 3,
                        "run_id": run_id,
                        "forecast_id": candidate.get("forecast_id"),
                        "selected_rung": selected_rung,
                    },
                    sort_keys=True,
                    default=str,
                ).encode("utf-8")
            ).hexdigest(),
            "created_ts": float(created_ts),
            "phase_scope": 3,
            "run_id": run_id,
            "forecast_id": candidate.get("forecast_id"),
            "simulation_id": None,
            "symbol": candidate.get("symbol"),
            "venue": candidate.get("venue"),
            "model_id": candidate.get("model_id"),
            "hypothesis": candidate.get("hypothesis"),
            "regime_hint": candidate.get("regime_hint"),
            "symbol_class": candidate.get("symbol_class"),
            "cohort_bucket": candidate.get("cohort_bucket"),
            "selected_rung": selected_rung,
            "candidate_rungs": [
                "abstain",
                "local_execution_policy",
                "commons_execution_policy",
                "stress_scenario_candidate",
            ],
            "selected_priority": candidate.get("research_route_priority"),
            "expected_net_bps": candidate.get("expected_net_bps"),
            "probability_positive_net": candidate.get("probability_positive_net"),
            "cost_bps": candidate.get("expected_cost_bps"),
            "authority_ceiling": "proposal_only",
            "outcome_status": outcome_status,
            "outcome_net_bps": candidate.get("expected_net_bps") if outcome_status == "ADMITTED" else None,
        }

    def _verify_phase3_commons_packet(self, packet: dict[str, Any], candidate_ids: set[str], now_ts: float) -> tuple[bool, list[str]]:
        adoption = packet.get("adoption_receipt") if isinstance(packet.get("adoption_receipt"), dict) else {}
        inference = packet.get("inference_receipt") if isinstance(packet.get("inference_receipt"), dict) else {}
        summary = inference.get("result_summary") if isinstance(inference.get("result_summary"), dict) else {}
        target = inference.get("target_object") if isinstance(inference.get("target_object"), dict) else {}
        reasons: list[str] = []
        if adoption.get("authority_ceiling") != "proposal_only":
            reasons.append("authority_ceiling_not_proposal_only")
        if adoption.get("local_reproduction_verdict") != "PASS":
            reasons.append("local_reproduction_not_passed")
        if str(inference.get("task_class") or "") not in {"phase3_execution_policy_candidate", "phase3_stress_scenario_candidate"}:
            reasons.append("wrong_task_class")
        if int(inference.get("phase_scope") or 0) != 3:
            reasons.append("wrong_phase_scope")
        created_ts = float(inference.get("created_ts") or 0.0)
        if created_ts <= 0 or (now_ts - created_ts) > float(max(60, int(getattr(self.cfg, "phase3_commons_max_packet_age_sec", 3600) or 3600))):
            reasons.append("packet_too_old")
        forecast_id = str(summary.get("forecast_id") or target.get("forecast_id") or "")
        if not forecast_id or forecast_id not in candidate_ids:
            reasons.append("forecast_not_in_local_candidate_set")
        ticket_id = inference.get("ticket_id")
        tickets = self.data_store.get_commons_pool_work_tickets(limit=100, pool_type="inference_pool") if self.data_store is not None else []
        ticket = next((row for row in tickets if row.get("ticket_id") == ticket_id), None)
        if not ticket:
            reasons.append("ticket_not_found")
        else:
            if float(ticket.get("expires_ts") or 0.0) < now_ts:
                reasons.append("ticket_expired")
            if str(ticket.get("challenge_nonce") or "") != str(inference.get("challenge_nonce") or ""):
                reasons.append("challenge_nonce_mismatch")
            if str(ticket.get("input_root") or "") != str(inference.get("input_root") or ""):
                reasons.append("input_root_mismatch")
        signature = str(inference.get("signature") or "")
        if not signature:
            reasons.append("signature_missing")
        elif signature != self._commons_signature_for(inference):
            reasons.append("signature_mismatch")
        policy = str(summary.get("order_policy") or "")
        scenario = str(summary.get("scenario") or "")
        if policy and policy not in self.policies:
            reasons.append("unsupported_policy")
        if scenario and scenario not in self.scenarios:
            reasons.append("unsupported_scenario")
        return (not reasons, reasons)

    def start(self) -> bool:
        if not self.enabled or self.data_store is None or self.hypothesis_swarm is None:
            with self._lock:
                self._latest["status"] = "UNAVAILABLE"
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="hivenance-execution-lab", daemon=True)
        self._thread.start()
        return True

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=max(0.0, timeout))

    def status(self) -> dict[str, Any]:
        with self._lock:
            latest = dict(self._latest)
        return {
            "phase": 3,
            "mode": "execution_simulation_only",
            "enabled": self.enabled,
            "status": latest.get("status", "UNKNOWN"),
            "run_count": self._run_count,
            "last_error": self._last_error,
            "thread_alive": bool(self._thread and self._thread.is_alive()),
            "policies": list(self.policies),
            "scenarios": list(self.scenarios),
            "execution_wired": False,
            "real_orders_submitted": 0,
        }

    def latest_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._latest, default=str))

    def _publish(self, key: str, payload: dict[str, Any]) -> None:
        if self.coordinator and hasattr(self.coordinator, "share_data"):
            self.coordinator.share_data(key, {
                "buzz": {"type": key, "source": "EXECUTION_LAB", "ts": int(time.time() * 1000)},
                "payload": payload,
            })

    def _record_route_damping_from_simulation(
        self,
        candidate: dict[str, Any],
        row: dict[str, Any],
        *,
        policy: str,
        scenario: str,
        events: list[dict[str, Any]],
    ) -> None:
        route_id = self.route_dampener.route_id_from_candidate(candidate, policy=policy, scenario=scenario)
        diagnostics = row.get("diagnostics") if isinstance(row.get("diagnostics"), dict) else {}
        causes = [str(item) for item in (diagnostics.get("failure_causes") or []) if str(item or "").strip()]
        if row.get("status") == "COMPLETED" and bool(row.get("profitable_after_costs")) and not causes:
            causes = ["profitable_after_costs"]
        elif row.get("status") == "COMPLETED" and not causes:
            causes = ["success" if float(row.get("net_return_bps") or 0.0) > 0.0 else "cost_drag"]
        elif row.get("status") == "EXPIRED" and not causes:
            causes = ["late_entry_or_missed_fill"]
        elif row.get("status") == "REJECTED" and not causes:
            causes = ["venue_rejection"]
        for cause in causes:
            score = self.route_dampener.record(route_id, cause, now=float(row.get("completed_ts") or time.time()))
            events.append({
                "route_id": route_id,
                "event": cause,
                "policy": policy,
                "scenario": scenario,
                "penalty": round(float(score.penalty), 6),
                "suppressed": float(score.penalty) >= self.route_dampener.suppress_at,
            })

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self.run_once()
                self._last_error = None
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {exc}"
                logging.exception("Execution lab cycle failed")
                with self._lock:
                    self._latest["status"] = "ERROR"
            self._stop.wait(max(1.0, self.interval_sec - (time.monotonic() - started)))

    def run_once(self, *, drive_phase2: bool = True) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("phase3 execution lab is disabled")
        started_ms = int(time.time() * 1000)
        run_id = f"sim-{started_ms}-{uuid.uuid4().hex[:8]}"
        phase2_payload = None
        if drive_phase2:
            phase2_payload = self.hypothesis_swarm.run_once()
        reuse_summary = ((phase2_payload or {}).get("research_reuse") or {}).get("summary") or {}
        settlement_model_id = ""
        settlement_model_prefix = ""
        settlement_follows_candidate_filter = True
        try:
            settlement_follows_candidate_filter = bool(
                getattr(self.cfg, "phase3_settlement_follows_candidate_filter", True)
            )
            if settlement_follows_candidate_filter:
                settlement_model_id = str(getattr(self.cfg, "phase3_candidate_model_id", "") or "").strip()
                settlement_model_prefix = str(getattr(self.cfg, "phase3_candidate_model_prefix", "") or "").strip()
        except Exception:
            settlement_model_id = ""
            settlement_model_prefix = ""
            settlement_follows_candidate_filter = True
        settlement = self.data_store.settle_mature_hypothesis_forecasts(
            tolerance_sec=float(getattr(self.cfg, "phase2_settlement_tolerance_sec", 600) or 600),
            limit=max(1, int(getattr(self.cfg, "phase2_settlement_batch_limit", 500) or 500)),
            min_target_ts=(
                time.time()
                - float(getattr(self.cfg, "phase2_settlement_max_backlog_age_sec", 6 * 3600) or 6 * 3600)
            ),
            model_id=settlement_model_id or None,
            model_prefix=(None if settlement_model_id else settlement_model_prefix or None),
            abandon_after_sec=float(getattr(self.cfg, "phase2_settlement_abandon_after_sec", 3600) or 3600),
        )
        candidate_pool = self.data_store.get_phase3_forecast_candidates(limit=self.max_forecasts_per_cycle)
        candidate_meta = (
            self.data_store.get_phase3_candidate_meta()
            if hasattr(self.data_store, "get_phase3_candidate_meta")
            else {}
        )
        candidate_meta = dict(candidate_meta or {})
        formal_selected_count = int(candidate_meta.get("selected_count") or len(candidate_pool))
        exploration_fallback_meta: dict[str, Any] = {"enabled": False, "reason": "formal_candidates_available"}
        if not candidate_pool:
            fallback_candidates, exploration_fallback_meta = self._phase3_exploration_fallback_candidates(
                limit=self.max_forecasts_per_cycle
            )
            if fallback_candidates:
                candidate_pool = fallback_candidates
                candidate_meta["formal_selected_count"] = formal_selected_count
                candidate_meta["selected_count"] = len(candidate_pool)
                candidate_meta["exploration_fallback"] = exploration_fallback_meta
                candidate_meta["sample"] = [
                    {
                        "forecast_id": row.get("forecast_id"),
                        "model_id": row.get("model_id"),
                        "symbol": row.get("symbol"),
                        "regime_hint": row.get("regime_hint"),
                        "symbol_class": row.get("symbol_class"),
                        "expected_net_bps": row.get("expected_net_bps"),
                        "probability_positive_net": row.get("probability_positive_net"),
                        "research_route": row.get("research_route"),
                        "execution_eligible": bool(row.get("execution_eligible")),
                    }
                    for row in candidate_pool[:5]
                ]
            else:
                candidate_meta["exploration_fallback"] = exploration_fallback_meta
        commons_tickets = []
        commons_packets_examined = 0
        commons_packets_accepted = 0
        commons_packets_rejected = 0
        commons_rejection_reasons: dict[str, int] = {}
        admission_receipts = [self._phase3_admission_receipt(candidate, started_ms) for candidate in candidate_pool]
        route_damping_events: list[dict[str, Any]] = []
        candidates = []
        for candidate, receipt in zip(candidate_pool, admission_receipts):
            route_id = self.route_dampener.route_id_from_candidate(candidate)
            for cause in receipt.get("rejection_causes") or []:
                score = self.route_dampener.record(route_id, str(cause), now=started_ms / 1000.0)
                route_damping_events.append({
                    "route_id": route_id,
                    "event": str(cause),
                    "penalty": round(float(score.penalty), 6),
                    "suppressed": float(score.penalty) >= self.route_dampener.suppress_at,
                })
            if not bool(receipt.get("admitted")):
                continue
            score = self.route_dampener.score(route_id, now=started_ms / 1000.0)
            if float(score.penalty) >= self.route_dampener.suppress_at:
                receipt["admitted"] = False
                receipt.setdefault("rejection_causes", []).append("beast_route_damped")
                route_damping_events.append({
                    "route_id": route_id,
                    "event": "beast_route_damped",
                    "penalty": round(float(score.penalty), 6),
                    "suppressed": True,
                })
                continue
            candidate["beast_route_damping"] = {
                "route_id": route_id,
                "penalty": round(float(score.penalty), 6),
                "suppressed": False,
                "authority": "research_selection_only",
            }
            candidates.append(candidate)
        abstention_receipts = [
            self._abstention_beat_receipt(candidate, receipt)
            for candidate, receipt in zip(candidate_pool, admission_receipts)
            if bool(receipt.get("admitted"))
        ]
        admission_rejections = [receipt for receipt in admission_receipts if not bool(receipt.get("admitted"))]
        negative_capabilities = [
            self._negative_capability_receipt(candidate, receipt)
            for candidate, receipt in zip(candidate_pool, admission_receipts)
            if not bool(receipt.get("admitted"))
        ]
        for candidate in candidates[: max(1, int(getattr(self.cfg, "phase3_commons_max_tickets_per_run", 12) or 12))]:
            for task_class in ("phase3_execution_policy_candidate", "phase3_stress_scenario_candidate"):
                ticket = self._issue_phase3_commons_ticket(candidate, started_ms / 1000.0, task_class=task_class)
                if self.data_store.persist_commons_pool_work_ticket(ticket):
                    commons_tickets.append(ticket)
        commons_packets = []
        if hasattr(self.data_store, "get_commons_phase3_adopted_execution_packets"):
            commons_packets = self.data_store.get_commons_phase3_adopted_execution_packets(limit=100)
        candidate_ids = {str(candidate.get("forecast_id") or "") for candidate in candidates}
        commons_simulation_plans: set[tuple[str, str, str]] = set()
        for packet in commons_packets:
            commons_packets_examined += 1
            allowed, reasons = self._verify_phase3_commons_packet(packet, candidate_ids, started_ms / 1000.0)
            if not allowed:
                commons_packets_rejected += 1
                for reason in reasons:
                    commons_rejection_reasons[reason] = commons_rejection_reasons.get(reason, 0) + 1
                continue
            inference = packet.get("inference_receipt") if isinstance(packet.get("inference_receipt"), dict) else {}
            summary = inference.get("result_summary") if isinstance(inference.get("result_summary"), dict) else {}
            forecast_id = str(summary.get("forecast_id") or ((inference.get("target_object") or {}).get("forecast_id") if isinstance(inference.get("target_object"), dict) else "") or "")
            order_policy = str(summary.get("order_policy") or "")
            scenario = str(summary.get("scenario") or "")
            if forecast_id and order_policy in self.policies and scenario in self.scenarios:
                commons_simulation_plans.add((forecast_id, order_policy, scenario))
                commons_packets_accepted += 1
        simulations = []
        skipped_existing = 0
        for candidate in candidates:
            for policy in self.policies:
                for scenario in self.scenarios:
                    sim_id = hashlib.sha256(
                        f"{candidate.get('forecast_id')}:{policy}:{scenario}:{self.simulator.simulator_version}".encode()
                    ).hexdigest()
                    if self.data_store.simulation_exists(sim_id):
                        skipped_existing += 1
                        continue
                    result = self.simulator.simulate(candidate, run_id=run_id, order_policy=policy, scenario=scenario)
                    row = result.to_dict()
                    if not self.data_store.persist_execution_simulation(row):
                        raise RuntimeError(f"failed to persist simulation {row.get('simulation_id')}")
                    self._record_route_damping_from_simulation(candidate, row, policy=policy, scenario=scenario, events=route_damping_events)
                    simulations.append(row)
            forecast_id = str(candidate.get("forecast_id") or "")
            for plan_forecast_id, policy, scenario in sorted(commons_simulation_plans):
                if plan_forecast_id != forecast_id:
                    continue
                sim_id = hashlib.sha256(
                    f"{candidate.get('forecast_id')}:{policy}:{scenario}:{self.simulator.simulator_version}".encode()
                ).hexdigest()
                if self.data_store.simulation_exists(sim_id):
                    skipped_existing += 1
                    continue
                result = self.simulator.simulate(candidate, run_id=run_id, order_policy=policy, scenario=scenario)
                row = result.to_dict()
                row["commons_source"] = {"mode": "adopted_execution_policy_candidate", "policy": policy, "scenario": scenario}
                if not self.data_store.persist_execution_simulation(row):
                    raise RuntimeError(f"failed to persist simulation {row.get('simulation_id')}")
                self._record_route_damping_from_simulation(candidate, row, policy=policy, scenario=scenario, events=route_damping_events)
                simulations.append(row)

        completed_ms = int(time.time() * 1000)
        summary = {
            "run_id": run_id,
            "started_at_ms": started_ms,
            "completed_at_ms": completed_ms,
            "forecasts_examined": len(candidates),
            "forecasts_considered": len(candidate_pool),
            "forecasts_admitted": len(candidates),
            "forecasts_refused_pre_simulation": len(admission_rejections),
            "simulations_created": len(simulations),
            "simulations_skipped_existing": skipped_existing,
            "completed": sum(1 for row in simulations if row.get("status") == "COMPLETED"),
            "rejected": sum(1 for row in simulations if row.get("status") == "REJECTED"),
            "expired": sum(1 for row in simulations if row.get("status") == "EXPIRED"),
            "partial_fills": sum(1 for row in simulations if 0 < float(row.get("fill_ratio") or 0) < 0.999),
            "unknown_incidents": sum(1 for row in simulations if row.get("incidents")),
            "execution_wired": False,
            "real_orders_submitted": 0,
        }
        if candidate_meta:
            summary["candidate_intake"] = candidate_meta
        summary["beast_route_damping"] = self.route_dampener.snapshot(limit=24, now=completed_ms / 1000.0)
        summary["beast_route_damping"]["events_this_run"] = route_damping_events[:100]
        if reuse_summary:
            summary["research_reuse"] = {
                "exact_reuse_candidate": int(reuse_summary.get("exact_reuse_candidate") or 0),
                "exact_reuse_too_weak": int(reuse_summary.get("exact_reuse_too_weak") or 0),
                "transformed_symbol_class_candidate": int(reuse_summary.get("transformed_symbol_class_candidate") or 0),
                "transformed_symbol_class_too_weak": int(reuse_summary.get("transformed_symbol_class_too_weak") or 0),
                "transformed_cohort_candidate": int(reuse_summary.get("transformed_cohort_candidate") or 0),
                "transformed_cohort_too_weak": int(reuse_summary.get("transformed_cohort_too_weak") or 0),
                "no_prior_evidence": int(reuse_summary.get("no_prior_evidence") or 0),
            }
        if admission_rejections:
            summary["negative_capabilities"] = {
                "rejected_count": len(admission_rejections),
                "by_cause": {
                    cause: sum(1 for receipt in admission_rejections if cause in (receipt.get("rejection_causes") or []))
                    for cause in sorted({cause for receipt in admission_rejections for cause in (receipt.get("rejection_causes") or [])})
                },
            }
        if abstention_receipts:
            summary["abstention"] = {
                "beats_abstention": sum(1 for receipt in abstention_receipts if bool(receipt.get("beats_abstention"))),
                "fails_abstention": sum(1 for receipt in abstention_receipts if not bool(receipt.get("beats_abstention"))),
                "failure_reasons": {
                    reason: sum(1 for receipt in abstention_receipts if reason in (receipt.get("reasons") or []))
                    for reason in sorted({reason for receipt in abstention_receipts for reason in (receipt.get("reasons") or []) if reason != "expected_action_superior_to_cash"})
                },
            }
        if isinstance(candidate_meta.get("allocation"), dict):
            summary["allocation"] = candidate_meta.get("allocation")
        summary["commons_inference_pool"] = {
            "tickets_issued": len(commons_tickets),
            "adopted_packets_examined": commons_packets_examined,
            "adopted_packets_accepted": commons_packets_accepted,
            "adopted_packets_rejected": commons_packets_rejected,
            "rejection_reasons": commons_rejection_reasons,
            "simulation_plan_count": len(commons_simulation_plans),
            "authority": "proposal_only",
        }
        payload = {
            "phase": 3,
            "mode": "execution_simulation_only",
            "status": (
                "HEALTHY"
                if candidates
                else (
                    "REFUSED_WORLD_STATE"
                    if admission_rejections
                    else (
                    "FILTERED_NO_EDGE"
                    if int((candidate_meta.get("raw_pool_size") or 0)) > 0
                    else "WAITING_FOR_SETTLED_FORECASTS"
                    )
                )
            ),
            "run": summary,
            "phase2_cycle": phase2_payload,
            "settlement": settlement,
            "policies": list(self.policies),
            "scenarios": list(self.scenarios),
            "simulations": simulations,
            "candidate_intake": candidate_meta,
            "phase3_admission": {
                "receipts": admission_receipts,
                "refusals": admission_rejections,
            },
            "abstention_analysis": {
                "receipts": abstention_receipts,
            },
            "allocation": candidate_meta.get("allocation") if isinstance(candidate_meta.get("allocation"), dict) else {},
            "negative_capabilities": negative_capabilities,
            "research_reuse": reuse_summary,
            "commons_inference_pool": summary["commons_inference_pool"],
            "execution_wired": False,
            "real_orders_submitted": 0,
        }
        payload["dataset_hash"] = hashlib.sha256(
            json.dumps(
                {
                    "run": summary,
                    "simulations": simulations,
                    "phase3_admission": payload["phase3_admission"],
                    "abstention_analysis": payload["abstention_analysis"],
                    "allocation": payload["allocation"],
                    "negative_capabilities": negative_capabilities,
                },
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        if hasattr(self.data_store, "persist_inference_rung"):
            for candidate in candidates:
                try:
                    self.data_store.persist_inference_rung(
                        self._phase3_rung_row(
                            candidate,
                            run_id=run_id,
                            created_ts=completed_ms / 1000.0,
                            outcome_status="ADMITTED",
                        )
                    )
                except Exception:
                    logging.exception("Failed to persist Phase-3 admitted rung")
            for candidate, receipt in zip(candidate_pool, admission_receipts):
                if bool(receipt.get("admitted")):
                    continue
                try:
                    self.data_store.persist_inference_rung(
                        self._phase3_rung_row(
                            candidate,
                            run_id=run_id,
                            created_ts=completed_ms / 1000.0,
                            outcome_status="REFUSED_PRE_SIMULATION",
                        )
                    )
                except Exception:
                    logging.exception("Failed to persist Phase-3 refused rung")
        if hasattr(self.data_store, "persist_crystal_registry_entry"):
            for receipt in negative_capabilities:
                try:
                    self.data_store.persist_crystal_registry_entry(
                        self._negative_capability_crystal_row(receipt, created_ts=completed_ms / 1000.0)
                    )
                except Exception:
                    logging.exception("Failed to persist negative capability crystal")
        self.data_store.persist_simulation_run(payload)
        with self._lock:
            self._latest = payload
            self._run_count += 1
        self._publish("buzz.execution_lab.snapshot", payload)
        self._publish("buzz.execution_lab.health", {
            "phase": 3,
            "status": payload["status"],
            "run_id": run_id,
            "simulations_created": len(simulations),
            "execution_wired": False,
            "real_orders_submitted": 0,
        })
        return payload
