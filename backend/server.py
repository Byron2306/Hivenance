"""
Hive Trading System - Streamlined Backend Server

Two modes:
- SIMPLE: Fast execution, minimal checks (for speed)
- GOVERNED: Full governance pipeline (for safety)

Features:
- Learning engine for profit tracking
- Gas optimization (Base L2)
- Safety system with circuit breakers
- Trade approval workflow
- Mobile-friendly API
"""

import os
import sys
import time
import json
import logging
import sqlite3

sys.path.insert(0, '/app')

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Hive Trading System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# Lightweight In-Memory State (No complex imports needed)
# ============================================================

class TradingState:
    def __init__(self):
        self.mode = "SIMPLE"  # SIMPLE or GOVERNED
        self.auto_trade = False
        self.approval_threshold = 10.0
        self.risk_tolerance = 0.5
        
        # Safety
        self.safety_level = "GREEN"
        self.circuit_breaker_active = False
        self.consecutive_losses = 0
        self.daily_pnl = 0.0
        self.trades_this_hour = 0
        self.max_trades_per_hour = 10
        
        # Learning
        self.coin_performance: Dict[str, Dict] = {}
        self.worker_weights: Dict[str, float] = {
            "SMA": 1.0, "RSI": 1.0, "BREAKOUT": 1.0, "MOMENTUM": 1.0
        }
        self.total_trades = 0
        self.winning_trades = 0
        
        # Gas
        self.gas_network = "base"
        self.gas_per_trade = 0.001
        self.gas_saved = 0.0
        self.batch_enabled = True
        self.pending_batch: List[Dict] = []
        
        # Approvals
        self.pending_approvals: List[Dict] = []
        
    def record_trade(self, symbol: str, profit: float, worker: str):
        """Record a trade outcome and update learning."""
        self.total_trades += 1
        is_win = profit > 0
        
        if is_win:
            self.winning_trades += 1
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
        
        self.daily_pnl += profit
        self.trades_this_hour += 1
        
        # Update coin performance
        if symbol not in self.coin_performance:
            self.coin_performance[symbol] = {
                "trades": 0, "wins": 0, "total_profit": 0.0, "score": 0.5
            }
        
        cp = self.coin_performance[symbol]
        cp["trades"] += 1
        if is_win:
            cp["wins"] += 1
        cp["total_profit"] += profit
        cp["score"] = cp["wins"] / max(1, cp["trades"])
        
        # Update worker weight
        if worker in self.worker_weights:
            if is_win:
                self.worker_weights[worker] = min(2.0, self.worker_weights[worker] * 1.05)
            else:
                self.worker_weights[worker] = max(0.3, self.worker_weights[worker] * 0.95)
        
        # Check circuit breaker
        if self.consecutive_losses >= 5:
            self.circuit_breaker_active = True
            self.safety_level = "RED"
            logger.warning("Circuit breaker triggered!")
    
    def validate_trade(self, symbol: str, amount_usd: float, wallet_balance: float) -> Dict:
        """Multi-layer validation for a trade."""
        checks_passed = []
        checks_failed = []
        
        # Layer 1: Circuit breaker
        if self.circuit_breaker_active:
            checks_failed.append("CIRCUIT_BREAKER_ACTIVE")
        else:
            checks_passed.append("CIRCUIT_BREAKER_OK")
        
        # Layer 2: Position size (max 10%)
        max_size = wallet_balance * 0.10
        if amount_usd > max_size:
            checks_failed.append("POSITION_TOO_LARGE")
        else:
            checks_passed.append("POSITION_SIZE_OK")
        
        # Layer 3: Rate limit
        if self.trades_this_hour >= self.max_trades_per_hour:
            checks_failed.append("RATE_LIMIT_EXCEEDED")
        else:
            checks_passed.append("RATE_LIMIT_OK")
        
        # Layer 4: Gas efficiency
        gas_pct = self.gas_per_trade / max(0.01, amount_usd)
        if gas_pct > 0.05:
            checks_failed.append("GAS_INEFFICIENT")
        else:
            checks_passed.append("GAS_OK")
        
        # Layer 5: Coin history (if GOVERNED mode)
        if self.mode == "GOVERNED":
            cp = self.coin_performance.get(symbol, {})
            if cp.get("trades", 0) >= 5 and cp.get("score", 0.5) < 0.3:
                checks_failed.append("COIN_POOR_HISTORY")
            else:
                checks_passed.append("COIN_HISTORY_OK")
        
        approved = len(checks_failed) == 0
        
        return {
            "approved": approved,
            "checks_passed": checks_passed,
            "checks_failed": checks_failed,
            "max_allowed_size": max_size,
            "recommended_size": min(amount_usd, max_size)
        }
    
    def get_top_coins(self, n: int = 5) -> List[Dict]:
        """Get top performing coins."""
        sorted_coins = sorted(
            self.coin_performance.items(),
            key=lambda x: x[1].get("score", 0),
            reverse=True
        )
        return [{"symbol": s, "score": d["score"], "trades": d["trades"]} 
                for s, d in sorted_coins[:n]]
    
    def reset_circuit_breaker(self):
        """Reset circuit breaker."""
        self.circuit_breaker_active = False
        self.consecutive_losses = 0
        self.safety_level = "GREEN"
        logger.info("Circuit breaker reset")

# Global state
state = TradingState()

# ============================================================
# Pydantic Models
# ============================================================

class ModeUpdate(BaseModel):
    mode: str

class AutoTradeUpdate(BaseModel):
    enabled: bool

class TradeRecord(BaseModel):
    symbol: str
    profit: float
    worker: str = "UNKNOWN"

class TradeValidation(BaseModel):
    symbol: str
    amount_usd: float
    wallet_balance: float = 100.0

class ApprovalAction(BaseModel):
    trade_id: str
    action: str  # APPROVE or REJECT

# ============================================================
# API Endpoints
# ============================================================

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Main dashboard HTML."""
    top_coins = state.get_top_coins(5)
    win_rate = (state.winning_trades / max(1, state.total_trades)) * 100
    
    html = f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🐝 Hive Trading System</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', system-ui, sans-serif;
            background: linear-gradient(135deg, #0a0a0f 0%, #1a1a2e 100%);
            color: #e0e0e0;
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{
            font-size: 2rem;
            margin-bottom: 20px;
            color: #ffd700;
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .badge {{
            font-size: 0.75rem;
            padding: 4px 12px;
            border-radius: 20px;
            font-weight: 600;
        }}
        .badge-simple {{ background: #22c55e20; color: #22c55e; border: 1px solid #22c55e; }}
        .badge-governed {{ background: #f59e0b20; color: #f59e0b; border: 1px solid #f59e0b; }}
        
        .mode-toggle {{
            display: flex;
            gap: 10px;
            margin-bottom: 24px;
        }}
        .mode-btn {{
            flex: 1;
            padding: 14px 24px;
            border: 2px solid #333;
            background: #1a1a2e;
            color: #888;
            border-radius: 10px;
            cursor: pointer;
            font-size: 1rem;
            font-weight: 600;
            transition: all 0.2s;
        }}
        .mode-btn:hover {{ border-color: #555; transform: translateY(-2px); }}
        .mode-btn.active {{
            background: linear-gradient(135deg, #2d2d4a 0%, #1a1a2e 100%);
            color: #fff;
            border-color: #4ade80;
            box-shadow: 0 0 20px rgba(74, 222, 128, 0.2);
        }}
        
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 24px;
        }}
        
        .card {{
            background: linear-gradient(135deg, #12121a 0%, #1a1a2e 100%);
            border: 1px solid #2a2a3e;
            border-radius: 16px;
            padding: 24px;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .card:hover {{
            transform: translateY(-4px);
            box-shadow: 0 10px 40px rgba(0,0,0,0.3);
        }}
        .card h2 {{
            font-size: 0.85rem;
            color: #888;
            margin-bottom: 16px;
            text-transform: uppercase;
            letter-spacing: 1.5px;
        }}
        
        .stat {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid #2a2a3e;
        }}
        .stat:last-child {{ border-bottom: none; }}
        .stat-label {{ color: #888; font-size: 0.9rem; }}
        .stat-value {{ font-weight: 700; font-size: 1.1rem; }}
        .green {{ color: #4ade80; }}
        .red {{ color: #f87171; }}
        .yellow {{ color: #fbbf24; }}
        
        .status-dot {{
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 8px;
            animation: pulse 2s infinite;
        }}
        .status-green {{ background: #4ade80; box-shadow: 0 0 15px #4ade80; }}
        .status-red {{ background: #f87171; box-shadow: 0 0 15px #f87171; }}
        .status-yellow {{ background: #fbbf24; box-shadow: 0 0 15px #fbbf24; }}
        
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.5; }}
        }}
        
        .coin-list {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .coin-badge {{
            padding: 8px 14px;
            background: #2a2a3e;
            border-radius: 20px;
            font-size: 0.85rem;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .coin-score {{ color: #4ade80; font-weight: 600; }}
        
        .btn {{
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            font-size: 0.9rem;
            transition: all 0.2s;
        }}
        .btn-primary {{ background: #4ade80; color: #000; }}
        .btn-primary:hover {{ background: #22c55e; transform: translateY(-2px); }}
        .btn-danger {{ background: #f87171; color: #000; }}
        .btn-danger:hover {{ background: #ef4444; }}
        
        .controls {{
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
        }}
        
        @media (max-width: 640px) {{
            body {{ padding: 12px; }}
            h1 {{ font-size: 1.5rem; }}
            .mode-btn {{ padding: 12px 16px; font-size: 0.9rem; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>
            🐝 Hive Trading System
            <span class="badge badge-{state.mode.lower()}">{state.mode} MODE</span>
        </h1>
        
        <div class="mode-toggle">
            <button class="mode-btn {'active' if state.mode == 'SIMPLE' else ''}" onclick="setMode('SIMPLE')">
                ⚡ SIMPLE MODE<br><small style="color:#888">Fast & Efficient</small>
            </button>
            <button class="mode-btn {'active' if state.mode == 'GOVERNED' else ''}" onclick="setMode('GOVERNED')">
                🏛️ GOVERNED MODE<br><small style="color:#888">Safe & Validated</small>
            </button>
        </div>
        
        <div class="grid">
            <div class="card">
                <h2>🛡️ Safety Status</h2>
                <div class="stat">
                    <span class="stat-label">System Status</span>
                    <span class="stat-value">
                        <span class="status-dot status-{'red' if state.circuit_breaker_active else 'green'}"></span>
                        {state.safety_level}
                    </span>
                </div>
                <div class="stat">
                    <span class="stat-label">Circuit Breaker</span>
                    <span class="stat-value {'red' if state.circuit_breaker_active else 'green'}">
                        {'🔴 ACTIVE' if state.circuit_breaker_active else '🟢 OK'}
                    </span>
                </div>
                <div class="stat">
                    <span class="stat-label">Consecutive Losses</span>
                    <span class="stat-value">{state.consecutive_losses} / 5</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Daily P&L</span>
                    <span class="stat-value {'green' if state.daily_pnl >= 0 else 'red'}">
                        ${state.daily_pnl:.4f}
                    </span>
                </div>
            </div>
            
            <div class="card">
                <h2>🧠 Learning Engine</h2>
                <div class="stat">
                    <span class="stat-label">Auto-Trade</span>
                    <span class="stat-value {'green' if state.auto_trade else 'yellow'}">
                        {'ENABLED' if state.auto_trade else 'MANUAL'}
                    </span>
                </div>
                <div class="stat">
                    <span class="stat-label">Total Trades</span>
                    <span class="stat-value">{state.total_trades}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Win Rate</span>
                    <span class="stat-value {'green' if win_rate >= 50 else 'red'}">{win_rate:.1f}%</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Approval Threshold</span>
                    <span class="stat-value">${state.approval_threshold:.2f}</span>
                </div>
            </div>
            
            <div class="card">
                <h2>⛽ Gas Optimizer</h2>
                <div class="stat">
                    <span class="stat-label">Network</span>
                    <span class="stat-value green">{state.gas_network.upper()} L2</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Cost per Trade</span>
                    <span class="stat-value green">${state.gas_per_trade:.4f}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Total Saved</span>
                    <span class="stat-value green">${state.gas_saved:.4f}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Batch Queue</span>
                    <span class="stat-value">{len(state.pending_batch)} trades</span>
                </div>
            </div>
            
            <div class="card">
                <h2>📊 Worker Performance</h2>
                {''.join(f'''
                <div class="stat">
                    <span class="stat-label">{w}</span>
                    <span class="stat-value {'green' if wt >= 1.0 else 'yellow' if wt >= 0.7 else 'red'}">{wt:.2f}x</span>
                </div>
                ''' for w, wt in state.worker_weights.items())}
            </div>
        </div>
        
        <div class="card">
            <h2>🏆 Top Performing Coins</h2>
            <div class="coin-list">
                {''.join(f'<span class="coin-badge">{c["symbol"]} <span class="coin-score">{c["score"]*100:.0f}%</span></span>' for c in top_coins) if top_coins else '<span style="color:#666">No coins tracked yet - trades will appear here</span>'}
            </div>
        </div>
        
        <div class="card" style="margin-top:20px">
            <h2>⚙️ Controls</h2>
            <div class="controls">
                <button class="btn btn-primary" onclick="toggleAutoTrade()">
                    {'🔴 Disable' if state.auto_trade else '🟢 Enable'} Auto-Trade
                </button>
                {'<button class="btn btn-danger" onclick="resetCircuitBreaker()">🔄 Reset Circuit Breaker</button>' if state.circuit_breaker_active else ''}
                <button class="btn" style="background:#6366f1;color:#fff" onclick="location.reload()">
                    🔄 Refresh
                </button>
            </div>
        </div>
    </div>
    
    <script>
        async function setMode(mode) {{
            await fetch('/api/mode', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{mode}})
            }});
            location.reload();
        }}
        
        async function toggleAutoTrade() {{
            await fetch('/api/auto_trade', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{enabled: {str(not state.auto_trade).lower()}}})
            }});
            location.reload();
        }}
        
        async function resetCircuitBreaker() {{
            await fetch('/api/safety/reset', {{method: 'POST'}});
            location.reload();
        }}
        
        // Auto-refresh every 15 seconds
        setTimeout(() => location.reload(), 15000);
    </script>
</body>
</html>
'''
    return HTMLResponse(content=html)

@app.get("/api/health")
async def health():
    return {"status": "ok", "mode": state.mode, "ts": int(time.time() * 1000)}

@app.get("/api/status")
async def status():
    """Full system status."""
    return {
        "mode": state.mode,
        "auto_trade": state.auto_trade,
        "safety": {
            "level": state.safety_level,
            "circuit_breaker": state.circuit_breaker_active,
            "consecutive_losses": state.consecutive_losses,
            "daily_pnl": state.daily_pnl
        },
        "learning": {
            "total_trades": state.total_trades,
            "winning_trades": state.winning_trades,
            "win_rate": state.winning_trades / max(1, state.total_trades),
            "coins_tracked": len(state.coin_performance),
            "top_coins": state.get_top_coins(5)
        },
        "gas": {
            "network": state.gas_network,
            "cost_per_trade": state.gas_per_trade,
            "total_saved": state.gas_saved,
            "batch_enabled": state.batch_enabled
        },
        "worker_weights": state.worker_weights
    }

@app.post("/api/mode")
async def set_mode(update: ModeUpdate):
    if update.mode.upper() in ["SIMPLE", "GOVERNED"]:
        state.mode = update.mode.upper()
        logger.info(f"Mode changed to: {state.mode}")
    return {"mode": state.mode}

@app.post("/api/auto_trade")
async def set_auto_trade(update: AutoTradeUpdate):
    state.auto_trade = update.enabled
    logger.info(f"Auto-trade: {state.auto_trade}")
    return {"auto_trade": state.auto_trade}

@app.post("/api/trade/record")
async def record_trade(trade: TradeRecord):
    """Record a trade outcome for learning."""
    state.record_trade(trade.symbol, trade.profit, trade.worker)
    return {"ok": True, "total_trades": state.total_trades}

@app.post("/api/trade/validate")
async def validate_trade(trade: TradeValidation):
    """Validate a trade before execution."""
    result = state.validate_trade(trade.symbol, trade.amount_usd, trade.wallet_balance)
    return result

@app.post("/api/safety/reset")
async def reset_safety():
    """Reset circuit breaker."""
    state.reset_circuit_breaker()
    return {"ok": True, "safety_level": state.safety_level}

@app.get("/api/mobile/dashboard")
async def mobile_dashboard():
    """Compact endpoint for mobile."""
    return {
        "mode": state.mode,
        "auto_trade": state.auto_trade,
        "safety_level": state.safety_level,
        "circuit_breaker": state.circuit_breaker_active,
        "daily_pnl": state.daily_pnl,
        "win_rate": state.winning_trades / max(1, state.total_trades),
        "top_coins": state.get_top_coins(3),
        "pending_approvals": len(state.pending_approvals)
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8001))
    logger.info(f"Starting Hive Trading System on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
