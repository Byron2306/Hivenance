import React, { useEffect, useState, useRef, useCallback } from 'react';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';
const WS_URL = API_URL.replace('https://', 'wss://').replace('http://', 'ws://') + '/ws';

// Stat component for displaying key metrics
const Stat = ({ label, value, color = 'white' }) => (
  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
    <span style={{ color: '#888' }}>{label}</span>
    <span style={{ color: color === 'green' ? '#22c55e' : color === 'red' ? '#ef4444' : '#fff', fontWeight: 'bold' }}>{value}</span>
  </div>
);

function App() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [wsConnected, setWsConnected] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [trades, setTrades] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);

  // WebSocket connection
  const connectWebSocket = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      const ws = new WebSocket(WS_URL);
      
      ws.onopen = () => {
        console.log('WebSocket connected');
        setWsConnected(true);
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          setLastUpdate(new Date());

          switch (msg.type) {
            case 'init':
            case 'update':
              setData(prev => ({ ...prev, ...msg.data }));
              setLoading(false);
              break;
            case 'trade':
              setTrades(prev => [msg.data, ...prev.slice(0, 9)]);
              break;
            case 'alert':
              setAlerts(prev => [msg.data, ...prev.slice(0, 4)]);
              setTimeout(() => setAlerts(prev => prev.slice(0, -1)), 5000);
              break;
            case 'mode_change':
            case 'auto_trade_change':
              setData(prev => ({ ...prev, ...msg.data }));
              break;
            default:
              break;
          }
        } catch (e) {
          console.error('WebSocket message error:', e);
        }
      };

      ws.onclose = () => {
        console.log('WebSocket disconnected');
        setWsConnected(false);
        // Reconnect after 3 seconds
        reconnectTimeoutRef.current = setTimeout(connectWebSocket, 3000);
      };

      ws.onerror = (error) => {
        console.error('WebSocket error:', error);
      };

      wsRef.current = ws;
    } catch (e) {
      console.error('WebSocket connection error:', e);
      reconnectTimeoutRef.current = setTimeout(connectWebSocket, 3000);
    }
  }, []);

  // Initial data fetch and WebSocket setup
  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await fetch(`${API_URL}/api/status`);
        const json = await res.json();
        setData(json);
        setLoading(false);
      } catch (e) {
        console.error('Fetch error:', e);
        setLoading(false);
      }
    };

    fetchData();
    connectWebSocket();

    return () => {
      if (wsRef.current) wsRef.current.close();
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
    };
  }, [connectWebSocket]);

  // Send WebSocket command
  const sendWsCommand = (action, payload = {}) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action, ...payload }));
    }
  };

  // Mode switching via WebSocket
  const setMode = async (mode) => {
    sendWsCommand('set_mode', { mode });
    // Also update via REST as fallback
    await fetch(`${API_URL}/api/mode`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode })
    });
  };

  // Toggle auto-trade
  const toggleAutoTrade = async () => {
    sendWsCommand('toggle_auto_trade');
    await fetch(`${API_URL}/api/auto_trade`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: !data?.auto_trade })
    });
  };

  // Reset circuit breaker
  const resetCircuitBreaker = async () => {
    await fetch(`${API_URL}/api/safety/reset`, { method: 'POST' });
  };

  if (loading) {
    return (
      <div style={styles.loading}>
        <div style={styles.spinner}></div>
        <p>Connecting to Hivenance...</p>
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  const safety = data?.safety || {};
  const learning = data?.learning || {};
  const workers = data?.worker_weights || {};
  const topCoins = learning.top_coins || [];
  const winRate = (learning.win_rate || 0) * 100;
  const prices = data?.prices || {};

  return (
    <div style={styles.container}>
      {/* Header */}
      <h1 style={styles.title}>
        🐝 Hive Trading System
        <span style={{
          ...styles.badge,
          backgroundColor: data?.mode === 'SIMPLE' ? '#22c55e20' : '#f59e0b20',
          color: data?.mode === 'SIMPLE' ? '#22c55e' : '#f59e0b',
          borderColor: data?.mode === 'SIMPLE' ? '#22c55e' : '#f59e0b'
        }}>
          {data?.mode} MODE
        </span>
        <span style={{
          ...styles.wsBadge,
          backgroundColor: wsConnected ? '#22c55e20' : '#ef444420',
          color: wsConnected ? '#22c55e' : '#ef4444',
        }}>
          {wsConnected ? '● LIVE' : '○ OFFLINE'}
        </span>
      </h1>

      {/* Alerts */}
      {alerts.length > 0 && (
        <div style={styles.alertContainer}>
          {alerts.map((alert, i) => (
            <div key={i} style={{
              ...styles.alert,
              borderLeftColor: alert.level === 'ERROR' ? '#ef4444' : alert.level === 'WARNING' ? '#f59e0b' : '#22c55e'
            }}>
              <strong>{alert.level}:</strong> {alert.message}
            </div>
          ))}
        </div>
      )}

      {/* Mode Toggle */}
      <div style={styles.modeToggle}>
        <button
          style={{ ...styles.modeBtn, ...(data?.mode === 'SIMPLE' ? styles.modeBtnActive : {}) }}
          onClick={() => setMode('SIMPLE')}
          data-testid="simple-mode-btn"
        >
          ⚡ SIMPLE MODE<br /><small style={{ color: '#888' }}>Fast & Efficient</small>
        </button>
        <button
          style={{ ...styles.modeBtn, ...(data?.mode === 'GOVERNED' ? styles.modeBtnActive : {}) }}
          onClick={() => setMode('GOVERNED')}
          data-testid="governed-mode-btn"
        >
          🏛️ GOVERNED MODE<br /><small style={{ color: '#888' }}>Safe & Validated</small>
        </button>
      </div>

      {/* Live Prices */}
      {Object.keys(prices).length > 0 && (
        <div style={styles.priceBar}>
          {Object.entries(prices).map(([symbol, price]) => (
            <div key={symbol} style={styles.priceItem}>
              <span style={{ color: '#888' }}>{symbol}</span>
              <span style={{ color: '#22c55e', fontWeight: 'bold' }}>${price.toLocaleString()}</span>
            </div>
          ))}
          {lastUpdate && (
            <div style={styles.priceItem}>
              <span style={{ color: '#666', fontSize: '0.8rem' }}>Last update: {lastUpdate.toLocaleTimeString()}</span>
            </div>
          )}
        </div>
      )}

      {/* Main Grid */}
      <div style={styles.grid}>
        {/* Safety Status */}
        <div style={styles.card}>
          <h2 style={styles.cardTitle}>🛡️ Safety Status</h2>
          <Stat label="System Status" value={safety.level || 'UNKNOWN'} color={safety.circuit_breaker ? 'red' : 'green'} />
          <Stat label="Circuit Breaker" value={safety.circuit_breaker ? '🔴 ACTIVE' : '🟢 OK'} color={safety.circuit_breaker ? 'red' : 'green'} />
          <Stat label="Consecutive Losses" value={`${safety.consecutive_losses || 0} / 5`} />
          <Stat label="Daily P&L" value={`$${(safety.daily_pnl || 0).toFixed(4)}`} color={safety.daily_pnl >= 0 ? 'green' : 'red'} />
          {safety.circuit_breaker && (
            <button style={styles.resetBtn} onClick={resetCircuitBreaker} data-testid="reset-circuit-btn">
              Reset Circuit Breaker
            </button>
          )}
        </div>

        {/* Learning Engine */}
        <div style={styles.card}>
          <h2 style={styles.cardTitle}>🧠 Learning Engine</h2>
          <Stat label="Auto-Trade" value={data?.auto_trade ? 'ENABLED' : 'MANUAL'} color={data?.auto_trade ? 'green' : 'white'} />
          <Stat label="Total Trades" value={learning.total_trades || 0} />
          <Stat label="Win Rate" value={`${winRate.toFixed(1)}%`} color={winRate >= 50 ? 'green' : 'red'} />
          <Stat label="Coins Tracked" value={topCoins.length} />
        </div>

        {/* Gas Optimizer */}
        <div style={styles.card}>
          <h2 style={styles.cardTitle}>⛽ Gas Optimizer</h2>
          <Stat label="Network" value="BASE L2" color="green" />
          <Stat label="Cost per Trade" value="$0.001" color="green" />
          <Stat label="vs Mainnet" value="99.97% cheaper" color="green" />
        </div>

        {/* Worker Performance */}
        <div style={styles.card}>
          <h2 style={styles.cardTitle}>📊 Worker Performance</h2>
          {Object.entries(workers).map(([name, weight]) => (
            <Stat key={name} label={name} value={`${weight.toFixed(2)}x`} color={weight > 1 ? 'green' : weight < 1 ? 'red' : 'white'} />
          ))}
        </div>
      </div>

      {/* Top Performing Coins */}
      <div style={styles.section}>
        <h2 style={styles.sectionTitle}>🏆 Top Performing Coins</h2>
        <div style={styles.coinGrid}>
          {topCoins.length > 0 ? topCoins.map((coin, i) => (
            <div key={i} style={styles.coinBadge}>
              {coin.symbol} <span style={{ color: coin.score > 0 ? '#22c55e' : '#888' }}>{(coin.score * 100).toFixed(0)}%</span>
            </div>
          )) : <span style={{ color: '#666' }}>No coins tracked yet</span>}
        </div>
      </div>

      {/* Recent Trades */}
      {trades.length > 0 && (
        <div style={styles.section}>
          <h2 style={styles.sectionTitle}>📈 Recent Trades (Live)</h2>
          <div style={styles.tradeList}>
            {trades.map((trade, i) => (
              <div key={i} style={styles.tradeItem}>
                <span style={{ color: trade.side === 'BUY' ? '#22c55e' : '#ef4444' }}>{trade.side}</span>
                <span>{trade.symbol}</span>
                <span>${trade.price}</span>
                <span style={{ color: trade.pnl >= 0 ? '#22c55e' : '#ef4444' }}>
                  {trade.pnl >= 0 ? '+' : ''}{trade.pnl?.toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Controls */}
      <div style={styles.section}>
        <h2 style={styles.sectionTitle}>⚙️ Controls</h2>
        <div style={styles.controls}>
          <button
            style={{ ...styles.btn, ...(data?.auto_trade ? styles.btnActive : {}) }}
            onClick={toggleAutoTrade}
            data-testid="auto-trade-btn"
          >
            {data?.auto_trade ? '🔴 Disable' : '🟢 Enable'} Auto-Trade
          </button>
          <button
            style={styles.btn}
            onClick={() => window.location.reload()}
            data-testid="refresh-btn"
          >
            🔄 Refresh
          </button>
        </div>
      </div>
    </div>
  );
}

const styles = {
  container: {
    minHeight: '100vh',
    background: 'linear-gradient(135deg, #0f172a 0%, #1e293b 100%)',
    color: '#fff',
    padding: '20px',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
  },
  loading: {
    minHeight: '100vh',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    background: '#0f172a',
    color: '#fff',
  },
  spinner: {
    width: '40px',
    height: '40px',
    border: '3px solid rgba(247, 183, 49, 0.3)',
    borderTopColor: '#f7b731',
    borderRadius: '50%',
    animation: 'spin 1s linear infinite',
    marginBottom: '20px',
  },
  title: {
    fontSize: '1.8rem',
    marginBottom: '20px',
    display: 'flex',
    alignItems: 'center',
    gap: '15px',
    flexWrap: 'wrap',
  },
  badge: {
    fontSize: '0.8rem',
    padding: '6px 12px',
    borderRadius: '20px',
    border: '1px solid',
  },
  wsBadge: {
    fontSize: '0.7rem',
    padding: '4px 10px',
    borderRadius: '15px',
  },
  alertContainer: {
    marginBottom: '20px',
  },
  alert: {
    background: 'rgba(255,255,255,0.05)',
    padding: '10px 15px',
    borderRadius: '8px',
    marginBottom: '8px',
    borderLeft: '3px solid',
  },
  modeToggle: {
    display: 'flex',
    gap: '10px',
    marginBottom: '20px',
  },
  modeBtn: {
    flex: 1,
    padding: '15px',
    background: 'rgba(255,255,255,0.05)',
    border: '2px solid transparent',
    borderRadius: '12px',
    color: '#fff',
    cursor: 'pointer',
    transition: 'all 0.3s',
    fontSize: '1rem',
  },
  modeBtnActive: {
    borderColor: '#22c55e',
    background: 'rgba(34, 197, 94, 0.1)',
  },
  priceBar: {
    display: 'flex',
    gap: '20px',
    padding: '15px',
    background: 'rgba(255,255,255,0.03)',
    borderRadius: '10px',
    marginBottom: '20px',
    flexWrap: 'wrap',
  },
  priceItem: {
    display: 'flex',
    gap: '10px',
    alignItems: 'center',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
    gap: '20px',
    marginBottom: '20px',
  },
  card: {
    background: 'rgba(255,255,255,0.05)',
    borderRadius: '15px',
    padding: '20px',
  },
  cardTitle: {
    fontSize: '0.9rem',
    color: '#94a3b8',
    marginBottom: '15px',
    textTransform: 'uppercase',
    letterSpacing: '1px',
  },
  resetBtn: {
    marginTop: '10px',
    padding: '8px 16px',
    background: '#ef4444',
    border: 'none',
    borderRadius: '8px',
    color: '#fff',
    cursor: 'pointer',
    width: '100%',
  },
  section: {
    marginBottom: '20px',
  },
  sectionTitle: {
    fontSize: '1rem',
    color: '#94a3b8',
    marginBottom: '15px',
    textTransform: 'uppercase',
    letterSpacing: '1px',
  },
  coinGrid: {
    display: 'flex',
    gap: '10px',
    flexWrap: 'wrap',
  },
  coinBadge: {
    background: 'rgba(255,255,255,0.1)',
    padding: '8px 16px',
    borderRadius: '20px',
    fontSize: '0.9rem',
  },
  tradeList: {
    background: 'rgba(255,255,255,0.03)',
    borderRadius: '10px',
    overflow: 'hidden',
  },
  tradeItem: {
    display: 'grid',
    gridTemplateColumns: '60px 1fr 100px 80px',
    gap: '10px',
    padding: '12px 15px',
    borderBottom: '1px solid rgba(255,255,255,0.05)',
    fontSize: '0.9rem',
  },
  controls: {
    display: 'flex',
    gap: '10px',
    flexWrap: 'wrap',
  },
  btn: {
    padding: '12px 24px',
    background: 'rgba(255,255,255,0.1)',
    border: 'none',
    borderRadius: '25px',
    color: '#fff',
    cursor: 'pointer',
    fontSize: '1rem',
    transition: 'all 0.3s',
  },
  btnActive: {
    background: '#22c55e',
  },
};

export default App;
