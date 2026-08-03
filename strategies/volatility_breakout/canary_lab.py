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

from .canary_models import CanaryApproval, CanaryIncident, CanaryIntent, CanaryOrder, CanaryPosition
from .canary_store import CanaryStore
from .shadow_flight import canonical_hash, frozen_config_hash


PHASE6_ACKNOWLEDGEMENT = "I AUTHORIZE ONE TINY LIVE KRAKEN CANARY"
PHASE6_CLIENT_PREFIX = "hv6"
PHASE6_CONFIG_KEYS = (
    "exchange",
    "phase6_canary_enabled",
    "phase6_live_submission_enabled",
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
    readiness = data_store.get_phase5_readiness(
        min_distinct_days=int(getattr(cfg, "phase5_readiness_min_distinct_days", 30) or 30),
        min_settled=int(getattr(cfg, "phase5_readiness_min_settled", 100) or 100),
        max_cost_mae_bps=float(getattr(cfg, "phase5_readiness_max_cost_mae_bps", 20.0) or 20.0),
        min_fill_ratio=float(getattr(cfg, "phase5_readiness_min_fill_ratio", 0.50) or 0.50),
        require_positive_mean=bool(getattr(cfg, "phase5_readiness_require_positive_mean", True)),
        current_config_hash=frozen_config_hash(cfg),
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

    @staticmethod
    def _num(value: Any, default: float = 0.0) -> float:
        try:
            result = float(value)
            return result if math.isfinite(result) else default
        except (TypeError, ValueError):
            return default

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
        has_order = any("create" in p and "order" in p for p in permissions) or any("modify" in p and "order" in p for p in permissions)
        has_query = any("query" in p or "open orders" in p or "closed orders" in p for p in permissions)
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

    def snapshot(self, limit: int = 100) -> dict[str, Any]:
        return {
            "phase": 6,
            "mode": "tiny_live_canary",
            "state": self.store.get_state(),
            "active_approval": self.store.get_active_approval(self.now_fn()),
            "approvals": self.store.approvals(limit=20),
            "runs": self.store.runs(limit=min(50, limit)),
            "orders": self.store.get_orders(limit=limit),
            "positions": self.store.get_positions(limit=limit),
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
