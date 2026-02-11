"""
Standalone Crypto Trading Dashboard Server

This server provides:
1. Web dashboard for trading system monitoring
2. API endpoints for learning, safety, gas optimization
3. Mobile-friendly dashboard endpoint
4. Trade approval management

Runs on port 8001 for compatibility with Emergent platform.
"""

import os
import sys
import time
import json
import logging
import threading

# Add app to path
sys.path.insert(0, '/app')

from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS

# Import our new systems
from agents.learning_engine import LearningEngine
from agents.gas_optimizer import GasOptimizer
from agents.safety_system import FoolproofSafetySystem
from agents.adaptive_coin_selector import AdaptiveCoinSelector

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Initialize systems
learning_engine = None
gas_optimizer = None
safety_system = None
coin_selector = None

# Trading mode: SIMPLE or GOVERNED
trading_mode = "SIMPLE"  # Default to efficient mode

def init_systems():
    """Initialize all trading systems."""
    global learning_engine, gas_optimizer, safety_system, coin_selector
    
    try:
        learning_engine = LearningEngine(coordinator=None, db_path="data/learning.db")
        learning_engine.approval_threshold_usd = 10.0
        learning_engine.set_auto_trade(False)
        logger.info("Learning Engine initialized")
    except Exception as e:
        logger.error(f"Failed to init Learning Engine: {e}")
    
    try:
        gas_optimizer = GasOptimizer(coordinator=None)
        logger.info("Gas Optimizer initialized")
    except Exception as e:
        logger.error(f"Failed to init Gas Optimizer: {e}")
    
    try:
        safety_system = FoolproofSafetySystem(
            coordinator=None,
            learning_engine=learning_engine,
            gas_optimizer=gas_optimizer
        )
        logger.info("Safety System initialized")
    except Exception as e:
        logger.error(f"Failed to init Safety System: {e}")
    
    try:
        coin_selector = AdaptiveCoinSelector(
            coordinator=None,
            learning_engine=learning_engine
        )
        logger.info("Adaptive Coin Selector initialized")
    except Exception as e:
        logger.error(f"Failed to init Coin Selector: {e}")

# Dashboard HTML template
DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🐝 Hive Trading System</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            background: #0a0a0f;
            color: #e0e0e0;
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 {
            font-size: 2rem;
            margin-bottom: 20px;
            color: #ffd700;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .mode-badge {
            font-size: 0.8rem;
            padding: 4px 12px;
            border-radius: 20px;
            background: #1a1a2e;
            border: 1px solid #333;
        }
        .mode-simple { border-color: #4ade80; color: #4ade80; }
        .mode-governed { border-color: #f59e0b; color: #f59e0b; }
        
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .card {
            background: #12121a;
            border: 1px solid #1e1e2e;
            border-radius: 12px;
            padding: 20px;
        }
        .card h2 {
            font-size: 1rem;
            color: #888;
            margin-bottom: 15px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .stat {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #1e1e2e;
        }
        .stat:last-child { border-bottom: none; }
        .stat-label { color: #666; }
        .stat-value { font-weight: bold; }
        .stat-value.green { color: #4ade80; }
        .stat-value.red { color: #f87171; }
        .stat-value.yellow { color: #fbbf24; }
        
        .toggle-group {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }
        .toggle-btn {
            flex: 1;
            padding: 12px 20px;
            border: 1px solid #333;
            background: #1a1a2e;
            color: #888;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
            font-family: inherit;
        }
        .toggle-btn:hover { border-color: #555; }
        .toggle-btn.active {
            background: #2d2d4a;
            color: #fff;
            border-color: #4ade80;
        }
        
        .approval-card {
            background: #1a1520;
            border: 1px solid #4a3a5a;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 10px;
        }
        .approval-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 10px;
        }
        .approval-symbol { font-weight: bold; color: #ffd700; }
        .approval-amount { color: #4ade80; }
        .approval-actions {
            display: flex;
            gap: 10px;
        }
        .btn {
            padding: 8px 20px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-family: inherit;
            font-weight: bold;
        }
        .btn-approve { background: #4ade80; color: #000; }
        .btn-reject { background: #f87171; color: #000; }
        .btn-approve:hover { background: #22c55e; }
        .btn-reject:hover { background: #ef4444; }
        
        .status-indicator {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            margin-right: 8px;
        }
        .status-green { background: #4ade80; box-shadow: 0 0 10px #4ade80; }
        .status-red { background: #f87171; box-shadow: 0 0 10px #f87171; }
        .status-yellow { background: #fbbf24; box-shadow: 0 0 10px #fbbf24; }
        
        .top-coins {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }
        .coin-badge {
            padding: 6px 12px;
            background: #1e1e2e;
            border-radius: 20px;
            font-size: 0.85rem;
        }
        .coin-score {
            color: #4ade80;
            margin-left: 5px;
        }
        
        @media (max-width: 768px) {
            body { padding: 10px; }
            h1 { font-size: 1.5rem; }
            .grid { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>
            🐝 Hive Trading System
            <span class="mode-badge mode-{{ mode.lower() }}">{{ mode }} MODE</span>
        </h1>
        
        <div class="toggle-group">
            <button class="toggle-btn {{ 'active' if mode == 'SIMPLE' else '' }}" onclick="setMode('SIMPLE')">
                ⚡ SIMPLE (Fast)
            </button>
            <button class="toggle-btn {{ 'active' if mode == 'GOVERNED' else '' }}" onclick="setMode('GOVERNED')">
                🏛️ GOVERNED (Safe)
            </button>
        </div>
        
        <div class="grid">
            <!-- Safety Status -->
            <div class="card">
                <h2>🛡️ Safety Status</h2>
                <div class="stat">
                    <span class="stat-label">Status</span>
                    <span class="stat-value">
                        <span class="status-indicator status-{{ 'green' if safety.safety_level == 'GREEN' else 'red' if safety.safety_level == 'RED' else 'yellow' }}"></span>
                        {{ safety.safety_level }}
                    </span>
                </div>
                <div class="stat">
                    <span class="stat-label">Circuit Breaker</span>
                    <span class="stat-value {{ 'red' if safety.circuit_breaker_active else 'green' }}">
                        {{ 'ACTIVE' if safety.circuit_breaker_active else 'OK' }}
                    </span>
                </div>
                <div class="stat">
                    <span class="stat-label">Consecutive Losses</span>
                    <span class="stat-value">{{ safety.consecutive_losses }} / 5</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Daily PnL</span>
                    <span class="stat-value {{ 'green' if safety.daily_pnl >= 0 else 'red' }}">
                        ${{ "%.4f"|format(safety.daily_pnl) }}
                    </span>
                </div>
                <div class="stat">
                    <span class="stat-label">Trades This Hour</span>
                    <span class="stat-value">{{ safety.trades_this_hour }} / 10</span>
                </div>
            </div>
            
            <!-- Learning Status -->
            <div class="card">
                <h2>🧠 Learning Engine</h2>
                <div class="stat">
                    <span class="stat-label">Auto-Trade</span>
                    <span class="stat-value {{ 'green' if learning.auto_trade_enabled else 'yellow' }}">
                        {{ 'ENABLED' if learning.auto_trade_enabled else 'MANUAL' }}
                    </span>
                </div>
                <div class="stat">
                    <span class="stat-label">Coins Tracked</span>
                    <span class="stat-value">{{ learning.total_coins_tracked }}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Profitable Coins</span>
                    <span class="stat-value green">{{ learning.profitable_coins }}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Approval Threshold</span>
                    <span class="stat-value">${{ "%.2f"|format(learning.approval_threshold_usd) }}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Risk Tolerance</span>
                    <span class="stat-value">{{ "%.0f"|format(learning.risk_tolerance * 100) }}%</span>
                </div>
            </div>
            
            <!-- Gas Optimizer -->
            <div class="card">
                <h2>⛽ Gas Optimizer</h2>
                <div class="stat">
                    <span class="stat-label">Network</span>
                    <span class="stat-value green">{{ gas.primary_network|upper }}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Gas per Trade</span>
                    <span class="stat-value green">${{ "%.4f"|format(gas.estimated_gas_per_trade) }}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Total Saved</span>
                    <span class="stat-value green">${{ "%.4f"|format(gas.total_gas_saved_usd) }}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Batching</span>
                    <span class="stat-value {{ 'green' if gas.batch_enabled else 'yellow' }}">
                        {{ 'ENABLED' if gas.batch_enabled else 'DISABLED' }}
                    </span>
                </div>
                <div class="stat">
                    <span class="stat-label">Pending Batch</span>
                    <span class="stat-value">{{ gas.pending_batch.count }} trades</span>
                </div>
            </div>
            
            <!-- Top Coins -->
            <div class="card">
                <h2>🏆 Top Performing Coins</h2>
                <div class="top-coins">
                    {% for coin in top_coins %}
                    <span class="coin-badge">
                        {{ coin.symbol }}
                        <span class="coin-score">{{ "%.0f"|format(coin.score * 100) }}%</span>
                    </span>
                    {% else %}
                    <span style="color: #666;">No coins tracked yet</span>
                    {% endfor %}
                </div>
            </div>
        </div>
        
        <!-- Pending Approvals -->
        <div class="card">
            <h2>📋 Pending Approvals ({{ pending_approvals|length }})</h2>
            {% for approval in pending_approvals %}
            <div class="approval-card">
                <div class="approval-header">
                    <span class="approval-symbol">{{ approval.symbol }}</span>
                    <span class="approval-amount">${{ "%.2f"|format(approval.amount_usd) }}</span>
                </div>
                <div class="approval-actions">
                    <button class="btn btn-approve" onclick="approveTradeAction('{{ approval.trade_id }}', true)">
                        ✓ APPROVE
                    </button>
                    <button class="btn btn-reject" onclick="approveTradeAction('{{ approval.trade_id }}', false)">
                        ✗ REJECT
                    </button>
                </div>
            </div>
            {% else %}
            <p style="color: #666; padding: 20px 0;">No pending approvals</p>
            {% endfor %}
        </div>
        
        <!-- Auto-Trade Toggle -->
        <div class="card" style="margin-top: 20px;">
            <h2>⚙️ Controls</h2>
            <div class="toggle-group">
                <button class="toggle-btn {{ 'active' if learning.auto_trade_enabled else '' }}" 
                        onclick="toggleAutoTrade({{ 'false' if learning.auto_trade_enabled else 'true' }})">
                    {{ '🔴 Disable Auto-Trade' if learning.auto_trade_enabled else '🟢 Enable Auto-Trade' }}
                </button>
                {% if safety.circuit_breaker_active %}
                <button class="toggle-btn" onclick="resetCircuitBreaker()">
                    🔄 Reset Circuit Breaker
                </button>
                {% endif %}
            </div>
        </div>
    </div>
    
    <script>
        function setMode(mode) {
            fetch('/api/mode', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({mode: mode})
            }).then(() => location.reload());
        }
        
        function toggleAutoTrade(enabled) {
            fetch('/api/learning/auto_trade', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({enabled: enabled})
            }).then(() => location.reload());
        }
        
        function approveTradeAction(tradeId, approved) {
            fetch('/api/approvals/action', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({trade_id: tradeId, action: approved ? 'APPROVE' : 'REJECT'})
            }).then(() => location.reload());
        }
        
        function resetCircuitBreaker() {
            fetch('/api/safety/circuit_breaker', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({action: 'RESET', reason: 'manual_ui_reset'})
            }).then(() => location.reload());
        }
        
        // Auto-refresh every 10 seconds
        setTimeout(() => location.reload(), 10000);
    </script>
</body>
</html>
'''

@app.route('/')
def dashboard():
    """Render main dashboard."""
    # Gather all status data
    safety_status = safety_system.get_safety_status() if safety_system else {
        'safety_level': 'UNKNOWN', 'circuit_breaker_active': False,
        'consecutive_losses': 0, 'daily_pnl': 0, 'trades_this_hour': 0
    }
    
    learning_status = learning_engine.get_system_health() if learning_engine else {
        'auto_trade_enabled': False, 'total_coins_tracked': 0,
        'profitable_coins': 0, 'risk_tolerance': 0.5
    }
    learning_status['approval_threshold_usd'] = learning_engine.approval_threshold_usd if learning_engine else 10.0
    
    gas_status = gas_optimizer.get_gas_report() if gas_optimizer else {
        'primary_network': 'base', 'estimated_gas_per_trade': 0.001,
        'total_gas_saved_usd': 0, 'batch_enabled': True,
        'pending_batch': {'count': 0}
    }
    
    top_coins = []
    if learning_engine:
        top_coins = [{'symbol': s, 'score': sc} for s, sc in learning_engine.get_top_coins(5)]
    
    pending = learning_engine.get_pending_approvals() if learning_engine else []
    
    return render_template_string(
        DASHBOARD_HTML,
        mode=trading_mode,
        safety=safety_status,
        learning=learning_status,
        gas=gas_status,
        top_coins=top_coins,
        pending_approvals=pending
    )

@app.route('/api/health')
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'ok',
        'mode': trading_mode,
        'learning': learning_engine is not None,
        'safety': safety_system is not None,
        'gas': gas_optimizer is not None
    })

@app.route('/api/mode', methods=['GET', 'POST'])
def mode_endpoint():
    """Get or set trading mode."""
    global trading_mode
    if request.method == 'POST':
        data = request.json or {}
        new_mode = data.get('mode', 'SIMPLE').upper()
        if new_mode in ['SIMPLE', 'GOVERNED']:
            trading_mode = new_mode
            logger.info(f"Trading mode changed to: {trading_mode}")
    return jsonify({'mode': trading_mode})

@app.route('/api/learning/status.json')
def learning_status():
    """Get learning engine status."""
    if not learning_engine:
        return jsonify({'error': 'Learning engine not initialized'}), 400
    return jsonify({
        'health': learning_engine.get_system_health(),
        'top_coins': [{'symbol': s, 'score': sc} for s, sc in learning_engine.get_top_coins(10)],
        'worker_weights': learning_engine.get_worker_weights()
    })

@app.route('/api/learning/auto_trade', methods=['GET', 'POST'])
def auto_trade():
    """Toggle auto-trade mode."""
    if not learning_engine:
        return jsonify({'error': 'Learning engine not initialized'}), 400
    
    if request.method == 'POST':
        data = request.json or {}
        enabled = str(data.get('enabled', 'false')).lower() in ('true', '1', 'yes')
        learning_engine.set_auto_trade(enabled)
    
    return jsonify({
        'auto_trade_enabled': learning_engine.auto_trade_enabled,
        'approval_threshold_usd': learning_engine.approval_threshold_usd
    })

@app.route('/api/safety/status.json')
def safety_status():
    """Get safety system status."""
    if not safety_system:
        return jsonify({'error': 'Safety system not initialized'}), 400
    return jsonify(safety_system.get_safety_status())

@app.route('/api/safety/circuit_breaker', methods=['GET', 'POST'])
def circuit_breaker():
    """Get or reset circuit breaker."""
    if not safety_system:
        return jsonify({'error': 'Safety system not initialized'}), 400
    
    if request.method == 'POST':
        data = request.json or {}
        action = str(data.get('action', '')).upper()
        reason = data.get('reason', 'api_reset')
        if action == 'RESET':
            safety_system.reset_circuit_breaker(reason)
    
    status = safety_system.get_safety_status()
    return jsonify({
        'circuit_breaker_active': status.get('circuit_breaker_active'),
        'circuit_breaker_reason': status.get('circuit_breaker_reason'),
        'safety_level': status.get('safety_level')
    })

@app.route('/api/gas/status.json')
def gas_status():
    """Get gas optimizer status."""
    if not gas_optimizer:
        return jsonify({'error': 'Gas optimizer not initialized'}), 400
    return jsonify({
        'report': gas_optimizer.get_gas_report(),
        'timing': gas_optimizer.get_optimal_timing(),
        'pending_batch': gas_optimizer.get_pending_batch()
    })

@app.route('/api/approvals/pending.json')
def pending_approvals():
    """Get pending trade approvals."""
    if not learning_engine:
        return jsonify({'pending': []})
    return jsonify({'pending': learning_engine.get_pending_approvals()})

@app.route('/api/approvals/action', methods=['POST'])
def approval_action():
    """Approve or reject a trade."""
    if not learning_engine:
        return jsonify({'ok': False, 'error': 'Learning engine not initialized'}), 400
    
    data = request.json or {}
    trade_id = data.get('trade_id')
    action = str(data.get('action', '')).upper()
    
    if not trade_id:
        return jsonify({'ok': False, 'error': 'trade_id required'}), 400
    if action not in ('APPROVE', 'REJECT'):
        return jsonify({'ok': False, 'error': 'action must be APPROVE or REJECT'}), 400
    
    ok = learning_engine.process_approval(trade_id, action == 'APPROVE', 'USER_UI')
    return jsonify({'ok': ok, 'trade_id': trade_id, 'action': action})

@app.route('/api/mobile/dashboard.json')
def mobile_dashboard():
    """Combined endpoint for mobile access."""
    result = {'ts': int(time.time() * 1000), 'mode': trading_mode}
    
    if learning_engine:
        result['learning'] = {
            'health': learning_engine.get_system_health(),
            'top_coins': [{'symbol': s, 'score': sc} for s, sc in learning_engine.get_top_coins(5)],
            'pending_approvals': len(learning_engine.get_pending_approvals())
        }
    
    if safety_system:
        result['safety'] = safety_system.get_safety_status()
    
    if gas_optimizer:
        result['gas'] = gas_optimizer.get_gas_report()
    
    return jsonify(result)

if __name__ == '__main__':
    print("=" * 50)
    print("🐝 Hive Trading System Dashboard")
    print("=" * 50)
    
    # Initialize all systems
    init_systems()
    
    # Run server
    port = int(os.environ.get('PORT', 8001))
    print(f"Starting server on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
