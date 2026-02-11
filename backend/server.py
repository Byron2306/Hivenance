"""
Backend server that runs the ORIGINAL Hivenance Flask UI.
"""
import sys
import os

sys.path.insert(0, '/app')

from fastapi import FastAPI, Request
from fastapi.middleware.wsgi import WSGIMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Flask UI at root - this serves at localhost:8001/
app.mount("/", WSGIMiddleware(ui_agent.app))
