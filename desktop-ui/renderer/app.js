// State management
let backendUrl = 'http://127.0.0.1:5000';
let autoRefreshInterval = null;
let isConnected = false;

// Initialize app
async function init() {
    // Get backend URL from main process
    backendUrl = await window.electronAPI.getBackendUrl();
    document.getElementById('backend-url').value = backendUrl;

    // Set up navigation
    setupNavigation();

    // Set up event listeners
    setupEventListeners();

    // Load initial data
    await checkConnection();
    loadDashboardData();

    // Set up auto-refresh if enabled
    const autoRefresh = localStorage.getItem('autoRefresh') === 'true';
    document.getElementById('auto-refresh').checked = autoRefresh;
    if (autoRefresh) {
        startAutoRefresh();
    }
}

// Navigation
function setupNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', () => {
            // Update active nav item
            navItems.forEach(nav => nav.classList.remove('active'));
            item.classList.add('active');

            // Show corresponding view
            const viewName = item.dataset.view;
            showView(viewName);
        });
    });
}

function showView(viewName) {
    const views = document.querySelectorAll('.view');
    views.forEach(view => view.classList.remove('active'));
    
    const targetView = document.getElementById(`${viewName}-view`);
    if (targetView) {
        targetView.classList.add('active');
        
        // Load data for specific views
        switch(viewName) {
            case 'agents':
                loadAgentsData();
                break;
            case 'trades':
                loadTradesData();
                break;
            case 'performance':
                loadPerformanceData();
                break;
            case 'logs':
                loadLogsData();
                break;
        }
    }
}

// Event listeners
function setupEventListeners() {
    // Settings
    document.getElementById('save-backend-url').addEventListener('click', async () => {
        const newUrl = document.getElementById('backend-url').value;
        await window.electronAPI.setBackendUrl(newUrl);
        backendUrl = newUrl;
        await checkConnection();
        showNotification('Backend URL updated', 'success');
    });

    document.getElementById('test-connection-btn').addEventListener('click', async () => {
        const result = await checkConnection();
        const resultElement = document.getElementById('connection-test-result');
        if (result) {
            resultElement.textContent = '✓ Connected';
            resultElement.style.color = 'var(--success)';
        } else {
            resultElement.textContent = '✗ Connection failed';
            resultElement.style.color = 'var(--error)';
        }
    });

    document.getElementById('auto-refresh').addEventListener('change', (e) => {
        localStorage.setItem('autoRefresh', e.target.checked);
        if (e.target.checked) {
            startAutoRefresh();
        } else {
            stopAutoRefresh();
        }
    });

    // Logs
    document.getElementById('clear-logs-btn').addEventListener('click', () => {
        document.getElementById('logs-container').innerHTML = '<p class="loading-text">Logs cleared</p>';
    });

    document.getElementById('refresh-logs-btn').addEventListener('click', loadLogsData);

    // Listen for IPC events
    window.electronAPI.onShowSettings(() => {
        showView('settings');
    });

    window.electronAPI.onShowAbout(() => {
        alert('Hivenance Trading Agent v1.0.0\n\nA sophisticated multi-agent trading system for cryptocurrency markets.');
    });
}

// Auto-refresh
function startAutoRefresh() {
    if (autoRefreshInterval) return;
    autoRefreshInterval = setInterval(() => {
        const activeView = document.querySelector('.view.active');
        if (activeView) {
            const viewId = activeView.id.replace('-view', '');
            if (viewId === 'dashboard') {
                loadDashboardData();
            }
        }
    }, 5000);
}

function stopAutoRefresh() {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
        autoRefreshInterval = null;
    }
}

// API calls
async function fetchAPI(endpoint) {
    try {
        const response = await fetch(`${backendUrl}${endpoint}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error('API fetch error:', error);
        return null;
    }
}

async function checkConnection() {
    try {
        const response = await fetch(`${backendUrl}/api/status`, { 
            method: 'GET',
            timeout: 5000 
        });
        isConnected = response.ok;
        updateConnectionStatus();
        return isConnected;
    } catch (error) {
        isConnected = false;
        updateConnectionStatus();
        return false;
    }
}

function updateConnectionStatus() {
    const statusBadge = document.getElementById('connection-status');
    if (isConnected) {
        statusBadge.classList.add('connected');
        statusBadge.classList.remove('disconnected');
    } else {
        statusBadge.classList.remove('connected');
        statusBadge.classList.add('disconnected');
    }
}

// Data loading functions
async function loadDashboardData() {
    const data = await fetchAPI('/api/status');
    if (!data) return;

    // Update wallet balance
    if (data.wallet) {
        const balance = data.wallet.total_usd || 0;
        document.getElementById('wallet-balance').textContent = `$${balance.toFixed(2)}`;
    }

    // Update active symbol
    if (data.symbol) {
        document.getElementById('active-symbol').textContent = data.symbol;
    }

    // Update current price
    if (data.market && data.market.price) {
        document.getElementById('current-price').textContent = `$${parseFloat(data.market.price).toFixed(2)}`;
    }

    // Update 24h change
    if (data.market && data.market.change_24h !== undefined) {
        const change = data.market.change_24h;
        const changeElement = document.getElementById('price-change');
        changeElement.textContent = `${change >= 0 ? '+' : ''}${change.toFixed(2)}%`;
        changeElement.style.color = change >= 0 ? 'var(--success)' : 'var(--error)';
    }

    // Update mode badge
    const modeBadge = document.getElementById('mode-badge');
    if (data.dry_run === false || data.live === true) {
        modeBadge.textContent = 'LIVE';
        modeBadge.className = 'mode-badge live';
    } else {
        modeBadge.textContent = 'DRY RUN';
        modeBadge.className = 'mode-badge dry-run';
    }

    // Update system status
    document.getElementById('killswitch-status').textContent = 
        data.kill_switch_active ? 'TRIGGERED' : 'ARMED';
    document.getElementById('killswitch-status').style.color = 
        data.kill_switch_active ? 'var(--error)' : 'var(--success)';

    document.getElementById('trading-mode').textContent = 
        data.dry_run ? 'Dry Run' : 'Live Trading';
    
    if (data.agents) {
        const activeCount = Object.values(data.agents).filter(a => a.status === 'active').length;
        document.getElementById('active-agents').textContent = 
            `${activeCount} / ${Object.keys(data.agents).length}`;
    }
}

async function loadAgentsData() {
    const data = await fetchAPI('/api/status');
    if (!data || !data.agents) return;

    const container = document.getElementById('agents-container');
    container.innerHTML = '';

    Object.entries(data.agents).forEach(([name, agent]) => {
        const card = document.createElement('div');
        card.className = 'agent-card';
        
        const statusClass = agent.status === 'active' ? 'active' : 'inactive';
        
        card.innerHTML = `
            <h4>
                <span class="agent-status ${statusClass}"></span>
                ${name}
            </h4>
            <div class="status-item">
                <span class="status-label">Status:</span>
                <span class="status-value">${agent.status || 'unknown'}</span>
            </div>
            <div class="status-item">
                <span class="status-label">Uptime:</span>
                <span class="status-value">${agent.uptime || '-'}</span>
            </div>
            ${agent.last_action ? `
                <div class="status-item">
                    <span class="status-label">Last Action:</span>
                    <span class="status-value">${agent.last_action}</span>
                </div>
            ` : ''}
        `;
        
        container.appendChild(card);
    });
}

async function loadTradesData() {
    const data = await fetchAPI('/api/trades');
    if (!data || !data.trades) return;

    const tbody = document.getElementById('trades-tbody');
    tbody.innerHTML = '';

    if (data.trades.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="loading-text">No trades yet</td></tr>';
        return;
    }

    data.trades.slice(0, 50).forEach(trade => {
        const row = document.createElement('tr');
        const sideClass = trade.side === 'BUY' ? 'trade-buy' : 'trade-sell';
        
        row.innerHTML = `
            <td>${new Date(trade.timestamp).toLocaleString()}</td>
            <td class="${sideClass}">${trade.side}</td>
            <td>${trade.symbol}</td>
            <td>${parseFloat(trade.amount).toFixed(6)}</td>
            <td>$${parseFloat(trade.price).toFixed(2)}</td>
            <td>${trade.status || 'completed'}</td>
        `;
        
        tbody.appendChild(row);
    });
}

async function loadPerformanceData() {
    const data = await fetchAPI('/api/performance');
    if (!data) return;

    if (data.total_pnl !== undefined) {
        const pnlElement = document.getElementById('total-pnl');
        pnlElement.textContent = `$${data.total_pnl.toFixed(2)}`;
        pnlElement.style.color = data.total_pnl >= 0 ? 'var(--success)' : 'var(--error)';
    }

    if (data.win_rate !== undefined) {
        document.getElementById('win-rate').textContent = `${(data.win_rate * 100).toFixed(1)}%`;
    }

    if (data.total_trades !== undefined) {
        document.getElementById('total-trades').textContent = data.total_trades;
    }

    if (data.sharpe_ratio !== undefined) {
        document.getElementById('sharpe-ratio').textContent = data.sharpe_ratio.toFixed(2);
    }
}

async function loadLogsData() {
    const data = await fetchAPI('/api/logs');
    if (!data || !data.logs) return;

    const container = document.getElementById('logs-container');
    container.innerHTML = '';

    if (data.logs.length === 0) {
        container.innerHTML = '<p class="loading-text">No logs available</p>';
        return;
    }

    data.logs.slice(0, 200).forEach(log => {
        const entry = document.createElement('div');
        entry.className = `log-entry ${log.level ? log.level.toLowerCase() : ''}`;
        entry.textContent = `[${new Date(log.timestamp).toLocaleTimeString()}] ${log.message}`;
        container.appendChild(entry);
    });

    // Auto-scroll to bottom
    container.scrollTop = container.scrollHeight;
}

function showNotification(message, type = 'info') {
    // Simple notification - you can enhance this
    console.log(`[${type}] ${message}`);
}

// Start the app
window.addEventListener('DOMContentLoaded', init);
