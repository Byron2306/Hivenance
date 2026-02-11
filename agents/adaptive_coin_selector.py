"""
Adaptive Coin Selector - Profit-First Coin Selection

This module implements intelligent coin selection based on:
1. Historical profit margins (from Learning Engine)
2. Real-time volatility metrics
3. Liquidity depth requirements
4. Gas efficiency considerations
5. Trend/regime alignment
6. Risk-adjusted opportunity scoring

The goal: SELECT COINS THAT MAKE MONEY, not just volatile coins.
"""

import time
import math
import logging
import threading
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class CoinOpportunity:
    """Represents a trading opportunity for a coin."""
    symbol: str
    base_asset: str
    quote_asset: str
    
    # Market metrics
    price: float = 0.0
    volume_24h_usd: float = 0.0
    volatility_24h: float = 0.0  # % price change range
    spread_pct: float = 0.0
    liquidity_depth_usd: float = 0.0
    
    # Profit metrics (from learning engine)
    historical_win_rate: float = 0.5
    historical_profit_factor: float = 1.0
    historical_score: float = 0.0
    avg_trade_profit_pct: float = 0.0
    
    # Efficiency metrics
    estimated_gas_cost_usd: float = 0.0
    min_profitable_trade_usd: float = 0.0  # Min trade size to cover gas
    gas_efficiency_score: float = 0.0
    
    # Regime alignment
    current_regime: str = "UNKNOWN"
    regime_alignment_score: float = 0.5
    
    # Final scores
    opportunity_score: float = 0.0
    risk_adjusted_score: float = 0.0
    final_rank: int = 0


class AdaptiveCoinSelector:
    """
    Intelligent coin selection that learns from profit history.
    
    Philosophy:
    - High volatility is ONLY good if we can capture it profitably
    - Low gas costs are essential for small stakes
    - Historical performance > theoretical opportunity
    - Adapt to regime changes dynamically
    """
    
    def __init__(self, coordinator=None, learning_engine=None):
        self.coordinator = coordinator
        self.learning_engine = learning_engine
        
        # Configuration
        self.min_volume_usd = 50000  # Minimum 24h volume
        self.min_liquidity_usd = 10000  # Minimum order book depth
        self.max_spread_pct = 0.02  # Maximum 2% spread
        self.min_volatility_pct = 0.01  # Minimum 1% volatility
        self.max_volatility_pct = 0.30  # Maximum 30% volatility (avoid manipulation)
        
        # Gas optimization
        self.base_gas_cost_usd = 0.001  # Base L2 gas cost
        self.target_gas_pct = 0.02  # Target 2% max gas
        
        # Selection parameters
        self.max_coins = 10  # Maximum coins to track
        self.rotation_interval_sec = 3600  # Re-evaluate every hour
        self.min_confidence_trades = 3  # Min trades for confidence
        
        # State
        self._lock = threading.RLock()
        self._opportunities: Dict[str, CoinOpportunity] = {}
        self._selected_coins: List[str] = []
        self._last_rotation = 0.0
        self._market_data_cache: Dict[str, Dict] = {}
        
        # Trend detection
        self._price_history: Dict[str, List[Tuple[float, float]]] = defaultdict(list)  # symbol -> [(ts, price)]
        
        logging.info("Adaptive Coin Selector initialized")
    
    def update_market_data(self, symbol: str, data: Dict[str, Any]):
        """Update market data for a coin."""
        with self._lock:
            self._market_data_cache[symbol] = {
                "price": data.get("price", 0.0),
                "volume_24h": data.get("volume_24h", 0.0),
                "high_24h": data.get("high_24h", 0.0),
                "low_24h": data.get("low_24h", 0.0),
                "bid": data.get("bid", 0.0),
                "ask": data.get("ask", 0.0),
                "ts": time.time()
            }
            
            # Track price history for trend detection
            if data.get("price"):
                history = self._price_history[symbol]
                history.append((time.time(), data["price"]))
                # Keep last 24 hours
                cutoff = time.time() - 86400
                self._price_history[symbol] = [(t, p) for t, p in history if t > cutoff]
    
    def evaluate_opportunities(self, candidate_symbols: List[str]) -> List[CoinOpportunity]:
        """
        Evaluate all candidate coins and return ranked opportunities.
        
        This is the CORE selection logic - profit-first approach.
        """
        with self._lock:
            opportunities = []
            
            for symbol in candidate_symbols:
                try:
                    opp = self._evaluate_single_coin(symbol)
                    if opp and self._passes_filters(opp):
                        opportunities.append(opp)
                except Exception as e:
                    logging.warning(f"Failed to evaluate {symbol}: {e}")
            
            # Rank by final score
            opportunities.sort(key=lambda x: x.final_rank_score(), reverse=True)
            
            # Assign ranks
            for i, opp in enumerate(opportunities):
                opp.final_rank = i + 1
            
            return opportunities
    
    def _evaluate_single_coin(self, symbol: str) -> Optional[CoinOpportunity]:
        """Evaluate a single coin and create opportunity object."""
        market = self._market_data_cache.get(symbol, {})
        if not market:
            return None
        
        # Parse symbol
        base, quote = self._parse_symbol(symbol)
        
        opp = CoinOpportunity(
            symbol=symbol,
            base_asset=base,
            quote_asset=quote
        )
        
        # Market metrics
        opp.price = market.get("price", 0.0)
        opp.volume_24h_usd = market.get("volume_24h", 0.0)
        
        # Calculate volatility from high/low
        high = market.get("high_24h", opp.price)
        low = market.get("low_24h", opp.price)
        if low > 0:
            opp.volatility_24h = (high - low) / low
        
        # Calculate spread
        bid = market.get("bid", opp.price * 0.999)
        ask = market.get("ask", opp.price * 1.001)
        if bid > 0:
            opp.spread_pct = (ask - bid) / bid
        
        # Estimate liquidity (simplified - would need order book data)
        opp.liquidity_depth_usd = opp.volume_24h_usd * 0.01  # Rough estimate
        
        # Get historical performance from learning engine
        if self.learning_engine:
            coin_perf = self.learning_engine.coin_performance.get(symbol)
            if coin_perf:
                opp.historical_win_rate = coin_perf.win_rate
                opp.historical_profit_factor = coin_perf.profit_factor
                opp.historical_score = coin_perf.score
                if coin_perf.total_trades > 0:
                    opp.avg_trade_profit_pct = (coin_perf.total_profit_usd - coin_perf.total_loss_usd) / max(1.0, coin_perf.gross_volume_usd)
        
        # Gas efficiency
        opp.estimated_gas_cost_usd = self.base_gas_cost_usd
        if opp.estimated_gas_cost_usd > 0:
            opp.min_profitable_trade_usd = opp.estimated_gas_cost_usd / self.target_gas_pct
            opp.gas_efficiency_score = 1.0 - min(1.0, opp.estimated_gas_cost_usd / 0.01)  # Penalize high gas
        
        # Regime alignment
        opp.current_regime = self._detect_regime(symbol)
        opp.regime_alignment_score = self._calculate_regime_alignment(opp)
        
        # Calculate final scores
        opp.opportunity_score = self._calculate_opportunity_score(opp)
        opp.risk_adjusted_score = self._calculate_risk_adjusted_score(opp)
        
        return opp
    
    def _passes_filters(self, opp: CoinOpportunity) -> bool:
        """Check if opportunity passes minimum filters."""
        if opp.volume_24h_usd < self.min_volume_usd:
            return False
        if opp.spread_pct > self.max_spread_pct:
            return False
        if opp.volatility_24h < self.min_volatility_pct:
            return False
        if opp.volatility_24h > self.max_volatility_pct:
            return False
        return True
    
    def _calculate_opportunity_score(self, opp: CoinOpportunity) -> float:
        """
        Calculate raw opportunity score.
        
        Components:
        - Historical profit performance (40%)
        - Volatility opportunity (20%)
        - Gas efficiency (15%)
        - Liquidity safety (15%)
        - Spread cost (10%)
        """
        score = 0.0
        
        # Historical profit (most important!)
        # If we've traded this before and made money, weight heavily
        if opp.historical_score > 0:
            score += 0.40 * opp.historical_score
        else:
            # New coin - use theoretical estimate
            theoretical = min(1.0, opp.volatility_24h * 5)  # 20% vol = 1.0
            score += 0.40 * theoretical * 0.5  # Discount new coins
        
        # Volatility (opportunity for profit)
        vol_score = min(1.0, opp.volatility_24h / 0.10)  # 10% vol = max score
        score += 0.20 * vol_score
        
        # Gas efficiency
        score += 0.15 * opp.gas_efficiency_score
        
        # Liquidity (safety)
        liq_score = min(1.0, opp.liquidity_depth_usd / 50000)
        score += 0.15 * liq_score
        
        # Spread (cost)
        spread_score = max(0, 1.0 - opp.spread_pct / 0.02)  # 2% spread = 0 score
        score += 0.10 * spread_score
        
        return score
    
    def _calculate_risk_adjusted_score(self, opp: CoinOpportunity) -> float:
        """
        Apply risk adjustments to opportunity score.
        
        Adjustments:
        - Penalize coins with losing history
        - Penalize coins misaligned with regime
        - Boost coins with proven track record
        """
        score = opp.opportunity_score
        
        # Historical win rate adjustment
        if opp.historical_win_rate > 0:
            if opp.historical_win_rate < 0.4:
                score *= 0.5  # Heavy penalty for losers
            elif opp.historical_win_rate > 0.6:
                score *= 1.2  # Bonus for winners
        
        # Profit factor adjustment
        if opp.historical_profit_factor > 0:
            if opp.historical_profit_factor < 0.8:
                score *= 0.6  # Losing coin
            elif opp.historical_profit_factor > 1.5:
                score *= 1.3  # Profitable coin
        
        # Regime alignment
        score *= (0.7 + 0.3 * opp.regime_alignment_score)
        
        return min(1.0, score)
    
    def _detect_regime(self, symbol: str) -> str:
        """Detect current market regime for a coin."""
        history = self._price_history.get(symbol, [])
        if len(history) < 10:
            return "UNKNOWN"
        
        # Simple trend detection
        prices = [p for _, p in history[-20:]]
        if len(prices) < 10:
            return "UNKNOWN"
        
        # Calculate short and long term momentum
        short_momentum = (prices[-1] - prices[-5]) / prices[-5] if prices[-5] > 0 else 0
        long_momentum = (prices[-1] - prices[0]) / prices[0] if prices[0] > 0 else 0
        
        # Calculate volatility
        returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices)) if prices[i-1] > 0]
        if returns:
            volatility = math.sqrt(sum(r*r for r in returns) / len(returns))
        else:
            volatility = 0
        
        # Classify regime
        if volatility > 0.05:  # High volatility
            if abs(short_momentum) < 0.01:
                return "CHAOTIC"
            elif short_momentum > 0.02:
                return "TREND_UP_VOLATILE"
            else:
                return "TREND_DOWN_VOLATILE"
        elif abs(long_momentum) > 0.03:  # Strong trend
            return "TREND_UP" if long_momentum > 0 else "TREND_DOWN"
        else:
            return "RANGING"
    
    def _calculate_regime_alignment(self, opp: CoinOpportunity) -> float:
        """Calculate how well the coin's current regime aligns with our strategies."""
        regime = opp.current_regime
        
        # Our strategies perform differently in different regimes
        # This should align with worker performance data
        regime_scores = {
            "TREND_UP": 0.9,
            "TREND_DOWN": 0.8,
            "TREND_UP_VOLATILE": 0.85,
            "TREND_DOWN_VOLATILE": 0.75,
            "RANGING": 0.7,
            "CHAOTIC": 0.3,
            "UNKNOWN": 0.5
        }
        
        return regime_scores.get(regime, 0.5)
    
    def _parse_symbol(self, symbol: str) -> Tuple[str, str]:
        """Parse trading pair symbol into base and quote assets."""
        # Handle common formats: BTC/USDT, BTCUSDT, BTC-USDT
        symbol = symbol.upper()
        
        for sep in ["/", "-", "_"]:
            if sep in symbol:
                parts = symbol.split(sep)
                return parts[0], parts[1] if len(parts) > 1 else "USDT"
        
        # Try to detect quote currency
        for quote in ["USDT", "USDC", "USD", "ETH", "BTC"]:
            if symbol.endswith(quote):
                base = symbol[:-len(quote)]
                return base, quote
        
        return symbol, "USDT"
    
    def select_coins(self, candidates: List[str] = None) -> List[str]:
        """
        Select the best coins to trade based on profit potential.
        
        Returns list of symbols ranked by opportunity.
        """
        with self._lock:
            now = time.time()
            
            # Check if rotation is needed
            if self._selected_coins and (now - self._last_rotation) < self.rotation_interval_sec:
                return self._selected_coins
            
            # Use default candidates if none provided
            if not candidates:
                candidates = list(self._market_data_cache.keys())
            
            if not candidates:
                return self._selected_coins
            
            # Evaluate all opportunities
            opportunities = self.evaluate_opportunities(candidates)
            
            # Select top coins
            selected = [opp.symbol for opp in opportunities[:self.max_coins]]
            
            # Log selection
            if selected != self._selected_coins:
                logging.info(f"Coin rotation: {len(selected)} coins selected")
                for i, opp in enumerate(opportunities[:5]):
                    logging.info(f"  #{i+1}: {opp.symbol} score={opp.risk_adjusted_score:.3f} "
                               f"hist_score={opp.historical_score:.3f} vol={opp.volatility_24h:.2%}")
            
            self._selected_coins = selected
            self._last_rotation = now
            
            # Emit selection buzz
            self._emit_selection(opportunities[:self.max_coins])
            
            return selected
    
    def get_best_opportunity(self) -> Optional[CoinOpportunity]:
        """Get the single best trading opportunity right now."""
        with self._lock:
            if not self._selected_coins:
                return None
            
            best_symbol = self._selected_coins[0]
            return self._opportunities.get(best_symbol)
    
    def get_coin_opportunity(self, symbol: str) -> Optional[CoinOpportunity]:
        """Get opportunity details for a specific coin."""
        with self._lock:
            if symbol in self._opportunities:
                return self._opportunities[symbol]
            
            # Try to evaluate it
            opp = self._evaluate_single_coin(symbol)
            if opp:
                self._opportunities[symbol] = opp
            return opp
    
    def force_rotation(self):
        """Force immediate coin rotation (for manual override)."""
        with self._lock:
            self._last_rotation = 0
            return self.select_coins()
    
    def add_hot_coin(self, symbol: str, reason: str = "manual"):
        """Manually add a coin to the selection (for trending coins)."""
        with self._lock:
            if symbol not in self._selected_coins:
                self._selected_coins.insert(0, symbol)
                if len(self._selected_coins) > self.max_coins:
                    self._selected_coins = self._selected_coins[:self.max_coins]
                logging.info(f"Hot coin added: {symbol} reason={reason}")
    
    def remove_cold_coin(self, symbol: str, reason: str = "performance"):
        """Remove a coin from selection (for poor performers)."""
        with self._lock:
            if symbol in self._selected_coins:
                self._selected_coins.remove(symbol)
                logging.info(f"Cold coin removed: {symbol} reason={reason}")
    
    def _emit_selection(self, opportunities: List[CoinOpportunity]):
        """Emit coin selection buzz."""
        if not self.coordinator:
            return
        try:
            self.coordinator.share_data("buzz.coin.selection", {
                "buzz": {"type": "buzz.coin.selection", "source": "COIN_SELECTOR", "ts": int(time.time() * 1000)},
                "payload": {
                    "selected_count": len(opportunities),
                    "top_coins": [
                        {
                            "symbol": opp.symbol,
                            "score": opp.risk_adjusted_score,
                            "historical_score": opp.historical_score,
                            "volatility": opp.volatility_24h,
                            "regime": opp.current_regime,
                            "win_rate": opp.historical_win_rate
                        }
                        for opp in opportunities[:5]
                    ],
                    "rotation_interval_sec": self.rotation_interval_sec
                }
            })
        except Exception as e:
            logging.exception(f"Failed to emit coin selection: {e}")
    
    def get_selection_report(self) -> Dict[str, Any]:
        """Get detailed report on current coin selection."""
        with self._lock:
            return {
                "selected_coins": self._selected_coins,
                "total_candidates": len(self._market_data_cache),
                "last_rotation": self._last_rotation,
                "next_rotation": self._last_rotation + self.rotation_interval_sec,
                "opportunities": {
                    symbol: {
                        "score": opp.risk_adjusted_score,
                        "historical_score": opp.historical_score,
                        "volatility": opp.volatility_24h,
                        "volume_24h": opp.volume_24h_usd,
                        "regime": opp.current_regime
                    }
                    for symbol, opp in self._opportunities.items()
                    if symbol in self._selected_coins
                }
            }


# Helper function to add final_rank_score method to dataclass
def _add_rank_method():
    def final_rank_score(self):
        return self.risk_adjusted_score
    CoinOpportunity.final_rank_score = final_rank_score

_add_rank_method()
