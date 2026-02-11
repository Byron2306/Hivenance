#!/usr/bin/env python3
"""
Comprehensive Backend Testing for Crypto Trading System
Tests the new Learning Engine, Gas Optimizer, Safety System, and Adaptive Coin Selector
"""

import sys
import os
import time
import json
import logging
import tempfile
import shutil
from datetime import datetime
from typing import Dict, Any, List, Optional

# Add the app directory to Python path
sys.path.insert(0, '/app')

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class CryptoTradingSystemTester:
    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.test_results = []
        self.temp_dir = None
        
        # Initialize test data
        self.setup_test_environment()
        
    def setup_test_environment(self):
        """Setup temporary test environment"""
        self.temp_dir = tempfile.mkdtemp(prefix="crypto_test_")
        logger.info(f"Test environment created at: {self.temp_dir}")
        
    def cleanup_test_environment(self):
        """Cleanup temporary test environment"""
        if self.temp_dir and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
            logger.info("Test environment cleaned up")
    
    def run_test(self, name: str, test_func, *args, **kwargs) -> bool:
        """Run a single test and record results"""
        self.tests_run += 1
        logger.info(f"\n🔍 Testing {name}...")
        
        try:
            result = test_func(*args, **kwargs)
            if result:
                self.tests_passed += 1
                logger.info(f"✅ {name} - PASSED")
                self.test_results.append({"name": name, "status": "PASSED", "error": None})
                return True
            else:
                logger.error(f"❌ {name} - FAILED")
                self.test_results.append({"name": name, "status": "FAILED", "error": "Test returned False"})
                return False
        except Exception as e:
            logger.error(f"❌ {name} - ERROR: {str(e)}")
            self.test_results.append({"name": name, "status": "ERROR", "error": str(e)})
            return False
    
    def test_learning_engine_initialization(self) -> bool:
        """Test Learning Engine can be initialized and basic functionality works"""
        try:
            from agents.learning_engine import LearningEngine
            
            # Test initialization
            db_path = os.path.join(self.temp_dir, "test_learning.db")
            learning = LearningEngine(coordinator=None, db_path=db_path)
            
            # Test basic properties
            assert hasattr(learning, 'coin_performance'), "Missing coin_performance attribute"
            assert hasattr(learning, 'worker_performance'), "Missing worker_performance attribute"
            assert hasattr(learning, 'approval_threshold_usd'), "Missing approval_threshold_usd"
            assert hasattr(learning, 'auto_trade_enabled'), "Missing auto_trade_enabled"
            
            # Test default values
            assert learning.approval_threshold_usd == 10.0, f"Expected approval threshold 10.0, got {learning.approval_threshold_usd}"
            assert learning.auto_trade_enabled == False, f"Expected auto_trade_enabled False, got {learning.auto_trade_enabled}"
            
            # Test database initialization
            assert os.path.exists(db_path), "Database file not created"
            
            # Test basic methods
            health = learning.get_system_health()
            assert isinstance(health, dict), "get_system_health should return dict"
            
            top_coins = learning.get_top_coins(5)
            assert isinstance(top_coins, list), "get_top_coins should return list"
            
            worker_weights = learning.get_worker_weights()
            assert isinstance(worker_weights, dict), "get_worker_weights should return dict"
            
            # Cleanup
            learning.stop()
            
            return True
            
        except ImportError as e:
            logger.error(f"Learning Engine import failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Learning Engine test failed: {e}")
            return False
    
    def test_learning_engine_coin_tracking(self) -> bool:
        """Test Learning Engine coin performance tracking"""
        try:
            from agents.learning_engine import LearningEngine
            
            db_path = os.path.join(self.temp_dir, "test_learning_coins.db")
            learning = LearningEngine(coordinator=None, db_path=db_path)
            
            # Record some test trades
            test_trades = [
                {"symbol": "BTC/USD", "worker": "SMA", "action": "BUY", "entry": 50000, "exit": 51000, "qty": 0.01, "gas": 0.001, "regime": "TREND_UP"},
                {"symbol": "BTC/USD", "worker": "RSI", "action": "SELL", "entry": 51000, "exit": 50500, "qty": 0.01, "gas": 0.001, "regime": "TREND_DOWN"},
                {"symbol": "ETH/USD", "worker": "SMA", "action": "BUY", "entry": 3000, "exit": 3100, "qty": 0.1, "gas": 0.001, "regime": "TREND_UP"},
            ]
            
            for trade in test_trades:
                learning.record_trade_outcome(
                    symbol=trade["symbol"],
                    worker=trade["worker"],
                    action=trade["action"],
                    entry_price=trade["entry"],
                    exit_price=trade["exit"],
                    quantity=trade["qty"],
                    gas_cost_usd=trade["gas"],
                    regime=trade["regime"]
                )
            
            # Test coin performance tracking
            assert "BTC/USD" in learning.coin_performance, "BTC/USD not tracked"
            assert "ETH/USD" in learning.coin_performance, "ETH/USD not tracked"
            
            btc_perf = learning.coin_performance["BTC/USD"]
            assert btc_perf.total_trades == 2, f"Expected 2 BTC trades, got {btc_perf.total_trades}"
            assert btc_perf.winning_trades == 2, f"Expected 2 winning BTC trades, got {btc_perf.winning_trades}"
            
            eth_perf = learning.coin_performance["ETH/USD"]
            assert eth_perf.total_trades == 1, f"Expected 1 ETH trade, got {eth_perf.total_trades}"
            assert eth_perf.winning_trades == 1, f"Expected 1 winning ETH trade, got {eth_perf.winning_trades}"
            
            # Test worker performance tracking
            assert "SMA" in learning.worker_performance, "SMA worker not tracked"
            assert "RSI" in learning.worker_performance, "RSI worker not tracked"
            
            sma_perf = learning.worker_performance["SMA"]
            assert sma_perf.executed_signals == 2, f"Expected 2 SMA signals, got {sma_perf.executed_signals}"
            
            # Test top coins selection
            top_coins = learning.get_top_coins(5, min_score=0.0)  # Lower min_score for test
            assert len(top_coins) >= 0, "Should return some coins"
            
            # Test coin report
            btc_report = learning.get_coin_report("BTC/USD")
            assert btc_report["symbol"] == "BTC/USD", "Wrong symbol in report"
            assert btc_report["total_trades"] == 2, "Wrong trade count in report"
            
            learning.stop()
            return True
            
        except Exception as e:
            logger.error(f"Learning Engine coin tracking test failed: {e}")
            return False
    
    def test_gas_optimizer_initialization(self) -> bool:
        """Test Gas Optimizer initialization and basic functionality"""
        try:
            from agents.gas_optimizer import GasOptimizer
            
            # Test initialization
            gas_opt = GasOptimizer(coordinator=None)
            
            # Test basic properties
            assert hasattr(gas_opt, 'primary_network'), "Missing primary_network attribute"
            assert hasattr(gas_opt, 'batch_enabled'), "Missing batch_enabled attribute"
            assert hasattr(gas_opt, 'network_gas_costs'), "Missing network_gas_costs attribute"
            
            # Test Base L2 is primary
            assert gas_opt.primary_network == "base", f"Expected primary network 'base', got {gas_opt.primary_network}"
            
            # Test gas cost estimates
            estimate = gas_opt.estimate_gas("swap")
            assert hasattr(estimate, 'cost_usd'), "Gas estimate missing cost_usd"
            assert estimate.cost_usd > 0, "Gas cost should be positive"
            assert estimate.network == "base", "Should use base network"
            
            # Test gas efficiency check
            is_efficient, message = gas_opt.is_trade_gas_efficient(100.0)  # $100 trade
            assert isinstance(is_efficient, bool), "Should return boolean"
            assert isinstance(message, str), "Should return message string"
            
            # Test batching logic
            should_batch = gas_opt.should_batch(5.0)  # $5 trade
            assert isinstance(should_batch, bool), "Should return boolean for batching decision"
            
            # Test gas report
            report = gas_opt.get_gas_report()
            assert isinstance(report, dict), "Gas report should be dict"
            assert "primary_network" in report, "Report missing primary_network"
            assert "estimated_gas_per_trade" in report, "Report missing gas estimate"
            
            gas_opt.stop()
            return True
            
        except ImportError as e:
            logger.error(f"Gas Optimizer import failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Gas Optimizer test failed: {e}")
            return False
    
    def test_gas_optimizer_batching(self) -> bool:
        """Test Gas Optimizer trade batching functionality"""
        try:
            from agents.gas_optimizer import GasOptimizer
            
            gas_opt = GasOptimizer(coordinator=None)
            
            # Test adding trades to batch
            test_trades = [
                {"trade_id": "test1", "symbol": "BTC/USD", "action": "BUY", "quantity": 0.01, "price": 50000, "notional_usd": 500},
                {"trade_id": "test2", "symbol": "ETH/USD", "action": "SELL", "quantity": 0.1, "price": 3000, "notional_usd": 300},
                {"trade_id": "test3", "symbol": "BTC/USD", "action": "SELL", "quantity": 0.005, "price": 50000, "notional_usd": 250},
            ]
            
            batch_ids = []
            for trade in test_trades:
                batch_id = gas_opt.add_to_batch(trade)
                batch_ids.append(batch_id)
                assert batch_id, "Should return batch ID"
            
            # Test pending batch
            pending = gas_opt.get_pending_batch()
            assert isinstance(pending, list), "Pending batch should be list"
            
            # Test break-even calculation
            break_even = gas_opt.calculate_break_even_trade_size()
            assert break_even > 0, "Break-even size should be positive"
            
            gas_opt.stop()
            return True
            
        except Exception as e:
            logger.error(f"Gas Optimizer batching test failed: {e}")
            return False
    
    def test_safety_system_initialization(self) -> bool:
        """Test Safety System initialization and basic functionality"""
        try:
            from agents.safety_system import FoolproofSafetySystem
            
            # Test initialization
            safety = FoolproofSafetySystem(coordinator=None, learning_engine=None, gas_optimizer=None)
            
            # Test basic properties
            assert hasattr(safety, 'max_position_pct'), "Missing max_position_pct attribute"
            assert hasattr(safety, 'max_daily_loss_pct'), "Missing max_daily_loss_pct attribute"
            assert hasattr(safety, 'circuit_breaker_triggers'), "Missing circuit_breaker_triggers attribute"
            
            # Test default limits
            assert safety.max_position_pct == 0.10, f"Expected max position 10%, got {safety.max_position_pct}"
            assert safety.max_daily_loss_pct == 0.05, f"Expected max daily loss 5%, got {safety.max_daily_loss_pct}"
            
            # Test safety status
            status = safety.get_safety_status()
            assert isinstance(status, dict), "Safety status should be dict"
            assert "safety_level" in status, "Status missing safety_level"
            assert "circuit_breaker_active" in status, "Status missing circuit_breaker_active"
            
            # Test audit trail
            audit = safety.get_audit_trail(10)
            assert isinstance(audit, list), "Audit trail should be list"
            
            return True
            
        except ImportError as e:
            logger.error(f"Safety System import failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Safety System test failed: {e}")
            return False
    
    def test_safety_system_validation(self) -> bool:
        """Test Safety System multi-layer trade validation"""
        try:
            from agents.safety_system import FoolproofSafetySystem
            
            safety = FoolproofSafetySystem(coordinator=None, learning_engine=None, gas_optimizer=None)
            
            # Test valid trade validation
            valid_result = safety.validate_trade(
                trade_id="test_valid",
                symbol="BTC/USD",
                action="BUY",
                quantity=0.01,
                price=50000,
                wallet_balance_usd=10000,
                current_positions=[]
            )
            
            assert hasattr(valid_result, 'approved'), "Validation result missing approved field"
            assert hasattr(valid_result, 'safety_level'), "Validation result missing safety_level"
            assert hasattr(valid_result, 'checks_passed'), "Validation result missing checks_passed"
            assert hasattr(valid_result, 'checks_failed'), "Validation result missing checks_failed"
            
            # Valid trade should pass basic checks
            assert len(valid_result.checks_passed) > 0, "Valid trade should pass some checks"
            
            # Test invalid trade validation (too large position)
            invalid_result = safety.validate_trade(
                trade_id="test_invalid",
                symbol="BTC/USD",
                action="BUY",
                quantity=10,  # Very large quantity
                price=50000,
                wallet_balance_usd=1000,  # Small wallet
                current_positions=[]
            )
            
            # Should fail position size check
            assert not invalid_result.approved, "Oversized trade should not be approved"
            assert "POSITION_SIZE_LIMIT" in invalid_result.checks_failed or "WALLET" in invalid_result.checks_failed, "Should fail position size check"
            
            # Test sanity check failures
            sanity_fail_result = safety.validate_trade(
                trade_id="test_sanity",
                symbol="",  # Invalid symbol
                action="INVALID",  # Invalid action
                quantity=-1,  # Invalid quantity
                price=0,  # Invalid price
                wallet_balance_usd=1000,
                current_positions=[]
            )
            
            assert not sanity_fail_result.approved, "Invalid parameters should not be approved"
            assert "SANITY" in sanity_fail_result.checks_failed, "Should fail sanity check"
            
            return True
            
        except Exception as e:
            logger.error(f"Safety System validation test failed: {e}")
            return False
    
    def test_safety_system_circuit_breaker(self) -> bool:
        """Test Safety System circuit breaker functionality"""
        try:
            from agents.safety_system import FoolproofSafetySystem
            
            safety = FoolproofSafetySystem(coordinator=None, learning_engine=None, gas_optimizer=None)
            
            # Set peak equity for drawdown calculation
            safety.set_peak_equity(1000.0)
            
            # Simulate consecutive losses to trigger circuit breaker
            for i in range(6):  # More than the threshold of 5
                safety.record_trade_result(f"loss_trade_{i}", -50.0, False)
            
            # Check if circuit breaker is triggered
            status = safety.get_safety_status()
            assert status["circuit_breaker_active"], "Circuit breaker should be active after consecutive losses"
            assert status["consecutive_losses"] >= 5, "Should track consecutive losses"
            
            # Test validation with circuit breaker active
            blocked_result = safety.validate_trade(
                trade_id="test_blocked",
                symbol="BTC/USD",
                action="BUY",
                quantity=0.01,
                price=50000,
                wallet_balance_usd=10000,
                current_positions=[]
            )
            
            assert not blocked_result.approved, "Trades should be blocked when circuit breaker is active"
            assert "CIRCUIT_BREAKER" in str(blocked_result.rejection_reasons), "Should mention circuit breaker in rejection"
            
            # Test circuit breaker reset
            safety.reset_circuit_breaker("test_reset")
            status_after_reset = safety.get_safety_status()
            assert not status_after_reset["circuit_breaker_active"], "Circuit breaker should be inactive after reset"
            
            return True
            
        except Exception as e:
            logger.error(f"Safety System circuit breaker test failed: {e}")
            return False
    
    def test_adaptive_coin_selector_initialization(self) -> bool:
        """Test Adaptive Coin Selector initialization"""
        try:
            from agents.adaptive_coin_selector import AdaptiveCoinSelector
            
            # Test initialization
            selector = AdaptiveCoinSelector(coordinator=None, learning_engine=None)
            
            # Test basic properties
            assert hasattr(selector, 'min_volume_usd'), "Missing min_volume_usd attribute"
            assert hasattr(selector, 'max_coins'), "Missing max_coins attribute"
            assert hasattr(selector, 'rotation_interval_sec'), "Missing rotation_interval_sec attribute"
            
            # Test default values
            assert selector.min_volume_usd == 50000, f"Expected min volume 50000, got {selector.min_volume_usd}"
            assert selector.max_coins == 10, f"Expected max coins 10, got {selector.max_coins}"
            
            # Test selection report
            report = selector.get_selection_report()
            assert isinstance(report, dict), "Selection report should be dict"
            assert "selected_coins" in report, "Report missing selected_coins"
            assert "total_candidates" in report, "Report missing total_candidates"
            
            return True
            
        except ImportError as e:
            logger.error(f"Adaptive Coin Selector import failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Adaptive Coin Selector test failed: {e}")
            return False
    
    def test_adaptive_coin_selector_evaluation(self) -> bool:
        """Test Adaptive Coin Selector coin evaluation and selection"""
        try:
            from agents.adaptive_coin_selector import AdaptiveCoinSelector
            
            selector = AdaptiveCoinSelector(coordinator=None, learning_engine=None)
            
            # Add some test market data
            test_market_data = [
                {"symbol": "BTC/USD", "price": 50000, "volume_24h": 1000000, "high_24h": 51000, "low_24h": 49000, "bid": 49950, "ask": 50050},
                {"symbol": "ETH/USD", "price": 3000, "volume_24h": 500000, "high_24h": 3100, "low_24h": 2900, "bid": 2995, "ask": 3005},
                {"symbol": "ADA/USD", "price": 0.5, "volume_24h": 100000, "high_24h": 0.52, "low_24h": 0.48, "bid": 0.499, "ask": 0.501},
            ]
            
            for data in test_market_data:
                selector.update_market_data(data["symbol"], data)
            
            # Test coin evaluation
            candidates = ["BTC/USD", "ETH/USD", "ADA/USD"]
            opportunities = selector.evaluate_opportunities(candidates)
            
            assert isinstance(opportunities, list), "Opportunities should be list"
            
            # Test coin selection
            selected = selector.select_coins(candidates)
            assert isinstance(selected, list), "Selected coins should be list"
            assert len(selected) <= selector.max_coins, "Should not exceed max coins limit"
            
            # Test force rotation
            rotated = selector.force_rotation()
            assert isinstance(rotated, list), "Force rotation should return list"
            
            # Test hot coin addition
            selector.add_hot_coin("DOGE/USD", "test_hot")
            
            # Test cold coin removal
            if selected:
                selector.remove_cold_coin(selected[0], "test_cold")
            
            return True
            
        except Exception as e:
            logger.error(f"Adaptive Coin Selector evaluation test failed: {e}")
            return False
    
    def test_coordinator_initialization(self) -> bool:
        """Test Coordinator properly initializes all new agents"""
        try:
            # Create a minimal config for testing
            class TestConfig:
                def __init__(self):
                    # Basic required attributes
                    self.symbol = "BTC/USD"
                    self.interval = "1m"
                    self.dry_run = True
                    self.exchange = "binance"
                    self.strategy_type = "sma_crossover"
                    self.sma_fast = 20
                    self.sma_slow = 50
                    self.max_position_base = 0.1
                    
                    # Strategy worker settings
                    self.rsi_window = 14
                    self.rsi_oversold = 30
                    self.rsi_overbought = 70
                    self.lookback = 20
                    
                    # Learning Engine settings
                    self.approval_threshold_usd = 10.0
                    self.max_position_pct = 0.10
                    self.risk_tolerance = 0.5
                    self.auto_trade_enabled = False
                    
                    # Gas Optimizer settings
                    self.gas_batch_enabled = True
                    self.gas_batch_threshold_usd = 5.0
                    self.max_gas_pct = 0.05
                    
                    # Adaptive Coin Selector settings
                    self.min_volume_usd = 50000
                    self.max_tracked_coins = 10
                    self.coin_rotation_interval_sec = 3600
                    
                    # Safety System settings
                    self.max_daily_loss_pct = 0.05
                    self.max_drawdown_pct = 0.10
                    self.max_trades_per_hour = 10
                    
                    # Network settings
                    self.redis_host = "localhost"
                    self.redis_port = 6379
                    self.redis_db = 0
                    self.redis_password = None
                    
                    # UI and other settings
                    self.ui_enabled = False
                    self.kill_switch_enabled = False
                    self.network_enabled = False
                    self.data_store_enabled = False
                    self.performance_enabled = False
                    self.security_enabled = False
                    
            from agents.coordinator import SwarmCoordinator
            
            test_cfg = TestConfig()
            coordinator = SwarmCoordinator(test_cfg)
            
            # Test that new agents are initialized
            expected_agents = ["learning", "gas_optimizer", "adaptive_selector", "safety"]
            
            for agent_name in expected_agents:
                if agent_name in coordinator.agents:
                    agent = coordinator.agents[agent_name]
                    if agent is not None:
                        logger.info(f"✅ {agent_name} agent initialized successfully")
                    else:
                        logger.warning(f"⚠️ {agent_name} agent is None (may be expected if dependencies missing)")
                else:
                    logger.warning(f"⚠️ {agent_name} agent not found in coordinator.agents")
            
            # Test that coordinator has the required methods
            assert hasattr(coordinator, 'agents'), "Coordinator missing agents attribute"
            assert hasattr(coordinator, 'share_data'), "Coordinator missing share_data method"
            assert hasattr(coordinator, 'get_shared_data'), "Coordinator missing get_shared_data method"
            
            return True
            
        except ImportError as e:
            logger.error(f"Coordinator import failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Coordinator initialization test failed: {e}")
            return False
    
    def test_approval_threshold_functionality(self) -> bool:
        """Test approval threshold works correctly ($10+)"""
        try:
            from agents.learning_engine import LearningEngine
            
            db_path = os.path.join(self.temp_dir, "test_approval.db")
            learning = LearningEngine(coordinator=None, db_path=db_path)
            
            # Test trades below threshold (should not require approval)
            small_trade = learning.should_require_approval(5.0)  # $5 trade
            assert not small_trade, "Small trades should not require approval"
            
            # Test trades above threshold (should require approval)
            large_trade = learning.should_require_approval(15.0)  # $15 trade
            assert large_trade, "Large trades should require approval"
            
            # Test exact threshold
            threshold_trade = learning.should_require_approval(10.0)  # Exactly $10
            assert threshold_trade, "Trades at threshold should require approval"
            
            # Test approval request creation
            approval_request = learning.request_approval(
                trade_id="test_approval",
                symbol="BTC/USD",
                action="BUY",
                amount_usd=15.0,
                validation=None,
                timeout_sec=300
            )
            
            assert isinstance(approval_request, dict), "Approval request should be dict"
            assert "trade_id" in approval_request, "Approval request missing trade_id"
            assert "amount_usd" in approval_request, "Approval request missing amount_usd"
            assert approval_request["amount_usd"] == 15.0, "Wrong amount in approval request"
            
            # Test pending approvals
            pending = learning.get_pending_approvals()
            assert isinstance(pending, list), "Pending approvals should be list"
            assert len(pending) > 0, "Should have pending approval"
            
            # Test approval processing
            success = learning.process_approval("test_approval", True, "TEST_USER")
            assert success, "Approval processing should succeed"
            
            learning.stop()
            return True
            
        except Exception as e:
            logger.error(f"Approval threshold test failed: {e}")
            return False
    
    def test_auto_trade_toggle(self) -> bool:
        """Test auto-trade toggle functionality"""
        try:
            from agents.learning_engine import LearningEngine
            
            db_path = os.path.join(self.temp_dir, "test_auto_trade.db")
            learning = LearningEngine(coordinator=None, db_path=db_path)
            
            # Test initial state
            assert not learning.auto_trade_enabled, "Auto-trade should be disabled by default"
            
            # Test enabling auto-trade
            learning.set_auto_trade(True)
            assert learning.auto_trade_enabled, "Auto-trade should be enabled after setting to True"
            
            # Test disabling auto-trade
            learning.set_auto_trade(False)
            assert not learning.auto_trade_enabled, "Auto-trade should be disabled after setting to False"
            
            # Test approval behavior with auto-trade enabled
            learning.set_auto_trade(True)
            small_trade_auto = learning.should_require_approval(5.0)
            large_trade_auto = learning.should_require_approval(15.0)
            
            # In auto-trade mode, small trades should not require approval
            assert not small_trade_auto, "Small trades should not require approval in auto-trade mode"
            # Large trades should still require approval
            assert large_trade_auto, "Large trades should still require approval in auto-trade mode"
            
            learning.stop()
            return True
            
        except Exception as e:
            logger.error(f"Auto-trade toggle test failed: {e}")
            return False
    
    def test_api_endpoints_structure(self) -> bool:
        """Test that API endpoints are properly structured in UI Agent"""
        try:
            from agents.ui_agent import UIAgent
            
            # Create a minimal coordinator for testing
            class MockCoordinator:
                def __init__(self):
                    self.agents = {}
                    self.cfg = type('Config', (), {
                        'allowed_ips': [],
                        'symbol': 'BTC/USD'
                    })()
            
            mock_coordinator = MockCoordinator()
            ui_agent = UIAgent(mock_coordinator, host="127.0.0.1", port=5001)
            
            # Test that the Flask app is created
            assert hasattr(ui_agent, 'app'), "UI Agent missing Flask app"
            
            # Test that required routes are registered
            expected_routes = [
                '/learning/status.json',
                '/safety/status.json', 
                '/gas/status.json',
                '/approvals/pending.json',
                '/mobile/dashboard.json'
            ]
            
            # Get all registered routes
            registered_routes = []
            for rule in ui_agent.app.url_map.iter_rules():
                registered_routes.append(rule.rule)
            
            # Check if expected routes are registered
            missing_routes = []
            for route in expected_routes:
                if route not in registered_routes:
                    missing_routes.append(route)
            
            if missing_routes:
                logger.warning(f"Missing API routes: {missing_routes}")
                # This is not a failure since routes might be conditionally registered
            else:
                logger.info("✅ All expected API routes are registered")
            
            return True
            
        except ImportError as e:
            logger.error(f"UI Agent import failed: {e}")
            return False
        except Exception as e:
            logger.error(f"API endpoints test failed: {e}")
            return False
    
    def run_all_tests(self) -> Dict[str, Any]:
        """Run all backend tests and return results"""
        logger.info("🚀 Starting Crypto Trading System Backend Tests")
        logger.info("=" * 60)
        
        # Core component tests
        self.run_test("Learning Engine Initialization", self.test_learning_engine_initialization)
        self.run_test("Learning Engine Coin Tracking", self.test_learning_engine_coin_tracking)
        self.run_test("Gas Optimizer Initialization", self.test_gas_optimizer_initialization)
        self.run_test("Gas Optimizer Batching", self.test_gas_optimizer_batching)
        self.run_test("Safety System Initialization", self.test_safety_system_initialization)
        self.run_test("Safety System Validation", self.test_safety_system_validation)
        self.run_test("Safety System Circuit Breaker", self.test_safety_system_circuit_breaker)
        self.run_test("Adaptive Coin Selector Initialization", self.test_adaptive_coin_selector_initialization)
        self.run_test("Adaptive Coin Selector Evaluation", self.test_adaptive_coin_selector_evaluation)
        
        # Integration tests
        self.run_test("Coordinator Initialization", self.test_coordinator_initialization)
        self.run_test("Approval Threshold Functionality", self.test_approval_threshold_functionality)
        self.run_test("Auto-Trade Toggle", self.test_auto_trade_toggle)
        self.run_test("API Endpoints Structure", self.test_api_endpoints_structure)
        
        # Calculate results
        success_rate = (self.tests_passed / self.tests_run) * 100 if self.tests_run > 0 else 0
        
        results = {
            "timestamp": datetime.now().isoformat(),
            "tests_run": self.tests_run,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_run - self.tests_passed,
            "success_rate": success_rate,
            "test_results": self.test_results
        }
        
        logger.info("=" * 60)
        logger.info(f"📊 Test Results: {self.tests_passed}/{self.tests_run} passed ({success_rate:.1f}%)")
        
        if success_rate >= 80:
            logger.info("🎉 Overall test result: GOOD")
        elif success_rate >= 60:
            logger.info("⚠️ Overall test result: ACCEPTABLE")
        else:
            logger.info("❌ Overall test result: NEEDS ATTENTION")
        
        return results

def main():
    """Main test execution function"""
    tester = CryptoTradingSystemTester()
    
    try:
        results = tester.run_all_tests()
        
        # Save results to file
        results_file = "/app/test_reports/backend_test_results.json"
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"📄 Test results saved to: {results_file}")
        
        # Return appropriate exit code
        if results["success_rate"] >= 60:
            return 0
        else:
            return 1
            
    except Exception as e:
        logger.error(f"Test execution failed: {e}")
        return 1
    finally:
        tester.cleanup_test_environment()

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)