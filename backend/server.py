"""
FastAPI wrapper that mounts the existing Flask UI agent.
This allows the custom multi-agent trading system to work with the Emergent platform's
supervisor configuration which expects a FastAPI server on port 8001.
"""
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.middleware.wsgi import WSGIMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

# Import the Flask UI setup
from agents.ui_agent import UIAgent

# Create a minimal coordinator-like object for standalone UI mode
class MinimalConfig:
    def __init__(self):
        self.feed_buffer_trades = 500
        self.feed_buffer_logs = 1000
        self.allowed_ips = []
        self.ui_host = "0.0.0.0"
        self.ui_port = 8001

class MinimalCoordinator:
    def __init__(self):
        self.cfg = MinimalConfig()
        self.agents = {}
        self.data_cache = {}
        self.running = True
    
    def get_shared_data(self, key):
        return self.data_cache.get(key)
    
    def share_data(self, key, value):
        self.data_cache[key] = value

# Initialize coordinator and UI agent
coordinator = MinimalCoordinator()
ui_agent = UIAgent(coordinator=coordinator, host="0.0.0.0", port=8001)

# Create FastAPI app
app = FastAPI(title="Hivenance Trading System", description="Multi-agent crypto trading platform")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the Flask app under /api
app.mount("/api", WSGIMiddleware(ui_agent.app))

# Root route redirects to the Flask UI
@app.get("/")
async def root():
    return RedirectResponse(url="/api/")

# Health check endpoint
@app.get("/health")
async def health():
    return {"status": "healthy", "service": "hivenance"}
