from __future__ import annotations

import json
import os
import shutil
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import yaml

from agents.phoenix_authority import PhoenixAuthorityGuard


@dataclass(frozen=True)
class ConfigField:
    caster: Callable[[Any], Any]
    category: str
    min_value: Optional[float] = None
    choices: Optional[tuple] = None
    requires_live_confirm: bool = False


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def _to_list(value: Any) -> list:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in str(value or "").replace("\n", ",").split(",") if part.strip()]


CONFIG_SCHEMA: Dict[str, ConfigField] = {
    "dry_run": ConfigField(_to_bool, "runtime", requires_live_confirm=True),
    "live_mode": ConfigField(_to_bool, "runtime", requires_live_confirm=True),
    "swarmguard_small_trade_bypass": ConfigField(_to_bool, "risk"),
    "volatility_harvest_enabled": ConfigField(_to_bool, "research"),
    "exchange": ConfigField(lambda v: str(v).strip().lower(), "market", choices=("kraken", "binance")),
    "symbol": ConfigField(lambda v: str(v).strip().upper(), "market"),
    "interval": ConfigField(lambda v: str(v).strip(), "market"),
    "quote_order_size": ConfigField(float, "risk", min_value=0),
    "max_notional": ConfigField(float, "risk", min_value=0),
    "min_trade_usd": ConfigField(float, "risk", min_value=0),
    "max_trade_usd": ConfigField(float, "risk", min_value=0),
    "multi_symbol_enabled": ConfigField(_to_bool, "market"),
    "multi_symbols": ConfigField(_to_list, "market"),
    "coin_selection_enabled": ConfigField(_to_bool, "market"),
    "coin_selection_auto_switch": ConfigField(_to_bool, "market"),
    "coin_selection_top_n": ConfigField(int, "market", min_value=1),
    "coin_selection_include": ConfigField(_to_list, "market"),
    "coin_selection_exclude": ConfigField(_to_list, "market"),
    "coin_selection_quote_assets": ConfigField(_to_list, "market"),
    "wallet_safety_enabled": ConfigField(_to_bool, "wallet"),
    "wallet_max_daily_spend_usd": ConfigField(float, "wallet", min_value=0),
    "wallet_max_token_exposure_pct": ConfigField(float, "wallet", min_value=0),
    "watch_address": ConfigField(lambda v: str(v).strip(), "wallet"),
    "erc20_token_address": ConfigField(lambda v: str(v).strip(), "wallet"),
    "onchain_enabled": ConfigField(_to_bool, "dex"),
    "dex_provider": ConfigField(lambda v: str(v).strip().lower() or "1inch", "dex"),
    "onchain_chain_id": ConfigField(int, "dex", min_value=1),
    "onchain_prefer_l2": ConfigField(_to_bool, "dex"),
    "onchain_l2_chain_id": ConfigField(int, "dex", min_value=1),
    "onchain_allowed_pairs": ConfigField(_to_list, "dex"),
    "dex_min_roundtrip_ratio": ConfigField(float, "dex", min_value=0),
    "dex_min_liquidity_usd": ConfigField(float, "dex", min_value=0),
    "dex_max_price_impact_pct": ConfigField(float, "dex", min_value=0),
    "market_bee_enabled": ConfigField(_to_bool, "research"),
    "market_bee_top_n": ConfigField(int, "research", min_value=1),
    "public_bot_metrics_auto_promote": ConfigField(_to_bool, "research"),
    "hummingbot_sidecar_live_enabled": ConfigField(_to_bool, "research"),
    "hummingbot_sidecar_command": ConfigField(lambda v: str(v).strip(), "research"),
    "hummingbot_sidecar_config_dir": ConfigField(lambda v: str(v).strip(), "research"),
    "hummingbot_v2_default_executor": ConfigField(lambda v: str(v).replace("_executor", "").strip().lower(), "research", choices=("position", "twap", "grid", "dca", "xemm", "arbitrage")),
    "hummingbot_v2_twap_duration_sec": ConfigField(int, "research", min_value=1),
    "hummingbot_v2_twap_interval_sec": ConfigField(int, "research", min_value=1),
    "hummingbot_v2_grid_width_pct": ConfigField(float, "research", min_value=0),
    "hummingbot_v2_dca_steps": ConfigField(int, "research", min_value=1),
    "hummingbot_v2_dca_step_pct": ConfigField(float, "research", min_value=0),
    "hummingbot_v2_leverage": ConfigField(int, "research", min_value=1),
    "local_crypto_bot_implementations_enabled": ConfigField(_to_bool, "research"),
    "ml_research_lab_enabled": ConfigField(_to_bool, "research"),
    "ml_model_families_enabled": ConfigField(_to_list, "research"),
    "execution_parity_max_latency_ms": ConfigField(int, "research", min_value=1),
    "execution_parity_max_slippage_pct": ConfigField(float, "research", min_value=0),
    "execution_parity_min_fill_ratio": ConfigField(float, "research", min_value=0),
    "execution_parity_max_queue_position_risk": ConfigField(float, "research", min_value=0),
    "orderbook_capture_enabled": ConfigField(_to_bool, "research"),
    "orderbook_capture_depth": ConfigField(int, "research", min_value=1),
    "signal_marketplace_min_originality": ConfigField(float, "research", min_value=0),
    "signal_marketplace_max_drawdown": ConfigField(float, "research", min_value=0),
    "signal_marketplace_min_stability": ConfigField(float, "research", min_value=0),
    "signal_marketplace_min_realized_samples": ConfigField(int, "research", min_value=1),
    "signal_marketplace_reward_scale": ConfigField(float, "research", min_value=0),
    "signal_marketplace_weight_strength": ConfigField(float, "research", min_value=0),
    "signal_marketplace_weight_realized_outcome": ConfigField(float, "research", min_value=0),
    "signal_marketplace_weight_originality": ConfigField(float, "research", min_value=0),
    "signal_marketplace_weight_stability": ConfigField(float, "research", min_value=0),
    "signal_marketplace_weight_win_rate": ConfigField(float, "research", min_value=0),
    "signal_marketplace_weight_drawdown_penalty": ConfigField(float, "research", min_value=0),
    "market_making_advisors_enabled": ConfigField(_to_bool, "research"),
    "market_making_quote_placement_enabled": ConfigField(_to_bool, "research"),
    "pmm_simple_min_liquidity_usd": ConfigField(float, "research", min_value=0),
    "pmm_simple_max_spread_pct": ConfigField(float, "research", min_value=0),
    "pmm_simple_min_quote_spread_pct": ConfigField(float, "research", min_value=0),
    "pmm_dynamic_min_volume_24h_usd": ConfigField(float, "research", min_value=0),
    "pmm_dynamic_max_spread_pct": ConfigField(float, "research", min_value=0),
    "pmm_dynamic_max_abs_change_24h_pct": ConfigField(float, "research", min_value=0),
    "pmm_dynamic_min_quote_spread_pct": ConfigField(float, "research", min_value=0),
    "pair_max_drawdown_pct": ConfigField(float, "pair_protection", min_value=0),
    "pairlist_min_volume_24h_usd": ConfigField(float, "pair_protection", min_value=0),
    "pairlist_max_spread_pct": ConfigField(float, "pair_protection", min_value=0),
    "pairlist_max_abs_change_24h_pct": ConfigField(float, "pair_protection", min_value=0),
    "pairlist_min_age_sec": ConfigField(int, "pair_protection", min_value=0),
    "openclaw_autonomy_enabled": ConfigField(_to_bool, "autonomy"),
    "market_stale_sec": ConfigField(float, "risk", min_value=0),
    "wallet_stale_sec": ConfigField(float, "risk", min_value=0),
    "slippage_threshold": ConfigField(float, "risk", min_value=0),
    "throttle_clear_sec": ConfigField(int, "risk", min_value=0),
    "kill_switch_grace_sec": ConfigField(int, "risk", min_value=0),
    "kill_switch_enforce_stale": ConfigField(_to_bool, "risk"),
}


PHOENIX_FALSE_ONLY_FIELDS = {
    "live_mode",
    "onchain_enabled",
    "public_bot_metrics_auto_promote",
    "hummingbot_sidecar_live_enabled",
    "market_making_quote_placement_enabled",
    "openclaw_autonomy_enabled",
    "coin_selection_auto_switch",
    "swarmguard_small_trade_bypass",
    "volatility_harvest_enabled",
}

PHOENIX_PROTECTED_FIELDS = PHOENIX_FALSE_ONLY_FIELDS | {"dry_run", "hummingbot_v2_leverage"}


class ConfigAgent:
    """Typed settings write boundary with audit log and rollback snapshots."""

    def __init__(
        self,
        config_path: str = "config/settings.yaml",
        snapshot_dir: str = "data/config_snapshots",
        audit_log_path: str = "logs/config_audit.jsonl",
    ):
        self.config_path = config_path
        self.snapshot_dir = snapshot_dir
        self.audit_log_path = audit_log_path
        self._lock = threading.RLock()
        self.authority = PhoenixAuthorityGuard()
        os.makedirs(self.snapshot_dir, exist_ok=True)
        os.makedirs(os.path.dirname(self.audit_log_path) or ".", exist_ok=True)

    def status(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "config_path": self.config_path,
            "snapshot_dir": self.snapshot_dir,
            "audit_log_path": self.audit_log_path,
            "schema_fields": len(CONFIG_SCHEMA),
            "snapshots": self.list_snapshots(limit=5),
            "authority": self.authority.component_contract("config_agent"),
        }

    def read(self) -> Dict[str, Any]:
        with self._lock:
            if not os.path.exists(self.config_path):
                return {}
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return data if isinstance(data, dict) else {}

    def update(self, updates: Dict[str, Any], actor: str = "system", reason: str = "") -> Dict[str, Any]:
        updates = updates or {}
        with self._lock:
            clean, errors = self.validate(updates)
            if errors:
                self._append_audit({
                    "ts": time.time(),
                    "actor": actor,
                    "reason": reason,
                    "event": "config_update_rejected",
                    "requested_fields": sorted(str(k) for k in updates),
                    "errors": errors,
                })
                return {"ok": False, "updates": {}, "errors": errors, "snapshot": None}
            before = self.read()
            snapshot = self.create_snapshot(actor=actor, reason=reason or "before_update")
            after = dict(before)
            after.update(clean)
            self._write(after)
            event = {
                "ts": time.time(),
                "actor": actor,
                "reason": reason,
                "updates": clean,
                "snapshot": snapshot,
            }
            self._append_audit(event)
            return {"ok": True, "updates": clean, "errors": {}, "snapshot": snapshot}

    def validate(self, updates: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, str]]:
        clean: Dict[str, Any] = {}
        errors: Dict[str, str] = {}
        current = self.read()
        quarantine = bool(current.get("phase0_quarantine", True))
        for key, raw in (updates or {}).items():
            if key == "confirm_live":
                errors[key] = "legacy_arm_live_retired_use_phase6_operator"
                continue
            field = CONFIG_SCHEMA.get(key)
            if not field:
                errors[key] = "unsupported_config_field"
                continue
            try:
                value = field.caster(raw)
                if field.min_value is not None and isinstance(value, (int, float)) and value < field.min_value:
                    raise ValueError(f"must be >= {field.min_value}")
                if field.choices and value not in field.choices:
                    raise ValueError("unsupported_choice")
                if key == "dry_run" and not bool(value):
                    raise ValueError("phoenix_authority_locked_use_phase6_operator")
                if key in PHOENIX_FALSE_ONLY_FIELDS and bool(value):
                    raise ValueError("phoenix_authority_locked_use_dedicated_operator")
                if key == "hummingbot_v2_leverage" and int(value) != 1:
                    raise ValueError("phoenix_research_requires_leverage_1")
                if quarantine and key in PHOENIX_PROTECTED_FIELDS:
                    # Safe values are accepted so operators can explicitly reassert them.
                    pass
                clean[key] = value
            except Exception as exc:
                errors[key] = str(exc)
        return clean, errors

    def _restore_safety_errors(self, data: Dict[str, Any]) -> Dict[str, str]:
        errors: Dict[str, str] = {}
        if not bool(data.get("dry_run", True)):
            errors["dry_run"] = "unsafe_snapshot_dry_run_false"
        for key in sorted(PHOENIX_FALSE_ONLY_FIELDS):
            if bool(data.get(key, False)):
                errors[key] = "unsafe_snapshot_protected_field_true"
        if int(data.get("hummingbot_v2_leverage", 1) or 1) != 1:
            errors["hummingbot_v2_leverage"] = "unsafe_snapshot_leverage_not_1"
        return errors

    def create_snapshot(self, actor: str = "system", reason: str = "") -> Dict[str, Any]:
        os.makedirs(self.snapshot_dir, exist_ok=True)
        snapshot_id = time.strftime("%Y%m%d-%H%M%S") + f"-{int((time.time() % 1) * 1000):03d}"
        target = os.path.join(self.snapshot_dir, f"settings-{snapshot_id}.yaml")
        if os.path.exists(self.config_path):
            shutil.copy2(self.config_path, target)
        else:
            with open(target, "w", encoding="utf-8") as f:
                yaml.safe_dump({}, f)
        return {"id": snapshot_id, "path": target, "actor": actor, "reason": reason}

    def rollback(self, snapshot_id: str, actor: str = "system", reason: str = "rollback") -> Dict[str, Any]:
        snapshot_id = str(snapshot_id or "").strip()
        if not snapshot_id:
            return {"ok": False, "error": "snapshot_id_required"}
        source = os.path.join(self.snapshot_dir, f"settings-{snapshot_id}.yaml")
        if not os.path.exists(source):
            return {"ok": False, "error": "snapshot_not_found", "snapshot_id": snapshot_id}
        try:
            with open(source, "r", encoding="utf-8") as handle:
                candidate = yaml.safe_load(handle) or {}
            if not isinstance(candidate, dict):
                raise ValueError("snapshot_not_mapping")
        except Exception as exc:
            return {"ok": False, "error": "snapshot_parse_failed", "details": str(exc)}
        safety_errors = self._restore_safety_errors(candidate)
        if safety_errors:
            self._append_audit({
                "ts": time.time(),
                "actor": actor,
                "reason": reason,
                "event": "config_rollback_rejected",
                "rollback_to": snapshot_id,
                "errors": safety_errors,
            })
            return {"ok": False, "error": "unsafe_snapshot_rejected", "errors": safety_errors}
        with self._lock:
            before = self.create_snapshot(actor=actor, reason="before_rollback")
            shutil.copy2(source, self.config_path)
            self._append_audit({
                "ts": time.time(),
                "actor": actor,
                "reason": reason,
                "event": "config_rollback_applied",
                "rollback_to": snapshot_id,
                "snapshot": before,
            })
        return {"ok": True, "rolled_back_to": snapshot_id, "snapshot": before}

    def list_snapshots(self, limit: int = 20) -> list:
        if not os.path.isdir(self.snapshot_dir):
            return []
        rows = []
        for name in sorted(os.listdir(self.snapshot_dir), reverse=True):
            if not name.startswith("settings-") or not name.endswith(".yaml"):
                continue
            path = os.path.join(self.snapshot_dir, name)
            rows.append({
                "id": name[len("settings-"):-len(".yaml")],
                "path": path,
                "mtime": os.path.getmtime(path),
            })
            if len(rows) >= limit:
                break
        return rows

    def _write(self, data: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.config_path) or ".", exist_ok=True)
        tmp = f"{self.config_path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, sort_keys=True)
        os.replace(tmp, self.config_path)

    def _append_audit(self, event: Dict[str, Any]) -> None:
        with open(self.audit_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, sort_keys=True) + "\n")
