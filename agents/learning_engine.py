"""
Learning Engine - Adaptive Profit Tracking & Strategy Evolution

This is the brain of the trading system. It:
1. Tracks profit margins per coin with decay-weighted history
2. Scores worker/strategy performance and auto-rebalances weights
3. Learns from market conditions to adapt coin selection
4. Implements multi-layer validation before any trade
5. Manages automatic position limits based on wallet size
6. Provides real-time PnL tracking with auto-stop

The system is designed to LEARN and ADAPT over time.
"""

import time
import math
import json
import os
import threading
import logging
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta


@dataclass
class CoinPerformance:
    """Tracks performance metrics for a single coin."""
    symbol: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_profit_usd: float = 0.0
    total_loss_usd: float = 0.0
    gross_volume_usd: float = 0.0
    avg_profit_per_trade: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0  # gross_profit / gross_loss
    sharpe_estimate: float = 0.0
    volatility_captured: float = 0.0  # % of volatility successfully traded
    best_regime: str = "UNKNOWN"
    worst_regime: str = "UNKNOWN"
    last_trade_ts: float = 0.0
    score: float = 0.0  # Overall attractiveness score
    decay_weight: float = 1.0  # Time decay on old performance
    consecutive_losses: int = 0
    consecutive_wins: int = 0
    gas_cost_total: float = 0.0
    net_profit_after_gas: float = 0.0
    
    def update_score(self):
        """Calculate overall coin attractiveness score."""
        if self.total_trades < 3:
            self.score = 0.0
            return
        
        # Components of score (0-1 each)
        win_component = min(1.0, self.win_rate / 0.6)  # Target 60% win rate
        profit_component = min(1.0, max(0, self.profit_factor - 1.0))  # >1 is profitable
        volume_component = min(1.0, self.gross_volume_usd / 100.0)  # Scale by volume
        recency_component = self.decay_weight
        gas_efficiency = 1.0 - min(1.0, self.gas_cost_total / max(0.01, self.total_profit_usd))
        
        # Weighted combination
        self.score = (
            0.30 * win_component +
            0.25 * profit_component +
            0.15 * volume_component +
            0.15 * recency_component +
            0.15 * gas_efficiency
        )
        
        # Penalty for consecutive losses
        if self.consecutive_losses >= 3:
            self.score *= 0.5
        
        # Bonus for hot streaks
        if self.consecutive_wins >= 3:
            self.score *= 1.2
            self.score = min(1.0, self.score)


@dataclass
class WorkerPerformance:
    """Tracks performance for each strategy worker."""
    name: str
    total_signals: int = 0
    approved_signals: int = 0
    executed_signals: int = 0
    winning_signals: int = 0
    losing_signals: int = 0
    total_profit_usd: float = 0.0
    total_loss_usd: float = 0.0
    avg_signal_strength: float = 0.0
    regime_accuracy: Dict[str, float] = field(default_factory=dict)
    current_weight: float = 1.0
    base_weight: float = 1.0
    last_update_ts: float = 0.0
    consecutive_losses: int = 0
    
    def calculate_adaptive_weight(self) -> float:
        """Calculate adaptive weight based on performance."""
        if self.executed_signals < 5:
            return self.base_weight
        
        win_rate = self.winning_signals / max(1, self.executed_signals)
        profit_factor = self.total_profit_usd / max(0.01, self.total_loss_usd)
        
        # Base weight adjustment
        weight = self.base_weight
        
        # Win rate adjustment
        if win_rate > 0.55:
            weight *= 1.0 + (win_rate - 0.55) * 2
        elif win_rate < 0.45:
            weight *= 0.5 + win_rate
        
        # Profit factor adjustment
        if profit_factor > 1.5:
            weight *= 1.2
        elif profit_factor < 0.8:
            weight *= 0.7
        
        # Consecutive loss penalty
        if self.consecutive_losses >= 3:
            weight *= 0.6
        
        # Clamp weight
        weight = max(0.2, min(2.0, weight))
        self.current_weight = weight
        return weight


@dataclass  
class TradeValidation:
    """Multi-layer validation result for a trade."""
    approved: bool = False
    layers_passed: List[str] = field(default_factory=list)
    layers_failed: List[str] = field(default_factory=list)
    risk_score: float = 0.0
    position_size_limit: float = 0.0
    recommended_size: float = 0.0
    gas_estimate_usd: float = 0.0
    expected_profit_usd: float = 0.0
    expected_net_after_gas: float = 0.0
    approval_reason: str = ""
    rejection_reason: str = ""


class LearningEngine:
    """
    The adaptive learning core of the trading system.
    
    Key responsibilities:
    1. Track and learn from every trade's profit/loss
    2. Score coins by profitability and adapt selection
    3. Score workers/strategies and rebalance weights
    4. Multi-layer validation before trades
    5. Dynamic position sizing based on confidence
    6. Gas optimization and tracking
    """
    
    def __init__(self, coordinator=None, db_path: str = "data/learning.db"):
        self.coordinator = coordinator
        self.db_path = db_path
        
        # Performance tracking
        self.coin_performance: Dict[str, CoinPerformance] = {}
        self.worker_performance: Dict[str, WorkerPerformance] = {}
        
        # Learning parameters
        self.decay_half_life_hours = 72  # Performance decays over 72 hours
        self.min_trades_for_confidence = 5
        self.max_position_pct_of_wallet = 0.10  # Max 10% per trade
        self.min_expected_profit_usd = 0.50  # Minimum expected profit
        self.max_gas_pct_of_trade = 0.05  # Max 5% gas cost
        
        # Approval thresholds
        self.approval_threshold_usd = 10.0  # Above this needs approval
        self.auto_trade_enabled = False
        self.risk_tolerance = 0.5  # 0-1, higher = more aggressive
        
        # State
        self._lock = threading.RLock()
        self._last_learning_update = 0.0
        self._pending_approvals: Dict[str, Dict] = {}
        
        # Initialize storage
        self._init_storage()
        self._load_state()
        
        # Start background learning loop
        self._running = True
        self._learn_thread = threading.Thread(target=self._learning_loop, daemon=True)
        self._learn_thread.start()
        
        logging.info("Learning Engine initialized")
    
    def _init_storage(self):
        """Initialize SQLite storage for learning data."""
        import sqlite3
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Coin performance history
        c.execute("""
        CREATE TABLE IF NOT EXISTS coin_performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            ts REAL,
            total_trades INTEGER,
            winning_trades INTEGER,
            total_profit_usd REAL,
            total_loss_usd REAL,
            gas_cost_total REAL,
            score REAL,
            regime TEXT
        )
        """)
        
        # Worker performance history
        c.execute("""
        CREATE TABLE IF NOT EXISTS worker_performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_name TEXT,
            ts REAL,
            total_signals INTEGER,
            winning_signals INTEGER,
            current_weight REAL,
            regime TEXT
        )
        """)
        
        # Trade outcomes for learning
        c.execute("""
        CREATE TABLE IF NOT EXISTS trade_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            symbol TEXT,
            worker TEXT,
            action TEXT,
            entry_price REAL,
            exit_price REAL,
            quantity REAL,
            profit_usd REAL,
            gas_cost_usd REAL,
            regime TEXT,
            signal_strength REAL,
            validation_score REAL
        )
        """)
        
        # Regime performance tracking
        c.execute("""
        CREATE TABLE IF NOT EXISTS regime_performance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            regime TEXT,
            ts REAL,
            total_trades INTEGER,
            win_rate REAL,
            avg_profit REAL,
            best_worker TEXT,
            best_coin TEXT
        )
        """)
        
        # Approval history
        c.execute("""
        CREATE TABLE IF NOT EXISTS approval_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL,
            trade_id TEXT,
            symbol TEXT,
            action TEXT,
            amount_usd REAL,
            approved INTEGER,
            auto_approved INTEGER,
            reason TEXT
        )
        """)
        
        conn.commit()
        conn.close()
    
    def _load_state(self):
        """Load historical performance state."""
        import sqlite3
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            # Load latest coin performance
            c.execute("""
                SELECT symbol, total_trades, winning_trades, total_profit_usd, 
                       total_loss_usd, gas_cost_total, score, MAX(ts)
                FROM coin_performance 
                GROUP BY symbol
            """)
            for row in c.fetchall():
                symbol = row[0]
                perf = CoinPerformance(symbol=symbol)
                perf.total_trades = row[1] or 0
                perf.winning_trades = row[2] or 0
                perf.total_profit_usd = row[3] or 0.0
                perf.total_loss_usd = row[4] or 0.0
                perf.gas_cost_total = row[5] or 0.0
                perf.score = row[6] or 0.0
                perf.losing_trades = perf.total_trades - perf.winning_trades
                if perf.total_trades > 0:
                    perf.win_rate = perf.winning_trades / perf.total_trades
                    perf.avg_profit_per_trade = (perf.total_profit_usd - perf.total_loss_usd) / perf.total_trades
                self.coin_performance[symbol] = perf
            
            # Load latest worker performance
            c.execute("""
                SELECT worker_name, total_signals, winning_signals, current_weight, MAX(ts)
                FROM worker_performance
                GROUP BY worker_name
            """)
            for row in c.fetchall():
                name = row[0]
                perf = WorkerPerformance(name=name)
                perf.total_signals = row[1] or 0
                perf.winning_signals = row[2] or 0
                perf.current_weight = row[3] or 1.0
                self.worker_performance[name] = perf
            
            conn.close()
            logging.info(f"Loaded {len(self.coin_performance)} coins, {len(self.worker_performance)} workers from history")
        except Exception as e:
            logging.exception(f"Failed to load learning state: {e}")
    
    def _save_state(self):
        """Persist current state to database."""
        import sqlite3
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            ts = time.time()
            
            # Save coin performance
            for symbol, perf in self.coin_performance.items():
                c.execute("""
                    INSERT INTO coin_performance 
                    (symbol, ts, total_trades, winning_trades, total_profit_usd, 
                     total_loss_usd, gas_cost_total, score, regime)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (symbol, ts, perf.total_trades, perf.winning_trades,
                      perf.total_profit_usd, perf.total_loss_usd, 
                      perf.gas_cost_total, perf.score, perf.best_regime))
            
            # Save worker performance
            for name, perf in self.worker_performance.items():
                c.execute("""
                    INSERT INTO worker_performance
                    (worker_name, ts, total_signals, winning_signals, current_weight, regime)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (name, ts, perf.total_signals, perf.winning_signals,
                      perf.current_weight, ""))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logging.exception(f"Failed to save learning state: {e}")
    
    def record_trade_outcome(
        self,
        symbol: str,
        worker: str,
        action: str,
        entry_price: float,
        exit_price: float,
        quantity: float,
        gas_cost_usd: float,
        regime: str = "UNKNOWN",
        signal_strength: float = 0.0
    ):
        """Record a completed trade and update all learning metrics."""
        with self._lock:
            # Calculate profit
            if action.upper() == "BUY":
                profit_usd = (exit_price - entry_price) * quantity - gas_cost_usd
            else:
                profit_usd = (entry_price - exit_price) * quantity - gas_cost_usd
            
            is_win = profit_usd > 0
            
            # Update coin performance
            if symbol not in self.coin_performance:
                self.coin_performance[symbol] = CoinPerformance(symbol=symbol)
            
            coin = self.coin_performance[symbol]
            coin.total_trades += 1
            coin.gross_volume_usd += abs(quantity * entry_price)
            coin.gas_cost_total += gas_cost_usd
            coin.last_trade_ts = time.time()
            
            if is_win:
                coin.winning_trades += 1
                coin.total_profit_usd += profit_usd
                coin.consecutive_wins += 1
                coin.consecutive_losses = 0
            else:
                coin.losing_trades += 1
                coin.total_loss_usd += abs(profit_usd)
                coin.consecutive_losses += 1
                coin.consecutive_wins = 0
            
            coin.win_rate = coin.winning_trades / coin.total_trades
            coin.avg_profit_per_trade = (coin.total_profit_usd - coin.total_loss_usd) / coin.total_trades
            coin.profit_factor = coin.total_profit_usd / max(0.01, coin.total_loss_usd)
            coin.net_profit_after_gas = coin.total_profit_usd - coin.total_loss_usd - coin.gas_cost_total
            coin.update_score()
            
            # Update worker performance
            if worker not in self.worker_performance:
                self.worker_performance[worker] = WorkerPerformance(name=worker)
            
            wp = self.worker_performance[worker]
            wp.executed_signals += 1
            wp.last_update_ts = time.time()
            
            if is_win:
                wp.winning_signals += 1
                wp.total_profit_usd += profit_usd
                wp.consecutive_losses = 0
            else:
                wp.losing_signals += 1
                wp.total_loss_usd += abs(profit_usd)
                wp.consecutive_losses += 1
            
            # Track regime performance for worker
            if regime not in wp.regime_accuracy:
                wp.regime_accuracy[regime] = 0.5
            
            # EMA update for regime accuracy
            alpha = 0.2
            result = 1.0 if is_win else 0.0
            wp.regime_accuracy[regime] = alpha * result + (1 - alpha) * wp.regime_accuracy[regime]
            
            # Recalculate adaptive weight
            wp.calculate_adaptive_weight()
            
            # Store in database
            import sqlite3
            try:
                conn = sqlite3.connect(self.db_path)
                c = conn.cursor()
                c.execute("""
                    INSERT INTO trade_outcomes
                    (ts, symbol, worker, action, entry_price, exit_price, quantity,
                     profit_usd, gas_cost_usd, regime, signal_strength, validation_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (time.time(), symbol, worker, action, entry_price, exit_price,
                      quantity, profit_usd, gas_cost_usd, regime, signal_strength, 0.0))
                conn.commit()
                conn.close()
            except Exception as e:
                logging.exception(f"Failed to store trade outcome: {e}")
            
            # Emit learning update buzz
            self._emit_learning_update(symbol, worker, profit_usd, is_win)
            
            logging.info(f"Trade recorded: {symbol} {action} profit=${profit_usd:.4f} win={is_win}")
    
    def get_top_coins(self, n: int = 5, min_score: float = 0.3) -> List[Tuple[str, float]]:
        """Get top N coins by profitability score."""
        with self._lock:
            # Apply time decay to all scores
            self._apply_time_decay()
            
            # Filter and sort
            eligible = [
                (symbol, perf.score)
                for symbol, perf in self.coin_performance.items()
                if perf.score >= min_score and perf.total_trades >= self.min_trades_for_confidence
            ]
            
            # Sort by score descending
            eligible.sort(key=lambda x: x[1], reverse=True)
            
            return eligible[:n]
    
    def get_worker_weights(self) -> Dict[str, float]:
        """Get current adaptive weights for all workers."""
        with self._lock:
            return {
                name: perf.current_weight
                for name, perf in self.worker_performance.items()
            }
    
    def validate_trade(
        self,
        symbol: str,
        action: str,
        proposed_size_usd: float,
        worker: str,
        signal_strength: float,
        regime: str,
        wallet_balance_usd: float,
        gas_estimate_usd: float
    ) -> TradeValidation:
        """
        Multi-layer validation for a proposed trade.
        
        Layers:
        1. Position size limits (% of wallet)
        2. Gas cost efficiency
        3. Expected profit viability
        4. Worker confidence in regime
        5. Coin historical performance
        6. Risk tolerance alignment
        7. Consecutive loss protection
        """
        result = TradeValidation()
        
        with self._lock:
            # Layer 1: Position size limits
            max_size = wallet_balance_usd * self.max_position_pct_of_wallet
            if proposed_size_usd > max_size:
                result.layers_failed.append("POSITION_SIZE_LIMIT")
                result.position_size_limit = max_size
                result.recommended_size = max_size
            else:
                result.layers_passed.append("POSITION_SIZE_LIMIT")
                result.position_size_limit = max_size
                result.recommended_size = proposed_size_usd
            
            # Layer 2: Gas cost efficiency
            gas_pct = gas_estimate_usd / max(0.01, proposed_size_usd)
            if gas_pct > self.max_gas_pct_of_trade:
                result.layers_failed.append("GAS_EFFICIENCY")
                # Suggest larger trade size to amortize gas
                min_size_for_gas = gas_estimate_usd / self.max_gas_pct_of_trade
                if min_size_for_gas <= max_size:
                    result.recommended_size = max(result.recommended_size, min_size_for_gas)
            else:
                result.layers_passed.append("GAS_EFFICIENCY")
            result.gas_estimate_usd = gas_estimate_usd
            
            # Layer 3: Expected profit viability
            coin_perf = self.coin_performance.get(symbol)
            if coin_perf and coin_perf.total_trades >= self.min_trades_for_confidence:
                expected_profit_rate = coin_perf.avg_profit_per_trade / max(1.0, coin_perf.gross_volume_usd / coin_perf.total_trades)
                result.expected_profit_usd = proposed_size_usd * expected_profit_rate
            else:
                # New coin - use conservative estimate
                result.expected_profit_usd = proposed_size_usd * 0.005  # 0.5% expected
            
            result.expected_net_after_gas = result.expected_profit_usd - gas_estimate_usd
            
            if result.expected_net_after_gas < self.min_expected_profit_usd:
                result.layers_failed.append("EXPECTED_PROFIT_TOO_LOW")
            else:
                result.layers_passed.append("EXPECTED_PROFIT_VIABLE")
            
            # Layer 4: Worker confidence in regime
            worker_perf = self.worker_performance.get(worker)
            if worker_perf:
                regime_accuracy = worker_perf.regime_accuracy.get(regime, 0.5)
                if regime_accuracy < 0.4:
                    result.layers_failed.append("WORKER_REGIME_MISMATCH")
                else:
                    result.layers_passed.append("WORKER_REGIME_OK")
                    
                # Apply worker weight to size
                result.recommended_size *= worker_perf.current_weight
            else:
                result.layers_passed.append("WORKER_NEW_OK")
            
            # Layer 5: Coin historical performance
            if coin_perf:
                if coin_perf.score < 0.2:
                    result.layers_failed.append("COIN_LOW_SCORE")
                elif coin_perf.consecutive_losses >= 5:
                    result.layers_failed.append("COIN_COLD_STREAK")
                else:
                    result.layers_passed.append("COIN_PERFORMANCE_OK")
                    # Boost size for high-performing coins
                    if coin_perf.score > 0.7:
                        result.recommended_size *= 1.2
            else:
                result.layers_passed.append("COIN_NEW_OK")
            
            # Layer 6: Risk tolerance
            risk_score = signal_strength * (0.5 + 0.5 * self.risk_tolerance)
            result.risk_score = risk_score
            
            if risk_score < 0.3:
                result.layers_failed.append("RISK_SCORE_TOO_LOW")
            else:
                result.layers_passed.append("RISK_SCORE_OK")
            
            # Layer 7: Consecutive loss protection
            if worker_perf and worker_perf.consecutive_losses >= 3:
                result.recommended_size *= 0.5
                result.layers_passed.append("LOSS_PROTECTION_APPLIED")
            
            # Final decision
            critical_failures = {"GAS_EFFICIENCY", "EXPECTED_PROFIT_TOO_LOW", "COIN_COLD_STREAK", "RISK_SCORE_TOO_LOW"}
            critical_failed = set(result.layers_failed) & critical_failures
            
            if not critical_failed and len(result.layers_passed) >= 4:
                result.approved = True
                result.approval_reason = f"Passed {len(result.layers_passed)}/{len(result.layers_passed) + len(result.layers_failed)} layers"
            else:
                result.approved = False
                result.rejection_reason = f"Failed critical: {list(critical_failed)}" if critical_failed else f"Insufficient passes: {len(result.layers_passed)}"
            
            # Clamp recommended size
            result.recommended_size = max(0.0, min(result.recommended_size, result.position_size_limit))
            
            return result
    
    def should_require_approval(self, trade_usd: float, validation=None) -> bool:
        """Determine if a trade needs manual approval."""
        if self.auto_trade_enabled:
            # Auto-trade mode: only require approval for large trades
            if trade_usd > self.approval_threshold_usd:
                return True
            # Or if validation had any failures
            if validation:
                # Support both TradeValidation (layers_failed) and TradeValidationResult (checks_failed)
                failures = getattr(validation, 'layers_failed', None) or getattr(validation, 'checks_failed', [])
                if len(failures) > 1:
                    return True
            return False
        else:
            # Manual mode: always require approval above threshold
            return trade_usd > self.approval_threshold_usd
    
    def request_approval(
        self,
        trade_id: str,
        symbol: str,
        action: str,
        amount_usd: float,
        validation=None,
        timeout_sec: int = 300
    ) -> Dict[str, Any]:
        """Request approval for a trade and return approval request details."""
        with self._lock:
            request = {
                "trade_id": trade_id,
                "symbol": symbol,
                "action": action,
                "amount_usd": amount_usd,
                "validation": asdict(validation),
                "requested_at": time.time(),
                "expires_at": time.time() + timeout_sec,
                "status": "PENDING",
                "approved": None,
                "approved_by": None
            }
            self._pending_approvals[trade_id] = request
            
            # Emit approval request buzz
            self._emit_approval_request(request)
            
            return request
    
    def process_approval(self, trade_id: str, approved: bool, approved_by: str = "USER") -> bool:
        """Process an approval decision."""
        with self._lock:
            if trade_id not in self._pending_approvals:
                return False
            
            request = self._pending_approvals[trade_id]
            
            # Check if expired
            if time.time() > request["expires_at"]:
                request["status"] = "EXPIRED"
                return False
            
            request["approved"] = approved
            request["approved_by"] = approved_by
            request["status"] = "APPROVED" if approved else "REJECTED"
            request["processed_at"] = time.time()
            
            # Store in database
            import sqlite3
            try:
                conn = sqlite3.connect(self.db_path)
                c = conn.cursor()
                c.execute("""
                    INSERT INTO approval_history
                    (ts, trade_id, symbol, action, amount_usd, approved, auto_approved, reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (time.time(), trade_id, request["symbol"], request["action"],
                      request["amount_usd"], 1 if approved else 0, 
                      0, request["status"]))
                conn.commit()
                conn.close()
            except Exception as e:
                logging.exception(f"Failed to store approval: {e}")
            
            # Emit approval result buzz
            self._emit_approval_result(request)
            
            return True
    
    def get_pending_approvals(self) -> List[Dict]:
        """Get all pending approval requests."""
        with self._lock:
            now = time.time()
            pending = []
            for trade_id, request in list(self._pending_approvals.items()):
                if request["status"] == "PENDING":
                    if now > request["expires_at"]:
                        request["status"] = "EXPIRED"
                    else:
                        pending.append(request)
            return pending
    
    def set_auto_trade(self, enabled: bool):
        """Enable/disable auto-trade mode."""
        self.auto_trade_enabled = enabled
        logging.info(f"Auto-trade mode: {'ENABLED' if enabled else 'DISABLED'}")
        
        # Emit mode change
        if self.coordinator:
            try:
                self.coordinator.share_data("buzz.learning.mode", {
                    "buzz": {"type": "buzz.learning.mode", "source": "LEARNING", "ts": int(time.time() * 1000)},
                    "payload": {"auto_trade": enabled, "approval_threshold_usd": self.approval_threshold_usd}
                })
            except Exception:
                pass
    
    def set_risk_tolerance(self, level: float):
        """Set risk tolerance (0-1)."""
        self.risk_tolerance = max(0.0, min(1.0, level))
        logging.info(f"Risk tolerance set to: {self.risk_tolerance}")
    
    def _apply_time_decay(self):
        """Apply time decay to all performance scores."""
        now = time.time()
        decay_constant = math.log(2) / (self.decay_half_life_hours * 3600)
        
        for coin in self.coin_performance.values():
            if coin.last_trade_ts > 0:
                age_sec = now - coin.last_trade_ts
                coin.decay_weight = math.exp(-decay_constant * age_sec)
                coin.update_score()
    
    def _learning_loop(self):
        """Background loop for continuous learning updates."""
        while self._running:
            try:
                # Periodic state save
                if time.time() - self._last_learning_update > 300:  # Every 5 minutes
                    self._save_state()
                    self._apply_time_decay()
                    self._last_learning_update = time.time()
                    
                    # Emit learning summary
                    self._emit_learning_summary()
                
                time.sleep(60)
            except Exception as e:
                logging.exception(f"Learning loop error: {e}")
                time.sleep(10)
    
    def _emit_learning_update(self, symbol: str, worker: str, profit: float, is_win: bool):
        """Emit a learning update buzz."""
        if not self.coordinator:
            return
        try:
            coin = self.coin_performance.get(symbol)
            wp = self.worker_performance.get(worker)
            
            self.coordinator.share_data("buzz.learning.update", {
                "buzz": {"type": "buzz.learning.update", "source": "LEARNING", "ts": int(time.time() * 1000)},
                "payload": {
                    "symbol": symbol,
                    "worker": worker,
                    "profit_usd": profit,
                    "is_win": is_win,
                    "coin_score": coin.score if coin else 0.0,
                    "coin_win_rate": coin.win_rate if coin else 0.0,
                    "worker_weight": wp.current_weight if wp else 1.0,
                    "worker_consecutive_losses": wp.consecutive_losses if wp else 0
                }
            })
        except Exception as e:
            logging.exception(f"Failed to emit learning update: {e}")
    
    def _emit_learning_summary(self):
        """Emit periodic learning summary."""
        if not self.coordinator:
            return
        try:
            top_coins = self.get_top_coins(5)
            worker_weights = self.get_worker_weights()
            
            total_profit = sum(c.net_profit_after_gas for c in self.coin_performance.values())
            total_trades = sum(c.total_trades for c in self.coin_performance.values())
            
            self.coordinator.share_data("buzz.learning.summary", {
                "buzz": {"type": "buzz.learning.summary", "source": "LEARNING", "ts": int(time.time() * 1000)},
                "payload": {
                    "top_coins": [{"symbol": s, "score": sc} for s, sc in top_coins],
                    "worker_weights": worker_weights,
                    "total_net_profit_usd": total_profit,
                    "total_trades": total_trades,
                    "auto_trade_enabled": self.auto_trade_enabled,
                    "risk_tolerance": self.risk_tolerance,
                    "pending_approvals": len(self.get_pending_approvals())
                }
            })
        except Exception as e:
            logging.exception(f"Failed to emit learning summary: {e}")
    
    def _emit_approval_request(self, request: Dict):
        """Emit approval request buzz."""
        if not self.coordinator:
            return
        try:
            self.coordinator.share_data("buzz.approval.request", {
                "buzz": {"type": "buzz.approval.request", "source": "LEARNING", "ts": int(time.time() * 1000)},
                "payload": request
            })
        except Exception:
            pass
    
    def _emit_approval_result(self, request: Dict):
        """Emit approval result buzz."""
        if not self.coordinator:
            return
        try:
            self.coordinator.share_data("buzz.approval.result", {
                "buzz": {"type": "buzz.approval.result", "source": "LEARNING", "ts": int(time.time() * 1000)},
                "payload": request
            })
        except Exception:
            pass
    
    def get_coin_report(self, symbol: str) -> Dict[str, Any]:
        """Get detailed performance report for a coin."""
        with self._lock:
            coin = self.coin_performance.get(symbol)
            if not coin:
                return {"error": "No data for coin"}
            
            return {
                "symbol": symbol,
                "total_trades": coin.total_trades,
                "win_rate": coin.win_rate,
                "profit_factor": coin.profit_factor,
                "net_profit_usd": coin.net_profit_after_gas,
                "total_gas_cost": coin.gas_cost_total,
                "score": coin.score,
                "consecutive_wins": coin.consecutive_wins,
                "consecutive_losses": coin.consecutive_losses,
                "best_regime": coin.best_regime,
                "last_trade_ts": coin.last_trade_ts
            }
    
    def get_system_health(self) -> Dict[str, Any]:
        """Get overall system learning health."""
        with self._lock:
            total_coins = len(self.coin_performance)
            profitable_coins = sum(1 for c in self.coin_performance.values() if c.net_profit_after_gas > 0)
            total_workers = len(self.worker_performance)
            
            avg_coin_score = sum(c.score for c in self.coin_performance.values()) / max(1, total_coins)
            avg_worker_weight = sum(w.current_weight for w in self.worker_performance.values()) / max(1, total_workers)
            
            return {
                "total_coins_tracked": total_coins,
                "profitable_coins": profitable_coins,
                "avg_coin_score": avg_coin_score,
                "total_workers": total_workers,
                "avg_worker_weight": avg_worker_weight,
                "auto_trade_enabled": self.auto_trade_enabled,
                "risk_tolerance": self.risk_tolerance,
                "pending_approvals": len(self.get_pending_approvals())
            }
    
    def stop(self):
        """Stop the learning engine."""
        self._running = False
        self._save_state()
        if self._learn_thread:
            self._learn_thread.join(timeout=2)
        logging.info("Learning Engine stopped")
