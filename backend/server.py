"""
Hive Trading System - Streamlined Backend Server
"""

import os
import sys
import time
import logging

sys.path.insert(0, '/app')

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Dict, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Hive Trading System")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Global State
class State:
    mode = "SIMPLE"
    auto_trade = False
    approval_threshold = 10.0
    safety_level = "GREEN"
    circuit_breaker_active = False
    consecutive_losses = 0
    daily_pnl = 0.0
    trades_this_hour = 0
    coin_performance: Dict[str, Dict] = {}
    worker_weights = {"SMA": 1.0, "RSI": 1.0, "BREAKOUT": 1.0, "MOMENTUM": 1.0}
    total_trades = 0
    winning_trades = 0
    gas_saved = 0.0
    pending_batch: List = []

state = State()

class ModeUpdate(BaseModel):
    mode: str

class AutoTradeUpdate(BaseModel):
    enabled: bool

class TradeRecord(BaseModel):
    symbol: str
    profit: float
    worker: str = "UNKNOWN"

def record_trade(symbol: str, profit: float, worker: str):
    state.total_trades += 1
    is_win = profit > 0
    if is_win:
        state.winning_trades += 1
        state.consecutive_losses = 0
    else:
        state.consecutive_losses += 1
    state.daily_pnl += profit
    
    if symbol not in state.coin_performance:
        state.coin_performance[symbol] = {"trades": 0, "wins": 0, "profit": 0.0, "score": 0.5}
    cp = state.coin_performance[symbol]
    cp["trades"] += 1
    if is_win: cp["wins"] += 1
    cp["profit"] += profit
    cp["score"] = cp["wins"] / max(1, cp["trades"])
    
    if worker in state.worker_weights:
        state.worker_weights[worker] *= 1.05 if is_win else 0.95
        state.worker_weights[worker] = max(0.3, min(2.0, state.worker_weights[worker]))
    
    if state.consecutive_losses >= 5:
        state.circuit_breaker_active = True
        state.safety_level = "RED"

def get_top_coins(n=5):
    sorted_coins = sorted(state.coin_performance.items(), key=lambda x: x[1].get("score", 0), reverse=True)
    return [{"symbol": s, "score": d["score"], "trades": d["trades"]} for s, d in sorted_coins[:n]]

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    top_coins = get_top_coins(5)
    win_rate = (state.winning_trades / max(1, state.total_trades)) * 100
    
    coins_html = ""
    for c in top_coins:
        coins_html += f'<span class="coin-badge">{c["symbol"]} <span class="coin-score">{c["score"]*100:.0f}%</span></span>'
    if not coins_html:
        coins_html = '<span style="color:#666">No coins tracked yet</span>'
    
    workers_html = ""
    for w, wt in state.worker_weights.items():
        color = "green" if wt >= 1.0 else "yellow" if wt >= 0.7 else "red"
        workers_html += f'<div class="stat"><span class="stat-label">{w}</span><span class="stat-value {color}">{wt:.2f}x</span></div>'
    
    mode_simple_active = "active" if state.mode == "SIMPLE" else ""
    mode_governed_active = "active" if state.mode == "GOVERNED" else ""
    safety_color = "red" if state.circuit_breaker_active else "green"
    pnl_color = "green" if state.daily_pnl >= 0 else "red"
    auto_color = "green" if state.auto_trade else "yellow"
    wr_color = "green" if win_rate >= 50 else "red"
    cb_text = "🔴 ACTIVE" if state.circuit_breaker_active else "🟢 OK"
    cb_color = "red" if state.circuit_breaker_active else "green"
    auto_text = "ENABLED" if state.auto_trade else "MANUAL"
    toggle_text = "🔴 Disable" if state.auto_trade else "🟢 Enable"
    toggle_enabled = "false" if state.auto_trade else "true"
    reset_btn = '<button class="btn btn-danger" onclick="resetCircuitBreaker()">🔄 Reset Circuit Breaker</button>' if state.circuit_breaker_active else ""
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🐝 Hive Trading System</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: linear-gradient(135deg, #0a0a0f 0%, #1a1a2e 100%); color: #e0e0e0; min-height: 100vh; padding: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{ font-size: 2rem; margin-bottom: 20px; color: #ffd700; display: flex; align-items: center; gap: 12px; }}
        .badge {{ font-size: 0.75rem; padding: 4px 12px; border-radius: 20px; font-weight: 600; }}
        .badge-simple {{ background: #22c55e20; color: #22c55e; border: 1px solid #22c55e; }}
        .badge-governed {{ background: #f59e0b20; color: #f59e0b; border: 1px solid #f59e0b; }}
        .mode-toggle {{ display: flex; gap: 10px; margin-bottom: 24px; }}
        .mode-btn {{ flex: 1; padding: 14px 24px; border: 2px solid #333; background: #1a1a2e; color: #888; border-radius: 10px; cursor: pointer; font-size: 1rem; font-weight: 600; transition: all 0.2s; }}
        .mode-btn:hover {{ border-color: #555; transform: translateY(-2px); }}
        .mode-btn.active {{ background: linear-gradient(135deg, #2d2d4a 0%, #1a1a2e 100%); color: #fff; border-color: #4ade80; box-shadow: 0 0 20px rgba(74, 222, 128, 0.2); }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin-bottom: 24px; }}
        .card {{ background: linear-gradient(135deg, #12121a 0%, #1a1a2e 100%); border: 1px solid #2a2a3e; border-radius: 16px; padding: 24px; transition: transform 0.2s; }}
        .card:hover {{ transform: translateY(-4px); box-shadow: 0 10px 40px rgba(0,0,0,0.3); }}
        .card h2 {{ font-size: 0.85rem; color: #888; margin-bottom: 16px; text-transform: uppercase; letter-spacing: 1.5px; }}
        .stat {{ display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #2a2a3e; }}
        .stat:last-child {{ border-bottom: none; }}
        .stat-label {{ color: #888; font-size: 0.9rem; }}
        .stat-value {{ font-weight: 700; font-size: 1.1rem; }}
        .green {{ color: #4ade80; }}
        .red {{ color: #f87171; }}
        .yellow {{ color: #fbbf24; }}
        .status-dot {{ display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 8px; animation: pulse 2s infinite; }}
        .status-green {{ background: #4ade80; box-shadow: 0 0 15px #4ade80; }}
        .status-red {{ background: #f87171; box-shadow: 0 0 15px #f87171; }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}
        .coin-list {{ display: flex; flex-wrap: wrap; gap: 8px; }}
        .coin-badge {{ padding: 8px 14px; background: #2a2a3e; border-radius: 20px; font-size: 0.85rem; display: flex; align-items: center; gap: 6px; }}
        .coin-score {{ color: #4ade80; font-weight: 600; }}
        .btn {{ padding: 12px 24px; border: none; border-radius: 8px; cursor: pointer; font-weight: 600; font-size: 0.9rem; transition: all 0.2s; }}
        .btn-primary {{ background: #4ade80; color: #000; }}
        .btn-primary:hover {{ background: #22c55e; transform: translateY(-2px); }}
        .btn-danger {{ background: #f87171; color: #000; }}
        .btn-danger:hover {{ background: #ef4444; }}
        .controls {{ display: flex; gap: 12px; flex-wrap: wrap; }}
        @media (max-width: 640px) {{ body {{ padding: 12px; }} h1 {{ font-size: 1.5rem; }} .mode-btn {{ padding: 12px 16px; font-size: 0.9rem; }} }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🐝 Hive Trading System <span class="badge badge-{state.mode.lower()}">{state.mode} MODE</span></h1>
        
        <div class="mode-toggle">
            <button class="mode-btn {mode_simple_active}" onclick="setMode('SIMPLE')">⚡ SIMPLE MODE<br><small style="color:#888">Fast & Efficient</small></button>
            <button class="mode-btn {mode_governed_active}" onclick="setMode('GOVERNED')">🏛️ GOVERNED MODE<br><small style="color:#888">Safe & Validated</small></button>
        </div>
        
        <div class="grid">
            <div class="card">
                <h2>🛡️ Safety Status</h2>
                <div class="stat"><span class="stat-label">System Status</span><span class="stat-value"><span class="status-dot status-{safety_color}"></span>{state.safety_level}</span></div>
                <div class="stat"><span class="stat-label">Circuit Breaker</span><span class="stat-value {cb_color}">{cb_text}</span></div>
                <div class="stat"><span class="stat-label">Consecutive Losses</span><span class="stat-value">{state.consecutive_losses} / 5</span></div>
                <div class="stat"><span class="stat-label">Daily P&L</span><span class="stat-value {pnl_color}">${state.daily_pnl:.4f}</span></div>
            </div>
            
            <div class="card">
                <h2>🧠 Learning Engine</h2>
                <div class="stat"><span class="stat-label">Auto-Trade</span><span class="stat-value {auto_color}">{auto_text}</span></div>
                <div class="stat"><span class="stat-label">Total Trades</span><span class="stat-value">{state.total_trades}</span></div>
                <div class="stat"><span class="stat-label">Win Rate</span><span class="stat-value {wr_color}">{win_rate:.1f}%</span></div>
                <div class="stat"><span class="stat-label">Approval Threshold</span><span class="stat-value">${state.approval_threshold:.2f}</span></div>
            </div>
            
            <div class="card">
                <h2>⛽ Gas Optimizer</h2>
                <div class="stat"><span class="stat-label">Network</span><span class="stat-value green">BASE L2</span></div>
                <div class="stat"><span class="stat-label">Cost per Trade</span><span class="stat-value green">$0.001</span></div>
                <div class="stat"><span class="stat-label">Total Saved</span><span class="stat-value green">${state.gas_saved:.4f}</span></div>
                <div class="stat"><span class="stat-label">Batch Queue</span><span class="stat-value">{len(state.pending_batch)} trades</span></div>
            </div>
            
            <div class="card">
                <h2>📊 Worker Performance</h2>
                {workers_html}
            </div>
        </div>
        
        <div class="card">
            <h2>🏆 Top Performing Coins</h2>
            <div class="coin-list">{coins_html}</div>
        </div>
        
        <div class="card" style="margin-top:20px">
            <h2>⚙️ Controls</h2>
            <div class="controls">
                <button class="btn btn-primary" onclick="toggleAutoTrade()">{toggle_text} Auto-Trade</button>
                {reset_btn}
                <button class="btn" style="background:#6366f1;color:#fff" onclick="location.reload()">🔄 Refresh</button>
            </div>
        </div>
    </div>
    
    <script>
        async function setMode(mode) {{ await fetch('/api/mode', {{ method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{mode}}) }}); location.reload(); }}
        async function toggleAutoTrade() {{ await fetch('/api/auto_trade', {{ method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{enabled: {toggle_enabled}}}) }}); location.reload(); }}
        async function resetCircuitBreaker() {{ await fetch('/api/safety/reset', {{method: 'POST'}}); location.reload(); }}
        setTimeout(() => location.reload(), 15000);
    </script>
</body>
</html>'''
    return HTMLResponse(content=html)

@app.get("/api/health")
async def health():
    return {"status": "ok", "mode": state.mode, "ts": int(time.time() * 1000)}

@app.get("/api/status")
async def status():
    return {
        "mode": state.mode, "auto_trade": state.auto_trade,
        "safety": {"level": state.safety_level, "circuit_breaker": state.circuit_breaker_active, "consecutive_losses": state.consecutive_losses, "daily_pnl": state.daily_pnl},
        "learning": {"total_trades": state.total_trades, "winning_trades": state.winning_trades, "win_rate": state.winning_trades / max(1, state.total_trades), "top_coins": get_top_coins(5)},
        "worker_weights": state.worker_weights
    }

@app.post("/api/mode")
async def set_mode(update: ModeUpdate):
    if update.mode.upper() in ["SIMPLE", "GOVERNED"]:
        state.mode = update.mode.upper()
    return {"mode": state.mode}

@app.post("/api/auto_trade")
async def set_auto_trade(update: AutoTradeUpdate):
    state.auto_trade = update.enabled
    return {"auto_trade": state.auto_trade}

@app.post("/api/trade/record")
async def api_record_trade(trade: TradeRecord):
    record_trade(trade.symbol, trade.profit, trade.worker)
    return {"ok": True, "total_trades": state.total_trades}

@app.post("/api/safety/reset")
async def reset_safety():
    state.circuit_breaker_active = False
    state.consecutive_losses = 0
    state.safety_level = "GREEN"
    return {"ok": True}

@app.get("/api/mobile/dashboard")
async def mobile_dashboard():
    return {"mode": state.mode, "auto_trade": state.auto_trade, "safety_level": state.safety_level, "circuit_breaker": state.circuit_breaker_active, "daily_pnl": state.daily_pnl, "win_rate": state.winning_trades / max(1, state.total_trades), "top_coins": get_top_coins(3)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8001)))
