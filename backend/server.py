"""
Backend server that runs the ORIGINAL Hivenance Flask UI.
The Flask app is mounted at /api/ which is where the platform routes backend requests.
"""
import sys
import os

sys.path.insert(0, '/app')

from fastapi import FastAPI
from fastapi.middleware.wsgi import WSGIMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from agents.ui_agent import UIAgent

class Config:
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

# Initialize
coordinator = Coordinator()
ui_agent = UIAgent(coordinator=coordinator, host="0.0.0.0", port=8001)

# Create FastAPI
app = FastAPI(title="Hivenance")

_cors_origins_env = os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
_cors_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# Redirect root to /api/
@app.get("/")
async def root_redirect():
    return RedirectResponse(url="/api/")

# Mount Flask UI at /api/ - this is where external requests are routed
app.mount("/api", WSGIMiddleware(ui_agent.app))
