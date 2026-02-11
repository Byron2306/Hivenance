"""
Backend server that runs the ORIGINAL Hivenance Flask UI.
Serves on port 8001 as required by the Emergent platform.
"""
import sys
import os

# Add app root to path
sys.path.insert(0, '/app')

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

# Initialize and create the Flask app
coordinator = Coordinator()
ui_agent = UIAgent(coordinator=coordinator, host="0.0.0.0", port=8001)

# Export the Flask app for uvicorn
app = ui_agent.app

if __name__ == "__main__":
    print("Starting Hivenance UI on http://0.0.0.0:8001")
    ui_agent.app.run(host="0.0.0.0", port=8001, debug=False, use_reloader=False)
