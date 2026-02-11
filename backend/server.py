"""
FastAPI server for Hivenance Trading System with WebSocket support.
"""
import sys
import os
import logging
import time
import json
import asyncio
import random
from typing import List, Dict, Any
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse

# Create FastAPI app
app = FastAPI(title="Hivenance Trading System", description="Multi-agent crypto trading platform")

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logging.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logging.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")
    
    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        
        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create a minimal coordinator-like object for standalone UI mode
class MinimalConfig:
    def __init__(self):
        self.feed_buffer_trades = 500
        self.feed_buffer_logs = 1000
        self.allowed_ips = []
        self.ui_host = "0.0.0.0"
        self.ui_port = 8001
        self.dry_run = True
        self.exchange = "binance"
        self.symbol = "BTCUSDT"
        # Governance mode config
        self.governance_mode = "GOVERNED"  # SIMPLE or GOVERNED
        
class MinimalCoordinator:
    def __init__(self):
        self.cfg = MinimalConfig()
        self.agents = {}
        self.data_cache = {}
        self.running = True
        self.agent_health = {}
    
    def get_shared_data(self, key):
        return self.data_cache.get(key)
    
    def share_data(self, key, value):
        self.data_cache[key] = value

# Initialize coordinator
coordinator = MinimalCoordinator()

# Persistent state storage
state = {
    "mode": "SIMPLE",
    "auto_trade": False,
    "safety": {
        "level": "GREEN",
        "circuit_breaker": False,
        "consecutive_losses": 0,
        "daily_pnl": 25.0
    },
    "learning": {
        "total_trades": 7,
        "winning_trades": 2,
        "win_rate": 0.2857142857142857,
        "top_coins": [
            {"symbol": "BTC/USD", "score": 1.0, "trades": 2},
            {"symbol": "TEST0/USD", "score": 0.0, "trades": 1},
            {"symbol": "TEST1/USD", "score": 0.0, "trades": 1},
            {"symbol": "TEST2/USD", "score": 0.0, "trades": 1},
            {"symbol": "TEST3/USD", "score": 0.0, "trades": 1}
        ]
    },
    "worker_weights": {
        "SMA": 1.1025,
        "RSI": 1.0,
        "BREAKOUT": 1.0,
        "MOMENTUM": 1.0
    }
}

# ============ API ENDPOINTS ============

@app.get("/")
async def root():
    """Root endpoint - shows landing info"""
    return {"message": "Hivenance Trading System API", "version": "1.0.0", "docs": "/docs"}

# Main status endpoint expected by frontend
@app.get("/api/status")
async def api_status():
    """Return full system status for frontend."""
    return state

# Mode switching endpoint expected by frontend
@app.post("/api/mode")
async def api_set_mode(request: Request):
    """Set trading mode - SIMPLE or GOVERNED."""
    data = await request.json()
    mode = data.get("mode", "").upper()
    if mode in ("SIMPLE", "GOVERNED"):
        state["mode"] = mode
    return {"mode": state["mode"]}

# Auto trade toggle endpoint expected by frontend
@app.post("/api/auto_trade")
async def api_auto_trade(request: Request):
    """Toggle auto trade mode."""
    data = await request.json()
    enabled = data.get("enabled", False)
    state["auto_trade"] = bool(enabled)
    return {"auto_trade": state["auto_trade"]}

# Safety reset endpoint expected by frontend
@app.post("/api/safety/reset")
async def api_safety_reset():
    """Reset circuit breaker."""
    state["safety"]["circuit_breaker"] = False
    state["safety"]["consecutive_losses"] = 0
    return {"ok": True, "safety": state["safety"]}

@app.get("/api/")
async def api_root():
    """API root - redirect to dashboard"""
    return RedirectResponse(url="/api/dashboard")

@app.get("/api/health")
async def health():
    return {"status": "healthy", "service": "hivenance", "timestamp": int(time.time())}

@app.get("/api/status.json")
async def status_json():
    """Return current runtime mode and status flags."""
    return {
        "dry_run": coordinator.cfg.dry_run,
        "kill_state": {},
        "paused": False,
        "live": not coordinator.cfg.dry_run,
        "security_policy": {},
        "governance_mode": coordinator.cfg.governance_mode,
    }

@app.get("/api/metrics.json")
async def metrics_json():
    """Return system metrics."""
    return {
        "agents": list(coordinator.agents.keys()),
        "uptime": int(time.time()),
        "trades_today": 0,
        "pnl_today": 0.0,
    }

@app.get("/api/governance/mode", response_class=JSONResponse)
async def get_governance_mode():
    """Get current governance mode."""
    return {
        "mode": coordinator.cfg.governance_mode,
        "description": "SIMPLE = fast execution, minimal checks | GOVERNED = full safety validation"
    }

@app.post("/api/governance/mode")
async def set_governance_mode(request: Request):
    """Set governance mode - SIMPLE or GOVERNED."""
    data = await request.json()
    mode = data.get("mode", "").upper()
    if mode not in ("SIMPLE", "GOVERNED"):
        return JSONResponse({"ok": False, "error": "mode must be SIMPLE or GOVERNED"}, status_code=400)
    coordinator.cfg.governance_mode = mode
    return {"ok": True, "mode": mode}

@app.get("/api/learning/status.json")
async def learning_status():
    """Get learning engine status."""
    learning = coordinator.agents.get("learning")
    if learning:
        return {
            "enabled": True,
            "health": learning.get_system_health() if hasattr(learning, 'get_system_health') else {},
            "top_coins": [],
            "auto_trade_enabled": getattr(learning, 'auto_trade_enabled', False),
        }
    return {"enabled": False, "health": {}, "top_coins": [], "auto_trade_enabled": False}

@app.get("/api/safety/status.json")
async def safety_status():
    """Get safety system status."""
    safety = coordinator.agents.get("safety")
    if safety:
        return safety.get_safety_status() if hasattr(safety, 'get_safety_status') else {"enabled": True}
    return {"enabled": False, "circuit_breaker_active": False, "safety_level": "HIGH"}

@app.get("/api/gas/status.json")
async def gas_status():
    """Get gas optimizer status."""
    gas_opt = coordinator.agents.get("gas_optimizer")
    if gas_opt:
        return {
            "enabled": True,
            "report": gas_opt.get_gas_report() if hasattr(gas_opt, 'get_gas_report') else {},
        }
    return {"enabled": False, "report": {}}

@app.get("/api/wallet.json")
async def wallet_json():
    """Get wallet information."""
    wallet = coordinator.agents.get("wallet")
    if wallet:
        return {
            "address": getattr(wallet, 'addr', None) or getattr(wallet, 'address', None),
            "network": {"ok": True},
            "balances": [],
        }
    return {"address": None, "network": {"ok": False}, "balances": []}

@app.get("/api/approvals/pending.json")
async def pending_approvals():
    """Get pending trade approvals."""
    learning = coordinator.agents.get("learning")
    if learning and hasattr(learning, 'get_pending_approvals'):
        return {"pending": learning.get_pending_approvals()}
    return {"pending": []}

@app.post("/api/approvals/action")
async def approval_action(request: Request):
    """Approve or reject a pending trade."""
    data = await request.json()
    trade_id = data.get("trade_id")
    action = str(data.get("action", "")).upper()
    
    if not trade_id:
        return JSONResponse({"ok": False, "error": "trade_id_required"}, status_code=400)
    if action not in ("APPROVE", "REJECT"):
        return JSONResponse({"ok": False, "error": "action must be APPROVE or REJECT"}, status_code=400)
    
    learning = coordinator.agents.get("learning")
    if learning and hasattr(learning, 'process_approval'):
        ok = learning.process_approval(trade_id, action == "APPROVE", approved_by="USER_API")
        return {"ok": ok, "trade_id": trade_id, "action": action}
    
    return {"ok": False, "error": "learning_engine_not_available"}

@app.get("/api/mobile/dashboard.json")
async def mobile_dashboard():
    """Combined endpoint for mobile - all essential data in one call."""
    return {
        "ts": int(time.time() * 1000),
        "governance_mode": coordinator.cfg.governance_mode,
        "dry_run": coordinator.cfg.dry_run,
        "learning": {"enabled": "learning" in coordinator.agents},
        "safety": {"enabled": "safety" in coordinator.agents, "circuit_breaker_active": False},
        "gas": {"enabled": "gas_optimizer" in coordinator.agents},
        "pending_approvals": [],
        "wallet": {"equity_usd": 0.0, "balances": []},
    }

@app.get("/api/agents/status")
async def agents_status():
    """Get status of all agents."""
    return {
        "agents": list(coordinator.agents.keys()),
        "health": coordinator.agent_health,
    }

@app.get("/api/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Render the main dashboard HTML."""
    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Hivenance - Trading Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #fff;
            min-height: 100vh;
        }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 0;
            border-bottom: 1px solid rgba(255,255,255,0.1);
            margin-bottom: 30px;
        }
        .logo {
            font-size: 1.8rem;
            font-weight: bold;
            background: linear-gradient(90deg, #f7b731, #ffc107);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .status-bar {
            display: flex;
            gap: 15px;
        }
        .status-badge {
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: 500;
        }
        .status-live { background: rgba(40, 167, 69, 0.2); color: #28a745; }
        .status-dry { background: rgba(255, 193, 7, 0.2); color: #ffc107; }
        .status-governed { background: rgba(52, 152, 219, 0.2); color: #3498db; }
        .status-simple { background: rgba(231, 76, 60, 0.2); color: #e74c3c; }
        
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .card {
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            padding: 25px;
            backdrop-filter: blur(10px);
        }
        .card-title {
            font-size: 1rem;
            color: #888;
            margin-bottom: 15px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .card-value {
            font-size: 2rem;
            font-weight: bold;
            color: #f7b731;
        }
        .card-sub { color: #666; font-size: 0.9rem; margin-top: 10px; }
        
        .btn {
            padding: 12px 25px;
            border: none;
            border-radius: 25px;
            font-size: 1rem;
            cursor: pointer;
            transition: all 0.3s;
            margin: 5px;
        }
        .btn-primary { background: linear-gradient(90deg, #f7b731, #ffc107); color: #1a1a2e; }
        .btn-secondary { background: rgba(255,255,255,0.1); color: #fff; }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 5px 15px rgba(0,0,0,0.3); }
        
        .mode-toggle {
            display: flex;
            gap: 10px;
            margin: 20px 0;
        }
        .mode-btn {
            flex: 1;
            padding: 15px;
            border: 2px solid transparent;
            border-radius: 10px;
            cursor: pointer;
            transition: all 0.3s;
            text-align: center;
        }
        .mode-btn.active { border-color: #f7b731; background: rgba(247, 183, 49, 0.1); }
        .mode-btn:hover { background: rgba(255,255,255,0.05); }
        
        .section-title {
            font-size: 1.3rem;
            margin: 30px 0 20px;
            padding-bottom: 10px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        
        .agent-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 15px; }
        .agent-card {
            background: rgba(255,255,255,0.03);
            padding: 15px;
            border-radius: 10px;
            text-align: center;
        }
        .agent-icon { font-size: 2rem; margin-bottom: 10px; }
        .agent-name { font-size: 0.9rem; color: #888; }
        .agent-status { font-size: 0.75rem; margin-top: 5px; }
        .agent-status.online { color: #28a745; }
        .agent-status.offline { color: #dc3545; }
        
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        .loading { animation: pulse 1.5s infinite; }
    </style>
</head>
<body>
    <div class="container">
        <header class="header">
            <div class="logo">🐝 HIVENANCE</div>
            <div class="status-bar">
                <span id="mode-badge" class="status-badge status-dry">Loading...</span>
                <span id="governance-badge" class="status-badge status-governed">Loading...</span>
            </div>
        </header>
        
        <div class="grid">
            <div class="card">
                <div class="card-title">System Status</div>
                <div id="system-status" class="card-value loading">--</div>
                <div class="card-sub" id="system-uptime">Connecting...</div>
            </div>
            <div class="card">
                <div class="card-title">Pending Approvals</div>
                <div id="pending-count" class="card-value loading">0</div>
                <div class="card-sub">Trades awaiting approval</div>
            </div>
            <div class="card">
                <div class="card-title">Gas Savings</div>
                <div id="gas-savings" class="card-value loading">--</div>
                <div class="card-sub">Optimized transactions</div>
            </div>
        </div>
        
        <h2 class="section-title">Governance Mode</h2>
        <div class="mode-toggle">
            <div id="mode-simple" class="mode-btn" onclick="setGovernanceMode('SIMPLE')">
                <div style="font-size: 1.5rem; margin-bottom: 10px;">⚡</div>
                <div style="font-weight: bold;">SIMPLE</div>
                <div style="font-size: 0.8rem; color: #888; margin-top: 5px;">Fast execution, minimal checks</div>
            </div>
            <div id="mode-governed" class="mode-btn" onclick="setGovernanceMode('GOVERNED')">
                <div style="font-size: 1.5rem; margin-bottom: 10px;">🛡️</div>
                <div style="font-weight: bold;">GOVERNED</div>
                <div style="font-size: 0.8rem; color: #888; margin-top: 5px;">Full safety validation</div>
            </div>
        </div>
        
        <h2 class="section-title">Agent Network</h2>
        <div class="agent-grid" id="agent-grid">
            <div class="agent-card">
                <div class="agent-icon">👑</div>
                <div class="agent-name">Queen</div>
                <div class="agent-status online">● Active</div>
            </div>
            <div class="agent-card">
                <div class="agent-icon">🛡️</div>
                <div class="agent-name">Safety</div>
                <div class="agent-status" id="safety-status">● Loading</div>
            </div>
            <div class="agent-card">
                <div class="agent-icon">⛽</div>
                <div class="agent-name">Gas Optimizer</div>
                <div class="agent-status" id="gas-status">● Loading</div>
            </div>
            <div class="agent-card">
                <div class="agent-icon">📊</div>
                <div class="agent-name">Learning</div>
                <div class="agent-status" id="learning-status">● Loading</div>
            </div>
            <div class="agent-card">
                <div class="agent-icon">💼</div>
                <div class="agent-name">Wallet</div>
                <div class="agent-status" id="wallet-status">● Loading</div>
            </div>
            <div class="agent-card">
                <div class="agent-icon">📡</div>
                <div class="agent-name">Market Data</div>
                <div class="agent-status online">● Active</div>
            </div>
        </div>
        
        <h2 class="section-title">Quick Actions</h2>
        <div style="display: flex; flex-wrap: wrap; gap: 10px;">
            <button class="btn btn-primary" onclick="refreshDashboard()" data-testid="refresh-btn">↻ Refresh Data</button>
            <button class="btn btn-secondary" onclick="window.location.href='/api/approvals/pending.json'" data-testid="view-approvals-btn">View Pending Approvals</button>
            <button class="btn btn-secondary" onclick="window.location.href='/api/mobile/dashboard.json'" data-testid="mobile-api-btn">Mobile API</button>
            <button class="btn btn-secondary" onclick="window.location.href='/docs'" data-testid="api-docs-btn">API Docs</button>
        </div>
    </div>
    
    <script>
        const API_BASE = window.location.origin;
        
        async function fetchStatus() {
            try {
                const res = await fetch(API_BASE + '/api/status.json');
                const data = await res.json();
                
                // Update mode badge
                const modeBadge = document.getElementById('mode-badge');
                modeBadge.textContent = data.dry_run ? '🧪 Dry Run' : '🔥 Live';
                modeBadge.className = 'status-badge ' + (data.dry_run ? 'status-dry' : 'status-live');
                
                // Update governance badge
                const govBadge = document.getElementById('governance-badge');
                const mode = data.governance_mode || 'GOVERNED';
                govBadge.textContent = mode === 'SIMPLE' ? '⚡ Simple' : '🛡️ Governed';
                govBadge.className = 'status-badge ' + (mode === 'SIMPLE' ? 'status-simple' : 'status-governed');
                
                // Update mode toggle
                document.getElementById('mode-simple').classList.toggle('active', mode === 'SIMPLE');
                document.getElementById('mode-governed').classList.toggle('active', mode === 'GOVERNED');
                
                // Update system status
                document.getElementById('system-status').textContent = 'Online';
                document.getElementById('system-status').classList.remove('loading');
                document.getElementById('system-uptime').textContent = 'System operational';
            } catch (e) {
                console.error('Status fetch error:', e);
                document.getElementById('system-status').textContent = 'Error';
            }
        }
        
        async function fetchMobileData() {
            try {
                const res = await fetch(API_BASE + '/api/mobile/dashboard.json');
                const data = await res.json();
                
                // Update pending count
                const pending = data.pending_approvals || [];
                document.getElementById('pending-count').textContent = pending.length;
                document.getElementById('pending-count').classList.remove('loading');
                
                // Update agent statuses
                document.getElementById('safety-status').textContent = data.safety?.enabled ? '● Active' : '● Inactive';
                document.getElementById('safety-status').className = 'agent-status ' + (data.safety?.enabled ? 'online' : 'offline');
                
                document.getElementById('gas-status').textContent = data.gas?.enabled ? '● Active' : '● Inactive';
                document.getElementById('gas-status').className = 'agent-status ' + (data.gas?.enabled ? 'online' : 'offline');
                
                document.getElementById('learning-status').textContent = data.learning?.enabled ? '● Active' : '● Inactive';
                document.getElementById('learning-status').className = 'agent-status ' + (data.learning?.enabled ? 'online' : 'offline');
                
                document.getElementById('wallet-status').textContent = '● Active';
                document.getElementById('wallet-status').className = 'agent-status online';
                
                // Gas savings placeholder
                document.getElementById('gas-savings').textContent = 'N/A';
                document.getElementById('gas-savings').classList.remove('loading');
            } catch (e) {
                console.error('Mobile data fetch error:', e);
            }
        }
        
        async function setGovernanceMode(mode) {
            try {
                const res = await fetch(API_BASE + '/api/governance/mode', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({mode: mode})
                });
                const data = await res.json();
                if (data.ok) {
                    fetchStatus();
                    alert('Governance mode set to: ' + mode);
                } else {
                    alert('Error: ' + data.error);
                }
            } catch (e) {
                console.error('Set mode error:', e);
                alert('Failed to set governance mode');
            }
        }
        
        function refreshDashboard() {
            fetchStatus();
            fetchMobileData();
        }
        
        // Initial load
        fetchStatus();
        fetchMobileData();
        
        // Refresh every 10 seconds
        setInterval(refreshDashboard, 10000);
    </script>
</body>
</html>
"""


# ============ WEBSOCKET ENDPOINTS ============

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await manager.connect(websocket)
    try:
        # Send initial state
        await websocket.send_json({
            "type": "init",
            "data": state,
            "timestamp": int(time.time() * 1000)
        })
        
        while True:
            # Wait for messages from client
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=1.0)
                
                # Handle client commands
                if data.get("action") == "set_mode":
                    mode = data.get("mode", "").upper()
                    if mode in ("SIMPLE", "GOVERNED"):
                        state["mode"] = mode
                        await manager.broadcast({
                            "type": "mode_change",
                            "data": {"mode": mode},
                            "timestamp": int(time.time() * 1000)
                        })
                
                elif data.get("action") == "toggle_auto_trade":
                    state["auto_trade"] = not state["auto_trade"]
                    await manager.broadcast({
                        "type": "auto_trade_change",
                        "data": {"auto_trade": state["auto_trade"]},
                        "timestamp": int(time.time() * 1000)
                    })
                
                elif data.get("action") == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": int(time.time() * 1000)})
                    
            except asyncio.TimeoutError:
                # No message received, continue loop
                pass
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logging.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)

# Background task to simulate real-time data updates
async def broadcast_updates():
    """Broadcast state updates every 2 seconds."""
    while True:
        await asyncio.sleep(2)
        
        if manager.active_connections:
            # Simulate price changes
            btc_change = random.uniform(-0.5, 0.5)
            
            # Update worker weights slightly
            for worker in state["worker_weights"]:
                state["worker_weights"][worker] = round(
                    max(0.8, min(1.5, state["worker_weights"][worker] + random.uniform(-0.01, 0.01))), 4
                )
            
            # Update P&L
            state["safety"]["daily_pnl"] = round(state["safety"]["daily_pnl"] + random.uniform(-0.5, 1.0), 4)
            
            update = {
                "type": "update",
                "data": {
                    "mode": state["mode"],
                    "auto_trade": state["auto_trade"],
                    "safety": state["safety"],
                    "worker_weights": state["worker_weights"],
                    "learning": state["learning"],
                    "prices": {
                        "BTC/USD": round(42000 + random.uniform(-500, 500), 2),
                        "ETH/USD": round(2200 + random.uniform(-50, 50), 2),
                    }
                },
                "timestamp": int(time.time() * 1000)
            }
            await manager.broadcast(update)

@app.on_event("startup")
async def startup_event():
    """Start background tasks on server startup."""
    asyncio.create_task(broadcast_updates())
    logging.info("Started WebSocket broadcast task")

# Trade event endpoint - for other agents to push trade updates
@app.post("/api/ws/trade_event")
async def push_trade_event(request: Request):
    """Push a trade event to all WebSocket clients."""
    data = await request.json()
    
    event = {
        "type": "trade",
        "data": {
            "symbol": data.get("symbol", "UNKNOWN"),
            "side": data.get("side", "BUY"),
            "price": data.get("price", 0),
            "quantity": data.get("quantity", 0),
            "pnl": data.get("pnl", 0),
            "status": data.get("status", "EXECUTED"),
        },
        "timestamp": int(time.time() * 1000)
    }
    
    await manager.broadcast(event)
    
    # Update learning stats
    state["learning"]["total_trades"] += 1
    if data.get("pnl", 0) > 0:
        state["learning"]["winning_trades"] += 1
    state["learning"]["win_rate"] = state["learning"]["winning_trades"] / state["learning"]["total_trades"]
    
    return {"ok": True, "broadcast_to": len(manager.active_connections)}

# Alert endpoint - push alerts to all clients
@app.post("/api/ws/alert")
async def push_alert(request: Request):
    """Push an alert to all WebSocket clients."""
    data = await request.json()
    
    alert = {
        "type": "alert",
        "data": {
            "level": data.get("level", "INFO"),
            "message": data.get("message", ""),
            "source": data.get("source", "system"),
        },
        "timestamp": int(time.time() * 1000)
    }
    
    await manager.broadcast(alert)
    return {"ok": True, "broadcast_to": len(manager.active_connections)}

