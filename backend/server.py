"""
FastAPI server that mounts the original Flask UI Agent with WebSocket support.
This serves the ORIGINAL Hivenance dashboard with bee agents, oracles, etc.
"""
import sys
import os
import logging
import time
import json
import asyncio
import random
from typing import List

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.wsgi import WSGIMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Import the original UI Agent
from agents.ui_agent import UIAgent

# Create a minimal coordinator for standalone mode
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

# Initialize coordinator and the original UI agent
coordinator = MinimalCoordinator()
ui_agent = UIAgent(coordinator=coordinator, host="0.0.0.0", port=8001)

# Create FastAPI app
app = FastAPI(title="Hivenance Trading System", description="Multi-agent crypto trading platform with WebSocket support")

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logging.info(f"WebSocket connected. Total: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logging.info(f"WebSocket disconnected. Total: {len(self.active_connections)}")
    
    async def broadcast(self, message: dict):
        disconnected = []
        for conn in self.active_connections:
            try:
                await conn.send_json(message)
            except Exception:
                disconnected.append(conn)
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

# System state for WebSocket broadcasts
state = {
    "mode": "GOVERNED",
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
        "win_rate": 0.2857,
        "top_coins": [
            {"symbol": "BTC/USD", "score": 1.0},
            {"symbol": "ETH/USD", "score": 0.8},
        ]
    },
    "worker_weights": {
        "SMA": 1.10,
        "RSI": 1.0,
        "BREAKOUT": 1.0,
        "MOMENTUM": 1.0
    }
}

# ============ WebSocket Endpoint ============

@app.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time WebSocket endpoint for live updates."""
    await manager.connect(websocket)
    try:
        # Send initial state
        await websocket.send_json({
            "type": "init",
            "data": state,
            "timestamp": int(time.time() * 1000)
        })
        
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=1.0)
                
                if data.get("action") == "set_mode":
                    mode = data.get("mode", "").upper()
                    if mode in ("SIMPLE", "GOVERNED"):
                        state["mode"] = mode
                        coordinator.cfg.governance_mode = mode
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
                pass
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logging.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)

# Background task for real-time updates
async def broadcast_updates():
    """Broadcast updates every 2 seconds."""
    while True:
        await asyncio.sleep(2)
        if manager.active_connections:
            # Simulate live data updates
            for worker in state["worker_weights"]:
                state["worker_weights"][worker] = round(
                    max(0.8, min(1.5, state["worker_weights"][worker] + random.uniform(-0.01, 0.01))), 4
                )
            state["safety"]["daily_pnl"] = round(state["safety"]["daily_pnl"] + random.uniform(-0.5, 1.0), 4)
            
            await manager.broadcast({
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
            })

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(broadcast_updates())
    logging.info("Started WebSocket broadcast task")

# ============ REST API Endpoints (for frontend) ============

@app.get("/api/status")
async def api_status():
    """Full status for React frontend."""
    return state

@app.post("/api/mode")
async def api_set_mode(request: Request):
    """Set governance mode."""
    data = await request.json()
    mode = data.get("mode", "").upper()
    if mode in ("SIMPLE", "GOVERNED"):
        state["mode"] = mode
        coordinator.cfg.governance_mode = mode
    return {"mode": state["mode"]}

@app.post("/api/auto_trade")
async def api_auto_trade(request: Request):
    """Toggle auto trade."""
    data = await request.json()
    state["auto_trade"] = bool(data.get("enabled", False))
    return {"auto_trade": state["auto_trade"]}

@app.post("/api/safety/reset")
async def api_safety_reset():
    """Reset circuit breaker."""
    state["safety"]["circuit_breaker"] = False
    state["safety"]["consecutive_losses"] = 0
    return {"ok": True, "safety": state["safety"]}

@app.post("/api/ws/trade_event")
async def push_trade_event(request: Request):
    """Push trade event to WebSocket clients."""
    data = await request.json()
    event = {
        "type": "trade",
        "data": {
            "symbol": data.get("symbol", "UNKNOWN"),
            "side": data.get("side", "BUY"),
            "price": data.get("price", 0),
            "quantity": data.get("quantity", 0),
            "pnl": data.get("pnl", 0),
        },
        "timestamp": int(time.time() * 1000)
    }
    await manager.broadcast(event)
    state["learning"]["total_trades"] += 1
    if data.get("pnl", 0) > 0:
        state["learning"]["winning_trades"] += 1
    state["learning"]["win_rate"] = state["learning"]["winning_trades"] / state["learning"]["total_trades"]
    return {"ok": True, "broadcast_to": len(manager.active_connections)}

@app.post("/api/ws/alert")
async def push_alert(request: Request):
    """Push alert to WebSocket clients."""
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

# ============ Mount Original Flask UI ============
# This serves the ORIGINAL dashboard with bee agents, oracles, strategy workers, etc.
app.mount("/", WSGIMiddleware(ui_agent.app))
