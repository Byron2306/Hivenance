import json
import requests
import threading
import time
import logging
from web3 import Web3
from typing import Optional, List, Dict, Any


ERC20_MIN_ABI = json.loads("""
[
  {"constant":true,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"},
  {"constant":true,"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"type":"function"},
  {"constant":true,"inputs":[],"name":"symbol","outputs":[{"name":"","type":"string"}],"type":"function"}
]
""")

# Common mainnet stablecoins for on-chain visibility
MAINNET_STABLES = {
    "USDT": {"address": "0xdAC17F958D2ee523a2206206994597C13D831ec7", "decimals": 6},
    "USDC": {"address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "decimals": 6},
    "DAI": {"address": "0x6B175474E89094C44Da98b954EedeAC495271d0F", "decimals": 18},
}


class WalletMonitor:
    def __init__(
        self,
        rpc_url: str,
        watch_address: str,
        erc20_token_address: Optional[str] = None,
        etherscan_api_key: Optional[str] = None,
        exchange_client: Optional[Any] = None,
        execution_agent: Optional[Any] = None,
        coordinator: Optional[Any] = None,
        poll_seconds: int = 5,
        rpc_timeout: int = 5,
        extra_token_addresses: Optional[Dict[str, Dict[str, Any]]] = None,
        multichain_watch: Optional[List[Dict[str, Any]]] = None,
    ):
        # Use a short RPC timeout so UI startup can't hang on a slow/unreachable endpoint.
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": rpc_timeout}))
        if not self.w3.is_connected():
            raise RuntimeError("Web3 provider not connected. Check WEB3_RPC_URL.")
        self.addr = self.w3.to_checksum_address(watch_address)
        self.etherscan_key = etherscan_api_key
        self.last_tx_hash = None  # To track new transactions
        self.exchange_client = exchange_client
        self.execution_agent = execution_agent
        self.coordinator = coordinator
        self.poll_seconds = poll_seconds

        self.token = None
        self.token_symbol = None
        self.token_decimals = None
        self.extra_tokens: Dict[str, Dict[str, Any]] = {}
        self.multichain_watch: List[Dict[str, Any]] = multichain_watch or []
        if erc20_token_address:
            taddr = self.w3.to_checksum_address(erc20_token_address)
            self.token = self.w3.eth.contract(address=taddr, abi=ERC20_MIN_ABI)
            try:
                self.token_symbol = self.token.functions.symbol().call()
                self.token_decimals = self.token.functions.decimals().call()
            except Exception:
                self.token_symbol = "ERC20"
                self.token_decimals = 18

        # Optional extra tokens (e.g. stables) for on-chain visibility
        try:
            if extra_token_addresses:
                self.extra_tokens.update(extra_token_addresses)
        except Exception:
            pass
        # If on-chain trading is enabled on mainnet, include common stables
        try:
            if self.coordinator and getattr(self.coordinator, "cfg", None):
                if getattr(self.coordinator.cfg, "onchain_enabled", False) and int(getattr(self.coordinator.cfg, "onchain_chain_id", 1)) == 1:
                    for sym, info in MAINNET_STABLES.items():
                        if sym not in self.extra_tokens:
                            self.extra_tokens[sym] = info
        except Exception:
            pass

        # internal state
        self._last_snapshot: Dict[str, Any] = {}
        self._last_publish_ts = 0
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def eth_balance(self) -> float:
        wei = self.w3.eth.get_balance(self.addr)
        return float(self.w3.from_wei(wei, "ether"))

    def erc20_balance(self) -> Optional[float]:
        if not self.token:
            return None
        raw = self.token.functions.balanceOf(self.addr).call()
        return float(raw) / (10 ** int(self.token_decimals or 18))

    def get_transaction_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Fetch recent transactions using Etherscan API.
        Returns list of transaction dicts.
        """
        if not self.etherscan_key:
            return []
        url = "https://api.etherscan.io/api"
        params = {
            "module": "account",
            "action": "txlist",
            "address": self.addr,
            "startblock": 0,
            "endblock": 99999999,
            "page": 1,
            "offset": limit,
            "sort": "desc",
            "apikey": self.etherscan_key
        }
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get("status") == "1":
                return data.get("result", [])
            else:
                print(f"Etherscan error: {data.get('message')}")
                return []
        except Exception as e:
            print(f"Error fetching transactions: {e}")
            return []

    def detect_new_transactions(self) -> List[Dict[str, Any]]:
        """
        Detect new transactions since last check.
        Returns list of new transactions.
        """
        txs = self.get_transaction_history(20)  # Fetch more to check
        new_txs = []
        for tx in txs:
            if self.last_tx_hash and tx["hash"] == self.last_tx_hash:
                break
            new_txs.append(tx)
        if txs:
            self.last_tx_hash = txs[0]["hash"]  # Update to latest
        return new_txs[::-1]  # Reverse to chronological order

    # --------------------- background polling & publishing ---------------------
    def _run(self):
        while self._running:
            try:
                self._poll_balances()
            except Exception as e:
                logging.exception(f"WalletMonitor poll error: {e}")
            time.sleep(self.poll_seconds)

    def stop(self):
        self._running = False
        try:
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=1)
        except Exception:
            pass

    def _poll_balances(self):
        """Poll exchange (if available) and on-chain balances, publish snapshots on meaningful change."""
        snapshot = {
            "wallet_type": "HYBRID",
            "venue": None,
            "account": None,
            "ts": int(time.time() * 1000),
            "balances": [],
        }
        # Refresh extra token list from current config so new tokens appear without restart
        try:
            if self.coordinator and getattr(self.coordinator, "cfg", None):
                latest = getattr(self.coordinator.cfg, "onchain_token_addresses", None)
                if isinstance(latest, dict):
                    self.extra_tokens = dict(latest)
        except Exception:
            pass

        # 1) CEX balances via execution_agent (preferred), skip if DEX mode (on-chain)
        try:
            if self.execution_agent and hasattr(self.execution_agent, 'balances'):
                dex_mode = False
                try:
                    dex_mode = str(getattr(self.execution_agent, 'venue', '')).upper() == 'DEX' or str(getattr(self.execution_agent, 'exchange', '')).lower() == '1inch'
                except Exception:
                    dex_mode = False
                if dex_mode:
                    snapshot['wallet_type'] = 'DEX'
                    snapshot['venue'] = getattr(self.execution_agent, 'venue', None) or getattr(self.execution_agent, 'exchange', None)
                    raise StopIteration  # skip CEX balances to avoid double-counting
                bal = None
                try:
                    bal = self.execution_agent.balances()
                except Exception:
                    # try direct client methods if present
                    if self.exchange_client and hasattr(self.exchange_client, 'get_account'):
                        try:
                            bal = self.exchange_client.get_account()
                        except Exception:
                            bal = None
                if bal:
                    # normalize expected returns: (base_free, quote_free) or dict
                    if isinstance(bal, (list, tuple)) and len(bal) >= 2:
                        base_free, quote_free = bal[0], bal[1]
                        snapshot['balances'].append({'asset': getattr(self.execution_agent, 'base_asset', 'BASE'), 'free': base_free, 'locked': 0.0})
                        snapshot['balances'].append({'asset': getattr(self.execution_agent, 'quote_asset', 'QUOTE'), 'free': quote_free, 'locked': 0.0})
                    elif isinstance(bal, dict):
                        for asset, info in bal.items():
                            try:
                                free = float(info.get('free', info.get('available', 0)))
                                locked = float(info.get('locked', info.get('reserved', 0)))
                            except Exception:
                                free = info
                                locked = 0.0
                            snapshot['balances'].append({'asset': asset, 'free': free, 'locked': locked})
                    snapshot['wallet_type'] = 'CEX_SPOT'
                    snapshot['venue'] = getattr(self.execution_agent, 'venue', None) or getattr(self.execution_agent, 'exchange', None)
        except Exception:
            pass

        # 2) On-chain balances for ETH/token
        try:
            eth_bal = self.eth_balance()
            snapshot['balances'].append({'asset': 'ETH', 'free': eth_bal, 'locked': 0.0})
            if self.token:
                tok_bal = self.erc20_balance()
                snapshot['balances'].append({'asset': self.token_symbol or 'ERC20', 'free': tok_bal, 'locked': 0.0})
            # extra tokens (stables etc)
            for sym, info in (self.extra_tokens or {}).items():
                try:
                    addr = info.get("address") if isinstance(info, dict) else None
                    if not addr:
                        continue
                    contract = self.w3.eth.contract(address=self.w3.to_checksum_address(addr), abi=ERC20_MIN_ABI)
                    raw = contract.functions.balanceOf(self.addr).call()
                    dec = int(info.get("decimals") or 18) if isinstance(info, dict) else 18
                    bal = float(raw) / (10 ** dec)
                    snapshot['balances'].append({'asset': sym, 'free': bal, 'locked': 0.0})
                except Exception:
                    continue
        except Exception:
            pass

        # Watch-only balances on other EVM chains. Execution remains bound to
        # the configured primary chain; these rows are visibility/risk context.
        try:
            for chain in self.multichain_watch or []:
                if not isinstance(chain, dict) or not chain.get("rpc_url"):
                    continue
                chain_name = str(chain.get("name") or chain.get("chain_id") or "chain")
                chain_id = chain.get("chain_id")
                native_symbol = str(chain.get("native_symbol") or "ETH")
                w3 = Web3(Web3.HTTPProvider(chain.get("rpc_url"), request_kwargs={"timeout": int(chain.get("rpc_timeout", 5) or 5)}))
                if not w3.is_connected():
                    continue
                watch_addr = w3.to_checksum_address(chain.get("watch_address") or self.addr)
                try:
                    native_bal = float(w3.from_wei(w3.eth.get_balance(watch_addr), "ether"))
                    snapshot['balances'].append({
                        'asset': native_symbol,
                        'free': native_bal,
                        'locked': 0.0,
                        'chain': chain_name,
                        'chain_id': chain_id,
                        'watch_only': True,
                    })
                except Exception:
                    pass
                for sym, info in (chain.get("tokens") or {}).items():
                    try:
                        addr = info.get("address") if isinstance(info, dict) else None
                        if not addr:
                            continue
                        contract = w3.eth.contract(address=w3.to_checksum_address(addr), abi=ERC20_MIN_ABI)
                        raw = contract.functions.balanceOf(watch_addr).call()
                        try:
                            dec = int(info.get("decimals")) if isinstance(info, dict) and info.get("decimals") is not None else int(contract.functions.decimals().call())
                        except Exception:
                            dec = 18
                        bal = float(raw) / (10 ** dec)
                        snapshot['balances'].append({
                            'asset': str(sym).upper(),
                            'free': bal,
                            'locked': 0.0,
                            'chain': chain_name,
                            'chain_id': chain_id,
                            'address': addr,
                            'watch_only': True,
                        })
                    except Exception:
                        continue
        except Exception:
            pass

        # Deduplicate assets (avoid double-counting on-chain vs execution balances)
        try:
            dex_mode = False
            if self.execution_agent:
                dex_mode = str(getattr(self.execution_agent, 'venue', '')).upper() == 'DEX' or str(getattr(self.execution_agent, 'exchange', '')).lower() == '1inch'
            merged = {}
            for b in snapshot.get('balances', []):
                asset = str(b.get('asset') or '')
                if not asset:
                    continue
                chain = str(b.get('chain') or '')
                key = f"{asset}@{chain}" if chain else asset
                free = float(b.get('free') or 0.0)
                locked = float(b.get('locked') or 0.0)
                if key not in merged:
                    merged[key] = dict(b)
                    merged[key]['free'] = free
                    merged[key]['locked'] = locked
                else:
                    if dex_mode:
                        # In DEX mode, prefer the larger observed value to avoid doubling
                        merged[key]['free'] = max(merged[key]['free'], free)
                        merged[key]['locked'] = max(merged[key]['locked'], locked)
                    else:
                        merged[key]['free'] += free
                        merged[key]['locked'] += locked
            snapshot['balances'] = list(merged.values())
        except Exception:
            pass

        # compute equity estimate if market data available via coordinator
        try:
            latest_price = None
            if self.coordinator:
                latest_price = self.coordinator.get_shared_data('latest_price')
                if isinstance(latest_price, dict) and 'payload' in latest_price:
                    latest_price = latest_price.get('payload')
            # estimate USD equity by summing ETH*price for ETH entries and treating quote assets as USD-like
            est = 0.0
            for b in snapshot['balances']:
                a = b.get('asset', '').upper()
                if a in ('USDT', 'USDC', 'USD'):
                    est += float(b.get('free') or 0) + float(b.get('locked') or 0)
                elif a == 'ETH' and latest_price:
                    est += float(b.get('free') or 0) * float(latest_price)
            if est > 0:
                snapshot['equity_usd_est'] = est
        except Exception:
            pass

        # decide whether to publish: compare to last snapshot
        publish = False
        try:
            if not self._last_snapshot:
                publish = True
            else:
                # simple per-asset change detection
                last_map = {s.get('asset'): float(s.get('free') or 0) for s in self._last_snapshot.get('balances', [])}
                for s in snapshot.get('balances', []):
                    asset = s.get('asset')
                    cur = float(s.get('free') or 0)
                    prev = last_map.get(asset, 0.0)
                    if abs(cur - prev) > max(0.0001, abs(prev) * 0.001):
                        publish = True
                        break
                # heartbeat publish every ~2x poll interval (min 10s)
                heartbeat_sec = max(10, int(self.poll_seconds * 2))
                if not publish and (time.time() - self._last_publish_ts) > heartbeat_sec:
                    publish = True
        except Exception:
            publish = True

        # If we couldn't collect any balances, still publish a heartbeat so
        # downstream agents (KillSwitch/UI) don't treat the wallet as stale.
        if not snapshot.get('balances'):
            snapshot['note'] = 'balance_unavailable'
            publish = True

        if publish:
            self._last_snapshot = snapshot
            self._last_publish_ts = time.time()
            # publish via coordinator if available. Publish both a legacy key and a
            # standardized buzz envelope so other agents (DataStore, KillSwitch) ingest it.
            try:
                if self.coordinator:
                    # legacy simple share for quick UI access
                    try:
                        self.coordinator.share_data('wallet.balance', snapshot)
                    except Exception:
                        pass

                    # standardized buzz envelope for durable agents
                    try:
                        evt = {'buzz': {'type': 'buzz.wallet.balance', 'source': 'WALLET', 'ts': int(time.time()*1000)}, 'payload': snapshot}
                        self.coordinator.share_data('buzz.wallet.balance', evt)
                    except Exception:
                        pass

                    # also store in data_store if present
                    if getattr(self.coordinator, 'agents', None) and self.coordinator.agents.get('data_store'):
                        try:
                            ds = self.coordinator.agents['data_store']
                            ds.store_wallet_balance(snapshot.get('account') or 'primary', 'BALANCES', json.dumps(snapshot))
                        except Exception:
                            pass
            except Exception:
                pass

    def get_snapshot(self) -> Dict[str, Any]:
        """Return last published wallet snapshot (best-effort)."""
        return self._last_snapshot or {}
