from flask import Flask, request, jsonify, redirect, make_response
import threading
import logging
import json
import yaml
import time
import os
import requests
import hmac
import hashlib
import html as _html
from datetime import datetime
from typing import List, Any

ERC20_MIN_ABI = json.loads("""
[
  {"constant":true,"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"type":"function"},
  {"constant":true,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"}
]
""")


class UIAgent:
    """
    Lightweight Flask UI that shows live price, recent trades, wallet snapshot, and basic metrics.
    Rebuilt after file corruption.
    """
    def __init__(self, coordinator, host: str = "0.0.0.0", port: int = 5000):
        self.coordinator = coordinator
        self.host = host
        self.port = port
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        static_folder = os.path.join(project_root, "static")
        self.app = Flask(__name__, static_folder=static_folder, static_url_path="/static")
        self.config_path = "config/settings.yaml"
        self.api_keys_path = "config/api_keys.json"
        self.allowed_ips: List[str] = getattr(coordinator.cfg, "allowed_ips", []) or []
        self._cache = {}
        self.thread = None
        self._setup_routes()
    # ------------------------------------------------------------------ routes
    def _setup_routes(self):
        @self.app.before_request
        def _ip_whitelist():
            if request.method == "OPTIONS":
                resp = make_response("", 204)
                resp.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
                resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
                resp.headers["Access-Control-Allow-Headers"] = request.headers.get("Access-Control-Request-Headers", "Content-Type")
                return resp
            # Canonicalize host to avoid split caches (localhost vs 127.0.0.1)
            try:
                host = request.host or ""
                if host.startswith(f"localhost:{self.port}") or host.startswith(f"0.0.0.0:{self.port}"):
                    return redirect(f"http://127.0.0.1:{self.port}{request.full_path}")
            except Exception:
                pass
            if not self.allowed_ips:
                return
            remote = request.remote_addr
            if remote in ("127.0.0.1", "::1"):
                return
            if remote not in self.allowed_ips:
                logging.warning(f"Blocked UI request from {remote}")
                return ("Forbidden", 403)

        @self.app.after_request
        def _no_cache(resp):
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Access-Control-Allow-Origin"] = request.headers.get("Origin", "*")
            resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = request.headers.get("Access-Control-Request-Headers", "Content-Type")
            return resp

        @self.app.route("/")
        def dashboard():
            return self._render_dashboard()

        @self.app.route("/swarmguard")
        def swarmguard_page():
            return self._render_swarmguard_page()

        @self.app.route("/buzz")
        def buzz_page():
            return self._render_buzz_page()

        @self.app.route("/favicon.ico")
        def favicon():
            return ("", 204)

        @self.app.route("/price.json")
        def price_json():
            now = time.time()
            ttl = 2.0
            cached = self._cache.get("price_json")
            if cached and now - cached["ts"] < ttl:
                return jsonify(cached["val"])
            labels, prices = self._price_series(limit=120)
            payload = {"labels": labels, "prices": prices}
            self._cache["price_json"] = {"ts": now, "val": payload}
            return jsonify(payload)

        @self.app.route("/price_series.json")
        def price_series_json():
            try:
                symbol = (request.args.get("symbol") or "").strip()
                if not symbol:
                    return jsonify({"error": "missing_symbol"}), 400
                try:
                    limit = int(request.args.get("limit") or 120)
                except Exception:
                    limit = 120
                key = f"price_series:{symbol}:{limit}"
                now = time.time()
                ttl = 5.0
                cached = self._cache.get(key)
                if cached and now - cached["ts"] < ttl:
                    return jsonify(cached["val"])
                labels, prices = self._price_series_for(symbol, limit=limit)
                payload = {"symbol": symbol, "labels": labels, "prices": prices}
                self._cache[key] = {"ts": now, "val": payload}
                return jsonify(payload)
            except Exception as e:
                logging.exception("price_series.json error")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/metrics.json")
        def metrics_json():
            now = time.time()
            ttl = 3.0
            cached = self._cache.get("metrics_json")
            if cached and now - cached["ts"] < ttl:
                return jsonify(cached["val"])
            data = self._collect_metrics()
            self._cache["metrics_json"] = {"ts": now, "val": data}
            return jsonify(data)

        @self.app.route("/market_snapshot.json")
        def market_snapshot_json():
            try:
                payload = self._get_market_snapshot()
                return jsonify(payload)
            except Exception as e:
                logging.exception("market_snapshot.json error")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/tape.json")
        def tape_json():
            try:
                now = time.time()
                ttl = 5.0
                cached = self._cache.get("tape_json")
                if cached and now - cached["ts"] < ttl:
                    return jsonify(cached["val"])
                trades = self._get_market_tape(limit=100)
                payload = {"trades": trades}
                self._cache["tape_json"] = {"ts": now, "val": payload}
                return jsonify(payload)
            except Exception as e:
                logging.exception("tape.json error")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/wallet.json")
        def wallet_json():
            try:
                now = time.time()
                ttl = 5.0
                cached = self._cache.get("wallet_json")
                if cached and now - cached["ts"] < ttl:
                    return jsonify(cached["val"])

                wallet = self.coordinator.agents.get("wallet")
                if not wallet:
                    return jsonify({"error": "wallet_agent_disabled"}), 400

                latency_ms = None
                ok = False
                start = time.time()
                try:
                    wallet.w3.eth.block_number
                    ok = True
                    latency_ms = int((time.time() - start) * 1000)
                except Exception:
                    ok = False

                try:
                    eth_bal = wallet.eth_balance()
                except Exception:
                    eth_bal = None
                tok_bal = None
                tok_symbol = getattr(wallet, "token_symbol", None)
                try:
                    tok_bal = wallet.erc20_balance()
                except Exception:
                    tok_bal = None

                try:
                    txs = wallet.get_transaction_history(limit=5)
                except Exception:
                    txs = []

                snapshot = {}
                try:
                    if hasattr(wallet, "get_snapshot"):
                        snapshot = wallet.get_snapshot() or {}
                except Exception:
                    snapshot = {}
                balances = snapshot.get("balances") or []
                # Hydrate missing on-chain token balances from config
                try:
                    balances = self._hydrate_onchain_balances(wallet, balances)
                except Exception:
                    pass
                if not ok and balances:
                    # If we have a recent snapshot, treat wallet as available for UI health.
                    ok = True
                payload = {
                    "address": getattr(wallet, "addr", None) or getattr(wallet, "address", None),
                    "network": {"ok": ok, "latency_ms": latency_ms},
                    "eth": {"balance": eth_bal},
                    "token": {"symbol": tok_symbol, "balance": tok_bal} if tok_symbol else {},
                    "balances": balances,
                    "wallet_type": snapshot.get("wallet_type"),
                    "venue": snapshot.get("venue"),
                    "equity_usd_est": snapshot.get("equity_usd_est"),
                    "txs": txs,
                }
                self._cache["wallet_json"] = {"ts": now, "val": payload}
                return jsonify(payload)
            except Exception as e:
                logging.exception("wallet.json error")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/wallet/save_token", methods=["POST"])
        def wallet_save_token():
            token_addr = (request.form.get("token_address") or "").strip()
            watch_addr = (request.form.get("watch_address") or "").strip()
            api_keys = self._load_api_keys()
            if token_addr:
                api_keys["erc20_token_address"] = token_addr
            if watch_addr:
                api_keys["watch_address"] = watch_addr
            with open(self.api_keys_path, "w") as f:
                json.dump(api_keys, f, indent=2)

            cfg = self._load_config()
            if token_addr:
                cfg["erc20_token_address"] = token_addr
            if watch_addr:
                cfg["watch_address"] = watch_addr
            with open(self.config_path, "w") as f:
                yaml.safe_dump(cfg, f)

            try:
                from main import load_config
                new_cfg = load_config()
                self.coordinator.reload_config(new_cfg)
            except Exception as e:
                logging.warning(f"Reload after wallet save failed: {e}")
            return jsonify({"ok": True, "token": token_addr, "watch": watch_addr})

        @self.app.route("/config", methods=["GET", "POST"])
        def config():
            if request.method == "POST":
                return self._save_config()
            return self._render_config()

        @self.app.route("/buzz/recent")
        def buzz_recent():
            """Return recent buzz messages for Agent Outputs."""
            try:
                limit = 200
                try:
                    limit = int(request.args.get("limit") or 200)
                except Exception:
                    limit = 200
                msgs = self._get_recent_buzz(limit=limit)
                return jsonify({"messages": msgs})
            except Exception as e:
                logging.exception(f"buzz_recent error: {e}")
                return jsonify({"messages": [], "error": str(e)}), 500

        @self.app.route("/decision_chain.json")
        def decision_chain_json():
            try:
                rows = self._get_decision_chain_rows(limit=20)
                return jsonify({"rows": rows})
            except Exception as e:
                logging.exception("decision_chain.json error")
                return jsonify({"rows": [], "error": str(e)}), 500


        @self.app.route("/signals.json")
        def signals_json():
            try:
                rows = self._get_unapproved_signals(limit=20)
                return jsonify({"rows": rows})
            except Exception as e:
                logging.exception("signals.json error")
                return jsonify({"rows": [], "error": str(e)}), 500

        @self.app.route("/regime.json")
        def regime_json():
            try:
                payload = self._latest_buzz_payload("buzz.regime.snapshot") or {}
                return jsonify({"payload": payload})
            except Exception as e:
                logging.exception("regime.json error")
                return jsonify({"payload": {}, "error": str(e)}), 500

        @self.app.route("/council.json")
        def council_json():
            try:
                payload = self._latest_buzz_payload("buzz.council.pack") or {}
                return jsonify({"payload": payload})
            except Exception as e:
                logging.exception("council.json error")
                return jsonify({"payload": {}, "error": str(e)}), 500

        @self.app.route("/governance.json")
        def governance_json():
            try:
                payload = self._latest_buzz_payload("buzz.governance.decision") or {}
                return jsonify({"payload": payload})
            except Exception as e:
                logging.exception("governance.json error")
                return jsonify({"payload": {}, "error": str(e)}), 500

        @self.app.route("/intents.json")
        def intents_json():
            try:
                rows = self._get_intents_rows(limit=30)
                return jsonify({"rows": rows})
            except Exception as e:
                logging.exception("intents.json error")
                return jsonify({"rows": [], "error": str(e)}), 500


        @self.app.route("/intent/detail")
        def intent_detail():
            try:
                intent_id = request.args.get('intent_id')
                if not intent_id:
                    return jsonify({'error': 'intent_id_required'}), 400
                detail = self._get_intent_detail(intent_id)
                return jsonify(detail)
            except Exception as e:
                logging.exception('intent_detail error')
                return jsonify({'error': str(e)}), 500


        @self.app.route("/intent/cancel", methods=["POST"])
        def intent_cancel():
            try:
                data = request.form.to_dict()
                if request.is_json:
                    data.update(request.json or {})
                intent_id = data.get('intent_id')
                if not intent_id:
                    return jsonify({'ok': False, 'error': 'intent_id_required'}), 400
                detail = self._get_intent_detail(intent_id)
                orders = detail.get('orders') or []
                exec_agent = self.coordinator.agents.get('execution') if self.coordinator else None
                canceled = False
                for o in orders:
                    oid = o.get('order_id') or o.get('client_order_id')
                    if oid and exec_agent and hasattr(exec_agent, 'cancel_order'):
                        try:
                            if exec_agent.cancel_order(oid):
                                canceled = True
                        except Exception:
                            logging.exception('cancel_order failed')
                # emit audit/buzz event
                try:
                    evt = {
                        'intent_id': intent_id,
                        'status': 'CANCELED' if canceled else 'NOT_CANCELED',
                        'reason': 'USER_CANCEL',
                    }
                    if self.coordinator:
                        self.coordinator.share_data('buzz.intent.state', evt)
                except Exception:
                    logging.exception('cancel audit emit failed')
                return jsonify({'ok': True, 'canceled': canceled})
            except Exception as e:
                logging.exception('intent_cancel error')
                return jsonify({'ok': False, 'error': str(e)}), 500

            except Exception as e:
                logging.exception('intent_cancel error')
                return jsonify({'ok': False, 'error': str(e)}), 500

        @self.app.route("/risk.json")
        def risk_json():
            try:
                payload = self._get_risk_payload()
                return jsonify(payload)
            except Exception as e:
                logging.exception("risk.json error")
                return jsonify({"state": {}, "metrics": {}, "error": str(e)}), 500

        @self.app.route("/risk_timeline.json")
        def risk_timeline_json():
            try:
                rows = self._get_risk_timeline_rows(limit=20)
                return jsonify({"rows": rows})
            except Exception as e:
                logging.exception("risk_timeline.json error")
                return jsonify({"rows": [], "error": str(e)}), 500

        @self.app.route("/performance.json")
        def performance_json():
            try:
                payload = self._get_performance_payload()
                return jsonify(payload)
            except Exception as e:
                logging.exception("performance.json error")
                return jsonify({"row": {}, "error": str(e)}), 500

        @self.app.route("/analytics.json")
        def analytics_json():
            try:
                evt = self._get_latest_analytics_event() or {}
                return jsonify({
                    "payload": evt.get("payload") or {},
                    "ts": (evt.get("buzz") or {}).get("ts")
                })
            except Exception as e:
                logging.exception("analytics.json error")
                return jsonify({"payload": {}, "error": str(e)}), 500

        @self.app.route("/swarmguard.json")
        def swarmguard_json():
            try:
                payload = self._latest_buzz_payload("buzz.swarmguard.decision") or {}
                return jsonify({"payload": payload})
            except Exception as e:
                logging.exception("swarmguard.json error")
                return jsonify({"payload": {}, "error": str(e)}), 500

        @self.app.route("/cycle.json")
        def cycle_json():
            try:
                payload = {}
                if self.coordinator:
                    # Prefer local cache, then network shared data
                    try:
                        cache = getattr(self.coordinator, "data_cache", {}) or {}
                        payload = cache.get("buzz.cycle.snapshot") or cache.get("buzz.cycle.result") or {}
                    except Exception:
                        payload = {}
                    if not payload:
                        payload = self.coordinator.get_shared_data("buzz.cycle.snapshot") or {}
                        if not payload:
                            payload = self.coordinator.get_shared_data("buzz.cycle.result") or {}
                if not payload and self.coordinator:
                    payload = getattr(self.coordinator, "_buzz_cycle_snapshot", {}) or {}
                return jsonify(payload or {})
            except Exception as e:
                logging.exception("cycle.json error")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/swarmguard/rules")
        def swarmguard_rules():
            try:
                return jsonify(self._read_json_file(getattr(self.coordinator.cfg, "swarmguard_rules_path", "config/swarmguard_rules_v1.json")))
            except Exception as e:
                logging.exception("swarmguard/rules error")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/swarmguard/risk_register")
        def swarmguard_risk_register():
            try:
                return jsonify(self._read_json_file(getattr(self.coordinator.cfg, "swarmguard_risk_register_path", "config/risk_register.json")))
            except Exception as e:
                logging.exception("swarmguard/risk_register error")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/swarmguard/risk_map")
        def swarmguard_risk_map():
            try:
                return jsonify(self._read_json_file(getattr(self.coordinator.cfg, "swarmguard_risk_map_path", "config/risk_agent_control_map.json")))
            except Exception as e:
                logging.exception("swarmguard/risk_map error")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/swarmguard/reset", methods=["POST"])
        def swarmguard_reset():
            try:
                results = {}
                sg = self.coordinator.agents.get("swarmguard") if self.coordinator else None
                if sg and hasattr(sg, "safety_reset"):
                    results["swarmguard"] = bool(sg.safety_reset())
                exec_agent = self.coordinator.agents.get("execution") if self.coordinator else None
                if exec_agent and hasattr(exec_agent, "safety_reset"):
                    results["execution"] = bool(exec_agent.safety_reset())
                ks = self.coordinator.agents.get("kill_switch") if self.coordinator else None
                if ks and hasattr(ks, "safety_reset"):
                    results["kill_switch"] = bool(ks.safety_reset())
                return jsonify({"ok": True, "results": results})
            except Exception as e:
                logging.exception("swarmguard/reset error")
                return jsonify({"ok": False, "error": str(e)}), 500

        @self.app.route("/buzz/status")
        def buzz_status():
            try:
                base_url, account = self._buzz_config()
                if not base_url or not account:
                    return jsonify({"ok": False, "error": "buzz_not_configured"}), 400
                last_err = None
                for b in self._buzz_base_urls():
                    try:
                        url = f"{b.rstrip('/')}/v1/accounts/{account}"
                        resp = requests.get(url, timeout=3)
                        if resp.status_code < 400:
                            return jsonify({"ok": True, "account": resp.json(), "base_url": b})
                        last_err = f"buzzservice_http_{resp.status_code}"
                    except Exception as e:
                        last_err = str(e)
                return jsonify({"ok": False, "error": last_err or "buzzservice_unavailable"}), 502
            except Exception as e:
                logging.exception("buzz/status error")
                return jsonify({"ok": False, "error": str(e)}), 502

        @self.app.route("/buzz/ledger")
        def buzz_ledger():
            try:
                base_url, account = self._buzz_config()
                if not base_url or not account:
                    return jsonify({"ok": False, "error": "buzz_not_configured"}), 400
                try:
                    limit = int(request.args.get("limit") or 25)
                except Exception:
                    limit = 25
                last_err = None
                for b in self._buzz_base_urls():
                    try:
                        url = f"{b.rstrip('/')}/v1/ledger/{account}?limit={limit}"
                        resp = requests.get(url, timeout=3)
                        if resp.status_code < 400:
                            return jsonify({"ok": True, "ledger": resp.json(), "base_url": b})
                        last_err = f"buzzservice_http_{resp.status_code}"
                    except Exception as e:
                        last_err = str(e)
                return jsonify({"ok": False, "error": last_err or "buzzservice_unavailable"}), 502
            except Exception as e:
                logging.exception("buzz/ledger error")
                return jsonify({"ok": False, "error": str(e)}), 502

        @self.app.route("/buzz/leaderboard")
        def buzz_leaderboard():
            try:
                base_url, account = self._buzz_config()
                if not base_url:
                    return jsonify({"ok": False, "error": "buzz_not_configured"}), 400
                accounts = self._buzz_accounts_list()
                if account and account not in accounts:
                    accounts.insert(0, account)
                rows = []
                base_urls = self._buzz_base_urls()
                if not base_urls:
                    return jsonify({"ok": False, "error": "buzz_not_configured"}), 400
                for acct in accounts:
                    try:
                        data = None
                        for b in base_urls:
                            try:
                                url = f"{b.rstrip('/')}/v1/accounts/{acct}"
                                resp = requests.get(url, timeout=3)
                                if resp.status_code < 400:
                                    data = resp.json() or {}
                                    break
                            except Exception:
                                continue
                        if not data:
                            continue
                        avail = int(data.get("available", 0))
                        locked = int(data.get("locked", 0))
                        total = avail + locked

                        # lightweight "volatility": std dev of signed deltas in last N ledger rows
                        series = []
                        for b in base_urls:
                            try:
                                led_url = f"{b.rstrip('/')}/v1/ledger/{acct}?limit=30"
                                led = requests.get(led_url, timeout=3)
                                if led.status_code < 400:
                                    entries = (led.json() or {}).get("entries") or []
                                    for e in entries:
                                        et = (e.get("entry_type") or "").upper()
                                        amt = int(e.get("amount", 0) or 0)
                                        if et in ("LOCK", "SLASH", "DEBIT"):
                                            series.append(-amt)
                                        elif et in ("RELEASE", "CREDIT"):
                                            series.append(amt)
                                    break
                            except Exception:
                                continue
                        vol = 0.0
                        if series:
                            mean = sum(series) / max(1, len(series))
                            var = sum([(x - mean) ** 2 for x in series]) / max(1, len(series))
                            vol = (var ** 0.5)
                        rows.append({
                            "account": acct,
                            "available": avail,
                            "locked": locked,
                            "total": total,
                            "volatility": vol,
                            "series": series[:20],
                            "updated_at": data.get("updated_at"),
                        })
                    except Exception:
                        continue

                rows.sort(key=lambda r: r.get("total", 0), reverse=True)
                return jsonify({"ok": True, "rows": rows})
            except Exception as e:
                logging.exception("buzz/leaderboard error")
                return jsonify({"ok": False, "error": str(e)}), 502

        @self.app.route("/buzz/credit", methods=["POST"])
        def buzz_credit():
            try:
                base_url, account = self._buzz_config()
                if not base_url or not account:
                    return jsonify({"ok": False, "error": "buzz_not_configured"}), 400
                secret = ""
                try:
                    secret = getattr(self.coordinator.cfg, "buzz_shared_secret", "") or ""
                except Exception:
                    secret = ""
                if not secret:
                    return jsonify({"ok": False, "error": "buzz_shared_secret_missing"}), 400

                data = {}
                try:
                    if request.is_json:
                        data = request.get_json() or {}
                    else:
                        data = request.form.to_dict() if request.form else {}
                except Exception:
                    data = {}
                try:
                    amount = int(data.get("amount") or 0)
                except Exception:
                    amount = 0
                if amount <= 0:
                    return jsonify({"ok": False, "error": "invalid_amount"}), 400
                acct = data.get("account") or account
                reason = data.get("reason") or "admin_credit"
                req_id = data.get("request_id") or f"credit-{int(time.time())}"

                payload = {"account": acct, "amount": amount, "reason": reason, "request_id": req_id}
                body = json.dumps(payload).encode("utf-8")
                sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
                headers = {"x-hive-service": "ui_agent", "x-hive-sig": sig, "content-type": "application/json"}

                last_err = None
                for b in self._buzz_base_urls():
                    try:
                        url = f"{b.rstrip('/')}/v1/admin/credit"
                        resp = requests.post(url, data=body, headers=headers, timeout=4)
                        if resp.status_code < 400:
                            return jsonify({"ok": True, "receipt": resp.json(), "base_url": b})
                        last_err = f"buzzservice_http_{resp.status_code}"
                    except Exception as e:
                        last_err = str(e)
                return jsonify({"ok": False, "error": last_err or "buzzservice_unavailable"}), 502
            except Exception as e:
                logging.exception("buzz/credit error")
                return jsonify({"ok": False, "error": str(e)}), 502

        @self.app.route("/override", methods=["GET", "POST"])
        def override_toggle():
            try:
                if request.method == "POST":
                    data = {}
                    try:
                        if request.is_json:
                            data = request.get_json() or {}
                        else:
                            data = request.form.to_dict() if request.form else {}
                    except Exception:
                        data = {}
                    enabled = bool(data.get("enabled", False))
                    reason = data.get("reason", "") or ""
                    try:
                        if self.coordinator and hasattr(self.coordinator, "set_override_request"):
                            self.coordinator.set_override_request(enabled, reason)
                    except Exception:
                        pass
                state = {}
                try:
                    if self.coordinator and hasattr(self.coordinator, "get_override_request"):
                        state = self.coordinator.get_override_request() or {}
                except Exception:
                    state = {}
                return jsonify({"enabled": bool(state.get("enabled")), "reason": state.get("reason", "")})
            except Exception as e:
                logging.exception("override toggle error")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/coin_selection.json")
        def coin_selection_json():
            try:
                payload = self._latest_buzz_payload("buzz.coin.selection") or {}
                return jsonify({"payload": payload})
            except Exception as e:
                logging.exception("coin_selection.json error")
                return jsonify({"payload": {}, "error": str(e)}), 500

        @self.app.route("/autonomy", methods=["GET", "POST"])
        def autonomy_toggle():
            try:
                if request.method == "POST":
                    data = {}
                    try:
                        if request.is_json:
                            data = request.get_json() or {}
                        else:
                            data = request.form.to_dict() if request.form else {}
                    except Exception:
                        data = {}
                    enabled = self._parse_bool(data.get("enabled", "false"))
                    try:
                        self._update_config_partial({"openclaw_autonomy_enabled": bool(enabled)})
                    except Exception:
                        pass
                cfg = getattr(self.coordinator, "cfg", None)
                state = bool(getattr(cfg, "openclaw_autonomy_enabled", False)) if cfg else False
                owner = "OPENCLAW" if state else "QUEEN"
                return jsonify({
                    "enabled": state,
                    "decision_owner": owner,
                    "ai_endpoint": "local",
                    "note": "OpenClaw uses local hive signals; no external AI API.",
                })
            except Exception as e:
                logging.exception("autonomy toggle error")
                return jsonify({"error": str(e)}), 500

        @self.app.route("/dex/pending.json")
        def dex_pending_json():
            try:
                exec_agent = self.coordinator.agents.get("execution") if self.coordinator else None
                if exec_agent and hasattr(exec_agent, "get_pending_swap"):
                    pending = exec_agent.get_pending_swap()
                    return jsonify({"pending": pending})
                return jsonify({"pending": None})
            except Exception as e:
                logging.exception("dex/pending.json error")
                return jsonify({"pending": None, "error": str(e)}), 500

        @self.app.route("/dex/ack", methods=["POST"])
        def dex_ack():
            try:
                data = request.json if request.is_json else request.form.to_dict()
                tx_hash = data.get("tx_hash") or data.get("hash")
                intent_id = data.get("intent_id")
                client_order_id = data.get("client_order_id")
                exec_agent = self.coordinator.agents.get("execution") if self.coordinator else None
                if exec_agent and hasattr(exec_agent, "ack_swap"):
                    ok = exec_agent.ack_swap(tx_hash, intent_id=intent_id, client_order_id=client_order_id)
                    return jsonify({"ok": bool(ok), "tx_hash": tx_hash})
                return jsonify({"ok": False, "error": "dex_execution_unavailable"}), 503
            except Exception as e:
                logging.exception("dex/ack error")
                return jsonify({"ok": False, "error": str(e)}), 500

        @self.app.route("/alerts.json")
        def alerts_json():
            try:
                rows = self._get_alert_rows(limit=20)
                return jsonify({"rows": rows})
            except Exception as e:
                logging.exception("alerts.json error")
                return jsonify({"rows": [], "error": str(e)}), 500

        @self.app.route("/audit.json")
        def audit_json():
            try:
                rows = self._get_audit_rows(limit=20)
                return jsonify({"rows": rows})
            except Exception as e:
                logging.exception("audit.json error")
                return jsonify({"rows": [], "error": str(e)}), 500


        @self.app.route("/control/mode", methods=["POST"])
        def control_mode():
            try:
                dry_run = request.form.get('dry_run')
                if dry_run is None and request.is_json:
                    dry_run = request.json.get('dry_run')
                dry_run_val = str(dry_run).lower() in ('1','true','yes','y')
                if not dry_run_val:
                    confirm = request.form.get('confirm') or (request.json.get('confirm') if request.is_json else None)
                    if str(confirm).strip().upper() != 'ARM LIVE':
                        return jsonify({'ok': False, 'error': 'confirm_required'}), 400
                self._update_config_partial({'dry_run': dry_run_val})
                # When switching to LIVE, arm security agent and resume kill switch if present.
                if not dry_run_val:
                    try:
                        sec = self.coordinator.agents.get('security') if self.coordinator else None
                        if sec is not None:
                            try:
                                sec.armed = True
                            except Exception:
                                pass
                            try:
                                self.coordinator.share_data('buzz.security.policy', {'armed': True, 'dry_run': False, 'paused': False})
                            except Exception:
                                pass
                    except Exception:
                        logging.exception("Failed to arm security agent")
                    try:
                        ks = self.coordinator.agents.get('kill_switch') if self.coordinator else None
                        if ks and hasattr(ks, 'resume_swarm'):
                            ks.resume_swarm()
                    except Exception:
                        logging.exception("Failed to resume kill switch")
                return jsonify({'ok': True, 'dry_run': dry_run_val})
            except Exception as e:
                logging.exception('control_mode failed')
                return jsonify({'ok': False, 'error': str(e)}), 500

        @self.app.route("/control/pause", methods=["POST"])
        def control_pause():
            try:
                confirm = request.form.get('confirm') or (request.json.get('confirm') if request.is_json else None)
                if str(confirm).strip().upper() != 'HALT':
                    return jsonify({'ok': False, 'error': 'confirm_required'}), 400
                ks = self.coordinator.agents.get('kill_switch') if self.coordinator else None
                if ks and hasattr(ks, 'pause_swarm'):
                    ks.pause_swarm()
                return jsonify({'ok': True})
            except Exception as e:
                logging.exception('control_pause failed')
                return jsonify({'ok': False, 'error': str(e)}), 500

        @self.app.route("/control/resume", methods=["POST"])
        def control_resume():
            try:
                ks = self.coordinator.agents.get('kill_switch') if self.coordinator else None
                if ks and hasattr(ks, 'resume_swarm'):
                    ks.resume_swarm()
                return jsonify({'ok': True})
            except Exception as e:
                logging.exception('control_resume failed')
                return jsonify({'ok': False, 'error': str(e)}), 500

        @self.app.route("/config/limits", methods=["POST"])
        def config_limits():
            try:
                data = request.form.to_dict()
                if request.is_json:
                    data.update(request.json or {})
                updates = {}
                for key in ('max_notional','strategy_cooldown','spread_guard_pct','throttle_multiplier','order_type_pref'):
                    if key in data and data[key] != '' and data[key] is not None:
                        val = data[key]
                        try:
                            if key in ('max_notional','strategy_cooldown','spread_guard_pct','throttle_multiplier'):
                                val = float(val)
                        except Exception:
                            pass
                        updates[key] = val
                if updates:
                    self._update_config_partial(updates)
                return jsonify({'ok': True, 'updates': updates})
            except Exception as e:
                logging.exception('config_limits failed')
                return jsonify({'ok': False, 'error': str(e)}), 500

        @self.app.route("/config/kill_switch", methods=["POST"])
        def config_kill_switch():
            try:
                data = request.form.to_dict()
                if request.is_json:
                    data.update(request.json or {})
                updates = {}
                for key in ('market_stale_sec','wallet_stale_sec','slippage_threshold','throttle_clear_sec','kill_switch_grace_sec','kill_switch_enforce_stale'):
                    if key in data and data[key] != '' and data[key] is not None:
                        try:
                            if key == 'kill_switch_enforce_stale':
                                val = str(data[key]).strip().lower() in ('1','true','yes','y','on')
                            else:
                                val = float(data[key])
                                if key == 'throttle_clear_sec':
                                    val = int(float(data[key]))
                                if key == 'kill_switch_grace_sec':
                                    val = int(float(data[key]))
                        except Exception:
                            val = data[key]
                        updates[key] = val
                if updates:
                    self._update_config_partial(updates)
                return jsonify({'ok': True, 'updates': updates})
            except Exception as e:
                logging.exception('config_kill_switch failed')
                return jsonify({'ok': False, 'error': str(e)}), 500

        @self.app.route("/enable_network", methods=["POST"])
        def enable_network():
            try:
                host = request.form.get("redis_host") or "localhost"
                port = int(request.form.get("redis_port") or 6379)
                db = int(request.form.get("redis_db") or 0)
                pwd = request.form.get("redis_password") or None
                ok = False
                try:
                    ok = self.coordinator.enable_network(host=host, port=port, db=db, password=pwd)
                except Exception as e:
                    logging.warning(f"enable_network failed: {e}")
                msg = "Connected" if ok else "Connection failed"
                wants_json = request.args.get("json") == "1" or request.headers.get("Accept", "").lower().startswith("application/json")
                if wants_json:
                    return jsonify({"success": ok, "message": msg})
                return f"<html><body><h3>{msg}</h3><a href='/'>Back</a></body></html>"
            except Exception:
                return ("Error", 500)

        @self.app.route("/agents/status")
        def agents_status():
            try:
                return jsonify({
                    "agents": list(self.coordinator.agents.keys()) if getattr(self.coordinator, "agents", None) else [],
                    "health": getattr(self.coordinator, "agent_health", {}) or {}
                })
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        def _route_exists(path: str) -> bool:
            try:
                for rule in self.app.url_map.iter_rules():
                    if rule.rule == path:
                        return True
            except Exception:
                return False
            return False

        if not _route_exists("/status.json"):
            def _status_json():
                """Return current runtime mode and kill-switch/status flags for the UI."""
                try:
                    dry_run = getattr(self.coordinator.cfg, 'dry_run', True)
                    paused = False
                    kill_state = {}
                    ks = self.coordinator.agents.get('kill_switch') if getattr(self.coordinator, 'agents', None) else None
                    try:
                        if ks and hasattr(ks, 'get_state'):
                            kill_state = ks.get_state() or {}
                            paused = (kill_state.get('state') == 'HALT')
                    except Exception:
                        kill_state = {}
                    # security policy override (armed/dry_run/paused) if present
                    policy = self._latest_security_policy() or {}
                    if policy:
                        try:
                            if policy.get('dry_run') is not None:
                                dry_run = bool(policy.get('dry_run'))
                            if policy.get('paused') is not None:
                                paused = bool(policy.get('paused'))
                        except Exception:
                            pass
                    # live_mode flag: honor env override or cfg flag
                    live_env = os.getenv('CRYPTSWARM_LIVE') == '1'
                    live_cfg = getattr(self.coordinator.cfg, 'live_mode', False) if hasattr(self.coordinator, 'cfg') else False
                    live = bool(live_env or live_cfg) and not bool(dry_run)
                    return jsonify({'dry_run': bool(dry_run), 'kill_state': kill_state or {}, 'paused': bool(paused), 'live': bool(live), 'security_policy': policy or {}})
                except Exception as e:
                    logging.exception('status.json error')
                    return jsonify({'dry_run': True, 'kill_state': {}, 'paused': False, 'error': str(e)}), 500

            self.app.add_url_rule("/status.json", endpoint="status_json", view_func=_status_json)
    # ------------------------------------------------------------------ renderers
    def _render_dashboard(self):
        """
        Dashboard layout aligned with the Crypto Trading Agent Script:
        top status bar, health tiles, market strip, decision chain (recent trades),
        agent outputs fed by buzz messages, and live logs. Theme stays blue/yellow.
        """
        agents = list(self.coordinator.agents.keys()) if self.coordinator.agents else []
        # include coordinator + network in UI agent list
        if "coordinator" not in agents:
            agents.append("coordinator")
        if "network" not in agents:
            agents.append("network")

        # Phase 1: SwarmOS bee alias mapping (display-only)
        alias_map = {
            "coordinator": "QUEEN",
            "kill_switch": "BUZZKILL",
            "killswitch": "BUZZKILL",
            "market_data": "SCOUT",
            "market": "SCOUT",
            "coingecko": "SCOUT",
            "sentiment": "SCOUT",
            "trend": "SCOUT",
            "oracle": "ORACLE",
            "council": "COUNCIL",
            "nurse": "NURSE",
            "wallet": "SENTRY",
            "wallet_monitor": "SENTRY",
            "network": "HUM",
            "network_agent": "HUM",
            "execution": "STING",
            "data_store": "HONEYCOMB",
            "datastore": "HONEYCOMB",
            "logging": "SCRIBE",
            "performance": "OBSERVER",
            "performance_agent": "OBSERVER",
            "security": "WAX",
            "ui": "GLASS",
            "user_interface": "GLASS",
            "strategy": "WORKER-SMA",
            "strategy_agent": "WORKER-SMA",
            "worker_sma": "WORKER-SMA",
            "worker_rsi": "WORKER-RSI",
            "worker_breakout": "WORKER-BREAKOUT",
            "worker_momentum": "WORKER-MOMENTUM",
            "openclaw": "AUTONOMOUS",
        }
        bee_icon_map = {
            "QUEEN": "coordinator.png",
            "BUZZKILL": "killswitch.png",
            "SCOUT": "market.png",
            "ORACLE": "oracle.png",
            "COUNCIL": "council.png",
            "NURSE": "nurse.png",
            "SENTRY": "wallet.png",
            "HUM": "network.png",
            "STING": "execution.png",
            "HONEYCOMB": "datastore.png",
            "SCRIBE": "logging.png",
            "OBSERVER": "performance.png",
            "WAX": "security.png",
            "GLASS": "ui.png",
            "WORKER-SMA": "strategy.png",
            "WORKER-RSI": "workerRSI.png",
            "WORKER-BREAKOUT": "workerBreakout.png",
            "WORKER-MOMENTUM": "workerMomentum.png",
            "AUTONOMOUS": "strategy.png",
        }
        default_bee_msg = {
            "QUEEN": "I'm coordinating the hive decisions and waiting for signals",
            "BUZZKILL": "I'm monitoring risk and ready to halt if safety is breached",
            "SCOUT": "I'm scanning price, volume, and spread changes",
            "ORACLE": "I'm reading the regime and confidence in market conditions",
            "COUNCIL": "I'm comparing strategy proposals and normalizing signals",
            "NURSE": "I'm reviewing recent trades for drift and anomalies",
            "SENTRY": "I'm watching wallet balances and transfers",
            "HUM": "I'm relaying messages across the swarm bus",
            "STING": "I'm standing by to execute approved orders",
            "HONEYCOMB": "I'm storing events, trades, and history",
            "SCRIBE": "I'm recording logs and system notes",
            "OBSERVER": "I'm tracking performance, drawdown, and slippage",
            "WAX": "I'm protecting keys and enforcing security policy",
            "GLASS": "I'm presenting the dashboard and controls",
            "WORKER-SMA": "I'm evaluating SMA crossovers for trend signals",
            "WORKER-RSI": "I'm looking for RSI mean-reversion setups",
            "WORKER-BREAKOUT": "I'm hunting for volatility breakouts",
            "WORKER-MOMENTUM": "I'm tracking short-term momentum bursts",
            "AUTONOMOUS": "I'm the autonomous trading agent, running heartbeat checks",
        }
        bee_preface = {
            "QUEEN": "I'm coordinating the hive. ",
            "BUZZKILL": "I'm on risk watch. ",
            "SCOUT": "I'm scanning the market. ",
            "ORACLE": "I'm reading the regime. ",
            "COUNCIL": "I'm comparing the strategies. ",
            "NURSE": "I'm reviewing recent trades. ",
            "SENTRY": "I'm monitoring the wallet. ",
            "HUM": "I'm keeping the swarm in sync. ",
            "STING": "I'm ready to execute. ",
            "HONEYCOMB": "I'm storing the hive's memory. ",
            "SCRIBE": "I'm keeping the record. ",
            "OBSERVER": "I'm tracking performance. ",
            "WAX": "I'm guarding security. ",
            "GLASS": "I'm presenting the hive view. ",
            "WORKER-SMA": "I'm watching for SMA signals. ",
            "WORKER-RSI": "I'm watching for RSI extremes. ",
            "WORKER-BREAKOUT": "I'm watching for breakouts. ",
            "WORKER-MOMENTUM": "I'm watching momentum swings. ",
            "AUTONOMOUS": "I'm the autonomous agent. ",
        }

        def _bee_name(agent_name: str) -> str:
            key = str(agent_name or "").lower().replace("-", "_").replace(" ", "_")
            return alias_map.get(key, agent_name)

        def _bee_sentence(bee: str, summary: str) -> str:
            msg = (summary or "").strip()
            if not msg or msg.lower() in ("no recent messages", "no payload") or msg in ("|", "-", "N/A"):
                msg = default_bee_msg.get(bee, "I am on standby for updates")
            else:
                pre = bee_preface.get(bee, "")
                msg = f"{pre}Here's what I'm seeing: {msg}" if pre else f"Here's what I'm seeing: {msg}"
            if msg and msg[-1] not in ".!?":
                msg = msg + "."
            return f"buzz buzz {msg}"
        agent_health = dict(getattr(self.coordinator, "agent_health", {}) or {})
        # set health for coordinator/network
        agent_health.setdefault("coordinator", "active")
        try:
            if self.coordinator.network and self.coordinator.network.is_connected():
                agent_health["network"] = "active"
            else:
                agent_health.setdefault("network", "inactive")
        except Exception:
            agent_health.setdefault("network", "inactive")
    
        def status_color(name: str) -> str:
            val = agent_health.get(name, {})
            status = val.get("status") if isinstance(val, dict) else val
            if status is None:
                return "red"
            return "green" if str(status).lower() in ("active", "ok", "initialized", "ready") else "red"
    
        try:
            latest_price = self.coordinator.get_shared_data("latest_price")
        except Exception:
            latest_price = None
        if isinstance(latest_price, dict):
            try:
                if "payload" in latest_price:
                    latest_price = latest_price.get("payload")
            except Exception:
                pass
        latest_price_str = f"{latest_price:.2f}" if isinstance(latest_price, (int, float)) else (latest_price or "N/A")
    
        perf_metrics = {}
        if self.coordinator.agents.get("performance"):
            try:
                perf_metrics = self.coordinator.agents["performance"].get_current_metrics() or {}
            except Exception:
                perf_metrics = {}
    
        trade_metrics = {}
        if self.coordinator.agents.get("logging"):
            try:
                trade_metrics = self.coordinator.agents["logging"].get_metrics() or {}
            except Exception:
                trade_metrics = {}
    
        # live logs minus buzz noise
        recent_logs = self._get_logs(limit=60)
        cleaned_logs = []
        for entry in recent_logs:
            msg = entry.get("message", "") if isinstance(entry, dict) else str(entry)
            agent_name = entry.get("agent", "") if isinstance(entry, dict) else ""
            text = f"{agent_name} {msg}".lower()
            if "buzz" in text:
                continue
            cleaned_logs.append(entry)
        log_lines = [
            f"[{entry.get('timestamp','')}] {entry.get('agent','')}: {entry.get('message','')}" if isinstance(entry, dict) else str(entry)
            for entry in cleaned_logs
        ]
        log_tail = "\n".join(log_lines)
    
        # agent outputs from buzz + latest logs
        agent_messages = {}
        for entry in recent_logs:
            agent_name = entry.get("agent") if isinstance(entry, dict) else None
            if agent_name and agent_name not in agent_messages:
                agent_messages[agent_name] = entry.get("message", "")
        try:
            cache = getattr(self.coordinator, "data_cache", {}) or {}
            for k, v in cache.items():
                if not (isinstance(k, str) and k.startswith("buzz.") and isinstance(v, dict)):
                    continue
                buzz = v.get("buzz", {}) if isinstance(v, dict) else {}
                src = buzz.get("source") or (v.get("payload", {}) or {}).get("source")
                if not src:
                    continue
                payload = v.get("payload") or {}
                msg = None
                if isinstance(payload, dict):
                    if "message" in payload:
                        msg = str(payload.get("message"))
                    elif "summary" in payload:
                        msg = str(payload.get("summary"))
                    elif "symbol" in payload and ("price" in payload or "avg_price" in payload):
                        price = payload.get("price") or payload.get("avg_price")
                        msg = f"{payload.get('symbol')} @ {price}"
                    else:
                        items = []
                        for i, (pk, pv) in enumerate(payload.items()):
                            items.append(f"{pk}={pv}")
                            if i >= 1:
                                break
                        msg = ", ".join(items) if items else str(payload)
                else:
                    msg = str(payload)
                if msg:
                    agent_messages[str(src)] = msg[:120] + ("..." if len(msg) > 120 else "")
        except Exception:
            pass
        # seed security policy message so security agent reports even when quiet
        try:
            policy = self._latest_security_policy() or {}
            if policy and "security" not in agent_messages:
                agent_messages["security"] = f"armed={policy.get('armed')} dry_run={policy.get('dry_run')} paused={policy.get('paused')}"
        except Exception:
            pass

        # seed network/coordinator if still empty
        if "network" not in agent_messages:
            try:
                if self.coordinator.network:
                    agent_messages["network"] = f"connected={self.coordinator.network.is_connected()}"
            except Exception:
                pass
        if "coordinator" not in agent_messages:
            try:
                agent_messages["coordinator"] = f"symbol={getattr(self.coordinator.cfg,'symbol',None)} interval={getattr(self.coordinator.cfg,'interval',None)}"
            except Exception:
                pass

        if not agent_messages:
            for a in agents:
                agent_messages[a] = "No recent messages"
        else:
            for a in agents:
                agent_messages.setdefault(a, "No recent messages")
    
        def _summarize(msg):
            try:
                import re, json
                msg = re.sub(r"^\[\d+\]\s*", "", str(msg))
                if msg and (msg.strip().startswith("{") or msg.strip().startswith("[")):
                    try:
                        j = json.loads(msg)
                        if isinstance(j, dict):
                            items = []
                            for i, (k, v) in enumerate(j.items()):
                                items.append(f"{k}={v}")
                                if i >= 1:
                                    break
                            return ", ".join(items)
                    except Exception:
                        pass
                if not msg:
                    return "No payload"
                if len(msg) > 120:
                    return msg[:117] + "..."
                return msg
            except Exception:
                return str(msg)
    
        icon_map = {
            "coordinator": "coordinator.png",
            "market": "market.png",
            "market_data": "market.png",
            "coingecko": "market.png",
            "sentiment": "market.png",
            "trend": "market.png",
            "strategy": "strategy.png",
            "execution": "execution.png",
            "wallet": "wallet.png",
            "data_store": "datastore.png",
            "datastore": "datastore.png",
            "logging": "logging.png",
            "kill_switch": "killswitch.png",
            "killswitch": "killswitch.png",
            "ui": "ui.png",
            "network": "network.png",
            "performance": "performance.png",
            "security": "security.png",
        }
        def _icon_for(agent_name: str) -> str:
            key = str(agent_name or "").lower().replace("-", "_").replace(" ", "_")
            return icon_map.get(key, "ui.png")

        # Build bee-level messages (group by alias)
        bee_messages = {}
        bee_status = {}
        bee_order_all = [
            "QUEEN", "AUTONOMOUS", "ORACLE", "COUNCIL", "NURSE",
            "BUZZKILL", "SCOUT", "SENTRY", "HUM",
            "STING", "HONEYCOMB", "SCRIBE", "OBSERVER", "WAX", "GLASS",
            "WORKER-SMA", "WORKER-RSI", "WORKER-BREAKOUT", "WORKER-MOMENTUM",
        ]
        # determine which bees are present based on current agents
        bees_present = []
        for a in agents:
            bee = _bee_name(a)
            if bee not in bees_present:
                bees_present.append(bee)
            if bee not in bee_status:
                bee_status[bee] = False
            try:
                if status_color(a) == "green":
                    bee_status[bee] = True
            except Exception:
                pass
            if bee not in bee_messages:
                summary = _summarize(agent_messages.get(a, "") or agent_messages.get(bee, ""))
                if isinstance(summary, str) and summary.strip().lower().startswith("heartbeat"):
                    summary = ""
                if summary:
                    bee_messages[bee] = summary
        bee_order = [b for b in bee_order_all if b in bees_present] or bees_present

        # Server-side fallback only; JS renders the live bee grid
        agent_outputs_html = '<div class="mini">Waiting for buzz updates...</div>'
    
        trades = self._get_recent_trades(limit=20) or []
        trade_rows = "".join(
            f"<tr><td>{t.get('timestamp','')}</td><td>{t.get('symbol','')}</td><td>{t.get('side','')}</td>"
            f"<td>{t.get('quantity','')}</td><td>{t.get('price','')}</td><td>{t.get('venue','kraken')}</td></tr>"
            for t in trades[:10]
        ) or '<tr><td colspan="6" class="empty">Waiting for trades...</td></tr>'
    
        # ---- HTML template (use $ placeholders to avoid brace escaping hassles)
        from string import Template
        agent_count = len(agents)
        exchange = getattr(self.coordinator.cfg, 'exchange', 'kraken').upper()
        symbol = getattr(self.coordinator.cfg, 'symbol', 'ETH/USDT')
        max_dd = getattr(self.coordinator.cfg, 'max_drawdown_pct', 5)
        wallet_eth = self._get_wallet_snapshot().get('ETH', 'N/A')
        watch_addr = ""
        try:
            watch_addr = (self._load_api_keys() or {}).get("watch_address", "") or ""
        except Exception:
            watch_addr = ""
        pnl_val = trade_metrics.get('profit_loss', '0')
        win_rate_val = trade_metrics.get('win_rate', 'N/A')
        cpu_val = perf_metrics.get('cpu_percent', 'N/A')
        mem_val = perf_metrics.get('memory_percent', 'N/A')
        max_notional = getattr(self.coordinator.cfg, 'max_notional', '')
        cooldown = getattr(self.coordinator.cfg, 'strategy_cooldown', getattr(self.coordinator.cfg, 'cooldown_sec', 120))
        spread_guard = getattr(self.coordinator.cfg, 'spread_guard_pct', '')
        throttle_mult = getattr(self.coordinator.cfg, 'throttle_multiplier', '')
        order_pref = getattr(self.coordinator.cfg, 'order_type_pref', 'MARKET')
        market_stale_sec = getattr(self.coordinator.cfg, 'market_stale_sec', 300)
        wallet_stale_sec = getattr(self.coordinator.cfg, 'wallet_stale_sec', 300)
        slippage_threshold = getattr(self.coordinator.cfg, 'slippage_threshold', 0.01)
        throttle_clear_sec = getattr(self.coordinator.cfg, 'throttle_clear_sec', 300)
        kill_switch_grace_sec = getattr(self.coordinator.cfg, 'kill_switch_grace_sec', 120)
        kill_switch_enforce_stale = getattr(self.coordinator.cfg, 'kill_switch_enforce_stale', True)

        # Build alias map for JS (normalized keys)
        def _norm_key(s: str) -> str:
            return (
                str(s or "")
                .lower()
                .replace("-", "_")
                .replace(" ", "_")
            )
        alias_norm = { _norm_key(k): v for k, v in alias_map.items() }

        tmpl = Template(r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Crypto Swarm Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <script src="/static/walletconnect_shim.js"></script>
  <script src="https://unpkg.com/@walletconnect/ethereum-provider@2.11.1/dist/index.umd.js"></script>
  <style>
    :root { --bg:#071026; --panel:#0d1730; --accent:#ffd24a; --text:#ffd24a; --muted:#d9c786; --danger:#ff6b6b; }
    * { box-sizing:border-box; }
    body { margin:0; padding:22px; font-family:'Segoe UI','Inter',sans-serif; background:radial-gradient(circle at 20% 20%, rgba(127,209,255,0.08), transparent 30%), var(--bg); color:var(--text); }
    .wrap { max-width:1200px; margin:0 auto; }
    .topbar { display:grid; grid-template-columns: 1fr 1fr 1fr; gap:10px; align-items:center; margin-bottom:14px; }
    .mode-pill { display:inline-flex; align-items:center; gap:10px; padding:10px 12px; border-radius:12px; background:rgba(255,255,255,0.05); border:1px solid rgba(255,255,255,0.08); }
    .pill-title { color:var(--muted); font-size:12px; letter-spacing:.4px; text-transform:uppercase; }
    .pill-value { font-weight:700; font-size:15px; }
    .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:12px; margin-bottom:14px; }
    .card { background:linear-gradient(145deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01)); border:1px solid rgba(255,255,255,0.06); border-radius:12px; padding:14px; box-shadow:0 12px 40px rgba(0,0,0,0.35); }
    .card h3 { margin:0 0 6px; font-size:13px; color:var(--muted); letter-spacing:.3px; }
    .card-title { display:flex; align-items:center; gap:10px; margin-bottom:6px; }
    .card-title img { width:28px; height:28px; border-radius:8px; padding:4px; background:rgba(255,255,255,0.08); border:1px solid rgba(255,255,255,0.12); }
    .link { color:var(--accent); text-decoration:none; }
    .link:hover { text-decoration: underline; }
    .value { font-size:22px; font-weight:600; color:var(--accent); }
    .value.small { font-size:16px; color:var(--text); }
    .mini { font-size:12px; color:var(--muted); }
    .status-dot { width:10px; height:10px; border-radius:50%; display:inline-block; }
    .status-dot.green { background:#3ad29f; box-shadow:0 0 6px rgba(58,210,159,0.8); }
    .status-dot.red { background:#ff6b6b; box-shadow:0 0 6px rgba(255,107,107,0.8); }
    table { width:100%; border-collapse:collapse; margin-top:8px; }
    th,td { padding:8px 10px; font-size:13px; text-align:left; }
    th { color:var(--muted); border-bottom:1px solid rgba(255,255,255,0.08); }
    tr:not(:last-child) td { border-bottom:1px solid rgba(255,255,255,0.04); }
    .row { display:grid; gap:12px; grid-template-columns: 1.4fr 1fr; } @media(max-width:960px){ .row{grid-template-columns:1fr;} }
    .chart-wrap { height:240px; }
    .mini-charts { display:grid; grid-template-columns:repeat(auto-fit, minmax(180px, 1fr)); gap:10px; margin-top:10px; }
    .mini-chart-card { background:rgba(255,255,255,0.02); border:1px solid rgba(255,255,255,0.05); border-radius:10px; padding:8px; }
    .mini-chart { height:120px; }
    .empty { color:var(--muted); font-style:italic; padding:8px 0; }
    .log-tail { background:rgba(0,0,0,0.35); border:1px solid rgba(255,255,255,0.06); padding:10px; border-radius:10px; max-height:200px; overflow-y:auto; font-family:'JetBrains Mono','Consolas',monospace; font-size:12px; white-space:pre-wrap; }
    #agentOutputs { display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap:10px; }
    .agent-line { display:flex; align-items:center; gap:12px; margin:6px 0; flex-wrap:wrap; }
    .bee-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:10px; }
    .bee-card { position:relative; overflow:hidden; display:flex; gap:10px; align-items:flex-start; padding:10px; border-radius:12px; border:1px solid rgba(255,255,255,0.08); background:rgba(255,255,255,0.03); transition: box-shadow .2s ease, border-color .2s ease, background .2s ease; }
    .bee-card.buzzing { animation: buzzPulse 1.2s ease; }
    .bee-card.buzzing .agent-icon-lg { animation: buzzSpin 0.6s ease; }
    .bee-card.veto { border-color:#ff6b6b; box-shadow:0 0 12px rgba(255,107,107,0.4); background:rgba(255,107,107,0.06); }
    .bee-card.veto::after { content:''; position:absolute; left:-20%; top:48%; width:140%; height:3px; background:rgba(255,107,107,0.95); transform:rotate(-6deg); box-shadow:0 0 8px rgba(255,107,107,0.8); }
    .bee-card.penalty { border-color:#ff6b6b; box-shadow:0 0 12px rgba(255,107,107,0.35); background:rgba(255,107,107,0.04); }
    .bee-card.penalty::before { content:''; position:absolute; left:-20%; top:58%; width:140%; height:3px; background:rgba(255,107,107,0.85); transform:rotate(6deg); box-shadow:0 0 8px rgba(255,107,107,0.6); }
    .bee-card .bee-meta { display:flex; flex-direction:column; gap:4px; }
    .bee-name { font-weight:700; }
    .bee-msg { font-size:12px; color:var(--muted); }
    .bee-badges { display:flex; gap:6px; flex-wrap:wrap; }
    .bee-badge { font-size:10px; padding:2px 6px; border-radius:999px; border:1px solid rgba(255,255,255,0.2); color:var(--accent); }
    .bee-badge.veto { border-color:#ff6b6b; color:#ff6b6b; }
    .bee-badge.major { border-color:#ffd24a; color:#ffd24a; }
    .bee-badge.penalty { border-color:#ff6b6b; color:#ff6b6b; }
    @keyframes buzzPulse {
      0% { box-shadow:0 0 0 rgba(255,210,74,0); transform: translateX(0); }
      30% { box-shadow:0 0 14px rgba(255,210,74,0.4); transform: translateX(2px); }
      60% { box-shadow:0 0 10px rgba(255,210,74,0.2); transform: translateX(-2px); }
      100% { box-shadow:0 0 0 rgba(255,210,74,0); transform: translateX(0); }
    }
    @keyframes buzzSpin {
      0% { transform: rotate(0deg) scale(1); }
      50% { transform: rotate(6deg) scale(1.05); }
      100% { transform: rotate(0deg) scale(1); }
    }
    .agent-icon { width:18px; height:18px; border-radius:4px; object-fit:contain; background: rgba(255,255,255,0.06); padding:2px; }
    .agent-icon-lg { width:54px; height:54px; border-radius:12px; object-fit:contain; background: rgba(255,255,255,0.08); padding:6px; border:2px solid rgba(255,255,255,0.08); }
    .agent-icon-lg.green { border-color:#3ad29f; box-shadow:0 0 10px rgba(58,210,159,0.6); }
    .agent-icon-lg.red { border-color:#ff6b6b; box-shadow:0 0 10px rgba(255,107,107,0.6); }
    .conf-wrap { display:flex; align-items:center; gap:6px; }
    .conf-bar { width:90px; height:6px; background:rgba(255,255,255,0.08); border-radius:6px; overflow:hidden; }
    .conf-bar > span { display:block; height:100%; background:var(--accent); }
    .conf-val { font-size:11px; color:var(--muted); }

    .agent-msg { color:var(--muted); font-size:12px; }
    .app-shell { display:grid; grid-template-columns: 200px 1fr; gap:18px; align-items:start; }
    .sidebar { position:sticky; top:16px; align-self:start; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); border-radius:14px; padding:14px; height: fit-content; }
    .sidebar-logo { font-weight:800; letter-spacing:.8px; margin-bottom:12px; color:var(--accent); }
    .nav { display:flex; flex-direction:column; gap:8px; }
    .nav a { color:var(--text); text-decoration:none; padding:8px 10px; border-radius:8px; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.04); font-size:13px; }
    .nav a:hover { background:rgba(255,255,255,0.08); }
    .main { min-width:0; }
    .brand { display:flex; flex-direction:column; gap:4px; }
    .brand-name { font-size:16px; font-weight:800; letter-spacing:.8px; }
    .brand-sub { font-size:12px; color:var(--muted); }
    .status-pills { display:flex; gap:8px; flex-wrap:wrap; }
    .pill { padding:6px 10px; border-radius:999px; background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.08); font-size:12px; }
    .health-pills { display:flex; gap:8px; flex-wrap:wrap; }
    .health-pill { display:flex; align-items:center; gap:6px; padding:6px 10px; border-radius:999px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.06); font-size:12px; }
    .health-pill .dot { width:8px; height:8px; border-radius:50%; background:#3ad29f; box-shadow:0 0 6px rgba(58,210,159,0.8); }
    
    .clock { font-size:12px; color:var(--muted); }
    .warn { color:#ffb74d; font-size:11px; }
    .drawer { position:fixed; right:-420px; top:0; height:100%; width:420px; background:#0d1730; border-left:1px solid rgba(255,255,255,0.08); box-shadow:-10px 0 30px rgba(0,0,0,0.4); padding:16px; transition:right .25s ease; z-index:50; }
    .drawer.open { right:0; }
    .drawer-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; }
    .drawer-title { font-weight:700; }
    .drawer-close { background:none; border:none; color:var(--text); font-size:18px; cursor:pointer; }
    .drawer-body { font-size:13px; color:var(--muted); line-height:1.4; }
    .drawer-actions { display:flex; gap:8px; margin-top:12px; }
    .btn { padding:6px 10px; border-radius:8px; border:none; background:var(--accent); color:#071026; cursor:pointer; font-size:12px; }
    .btn.secondary { background:rgba(255,255,255,0.08); color:var(--text); border:1px solid rgba(255,255,255,0.12); }
    
    .meter { height:8px; border-radius:999px; background:rgba(255,255,255,0.08); overflow:hidden; }
    .filters { display:flex; gap:8px; flex-wrap:wrap; margin:8px 0; }
    .filters input { background:#0f1427; border:1px solid #2a3350; color:var(--text); padding:6px 8px; border-radius:8px; font-size:12px; }
    .modal { position:fixed; inset:0; background:rgba(0,0,0,0.6); display:none; align-items:center; justify-content:center; z-index:60; }
    .modal.open { display:flex; }
    .modal-card { background:#0d1730; border:1px solid rgba(255,255,255,0.08); padding:16px; border-radius:12px; width:min(900px, 90vw); }
    .modal-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }
    .modal-title { font-weight:700; }
    .flash { animation: flash 1.2s ease; }

    /* Oracle Regime display */
    .oracle-wrap { display:grid; grid-template-columns: 160px 1fr; gap:12px; align-items:center; }
    .oracle-dial { position:relative; width:160px; height:160px; border-radius:50%; background:radial-gradient(circle at 30% 30%, rgba(255,210,74,0.12), rgba(7,16,38,0.9) 60%); border:1px solid rgba(255,210,74,0.25); box-shadow:0 0 30px rgba(255,210,74,0.15) inset; }
    .oracle-ring { position:absolute; inset:10px; border-radius:50%; border:1px dashed rgba(255,210,74,0.25); }
    .oracle-needle { position:absolute; left:50%; top:50%; width:60px; height:2px; background:linear-gradient(90deg, rgba(255,210,74,0.0), rgba(255,210,74,0.9)); transform-origin:0% 50%; transform:rotate(-90deg); transition:transform 0.4s ease; }
    .oracle-core { position:absolute; left:50%; top:50%; width:10px; height:10px; margin-left:-5px; margin-top:-5px; border-radius:50%; background:#ffd24a; box-shadow:0 0 8px rgba(255,210,74,0.8); }
    .oracle-readout { position:absolute; bottom:10px; left:0; right:0; text-align:center; font-size:11px; color:var(--muted); }
    .oracle-readout .oracle-name { font-weight:700; color:var(--accent); font-size:12px; }
    .oracle-readout .oracle-conf { font-size:11px; }
    .oracle-bars { display:grid; gap:6px; }
    .oracle-bar { display:grid; grid-template-columns: 80px 1fr 40px; gap:6px; align-items:center; font-size:11px; color:var(--muted); }
    .oracle-bar .meter { height:6px; border-radius:999px; background:rgba(255,255,255,0.08); overflow:hidden; }
    .oracle-bar .meter > span { display:block; height:100%; background:linear-gradient(90deg, rgba(255,210,74,0.5), rgba(255,210,74,0.95)); }
    .leaderboard { display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:10px; }
    .leader-card { position:relative; padding:10px; border-radius:10px; border:1px solid rgba(255,255,255,0.08); background:rgba(255,255,255,0.03); }
    .leader-card.lead { border-color: rgba(255,210,74,0.7); box-shadow: 0 0 12px rgba(255,210,74,0.35); }
    .leader-badge { position:absolute; top:8px; right:8px; font-size:11px; color:var(--accent); }
    .action-buy { color:#3ad29f; }
    .action-sell { color:#ff6b6b; }
    .action-hold { color:#9fb0d8; }
    .strip { display:flex; flex-wrap:wrap; gap:8px; }
    .strip-item { padding:6px 10px; border-radius:999px; border:1px solid rgba(255,255,255,0.08); background:rgba(255,255,255,0.04); font-size:12px; }
    .race { display:flex; flex-direction:column; gap:10px; margin-top:8px; }
    .race-row { display:grid; grid-template-columns: 26px 140px 1fr 60px; gap:8px; align-items:center; }
    .race-label { font-size:12px; color:var(--muted); display:flex; align-items:center; gap:6px; }
    .race-score { font-size:12px; color:var(--text); text-align:right; }
    .race-track { position:relative; height:16px; border-radius:999px; background:linear-gradient(90deg, rgba(255,255,255,0.08), rgba(255,255,255,0.02)); border:1px solid rgba(255,255,255,0.08); overflow:hidden; }
    .race-track::after { content:"🏁"; position:absolute; right:6px; top:-2px; font-size:12px; opacity:0.6; }
    .race-bee { position:absolute; top:-6px; width:22px; height:22px; border-radius:50%; padding:2px; background:rgba(255,255,255,0.12); border:1px solid rgba(255,255,255,0.3); transition:left .6s ease; }
    .race-bee.action-buy { box-shadow:0 0 8px rgba(58,210,159,0.5); }
    .race-bee.action-sell { box-shadow:0 0 8px rgba(255,107,107,0.5); }
    .race-bee.action-hold { box-shadow:0 0 8px rgba(159,176,216,0.5); }
    .race-badge { font-size:10px; padding:2px 6px; border-radius:999px; border:1px solid rgba(255,255,255,0.2); color:var(--accent); }
    .race-badge.queen { border-color: rgba(255,210,74,0.7); color: var(--accent); }
    .race-badge.tie { border-color: rgba(159,176,216,0.7); color: #9fb0d8; }
    .cycle-bar { height:6px; border-radius:999px; background:rgba(255,255,255,0.08); border:1px solid rgba(255,255,255,0.08); overflow:hidden; margin-top:6px; }
    .cycle-bar span { display:block; height:100%; background:linear-gradient(90deg, rgba(58,210,159,0.7), rgba(255,210,74,0.7)); width:0%; transition:width .5s ease; }
    .stake-strip { display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }
    .stake-pill { font-size:10px; padding:2px 6px; border-radius:999px; border:1px solid rgba(255,255,255,0.2); color:var(--text); background:rgba(255,255,255,0.05); }
    .stake-card { display:flex; align-items:center; gap:8px; padding:6px 10px; border-radius:12px; border:1px solid rgba(255,255,255,0.12); background:rgba(255,255,255,0.04); }
    .stake-card img { width:22px; height:22px; border-radius:6px; padding:2px; background:rgba(255,255,255,0.08); }
    .stake-meta { display:flex; flex-direction:column; gap:2px; }
    .stake-name { font-size:12px; color:var(--text); font-weight:600; }
    .stake-amt { display:flex; align-items:center; gap:4px; font-size:12px; color:var(--muted); }
    .stake-amt img { width:14px; height:14px; border-radius:4px; padding:1px; background:rgba(255,255,255,0.08); }
    .cycle-score { display:flex; flex-direction:column; gap:6px; margin-top:8px; }
    .score-row { display:grid; grid-template-columns: 140px 1fr 60px; gap:8px; align-items:center; }
    .score-bar { height:10px; border-radius:8px; background:rgba(255,255,255,0.08); overflow:hidden; }
    .score-bar span { display:block; height:100%; background:rgba(255,210,74,0.8); width:0%; transition:width .5s ease; }
    .cycle-payout { display:flex; flex-direction:column; gap:6px; margin-top:8px; }
    .payout-row { display:grid; grid-template-columns: 1.2fr 1fr 1fr; gap:8px; align-items:center; font-size:12px; color:var(--muted); }
    .payout-row strong { color:var(--text); font-weight:600; }
    .row-veto td { color:#ff8a8a; }
    @keyframes flash {
      0% { box-shadow: 0 0 0 rgba(255,210,74,0); }
      50% { box-shadow: 0 0 18px rgba(255,210,74,0.45); }
      100% { box-shadow: 0 0 0 rgba(255,210,74,0); }
    }

    .meter > span { display:block; height:100%; background:#ffd24a; }

    @media(max-width: 980px){ .app-shell{grid-template-columns:1fr;} .sidebar{position:relative;} #agentOutputs{grid-template-columns:1fr;} }

  </style>
</head>
<body>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="sidebar-logo">HIVENANCE</div>
      <nav class="nav">
        <a href="#status">Status</a>
        <a href="#intents">Intents</a>
        <a href="#risk">Risk</a>
        <a href="#performance">Performance</a>
        <a href="#config">Config</a>
        <a href="#audit">Audit</a>
        <a href="/swarmguard">SwarmGuard</a>
        <a href="/buzz">BuzzCoin</a>
      </nav>
    </aside>
    <main class="main">
  <div style="display:flex; justify-content:center; margin:6px 0 14px 0;">
    <img src="/static/hivenance_logo.png" alt="logo" style="max-width:380px; max-height:240px; object-fit:contain;">
  </div>
  <div class="wrap">
    
    <div class="topbar" id="status">
      <div class="brand">
        <div class="brand-name">HIVENANCE</div>
        <div class="brand-sub">$MODE | $EXCHANGE | $SYMBOL</div>
      </div>
      <div class="status-pills">
        <div class="pill" id="pillMode">$MODE</div>
        <div class="pill" id="pillRun">RUNNING</div>
        <div class="pill" id="pillRisk">RISK: OK</div>
      </div>
      <div class="health-pills">
        <div class="health-pill" id="healthMarket"><span class="dot"></span>Market</div>
        <div class="health-pill" id="healthWallet"><span class="dot"></span>Wallet</div>
        <div class="health-pill" id="healthExec"><span class="dot"></span>Exec</div>
        <div class="health-pill" id="healthBus"><span class="dot"></span>Bus</div>
      </div>
      <div class="clock" id="clock">--:--:--</div>
    </div>

    <div class="grid">

      <div class="card"><h3>Market</h3><div class="value" id="latestPrice">$LATEST_PRICE</div><div class="mini">Last price</div></div>
      <div class="card">
        <h3>Wallet</h3>
        <div class="value" id="walletPrimary">$WALLET_ETH</div>
        <div class="mini" id="walletSub">ETH balance</div>
        <div class="mini warn" id="walletWarn" style="display:none;"></div>
        <div class="mini" id="walletBalances"></div>
      </div>
      <div class="card"><h3>PnL agg</h3><div class="value" id="pnlAgg">$PNL</div><div class="mini">Cumulative</div></div>
      <div class="card"><h3>Win rate</h3><div class="value" id="winRate">$WINRATE</div><div class="mini">All time</div></div>
      <div class="card"><h3>CPU</h3><div class="value small" id="cpuUsage">$CPU</div></div>
      <div class="card"><h3>Memory</h3><div class="value small" id="memUsage">$MEM</div></div>

    </div>

    <div class="row">
      <div class="card">
        <h3>Market Snapshot</h3>
        <div class="mini" id="marketSnap">Last: $LATEST_PRICE | Bid: | | Ask: | | Spread: |</div>
        <div class="mini" id="marketMeta">Volume (1m): | | Candle: |</div>
      </div>
      <div class="card">
        <h3>Portfolio</h3>
        <div class="mini" id="portfolioLine">Equity: | | Realized: | | Unrealized: |</div>
        <div class="mini" id="exposureLine">Exposure: $WALLET_ETH ETH</div>
      </div>
    </div>

    <div class="row">
      <div class="card">
        <h3>Analytics (window)</h3>
        <div class="mini" id="analyticsLine1">Trades: | | Filled: | | Rejected: |</div>
        <div class="mini" id="analyticsLine2">Equity: | | PnL %: | | Drawdown %: |</div>
        <div class="mini" id="analyticsLine3">Avg Slippage: | | p95 Latency: |</div>
      </div>
      <div class="card">
        <h3>Mode & Policy</h3>
        <div class="mini" id="policyLine">Policy: |</div>
        <div class="mini" id="policyLine2">Window: |</div>
      </div>
    </div>

    <div class="row">
      <div class="card" id="regimeCard">
        <h3>Regime (Oracle)</h3>
        <div class="mini" id="regimeLine">Regime: | Confidence: |</div>
        <div class="oracle-wrap">
          <div class="oracle-dial">
            <div class="oracle-ring"></div>
            <div class="oracle-needle" id="regimeNeedle"></div>
            <div class="oracle-core"></div>
            <div class="oracle-readout">
              <div class="oracle-name" id="regimeName">--</div>
              <div class="oracle-conf" id="regimeConf">--</div>
            </div>
          </div>
          <div class="oracle-bars">
            <div class="oracle-bar"><span>trend</span><div class="meter"><span id="regimeBar-trend"></span></div><span id="regimeVal-trend">|</span></div>
            <div class="oracle-bar"><span>vol</span><div class="meter"><span id="regimeBar-vol"></span></div><span id="regimeVal-vol">|</span></div>
            <div class="oracle-bar"><span>spread</span><div class="meter"><span id="regimeBar-spread"></span></div><span id="regimeVal-spread">|</span></div>
            <div class="oracle-bar"><span>mean</span><div class="meter"><span id="regimeBar-mean_cross"></span></div><span id="regimeVal-mean_cross">|</span></div>
            <div class="oracle-bar"><span>bb</span><div class="meter"><span id="regimeBar-bb_width"></span></div><span id="regimeVal-bb_width">|</span></div>
            <div class="oracle-bar"><span>volume</span><div class="meter"><span id="regimeBar-volume"></span></div><span id="regimeVal-volume">|</span></div>
          </div>
        </div>
      </div>
      <div class="card" id="councilCard">
        <h3>Council (Competition)</h3>
        <div class="mini" id="councilSummary">No proposals yet</div>
        <div class="mini" id="councilRaceMeta">Leader: | Queen: |</div>
        <div class="mini" id="cycleMeta">Cycle: |</div>
        <div class="cycle-bar"><span id="cycleProgress"></span></div>
        <div class="stake-strip" id="cycleStakes"></div>
        <div class="race" id="councilRace"></div>
        <div class="cycle-score" id="cycleScore"></div>
        <div class="cycle-payout" id="cyclePayout"></div>
      </div>
    </div>

    <div class="row">
      <div class="card">
        <h3>Strategy Competition</h3>
        <div class="mini">Live race view replaces redundant tables/strips.</div>
        <div class="leaderboard" id="strategyBoard" style="display:none;"></div>
      </div>
    </div>

    <div class="card" id="queenCard" style="margin-top:12px;">
      <h3>Queen Rationale</h3>
      <div class="mini" id="queenLine">Decision: | Strategy: | Size: | SVS: |</div>
      <div class="mini" id="queenReason">Reason: |</div>
      <div class="mini" id="queenOthers">Others: |</div>
    </div>

    <div id="queenModal" class="modal">
      <div class="modal-card" style="max-width:520px;">
        <div class="modal-header">
          <div class="modal-title" id="queenModalTitle">Queen Alert</div>
          <button class="drawer-close" onclick="closeQueenModal()">|</button>
        </div>
        <div style="display:flex; gap:12px; align-items:center; margin-bottom:10px;">
          <img src="/static/queen.png" alt="Queen" style="width:64px; height:64px; border-radius:14px; background:rgba(255,255,255,0.08); padding:8px; border:2px solid rgba(255,210,74,0.6);">
          <div class="mini" id="queenModalBody">No decision</div>
        </div>
        <div class="drawer-actions">
          <button class="btn" onclick="closeQueenModal()">Acknowledge</button>
          <button class="btn secondary" onclick="scrollToIntents()">View Intents</button>
        </div>
      </div>
    </div>

    <div class="card" id="swarmguardCard" style="margin-top:12px;">
      <div class="card-title">
        <img src="/static/swarmguard.png" alt="SwarmGuard">
        <div>
          <h3 style="margin:0;">SwarmGuard</h3>
          <div class="mini">Rules + veto logic</div>
        </div>
      </div>
      <div class="mini" id="swarmguardLine">Decision: | Reason: |</div>
      <div class="mini" id="swarmguardSize">Adjusted Size: |</div>
        <div class="mini" id="overrideStatus">Override: OFF</div>
        <div class="mini" id="autonomyStatus">Autonomy: OFF | Decision: QUEEN | AI: local</div>
      <div class="mini" id="safetyResetStatus">Safety: Ready</div>
        <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:8px;">
          <input id="overrideReason" class="input" placeholder="Override reason (optional)" style="flex:1; min-width:200px;">
          <button id="overrideToggleBtn" class="btn secondary" onclick="toggleOverride()">Enable Override</button>
          <button id="safetyResetBtn" class="btn" onclick="safetyReset()">Safety Reset</button>
        </div>
        <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:8px;">
          <button id="autonomyToggleBtn" class="btn secondary" onclick="toggleAutonomy()" aria-label="Toggle OpenClaw autonomous trade control on or off">Toggle Autonomous Control</button>
        </div>
      <div class="mini" style="margin-top:6px;"><a class="link" href="/swarmguard">Open SwarmGuard details</a></div>
    </div>

    <div class="card" id="buzzCard" style="margin-top:12px;">
      <div class="card-title">
        <img src="/static/buzzcoin.png" alt="BuzzCoin">
        <div>
          <h3 style="margin:0;">BuzzCoin</h3>
          <div class="mini">Internal stake ledger</div>
        </div>
      </div>
      <div class="mini" id="buzzSummary">BuzzService: |</div>
      <div class="mini" style="margin-top:6px;"><a class="link" href="/buzz">Open BuzzCoin ledger</a></div>
    </div>

    <div class="card" id="coinSelectionCard" style="margin-top:12px;">
      <h3>Coin Selection</h3>
      <div class="mini" id="coinSelectionTop">Top: |</div>
      <div class="mini" id="coinSelectionList">Candidates: |</div>
    </div>

    <div class="card" id="dexCard" style="margin-top:12px; display:$ONCHAIN_DISPLAY;">
      <h3>On-chain Trade Approval</h3>
      <div class="mini" id="dexStatus">No pending swaps</div>
      <div class="mini" id="dexDetails"></div>
      <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:8px;">
        <button class="btn secondary" onclick="openMetaMask()">Open MetaMask</button>
        <button class="btn secondary" onclick="connectWallet()">Connect Wallet</button>
        <button class="btn" onclick="approveSwap()">Approve & Send</button>
      </div>
      <div class="mini" style="opacity:0.7; margin-top:6px;">Requires wallet signature (WalletConnect or injected wallet).</div>
    </div>

    <div class="row">
      <div class="card">
        <h3>Market Price (live)</h3>
        <div class="chart-wrap"><canvas id="priceChart"></canvas></div>
        ${ALT_CHARTS_HTML}
      </div>
    </div>

    <div class="card" style="margin-top:12px;">
      <h3>Agent Outputs</h3>
      <div id="agentOutputs">${AGENT_OUTPUTS}</div>
    </div>

    
    <div class="card" style="margin-top:12px;">
      <h3>Signals (latest)</h3>
      <table>
        <thead><tr><th>Time</th><th>Strategy</th><th>Action</th><th>Confidence</th><th>Notes</th></tr></thead>
        <tbody id="signalsBody"><tr><td colspan="5" class="empty">No signals</td></tr></tbody>
      </table>
    </div>

<div class="card" style="margin-top:12px;">
      <h3>Decision Chain (latest)</h3>
      <table>
        <thead><tr><th>Time</th><th>Signal</th><th>Gate</th><th>Order</th><th>Execution</th><th>Outcome</th></tr></thead>
        <tbody id="decisionChainBody"><tr><td colspan="6" class="empty">Waiting for decisions...</td></tr></tbody>
      </table>

    <div id="rawJsonModal" class="modal">
      <div class="modal-card">
        <div class="modal-header">
          <div class="modal-title">Raw Event</div>
          <button class="drawer-close" onclick="closeRawJson()">|</button>
        </div>
        <pre id="rawJsonBody" class="log-tail" style="max-height:60vh;">|</pre>
      </div>
    </div>
    </div>

    <div class="card" style="margin-top:12px;">
      <h3>Recent Trades</h3>
      <table>
        <thead><tr><th>Time</th><th>Pair</th><th>Side</th><th>Qty</th><th>Price</th><th>Venue</th></tr></thead>
        <tbody id="recentTradesBody">${TRADE_ROWS}</tbody>
      </table>
    </div>

    <div class="card" style="margin-top:12px;">
      <h3>Vetoed Decisions</h3>
      <table>
        <thead><tr><th>Time</th><th>Signal</th><th>Reason</th></tr></thead>
        <tbody id="vetoBody"><tr><td colspan="3" class="empty">No vetoes</td></tr></tbody>
      </table>
    </div>

    <div class="card" id="intents" style="margin-top:12px;">
      <h3>Intents & Orders</h3>
      <table>
        <thead><tr><th>Intent ID</th><th>Strategy</th><th>Action</th><th>State</th><th>Timer</th><th>Cancel</th></tr></thead>
        <tbody id="intentsBody"><tr><td colspan="6" class="empty">Waiting for decisions...</td></tr></tbody>
      </table>
    
    <div id="intentDrawer" class="drawer">
      <div class="drawer-header">
        <div class="drawer-title">Intent Detail</div>
        <button class="drawer-close" onclick="closeIntentDrawer()">|</button>
      </div>
      <div class="drawer-body" id="intentDrawerBody">
        <div class="mini">Select a decision row to view details.</div>
      </div>
      <div class="drawer-actions">
        <button class="btn secondary" id="cancelIntentBtn" onclick="cancelIntent(window.__lastIntentId)">Cancel Order</button>
        <button class="btn" onclick="viewMarketSnapshot()">View Market Snapshot</button>
      </div>
    </div>
</div>

    <div class="card" id="risk" style="margin-top:12px;">
      <h3>Risk & Kill Switch</h3>
      <div class="mini" id="riskStateLine">State: OK - Reason: -</div>
      <div class="grid">
        <div class="card"><h3>Daily PnL %</h3><div class="value" id="riskPnl">N/A</div></div>
        <div class="card"><h3>Drawdown %</h3><div class="value" id="riskDd">N/A</div></div>
        <div class="card"><h3>Reject rate (5m)</h3><div class="value" id="riskReject">N/A</div></div>
        <div class="card"><h3>Feed staleness</h3><div class="value" id="riskStale">N/A</div></div>
      </div>
    <div class="card" style="margin-top:12px;">
      <h3>Why we throttled</h3>
      <table>
        <thead><tr><th>Time</th><th>Event</th></tr></thead>
        <tbody id="riskTimelineBody"><tr><td colspan="2" class="empty">No events</td></tr></tbody>
      </table>
    </div>

    <div class="card" id="performance" style="margin-top:12px;">
      <h3>Performance KPIs</h3>
      <div style="display:flex; gap:8px; margin:6px 0;">
        <button class="btn secondary" disabled>Export CSV</button>
        <button class="btn secondary" disabled>Export JSON</button>
      </div>
      <table>
        <thead><tr><th>Trades (today)</th><th>Win rate</th><th>Fees</th><th>Avg slippage</th><th>Max drawdown</th></tr></thead>
        <tbody id="perfBody"><tr><td colspan="5" class="empty">Loading...</td></tr></tbody>
      </table>
    </div>

    <div class="card" id="alerts" style="margin-top:12px;">
      <h3>Alerts Inbox</h3>
      <table>
        <thead><tr><th>Severity</th><th>Source</th><th>Reason</th><th>Action</th></tr></thead>
        <tbody id="alertsBody"><tr><td colspan="4" class="empty">No alerts</td></tr></tbody>
      </table>
    </div>

    
    <div class="card" id="config" style="margin-top:12px;">
      <h3>Config (Safe)</h3>
      <div class="mini" id="modeLine">Mode: $MODE</div>
      <div style="display:flex; gap:8px; flex-wrap:wrap; margin:8px 0;">
        <button class="btn secondary" onclick="setDryRun(true)">Dry Run</button>
        <button class="btn" onclick="goLive()">Go Live</button>
        <button class="btn secondary" onclick="haltNow()">HALT</button>
        <button class="btn secondary" onclick="resumeSwarm()">Resume</button>
      </div>
      <div class="filters">
        <input id="cfgMaxNotional" placeholder="Max Notional" value="$MAX_NOTIONAL" />
        <input id="cfgCooldown" placeholder="Cooldown (sec)" value="$COOLDOWN" />
        <input id="cfgSpread" placeholder="Spread Guard %" value="$SPREAD_GUARD" />
        <input id="cfgThrottle" placeholder="Throttle Mult" value="$THROTTLE_MULT" />
        <input id="cfgOrderPref" placeholder="Order Type Pref" value="$ORDER_PREF" />
        <button class="btn" onclick="saveLimits()">Save Limits</button>
      </div>
      <div class="filters">
        <input id="cfgMarketStale" placeholder="Market Stale Sec" value="$MARKET_STALE_SEC" />
        <input id="cfgWalletStale" placeholder="Wallet Stale Sec" value="$WALLET_STALE_SEC" />
        <input id="cfgSlip" placeholder="Slippage Threshold" value="$SLIPPAGE_THRESHOLD" />
        <input id="cfgThrottleClear" placeholder="Throttle Clear Sec" value="$THROTTLE_CLEAR_SEC" />
        <input id="cfgGrace" placeholder="Kill Switch Grace Sec" value="$KILL_SWITCH_GRACE_SEC" />
        <input id="cfgEnforceStale" placeholder="Enforce Stale (true/false)" value="$KILL_SWITCH_ENFORCE_STALE" />
        <button class="btn" onclick="saveKillSwitch()">Save Kill Switch</button>
      </div>
      <div class="mini">Changes apply immediately where supported.</div>
    </div>
<div class="card" id="audit" style="margin-top:12px;">
      <h3>Audit Log (recent)</h3>
      <div class="filters">
        <input id="auditFilterType" placeholder="Type" />
        <input id="auditFilterSource" placeholder="Source" />
        <input id="auditFilterSeverity" placeholder="Severity" />
        <input id="auditFilterIntent" placeholder="Intent ID / Trace" />
      </div>
      <table>
        <thead><tr><th>Time</th><th>Event</th><th>Detail</th></tr></thead>
        <tbody id="auditBody"><tr><td colspan="3" class="empty">No audit events</td></tr></tbody>
      </table>
    </div>

    <div class="card" id="config" style="margin-top:12px;">
      <h3>Live Logs</h3>
      <pre class="log-tail">${LOG_TAIL}</pre>
    </div>
  </div>

  <script>
    const cb = () => 'v=' + Date.now();
    const UI_PORT = '$UI_PORT';
    const sameOrigin = (location.port === UI_PORT) || (location.hostname === '127.0.0.1') || (location.hostname === 'localhost');
    const API_BASE = sameOrigin ? '' : `http://127.0.0.1:${UI_PORT}`;
    const api = (path) => API_BASE + path;
    let priceChart;
    const DEFAULT_SYMBOL = "$SYMBOL";
    const lastPrices = {};
    const lastAssetPrices = {};
    function setLastPrice(symbol, price){
      if (!symbol || price === null || price === undefined) return;
      const p = Number(price);
      if (Number.isNaN(p)) return;
      lastPrices[symbol] = p;
      try{
        const base = symbol.split('/')[0];
        if (base) lastAssetPrices[base.toUpperCase()] = p;
      }catch(e){}
    }
    const ALT_MARKETS = ${ALT_MARKETS_JSON};
    const altCharts = {};

    
    async function setDryRun(on){
      try{
        const body = `dry_run=$${on ? 'true' : 'false'}`;
        const res = await fetch(api('/control/mode'), {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body});
        const j = await res.json();
        if (!j.ok) alert('Failed: ' + (j.error || 'unknown'));
        if (j && j.ok) await loadStatus();
      }catch(e){ alert('Failed: ' + e); }
    }
    async function goLive(){
      const confirm = prompt('Type ARM LIVE to confirm');
      if (!confirm) return;
      try{
        const body = `dry_run=false&confirm=$${encodeURIComponent(confirm)}`;
        const res = await fetch(api('/control/mode'), {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body});
        const j = await res.json();
        if (!j.ok) alert('Failed: ' + (j.error || 'unknown'));
        if (j && j.ok) await loadStatus();
      }catch(e){ alert('Failed: ' + e); }
    }
    async function haltNow(){
      const confirm = prompt('Type HALT to confirm');
      if (!confirm) return;
      try{
        const body = `confirm=$${encodeURIComponent(confirm)}`;
        const res = await fetch(api('/control/pause'), {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body});
        const j = await res.json();
        if (!j.ok) alert('Failed: ' + (j.error || 'unknown'));
      }catch(e){ alert('Failed: ' + e); }
    }
    async function resumeSwarm(){
      try{
        const res = await fetch(api('/control/resume'), {method:'POST'});
        const j = await res.json();
        if (!j.ok) alert('Failed: ' + (j.error || 'unknown'));
        if (j && j.ok) await loadStatus();
      }catch(e){ alert('Failed: ' + e); }
    }

    async function loadAutonomy(){
      try{
        const res = await fetch(api('/autonomy?' + cb()));
        const j = await res.json();
        const btn = document.getElementById('autonomyToggleBtn');
        if (!btn) return;
        const enabled = !!j.enabled;
        btn.innerText = enabled ? 'Disable Autonomous Control' : 'Enable Autonomous Control';
        btn.setAttribute('aria-label', enabled ? 'Disable OpenClaw autonomous trade control' : 'Enable OpenClaw autonomous trade control');
        btn.classList.toggle('secondary', !enabled);
        const status = document.getElementById('autonomyStatus');
        if (status) {
          const owner = j.decision_owner || (enabled ? 'OPENCLAW' : 'QUEEN');
          const ai = j.ai_endpoint || 'local';
          status.innerText = `Autonomy: $${enabled ? 'ON' : 'OFF'} | Decision: $${owner} | AI: $${ai}`;
        }
      }catch(e){ /* ignore */ }
    }

    async function toggleAutonomy(){
      try{
        const res = await fetch(api('/autonomy?' + cb()));
        const st = await res.json();
        const next = !(st && st.enabled);
        const body = 'enabled=' + (next ? 'true' : 'false');
        const update = await fetch(api('/autonomy'), {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body});
        const j = await update.json();
        if (!j || j.error) alert('Failed: ' + (j.error || 'unknown'));
        await loadAutonomy();
      }catch(e){ alert('Failed: ' + e); }
    }
    async function saveLimits(){
      const maxNotional = ((document.getElementById('cfgMaxNotional') || {}).value || '');
      const cooldown = ((document.getElementById('cfgCooldown') || {}).value || '');
      const spread = ((document.getElementById('cfgSpread') || {}).value || '');
      const throttle = ((document.getElementById('cfgThrottle') || {}).value || '');
      const orderPref = ((document.getElementById('cfgOrderPref') || {}).value || '');
      const body = `max_notional=$${encodeURIComponent(maxNotional)}&strategy_cooldown=$${encodeURIComponent(cooldown)}&spread_guard_pct=$${encodeURIComponent(spread)}&throttle_multiplier=$${encodeURIComponent(throttle)}&order_type_pref=$${encodeURIComponent(orderPref)}`;
      try{
        const res = await fetch(api('/config/limits'), {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body});
        const j = await res.json();
        if (!j.ok) alert('Failed: ' + (j.error || 'unknown'));
      }catch(e){ alert('Failed: ' + e); }
    }

    async function saveKillSwitch(){
      const marketStale = ((document.getElementById('cfgMarketStale') || {}).value || '');
      const walletStale = ((document.getElementById('cfgWalletStale') || {}).value || '');
      const slip = ((document.getElementById('cfgSlip') || {}).value || '');
      const throttleClear = ((document.getElementById('cfgThrottleClear') || {}).value || '');
      const grace = ((document.getElementById('cfgGrace') || {}).value || '');
      const enforceStale = ((document.getElementById('cfgEnforceStale') || {}).value || '');
      const body = `market_stale_sec=$${encodeURIComponent(marketStale)}&wallet_stale_sec=$${encodeURIComponent(walletStale)}&slippage_threshold=$${encodeURIComponent(slip)}&throttle_clear_sec=$${encodeURIComponent(throttleClear)}&kill_switch_grace_sec=$${encodeURIComponent(grace)}&kill_switch_enforce_stale=$${encodeURIComponent(enforceStale)}`;
      try{
        const res = await fetch(api('/config/kill_switch'), {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body});
        const j = await res.json();
        if (!j.ok) alert('Failed: ' + (j.error || 'unknown'));
      }catch(e){ alert('Failed: ' + e); }
    }

    async function cancelIntent(intentId){
      if (!intentId) return;
      const confirm = prompt('Type CANCEL to confirm');
      if (!confirm || confirm.toUpperCase() !== 'CANCEL') { alert('Cancel aborted'); return; }
      try{
        const body = `intent_id=$${encodeURIComponent(intentId)}`;
        const res = await fetch(api('/intent/cancel'), {method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body});
        const j = await res.json().catch(() => ({}));
        if (!j.ok) {
          alert('Cancel failed: ' + (j.error || 'unknown'));
        } else if (j.canceled) {
          alert('Cancel request sent');
        } else {
          alert('No live order found to cancel (request recorded).');
        }
        try { loadIntents(); loadDecisionChain(); } catch(e) {}
      }catch(e){ alert('Cancel failed: ' + e); }
    }
function openRawJson(payload){
      const modal = document.getElementById('rawJsonModal');
      const body = document.getElementById('rawJsonBody');
      if (body) body.innerText = JSON.stringify(payload || {}, null, 2);
      if (modal) modal.classList.add('open');
    }
    function closeRawJson(){
      const modal = document.getElementById('rawJsonModal');
      if (modal) modal.classList.remove('open');
    }


    function openIntentDrawer(detailHtml){
      const drawer = document.getElementById('intentDrawer');
      const body = document.getElementById('intentDrawerBody');
      if (body) body.innerHTML = detailHtml || '<div class="mini">No details.</div>';
      if (drawer) drawer.classList.add('open');
    }
    function setIntentActions(intentId){
      window.__lastIntentId = intentId || null;
      const btn = document.getElementById('cancelIntentBtn');
      if (btn) btn.disabled = !intentId;
    }
    function closeIntentDrawer(){
      const drawer = document.getElementById('intentDrawer');
      if (drawer) drawer.classList.remove('open');
    }

    function viewMarketSnapshot(){
      try{
        const el = document.getElementById('marketSnap');
        if (!el) return;
        const card = el.closest('.card');
        if (card) {
          card.scrollIntoView({behavior:'smooth', block:'center'});
          card.classList.add('flash');
          setTimeout(() => card.classList.remove('flash'), 1200);
        } else {
          el.scrollIntoView({behavior:'smooth', block:'center'});
        }
      }catch(e){}
    }


    async function loadPrice() {
      try {
        const res = await fetch(api('/price.json?' + cb()));
        const data = await res.json();
        const labels = Array.isArray(data.labels) ? data.labels : [];
        const prices = Array.isArray(data.prices) ? data.prices : [];
        const latest = prices.length ? prices[prices.length - 1] : null;
        const priceEl = document.getElementById('latestPrice');
        if (priceEl) priceEl.innerText = latest !== null ? Number(latest).toFixed(2) : 'N/A';
        // Track last price for current symbol to support portfolio valuation
        setLastPrice((window.currentSymbol || DEFAULT_SYMBOL), latest);
        if (!priceChart) {
          const ctx = document.getElementById('priceChart').getContext('2d');
          priceChart = new Chart(ctx, {
            type: 'line',
            data: { labels, datasets: [{ label:'Price', data: prices, borderColor:'#ffd24a', backgroundColor:'rgba(255,210,74,0.15)', tension:0.25, pointRadius:0 }] },
            options: { responsive:true, animation:false, plugins:{legend:{display:false}}, scales:{x:{ticks:{color:'#9fb0d8'}, grid:{color:'rgba(255,255,255,0.05)'}}, y:{ticks:{color:'#9fb0d8'}, grid:{color:'rgba(255,255,255,0.05)'}}} }
          });
        } else {
          priceChart.data.labels = labels;
          priceChart.data.datasets[0].data = prices;
          priceChart.update();
        }
      } catch (err) { console.error('price load failed', err); }
    }

    async function loadAltPrices(){
      for (const m of ALT_MARKETS){
        try{
          const url = api('/price_series.json?symbol=' + encodeURIComponent(m.symbol) + '&limit=120&' + cb());
          const res = await fetch(url);
          const data = await res.json();
          const labels = Array.isArray(data.labels) ? data.labels : [];
          const prices = Array.isArray(data.prices) ? data.prices : [];
          if (prices.length) setLastPrice(m.symbol, prices[prices.length - 1]);
          const canvas = document.getElementById('priceChart_' + m.id);
          if (!canvas) continue;
          if (!altCharts[m.id]) {
            const ctx = canvas.getContext('2d');
            altCharts[m.id] = new Chart(ctx, {
              type: 'line',
              data: { labels: labels, datasets: [{ label: m.label, data: prices, borderColor: m.color, backgroundColor: 'rgba(255,255,255,0.06)', tension: 0.25, pointRadius: 0 }] },
              options: {
                responsive: true,
                animation: false,
                plugins: { legend: { display: false } },
                scales: {
                  x: { display: false, grid: { display: false } },
                  y: { ticks: { color: '#9fb0d8' }, grid: { color: 'rgba(255,255,255,0.05)' } }
                }
              }
            });
          } else {
            altCharts[m.id].data.labels = labels;
            altCharts[m.id].data.datasets[0].data = prices;
            altCharts[m.id].update();
          }
        }catch(e){
          console.error('alt price load failed', m.symbol, e);
        }
      }
    }

    async function loadMetrics() {
      try {
        const res = await fetch(api('/metrics.json?' + cb()));
        const data = await res.json();
        const perf = data.performance || {};
        const trading = data.trading || {};
        const setVal = (id, val) => { const el = document.getElementById(id); if (el && val!==undefined && val!==null) el.innerText = val; };
        setVal('cpuUsage', perf.cpu_percent);
        setVal('memUsage', perf.memory_percent);
        setVal('pnlAgg', trading.profit_loss);
        setVal('winRate', trading.win_rate !== undefined && trading.win_rate !== null ? Math.round(trading.win_rate*100)+'%' : undefined);
      } catch(err) { console.error('metrics load failed', err); }
    }

    
    async function loadSignals(){
      try{
        const res = await fetch(api('/signals.json?' + cb()));
        const data = await res.json();
        const rows = data.rows || [];
        const body = document.getElementById('signalsBody');
        if (!body) return;
        body.innerHTML = rows.length ? rows.map(r => {
          const confVal = (r.confidence !== undefined && r.confidence !== null) ? Number(r.confidence) : null;
          const pct = (confVal !== null && !Number.isNaN(confVal)) ? Math.round(confVal * 100) : null;
          const confHtml = (pct !== null)
            ? '<div class="conf-wrap"><div class="conf-bar"><span style="width:'+pct+'%"></span></div><span class="conf-val">'+pct+'%</span></div>'
            : '|';
          return '<tr>' +
            '<td>' + (r.time || '') + '</td>' +
            '<td>' + (r.strategy || '') + '</td>' +
            '<td>' + (r.action || '') + '</td>' +
            '<td>' + confHtml + '</td>' +
            '<td>' + (r.notes || '') + '</td>' +
          '</tr>';
        }).join('') : '<tr><td colspan="5" class="empty">No signals</td></tr>';
      }catch(e){ console.error('signals load failed', e); }
    }


    async function loadMarketSnapshot(){
      try{
        const res = await fetch(api('/market_snapshot.json?' + cb()));
        const data = await res.json();
        const last = data.last;
        const bid = data.bid;
        const ask = data.ask;
        const spread = data.spread_pct;
        const vol = data.volume_1m;
        const rem = data.candle_remain_sec;
        const snap = document.getElementById('marketSnap');
        const meta = document.getElementById('marketMeta');
        const spreadStr = (spread !== undefined && spread !== null) ? Number(spread).toFixed(3) + '%' : '|';
        const remStr = (rem !== undefined && rem !== null) ? rem + 's' : '|';
        if (snap) snap.innerText = `Last: $${last || '|'} | Bid: $${bid || '|'} | Ask: $${ask || '|'} | Spread: $${spreadStr}`;
        if (meta) meta.innerText = `Volume (1m): $${vol || '|'} | Candle: $${remStr}`;
      }catch(e){ console.error('market snapshot failed', e); }
    }

    async function loadAnalytics(){
      try{
        const res = await fetch(api('/analytics.json?' + cb()));
        const data = await res.json();
        const p = data.payload || {};
        const fmt = (v, digits=2) => {
          if (v === 0) return Number(0).toFixed(digits);
          if (v === null || v === undefined || v === '') return '|';
          const n = Number(v);
          if (Number.isNaN(n)) return v;
          return n.toFixed(digits);
        };
        const eq = p.equity_usd_est;
        const pnl = p.daily_pnl_pct ?? p.equity_change_pct;
        const dd = p.drawdown_pct;
        const trades = p.trades;
        const filled = p.filled;
        const rejected = p.rejected;
        const slip = p.avg_slippage_pct;
        const p95 = p.p95_latency_ms;
        const win = document.getElementById('analyticsLine1');
        const line2 = document.getElementById('analyticsLine2');
        const line3 = document.getElementById('analyticsLine3');
        if (win) win.innerText = 'Trades: ' + (trades ?? '|') + ' | Filled: ' + (filled ?? '|') + ' | Rejected: ' + (rejected ?? '|');
        const sym = p.symbol || DEFAULT_SYMBOL;
        window.currentSymbol = sym;
        let equityDisplay = (eq !== undefined && eq !== null) ? Number(eq) : null;
        try{
          if (window.__lastWallet && Array.isArray(window.__lastWallet.balances)) {
            const bals = window.__lastWallet.balances;
            let total = 0.0;
            for (const b of bals){
              const asset = String(b.asset || '').toUpperCase();
              const free = Number(b.free || 0);
              const locked = Number(b.locked || 0);
              const qty = free + locked;
              if (!qty) continue;
              if (['USD','USDT','USDC','DAI'].includes(asset)) {
                total += qty;
              } else if (lastAssetPrices[asset]) {
                total += qty * lastAssetPrices[asset];
              }
            }
            if (total > 0) equityDisplay = total;
          }
        }catch(e){}
        if (line2) line2.innerText = 'Equity: $$' + (equityDisplay !== undefined && equityDisplay !== null ? fmt(equityDisplay,2) : '|') + ' | PnL %: ' + fmt(pnl,2) + ' | Drawdown %: ' + fmt(dd,2);
        if (line3) line3.innerText = 'Avg Slippage: ' + fmt(slip,4) + ' | p95 Latency: ' + (p95 ?? '|') + ' ms';
        const port = document.getElementById('portfolioLine');
        if (port) port.innerText = 'Equity: $$' + (equityDisplay !== undefined && equityDisplay !== null ? fmt(equityDisplay,2) : '|') + ' | PnL %: ' + fmt(pnl,2) + ' | Drawdown %: ' + fmt(dd,2);
        const policy = document.getElementById('policyLine');
        if (policy) policy.innerText = 'Policy: window=' + (p.window_sec || '|') + 's | symbol=' + (p.symbol || '|');
        const policy2 = document.getElementById('policyLine2');
        if (policy2) policy2.innerText = 'Updated: ' + (data.ts ? new Date(data.ts).toLocaleTimeString() : '|');
      }catch(e){ console.error('analytics load failed', e); }
    }

    async function loadSwarmGuard(){
      try{
        const res = await fetch(api('/swarmguard.json?' + cb()));
        const data = await res.json();
        const p = data.payload || {};
        const line = document.getElementById('swarmguardLine');
        const size = document.getElementById('swarmguardSize');
        if (line) line.innerText = 'Decision: ' + (p.decision || '|') + ' | Reason: ' + (p.reason || '|');
        if (size) size.innerText = 'Adjusted Size: ' + (p.position_size !== undefined ? p.position_size : '|');
      }catch(e){ console.error('swarmguard load failed', e); }
    }

    async function loadBuzzSummary(){
      try{
        const res = await fetch(api('/buzz/status?' + cb()));
        const data = await res.json();
        const el = document.getElementById('buzzSummary');
        if (!el) return;
        if (!data.ok) {
          el.innerText = 'BuzzService: offline';
          return;
        }
        const acct = data.account || {};
        const avail = (acct.available !== undefined) ? acct.available : (acct.available_buzz ?? 0);
        const locked = (acct.locked !== undefined) ? acct.locked : (acct.staked_buzz ?? 0);
        el.innerText = 'Balance: ' + avail + ' | Locked: ' + locked;
      }catch(e){
        const el = document.getElementById('buzzSummary');
        if (el) el.innerText = 'BuzzService: offline';
      }
    }

    let overrideEnabled = false;
    async function loadOverride(){
      try{
        const res = await fetch(api('/override'));
        const data = await res.json();
        overrideEnabled = !!data.enabled;
        const status = document.getElementById('overrideStatus');
        const btn = document.getElementById('overrideToggleBtn');
        if (status) status.innerText = 'Override: ' + (overrideEnabled ? 'ON' : 'OFF');
        if (btn) btn.innerText = overrideEnabled ? 'Disable Override' : 'Enable Override';
        const reason = document.getElementById('overrideReason');
        if (reason && data.reason) reason.value = data.reason;
      }catch(e){ console.warn('override load failed', e); }
    }

    async function toggleOverride(){
      try{
        const reason = (document.getElementById('overrideReason') || {}).value || '';
        const res = await fetch(api('/override'), {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({enabled: !overrideEnabled, reason})
        });
        const data = await res.json();
        overrideEnabled = !!data.enabled;
        const status = document.getElementById('overrideStatus');
        const btn = document.getElementById('overrideToggleBtn');
        if (status) status.innerText = 'Override: ' + (overrideEnabled ? 'ON' : 'OFF');
        if (btn) btn.innerText = overrideEnabled ? 'Disable Override' : 'Enable Override';
      }catch(e){ console.warn('override toggle failed', e); }
    }

    async function safetyReset(){
      const status = document.getElementById('safetyResetStatus');
      try{
        if (!confirm('Reset safety counters, pending execution, and overtrading timers?')) return;
        if (status) status.innerText = 'Safety: Resetting...';
        const res = await fetch(api('/swarmguard/reset'), { method: 'POST' });
        const data = await res.json();
        if (data.ok) {
          if (status) status.innerText = 'Safety: Reset complete';
        } else {
          if (status) status.innerText = 'Safety: Reset failed';
        }
      }catch(e){
        if (status) status.innerText = 'Safety: Reset failed';
      }
    }

    async function loadCoinSelection(){
      try{
        const res = await fetch(api('/coin_selection.json?' + cb()));
        const data = await res.json();
        const p = data.payload || {};
        const top = document.getElementById('coinSelectionTop');
        const list = document.getElementById('coinSelectionList');
        const topSym = p.symbol || (p.top && p.top[0] && p.top[0].symbol) || '|';
        if (top) top.innerText = 'Top: ' + topSym;
        if (list) {
          const arr = p.top || [];
          const txt = arr.length ? arr.map(x => (x.symbol || '') + ' (vol=' + (x.volatility ?? 0).toFixed(4) + ')').join(' | ') : '|';
          list.innerText = 'Candidates: ' + txt;
        }
      }catch(e){ console.error('coin selection load failed', e); }
    }

    const WALLETCONNECT_ID = "$WALLETCONNECT_ID";
    const ONCHAIN_ENABLED = "$ONCHAIN_ENABLED";
    const ONCHAIN_CHAIN_ID = Number("$ONCHAIN_CHAIN_ID");
    const ONCHAIN_CHAIN_HEX = "$ONCHAIN_CHAIN_HEX";
    const ONCHAIN_RPC_URL = "$ONCHAIN_RPC_URL";
    const ONCHAIN_CHAIN_NAME = "$ONCHAIN_CHAIN_NAME";
    const ONCHAIN_EXPLORER_URL = "$ONCHAIN_EXPLORER_URL";
    let __wcProvider = null;
    let __pendingDex = null;

    async function getWalletProvider(){
      if (window.ethereum) return window.ethereum;
      if (window.WalletConnectEthereumProvider && WALLETCONNECT_ID && ONCHAIN_ENABLED === "true") {
        if (!__wcProvider) {
          __wcProvider = await window.WalletConnectEthereumProvider.init({
            projectId: WALLETCONNECT_ID,
            chains: [ONCHAIN_CHAIN_ID || 1],
            showQrModal: true
          });
        }
        await __wcProvider.connect();
        return __wcProvider;
      }
      throw new Error('No wallet provider available');
    }

    async function connectWallet(){
      try{
        const p = await getWalletProvider();
        await p.request({ method: 'eth_requestAccounts' });
        alert('Wallet connected');
      }catch(e){
        console.error('wallet connect failed', e);
        alert('Wallet connect failed: ' + e);
      }
    }

    function openMetaMask(){
      try{
        if (window.ethereum && window.ethereum.isMetaMask) {
          window.ethereum.request({ method: 'eth_requestAccounts' }).catch(()=>{});
        }
      }catch(e){}
      try{
        window.open('https://portfolio.metamask.io/', '_blank');
      }catch(e){}
    }

    async function loadDexPending(){
      try{
        if (ONCHAIN_ENABLED !== "true") return;
        const res = await fetch(api('/dex/pending.json?' + cb()));
        const data = await res.json();
        const pending = data.pending;
        __pendingDex = pending || null;
        const statusEl = document.getElementById('dexStatus');
        const detailsEl = document.getElementById('dexDetails');
        if (!statusEl || !detailsEl) return;
        if (!pending) {
          statusEl.innerText = 'No pending swaps';
          detailsEl.innerText = '';
          return;
        }
        const side = pending.side || '';
        const sym = pending.symbol || '';
        statusEl.innerText = 'Pending: ' + side + ' ' + sym;
        let detail = 'Intent: ' + (pending.intent_id || '') + ' | Client: ' + (pending.client_order_id || '');
        const pv = pending.preview || {};
        try {
          if (pv.from_amount && pv.to_amount) {
            const fa = Number(pv.from_amount) / Math.pow(10, Number(pv.from_decimals || 18));
            const ta = Number(pv.to_amount) / Math.pow(10, Number(pv.to_decimals || 18));
            detail += ' | ' + (fa.toFixed(6)) + ' ' + (pv.from_symbol || '') + ' → ' + (ta.toFixed(6)) + ' ' + (pv.to_symbol || '');
          }
          if (pv.estimated_gas) {
            detail += ' | est gas: ' + pv.estimated_gas;
          }
        } catch(e) {}
        detailsEl.innerText = detail;
      }catch(e){
        console.error('dex pending load failed', e);
      }
    }

    async function approveSwap(){
      try{
        if (!__pendingDex || !__pendingDex.tx) { alert('No pending swap'); return; }
        const provider = await getWalletProvider();
        await provider.request({ method: 'eth_requestAccounts' });
        const chainId = await provider.request({ method: 'eth_chainId' });
        const target = ONCHAIN_CHAIN_HEX || '0x1';
        if (chainId !== target) {
          try {
            await provider.request({ method: 'wallet_switchEthereumChain', params: [{ chainId: target }] });
          } catch (e) {
            // Attempt to add the chain if missing
            try {
              await provider.request({
                method: 'wallet_addEthereumChain',
                params: [{
                  chainId: target,
                  chainName: ONCHAIN_CHAIN_NAME || 'Ethereum',
                  rpcUrls: ONCHAIN_RPC_URL ? [ONCHAIN_RPC_URL] : undefined,
                  blockExplorerUrls: ONCHAIN_EXPLORER_URL ? [ONCHAIN_EXPLORER_URL] : undefined,
                  nativeCurrency: { name: 'Ether', symbol: 'ETH', decimals: 18 },
                }],
              });
              await provider.request({ method: 'wallet_switchEthereumChain', params: [{ chainId: target }] });
            } catch (e2) {
              // fall through
            }
          }
        }
        const accounts = await provider.request({ method: 'eth_accounts' });
        const tx = __pendingDex.tx;
        if (!tx.from && accounts && accounts.length) tx.from = accounts[0];
        const txHash = await provider.request({ method: 'eth_sendTransaction', params: [tx] });
        await fetch(api('/dex/ack'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tx_hash: txHash, intent_id: __pendingDex.intent_id, client_order_id: __pendingDex.client_order_id })
        });
        alert('Transaction sent: ' + txHash);
        __pendingDex = null;
        loadDexPending();
      }catch(e){
        console.error('approve swap failed', e);
        alert('Approve failed: ' + e);
      }
    }

    async function loadRegime(){
      try{
        const res = await fetch(api('/regime.json?' + cb()));
        const data = await res.json();
        const p = data.payload || {};
        const reg = p.regime || '|';
        let confNum = (p.confidence !== undefined && p.confidence !== null) ? Number(p.confidence) : null;
        if (confNum !== null && confNum > 1) confNum = confNum / 100;
        const conf = (confNum !== null && !Number.isNaN(confNum)) ? Math.round(confNum * 100) + '%' : '|';
        const line = document.getElementById('regimeLine');
        if (line) line.innerText = 'Regime: ' + reg + ' | Confidence: ' + conf;
        const nameEl = document.getElementById('regimeName');
        const confEl = document.getElementById('regimeConf');
        if (nameEl) nameEl.innerText = String(reg || '--');
        if (confEl) confEl.innerText = (conf !== '|' ? ('Confidence ' + conf) : 'Confidence --');
        const needle = document.getElementById('regimeNeedle');
        if (needle && confNum !== null && !Number.isNaN(confNum)) {
          const deg = -90 + Math.max(0, Math.min(1, confNum)) * 180;
          needle.style.transform = 'rotate(' + deg + 'deg)';
        }
        const f = p.features || {};
        const keys = ['trend','vol','spread','mean_cross','bb_width','volume'];
        keys.forEach(k => {
          const val = f[k];
          const n = Number(val);
          const pct = (!Number.isNaN(n)) ? Math.max(3, Math.min(100, Math.abs(n) * 100)) : 3;
          const bar = document.getElementById('regimeBar-' + k);
          if (bar) bar.style.width = pct + '%';
          const label = document.getElementById('regimeVal-' + k);
          if (label) label.innerText = fmtFeature(val);
        });
      }catch(e){ console.error('regime load failed', e); }
    }

    function fmtFeature(v){
      if (v === null || v === undefined) return '|';
      const n = Number(v);
      if (Number.isNaN(n)) return v;
      return n.toFixed(2);
    }

    function showQueenModal(p){
      try{
        const modal = document.getElementById('queenModal');
        const body = document.getElementById('queenModalBody');
        const title = document.getElementById('queenModalTitle');
        if (!modal || !body || !title) return;
        const action = (p.action || '').toUpperCase();
        title.innerText = action ? ('Queen Alert: ' + action) : 'Queen Alert';
        const size = (p.position_size !== undefined && p.position_size !== null) ? fmtFeature(p.position_size) : '|';
        const svs = (p.svs !== undefined && p.svs !== null) ? fmtFeature(p.svs) : '|';
        const strat = p.strategy || '|';
        const reason = p.rationale || p.reason || '|';
        body.innerText = 'buzz buzz I recommend: ' + action + ' | Strategy: ' + strat + ' | Size: ' + size + ' | SVS: ' + svs + ' | ' + reason;
        modal.classList.add('open');
      }catch(e){ console.error('queen modal error', e); }
    }
    function closeQueenModal(){
      const modal = document.getElementById('queenModal');
      if (modal) modal.classList.remove('open');
    }
    function scrollToIntents(){
      closeQueenModal();
      const el = document.getElementById('intents');
      if (el) el.scrollIntoView({behavior:'smooth', block:'start'});
    }

    function actionClass(action){
      const a = String(action || '').toUpperCase();
      if (a === 'BUY') return 'action-buy';
      if (a === 'SELL') return 'action-sell';
      return 'action-hold';
    }
    function safeId(s){
      return String(s || '').replace(/[^a-z0-9_-]/gi, '_');
    }

    async function loadCouncil(){
      try{
        const res = await fetch(api('/council.json?' + cb()));
        const data = await res.json();
        const p = data.payload || {};
        const list = p.proposals || [];
        const sum = 'Proposals: ' + list.length + ' | ' + (p.symbol || '');
        const el = document.getElementById('councilSummary');
        if (el) el.innerText = sum;
        const raceEl = document.getElementById('councilRace');
        const raceMeta = document.getElementById('councilRaceMeta');

        // choose leader by strength/edge
        let leader = null;
        list.forEach(p => {
          const score = Number(p.signal_strength ?? p.edge ?? 0);
          if (!leader || score > leader.score) leader = { name: p.strategy || '', score, action: p.action || '' };
        });

        // removed redundant strip/list/table views

        if (raceEl) {
          const maxScore = list.reduce((m, p) => {
            const s = Number(p.signal_strength ?? p.edge ?? 0);
            return s > m ? s : m;
          }, 0) || 1;
          const queenPick = window.__lastQueenStrategy || null;
          const leaderName = leader ? leader.name : null;
          const tieThreshold = 0.02;
          raceEl.innerHTML = list.length ? list.map(p => {
            const score = Number(p.signal_strength ?? p.edge ?? 0);
            const pct = Math.max(3, Math.min(100, (score / maxScore) * 100));
            const cls = actionClass(p.action);
            const name = p.strategy || '';
            const isLead = leaderName && name === leaderName;
            const isQueen = queenPick && name === queenPick;
            const tie = leader && !isLead && Math.abs(score - leader.score) <= tieThreshold;
            const icon = BEE_ICONS[name] || BEE_ICONS[String(name).toUpperCase()] || 'strategy.png';
            const left = Math.max(0, Math.min(92, pct));
            return '<div class="race-row">' +
              '<img class="agent-icon" src="/static/' + icon + '" alt="' + name + '">' +
              '<div class="race-label">' +
                '<span>' + name + '</span>' +
                (isQueen ? '<span class="race-badge queen">QUEEN</span>' : '') +
                (tie ? '<span class="race-badge tie">TIE</span>' : '') +
              '</div>' +
              '<div class="race-track">' +
                '<img class="race-bee ' + cls + '" src="/static/' + icon + '" alt="' + name + '" style="left: calc(' + left + '% - 10px)"/>' +
              '</div>' +
              '<div class="race-score">' + fmtFeature(score) + '</div>' +
            '</div>';
          }).join('') : '<div class="mini">No proposals yet</div>';

          if (raceMeta) {
            const leadLabel = leaderName || '|';
            const queenLabel = queenPick || '|';
            raceMeta.innerText = 'Leader: ' + leadLabel + ' | Queen: ' + queenLabel;
          }
        }

        // leaderboard panel hidden to avoid duplicate competition views

        // store for queen rationale and flash on lead change
        window.__lastCouncilProposals = list;
        const prevLead = window.__lastCouncilLeader;
        const newLead = leader ? leader.name : null;
        window.__lastCouncilLeader = newLead;
        // lead change flash handled by race track animation
      }catch(e){ console.error('council load failed', e); }
    }

    async function loadCycle(){
      try{
        const res = await fetch(api('/cycle.json?' + cb()));
        const data = await res.json();
        const payload = (data && (data.payload || data)) || {};
        const meta = document.getElementById('cycleMeta');
        const prog = document.getElementById('cycleProgress');
        const stakesEl = document.getElementById('cycleStakes');
        const scoreEl = document.getElementById('cycleScore');
        const payoutEl = document.getElementById('cyclePayout');

        const startTs = Number(payload.start_ts || 0);
        const endTs = Number(payload.end_ts || 0);
        const now = Date.now();
        if (!endTs || !startTs) {
          if (prog) prog.style.width = '0%';
          if (meta) meta.innerText = 'Cycle: waiting for data';
          if (stakesEl) stakesEl.innerHTML = '<span class="mini">No stakes yet</span>';
          if (scoreEl) scoreEl.innerHTML = '<div class="mini">No cycle scores yet</div>';
          if (payoutEl) payoutEl.innerHTML = '<div class="mini">No cycle payouts yet</div>';
          return;
        }
        const total = Math.max(1, endTs - startTs);
        const leftMs = Math.max(0, endTs - now);
        const pct = Math.max(0, Math.min(100, ((total - leftMs) / total) * 100));
        if (prog) prog.style.width = pct + '%';
        if (meta) {
          const sym = payload.symbol || '|';
          const tl = payload.time_left_sec !== undefined ? payload.time_left_sec : Math.round(leftMs / 1000);
          const outcome = payload.outcome || (payload.type === 'cycle_result' ? payload.outcome : '');
          meta.innerText = 'Cycle: ' + sym + ' | time left: ' + tl + 's' + (outcome ? (' | outcome: ' + outcome) : '');
        }

        // stake strip
        if (stakesEl) {
          const stakes = payload.stakes || [];
          if (!stakes.length) {
            stakesEl.innerHTML = '<span class="mini">No stakes yet</span>';
          } else {
            const agentLabel = (a) => {
              if (!a) return 'AGENT';
              const norm = String(a).toUpperCase();
              if (AGENT_ALIAS && AGENT_ALIAS[norm]) return AGENT_ALIAS[norm];
              return norm;
            };
            const agentIcon = (a) => {
              const name = agentLabel(a);
              if (BEE_ICONS && BEE_ICONS[name]) return BEE_ICONS[name];
              return 'ui.png';
            };
            stakesEl.innerHTML = stakes.map(s => {
              const ctx = s.context || {};
              const who = s.actor || s.account || 'AGENT';
              const name = agentLabel(who);
              const icon = agentIcon(who);
              const amt = s.amount || 0;
              let note = '';
              if (ctx.strategy) note = ctx.strategy;
              else if (ctx.regime) note = ctx.regime;
              else if (ctx.action) note = ctx.action;
              return '<div class="stake-card">' +
                '<img src="/static/' + icon + '" alt="' + name + '">' +
                '<div class="stake-meta">' +
                  '<div class="stake-name">' + name + (note ? (' • ' + note) : '') + '</div>' +
                  '<div class="stake-amt"><span>' + amt + '</span><img src="/static/buzzcoin.png" alt="BUZZ"></div>' +
                '</div>' +
              '</div>';
            }).join('');
          }
        }

        // cycle score
        if (scoreEl) {
          let rows = [];
          if (payload.scores && Array.isArray(payload.scores)) {
            rows = payload.scores;
          } else if (payload.proposals) {
            rows = Object.keys(payload.proposals || {}).map(k => {
              const p = payload.proposals[k] || {};
              return { strategy: k, strength: Number(p.signal_strength || 0), score: Number(p.signal_strength || 0) };
            });
          }
          if (!rows.length) {
            scoreEl.innerHTML = '<div class="mini">No cycle scores yet</div>';
          } else {
            const max = rows.reduce((m, r) => Math.max(m, Number(r.score ?? r.strength ?? 0)), 0) || 1;
            scoreEl.innerHTML = rows.map(r => {
              const name = r.strategy || r.worker || 'WORKER';
              const val = Number(r.score ?? r.strength ?? 0);
              const width = Math.max(4, Math.min(100, (val / max) * 100));
              return '<div class="score-row">' +
                '<div class="mini">' + name + '</div>' +
                '<div class="score-bar"><span style="width:' + width + '%"></span></div>' +
                '<div class="mini" style="text-align:right;">' + fmtFeature(val) + '</div>' +
              '</div>';
            }).join('');
          }
        }
        // payout summary
        if (payoutEl) {
          const payouts = payload.payouts || [];
          const summary = payload.payout_summary || {};
          if (!payouts.length) {
            payoutEl.innerHTML = '<div class="mini">No cycle payouts yet</div>';
          } else {
            const head = '<div class="mini">Payouts (win vs loss)</div>';
            const body = payouts.map(p => {
              const who = p.actor || p.account || 'agent';
              const out = String(p.outcome || '').toUpperCase();
              const reward = p.reward || 0;
              const slash = p.slash || 0;
              return '<div class="payout-row"><strong>' + who + '</strong><span>' + out + '</span><span>+' + reward + ' / -' + slash + '</span></div>';
            }).join('');
            const foot = '<div class="mini">Total staked: ' + (summary.total_staked || 0) + ' | Rewards: ' + (summary.total_reward || 0) + ' | Slashed: ' + (summary.total_slash || 0) + '</div>';
            payoutEl.innerHTML = head + body + foot;
          }
        }
      } catch (e) {
        console.error('cycle load failed', e);
      }
    }

    async function loadGovernance(){
      try{
        const res = await fetch(api('/governance.json?' + cb()));
        const data = await res.json();
        const p = data.payload || {};
        const line = document.getElementById('queenLine');
        if (line) {
          const svs = (p.svs !== undefined && p.svs !== null) ? fmtFeature(p.svs) : '|';
          const size = (p.position_size !== undefined && p.position_size !== null) ? fmtFeature(p.position_size) : '|';
          line.innerText = 'Decision: ' + (p.action || '|') + ' | Strategy: ' + (p.strategy || '|') + ' | Size: ' + size + ' | SVS: ' + svs;
        }
        window.__lastQueenStrategy = p.strategy || null;
        const reason = document.getElementById('queenReason');
        if (reason) reason.innerText = 'Reason: ' + (p.rationale || '|');
        const others = document.getElementById('queenOthers');
        if (others) {
          const list = window.__lastCouncilProposals || [];
          if (!list.length) {
            others.innerText = 'Others: |';
          } else {
            const sorted = list.slice().sort((a,b) => Number(b.signal_strength ?? b.edge ?? 0) - Number(a.signal_strength ?? a.edge ?? 0));
            const picked = String(p.strategy || '');
            const losers = sorted.filter(x => x.strategy !== picked).slice(0,3).map(x => {
              const strength = x.signal_strength ?? x.edge ?? 0;
              return (x.strategy || '') + ' ' + fmtFeature(strength);
            });
            others.innerText = 'Others: ' + (losers.join(' | ') || '|');
          }
        }
        // Pop a queen alert when a buy/sell decision is emitted
        try {
          const action = String(p.action || '').toUpperCase();
          const approved = p.approved !== false;
          const ts = Number(p.ts || 0);
          const size = Number(p.position_size || 0);
          if ((action === 'BUY' || action === 'SELL') && approved && size > 0) {
            if (!window.__lastQueenPopupTs || ts > window.__lastQueenPopupTs) {
              window.__lastQueenPopupTs = ts;
              showQueenModal(p);
            }
          }
        } catch(e) { /* ignore */ }
      }catch(e){ console.error('governance load failed', e); }
    }

async function loadTrades() {
      try {
        const res = await fetch(api('/tape.json?' + cb()));
        const data = await res.json();
        let trades = data.trades || [];
        trades = trades.slice(0, 10);
        const tbody = document.getElementById('recentTradesBody');
        if (!tbody) return;
        tbody.innerHTML = trades.length ? trades.map(t => `
          <tr>
            <td>$${t.timestamp || ''}</td>
            <td>$${t.symbol || ''}</td>
            <td>$${t.side || ''}</td>
            <td>$${t.quantity || ''}</td>
            <td>$${t.price || ''}</td>
            <td>$${t.venue || ''}</td>
          </tr>`).join('') : '<tr><td colspan="6" class="empty">No trades captured yet</td></tr>';
      } catch(err) { console.error('trades load failed', err); }
    }

    
    async function loadDecisionChain() {
      try {
        const res = await fetch(api('/decision_chain.json?' + cb()));
        const data = await res.json();
        const rows = data.rows || [];
        const body = document.getElementById('decisionChainBody');
        if (!body) return;
        body.innerHTML = rows.length ? rows.map((r, idx) => `
          <tr data-idx="$${idx}" class="$${String(r.gate || '').includes('VETO') || String(r.outcome || '').includes('VETO') ? 'row-veto' : ''}">
            <td>$${r.time || ''}</td>
            <td>$${r.signal || ''}</td>
            <td>$${r.gate || ''}</td>
            <td>$${r.order || ''}</td>
            <td>$${r.execution || ''}</td>
            <td>$${r.outcome || ''}</td>
          </tr>`).join('') : '<tr><td colspan="6" class="empty">No decisions yet</td></tr>';
        if (rows.length) {
          body.querySelectorAll('tr').forEach(tr => {
            tr.style.cursor = 'pointer';
            tr.addEventListener('click', async () => {
              const i = Number(tr.getAttribute('data-idx')) || 0;
              const r = rows[i] || {};
              if (!r.intent_id || r.intent_id === '|') {
                const html = `
                  <div><strong>Intent:</strong> $${r.intent_id || '|'}</div>
                  <div><strong>Signal:</strong> $${r.signal || '|'}</div>
                  <div><strong>Gate:</strong> $${r.gate || '|'}</div>
                `;
                setIntentActions(null);
                openIntentDrawer(html);
                return;
              }
              try {
                const res = await fetch(api('/intent/detail?intent_id=' + encodeURIComponent(r.intent_id)));
                const d = await res.json();
                const intent = d.intent || {};
                const decision = d.decision || {};
                const signal = d.signal || {};
                const order = (d.orders && d.orders[0]) || {};
                const fill = (d.fills && d.fills[0]) || {};
                const hasDetail =
                  (intent && Object.keys(intent).length) ||
                  (decision && Object.keys(decision).length) ||
                  (signal && Object.keys(signal).length) ||
                  (d.orders && d.orders.length) ||
                  (d.fills && d.fills.length);
                if (!hasDetail) {
                  const html = `
                    <div><strong>Intent:</strong> $${r.intent_id || '|'}</div>
                    <div><strong>Signal:</strong> $${r.signal || '|'}</div>
                    <div><strong>Gate:</strong> $${r.gate || '|'}</div>
                    <div><strong>Order:</strong> $${r.order || '|'}</div>
                    <div><strong>Execution:</strong> $${r.execution || '|'}</div>
                    <div><strong>Outcome:</strong> $${r.outcome || '|'}</div>
                    <div class="mini">No persisted intent detail yet.</div>
                  `;
                  setIntentActions(r.intent_id);
                  openIntentDrawer(html);
                  return;
                }
                const html = `
                  <div><strong>Intent:</strong> $${d.intent_id || '|'}</div>
                  <div><strong>Strategy:</strong> $${intent.origin_strategy || signal.strategy || '|'}</div>
                  <div><strong>Signal:</strong> $${signal.action || intent.action || '|'} ($${signal.confidence || '|'})</div>
                  <div><strong>Gate:</strong> $${decision.decision || intent.state || '|'} ($${decision.reason || intent.final_reason || '|'})</div>
                  <div><strong>Order:</strong> $${order.order_type || '|'} $${order.side || ''} $${order.status || ''}</div>
                  <div><strong>Order IDs:</strong> $${order.client_order_id || '|'} / $${order.order_id || '|'}</div>
                  <div><strong>Execution:</strong> $${fill.filled_qty || '|'} @ $${fill.avg_price || '|'}</div>
                  <div><strong>Fees:</strong> $${fill.fee || '|'} | <strong>Slippage:</strong> $${fill.slippage_pct || '|'}</div>
                `;
                setIntentActions(r.intent_id);
                openIntentDrawer(html);
              } catch (e) {
                const html = `
                  <div><strong>Intent:</strong> $${r.intent_id || '|'}</div>
                  <div class="mini">Failed to load detail</div>
                `;
                setIntentActions(r.intent_id);
                openIntentDrawer(html);
              }
            });
          });
        }
        // Update veto table
        try {
          const vetoBody = document.getElementById('vetoBody');
          if (vetoBody) {
            const vetoes = rows.filter(r => String(r.gate || '').includes('VETO') || String(r.outcome || '').includes('VETO'));
            vetoBody.innerHTML = vetoes.length ? vetoes.slice(0,10).map(r => `
              <tr><td>$${r.time || ''}</td><td>$${r.signal || ''}</td><td>$${r.gate || r.outcome || ''}</td></tr>
            `).join('') : '<tr><td colspan="3" class="empty">No vetoes</td></tr>';
          }
        } catch(e) {}
      } catch(err) { console.error('decision chain load failed', err); }
    }

    async function loadIntents() {
      try {
        const res = await fetch(api('/intents.json?' + cb()));
        const data = await res.json();
        const rows = data.rows || [];
        const body = document.getElementById('intentsBody');
        if (!body) return;
        body.innerHTML = rows.length ? rows.map(r => `
          <tr>
            <td>$${r.intent_id || ''}</td>
            <td>$${r.origin_strategy || r.symbol || ''}</td>
            <td>$${r.action || ''}</td>
            <td>$${r.state || ''}</td>
            <td>$${r.created_ts || ''}</td>
            <td><button class="btn secondary" data-intent="$${r.intent_id || ''}">Cancel</button></td>
          </tr>`).join('') : '<tr><td colspan="6" class="empty">No active intents</td></tr>';
        if (rows.length) {
          body.querySelectorAll('button[data-intent]').forEach(btn => {
            btn.addEventListener('click', () => cancelIntent(btn.getAttribute('data-intent')));
          });
        }
      } catch(err) { console.error('intents load failed', err); }
    }

    
    async function loadRisk() {
      try {
        const res = await fetch(api('/risk.json?' + cb()));
        const data = await res.json();
        const state = data.state || {};
        const metrics = data.metrics || {};
        const line = document.getElementById('riskStateLine');
        if (line) line.innerText = `State: $${state.state || 'OK'} | Reason: $${state.reason || '|'}`;
        const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.innerText = (val !== undefined && val !== null) ? val : '|'; };
        const ddVal = (metrics.drawdown_pct !== undefined && metrics.drawdown_pct !== null) ? metrics.drawdown_pct : metrics.max_drawdown;
        setVal('riskPnl', metrics.daily_pnl_pct);
        setVal('riskDd', ddVal);
        setVal('riskReject', metrics.rejected);
        setVal('riskStale', metrics.market_stale_events);
        const setBar = (id, pct) => { const el = document.getElementById(id); if (!el) return; const v = Math.max(0, Math.min(100, Number(pct) || 0)); el.style.width = v + '%'; };
        setBar('riskPnlBar', Math.min(100, Math.abs(Number(metrics.daily_pnl_pct) || 0) * 10));
        setBar('riskDdBar', Math.min(100, Math.abs(Number(ddVal) || 0) * 10));
        setBar('riskRejectBar', Math.min(100, (Number(metrics.rejected) || 0) * 10));
        setBar('riskStaleBar', Math.min(100, (Number(metrics.market_stale_events) || 0) * 10));
      } catch(err) { console.error('risk load failed', err); }
    }

    
    async function loadRiskTimeline(){
      try{
        const res = await fetch(api('/risk_timeline.json?' + cb()));
        const data = await res.json();
        const rows = data.rows || [];
        const body = document.getElementById('riskTimelineBody');
        if (!body) return;
        body.innerHTML = rows.length ? rows.slice(0,5).map(r => `
          <tr><td>$${r.ts || ''}</td><td>$${r.detail || r.type || ''}</td></tr>
        `).join('') : '<tr><td colspan="2" class="empty">No events</td></tr>';
      }catch(e){ console.error('risk timeline failed', e); }
    }

async function loadPerformance() {
      try {
        const res = await fetch(api('/performance.json?' + cb()));
        const data = await res.json();
        const row = data.row || {};
        const body = document.getElementById('perfBody');
        if (!body) return;
        body.innerHTML = `<tr>
          <td>$${row.trades || 'N/A'}</td>
          <td>$${row.win_rate || 'N/A'}</td>
          <td>$${row.fees || 'N/A'}</td>
          <td>$${row.avg_slippage || 'N/A'}</td>
          <td>$${row.max_drawdown || 'N/A'}</td>
        </tr>`;
      } catch(err) { console.error('performance load failed', err); }
    }

    async function loadAlerts() {
      try {
        const res = await fetch(api('/alerts.json?' + cb()));
        const data = await res.json();
        const rows = data.rows || [];
        const body = document.getElementById('alertsBody');
        if (!body) return;
        body.innerHTML = rows.length ? rows.map(r => `
          <tr><td>$${r.severity || 'info'}</td><td>$${r.source || ''}</td><td>$${r.reason || ''}</td><td>$${r.action || ''}</td></tr>
        `).join('') : '<tr><td colspan="4" class="empty">No alerts</td></tr>';
      } catch(err) { console.error('alerts load failed', err); }
    }

    
    async function loadAudit() {
      try {
        const res = await fetch(api('/audit.json?' + cb()));
        const data = await res.json();
        let rows = data.rows || [];
        const typeF = ((document.getElementById('auditFilterType') || {}).value || '').toLowerCase();
        const srcF = ((document.getElementById('auditFilterSource') || {}).value || '').toLowerCase();
        const sevF = ((document.getElementById('auditFilterSeverity') || {}).value || '').toLowerCase();
        const intentF = ((document.getElementById('auditFilterIntent') || {}).value || '').toLowerCase();
        if (typeF || srcF || sevF || intentF) {
          rows = rows.filter(r => {
            const t = String(r.type||'').toLowerCase();
            const d = String(r.detail||'').toLowerCase();
            return (!typeF || t.includes(typeF)) && (!srcF || d.includes(srcF)) && (!sevF || d.includes(sevF)) && (!intentF || d.includes(intentF));
          });
        }
        const body = document.getElementById('auditBody');
        if (!body) return;
        body.innerHTML = rows.length ? rows.map((r, idx) => `
          <tr data-idx="$${idx}"><td>$${r.ts || ''}</td><td>$${r.type || ''}</td><td>$${r.detail || ''}</td></tr>
        `).join('') : '<tr><td colspan="3" class="empty">No audit events</td></tr>';
        if (rows.length) {
          body.querySelectorAll('tr').forEach(tr => {
            tr.style.cursor = 'pointer';
            tr.addEventListener('click', () => {
              const i = Number(tr.getAttribute('data-idx')) || 0;
              openRawJson(rows[i]);
            });
          });
        }
      } catch(err) { console.error('audit load failed', err); }
    }

    const AGENTS = ${AGENTS_JSON};
    const AGENT_HEALTH = ${AGENT_HEALTH_JSON};
    const AGENT_ALIAS = ${AGENT_ALIAS_JSON};
    const BEE_ORDER = ${BEE_ORDER_JSON};
    const CONFIG_WATCH_ADDRESS = '$WATCH_ADDRESS';
    const AGENT_ICONS = {
      coordinator: 'coordinator.png',
      market: 'market.png',
      market_data: 'market.png',
      coingecko: 'market.png',
      sentiment: 'market.png',
      trend: 'market.png',
      oracle: 'oracle.png',
      council: 'council.png',
      nurse: 'nurse.png',
      strategy: 'strategy.png',
      execution: 'execution.png',
      wallet: 'wallet.png',
      data_store: 'datastore.png',
      datastore: 'datastore.png',
      logging: 'logging.png',
      kill_switch: 'killswitch.png',
      killswitch: 'killswitch.png',
      ui: 'ui.png',
      network: 'network.png',
      performance: 'performance.png',
      security: 'security.png',
      worker_sma: 'strategy.png',
      worker_rsi: 'workerRSI.png',
      worker_breakout: 'workerBreakout.png',
      worker_momentum: 'workerMomentum.png',
    };
    const BEE_ICONS = {
      QUEEN: 'coordinator.png',
      ORACLE: 'oracle.png',
      COUNCIL: 'council.png',
      NURSE: 'nurse.png',
      BUZZKILL: 'killswitch.png',
      SCOUT: 'market.png',
      SENTRY: 'wallet.png',
      HUM: 'network.png',
      STING: 'execution.png',
      HONEYCOMB: 'datastore.png',
      SCRIBE: 'logging.png',
      OBSERVER: 'performance.png',
      WAX: 'security.png',
      GLASS: 'ui.png',
      'WORKER-SMA': 'strategy.png',
      'WORKER-RSI': 'workerRSI.png',
      'WORKER-BREAKOUT': 'workerBreakout.png',
      'WORKER-MOMENTUM': 'workerMomentum.png',
    };
    const AGENT_NORM = {};
    function normAgentKey(s){
      return String(s || '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$$/g, '');
    }
    AGENTS.forEach(a => { AGENT_NORM[normAgentKey(a)] = a; });
    function beeNameFor(agent){
      const key = normAgentKey(agent);
      if (AGENT_ALIAS && AGENT_ALIAS[key]) return AGENT_ALIAS[key];
      return agent;
    }
    function beeList(){
      if (Array.isArray(BEE_ORDER) && BEE_ORDER.length) return BEE_ORDER;
      const seen = {};
      const out = [];
      AGENTS.forEach(a => {
        const bee = beeNameFor(a);
        if (!seen[bee]) { seen[bee] = true; out.push(bee); }
      });
      return out;
    }
    function beeStatus(bee){
      let active = false;
      AGENTS.forEach(a => {
        if (beeNameFor(a) !== bee) return;
        const statusRaw = AGENT_HEALTH && AGENT_HEALTH[a];
        if (statusRaw && String(statusRaw).toLowerCase().includes('active')) active = true;
      });
      return active;
    }
    function buzzSentence(raw, bee){
      let msg = (raw || '').toString().trim();
      if (!msg || msg.toLowerCase() === 'no recent messages' || msg.toLowerCase() === 'no payload' || msg === '|' || msg === '-' || msg === 'N/A'){
        const defaults = {
          QUEEN: "I'm coordinating the hive decisions and waiting for signals",
          ORACLE: "I'm reading the regime and confidence in market conditions",
          COUNCIL: "I'm comparing strategy proposals and normalizing signals",
          NURSE: "I'm reviewing recent trades for drift and anomalies",
          BUZZKILL: "I'm monitoring risk and ready to halt if safety is breached",
          SCOUT: "I'm scanning price, volume, and spread changes",
          SENTRY: "I'm watching wallet balances and transfers",
          HUM: "I'm relaying messages across the swarm bus",
          STING: "I'm standing by to execute approved orders",
          HONEYCOMB: "I'm storing events, trades, and history",
          SCRIBE: "I'm recording logs and system notes",
          OBSERVER: "I'm tracking performance, drawdown, and slippage",
          WAX: "I'm protecting keys and enforcing security policy",
          GLASS: "I'm presenting the dashboard and controls",
          'WORKER-SMA': "I'm evaluating SMA crossovers for trend signals",
          'WORKER-RSI': "I'm looking for RSI mean-reversion setups",
          'WORKER-BREAKOUT': "I'm hunting for volatility breakouts",
          'WORKER-MOMENTUM': "I'm tracking short-term momentum bursts",
        };
        msg = defaults[bee] || 'I am on standby for updates';
      } else {
        const preface = {
          QUEEN: "I'm coordinating the hive. ",
          ORACLE: "I'm reading the regime. ",
          COUNCIL: "I'm comparing the strategies. ",
          NURSE: "I'm reviewing recent trades. ",
          BUZZKILL: "I'm on risk watch. ",
          SCOUT: "I'm scanning the market. ",
          SENTRY: "I'm monitoring the wallet. ",
          HUM: "I'm keeping the swarm in sync. ",
          STING: "I'm ready to execute. ",
          HONEYCOMB: "I'm storing the hive's memory. ",
          SCRIBE: "I'm keeping the record. ",
          OBSERVER: "I'm tracking performance. ",
          WAX: "I'm guarding security. ",
          GLASS: "I'm presenting the hive view. ",
          'WORKER-SMA': "I'm watching for SMA signals. ",
          'WORKER-RSI': "I'm watching for RSI extremes. ",
          'WORKER-BREAKOUT': "I'm watching for breakouts. ",
          'WORKER-MOMENTUM': "I'm watching momentum swings. ",
        };
        msg = (preface[bee] || '') + "Here's what I'm seeing: " + msg;
      }
      const last = msg.slice(-1);
      if (last !== '.' && last !== '!' && last !== '?') msg = msg + '.';
      return 'buzz buzz ' + msg;
    }
    function renderAlerts(msgs) {
      const body = document.getElementById('alertsBody');
      if (!body) return;
      const alerts = msgs.filter(m => (m.buzz && m.buzz.type || '').includes('alert'));
      if (!alerts.length) {
        body.innerHTML = '<tr><td colspan="4" class="empty">No alerts</td></tr>';
        return;
      }
      body.innerHTML = alerts.map(m => {
        const p = m.payload || {};
       return `<tr><td>$${p.severity || 'info'}</td><td>$${(m.buzz && m.buzz.source) || ''}</td><td>$${p.reason || ''}</td><td>$${p.action || ''}</td></tr>`;
      }).join('');
    }
    function renderAudit(msgs) {
      const body = document.getElementById('auditBody');
      if (!body) return;
      if (!msgs.length) { body.innerHTML = '<tr><td colspan="3" class="empty">No audit events</td></tr>'; return; }
      body.innerHTML = msgs.slice(0,10).map(m => {
        const ts = (m.buzz && m.buzz.ts) || '';
        const type = (m.buzz && m.buzz.type) || '';
        const detail = m.payload ? JSON.stringify(m.payload).slice(0,80) : '';
       return `<tr><td>$${ts}</td><td>$${type}</td><td>$${detail}</td></tr>`;
      }).join('');
    }
    function renderAgentOutputs(latestMap, metaMap) {
      const cont = document.getElementById('agentOutputs');
      if (!cont) return;
      if (!cont.dataset.init) {
        cont.className = 'bee-grid';
        cont.innerHTML = '';
        const bees = beeList();
        bees.forEach(bee => {
          const icon = BEE_ICONS[bee] || 'ui.png';
          const dot = beeStatus(bee) ? 'green' : 'red';
          const div = document.createElement('div');
          div.className = 'bee-card';
          div.id = 'bee-' + safeId(bee);
          div.innerHTML =
            '<img class="agent-icon-lg ' + dot + '" src="/static/' + icon + '" alt="' + bee + '"/>' +
            '<div class="bee-meta">' +
              '<div class="bee-name">' + bee + '</div>' +
              '<div class="bee-badges"></div>' +
              '<div class="bee-msg">' + buzzSentence('', bee) + '</div>' +
            '</div>';
          cont.appendChild(div);
        });
        cont.dataset.init = '1';
      }
      const map = latestMap || {};
      const meta = metaMap || {};
      window.__beeLastMeta = window.__beeLastMeta || {};
      const nowTs = Date.now();
      const beeMsgs = {};
      AGENTS.forEach(a => {
        const bee = beeNameFor(a);
        if (!beeMsgs[bee] && map[a]) beeMsgs[bee] = map[a];
        if (!beeMsgs[bee] && map[bee]) beeMsgs[bee] = map[bee];
      });
      const bees = beeList();
      bees.forEach(bee => {
        const el = document.getElementById('bee-' + safeId(bee));
        if (!el) return;
        const msg = buzzSentence(beeMsgs[bee] || '', bee);
        const badgeWrap = el.querySelector('.bee-badges');
        const msgEl = el.querySelector('.bee-msg');
        const isMajor = meta[bee] && meta[bee].major;
        const isVeto = meta[bee] && meta[bee].veto;
        const isPenalty = meta[bee] && meta[bee].penalty;
        const shouldUpdate = isMajor || isVeto || isPenalty;
        if (shouldUpdate) {
          window.__beeLastMeta[bee] = { ts: nowTs, veto: !!isVeto, penalty: !!isPenalty };
          if (msgEl) {
            msgEl.textContent = msg;
            el.classList.remove('buzzing');
            void el.offsetWidth;
            el.classList.add('buzzing');
          }
        }
        // apply badges, with auto-clear after 15s
        const last = window.__beeLastMeta[bee] || {};
        const activeVeto = last.veto && (nowTs - (last.ts || 0) < 15000);
        const activePenalty = last.penalty && (nowTs - (last.ts || 0) < 15000);
        if (activeVeto) {
          el.classList.add('veto');
        } else {
          el.classList.remove('veto');
        }
        if (activePenalty) {
          el.classList.add('penalty');
        } else {
          el.classList.remove('penalty');
        }
        if (badgeWrap) {
          const badges = [];
          if (isMajor) badges.push('<span class="bee-badge major">BUZZ</span>');
          if (activeVeto) badges.push('<span class="bee-badge veto">VETO</span>');
          if (activePenalty) badges.push('<span class="bee-badge penalty">STRIKE</span>');
          badgeWrap.innerHTML = badges.join('');
        }
      });
    }

    function isMajorBuzz(m){
      const typ = (m.buzz && m.buzz.type) || '';
      if (!typ) return false;
      const major = [
        'buzz.trade.execution',
        'buzz.trade.request',
        'buzz.coordinator.decision',
        'buzz.swarmguard.decision',
        'buzz.kill.check',
        'buzz.security.policy',
        'buzz.wallet.balance',
        'buzz.regime.snapshot',
        'buzz.council.pack',
      ];
      return major.some(t => typ.startsWith(t));
    }
    function isVetoBuzz(m){
      const typ = (m.buzz && m.buzz.type) || '';
      const p = m.payload || {};
      if (typ.includes('veto')) return true;
      const decision = (p.decision || p.gate || p.status || '').toString().toUpperCase();
      const reason = (p.reason || p.rationale || '').toString().toUpperCase();
      return decision.includes('VETO') || reason.includes('VETO');
    }
    function isPenaltyBuzz(m){
      const p = m.payload || {};
      const reason = (p.reason || p.notes || p.detail || '').toString().toUpperCase();
      if (p.penalty || p.consensus_penalty || p.weight_decay) return true;
      return reason.includes('PENALTY') || reason.includes('DECAY') || reason.includes('CONSENSUS');
    }
    function buzzTargets(m, srcKey){
      const out = [];
      try {
        const srcBee = beeNameFor(srcKey);
        if (srcBee) out.push(srcBee);
        const p = m.payload || {};
        const strat = p.strategy || p.worker || p.origin_strategy || (p.proposal && p.proposal.strategy);
        if (strat) {
          const s = String(strat);
          const bee = (BEE_ICONS && BEE_ICONS[s]) ? s : (AGENT_ALIAS && AGENT_ALIAS[normAgentKey(s)] ? AGENT_ALIAS[normAgentKey(s)] : s);
          out.push(bee);
        }
      } catch(e) { }
      // unique
      const uniq = {};
      const res = [];
      out.forEach(x => { if (x && !uniq[x]) { uniq[x] = true; res.push(x); } });
      return res;
    }
    function summarizeBuzz(m){
      const typ = (m.buzz && m.buzz.type) || '';
      const p = m.payload || {};
      if (typ === 'buzz.swarmguard.decision') {
        const d = p.decision || '';
        const r = p.reason || '';
        return (String(d || '') + ' ' + String(r || '')).trim();
      }
      if (typ === 'buzz.coordinator.decision') {
        return (String(p.action || '') + ' ' + String(p.symbol || '') + ' ' + String(p.reason || '')).trim();
      }
      if (typ === 'buzz.trade.execution') {
        return ('Execution ' + String(p.status || '') + ' ' + String(p.symbol || '')).trim();
      }
      if (typ === 'buzz.trade.request') {
        return ('Request ' + String(p.side || '') + ' ' + String(p.symbol || '')).trim();
      }
      if (typ === 'buzz.kill.check') {
        return ('KillSwitch ' + String(p.risk_state || p.state || '') + ' ' + String(p.reason || '')).trim();
      }
      if (typ === 'buzz.security.policy') {
        return ('Policy armed=' + String(p.armed) + ' paused=' + String(p.paused)).trim();
      }
      if (typ === 'buzz.wallet.balance') {
        return ('Wallet updated (' + String((p.balances || []).length) + ' assets)'); 
      }
      if (typ === 'buzz.regime.snapshot') {
        return ('Regime ' + String(p.regime || '') + ' (' + String(p.confidence || '') + ')');
      }
      if (typ === 'buzz.council.pack') {
        return ('Council ' + String(p.count || 0) + ' proposals');
      }
      if (p && typeof p === 'object') {
        const msg = p.message || p.notes || p.reason;
        if (msg) return String(msg).slice(0,120);
      }
      return (m.summary || (m.payload ? String(m.payload).slice(0,120) : 'No recent messages'));
    }
    async function pollBuzz() {
      try {
        const res = await fetch(api('/buzz/recent?' + cb()));
        const data = await res.json();
        const msgs = data.messages || [];
        const latest = {};
        const meta = {};
        msgs.forEach(m => {
          const srcRaw = (m.buzz && m.buzz.source) || 'UI';
          const key = AGENT_NORM[normAgentKey(srcRaw)] || AGENT_NORM[normAgentKey((m.buzz && m.buzz.type) || '')] || String(srcRaw);
          const veto = isVetoBuzz(m);
          const penalty = isPenaltyBuzz(m);
          if (!isMajorBuzz(m) && !veto && !penalty) return;
          const msgText = summarizeBuzz(m);
          const targets = buzzTargets(m, key);
          targets.forEach(bee => {
            latest[bee] = msgText;
            meta[bee] = { major: true, veto: veto, penalty: penalty };
          });
        });
        renderAgentOutputs(latest, meta);
      } catch(err) {
        console.error('buzz poll failed', err);
      } finally {
        setTimeout(pollBuzz, 3000);
      }
    }


    function tickClock(){
      const el = document.getElementById('clock');
      if (!el) return;
      const now = new Date();
      el.innerText = now.toLocaleTimeString();
    }
    async function loadHealth(){
      try{
        const res = await fetch(api('/wallet.json?' + cb()));
        const w = await res.json();
        const ok = w && ((w.network && w.network.ok) || (Array.isArray(w.balances) && w.balances.length > 0));
        const set = (id, on)=>{ const el=document.getElementById(id); if(!el) return; const dot=el.querySelector('.dot'); if(dot){ dot.style.background = on ? '#3ad29f' : '#ff6b6b'; dot.style.boxShadow = on ? '0 0 6px rgba(58,210,159,0.8)' : '0 0 6px rgba(255,107,107,0.8)'; } };
        set('healthWallet', !!ok);
        set('healthMarket', true);
        set('healthExec', true);
        set('healthBus', true);
      }catch(e){ /* ignore */ }
    }

    async function loadWallet(){
      try{
        const res = await fetch(api('/wallet.json?' + cb()));
        const w = await res.json();
        window.__lastWallet = w;
        const primary = document.getElementById('walletPrimary');
        const sub = document.getElementById('walletSub');
        const list = document.getElementById('walletBalances');
        const warn = document.getElementById('walletWarn');
        if (!primary || !sub || !list) return;
        if (w.error) {
          primary.innerText = 'N/A';
          sub.innerText = w.error;
          list.innerText = '';
          if (warn) { warn.style.display = 'none'; warn.innerText = ''; }
          return;
        }
        const eth = (w.eth && w.eth.balance !== null && w.eth.balance !== undefined) ? Number(w.eth.balance) : null;
        primary.innerText = eth !== null && !Number.isNaN(eth) ? eth.toFixed(6) : 'N/A';
        const addr = w.address ? String(w.address) : '';
        sub.innerText = addr ? ('Watching ' + addr.slice(0,6) + '...' + addr.slice(-4)) : 'ETH balance';
        if (warn) {
          const cfgAddr = (CONFIG_WATCH_ADDRESS || '').toLowerCase();
          const actual = addr.toLowerCase();
          if (!cfgAddr) {
            warn.innerText = 'No watch address configured.';
            warn.style.display = 'block';
          } else if (cfgAddr && actual && cfgAddr !== actual) {
            warn.innerText = 'Config watch address mismatch. UI: ' + (addr.slice(0,6) + '...' + addr.slice(-4));
            warn.style.display = 'block';
          } else {
            warn.style.display = 'none';
            warn.innerText = '';
          }
        }
        const balsRaw = Array.isArray(w.balances) ? w.balances : [];
        const agg = {};
        for (const b of balsRaw){
          const a = String(b.asset || '').toUpperCase().trim();
          if (!a) continue;
          const free = Number(b.free || 0);
          const locked = Number(b.locked || 0);
          if (!agg[a]) agg[a] = {free: 0, locked: 0};
          agg[a].free += free;
          agg[a].locked += locked;
        }
        const minBal = 1e-8;
        const bals = Object.keys(agg)
          .map(a => ({asset: a, free: agg[a].free, locked: agg[a].locked}))
          .filter(b => {
            const total = Math.abs(Number(b.free) || 0) + Math.abs(Number(b.locked) || 0);
            return total > minBal;
          });
        if (!bals.length) {
          list.innerText = '';
          return;
        }
        const parts = bals.map(b => {
          const a = b.asset || '';
          const f = (b.free !== undefined && b.free !== null) ? Number(b.free) : null;
          if (f === null || Number.isNaN(f)) return a;
          return a + ': ' + f.toFixed(6);
        });
        list.innerText = parts.join(' | ');
      }catch(e){ /* ignore */ }
    }

    function applyStatus(dryRun, paused, riskState){
      const mode = dryRun ? 'DRY RUN' : 'LIVE';
      const pillMode = document.getElementById('pillMode');
      if (pillMode) pillMode.innerText = mode;
      const modeLine = document.getElementById('modeLine');
      if (modeLine) modeLine.innerText = 'Mode: ' + mode + ' | ' + (paused ? 'PAUSED' : 'RUNNING');
      const brandSub = document.querySelector('.brand-sub');
      if (brandSub) {
        const parts = brandSub.innerText.split('|').map(p => p.trim());
        if (parts.length >= 1) {
          parts[0] = mode;
          brandSub.innerText = parts.join(' | ');
        }
      }
      const pillRun = document.getElementById('pillRun');
      if (pillRun) {
        pillRun.innerText = paused ? 'PAUSED' : 'RUNNING';
        pillRun.style.background = paused ? 'rgba(255,107,107,0.15)' : 'rgba(58,210,159,0.12)';
        pillRun.style.borderColor = paused ? 'rgba(255,107,107,0.45)' : 'rgba(58,210,159,0.45)';
      }
      const pillRisk = document.getElementById('pillRisk');
      if (pillRisk) {
        const rs = (riskState && riskState.state) ? riskState.state : 'OK';
        pillRisk.innerText = 'RISK: ' + rs;
      }
    }

    async function loadStatus(){
      try{
        const res = await fetch(api('/status.json?' + cb()));
        const st = await res.json();
        applyStatus(!!st.dry_run, !!st.paused, st.kill_state || {});
      }catch(e){ /* ignore */ }
    }

    loadPrice(); loadAltPrices(); loadMetrics(); loadMarketSnapshot(); loadAnalytics(); loadSwarmGuard(); loadOverride(); loadAutonomy(); loadBuzzSummary(); loadCoinSelection(); loadRegime(); loadCouncil(); loadCycle(); loadGovernance(); loadTrades(); loadSignals(); loadDecisionChain(); loadIntents(); loadRisk(); loadPerformance(); loadAlerts(); loadAudit(); loadRiskTimeline(); loadDexPending(); pollBuzz();
    tickClock(); loadHealth(); loadWallet(); loadStatus();
    setInterval(tickClock, 1000);
    setInterval(loadHealth, 10000);
    setInterval(loadWallet, 10000);
    setInterval(loadStatus, 5000);

    setInterval(loadPrice, 5000);
    setInterval(loadAltPrices, 10000);
    setInterval(loadMetrics, 5000);
    setInterval(loadTrades, 5000);
    setInterval(loadMarketSnapshot, 5000);
    setInterval(loadAnalytics, 7000);
    setInterval(loadSwarmGuard, 7000);
    setInterval(loadOverride, 10000);
    setInterval(loadAutonomy, 10000);
    setInterval(loadBuzzSummary, 10000);
    setInterval(loadCoinSelection, 10000);
    setInterval(loadRegime, 7000);
    setInterval(loadCouncil, 7000);
    setInterval(loadCycle, 5000);
    setInterval(loadGovernance, 7000);
    setInterval(loadSignals, 7000);
    setInterval(loadDecisionChain, 7000);
    setInterval(loadIntents, 7000);
    setInterval(loadDexPending, 5000);
    setInterval(loadRisk, 7000);
    setInterval(loadPerformance, 7000);
    setInterval(loadAlerts, 7000);
    setInterval(loadAudit, 7000);
    setInterval(loadRiskTimeline, 7000);
  </script>
    </main>
  </div>
</body>
</html>
        """)

        onchain_enabled = False
        walletconnect_id = ""
        onchain_chain_id = 1
        onchain_rpc_url = ""
        onchain_chain_name = "Ethereum"
        onchain_explorer = ""
        try:
            if self.coordinator and getattr(self.coordinator, 'cfg', None):
                onchain_enabled = bool(getattr(self.coordinator.cfg, 'onchain_enabled', False))
                walletconnect_id = getattr(self.coordinator.cfg, 'walletconnect_project_id', '') or ''
                onchain_chain_id = int(getattr(self.coordinator.cfg, 'onchain_chain_id', 1) or 1)
                onchain_rpc_url = getattr(self.coordinator.cfg, 'web3_rpc_url', '') or ''
                # Provide a friendly chain name for wallet add/switch
                if onchain_chain_id == 8453:
                    onchain_chain_name = "Base"
                    onchain_explorer = "https://basescan.org"
                elif onchain_chain_id == 1:
                    onchain_chain_name = "Ethereum"
                    onchain_explorer = "https://etherscan.io"
        except Exception:
            onchain_enabled = False
            walletconnect_id = ""
            onchain_chain_id = 1
            onchain_rpc_url = ""
            onchain_chain_name = "Ethereum"
            onchain_explorer = ""

        try:
            chain_hex = hex(int(onchain_chain_id))
        except Exception:
            chain_hex = "0x1"

        # Build secondary market charts from configured symbols (only traded pairs)
        alt_markets = []
        alt_charts_html = '<div class="mini-charts" style="display:none;"></div>'
        try:
            cfg_symbols = []
            try:
                if getattr(self.coordinator.cfg, 'multi_symbol_enabled', False):
                    cfg_symbols = list(getattr(self.coordinator.cfg, 'multi_symbols', []) or [])
            except Exception:
                cfg_symbols = []
            if not cfg_symbols:
                cfg_symbols = [symbol] if symbol else []
            # If on-chain is enabled and allowlist exists, filter to those pairs
            try:
                if getattr(self.coordinator.cfg, 'onchain_enabled', False):
                    allowed = getattr(self.coordinator.cfg, 'onchain_allowed_pairs', []) or []
                    if allowed:
                        cfg_symbols = [s for s in cfg_symbols if s in allowed] or cfg_symbols
            except Exception:
                pass
            # unique while preserving order
            seen = set()
            cfg_symbols = [s for s in cfg_symbols if s and not (s in seen or seen.add(s))]
            alt_symbols = [s for s in cfg_symbols if s != symbol]
            palette = ['#7fd1ff', '#b4ff6a', '#ffb86b', '#ffd24a', '#9fb0d8', '#ff6b6b']
            for idx, sym in enumerate(alt_symbols):
                base = sym.split('/')[0] if isinstance(sym, str) else str(sym)
                safe = ''.join([c for c in base if c.isalnum()]) or f"S{idx+1}"
                # ensure unique ids
                existing_ids = {m['id'] for m in alt_markets}
                if safe in existing_ids:
                    safe = f"{safe}{idx+1}"
                alt_markets.append({
                    "id": safe,
                    "symbol": sym,
                    "label": sym,
                    "color": palette[idx % len(palette)],
                })
            if alt_markets:
                cards = []
                for m in alt_markets:
                    cards.append(
                        f'<div class="mini-chart-card">'
                        f'<div class="mini">{m["label"]}</div>'
                        f'<div class="mini-chart"><canvas id="priceChart_{m["id"]}"></canvas></div>'
                        f'</div>'
                    )
                alt_charts_html = '<div class="mini-charts">' + ''.join(cards) + '</div>'
        except Exception:
            alt_markets = []
            alt_charts_html = '<div class="mini-charts" style="display:none;"></div>'

        html = tmpl.substitute(
            MODE='Loading...',
            EXCHANGE=exchange,
            SYMBOL=symbol,
            MAX_DD=max_dd,
            AGENT_COUNT=agent_count,
            LATEST_PRICE=latest_price_str,
            WALLET_ETH=wallet_eth,
            PNL=pnl_val,
            WINRATE=win_rate_val,
            CPU=cpu_val,
            MEM=mem_val,
            MAX_NOTIONAL=max_notional,
            COOLDOWN=cooldown,
            SPREAD_GUARD=spread_guard,
            THROTTLE_MULT=throttle_mult,
            ORDER_PREF=order_pref,
            MARKET_STALE_SEC=market_stale_sec,
            WALLET_STALE_SEC=wallet_stale_sec,
            SLIPPAGE_THRESHOLD=slippage_threshold,
            THROTTLE_CLEAR_SEC=throttle_clear_sec,
            KILL_SWITCH_GRACE_SEC=kill_switch_grace_sec,
            KILL_SWITCH_ENFORCE_STALE=str(kill_switch_enforce_stale).lower(),
            WALLETCONNECT_ID=walletconnect_id,
            ONCHAIN_ENABLED='true' if onchain_enabled else 'false',
            ONCHAIN_DISPLAY='block' if onchain_enabled else 'none',
            ONCHAIN_CHAIN_ID=str(onchain_chain_id),
            ONCHAIN_CHAIN_HEX=chain_hex,
            ONCHAIN_RPC_URL=onchain_rpc_url,
            ONCHAIN_CHAIN_NAME=onchain_chain_name,
            ONCHAIN_EXPLORER_URL=onchain_explorer,
            WATCH_ADDRESS=watch_addr,
            ALT_MARKETS_JSON=json.dumps(alt_markets),
            ALT_CHARTS_HTML=alt_charts_html,

            AGENT_OUTPUTS=agent_outputs_html,
            TRADE_ROWS=trade_rows,
            LOG_TAIL=log_tail,
            AGENTS_JSON=json.dumps(agents),
            AGENT_HEALTH_JSON=json.dumps(agent_health),
            AGENT_ALIAS_JSON=json.dumps(alias_norm),
            BEE_ORDER_JSON=json.dumps(bee_order),
            UI_PORT=str(getattr(self.coordinator.cfg, 'ui_port', self.port)),
        )
        return html

    def _buzz_config(self):
        base_url = ""
        account = ""
        try:
            if self.coordinator and getattr(self.coordinator, "cfg", None):
                base_url = getattr(self.coordinator.cfg, "buzz_base_url", "") or ""
                account = getattr(self.coordinator.cfg, "buzz_account", "") or ""
        except Exception:
            base_url = ""
            account = ""
        if not base_url:
            base_url = "http://localhost:9009"
        if not account:
            account = "hivenance-system"
        return base_url, account

    def _buzz_base_urls(self) -> list:
        """Return a list of base URLs to try (helps in Docker/host setups)."""
        base_url, _ = self._buzz_config()
        urls = [base_url]
        if "localhost" in base_url or "127.0.0.1" in base_url:
            urls.append("http://host.docker.internal:9009")
            urls.append("http://127.0.0.1:9009")
            urls.append("http://localhost:9009")
        # de-dup preserving order
        out = []
        for u in urls:
            if u and u not in out:
                out.append(u)
        return out

    def _buzz_accounts_list(self) -> list:
        """Build a stable list of BUZZ accounts for workers + system."""
        accounts = []
        try:
            # Prefer bee order if present on UI/agent mapping
            agents = list(self.coordinator.agents.keys()) if self.coordinator and getattr(self.coordinator, "agents", None) else []
            # common worker labels from strategy stack
            worker_aliases = [
                "WORKER-RSI",
                "WORKER-BREAKOUT",
                "WORKER-MOMENTUM",
                "WORKER-SMA",
                "WORKER-MACD",
                "WORKER-TREND",
            ]
            for a in agents:
                accounts.append(f"agent.{a}")
            for w in worker_aliases:
                if f"agent.{w}" not in accounts:
                    accounts.append(f"agent.{w}")
            # governance actors (not always registered as agents)
            for gov in ["QUEEN", "COUNCIL", "ORACLE", "KILL_SWITCH", "SECURITY"]:
                acct = f"agent.{gov}"
                if acct not in accounts:
                    accounts.append(acct)
        except Exception:
            pass
        return accounts

    def _read_json_file(self, path: str) -> dict:
        try:
            if path and os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            return {}
        return {}

    def _render_swarmguard_page(self) -> str:
        html = """
        <!DOCTYPE html>
        <html>
        <head>
          <title>SwarmGuard</title>
          <style>
            body { font-family: Arial, sans-serif; background:#071026; color:#ffd24a; margin:0; padding:20px; }
            .wrap { max-width:1100px; margin:0 auto; }
            .card { background:#0d1730; border:1px solid rgba(255,210,74,0.08); border-radius:12px; padding:16px; margin-bottom:14px; }
            .head { display:flex; gap:12px; align-items:center; }
            .head img { width:48px; height:48px; border-radius:12px; padding:6px; background:rgba(255,255,255,0.08); border:1px solid rgba(255,255,255,0.12); }
            .mini { font-size:12px; color:#d9c786; }
            .btn { padding:8px 12px; background:#ffd24a; color:#071026; border:none; border-radius:8px; font-weight:700; cursor:pointer; }
            pre { background:#0f1427; color:#ffd24a; padding:12px; border-radius:10px; overflow:auto; max-height:420px; }
            .grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap:12px; }
            .pill { display:inline-flex; align-items:center; gap:6px; padding:4px 8px; border-radius:999px; background:rgba(255,255,255,0.06); font-size:12px; }
            .ok { color:#3ad29f; }
            .warn { color:#ffd24a; }
            .bad { color:#ff6b6b; }
            .list { margin:6px 0 0 0; padding-left:18px; }
            .row { display:flex; gap:12px; flex-wrap:wrap; }
            .leaderboard-cards { display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:10px; margin-top:8px; }
            .lb-card { border:1px solid rgba(255,255,255,0.08); border-radius:12px; padding:10px; background:rgba(255,255,255,0.04); }
            .lb-card .name { font-weight:700; color:#ffd24a; }
            a { color:#ffd24a; }
          </style>
        </head>
        <body>
          <div class="wrap">
            <a href="/">← Back to Dashboard</a>
            <div class="card">
              <div class="head">
                <img src="/static/swarmguard.png" alt="SwarmGuard">
                <div>
                  <h2 style="margin:0;">SwarmGuard</h2>
                  <div class="mini">Rulebook + risk enforcement view</div>
                </div>
              </div>
            </div>
            <div class="card">
              <h3 style="margin-top:0;">Latest Decision</h3>
              <div class="row">
                <div class="pill" id="sgDecisionPill">Decision: |</div>
                <div class="pill" id="sgReasonPill">Reason: |</div>
                <div class="pill" id="sgSizePill">Adj Size: |</div>
                <div class="pill" id="sgStakePill">BUZZ Stake: |</div>
              </div>
              <div class="grid" style="margin-top:12px;">
                <div class="card" style="margin-bottom:0;">
                  <h4 style="margin:0 0 6px 0;">Permit</h4>
                  <div class="mini" id="sgPermit">Loading...</div>
                </div>
                <div class="card" style="margin-bottom:0;">
                  <h4 style="margin:0 0 6px 0;">Risk Summary</h4>
                  <div class="mini" id="sgRisk">Loading...</div>
                </div>
              </div>
              <div class="card" style="margin-top:12px; margin-bottom:0;">
                <h4 style="margin:0 0 6px 0;">Triggered Rules</h4>
                <ul class="list" id="sgTriggers"><li class="mini">Loading...</li></ul>
              </div>
              <div style="margin-top:10px;">
                <button class="btn" onclick="safetyReset()">Safety Reset</button>
              </div>
            </div>
            <div class="card">
              <h3 style="margin-top:0;">Rulebook</h3>
              <div class="mini" id="sgRulesSummary">Loading...</div>
              <table>
                <thead><tr><th>Rule</th><th>Type</th><th>Action</th><th>Enforced By</th></tr></thead>
                <tbody id="sgRulesTable"><tr><td colspan="4" class="mini">Loading...</td></tr></tbody>
              </table>
              <details>
                <summary class="mini">Show JSON</summary>
                <pre id="sgRules">|</pre>
              </details>
            </div>
            <div class="card">
              <h3 style="margin-top:0;">Risk Register</h3>
              <table>
                <thead><tr><th>Risk</th><th>Category</th><th>Owner</th><th>Impact</th><th>Likelihood</th></tr></thead>
                <tbody id="sgRiskTable"><tr><td colspan="5" class="mini">Loading...</td></tr></tbody>
              </table>
              <details>
                <summary class="mini">Show JSON</summary>
                <pre id="sgRiskRegister">|</pre>
              </details>
            </div>
            <div class="card">
              <h3 style="margin-top:0;">Risk → Agent Map</h3>
              <div id="sgRiskMapViz" class="grid">
                <div class="mini">Loading...</div>
              </div>
              <details>
                <summary class="mini">Show JSON</summary>
                <pre id="sgRiskMap">|</pre>
              </details>
            </div>
            <div class="card">
              <h3 style="margin-top:0;">Governance Leaderboard</h3>
              <div id="sgGovBoard" class="leaderboard-cards"><div class="mini">Loading...</div></div>
            </div>
          </div>
          <script>
            async function loadDecision() {
              try {
                const res = await fetch('/swarmguard.json');
                const data = await res.json();
                const payload = data.payload || {};
                const decision = payload.decision || payload.action || '|';
                const reason = payload.reason || '|';
                const size = payload.position_size !== undefined ? payload.position_size : (payload.adjusted_size || '|');
                const stake = (payload.buzz && payload.buzz.stake_amount !== undefined) ? payload.buzz.stake_amount : '|';
                const pillDecision = document.getElementById('sgDecisionPill');
                const pillReason = document.getElementById('sgReasonPill');
                const pillSize = document.getElementById('sgSizePill');
                const pillStake = document.getElementById('sgStakePill');
                if (pillDecision) pillDecision.innerText = 'Decision: ' + decision;
                if (pillReason) pillReason.innerText = 'Reason: ' + reason;
                if (pillSize) pillSize.innerText = 'Adj Size: ' + size;
                if (pillStake) pillStake.innerText = 'BUZZ Stake: ' + stake;

                const permit = payload.permit || {};
                const permitEl = document.getElementById('sgPermit');
                if (permitEl) {
                  permitEl.innerText =
                    'max_notional_usd=' + (permit.max_notional_usdt ?? '|') +
                    ' | max_position_pct=' + (permit.max_position_pct ?? '|') +
                    ' | max_slippage_bps=' + (permit.max_slippage_bps ?? '|') +
                    ' | cooldown=' + (permit.cooldown_secs ?? '|') + 's';
                }

                const risk = payload.risk || {};
                const riskEl = document.getElementById('sgRisk');
                if (riskEl) {
                  riskEl.innerText = 'vetoed=' + (risk.vetoed ? 'true' : 'false') + ' | triggered=' + ((risk.triggered || []).length);
                }
                const triggers = document.getElementById('sgTriggers');
                if (triggers) {
                  const arr = risk.triggered || [];
                  if (!arr.length) {
                    triggers.innerHTML = '<li class="mini">No triggers</li>';
                  } else {
                    triggers.innerHTML = arr.map(t => {
                      const sev = (t.severity || 'INFO').toUpperCase();
                      const cls = sev === 'VETO' ? 'bad' : (sev === 'WARN' ? 'warn' : 'ok');
                      return '<li><span class="' + cls + '">' + (t.rule_id || '') + '</span> — ' + (t.message || '') + '</li>';
                    }).join('');
                  }
                }
              } catch (e) {
                const triggers = document.getElementById('sgTriggers');
                if (triggers) triggers.innerHTML = '<li class="mini">Failed to load decision: ' + e + '</li>';
              }
            }
            async function loadDocs() {
              try {
                const r1 = await fetch('/swarmguard/rules'); const j1 = await r1.json();
                const r2 = await fetch('/swarmguard/risk_register'); const j2 = await r2.json();
                const r3 = await fetch('/swarmguard/risk_map'); const j3 = await r3.json();
                const p1 = document.getElementById('sgRules'); if (p1) p1.textContent = JSON.stringify(j1, null, 2);
                const p2 = document.getElementById('sgRiskRegister'); if (p2) p2.textContent = JSON.stringify(j2, null, 2);
                const p3 = document.getElementById('sgRiskMap'); if (p3) p3.textContent = JSON.stringify(j3, null, 2);

                // Rulebook summary
                const rules = (j1 && (j1.swarmguard_rules || j1.rules)) || [];
                const summary = document.getElementById('sgRulesSummary');
                if (summary) summary.textContent = 'Total rules: ' + rules.length;
                const table = document.getElementById('sgRulesTable');
                if (table) {
                  if (!rules.length) {
                    table.innerHTML = '<tr><td colspan="4" class="mini">No rules</td></tr>';
                  } else {
                    table.innerHTML = rules.slice(0, 12).map(r => {
                      return '<tr><td>' + (r.rule_id || '') + '</td><td>' + (r.type || '') + '</td><td>' + (r.action || '') + '</td><td>' + (r.enforced_by || '') + '</td></tr>';
                    }).join('');
                  }
                }

                // Risk register summary
                const risks = (j2 && (j2.risk_register || j2.risks)) || [];
                const rtable = document.getElementById('sgRiskTable');
                if (rtable) {
                  if (!risks.length) {
                    rtable.innerHTML = '<tr><td colspan="5" class="mini">No risks</td></tr>';
                  } else {
                    rtable.innerHTML = risks.map(r => {
                      return '<tr><td>' + (r.risk_id || '') + '</td><td>' + (r.category || '') + '</td><td>' + (r.owner || '') + '</td><td>' + (r.impact || '') + '</td><td>' + (r.likelihood || '') + '</td></tr>';
                    }).join('');
                  }
                }

                // Risk map visual
                const rm = (j3 && (j3.risk_agent_control_map || j3.map)) || [];
                const viz = document.getElementById('sgRiskMapViz');
                if (viz) {
                  if (!rm.length) {
                    viz.innerHTML = '<div class="mini">No map entries</div>';
                  } else {
                    viz.innerHTML = rm.map(m => {
                      const agents = (m.agents || []).map(a => '<span class="pill">' + a + '</span>').join(' ');
                      const ctrls = (m.controls || []).map(c => '<span class="pill">' + c + '</span>').join(' ');
                      return '<div class="card" style="margin-bottom:0;"><div><strong>' + (m.risk_id || '') + '</strong></div><div class="mini" style="margin-top:6px;">Agents:</div><div>' + agents + '</div><div class="mini" style="margin-top:6px;">Controls:</div><div>' + ctrls + '</div></div>';
                    }).join('');
                  }
                }
              } catch (e) {
                const p1 = document.getElementById('sgRules'); if (p1) p1.textContent = 'Failed to load docs: ' + e;
              }
            }
            async function loadGovBoard() {
              const table = document.getElementById('sgGovBoard');
              try {
                const res = await fetch('/buzz/leaderboard');
                const data = await res.json();
                if (!data.ok) {
                  if (table) table.innerHTML = '<div class="mini">BuzzService unavailable</div>';
                  return;
                }
                const rows = (data.rows || []).filter(r => (r.account || '').startsWith('agent.'));
                const gov = rows.filter(r => {
                  const a = (r.account || '').toUpperCase();
                  return a.includes('QUEEN') || a.includes('COUNCIL') || a.includes('ORACLE') || a.includes('KILL_SWITCH') || a.includes('SECURITY');
                });
                if (!gov.length) {
                  if (table) table.innerHTML = '<div class="mini">No governance accounts yet</div>';
                  return;
                }
                if (table) {
                  table.innerHTML = gov.map(r => {
                    return '<div class="lb-card">' +
                      '<div class="name">' + r.account + '</div>' +
                      '<div class="mini">Total: ' + r.total + '</div>' +
                      '<div class="mini">Available: ' + r.available + ' | Locked: ' + r.locked + '</div>' +
                      '<div class="mini">Vol: ' + (r.volatility ? r.volatility.toFixed(2) : '0.00') + '</div>' +
                    '</div>';
                  }).join('');
                }
              } catch (e) {
                if (table) table.innerHTML = '<div class="mini">BuzzService unavailable</div>';
              }
            }
            async function safetyReset() {
              if (!confirm('Reset safety counters, pending execution, and overtrading timers?')) return;
              try {
                const res = await fetch('/swarmguard/reset', { method: 'POST' });
                const data = await res.json();
                alert(data.ok ? 'Safety reset complete.' : 'Safety reset failed: ' + (data.error || 'unknown'));
              } catch (e) {
                alert('Safety reset failed: ' + e);
              }
            }
            loadDecision();
            loadDocs();
            loadGovBoard();
            setInterval(loadDecision, 7000);
            setInterval(loadGovBoard, 12000);
          </script>
        </body>
        </html>
        """
        return html

    def _render_buzz_page(self) -> str:
        base_url, account = self._buzz_config()
        html = """
        <!DOCTYPE html>
        <html>
        <head>
          <title>BuzzCoin</title>
          <style>
            body { font-family: Arial, sans-serif; background:#071026; color:#ffd24a; margin:0; padding:20px; }
            .wrap { max-width:1000px; margin:0 auto; }
            .card { background:#0d1730; border:1px solid rgba(255,210,74,0.08); border-radius:12px; padding:16px; margin-bottom:14px; }
            .head { display:flex; gap:12px; align-items:center; }
            .head img { width:48px; height:48px; border-radius:12px; padding:6px; background:rgba(255,255,255,0.08); border:1px solid rgba(255,255,255,0.12); }
            .mini { font-size:12px; color:#d9c786; }
            table { width:100%; border-collapse:collapse; margin-top:8px; }
            th,td { padding:8px 10px; font-size:13px; text-align:left; }
            th { color:#d9c786; border-bottom:1px solid rgba(255,255,255,0.08); }
            tr:not(:last-child) td { border-bottom:1px solid rgba(255,255,255,0.04); }
            .leaderboard-cards { display:grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap:10px; margin-top:8px; }
            .lb-card { border:1px solid rgba(255,255,255,0.08); border-radius:12px; padding:10px; background:rgba(255,255,255,0.04); }
            .lb-card .name { font-weight:700; color:#ffd24a; }
            .lb-card .mini { margin-top:4px; }
            a { color:#ffd24a; }
          </style>
        </head>
        <body>
          <div class="wrap">
            <a href="/">← Back to Dashboard</a>
            <div class="card">
              <div class="head">
                <img src="/static/buzzcoin.png" alt="BuzzCoin">
                <div>
                  <h2 style="margin:0;">BuzzCoin</h2>
                  <div class="mini">Internal stake ledger (BuzzService)</div>
                </div>
              </div>
              <div class="mini">Service: __BUZZ_BASE__ | Account: __BUZZ_ACCOUNT__</div>
            </div>
            <div class="card">
              <h3 style="margin-top:0;">Account</h3>
              <div id="buzzAccount" class="mini">Loading...</div>
            </div>
            <div class="card">
              <h3 style="margin-top:0;">Admin Credit (set starting BUZZ)</h3>
              <div class="mini">This mints BUZZ into the internal ledger (not on-chain). Requires BuzzService running and shared secret set.</div>
              <form id="buzzCreditForm" style="margin-top:10px; display:flex; gap:10px; flex-wrap:wrap;">
                <input id="buzzAmount" type="number" min="1" step="1" placeholder="Amount" style="padding:8px; border-radius:6px; border:1px solid #2a3350; background:#0f1427; color:#ffd24a;">
                <input id="buzzReason" type="text" placeholder="Reason (optional)" style="padding:8px; border-radius:6px; border:1px solid #2a3350; background:#0f1427; color:#ffd24a; min-width:200px;">
                <button type="submit" style="padding:8px 12px; background:#ffd24a; color:#071026; border:none; border-radius:8px; font-weight:700; cursor:pointer;">Mint BUZZ</button>
              </form>
              <div id="buzzCreditStatus" class="mini" style="margin-top:8px;"></div>
            </div>
            <div class="card">
              <h3 style="margin-top:0;">Ledger (latest)</h3>
              <table>
                <thead><tr><th>Time</th><th>Type</th><th>Amount</th><th>Avail</th><th>Locked</th><th>Ref</th></tr></thead>
                <tbody id="buzzLedger"><tr><td colspan="6" class="mini">Loading...</td></tr></tbody>
              </table>
            </div>
            <div class="card">
              <h3 style="margin-top:0;">BUZZ Volatility (mock)</h3>
              <div class="mini" id="buzzVolatility">Loading...</div>
              <div id="buzzSpark" style="display:flex; gap:4px; margin-top:8px; align-items:flex-end;"></div>
            </div>
            <div class="card">
              <h3 style="margin-top:0;">Leaderboard</h3>
              <div id="buzzLeaderboard" class="leaderboard-cards"><div class="mini">Loading...</div></div>
            </div>
          </div>
          <script>
            async function loadBuzz() {
              const acctEl = document.getElementById('buzzAccount');
              const ledgerEl = document.getElementById('buzzLedger');
              try {
                const res = await fetch('/buzz/status');
                const data = await res.json();
                if (!data.ok) {
                  if (acctEl) acctEl.textContent = 'BuzzService unavailable: ' + (data.error || 'unknown');
                } else {
                  const acct = data.account || {};
                  const avail = (acct.available !== undefined) ? acct.available : (acct.available_buzz ?? 0);
                  const locked = (acct.locked !== undefined) ? acct.locked : (acct.staked_buzz ?? 0);
                  if (acctEl) acctEl.textContent = 'Available: ' + avail + ' | Locked: ' + locked + ' | Updated: ' + (acct.updated_at || '|');
                }
              } catch (e) {
                if (acctEl) acctEl.textContent = 'BuzzService unavailable: ' + e;
              }

              try {
                const res2 = await fetch('/buzz/ledger?limit=25');
                const data2 = await res2.json();
                if (!data2.ok) {
                  if (ledgerEl) ledgerEl.innerHTML = '<tr><td colspan="6">BuzzService unavailable</td></tr>';
                } else {
                  const entries = (data2.ledger && data2.ledger.entries) ? data2.ledger.entries : [];
                  if (!entries.length) {
                    if (ledgerEl) ledgerEl.innerHTML = '<tr><td colspan="6">No ledger entries</td></tr>';
                  } else {
                    const rows = entries.map(e => {
                      const ts = e.ts ? new Date(e.ts * 1000).toLocaleString() : '';
                      return '<tr><td>' + ts + '</td><td>' + (e.entry_type || '') + '</td><td>' + (e.amount || '') + '</td><td>' + (e.balance_available || '') + '</td><td>' + (e.balance_locked || '') + '</td><td>' + (e.ref || '') + '</td></tr>';
                    });
                    if (ledgerEl) ledgerEl.innerHTML = rows.join('');
                  }
                }
              } catch (e) {
                if (ledgerEl) ledgerEl.innerHTML = '<tr><td colspan="6">BuzzService unavailable</td></tr>';
              }
            }

            async function loadLeaderboard() {
              const table = document.getElementById('buzzLeaderboard');
              const volEl = document.getElementById('buzzVolatility');
              const spark = document.getElementById('buzzSpark');
              try {
                const res = await fetch('/buzz/leaderboard');
                const data = await res.json();
                if (!data.ok) {
                  if (table) table.innerHTML = '<div class="mini">BuzzService unavailable</div>';
                  return;
                }
                const rows = data.rows || [];
                if (!rows.length) {
                  if (table) table.innerHTML = '<div class="mini">No accounts yet</div>';
                  return;
                }
                if (table) {
                  table.innerHTML = rows.map(r => {
                    return '<div class="lb-card">' +
                      '<div class="name">' + r.account + '</div>' +
                      '<div class="mini">Total: ' + r.total + '</div>' +
                      '<div class="mini">Available: ' + r.available + ' | Locked: ' + r.locked + '</div>' +
                      '<div class="mini">Vol: ' + (r.volatility ? r.volatility.toFixed(2) : '0.00') + '</div>' +
                    '</div>';
                  }).join('');
                }
                // use top row for "volatility" spark
                const top = rows[0];
                if (volEl) {
                  volEl.textContent = 'Top account: ' + top.account + ' | Volatility: ' + (top.volatility ? top.volatility.toFixed(2) : '0.00');
                }
                if (spark) {
                  spark.innerHTML = '';
                  const series = top.series || [];
                  const max = Math.max(1, ...series.map(v => Math.abs(v)));
                  series.slice(0, 20).forEach(v => {
                    const h = Math.max(4, Math.min(30, Math.round((Math.abs(v) / max) * 30)));
                    const bar = document.createElement('div');
                    bar.style.width = '8px';
                    bar.style.height = h + 'px';
                    bar.style.background = v >= 0 ? '#3ad29f' : '#ff6b6b';
                    bar.style.borderRadius = '3px';
                    spark.appendChild(bar);
                  });
                }
              } catch (e) {
                if (table) table.innerHTML = '<div class="mini">BuzzService unavailable</div>';
              }
            }
            loadBuzz();
            loadLeaderboard();
            setInterval(loadBuzz, 10000);
            setInterval(loadLeaderboard, 12000);

            const creditForm = document.getElementById('buzzCreditForm');
            if (creditForm) {
              creditForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                const amt = Number(document.getElementById('buzzAmount').value || 0);
                const reason = document.getElementById('buzzReason').value || '';
                const status = document.getElementById('buzzCreditStatus');
                if (!amt || amt <= 0) {
                  if (status) status.textContent = 'Enter a valid amount.';
                  return;
                }
                try {
                  const body = `amount=${encodeURIComponent(amt)}&reason=${encodeURIComponent(reason)}`;
                  const res = await fetch('/buzz/credit', { method: 'POST', headers: {'Content-Type':'application/x-www-form-urlencoded'}, body });
                  const data = await res.json();
                  if (!data.ok) {
                    if (status) status.textContent = 'Credit failed: ' + (data.error || 'unknown');
                  } else {
                    if (status) status.textContent = 'Credit ok. Receipt id: ' + ((data.receipt || {}).request_id || '');
                    loadBuzz();
                  }
                } catch (err) {
                  if (status) status.textContent = 'Credit failed: ' + err;
                }
              });
            }
          </script>
        </body>
        </html>
        """
        html = html.replace("__BUZZ_BASE__", _html.escape(base_url)).replace("__BUZZ_ACCOUNT__", _html.escape(account))
        return html

    def _hydrate_onchain_balances(self, wallet, balances: list) -> list:
        """Fill or refresh token balances using on-chain contract calls."""
        try:
            w3 = getattr(wallet, "w3", None)
            addr = getattr(wallet, "addr", None) or getattr(wallet, "address", None)
            if not w3 or not addr:
                return balances
            tokens = getattr(self.coordinator.cfg, "onchain_token_addresses", None) or {}
            if not isinstance(tokens, dict):
                return balances
            # Preserve original ordering, but consolidate duplicates
            order = []
            balance_map = {}
            for b in balances:
                sym_u = str(b.get("asset") or "").upper()
                if not sym_u:
                    continue
                if sym_u not in order:
                    order.append(sym_u)
                try:
                    free = float(b.get("free") or 0)
                except Exception:
                    free = 0.0
                try:
                    locked = float(b.get("locked") or 0)
                except Exception:
                    locked = 0.0
                prev = balance_map.get(sym_u, {"free": 0.0, "locked": 0.0})
                balance_map[sym_u] = {"free": prev["free"] + free, "locked": prev["locked"] + locked}

            # Normalize USD -> USDC if configured
            if "USDC" in tokens and "USD" in balance_map:
                usd = balance_map.pop("USD")
                prev = balance_map.get("USDC", {"free": 0.0, "locked": 0.0})
                balance_map["USDC"] = {"free": prev["free"] + usd["free"], "locked": prev["locked"] + usd["locked"]}
                if "USD" in order:
                    order = [k for k in order if k != "USD"]
                if "USDC" not in order:
                    order.append("USDC")

            # Refresh balances for configured tokens from chain
            for sym, info in tokens.items():
                sym_u = str(sym or "").upper()
                if not sym_u:
                    continue
                addr_token = None
                dec = 18
                if isinstance(info, dict):
                    addr_token = info.get("address") or info.get("addr")
                    try:
                        dec = int(info.get("decimals") or 18)
                    except Exception:
                        dec = 18
                else:
                    addr_token = info
                if not addr_token:
                    continue
                try:
                    contract = w3.eth.contract(address=w3.to_checksum_address(addr_token), abi=ERC20_MIN_ABI)
                    raw = contract.functions.balanceOf(w3.to_checksum_address(addr)).call()
                    bal = float(raw) / (10 ** dec)
                    balance_map[sym_u] = {"free": bal, "locked": 0.0}
                    if sym_u not in order:
                        order.append(sym_u)
                except Exception:
                    continue
            # Rebuild list in stable order
            out = []
            for sym_u in order:
                v = balance_map.get(sym_u)
                if v is None:
                    continue
                out.append({"asset": sym_u, "free": v.get("free", 0.0), "locked": v.get("locked", 0.0)})
            return out
        except Exception:
            return balances
    
    # ------------------------------------------------------------------ helpers
    def _fmt_ts(self, ts) -> str:
        if ts is None:
            return ""
        try:
            if isinstance(ts, (int, float)):
                val = float(ts)
                if val > 1e12:
                    val = val / 1000.0
                return datetime.fromtimestamp(val).strftime("%H:%M:%S")
            if isinstance(ts, str):
                s = ts.strip()
                if s.replace(".", "", 1).isdigit():
                    return self._fmt_ts(float(s))
                return s
        except Exception:
            pass
        return str(ts)

    def _db_query(self, sql: str, params=()):
        ds = self.coordinator.agents.get("data_store") if self.coordinator else None
        db_path = getattr(ds, "db_path", None) if ds else None
        if not db_path:
            return []
        try:
            import sqlite3
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        except sqlite3.DatabaseError as e:
            try:
                if ds and hasattr(ds, "_is_corrupt_error") and ds._is_corrupt_error(e):
                    ds._recover_db(str(e))
            except Exception:
                pass
            logging.exception("db query failed")
            return []
        except Exception:
            logging.exception("db query failed")
            return []

    def _update_config_partial(self, updates: dict) -> bool:
        """Update settings.yaml with a partial dict and reload coordinator config if possible."""
        try:
            cfg = self._load_config() or {}
            if not isinstance(cfg, dict):
                cfg = {}
            cfg.update(updates or {})
            with open(self.config_path, "w") as f:
                yaml.safe_dump(cfg, f)
            try:
                from main import load_config
                new_cfg = load_config()
                if hasattr(self.coordinator, "reload_config"):
                    self.coordinator.reload_config(new_cfg)
                else:
                    self.coordinator.cfg = new_cfg
            except Exception as e:
                logging.warning(f"Config reload failed after partial update: {e}")
            return True
        except Exception as e:
            logging.exception(f"_update_config_partial failed: {e}")
            return False

    def _latest_analytics_payload(self) -> dict:
        try:
            cache = getattr(self.coordinator, "data_cache", {}) or {}
            snap = cache.get("buzz.analytics.snapshot")
            if isinstance(snap, dict):
                return snap.get("payload") if "payload" in snap else snap
        except Exception:
            pass
        # Fallback to last persisted analytics snapshot
        try:
            rows = self._db_query(
                "SELECT payload FROM raw_events WHERE type='buzz.analytics.snapshot' ORDER BY ts DESC LIMIT 1"
            )
            if rows:
                payload = rows[0].get("payload")
                if isinstance(payload, str):
                    return json.loads(payload)
                if isinstance(payload, dict):
                    return payload
        except Exception:
            pass
        return {}

    def _parse_bool(self, value: Any) -> bool:
        """Convert common truthy string values to bool."""
        try:
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("1", "true", "yes", "y", "on")
        except Exception:
            return False

    def _latest_buzz_payload(self, typ: str) -> dict:
        """Fetch latest payload for a given buzz type from cache or DB."""
        try:
            cache = getattr(self.coordinator, "data_cache", {}) or {}
            snap = cache.get(typ)
            if isinstance(snap, dict):
                payload = snap.get("payload") if "payload" in snap else snap
                if isinstance(payload, dict):
                    return payload
        except Exception:
            pass
        try:
            rows = self._db_query(
                "SELECT payload FROM raw_events WHERE type=? ORDER BY ts DESC LIMIT 1",
                (typ,),
            )
            if rows:
                payload = rows[0].get("payload")
                if isinstance(payload, str):
                    return json.loads(payload)
                if isinstance(payload, dict):
                    return payload
        except Exception:
            pass
        # Fallbacks from coordinator recent values
        try:
            if typ == "buzz.regime.snapshot":
                return getattr(self.coordinator, "_last_regime", {}) or {}
            if typ == "buzz.council.pack":
                return getattr(self.coordinator, "_last_council", {}) or {}
        except Exception:
            pass
        return {}

    def _get_latest_analytics_event(self) -> dict:
        """Return the most recent analytics snapshot event (buzz + payload)."""
        try:
            cache = getattr(self.coordinator, "data_cache", {}) or {}
            snap = cache.get("buzz.analytics.snapshot")
            if isinstance(snap, dict) and "payload" in snap:
                return snap
        except Exception:
            pass
        try:
            rows = self._db_query(
                "SELECT ts, type, source, payload FROM raw_events WHERE type='buzz.analytics.snapshot' ORDER BY ts DESC LIMIT 1"
            )
            if rows:
                r = rows[0]
                payload = r.get("payload")
                try:
                    payload = json.loads(payload) if isinstance(payload, str) else (payload or {})
                except Exception:
                    payload = {}
                return {
                    "buzz": {"type": "buzz.analytics.snapshot", "source": r.get("source") or "ANALYTICS", "ts": int(float(r.get("ts") or 0) * 1000)},
                    "payload": payload,
                }
        except Exception:
            pass
        return {}

    def _latest_security_policy(self) -> dict:
        try:
            cache = getattr(self.coordinator, "data_cache", {}) or {}
            snap = cache.get("buzz.security.policy")
            if isinstance(snap, dict):
                return snap.get("payload") if "payload" in snap else snap
        except Exception:
            pass
        try:
            rows = self._db_query(
                "SELECT payload FROM raw_events WHERE type='buzz.security.policy' ORDER BY ts DESC LIMIT 1"
            )
            if rows:
                payload = rows[0].get("payload")
                if isinstance(payload, str):
                    return json.loads(payload)
                if isinstance(payload, dict):
                    return payload
        except Exception:
            pass
        return {}

    def _get_market_snapshot(self) -> dict:
        md = self.coordinator.agents.get("market_data") if self.coordinator else None
        symbol = getattr(self.coordinator.cfg, "symbol", None) if self.coordinator else None
        last = None
        bid = None
        ask = None
        spread = None
        vol = None
        candle_sec = None
        # Try market data agent / client
        try:
            if md and hasattr(md, "fetch_latest_price"):
                last = md.fetch_latest_price()
            client = getattr(md, "client", None) if md else None
            if client and hasattr(client, "fetch_ticker"):
                t = client.fetch_ticker(symbol)
                last = t.get("last") or last
                bid = t.get("bid")
                ask = t.get("ask")
                if bid and ask:
                    spread = (ask - bid) / bid * 100.0 if bid else None
                vol = t.get("baseVolume") or t.get("quoteVolume")
        except Exception:
            pass
        # Fallback to shared latest_price
        if last is None:
            try:
                lp = self.coordinator.get_shared_data("latest_price")
                if isinstance(lp, dict) and "payload" in lp:
                    lp = lp.get("payload")
                if isinstance(lp, (int, float)):
                    last = lp
            except Exception:
                pass
        # Candle countdown (best-effort)
        try:
            if md and hasattr(md, "fetch_closes"):
                times, _ = md.fetch_closes(2)
                if times:
                    last_close = int(times[-1]) / 1000.0
                    interval = getattr(self.coordinator.cfg, "interval", "1m")
                    sec_map = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}
                    candle_sec = sec_map.get(interval, 60)
                    now = time.time()
                    rem = max(0, int(last_close + candle_sec - now))
                else:
                    rem = None
            else:
                rem = None
        except Exception:
            rem = None
        return {
            "last": last,
            "bid": bid,
            "ask": ask,
            "spread_pct": spread,
            "volume_1m": vol,
            "candle_remain_sec": rem,
        }

    def _get_decision_chain_rows(self, limit: int = 20) -> list:
        intents = self._db_query(
            "SELECT intent_id, symbol, action, origin_strategy, created_ts, state, final_outcome, final_reason "
            "FROM intents ORDER BY created_ts DESC LIMIT ?",
            (limit,)
        )
        orders = self._db_query(
            "SELECT client_order_id, intent_id, order_id, side, order_type, status, placed_ts, final_ts "
            "FROM orders ORDER BY placed_ts DESC LIMIT ?",
            (limit * 5,)
        )
        fills = self._db_query(
            "SELECT order_id, client_order_id, filled_qty, avg_price, fee, slippage_pct, ts "
            "FROM fills ORDER BY ts DESC LIMIT ?",
            (limit * 10,)
        )
        raw = self._db_query(
            "SELECT ts, type, source, payload FROM raw_events "
            "WHERE type IN ('buzz.strategy.signal','buzz.coordinator.decision') "
            "ORDER BY ts DESC LIMIT ?",
            (limit * 50,)
        )

        signals = []
        signals_by_id = {}
        used_signal_ids = set()
        decisions_by_intent = {}
        extra_decisions = []
        for r in raw:
            typ = r.get('type')
            payload = r.get('payload')
            try:
                payload = json.loads(payload) if isinstance(payload, str) else (payload or {})
            except Exception:
                payload = {}
            if typ == 'buzz.strategy.signal':
                sig_id = payload.get('signal_id') or payload.get('id')
                sig = {
                    'signal_id': sig_id,
                    'symbol': payload.get('symbol'),
                    'action': payload.get('action'),
                    'strategy': payload.get('strategy'),
                    'confidence': payload.get('confidence'),
                    'ts': payload.get('ts') or r.get('ts'),
                }
                signals.append(sig)
                if sig_id:
                    signals_by_id[sig_id] = sig
            elif typ == 'buzz.coordinator.decision':
                intent_id = payload.get('intent_id')
                dec = {
                    'intent_id': intent_id,
                    'decision': payload.get('decision') or payload.get('state'),
                    'reason': payload.get('reason'),
                    'signal_id': payload.get('signal_id'),
                    'symbol': payload.get('symbol'),
                    'action': payload.get('action'),
                    'ts': payload.get('ts') or r.get('ts'),
                }
                if intent_id:
                    decisions_by_intent[intent_id] = dec
                else:
                    extra_decisions.append(dec)

        def match_signal(symbol, action, signal_id=None):
            if signal_id and signal_id in signals_by_id:
                return signals_by_id.get(signal_id)
            for s in signals:
                if s.get('symbol') == symbol and s.get('action') == action:
                    return s
            return None

        order_by_intent = {}
        for o in orders:
            key = o.get('intent_id')
            if not key:
                continue
            if key not in order_by_intent or (o.get('placed_ts') or 0) > (order_by_intent[key].get('placed_ts') or 0):
                order_by_intent[key] = o

        fill_by_order = {}
        for f in fills:
            key = f.get('order_id') or f.get('client_order_id')
            if key and key not in fill_by_order:
                fill_by_order[key] = f

        rows = []
        for it in intents or []:
            intent_id = it.get('intent_id')
            decision = decisions_by_intent.get(intent_id, {})
            sig = match_signal(it.get('symbol'), it.get('action'), decision.get('signal_id')) if decision else None
            if sig:
                if sig.get('signal_id'):
                    used_signal_ids.add(sig.get('signal_id'))
                conf = sig.get('confidence')
                conf_str = f" ({conf})" if conf is not None else ""
                signal_str = f"{sig.get('strategy') or ''} {sig.get('action') or ''}{conf_str}".strip()
            else:
                signal_str = " ".join([x for x in [it.get('origin_strategy'), it.get('action'), it.get('symbol')] if x])

            if decision.get('decision'):
                gate = decision.get('decision')
                if decision.get('reason'):
                    gate = f"{gate} ({decision.get('reason')})"
            else:
                gate = it.get('state') or "|"

            order = order_by_intent.get(intent_id) or {}
            order_str = " ".join([x for x in [order.get('side'), order.get('order_type'), order.get('status')] if x]) or "|"

            fill = fill_by_order.get(order.get('order_id')) or fill_by_order.get(order.get('client_order_id')) or {}
            execution = "|"
            if fill:
                try:
                    filled = fill.get('filled_qty')
                    avg_price = fill.get('avg_price')
                    slp = fill.get('slippage_pct')
                    execution = f"{filled} @ {avg_price}"
                    if slp is not None:
                        execution += f" (slip {float(slp):.4f})"
                except Exception:
                    execution = "filled"

            outcome = it.get('final_outcome') or order.get('status') or it.get('final_reason') or "|"
            rows.append({
                'intent_id': intent_id,
                'time': self._fmt_ts(it.get('created_ts')),
                'signal': signal_str,
                'gate': gate,
                'order': order_str,
                'execution': execution,
                'outcome': outcome,
            })

        # include decision-only (veto) rows without intent_id
        for dec in extra_decisions[:5]:
            sig = match_signal(dec.get('symbol'), dec.get('action'), dec.get('signal_id'))
            if sig:
                if sig.get('signal_id'):
                    used_signal_ids.add(sig.get('signal_id'))
                conf = sig.get('confidence')
                conf_str = f" ({conf})" if conf is not None else ""
                signal_str = f"{sig.get('strategy') or ''} {sig.get('action') or ''}{conf_str}".strip()
            else:
                signal_str = " ".join([x for x in [dec.get('action'), dec.get('symbol')] if x])
            gate = dec.get('decision') or 'VETO'
            if dec.get('reason'):
                gate = f"{gate} ({dec.get('reason')})"
            rows.append({
                'intent_id': dec.get('intent_id') or '|',
                'time': self._fmt_ts(dec.get('ts')),
                'signal': signal_str,
                'gate': gate,
                'order': '|',
                'execution': '|',
                'outcome': dec.get('decision') or 'VETO',
            })

        # If no intents yet, surface signals as pending rows so the UI isn't empty
        if signals:
            for sig in signals:
                sig_id = sig.get('signal_id')
                if sig_id and sig_id in used_signal_ids:
                    continue
                conf = sig.get('confidence')
                conf_str = f" ({conf})" if conf is not None else ""
                signal_str = f"{sig.get('strategy') or ''} {sig.get('action') or ''}{conf_str}".strip()
                rows.append({
                    'intent_id': sig_id or '|',
                    'time': self._fmt_ts(sig.get('ts')),
                    'signal': signal_str or '|',
                    'gate': 'PENDING',
                    'order': '|',
                    'execution': '|',
                    'outcome': '|',
                })
                if len(rows) >= limit:
                    break

        return rows

    def _get_intent_detail(self, intent_id: str) -> dict:
        """Return intent + linked decision/signal/orders/fills for drawer UI."""
        detail = {"intent_id": intent_id, "intent": {}, "orders": [], "fills": [], "decision": {}, "signal": {}}
        try:
            intents = self._db_query("SELECT * FROM intents WHERE intent_id=? LIMIT 1", (intent_id,))
            if intents:
                detail["intent"] = intents[0]
            orders = self._db_query("SELECT * FROM orders WHERE intent_id=? ORDER BY placed_ts DESC", (intent_id,))
            detail["orders"] = orders or []
            # fills by order_id or client_order_id
            order_ids = [o.get("order_id") or o.get("client_order_id") for o in (orders or []) if (o.get("order_id") or o.get("client_order_id"))]
            if order_ids:
                q = "SELECT * FROM fills WHERE order_id IN ({}) ORDER BY ts DESC".format(",".join(["?"] * len(order_ids)))
                detail["fills"] = self._db_query(q, tuple(order_ids))
            # decision + signal from raw_events
            rows = self._db_query(
                "SELECT ts, type, payload FROM raw_events WHERE type IN ('buzz.coordinator.decision','buzz.strategy.signal') ORDER BY ts DESC LIMIT ?",
                (200,)
            )
            decision = None
            signals = []
            for r in rows:
                payload = r.get("payload")
                try:
                    payload = json.loads(payload) if isinstance(payload, str) else (payload or {})
                except Exception:
                    payload = {}
                if r.get("type") == "buzz.coordinator.decision" and payload.get("intent_id") == intent_id and decision is None:
                    decision = payload
                if r.get("type") == "buzz.strategy.signal":
                    signals.append(payload)
            if decision:
                detail["decision"] = decision
                sid = decision.get("signal_id")
                sig = None
                if sid:
                    sig = next((s for s in signals if s.get("signal_id") == sid), None)
                if not sig:
                    sig = next((s for s in signals if s.get("symbol") == decision.get("symbol") and s.get("action") == decision.get("action")), None)
                if sig:
                    detail["signal"] = sig
            else:
                # fallback: match signal by intent symbol/action
                sym = detail.get("intent", {}).get("symbol")
                act = detail.get("intent", {}).get("action")
                sig = next((s for s in signals if s.get("symbol") == sym and s.get("action") == act), None)
                if sig:
                    detail["signal"] = sig
        except Exception:
            logging.exception("intent detail query failed")
        return detail

    def _get_unapproved_signals(self, limit: int = 20) -> list:
        """Return latest strategy signals for the Signals panel."""
        rows = self._db_query(
            "SELECT ts, type, source, payload FROM raw_events "
            "WHERE type IN ('buzz.strategy.signal','buzz.strategy.proposal') "
            "ORDER BY ts DESC LIMIT ?",
            (limit * 5,)
        )
        out = []
        for r in rows:
            payload = r.get('payload')
            try:
                payload = json.loads(payload) if isinstance(payload, str) else (payload or {})
            except Exception:
                payload = {}
            if r.get("type") == "buzz.strategy.proposal":
                out.append({
                    'time': self._fmt_ts(payload.get('ts') or r.get('ts')),
                    'strategy': payload.get('strategy') or payload.get('origin_strategy') or '',
                    'action': payload.get('action') or '',
                    'confidence': payload.get('signal_strength') or payload.get('edge'),
                    'notes': payload.get('notes') or payload.get('reason') or '',
                })
            else:
                out.append({
                    'time': self._fmt_ts(payload.get('ts') or r.get('ts')),
                    'strategy': payload.get('strategy') or payload.get('origin_strategy') or '',
                    'action': payload.get('action') or '',
                    'confidence': payload.get('confidence'),
                    'notes': payload.get('notes') or payload.get('reason') or '',
                })
        return out[:limit]

    def _get_intents_rows(self, limit: int = 30) -> list:
        intents = self._db_query(
            "SELECT intent_id, origin_strategy, symbol, action, state, created_ts "
            "FROM intents ORDER BY created_ts DESC LIMIT ?",
            (limit,)
        )
        rows = []
        for it in intents:
            rows.append({
                "intent_id": it.get("intent_id"),
                "origin_strategy": it.get("origin_strategy") or it.get("symbol"),
                "action": it.get("action"),
                "state": it.get("state"),
                "created_ts": self._fmt_ts(it.get("created_ts")),
            })
        if rows:
            return rows
        # Fallback: show recent strategy signals as pending intents
        sig_rows = self._db_query(
            "SELECT ts, payload FROM raw_events WHERE type='buzz.strategy.signal' ORDER BY ts DESC LIMIT ?",
            (limit,)
        )
        for r in sig_rows:
            payload = r.get("payload")
            try:
                payload = json.loads(payload) if isinstance(payload, str) else (payload or {})
            except Exception:
                payload = {}
            rows.append({
                "intent_id": payload.get("signal_id") or payload.get("id") or "|",
                "origin_strategy": payload.get("strategy") or payload.get("origin_strategy") or payload.get("symbol") or "",
                "action": payload.get("action") or "",
                "state": "SIGNAL",
                "created_ts": self._fmt_ts(payload.get("ts") or r.get("ts")),
            })
        return rows

    def _get_risk_payload(self) -> dict:
        state = {}
        ks = self.coordinator.agents.get("kill_switch") if self.coordinator else None
        if ks:
            try:
                state = ks.get_state() or {}
            except Exception:
                state = {}
        if not state:
            rows = self._db_query(
                "SELECT ts, state, reason, metrics_json FROM killswitch ORDER BY ts DESC LIMIT 1"
            )
            if rows:
                state = {"state": rows[0].get("state"), "reason": rows[0].get("reason"), "since": rows[0].get("ts")}
        metrics = {}
        snap = self._latest_analytics_payload() or {}
        if snap:
            daily_pnl = snap.get("daily_pnl_pct")
            if daily_pnl is None:
                daily_pnl = snap.get("equity_change_pct")
            drawdown = snap.get("drawdown_pct")
            if drawdown is None:
                drawdown = snap.get("max_drawdown")
            metrics.update({
                "daily_pnl_pct": daily_pnl,
                "drawdown_pct": drawdown,
                "rejected": snap.get("rejected"),
                "market_stale_events": snap.get("market_stale_events"),
                "wallet_stale_events": snap.get("wallet_stale_events"),
            })
        # Fallback to latest kill-check payload for reject/slippage visibility
        try:
            if not metrics.get("rejected") and not metrics.get("avg_slippage_pct"):
                rows = self._db_query(
                    "SELECT payload FROM raw_events WHERE type='buzz.kill.check' ORDER BY ts DESC LIMIT 1"
                )
                if rows:
                    payload = rows[0].get("payload")
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    if isinstance(payload, dict):
                        kmetrics = payload.get("metrics") or {}
                        if "rejected" not in metrics and "rejects_5m" in kmetrics:
                            metrics["rejected"] = kmetrics.get("rejects_5m")
                        if "avg_slippage_pct" not in metrics and "avg_slippage_pct" in kmetrics:
                            metrics["avg_slippage_pct"] = kmetrics.get("avg_slippage_pct")
        except Exception:
            pass
        # Normalize missing metrics to zero so the UI doesn't show blanks
        for key in ("daily_pnl_pct", "drawdown_pct", "rejected", "market_stale_events", "wallet_stale_events"):
            if metrics.get(key) is None:
                metrics[key] = 0
        policy = self._latest_security_policy() or {}
        if policy and (state.get("state") in (None, "", "OK")):
            # surface security policy pause as the reason to avoid confusion
            try:
                if policy.get("paused") and not state.get("reason"):
                    state["reason"] = "SECURITY_POLICY_PAUSED"
            except Exception:
                pass
        return {"state": state, "metrics": metrics, "policy": policy}

    def _get_performance_payload(self) -> dict:
        metrics = self._collect_metrics()
        trading = metrics.get("trading") or {}
        snap = self._latest_analytics_payload() or {}
        row = {
            "trades": snap.get("trades") or trading.get("total_trades"),
            "win_rate": (trading.get("win_rate") * 100) if isinstance(trading.get("win_rate"), (int, float)) else trading.get("win_rate"),
            "fees": snap.get("fees") or trading.get("fees") or "N/A",
            "avg_slippage": snap.get("avg_slippage_pct") or "N/A",
            "max_drawdown": trading.get("max_drawdown") or trading.get("drawdown_pct") or "N/A",
        }
        return {"row": row}

    def _get_alert_rows(self, limit: int = 20) -> list:
        rows = self._db_query(
            "SELECT ts, severity, event_type, details, recommended_action FROM security_audit ORDER BY ts DESC LIMIT ?",
            (limit,)
        )
        out = []
        for r in rows:
            out.append({
                "severity": r.get("severity") or "info",
                "source": r.get("event_type") or "SECURITY",
                "reason": r.get("details") or "",
                "action": r.get("recommended_action") or "",
            })
        return out

    def _get_audit_rows(self, limit: int = 20) -> list:
        rows = self._db_query(
            "SELECT ts, type, source, payload FROM raw_events ORDER BY ts DESC LIMIT ?",
            (limit,)
        )
        out = []
        for r in rows:
            detail = r.get("payload")
            try:
                if isinstance(detail, str) and len(detail) > 120:
                    detail = detail[:117] + "..."
            except Exception:
                pass
            out.append({
                "ts": self._fmt_ts(r.get("ts")),
                "type": r.get("type") or "",
                "detail": detail or "",
            })
        return out

    def _get_risk_timeline_rows(self, limit: int = 20) -> list:
        rows = self._db_query(
            "SELECT ts, type, source, payload FROM raw_events WHERE type LIKE 'buzz.kill.%' ORDER BY ts DESC LIMIT ?",
            (limit * 10,)
        )
        out = []
        for r in rows:
            typ = r.get("type") or ""
            payload = r.get("payload")
            try:
                payload = json.loads(payload) if isinstance(payload, str) else (payload or {})
            except Exception:
                payload = {}
            state = payload.get("risk_state") or payload.get("state") or ""
            reason = payload.get("reason")
            metrics = payload.get("metrics") or {}
            # Only show non-OK risk events (THROTTLE/HALT) or entries with an explicit reason
            if (str(state).upper() == "OK") and not reason:
                continue
            parts = []
            if state:
                parts.append(state)
            if reason:
                parts.append(f"reason={reason}")
            if "rejects_5m" in metrics:
                parts.append(f"rejects_5m={metrics.get('rejects_5m')}")
            if "avg_slippage_pct" in metrics:
                parts.append(f"avg_slippage_pct={metrics.get('avg_slippage_pct')}")
            if "market_stale_events" in metrics:
                parts.append(f"market_stale_events={metrics.get('market_stale_events')}")
            if "wallet_stale_events" in metrics:
                parts.append(f"wallet_stale_events={metrics.get('wallet_stale_events')}")
            detail = " | ".join([p for p in parts if p]) or (json.dumps(payload) if payload else typ)
            out.append({
                "ts": self._fmt_ts(r.get("ts")),
                "type": typ,
                "detail": detail,
            })
            if len(out) >= limit:
                break
        return out

    def _get_recent_buzz(self, limit: int = 200) -> list:
        """Return recent buzz messages, preferring raw_events for full history."""
        msgs = []
        rows = self._db_query(
            "SELECT ts, type, source, payload FROM raw_events ORDER BY ts DESC LIMIT ?",
            (limit,)
        )
        if rows:
            for r in rows:
                typ = r.get("type") or ""
                payload = r.get("payload")
                try:
                    payload = json.loads(payload) if isinstance(payload, str) else (payload or {})
                except Exception:
                    payload = {"raw": payload}
                buzz = {
                    "type": typ,
                    "source": r.get("source") or "UNKNOWN",
                    "ts": int(float(r.get("ts") or 0) * 1000),
                }
                msgs.append({
                    "buzz": buzz,
                    "payload": payload,
                    "summary": self._summarize_buzz(typ, payload),
                })
            return msgs
        # Fallback: last values from in-memory cache
        cache = getattr(self.coordinator, "data_cache", {}) or {}
        for k, v in cache.items():
            if isinstance(k, str) and k.startswith("buzz.") and isinstance(v, dict):
                typ = v.get("buzz", {}).get("type", k)
                payload = v.get("payload") or v
                v["summary"] = self._summarize_buzz(typ, payload)
                msgs.append(v)
        # Order by sequence if present, otherwise by timestamp
        def _order_key(m):
            try:
                b = m.get("buzz", {})
                if b.get("seq") is not None:
                    return int(b.get("seq"))
                return int(b.get("ts") or 0)
            except Exception:
                return 0
        return sorted(msgs, key=_order_key, reverse=True)[:limit]

    def _summarize_buzz(self, typ: str, payload: dict) -> str:
        """Return a short, human-friendly summary for a buzz event."""
        try:
            if typ == "buzz.kill.check":
                metrics = payload.get("metrics") or {}
                state = payload.get("risk_state") or payload.get("state") or "OK"
                reason = payload.get("reason")
                return f"{state}" + (f" ({reason})" if reason else "") + \
                    f" | rejects_5m={metrics.get('rejects_5m', 0)} | slippage={metrics.get('avg_slippage_pct', 0)}"
            if typ == "buzz.kill.trigger":
                return f"HALT ({payload.get('reason') or 'trigger'})"
            if typ == "buzz.wallet.balance":
                bals = payload.get("balances") or []
                if bals:
                    b = bals[0]
                    return f"{b.get('asset')}={b.get('free')}"
                return "wallet balance update"
            if typ in ("buzz.market.data", "buzz.market.candle"):
                return f"{payload.get('symbol') or ''} price={payload.get('price') or payload.get('c')}"
            if typ == "buzz.strategy.signal":
                return f"{payload.get('strategy')} {payload.get('action')} ({payload.get('confidence')})"
            if typ == "buzz.coordinator.decision":
                return f"{payload.get('decision') or payload.get('state')} ({payload.get('reason') or 'ok'})"
            if typ == "buzz.trade.execution":
                return f"{payload.get('status')} {payload.get('symbol')} {payload.get('filled_qty')} @ {payload.get('avg_price')}"
            if typ == "buzz.analytics.snapshot":
                return f"trades={payload.get('trades', 0)} rejected={payload.get('rejected', 0)} slip={payload.get('avg_slippage_pct', 0)}"
            msg = payload.get("message") if isinstance(payload, dict) else None
            if msg:
                return str(msg)
            if payload:
                return json.dumps(payload)[:120]
        except Exception:
            pass
        return typ

    def _price_series(self, limit: int = 100):
        md = self.coordinator.agents.get("market_data")
        if not md:
            return [], []
        try:
            times, closes = md.fetch_closes(limit)
            labels = [datetime.fromtimestamp(t / 1000).strftime("%H:%M") for t in times]
            return labels, closes
        except Exception:
            return [], []

    def _price_series_for(self, symbol: str, limit: int = 120):
        """Fetch OHLC close series for an arbitrary symbol without mutating the main market_data agent."""
        symbol = (symbol or "").strip()
        if not symbol:
            return [], []
        client = getattr(self.coordinator, "_client", None)
        interval = getattr(getattr(self.coordinator, "cfg", None), "interval", "1m")
        # Prefer ccxt-style client
        if client and hasattr(client, "fetch_ohlcv"):
            try:
                timeframe = interval
                ohlcv = client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
                times = [int(c[0]) for c in ohlcv]
                closes = [float(c[4]) for c in ohlcv]
                labels = [datetime.fromtimestamp(t / 1000).strftime("%H:%M") for t in times]
                return labels, closes
            except Exception:
                return [], []
        # Fallback for Binance REST client
        if client and hasattr(client, "get_klines"):
            try:
                binance_symbol = symbol.replace("/", "")
                klines = client.get_klines(symbol=binance_symbol, interval=interval, limit=limit)
                times = [int(k[6]) for k in klines]
                closes = [float(k[4]) for k in klines]
                labels = [datetime.fromtimestamp(t / 1000).strftime("%H:%M") for t in times]
                return labels, closes
            except Exception:
                return [], []
        return [], []

    def _collect_metrics(self):
        data = {"performance": {}, "trading": {}, "agents": list(self.coordinator.agents.keys())}
        perf = self.coordinator.agents.get("performance")
        if perf:
            try:
                data["performance"] = perf.get_current_metrics()
            except Exception:
                data["performance"] = {}
        log_agent = self.coordinator.agents.get("logging")
        if log_agent:
            try:
                data["trading"] = log_agent.get_metrics()
            except Exception:
                data["trading"] = {}
        if not data["trading"]:
            data["trading"] = {"total_trades": 0, "wins": 0, "losses": 0, "profit_loss": 0.0, "win_rate": 0.0}
        try:
            data["latest_price"] = self.coordinator.get_shared_data("latest_price")
        except Exception:
            data["latest_price"] = None
        return data

    def _get_logs(self, limit: int = 40):
        logs = []
        if self.coordinator.agents.get("data_store"):
            try:
                raw = self.coordinator.agents["data_store"].get_logs(limit=limit)
                for row in raw:
                    if isinstance(row, dict):
                        logs.append(dict(row))
                    elif hasattr(row, "keys"):
                        logs.append({k: row[k] for k in row.keys()})
                    elif isinstance(row, (list, tuple)) and len(row) >= 4:
                        logs.append({"timestamp": row[0], "level": row[1], "message": row[2], "agent": row[3]})
            except Exception:
                logs = []
        if not logs:
            try:
                from pathlib import Path
                path = Path("logs/activity.log")
                if path.exists():
                    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()[-limit:]
                    logs = [{"timestamp": "", "level": "INFO", "message": line, "agent": "file"} for line in lines]
            except Exception:
                pass
        return logs

    def _get_recent_trades(self, limit: int = 20):
        trades = []
        try:
            if self.coordinator.agents.get("logging"):
                trades = self.coordinator.agents["logging"].get_recent_trades(limit)
            if (not trades) and self.coordinator.agents.get("data_store"):
                trades = self.coordinator.agents["data_store"].get_recent_trades(limit)
        except Exception:
            trades = []

        normalized = []
        for t in trades or []:
            if isinstance(t, dict):
                normalized.append(t)
            elif isinstance(t, (list, tuple)) and len(t) >= 7:
                normalized.append({
                    "id": t[0], "timestamp": t[1], "symbol": t[2], "side": t[3],
                    "quantity": t[4], "price": t[5], "status": t[6], "venue": "kraken"
                })
        if normalized:
            return normalized

        try:
            from pathlib import Path
            import csv
            path = Path("logs") / "trades.csv"
            if path.exists():
                with path.open("r", encoding="utf-8", errors="ignore") as f:
                    rows = list(csv.DictReader(f))[-limit:]
                out = []
                for r in reversed(rows):
                    qty = float(r.get("quantity") or r.get("qty") or 0)
                    price = float(r.get("price") or 0)
                    out.append({
                        "timestamp": r.get("timestamp") or r.get("ts") or "",
                        "symbol": r.get("symbol") or r.get("pair") or "",
                        "side": r.get("side") or "",
                        "quantity": qty,
                        "price": price,
                        "status": r.get("status") or "tape",
                        "venue": r.get("venue") or "kraken",
                    })
                return out
        except Exception:
            pass
        return []

    def _get_market_tape(self, limit: int = 50):
        trades = self._get_recent_trades(limit=200) or []

        def notional(t):
            try:
                return float(t.get("notional") or (float(t.get("quantity") or 0) * float(t.get("price") or 0)))
            except Exception:
                return 0.0

        candidates = []
        for t in trades:
            try:
                side = (t.get("side") or "").upper()
                n = notional(t)
                if side == "SELL" and n >= 2000:
                    t["notional"] = n
                    candidates.append(t)
            except Exception:
                continue
        return sorted(candidates, key=lambda x: float(x.get("notional") or 0), reverse=True)[:limit]

    def _get_wallet_snapshot(self):
        """Return a lightweight wallet balance snapshot for the UI."""
        wallet = self.coordinator.agents.get("wallet")
        if not wallet:
            return {}
        # Prefer wallet's published snapshot if available
        try:
            if hasattr(wallet, "get_snapshot"):
                snap = wallet.get_snapshot() or {}
                balances = snap.get("balances") or []
                if balances:
                    out = {}
                    for b in balances:
                        try:
                            asset = b.get("asset") or ""
                            free = b.get("free")
                            if asset:
                                out[asset] = f"{float(free or 0):.4f}"
                        except Exception:
                            continue
                    if out:
                        return out
        except Exception:
            pass
        snapshot = {}
        try:
            snapshot["ETH"] = f"{wallet.eth_balance():.4f}"
            tok = wallet.erc20_balance()
            if tok is not None:
                symbol = getattr(wallet, "token_symbol", "TOKEN") or "TOKEN"
                snapshot[symbol] = f"{tok:.4f}"
        except Exception:
            return {}
        return snapshot

    def _load_config(self):
        try:
            with open(self.config_path, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def _load_api_keys(self):
        try:
            with open(self.api_keys_path, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _render_config(self):
        cfg = self._load_config()
        keys = self._load_api_keys()

        def val(mapping, key, default=""):
            return mapping.get(key, default) if mapping else default

        return f"""
        <!DOCTYPE html>
        <html><head><title>Configuration</title>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 960px; margin: 20px auto; background:#071026; color:#ffd24a; }}
            .card {{ background:#0d1730; border:1px solid rgba(255,210,74,0.08); border-radius:10px; padding:18px; margin-bottom:16px; }}
            label {{ display:block; margin:8px 0 4px; font-weight:600; color:#d9c786; }}
            input {{ width:100%; padding:8px; border-radius:6px; border:1px solid #2a3350; background:#0f1427; color:#ffd24a; }}
            button {{ padding:10px 16px; background:#ffd24a; color:#071026; border:none; border-radius:8px; font-weight:700; cursor:pointer; }}
            a {{ color:#ffd24a; }}
        </style>
        </head><body>
            <h1>Configuration</h1>
            <form method=\"post\" action=\"/config\">
                <div class=\"card\">
                    <h3>Exchange & Strategy</h3>
                    <label>Exchange</label><input name=\"exchange\" value=\"{val(cfg,'exchange','kraken')}\">
                    <label>Symbol</label><input name=\"symbol\" value=\"{val(cfg,'symbol','ETH/USDT')}\">
                    <label>Interval</label><input name=\"interval\" value=\"{val(cfg,'interval','1m')}\">
                    <label>Market Stale Sec (Kill Switch)</label><input name=\"market_stale_sec\" type=\"number\" step=\"1\" min=\"5\" value=\"{val(cfg,'market_stale_sec','300')}\">
                    <label>Wallet Stale Sec (Kill Switch)</label><input name=\"wallet_stale_sec\" type=\"number\" step=\"1\" min=\"5\" value=\"{val(cfg,'wallet_stale_sec','300')}\">
                    <label>Slippage Threshold (Kill Switch)</label><input name=\"slippage_threshold\" type=\"number\" step=\"0.0001\" min=\"0\" value=\"{val(cfg,'slippage_threshold','0.01')}\">
                    <label>Throttle Clear Sec (Kill Switch)</label><input name=\"throttle_clear_sec\" type=\"number\" step=\"1\" min=\"10\" value=\"{val(cfg,'throttle_clear_sec','300')}\">
                </div>
                <div class=\"card\">
                    <h3>API Keys</h3>
                    <label>Kraken API Key</label><input name=\"kraken_api_key\" value=\"{val(keys,'kraken_api_key','')}\" type=\"password\">
                    <label>Kraken API Secret</label><input name=\"kraken_api_secret\" value=\"{val(keys,'kraken_api_secret','')}\" type=\"password\">
                    <label>Etherscan API Key</label><input name=\"etherscan_api_key\" value=\"{val(keys,'etherscan_api_key','')}\" type=\"password\">
                    <label>Web3 RPC URL</label><input name=\"web3_rpc_url\" value=\"{val(keys,'web3_rpc_url','')}\" type=\"url\">
                    <label>Watch Address</label><input name=\"watch_address\" value=\"{val(keys,'watch_address','')}\" placeholder=\"0x...\">
                    <label>ERC20 Token Address (optional)</label><input name=\"erc20_token_address\" value=\"{val(keys,'erc20_token_address','')}\" placeholder=\"0x...\">
                </div>
                <button type=\"submit\">Save & Apply</button>
                <p><a href=\"/\">Back to dashboard</a></p>
            </form>
        </body></html>
        """

    def _save_config(self):
        try:
            data = request.form.to_dict()
            cfg_updates = {
                "exchange": data.get("exchange", "kraken"),
                "symbol": data.get("symbol", "ETH/USDT"),
                "interval": data.get("interval", "1m"),
                "market_stale_sec": float(data.get("market_stale_sec", 300)),
                "wallet_stale_sec": float(data.get("wallet_stale_sec", 300)),
                "slippage_threshold": float(data.get("slippage_threshold", 0.01)),
                "throttle_clear_sec": int(float(data.get("throttle_clear_sec", 300))),
            }
            api_updates = {
                "kraken_api_key": data.get("kraken_api_key", ""),
                "kraken_api_secret": data.get("kraken_api_secret", ""),
                "etherscan_api_key": data.get("etherscan_api_key", ""),
                "web3_rpc_url": data.get("web3_rpc_url", ""),
                "watch_address": data.get("watch_address", ""),
                "erc20_token_address": data.get("erc20_token_address", ""),
            }
            cfg = self._load_config()
            keys = self._load_api_keys()
            cfg.update(cfg_updates)
            keys.update(api_updates)
            with open(self.config_path, "w") as f:
                yaml.safe_dump(cfg, f)
            with open(self.api_keys_path, "w") as f:
                json.dump(keys, f, indent=2)
            try:
                from main import load_config
                new_cfg = load_config()
                self.coordinator.reload_config(new_cfg)
            except Exception as e:
                logging.warning(f"Reload after save failed: {e}")
            return "<html><body><h3>Saved.</h3><a href='/' >Back</a></body></html>"
        except Exception as e:
            logging.error(f"Save config error: {e}")
            return ("Error saving config", 500)

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        self.thread = threading.Thread(target=self._run_server, daemon=True)
        self.thread.start()
        logging.info(f"UI Agent started on http://{self.host}:{self.port}")

    def _run_server(self):
        self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)

    def stop(self):
        if self.thread:
            logging.info("UI Agent stopping...")
            self.thread = None
