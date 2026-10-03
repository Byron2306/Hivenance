import sqlite3
import json
import logging
import time
import os
import threading
import shutil
from typing import Any, Dict, Optional
from datetime import datetime


class DataStoreAgent:
    """
    Data Store Agent: SQLite-backed authoritative store for intents, orders, fills,
    balances, kill-switch transitions, and config versions. It accepts buzz events
    via `handle_event` and responds to `buzz.store.query` by publishing
    `buzz.store.result` via the coordinator when available.
    """

    def __init__(self, db_path: str = "swarm_data.db", coordinator: Optional[Any] = None):
        self.db_path = db_path
        self.conn = None
        self.coordinator = coordinator
        self._lock = threading.RLock()
        self._recovering = False
        self._connect()
        self._create_tables()

    def _connect(self, check_integrity: bool = True):
        """Establish SQLite connection."""
        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            try:
                self.conn.execute("PRAGMA journal_mode=WAL")
                self.conn.execute("PRAGMA synchronous=NORMAL")
            except Exception:
                pass
            if check_integrity and not self._check_integrity():
                self._recover_db("quick_check failed")
                return
            logging.info(f"Data Store Agent connected to {self.db_path}")
        except Exception as e:
            logging.error(f"Failed to connect to database: {e}")
            self.conn = None

    def _check_integrity(self) -> bool:
        if not self.conn:
            return False
        try:
            cur = self.conn.cursor()
            cur.execute("PRAGMA quick_check")
            row = cur.fetchone()
            return bool(row and row[0] == "ok")
        except Exception:
            return False

    def _create_tables(self):
        """Create necessary tables."""
        if not self.conn:
            return
        try:
            c = self.conn.cursor()
            # raw events (optional)
            c.execute("""
            CREATE TABLE IF NOT EXISTS raw_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                type TEXT,
                source TEXT,
                payload TEXT
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS event_envelopes (
                event_id TEXT PRIMARY KEY,
                ts REAL,
                type TEXT,
                source TEXT,
                severity TEXT,
                correlation_id TEXT,
                seq INTEGER,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_event_envelopes_type_ts ON event_envelopes(type, ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_event_envelopes_correlation ON event_envelopes(correlation_id)")
            # intents
            c.execute("""
            CREATE TABLE IF NOT EXISTS intents (
                intent_id TEXT PRIMARY KEY,
                symbol TEXT,
                action TEXT,
                origin_strategy TEXT,
                created_ts REAL,
                state TEXT,
                final_outcome TEXT,
                final_reason TEXT,
                position_size_pct REAL,
                qty REAL,
                order_type TEXT
            )
            """)
            # orders
            c.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                client_order_id TEXT PRIMARY KEY,
                intent_id TEXT,
                venue TEXT,
                symbol TEXT,
                side TEXT,
                order_type TEXT,
                order_id TEXT,
                status TEXT,
                placed_ts REAL,
                final_ts REAL
            )
            """)
            # fills
            c.execute("""
            CREATE TABLE IF NOT EXISTS fills (
                fill_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT,
                client_order_id TEXT,
                filled_qty REAL,
                avg_price REAL,
                fee REAL,
                slippage_pct REAL,
                ts REAL
            )
            """)
            # balances
            c.execute("""
            CREATE TABLE IF NOT EXISTS balances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                venue TEXT,
                eth_free REAL,
                eth_locked REAL,
                usdt_free REAL,
                usdt_locked REAL,
                equity_usd_est REAL
            )
            """)
            # killswitch transitions
            c.execute("""
            CREATE TABLE IF NOT EXISTS killswitch (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                state TEXT,
                reason TEXT,
                metrics_json TEXT
            )
            """)
            # swarmguard decisions
            c.execute("""
            CREATE TABLE IF NOT EXISTS swarmguard (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                decision TEXT,
                reason TEXT,
                position_size REAL,
                strategy TEXT,
                symbol TEXT,
                weight REAL,
                consensus_mult REAL
            )
            """)
            # config versions
            c.execute("""
            CREATE TABLE IF NOT EXISTS config_versions (
                version_id TEXT PRIMARY KEY,
                ts REAL,
                config_json TEXT,
                changed_by TEXT
            )
            """)
            # security audit
            c.execute("""
            CREATE TABLE IF NOT EXISTS security_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                severity TEXT,
                event_type TEXT,
                details TEXT,
                recommended_action TEXT
            )
            """)
            # trades table (used by store_trade and UI)
            c.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                symbol TEXT,
                side TEXT,
                quantity REAL,
                price REAL,
                status TEXT,
                intent_id TEXT,
                order_id TEXT,
                venue TEXT
            )
            """)
            # market data snapshots
            c.execute("""
            CREATE TABLE IF NOT EXISTS market_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                symbol TEXT,
                price REAL,
                volume REAL,
                source TEXT
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS market_bee_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                symbol TEXT,
                score REAL,
                allowed INTEGER,
                reason TEXT,
                price_usd REAL,
                liquidity_usd REAL,
                volume_24h_usd REAL,
                h1_change_pct REAL,
                h24_change_pct REAL,
                roundtrip_ratio REAL,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_market_bee_symbol_ts ON market_bee_snapshots(symbol, ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS orderbook_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                symbol TEXT,
                venue TEXT,
                bid REAL,
                ask REAL,
                spread_pct REAL,
                mid_price REAL,
                top_of_book_depth_usd REAL,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_orderbook_symbol_ts ON orderbook_snapshots(symbol, ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                symbol TEXT,
                side TEXT,
                qty REAL,
                price REAL,
                notional_usd REAL,
                reason TEXT,
                net_margin_pct REAL,
                status TEXT
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS position_memory (
                symbol TEXT PRIMARY KEY,
                qty REAL,
                entry_price REAL,
                highest_price REAL,
                opened_ts REAL,
                updated_ts REAL,
                status TEXT,
                payload TEXT
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS paper_positions (
                symbol TEXT PRIMARY KEY,
                qty REAL,
                entry_price REAL,
                highest_price REAL,
                opened_ts REAL,
                updated_ts REAL,
                status TEXT,
                payload TEXT
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS executor_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                executor TEXT,
                symbol TEXT,
                side TEXT,
                status TEXT,
                qty REAL,
                price REAL,
                notional_usd REAL,
                net_margin_pct REAL,
                route_loss_pct REAL,
                reason TEXT,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_executor_events_symbol_ts ON executor_events(symbol, ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS hummingbot_executor_lifecycle (
                executor_id TEXT PRIMARY KEY,
                executor_type TEXT,
                symbol TEXT,
                side TEXT,
                state TEXT,
                attempts INTEGER,
                created_ts REAL,
                updated_ts REAL,
                stopped_ts REAL,
                reason TEXT,
                config TEXT,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_hb_lifecycle_state_ts ON hummingbot_executor_lifecycle(state, updated_ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS replay_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                symbol TEXT,
                days REAL,
                trades INTEGER,
                wins INTEGER,
                losses INTEGER,
                net_margin_pct REAL,
                max_drawdown_pct REAL,
                clean_exits INTEGER,
                failed_exits INTEGER,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_replay_results_symbol_ts ON replay_results(symbol, ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS public_bot_backtests (
                run_id TEXT PRIMARY KEY,
                engine TEXT,
                symbol TEXT,
                status TEXT,
                export_path TEXT,
                metrics TEXT,
                created_ts REAL,
                updated_ts REAL,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_public_bot_backtests_engine_ts ON public_bot_backtests(engine, updated_ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS evidence_records (
                evidence_id TEXT PRIMARY KEY,
                source TEXT,
                engine TEXT,
                run_id TEXT,
                symbol TEXT,
                strategy TEXT,
                verdict TEXT,
                promotion_stage TEXT,
                trades INTEGER,
                win_rate REAL,
                net_profit_pct REAL,
                max_drawdown_pct REAL,
                created_ts REAL,
                updated_ts REAL,
                gates TEXT,
                metrics TEXT,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_evidence_symbol_ts ON evidence_records(symbol, updated_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_evidence_verdict_ts ON evidence_records(verdict, updated_ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS ml_model_candidates (
                candidate_id TEXT PRIMARY KEY,
                family TEXT,
                symbol TEXT,
                objective TEXT,
                status TEXT,
                verdict TEXT,
                created_ts REAL,
                updated_ts REAL,
                model_card_path TEXT,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_ml_candidates_family_ts ON ml_model_candidates(family, updated_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_ml_candidates_symbol_ts ON ml_model_candidates(symbol, updated_ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS execution_parity_diagnostics (
                parity_id TEXT PRIMARY KEY,
                source TEXT,
                symbol TEXT,
                run_id TEXT,
                evidence_id TEXT,
                verdict TEXT,
                created_ts REAL,
                updated_ts REAL,
                metrics TEXT,
                gates TEXT,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_execution_parity_symbol_ts ON execution_parity_diagnostics(symbol, updated_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_execution_parity_verdict_ts ON execution_parity_diagnostics(verdict, updated_ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS signal_marketplace_rounds (
                round_id TEXT PRIMARY KEY,
                source TEXT,
                symbol TEXT,
                status TEXT,
                verdict TEXT,
                submitted INTEGER,
                eligible INTEGER,
                total_simulated_reward REAL,
                created_ts REAL,
                updated_ts REAL,
                gates TEXT,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_signal_marketplace_symbol_ts ON signal_marketplace_rounds(symbol, updated_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_signal_marketplace_verdict_ts ON signal_marketplace_rounds(verdict, updated_ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS worker_performance (
                worker TEXT PRIMARY KEY,
                total INTEGER,
                wins INTEGER,
                losses INTEGER,
                recent TEXT,
                updated_ts REAL,
                payload TEXT
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS pair_protections (
                symbol TEXT PRIMARY KEY,
                state TEXT,
                reason TEXT,
                cooldown_until REAL,
                daily_loss_pct REAL,
                failed_quotes INTEGER,
                route_loss_spike_pct REAL,
                low_profit_until REAL,
                updated_ts REAL,
                payload TEXT
            )
            """)
            c.execute("""
            CREATE TABLE IF NOT EXISTS promotion_records (
                symbol TEXT PRIMARY KEY,
                stage TEXT,
                eligible INTEGER,
                reason TEXT,
                paper_trades INTEGER,
                win_rate REAL,
                net_margin_sum REAL,
                max_drawdown_pct REAL,
                clean_exits INTEGER,
                failed_exits INTEGER,
                updated_ts REAL,
                payload TEXT
            )
            """)
            # simple logs table for UI/activity
            c.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                level TEXT,
                message TEXT,
                agent TEXT
            )
            """)
            # wallet balances table
            c.execute("""
            CREATE TABLE IF NOT EXISTS wallet_balances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                address TEXT,
                asset TEXT,
                balance REAL
            )
            """)
            self.conn.commit()
            logging.info("Data Store tables created/verified")
        except sqlite3.DatabaseError as e:
            if self._is_corrupt_error(e):
                logging.error("Error creating data store tables due to corruption; triggering recovery")
                self._recover_db(str(e))
            else:
                logging.exception("Error creating data store tables")
        except Exception:
            logging.exception("Error creating data store tables")

    def _is_corrupt_error(self, err: Exception) -> bool:
        msg = str(err).lower()
        return ("malformed" in msg) or ("disk image" in msg) or ("file is not a database" in msg)

    def _recover_db(self, reason: str = "database corruption"):
        """Recover from a malformed SQLite DB by backing it up and recreating."""
        if self._recovering:
            return
        self._recovering = True
        try:
            logging.error(f"Data Store DB recovery triggered: {reason}")
            try:
                if self.conn:
                    self.conn.close()
            except Exception:
                pass
            ts = int(time.time())
            base = self.db_path
            wal = f"{base}-wal"
            shm = f"{base}-shm"
            # best-effort backups for base + WAL/SHM
            for path in (wal, shm, base):
                try:
                    if os.path.exists(path):
                        backup = f"{path}.corrupt.{ts}"
                        try:
                            os.replace(path, backup)
                            logging.error(f"Backed up corrupt file to {backup}")
                        except Exception:
                            try:
                                shutil.copy2(path, backup)
                                os.remove(path)
                                logging.error(f"Copied corrupt file to {backup} and removed original")
                            except Exception:
                                pass
                except Exception:
                    pass
            self._connect(check_integrity=False)
            self._create_tables()
        except Exception:
            logging.exception("Failed to recover data store DB")
        finally:
            self._recovering = False

    def store_trade(self, trade_data: Dict[str, Any]):
        """Store a trade record."""
        if not self.conn:
            return
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("""
                    INSERT INTO trades (timestamp, symbol, side, quantity, price, status)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    trade_data.get('timestamp', datetime.now().isoformat()),
                    trade_data.get('symbol'),
                    trade_data.get('side'),
                    trade_data.get('quantity'),
                    trade_data.get('price'),
                    trade_data.get('status', 'pending')
                ))
                self.conn.commit()
                logging.debug(f"Stored trade: {trade_data}")
        except sqlite3.DatabaseError as e:
            if self._is_corrupt_error(e):
                self._recover_db(str(e))
            else:
                logging.error(f"Error storing trade: {e}")
        except Exception as e:
            logging.error(f"Error storing trade: {e}")

    # ------------------ event ingestion / projection ------------------
    def handle_event(self, evt: Dict[str, Any]):
        """Handle incoming buzz events for durable storage. Idempotent where applicable."""
        try:
            if not self.conn:
                return
            buzz = evt.get('buzz', {})
            typ = buzz.get('type')
            payload = evt.get('payload') or {}
            ts = int(buzz.get('ts', int(time.time() * 1000))) / 1000.0
            publish_result = None
            with self._lock:
                c = self.conn.cursor()
                # record raw event
                try:
                    c.execute('INSERT INTO raw_events (ts, type, source, payload) VALUES (?,?,?,?)', (ts, typ, buzz.get('source'), json.dumps(payload)))
                    if typ and buzz.get('id'):
                        c.execute(
                            """
                            INSERT OR IGNORE INTO event_envelopes
                            (event_id, ts, type, source, severity, correlation_id, seq, payload)
                            VALUES (?,?,?,?,?,?,?,?)
                            """,
                            (
                                buzz.get('id'),
                                ts,
                                typ,
                                buzz.get('source'),
                                buzz.get('severity'),
                                buzz.get('correlation_id'),
                                buzz.get('seq'),
                                json.dumps(payload),
                            )
                        )
                    # Mirror a lightweight activity log entry for UI convenience so the dashboard can show buzzes
                    try:
                        msg = payload.get('message') if isinstance(payload, dict) and 'message' in payload else (json.dumps(payload) if payload else typ)
                        c.execute('INSERT INTO logs (timestamp, level, message, agent) VALUES (?,?,?,?)', (ts, 'INFO', msg, buzz.get('source') or 'DATA_STORE'))
                    except Exception:
                        pass
                except Exception:
                    pass

                if typ in ('buzz.intent.state', 'buzz.coordinator.decision'):
                    intent_id = payload.get('intent_id') or payload.get('id')
                    if intent_id:
                        # upsert intent
                        c.execute('SELECT intent_id FROM intents WHERE intent_id=?', (intent_id,))
                        exists = c.fetchone()
                        if exists:
                            c.execute('UPDATE intents SET state=?, final_outcome=?, final_reason=?, qty=?, action=? WHERE intent_id=?', (payload.get('state') or payload.get('status'), payload.get('final_outcome'), payload.get('reason'), payload.get('qty'), payload.get('action'), intent_id))
                        else:
                            c.execute('INSERT INTO intents (intent_id, symbol, action, origin_strategy, created_ts, state, final_outcome, final_reason, position_size_pct, qty, order_type) VALUES (?,?,?,?,?,?,?,?,?,?,?)', (
                                intent_id, payload.get('symbol'), payload.get('action') or payload.get('type'), payload.get('strategy'), ts, payload.get('state') or payload.get('status'), payload.get('final_outcome'), payload.get('reason'), payload.get('position_size_pct'), payload.get('qty'), payload.get('order_type')
                            ))

                elif typ in ('buzz.trade.request', 'buzz.trade.order'):
                    # create or update order record
                    client_order_id = payload.get('client_order_id') or payload.get('clientId')
                    if client_order_id:
                        c.execute('SELECT client_order_id FROM orders WHERE client_order_id=?', (client_order_id,))
                        if c.fetchone():
                            c.execute('UPDATE orders SET status=?, order_id=?, placed_ts=? WHERE client_order_id=?', (payload.get('status') or 'REQUESTED', payload.get('order_id'), ts, client_order_id))
                        else:
                            c.execute('INSERT INTO orders (client_order_id, intent_id, venue, symbol, side, order_type, order_id, status, placed_ts, final_ts) VALUES (?,?,?,?,?,?,?,?,?,?)', (
                                client_order_id, payload.get('intent_id'), payload.get('venue'), payload.get('symbol'), payload.get('side'), payload.get('order_type'), payload.get('order_id'), payload.get('status') or 'REQUESTED', ts, None
                            ))

                elif typ in ('buzz.trade.execution',):
                    # update order and insert fills
                    client_order_id = payload.get('client_order_id')
                    order_id = payload.get('order_id')
                    status = payload.get('status')
                    filled = float(payload.get('filled_qty') or 0)
                    avg_price = payload.get('avg_price')
                    fees = payload.get('fees') or 0.0
                    slippage = payload.get('slippage_pct') or 0.0
                    # upsert order
                    if client_order_id:
                        c.execute('SELECT client_order_id FROM orders WHERE client_order_id=?', (client_order_id,))
                        if c.fetchone():
                            c.execute(
                                """
                                UPDATE orders
                                SET status=?,
                                    order_id=COALESCE(?, order_id),
                                    venue=COALESCE(?, venue),
                                    symbol=COALESCE(?, symbol),
                                    side=COALESCE(?, side),
                                    order_type=COALESCE(?, order_type),
                                    final_ts=?
                                WHERE client_order_id=?
                                """,
                                (
                                    status,
                                    order_id,
                                    payload.get('venue'),
                                    payload.get('symbol'),
                                    payload.get('side'),
                                    payload.get('order_type'),
                                    ts,
                                    client_order_id,
                                ),
                            )
                        else:
                            c.execute('INSERT OR IGNORE INTO orders (client_order_id, intent_id, venue, symbol, side, order_type, order_id, status, placed_ts, final_ts) VALUES (?,?,?,?,?,?,?,?,?,?)', (
                                client_order_id, payload.get('intent_id'), payload.get('venue'), payload.get('symbol'), payload.get('side'), payload.get('order_type'), order_id, status, payload.get('placed_ts') or ts, ts
                            ))
                    # record fill
                    if filled > 0:
                        try:
                            c.execute('INSERT INTO fills (order_id, client_order_id, filled_qty, avg_price, fee, slippage_pct, ts) VALUES (?,?,?,?,?,?,?)', (order_id, client_order_id, filled, avg_price, fees, slippage, ts))
                        except Exception:
                            logging.exception('Failed to insert fill')

                elif typ in ('buzz.wallet.balance',):
                    balances = payload.get('balances') or []
                    equity = payload.get('equity_usd_est') or payload.get('equity_est') or 0.0
                    venue = payload.get('venue') or 'wallet'
                    eth_free = eth_locked = usdt_free = usdt_locked = 0.0
                    for b in balances:
                        a = (b.get('asset') or '').upper()
                        if a == 'ETH':
                            eth_free = float(b.get('free') or 0)
                            eth_locked = float(b.get('locked') or 0)
                        if a in ('USDT', 'USDC'):
                            usdt_free = float(b.get('free') or 0)
                            usdt_locked = float(b.get('locked') or 0)
                    c.execute('INSERT INTO balances (ts, venue, eth_free, eth_locked, usdt_free, usdt_locked, equity_usd_est) VALUES (?,?,?,?,?,?,?)', (ts, venue, eth_free, eth_locked, usdt_free, usdt_locked, equity))

                elif typ in ('buzz.kill.check', 'buzz.kill.trigger'):
                    payload_json = json.dumps(payload)
                    state = payload.get('risk_state') or payload.get('state') or payload.get('risk')
                    c.execute('INSERT INTO killswitch (ts, state, reason, metrics_json) VALUES (?,?,?,?)', (ts, state, payload.get('reason'), payload_json))

                elif typ == 'buzz.swarmguard.decision':
                    try:
                        c.execute(
                            'INSERT INTO swarmguard (ts, decision, reason, position_size, strategy, symbol, weight, consensus_mult) VALUES (?,?,?,?,?,?,?,?)',
                            (
                                ts,
                                payload.get('decision'),
                                payload.get('reason'),
                                payload.get('position_size'),
                                payload.get('strategy'),
                                payload.get('symbol'),
                                payload.get('weight'),
                                payload.get('consensus_mult'),
                            )
                        )
                    except Exception:
                        logging.exception('Failed to insert swarmguard row')

                elif typ == 'buzz.market.bee':
                    try:
                        rows = payload.get('all') or payload.get('top') or []
                        for row in rows:
                            q = row.get('quality') or {}
                            h = row.get('horizons') or {}
                            hour = h.get('hour') or {}
                            day = h.get('day') or {}
                            pool = row.get('pool') or {}
                            c.execute(
                                """
                                INSERT INTO market_bee_snapshots
                                (ts, symbol, score, allowed, reason, price_usd, liquidity_usd, volume_24h_usd,
                                 h1_change_pct, h24_change_pct, roundtrip_ratio, payload)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                                """,
                                (
                                    ts,
                                    row.get('symbol'),
                                    row.get('score'),
                                    1 if row.get('allowed') else 0,
                                    row.get('reason'),
                                    pool.get('price_usd'),
                                    q.get('liquidity_usd'),
                                    q.get('volume_24h_usd'),
                                    hour.get('price_change_pct'),
                                    day.get('price_change_pct'),
                                    q.get('roundtrip_ratio'),
                                    json.dumps(row),
                                )
                            )
                    except Exception:
                        logging.exception('Failed to insert market bee snapshots')

                elif typ == 'buzz.market.orderbook':
                    try:
                        c.execute(
                            """
                            INSERT INTO orderbook_snapshots
                            (ts, symbol, venue, bid, ask, spread_pct, mid_price, top_of_book_depth_usd, payload)
                            VALUES (?,?,?,?,?,?,?,?,?)
                            """,
                            (
                                ts,
                                payload.get('symbol'),
                                payload.get('venue'),
                                payload.get('bid'),
                                payload.get('ask'),
                                payload.get('spread_pct'),
                                payload.get('mid_price'),
                                payload.get('top_of_book_depth_usd'),
                                json.dumps(payload),
                            )
                        )
                    except Exception:
                        logging.exception('Failed to insert orderbook snapshot')

                elif typ == 'buzz.store.query':
                    # perform query and publish result over coordinator
                    q = payload or {}
                    query_id = q.get('query_id')
                    name = q.get('name')
                    params = q.get('params') or {}
                    rows = []
                    ok = True
                    try:
                        rows = self._execute_named_query(name, params)
                    except Exception as e:
                        ok = False
                        rows = {'error': str(e)}
                    publish_result = {'buzz': {'type': 'buzz.store.result', 'source': 'DATA_STORE', 'ts': int(time.time()*1000)}, 'payload': {'query_id': query_id, 'ok': ok, 'rows': rows}}

                # commit at end
                try:
                    self.conn.commit()
                except Exception:
                    pass
        except sqlite3.DatabaseError as e:
            if self._is_corrupt_error(e):
                self._recover_db(str(e))
            else:
                logging.exception('DataStoreAgent.handle_event failed')
        except Exception:
            logging.exception('DataStoreAgent.handle_event failed')
        # publish store.query result outside lock
        try:
            if publish_result and self.coordinator:
                self.coordinator.share_data('buzz.store.result', publish_result)
        except Exception:
            logging.exception('Failed to publish store.query result')

    def _execute_named_query(self, name: str, params: Dict[str, Any]):
        if not self.conn:
            return []
        with self._lock:
            c = self.conn.cursor()
        if name == 'get_recent_intents':
            limit = int(params.get('limit', 50))
            c.execute('SELECT intent_id, symbol, action, state, final_outcome, final_reason, qty FROM intents ORDER BY created_ts DESC LIMIT ?', (limit,))
            rows = [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]
            return rows
        if name == 'get_open_intents':
            c.execute("SELECT intent_id, symbol, action, state, qty FROM intents WHERE state NOT IN ('DONE','CANCELED') ORDER BY created_ts ASC")
            rows = [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]
            return rows
        if name == 'get_recent_fills':
            limit = int(params.get('limit', 100))
            c.execute('SELECT * FROM fills ORDER BY ts DESC LIMIT ?', (limit,))
            rows = [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]
            return rows
        # fallback: simple raw SQL if provided (dangerous but useful for debugging)
        if name == 'raw_sql' and params.get('sql'):
            sql = params.get('sql')
            c.execute(sql)
            rows = [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]
            return rows
        raise ValueError('Unknown query name')

    def get_trades(self, symbol: Optional[str] = None, limit: int = 100) -> list:
        """Retrieve trade records."""
        if not self.conn:
            return []
        try:
            with self._lock:
                cursor = self.conn.cursor()
                if symbol:
                    cursor.execute("SELECT * FROM trades WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?",
                                 (symbol, limit))
                else:
                    cursor.execute("SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,))
                return cursor.fetchall()
        except sqlite3.DatabaseError as e:
            if self._is_corrupt_error(e):
                self._recover_db(str(e))
            else:
                logging.error(f"Error retrieving trades: {e}")
            return []
        except Exception as e:
            logging.error(f"Error retrieving trades: {e}")
            return []

    def get_recent_trades(self, limit: int = 100) -> list:
        """Convenience wrapper for most recent trades."""
        return self.get_trades(symbol=None, limit=limit)

    def store_market_data(self, symbol_or_data, data: Optional[Dict[str, Any]] = None):
        """Store market data.

        Can be called as store_market_data(data_dict) or store_market_data(symbol, data_dict).
        """
        if not self.conn:
            return
        try:
            if data is None and isinstance(symbol_or_data, dict):
                payload = symbol_or_data
            else:
                payload = data or {}
                payload.setdefault('symbol', symbol_or_data)

            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("""
                    INSERT INTO market_data (timestamp, symbol, price, volume, source)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    payload.get('timestamp', datetime.now().isoformat()),
                    payload.get('symbol'),
                    payload.get('price'),
                    payload.get('volume'),
                    payload.get('source', 'unknown')
                ))
                self.conn.commit()
                logging.debug(f"Stored market data: {payload}")
        except sqlite3.DatabaseError as e:
            if self._is_corrupt_error(e):
                self._recover_db(str(e))
            else:
                logging.error(f"Error storing market data: {e}")
        except Exception as e:
            logging.error(f"Error storing market data: {e}")

    def market_bee_history(self, symbol: str, days: int = 30) -> list:
        if not self.conn:
            return []
        try:
            cutoff = time.time() - (float(days) * 86400.0)
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute(
                        "SELECT * FROM market_bee_snapshots WHERE symbol=? AND ts>=? ORDER BY ts ASC",
                        (symbol, cutoff),
                    )
                else:
                    c.execute(
                        "SELECT * FROM market_bee_snapshots WHERE ts>=? ORDER BY ts ASC",
                        (cutoff,),
                    )
                cols = [d[0] for d in c.description]
                return [dict(zip(cols, row)) for row in c.fetchall()]
        except Exception:
            return []

    def get_orderbook_snapshots(self, symbol: Optional[str] = None, limit: int = 100) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute("SELECT * FROM orderbook_snapshots WHERE symbol=? ORDER BY ts DESC LIMIT ?", (symbol, int(limit or 100)))
                else:
                    c.execute("SELECT * FROM orderbook_snapshots ORDER BY ts DESC LIMIT ?", (int(limit or 100),))
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = []
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    payload = json.loads(d.get("payload") or "{}")
                    if isinstance(payload, dict):
                        d.update(payload)
                except Exception:
                    pass
                out.append(d)
            return out
        except Exception:
            logging.exception("Error fetching orderbook snapshots")
            return []

    def store_executor_event(self, payload: Dict[str, Any]):
        if not self.conn:
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO executor_events
                    (ts, executor, symbol, side, status, qty, price, notional_usd,
                     net_margin_pct, route_loss_pct, reason, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        payload.get("ts", time.time()),
                        payload.get("executor"),
                        payload.get("symbol"),
                        payload.get("side"),
                        payload.get("status"),
                        payload.get("qty"),
                        payload.get("price"),
                        payload.get("notional_usd"),
                        payload.get("net_margin_pct"),
                        payload.get("route_loss_pct"),
                        payload.get("reason"),
                        json.dumps(payload),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error storing executor event")

    def get_executor_events(self, symbol: Optional[str] = None, days: int = 30) -> list:
        if not self.conn:
            return []
        try:
            cutoff = time.time() - float(days) * 86400.0
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute("SELECT * FROM executor_events WHERE symbol=? AND ts>=? ORDER BY ts ASC", (symbol, cutoff))
                else:
                    c.execute("SELECT * FROM executor_events WHERE ts>=? ORDER BY ts ASC", (cutoff,))
                cols = [d[0] for d in c.description]
                return [dict(zip(cols, row)) for row in c.fetchall()]
        except Exception:
            return []

    def upsert_hummingbot_lifecycle(self, payload: Dict[str, Any]):
        if not self.conn or not payload.get("executor_id"):
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO hummingbot_executor_lifecycle
                    (executor_id, executor_type, symbol, side, state, attempts, created_ts,
                     updated_ts, stopped_ts, reason, config, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(executor_id) DO UPDATE SET
                      executor_type=excluded.executor_type,
                      symbol=excluded.symbol,
                      side=excluded.side,
                      state=excluded.state,
                      attempts=excluded.attempts,
                      updated_ts=excluded.updated_ts,
                      stopped_ts=excluded.stopped_ts,
                      reason=excluded.reason,
                      config=excluded.config,
                      payload=excluded.payload
                    """,
                    (
                        payload.get("executor_id"),
                        payload.get("executor_type"),
                        payload.get("symbol"),
                        payload.get("side"),
                        payload.get("state"),
                        int(payload.get("attempts") or 0),
                        payload.get("created_ts", time.time()),
                        payload.get("updated_ts", time.time()),
                        payload.get("stopped_ts"),
                        payload.get("reason"),
                        json.dumps(payload.get("config") or {}),
                        json.dumps(payload),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error upserting Hummingbot lifecycle")

    def get_hummingbot_lifecycle(self, executor_id: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                if executor_id:
                    c.execute("SELECT * FROM hummingbot_executor_lifecycle WHERE executor_id=?", (executor_id,))
                else:
                    c.execute("SELECT * FROM hummingbot_executor_lifecycle ORDER BY updated_ts DESC LIMIT ?", (int(limit or 100),))
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = {}
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    d.update(json.loads(d.get("payload") or "{}"))
                except Exception:
                    pass
                out[d.get("executor_id")] = d
            return out
        except Exception:
            return {}

    def upsert_worker_performance(self, worker: str, payload: Dict[str, Any]):
        if not self.conn or not worker:
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO worker_performance
                    (worker, total, wins, losses, recent, updated_ts, payload)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(worker) DO UPDATE SET
                      total=excluded.total,
                      wins=excluded.wins,
                      losses=excluded.losses,
                      recent=excluded.recent,
                      updated_ts=excluded.updated_ts,
                      payload=excluded.payload
                    """,
                    (
                        worker,
                        int(payload.get("total") or 0),
                        int(payload.get("wins") or 0),
                        int(payload.get("losses") or 0),
                        json.dumps(payload.get("recent") or []),
                        payload.get("updated_ts", time.time()),
                        json.dumps(payload),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error upserting worker performance")

    def get_worker_performance(self) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute("SELECT * FROM worker_performance")
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = {}
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    payload = json.loads(d.get("payload") or "{}")
                    d.update(payload)
                except Exception:
                    try:
                        d["recent"] = json.loads(d.get("recent") or "[]")
                    except Exception:
                        d["recent"] = []
                out[d.get("worker")] = d
            return out
        except Exception:
            return {}

    def upsert_public_bot_backtest(self, run_id: str, payload: Dict[str, Any]):
        if not self.conn or not run_id:
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO public_bot_backtests
                    (run_id, engine, symbol, status, export_path, metrics, created_ts, updated_ts, payload)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(run_id) DO UPDATE SET
                      engine=excluded.engine,
                      symbol=excluded.symbol,
                      status=excluded.status,
                      export_path=excluded.export_path,
                      metrics=excluded.metrics,
                      updated_ts=excluded.updated_ts,
                      payload=excluded.payload
                    """,
                    (
                        run_id,
                        payload.get("engine"),
                        payload.get("symbol"),
                        payload.get("status"),
                        payload.get("export_path"),
                        json.dumps(payload.get("metrics") or {}),
                        payload.get("created_ts", time.time()),
                        payload.get("updated_ts", time.time()),
                        json.dumps(payload),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error upserting public bot backtest")

    def get_public_bot_backtests(self, run_id: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                if run_id:
                    c.execute("SELECT * FROM public_bot_backtests WHERE run_id=?", (run_id,))
                else:
                    c.execute("SELECT * FROM public_bot_backtests ORDER BY updated_ts DESC LIMIT ?", (int(limit or 100),))
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = {}
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    d.update(json.loads(d.get("payload") or "{}"))
                except Exception:
                    pass
                out[d.get("run_id")] = d
            return out
        except Exception:
            return {}

    def upsert_evidence_record(self, record: Dict[str, Any]):
        if not self.conn or not record or not record.get("evidence_id"):
            return
        try:
            metrics = record.get("metrics") or {}
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO evidence_records
                    (evidence_id, source, engine, run_id, symbol, strategy, verdict, promotion_stage,
                     trades, win_rate, net_profit_pct, max_drawdown_pct, created_ts, updated_ts,
                     gates, metrics, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(evidence_id) DO UPDATE SET
                      source=excluded.source,
                      engine=excluded.engine,
                      run_id=excluded.run_id,
                      symbol=excluded.symbol,
                      strategy=excluded.strategy,
                      verdict=excluded.verdict,
                      promotion_stage=excluded.promotion_stage,
                      trades=excluded.trades,
                      win_rate=excluded.win_rate,
                      net_profit_pct=excluded.net_profit_pct,
                      max_drawdown_pct=excluded.max_drawdown_pct,
                      updated_ts=excluded.updated_ts,
                      gates=excluded.gates,
                      metrics=excluded.metrics,
                      payload=excluded.payload
                    """,
                    (
                        record.get("evidence_id"),
                        record.get("source"),
                        record.get("engine"),
                        record.get("run_id"),
                        record.get("symbol"),
                        record.get("strategy"),
                        record.get("verdict"),
                        record.get("promotion_stage"),
                        metrics.get("trades"),
                        metrics.get("win_rate"),
                        metrics.get("net_profit_pct"),
                        metrics.get("max_drawdown_pct"),
                        record.get("created_ts", time.time()),
                        record.get("updated_ts", time.time()),
                        json.dumps(record.get("gates") or {}),
                        json.dumps(metrics),
                        json.dumps(record),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error upserting evidence record")

    def get_evidence_records(self, symbol: Optional[str] = None, run_id: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                if run_id:
                    c.execute("SELECT * FROM evidence_records WHERE run_id=? ORDER BY updated_ts DESC LIMIT ?", (run_id, int(limit or 100)))
                elif symbol:
                    c.execute("SELECT * FROM evidence_records WHERE symbol=? ORDER BY updated_ts DESC LIMIT ?", (symbol, int(limit or 100)))
                else:
                    c.execute("SELECT * FROM evidence_records ORDER BY updated_ts DESC LIMIT ?", (int(limit or 100),))
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = {}
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    payload = json.loads(d.get("payload") or "{}")
                    if isinstance(payload, dict):
                        d.update(payload)
                except Exception:
                    for key in ("gates", "metrics"):
                        try:
                            d[key] = json.loads(d.get(key) or "{}")
                        except Exception:
                            d[key] = {}
                out[d.get("evidence_id")] = d
            return out
        except Exception:
            logging.exception("Error fetching evidence records")
            return {}

    def upsert_ml_model_candidate(self, candidate: Dict[str, Any]):
        if not self.conn or not candidate or not candidate.get("candidate_id"):
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO ml_model_candidates
                    (candidate_id, family, symbol, objective, status, verdict, created_ts,
                     updated_ts, model_card_path, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(candidate_id) DO UPDATE SET
                      family=excluded.family,
                      symbol=excluded.symbol,
                      objective=excluded.objective,
                      status=excluded.status,
                      verdict=excluded.verdict,
                      updated_ts=excluded.updated_ts,
                      model_card_path=excluded.model_card_path,
                      payload=excluded.payload
                    """,
                    (
                        candidate.get("candidate_id"),
                        candidate.get("family"),
                        candidate.get("symbol"),
                        candidate.get("objective"),
                        candidate.get("status"),
                        candidate.get("verdict"),
                        candidate.get("created_ts", time.time()),
                        candidate.get("updated_ts", time.time()),
                        candidate.get("model_card_path"),
                        json.dumps(candidate),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error upserting ML model candidate")

    def get_ml_model_candidates(self, family: Optional[str] = None, symbol: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                if family:
                    c.execute("SELECT * FROM ml_model_candidates WHERE family=? ORDER BY updated_ts DESC LIMIT ?", (family, int(limit or 100)))
                elif symbol:
                    c.execute("SELECT * FROM ml_model_candidates WHERE symbol=? ORDER BY updated_ts DESC LIMIT ?", (symbol, int(limit or 100)))
                else:
                    c.execute("SELECT * FROM ml_model_candidates ORDER BY updated_ts DESC LIMIT ?", (int(limit or 100),))
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = {}
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    payload = json.loads(d.get("payload") or "{}")
                    if isinstance(payload, dict):
                        d.update(payload)
                except Exception:
                    pass
                out[d.get("candidate_id")] = d
            return out
        except Exception:
            logging.exception("Error fetching ML model candidates")
            return {}

    def upsert_execution_parity_diagnostic(self, diagnostic: Dict[str, Any]):
        if not self.conn or not diagnostic or not diagnostic.get("parity_id"):
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO execution_parity_diagnostics
                    (parity_id, source, symbol, run_id, evidence_id, verdict, created_ts,
                     updated_ts, metrics, gates, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(parity_id) DO UPDATE SET
                      source=excluded.source,
                      symbol=excluded.symbol,
                      run_id=excluded.run_id,
                      evidence_id=excluded.evidence_id,
                      verdict=excluded.verdict,
                      updated_ts=excluded.updated_ts,
                      metrics=excluded.metrics,
                      gates=excluded.gates,
                      payload=excluded.payload
                    """,
                    (
                        diagnostic.get("parity_id"),
                        diagnostic.get("source"),
                        diagnostic.get("symbol"),
                        diagnostic.get("run_id"),
                        diagnostic.get("evidence_id"),
                        diagnostic.get("verdict"),
                        diagnostic.get("created_ts", time.time()),
                        diagnostic.get("updated_ts", time.time()),
                        json.dumps(diagnostic.get("metrics") or {}),
                        json.dumps(diagnostic.get("gates") or {}),
                        json.dumps(diagnostic),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error upserting execution parity diagnostic")

    def get_execution_parity_diagnostics(self, symbol: Optional[str] = None, run_id: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                if run_id:
                    c.execute("SELECT * FROM execution_parity_diagnostics WHERE run_id=? ORDER BY updated_ts DESC LIMIT ?", (run_id, int(limit or 100)))
                elif symbol:
                    c.execute("SELECT * FROM execution_parity_diagnostics WHERE symbol=? ORDER BY updated_ts DESC LIMIT ?", (symbol, int(limit or 100)))
                else:
                    c.execute("SELECT * FROM execution_parity_diagnostics ORDER BY updated_ts DESC LIMIT ?", (int(limit or 100),))
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = {}
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    payload = json.loads(d.get("payload") or "{}")
                    if isinstance(payload, dict):
                        d.update(payload)
                except Exception:
                    for key in ("metrics", "gates"):
                        try:
                            d[key] = json.loads(d.get(key) or "{}")
                        except Exception:
                            d[key] = {}
                out[d.get("parity_id")] = d
            return out
        except Exception:
            logging.exception("Error fetching execution parity diagnostics")
            return {}

    def upsert_signal_marketplace_round(self, round_record: Dict[str, Any]):
        if not self.conn or not round_record or not round_record.get("round_id"):
            return
        try:
            summary = round_record.get("summary") or {}
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO signal_marketplace_rounds
                    (round_id, source, symbol, status, verdict, submitted, eligible,
                     total_simulated_reward, created_ts, updated_ts, gates, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(round_id) DO UPDATE SET
                      source=excluded.source,
                      symbol=excluded.symbol,
                      status=excluded.status,
                      verdict=excluded.verdict,
                      submitted=excluded.submitted,
                      eligible=excluded.eligible,
                      total_simulated_reward=excluded.total_simulated_reward,
                      updated_ts=excluded.updated_ts,
                      gates=excluded.gates,
                      payload=excluded.payload
                    """,
                    (
                        round_record.get("round_id"),
                        round_record.get("source"),
                        round_record.get("symbol"),
                        round_record.get("status"),
                        round_record.get("verdict"),
                        int(summary.get("submitted") or 0),
                        int(summary.get("eligible") or 0),
                        float(summary.get("total_simulated_reward") or 0.0),
                        round_record.get("created_ts", time.time()),
                        round_record.get("updated_ts", time.time()),
                        json.dumps(round_record.get("gates") or {}),
                        json.dumps(round_record),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error upserting signal marketplace round")

    def get_signal_marketplace_rounds(self, symbol: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute("SELECT * FROM signal_marketplace_rounds WHERE symbol=? ORDER BY updated_ts DESC LIMIT ?", (symbol, int(limit or 100)))
                else:
                    c.execute("SELECT * FROM signal_marketplace_rounds ORDER BY updated_ts DESC LIMIT ?", (int(limit or 100),))
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = {}
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    payload = json.loads(d.get("payload") or "{}")
                    if isinstance(payload, dict):
                        d.update(payload)
                except Exception:
                    try:
                        d["gates"] = json.loads(d.get("gates") or "{}")
                    except Exception:
                        d["gates"] = {}
                out[d.get("round_id")] = d
            return out
        except Exception:
            logging.exception("Error fetching signal marketplace rounds")
            return {}

    def get_execution_observations(self, symbol: Optional[str] = None, limit: int = 500) -> Dict[str, Any]:
        if not self.conn:
            return {"orders": [], "fills": [], "latencies_ms": []}
        try:
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute(
                        """
                        SELECT client_order_id, intent_id, venue, symbol, side, order_type, order_id,
                               status, placed_ts, final_ts
                        FROM orders
                        WHERE symbol=?
                        ORDER BY COALESCE(final_ts, placed_ts, 0) DESC
                        LIMIT ?
                        """,
                        (symbol, int(limit or 500)),
                    )
                else:
                    c.execute(
                        """
                        SELECT client_order_id, intent_id, venue, symbol, side, order_type, order_id,
                               status, placed_ts, final_ts
                        FROM orders
                        ORDER BY COALESCE(final_ts, placed_ts, 0) DESC
                        LIMIT ?
                        """,
                        (int(limit or 500),),
                    )
                orders = [dict(zip([d[0] for d in c.description], row)) for row in c.fetchall()]
                client_ids = [o.get("client_order_id") for o in orders if o.get("client_order_id")]
                fills = []
                if client_ids:
                    placeholders = ",".join(["?"] * len(client_ids))
                    c.execute(
                        f"""
                        SELECT order_id, client_order_id, filled_qty, avg_price, fee, slippage_pct, ts
                        FROM fills
                        WHERE client_order_id IN ({placeholders})
                        ORDER BY ts DESC
                        """,
                        tuple(client_ids),
                    )
                    fills = [dict(zip([d[0] for d in c.description], row)) for row in c.fetchall()]
            latencies = []
            for order in orders:
                placed = order.get("placed_ts")
                final = order.get("final_ts")
                try:
                    if placed is not None and final is not None:
                        latencies.append(max(0.0, (float(final) - float(placed)) * 1000.0))
                except Exception:
                    continue
            return {"orders": orders, "fills": fills, "latencies_ms": latencies}
        except Exception:
            logging.exception("Error fetching execution observations")
            return {"orders": [], "fills": [], "latencies_ms": []}

    def store_replay_result(self, payload: Dict[str, Any]):
        if not self.conn:
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO replay_results
                    (ts, symbol, days, trades, wins, losses, net_margin_pct,
                     max_drawdown_pct, clean_exits, failed_exits, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        payload.get("ts", time.time()),
                        payload.get("symbol"),
                        payload.get("days"),
                        payload.get("trades"),
                        payload.get("wins"),
                        payload.get("losses"),
                        payload.get("net_margin_pct"),
                        payload.get("max_drawdown_pct"),
                        payload.get("clean_exits"),
                        payload.get("failed_exits"),
                        json.dumps(payload),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error storing replay result")

    def upsert_pair_protection(self, symbol: str, payload: Dict[str, Any]):
        if not self.conn or not symbol:
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO pair_protections
                    (symbol, state, reason, cooldown_until, daily_loss_pct, failed_quotes,
                     route_loss_spike_pct, low_profit_until, updated_ts, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(symbol) DO UPDATE SET
                      state=excluded.state,
                      reason=excluded.reason,
                      cooldown_until=excluded.cooldown_until,
                      daily_loss_pct=excluded.daily_loss_pct,
                      failed_quotes=excluded.failed_quotes,
                      route_loss_spike_pct=excluded.route_loss_spike_pct,
                      low_profit_until=excluded.low_profit_until,
                      updated_ts=excluded.updated_ts,
                      payload=excluded.payload
                    """,
                    (
                        symbol,
                        payload.get("state"),
                        payload.get("reason"),
                        payload.get("cooldown_until"),
                        payload.get("daily_loss_pct"),
                        payload.get("failed_quotes"),
                        payload.get("route_loss_spike_pct"),
                        payload.get("low_profit_until"),
                        payload.get("updated_ts", time.time()),
                        json.dumps(payload),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error upserting pair protection")

    def get_pair_protections(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute("SELECT * FROM pair_protections WHERE symbol=?", (symbol,))
                else:
                    c.execute("SELECT * FROM pair_protections")
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = {}
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    d.update(json.loads(d.get("payload") or "{}"))
                except Exception:
                    pass
                out[d.get("symbol")] = d
            return out
        except Exception:
            return {}

    def upsert_promotion_record(self, symbol: str, payload: Dict[str, Any]):
        if not self.conn or not symbol:
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO promotion_records
                    (symbol, stage, eligible, reason, paper_trades, win_rate, net_margin_sum,
                     max_drawdown_pct, clean_exits, failed_exits, updated_ts, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(symbol) DO UPDATE SET
                      stage=excluded.stage,
                      eligible=excluded.eligible,
                      reason=excluded.reason,
                      paper_trades=excluded.paper_trades,
                      win_rate=excluded.win_rate,
                      net_margin_sum=excluded.net_margin_sum,
                      max_drawdown_pct=excluded.max_drawdown_pct,
                      clean_exits=excluded.clean_exits,
                      failed_exits=excluded.failed_exits,
                      updated_ts=excluded.updated_ts,
                      payload=excluded.payload
                    """,
                    (
                        symbol,
                        payload.get("stage"),
                        1 if payload.get("eligible") else 0,
                        payload.get("reason"),
                        payload.get("paper_trades"),
                        payload.get("win_rate"),
                        payload.get("net_margin_sum"),
                        payload.get("max_drawdown_pct"),
                        payload.get("clean_exits"),
                        payload.get("failed_exits"),
                        payload.get("updated_ts", time.time()),
                        json.dumps(payload),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error upserting promotion record")

    def get_promotion_records(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute("SELECT * FROM promotion_records WHERE symbol=?", (symbol,))
                else:
                    c.execute("SELECT * FROM promotion_records")
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = {}
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    d.update(json.loads(d.get("payload") or "{}"))
                except Exception:
                    pass
                out[d.get("symbol")] = d
            return out
        except Exception:
            return {}

    def store_paper_trade(self, payload: Dict[str, Any]):
        if not self.conn:
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO paper_trades
                    (ts, symbol, side, qty, price, notional_usd, reason, net_margin_pct, status)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        payload.get("ts", time.time()),
                        payload.get("symbol"),
                        payload.get("side"),
                        payload.get("qty"),
                        payload.get("price"),
                        payload.get("notional_usd"),
                        payload.get("reason"),
                        payload.get("net_margin_pct"),
                        payload.get("status", "PAPER"),
                    )
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error storing paper trade")

    def get_paper_stats(self, symbol: Optional[str] = None, days: int = 30) -> Dict[str, Any]:
        out = {"trades": 0, "wins": 0, "losses": 0, "net_margin_sum": 0.0, "max_drawdown_pct": 0.0}
        if not self.conn:
            return out
        try:
            cutoff = time.time() - float(days) * 86400.0
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute("SELECT * FROM paper_trades WHERE symbol=? AND ts>=? ORDER BY ts ASC", (symbol, cutoff))
                else:
                    c.execute("SELECT * FROM paper_trades WHERE ts>=? ORDER BY ts ASC", (cutoff,))
                rows = [dict(zip([d[0] for d in c.description], r)) for r in c.fetchall()]
            margins = [float(r.get("net_margin_pct") or 0.0) for r in rows]
            out["trades"] = len(rows)
            out["wins"] = len([m for m in margins if m > 0])
            out["losses"] = len([m for m in margins if m <= 0])
            out["net_margin_sum"] = sum(margins)
            out["win_rate"] = (out["wins"] / len(rows)) if rows else 0.0
            running = 0.0
            peak = 0.0
            max_dd = 0.0
            for m in margins:
                running += m
                peak = max(peak, running)
                max_dd = min(max_dd, running - peak)
            out["max_drawdown_pct"] = abs(max_dd)
            return out
        except Exception:
            return out

    def get_paper_trades(self, symbol: Optional[str] = None, days: int = 30) -> list:
        if not self.conn:
            return []
        try:
            cutoff = time.time() - float(days) * 86400.0
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute("SELECT * FROM paper_trades WHERE symbol=? AND ts>=? ORDER BY ts ASC", (symbol, cutoff))
                else:
                    c.execute("SELECT * FROM paper_trades WHERE ts>=? ORDER BY ts ASC", (cutoff,))
                cols = [d[0] for d in c.description]
                return [dict(zip(cols, row)) for row in c.fetchall()]
        except Exception:
            return []

    def upsert_paper_position(self, symbol: str, payload: Dict[str, Any]):
        if not self.conn or not symbol:
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO paper_positions
                    (symbol, qty, entry_price, highest_price, opened_ts, updated_ts, status, payload)
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(symbol) DO UPDATE SET
                      qty=excluded.qty,
                      entry_price=excluded.entry_price,
                      highest_price=excluded.highest_price,
                      updated_ts=excluded.updated_ts,
                      status=excluded.status,
                      payload=excluded.payload
                    """,
                    (
                        symbol,
                        payload.get("qty"),
                        payload.get("entry_price"),
                        payload.get("highest_price"),
                        payload.get("opened_ts"),
                        payload.get("updated_ts", time.time()),
                        payload.get("status", "OPEN"),
                        json.dumps(payload),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error upserting paper position")

    def get_paper_position(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute("SELECT * FROM paper_positions WHERE symbol=?", (symbol,))
                else:
                    c.execute("SELECT * FROM paper_positions")
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = {}
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    payload = json.loads(d.get("payload") or "{}")
                    d.update(payload)
                except Exception:
                    pass
                out[d.get("symbol")] = d
            return out
        except Exception:
            return {}

    def upsert_position_memory(self, symbol: str, payload: Dict[str, Any]):
        if not self.conn or not symbol:
            return
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO position_memory
                    (symbol, qty, entry_price, highest_price, opened_ts, updated_ts, status, payload)
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(symbol) DO UPDATE SET
                      qty=excluded.qty,
                      entry_price=excluded.entry_price,
                      highest_price=excluded.highest_price,
                      updated_ts=excluded.updated_ts,
                      status=excluded.status,
                      payload=excluded.payload
                    """,
                    (
                        symbol,
                        payload.get("qty"),
                        payload.get("entry_price"),
                        payload.get("highest_price"),
                        payload.get("opened_ts"),
                        payload.get("updated_ts", time.time()),
                        payload.get("status", "OPEN"),
                        json.dumps(payload),
                    ),
                )
                self.conn.commit()
        except Exception:
            logging.exception("Error upserting position memory")

    def get_position_memory(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute("SELECT * FROM position_memory WHERE symbol=?", (symbol,))
                else:
                    c.execute("SELECT * FROM position_memory")
                rows = c.fetchall()
                cols = [d[0] for d in c.description]
            out = {}
            for row in rows:
                d = dict(zip(cols, row))
                try:
                    payload = json.loads(d.get("payload") or "{}")
                    d.update(payload)
                except Exception:
                    pass
                out[d.get("symbol")] = d
            return out
        except Exception:
            return {}

    def get_market_data(self, symbol: str, limit: int = 100) -> list:
        """Retrieve market data for a symbol."""
        if not self.conn:
            return []
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("SELECT * FROM market_data WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?",
                             (symbol, limit))
                return cursor.fetchall()
        except sqlite3.DatabaseError as e:
            if self._is_corrupt_error(e):
                self._recover_db(str(e))
            return []
        except Exception as e:
            logging.error(f"Error retrieving market data: {e}")
            return []

    def store_log(self, level: str, message: str, agent: str = "unknown"):
        """Store a log entry."""
        if not self.conn:
            return
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("""
                    INSERT INTO logs (timestamp, level, message, agent)
                    VALUES (?, ?, ?, ?)
                """, (datetime.now().isoformat(), level, message, agent))
                self.conn.commit()
        except sqlite3.DatabaseError as e:
            if self._is_corrupt_error(e):
                self._recover_db(str(e))
            else:
                logging.error(f"Error storing log: {e}")
        except Exception as e:
            logging.error(f"Error storing log: {e}")

    def get_logs(self, level: Optional[str] = None, limit: int = 100) -> list:
        """Retrieve log entries."""
        if not self.conn:
            return []
        try:
            with self._lock:
                cursor = self.conn.cursor()
                if level:
                    cursor.execute("SELECT * FROM logs WHERE level = ? ORDER BY timestamp DESC LIMIT ?",
                                 (level, limit))
                else:
                    cursor.execute("SELECT * FROM logs ORDER BY timestamp DESC LIMIT ?", (limit,))
                return cursor.fetchall()
        except sqlite3.DatabaseError as e:
            if self._is_corrupt_error(e):
                self._recover_db(str(e))
            return []
        except Exception as e:
            logging.error(f"Error retrieving logs: {e}")
            return []

    def store_wallet_balance(self, address: str, asset: str, balance: float):
        """Store wallet balance snapshot."""
        if not self.conn:
            return
        try:
            with self._lock:
                cursor = self.conn.cursor()
                cursor.execute("""
                    INSERT INTO wallet_balances (timestamp, address, asset, balance)
                    VALUES (?, ?, ?, ?)
                """, (datetime.now().isoformat(), address, asset, balance))
                self.conn.commit()
        except sqlite3.DatabaseError as e:
            if self._is_corrupt_error(e):
                self._recover_db(str(e))
            else:
                logging.error(f"Error storing wallet balance: {e}")
        except Exception as e:
            logging.error(f"Error storing wallet balance: {e}")

    def store_security_audit(self, payload: Dict[str, Any]):
        """Persist a security audit record into the DB."""
        if not self.conn:
            return
        try:
            with self._lock:
                cursor = self.conn.cursor()
                ts = int(time.time() * 1000)
                severity = payload.get('severity')
                etype = payload.get('type')
                details = json.dumps(payload.get('details') or {})
                rec = payload.get('recommended_action')
                cursor.execute('INSERT INTO security_audit (ts, severity, event_type, details, recommended_action) VALUES (?,?,?,?,?)', (ts, severity, etype, details, rec))
                self.conn.commit()
        except sqlite3.DatabaseError as e:
            if self._is_corrupt_error(e):
                self._recover_db(str(e))
            else:
                logging.exception('Failed to insert security audit')
        except Exception:
            logging.exception('Failed to insert security audit')

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            logging.info("Data Store Agent closed")
