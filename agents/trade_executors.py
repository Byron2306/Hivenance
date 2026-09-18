import time
from typing import Any, Dict, Optional

from agents.hummingbot_strategy_v2 import HummingbotStrategyV2Catalog, HummingbotV2IntentAdapter


class ExecutorResult(dict):
    """Small dict result wrapper for executor outcomes."""


class ExecutorUnavailable(Exception):
    pass


class BaseExecutor:
    name = "BASE_EXECUTOR"
    chain_id = None
    enabled = False

    def __init__(self, cfg: Any, coordinator: Optional[Any] = None):
        self.cfg = cfg
        self.coordinator = coordinator

    def status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "enabled": bool(self.enabled),
            "chain_id": self.chain_id,
            "mode": "disabled",
            "reason": "executor_not_implemented",
        }

    def execute(self, intent: Dict[str, Any], market_row: Optional[Dict[str, Any]] = None) -> ExecutorResult:
        raise ExecutorUnavailable(f"{self.name} is not enabled")


class PaperExecutor(BaseExecutor):
    name = "PAPER_EXECUTOR"
    enabled = True

    def status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "enabled": True,
            "chain_id": "paper",
            "mode": "paper",
            "reason": "simulated_fills_only",
        }

    def execute(self, intent: Dict[str, Any], market_row: Optional[Dict[str, Any]] = None) -> ExecutorResult:
        market_row = market_row or {}
        pool = market_row.get("pool") or {}
        quality = market_row.get("quality") or {}
        symbol = intent.get("symbol") or market_row.get("symbol")
        side = str(intent.get("side") or intent.get("action") or "BUY").upper()
        notional = float(intent.get("notional_usd") or intent.get("quote_amount") or 0.0)
        price = float(intent.get("price") or pool.get("price_usd") or 0.0)
        qty = float(intent.get("qty") or 0.0)
        if qty <= 0 and price > 0 and notional > 0:
            qty = notional / price
        rr = quality.get("roundtrip_ratio")
        route_loss = 1.0 - float(rr) if rr is not None else 0.0
        gross_edge = float(intent.get("gross_edge_pct") or 0.0)
        net_margin = gross_edge - max(0.0, route_loss)
        now = time.time()
        result = ExecutorResult({
            "ok": bool(symbol and price > 0 and qty > 0),
            "executor": self.name,
            "status": "FILLED" if symbol and price > 0 and qty > 0 else "REJECTED",
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "notional_usd": qty * price,
            "route_loss_pct": route_loss,
            "net_margin_pct": net_margin,
            "reason": intent.get("reason") or market_row.get("reason") or "PAPER_EXECUTION",
            "ts": now,
        })
        ds = None
        try:
            ds = self.coordinator.agents.get("data_store") if self.coordinator else None
        except Exception:
            ds = None
        if ds and hasattr(ds, "store_executor_event"):
            ds.store_executor_event(dict(result))
        try:
            if self.coordinator:
                self.coordinator.share_data("buzz.executor.paper", {
                    "buzz": {"type": "buzz.executor.paper", "source": self.name, "ts": int(now * 1000)},
                    "payload": dict(result),
                })
        except Exception:
            pass
        return result


class BaseDexExecutor(BaseExecutor):
    name = "BASE_DEX_EXECUTOR"
    chain_id = 8453


class ArbitrumExecutor(BaseExecutor):
    name = "ARBITRUM_EXECUTOR"
    chain_id = 42161

    def status(self) -> Dict[str, Any]:
        data = super().status()
        data["reason"] = "watch_only_until_arbitrum_router_and_risk_guards_exist"
        return data


class BnbExecutor(BaseExecutor):
    name = "BNB_EXECUTOR"
    chain_id = 56

    def status(self) -> Dict[str, Any]:
        data = super().status()
        data["reason"] = "watch_only_until_bnb_router_and_risk_guards_exist"
        return data


class HummingbotStrategyV2Executor(BaseExecutor):
    name = "HUMMINGBOT_STRATEGY_V2"
    enabled = False

    def __init__(self, cfg: Any, coordinator: Optional[Any] = None):
        super().__init__(cfg, coordinator=coordinator)
        self.catalog = HummingbotStrategyV2Catalog(cfg)
        self.adapter = HummingbotV2IntentAdapter(cfg)

    def status(self) -> Dict[str, Any]:
        data = self.catalog.status()
        data.update({
            "name": self.name,
            "enabled": False,
            "mode": "plan_only",
            "reason": "strategy_v2_catalog_available_sidecar_execution_not_enabled",
        })
        return data

    def plan(self, executor_type: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        catalog_plan = self.catalog.execution_plan(executor_type, intent=intent)
        adapter_plan = self.adapter.plan(intent or {}, executor_type=executor_type)
        if catalog_plan.get("ok"):
            adapter_plan["executor"] = catalog_plan.get("executor")
        return adapter_plan


def build_executor_registry(cfg: Any, coordinator: Optional[Any] = None) -> Dict[str, BaseExecutor]:
    return {
        "paper": PaperExecutor(cfg, coordinator=coordinator),
        "base": BaseDexExecutor(cfg, coordinator=coordinator),
        "arbitrum": ArbitrumExecutor(cfg, coordinator=coordinator),
        "bnb": BnbExecutor(cfg, coordinator=coordinator),
        "hummingbot_v2": HummingbotStrategyV2Executor(cfg, coordinator=coordinator),
    }
