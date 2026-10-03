// State management
let backendUrl = window.location.origin || 'http://127.0.0.1:5001';
let autoRefreshInterval = null;
let isConnected = false;
const loadingState = {};
const appStartedAt = Date.now();
const electronAPI = window.electronAPI || {
    getBackendUrl: async () => window.location.origin,
    setBackendUrl: async (url) => ({ success: true, url }),
    onShowSettings: () => {},
    onShowAbout: () => {}
};
const iconBasePath = '../../static/';
const agentIconMap = {
    coingecko: 'market.png',
    coordinator: 'coordinator.png',
    council: 'council.png',
    data_store: 'datastore.png',
    datastore: 'datastore.png',
    dex_margin_oracle: 'oracle.png',
    execution: 'execution.png',
    executor_registry: 'execution.png',
    kill_switch: 'killswitch.png',
    logging: 'logging.png',
    market_data: 'market.png',
    network: 'network.png',
    nurse: 'nurse.png',
    openclaw: 'strategy.png',
    oracle: 'oracle.png',
    performance: 'performance.png',
    public_bot_bridge: 'buzzcoin.png',
    security: 'security.png',
    sentiment: 'market.png',
    strategy: 'strategy.png',
    swarmguard: 'swarmguard.png',
    trend: 'market.png',
    ui: 'ui.png',
    wallet: 'wallet.png',
    worker_breakout: 'workerBreakout.png',
    worker_exit_risk: 'killswitch.png',
    worker_latency: 'performance.png',
    worker_momentum: 'workerMomentum.png',
    worker_protection: 'swarmguard.png',
    worker_rsi: 'workerRSI.png',
    worker_rsi2: 'workerRSI.png',
    worker_sma: 'strategy.png',
    worker_vol_expansion: 'market.png'
};

// Initialize app
async function init() {
    try {
        backendUrl = await electronAPI.getBackendUrl();
        document.getElementById('backend-url').value = backendUrl;

        setupNavigation();
        setupEventListeners();

        await checkConnection();
        loadDashboardData();

        const autoRefresh = localStorage.getItem('autoRefresh') !== 'false';
        document.getElementById('auto-refresh').checked = autoRefresh;
        if (autoRefresh) {
            startAutoRefresh();
        }
    } catch (error) {
        console.error('App initialization failed:', error);
        setText('wallet-balance', 'UI error');
        setText('active-symbol', 'Check console');
    }
}

// Navigation
function setupNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        const activateItem = () => {
            // Update active nav item
            navItems.forEach(nav => nav.classList.remove('active'));
            item.classList.add('active');

            // Show corresponding view
            const viewName = item.dataset.view;
            showView(viewName);
        };

        item.addEventListener('click', activateItem);
        item.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                activateItem();
            }
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
            case 'market':
                loadMarketPreview();
                break;
            case 'agents':
                loadAgentsData();
                break;
            case 'buzzcoin':
                loadBuzzCoinData();
                break;
            case 'swarmguard':
                loadSwarmGuardData();
                break;
            case 'trades':
                loadTradesData();
                break;
            case 'performance':
                loadPerformanceData();
                break;
            case 'integrations':
                loadIntegrationsData();
                break;
            case 'logs':
                loadLogsData();
                break;
        }
    }
}

// Settings management
async function loadSettings() {
    const settings = await fetchAPI('/api/settings');
    if (!settings) return;

    const keys = ['symbol', 'interval', 'risk_pct', 'max_notional'];
    keys.forEach(key => {
        const el = document.getElementById(`setting-${key}`);
        if (el) el.value = settings[key];
    });
}

async function saveSettings() {
    const newSettings = {};
    const keys = ['symbol', 'interval', 'risk_pct', 'max_notional'];
    keys.forEach(key => {
        const el = document.getElementById(`setting-${key}`);
        if (el) newSettings[key] = el.value;
    });

    const result = await postAPI('/api/settings', newSettings);
    if (result && result.ok) {
        showNotification('Settings saved successfully', 'success');
    } else {
        showNotification('Failed to save settings', 'error');
    }
}

function setupEventListeners() {
    // Settings
    document.getElementById('save-backend-url').addEventListener('click', async () => {
        const newUrl = document.getElementById('backend-url').value;
        await electronAPI.setBackendUrl(newUrl);
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
    const integrationRefresh = document.getElementById('integration-refresh-btn');
    if (integrationRefresh) integrationRefresh.addEventListener('click', loadIntegrationsData);
    const integrationPlan = document.getElementById('integration-plan-btn');
    if (integrationPlan) integrationPlan.addEventListener('click', buildIntegrationPlan);
    const integrationCreate = document.getElementById('integration-create-btn');
    if (integrationCreate) integrationCreate.addEventListener('click', createIntegrationLifecycle);
    const integrationMonitor = document.getElementById('integration-monitor-btn');
    if (integrationMonitor) integrationMonitor.addEventListener('click', monitorIntegrationLifecycle);
    const integrationExport = document.getElementById('integration-export-btn');
    if (integrationExport) integrationExport.addEventListener('click', exportPublicBotBacktest);
    const integrationApply = document.getElementById('integration-apply-btn');
    if (integrationApply) integrationApply.addEventListener('click', applyPublicBotBacktestMetrics);
    document.addEventListener('submit', (event) => {
        if (event.target && event.target.id === 'runtime-control-form') {
            saveRuntimeControls(event);
        }
    });

    // Listen for IPC events
    electronAPI.onShowSettings(() => {
        showView('settings');
        loadSettings(); // Call to load current settings
    });

    electronAPI.onShowAbout(() => {
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
            } else if (viewId === 'market') {
                loadMarketPreview();
            } else if (viewId === 'agents') {
                loadAgentsData();
            } else if (viewId === 'buzzcoin') {
                loadBuzzCoinData();
            } else if (viewId === 'swarmguard') {
                loadSwarmGuardData();
            } else if (viewId === 'integrations') {
                loadIntegrationsData();
            }
        }
    }, 10000);
}

function stopAutoRefresh() {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
        autoRefreshInterval = null;
    }
}

// API calls
async function fetchAPI(endpoint, timeoutMs = 3500) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const response = await fetch(`${backendUrl}${endpoint}`, { signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error('API fetch error:', error);
        return null;
    } finally {
        clearTimeout(timer);
    }
}

async function checkConnection() {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 2500);
    try {
        const response = await fetch(`${backendUrl}/api/status`, { 
            method: 'GET',
            signal: controller.signal
        });
        isConnected = response.ok;
        updateConnectionStatus();
        return isConnected;
    } catch (error) {
        isConnected = false;
        updateConnectionStatus();
        return false;
    } finally {
        clearTimeout(timer);
    }
}

function updateConnectionStatus() {
    const statusBadge = document.getElementById('connection-status');
    const statusLabel = document.getElementById('connection-label');
    if (isConnected) {
        statusBadge.classList.add('connected');
        statusBadge.classList.remove('disconnected');
        if (statusLabel) statusLabel.textContent = 'Online';
    } else {
        statusBadge.classList.remove('connected');
        statusBadge.classList.add('disconnected');
        if (statusLabel) statusLabel.textContent = 'Offline';
    }
}

function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
}

function setBar(id, percent) {
    const element = document.getElementById(id);
    if (!element) return;
    const safePercent = Math.max(0, Math.min(100, percent));
    element.style.width = `${safePercent}%`;
}

function clampPercent(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return 0;
    return Math.max(0, Math.min(100, number));
}

function setDial(id, percent, labelId, label) {
    const element = document.getElementById(id);
    const safePercent = clampPercent(percent);
    if (element) element.style.setProperty('--meter', `${Math.round(safePercent * 3.6)}deg`);
    if (labelId) setText(labelId, label !== undefined ? label : `${Math.round(safePercent)}%`);
}

function setNeedle(id, percent) {
    const element = document.getElementById(id);
    if (!element) return;
    const safePercent = clampPercent(percent);
    element.style.setProperty('--needle', `${-72 + (safePercent * 1.44)}deg`);
}

function setGaugeFill(selector, percent) {
    const element = document.querySelector(`${selector} .fill span`);
    if (element) element.style.width = `${clampPercent(percent)}%`;
}

function setSegments(id, percent) {
    const element = document.getElementById(id);
    if (!element) return;
    const active = Math.ceil(clampPercent(percent) / 20);
    [...element.querySelectorAll('span')].forEach((segment, index) => {
        segment.classList.toggle('active', index < active);
        if (element.classList.contains('vertical-bars')) {
            segment.style.height = `${18 + (index + 1) * 10}px`;
        }
    });
}

function setChangeMeter(id, changePct) {
    const element = document.getElementById(id);
    if (!element) return;
    const change = Number(changePct || 0);
    const width = Math.min(50, Math.abs(change) * 4);
    element.style.width = `${width}%`;
    element.style.left = change >= 0 ? '50%' : `${50 - width}%`;
    element.style.background = change >= 0 ? 'var(--green)' : 'var(--red)';
}

function agentIsActive(agent) {
    return String(agent && agent.status || '').toLowerCase() === 'active';
}

function runtimeUptime() {
    const seconds = Math.max(1, Math.floor((Date.now() - appStartedAt) / 1000));
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m`;
    return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

async function updateDashboardVisuals(data) {
    const agents = data.agents || {};
    const agentEntries = Object.entries(agents);
    const totalAgents = agentEntries.length;
    const activeAgents = agentEntries.filter(([, agent]) => agentIsActive(agent)).length;
    const activePct = totalAgents ? Math.round((activeAgents / totalAgents) * 100) : 0;

    setText('agent-health-label', totalAgents ? `${activePct}%` : '-');
    setBar('agent-health-bar', activePct);

    const oracleActive = agentIsActive(agents.oracle);
    const councilActive = agentIsActive(agents.council);
    const swarmguardActive = agentIsActive(agents.swarmguard);
    const signalScore = Math.round((activePct * 0.55) + (oracleActive ? 20 : 0) + (councilActive ? 15 : 0) + (swarmguardActive ? 10 : 0));
    const clampedSignal = Math.max(0, Math.min(100, signalScore));
    const oracleMeter = document.getElementById('oracle-meter');
    if (oracleMeter) {
        oracleMeter.style.setProperty('--meter', `${Math.round(clampedSignal * 3.6)}deg`);
    }
    setText('oracle-score', `${clampedSignal}%`);
    setText('oracle-label', oracleActive ? 'Synced' : 'Waiting');
    setText('oracle-status', oracleActive ? 'Active' : 'Offline');
    setText('council-status', councilActive ? 'Voting' : 'Idle');
    setText('swarmguard-status', swarmguardActive ? 'Guarding' : 'Offline');

    // Update new gauges
    const [regime, council, guard] = await Promise.all([
        fetchAPI('/regime.json'),
        fetchAPI('/council.json'),
        fetchAPI('/swarmguard.json')
    ]);
    
    setGaugeFill('#gauge-regime', (regime && regime.payload && regime.payload.confidence || 0) * 100);
    setGaugeFill('#gauge-council', (council && council.payload && council.payload.consensus || 0) * 100);
    setGaugeFill('#gauge-guard', (guard && guard.payload && guard.payload.risk_score || 0) * 100);

    const riskPct = data.kill_switch_active ? 100 : (data.live === true || data.dry_run === false ? 68 : 24);
    setText('risk-meter-label', data.kill_switch_active ? 'Halted' : (riskPct > 50 ? 'Elevated' : 'Nominal'));
    setBar('risk-meter-bar', riskPct);
}

function formatAgentName(name) {
    return String(name || '')
        .replace(/^worker_/, 'worker ')
        .replace(/_/g, ' ')
        .replace(/\b\w/g, char => char.toUpperCase());
}

function getAgentIcon(name) {
    return `${iconBasePath}${agentIconMap[name] || 'buzzcoin.png'}`;
}

function agentMeterValue(name, agent) {
    if (!agentIsActive(agent)) return 8;
    const text = String(name || '');
    if (text.includes('oracle') || text.includes('council')) return 92;
    if (text.includes('worker')) return 78;
    if (text.includes('guard') || text.includes('security') || text.includes('kill')) return 88;
    return 84;
}

function updateAgentsSummary(agents) {
    const entries = Object.entries(agents || {});
    const total = entries.length;
    const active = entries.filter(([, agent]) => agentIsActive(agent)).length;
    const inactive = Math.max(0, total - active);
    const workers = entries.filter(([name]) => String(name).startsWith('worker_')).length;
    const pct = total ? Math.round((active / total) * 100) : 0;

    setText('agent-swarm-score', `${pct}%`);
    setText('agents-active-count', String(active));
    setText('agents-inactive-count', String(inactive));
    setText('agents-worker-count', String(workers));

    const ring = document.getElementById('agent-swarm-ring');
    if (ring) {
        ring.style.setProperty('--meter', `${Math.round(pct * 3.6)}deg`);
    }
}

function renderPriceChart(labels, prices) {
    renderPriceChartInto({
        lineId: 'agent-price-line',
        areaId: 'agent-price-area',
        latestId: 'agent-price-latest',
        startId: 'agent-price-start',
        rangeId: 'agent-price-range',
        endId: 'agent-price-end',
        labels,
        prices
    });
}

function renderPriceChartInto({ lineId, areaId, latestId, startId, rangeId, endId, labels, prices }) {
    const line = document.getElementById(lineId);
    const area = document.getElementById(areaId);
    if (!line || !area || !Array.isArray(prices) || prices.length < 2) return;

    const width = 640;
    const height = 220;
    const padX = 18;
    const padY = 18;
    const usableWidth = width - padX * 2;
    const usableHeight = height - padY * 2;
    const numericPrices = prices.map(Number).filter(Number.isFinite);
    if (numericPrices.length < 2) return;

    const min = Math.min(...numericPrices);
    const max = Math.max(...numericPrices);
    const spread = Math.max(0.000001, max - min);
    const points = numericPrices.map((price, index) => {
        const x = padX + (index / Math.max(1, numericPrices.length - 1)) * usableWidth;
        const y = padY + (1 - ((price - min) / spread)) * usableHeight;
        return [x, y];
    });

    const path = points.map(([x, y], index) => `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`).join(' ');
    const areaPath = `${path} L ${points[points.length - 1][0].toFixed(2)} ${height - padY} L ${points[0][0].toFixed(2)} ${height - padY} Z`;
    line.setAttribute('d', path);
    area.setAttribute('d', areaPath);

    const first = numericPrices[0];
    const last = numericPrices[numericPrices.length - 1];
    const change = ((last - first) / Math.max(0.000001, first)) * 100;
    setText(latestId, `$${last.toFixed(2)}`);
    setText(startId, labels && labels.length ? labels[0] : 'Start');
    setText(endId, labels && labels.length ? labels[labels.length - 1] : 'Now');
    setText(rangeId, `${change >= 0 ? '+' : ''}${change.toFixed(2)}%`);
}

async function loadAgentPriceGraph(symbol) {
    const title = document.getElementById('agent-price-title');
    if (title && symbol) title.textContent = `${symbol} Price Graph`;

    const data = await fetchAPI('/price.json');
    if (!data || !data.prices) return;
    renderPriceChart(data.labels || [], data.prices || []);
}

async function loadMarketPreview(symbolOverride) {
    if (loadingState.market) return;
    loadingState.market = true;
    try {
    const status = await fetchAPI('/api/status');
    const symbol = symbolOverride || (status && status.symbol) || 'Market';
    setText('market-price-title', `${symbol} Price Graph`);
    setText('dashboard-market-title', `${symbol} Market Preview`);

    const data = await fetchAPI('/price.json');
    if (!data || !data.prices) return;
    const labels = data.labels || [];
    const prices = data.prices || [];
    renderPriceChartInto({
        lineId: 'market-price-line',
        areaId: 'market-price-area',
        latestId: 'market-price-latest',
        startId: 'market-price-start',
        rangeId: 'market-price-range',
        endId: 'market-price-end',
        labels,
        prices
    });
    renderPriceChartInto({
        lineId: 'dashboard-market-line',
        areaId: 'dashboard-market-area',
        latestId: 'dashboard-market-latest',
        startId: 'dashboard-market-start',
        rangeId: 'dashboard-market-range',
        endId: 'dashboard-market-end',
        labels,
        prices
    });
    } finally {
        loadingState.market = false;
    }
}

function extractMetricPrice(metrics) {
    const latest = metrics && metrics.latest_price;
    if (typeof latest === 'number') return latest;
    if (latest && typeof latest === 'object') {
        const payload = latest.payload;
        if (typeof payload === 'number') return payload;
        if (payload && typeof payload === 'object') return Number(payload.price || payload.last || 0);
        return Number(latest.price || latest.last || 0);
    }
    return 0;
}

function latestPriceFromSeries(series) {
    const prices = series && series.prices;
    if (!Array.isArray(prices) || !prices.length) return 0;
    return Number(prices[prices.length - 1] || 0);
}

async function getDashboardSources() {
    const [status, wallet, metrics, priceSeries, integrations, buzz, performance] = await Promise.all([
        fetchAPI('/api/status'),
        fetchAPI('/wallet.json'),
        fetchAPI('/metrics.json'),
        fetchAPI('/price.json'),
        fetchOptionalAPI('/integration_planes.json', 4500),
        fetchOptionalAPI('/buzz/status', 3000),
        fetchOptionalAPI('/api/performance', 3000)
    ]);
    return { status, wallet, metrics, priceSeries, integrations, buzz, performance };
}

function updateMetricInstruments({ status, wallet, metrics, priceSeries, integrations, buzz, performance }) {
    const walletTotal = Number(
        (wallet && wallet.equity_usd_est)
        || (status && status.wallet && status.wallet.total_usd)
        || (metrics && metrics.trading && metrics.trading.equity_usd_est)
        || 0
    );
    const equityPct = walletTotal > 0 ? Math.min(100, Math.log10(walletTotal + 1) * 22) : 0;
    setDial('equity-dial', equityPct, 'equity-dial-label', walletTotal > 0 ? 'Live' : '0%');

    const prices = (priceSeries && priceSeries.prices || []).map(Number).filter(Number.isFinite);
    const last = prices.length ? prices[prices.length - 1] : 0;
    const min = prices.length ? Math.min(...prices) : 0;
    const max = prices.length ? Math.max(...prices) : 0;
    const pricePct = max > min ? ((last - min) / (max - min)) * 100 : 50;
    setNeedle('price-dial', pricePct);

    const change = status && status.market && Number(status.market.change_24h);
    const seriesChange = prices.length > 1 ? ((last - prices[0]) / Math.max(0.000001, prices[0])) * 100 : 0;
    setChangeMeter('change-meter-bar', Number.isFinite(change) ? change : seriesChange);
    setSegments('symbol-activity-meter', prices.length ? Math.min(100, prices.length) : 0);

    const buzzAccount = (buzz && buzz.data && buzz.data.account) || {};
    const buzzAvailable = Number(buzzAccount.available || 0);
    const buzzLocked = Number(buzzAccount.locked || 0);
    const buzzTotal = buzzAvailable + buzzLocked;
    setDial('buzz-dial', buzzTotal ? Math.min(100, Math.log10(buzzTotal + 1) * 24) : 0, 'buzz-dial-label', formatBuzzAmount(buzzTotal));
    setText('buzz-total-metric', buzz.ok ? formatBuzzAmount(buzzTotal) : '-');
    setText('buzz-locked-metric', buzz.ok ? `${formatBuzzAmount(buzzLocked)} locked` : ((buzz && buzz.data && buzz.data.error) || 'BuzzService offline'));

    const plane = (integrations && integrations.data && integrations.data.payload) || {};
    const integrationStatus = plane.integration_status || {};
    const activeStatusCount = Object.values(integrationStatus).filter(value => {
        const text = String(value || '').toLowerCase();
        return text && !text.includes('disabled') && !text.includes('unavailable') && !text.includes('pending');
    }).length;
    const statusCount = Math.max(1, Object.keys(integrationStatus).length);
    const syncPct = integrations && integrations.ok ? (activeStatusCount / statusCount) * 100 : 0;
    setSegments('integration-sync-bars', syncPct);
    setText('integration-sync-metric', integrations && integrations.ok ? `${Math.round(syncPct)}%` : '-');
    setText('integration-sync-caption', integrationStatus.hummingbot_v2_adapter || integrationStatus.hummingbot_live_sidecar || 'Integration plane');

    const workers = (plane.workers && plane.workers.perf_by_worker) || {};
    const workerRows = Object.values(workers);
    const avgWin = workerRows.length
        ? workerRows.reduce((sum, row) => sum + Number(row.win_rate || 0), 0) / workerRows.length
        : Number(performance && performance.data && performance.data.win_rate || 0);
    const workerPct = avgWin <= 1 ? avgWin * 100 : avgWin;
    setDial('worker-win-dial', workerPct, 'worker-win-label', `${Math.round(workerPct || 0)}%`);
    setText('worker-win-metric', workerRows.length ? `${workerRows.length} workers` : '-');
    setText('worker-win-caption', workerRows.length ? 'Average worker win rate' : 'No worker samples yet');

    const protections = plane.pair_protections || {};
    const protectionRows = Object.values(protections);
    const allowed = protectionRows.filter(row => row && row.allowed !== false).length;
    const protectionPct = protectionRows.length ? (allowed / protectionRows.length) * 100 : 0;
    setSegments('protection-gates', protectionPct);
    setText('protection-gate-metric', protectionRows.length ? `${allowed}/${protectionRows.length}` : '-');
    setText('protection-gate-caption', protectionRows.length ? 'Pairs currently allowed' : 'No pair gates loaded');
}

function formatBuzzAmount(value) {
    const number = Number(value || 0);
    return Number.isFinite(number) ? number.toLocaleString() : '-';
}

function formatShortTime(value) {
    if (!value) return '-';
    const numeric = Number(value);
    const date = Number.isFinite(numeric)
        ? new Date(numeric < 100000000000 ? numeric * 1000 : numeric)
        : new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleTimeString();
}

async function fetchOptionalAPI(endpoint, timeoutMs = 3000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const response = await fetch(`${backendUrl}${endpoint}`, { signal: controller.signal });
        const data = await response.json().catch(() => ({}));
        return { ok: response.ok, data, status: response.status };
    } catch (error) {
        return { ok: false, data: { error: error.message }, status: 0 };
    } finally {
        clearTimeout(timer);
    }
}

async function postAPI(endpoint, body, timeoutMs = 8000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const response = await fetch(`${backendUrl}${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body || {}),
            signal: controller.signal
        });
        const data = await response.json().catch(() => ({}));
        return { ok: response.ok, data, status: response.status };
    } catch (error) {
        return { ok: false, data: { error: error.message }, status: 0 };
    } finally {
        clearTimeout(timer);
    }
}

function escapeHTML(value) {
    return String(value === undefined || value === null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function integrationIntent() {
    const side = (document.getElementById('integration-side')?.value || 'BUY').trim().toUpperCase();
    const symbol = (document.getElementById('integration-symbol')?.value || 'ETH/USD').trim();
    const notional = Number(document.getElementById('integration-notional')?.value || 0);
    const executor = (document.getElementById('integration-executor')?.value || 'position').trim().toLowerCase();
    return {
        executor_type: executor || 'position',
        intent: {
            symbol,
            action: side || 'BUY',
            notional_usd: Number.isFinite(notional) ? notional : 0
        }
    };
}

function statusWord(value, yesText, noText) {
    return value ? yesText : noText;
}

const runtimeControlSections = [
    {
        title: 'Mode',
        fields: [
            { key: 'dry_run', label: 'Dry Run', type: 'bool' },
            { key: 'live_mode', label: 'Live Mode', type: 'bool' },
            { key: 'confirm_live', label: 'Live Confirm', type: 'text', placeholder: 'ARM LIVE' }
        ]
    },
    {
        title: 'Market',
        fields: [
            { key: 'exchange', label: 'Marketplace', type: 'select', options: ['kraken', 'binance'] },
            { key: 'symbol', label: 'Active Coin', type: 'text', placeholder: 'ETH/USD' },
            { key: 'interval', label: 'Interval', type: 'text', placeholder: '1m' },
            { key: 'multi_symbol_enabled', label: 'Multi Coin', type: 'bool' },
            { key: 'multi_symbols', label: 'Coins', type: 'list', placeholder: 'ETH/USD,BTC/USD,SOL/USD' }
        ]
    },
    {
        title: 'Coin Selection',
        fields: [
            { key: 'coin_selection_enabled', label: 'Auto Select', type: 'bool' },
            { key: 'coin_selection_auto_switch', label: 'Auto Switch', type: 'bool' },
            { key: 'coin_selection_top_n', label: 'Top N', type: 'number' },
            { key: 'coin_selection_include', label: 'Include', type: 'list' },
            { key: 'coin_selection_exclude', label: 'Exclude', type: 'list' },
            { key: 'coin_selection_quote_assets', label: 'Quote Assets', type: 'list' }
        ]
    },
    {
        title: 'Wallet + DEX',
        fields: [
            { key: 'wallet_safety_enabled', label: 'Wallet Safety', type: 'bool' },
            { key: 'watch_address', label: 'Watch Wallet', type: 'text' },
            { key: 'erc20_token_address', label: 'Token Address', type: 'text' },
            { key: 'wallet_max_daily_spend_usd', label: 'Daily Spend USD', type: 'number' },
            { key: 'wallet_max_token_exposure_pct', label: 'Max Token Exposure', type: 'number' },
            { key: 'onchain_enabled', label: 'On-chain', type: 'bool' },
            { key: 'dex_provider', label: 'DEX Provider', type: 'text' },
            { key: 'onchain_chain_id', label: 'Chain ID', type: 'number' },
            { key: 'onchain_allowed_pairs', label: 'DEX Pairs', type: 'list' }
        ]
    },
    {
        title: 'Research Gates',
        fields: [
            { key: 'public_bot_metrics_auto_promote', label: 'Auto Promote', type: 'bool' },
            { key: 'market_bee_enabled', label: 'Market Bee', type: 'bool' },
            { key: 'market_bee_top_n', label: 'Market Bee Top N', type: 'number' },
            { key: 'hummingbot_sidecar_live_enabled', label: 'Hummingbot Live', type: 'bool' },
            { key: 'market_making_advisors_enabled', label: 'PMM Advisors', type: 'bool' },
            { key: 'market_making_quote_placement_enabled', label: 'Quote Placement', type: 'bool' }
        ]
    }
];

function setChip(id, text, stateClass) {
    const element = document.getElementById(id);
    if (!element) return;
    element.textContent = text;
    element.className = `market-chip ${stateClass || ''}`.trim();
}

function renderIntegrationList(containerId, rows) {
    const container = document.getElementById(containerId);
    if (!container) return;
    if (!rows.length) {
        container.innerHTML = '<p class="loading-text">No records available</p>';
        return;
    }
    container.innerHTML = rows.map(row => `
        <div class="integration-list-item">
            <div>
                <span>${escapeHTML(row.label)}</span>
                <strong>${escapeHTML(row.value)}</strong>
            </div>
            <p>${escapeHTML(row.detail || '')}</p>
        </div>
    `).join('');
}

function renderIntegrationLifecycle(states) {
    const tbody = document.getElementById('integration-lifecycle-body');
    if (!tbody) return 0;
    const rows = Object.values(states || {}).sort((a, b) => Number(b.updated_ts || 0) - Number(a.updated_ts || 0));
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="loading-text">No lifecycle executors yet</td></tr>';
        return 0;
    }
    tbody.innerHTML = rows.slice(0, 10).map(row => `
        <tr>
            <td>${escapeHTML(row.executor_id || '-')}</td>
            <td>${escapeHTML(row.executor_type || '-')}</td>
            <td>${escapeHTML(row.symbol || '-')}</td>
            <td class="${String(row.side || '').toUpperCase() === 'BUY' ? 'trade-buy' : 'trade-sell'}">${escapeHTML(row.side || '-')}</td>
            <td>${escapeHTML(row.state || '-')}</td>
        </tr>
    `).join('');
    return rows.length;
}

function renderIntegrationAdvisors(payload) {
    const advisors = payload.market_making_advisors || {};
    const quoteEnabled = !!advisors.quote_placement_enabled;
    const pairProtections = payload.pair_protections || {};
    const directAdvice = (payload.quote_quality_advice && payload.quote_quality_advice.advice) || {};
    const adviceRows = [];
    Object.entries(directAdvice).slice(0, 8).forEach(([symbol, quote]) => {
        const score = quote.quote_quality_score;
        adviceRows.push({
            label: symbol,
            value: `${quote.state || 'ADVICE'} ${Number.isFinite(Number(score)) ? Math.round(Number(score) * 100) + '%' : ''}`,
            detail: quote.reason || quote.requires_quote_quality || 'Quote-quality advice'
        });
    });
    Object.entries(pairProtections).slice(0, 8).forEach(([symbol, row]) => {
        const quote = row.quote_advice || {};
        const score = quote.quote_quality_score;
        const state = quote.state || (row.allowed === false ? 'BLOCK' : 'CLEAR');
        adviceRows.push({
            label: symbol,
            value: `${state} ${Number.isFinite(Number(score)) ? Math.round(Number(score) * 100) + '%' : ''}`,
            detail: quote.reason || row.reason || statusWord(row.allowed, 'pair allowed', 'pair blocked')
        });
    });
    if (!adviceRows.length && Array.isArray(advisors.advisors)) {
        advisors.advisors.forEach(name => adviceRows.push({
            label: name,
            value: advisors.mode || 'watch_only_quote_quality',
            detail: quoteEnabled ? 'quote placement enabled' : 'quote placement disabled'
        }));
    }
    renderIntegrationList('integration-advisor-list', adviceRows);
    setText('integration-quote-state', quoteEnabled ? 'LIVE' : 'WATCH');
    setText('integration-quote-caption', quoteEnabled ? 'Quote placement enabled' : 'Quote placement disabled');
    setText('integration-advisor-mode', quoteEnabled ? 'Quote Placement' : 'Watch-only');
}

function renderIntegrationBacktests(payload) {
    const backtests = payload.public_bot_backtesting || payload.backtesting || {};
    const metrics = payload.public_bot_metrics || {};
    const evidence = payload.evidence_registry || {};
    const evidenceRecords = payload.evidence_records || {};
    const controls = payload.controls || {};
    const recordRows = Object.values(evidenceRecords || {});
    const reviewReady = recordRows.filter(row => row.verdict === 'review_ready').length;
    const reviewRequired = recordRows.filter(row => row.verdict === 'review_required').length;
    const rows = [
        {
            label: 'Promotion Mode',
            value: controls.public_bot_metrics_auto_promote ? 'Auto-promote' : 'Review-first',
            detail: controls.public_bot_metrics_auto_promote
                ? 'Eligible public-bot metrics can promote symbols.'
                : 'Metrics are staged for review before promotion.'
        },
        {
            label: 'Export/Ingest',
            value: backtests.mode || backtests.status || 'connected',
            detail: backtests.export_dir || backtests.metrics_dir || 'Freqtrade/Jesse sidecar research loop'
        },
        {
            label: 'Evidence Registry',
            value: evidence.ok ? `${recordRows.length} records` : 'pending',
            detail: `${reviewReady} review ready | ${reviewRequired} need research details`
        }
    ];
    recordRows.slice(0, 4).forEach(row => rows.push({
        label: row.symbol || row.engine || 'Evidence',
        value: row.verdict || 'collecting',
        detail: `${row.engine || row.source || 'engine'} | trades ${((row.metrics || {}).trades) ?? row.trades ?? '-'} | net ${((row.metrics || {}).net_profit_pct) ?? row.net_profit_pct ?? '-'}`
    }));
    Object.entries(metrics).slice(0, 4).forEach(([symbol, row]) => rows.push({
        label: symbol,
        value: row.engine || row.source || 'metric',
        detail: `score ${row.score !== undefined ? row.score : '-'} | trades ${row.trades !== undefined ? row.trades : '-'}`
    }));
    renderIntegrationList('integration-backtest-list', rows);
    setText('integration-backtest-state', controls.public_bot_metrics_auto_promote ? 'AUTO' : 'REVIEW');
    setText('integration-backtest-caption', controls.public_bot_metrics_auto_promote ? 'Auto-promotion enabled' : 'Review-first metrics');
}

function renderIntegrationControls(payload) {
    const controls = payload.controls || {};
    const command = controls.hummingbot_sidecar_command || '';
    const container = document.getElementById('integration-control-list');
    if (container) {
        container.innerHTML = `
            <form id="runtime-control-form" class="runtime-control-form">
                ${runtimeControlSections.map(section => `
                    <fieldset>
                        <legend>${escapeHTML(section.title)}</legend>
                        ${section.fields.map(field => renderRuntimeField(field, controls)).join('')}
                    </fieldset>
                `).join('')}
                <div class="runtime-control-actions">
                    <button type="submit" class="btn btn-primary">Save Settings</button>
                    <span id="runtime-control-result" class="inline-result">Ready</span>
                </div>
            </form>
            <div class="integration-list-item">
                <div><span>Hummingbot Sidecar</span><strong>${controls.hummingbot_sidecar_live_enabled ? 'live enabled' : 'plan gated'}</strong></div>
                <p>${escapeHTML(command || 'No sidecar command configured')}</p>
            </div>
        `;
    }
    setChip('hb-live-chip', controls.hummingbot_sidecar_live_enabled ? 'Sidecar live' : 'Sidecar gated', controls.hummingbot_sidecar_live_enabled ? '' : 'blue-chip');
    setChip('promotion-chip', controls.public_bot_metrics_auto_promote ? 'Auto-promote' : 'Review-first', controls.public_bot_metrics_auto_promote ? '' : 'blue-chip');
    setChip('quote-chip', controls.market_making_quote_placement_enabled ? 'Quotes live' : 'Quotes watch-only', controls.market_making_quote_placement_enabled ? '' : 'red-chip');
}

function renderRuntimeField(field, controls) {
    const value = controls[field.key];
    const name = escapeHTML(field.key);
    const label = escapeHTML(field.label);
    if (field.type === 'bool') {
        return `
            <label class="runtime-field runtime-toggle">
                <span>${label}</span>
                <select name="${name}">
                    <option value="true" ${value === true ? 'selected' : ''}>On</option>
                    <option value="false" ${value === false ? 'selected' : ''}>Off</option>
                </select>
            </label>
        `;
    }
    if (field.type === 'select') {
        return `
            <label class="runtime-field">
                <span>${label}</span>
                <select name="${name}">
                    ${(field.options || []).map(option => `<option value="${escapeHTML(option)}" ${String(value || '').toLowerCase() === option ? 'selected' : ''}>${escapeHTML(option)}</option>`).join('')}
                </select>
            </label>
        `;
    }
    const fieldValue = Array.isArray(value) ? value.join(',') : (value === undefined || value === null ? '' : value);
    const inputType = field.type === 'number' ? 'number' : 'text';
    return `
        <label class="runtime-field">
            <span>${label}</span>
            <input name="${name}" type="${inputType}" step="any" value="${escapeHTML(fieldValue)}" placeholder="${escapeHTML(field.placeholder || '')}">
        </label>
    `;
}

async function saveRuntimeControls(event) {
    event.preventDefault();
    const form = event.target;
    const body = Object.fromEntries(new FormData(form).entries());
    const resultEl = document.getElementById('runtime-control-result');
    if (resultEl) resultEl.textContent = 'Saving...';
    const result = await postAPI('/integration_controls', body, 12000);
    const data = result.data || {};
    if (resultEl) {
        resultEl.textContent = result.ok && data.ok
            ? `Saved ${Object.keys(data.updates || {}).length} settings`
            : (JSON.stringify(data.errors || data.error || 'Save failed'));
    }
    await loadIntegrationsData();
    await checkConnection();
}

function renderIntegrationWorkers(payload) {
    const workers = (payload.workers && payload.workers.perf_by_worker) || {};
    const rows = Object.entries(workers).slice(0, 10).map(([worker, row]) => ({
        label: worker,
        value: `${Math.round(Number(row.win_rate || 0) * 100)}% win | ${row.samples || 0} samples`,
        detail: `recent ${Math.round(Number(row.recent_win_rate || 0) * 100)}% | drawdown ${Number(row.drawdown || 0).toFixed(2)} | avg R ${Number(row.avg_r_multiple || 0).toFixed(2)}`
    }));
    renderIntegrationList('integration-worker-list', rows);
    setText('integration-worker-count', rows.length ? `${rows.length} workers` : 'No workers');
}

function renderIntegrationProtections(payload) {
    const protections = payload.pair_protections || {};
    const rows = Object.entries(protections).slice(0, 12).map(([symbol, row]) => {
        const quote = row.quote_advice || {};
        const allowed = row.allowed !== false;
        return {
            label: symbol,
            value: allowed ? 'Allowed' : 'Blocked',
            detail: quote.reason || row.reason || row.state || 'No gate reason reported'
        };
    });
    renderIntegrationList('integration-protection-list', rows);
    const allowed = Object.values(protections).filter(row => row && row.allowed !== false).length;
    const total = Object.keys(protections).length;
    setText('integration-protection-count', total ? `${allowed}/${total} allowed` : 'No gates');
}

function renderIntegrationRaw(payload) {
    const element = document.getElementById('integration-raw-plane');
    if (!element) return;
    element.textContent = JSON.stringify(payload || {}, null, 2);
}

function renderQueenAlerts(rows) {
    const container = document.getElementById('queen-alert-list');
    if (!container) return;
    const cleanRows = rows || [];
    setText('queen-alert-count', cleanRows.length ? `${cleanRows.length} alerts` : 'Quiet');
    if (!cleanRows.length) {
        container.innerHTML = '<p class="loading-text">No Queen alerts yet</p>';
        return;
    }
    container.innerHTML = cleanRows.slice(0, 8).map(row => `
        <div class="integration-list-item queen-alert-item">
            <div>
                <span>${escapeHTML(row.action || row.type || 'Queen')}</span>
                <strong>${escapeHTML(row.strategy || '-')} | SVS ${escapeHTML(row.svs ?? '-')}</strong>
            </div>
            <p>${escapeHTML(row.reason || '')}</p>
        </div>
    `).join('');
}

function renderIntegrationArchitecture(payload) {
    const arch = payload.research_architecture || {};
    const configSpine = payload.config_spine || {};
    const eventSpine = payload.event_spine || {};
    const mlLab = payload.ml_research_lab || {};
    const mlCandidates = payload.ml_model_candidates || {};
    const active = arch.active_layer || {};
    const container = document.getElementById('architecture-layer-list');
    setText('architecture-layer-state', eventSpine.ok ? 'event spine' : (configSpine.ok ? 'config spine' : (active.status || 'planned')));
    if (!container) return;
    const policy = arch.evidence_policy || {};
    const gates = active.gates || [];
    const systems = active.systems || [];
    container.innerHTML = `
        <div class="integration-list-item architecture-layer-item">
            <div>
                <span>${escapeHTML(active.id || 'layer')}</span>
                <strong>${escapeHTML(active.name || 'Research Architecture')}</strong>
            </div>
            <p>${escapeHTML(active.purpose || '')}</p>
        </div>
        <div class="integration-list-item">
            <div><span>Systems</span><strong>${systems.length}</strong></div>
            <p>${escapeHTML(systems.join(', ') || 'No systems listed')}</p>
        </div>
        <div class="integration-list-item">
            <div><span>Gates</span><strong>${gates.length}</strong></div>
            <p>${escapeHTML(gates.join(', ') || 'No gates listed')}</p>
        </div>
        <div class="integration-list-item">
            <div><span>Promotion Policy</span><strong>${escapeHTML(policy.live_promotion || '-')}</strong></div>
            <p>${escapeHTML(policy.profit_claims || 'profit claims require reproduction')}</p>
        </div>
        <div class="integration-list-item architecture-layer-item">
            <div><span>Config Spine</span><strong>${configSpine.ok ? 'Active' : 'Pending'}</strong></div>
            <p>${escapeHTML((configSpine.schema_fields || 0) + ' typed fields | snapshots ' + ((configSpine.snapshots || []).length || 0))}</p>
        </div>
        <div class="integration-list-item architecture-layer-item">
            <div><span>Event Spine</span><strong>${eventSpine.ok ? 'Active' : 'Pending'}</strong></div>
            <p>${escapeHTML((eventSpine.validated_count || 0) + ' validated | ' + (eventSpine.critical_count || 0) + ' critical | ' + (eventSpine.invalid_count || 0) + ' invalid')}</p>
        </div>
        <div class="integration-list-item architecture-layer-item">
            <div><span>ML Research</span><strong>${mlLab.ok ? 'Offline' : 'Pending'}</strong></div>
            <p>${escapeHTML(Object.keys(mlCandidates).length + ' candidates | ' + (mlLab.mode || 'offline_proposals_only'))}</p>
        </div>
    `;
}

function updateIntegrationHero(payload) {
    const controls = payload.controls || {};
    const lifecycle = payload.hummingbot_lifecycle || {};
    const statuses = payload.integration_status || {};
    const states = lifecycle.states || {};
    const enabledCount = [
        lifecycle.enabled,
        controls.market_making_advisors_enabled,
        statuses.public_bot_backtesting === 'export_ingest_connected',
        statuses.worker_performance === 'sqlite_persisted_feedback',
        statuses.pair_protections === 'swarmguard_enforced'
    ].filter(Boolean).length;
    const score = Math.round((enabledCount / 5) * 100);
    const orbital = document.getElementById('integration-orbital');
    if (orbital) orbital.style.setProperty('--meter', `${Math.round(score * 3.6)}deg`);
    setText('integration-score', `${score}%`);
    setText('integration-hero-title', lifecycle.name || 'Hummingbot V2 Adapter');
    setText('integration-hero-text', `${statuses.hummingbot_v2_adapter || 'plan_and_lifecycle'} | ${statuses.public_bot_backtesting || 'research pending'} | ${statuses.market_making_advisors || 'quote advisors pending'}`);
    setText('integration-lifecycle-state', lifecycle.live_enabled ? 'LIVE' : 'PLAN');
    setText('integration-lifecycle-count', `${Object.keys(states).length} executor records`);
    setText('integration-protection-state', statuses.pair_protections === 'swarmguard_enforced' ? 'ON' : 'CHECK');
    setText('integration-protection-caption', statuses.pair_protections || 'Pair protections pending');
    setText('integration-updated', new Date().toLocaleTimeString());
}

async function loadIntegrationsData() {
    if (loadingState.integrations) return;
    loadingState.integrations = true;
    try {
        const [result, queenResult] = await Promise.all([
            fetchOptionalAPI('/integration_planes.json', 6000),
            fetchOptionalAPI('/queen/alerts.json', 4000)
        ]);
        const payload = (result.data || {}).payload || {};
        if (!result.ok) {
            setText('integration-action-result', result.data.error || 'Integration plane unavailable');
            return;
        }
        updateIntegrationHero(payload);
        renderIntegrationLifecycle((payload.hummingbot_lifecycle || {}).states || {});
        renderIntegrationAdvisors(payload);
        renderIntegrationBacktests(payload);
        renderIntegrationControls(payload);
        renderIntegrationWorkers(payload);
        renderIntegrationProtections(payload);
        renderIntegrationRaw(payload);
        renderIntegrationArchitecture(payload);
        renderQueenAlerts((queenResult.data || {}).rows || []);
    } finally {
        loadingState.integrations = false;
    }
}

async function buildIntegrationPlan() {
    const request = integrationIntent();
    setText('integration-action-result', 'Building executor plan...');
    const result = await postAPI('/hummingbot/plan.json', request, 8000);
    const payload = (result.data || {}).payload || {};
    if (result.ok && payload.ok) {
        const config = payload.config || {};
        setText('integration-action-result', `${payload.executor_type || request.executor_type} plan ready for ${config.trading_pair || request.intent.symbol}`);
    } else {
        setText('integration-action-result', payload.error || result.data.error || 'Plan failed');
    }
    loadIntegrationsData();
}

async function createIntegrationLifecycle() {
    const request = integrationIntent();
    setText('integration-action-result', 'Creating lifecycle record...');
    const result = await postAPI('/hummingbot/lifecycle.json', {
        action: 'create',
        executor_type: request.executor_type,
        intent: request.intent
    }, 10000);
    const payload = (result.data || {}).payload || {};
    if (result.ok && payload.ok) {
        setText('integration-action-result', `Created ${payload.executor_id || 'executor'}`);
    } else {
        setText('integration-action-result', payload.error || result.data.error || 'Create failed');
    }
    loadIntegrationsData();
}

async function monitorIntegrationLifecycle() {
    setText('integration-action-result', 'Monitoring lifecycle...');
    const result = await postAPI('/hummingbot/lifecycle.json', { action: 'monitor' }, 8000);
    const payload = (result.data || {}).payload || {};
    setText('integration-action-result', result.ok ? 'Lifecycle monitor refreshed' : (payload.error || 'Monitor failed'));
    loadIntegrationsData();
}

async function exportPublicBotBacktest() {
    const symbol = (document.getElementById('integration-symbol')?.value || 'ETH/USD').trim();
    setText('integration-action-result', 'Exporting public-bot backtest bundle...');
    const result = await postAPI('/public_bot/backtest/export.json', {
        engine: 'freqtrade',
        symbol,
        days: 30
    }, 12000);
    const payload = (result.data || {}).payload || {};
    setText('integration-action-result', result.ok && payload.ok ? `Exported ${payload.engine || 'public-bot'} bundle` : (payload.error || result.data.error || 'Export failed'));
    loadIntegrationsData();
}

async function applyPublicBotBacktestMetrics() {
    setText('integration-action-result', 'Applying ingested public-bot metrics...');
    const result = await postAPI('/public_bot/backtest/apply.json', {}, 10000);
    const payload = (result.data || {}).payload || {};
    setText('integration-action-result', result.ok && payload.ok ? 'Metrics applied to review pipeline' : (payload.error || result.data.error || 'Apply failed'));
    loadIntegrationsData();
}

async function loadBuzzCoinData() {
    if (loadingState.buzzcoin) return;
    loadingState.buzzcoin = true;
    try {
    const [statusResult, ledgerResult, leaderboardResult] = await Promise.all([
        fetchOptionalAPI('/buzz/status'),
        fetchOptionalAPI('/buzz/ledger?limit=25'),
        fetchOptionalAPI('/buzz/leaderboard')
    ]);

    if (statusResult.ok && statusResult.data.ok) {
        const account = statusResult.data.account || {};
        const available = account.available !== undefined ? account.available : account.available_buzz;
        const locked = account.locked !== undefined ? account.locked : account.staked_buzz;
        const total = Number(available || 0) + Number(locked || 0);
        setText('buzzcoin-account-title', account.account || account.id || 'Buzz Account');
        setText('buzzcoin-status-text', `Connected via ${statusResult.data.base_url || 'BuzzService'}`);
        setText('buzzcoin-available', formatBuzzAmount(available));
        setText('buzzcoin-locked', formatBuzzAmount(locked));
        setText('buzzcoin-total', formatBuzzAmount(total));
    } else {
        setText('buzzcoin-account-title', 'BuzzService Offline');
        setText('buzzcoin-status-text', statusResult.data.error || 'BuzzCoin service is not configured or unavailable.');
        setText('buzzcoin-available', '-');
        setText('buzzcoin-locked', '-');
        setText('buzzcoin-total', '-');
    }

    const ledgerBody = document.getElementById('buzzcoin-ledger-body');
    if (ledgerBody) {
        const entries = (((ledgerResult.data || {}).ledger || {}).entries) || [];
        if (ledgerResult.ok && entries.length) {
            ledgerBody.innerHTML = entries.slice(0, 25).map(entry => `
                <tr>
                    <td>${formatShortTime(entry.created_at || entry.ts || entry.timestamp)}</td>
                    <td>${entry.entry_type || entry.type || '-'}</td>
                    <td class="${Number(entry.amount || 0) < 0 ? 'trade-sell' : 'trade-buy'}">${formatBuzzAmount(entry.amount)}</td>
                    <td>${entry.reason || entry.memo || '-'}</td>
                </tr>
            `).join('');
            setText('buzzcoin-ledger-state', 'Live');
        } else {
            ledgerBody.innerHTML = `<tr><td colspan="4" class="loading-text">${ledgerResult.data.error || 'No ledger entries available'}</td></tr>`;
            setText('buzzcoin-ledger-state', ledgerResult.ok ? 'Empty' : 'Offline');
        }
    }

    const leaderboard = document.getElementById('buzzcoin-leaderboard');
    if (leaderboard) {
        const rows = (leaderboardResult.data || {}).rows || [];
        if (leaderboardResult.ok && rows.length) {
            leaderboard.innerHTML = rows.slice(0, 8).map(row => `
                <div class="leaderboard-item">
                    <div>
                        <span>${row.account || 'Account'}</span>
                        <strong>${formatBuzzAmount(row.available)} available | ${formatBuzzAmount(row.locked)} locked</strong>
                    </div>
                    <div class="leaderboard-total">${formatBuzzAmount(row.total)}</div>
                </div>
            `).join('');
        } else {
            leaderboard.innerHTML = `<p class="loading-text">${leaderboardResult.data.error || 'No leaderboard rows available'}</p>`;
        }
    }
    } finally {
        loadingState.buzzcoin = false;
    }
}

async function loadSwarmGuardData() {
    if (loadingState.swarmguard) return;
    loadingState.swarmguard = true;
    try {
    const [decisionResult, rulesResult, risksResult] = await Promise.all([
        fetchOptionalAPI('/swarmguard.json'),
        fetchOptionalAPI('/swarmguard/rules'),
        fetchOptionalAPI('/swarmguard/risk_register')
    ]);

    const payload = (decisionResult.data || {}).payload || {};
    setText('swarmguard-decision', payload.decision || '-');
    setText('swarmguard-reason', payload.reason || 'Waiting for guard decision...');
    setText('swarmguard-action', payload.action || '-');
    setText('swarmguard-symbol', payload.symbol || '-');
    setText('swarmguard-size', payload.position_size !== undefined ? String(payload.position_size) : '-');

    const rulebook = document.getElementById('swarmguard-rulebook');
    if (rulebook) {
        const caps = (rulesResult.data || {}).regime_caps || {};
        const thresholds = (rulesResult.data || {}).svs_thresholds || {};
        const capRows = Object.entries(caps).map(([name, cap]) => `
            <div class="rulebook-item">
                <span>${name}</span>
                <strong>$${cap.max_notional_usdt || '-'} max | ${cap.cooldown_secs || '-'}s cooldown</strong>
                <p>${(cap.allowed_recommendations || []).join(', ') || 'No recommendations listed'}</p>
            </div>
        `).join('');
        rulebook.innerHTML = capRows || `
            <div class="rulebook-item">
                <span>SVS Threshold</span>
                <strong>${thresholds.reject_below || '-'}</strong>
                <p>Rulebook unavailable or empty.</p>
            </div>
        `;
    }

    const risks = document.getElementById('swarmguard-risks');
    if (risks) {
        const rows = (risksResult.data || {}).risk_register || [];
        if (rows.length) {
            risks.innerHTML = rows.slice(0, 8).map(row => `
                <div class="risk-card">
                    <div>
                        <span>${row.risk_id || 'Risk'}</span>
                        <strong>${row.category || '-'}</strong>
                    </div>
                    <div class="risk-impact">${row.impact || '-'}</div>
                    <p>${row.description || ''}</p>
                </div>
            `).join('');
        } else {
            risks.innerHTML = '<p class="loading-text">No risk register rows available</p>';
        }
    }
    } finally {
        loadingState.swarmguard = false;
    }
}

// Data loading functions
async function loadDashboardData() {
    if (loadingState.dashboard) return;
    loadingState.dashboard = true;
    try {
    const { status, wallet, metrics, priceSeries, integrations, buzz, performance } = await getDashboardSources();
    const data = status;
    if (!data) return;

    // Update wallet balance
    const walletTotal = (
        (wallet && wallet.equity_usd_est)
        || (data.wallet && data.wallet.total_usd)
        || (metrics && metrics.trading && metrics.trading.equity_usd_est)
        || 0
    );
    if (walletTotal !== undefined) {
        const balance = Number(walletTotal) || 0;
        document.getElementById('wallet-balance').textContent = `$${balance.toFixed(2)}`;
    }

    // Update active symbol
    if (data.symbol) {
        document.getElementById('active-symbol').textContent = data.symbol;
    }

    // Update current price
    const livePrice = (
        Number(data.market && data.market.price)
        || extractMetricPrice(metrics)
        || latestPriceFromSeries(priceSeries)
        || 0
    );
    if (livePrice) {
        document.getElementById('current-price').textContent = `$${parseFloat(livePrice).toFixed(2)}`;
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

    updateMetricInstruments({ status, wallet, metrics, priceSeries, integrations, buzz, performance });
    updateDashboardVisuals(data);
    if (priceSeries && priceSeries.prices) {
        renderPriceChartInto({
            lineId: 'dashboard-market-line',
            areaId: 'dashboard-market-area',
            latestId: 'dashboard-market-latest',
            startId: 'dashboard-market-start',
            rangeId: 'dashboard-market-range',
            endId: 'dashboard-market-end',
            labels: priceSeries.labels || [],
            prices: priceSeries.prices || []
        });
        setText('dashboard-market-title', `${data.symbol || 'Market'} Market Preview`);
    } else {
        loadMarketPreview(data.symbol);
    }
    } finally {
        loadingState.dashboard = false;
    }
}

async function loadAgentsData() {
    if (loadingState.agents) return;
    loadingState.agents = true;
    try {
    const data = await fetchAPI('/api/status');
    if (!data || !data.agents) return;

    updateAgentsSummary(data.agents);
    loadAgentPriceGraph(data.symbol);

    const container = document.getElementById('agents-container');
    container.innerHTML = '';

    Object.entries(data.agents).forEach(([name, agent]) => {
        const card = document.createElement('div');
        card.className = 'agent-card';
        
        const statusClass = agent.status === 'active' ? 'active' : 'inactive';
        const meterValue = agentMeterValue(name, agent);
        
        card.innerHTML = `
            <h4>
                <span class="agent-title">
                    <span class="agent-bee"><img src="${getAgentIcon(name)}" alt=""></span>
                    <span class="agent-name">${formatAgentName(name)}</span>
                </span>
                <span class="agent-status ${statusClass}"></span>
            </h4>
            <div class="status-item">
                <span class="status-label">Status</span>
                <span class="status-value">${agent.status || 'unknown'}</span>
            </div>
            <div class="agent-mini-meter">
                <div class="meter-track">
                    <span class="meter-fill" style="width: ${meterValue}%"></span>
                </div>
            </div>
            <div class="status-item">
                <span class="status-label">Uptime</span>
                <span class="status-value">${agent.uptime && agent.uptime !== '-' ? agent.uptime : runtimeUptime()}</span>
            </div>
            ${agent.last_action ? `
                <div class="status-item">
                    <span class="status-label">Last Action</span>
                    <span class="status-value">${agent.last_action}</span>
                </div>
            ` : ''}
        `;
        
        container.appendChild(card);
    });
    } finally {
        loadingState.agents = false;
    }
}

async function loadTradesData() {
    if (loadingState.trades) return;
    loadingState.trades = true;
    try {
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
    } finally {
        loadingState.trades = false;
    }
}

async function loadPerformanceData() {
    if (loadingState.performance) return;
    loadingState.performance = true;
    try {
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
    } finally {
        loadingState.performance = false;
    }
}

async function loadLogsData() {
    if (loadingState.logs) return;
    loadingState.logs = true;
    try {
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
    } finally {
        loadingState.logs = false;
    }
}

function showNotification(message, type = 'info') {
    // Simple notification - you can enhance this
    console.log(`[${type}] ${message}`);
}

// Start the app
window.addEventListener('DOMContentLoaded', init);
