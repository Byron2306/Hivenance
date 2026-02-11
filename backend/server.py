"""
Backend server that runs the ORIGINAL Hivenance Flask UI.
Serves on port 8001 as required by the Emergent platform.
"""
import sys
import os
import time

# Add app root to path
sys.path.insert(0, '/app')

from fastapi import FastAPI
from fastapi.middleware.wsgi import WSGIMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from agents.ui_agent import UIAgent

class Config:
    """Minimal config for standalone UI mode."""
    def __init__(self):
        self.feed_buffer_trades = 500
        self.feed_buffer_logs = 1000
        self.allowed_ips = []
        self.ui_host = "0.0.0.0"
        self.ui_port = 8001
        self.dry_run = True
        self.exchange = "kraken"
        self.symbol = "ETH/USD"
        self.governance_mode = "GOVERNED"

class Coordinator:
    """Minimal coordinator for standalone UI mode."""
    def __init__(self):
        self.cfg = Config()
        self.agents = {}
        self.data_cache = {}
        self.running = True
        self.agent_health = {}
    
    def get_shared_data(self, key):
        return self.data_cache.get(key)
    
    def share_data(self, key, value):
        self.data_cache[key] = value

# Initialize coordinator and Flask UI
coordinator = Coordinator()
ui_agent = UIAgent(coordinator=coordinator, host="0.0.0.0", port=8001)

# Create FastAPI wrapper
app = FastAPI(title="Hivenance Trading System")

# Add CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cache buster - unique path that changes
CACHE_BUSTER = str(int(time.time()))

@app.get("/api/v2")
async def api_v2_redirect():
    """Redirect to dashboard with cache buster."""
    return RedirectResponse(url=f"/api/dashboard/{CACHE_BUSTER}/")

# Mount the original Flask UI at a unique path to bypass cache
app.mount(f"/api/dashboard/{CACHE_BUSTER}", WSGIMiddleware(ui_agent.app))

# Also mount at standard locations
app.mount("/api/dashboard", WSGIMiddleware(ui_agent.app))
app.mount("/", WSGIMiddleware(ui_agent.app))
