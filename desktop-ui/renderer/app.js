// State management
const initialQueryUrl = (() => {
    try {
        return new URLSearchParams(window.location.search).get('backendUrl') || '';
    } catch (_error) {
        return '';
    }
})();
const storedBackendUrl = (() => {
    try {
        return localStorage.getItem('backendUrl') || '';
    } catch (_error) {
        return '';
    }
})();
let backendUrl = initialQueryUrl || storedBackendUrl || 'http://127.0.0.1:5000';
let autoRefreshInterval = null;
let isConnected = false;
const loadingState = {};
const appStartedAt = Date.now();
let backendReconnectPromise = null;
const desktopAPI = window.electronAPI || {
    getBackendUrl: async () => window.location.origin,
    setBackendUrl: async (url) => ({ success: true, url }),
    onShowSettings: () => {},
    onShowAbout: () => {}
};
const iconBasePath = '../../static/';
const agentIconMap = {
    coingecko: 'market.png',
    config_agent: 'configAgent.png.svg',
    controlled_growth_governor: 'growth.png.svg',
    coordinator: 'coordinator.png',
    council: 'council.png',
    data_store: 'datastore.png',
    datastore: 'datastore.png',
    dex_margin_oracle: 'oracle.png',
    evidence_registry: 'validation.png.svg',
    event_spine: 'eventSpine.png.svg',
    execution: 'execution.png',
    execution_lab: 'execution.png',
    execution_parity: 'executionParity.png.svg',
    hummingbot_lifecycle: 'hummingbotLifecycle.png.svg',
    hypothesis_swarm: 'hypothesis.png.svg',
    market_making_advisors: 'workerProtection.png.svg',
    ml_research_lab: 'mlResearch.png.svg',
    phoenix_authority: 'growth.png.svg',
    public_bot_backtests: 'hypothesis.png.svg',
    public_bot_bridge: 'bridge.png.svg',
    research_architecture: 'hypothesis.png.svg',
    shadow_flight: 'shadowflight.png.svg',
    signal_marketplace: 'signalMarketplace.png.svg',
    tiny_live_canary: 'canary.png.svg',
    validation_lab: 'validation.png.svg',
    executor_registry: 'execution.png',
    kill_switch: 'killswitch.png',
    logging: 'logging.png',
    market_data: 'market.png',
    observation_swarm: 'market.png',
    network: 'network.png',
    nurse: 'nurse.png',
    openclaw: 'strategy.png',
    oracle: 'oracle.png',
    performance: 'performance.png',
    security: 'security.png',
    sentiment: 'market.png',
    strategy: 'strategy.png',
    swarmguard: 'swarmguard.png',
    trend: 'market.png',
    ui: 'ui.png',
    wallet: 'wallet.png',
    worker_bollinger: 'workerBollinger.png.svg',
    worker_breakout: 'workerBreakout.png',
    worker_exit_risk: 'workerExitRisk.png.svg',
    worker_latency: 'performance.png',
    worker_momentum: 'workerMomentum.png',
    worker_protection: 'workerProtection.png.svg',
    worker_rsi: 'workerRSI.png',
    worker_rsi2: 'workerRSI.png',
    worker_sma: 'strategy.png',
    worker_supertrend: 'workerSupertrend.png.svg',
    worker_vol_expansion: 'workerVolExpansion.png.svg'
};

// Initialize app
async function init() {
    setupNavigation();
    setupEventListeners();

    try {
        const configuredUrl = await desktopAPI.getBackendUrl();
        if (configuredUrl) {
            backendUrl = configuredUrl;
            try {
                localStorage.setItem('backendUrl', backendUrl);
            } catch (_error) {
                // Local persistence is optional in Electron.
            }
        }
    } catch (error) {
        console.warn('Falling back to stored/default backend URL:', error);
    }

    const backendInput = document.getElementById('backend-url');
    if (backendInput) {
        backendInput.value = backendUrl;
    }

    await connectToAvailableBackend();
    loadDashboardData();

    try {
        const autoRefresh = localStorage.getItem('autoRefresh') !== 'false';
        const autoRefreshToggle = document.getElementById('auto-refresh');
        if (autoRefreshToggle) {
            autoRefreshToggle.checked = autoRefresh;
        }
        if (autoRefresh) {
            startAutoRefresh();
        }
    } catch (error) {
        console.error('App preference initialization failed:', error);
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
        const viewLoaders = {
            market: loadMarketPreview,
            observation: loadObservationData,
            hypotheses: loadHypothesisData,
            executionlab: loadExecutionLabData,
            validationlab: loadValidationLabData,
            shadowflight: loadShadowFlightData,
            canary: loadCanaryData,
            growth: loadGrowthData,
            agents: loadAgentsData,
            buzzcoin: loadBuzzCoinData,
            swarmguard: loadSwarmGuardData,
            trades: loadTradesData,
            performance: loadPerformanceData,
            integrations: loadIntegrationsData,
            logs: loadLogsData,
        };
        triggerViewLoad(viewName, viewLoaders[viewName]);
    }
}

function triggerViewLoad(viewName, loader) {
    if (typeof loader !== 'function') return;
    Promise.resolve()
        .then(() => loader())
        .catch(error => {
            console.error(`${viewName} view failed:`, error);
            showNotification(`${viewName} view failed to render`, 'error');
        });
}

function formatPercent(value) {
    if (value == null || Number.isNaN(Number(value))) return '-';
    return `${(Number(value) * 100).toFixed(1)}%`;
}

function formatBps(value, digits = 2) {
    if (value == null || Number.isNaN(Number(value))) return '-';
    return `${Number(value).toFixed(digits)} bps`;
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
    const saveBackendButton = document.getElementById('save-backend-url');
    if (saveBackendButton) {
        saveBackendButton.addEventListener('click', async () => {
        const newUrl = document.getElementById('backend-url').value;
        await desktopAPI.setBackendUrl(newUrl);
        backendUrl = newUrl;
        try {
            localStorage.setItem('backendUrl', backendUrl);
        } catch (_error) {
            // Local persistence is optional in Electron.
        }
        await checkConnection();
        showNotification('Backend URL updated', 'success');
    });
    }

    const testConnectionButton = document.getElementById('test-connection-btn');
    if (testConnectionButton) {
        testConnectionButton.addEventListener('click', async () => {
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
    }

    const autoRefreshToggle = document.getElementById('auto-refresh');
    if (autoRefreshToggle) {
        autoRefreshToggle.addEventListener('change', (e) => {
        localStorage.setItem('autoRefresh', e.target.checked);
        if (e.target.checked) {
            startAutoRefresh();
        } else {
            stopAutoRefresh();
        }
    });
    }

    // Logs
    const clearLogsButton = document.getElementById('clear-logs-btn');
    if (clearLogsButton) {
        clearLogsButton.addEventListener('click', () => {
        document.getElementById('logs-container').innerHTML = '<p class="loading-text">Logs cleared</p>';
    });
    }

    const refreshLogsButton = document.getElementById('refresh-logs-btn');
    if (refreshLogsButton) refreshLogsButton.addEventListener('click', loadLogsData);
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
    desktopAPI.onShowSettings(() => {
        showView('settings');
        loadSettings(); // Call to load current settings
    });

    desktopAPI.onShowAbout(() => {
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
            } else if (viewId === 'observation') {
                loadObservationData();
            } else if (viewId === 'hypotheses') {
                loadHypothesisData();
            } else if (viewId === 'executionlab') {
                loadExecutionLabData();
            } else if (viewId === 'validationlab') {
                loadValidationLabData();
            } else if (viewId === 'shadowflight') {
                loadShadowFlightData();
            } else if (viewId === 'canary') {
                loadCanaryData();
            } else if (viewId === 'growth') {
                loadGrowthData();
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
        const reconnected = await reconnectBackend();
        if (!reconnected) {
            return null;
        }
        const retryController = new AbortController();
        const retryTimer = setTimeout(() => retryController.abort(), timeoutMs);
        try {
            const retryResponse = await fetch(`${backendUrl}${endpoint}`, { signal: retryController.signal });
            if (!retryResponse.ok) throw new Error(`HTTP ${retryResponse.status}`);
            return await retryResponse.json();
        } catch (retryError) {
            console.error('API retry error:', retryError);
            return null;
        } finally {
            clearTimeout(retryTimer);
        }
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

function backendCandidates() {
    const candidates = [
        backendUrl,
        initialQueryUrl,
        storedBackendUrl,
        'http://127.0.0.1:5000',
        'http://localhost:5000',
        'http://127.0.0.1:5010',
        'http://127.0.0.1:5001',
        'http://localhost:5010',
        'http://localhost:5001'
    ];
    return [...new Set(candidates.filter(value => value && !String(value).startsWith('file:')))];
}

async function connectToAvailableBackend() {
    for (const candidate of backendCandidates()) {
        backendUrl = candidate;
        if (await checkConnection()) {
            try {
                localStorage.setItem('backendUrl', backendUrl);
            } catch (_error) {
                // Local persistence is optional in Electron.
            }
            const backendInput = document.getElementById('backend-url');
            if (backendInput) {
                backendInput.value = backendUrl;
            }
            return true;
        }
    }
    return false;
}

async function reconnectBackend() {
    if (backendReconnectPromise) {
        return backendReconnectPromise;
    }
    backendReconnectPromise = (async () => {
        const connected = await connectToAvailableBackend();
        if (!connected) {
            isConnected = false;
            updateConnectionStatus();
        }
        return connected;
    })();
    try {
        return await backendReconnectPromise;
    } finally {
        backendReconnectPromise = null;
    }
}

function updateConnectionStatus() {
    const statusBadge = document.getElementById('connection-status');
    const statusLabel = document.getElementById('connection-label');
    if (!statusBadge) return;
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
    const publicBots = payload.public_bots || {};
    const repos = Object.entries((publicBots && publicBots.repos) || {});
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
        },
        {
            label: 'Sidecar Repos',
            value: repos.length ? `${repos.filter(([, meta]) => meta.present).length}/${repos.length} present` : 'none',
            detail: repos.length
                ? repos.slice(0, 4).map(([name, meta]) => `${name}:${meta.present ? 'ready' : 'missing'}`).join(' | ')
                : 'Attach Freqtrade, Jesse, Hummingbot, or OctoBot repos to deepen the research loop.'
        }
    ];
    repos.filter(([, meta]) => meta.present).slice(0, 4).forEach(([name, meta]) => rows.push({
        label: name,
        value: meta.mode || 'sidecar',
        detail: `${meta.license || '-'} | ${(meta.strengths || []).slice(0, 3).join(', ') || 'research sidecar'}`
    }));
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
    const publicBots = payload.public_bots || {};
    const sidecarCommands = publicBots.sidecar_commands || {};
    const commandRows = Object.entries(sidecarCommands).map(([name, meta]) => `
        <div class="integration-list-item">
            <div><span>${escapeHTML(name)}</span><strong>${escapeHTML(meta.notes || 'sidecar command')}</strong></div>
            <p>${escapeHTML(meta.start || meta.research || meta.dry_run_backtest || 'No command provided')}</p>
        </div>
    `).join('');
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
            ${commandRows}
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
    const publicBots = payload.public_bots || {};
    const repoEntries = Object.values((publicBots && publicBots.repos) || {});
    const readyRepos = repoEntries.filter(meta => meta && meta.present).length;
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
    setText(
        'integration-hero-text',
        `${statuses.hummingbot_v2_adapter || 'plan_and_lifecycle'} | ${statuses.public_bot_backtesting || 'research pending'} | ${readyRepos}/${repoEntries.length || 0} sidecar repos ready`
    );
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


async function loadObservationData() {
    if (loadingState.observation) return;
    loadingState.observation = true;
    try {
        const data = await fetchAPI('/observation.json?limit=1&compact=1', 30000);
        if (!data) {
            setText('observation-status', 'Offline');
            setText('observation-status-caption', 'Backend observation endpoint unavailable');
            return;
        }
        const latest = data.latest || {};
        const run = latest.run || {};
        const candidates = Array.isArray(latest.candidates) ? latest.candidates : [];
        const status = latest.status || (data.status && data.status.status) || 'WAITING';
        const quality = Number(run.mean_data_quality || 0);
        const readiness = data.readiness || {};
        const summary = data.summary || {};

        setText('observation-status', status);
        setText('observation-status-caption', latest.observed_at || 'Public market telemetry only');
        setText('observation-symbols', run.symbols_successful ?? candidates.length ?? 0);
        setText('observation-quality', `${Math.round(quality * 100)}%`);
        setText('observation-days', `${Number(readiness.observed_days || 0).toFixed(2)}d`);
        setText(
            'observation-readiness',
            readiness.ready_for_phase2_review ? 'Ready for human Phase 2 review' : 'Phase 2 gate remains closed'
        );
        setText('observation-run-id', run.run_id || 'No run yet');
        setText('observation-dataset-hash', `DATASET HASH: ${(latest.dataset_hash || '-').slice(0, 18)}`);
        const topSymbol = summary.top_symbol || null;
        setText('observation-top-symbol', topSymbol && topSymbol.symbol ? topSymbol.symbol : 'No leader yet');
        setText(
            'observation-top-symbol-detail',
            topSymbol && topSymbol.symbol
                ? `${formatBps(topSymbol.spread_bps)} spread · $${Number(topSymbol.depth_usd_25bps || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })} depth`
                : 'No symbol focus yet'
        );
        setText('observation-avg-spread', formatBps(summary.avg_spread_bps));
        setText(
            'observation-avg-depth',
            summary.avg_depth_usd_25bps == null || Number.isNaN(Number(summary.avg_depth_usd_25bps))
                ? '-'
                : `$${Number(summary.avg_depth_usd_25bps).toLocaleString(undefined, { maximumFractionDigits: 0 })}`
        );
        setText(
            'observation-avg-freshness',
            summary.avg_freshness_sec == null || Number.isNaN(Number(summary.avg_freshness_sec))
                ? '-'
                : `${Number(summary.avg_freshness_sec).toFixed(2)}s`
        );
        const regimeBody = document.getElementById('observation-regime-tbody');
        if (regimeBody) {
            regimeBody.innerHTML = '';
            const regimeRows = Array.isArray(summary.regime_mix) ? summary.regime_mix : [];
            if (!regimeRows.length) {
                regimeBody.innerHTML = '<tr><td colspan="2" class="loading-text">No regime mix recorded yet.</td></tr>';
            } else {
                regimeRows.forEach(entry => {
                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td><strong>${entry.regime || '-'}</strong></td>
                        <td>${Number(entry.count || 0)}</td>
                    `;
                    regimeBody.appendChild(row);
                });
            }
        }
        const strictBody = document.getElementById('observation-strict-tbody');
        if (strictBody) {
            strictBody.innerHTML = '';
            const rows = Array.isArray(summary.strict_eligible_symbols) ? summary.strict_eligible_symbols : [];
            strictBody.innerHTML = rows.length
                ? rows.map(row => `
                    <tr>
                        <td><strong>${row.symbol || '-'}</strong></td>
                        <td>${Number(row.score || 0).toFixed(3)}</td>
                        <td>${formatBps(row.spread_bps)}</td>
                        <td>${row.depth_usd_25bps == null ? '-' : `$${Number(row.depth_usd_25bps).toLocaleString(undefined, { maximumFractionDigits: 0 })}`}</td>
                    </tr>
                `).join('')
                : '<tr><td colspan="4" class="loading-text">No strict eligible universe yet.</td></tr>';
        }
        const benchBody = document.getElementById('observation-bench-tbody');
        if (benchBody) {
            benchBody.innerHTML = '';
            const rows = Array.isArray(summary.research_bench_symbols) ? summary.research_bench_symbols : [];
            benchBody.innerHTML = rows.length
                ? rows.map(row => `
                    <tr>
                        <td><strong>${row.symbol || '-'}</strong></td>
                        <td>${Number(row.tradable_opportunity_score || 0).toFixed(3)}</td>
                        <td title="${Array.isArray(row.rejection_reasons) ? row.rejection_reasons.join(', ') : ''}">${Array.isArray(row.rejection_reasons) && row.rejection_reasons.length ? row.rejection_reasons.slice(0, 2).join(', ') : '-'}</td>
                    </tr>
                `).join('')
                : '<tr><td colspan="3" class="loading-text">No research bench symbols yet.</td></tr>';
        }
        const cohortBody = document.getElementById('observation-cohort-tbody');
        if (cohortBody) {
            cohortBody.innerHTML = '';
            const cohorts = summary.universe_cohorts || {};
            const entries = Object.entries(cohorts);
            cohortBody.innerHTML = entries.length
                ? entries.map(([name, rows]) => `
                    <tr>
                        <td><strong>${name}</strong></td>
                        <td>${Array.isArray(rows) && rows.length ? rows.map(row => row.symbol || '-').join(', ') : '-'}</td>
                    </tr>
                `).join('')
                : '<tr><td colspan="2" class="loading-text">No cohort universe built yet.</td></tr>';
        }
        const whyNow = document.getElementById('observation-why-now');
        if (whyNow) {
            const lines = Array.isArray(summary.why_now) ? summary.why_now : [];
            whyNow.textContent = lines.length ? lines.join('\n') : 'Waiting for observation summary...';
        }

        const tbody = document.getElementById('observation-tbody');
        if (!tbody) return;
        tbody.innerHTML = '';
        if (!candidates.length) {
            tbody.innerHTML = '<tr><td colspan="9" class="loading-text">No observation candidates recorded yet.</td></tr>';
            return;
        }
        candidates.forEach((candidate, index) => {
            const row = document.createElement('tr');
            const values = candidate.values || {};
            const reasons = Array.isArray(candidate.rejection_reasons) ? candidate.rejection_reasons : [];
            const qualityPct = Math.round(Number(candidate.data_quality || 0) * 100);
            const spread = Number(candidate.spread_bps);
            const depth = Number(candidate.depth_usd_25bps);
            const expansion = Number(values.volatility_expansion);
            const volumeZ = Number(values.volume_zscore);
            const freshness = Number(candidate.freshness_sec);
            const regimeInputs = values.regime_inputs || {};
            const regimeHint = regimeInputs.regime_hint || '-';
            row.innerHTML = `
                <td>${index + 1}</td>
                <td><strong>${candidate.symbol || '-'}</strong></td>
                <td title="freshness ${Number.isFinite(freshness) ? `${freshness.toFixed(2)}s` : '-'}">${Number.isFinite(qualityPct) ? `${qualityPct}%` : '-'}</td>
                <td title="${regimeHint}">${Number.isFinite(spread) ? `${spread.toFixed(2)} bps` : '-'}</td>
                <td>${Number.isFinite(depth) ? `$${depth.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '-'}</td>
                <td>${Number.isFinite(expansion) ? `${expansion.toFixed(2)}×` : '-'}</td>
                <td>${Number.isFinite(volumeZ) ? volumeZ.toFixed(2) : '-'}</td>
                <td class="${candidate.observation_eligible ? 'trade-buy' : 'trade-sell'}">${candidate.observation_eligible ? 'YES' : 'NO'}</td>
                <td title="${reasons.join(', ')}">${reasons.length ? reasons.slice(0, 2).join(', ') : `${regimeHint} · research eligible`}</td>
            `;
            tbody.appendChild(row);
        });
    } catch (error) {
        console.error('loadObservationData failed:', error);
        setText('observation-status', 'Error');
        setText('observation-status-caption', 'Observation view failed to render');
        const whyNow = document.getElementById('observation-why-now');
        if (whyNow) {
            whyNow.textContent = `Observation render error: ${error && error.message ? error.message : error}`;
        }
    } finally {
        loadingState.observation = false;
    }
}

async function loadHypothesisData() {
    if (loadingState.hypotheses) return;
    loadingState.hypotheses = true;
    try {
        const data = await fetchAPI('/hypotheses.json?limit=1&compact=1', 30000);
        if (!data) {
            setText('hypothesis-status', 'Offline');
            return;
        }
        const latest = data.latest || {};
        const run = latest.run || {};
        const readiness = data.readiness || {};
        const scorecard = data.scorecard || {};
        const summary = data.summary || {};
        const models = Array.isArray(scorecard.models) ? scorecard.models : [];
        const forecasts = Array.isArray(data.forecasts) ? data.forecasts : [];
        const settled = models.reduce((total, item) => total + Number(item.settled_trades || 0), 0);

        setText('hypothesis-status', latest.status || (data.status && data.status.status) || 'WAITING');
        setText('hypothesis-forecasts', run.forecasts_total ?? forecasts.length ?? 0);
        setText('hypothesis-active', run.non_abstain_forecasts ?? 0);
        setText('hypothesis-settled', settled);
        setText(
            'hypothesis-readiness',
            readiness.ready_for_phase3_review ? 'Ready for human Phase 3 review' : 'Phase 3 gate remains closed'
        );
        setText('hypothesis-run-id', run.run_id || 'No run yet');
        setText('hypothesis-dataset-hash', `DATASET HASH: ${(latest.dataset_hash || '-').slice(0, 18)}`);
        const federation = latest.federation || (data.status && data.status.federation) || {};
        setText('federation-model-count', String(federation.model_count ?? 0));
        setText('federation-runtime-count', String(federation.external_execution_runtimes_started ?? 0));
        const champion = summary.champion_model || null;
        const championResearch = summary.champion_research_model || null;
        const leadingSymbol = summary.leading_symbol || null;
        setText('hypothesis-champion-model', champion && champion.model_id ? champion.model_id : 'No leader yet');
        setText(
            'hypothesis-champion-model-detail',
            champion && champion.model_id
                ? `${champion.model_role || 'MODEL'} · ${formatBps(champion.mean_net_bps)} mean net · ${Number(champion.settled_trades || 0)} settled`
                : 'No settled evidence yet'
        );
        setText('hypothesis-champion-research', championResearch && championResearch.model_id ? championResearch.model_id : 'No research leader yet');
        setText(
            'hypothesis-champion-research-detail',
            championResearch && championResearch.model_id
                ? `${championResearch.model_family || championResearch.model_role || 'RESEARCH'} · ${formatBps(championResearch.mean_net_bps)} mean net`
                : 'Federated or native research winner not established yet'
        );
        setText('hypothesis-leading-symbol', leadingSymbol && leadingSymbol.symbol ? leadingSymbol.symbol : 'No focus yet');
        setText(
            'hypothesis-leading-symbol-detail',
            leadingSymbol && leadingSymbol.symbol
                ? `${formatBps(leadingSymbol.avg_expected_net_bps)} avg net · ${formatPercent(leadingSymbol.avg_probability_positive_net)} avg P(Net+)`
                : 'No active symbol cluster yet'
        );
        const whyNow = document.getElementById('hypothesis-why-now');
        if (whyNow) {
            const lines = Array.isArray(summary.why_now) ? summary.why_now : [];
            whyNow.textContent = lines.length ? lines.join('\n') : 'Waiting for Phase 2 explanation...';
        }
        const federationBody = document.getElementById('federation-model-tbody');
        if (federationBody) {
            federationBody.innerHTML = '';
            const federationModels = Array.isArray(federation.models) ? federation.models : [];
            if (!federationModels.length) {
                federationBody.innerHTML = '<tr><td colspan="6" class="loading-text">Federation disabled or unavailable.</td></tr>';
            } else {
                federationModels.forEach(model => {
                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td><strong>${model.model_id || '-'}</strong></td>
                        <td>${model.family || '-'}</td>
                        <td>${model.implementation || '-'}</td>
                        <td title="${model.fidelity || ''}">${model.fidelity || '-'}</td>
                        <td>${model.external_runtime ? 'EXTERNAL' : 'LOCAL'}</td>
                        <td class="trade-buy">RESEARCH ONLY</td>
                    `;
                    federationBody.appendChild(row);
                });
            }
        }

        const symbolFocusBody = document.getElementById('hypothesis-symbol-focus-tbody');
        if (symbolFocusBody) {
            symbolFocusBody.innerHTML = '';
            const focusRows = Array.isArray(summary.symbol_focus) ? summary.symbol_focus : [];
            if (!focusRows.length) {
                symbolFocusBody.innerHTML = '<tr><td colspan="6" class="loading-text">No non-abstain symbol cluster yet.</td></tr>';
            } else {
                focusRows.forEach(entry => {
                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td><strong>${entry.symbol || '-'}</strong></td>
                        <td>${Number(entry.forecast_count || 0)}</td>
                        <td class="${Number(entry.avg_expected_net_bps || 0) >= 0 ? 'trade-buy' : 'trade-sell'}">${formatBps(entry.avg_expected_net_bps)}</td>
                        <td>${formatPercent(entry.avg_probability_positive_net)}</td>
                        <td title="${entry.explanation || ''}">${Array.isArray(entry.regime_hints) && entry.regime_hints.length ? entry.regime_hints.join(', ') : '-'}</td>
                        <td>${Array.isArray(entry.top_models) && entry.top_models.length ? entry.top_models.join(', ') : '-'}</td>
                    `;
                    symbolFocusBody.appendChild(row);
                });
            }
        }
        const cohortBody = document.getElementById('hypothesis-cohort-tbody');
        if (cohortBody) {
            cohortBody.innerHTML = '';
            const rows = Object.entries(summary.cohort_breakdown || {});
            cohortBody.innerHTML = rows.length
                ? rows.map(([cohort, entry]) => `
                    <tr>
                        <td><strong>${cohort}</strong></td>
                        <td>${Number(entry.forecasts || 0)}</td>
                        <td>${formatPercent(entry.activation_rate)}</td>
                        <td class="${Number(entry.mean_expected_net_bps || 0) >= 0 ? 'trade-buy' : 'trade-sell'}">${formatBps(entry.mean_expected_net_bps)}</td>
                        <td class="${Number(entry.mean_realized_net_bps || 0) >= 0 ? 'trade-buy' : 'trade-sell'}">${formatBps(entry.mean_realized_net_bps)}</td>
                        <td>${Array.isArray(entry.top_models) && entry.top_models.length ? entry.top_models.map(item => item.model_id).join(', ') : '-'}</td>
                    </tr>
                `).join('')
                : '<tr><td colspan="6" class="loading-text">Waiting for cohort evidence...</td></tr>';
        }
        const abstentionBody = document.getElementById('hypothesis-abstention-tbody');
        if (abstentionBody) {
            abstentionBody.innerHTML = '';
            const rows = Array.isArray(summary.abstention_reason_breakdown) ? summary.abstention_reason_breakdown : [];
            abstentionBody.innerHTML = rows.length
                ? rows.map(entry => `
                    <tr>
                        <td><strong>${entry.reason || '-'}</strong></td>
                        <td>${Number(entry.count || 0)}</td>
                    </tr>
                `).join('')
                : '<tr><td colspan="2" class="loading-text">No abstention concentration yet.</td></tr>';
        }
        const recoveryBody = document.getElementById('hypothesis-recovery-tbody');
        if (recoveryBody) {
            recoveryBody.innerHTML = '';
            const rows = Array.isArray(summary.near_miss_recovery_candidates) ? summary.near_miss_recovery_candidates : [];
            recoveryBody.innerHTML = rows.length
                ? rows.map(entry => `
                    <tr>
                        <td><strong>${entry.symbol || '-'}</strong></td>
                        <td>${entry.model_id || '-'}</td>
                        <td>${formatPercent(entry.near_miss_score)}</td>
                        <td>${formatPercent(entry.tradability_score)}</td>
                        <td title="${Array.isArray(entry.largest_gaps) ? entry.largest_gaps.join(', ') : ''}">${Array.isArray(entry.largest_gaps) && entry.largest_gaps.length ? entry.largest_gaps[0] : (entry.reason || '-')}</td>
                    </tr>
                `).join('')
                : '<tr><td colspan="5" class="loading-text">No recovery candidates staged yet.</td></tr>';
        }
        const demotionBody = document.getElementById('hypothesis-demotion-tbody');
        if (demotionBody) {
            demotionBody.innerHTML = '';
            const rows = Array.isArray(summary.demotion_recommendations) ? summary.demotion_recommendations : [];
            demotionBody.innerHTML = rows.length
                ? rows.map(entry => `
                    <tr>
                        <td><strong>${entry.model_id || '-'}</strong></td>
                        <td>${Number(entry.settled_trades || 0)}</td>
                        <td>${formatPercent(entry.activation_rate)}</td>
                        <td class="${Number(entry.mean_expected_net_bps || 0) >= 0 ? 'trade-buy' : 'trade-sell'}">${formatBps(entry.mean_expected_net_bps)}</td>
                        <td class="${Number(entry.mean_net_bps || 0) >= 0 ? 'trade-buy' : 'trade-sell'}">${formatBps(entry.mean_net_bps)}</td>
                        <td title="${Array.isArray(entry.reasons) ? entry.reasons.join(', ') : ''}">${Array.isArray(entry.reasons) && entry.reasons.length ? entry.reasons.join(', ') : '-'}</td>
                    </tr>
                `).join('')
                : '<tr><td colspan="6" class="loading-text">No demotion candidates yet.</td></tr>';
        }

        const scoreBody = document.getElementById('hypothesis-scorecard-tbody');
        if (scoreBody) {
            scoreBody.innerHTML = '';
            if (!models.length) {
                scoreBody.innerHTML = '<tr><td colspan="8" class="loading-text">No settled model evidence yet.</td></tr>';
            } else {
                models.forEach(model => {
                    const row = document.createElement('tr');
                    const forecastsCount = Number(model.forecasts || 0);
                    const nonAbstain = Number(model.non_abstain || 0);
                    const actionRate = forecastsCount ? (nonAbstain / forecastsCount) * 100 : 0;
                    const winRate = formatPercent(model.win_rate);
                    const meanNet = formatBps(model.mean_net_bps);
                    const brier = model.brier_score == null ? '-' : Number(model.brier_score).toFixed(4);
                    row.innerHTML = `
                        <td><strong>${model.model_id || '-'}</strong></td>
                        <td>${model.model_role || (model.is_baseline ? 'BASELINE' : 'PRIMARY')}</td>
                        <td>${forecastsCount}</td>
                        <td>${Number(model.settled_trades || 0)}</td>
                        <td>${winRate}</td>
                        <td class="${Number(model.mean_net_bps || 0) >= 0 ? 'trade-buy' : 'trade-sell'}">${meanNet}</td>
                        <td>${brier}</td>
                        <td>${actionRate.toFixed(1)}%</td>
                    `;
                    scoreBody.appendChild(row);
                });
            }
        }

        const forecastBody = document.getElementById('hypothesis-forecast-tbody');
        if (forecastBody) {
            forecastBody.innerHTML = '';
            if (!forecasts.length) {
                forecastBody.innerHTML = '<tr><td colspan="9" class="loading-text">No forecasts recorded yet.</td></tr>';
            } else {
                forecasts.slice(0, 100).forEach(forecast => {
                    const row = document.createElement('tr');
                    const probability = formatPercent(forecast.probability_positive_net);
                    const move = formatBps(forecast.expected_move_bps, 1);
                    const cost = formatBps(forecast.expected_cost_bps, 1);
                    const net = formatBps(forecast.expected_net_bps, 1);
                    const state = forecast.abstain ? `ABSTAIN · ${forecast.reason || ''}` : (forecast.settled ? 'SETTLED' : 'OPEN');
                    row.innerHTML = `
                        <td><strong>${forecast.symbol || '-'}</strong></td>
                        <td>${forecast.model_id || '-'}</td>
                        <td>${Math.round(Number(forecast.horizon_seconds || 0) / 60)}m</td>
                        <td class="${forecast.direction === 'UP' ? 'trade-buy' : forecast.direction === 'DOWN' ? 'trade-sell' : ''}">${forecast.direction || '-'}</td>
                        <td>${probability}</td>
                        <td>${move}</td>
                        <td>${cost}</td>
                        <td>${net}</td>
                        <td title="${forecast.reason || ''}">${state}</td>
                    `;
                    forecastBody.appendChild(row);
                });
            }
        }
    } catch (error) {
        console.error('loadHypothesisData failed:', error);
        setText('hypothesis-status', 'Error');
        const whyNow = document.getElementById('hypothesis-why-now');
        if (whyNow) {
            whyNow.textContent = `Hypothesis view failed to render: ${error && error.message ? error.message : error}`;
        }
    } finally {
        loadingState.hypotheses = false;
    }
}

async function loadExecutionLabData() {
    if (loadingState.executionLab) return;
    loadingState.executionLab = true;
    try {
        const data = await fetchAPI('/execution_lab.json?limit=1&compact=1', 30000);
        if (!data) {
            setText('execution-lab-status', 'Offline');
            return;
        }
        const latest = data.latest || {};
        const run = latest.run || {};
        const scorecard = data.scorecard || {};
        const readiness = data.readiness || {};
        const summary = data.summary || {};
        const rows = Array.isArray(scorecard.rows) ? scorecard.rows : [];
        const orders = Array.isArray(data.orders) ? data.orders : [];
        const completed = rows.reduce((sum, row) => sum + Number(row.completed || 0), 0);
        const simulations = rows.reduce((sum, row) => sum + Number(row.simulations || 0), 0);
        const weightedFill = rows.reduce((sum, row) => sum + Number(row.mean_fill_ratio || 0) * Number(row.completed || 0), 0);
        const fillRate = completed ? weightedFill / completed : 0;

        setText('execution-lab-status', latest.status || (data.status && data.status.status) || 'WAITING');
        setText('execution-lab-simulations', run.simulations_created ?? simulations);
        setText('execution-lab-completed', completed);
        setText('execution-lab-fill-rate', `Mean fill: ${(fillRate * 100).toFixed(1)}%`);
        setText('execution-lab-evidence', readiness.completed_normal_simulations ?? 0);
        setText(
            'execution-lab-readiness',
            readiness.ready_for_phase4_review ? 'Ready for human Phase 4 review' : 'Phase 4 gate remains closed'
        );
        setText('execution-lab-run-id', run.run_id || 'No run yet');
        setText('execution-lab-dataset-hash', `DATASET HASH: ${(latest.dataset_hash || '-').slice(0, 18)}`);
        const bestPolicy = summary.best_normal_policy || null;
        setText(
            'execution-lab-best-policy',
            bestPolicy ? `${bestPolicy.model_id || '-'} / ${bestPolicy.order_policy || '-'}` : 'No winner yet'
        );
        setText(
            'execution-lab-best-policy-detail',
            bestPolicy
                ? `${bestPolicy.scenario || 'normal'} · ${formatBps(bestPolicy.mean_net_bps)} mean net`
                : 'No normal-cost winner yet'
        );
        setText('execution-lab-scenario-count', String(summary.scenario_count ?? 0));
        setText('execution-lab-policy-count', String(summary.policy_count ?? 0));
        setText('execution-lab-avg-cost', formatBps(summary.avg_total_cost_bps));
        setText('execution-lab-avg-latency', `Latency cost: ${formatBps(summary.avg_latency_bps)}`);
        setText('execution-lab-profitable-outcomes', `${Number(summary.profitable_outcomes || 0).toLocaleString()}`);
        setText('execution-lab-profitable-rate', `${formatPercent(summary.profitable_rate)} of completed simulations`);
        const recoverySignals = summary.recovery_signals || {};
        const bestRecovery = recoverySignals.best_recovery_candidate || null;
        const bestSuppressed = recoverySignals.best_suppressed_candidate || null;
        setText('execution-lab-recovering-count', Number(recoverySignals.recovering_candidates || 0));
        setText(
            'execution-lab-recovering-detail',
            bestRecovery
                ? `${bestRecovery.model_id || '-'} ${bestRecovery.symbol || '-'} · ${bestRecovery.regime_hint || 'unknown'} · ${formatBps(bestRecovery.recent_regime_historical_mean_net_bps)} recent`
                : 'No re-entry evidence yet'
        );
        setText('execution-lab-suppressed-count', Number(recoverySignals.suppressed_candidates || 0));
        setText(
            'execution-lab-suppressed-detail',
            bestSuppressed
                ? `${bestSuppressed.model_id || '-'} ${bestSuppressed.symbol || '-'} · ${bestSuppressed.regime_hint || 'unknown'} · ${formatBps(bestSuppressed.regime_historical_mean_net_bps)} long-run`
                : 'No damaged slices identified'
        );
        const capBody = document.getElementById('execution-lab-capabilities-tbody');
        if (capBody) {
            capBody.innerHTML = '';
            const caps = Array.isArray(summary.capabilities) ? summary.capabilities : [];
            if (!caps.length) {
                capBody.innerHTML = '<tr><td colspan="2" class="loading-text">No simulation capability map yet.</td></tr>';
            } else {
                caps.forEach(cap => {
                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td><strong>${String(cap.name || '-').replace(/_/g, ' ')}</strong></td>
                        <td class="${cap.active ? 'trade-buy' : 'trade-sell'}">${cap.active ? 'ACTIVE' : 'INACTIVE'}</td>
                    `;
                    capBody.appendChild(row);
                });
            }
        }
        const robustnessBody = document.getElementById('execution-lab-robustness-tbody');
        if (robustnessBody) {
            robustnessBody.innerHTML = '';
            const ranking = Array.isArray(summary.robustness_ranking) ? summary.robustness_ranking : [];
            if (!ranking.length) {
                robustnessBody.innerHTML = '<tr><td colspan="7" class="loading-text">No robustness ranking yet.</td></tr>';
            } else {
                ranking.forEach(item => {
                    const row = document.createElement('tr');
                    const tier = item.is_baseline ? 'BASELINE' : 'RESEARCH';
                    row.innerHTML = `
                        <td>${tier}</td>
                        <td><strong>${item.model_id || '-'}</strong></td>
                        <td>${item.order_policy || '-'}</td>
                        <td>${Number(item.scenario_coverage || 0)}</td>
                        <td>${Number(item.positive_scenarios || 0)}</td>
                        <td class="${Number(item.avg_mean_net_bps || 0) >= 0 ? 'trade-buy' : 'trade-sell'}">${formatBps(item.avg_mean_net_bps)}</td>
                        <td class="${Number(item.worst_mean_net_bps || 0) >= 0 ? 'trade-buy' : 'trade-sell'}">${formatBps(item.worst_mean_net_bps)}</td>
                    `;
                    robustnessBody.appendChild(row);
                });
            }
        }
        const researchWinnersBody = document.getElementById('execution-lab-research-winners-tbody');
        if (researchWinnersBody) {
            researchWinnersBody.innerHTML = '';
            const winners = Array.isArray(summary.research_winners) ? summary.research_winners : [];
            if (!winners.length) {
                researchWinnersBody.innerHTML = '<tr><td colspan="5" class="loading-text">No research winners yet.</td></tr>';
            } else {
                winners.forEach(item => {
                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td><strong>${item.model_id || '-'}</strong></td>
                        <td>${item.order_policy || '-'}</td>
                        <td class="${Number(item.avg_mean_net_bps || 0) >= 0 ? 'trade-buy' : 'trade-sell'}">${formatBps(item.avg_mean_net_bps)}</td>
                        <td class="${Number(item.worst_mean_net_bps || 0) >= 0 ? 'trade-buy' : 'trade-sell'}">${formatBps(item.worst_mean_net_bps)}</td>
                        <td>${Number(item.positive_scenarios || 0)}</td>
                    `;
                    researchWinnersBody.appendChild(row);
                });
            }
        }
        const recoveryBody = document.getElementById('execution-lab-recovery-tbody');
        if (recoveryBody) {
            recoveryBody.innerHTML = '';
            const recovering = Array.isArray(recoverySignals.recovering_sample) ? recoverySignals.recovering_sample : [];
            const suppressed = Array.isArray(recoverySignals.suppressed_sample) ? recoverySignals.suppressed_sample : [];
            const combined = [
                ...recovering.map(item => ({ state: 'RECOVERING', ...item })),
                ...suppressed.map(item => ({ state: 'SUPPRESSED', ...item })),
            ];
            if (!combined.length) {
                recoveryBody.innerHTML = '<tr><td colspan="8" class="loading-text">Waiting for recovery diagnostics...</td></tr>';
            } else {
                combined.slice(0, 16).forEach(item => {
                    const row = document.createElement('tr');
                    const recoveringState = item.state === 'RECOVERING';
                    row.innerHTML = `
                        <td class="${recoveringState ? 'trade-buy' : 'trade-sell'}"><strong>${item.state}</strong></td>
                        <td>${item.forecast_id || '-'}</td>
                        <td>${item.model_id || '-'}</td>
                        <td><strong>${item.symbol || '-'}</strong></td>
                        <td>${item.regime_hint || '-'}</td>
                        <td class="${Number(item.recent_regime_historical_mean_net_bps || 0) >= 0 ? 'trade-buy' : 'trade-sell'}">${formatBps(item.recent_regime_historical_mean_net_bps)}</td>
                        <td class="${Number(item.regime_historical_mean_net_bps || 0) >= 0 ? 'trade-buy' : 'trade-sell'}">${formatBps(item.regime_historical_mean_net_bps)}</td>
                        <td class="${Number(item.expected_net_bps || 0) >= 0 ? 'trade-buy' : 'trade-sell'}">${formatBps(item.expected_net_bps)}</td>
                    `;
                    recoveryBody.appendChild(row);
                });
            }
        }
        const adaptationBody = document.getElementById('execution-lab-adaptation-tbody');
        if (adaptationBody) {
            adaptationBody.innerHTML = '';
            const breakdown = summary.adaptation_breakdown || {};
            const rows = [
                ["Adapted", breakdown.adapted || null],
                ["Standard", breakdown.standard || null],
            ].filter(([, entry]) => entry);
            adaptationBody.innerHTML = rows.length
                ? rows.map(([label, entry]) => `
                    <tr>
                        <td><strong>${label}</strong></td>
                        <td>${Number(entry.completed || 0)}</td>
                        <td>${formatPercent(entry.profitable_rate)}</td>
                        <td class="${Number(entry.mean_net_bps || 0) >= 0 ? 'trade-buy' : 'trade-sell'}">${formatBps(entry.mean_net_bps)}</td>
                        <td>${Array.isArray(entry.adaptation_reasons) && entry.adaptation_reasons.length ? entry.adaptation_reasons[0].reason : '-'}</td>
                    </tr>
                `).join('')
                : '<tr><td colspan="5" class="loading-text">Waiting for adaptation comparison...</td></tr>';
        }
        const whyNow = document.getElementById('execution-lab-why-now');
        if (whyNow) {
            const lines = Array.isArray(summary.why_now) ? summary.why_now : [];
            whyNow.textContent = lines.length ? lines.join('\n') : 'Waiting for execution simulation summary...';
        }

        const scoreBody = document.getElementById('execution-lab-scorecard-tbody');
        if (scoreBody) {
            scoreBody.innerHTML = '';
            if (!rows.length) {
                scoreBody.innerHTML = '<tr><td colspan="8" class="loading-text">No execution scorecard evidence yet.</td></tr>';
            } else {
                rows.slice(0, 120).forEach(item => {
                    const row = document.createElement('tr');
                    const net = item.mean_net_bps == null ? '-' : `${Number(item.mean_net_bps).toFixed(2)} bps`;
                    const cost = item.mean_total_cost_bps == null ? '-' : `${Number(item.mean_total_cost_bps).toFixed(2)} bps`;
                    const win = item.win_rate == null ? '-' : `${(Number(item.win_rate) * 100).toFixed(1)}%`;
                    const fill = item.mean_fill_ratio == null ? '-' : `${(Number(item.mean_fill_ratio) * 100).toFixed(1)}%`;
                    row.innerHTML = `
                        <td><strong>${item.model_id || '-'}</strong></td>
                        <td>${item.order_policy || '-'}</td>
                        <td>${item.scenario || '-'}</td>
                        <td>${Number(item.completed || 0)}</td>
                        <td>${fill}</td>
                        <td>${win}</td>
                        <td class="${Number(item.mean_net_bps || 0) >= 0 ? 'trade-buy' : 'trade-sell'}">${net}</td>
                        <td>${cost}</td>
                    `;
                    scoreBody.appendChild(row);
                });
            }
        }

        const orderBody = document.getElementById('execution-lab-orders-tbody');
        if (orderBody) {
            orderBody.innerHTML = '';
            if (!orders.length) {
                orderBody.innerHTML = '<tr><td colspan="9" class="loading-text">No simulated orders recorded yet.</td></tr>';
            } else {
                orders.slice(0, 150).forEach(item => {
                    const row = document.createElement('tr');
                    const gross = item.gross_return_bps == null ? '-' : `${Number(item.gross_return_bps).toFixed(2)} bps`;
                    const net = item.net_return_bps == null ? '-' : `${Number(item.net_return_bps).toFixed(2)} bps`;
                    row.innerHTML = `
                        <td><strong>${item.symbol || '-'}</strong></td>
                        <td>${item.model_id || '-'}</td>
                        <td>${item.order_policy || '-'}</td>
                        <td>${item.scenario || '-'}</td>
                        <td>${item.terminal_state || item.status || '-'}</td>
                        <td>${(Number(item.fill_ratio || 0) * 100).toFixed(1)}%</td>
                        <td>${gross}</td>
                        <td class="${Number(item.net_return_bps || 0) >= 0 ? 'trade-buy' : 'trade-sell'}">${net}</td>
                        <td>${Number(item.spot_executable || 0) ? 'LONG' : 'SYNTHETIC'}</td>
                    `;
                    orderBody.appendChild(row);
                });
            }
        }
    } catch (error) {
        console.error('loadExecutionLabData failed:', error);
        setText('execution-lab-status', 'Error');
        const whyNow = document.getElementById('execution-lab-why-now');
        if (whyNow) {
            whyNow.textContent = `Execution lab view failed to render: ${error && error.message ? error.message : error}`;
        }
    } finally {
        loadingState.executionLab = false;
    }
}

async function loadValidationLabData() {
    if (loadingState.validationLab) return;
    loadingState.validationLab = true;
    try {
        const data = await fetchAPI('/validation_lab.json?limit=1&compact=1', 30000);
        if (!data) {
            setText('validation-lab-status', 'Offline');
            return;
        }
        const latest = data.latest || {};
        const readiness = data.readiness || latest.readiness || {};
        const pbo = latest.pbo || {};
        const summary = data.summary || {};
        const candidates = Array.isArray(latest.candidate_results)
            ? latest.candidate_results
            : (Array.isArray(data.candidates) ? data.candidates : []);
        setText('validation-lab-status', latest.status || (data.status && data.status.status) || 'WAITING');
        setText('validation-lab-candidates', latest.candidate_count ?? candidates.length ?? 0);
        setText('validation-lab-pbo', pbo.pbo_estimate == null ? '-' : `${(Number(pbo.pbo_estimate) * 100).toFixed(1)}%`);
        setText('validation-lab-ready', readiness.ready_for_phase5_review ? 'REVIEW READY' : 'CLOSED');
        setText(
            'validation-lab-readiness',
            readiness.ready_for_phase5_review ? 'Human Phase 5 review may begin' : 'Adversarial gate remains closed'
        );
        setText('validation-lab-run-id', latest.run_id || 'No run yet');
        setText('validation-lab-dataset-hash', `DATASET HASH: ${(latest.dataset_hash || '-').slice(0, 18)}`);
        const champion = summary.champion || latest.champion || {};
        const bootstrap = champion.bootstrap || {};
        const topFailure = Array.isArray(summary.top_failure_reasons) && summary.top_failure_reasons.length
            ? summary.top_failure_reasons[0]
            : null;
        setText('validation-lab-champion', champion.candidate_key || 'No champion');
        setText(
            'validation-lab-champion-detail',
            champion.candidate_key
                ? `${formatBps((champion.normal || {}).mean_net_bps)} mean net · ${(Number(champion.walk_forward_positive_ratio || 0) * 100).toFixed(1)}% WF+`
                : 'Awaiting robust candidate'
        );
        setText('validation-lab-robust-score', champion.robust_score == null ? '-' : Number(champion.robust_score).toFixed(2));
        setText(
            'validation-lab-bootstrap-detail',
            champion.candidate_key
                ? `${formatBps(bootstrap.lower_95_bps)} lower 95% · ${(Number(((champion.deflated_sharpe || {}).dsr_probability || 0)) * 100).toFixed(1)}% DSR`
                : 'Bootstrap lower bound not available'
        );
        setText(
            'validation-lab-pass-fail',
            `${Number(summary.passing_count || 0)} / ${Number(summary.failing_count || 0)}`
        );
        setText('validation-lab-pass-fail-detail', 'Pass / fail candidate gate outcomes');
        setText('validation-lab-top-failure', topFailure ? topFailure.reason : 'None');
        setText(
            'validation-lab-top-failure-detail',
            topFailure ? `${Number(topFailure.count || 0)} candidate rejections` : 'No recurring rejection pattern yet'
        );
        const whyNow = document.getElementById('validation-lab-why-now');
        if (whyNow) {
            const lines = Array.isArray(summary.why_now) ? summary.why_now : [];
            whyNow.textContent = lines.length ? lines.join('\n') : 'Waiting for validation summary...';
        }

        const tbody = document.getElementById('validation-lab-candidates-tbody');
        if (tbody) {
            tbody.innerHTML = '';
            if (!candidates.length) {
                tbody.innerHTML = '<tr><td colspan="8" class="loading-text">No candidate validation evidence yet.</td></tr>';
            } else {
                candidates.slice(0, 100).forEach(item => {
                    const normal = item.normal || {};
                    const bootstrap = item.bootstrap || {};
                    const dsr = item.deflated_sharpe || {};
                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td><strong>${item.candidate_key || `${item.model_id || '-'}::${item.order_policy || '-'}`}</strong></td>
                        <td>${Number(normal.samples ?? item.normal_samples ?? 0)}</td>
                        <td class="${Number(normal.mean_net_bps ?? item.mean_net_bps ?? 0) >= 0 ? 'trade-buy' : 'trade-sell'}">${Number(normal.mean_net_bps ?? item.mean_net_bps ?? 0).toFixed(2)} bps</td>
                        <td>${Number(bootstrap.lower_95_bps ?? item.bootstrap_lower_95_bps ?? 0).toFixed(2)} bps</td>
                        <td>${(Number(dsr.dsr_probability ?? item.dsr_probability ?? 0) * 100).toFixed(1)}%</td>
                        <td>${(Number(item.walk_forward_positive_ratio || 0) * 100).toFixed(1)}%</td>
                        <td>${(Number(item.symbol_profit_concentration || 0) * 100).toFixed(1)}%</td>
                        <td class="${item.passes_candidate_gates ? 'trade-buy' : 'trade-sell'}">${item.passes_candidate_gates ? 'PASS' : 'REJECT'}</td>
                    `;
                    tbody.appendChild(row);
                });
            }
        }
        const reasons = document.getElementById('validation-lab-reasons');
        if (reasons) {
            const globalReasons = Array.isArray(readiness.reasons) ? readiness.reasons : [];
            const candidateReasons = Array.isArray(champion.reasons) ? champion.reasons : [];
            const lines = [
                `Champion: ${champion.candidate_key || 'none'}`,
                `Global gate: ${globalReasons.length ? globalReasons.join(', ') : 'no global failures'}`,
                `Champion gate: ${candidateReasons.length ? candidateReasons.join(', ') : 'no candidate failures'}`,
                'Execution eligibility remains FALSE. Human review is mandatory.'
            ];
            reasons.textContent = lines.join('\n');
        }
    } catch (error) {
        console.error('loadValidationLabData failed:', error);
        setText('validation-lab-status', 'Error');
        const whyNow = document.getElementById('validation-lab-why-now');
        if (whyNow) {
            whyNow.textContent = `Validation view failed to render: ${error && error.message ? error.message : error}`;
        }
    } finally {
        loadingState.validationLab = false;
    }
}

async function loadShadowFlightData() {
    if (loadingState.shadowFlight) return;
    loadingState.shadowFlight = true;
    try {
        const data = await fetchAPI('/shadow_flight.json?limit=250', 30000);
        if (!data) {
            setText('shadow-flight-status', 'Offline');
            return;
        }
        const latest = data.latest || {};
        const freeze = data.freeze || latest.freeze || {};
        const readiness = data.readiness || latest.readiness || {};
        const score = data.scorecard || readiness.scorecard || {};
        const intents = Array.isArray(data.intents) ? data.intents : [];
        setText('shadow-flight-status', latest.status || (data.status && data.status.status) || 'WAITING');
        setText('shadow-flight-intents', intents.length);
        setText('shadow-flight-settled', Number(score.settled || 0));
        setText('shadow-flight-ready', readiness.ready_for_phase6_review ? 'REVIEW READY' : 'CLOSED');
        setText('shadow-flight-readiness', readiness.ready_for_phase6_review ? 'Human Phase 6 review may begin' : 'Shadow evidence gate remains closed');
        setText('shadow-flight-champion', freeze.candidate_key || 'No approved champion');
        setText('shadow-flight-run-id', latest.run_id || 'No run yet');
        setText('shadow-flight-transmissions', Number(score.transmission_attempts || 0));
        setText('shadow-flight-config-hash', `FREEZE HASH: ${(freeze.config_hash || '-').slice(0, 18)}`);
        setText('shadow-flight-cost-mae', score.cost_mae_bps == null ? 'COST MAE: -' : `COST MAE: ${Number(score.cost_mae_bps).toFixed(2)} bps`);
        const tbody = document.getElementById('shadow-flight-intents-tbody');
        if (tbody) {
            tbody.innerHTML = '';
            if (!intents.length) {
                tbody.innerHTML = '<tr><td colspan="8" class="loading-text">No shadow intents yet.</td></tr>';
            } else {
                intents.slice(0, 100).forEach(item => {
                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td><strong>${item.symbol || '-'}</strong></td>
                        <td>${item.model_id || '-'}</td>
                        <td>${item.order_policy || '-'}</td>
                        <td>${item.order_type || '-'} ${item.quantity == null ? '' : Number(item.quantity).toFixed(8)}</td>
                        <td>${Number(item.predicted_net_bps || 0).toFixed(2)} bps</td>
                        <td>${item.status || 'READY_NOT_TRANSMITTED'}</td>
                        <td>${item.target_ts ? new Date(Number(item.target_ts) * 1000).toLocaleString() : '-'}</td>
                        <td class="trade-buy">NEVER</td>
                    `;
                    tbody.appendChild(row);
                });
            }
        }
        const reasons = document.getElementById('shadow-flight-reasons');
        if (reasons) {
            const failures = Array.isArray(readiness.reasons) ? readiness.reasons : [];
            reasons.textContent = [
                `Approved by: ${freeze.approved_by || 'nobody yet'}`,
                `Settled shadows: ${Number(score.settled || 0)} across ${Number(score.distinct_days || 0)} UTC days`,
                `Mean fill ratio: ${(Number(score.mean_fill_ratio || 0) * 100).toFixed(1)}%`,
                `Mean net: ${score.mean_net_bps == null ? '-' : Number(score.mean_net_bps).toFixed(2)} bps`,
                `Gate: ${failures.length ? failures.join(', ') : 'no current failures'}`,
                'Execution eligibility remains FALSE. Every order payload is retained but never transmitted.'
            ].join('\n');
        }
    } catch (error) {
        console.error('loadShadowFlightData failed:', error);
        setText('shadow-flight-status', 'Error');
    } finally {
        loadingState.shadowFlight = false;
    }
}

async function loadCanaryData() {
    if (loadingState.canary) return;
    loadingState.canary = true;
    try {
        const data = await fetchAPI('/canary.json?limit=100', 30000);
        if (!data) {
            setText('canary-state', 'OFFLINE');
            return;
        }
        const state = data.state || {};
        const score = data.scorecard || {};
        const readiness = data.readiness || {};
        const approvals = Array.isArray(data.approvals) ? data.approvals : [];
        const orders = Array.isArray(data.orders) ? data.orders : [];
        const positions = Array.isArray(data.positions) ? data.positions : [];
        const incidents = Array.isArray(data.incidents) ? data.incidents : [];
        const reconciliations = Array.isArray(data.reconciliations) ? data.reconciliations : [];
        const activeApproval = approvals.find(item => item.status === 'ACTIVE') || approvals[0] || {};
        const latestReconciliation = reconciliations[0] || {};

        setText('canary-state', state.state || 'DISARMED');
        setText('canary-state-reason', state.reason || 'No operator authority');
        setText('canary-live-orders', Number(score.live_orders_submitted || 0));
        setText('canary-round-trips', Number(score.completed_round_trips || 0));
        setText('canary-ready', readiness.ready_for_phase7_review ? 'REVIEW READY' : 'CLOSED');
        setText('canary-readiness', readiness.ready_for_phase7_review ? 'Human Phase 7 review may begin' : 'Evidence gate remains closed');
        setText('canary-approval', activeApproval.approval_id ? `Approval ${String(activeApproval.approval_id).slice(0, 16)}` : 'No active approval');
        setText('canary-cap', `MAX $${Number(data.max_notional_usd || 5).toFixed(2)}`);
        setText('canary-entry-cap', Number(data.max_entry_orders_per_approval || 1));
        setText('canary-open-positions', `OPEN: ${Number(score.open_positions || 0)}`);
        setText('canary-incidents', `OPEN: ${Number(score.open_incidents || incidents.length || 0)}`);
        setText('canary-reconciliation', latestReconciliation.status || 'NO RECONCILIATION');

        const tbody = document.getElementById('canary-orders-tbody');
        if (tbody) {
            tbody.innerHTML = '';
            if (!orders.length) {
                tbody.innerHTML = '<tr><td colspan="8" class="loading-text">No Phase-6 orders.</td></tr>';
            } else {
                orders.slice(0, 100).forEach(item => {
                    const row = document.createElement('tr');
                    const orderId = escapeHTML(String(item.client_order_id || '-'));
                    const symbol = escapeHTML(String(item.symbol || '-'));
                    const side = escapeHTML(String(item.side || '-').toUpperCase());
                    const status = escapeHTML(String(item.status || '-'));
                    row.innerHTML = `
                        <td><strong>${orderId.slice(0, 18)}</strong></td>
                        <td>${symbol}</td>
                        <td class="${side === 'BUY' ? 'trade-buy' : 'trade-sell'}">${side}</td>
                        <td>${status}</td>
                        <td>${Number(item.filled_quantity || 0).toFixed(8)}</td>
                        <td>${item.average_fill_price == null ? '-' : Number(item.average_fill_price).toFixed(4)}</td>
                        <td>${item.reconciled ? 'YES' : 'NO'}</td>
                        <td>${item.updated_ts ? new Date(Number(item.updated_ts) * 1000).toLocaleString() : '-'}</td>
                    `;
                    tbody.appendChild(row);
                });
            }
        }

        const positionLog = document.getElementById('canary-position-log');
        if (positionLog) {
            positionLog.textContent = positions.length ? positions.slice(0, 20).map(item =>
                `${item.symbol || '-'} | ${item.status || '-'} | qty ${Number(item.quantity || 0).toFixed(8)} | ` +
                `entry ${Number(item.entry_price || 0).toFixed(4)} | P&L ${item.realized_pnl_quote == null ? '-' : Number(item.realized_pnl_quote).toFixed(4)}`
            ).join('\n') : 'No canary positions.';
        }
        const incidentLog = document.getElementById('canary-incident-log');
        if (incidentLog) {
            incidentLog.textContent = incidents.length ? incidents.slice(0, 20).map(item =>
                `${String(item.severity || 'UNKNOWN').toUpperCase()} | ${item.category || '-'} | ${item.message || '-'}`
            ).join('\n') : 'No unresolved incidents.';
        }
        const reasons = document.getElementById('canary-reasons');
        if (reasons) {
            const failures = Array.isArray(readiness.reasons) ? readiness.reasons : [];
            reasons.textContent = [
                `State: ${state.state || 'DISARMED'} (${state.reason || 'no reason recorded'})`,
                `Latest reconciliation: ${latestReconciliation.status || 'none'}; unknown orders ${Number(score.unknown_orders || 0)}`,
                `Closed round trips: ${Number(score.completed_round_trips || 0)}; realised total ${Number(score.total_realized_pnl_quote || 0).toFixed(4)} quote`,
                `Phase 7 gate: ${failures.length ? failures.join(', ') : 'review criteria currently satisfied'}`,
                'Desktop authority: READ ONLY. Arming, submission, scaling and recovery are absent.',
                'Environment interlock and credentials are intentionally never exposed here.'
            ].join('\n');
        }
    } catch (error) {
        console.error('loadCanaryData failed:', error);
        setText('canary-state', 'ERROR');
        setText('canary-state-reason', error && error.message ? error.message : 'Canary view failed to render');
    } finally {
        loadingState.canary = false;
    }
}


async function loadGrowthData() {
    if (loadingState.growth) return;
    loadingState.growth = true;
    try {
        const data = await fetchAPI('/growth.json?limit=50', 30000);
        if (!data) {
            setText('growth-state', 'OFFLINE');
            return;
        }
        const state = data.state || {};
        const stage = data.current_stage || {};
        const readiness = data.readiness || {};
        const evidence = readiness.evidence || {};
        const proposals = Array.isArray(data.proposals) ? data.proposals : [];
        const incidents = Array.isArray(data.incidents) ? data.incidents : [];
        const stages = Array.isArray(data.stages) ? data.stages : [];
        setText('growth-state', state.state || 'LOCKED');
        setText('growth-state-reason', state.reason || 'No stage activated');
        setText('growth-stage', stage.name || 'CANARY');
        setText('growth-envelope', `$${Number(stage.max_notional_usd || 5).toFixed(2)} · ${(stage.allowed_symbols || []).length || 1} symbol(s)`);
        setText('growth-round-trips', Number(evidence.new_round_trips || 0));
        setText('growth-days', `${Number(evidence.distinct_days || 0)} live days`);
        setText('growth-ready', readiness.ready_for_next_stage_proposal ? 'REVIEW READY' : 'CLOSED');
        setText('growth-next-stage', readiness.target_stage ? `NEXT: ${readiness.target_stage.name}` : 'MAX STAGE');
        setText('growth-pnl', `P&L: ${Number(evidence.total_realized_pnl_quote || 0).toFixed(4)}`);
        setText('growth-incidents', `OPEN: ${incidents.length}`);
        setText('growth-authority', data.execution_scale_authorized ? 'STAGE ACTIVE' : 'LOCKED');

        const tbody = document.getElementById('growth-stages-tbody');
        if (tbody) {
            tbody.innerHTML = '';
            stages.forEach(item => {
                const row = document.createElement('tr');
                const status = Number(item.stage_id) === Number(stage.stage_id) ? 'CURRENT' : (Number(item.stage_id) < Number(stage.stage_id) ? 'COMPLETED' : 'LOCKED');
                row.innerHTML = `<td><strong>${escapeHTML(String(item.name || '-'))}</strong></td>` +
                    `<td>$${Number(item.max_notional_usd || 0).toFixed(2)}</td>` +
                    `<td>${escapeHTML((item.allowed_symbols || []).join(', '))}</td>` +
                    `<td>${Number(item.min_new_round_trips || 0)} trades / ${Number(item.min_distinct_days || 0)} days</td>` +
                    `<td>${status}</td>`;
                tbody.appendChild(row);
            });
        }
        const evidenceLog = document.getElementById('growth-evidence-log');
        if (evidenceLog) {
            evidenceLog.textContent = [
                `Profit factor: ${Number(evidence.profit_factor || 0).toFixed(3)}`,
                `Mean return: ${Number(evidence.mean_return_bps || 0).toFixed(2)} bps`,
                `Maximum drawdown: ${Number(evidence.max_drawdown_bps || 0).toFixed(2)} bps`,
                `Loss rate: ${(Number(evidence.loss_rate || 0) * 100).toFixed(1)}%`,
                `Rejection rate: ${(Number(evidence.rejection_rate || 0) * 100).toFixed(1)}%`,
                `Mean absolute slippage: ${Number(evidence.mean_abs_slippage_bps || 0).toFixed(2)} bps`
            ].join('\n');
        }
        const proposalLog = document.getElementById('growth-proposal-log');
        if (proposalLog) {
            const proposalLines = proposals.slice(0, 10).map(item =>
                `${item.status || '-'} | stage ${item.from_stage} → ${item.to_stage} | ${item.proposed_by || '-'} | ${item.proposal_id ? String(item.proposal_id).slice(0, 14) : '-'}`
            );
            const incidentLines = incidents.slice(0, 10).map(item =>
                `${String(item.severity || 'UNKNOWN').toUpperCase()} | ${item.category || '-'} | ${item.message || '-'}`
            );
            proposalLog.textContent = [...proposalLines, ...incidentLines].join('\n') || 'No growth proposals or incidents.';
        }
        const reasons = document.getElementById('growth-reasons');
        if (reasons) {
            const failures = Array.isArray(readiness.reasons) ? readiness.reasons : [];
            reasons.textContent = [
                `Current stage: ${stage.name || 'CANARY'}; notional cap $${Number(stage.max_notional_usd || 5).toFixed(2)}`,
                `Next-stage gate: ${failures.length ? failures.join(', ') : 'evidence criteria currently satisfied'}`,
                'Promotion path: proposal → cooling-off → human approval → separate environment interlock → activation.',
                'Demotion path: automatic on ambiguity, incidents, drawdown, rejection or slippage breach.',
                'Desktop authority: READ ONLY. Proposal, approval, activation, execution and recovery are absent.'
            ].join('\n');
        }
    } catch (error) {
        console.error('loadGrowthData failed:', error);
        setText('growth-state', 'ERROR');
        setText('growth-state-reason', error && error.message ? error.message : 'Growth view failed to render');
    } finally {
        loadingState.growth = false;
    }
}

async function loadTradesData() {
    if (loadingState.trades) return;
    loadingState.trades = true;
    try {
    const data = await fetchAPI('/api/trades');
    if (!data || !data.trades) return;

    const tbody = document.getElementById('trades-tbody');
    if (!tbody) return;
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
    } catch (error) {
        console.error('loadTradesData failed:', error);
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
        if (!pnlElement) return;
        pnlElement.textContent = `$${data.total_pnl.toFixed(2)}`;
        pnlElement.style.color = data.total_pnl >= 0 ? 'var(--success)' : 'var(--error)';
    }

    if (data.win_rate !== undefined) {
        const element = document.getElementById('win-rate');
        if (element) element.textContent = `${(data.win_rate * 100).toFixed(1)}%`;
    }

    if (data.total_trades !== undefined) {
        const element = document.getElementById('total-trades');
        if (element) element.textContent = data.total_trades;
    }

    if (data.sharpe_ratio !== undefined) {
        const element = document.getElementById('sharpe-ratio');
        if (element) element.textContent = data.sharpe_ratio.toFixed(2);
    }
    } catch (error) {
        console.error('loadPerformanceData failed:', error);
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
    if (!container) return;
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
    } catch (error) {
        console.error('loadLogsData failed:', error);
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
