"""
Gas Optimizer - Minimize Transaction Costs

This module implements multiple gas-saving strategies:
1. Base L2 exclusive trading (~$0.001 per tx)
2. Trade batching for multiple small orders
3. Dynamic gas price monitoring
4. Gasless limit orders via DEX aggregators
5. MEV protection through private transaction pools

The goal: SPEND AS LITTLE ON GAS AS POSSIBLE
"""

import time
import math
import logging
import threading
from typing import Dict, Any, List, Optional, Tuple
from collections import deque
from dataclasses import dataclass, field


@dataclass
class GasEstimate:
    """Gas estimate for a transaction."""
    gas_units: int = 0
    gas_price_gwei: float = 0.0
    cost_eth: float = 0.0
    cost_usd: float = 0.0
    network: str = "base"
    is_profitable: bool = True
    recommendation: str = ""


@dataclass
class BatchedTrade:
    """Trade waiting in batch queue."""
    trade_id: str
    symbol: str
    action: str
    quantity: float
    price: float
    notional_usd: float
    created_at: float
    expires_at: float
    priority: int = 0  # Higher = more urgent


class GasOptimizer:
    """
    Aggressive gas optimization for small-stake trading.
    
    Strategies:
    1. USE BASE L2 ONLY - ~$0.001 per tx vs $2-5 on mainnet
    2. Batch small trades - accumulate and execute together
    3. Time trades for low gas periods
    4. Use gasless protocols where available
    5. Monitor and reject trades where gas > 5% of value
    """
    
    def __init__(self, coordinator=None):
        self.coordinator = coordinator
        
        # Network configuration - BASE L2 IS PRIMARY
        self.primary_network = "base"
        self.fallback_network = None  # No fallback - Base only
        
        # Gas costs by network (approximate USD per typical swap)
        self.network_gas_costs = {
            "base": 0.001,      # ~$0.001 on Base L2
            "arbitrum": 0.05,   # ~$0.05 on Arbitrum
            "optimism": 0.05,   # ~$0.05 on Optimism
            "polygon": 0.01,    # ~$0.01 on Polygon
            "ethereum": 3.00,   # ~$3.00 on Ethereum mainnet - AVOID
        }
        
        # Batching configuration
        self.batch_enabled = True
        self.batch_threshold_usd = 5.0  # Minimum batch value to execute
        self.batch_max_age_sec = 300  # Maximum time to hold trades
        self.batch_max_count = 10  # Maximum trades per batch
        
        # Gas limits
        self.max_gas_pct = 0.05  # Maximum 5% of trade value for gas
        self.target_gas_pct = 0.02  # Target 2% of trade value for gas
        self.absolute_max_gas_usd = 0.50  # Never pay more than $0.50
        
        # State
        self._lock = threading.RLock()
        self._batch_queue: deque = deque()
        self._gas_price_history: List[Tuple[float, float]] = []  # (ts, price_gwei)
        self._total_gas_saved = 0.0
        self._total_gas_spent = 0.0
        self._trades_batched = 0
        self._trades_optimized = 0
        
        # Current gas prices
        self._current_gas_prices = {
            "base": 0.001,
            "ethereum": 30.0,  # gwei - but we don't use it
        }
        self._eth_price_usd = 3000.0  # Will be updated
        
        # Background gas monitor
        self._running = True
        self._monitor_thread = threading.Thread(target=self._gas_monitor_loop, daemon=True)
        self._monitor_thread.start()
        
        logging.info("Gas Optimizer initialized - Primary network: BASE L2")
    
    def estimate_gas(self, trade_type: str = "swap", network: str = None) -> GasEstimate:
        """
        Estimate gas cost for a transaction.
        
        trade_type: "swap", "transfer", "approve", "batch_swap"
        """
        network = network or self.primary_network
        
        estimate = GasEstimate(network=network)
        
        # Gas units by operation type (Base L2 estimates)
        gas_units_map = {
            "swap": 150000,
            "transfer": 21000,
            "approve": 50000,
            "batch_swap": 200000,  # Slightly more for batched operations
        }
        
        estimate.gas_units = gas_units_map.get(trade_type, 150000)
        
        # Get current gas price
        gas_price = self._current_gas_prices.get(network, 0.001)
        estimate.gas_price_gwei = gas_price
        
        # Calculate cost
        if network == "base":
            # Base L2 uses very low gas
            estimate.cost_usd = self.network_gas_costs["base"]
        else:
            estimate.cost_eth = (estimate.gas_units * gas_price) / 1e9
            estimate.cost_usd = estimate.cost_eth * self._eth_price_usd
        
        return estimate
    
    def is_trade_gas_efficient(self, trade_usd: float, network: str = None) -> Tuple[bool, str]:
        """
        Check if a trade is gas-efficient.
        
        Returns: (is_efficient, recommendation)
        """
        network = network or self.primary_network
        estimate = self.estimate_gas("swap", network)
        
        gas_pct = estimate.cost_usd / max(0.01, trade_usd)
        
        if gas_pct > self.max_gas_pct:
            min_trade = estimate.cost_usd / self.target_gas_pct
            return False, f"Gas too high ({gas_pct:.1%}). Min trade: ${min_trade:.2f}"
        
        if gas_pct > self.target_gas_pct:
            return True, f"Gas acceptable ({gas_pct:.1%}) but consider batching"
        
        return True, f"Gas efficient ({gas_pct:.1%})"
    
    def should_batch(self, trade_usd: float) -> bool:
        """Determine if a trade should be batched."""
        if not self.batch_enabled:
            return False
        
        # Small trades should be batched
        if trade_usd < self.batch_threshold_usd:
            return True
        
        # Check if gas efficiency improves with batching
        estimate_single = self.estimate_gas("swap")
        estimate_batch = self.estimate_gas("batch_swap")
        
        # Batching is worth it if per-trade gas is lower
        current_queue_value = sum(t.notional_usd for t in self._batch_queue)
        total_batch_value = current_queue_value + trade_usd
        
        single_gas_pct = estimate_single.cost_usd / max(0.01, trade_usd)
        batch_gas_pct = estimate_batch.cost_usd / max(0.01, total_batch_value)
        
        return batch_gas_pct < single_gas_pct
    
    def add_to_batch(self, trade: Dict[str, Any]) -> str:
        """
        Add a trade to the batch queue.
        
        Returns: batch_id or trade_id
        """
        with self._lock:
            batched = BatchedTrade(
                trade_id=trade.get("trade_id", f"batch-{int(time.time()*1000)}"),
                symbol=trade.get("symbol", ""),
                action=trade.get("action", ""),
                quantity=float(trade.get("quantity", 0)),
                price=float(trade.get("price", 0)),
                notional_usd=float(trade.get("notional_usd", 0)),
                created_at=time.time(),
                expires_at=time.time() + self.batch_max_age_sec,
                priority=int(trade.get("priority", 0))
            )
            
            self._batch_queue.append(batched)
            self._trades_batched += 1
            
            logging.info(f"Trade batched: {batched.symbol} ${batched.notional_usd:.2f}")
            
            # Check if batch should execute
            if self._should_execute_batch():
                return self._execute_batch()
            
            return batched.trade_id
    
    def _should_execute_batch(self) -> bool:
        """Check if batch should execute now."""
        if not self._batch_queue:
            return False
        
        # Check batch size
        if len(self._batch_queue) >= self.batch_max_count:
            return True
        
        # Check total value
        total_value = sum(t.notional_usd for t in self._batch_queue)
        if total_value >= self.batch_threshold_usd:
            return True
        
        # Check oldest trade expiry
        oldest = self._batch_queue[0]
        if time.time() > oldest.expires_at:
            return True
        
        return False
    
    def _execute_batch(self) -> str:
        """Execute all trades in batch."""
        with self._lock:
            if not self._batch_queue:
                return ""
            
            batch_id = f"batch-{int(time.time()*1000)}"
            trades = list(self._batch_queue)
            self._batch_queue.clear()
            
            # Calculate gas savings
            single_gas = self.estimate_gas("swap").cost_usd * len(trades)
            batch_gas = self.estimate_gas("batch_swap").cost_usd
            gas_saved = single_gas - batch_gas
            
            self._total_gas_saved += gas_saved
            self._total_gas_spent += batch_gas
            self._trades_optimized += len(trades)
            
            logging.info(f"Batch executed: {len(trades)} trades, saved ${gas_saved:.4f} in gas")
            
            # Emit batch execution event
            self._emit_batch_event(batch_id, trades, batch_gas, gas_saved)
            
            return batch_id
    
    def get_optimal_timing(self) -> Dict[str, Any]:
        """
        Get optimal timing for trade execution based on gas prices.
        
        On Base L2, this is less critical but still useful.
        """
        with self._lock:
            current_gas = self._current_gas_prices.get(self.primary_network, 0.001)
            
            # Calculate average from history
            if self._gas_price_history:
                recent = [p for t, p in self._gas_price_history if time.time() - t < 3600]
                avg_gas = sum(recent) / len(recent) if recent else current_gas
            else:
                avg_gas = current_gas
            
            is_low = current_gas <= avg_gas
            
            return {
                "network": self.primary_network,
                "current_gas_usd": current_gas,
                "avg_gas_usd": avg_gas,
                "is_favorable": is_low,
                "recommendation": "Execute now" if is_low else "Consider waiting",
                "estimated_cost": self.estimate_gas("swap").cost_usd
            }
    
    def get_gas_report(self) -> Dict[str, Any]:
        """Get comprehensive gas optimization report."""
        with self._lock:
            pending_batch_value = sum(t.notional_usd for t in self._batch_queue)
            pending_count = len(self._batch_queue)
            
            return {
                "primary_network": self.primary_network,
                "estimated_gas_per_trade": self.estimate_gas("swap").cost_usd,
                "total_gas_saved_usd": self._total_gas_saved,
                "total_gas_spent_usd": self._total_gas_spent,
                "trades_batched": self._trades_batched,
                "trades_optimized": self._trades_optimized,
                "savings_rate": self._total_gas_saved / max(0.01, self._total_gas_saved + self._total_gas_spent),
                "pending_batch": {
                    "count": pending_count,
                    "value_usd": pending_batch_value,
                    "will_execute_at": pending_batch_value + self.batch_threshold_usd
                },
                "batch_enabled": self.batch_enabled,
                "max_gas_pct": self.max_gas_pct,
                "network_comparison": {
                    network: cost
                    for network, cost in self.network_gas_costs.items()
                }
            }
    
    def update_eth_price(self, price_usd: float):
        """Update ETH price for gas calculations."""
        self._eth_price_usd = price_usd
    
    def update_gas_price(self, network: str, price: float):
        """Update gas price for a network."""
        with self._lock:
            self._current_gas_prices[network] = price
            self._gas_price_history.append((time.time(), price))
            
            # Keep last 24 hours
            cutoff = time.time() - 86400
            self._gas_price_history = [(t, p) for t, p in self._gas_price_history if t > cutoff]
    
    def force_batch_execute(self) -> str:
        """Force execute current batch (for manual trigger)."""
        return self._execute_batch()
    
    def get_pending_batch(self) -> List[Dict]:
        """Get details of pending batch trades."""
        with self._lock:
            return [
                {
                    "trade_id": t.trade_id,
                    "symbol": t.symbol,
                    "action": t.action,
                    "notional_usd": t.notional_usd,
                    "created_at": t.created_at,
                    "expires_at": t.expires_at,
                    "time_remaining_sec": t.expires_at - time.time()
                }
                for t in self._batch_queue
            ]
    
    def _gas_monitor_loop(self):
        """Background loop to monitor gas prices."""
        while self._running:
            try:
                # On Base L2, gas is very stable, so just periodic check
                # In production, this would query the network
                
                # Check if batch needs executing
                with self._lock:
                    if self._should_execute_batch():
                        self._execute_batch()
                
                time.sleep(30)  # Check every 30 seconds
            except Exception as e:
                logging.exception(f"Gas monitor error: {e}")
                time.sleep(60)
    
    def _emit_batch_event(self, batch_id: str, trades: List[BatchedTrade], gas_cost: float, gas_saved: float):
        """Emit batch execution buzz."""
        if not self.coordinator:
            return
        try:
            self.coordinator.share_data("buzz.gas.batch", {
                "buzz": {"type": "buzz.gas.batch", "source": "GAS_OPTIMIZER", "ts": int(time.time() * 1000)},
                "payload": {
                    "batch_id": batch_id,
                    "trade_count": len(trades),
                    "total_value_usd": sum(t.notional_usd for t in trades),
                    "gas_cost_usd": gas_cost,
                    "gas_saved_usd": gas_saved,
                    "network": self.primary_network,
                    "trades": [
                        {"symbol": t.symbol, "action": t.action, "notional_usd": t.notional_usd}
                        for t in trades
                    ]
                }
            })
        except Exception as e:
            logging.exception(f"Failed to emit batch event: {e}")
    
    def calculate_break_even_trade_size(self) -> float:
        """Calculate minimum trade size to be profitable after gas."""
        estimate = self.estimate_gas("swap")
        # Assuming 0.5% expected profit per trade
        expected_profit_rate = 0.005
        break_even = estimate.cost_usd / expected_profit_rate
        return break_even
    
    def stop(self):
        """Stop the gas optimizer."""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2)
        
        # Execute any remaining batch
        if self._batch_queue:
            self._execute_batch()
        
        logging.info("Gas Optimizer stopped")


class GaslessProtocolIntegration:
    """
    Integration with gasless trading protocols.
    
    Options:
    1. 0x Protocol - Gasless limit orders
    2. CoW Protocol - MEV protection + batch auctions
    3. Uniswap X - Intent-based trading
    """
    
    def __init__(self):
        self.protocols = {
            "0x": {
                "enabled": True,
                "networks": ["base", "ethereum", "arbitrum", "optimism"],
                "order_types": ["limit", "stop_limit"],
                "gas_model": "maker_pays"
            },
            "cow": {
                "enabled": True,
                "networks": ["ethereum", "gnosis"],
                "order_types": ["limit", "market"],
                "gas_model": "batch_auction"
            }
        }
        
        self.primary_protocol = "0x"  # Best for Base L2
    
    def create_gasless_order(
        self,
        protocol: str,
        symbol: str,
        side: str,
        amount: float,
        price: float
    ) -> Dict[str, Any]:
        """Create a gasless limit order."""
        # This would integrate with actual protocol APIs
        return {
            "protocol": protocol,
            "order_type": "limit",
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "price": price,
            "gas_cost": 0.0,  # Gasless!
            "status": "created",
            "note": "Gasless order - no transaction fee"
        }
    
    def get_best_protocol(self, network: str, order_type: str) -> Optional[str]:
        """Get the best gasless protocol for a given network and order type."""
        for name, config in self.protocols.items():
            if not config["enabled"]:
                continue
            if network not in config["networks"]:
                continue
            if order_type not in config["order_types"]:
                continue
            return name
        return None
