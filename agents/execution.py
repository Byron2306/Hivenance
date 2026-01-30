import math
import logging
import ccxt
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceOrderException
from typing import Tuple, Dict, Any, Optional
import json
import requests
from web3 import Web3
import time


def round_step_size(quantity: float, step_size: float) -> float:
    """Rounds down to the nearest step size."""
    if step_size <= 0:
        return quantity
    precision = int(round(-math.log(step_size, 10), 0))
    return math.floor(quantity * (10 ** precision)) / (10 ** precision)


class OrderTracker:
    def __init__(self):
        self.orders = []

    def add_order(self, order: Dict[str, Any]):
        self.orders.append(order)

    def get_open_orders(self):
        return [o for o in self.orders if o.get("status") == "NEW"]

    def update_order_status(self, order_id: str, status: str):
        for o in self.orders:
            if o.get("orderId") == order_id:
                o["status"] = status


class BinanceTrader:
    def __init__(self, client: Client, symbol: str, dry_run: bool, max_position_base: float):
        self.client = client
        self.symbol = symbol
        self.dry_run = dry_run
        self.max_position_base = max_position_base
        self.order_tracker = OrderTracker()

        # Infer base/quote assets from symbol info
        info = self.client.get_symbol_info(symbol)
        if not info:
            raise RuntimeError(f"Unknown symbol: {symbol}")
        self.base_asset = info["baseAsset"]
        self.quote_asset = info["quoteAsset"]
        self.filters = {f["filterType"]: f for f in info["filters"]}

    def _get_step_size(self) -> float:
        lot = self.filters.get("LOT_SIZE")
        return float(lot["stepSize"]) if lot else 0.0

    def _get_tick_size(self) -> float:
        price_filter = self.filters.get("PRICE_FILTER")
        return float(price_filter["tickSize"]) if price_filter else 0.0

    def balances(self) -> Tuple[float, float]:
        base_free = float(self.client.get_asset_balance(asset=self.base_asset)["free"])
        quote_free = float(self.client.get_asset_balance(asset=self.quote_asset)["free"])
        return base_free, quote_free

    def place_order(self, side: str, order_type: str, quantity: Optional[float] = None, quote_quantity: Optional[float] = None, price: Optional[float] = None, stop_price: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """
        Place an order: MARKET, LIMIT, STOP_LOSS_LIMIT
        """
        if self.dry_run:
            logging.info(f"[DRY_RUN] {side} {order_type} {self.symbol} qty={quantity} quote_qty={quote_quantity} price={price} stop={stop_price}")
            return {"orderId": "dry_run", "status": "FILLED", "side": side, "type": order_type}

        try:
            if order_type == "MARKET":
                if side == "BUY" and quote_quantity:
                    order = self.client.order_market_buy(symbol=self.symbol, quoteOrderQty=quote_quantity)
                elif side == "SELL" and quantity:
                    order = self.client.order_market_sell(symbol=self.symbol, quantity=quantity)
                else:
                    logging.error("Invalid MARKET order params")
                    return None
            elif order_type == "LIMIT":
                if not price or not quantity:
                    logging.error("LIMIT order requires price and quantity")
                    return None
                order = self.client.create_order(symbol=self.symbol, side=side, type="LIMIT", timeInForce="GTC", quantity=quantity, price=price)
            elif order_type == "STOP_LOSS_LIMIT":
                if not price or not stop_price or not quantity:
                    logging.error("STOP_LOSS_LIMIT order requires price, stop_price, and quantity")
                    return None
                order = self.client.create_order(symbol=self.symbol, side=side, type="STOP_LOSS_LIMIT", timeInForce="GTC", quantity=quantity, price=price, stopPrice=stop_price)
            else:
                logging.error(f"Unsupported order type: {order_type}")
                return None

            self.order_tracker.add_order(order)
            logging.info(f"{side} {order_type} order placed: {order}")
            return order
        except (BinanceAPIException, BinanceOrderException) as e:
            logging.error(f"{side} {order_type} failed: {e}")
            return None

    def buy_market_quote(self, quote_amount: float) -> Optional[Dict[str, Any]]:
        return self.place_order("BUY", "MARKET", quote_quantity=quote_amount)

    def sell_market_base(self, base_qty: float) -> Optional[Dict[str, Any]]:
        step = self._get_step_size()
        qty = round_step_size(base_qty, step)
        if qty <= 0:
            logging.info("Sell qty rounded to 0; skipping.")
            return None
        return self.place_order("SELL", "MARKET", quantity=qty)

    def buy_limit(self, quantity: float, price: float) -> Optional[Dict[str, Any]]:
        tick = self._get_tick_size()
        price = round(price / tick) * tick
        return self.place_order("BUY", "LIMIT", quantity=quantity, price=price)

    def sell_limit(self, quantity: float, price: float) -> Optional[Dict[str, Any]]:
        tick = self._get_tick_size()
        price = round(price / tick) * tick
        return self.place_order("SELL", "LIMIT", quantity=quantity, price=price)

    def stop_loss_sell(self, quantity: float, stop_price: float, limit_price: float) -> Optional[Dict[str, Any]]:
        return self.place_order("SELL", "STOP_LOSS_LIMIT", quantity=quantity, price=limit_price, stop_price=stop_price)

    def check_order_status(self, order_id: str) -> Optional[Dict[str, Any]]:
        try:
            order = self.client.get_order(symbol=self.symbol, orderId=order_id)
            self.order_tracker.update_order_status(order_id, order["status"])
            return order
        except Exception as e:
            logging.error(f"Error checking order {order_id}: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        try:
            result = self.client.cancel_order(symbol=self.symbol, orderId=order_id)
            self.order_tracker.update_order_status(order_id, "CANCELED")
            logging.info(f"Order {order_id} canceled")
            return True
        except Exception as e:
            logging.error(f"Error canceling order {order_id}: {e}")
            return False


# Placeholder for DEX execution
class DexTrader:
    def __init__(self, web3_provider: str, private_key: str, uniswap_router_address: str):
        self.w3 = Web3(Web3.HTTPProvider(web3_provider))
        self.account = self.w3.eth.account.from_key(private_key)
        self.router = self.w3.eth.contract(address=uniswap_router_address, abi=[])  # Need Uniswap ABI

    def swap(self, token_in: str, token_out: str, amount_in: int) -> str:
        # Implement Uniswap swap
        # This is a placeholder
        logging.info(f"[DEX] Swapping {amount_in} {token_in} for {token_out}")
        return "tx_hash_placeholder"


# -------- On-chain execution via 1inch (tx building only; signing happens in wallet) --------
ERC20_MIN_ABI = json.loads("""
[
  {"constant":true,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"},
  {"constant":true,"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"type":"function"},
  {"constant":true,"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"type":"function"}
]
""")


class DexExecutionAgent:
    def __init__(self, cfg: Any, coordinator: Optional[Any] = None):
        self.coordinator = coordinator
        self.cfg = cfg
        self.exchange = "1inch"
        self.venue = "DEX"
        self.symbol = getattr(cfg, "symbol", "ETH/USDT")
        self.base_asset, self.quote_asset = (self.symbol.split("/") + ["USDT"])[:2]
        self.wallet_address = getattr(cfg, "watch_address", None)
        self.chain_id = int(getattr(cfg, "onchain_chain_id", 1) or 1)
        # Optional L2 preference / forced chain override
        try:
            force_chain = getattr(cfg, "onchain_force_chain_id", None)
            force_base = bool(getattr(cfg, "onchain_force_base", False))
            prefer_l2 = bool(getattr(cfg, "onchain_prefer_l2", False))
            l2_chain = int(getattr(cfg, "onchain_l2_chain_id", 8453) or 8453)
            if force_chain:
                self.chain_id = int(force_chain)
            elif force_base:
                self.chain_id = 8453
            elif prefer_l2 and self.chain_id == 1:
                self.chain_id = l2_chain
        except Exception:
            pass
        self.slippage_bps = int(getattr(cfg, "onchain_slippage_bps", 50) or 50)
        self.api_key = getattr(cfg, "oneinch_api_key", None)
        self.web3_rpc_url = getattr(cfg, "web3_rpc_url", None)
        self._pending_swap: Optional[Dict[str, Any]] = None
        self._last_tx_hash: Optional[str] = None
        self._last_error: Optional[Dict[str, Any]] = None
        self._w3 = None
        if self.web3_rpc_url:
            try:
                self._w3 = Web3(Web3.HTTPProvider(self.web3_rpc_url, request_kwargs={"timeout": 6}))
            except Exception:
                self._w3 = None

        # Mainnet token map (1inch uses 0xEeee for native ETH)
        self._token_addr = {
            "ETH": "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
            "WETH": "0xC02aaA39b223FE8D0A0E5C4F27eAD9083C756Cc2",
            "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
            "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
            "DAI": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
            # Treat USD as USDC for on-chain swaps
            "USD": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        }
        self._token_decimals = {
            "ETH": 18, "WETH": 18, "USDT": 6, "USDC": 6, "DAI": 18, "USD": 6
        }
        # Extend token map with configured on-chain addresses (e.g., WLD, XCN)
        try:
            extra = getattr(cfg, "onchain_token_addresses", None) or {}
            if isinstance(extra, dict):
                for sym, info in extra.items():
                    if not sym:
                        continue
                    if isinstance(info, dict):
                        addr = info.get("address") or info.get("addr")
                        dec = info.get("decimals")
                    else:
                        addr = info
                        dec = None
                    if addr:
                        self._token_addr[str(sym).upper()] = addr
                        if dec is not None:
                            self._token_decimals[str(sym).upper()] = int(dec)
                # If USDC is configured for this chain, alias USD to the same contract
                try:
                    if "USDC" in self._token_addr:
                        self._token_addr["USD"] = self._token_addr["USDC"]
                        self._token_decimals["USD"] = int(self._token_decimals.get("USDC", 6))
                except Exception:
                    pass
        except Exception:
            pass

    def set_symbol(self, symbol: str):
        """Update the execution agent to target a new symbol."""
        if not symbol:
            return
        self.symbol = symbol
        try:
            if "/" in symbol:
                self.base_asset, self.quote_asset = symbol.split("/")
        except Exception:
            pass

    def _asset_addr(self, asset: str) -> Optional[str]:
        return self._token_addr.get((asset or "").upper())

    def _asset_decimals(self, asset: str) -> int:
        return int(self._token_decimals.get((asset or "").upper(), 18))

    def _to_units(self, asset: str, amount: float) -> int:
        dec = self._asset_decimals(asset)
        return int(max(0, float(amount)) * (10 ** dec))

    def balances(self):
        """Return (base_free, quote_free) from on-chain wallet if possible."""
        base = 0.0
        quote = 0.0
        if not self._w3 or not self.wallet_address:
            return base, quote
        try:
            addr = self._w3.to_checksum_address(self.wallet_address)
            # base
            if self.base_asset.upper() == "ETH":
                base = float(self._w3.from_wei(self._w3.eth.get_balance(addr), "ether"))
            else:
                token_addr = self._asset_addr(self.base_asset)
                if token_addr and token_addr.lower().startswith("0x"):
                    contract = self._w3.eth.contract(address=self._w3.to_checksum_address(token_addr), abi=ERC20_MIN_ABI)
                    raw = contract.functions.balanceOf(addr).call()
                    base = float(raw) / (10 ** self._asset_decimals(self.base_asset))
            # quote
            if self.quote_asset.upper() == "ETH":
                quote = float(self._w3.from_wei(self._w3.eth.get_balance(addr), "ether"))
            else:
                qaddr = self._asset_addr(self.quote_asset)
                if qaddr and qaddr.lower().startswith("0x"):
                    qcontract = self._w3.eth.contract(address=self._w3.to_checksum_address(qaddr), abi=ERC20_MIN_ABI)
                    rawq = qcontract.functions.balanceOf(addr).call()
                    quote = float(rawq) / (10 ** self._asset_decimals(self.quote_asset))
        except Exception:
            pass
        return base, quote

    def get_pending_swap(self) -> Optional[Dict[str, Any]]:
        return self._pending_swap

    def get_last_error(self) -> Optional[Dict[str, Any]]:
        return self._last_error

    def health_snapshot(self) -> Dict[str, Any]:
        pending_ms = 0
        try:
            if self._pending_swap and self._pending_swap.get("ts"):
                pending_ms = int(time.time() * 1000 - int(self._pending_swap.get("ts")))
                if pending_ms > 300000:
                    self._pending_swap = None
                    pending_ms = 0
        except Exception:
            pending_ms = 0
        return {
            "order_unconfirmed_ms": pending_ms,
            "api_failures_60s": 0,
            "last_error": self._last_error,
        }

    def safety_reset(self) -> bool:
        """Clear pending swap state and last error."""
        try:
            self._pending_swap = None
            self._last_error = None
            self._last_tx_hash = None
            return True
        except Exception:
            return False

    def _set_last_error(self, err: Optional[Dict[str, Any]]):
        self._last_error = err

    def _emit_exec(self, payload: Dict[str, Any]):
        try:
            if self.coordinator:
                self.coordinator.share_data('buzz.trade.execution', {
                    "buzz": {"type": "buzz.trade.execution", "source": "EXECUTION", "ts": int(time.time()*1000)},
                    "payload": payload,
                })
        except Exception:
            pass

    def ack_swap(self, tx_hash: str, intent_id: Optional[str] = None, client_order_id: Optional[str] = None):
        self._last_tx_hash = tx_hash
        if self._pending_swap:
            if intent_id and self._pending_swap.get("intent_id") and intent_id != self._pending_swap.get("intent_id"):
                return False
        # emit a submitted execution event for audit/UI
        try:
            if self.coordinator:
                self.coordinator.share_data('buzz.trade.execution', {
                    "buzz": {"type": "buzz.trade.execution", "source": "EXECUTION", "ts": int(time.time()*1000)},
                    "payload": {
                        "status": "SUBMITTED",
                        "venue": self.venue,
                        "tx_hash": tx_hash,
                        "intent_id": intent_id,
                        "client_order_id": client_order_id,
                    }
                })
        except Exception:
            pass
        self._pending_swap = None
        return True

    def _oneinch_swap(self, from_token: str, to_token: str, amount: int) -> Dict[str, Any]:
        if not self.wallet_address:
            raise RuntimeError("Wallet address not configured for on-chain swaps")
        if not self.api_key:
            raise RuntimeError("1inch API key missing")
        slippage = max(0.1, float(self.slippage_bps) / 100.0)  # 50 bps -> 0.5%
        headers = {"Authorization": f"Bearer {self.api_key}"}
        from_addr = self.wallet_address
        urls = [
            (f"https://api.1inch.dev/swap/v6.0/{self.chain_id}/swap", {
                "src": from_token,
                "dst": to_token,
                "amount": str(amount),
                "from": from_addr,
                "slippage": str(slippage),
                "disableEstimate": "true",
            }),
            (f"https://api.1inch.dev/swap/v5.2/{self.chain_id}/swap", {
                "fromTokenAddress": from_token,
                "toTokenAddress": to_token,
                "amount": str(amount),
                "fromAddress": from_addr,
                "slippage": str(slippage),
                "disableEstimate": "true",
            }),
        ]
        last_err = None
        for url, params in urls:
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=12)
                if resp.status_code >= 200 and resp.status_code < 300:
                    return resp.json()
                last_err = f"{resp.status_code}: {resp.text}"
            except Exception as e:
                last_err = str(e)
        raise RuntimeError(f"1inch swap request failed: {last_err}")

    def _request_swap(self, side: str, amount: float, client_order_id: Optional[str], intent_id: Optional[str]) -> Optional[Dict[str, Any]]:
        self._set_last_error(None)
        # Allowlist guard
        try:
            allowed = getattr(self.cfg, "onchain_allowed_pairs", []) or []
            if allowed and self.symbol not in allowed:
                self._emit_exec({
                    "status": "PRECHECK_FAILED",
                    "venue": self.venue,
                    "intent_id": intent_id,
                    "client_order_id": client_order_id,
                    "error": {"class": "SYMBOL_NOT_ALLOWED", "message": f"{self.symbol} not in allowlist"},
                })
                self._set_last_error({"class": "SYMBOL_NOT_ALLOWED", "message": f"{self.symbol} not in allowlist"})
                return None
        except Exception:
            pass
        # Resolve tokens and amounts
        if side == "BUY":
            # spend quote to buy base
            from_token = self._asset_addr(self.quote_asset)
            to_token = self._asset_addr(self.base_asset)
            amount_in = self._to_units(self.quote_asset, float(amount or 0.0))
        else:
            # sell base for quote
            from_token = self._asset_addr(self.base_asset)
            to_token = self._asset_addr(self.quote_asset)
            amount_in = self._to_units(self.base_asset, float(amount or 0.0))
        if not from_token or not to_token:
            logging.error(f"On-chain swap failed: token mapping missing for {self.symbol}")
            self._emit_exec({
                "status": "PRECHECK_FAILED",
                "venue": self.venue,
                "intent_id": intent_id,
                "client_order_id": client_order_id,
                "error": {"class": "TOKEN_MAPPING_MISSING", "message": f"{self.symbol} mapping missing"},
            })
            self._set_last_error({"class": "TOKEN_MAPPING_MISSING", "message": f"{self.symbol} mapping missing"})
            return None
        if amount_in <= 0:
            logging.warning("On-chain swap amount <= 0; skipping.")
            self._emit_exec({
                "status": "PRECHECK_FAILED",
                "venue": self.venue,
                "intent_id": intent_id,
                "client_order_id": client_order_id,
                "error": {"class": "AMOUNT_TOO_LOW", "message": "amount_in <= 0"},
            })
            self._set_last_error({"class": "AMOUNT_TOO_LOW", "message": "amount_in <= 0"})
            return None

        try:
            swap = self._oneinch_swap(from_token, to_token, amount_in)
            tx = swap.get("tx") or {}
            # Ensure tx includes chain id so wallets switch correctly
            if not tx.get("chainId"):
                try:
                    tx["chainId"] = int(self.chain_id)
                except Exception:
                    pass
            if not tx.get("from") and self.wallet_address:
                tx["from"] = self.wallet_address
            # Gas/fee estimation for safety caps
            def _to_int(v):
                try:
                    if isinstance(v, str) and v.startswith("0x"):
                        return int(v, 16)
                    return int(v)
                except Exception:
                    return None
            est_gas = _to_int(swap.get("estimatedGas") or swap.get("gas") or tx.get("gas"))
            gas_price = _to_int(tx.get("gasPrice") or tx.get("maxFeePerGas") or tx.get("maxPriorityFeePerGas"))
            gas_gwei = None
            fee_eth = None
            try:
                if gas_price is not None:
                    gas_gwei = float(gas_price) / 1e9
                if est_gas is not None and gas_price is not None:
                    fee_eth = (float(est_gas) * float(gas_price)) / 1e18
            except Exception:
                gas_gwei = None
                fee_eth = None
            # Enforce caps if configured
            try:
                max_gas_gwei = float(getattr(self.cfg, "onchain_max_gas_gwei", 0.0) or 0.0)
                max_fee_eth = float(getattr(self.cfg, "onchain_max_gas_eth", 0.0) or 0.0)
                if not max_fee_eth:
                    max_fee_eth = float(getattr(self.cfg, "onchain_max_fee_eth", 0.0) or 0.0)
                max_fee_usd = float(getattr(self.cfg, "onchain_max_gas_usd", 0.0) or 0.0)
                fee_usd = None
                try:
                    if fee_eth is not None and self.coordinator and hasattr(self.coordinator, "get_shared_data"):
                        latest_price = self.coordinator.get_shared_data("latest_price")
                        if latest_price and str(self.base_asset).upper() == "ETH":
                            fee_usd = float(fee_eth) * float(latest_price)
                except Exception:
                    fee_usd = None
                if gas_gwei is not None and max_gas_gwei and gas_gwei > max_gas_gwei:
                    self._emit_exec({
                        "status": "PRECHECK_FAILED",
                        "venue": self.venue,
                        "intent_id": intent_id,
                        "client_order_id": client_order_id,
                        "error": {"class": "GAS_PRICE_TOO_HIGH", "message": f"gas_gwei {gas_gwei:.2f} > cap {max_gas_gwei:.2f}"},
                    })
                    self._set_last_error({"class": "GAS_TOO_HIGH", "gas_gwei": gas_gwei, "cap_gwei": max_gas_gwei})
                    return None
                if fee_eth is not None and max_fee_eth and fee_eth > max_fee_eth:
                    self._emit_exec({
                        "status": "PRECHECK_FAILED",
                        "venue": self.venue,
                        "intent_id": intent_id,
                        "client_order_id": client_order_id,
                        "error": {"class": "GAS_FEE_TOO_HIGH", "message": f"fee_eth {fee_eth:.6f} > cap {max_fee_eth:.6f}"},
                    })
                    self._set_last_error({"class": "GAS_TOO_HIGH", "fee_eth": fee_eth, "cap_eth": max_fee_eth})
                    return None
                if fee_usd is not None and max_fee_usd and fee_usd > max_fee_usd:
                    self._emit_exec({
                        "status": "PRECHECK_FAILED",
                        "venue": self.venue,
                        "intent_id": intent_id,
                        "client_order_id": client_order_id,
                        "error": {"class": "GAS_FEE_TOO_HIGH", "message": f"fee_usd {fee_usd:.4f} > cap {max_fee_usd:.4f}"},
                    })
                    self._set_last_error({"class": "GAS_TOO_HIGH", "fee_usd": fee_usd, "cap_usd": max_fee_usd})
                    return None
            except Exception:
                pass
            # Build preview info for UI
            preview = {}
            try:
                ft = swap.get("fromToken") or {}
                tt = swap.get("toToken") or {}
                from_amt = swap.get("fromTokenAmount") or swap.get("fromAmount") or amount_in
                to_amt = swap.get("toTokenAmount") or swap.get("toAmount")
                from_sym = (ft.get("symbol") or (self.base_asset if side == "SELL" else self.quote_asset))
                to_sym = (tt.get("symbol") or (self.quote_asset if side == "SELL" else self.base_asset))
                preview = {
                    "from_symbol": from_sym,
                    "to_symbol": to_sym,
                    "from_amount": from_amt,
                    "to_amount": to_amt,
                    "from_decimals": ft.get("decimals") or self._asset_decimals(from_sym or ""),
                    "to_decimals": tt.get("decimals") or self._asset_decimals(to_sym or ""),
                    "estimated_gas": est_gas,
                    "gas_price_gwei": gas_gwei,
                    "estimated_fee_eth": fee_eth,
                }
            except Exception:
                preview = {}
            pending = {
                "intent_id": intent_id,
                "client_order_id": client_order_id,
                "side": side,
                "symbol": self.symbol,
                "from_token": from_token,
                "to_token": to_token,
                "amount_in": amount_in,
                "tx": tx,
                "preview": preview,
                "ts": int(time.time()*1000),
            }
            self._pending_swap = pending
            # Emit a request so UI/audit can show it
            try:
                if self.coordinator:
                    self.coordinator.share_data('buzz.trade.request', {
                        "buzz": {"type": "buzz.trade.request", "source": "EXECUTION", "ts": int(time.time()*1000)},
                        "payload": {
                            "client_order_id": client_order_id,
                            "intent_id": intent_id,
                            "venue": self.venue,
                            "symbol": self.symbol,
                            "side": side,
                            "order_type": "SWAP",
                            "status": "REQUESTED",
                        }
                    })
                    self.coordinator.share_data('buzz.trade.execution', {
                        "buzz": {"type": "buzz.trade.execution", "source": "EXECUTION", "ts": int(time.time()*1000)},
                        "payload": {
                            "status": "PENDING_SIGNATURE",
                            "venue": self.venue,
                            "intent_id": intent_id,
                            "client_order_id": client_order_id,
                        }
                    })
            except Exception:
                pass
            return pending
        except Exception as e:
            logging.error(f"On-chain swap request failed: {e}")
            self._set_last_error({"class": "SWAP_FAILED", "message": str(e)})
            return None

    def buy_market_quote(self, quote_amount: float, client_order_id: Optional[str] = None, intent_id: Optional[str] = None, ts: Optional[int] = None, **kwargs):
        return self._request_swap("BUY", quote_amount, client_order_id, intent_id)

    def sell_market_base(self, base_qty: float, client_order_id: Optional[str] = None, intent_id: Optional[str] = None, ts: Optional[int] = None, **kwargs):
        return self._request_swap("SELL", base_qty, client_order_id, intent_id)


class KrakenTrader:
    """
    Minimal trading adapter for Kraken via ccxt.
    Uses base-amount orders (ccxt standard). For BUY, quote_amount is converted using last price.
    """

    def __init__(self, client: ccxt.kraken, symbol: str, dry_run: bool, max_position_base: float):
        self.client = client
        self.symbol = symbol  # e.g., "XBT/USDT"
        self.dry_run = dry_run
        self.max_position_base = max_position_base
        self.order_tracker = OrderTracker()

        # Infer base/quote from symbol "BASE/QUOTE"
        if "/" not in symbol:
            raise RuntimeError("Kraken symbol must be like 'XBT/USDT'")
        self.base_asset, self.quote_asset = symbol.split("/")

    def balances(self) -> Tuple[float, float]:
        bal = self.client.fetch_balance()
        base_free = float(bal.get(self.base_asset, {}).get("free", 0))
        quote_free = float(bal.get(self.quote_asset, {}).get("free", 0))
        return base_free, quote_free

    def _place(self, side: str, amount: float) -> Optional[Dict[str, Any]]:
        if amount <= 0:
            logging.info("Order amount <= 0; skipping.")
            return None
        if self.dry_run:
            logging.info(f"[DRY_RUN] {side} {self.symbol} amount={amount}")
            return {"orderId": "dry_run", "status": "FILLED", "side": side, "type": "MARKET"}
        try:
            if side == "BUY":
                order = self.client.create_market_buy_order(self.symbol, amount)
            else:
                order = self.client.create_market_sell_order(self.symbol, amount)
            self.order_tracker.add_order(order)
            logging.info(f"{side} MARKET order placed: {order}")
            return order
        except Exception as e:
            logging.error(f"{side} MARKET failed: {e}")
            return None

    def buy_market_quote(self, quote_amount: float) -> Optional[Dict[str, Any]]:
        try:
            price = float(self.client.fetch_ticker(self.symbol)["last"])
        except Exception as e:
            logging.error(f"Could not fetch price for BUY: {e}")
            return None
        amount = quote_amount / price
        return self._place("BUY", amount)

    def sell_market_base(self, base_qty: float) -> Optional[Dict[str, Any]]:
        qty = min(base_qty, self.max_position_base)
        return self._place("SELL", qty)


class ExecutionAgent:
    """Wrapper around a low-level trader that provides deterministic, paranoid execution.

    It performs prechecks (kill switch, balances, spread, staleness), enforces idempotency
    by `client_order_id`, emits structured execution events via coordinator.share_data,
    and exposes the same convenience methods as the underlying trader.
    """
    def __init__(self, trader: Any, coordinator: Optional[Any] = None, dry_run: bool = False,
                 min_notional: float = 1.0, spread_threshold_pct: float = 0.0015,
                 freshness_sec: int = 3):
        self.trader = trader
        self.coordinator = coordinator
        self.dry_run = dry_run
        self.min_notional = min_notional
        self.spread_threshold_pct = spread_threshold_pct
        self.freshness_sec = freshness_sec
        self._client_orders: Dict[str, Dict[str, Any]] = {}  # idempotency store
        self._api_failures: Dict[str, float] = {}
        self._order_sent_ts: Dict[str, float] = {}
        self._last_confirm_ms: Optional[int] = None
        # expose base/quote assets if the underlying trader has them
        self.base_asset = getattr(trader, "base_asset", None)
        self.quote_asset = getattr(trader, "quote_asset", None)


    def cancel_order(self, order_id: str) -> bool:
        try:
            if hasattr(self.trader, 'cancel_order'):
                return bool(self.trader.cancel_order(order_id))
        except Exception:
            logging.exception('ExecutionAgent.cancel_order failed')
        return False

    def _emit(self, payload: Dict[str, Any]):
        evt = {"buzz": {"type": "buzz.trade.execution", "source": "EXECUTION"}, "payload": payload}
        try:
            if self.coordinator:
                # store on coordinator.shared data for consumers
                self.coordinator.share_data('buzz.trade.execution', evt)
                # also call coordinator handler directly if available for immediate processing
                try:
                    if hasattr(self.coordinator, 'on_trade_execution'):
                        # pass the event dict
                        self.coordinator.on_trade_execution(evt)
                except Exception:
                    pass
        except Exception:
            pass
        # update confirmation latency if this payload is a fill
        try:
            status = (payload or {}).get("status")
            cid = (payload or {}).get("client_order_id")
            if status in ("FILLED", "filled") and cid:
                sent_ts = self._order_sent_ts.pop(cid, None)
                if sent_ts:
                    self._last_confirm_ms = int((time.time() - sent_ts) * 1000)
        except Exception:
            pass

    def _record_api_failure(self):
        try:
            key = str(time.time())
            self._api_failures[key] = time.time()
        except Exception:
            pass

    def _prune_failures(self, window_sec: int = 60):
        try:
            cutoff = time.time() - window_sec
            for k, ts in list(self._api_failures.items()):
                if ts < cutoff:
                    self._api_failures.pop(k, None)
        except Exception:
            pass

    def health_snapshot(self) -> Dict[str, Any]:
        self._prune_failures(60)
        pending_ms = 0
        try:
            # if any pending order, use oldest
            if self._order_sent_ts:
                oldest = min(self._order_sent_ts.values())
                pending_ms = int((time.time() - oldest) * 1000)
                if pending_ms > 300000:
                    self._order_sent_ts.clear()
                    pending_ms = 0
        except Exception:
            pending_ms = 0
        return {
            "order_unconfirmed_ms": pending_ms,
            "api_failures_60s": len(self._api_failures),
            "last_confirm_ms": self._last_confirm_ms,
        }

    def safety_reset(self) -> bool:
        """Clear execution health counters and pending orders."""
        try:
            self._client_orders.clear()
            self._api_failures.clear()
            self._order_sent_ts.clear()
            self._last_confirm_ms = None
            # Also reset underlying trader if it supports it
            try:
                if hasattr(self.trader, "safety_reset"):
                    self.trader.safety_reset()
            except Exception:
                pass
            return True
        except Exception:
            return False

    def _precheck(self, req: Dict[str, Any]) -> Tuple[bool, Optional[Dict[str, Any]]]:
        # Kill switch
        try:
            ks = self.coordinator.agents.get('kill_switch') if self.coordinator and getattr(self.coordinator, 'agents', None) else None
            if ks and ks.is_paused():
                return False, {"status": "PRECHECK_FAILED", "error": {"class": "KILL_SWITCH", "message": "kill switch is paused"}}
        except Exception:
            pass

        # Freshness
        try:
            ts = req.get('ts')
            if ts:
                age = abs(time.time() - (float(ts) / 1000.0))
                if req.get('order_type') == 'MARKET' and age > self.freshness_sec:
                    return False, {"status": "PRECHECK_FAILED", "error": {"class": "STALE_REQUEST", "message": "request too old"}}
        except Exception:
            pass

        # Spread guard
        try:
            md = None
            if self.coordinator:
                md = self.coordinator.get_shared_data('market.data') or self.coordinator.get_shared_data('latest_price')
            sp = None
            if isinstance(md, dict):
                sp = md.get('spread_pct')
            if sp is not None:
                try:
                    spv = float(sp)
                    if spv > self.spread_threshold_pct:
                        return False, {"status": "PRECHECK_FAILED", "error": {"class": "SPREAD_TOO_WIDE", "message": f"spread_pct {spv} > {self.spread_threshold_pct}"}}
                except Exception:
                    pass
        except Exception:
            pass

        # Balance guard (best-effort using coordinator wallet snapshot)
        try:
            wb = self.coordinator.get_shared_data('wallet.balance') if self.coordinator else None
            if wb and isinstance(wb, dict) and wb.get('balances'):
                balances = {b.get('asset'): float(b.get('free') or 0) for b in wb.get('balances', [])}
                side = req.get('side')
                if side == 'BUY':
                    quote = req.get('quote') or req.get('quote_amount') or req.get('qty')
                    # need latest price to estimate
                    price = None
                    if isinstance(self.coordinator.get_shared_data('latest_price'), (int, float)):
                        price = float(self.coordinator.get_shared_data('latest_price'))
                    if price and req.get('qty') and not req.get('quote'):
                        quote = float(req.get('qty')) * price
                    if quote and balances.get('USDT', 0) < float(quote):
                        return False, {"status": "PRECHECK_FAILED", "error": {"class": "INSUFFICIENT_FUNDS", "message": "Not enough quote balance"}}
                elif side == 'SELL':
                    base = req.get('qty')
                    base_asset = getattr(self.trader, 'base_asset', None)
                    if base_asset and balances.get(base_asset, 0) < float(base or 0):
                        return False, {"status": "PRECHECK_FAILED", "error": {"class": "INSUFFICIENT_FUNDS", "message": "Not enough base balance"}}
        except Exception:
            pass

        # Min notional
        try:
            if req.get('order_type') == 'MARKET':
                qty = req.get('qty') or req.get('quote') or req.get('quote_amount')
                if qty and float(qty) < self.min_notional:
                    return False, {"status": "PRECHECK_FAILED", "error": {"class": "MIN_NOTIONAL", "message": "quantity below min notional"}}
        except Exception:
            pass

        return True, None

    def _idempotent_check(self, client_order_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not client_order_id:
            return None
        return self._client_orders.get(client_order_id)

    def buy_market_quote(self, quote_amount: float, client_order_id: Optional[str] = None, intent_id: Optional[str] = None, ts: Optional[int] = None, **kwargs) -> Optional[Dict[str, Any]]:
        req = {"client_order_id": client_order_id, "intent_id": intent_id, "side": "BUY", "order_type": "MARKET", "quote": quote_amount, "ts": ts or int(time.time() * 1000)}
        # idempotency
        prev = self._idempotent_check(client_order_id)
        if prev:
            # re-emit latest known
            self._emit(prev)
            return prev.get('order')

        # ACK
        ack = {"client_order_id": client_order_id, "status": "RECEIVED", "venue": getattr(self.trader, 'exchange', None) or getattr(self.trader, 'client', None) and 'binance'}
        self._emit(ack)

        ok, fail = self._precheck(req)
        if not ok:
            resp = {**req, **(fail or {})}
            self._client_orders[client_order_id or str(time.time())] = {"status": resp.get('status'), "order": None}
            self._emit(resp)
            return None

        # Place order
        try:
            order = self.trader.buy_market_quote(quote_amount)
        except Exception as e:
            order = None
            self._record_api_failure()
            logging.exception(f"Execution place order failed: {e}")

        if order:
            order_id = order.get('orderId') or order.get('id') or 'unknown'
            if client_order_id:
                self._order_sent_ts[client_order_id] = time.time()
            placed = {"client_order_id": client_order_id, "intent_id": intent_id, "order_id": order_id, "status": "PLACED", "filled_qty": order.get('executedQty') or order.get('filledQty') or 0.0, "avg_price": order.get('avgPrice') or order.get('price') or None}
            self._client_orders[client_order_id or order_id] = {"status": placed['status'], "order": order}
            self._emit(placed)
            # If immediate FILLED
            if order.get('status') == 'FILLED' or order.get('status') == 'filled':
                filled = {**placed, "status": "FILLED"}
                self._emit(filled)
            return order
        else:
            err = {"client_order_id": client_order_id, "intent_id": intent_id, "status": "ERROR", "error": {"class": "ORDER_FAILED", "message": "placement failed"}}
            self._emit(err)
            return None

    def sell_market_base(self, base_qty: float, client_order_id: Optional[str] = None, intent_id: Optional[str] = None, ts: Optional[int] = None, **kwargs) -> Optional[Dict[str, Any]]:
        req = {"client_order_id": client_order_id, "intent_id": intent_id, "side": "SELL", "order_type": "MARKET", "qty": base_qty, "ts": ts or int(time.time() * 1000)}
        prev = self._idempotent_check(client_order_id)
        if prev:
            self._emit(prev)
            return prev.get('order')

        ack = {"client_order_id": client_order_id, "status": "RECEIVED"}
        self._emit(ack)

        ok, fail = self._precheck(req)
        if not ok:
            resp = {**req, **(fail or {})}
            self._client_orders[client_order_id or str(time.time())] = {"status": resp.get('status'), "order": None}
            self._emit(resp)
            return None

        try:
            order = self.trader.sell_market_base(base_qty)
        except Exception as e:
            order = None
            self._record_api_failure()
            logging.exception(f"Execution place order failed: {e}")

        if order:
            order_id = order.get('orderId') or order.get('id') or 'unknown'
            if client_order_id:
                self._order_sent_ts[client_order_id] = time.time()
            placed = {"client_order_id": client_order_id, "intent_id": intent_id, "order_id": order_id, "status": "PLACED", "filled_qty": order.get('executedQty') or order.get('filledQty') or 0.0, "avg_price": order.get('avgPrice') or order.get('price') or None}
            self._client_orders[client_order_id or order_id] = {"status": placed['status'], "order": order}
            self._emit(placed)
            if order.get('status') == 'FILLED' or order.get('status') == 'filled':
                filled = {**placed, "status": "FILLED"}
                self._emit(filled)
            return order
        else:
            err = {"client_order_id": client_order_id, "intent_id": intent_id, "status": "ERROR", "error": {"class": "ORDER_FAILED", "message": "placement failed"}}
            self._emit(err)
            return None
