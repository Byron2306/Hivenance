import sqlite3
import json
import logging
import time
import os
import threading
import shutil
import hashlib
import math
from typing import Any, Dict, Optional
from datetime import datetime

_PHASE3_REGIME_FALLBACK = "unknown"


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
        self._last_phase3_candidate_meta: Dict[str, Any] = {}
        self._connect()
        self._create_tables()

    def _connect(self, check_integrity: bool = True):
        """Establish SQLite connection."""
        try:
            if os.getenv("HIVENANCE_SKIP_DB_QUICK_CHECK", "0") == "1":
                check_integrity = False
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
            CREATE TABLE IF NOT EXISTS observation_runs (
                run_id TEXT PRIMARY KEY,
                started_ts REAL,
                completed_ts REAL,
                venue TEXT,
                status TEXT,
                symbols_attempted INTEGER,
                symbols_successful INTEGER,
                symbols_eligible INTEGER,
                mean_data_quality REAL,
                error_count INTEGER,
                dataset_hash TEXT,
                execution_wired INTEGER DEFAULT 0,
                orders_submitted INTEGER DEFAULT 0,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_observation_runs_completed ON observation_runs(completed_ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS observation_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                ts REAL,
                venue TEXT,
                symbol TEXT,
                price REAL,
                quote_volume_24h REAL,
                spread_bps REAL,
                depth_usd_25bps REAL,
                volatility_expansion REAL,
                volume_zscore REAL,
                book_imbalance REAL,
                data_quality REAL,
                observation_eligible INTEGER,
                execution_eligible INTEGER DEFAULT 0,
                rejection_reasons TEXT,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_observation_symbol_ts ON observation_snapshots(symbol, ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_observation_ts_desc ON observation_snapshots(ts DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_observation_run ON observation_snapshots(run_id)")
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_observation_run_symbol ON observation_snapshots(run_id, symbol)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS hypothesis_runs (
                run_id TEXT PRIMARY KEY,
                observation_run_id TEXT,
                started_ts REAL,
                completed_ts REAL,
                venue TEXT,
                status TEXT,
                symbols_evaluated INTEGER,
                forecasts_total INTEGER,
                non_abstain_forecasts INTEGER,
                abstentions INTEGER,
                dataset_hash TEXT,
                execution_wired INTEGER DEFAULT 0,
                orders_submitted INTEGER DEFAULT 0,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_runs_completed ON hypothesis_runs(completed_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_runs_status_completed ON hypothesis_runs(status, completed_ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS hypothesis_forecasts (
                forecast_id TEXT PRIMARY KEY,
                run_id TEXT,
                observation_run_id TEXT,
                ts REAL,
                target_ts REAL,
                venue TEXT,
                symbol TEXT,
                model_id TEXT,
                hypothesis TEXT,
                horizon_seconds INTEGER,
                direction TEXT,
                entry_price REAL,
                probability_positive_net REAL,
                expected_move_bps REAL,
                expected_cost_bps REAL,
                expected_net_bps REAL,
                raw_score REAL,
                abstain INTEGER,
                reason TEXT,
                settled INTEGER DEFAULT 0,
                execution_eligible INTEGER DEFAULT 0,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_forecast_model_ts ON hypothesis_forecasts(model_id, ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_forecast_symbol_target ON hypothesis_forecasts(symbol, target_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_forecast_ts_desc ON hypothesis_forecasts(ts DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_forecast_run_ts ON hypothesis_forecasts(run_id, ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_forecast_settled_abstain_ts ON hypothesis_forecasts(settled, abstain, ts DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_forecast_settled_model_symbol_ts ON hypothesis_forecasts(settled, abstain, model_id, symbol, ts DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_forecast_settled_hypothesis_ts ON hypothesis_forecasts(settled, abstain, hypothesis, ts DESC)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS hypothesis_outcomes (
                forecast_id TEXT PRIMARY KEY,
                settled_ts REAL,
                exit_price REAL,
                gross_return_bps REAL,
                directional_return_bps REAL,
                net_return_bps REAL,
                positive_net INTEGER,
                brier_score REAL,
                absolute_error_bps REAL,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_outcomes_settled ON hypothesis_outcomes(settled_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_hypothesis_outcomes_positive_settled ON hypothesis_outcomes(positive_net, settled_ts)")
            c.execute("""
            CREATE TABLE IF NOT EXISTS simulation_runs (
                run_id TEXT PRIMARY KEY,
                started_ts REAL,
                completed_ts REAL,
                status TEXT,
                forecasts_examined INTEGER,
                simulations_created INTEGER,
                simulations_skipped_existing INTEGER,
                completed INTEGER,
                rejected INTEGER,
                expired INTEGER,
                partial_fills INTEGER,
                unknown_incidents INTEGER,
                dataset_hash TEXT,
                execution_wired INTEGER DEFAULT 0,
                real_orders_submitted INTEGER DEFAULT 0,
                payload TEXT
            )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_simulation_runs_completed ON simulation_runs(completed_ts)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS simulated_order_intents (
                intent_id TEXT PRIMARY KEY,
                simulation_id TEXT UNIQUE,
                forecast_id TEXT,
                model_id TEXT,
                venue TEXT,
                symbol TEXT,
                side TEXT,
                order_policy TEXT,
                scenario TEXT,
                quantity REAL,
                notional_usd REAL,
                reference_price REAL,
                limit_price REAL,
                risk_budget_usd REAL,
                stop_distance_bps REAL,
                horizon_seconds INTEGER,
                created_ts REAL,
                spot_executable INTEGER,
                live_eligible INTEGER DEFAULT 0,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_sim_intent_forecast ON simulated_order_intents(forecast_id)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS simulated_orders (
                simulation_id TEXT PRIMARY KEY,
                run_id TEXT,
                forecast_id TEXT,
                model_id TEXT,
                hypothesis TEXT,
                venue TEXT,
                symbol TEXT,
                direction TEXT,
                order_policy TEXT,
                scenario TEXT,
                fidelity TEXT,
                seed INTEGER,
                status TEXT,
                terminal_state TEXT,
                started_ts REAL,
                completed_ts REAL,
                fill_ratio REAL,
                quantity_requested REAL,
                quantity_filled REAL,
                notional_requested_usd REAL,
                entry_reference_price REAL,
                exit_reference_price REAL,
                entry_fill_price REAL,
                exit_fill_price REAL,
                gross_return_bps REAL,
                net_return_bps REAL,
                profitable_after_costs INTEGER,
                spot_executable INTEGER,
                execution_wired INTEGER DEFAULT 0,
                real_orders_submitted INTEGER DEFAULT 0,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_sim_orders_model_policy ON simulated_orders(model_id, order_policy, scenario)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_sim_orders_symbol_ts ON simulated_orders(symbol, completed_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_sim_orders_status_completed ON simulated_orders(status, completed_ts DESC)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_sim_orders_forecast ON simulated_orders(forecast_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_sim_orders_model_symbol_completed ON simulated_orders(model_id, symbol, completed_ts DESC)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS simulated_order_events (
                simulation_id TEXT,
                sequence INTEGER,
                state TEXT,
                ts REAL,
                reason TEXT,
                payload TEXT,
                PRIMARY KEY(simulation_id, sequence)
            )
            ''')
            c.execute('''
            CREATE TABLE IF NOT EXISTS simulated_fills (
                fill_id TEXT PRIMARY KEY,
                simulation_id TEXT,
                leg TEXT,
                side TEXT,
                quantity REAL,
                price REAL,
                notional_usd REAL,
                fee_usd REAL,
                liquidity TEXT,
                ts REAL,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_sim_fills_simulation ON simulated_fills(simulation_id)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS simulated_positions (
                simulation_id TEXT PRIMARY KEY,
                symbol TEXT,
                direction TEXT,
                quantity REAL,
                entry_price REAL,
                exit_price REAL,
                status TEXT,
                gross_return_bps REAL,
                net_return_bps REAL,
                opened_ts REAL,
                closed_ts REAL,
                payload TEXT
            )
            ''')
            c.execute('''
            CREATE TABLE IF NOT EXISTS simulated_cost_attribution (
                simulation_id TEXT PRIMARY KEY,
                forecast_gross_bps REAL,
                market_gross_bps REAL,
                entry_spread_bps REAL,
                exit_spread_bps REAL,
                entry_impact_bps REAL,
                exit_impact_bps REAL,
                entry_latency_bps REAL,
                exit_latency_bps REAL,
                fee_bps REAL,
                missed_fill_opportunity_bps REAL,
                stop_slippage_bps REAL,
                total_cost_bps REAL,
                net_bps REAL,
                payload TEXT
            )
            ''')
            c.execute('''
            CREATE TABLE IF NOT EXISTS simulation_incidents (
                incident_id TEXT PRIMARY KEY,
                simulation_id TEXT,
                incident_type TEXT,
                severity TEXT,
                symbol_halted INTEGER,
                automatic_recovery INTEGER,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_sim_incidents_simulation ON simulation_incidents(simulation_id)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase4_validation_runs (
                run_id TEXT PRIMARY KEY,
                started_ts REAL,
                completed_ts REAL,
                status TEXT,
                validator_version TEXT,
                rows_examined INTEGER,
                primary_rows INTEGER,
                candidate_count INTEGER,
                pbo_estimate REAL,
                champion_key TEXT,
                ready_for_phase5_review INTEGER,
                dataset_hash TEXT,
                execution_wired INTEGER DEFAULT 0,
                real_orders_submitted INTEGER DEFAULT 0,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase4_runs_completed ON phase4_validation_runs(completed_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase4_runs_status_completed ON phase4_validation_runs(status, completed_ts)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase4_candidate_results (
                run_id TEXT,
                candidate_key TEXT,
                model_id TEXT,
                order_policy TEXT,
                normal_samples INTEGER,
                mean_net_bps REAL,
                bootstrap_lower_95_bps REAL,
                dsr_probability REAL,
                walk_forward_positive_ratio REAL,
                parameter_positive_ratio REAL,
                symbol_holdout_positive_ratio REAL,
                regime_holdout_positive_ratio REAL,
                symbol_profit_concentration REAL,
                month_profit_concentration REAL,
                robust_score REAL,
                passes_candidate_gates INTEGER,
                payload TEXT,
                PRIMARY KEY(run_id, candidate_key)
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase4_candidates_run_pass ON phase4_candidate_results(run_id, passes_candidate_gates)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase4_candidates_model_policy ON phase4_candidate_results(model_id, order_policy)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase4_fold_results (
                run_id TEXT,
                candidate_key TEXT,
                fold_index INTEGER,
                test_start_ts REAL,
                test_end_ts REAL,
                test_samples INTEGER,
                test_mean_net_bps REAL,
                test_positive INTEGER,
                payload TEXT,
                PRIMARY KEY(run_id, candidate_key, fold_index)
            )
            ''')
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase4_holdout_results (
                run_id TEXT,
                candidate_key TEXT,
                holdout_type TEXT,
                holdout_value TEXT,
                test_samples INTEGER,
                test_mean_net_bps REAL,
                test_positive INTEGER,
                payload TEXT,
                PRIMARY KEY(run_id, candidate_key, holdout_type, holdout_value)
            )
            ''')
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase4_perturbation_results (
                run_id TEXT,
                candidate_key TEXT,
                probability_gate REAL,
                expected_net_gate_bps REAL,
                selected_samples INTEGER,
                mean_net_bps REAL,
                positive INTEGER,
                payload TEXT,
                PRIMARY KEY(run_id, candidate_key, probability_gate, expected_net_gate_bps)
            )
            ''')
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase5_model_freezes (
                freeze_id TEXT PRIMARY KEY,
                phase4_run_id TEXT,
                candidate_key TEXT,
                model_id TEXT,
                order_policy TEXT,
                approved_by TEXT,
                approved_ts REAL,
                phase4_dataset_hash TEXT,
                config_hash TEXT,
                status TEXT,
                shadow_only INTEGER DEFAULT 1,
                execution_eligible INTEGER DEFAULT 0,
                revoked_ts REAL,
                revoke_reason TEXT,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase5_freeze_status_ts ON phase5_model_freezes(status, approved_ts)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase5_shadow_runs (
                run_id TEXT PRIMARY KEY,
                started_ts REAL,
                completed_ts REAL,
                status TEXT,
                freeze_id TEXT,
                intents_created INTEGER,
                intents_skipped INTEGER,
                settlements_created INTEGER,
                ready_for_phase6_review INTEGER,
                dataset_hash TEXT,
                execution_wired INTEGER DEFAULT 0,
                private_exchange_access INTEGER DEFAULT 0,
                transmission_attempts INTEGER DEFAULT 0,
                real_orders_submitted INTEGER DEFAULT 0,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase5_runs_completed ON phase5_shadow_runs(completed_ts)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase5_shadow_intents (
                shadow_intent_id TEXT PRIMARY KEY,
                forecast_id TEXT UNIQUE,
                freeze_id TEXT,
                phase4_run_id TEXT,
                candidate_key TEXT,
                model_id TEXT,
                order_policy TEXT,
                venue TEXT,
                symbol TEXT,
                direction TEXT,
                side TEXT,
                order_type TEXT,
                time_in_force TEXT,
                quantity REAL,
                notional_usd REAL,
                reference_price REAL,
                limit_price REAL,
                stop_distance_bps REAL,
                risk_budget_usd REAL,
                predicted_move_bps REAL,
                predicted_cost_bps REAL,
                predicted_net_bps REAL,
                probability_positive_net REAL,
                horizon_seconds INTEGER,
                created_ts REAL,
                target_ts REAL,
                data_quality REAL,
                spread_bps REAL,
                depth_usd_25bps REAL,
                venue_profile_version TEXT,
                config_hash TEXT,
                status TEXT,
                transmission_status TEXT,
                private_endpoint_called INTEGER DEFAULT 0,
                credentials_used INTEGER DEFAULT 0,
                transmission_attempted INTEGER DEFAULT 0,
                settled INTEGER DEFAULT 0,
                execution_wired INTEGER DEFAULT 0,
                live_eligible INTEGER DEFAULT 0,
                real_orders_submitted INTEGER DEFAULT 0,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase5_intents_target ON phase5_shadow_intents(settled, target_ts)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase5_intents_model_ts ON phase5_shadow_intents(model_id, created_ts)")
            c.execute('''
            CREATE TABLE IF NOT EXISTS phase5_shadow_settlements (
                settlement_id TEXT PRIMARY KEY,
                shadow_intent_id TEXT UNIQUE,
                forecast_id TEXT,
                settled_ts REAL,
                status TEXT,
                fill_model TEXT,
                fill_ratio REAL,
                intended_entry_price REAL,
                hypothetical_entry_price REAL,
                reference_exit_price REAL,
                hypothetical_exit_price REAL,
                entry_slippage_bps REAL,
                exit_slippage_bps REAL,
                fee_bps REAL,
                impact_bps REAL,
                observed_total_cost_bps REAL,
                predicted_cost_bps REAL,
                cost_error_bps REAL,
                gross_directional_return_bps REAL,
                net_return_bps REAL,
                profitable_after_costs INTEGER,
                data_quality REAL,
                transmission_attempted INTEGER DEFAULT 0,
                real_orders_submitted INTEGER DEFAULT 0,
                payload TEXT
            )
            ''')
            c.execute("CREATE INDEX IF NOT EXISTS idx_phase5_settlements_ts ON phase5_shadow_settlements(settled_ts)")
            c.execute('''
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
            ''')
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

                elif typ == 'buzz.observation.snapshot':
                    try:
                        run = payload.get('run') or {}
                        run_id = run.get('run_id')
                        if run_id:
                            c.execute(
                                """
                                INSERT INTO observation_runs
                                (run_id, started_ts, completed_ts, venue, status, symbols_attempted,
                                 symbols_successful, symbols_eligible, mean_data_quality, error_count,
                                 dataset_hash, execution_wired, orders_submitted, payload)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                                ON CONFLICT(run_id) DO UPDATE SET
                                  completed_ts=excluded.completed_ts,
                                  status=excluded.status,
                                  symbols_attempted=excluded.symbols_attempted,
                                  symbols_successful=excluded.symbols_successful,
                                  symbols_eligible=excluded.symbols_eligible,
                                  mean_data_quality=excluded.mean_data_quality,
                                  error_count=excluded.error_count,
                                  dataset_hash=excluded.dataset_hash,
                                  execution_wired=0,
                                  orders_submitted=0,
                                  payload=excluded.payload
                                """,
                                (
                                    run_id,
                                    float(run.get('started_at_ms') or 0) / 1000.0,
                                    float(run.get('completed_at_ms') or 0) / 1000.0,
                                    run.get('venue'),
                                    payload.get('status'),
                                    int(run.get('symbols_attempted') or 0),
                                    int(run.get('symbols_successful') or 0),
                                    int(run.get('symbols_eligible') or 0),
                                    float(run.get('mean_data_quality') or 0.0),
                                    len(run.get('errors') or []),
                                    payload.get('dataset_hash'),
                                    0,
                                    0,
                                    json.dumps(payload),
                                ),
                            )
                            for row in payload.get('candidates') or []:
                                values = row.get('values') or {}
                                c.execute(
                                    """
                                    INSERT OR REPLACE INTO observation_snapshots
                                    (run_id, ts, venue, symbol, price, quote_volume_24h, spread_bps,
                                     depth_usd_25bps, volatility_expansion, volume_zscore, book_imbalance,
                                     data_quality, observation_eligible, execution_eligible,
                                     rejection_reasons, payload)
                                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                                    """,
                                    (
                                        run_id,
                                        float(row.get('timestamp_ms') or 0) / 1000.0,
                                        row.get('venue'),
                                        row.get('symbol'),
                                        row.get('price'),
                                        row.get('quote_volume_24h'),
                                        row.get('spread_bps'),
                                        row.get('depth_usd_25bps'),
                                        values.get('volatility_expansion'),
                                        values.get('volume_zscore'),
                                        values.get('book_imbalance'),
                                        row.get('data_quality'),
                                        1 if row.get('observation_eligible') else 0,
                                        0,
                                        json.dumps(row.get('rejection_reasons') or []),
                                        json.dumps(row),
                                    ),
                                )
                    except Exception:
                        logging.exception('Failed to insert observation snapshot')

                elif typ == 'buzz.hypothesis.snapshot':
                    try:
                        run = payload.get('run') or {}
                        run_id = run.get('run_id')
                        if run_id:
                            c.execute(
                                """
                                INSERT INTO hypothesis_runs
                                (run_id, observation_run_id, started_ts, completed_ts, venue, status,
                                 symbols_evaluated, forecasts_total, non_abstain_forecasts, abstentions,
                                 dataset_hash, execution_wired, orders_submitted, payload)
                                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                                ON CONFLICT(run_id) DO UPDATE SET
                                  completed_ts=excluded.completed_ts, status=excluded.status,
                                  symbols_evaluated=excluded.symbols_evaluated, forecasts_total=excluded.forecasts_total,
                                  non_abstain_forecasts=excluded.non_abstain_forecasts, abstentions=excluded.abstentions,
                                  dataset_hash=excluded.dataset_hash, execution_wired=0, orders_submitted=0,
                                  payload=excluded.payload
                                """,
                                (
                                    run_id, run.get('observation_run_id'),
                                    float(run.get('started_at_ms') or 0) / 1000.0,
                                    float(run.get('completed_at_ms') or 0) / 1000.0,
                                    run.get('venue'), payload.get('status'),
                                    int(run.get('symbols_evaluated') or 0),
                                    int(run.get('forecasts_total') or 0),
                                    int(run.get('non_abstain_forecasts') or 0),
                                    int(run.get('abstentions') or 0),
                                    payload.get('dataset_hash'), 0, 0, json.dumps(payload),
                                ),
                            )
                            for row in payload.get('forecasts') or []:
                                forecast_id = row.get('forecast_id')
                                if not forecast_id:
                                    continue
                                c.execute(
                                    """
                                    INSERT OR REPLACE INTO hypothesis_forecasts
                                    (forecast_id, run_id, observation_run_id, ts, target_ts, venue, symbol,
                                     model_id, hypothesis, horizon_seconds, direction, entry_price,
                                     probability_positive_net, expected_move_bps, expected_cost_bps,
                                     expected_net_bps, raw_score, abstain, reason, settled,
                                     execution_eligible, payload)
                                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                                    """,
                                    (
                                        forecast_id, run_id, row.get('observation_run_id'),
                                        float(row.get('timestamp_ms') or 0) / 1000.0,
                                        float(row.get('target_timestamp_ms') or 0) / 1000.0,
                                        row.get('venue'), row.get('symbol'), row.get('model_id'),
                                        row.get('hypothesis'), int(row.get('horizon_seconds') or 0),
                                        row.get('direction'), row.get('entry_price'),
                                        row.get('probability_positive_net'), row.get('expected_move_bps'),
                                        row.get('expected_cost_bps'), row.get('expected_net_bps'),
                                        row.get('raw_score'), 1 if row.get('abstain') else 0,
                                        row.get('reason'), 0, 0, json.dumps(row),
                                    ),
                                )
                    except Exception:
                        logging.exception('Failed to insert hypothesis snapshot')

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

    def get_observation_runs(self, limit: int = 100) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute("SELECT * FROM observation_runs ORDER BY completed_ts DESC LIMIT ?", (int(limit or 100),))
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            out = []
            for row in rows:
                record = dict(zip(cols, row))
                try:
                    payload = json.loads(record.get("payload") or "{}")
                    record["payload"] = payload
                except Exception:
                    record["payload"] = {}
                record["execution_wired"] = False
                record["orders_submitted"] = 0
                out.append(record)
            return out
        except Exception:
            logging.exception("Error fetching observation runs")
            return []

    def get_observation_snapshots(self, symbol: Optional[str] = None, limit: int = 100) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                if symbol:
                    c.execute("SELECT * FROM observation_snapshots WHERE symbol=? ORDER BY ts DESC LIMIT ?", (symbol, int(limit or 100)))
                else:
                    c.execute("SELECT * FROM observation_snapshots ORDER BY ts DESC LIMIT ?", (int(limit or 100),))
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            out = []
            for row in rows:
                record = dict(zip(cols, row))
                try:
                    payload = json.loads(record.get("payload") or "{}")
                    if isinstance(payload, dict):
                        record.update(payload)
                except Exception:
                    pass
                reasons = record.get("rejection_reasons")
                if isinstance(reasons, str):
                    try:
                        record["rejection_reasons"] = json.loads(reasons or "[]")
                    except Exception:
                        record["rejection_reasons"] = []
                elif isinstance(reasons, (list, tuple)):
                    record["rejection_reasons"] = list(reasons)
                else:
                    record["rejection_reasons"] = []
                record["execution_eligible"] = False
                out.append(record)
            return out
        except Exception:
            logging.exception("Error fetching observation snapshots")
            return []

    def get_observation_readiness(
        self,
        *,
        required_days: float = 7.0,
        min_mean_quality: float = 0.99,
        min_success_ratio: float = 0.90,
    ) -> Dict[str, Any]:
        """Summarize whether Phase-1 has accumulated enough clean observation evidence.

        This is an evidence-age gate only. It never grants execution eligibility.
        """
        result: Dict[str, Any] = {
            "phase": 1,
            "mode": "observation_only",
            "ready_for_phase2_review": False,
            "execution_eligible": False,
            "required_days": float(required_days),
            "observed_days": 0,
            "calendar_span_days": 0.0,
            "runs": 0,
            "healthy_runs": 0,
            "run_success_ratio": 0.0,
            "snapshots": 0,
            "mean_data_quality": 0.0,
            "execution_wired_violations": 0,
            "orders_submitted": 0,
            "reasons": [],
        }
        if not self.conn:
            result["reasons"] = ["data_store_unavailable"]
            return result
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    SELECT COUNT(*), MIN(started_ts), MAX(completed_ts),
                           SUM(CASE WHEN status='HEALTHY' THEN 1 ELSE 0 END),
                           AVG(mean_data_quality),
                           SUM(CASE WHEN execution_wired != 0 THEN 1 ELSE 0 END),
                           SUM(COALESCE(orders_submitted, 0)),
                           COUNT(DISTINCT date(completed_ts, 'unixepoch'))
                    FROM observation_runs
                    """
                )
                row = c.fetchone() or (0, None, None, 0, 0.0, 0, 0, 0)
                c.execute("SELECT COUNT(*) FROM observation_snapshots")
                snapshots = int((c.fetchone() or [0])[0] or 0)
            runs = int(row[0] or 0)
            started = row[1]
            completed = row[2]
            healthy = int(row[3] or 0)
            calendar_span_days = 0.0
            if started is not None and completed is not None and completed >= started:
                calendar_span_days = (float(completed) - float(started)) / 86_400.0
            observed_days = int(row[7] or 0)
            quality = float(row[4] or 0.0)
            execution_violations = int(row[5] or 0)
            orders = int(row[6] or 0)
            success_ratio = healthy / runs if runs else 0.0
            reasons = []
            if runs <= 0:
                reasons.append("no_observation_runs")
            if observed_days < int(required_days):
                reasons.append("insufficient_observation_days")
            if snapshots <= 0:
                reasons.append("no_observation_snapshots")
            if quality < float(min_mean_quality):
                reasons.append("mean_data_quality_below_gate")
            if success_ratio < float(min_success_ratio):
                reasons.append("healthy_run_ratio_below_gate")
            if execution_violations:
                reasons.append("execution_wired_violation")
            if orders:
                reasons.append("nonzero_orders_submitted")
            result.update({
                "ready_for_phase2_review": not reasons,
                "observed_days": max(0, observed_days),
                "calendar_span_days": round(max(0.0, calendar_span_days), 6),
                "runs": runs,
                "healthy_runs": healthy,
                "run_success_ratio": round(success_ratio, 6),
                "snapshots": snapshots,
                "mean_data_quality": round(quality, 6),
                "execution_wired_violations": execution_violations,
                "orders_submitted": orders,
                "reasons": reasons,
            })
            return result
        except Exception:
            logging.exception("Error computing Phase-1 observation readiness")
            result["reasons"] = ["readiness_query_failed"]
            return result

    def get_observation_universe(self, *, days: float = 7.0, limit_per_cohort: int = 8) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "days": float(days),
            "cohorts": {},
            "symbols": {},
        }
        if not self.conn:
            result["error"] = "data_store_unavailable"
            return result
        cutoff = time.time() - (max(0.25, float(days)) * 86400.0)
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    "SELECT symbol, observation_eligible, spread_bps, depth_usd_25bps, data_quality, payload FROM observation_snapshots WHERE ts>=? ORDER BY ts DESC",
                    (cutoff,),
                )
                rows = c.fetchall()
            cohorts: Dict[str, list[Dict[str, Any]]] = {}
            symbols: Dict[str, Dict[str, Any]] = {}
            for symbol, observation_eligible, spread_bps, depth_usd_25bps, data_quality, payload in rows:
                try:
                    record = json.loads(payload or "{}")
                except Exception:
                    record = {}
                if not isinstance(record, dict):
                    record = {}
                values = record.get("values") if isinstance(record.get("values"), dict) else {}
                cohort = str(values.get("cohort_bucket") or "research_bench")
                tradable_score = float(values.get("tradable_opportunity_score") or 0.0)
                entry = symbols.setdefault(str(symbol), {
                    "symbol": str(symbol),
                    "cohort_bucket": cohort,
                    "latest_data_quality": float(data_quality or 0.0),
                    "latest_spread_bps": spread_bps,
                    "latest_depth_usd_25bps": depth_usd_25bps,
                    "eligible_hits": 0,
                    "bench_hits": 0,
                    "observations": 0,
                    "best_tradable_opportunity_score": tradable_score,
                })
                entry["observations"] += 1
                if observation_eligible:
                    entry["eligible_hits"] += 1
                else:
                    entry["bench_hits"] += 1
                entry["best_tradable_opportunity_score"] = max(entry["best_tradable_opportunity_score"], tradable_score)
                entry["cohort_bucket"] = cohort
            for item in symbols.values():
                item["eligibility_ratio"] = round(int(item["eligible_hits"]) / max(1, int(item["observations"])), 6)
                cohorts.setdefault(str(item["cohort_bucket"]), []).append(item)
            result["symbols"] = symbols
            result["cohorts"] = {
                cohort: sorted(
                    rows,
                    key=lambda item: (
                        -float(item.get("eligibility_ratio") or 0.0),
                        -float(item.get("best_tradable_opportunity_score") or 0.0),
                        -int(item.get("observations") or 0),
                    ),
                )[: max(1, int(limit_per_cohort or 8))]
                for cohort, rows in cohorts.items()
            }
            return result
        except Exception:
            logging.exception("Error computing observation universe")
            result["error"] = "observation_universe_failed"
            return result

    def get_hypothesis_runs(self, limit: int = 100) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute("SELECT * FROM hypothesis_runs ORDER BY completed_ts DESC LIMIT ?", (int(limit or 100),))
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            out = []
            for row in rows:
                record = dict(zip(cols, row))
                try:
                    record["payload"] = json.loads(record.get("payload") or "{}")
                except Exception:
                    record["payload"] = {}
                record["execution_wired"] = False
                record["orders_submitted"] = 0
                out.append(record)
            return out
        except Exception:
            logging.exception("Error fetching hypothesis runs")
            return []

    def get_hypothesis_forecasts(
        self,
        model_id: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 250,
    ) -> list:
        if not self.conn:
            return []
        try:
            clauses = []
            params: list[Any] = []
            if model_id:
                clauses.append("model_id=?")
                params.append(model_id)
            if symbol:
                clauses.append("symbol=?")
                params.append(symbol)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            params.append(int(limit or 250))
            with self._lock:
                c = self.conn.cursor()
                c.execute(f"SELECT * FROM hypothesis_forecasts {where} ORDER BY ts DESC LIMIT ?", tuple(params))
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            out = []
            for row in rows:
                record = dict(zip(cols, row))
                try:
                    payload = json.loads(record.get("payload") or "{}")
                    if isinstance(payload, dict):
                        record.update(payload)
                except Exception:
                    pass
                record["execution_eligible"] = False
                out.append(record)
            return out
        except Exception:
            logging.exception("Error fetching hypothesis forecasts")
            return []

    def get_hypothesis_outcomes(self, model_id: Optional[str] = None, limit: int = 250) -> list:
        if not self.conn:
            return []
        try:
            params: list[Any] = []
            where = ""
            if model_id:
                where = "WHERE f.model_id=?"
                params.append(model_id)
            params.append(int(limit or 250))
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    f"""
                    SELECT o.*, f.model_id, f.hypothesis, f.symbol, f.horizon_seconds,
                           f.direction, f.entry_price, f.probability_positive_net,
                           f.expected_move_bps, f.expected_cost_bps, f.abstain
                    FROM hypothesis_outcomes o
                    JOIN hypothesis_forecasts f ON f.forecast_id=o.forecast_id
                    {where}
                    ORDER BY o.settled_ts DESC LIMIT ?
                    """,
                    tuple(params),
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            logging.exception("Error fetching hypothesis outcomes")
            return []

    def settle_mature_hypothesis_forecasts(
        self,
        *,
        now_ts: Optional[float] = None,
        tolerance_sec: float = 600.0,
        limit: int = 5000,
    ) -> Dict[str, Any]:
        """Settle forecasts against the first persisted observation after target time.

        DOWN forecasts are evaluated synthetically for research parity. This method
        does not create orders, positions, balances, or execution intents.
        """
        result = {"examined": 0, "settled": 0, "pending": 0, "execution_wired": False, "orders_submitted": 0}
        if not self.conn:
            result["error"] = "data_store_unavailable"
            return result
        cutoff = float(now_ts if now_ts is not None else time.time())
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    SELECT forecast_id, symbol, target_ts, direction, entry_price,
                           probability_positive_net, expected_move_bps, expected_cost_bps, abstain
                    FROM hypothesis_forecasts
                    WHERE settled=0 AND target_ts<=?
                    ORDER BY target_ts ASC LIMIT ?
                    """,
                    (cutoff, int(limit or 5000)),
                )
                forecasts = c.fetchall()
                result["examined"] = len(forecasts)
                for row in forecasts:
                    (forecast_id, symbol, target_ts, direction, entry_price, probability,
                     expected_move, expected_cost, abstain) = row
                    c.execute(
                        """
                        SELECT ts, price FROM observation_snapshots
                        WHERE symbol=? AND ts>=? AND ts<=? AND price IS NOT NULL
                        ORDER BY ts ASC LIMIT 1
                        """,
                        (symbol, float(target_ts), float(target_ts) + float(tolerance_sec)),
                    )
                    market_row = c.fetchone()
                    if not market_row or not entry_price or float(entry_price) <= 0:
                        result["pending"] += 1
                        continue
                    settled_ts, exit_price = market_row
                    raw_return_bps = ((float(exit_price) - float(entry_price)) / float(entry_price)) * 10_000.0
                    if direction == "UP":
                        directional_bps = raw_return_bps
                    elif direction == "DOWN":
                        directional_bps = -raw_return_bps
                    else:
                        directional_bps = 0.0
                    cost_bps = float(expected_cost or 0.0) if not abstain else 0.0
                    net_bps = directional_bps - cost_bps if not abstain else 0.0
                    positive = 1 if net_bps > 0 else 0
                    brier = None
                    if probability is not None:
                        brier = (float(probability) - float(positive)) ** 2
                    absolute_error = None
                    if expected_move is not None and not abstain:
                        absolute_error = abs(abs(directional_bps) - float(expected_move))
                    payload = {
                        "forecast_id": forecast_id,
                        "target_ts": target_ts,
                        "settled_ts": settled_ts,
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "market_return_bps": raw_return_bps,
                        "directional_return_bps": directional_bps,
                        "expected_cost_bps": cost_bps,
                        "net_return_bps": net_bps,
                        "positive_net": bool(positive),
                        "research_only": True,
                    }
                    c.execute(
                        """
                        INSERT OR REPLACE INTO hypothesis_outcomes
                        (forecast_id, settled_ts, exit_price, gross_return_bps,
                         directional_return_bps, net_return_bps, positive_net,
                         brier_score, absolute_error_bps, payload)
                        VALUES (?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            forecast_id, settled_ts, exit_price, raw_return_bps,
                            directional_bps, net_bps, positive, brier,
                            absolute_error, json.dumps(payload),
                        ),
                    )
                    c.execute("UPDATE hypothesis_forecasts SET settled=1 WHERE forecast_id=?", (forecast_id,))
                    result["settled"] += 1
                self.conn.commit()
            return result
        except Exception:
            logging.exception("Error settling hypothesis forecasts")
            result["error"] = "settlement_failed"
            return result

    def get_hypothesis_scorecard(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "phase": 2,
            "mode": "hypothesis_research_only",
            "models": [],
            "native_model_diagnostics": [],
            "expectancy_breakdown": {},
            "demotion_recommendations": [],
            "cohort_breakdown": {},
            "slice_breakdown": [],
            "regime_model_breakdown": [],
            "profitability_frontier": [],
            "abstention_reason_breakdown": [],
            "near_miss_recovery_candidates": [],
            "execution_eligible": False,
            "orders_submitted": 0,
        }
        if not self.conn:
            result["error"] = "data_store_unavailable"
            return result
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    SELECT f.model_id, f.hypothesis,
                           COUNT(*) AS forecasts,
                           SUM(CASE WHEN f.abstain=0 THEN 1 ELSE 0 END) AS non_abstain,
                           SUM(CASE WHEN f.settled=1 THEN 1 ELSE 0 END) AS settled,
                           SUM(CASE WHEN f.settled=1 AND f.abstain=0 THEN 1 ELSE 0 END) AS settled_trades,
                           AVG(CASE WHEN f.abstain=0 THEN f.expected_net_bps END) AS mean_expected_net_bps,
                           AVG(CASE WHEN f.abstain=0 THEN f.expected_cost_bps END) AS mean_expected_cost_bps,
                           AVG(CASE WHEN f.settled=1 AND f.abstain=0 THEN o.net_return_bps END) AS mean_net_bps,
                           AVG(CASE WHEN f.settled=1 AND f.abstain=0 THEN o.directional_return_bps END) AS mean_directional_bps,
                           AVG(CASE WHEN f.settled=1 AND f.abstain=0 THEN o.positive_net END) AS win_rate,
                           AVG(CASE WHEN f.settled=1 AND f.probability_positive_net IS NOT NULL THEN o.brier_score END) AS brier_score,
                           AVG(CASE WHEN f.settled=1 AND f.abstain=0 THEN o.absolute_error_bps END) AS mean_abs_error_bps,
                           SUM(CASE WHEN f.settled=1 AND f.abstain=0 THEN o.net_return_bps ELSE 0 END) AS cumulative_net_bps
                    FROM hypothesis_forecasts f
                    LEFT JOIN hypothesis_outcomes o ON o.forecast_id=f.forecast_id
                    GROUP BY f.model_id, f.hypothesis
                    ORDER BY f.model_id
                    """
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            models = []
            for row in rows:
                record = dict(zip(cols, row))
                for key in (
                    "mean_expected_net_bps",
                    "mean_expected_cost_bps",
                    "mean_net_bps",
                    "mean_directional_bps",
                    "win_rate",
                    "brier_score",
                    "mean_abs_error_bps",
                    "cumulative_net_bps",
                ):
                    if record.get(key) is not None:
                        record[key] = round(float(record[key]), 6)
                model_id = str(record.get("model_id") or "")
                forecasts = int(record.get("forecasts") or 0)
                non_abstain = int(record.get("non_abstain") or 0)
                settled_trades = int(record.get("settled_trades") or 0)
                record["activation_rate"] = round(non_abstain / max(1, forecasts), 6)
                record["abstain_rate"] = round(1.0 - record["activation_rate"], 6)
                record["settled_trade_rate"] = round(settled_trades / max(1, non_abstain), 6) if non_abstain else 0.0
                expected = float(record.get("mean_expected_net_bps") or 0.0)
                realized = float(record.get("mean_net_bps") or 0.0) if record.get("mean_net_bps") is not None else None
                realized_move = float(record.get("mean_directional_bps") or 0.0) if record.get("mean_directional_bps") is not None else None
                expected_cost = float(record.get("mean_expected_cost_bps") or 0.0)
                record["cost_drag_bps"] = round((realized_move - realized) if realized is not None and realized_move is not None else expected_cost, 6)
                if settled_trades <= 0:
                    record["diagnostic_label"] = "inactive_or_unsettled"
                elif realized is not None and realized > 0:
                    record["diagnostic_label"] = "profitable_so_far"
                elif expected > 0 and realized is not None and realized <= 0:
                    record["diagnostic_label"] = "active_but_expectancy_failing"
                elif record["activation_rate"] < 0.05:
                    record["diagnostic_label"] = "too_strict_or_untriggered"
                else:
                    record["diagnostic_label"] = "active_but_unprofitable"
                record["is_baseline"] = model_id.startswith("baseline_")
                if record["is_baseline"]:
                    record["model_role"] = "BASELINE"
                    record["model_family"] = "phoenix_baseline"
                elif model_id.startswith("adapter_freqtrade"):
                    record["model_role"] = "FEDERATED"
                    record["model_family"] = "freqtrade"
                elif model_id.startswith("adapter_jesse"):
                    record["model_role"] = "FEDERATED"
                    record["model_family"] = "jesse"
                elif model_id.startswith("candidate_freqai"):
                    record["model_role"] = "FEDERATED"
                    record["model_family"] = "freqai"
                elif model_id.startswith("candidate_finrl"):
                    record["model_role"] = "FEDERATED"
                    record["model_family"] = "finrl_crypto"
                elif model_id.startswith("candidate_macrohft"):
                    record["model_role"] = "FEDERATED"
                    record["model_family"] = "macrohft"
                elif model_id.startswith("candidate_webcrypto"):
                    record["model_role"] = "FEDERATED"
                    record["model_family"] = "webcryptoagent"
                else:
                    record["model_role"] = "PRIMARY"
                    record["model_family"] = "phoenix_native"
                models.append(record)
            result["models"] = models
            result["champion_by_mean_net_bps"] = None
            result["champion_research_model_by_mean_net_bps"] = None
            eligible = [m for m in models if int(m.get("settled_trades") or 0) > 0 and m.get("mean_net_bps") is not None]
            if eligible:
                result["champion_by_mean_net_bps"] = max(eligible, key=lambda item: float(item["mean_net_bps"]))["model_id"]
            research_eligible = [m for m in eligible if not m.get("is_baseline")]
            if research_eligible:
                result["champion_research_model_by_mean_net_bps"] = max(
                    research_eligible, key=lambda item: float(item["mean_net_bps"])
                )["model_id"]
            native_models = [m for m in models if m.get("model_family") == "phoenix_native"]
            result["native_model_diagnostics"] = [
                {
                    "model_id": row.get("model_id"),
                    "hypothesis": row.get("hypothesis"),
                    "activation_rate": row.get("activation_rate"),
                    "settled_trades": int(row.get("settled_trades") or 0),
                    "mean_expected_net_bps": row.get("mean_expected_net_bps"),
                    "mean_net_bps": row.get("mean_net_bps"),
                    "cost_drag_bps": row.get("cost_drag_bps"),
                    "diagnostic_label": row.get("diagnostic_label"),
                }
                for row in sorted(
                    native_models,
                    key=lambda item: (
                        int(item.get("settled_trades") or 0),
                        float(item.get("activation_rate") or 0.0),
                        float(item.get("mean_net_bps") if item.get("mean_net_bps") is not None else -10**9),
                    ),
                    reverse=True,
                )
            ]
            def _aggregate(group: list[Dict[str, Any]]) -> Dict[str, Any]:
                forecasts = sum(int(item.get("forecasts") or 0) for item in group)
                non_abstain = sum(int(item.get("non_abstain") or 0) for item in group)
                settled_trades = sum(int(item.get("settled_trades") or 0) for item in group)
                expected_weighted_sum = sum(
                    float(item.get("mean_expected_net_bps") or 0.0) * int(item.get("non_abstain") or 0)
                    for item in group
                    if item.get("mean_expected_net_bps") is not None
                )
                realized_weighted_sum = sum(
                    float(item.get("mean_net_bps") or 0.0) * int(item.get("settled_trades") or 0)
                    for item in group
                    if item.get("mean_net_bps") is not None
                )
                cost_weighted_sum = sum(
                    float(item.get("cost_drag_bps") or 0.0) * int(item.get("settled_trades") or 0)
                    for item in group
                    if item.get("cost_drag_bps") is not None
                )
                return {
                    "models": len(group),
                    "forecasts": forecasts,
                    "non_abstain": non_abstain,
                    "settled_trades": settled_trades,
                    "activation_rate": round(non_abstain / max(1, forecasts), 6),
                    "mean_expected_net_bps": round(expected_weighted_sum / max(1, non_abstain), 6) if non_abstain else None,
                    "mean_realized_net_bps": round(realized_weighted_sum / max(1, settled_trades), 6) if settled_trades else None,
                    "mean_cost_drag_bps": round(cost_weighted_sum / max(1, settled_trades), 6) if settled_trades else None,
                }
            result["expectancy_breakdown"] = {
                "native": _aggregate([m for m in models if m.get("model_family") == "phoenix_native"]),
                "federated": _aggregate([m for m in models if m.get("model_role") == "FEDERATED"]),
                "baseline": _aggregate([m for m in models if m.get("is_baseline")]),
            }
            with self._lock:
                c = self.conn.cursor()
                c.execute("SELECT payload FROM hypothesis_forecasts ORDER BY ts DESC LIMIT 10000")
                payload_rows = [row[0] for row in c.fetchall()]
            cohort_stats: Dict[str, Dict[str, Any]] = {}
            for raw_payload in payload_rows:
                try:
                    payload = json.loads(raw_payload or "{}")
                except Exception:
                    payload = {}
                if not isinstance(payload, dict):
                    continue
                inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
                cohort = str(inputs.get("cohort_bucket") or "unknown")
                bucket = cohort_stats.setdefault(cohort, {
                    "cohort_bucket": cohort,
                    "forecasts": 0,
                    "non_abstain": 0,
                    "settled_trades": 0,
                    "expected_sum": 0.0,
                    "expected_n": 0,
                    "realized_sum": 0.0,
                    "realized_n": 0,
                    "top_models": {},
                })
                bucket["forecasts"] += 1
                if not payload.get("abstain"):
                    bucket["non_abstain"] += 1
                exp = payload.get("expected_net_bps")
                if exp is not None:
                    bucket["expected_sum"] += float(exp)
                    bucket["expected_n"] += 1
                model_id = str(payload.get("model_id") or "unknown")
                bucket["top_models"][model_id] = bucket["top_models"].get(model_id, 0) + (0 if payload.get("abstain") else 1)
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    SELECT f.payload, o.net_return_bps
                    FROM hypothesis_outcomes o
                    JOIN hypothesis_forecasts f ON f.forecast_id=o.forecast_id
                    ORDER BY o.settled_ts DESC LIMIT 10000
                    """
                )
                outcome_rows = c.fetchall()
            for raw_payload, net_return_bps in outcome_rows:
                try:
                    payload = json.loads(raw_payload or "{}")
                except Exception:
                    payload = {}
                if not isinstance(payload, dict) or payload.get("abstain"):
                    continue
                inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
                cohort = str(inputs.get("cohort_bucket") or "unknown")
                bucket = cohort_stats.setdefault(cohort, {
                    "cohort_bucket": cohort,
                    "forecasts": 0,
                    "non_abstain": 0,
                    "settled_trades": 0,
                    "expected_sum": 0.0,
                    "expected_n": 0,
                    "realized_sum": 0.0,
                    "realized_n": 0,
                    "top_models": {},
                })
                bucket["settled_trades"] += 1
                if net_return_bps is not None:
                    bucket["realized_sum"] += float(net_return_bps)
                    bucket["realized_n"] += 1
            result["cohort_breakdown"] = {
                cohort: {
                    "cohort_bucket": cohort,
                    "forecasts": int(bucket["forecasts"]),
                    "non_abstain": int(bucket["non_abstain"]),
                    "activation_rate": round(int(bucket["non_abstain"]) / max(1, int(bucket["forecasts"])), 6),
                    "settled_trades": int(bucket["settled_trades"]),
                    "mean_expected_net_bps": round(bucket["expected_sum"] / max(1, int(bucket["expected_n"])), 6) if bucket["expected_n"] else None,
                    "mean_realized_net_bps": round(bucket["realized_sum"] / max(1, int(bucket["realized_n"])), 6) if bucket["realized_n"] else None,
                    "top_models": [
                        {"model_id": model_id, "non_abstain": count}
                        for model_id, count in sorted(bucket["top_models"].items(), key=lambda item: (-item[1], item[0]))[:4]
                    ],
                }
                for cohort, bucket in cohort_stats.items()
            }
            slice_stats: Dict[tuple[str, str, str, str], Dict[str, Any]] = {}
            for raw_payload in payload_rows:
                try:
                    payload = json.loads(raw_payload or "{}")
                except Exception:
                    payload = {}
                if not isinstance(payload, dict):
                    continue
                inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
                regime_hint = str(inputs.get("regime_hint") or ((inputs.get("regime_inputs") or {}).get("regime_hint")) or "unknown")
                cohort_bucket = str(inputs.get("cohort_bucket") or "unknown")
                symbol_class = str(inputs.get("symbol_class") or "unknown")
                hypothesis = str(payload.get("hypothesis") or "unknown")
                key = (hypothesis, regime_hint, cohort_bucket, symbol_class)
                bucket = slice_stats.setdefault(key, {
                    "hypothesis": hypothesis,
                    "regime_hint": regime_hint,
                    "cohort_bucket": cohort_bucket,
                    "symbol_class": symbol_class,
                    "forecasts": 0,
                    "non_abstain": 0,
                    "settled_trades": 0,
                    "expected_sum": 0.0,
                    "expected_n": 0,
                    "realized_sum": 0.0,
                    "realized_n": 0,
                    "top_models": {},
                })
                bucket["forecasts"] += 1
                if not payload.get("abstain"):
                    bucket["non_abstain"] += 1
                    model_id = str(payload.get("model_id") or "unknown")
                    bucket["top_models"][model_id] = bucket["top_models"].get(model_id, 0) + 1
                exp = payload.get("expected_net_bps")
                if exp is not None and not payload.get("abstain"):
                    bucket["expected_sum"] += float(exp)
                    bucket["expected_n"] += 1
            for raw_payload, net_return_bps in outcome_rows:
                try:
                    payload = json.loads(raw_payload or "{}")
                except Exception:
                    payload = {}
                if not isinstance(payload, dict) or payload.get("abstain"):
                    continue
                inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
                regime_hint = str(inputs.get("regime_hint") or ((inputs.get("regime_inputs") or {}).get("regime_hint")) or "unknown")
                cohort_bucket = str(inputs.get("cohort_bucket") or "unknown")
                symbol_class = str(inputs.get("symbol_class") or "unknown")
                hypothesis = str(payload.get("hypothesis") or "unknown")
                key = (hypothesis, regime_hint, cohort_bucket, symbol_class)
                bucket = slice_stats.setdefault(key, {
                    "hypothesis": hypothesis,
                    "regime_hint": regime_hint,
                    "cohort_bucket": cohort_bucket,
                    "symbol_class": symbol_class,
                    "forecasts": 0,
                    "non_abstain": 0,
                    "settled_trades": 0,
                    "expected_sum": 0.0,
                    "expected_n": 0,
                    "realized_sum": 0.0,
                    "realized_n": 0,
                    "top_models": {},
                })
                bucket["settled_trades"] += 1
                if net_return_bps is not None:
                    bucket["realized_sum"] += float(net_return_bps)
                    bucket["realized_n"] += 1
            result["slice_breakdown"] = sorted(
                [
                    {
                        "slice_key": f"{hypothesis}|{regime_hint}|{cohort_bucket}|{symbol_class}",
                        "hypothesis": hypothesis,
                        "regime_hint": regime_hint,
                        "cohort_bucket": cohort_bucket,
                        "symbol_class": symbol_class,
                        "forecasts": int(bucket["forecasts"]),
                        "non_abstain": int(bucket["non_abstain"]),
                        "settled_trades": int(bucket["settled_trades"]),
                        "activation_rate": round(int(bucket["non_abstain"]) / max(1, int(bucket["forecasts"])), 6),
                        "mean_expected_net_bps": round(bucket["expected_sum"] / max(1, int(bucket["expected_n"])), 6) if bucket["expected_n"] else None,
                        "mean_realized_net_bps": round(bucket["realized_sum"] / max(1, int(bucket["realized_n"])), 6) if bucket["realized_n"] else None,
                        "top_models": [
                            {"model_id": model_id, "non_abstain": count}
                            for model_id, count in sorted(bucket["top_models"].items(), key=lambda item: (-item[1], item[0]))[:3]
                        ],
                    }
                    for (hypothesis, regime_hint, cohort_bucket, symbol_class), bucket in slice_stats.items()
                ],
                key=lambda item: (
                    float(item.get("mean_realized_net_bps") if item.get("mean_realized_net_bps") is not None else -10**9),
                    int(item.get("settled_trades") or 0),
                    float(item.get("mean_expected_net_bps") if item.get("mean_expected_net_bps") is not None else -10**9),
                ),
                reverse=True,
            )[:24]
            regime_model_stats: Dict[tuple[str, str], Dict[str, Any]] = {}
            for raw_payload in payload_rows:
                try:
                    payload = json.loads(raw_payload or "{}")
                except Exception:
                    payload = {}
                if not isinstance(payload, dict):
                    continue
                inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
                regime_hint = str(inputs.get("regime_hint") or ((inputs.get("regime_inputs") or {}).get("regime_hint")) or "unknown")
                model_id = str(payload.get("model_id") or "unknown")
                key = (model_id, regime_hint)
                bucket = regime_model_stats.setdefault(key, {
                    "model_id": model_id,
                    "hypothesis": str(payload.get("hypothesis") or "unknown"),
                    "regime_hint": regime_hint,
                    "forecasts": 0,
                    "non_abstain": 0,
                    "settled_trades": 0,
                    "expected_sum": 0.0,
                    "expected_n": 0,
                    "realized_sum": 0.0,
                    "realized_n": 0,
                    "symbols": set(),
                })
                bucket["forecasts"] += 1
                symbol = payload.get("symbol")
                if symbol:
                    bucket["symbols"].add(str(symbol))
                if not payload.get("abstain"):
                    bucket["non_abstain"] += 1
                    exp = payload.get("expected_net_bps")
                    if exp is not None:
                        bucket["expected_sum"] += float(exp)
                        bucket["expected_n"] += 1
            for raw_payload, net_return_bps in outcome_rows:
                try:
                    payload = json.loads(raw_payload or "{}")
                except Exception:
                    payload = {}
                if not isinstance(payload, dict) or payload.get("abstain"):
                    continue
                inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
                regime_hint = str(inputs.get("regime_hint") or ((inputs.get("regime_inputs") or {}).get("regime_hint")) or "unknown")
                model_id = str(payload.get("model_id") or "unknown")
                key = (model_id, regime_hint)
                bucket = regime_model_stats.setdefault(key, {
                    "model_id": model_id,
                    "hypothesis": str(payload.get("hypothesis") or "unknown"),
                    "regime_hint": regime_hint,
                    "forecasts": 0,
                    "non_abstain": 0,
                    "settled_trades": 0,
                    "expected_sum": 0.0,
                    "expected_n": 0,
                    "realized_sum": 0.0,
                    "realized_n": 0,
                    "symbols": set(),
                })
                bucket["settled_trades"] += 1
                if net_return_bps is not None:
                    bucket["realized_sum"] += float(net_return_bps)
                    bucket["realized_n"] += 1
            result["regime_model_breakdown"] = sorted(
                [
                    {
                        "model_id": bucket["model_id"],
                        "hypothesis": bucket["hypothesis"],
                        "regime_hint": bucket["regime_hint"],
                        "forecasts": int(bucket["forecasts"]),
                        "non_abstain": int(bucket["non_abstain"]),
                        "settled_trades": int(bucket["settled_trades"]),
                        "activation_rate": round(int(bucket["non_abstain"]) / max(1, int(bucket["forecasts"])), 6),
                        "mean_expected_net_bps": round(bucket["expected_sum"] / max(1, int(bucket["expected_n"])), 6) if bucket["expected_n"] else None,
                        "mean_realized_net_bps": round(bucket["realized_sum"] / max(1, int(bucket["realized_n"])), 6) if bucket["realized_n"] else None,
                        "symbol_count": len(bucket["symbols"]),
                    }
                    for bucket in regime_model_stats.values()
                ],
                key=lambda item: (
                    float(item.get("mean_realized_net_bps") if item.get("mean_realized_net_bps") is not None else -10**9),
                    int(item.get("settled_trades") or 0),
                    float(item.get("mean_expected_net_bps") if item.get("mean_expected_net_bps") is not None else -10**9),
                    int(item.get("non_abstain") or 0),
                ),
                reverse=True,
            )[:40]
            frontier = []
            for row in result["regime_model_breakdown"]:
                if int(row.get("settled_trades") or 0) < 5:
                    continue
                realized = row.get("mean_realized_net_bps")
                expected = row.get("mean_expected_net_bps")
                if realized is None or expected is None:
                    continue
                if float(realized) <= 0:
                    continue
                frontier.append({
                    **row,
                    "expectation_realization_gap_bps": round(float(realized) - float(expected), 6),
                    "promotion_hint": (
                        "credible_positive_slice"
                        if int(row.get("settled_trades") or 0) >= 12 and float(realized) >= 5.0
                        else "promising_but_small_sample"
                    ),
                })
            result["profitability_frontier"] = frontier[:12]
            reason_counts: Dict[str, int] = {}
            recovery_candidates: list[Dict[str, Any]] = []
            for raw_payload in payload_rows:
                try:
                    payload = json.loads(raw_payload or "{}")
                except Exception:
                    payload = {}
                if not isinstance(payload, dict) or not payload.get("abstain"):
                    continue
                reasons = payload.get("reasons")
                if isinstance(reasons, (list, tuple)):
                    reason_list = [str(item) for item in reasons if item]
                else:
                    primary_reason = payload.get("reason")
                    reason_list = [str(primary_reason)] if primary_reason else []
                for reason in reason_list:
                    reason_counts[reason] = reason_counts.get(reason, 0) + 1
                inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
                near_miss = inputs.get("near_miss") if isinstance(inputs.get("near_miss"), dict) else {}
                near_miss_score = float(near_miss.get("score") or 0.0)
                tradability = inputs.get("tradability") if isinstance(inputs.get("tradability"), dict) else {}
                tradability_score = float(tradability.get("tradability_score") or 0.0)
                if near_miss_score < 0.72 or tradability_score < 0.45:
                    continue
                recovery_candidates.append({
                    "forecast_id": payload.get("forecast_id"),
                    "symbol": payload.get("symbol"),
                    "model_id": payload.get("model_id"),
                    "hypothesis": payload.get("hypothesis"),
                    "cohort_bucket": inputs.get("cohort_bucket") or "unknown",
                    "reason": reason_list[0] if reason_list else "abstain",
                    "reasons": reason_list[:4],
                    "near_miss_score": round(near_miss_score, 6),
                    "tradability_score": round(tradability_score, 6),
                    "regime_hint": inputs.get("regime_hint") or ((inputs.get("regime_inputs") or {}).get("regime_hint")),
                    "closest_passes": near_miss.get("closest_passes") if isinstance(near_miss.get("closest_passes"), list) else [],
                    "largest_gaps": near_miss.get("largest_gaps") if isinstance(near_miss.get("largest_gaps"), list) else [],
                    "expected_cost_bps": payload.get("expected_cost_bps"),
                    "raw_score": payload.get("raw_score"),
                })
            result["abstention_reason_breakdown"] = [
                {"reason": reason, "count": count}
                for reason, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))[:12]
            ]
            recovery_candidates.sort(
                key=lambda item: (
                    float(item.get("near_miss_score") or 0.0),
                    float(item.get("tradability_score") or 0.0),
                    -len(item.get("largest_gaps") or []),
                ),
                reverse=True,
            )
            result["near_miss_recovery_candidates"] = recovery_candidates[:12]
            demotions: list[Dict[str, Any]] = []
            for row in models:
                if row.get("is_baseline"):
                    continue
                settled_trades = int(row.get("settled_trades") or 0)
                activation_rate = float(row.get("activation_rate") or 0.0)
                mean_net = row.get("mean_net_bps")
                if settled_trades < 25 or mean_net is None:
                    continue
                reasons: list[str] = []
                if float(mean_net) <= -20.0:
                    reasons.append("mean_net_bps_below_minus_20")
                if activation_rate >= 0.10 and float(mean_net) < 0.0:
                    reasons.append("active_but_negative")
                if row.get("diagnostic_label") in {"active_but_unprofitable", "active_but_expectancy_failing"}:
                    reasons.append(str(row.get("diagnostic_label")))
                if reasons:
                    demotions.append({
                        "model_id": row.get("model_id"),
                        "model_role": row.get("model_role"),
                        "model_family": row.get("model_family"),
                        "settled_trades": settled_trades,
                        "activation_rate": round(activation_rate, 6),
                        "mean_expected_net_bps": row.get("mean_expected_net_bps"),
                        "mean_net_bps": row.get("mean_net_bps"),
                        "cost_drag_bps": row.get("cost_drag_bps"),
                        "reasons": reasons,
                    })
            result["demotion_recommendations"] = sorted(
                demotions,
                key=lambda item: (
                    float(item.get("mean_net_bps") if item.get("mean_net_bps") is not None else 10**9),
                    -int(item.get("settled_trades") or 0),
                ),
            )
            return result
        except Exception:
            logging.exception("Error computing hypothesis scorecard")
            result["error"] = "scorecard_failed"
            return result

    def get_phase2_readiness(
        self,
        *,
        min_forecasts: int = 300,
        min_settled_non_abstain: int = 100,
        min_distinct_days: int = 14,
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "phase": 2,
            "ready_for_phase3_review": False,
            "execution_eligible": False,
            "orders_submitted": 0,
            "reasons": [],
        }
        if not self.conn:
            result["reasons"] = ["data_store_unavailable"]
            return result
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    SELECT COUNT(*),
                           SUM(CASE WHEN settled=1 AND abstain=0 THEN 1 ELSE 0 END),
                           COUNT(DISTINCT date(ts, 'unixepoch')),
                           SUM(CASE WHEN execution_eligible<>0 THEN 1 ELSE 0 END)
                    FROM hypothesis_forecasts
                    """
                )
                forecasts, settled_non_abstain, days, execution_violations = c.fetchone() or (0, 0, 0, 0)
                c.execute("SELECT COALESCE(SUM(orders_submitted),0), COALESCE(SUM(execution_wired),0) FROM hypothesis_runs")
                orders, execution_wired = c.fetchone() or (0, 0)
            reasons = []
            if int(forecasts or 0) < int(min_forecasts):
                reasons.append("insufficient_forecasts")
            if int(settled_non_abstain or 0) < int(min_settled_non_abstain):
                reasons.append("insufficient_settled_non_abstain_forecasts")
            if int(days or 0) < int(min_distinct_days):
                reasons.append("insufficient_distinct_research_days")
            if int(execution_violations or 0) or int(execution_wired or 0):
                reasons.append("execution_wiring_violation")
            if int(orders or 0):
                reasons.append("nonzero_orders_submitted")
            scorecard = self.get_hypothesis_scorecard()
            primary = [m for m in scorecard.get("models", []) if not m.get("is_baseline") and int(m.get("settled_trades") or 0) > 0]
            baselines = [m for m in scorecard.get("models", []) if m.get("is_baseline") and int(m.get("settled_trades") or 0) > 0]
            best_primary = max((float(m.get("mean_net_bps") or -1e18) for m in primary), default=None)
            best_baseline = max((float(m.get("mean_net_bps") or -1e18) for m in baselines), default=None)
            if best_primary is None:
                reasons.append("no_settled_primary_model")
            elif best_primary <= 0:
                reasons.append("primary_models_not_positive_after_costs")
            if best_baseline is not None and best_primary is not None and best_primary <= best_baseline:
                reasons.append("primary_models_do_not_beat_baselines")
            result.update({
                "ready_for_phase3_review": not reasons,
                "forecasts": int(forecasts or 0),
                "settled_non_abstain_forecasts": int(settled_non_abstain or 0),
                "distinct_research_days": int(days or 0),
                "execution_wiring_violations": int(execution_violations or 0) + int(execution_wired or 0),
                "orders_submitted": int(orders or 0),
                "scorecard": scorecard,
                "reasons": reasons,
            })
            return result
        except Exception:
            logging.exception("Error computing Phase-2 readiness")
            result["reasons"] = ["readiness_query_failed"]
            return result

    def simulation_exists(self, simulation_id: str) -> bool:
        if not self.conn or not simulation_id:
            return False
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute("SELECT 1 FROM simulated_orders WHERE simulation_id=? LIMIT 1", (simulation_id,))
                return c.fetchone() is not None
        except Exception:
            logging.exception("Error checking simulation idempotency")
            return False

    def persist_simulation_run(self, payload: Dict[str, Any]) -> bool:
        if not self.conn:
            return False
        run = payload.get("run") or {}
        run_id = run.get("run_id")
        if not run_id:
            return False
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT INTO simulation_runs
                    (run_id, started_ts, completed_ts, status, forecasts_examined,
                     simulations_created, simulations_skipped_existing, completed,
                     rejected, expired, partial_fills, unknown_incidents, dataset_hash,
                     execution_wired, real_orders_submitted, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(run_id) DO UPDATE SET
                      completed_ts=excluded.completed_ts,
                      status=excluded.status,
                      forecasts_examined=excluded.forecasts_examined,
                      simulations_created=excluded.simulations_created,
                      simulations_skipped_existing=excluded.simulations_skipped_existing,
                      completed=excluded.completed,
                      rejected=excluded.rejected,
                      expired=excluded.expired,
                      partial_fills=excluded.partial_fills,
                      unknown_incidents=excluded.unknown_incidents,
                      dataset_hash=excluded.dataset_hash,
                      execution_wired=0,
                      real_orders_submitted=0,
                      payload=excluded.payload
                    """,
                    (
                        run_id,
                        float(run.get("started_at_ms") or 0) / 1000.0,
                        float(run.get("completed_at_ms") or 0) / 1000.0,
                        payload.get("status"),
                        int(run.get("forecasts_examined") or 0),
                        int(run.get("simulations_created") or 0),
                        int(run.get("simulations_skipped_existing") or 0),
                        int(run.get("completed") or 0),
                        int(run.get("rejected") or 0),
                        int(run.get("expired") or 0),
                        int(run.get("partial_fills") or 0),
                        int(run.get("unknown_incidents") or 0),
                        payload.get("dataset_hash"), 0, 0, json.dumps(payload),
                    ),
                )
                self.conn.commit()
            return True
        except Exception:
            logging.exception("Error persisting simulation run")
            return False

    def persist_execution_simulation(self, row: Dict[str, Any]) -> bool:
        """Persist a Phase-3 simulation without touching live order tables."""
        if not self.conn:
            return False
        simulation_id = row.get("simulation_id")
        intent = row.get("intent") or {}
        if not simulation_id or not intent.get("intent_id"):
            return False
        if row.get("execution_wired") or int(row.get("real_orders_submitted") or 0):
            raise ValueError("Phase-3 simulation attempted to claim live execution")
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT OR IGNORE INTO simulated_order_intents
                    (intent_id, simulation_id, forecast_id, model_id, venue, symbol, side,
                     order_policy, scenario, quantity, notional_usd, reference_price,
                     limit_price, risk_budget_usd, stop_distance_bps, horizon_seconds,
                     created_ts, spot_executable, live_eligible, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        intent.get("intent_id"), simulation_id, row.get("forecast_id"),
                        row.get("model_id"), row.get("venue"), row.get("symbol"), intent.get("side"),
                        row.get("order_policy"), row.get("scenario"), intent.get("quantity"),
                        intent.get("notional_usd"), intent.get("reference_price"), intent.get("limit_price"),
                        intent.get("risk_budget_usd"), intent.get("stop_distance_bps"),
                        intent.get("horizon_seconds"), intent.get("created_ts"),
                        1 if intent.get("spot_executable") else 0, 0, json.dumps(intent),
                    ),
                )
                c.execute(
                    """
                    INSERT OR IGNORE INTO simulated_orders
                    (simulation_id, run_id, forecast_id, model_id, hypothesis, venue, symbol,
                     direction, order_policy, scenario, fidelity, seed, status, terminal_state,
                     started_ts, completed_ts, fill_ratio, quantity_requested, quantity_filled,
                     notional_requested_usd, entry_reference_price, exit_reference_price,
                     entry_fill_price, exit_fill_price, gross_return_bps, net_return_bps,
                     profitable_after_costs, spot_executable, execution_wired,
                     real_orders_submitted, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        simulation_id, row.get("run_id"), row.get("forecast_id"), row.get("model_id"),
                        row.get("hypothesis"), row.get("venue"), row.get("symbol"), row.get("direction"),
                        row.get("order_policy"), row.get("scenario"), row.get("fidelity"), row.get("seed"),
                        row.get("status"), row.get("terminal_state"), row.get("started_ts"), row.get("completed_ts"),
                        row.get("fill_ratio"), row.get("quantity_requested"), row.get("quantity_filled"),
                        row.get("notional_requested_usd"), row.get("entry_reference_price"), row.get("exit_reference_price"),
                        row.get("entry_fill_price"), row.get("exit_fill_price"), row.get("gross_return_bps"),
                        row.get("net_return_bps"), 1 if row.get("profitable_after_costs") else 0,
                        1 if row.get("spot_executable") else 0, 0, 0, json.dumps(row),
                    ),
                )
                if c.rowcount == 0:
                    self.conn.commit()
                    return True
                for event in row.get("events") or []:
                    c.execute(
                        """
                        INSERT OR IGNORE INTO simulated_order_events
                        (simulation_id, sequence, state, ts, reason, payload)
                        VALUES (?,?,?,?,?,?)
                        """,
                        (simulation_id, int(event.get("sequence") or 0), event.get("state"),
                         event.get("ts"), event.get("reason"), json.dumps(event)),
                    )
                for fill in row.get("fills") or []:
                    c.execute(
                        """
                        INSERT OR IGNORE INTO simulated_fills
                        (fill_id, simulation_id, leg, side, quantity, price, notional_usd,
                         fee_usd, liquidity, ts, payload)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (fill.get("fill_id"), simulation_id, fill.get("leg"), fill.get("side"),
                         fill.get("quantity"), fill.get("price"), fill.get("notional_usd"),
                         fill.get("fee_usd"), fill.get("liquidity"), fill.get("ts"), json.dumps(fill)),
                    )
                costs = row.get("costs") or {}
                c.execute(
                    """
                    INSERT OR REPLACE INTO simulated_cost_attribution
                    (simulation_id, forecast_gross_bps, market_gross_bps, entry_spread_bps,
                     exit_spread_bps, entry_impact_bps, exit_impact_bps, entry_latency_bps,
                     exit_latency_bps, fee_bps, missed_fill_opportunity_bps,
                     stop_slippage_bps, total_cost_bps, net_bps, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (simulation_id, costs.get("forecast_gross_bps"), costs.get("market_gross_bps"),
                     costs.get("entry_spread_bps"), costs.get("exit_spread_bps"), costs.get("entry_impact_bps"),
                     costs.get("exit_impact_bps"), costs.get("entry_latency_bps"), costs.get("exit_latency_bps"),
                     costs.get("fee_bps"), costs.get("missed_fill_opportunity_bps"), costs.get("stop_slippage_bps"),
                     costs.get("total_cost_bps"), costs.get("net_bps"), json.dumps(costs)),
                )
                c.execute(
                    """
                    INSERT OR REPLACE INTO simulated_positions
                    (simulation_id, symbol, direction, quantity, entry_price, exit_price,
                     status, gross_return_bps, net_return_bps, opened_ts, closed_ts, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (simulation_id, row.get("symbol"), row.get("direction"), row.get("quantity_filled"),
                     row.get("entry_fill_price"), row.get("exit_fill_price"), row.get("terminal_state"),
                     row.get("gross_return_bps"), row.get("net_return_bps"), row.get("started_ts"),
                     row.get("completed_ts"), json.dumps({"fidelity": row.get("fidelity")})),
                )
                for index, incident in enumerate(row.get("incidents") or []):
                    incident_id = hashlib.sha256(
                        f"{simulation_id}:{index}:{incident.get('type')}".encode()
                    ).hexdigest()
                    c.execute(
                        """
                        INSERT OR IGNORE INTO simulation_incidents
                        (incident_id, simulation_id, incident_type, severity, symbol_halted,
                         automatic_recovery, payload)
                        VALUES (?,?,?,?,?,?,?)
                        """,
                        (incident_id, simulation_id, incident.get("type"), incident.get("severity"),
                         1 if incident.get("symbol_halted") else 0,
                         1 if incident.get("automatic_recovery") else 0, json.dumps(incident)),
                    )
                self.conn.commit()
            return True
        except Exception:
            try:
                self.conn.rollback()
            except Exception:
                pass
            logging.exception("Error persisting execution simulation")
            return False

    def get_phase3_forecast_candidates(self, limit: int = 100) -> list:
        if not self.conn:
            return []
        try:
            min_expected_net_bps = 0.0
            min_probability = 0.0
            min_historical_realized_net_bps = float("-inf")
            min_historical_samples = 0
            prefer_research_only = False
            max_simulations_per_forecast = 20
            min_regime_historical_realized_net_bps = float("-inf")
            min_regime_historical_samples = 0
            prefer_regime_alignment = True
            min_cost_survival_ratio = 1.0
            unique_per_symbol_cohort = True
            recency_window = 8
            frontier_min_settled_trades = 5
            frontier_min_mean_realized_net_bps = 2.5
            prefer_profitability_frontier = True
            regime_reentry_recent_window = 4
            regime_reentry_min_samples = 3
            regime_reentry_min_mean_realized_net_bps = 2.0
            try:
                if self.coordinator and hasattr(self.coordinator, "cfg"):
                    cfg = self.coordinator.cfg
                    min_expected_net_bps = float(getattr(cfg, "phase3_min_expected_net_bps", 0.0) or 0.0)
                    min_probability = float(getattr(cfg, "phase3_min_probability_positive_net", 0.0) or 0.0)
                    min_historical_realized_net_bps = float(
                        getattr(cfg, "phase3_min_historical_realized_net_bps", float("-inf")) or float("-inf")
                    )
                    min_historical_samples = max(
                        0,
                        int(getattr(cfg, "phase3_min_historical_samples", 0) or 0),
                    )
                    prefer_research_only = bool(getattr(cfg, "phase3_prefer_research_candidates", False))
                    max_simulations_per_forecast = max(
                        1,
                        int(getattr(cfg, "phase3_max_simulations_per_forecast", 20) or 20),
                    )
                    min_regime_historical_realized_net_bps = float(
                        getattr(
                            cfg,
                            "phase3_min_regime_historical_realized_net_bps",
                            min_historical_realized_net_bps,
                        ) or min_historical_realized_net_bps
                    )
                    min_regime_historical_samples = max(
                        0,
                        int(getattr(cfg, "phase3_min_regime_historical_samples", min_historical_samples) or min_historical_samples),
                    )
                    prefer_regime_alignment = bool(getattr(cfg, "phase3_prefer_regime_alignment", True))
                    frontier_min_settled_trades = max(
                        1,
                        int(getattr(cfg, "phase3_frontier_min_settled_trades", 5) or 5),
                    )
                    frontier_min_mean_realized_net_bps = float(
                        getattr(cfg, "phase3_frontier_min_mean_realized_net_bps", 2.5) or 2.5
                    )
                    prefer_profitability_frontier = bool(getattr(cfg, "phase3_prefer_profitability_frontier", True))
                    min_cost_survival_ratio = float(getattr(cfg, "phase3_min_cost_survival_ratio", 1.0) or 1.0)
                    unique_per_symbol_cohort = bool(getattr(cfg, "phase3_unique_per_symbol_cohort", True))
                    recency_window = max(1, int(getattr(cfg, "phase3_recency_window", 8) or 8))
                    regime_reentry_recent_window = max(
                        2,
                        int(getattr(cfg, "phase3_regime_reentry_recent_window", 4) or 4),
                    )
                    regime_reentry_min_samples = max(
                        2,
                        int(getattr(cfg, "phase3_regime_reentry_min_samples", 3) or 3),
                    )
                    regime_reentry_min_mean_realized_net_bps = float(
                        getattr(cfg, "phase3_regime_reentry_min_mean_realized_net_bps", 2.0) or 2.0
                    )
            except Exception:
                pass
            meta = {
                "requested_limit": int(limit or 100),
                "raw_pool_size": 0,
                "selected_count": 0,
                "filters": {
                    "min_expected_net_bps": float(min_expected_net_bps),
                    "min_probability_positive_net": float(min_probability),
                    "min_historical_realized_net_bps": (
                        None if math.isinf(min_historical_realized_net_bps) else float(min_historical_realized_net_bps)
                    ),
                    "min_historical_samples": int(min_historical_samples),
                    "min_regime_historical_realized_net_bps": (
                        None
                        if math.isinf(min_regime_historical_realized_net_bps)
                        else float(min_regime_historical_realized_net_bps)
                    ),
                    "min_regime_historical_samples": int(min_regime_historical_samples),
                    "prefer_research_candidates": bool(prefer_research_only),
                    "prefer_regime_alignment": bool(prefer_regime_alignment),
                    "frontier_min_settled_trades": int(frontier_min_settled_trades),
                    "frontier_min_mean_realized_net_bps": float(frontier_min_mean_realized_net_bps),
                    "prefer_profitability_frontier": bool(prefer_profitability_frontier),
                    "regime_reentry_recent_window": int(regime_reentry_recent_window),
                    "regime_reentry_min_samples": int(regime_reentry_min_samples),
                    "regime_reentry_min_mean_realized_net_bps": float(regime_reentry_min_mean_realized_net_bps),
                    "min_cost_survival_ratio": float(min_cost_survival_ratio),
                    "unique_per_symbol_cohort": bool(unique_per_symbol_cohort),
                    "max_simulations_per_forecast": int(max_simulations_per_forecast),
                    "recency_window": int(recency_window),
                },
                "rejections": {
                    "expected_net_below_gate": 0,
                    "probability_below_gate": 0,
                    "historical_edge_below_gate": 0,
                    "insufficient_history": 0,
                    "regime_edge_below_gate": 0,
                    "insufficient_regime_history": 0,
                    "cost_survival_below_gate": 0,
                },
            }
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    SELECT f.forecast_id, f.ts, f.target_ts, f.venue, f.symbol, f.model_id,
                           f.hypothesis, f.horizon_seconds, f.direction, f.entry_price,
                           f.probability_positive_net, f.expected_move_bps, f.expected_cost_bps,
                           f.expected_net_bps, f.raw_score, f.payload,
                           o.settled_ts, o.exit_price, o.directional_return_bps, o.net_return_bps
                    FROM hypothesis_forecasts f
                    JOIN hypothesis_outcomes o ON o.forecast_id=f.forecast_id
                    WHERE f.settled=1 AND f.abstain=0
                      AND (
                          SELECT COUNT(*) FROM simulated_orders s
                          WHERE s.forecast_id=f.forecast_id
                      ) < ?
                    ORDER BY o.settled_ts DESC LIMIT ?
                    """,
                    (int(max_simulations_per_forecast), max(int(limit or 100) * 8, int(limit or 100))),
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
                meta["raw_pool_size"] = len(rows)
                out = []
                for raw in rows:
                    record = dict(zip(cols, raw))
                    try:
                        record["forecast_payload"] = json.loads(record.pop("payload") or "{}")
                    except Exception:
                        record["forecast_payload"] = {}
                    record["forecast_ts"] = record.pop("ts", None)
                    c.execute(
                        """
                        SELECT payload FROM observation_snapshots
                        WHERE symbol=? AND ts<=? ORDER BY ts DESC LIMIT 1
                        """,
                        (record.get("symbol"), record.get("forecast_ts")),
                    )
                    obs = c.fetchone()
                    try:
                        record["entry_observation"] = json.loads(obs[0]) if obs and obs[0] else {}
                    except Exception:
                        record["entry_observation"] = {}
                    record["regime_hint"] = self._phase3_regime_hint(record)
                    c.execute(
                        """
                        SELECT COUNT(*), AVG(COALESCE(o2.net_return_bps, 0.0))
                        FROM hypothesis_forecasts f2
                        JOIN hypothesis_outcomes o2 ON o2.forecast_id=f2.forecast_id
                        WHERE f2.model_id=?
                          AND f2.symbol=?
                          AND f2.abstain=0
                          AND f2.settled=1
                          AND f2.forecast_id<>?
                          AND f2.ts < ?
                          AND o2.settled_ts <= ?
                        """,
                        (
                            record.get("model_id"),
                            record.get("symbol"),
                            record.get("forecast_id"),
                            record.get("forecast_ts"),
                            record.get("forecast_ts"),
                        ),
                    )
                    history = c.fetchone() or (0, None)
                    record["historical_samples"] = int(history[0] or 0)
                    record["historical_mean_net_bps"] = (
                        float(history[1]) if history[1] is not None else None
                    )
                    c.execute(
                        """
                        SELECT o2.net_return_bps
                        FROM hypothesis_forecasts f2
                        JOIN hypothesis_outcomes o2 ON o2.forecast_id=f2.forecast_id
                        WHERE f2.model_id=?
                          AND f2.symbol=?
                          AND f2.abstain=0
                          AND f2.settled=1
                          AND f2.forecast_id<>?
                          AND f2.ts < ?
                          AND o2.settled_ts <= ?
                        ORDER BY o2.settled_ts DESC
                        LIMIT ?
                        """,
                        (
                            record.get("model_id"),
                            record.get("symbol"),
                            record.get("forecast_id"),
                            record.get("forecast_ts"),
                            record.get("forecast_ts"),
                            int(recency_window),
                        ),
                    )
                    recent_history_samples = [float(item[0] or 0.0) for item in c.fetchall()]
                    record["recent_historical_samples"] = len(recent_history_samples)
                    record["recent_historical_mean_net_bps"] = (
                        sum(recent_history_samples) / len(recent_history_samples) if recent_history_samples else None
                    )
                    target_regime = record.get("regime_hint") or _PHASE3_REGIME_FALLBACK
                    c.execute(
                        """
                        SELECT f2.payload, o2.net_return_bps
                        FROM hypothesis_forecasts f2
                        JOIN hypothesis_outcomes o2 ON o2.forecast_id=f2.forecast_id
                        WHERE f2.model_id=?
                          AND f2.symbol=?
                          AND f2.abstain=0
                          AND f2.settled=1
                          AND f2.forecast_id<>?
                          AND f2.ts < ?
                          AND o2.settled_ts <= ?
                        """,
                        (
                            record.get("model_id"),
                            record.get("symbol"),
                            record.get("forecast_id"),
                            record.get("forecast_ts"),
                            record.get("forecast_ts"),
                        ),
                    )
                    regime_samples = []
                    for payload_raw, net_bps in c.fetchall():
                        sample_regime = self._phase3_regime_hint_from_payload(payload_raw)
                        if sample_regime == target_regime:
                            regime_samples.append(float(net_bps or 0.0))
                    record["regime_historical_samples"] = len(regime_samples)
                    record["regime_historical_mean_net_bps"] = (
                        sum(regime_samples) / len(regime_samples) if regime_samples else None
                    )
                    recent_regime_samples = regime_samples[-int(regime_reentry_recent_window):]
                    record["recent_regime_historical_samples"] = len(recent_regime_samples)
                    record["recent_regime_historical_mean_net_bps"] = (
                        sum(recent_regime_samples) / len(recent_regime_samples) if recent_regime_samples else None
                    )
                    record["regime_reentry_eligible"] = bool(
                        recent_regime_samples
                        and len(recent_regime_samples) >= int(regime_reentry_min_samples)
                        and (sum(recent_regime_samples) / len(recent_regime_samples))
                        >= float(regime_reentry_min_mean_realized_net_bps)
                    )
                    c.execute(
                        """
                        SELECT f2.payload, o2.net_return_bps
                        FROM hypothesis_forecasts f2
                        JOIN hypothesis_outcomes o2 ON o2.forecast_id=f2.forecast_id
                        WHERE f2.model_id=?
                          AND f2.abstain=0
                          AND f2.settled=1
                          AND f2.forecast_id<>?
                          AND f2.ts < ?
                          AND o2.settled_ts <= ?
                        """,
                        (
                            record.get("model_id"),
                            record.get("forecast_id"),
                            record.get("forecast_ts"),
                            record.get("forecast_ts"),
                        ),
                    )
                    frontier_samples = []
                    for payload_raw, net_bps in c.fetchall():
                        sample_regime = self._phase3_regime_hint_from_payload(payload_raw)
                        if sample_regime == target_regime:
                            frontier_samples.append(float(net_bps or 0.0))
                    record["frontier_regime_samples"] = len(frontier_samples)
                    record["frontier_regime_mean_net_bps"] = (
                        sum(frontier_samples) / len(frontier_samples) if frontier_samples else None
                    )
                    record["frontier_eligible"] = bool(
                        frontier_samples
                        and len(frontier_samples) >= int(frontier_min_settled_trades)
                        and (sum(frontier_samples) / len(frontier_samples)) >= float(frontier_min_mean_realized_net_bps)
                    )
                    payload_inputs = (
                        record.get("forecast_payload", {}).get("inputs")
                        if isinstance(record.get("forecast_payload"), dict)
                        else {}
                    )
                    adaptive_policy = payload_inputs.get("adaptive_policy") if isinstance(payload_inputs.get("adaptive_policy"), dict) else {}
                    record["adaptation_active"] = bool(adaptive_policy)
                    record["adaptation_reason"] = str(adaptive_policy.get("adaptation_reason") or "")
                    record["cohort_bucket"] = str(payload_inputs.get("cohort_bucket") or "unknown")
                    record["symbol_class"] = str(payload_inputs.get("symbol_class") or "unknown")
                    c.execute(
                        """
                        SELECT f2.payload, o2.net_return_bps
                        FROM hypothesis_forecasts f2
                        JOIN hypothesis_outcomes o2 ON o2.forecast_id=f2.forecast_id
                        WHERE f2.hypothesis=?
                          AND f2.abstain=0
                          AND f2.settled=1
                          AND f2.forecast_id<>?
                          AND f2.ts < ?
                          AND o2.settled_ts <= ?
                        """,
                        (
                            record.get("hypothesis"),
                            record.get("forecast_id"),
                            record.get("forecast_ts"),
                            record.get("forecast_ts"),
                        ),
                    )
                    slice_samples = []
                    target_cohort = str(record.get("cohort_bucket") or "unknown")
                    target_symbol_class = str(record.get("symbol_class") or "unknown")
                    for payload_raw, net_bps in c.fetchall():
                        payload = {}
                        try:
                            payload = json.loads(payload_raw or "{}")
                        except Exception:
                            payload = {}
                        inputs = payload.get("inputs") if isinstance(payload, dict) else {}
                        if not isinstance(inputs, dict):
                            inputs = {}
                        sample_regime = self._phase3_regime_hint_from_payload(payload_raw)
                        sample_cohort = str(inputs.get("cohort_bucket") or "unknown")
                        sample_symbol_class = str(inputs.get("symbol_class") or "unknown")
                        if (
                            sample_regime == target_regime
                            and sample_cohort == target_cohort
                            and sample_symbol_class == target_symbol_class
                        ):
                            slice_samples.append(float(net_bps or 0.0))
                    record["slice_historical_samples"] = len(slice_samples)
                    record["slice_historical_mean_net_bps"] = (
                        sum(slice_samples) / len(slice_samples) if slice_samples else None
                    )
                    record["recent_slice_historical_samples"] = min(len(slice_samples), int(recency_window))
                    record["recent_slice_historical_mean_net_bps"] = (
                        sum(slice_samples[-int(recency_window):]) / min(len(slice_samples), int(recency_window))
                        if slice_samples else None
                    )
                    expected_move = float(record.get("expected_move_bps") or 0.0)
                    expected_cost = max(0.000001, float(record.get("expected_cost_bps") or 0.0))
                    expected_net = float(record.get("expected_net_bps") or 0.0)
                    record["cost_survival_ratio"] = expected_move / expected_cost if expected_cost > 0 else 0.0
                    record["edge_quality_score"] = (
                        0.34 * expected_net
                        + 0.22 * float(record.get("probability_positive_net") or 0.0) * 100.0
                        + 0.24 * float(record.get("frontier_regime_mean_net_bps") or 0.0)
                        + 0.24 * float(record.get("recent_regime_historical_mean_net_bps") or 0.0)
                        + 0.26 * float(record.get("recent_slice_historical_mean_net_bps") or 0.0)
                        + 0.22 * float(record.get("slice_historical_mean_net_bps") or 0.0)
                        + 0.14 * float(record.get("regime_historical_mean_net_bps") or 0.0)
                        + 0.10 * float(record.get("recent_historical_mean_net_bps") or 0.0)
                        + 0.08 * float(record.get("historical_mean_net_bps") or 0.0)
                        + 0.06 * float(record.get("cost_survival_ratio") or 0.0)
                    )
                    out.append(record)
            filtered = []
            for record in out:
                expected_net = record.get("expected_net_bps")
                probability = record.get("probability_positive_net")
                if expected_net is not None and float(expected_net) < float(min_expected_net_bps):
                    meta["rejections"]["expected_net_below_gate"] += 1
                    continue
                if probability is not None and float(probability) < float(min_probability):
                    meta["rejections"]["probability_below_gate"] += 1
                    continue
                if float(record.get("cost_survival_ratio") or 0.0) < float(min_cost_survival_ratio):
                    meta["rejections"]["cost_survival_below_gate"] += 1
                    continue
                historical_samples = int(record.get("historical_samples") or 0)
                historical_mean = record.get("historical_mean_net_bps")
                if historical_samples < int(min_historical_samples):
                    meta["rejections"]["insufficient_history"] += 1
                    continue
                if historical_mean is not None and historical_mean < float(min_historical_realized_net_bps):
                    meta["rejections"]["historical_edge_below_gate"] += 1
                    continue
                regime_historical_samples = int(record.get("regime_historical_samples") or 0)
                regime_historical_mean = record.get("regime_historical_mean_net_bps")
                recent_regime_historical_samples = int(record.get("recent_regime_historical_samples") or 0)
                recent_regime_historical_mean = record.get("recent_regime_historical_mean_net_bps")
                regime_reentry_eligible = bool(record.get("regime_reentry_eligible"))
                if regime_historical_samples < int(min_regime_historical_samples):
                    meta["rejections"]["insufficient_regime_history"] += 1
                    continue
                if (
                    regime_historical_mean is not None
                    and regime_historical_mean < float(min_regime_historical_realized_net_bps)
                    and not (
                        regime_reentry_eligible
                        and recent_regime_historical_samples >= int(regime_reentry_min_samples)
                        and recent_regime_historical_mean is not None
                        and recent_regime_historical_mean >= float(regime_reentry_min_mean_realized_net_bps)
                    )
                ):
                    meta["rejections"]["regime_edge_below_gate"] += 1
                    continue
                filtered.append(record)
            filtered.sort(
                key=lambda row: (
                    1 if prefer_research_only and not str(row.get("model_id") or "").startswith("baseline_") else 0,
                    1
                    if int(row.get("slice_historical_samples") or 0) > 0
                    and (row.get("slice_historical_mean_net_bps") is not None)
                    else 0,
                    float(row.get("recent_slice_historical_mean_net_bps") or -10**9),
                    int(row.get("recent_slice_historical_samples") or 0),
                    float(row.get("slice_historical_mean_net_bps") or -10**9),
                    int(row.get("slice_historical_samples") or 0),
                    1 if bool(row.get("regime_reentry_eligible")) else 0,
                    float(row.get("recent_regime_historical_mean_net_bps") or -10**9),
                    int(row.get("recent_regime_historical_samples") or 0),
                    1 if prefer_profitability_frontier and bool(row.get("frontier_eligible")) else 0,
                    float(row.get("frontier_regime_mean_net_bps") or -10**9),
                    int(row.get("frontier_regime_samples") or 0),
                    1
                    if prefer_regime_alignment
                    and int(row.get("regime_historical_samples") or 0) > 0
                    and (row.get("regime_historical_mean_net_bps") is not None)
                    else 0,
                    float(row.get("settled_ts") or row.get("forecast_ts") or 0.0),
                    float(row.get("expected_net_bps") or -10**9),
                    float(row.get("cost_survival_ratio") or -10**9),
                    float(row.get("probability_positive_net") or 0.0),
                    float(row.get("edge_quality_score") or -10**9),
                    float(row.get("regime_historical_mean_net_bps") or -10**9),
                    float(row.get("historical_mean_net_bps") or -10**9),
                    float(row.get("net_return_bps") or -10**9),
                ),
                reverse=True,
            )
            if unique_per_symbol_cohort:
                deduped = []
                seen_keys = set()
                for row in filtered:
                    key = (str(row.get("symbol") or ""), str(row.get("cohort_bucket") or "unknown"))
                    if key in seen_keys:
                        continue
                    deduped.append(row)
                    seen_keys.add(key)
                filtered = deduped
            selected = filtered[: int(limit or 100)]
            meta["selected_count"] = len(selected)
            meta["sample"] = [
                {
                    "forecast_id": row.get("forecast_id"),
                    "model_id": row.get("model_id"),
                    "symbol": row.get("symbol"),
                    "cohort_bucket": row.get("cohort_bucket"),
                    "symbol_class": row.get("symbol_class"),
                    "adaptation_active": row.get("adaptation_active"),
                    "adaptation_reason": row.get("adaptation_reason"),
                    "regime_hint": row.get("regime_hint"),
                    "expected_net_bps": row.get("expected_net_bps"),
                    "cost_survival_ratio": row.get("cost_survival_ratio"),
                    "edge_quality_score": row.get("edge_quality_score"),
                    "probability_positive_net": row.get("probability_positive_net"),
                    "frontier_eligible": bool(row.get("frontier_eligible")),
                    "frontier_regime_mean_net_bps": row.get("frontier_regime_mean_net_bps"),
                    "frontier_regime_samples": row.get("frontier_regime_samples"),
                    "recent_slice_historical_mean_net_bps": row.get("recent_slice_historical_mean_net_bps"),
                    "recent_slice_historical_samples": row.get("recent_slice_historical_samples"),
                    "slice_historical_mean_net_bps": row.get("slice_historical_mean_net_bps"),
                    "slice_historical_samples": row.get("slice_historical_samples"),
                    "recent_historical_mean_net_bps": row.get("recent_historical_mean_net_bps"),
                    "recent_historical_samples": row.get("recent_historical_samples"),
                    "historical_mean_net_bps": row.get("historical_mean_net_bps"),
                    "historical_samples": row.get("historical_samples"),
                    "regime_historical_mean_net_bps": row.get("regime_historical_mean_net_bps"),
                    "regime_historical_samples": row.get("regime_historical_samples"),
                    "recent_regime_historical_mean_net_bps": row.get("recent_regime_historical_mean_net_bps"),
                    "recent_regime_historical_samples": row.get("recent_regime_historical_samples"),
                    "regime_reentry_eligible": bool(row.get("regime_reentry_eligible")),
                }
                for row in selected[:5]
            ]
            self._last_phase3_candidate_meta = meta
            return selected
        except Exception:
            logging.exception("Error fetching Phase-3 forecast candidates")
            return []

    def get_phase3_candidate_meta(self) -> Dict[str, Any]:
        return dict(self._last_phase3_candidate_meta or {})

    @staticmethod
    def _phase3_regime_hint_from_payload(payload_raw: Any) -> str:
        payload: Dict[str, Any] = {}
        if isinstance(payload_raw, str):
            try:
                payload = json.loads(payload_raw) or {}
            except Exception:
                payload = {}
        elif isinstance(payload_raw, dict):
            payload = payload_raw
        inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
        regime_inputs = inputs.get("regime_inputs") if isinstance(inputs.get("regime_inputs"), dict) else {}
        regime_hint = inputs.get("regime_hint") or regime_inputs.get("regime_hint")
        return str(regime_hint or _PHASE3_REGIME_FALLBACK)

    @classmethod
    def _phase3_regime_hint(cls, record: Dict[str, Any]) -> str:
        forecast_payload = record.get("forecast_payload") if isinstance(record.get("forecast_payload"), dict) else {}
        hint = cls._phase3_regime_hint_from_payload(forecast_payload)
        if hint != _PHASE3_REGIME_FALLBACK:
            return hint
        entry_observation = record.get("entry_observation") if isinstance(record.get("entry_observation"), dict) else {}
        values = entry_observation.get("values") if isinstance(entry_observation.get("values"), dict) else {}
        regime_inputs = values.get("regime_inputs") if isinstance(values.get("regime_inputs"), dict) else {}
        return str(regime_inputs.get("regime_hint") or _PHASE3_REGIME_FALLBACK)

    def get_simulation_runs(self, limit: int = 50) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    "SELECT * FROM simulation_runs ORDER BY completed_ts DESC LIMIT ?",
                    (int(limit or 50),),
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            logging.exception("Error fetching simulation runs")
            return []

    def get_simulated_orders(
        self,
        model_id: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 250,
    ) -> list:
        if not self.conn:
            return []
        try:
            clauses, params = [], []
            if model_id:
                clauses.append("model_id=?")
                params.append(model_id)
            if symbol:
                clauses.append("symbol=?")
                params.append(symbol)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            params.append(int(limit or 250))
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    f"SELECT * FROM simulated_orders {where} ORDER BY completed_ts DESC LIMIT ?",
                    tuple(params),
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            logging.exception("Error fetching simulated orders")
            return []

    def get_execution_scorecard(self) -> Dict[str, Any]:
        result = {
            "phase": 3,
            "mode": "execution_simulation_only",
            "rows": [],
            "slice_execution_breakdown": [],
            "execution_wired": False,
            "real_orders_submitted": 0,
        }
        if not self.conn:
            result["error"] = "data_store_unavailable"
            return result
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    SELECT o.model_id, o.order_policy, o.scenario,
                           CASE
                               WHEN json_extract(f.payload, '$.inputs.adaptive_policy.adaptation_reason') IS NOT NULL
                               THEN 1 ELSE 0
                           END AS adaptation_active,
                           COALESCE(json_extract(f.payload, '$.inputs.adaptive_policy.adaptation_reason'), '') AS adaptation_reason,
                           COUNT(*) AS simulations,
                           SUM(CASE WHEN o.status='COMPLETED' THEN 1 ELSE 0 END) AS completed,
                           SUM(CASE WHEN o.status='REJECTED' THEN 1 ELSE 0 END) AS rejected,
                           SUM(CASE WHEN o.status='EXPIRED' THEN 1 ELSE 0 END) AS expired,
                           AVG(CASE WHEN o.status='COMPLETED' THEN o.fill_ratio END) AS mean_fill_ratio,
                           AVG(CASE WHEN o.status='COMPLETED' THEN o.net_return_bps END) AS mean_net_bps,
                           AVG(CASE WHEN o.status='COMPLETED' THEN o.profitable_after_costs END) AS win_rate,
                           AVG(CASE WHEN o.status='COMPLETED' THEN c.total_cost_bps END) AS mean_total_cost_bps,
                           AVG(CASE WHEN o.status='COMPLETED' THEN c.fee_bps END) AS mean_fee_bps,
                           AVG(CASE WHEN o.status='COMPLETED' THEN c.entry_spread_bps+c.exit_spread_bps END) AS mean_spread_bps,
                           AVG(CASE WHEN o.status='COMPLETED' THEN c.entry_impact_bps+c.exit_impact_bps END) AS mean_impact_bps,
                           AVG(CASE WHEN o.status='COMPLETED' THEN c.entry_latency_bps+c.exit_latency_bps END) AS mean_latency_bps,
                           SUM(CASE WHEN o.spot_executable=1 AND o.status='COMPLETED' THEN 1 ELSE 0 END) AS spot_completed
                    FROM simulated_orders o
                    LEFT JOIN hypothesis_forecasts f ON f.forecast_id=o.forecast_id
                    LEFT JOIN simulated_cost_attribution c ON c.simulation_id=o.simulation_id
                    GROUP BY o.model_id, o.order_policy, o.scenario, adaptation_active, adaptation_reason
                    ORDER BY o.model_id, o.order_policy, o.scenario, adaptation_active DESC, adaptation_reason
                    """
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
                c.execute(
                    """
                    SELECT o.model_id, o.hypothesis, o.symbol, o.order_policy, o.scenario,
                           f.payload, o.status, o.fill_ratio, o.net_return_bps,
                           o.profitable_after_costs, c.total_cost_bps
                    FROM simulated_orders o
                    LEFT JOIN hypothesis_forecasts f ON f.forecast_id=o.forecast_id
                    LEFT JOIN simulated_cost_attribution c ON c.simulation_id=o.simulation_id
                    """
                )
                slice_rows = c.fetchall()
                slice_cols = [item[0] for item in c.description]
                c.execute(
                    "SELECT COUNT(*), COALESCE(SUM(symbol_halted),0), "
                    "COALESCE(SUM(automatic_recovery),0) FROM simulation_incidents"
                )
                incident_count, symbol_halts, auto_recoveries = c.fetchone() or (0, 0, 0)
                c.execute(
                    "SELECT COALESCE(SUM(real_orders_submitted),0), "
                    "COALESCE(SUM(execution_wired),0) FROM simulated_orders"
                )
                orders, wired = c.fetchone() or (0, 0)
            score_rows = []
            for raw in rows:
                record = dict(zip(cols, raw))
                record["adaptation_active"] = bool(record.get("adaptation_active"))
                for key in (
                    "mean_fill_ratio", "mean_net_bps", "win_rate",
                    "mean_total_cost_bps", "mean_fee_bps", "mean_spread_bps",
                    "mean_impact_bps", "mean_latency_bps",
                ):
                    if record.get(key) is not None:
                        record[key] = round(float(record[key]), 6)
                score_rows.append(record)
            adaptation_groups: Dict[str, Dict[str, Any]] = {}
            for row in score_rows:
                key = "adapted" if row.get("adaptation_active") else "standard"
                bucket = adaptation_groups.setdefault(key, {
                    "segment": key,
                    "policies": 0,
                    "completed": 0,
                    "profitable_proxy": 0.0,
                    "mean_net_sum": 0.0,
                    "mean_net_n": 0,
                    "adaptation_reasons": {},
                })
                bucket["policies"] += 1
                completed = int(row.get("completed") or 0)
                bucket["completed"] += completed
                bucket["profitable_proxy"] += completed * float(row.get("win_rate") or 0.0)
                if row.get("mean_net_bps") is not None:
                    bucket["mean_net_sum"] += float(row.get("mean_net_bps") or 0.0) * completed
                    bucket["mean_net_n"] += completed
                reason = str(row.get("adaptation_reason") or "")
                if reason:
                    bucket["adaptation_reasons"][reason] = bucket["adaptation_reasons"].get(reason, 0) + completed
            slice_buckets: Dict[tuple[str, str, str, str, str, str], Dict[str, Any]] = {}
            for raw in slice_rows:
                record = dict(zip(slice_cols, raw))
                try:
                    payload = json.loads(record.get("payload") or "{}")
                except Exception:
                    payload = {}
                inputs = payload.get("inputs") if isinstance(payload, dict) else {}
                if not isinstance(inputs, dict):
                    inputs = {}
                regime_inputs = inputs.get("regime_inputs") if isinstance(inputs.get("regime_inputs"), dict) else {}
                regime_hint = str(inputs.get("regime_hint") or regime_inputs.get("regime_hint") or _PHASE3_REGIME_FALLBACK)
                cohort_bucket = str(inputs.get("cohort_bucket") or "unknown")
                symbol_class = str(inputs.get("symbol_class") or "unknown")
                key = (
                    str(record.get("hypothesis") or "unknown"),
                    regime_hint,
                    cohort_bucket,
                    symbol_class,
                    str(record.get("order_policy") or "unknown"),
                    str(record.get("scenario") or "unknown"),
                )
                bucket = slice_buckets.setdefault(key, {
                    "hypothesis": key[0],
                    "regime_hint": key[1],
                    "cohort_bucket": key[2],
                    "symbol_class": key[3],
                    "order_policy": key[4],
                    "scenario": key[5],
                    "simulations": 0,
                    "completed": 0,
                    "profitable_proxy": 0.0,
                    "fill_ratio_sum": 0.0,
                    "fill_ratio_n": 0,
                    "net_sum": 0.0,
                    "net_n": 0,
                    "cost_sum": 0.0,
                    "cost_n": 0,
                    "symbols": {},
                    "models": {},
                })
                bucket["simulations"] += 1
                symbol = str(record.get("symbol") or "unknown")
                model_id = str(record.get("model_id") or "unknown")
                bucket["symbols"][symbol] = bucket["symbols"].get(symbol, 0) + 1
                bucket["models"][model_id] = bucket["models"].get(model_id, 0) + 1
                if record.get("status") == "COMPLETED":
                    bucket["completed"] += 1
                    bucket["profitable_proxy"] += float(record.get("profitable_after_costs") or 0.0)
                    if record.get("fill_ratio") is not None:
                        bucket["fill_ratio_sum"] += float(record.get("fill_ratio") or 0.0)
                        bucket["fill_ratio_n"] += 1
                    if record.get("net_return_bps") is not None:
                        bucket["net_sum"] += float(record.get("net_return_bps") or 0.0)
                        bucket["net_n"] += 1
                    if record.get("total_cost_bps") is not None:
                        bucket["cost_sum"] += float(record.get("total_cost_bps") or 0.0)
                        bucket["cost_n"] += 1
            result.update({
                "rows": score_rows,
                "slice_execution_breakdown": sorted(
                    [
                        {
                            "slice_key": "|".join(key),
                            "hypothesis": bucket["hypothesis"],
                            "regime_hint": bucket["regime_hint"],
                            "cohort_bucket": bucket["cohort_bucket"],
                            "symbol_class": bucket["symbol_class"],
                            "order_policy": bucket["order_policy"],
                            "scenario": bucket["scenario"],
                            "simulations": int(bucket["simulations"]),
                            "completed": int(bucket["completed"]),
                            "profitable_outcomes": int(round(bucket["profitable_proxy"])),
                            "profitable_rate": round(bucket["profitable_proxy"] / max(1, int(bucket["completed"])), 6),
                            "mean_fill_ratio": round(bucket["fill_ratio_sum"] / max(1, int(bucket["fill_ratio_n"])), 6) if bucket["fill_ratio_n"] else None,
                            "mean_net_bps": round(bucket["net_sum"] / max(1, int(bucket["net_n"])), 6) if bucket["net_n"] else None,
                            "mean_total_cost_bps": round(bucket["cost_sum"] / max(1, int(bucket["cost_n"])), 6) if bucket["cost_n"] else None,
                            "symbol_count": len(bucket["symbols"]),
                            "top_symbols": [
                                {"symbol": symbol, "count": count}
                                for symbol, count in sorted(bucket["symbols"].items(), key=lambda item: (-item[1], item[0]))[:3]
                            ],
                            "top_models": [
                                {"model_id": model_id, "count": count}
                                for model_id, count in sorted(bucket["models"].items(), key=lambda item: (-item[1], item[0]))[:3]
                            ],
                        }
                        for key, bucket in slice_buckets.items()
                    ],
                    key=lambda item: (
                        float(item.get("mean_net_bps") if item.get("mean_net_bps") is not None else -10**9),
                        int(item.get("completed") or 0),
                        float(item.get("profitable_rate") or 0.0),
                    ),
                    reverse=True,
                )[:24],
                "adaptation_breakdown": {
                    key: {
                        "segment": bucket["segment"],
                        "policies": int(bucket["policies"]),
                        "completed": int(bucket["completed"]),
                        "profitable_outcomes": int(round(bucket["profitable_proxy"])),
                        "profitable_rate": round(bucket["profitable_proxy"] / max(1, int(bucket["completed"])), 6),
                        "mean_net_bps": round(bucket["mean_net_sum"] / max(1, int(bucket["mean_net_n"])), 6) if bucket["mean_net_n"] else None,
                        "adaptation_reasons": [
                            {"reason": reason, "completed": count}
                            for reason, count in sorted(bucket["adaptation_reasons"].items(), key=lambda item: (-item[1], item[0]))[:6]
                        ],
                    }
                    for key, bucket in adaptation_groups.items()
                },
                "incident_count": int(incident_count or 0),
                "symbol_halts": int(symbol_halts or 0),
                "automatic_recoveries": int(auto_recoveries or 0),
                "execution_wiring_violations": int(wired or 0),
                "real_orders_submitted": int(orders or 0),
            })
            return result
        except Exception:
            logging.exception("Error computing execution scorecard")
            result["error"] = "scorecard_failed"
            return result

    def get_phase3_readiness(
        self,
        min_completed: int = 100,
        max_mean_2x_loss_bps: float = 50.0,
    ) -> Dict[str, Any]:
        result = {
            "phase": 3,
            "ready_for_phase4_review": False,
            "execution_eligible": False,
            "real_orders_submitted": 0,
            "reasons": [],
        }
        if not self.conn:
            result["reasons"] = ["data_store_unavailable"]
            return result
        scorecard = self.get_execution_scorecard()
        rows = scorecard.get("rows") or []
        slice_rows = [
            row for row in (scorecard.get("slice_execution_breakdown") or [])
            if row.get("scenario") == "normal" and int(row.get("completed") or 0) > 0
        ]
        reasons = []
        completed = sum(
            int(row.get("completed") or 0)
            for row in rows
            if row.get("scenario") == "normal"
        )
        if completed < int(min_completed):
            reasons.append("insufficient_completed_normal_simulations")
        normal_primary = [
            row for row in rows
            if row.get("scenario") == "normal"
            and not str(row.get("model_id") or "").startswith("baseline_")
            and int(row.get("completed") or 0) > 0
        ]
        stress_15 = [
            row for row in rows
            if row.get("scenario") == "cost_1_5x"
            and not str(row.get("model_id") or "").startswith("baseline_")
            and int(row.get("completed") or 0) > 0
        ]
        stress_2 = [
            row for row in rows
            if row.get("scenario") == "cost_2x"
            and not str(row.get("model_id") or "").startswith("baseline_")
            and int(row.get("completed") or 0) > 0
        ]
        if not normal_primary or max(
            float(row.get("mean_net_bps") or -1e18) for row in normal_primary
        ) <= 0:
            reasons.append("no_positive_primary_execution_policy_at_normal_cost")
        if not stress_15 or max(
            float(row.get("mean_net_bps") or -1e18) for row in stress_15
        ) <= 0:
            reasons.append("no_positive_primary_execution_policy_at_1_5x_cost")
        if stress_2 and max(
            float(row.get("mean_net_bps") or -1e18) for row in stress_2
        ) < -abs(float(max_mean_2x_loss_bps)):
            reasons.append("catastrophic_primary_result_at_2x_cost")
        if not slice_rows:
            reasons.append("no_slice_level_execution_evidence")
        elif max(float(row.get("mean_net_bps") or -1e18) for row in slice_rows) <= 0:
            reasons.append("no_positive_execution_slice_at_normal_cost")
        if int(scorecard.get("execution_wiring_violations") or 0):
            reasons.append("execution_wiring_violation")
        if int(scorecard.get("real_orders_submitted") or 0):
            reasons.append("nonzero_real_orders_submitted")
        if int(scorecard.get("automatic_recoveries") or 0):
            reasons.append("automatic_recovery_violation")
        result.update({
            "ready_for_phase4_review": not reasons,
            "completed_normal_simulations": completed,
            "scorecard": scorecard,
            "reasons": reasons,
        })
        return result

    def get_phase4_validation_dataset(self, limit: int = 100000) -> list:
        """Return balanced immutable Phase-3 evidence joined to its source forecasts."""
        if not self.conn:
            return []
        try:
            per_candidate_scenario = 400
            try:
                if self.coordinator and hasattr(self.coordinator, "cfg"):
                    cfg = self.coordinator.cfg
                    per_candidate_scenario = max(
                        1,
                        int(getattr(cfg, "phase4_max_rows_per_candidate_scenario", 400) or 400),
                    )
            except Exception:
                pass
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    WITH ranked_completed AS (
                        SELECT simulation_id, forecast_id, model_id, hypothesis,
                               venue, symbol, direction, order_policy, scenario,
                               status, terminal_state, completed_ts, net_return_bps,
                               gross_return_bps, fill_ratio, profitable_after_costs,
                               execution_wired, real_orders_submitted,
                               ROW_NUMBER() OVER (
                                   PARTITION BY model_id, order_policy, scenario
                                   ORDER BY completed_ts DESC
                               ) AS rn
                        FROM simulated_orders
                        WHERE status='COMPLETED'
                    )
                    SELECT o.simulation_id, o.forecast_id, o.model_id, o.hypothesis,
                           o.venue, o.symbol, o.direction, o.order_policy, o.scenario,
                           o.status, o.terminal_state, o.completed_ts, o.net_return_bps,
                           o.gross_return_bps, o.fill_ratio, o.profitable_after_costs,
                           o.execution_wired, o.real_orders_submitted,
                           f.ts AS forecast_ts, f.target_ts, f.horizon_seconds,
                           f.probability_positive_net, f.expected_move_bps,
                           f.expected_cost_bps, f.expected_net_bps, f.raw_score,
                           f.payload AS forecast_payload,
                           ca.total_cost_bps, ca.fee_bps, ca.entry_spread_bps,
                           ca.exit_spread_bps, ca.entry_impact_bps, ca.exit_impact_bps,
                           ca.entry_latency_bps, ca.exit_latency_bps
                    FROM ranked_completed o
                    JOIN hypothesis_forecasts f ON f.forecast_id=o.forecast_id
                    LEFT JOIN simulated_cost_attribution ca ON ca.simulation_id=o.simulation_id
                    WHERE o.rn <= ?
                    ORDER BY f.ts ASC, o.model_id, o.order_policy, o.scenario
                    LIMIT ?
                    """,
                    (int(per_candidate_scenario), int(limit or 100000)),
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            out = []
            for raw in rows:
                row = dict(zip(cols, raw))
                try:
                    payload = json.loads(row.pop("forecast_payload") or "{}")
                except Exception:
                    payload = {}
                inputs = payload.get("inputs") if isinstance(payload, dict) else {}
                inputs = inputs if isinstance(inputs, dict) else {}
                row["volatility_expansion"] = inputs.get("volatility_expansion")
                row["return_zscore"] = inputs.get("return_zscore", inputs.get("stretch_zscore"))
                row["volume_zscore"] = inputs.get("volume_zscore")
                row["range_position"] = inputs.get("range_position")
                row["forecast_payload"] = payload
                out.append(row)
            return out
        except Exception:
            logging.exception("Error fetching Phase-4 validation dataset")
            return []

    def persist_phase4_validation_report(self, report: Dict[str, Any]) -> bool:
        if not self.conn or not report.get("run_id"):
            return False
        if report.get("execution_wired") or int(report.get("real_orders_submitted") or 0):
            raise ValueError("Phase-4 report attempted to claim live execution")
        run_id = str(report.get("run_id"))
        readiness = report.get("readiness") or {}
        pbo = report.get("pbo") or {}
        champion = report.get("champion") or {}
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT OR REPLACE INTO phase4_validation_runs
                    (run_id, started_ts, completed_ts, status, validator_version,
                     rows_examined, primary_rows, candidate_count, pbo_estimate,
                     champion_key, ready_for_phase5_review, dataset_hash,
                     execution_wired, real_orders_submitted, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        run_id, report.get("started_ts"), report.get("completed_ts"),
                        report.get("status"), report.get("validator_version"),
                        int(report.get("rows_examined") or 0), int(report.get("primary_rows") or 0),
                        int(report.get("candidate_count") or 0), float(pbo.get("pbo_estimate") or 0.0),
                        champion.get("candidate_key"),
                        1 if readiness.get("ready_for_phase5_review") else 0,
                        report.get("dataset_hash"), 0, 0, json.dumps(report),
                    ),
                )
                for item in report.get("candidate_results") or []:
                    normal = item.get("normal") or {}
                    bootstrap = item.get("bootstrap") or {}
                    dsr = item.get("deflated_sharpe") or {}
                    c.execute(
                        """
                        INSERT OR REPLACE INTO phase4_candidate_results
                        (run_id, candidate_key, model_id, order_policy, normal_samples,
                         mean_net_bps, bootstrap_lower_95_bps, dsr_probability,
                         walk_forward_positive_ratio, parameter_positive_ratio,
                         symbol_holdout_positive_ratio, regime_holdout_positive_ratio,
                         symbol_profit_concentration, month_profit_concentration,
                         robust_score, passes_candidate_gates, payload)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            run_id, item.get("candidate_key"), item.get("model_id"), item.get("order_policy"),
                            int(normal.get("samples") or 0), normal.get("mean_net_bps"),
                            bootstrap.get("lower_95_bps"), dsr.get("dsr_probability"),
                            item.get("walk_forward_positive_ratio"), item.get("parameter_positive_ratio"),
                            item.get("symbol_holdout_positive_ratio"), item.get("regime_holdout_positive_ratio"),
                            item.get("symbol_profit_concentration"), item.get("month_profit_concentration"),
                            item.get("robust_score"), 1 if item.get("passes_candidate_gates") else 0,
                            json.dumps(item),
                        ),
                    )
                for item in report.get("fold_results") or []:
                    test = item.get("test") or {}
                    c.execute(
                        """
                        INSERT OR REPLACE INTO phase4_fold_results
                        (run_id, candidate_key, fold_index, test_start_ts, test_end_ts,
                         test_samples, test_mean_net_bps, test_positive, payload)
                        VALUES (?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            run_id, item.get("candidate_key"), int(item.get("fold_index") or 0),
                            item.get("test_start_ts"), item.get("test_end_ts"),
                            int(test.get("samples") or 0), test.get("mean_net_bps"),
                            1 if item.get("test_positive") else 0, json.dumps(item),
                        ),
                    )
                for item in report.get("holdout_results") or []:
                    test = item.get("test") or {}
                    c.execute(
                        """
                        INSERT OR REPLACE INTO phase4_holdout_results
                        (run_id, candidate_key, holdout_type, holdout_value,
                         test_samples, test_mean_net_bps, test_positive, payload)
                        VALUES (?,?,?,?,?,?,?,?)
                        """,
                        (
                            run_id, item.get("candidate_key"), item.get("holdout_type"),
                            item.get("holdout_value"), int(test.get("samples") or 0),
                            test.get("mean_net_bps"), 1 if item.get("test_positive") else 0,
                            json.dumps(item),
                        ),
                    )
                for item in report.get("perturbation_results") or []:
                    metrics = item.get("metrics") or {}
                    c.execute(
                        """
                        INSERT OR REPLACE INTO phase4_perturbation_results
                        (run_id, candidate_key, probability_gate, expected_net_gate_bps,
                         selected_samples, mean_net_bps, positive, payload)
                        VALUES (?,?,?,?,?,?,?,?)
                        """,
                        (
                            run_id, item.get("candidate_key"), item.get("probability_gate"),
                            item.get("expected_net_gate_bps"), int(item.get("selected_samples") or 0),
                            metrics.get("mean_net_bps"), 1 if item.get("positive") else 0,
                            json.dumps(item),
                        ),
                    )
                self.conn.commit()
            return True
        except Exception:
            try:
                self.conn.rollback()
            except Exception:
                pass
            logging.exception("Error persisting Phase-4 validation report")
            return False

    def get_phase4_validation_runs(self, limit: int = 50) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute("SELECT * FROM phase4_validation_runs ORDER BY completed_ts DESC LIMIT ?", (int(limit or 50),))
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            logging.exception("Error fetching Phase-4 validation runs")
            return []

    def get_phase4_candidate_results(self, run_id: Optional[str] = None, limit: int = 100) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                if not run_id:
                    row = c.execute("SELECT run_id FROM phase4_validation_runs ORDER BY completed_ts DESC LIMIT 1").fetchone()
                    run_id = row[0] if row else None
                if not run_id:
                    return []
                c.execute(
                    "SELECT * FROM phase4_candidate_results WHERE run_id=? ORDER BY robust_score DESC LIMIT ?",
                    (run_id, int(limit or 100)),
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            logging.exception("Error fetching Phase-4 candidate results")
            return []

    def get_phase4_latest_report(self) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                row = self.conn.execute(
                    "SELECT payload FROM phase4_validation_runs ORDER BY completed_ts DESC LIMIT 1"
                ).fetchone()
            return json.loads(row[0]) if row and row[0] else {}
        except Exception:
            return {}

    def get_phase4_readiness(self) -> Dict[str, Any]:
        report = self.get_phase4_latest_report()
        if not report:
            return {
                "phase": 4, "ready_for_phase5_review": False,
                "execution_eligible": False, "human_review_required": True,
                "real_orders_submitted": 0, "reasons": ["no_phase4_validation_report"],
            }
        readiness = dict(report.get("readiness") or {})
        readiness.setdefault("phase", 4)
        readiness["execution_eligible"] = False
        readiness["human_review_required"] = True
        readiness["real_orders_submitted"] = 0
        return readiness

    def persist_phase5_freeze(self, freeze: Dict[str, Any]) -> bool:
        if not self.conn:
            return False
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute("UPDATE phase5_model_freezes SET status='SUPERSEDED' WHERE status='ACTIVE'")
                c.execute(
                    """
                    INSERT OR REPLACE INTO phase5_model_freezes
                    (freeze_id, phase4_run_id, candidate_key, model_id, order_policy,
                     approved_by, approved_ts, phase4_dataset_hash, config_hash, status,
                     shadow_only, execution_eligible, revoked_ts, revoke_reason, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        freeze.get("freeze_id"), freeze.get("phase4_run_id"), freeze.get("candidate_key"),
                        freeze.get("model_id"), freeze.get("order_policy"), freeze.get("approved_by"),
                        freeze.get("approved_ts"), freeze.get("phase4_dataset_hash"), freeze.get("config_hash"),
                        freeze.get("status", "ACTIVE"), 1, 0, None, None, json.dumps(freeze),
                    ),
                )
                self.conn.commit()
            return True
        except Exception:
            logging.exception("Error persisting Phase-5 model freeze")
            return False

    def revoke_phase5_freeze(self, reason: str, revoked_ts: Optional[float] = None) -> bool:
        if not self.conn:
            return False
        try:
            with self._lock:
                self.conn.execute(
                    "UPDATE phase5_model_freezes SET status='REVOKED', revoked_ts=?, revoke_reason=? WHERE status='ACTIVE'",
                    (float(revoked_ts or time.time()), str(reason or "human_revocation")),
                )
                self.conn.commit()
            return True
        except Exception:
            logging.exception("Error revoking Phase-5 model freeze")
            return False

    def get_phase5_active_freeze(self) -> Dict[str, Any]:
        if not self.conn:
            return {}
        try:
            with self._lock:
                c = self.conn.cursor()
                row = c.execute(
                    "SELECT * FROM phase5_model_freezes WHERE status='ACTIVE' ORDER BY approved_ts DESC LIMIT 1"
                ).fetchone()
                if not row:
                    return {}
                cols = [item[0] for item in c.description]
            record = dict(zip(cols, row))
            try:
                payload = json.loads(record.get("payload") or "{}")
                if isinstance(payload, dict):
                    record.update(payload)
            except Exception:
                pass
            record["execution_eligible"] = False
            record["shadow_only"] = True
            return record
        except Exception:
            logging.exception("Error fetching Phase-5 active freeze")
            return {}

    def get_phase5_forecast_candidates(
        self,
        *,
        model_id: str,
        approved_after_ts: float,
        limit: int = 25,
        now_ts: Optional[float] = None,
    ) -> list:
        if not self.conn:
            return []
        try:
            now_ts = float(now_ts if now_ts is not None else time.time())
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    SELECT f.*
                    FROM hypothesis_forecasts f
                    WHERE f.model_id=? AND f.abstain=0 AND f.direction='UP' AND f.ts>=?
                      AND f.settled=0
                      AND f.target_ts>?
                      AND NOT EXISTS (
                          SELECT 1 FROM phase5_shadow_intents s WHERE s.forecast_id=f.forecast_id
                      )
                    ORDER BY f.ts ASC LIMIT ?
                    """,
                    (str(model_id), float(approved_after_ts), now_ts, int(limit or 25)),
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
                out = []
                for raw in rows:
                    record = dict(zip(cols, raw))
                    try:
                        payload = json.loads(record.get("payload") or "{}")
                        if isinstance(payload, dict):
                            record.update(payload)
                    except Exception:
                        pass
                    obs = c.execute(
                        "SELECT * FROM observation_snapshots WHERE symbol=? AND ts<=? ORDER BY ts DESC LIMIT 1",
                        (record.get("symbol"), record.get("ts")),
                    ).fetchone()
                    if obs:
                        obs_cols = [item[0] for item in c.description]
                        observation = dict(zip(obs_cols, obs))
                        try:
                            payload = json.loads(observation.get("payload") or "{}")
                            if isinstance(payload, dict):
                                observation.update(payload)
                        except Exception:
                            pass
                    else:
                        observation = {}
                    record["entry_observation"] = observation
                    record["execution_eligible"] = False
                    out.append(record)
            return out
        except Exception:
            logging.exception("Error fetching Phase-5 forecast candidates")
            return []

    def persist_shadow_intent(self, intent: Dict[str, Any]) -> bool:
        if not self.conn:
            return False
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    INSERT OR IGNORE INTO phase5_shadow_intents
                    (shadow_intent_id, forecast_id, freeze_id, phase4_run_id, candidate_key,
                     model_id, order_policy, venue, symbol, direction, side, order_type,
                     time_in_force, quantity, notional_usd, reference_price, limit_price,
                     stop_distance_bps, risk_budget_usd, predicted_move_bps, predicted_cost_bps,
                     predicted_net_bps, probability_positive_net, horizon_seconds, created_ts,
                     target_ts, data_quality, spread_bps, depth_usd_25bps, venue_profile_version,
                     config_hash, status, transmission_status, private_endpoint_called,
                     credentials_used, transmission_attempted, settled, execution_wired,
                     live_eligible, real_orders_submitted, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        intent.get("shadow_intent_id"), intent.get("forecast_id"), intent.get("freeze_id"),
                        intent.get("phase4_run_id"), intent.get("candidate_key"), intent.get("model_id"),
                        intent.get("order_policy"), intent.get("venue"), intent.get("symbol"),
                        intent.get("direction"), intent.get("side"), intent.get("order_type"),
                        intent.get("time_in_force"), intent.get("quantity"), intent.get("notional_usd"),
                        intent.get("reference_price"), intent.get("limit_price"), intent.get("stop_distance_bps"),
                        intent.get("risk_budget_usd"), intent.get("predicted_move_bps"), intent.get("predicted_cost_bps"),
                        intent.get("predicted_net_bps"), intent.get("probability_positive_net"),
                        int(intent.get("horizon_seconds") or 0), intent.get("created_ts"), intent.get("target_ts"),
                        intent.get("data_quality"), intent.get("spread_bps"), intent.get("depth_usd_25bps"),
                        intent.get("venue_profile_version"), intent.get("config_hash"), "READY_NOT_TRANSMITTED",
                        "NEVER_TRANSMITTED", 0, 0, 0, 0, 0, 0, 0, json.dumps(intent),
                    ),
                )
                created = c.rowcount > 0
                self.conn.commit()
            return created
        except Exception:
            logging.exception("Error persisting Phase-5 shadow intent")
            return False

    def settle_mature_shadow_intents(self, settler: Any, *, now_ts: Optional[float] = None, tolerance_sec: int = 900) -> Dict[str, Any]:
        result = {"phase": 5, "examined": 0, "settled": 0, "missed_fills": 0,
                  "transmission_attempts": 0, "real_orders_submitted": 0}
        if not self.conn:
            result["error"] = "data_store_unavailable"
            return result
        now = float(now_ts or time.time())
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    "SELECT * FROM phase5_shadow_intents WHERE settled=0 AND target_ts<=? ORDER BY target_ts ASC",
                    (now,),
                )
                rows = c.fetchall()
                cols = [item[0] for item in c.description]
                for raw in rows:
                    intent = dict(zip(cols, raw))
                    result["examined"] += 1
                    observations_raw = c.execute(
                        """
                        SELECT * FROM observation_snapshots
                        WHERE symbol=? AND ts>=? AND ts<=?
                        ORDER BY ts ASC
                        """,
                        (intent.get("symbol"), float(intent.get("created_ts") or 0.0),
                         float(intent.get("target_ts") or 0.0) + float(tolerance_sec)),
                    ).fetchall()
                    obs_cols = [item[0] for item in c.description]
                    observations = []
                    for obs_raw in observations_raw:
                        obs = dict(zip(obs_cols, obs_raw))
                        try:
                            payload = json.loads(obs.get("payload") or "{}")
                            if isinstance(payload, dict):
                                obs.update(payload)
                        except Exception:
                            pass
                        observations.append(obs)
                    settlement = settler.settle(intent, observations, settled_ts=now)
                    if settlement is None:
                        continue
                    payload = settlement.to_dict() if hasattr(settlement, "to_dict") else dict(settlement)
                    c.execute(
                        """
                        INSERT OR IGNORE INTO phase5_shadow_settlements
                        (settlement_id, shadow_intent_id, forecast_id, settled_ts, status,
                         fill_model, fill_ratio, intended_entry_price, hypothetical_entry_price,
                         reference_exit_price, hypothetical_exit_price, entry_slippage_bps,
                         exit_slippage_bps, fee_bps, impact_bps, observed_total_cost_bps,
                         predicted_cost_bps, cost_error_bps, gross_directional_return_bps,
                         net_return_bps, profitable_after_costs, data_quality,
                         transmission_attempted, real_orders_submitted, payload)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            payload.get("settlement_id"), payload.get("shadow_intent_id"), payload.get("forecast_id"),
                            payload.get("settled_ts"), payload.get("status"), payload.get("fill_model"),
                            payload.get("fill_ratio"), payload.get("intended_entry_price"),
                            payload.get("hypothetical_entry_price"), payload.get("reference_exit_price"),
                            payload.get("hypothetical_exit_price"), payload.get("entry_slippage_bps"),
                            payload.get("exit_slippage_bps"), payload.get("fee_bps"), payload.get("impact_bps"),
                            payload.get("observed_total_cost_bps"), payload.get("predicted_cost_bps"),
                            payload.get("cost_error_bps"), payload.get("gross_directional_return_bps"),
                            payload.get("net_return_bps"), 1 if payload.get("profitable_after_costs") else 0,
                            payload.get("data_quality"), 0, 0, json.dumps(payload),
                        ),
                    )
                    c.execute(
                        "UPDATE phase5_shadow_intents SET settled=1, status=? WHERE shadow_intent_id=?",
                        (payload.get("status"), intent.get("shadow_intent_id")),
                    )
                    result["settled"] += 1
                    if payload.get("status") == "MISSED_FILL":
                        result["missed_fills"] += 1
                self.conn.commit()
            return result
        except Exception:
            logging.exception("Error settling Phase-5 shadow intents")
            result["error"] = "settlement_failed"
            return result

    def persist_phase5_shadow_run(self, report: Dict[str, Any]) -> bool:
        if not self.conn:
            return False
        try:
            with self._lock:
                readiness = report.get("readiness") or {}
                settlement = report.get("settlement") or {}
                freeze = report.get("freeze") or {}
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO phase5_shadow_runs
                    (run_id, started_ts, completed_ts, status, freeze_id, intents_created,
                     intents_skipped, settlements_created, ready_for_phase6_review, dataset_hash,
                     execution_wired, private_exchange_access, transmission_attempts,
                     real_orders_submitted, payload)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        report.get("run_id"), report.get("started_ts"), report.get("completed_ts"),
                        report.get("status"), freeze.get("freeze_id"), int(report.get("intents_created") or 0),
                        int(report.get("intents_skipped") or 0), int(settlement.get("settled") or 0),
                        1 if readiness.get("ready_for_phase6_review") else 0, report.get("dataset_hash"),
                        0, 0, 0, 0, json.dumps(report),
                    ),
                )
                self.conn.commit()
            return True
        except Exception:
            logging.exception("Error persisting Phase-5 shadow run")
            return False

    def get_phase5_shadow_runs(self, limit: int = 50) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute("SELECT * FROM phase5_shadow_runs ORDER BY completed_ts DESC LIMIT ?", (int(limit or 50),))
                rows = c.fetchall(); cols = [item[0] for item in c.description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            return []

    def get_phase5_shadow_intents(self, limit: int = 250) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute("SELECT * FROM phase5_shadow_intents ORDER BY created_ts DESC LIMIT ?", (int(limit or 250),))
                rows = c.fetchall(); cols = [item[0] for item in c.description]
            out = []
            for row in rows:
                record = dict(zip(cols, row))
                record["execution_wired"] = False
                record["live_eligible"] = False
                record["real_orders_submitted"] = 0
                out.append(record)
            return out
        except Exception:
            return []

    def get_phase5_shadow_settlements(self, limit: int = 250) -> list:
        if not self.conn:
            return []
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute("SELECT * FROM phase5_shadow_settlements ORDER BY settled_ts DESC LIMIT ?", (int(limit or 250),))
                rows = c.fetchall(); cols = [item[0] for item in c.description]
            return [dict(zip(cols, row)) for row in rows]
        except Exception:
            return []

    def get_phase5_scorecard(self) -> Dict[str, Any]:
        result = {"phase": 5, "mode": "public_shadow_only", "execution_eligible": False,
                  "transmission_attempts": 0, "real_orders_submitted": 0}
        if not self.conn:
            result["error"] = "data_store_unavailable"
            return result
        try:
            with self._lock:
                c = self.conn.cursor()
                c.execute(
                    """
                    SELECT COUNT(*) AS settled,
                           SUM(CASE WHEN s.status='SETTLED' THEN 1 ELSE 0 END) AS filled,
                           AVG(s.fill_ratio) AS mean_fill_ratio,
                           AVG(CASE WHEN s.status='SETTLED' THEN s.net_return_bps END) AS mean_net_bps,
                           AVG(CASE WHEN s.status='SETTLED' THEN s.profitable_after_costs END) AS win_rate,
                           AVG(CASE WHEN s.status='SETTLED' THEN s.cost_error_bps END) AS cost_mae_bps,
                           AVG(s.data_quality) AS mean_data_quality,
                           COUNT(DISTINCT date(i.target_ts, 'unixepoch')) AS distinct_days,
                           SUM(s.transmission_attempted) AS transmission_attempts,
                           SUM(s.real_orders_submitted) AS real_orders_submitted
                    FROM phase5_shadow_settlements s
                    JOIN phase5_shadow_intents i ON i.shadow_intent_id=s.shadow_intent_id
                    """
                )
                row = c.fetchone()
                cols = [item[0] for item in c.description]
            metrics = dict(zip(cols, row)) if row else {}
            for key in ("mean_fill_ratio", "mean_net_bps", "win_rate", "cost_mae_bps", "mean_data_quality"):
                if metrics.get(key) is not None:
                    metrics[key] = round(float(metrics[key]), 8)
            result.update(metrics)
            result["transmission_attempts"] = int(result.get("transmission_attempts") or 0)
            result["real_orders_submitted"] = int(result.get("real_orders_submitted") or 0)
            return result
        except Exception:
            logging.exception("Error computing Phase-5 scorecard")
            result["error"] = "scorecard_failed"
            return result

    def get_phase5_readiness(self, *, min_distinct_days: int = 30, min_settled: int = 100,
                             max_cost_mae_bps: float = 20.0, min_fill_ratio: float = 0.50,
                             require_positive_mean: bool = True, current_config_hash: Optional[str] = None) -> Dict[str, Any]:
        score = self.get_phase5_scorecard()
        freeze = self.get_phase5_active_freeze()
        reasons = []
        if not freeze:
            reasons.append("no_active_human_approved_freeze")
        if freeze and current_config_hash and freeze.get("config_hash") != current_config_hash:
            reasons.append("frozen_parameter_drift")
        if int(score.get("settled") or 0) < int(min_settled):
            reasons.append("insufficient_settled_shadow_intents")
        if int(score.get("distinct_days") or 0) < int(min_distinct_days):
            reasons.append("insufficient_distinct_shadow_days")
        if float(score.get("mean_fill_ratio") or 0.0) < float(min_fill_ratio):
            reasons.append("hypothetical_fill_ratio_below_gate")
        if score.get("cost_mae_bps") is None or float(score.get("cost_mae_bps") or 0.0) > float(max_cost_mae_bps):
            reasons.append("cost_model_error_above_gate")
        if require_positive_mean and (score.get("mean_net_bps") is None or float(score.get("mean_net_bps") or 0.0) <= 0.0):
            reasons.append("shadow_mean_net_not_positive")
        if int(score.get("transmission_attempts") or 0) != 0:
            reasons.append("transmission_attempt_detected")
        if int(score.get("real_orders_submitted") or 0) != 0:
            reasons.append("real_order_submission_detected")
        live_order_rows = 0
        try:
            live_order_rows = int(self.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0])
        except Exception:
            live_order_rows = -1
        if live_order_rows != 0:
            reasons.append("live_order_table_not_empty")
        return {
            "phase": 5,
            "ready_for_phase6_review": not reasons,
            "execution_eligible": False,
            "human_review_required": True,
            "automatic_promotion": False,
            "reasons": reasons,
            "scorecard": score,
            "freeze": freeze,
            "live_order_rows": live_order_rows,
            "transmission_attempts": int(score.get("transmission_attempts") or 0),
            "real_orders_submitted": 0,
        }

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
