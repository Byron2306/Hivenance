import os
from typing import Any, Dict, List, Optional


class HummingbotStrategyV2Catalog:
    """Filesystem catalog for Hummingbot Strategy V2 references.

    Hivenance keeps Hummingbot behind a sidecar/reference boundary, so this class
    inspects the checked-out source tree instead of importing Hummingbot modules.
    """

    EXECUTOR_ROOT = os.path.join("hummingbot", "strategy_v2", "executors")
    ORCHESTRATOR = os.path.join(EXECUTOR_ROOT, "executor_orchestrator.py")
    DIRECTIONAL_CONTROLLERS = os.path.join("controllers", "directional_trading")
    MARKET_MAKING_CONTROLLERS = os.path.join("controllers", "market_making")

    def __init__(self, cfg: Any, root: Optional[str] = None):
        self.cfg = cfg
        repo_root = root or getattr(cfg, "public_bot_repo_root", "external/public-bots")
        self.repo_path = os.path.join(repo_root, "hummingbot")

    def status(self) -> Dict[str, Any]:
        return {
            "name": "HUMMINGBOT_STRATEGY_V2",
            "enabled": bool(getattr(self.cfg, "hummingbot_strategy_v2_enabled", True)),
            "mode": "reference_adapter",
            "repo_path": self.repo_path,
            "present": os.path.isdir(self.repo_path),
            "executor_orchestrator": self._rel_status(self.ORCHESTRATOR),
            "executors": self.executors(),
            "controllers": {
                "directional_trading": self.controllers("directional_trading"),
                "market_making": self.controllers("market_making"),
            },
            "policy": {
                "imports_hummingbot": False,
                "wallet_authority": "hivenance_only",
                "live_execution": "disabled_until_explicit_adapter",
            },
        }

    def executors(self) -> List[Dict[str, Any]]:
        root = os.path.join(self.repo_path, self.EXECUTOR_ROOT)
        out = []
        for name in self._child_dirs(root):
            if not name.endswith("_executor"):
                continue
            rel = os.path.join(self.EXECUTOR_ROOT, name)
            out.append({
                "name": name,
                "type": name.replace("_executor", ""),
                "path": rel,
                "implementation": self._first_existing(
                    os.path.join(rel, f"{name}.py"),
                    os.path.join(rel, "__init__.py"),
                ),
                "data_types": self._rel_status(os.path.join(rel, "data_types.py")),
            })
        return out

    def controllers(self, group: str) -> List[Dict[str, Any]]:
        if group == "directional_trading":
            root_rel = self.DIRECTIONAL_CONTROLLERS
        elif group == "market_making":
            root_rel = self.MARKET_MAKING_CONTROLLERS
        else:
            return []
        root = os.path.join(self.repo_path, root_rel)
        out = []
        for filename in self._py_files(root):
            if filename == "__init__.py":
                continue
            rel = os.path.join(root_rel, filename)
            out.append({
                "name": filename[:-3],
                "path": rel,
                "group": group,
            })
        return out

    def execution_plan(self, executor_type: str, intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        intent = intent or {}
        executor_type = str(executor_type or "").replace("_executor", "").lower()
        matches = [e for e in self.executors() if e.get("type") == executor_type or e.get("name") == executor_type]
        if not matches:
            return {
                "ok": False,
                "executor_type": executor_type,
                "reason": "hummingbot_strategy_v2_executor_not_found",
            }
        return {
            "ok": True,
            "executor_type": matches[0].get("type"),
            "executor": matches[0],
            "intent": intent,
            "mode": "plan_only",
            "reason": "Hummingbot Strategy V2 cataloged; execution remains sidecar/adapter-only.",
        }

    def _rel_status(self, rel: str) -> Dict[str, Any]:
        path = os.path.join(self.repo_path, rel)
        return {"path": rel, "present": os.path.exists(path)}

    def _first_existing(self, *rels: str) -> Optional[str]:
        for rel in rels:
            if os.path.exists(os.path.join(self.repo_path, rel)):
                return rel
        return None

    def _child_dirs(self, root: str) -> List[str]:
        try:
            return sorted([name for name in os.listdir(root) if os.path.isdir(os.path.join(root, name))])
        except Exception:
            return []

    def _py_files(self, root: str) -> List[str]:
        try:
            return sorted([name for name in os.listdir(root) if name.endswith(".py") and os.path.isfile(os.path.join(root, name))])
        except Exception:
            return []


class HummingbotV2IntentAdapter:
    """Build local plan-only Hummingbot Strategy V2 executor configs from Hivenance intents."""

    def __init__(self, cfg: Any):
        self.cfg = cfg

    def plan(self, intent: Dict[str, Any], executor_type: Optional[str] = None) -> Dict[str, Any]:
        executor_type = self._select_executor(intent, executor_type)
        if executor_type == "position":
            config = self.position_config(intent)
        elif executor_type == "twap":
            config = self.twap_config(intent)
        elif executor_type == "grid":
            config = self.grid_config(intent)
        elif executor_type == "dca":
            config = self.dca_config(intent)
        elif executor_type == "xemm":
            config = self.xemm_config(intent)
        elif executor_type == "arbitrage":
            config = self.arbitrage_config(intent)
        else:
            return {"ok": False, "executor_type": executor_type, "reason": "unsupported_hummingbot_v2_executor"}
        return {
            "ok": True,
            "mode": "plan_only",
            "executor_type": executor_type,
            "config": config,
            "reason": "Local Hivenance intent translated to Hummingbot Strategy V2-shaped config.",
        }

    def position_config(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        side = self._side(intent)
        amount = self._amount_base(intent)
        return {
            "type": "position_executor",
            "connector_name": self._connector(intent),
            "trading_pair": self._trading_pair(intent),
            "side": side,
            "entry_price": self._price(intent),
            "amount": amount,
            "leverage": int(intent.get("leverage") or getattr(self.cfg, "hummingbot_v2_leverage", 1) or 1),
            "triple_barrier_config": self._triple_barrier(intent),
            "level_id": intent.get("signal_id") or intent.get("intent_id"),
        }

    def twap_config(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        total_quote = self._amount_quote(intent)
        duration = int(intent.get("twap_duration_sec") or getattr(self.cfg, "hummingbot_v2_twap_duration_sec", 300) or 300)
        interval = int(intent.get("twap_interval_sec") or getattr(self.cfg, "hummingbot_v2_twap_interval_sec", 30) or 30)
        return {
            "type": "twap_executor",
            "connector_name": self._connector(intent),
            "trading_pair": self._trading_pair(intent),
            "side": self._side(intent),
            "leverage": int(intent.get("leverage") or getattr(self.cfg, "hummingbot_v2_leverage", 1) or 1),
            "total_amount_quote": total_quote,
            "total_duration": duration,
            "order_interval": max(1, min(interval, duration)),
            "mode": str(intent.get("twap_mode") or getattr(self.cfg, "hummingbot_v2_twap_mode", "TAKER")).upper(),
        }

    def grid_config(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        price = max(1e-9, self._price(intent) or 0.0)
        width = float(intent.get("grid_width_pct") or getattr(self.cfg, "hummingbot_v2_grid_width_pct", 0.012) or 0.012)
        lower = float(intent.get("grid_start_price") or price * (1.0 - width))
        upper = float(intent.get("grid_end_price") or price * (1.0 + width))
        return {
            "type": "grid_executor",
            "connector_name": self._connector(intent),
            "trading_pair": self._trading_pair(intent),
            "start_price": lower,
            "end_price": upper,
            "limit_price": price,
            "side": self._side(intent),
            "total_amount_quote": self._amount_quote(intent),
            "min_spread_between_orders": float(getattr(self.cfg, "hummingbot_v2_grid_min_spread", 0.0005) or 0.0005),
            "min_order_amount_quote": float(getattr(self.cfg, "hummingbot_v2_min_order_quote", 5.0) or 5.0),
            "max_open_orders": int(getattr(self.cfg, "hummingbot_v2_grid_max_open_orders", 5) or 5),
            "triple_barrier_config": self._triple_barrier(intent),
            "leverage": int(intent.get("leverage") or getattr(self.cfg, "hummingbot_v2_leverage", 1) or 1),
            "level_id": intent.get("signal_id") or intent.get("intent_id"),
        }

    def dca_config(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        price = max(1e-9, self._price(intent) or 0.0)
        total_quote = self._amount_quote(intent)
        steps = max(1, int(intent.get("dca_steps") or getattr(self.cfg, "hummingbot_v2_dca_steps", 3) or 3))
        step_pct = float(intent.get("dca_step_pct") or getattr(self.cfg, "hummingbot_v2_dca_step_pct", 0.006) or 0.006)
        side = self._side(intent)
        direction = -1.0 if side == "BUY" else 1.0
        return {
            "type": "dca_executor",
            "connector_name": self._connector(intent),
            "trading_pair": self._trading_pair(intent),
            "side": side,
            "leverage": int(intent.get("leverage") or getattr(self.cfg, "hummingbot_v2_leverage", 1) or 1),
            "amounts_quote": [total_quote / steps for _ in range(steps)],
            "prices": [price * (1.0 + direction * step_pct * i) for i in range(steps)],
            "take_profit": float(intent.get("take_profit_pct") or getattr(self.cfg, "hummingbot_v2_take_profit_pct", 0.012) or 0.012),
            "stop_loss": float(intent.get("stop_loss_pct") or getattr(self.cfg, "hummingbot_v2_stop_loss_pct", 0.008) or 0.008),
            "time_limit": int(intent.get("time_limit_sec") or getattr(self.cfg, "hummingbot_v2_time_limit_sec", 900) or 900),
            "mode": str(intent.get("dca_mode") or getattr(self.cfg, "hummingbot_v2_dca_mode", "MAKER")).upper(),
            "level_id": intent.get("signal_id") or intent.get("intent_id"),
        }

    def xemm_config(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "xemm_executor",
            "maker_connector_name": str(intent.get("maker_connector_name") or getattr(self.cfg, "hummingbot_v2_maker_connector", "binance")).lower(),
            "taker_connector_name": str(intent.get("taker_connector_name") or getattr(self.cfg, "hummingbot_v2_taker_connector", "base")).lower(),
            "trading_pair": self._trading_pair(intent),
            "side": self._side(intent),
            "amount": self._amount_base(intent),
            "target_profitability": float(intent.get("target_profitability") or getattr(self.cfg, "hummingbot_v2_xemm_target_profitability", 0.003) or 0.003),
            "min_profitability": float(intent.get("min_profitability") or getattr(self.cfg, "hummingbot_v2_xemm_min_profitability", 0.001) or 0.001),
            "order_refresh_time": int(intent.get("order_refresh_time") or getattr(self.cfg, "hummingbot_v2_xemm_refresh_sec", 15) or 15),
            "level_id": intent.get("signal_id") or intent.get("intent_id"),
        }

    def arbitrage_config(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "arbitrage_executor",
            "buying_market": str(intent.get("buying_market") or getattr(self.cfg, "hummingbot_v2_buying_market", "base")).lower(),
            "selling_market": str(intent.get("selling_market") or getattr(self.cfg, "hummingbot_v2_selling_market", "binance")).lower(),
            "trading_pair": self._trading_pair(intent),
            "order_amount": self._amount_base(intent),
            "min_profitability": float(intent.get("min_profitability") or getattr(self.cfg, "hummingbot_v2_arbitrage_min_profitability", 0.002) or 0.002),
            "quote_amount": self._amount_quote(intent),
            "level_id": intent.get("signal_id") or intent.get("intent_id"),
        }

    def _select_executor(self, intent: Dict[str, Any], requested: Optional[str]) -> str:
        if requested:
            return str(requested).replace("_executor", "").lower()
        if intent.get("arbitrage"):
            return "arbitrage"
        if intent.get("cross_exchange") or intent.get("xemm"):
            return "xemm"
        regime = str(intent.get("regime") or "").upper()
        if intent.get("twap") or intent.get("urgency") == "LOW":
            return "twap"
        if "RANGE" in regime or "CHOP" in regime or "MEAN" in regime:
            return "grid"
        if intent.get("dca"):
            return "dca"
        return "position"

    def _triple_barrier(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "stop_loss": float(intent.get("stop_loss_pct") or getattr(self.cfg, "hummingbot_v2_stop_loss_pct", 0.008) or 0.008),
            "take_profit": float(intent.get("take_profit_pct") or getattr(self.cfg, "hummingbot_v2_take_profit_pct", 0.012) or 0.012),
            "time_limit": int(intent.get("time_limit_sec") or getattr(self.cfg, "hummingbot_v2_time_limit_sec", 900) or 900),
            "open_order_type": str(intent.get("order_type") or "LIMIT").upper(),
            "take_profit_order_type": "MARKET",
            "stop_loss_order_type": "MARKET",
            "time_limit_order_type": "MARKET",
        }

    def _connector(self, intent: Dict[str, Any]) -> str:
        return str(intent.get("connector_name") or getattr(self.cfg, "hummingbot_v2_connector_name", None) or getattr(self.cfg, "exchange", "binance")).lower()

    def _trading_pair(self, intent: Dict[str, Any]) -> str:
        symbol = str(intent.get("symbol") or getattr(self.cfg, "symbol", "ETH-USDT"))
        return symbol.replace("/", "-")

    def _side(self, intent: Dict[str, Any]) -> str:
        action = str(intent.get("side") or intent.get("action") or "BUY").upper()
        return "SELL" if action == "SELL" else "BUY"

    def _price(self, intent: Dict[str, Any]) -> float:
        return float(intent.get("price") or intent.get("entry_price") or intent.get("latest_price") or 0.0)

    def _amount_base(self, intent: Dict[str, Any]) -> float:
        qty = float(intent.get("qty") or intent.get("amount") or intent.get("base_amount") or 0.0)
        if qty <= 0:
            price = self._price(intent)
            quote = self._amount_quote(intent)
            qty = quote / price if price > 0 else 0.0
        return max(0.0, qty)

    def _amount_quote(self, intent: Dict[str, Any]) -> float:
        quote = float(intent.get("notional_usd") or intent.get("quote_amount") or intent.get("total_amount_quote") or 0.0)
        if quote <= 0:
            qty = float(intent.get("qty") or intent.get("amount") or intent.get("base_amount") or 0.0)
            quote = qty * self._price(intent)
        if quote <= 0:
            quote = float(getattr(self.cfg, "quote_order_size", 0.0) or 0.0)
        return max(0.0, quote)
