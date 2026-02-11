import React, { useEffect, useState } from 'react';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || '';

function App() {
  const [loading, setLoading] = useState(true);
  const [healthStatus, setHealthStatus] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    // Check backend health and redirect to trading dashboard
    const checkHealth = async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/api/status.json`);
        if (response.ok) {
          const data = await response.json();
          setHealthStatus(data);
          setLoading(false);
        } else {
          setError('Backend not responding');
          setLoading(false);
        }
      } catch (err) {
        setError(`Connection error: ${err.message}`);
        setLoading(false);
      }
    };
    
    checkHealth();
    
    // Refresh status every 5 seconds
    const interval = setInterval(checkHealth, 5000);
    return () => clearInterval(interval);
  }, []);

  const openDashboard = () => {
    window.location.href = `${BACKEND_URL}/api/`;
  };

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      color: '#fff',
      padding: '20px',
    }}>
      <div style={{
        background: 'rgba(255, 255, 255, 0.05)',
        borderRadius: '20px',
        padding: '40px',
        maxWidth: '600px',
        textAlign: 'center',
        boxShadow: '0 8px 32px rgba(0, 0, 0, 0.3)',
        backdropFilter: 'blur(10px)',
      }}>
        <h1 style={{
          fontSize: '2.5rem',
          marginBottom: '10px',
          background: 'linear-gradient(90deg, #f7b731, #ffc107)',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor: 'transparent',
        }}>
          🐝 HIVENANCE
        </h1>
        <p style={{
          fontSize: '1.1rem',
          color: '#a0a0a0',
          marginBottom: '30px',
        }}>
          Multi-Agent Crypto Trading Platform
        </p>
        
        {loading ? (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '15px',
          }}>
            <div style={{
              width: '40px',
              height: '40px',
              border: '3px solid rgba(247, 183, 49, 0.3)',
              borderTopColor: '#f7b731',
              borderRadius: '50%',
              animation: 'spin 1s linear infinite',
            }} />
            <p>Connecting to trading system...</p>
            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
          </div>
        ) : error ? (
          <div style={{ color: '#ff6b6b' }}>
            <p style={{ marginBottom: '20px' }}>⚠️ {error}</p>
            <button
              onClick={() => window.location.reload()}
              style={{
                background: '#ff6b6b',
                color: '#fff',
                border: 'none',
                padding: '12px 30px',
                borderRadius: '25px',
                cursor: 'pointer',
                fontSize: '1rem',
              }}
            >
              Retry Connection
            </button>
          </div>
        ) : (
          <div>
            <div style={{
              display: 'flex',
              justifyContent: 'center',
              gap: '20px',
              marginBottom: '30px',
              flexWrap: 'wrap',
            }}>
              <div style={{
                background: 'rgba(40, 167, 69, 0.2)',
                padding: '10px 20px',
                borderRadius: '10px',
              }}>
                <span style={{ color: '#28a745' }}>●</span> System Online
              </div>
              <div style={{
                background: healthStatus?.dry_run ? 'rgba(255, 193, 7, 0.2)' : 'rgba(40, 167, 69, 0.2)',
                padding: '10px 20px',
                borderRadius: '10px',
              }}>
                {healthStatus?.dry_run ? '🧪 Dry Run Mode' : '🔥 Live Mode'}
              </div>
            </div>
            
            <button
              onClick={openDashboard}
              data-testid="open-dashboard-btn"
              style={{
                background: 'linear-gradient(90deg, #f7b731, #ffc107)',
                color: '#1a1a2e',
                border: 'none',
                padding: '15px 40px',
                borderRadius: '30px',
                fontSize: '1.1rem',
                fontWeight: 'bold',
                cursor: 'pointer',
                transition: 'transform 0.2s, box-shadow 0.2s',
                boxShadow: '0 4px 15px rgba(247, 183, 49, 0.3)',
              }}
              onMouseOver={(e) => {
                e.target.style.transform = 'scale(1.05)';
                e.target.style.boxShadow = '0 6px 20px rgba(247, 183, 49, 0.4)';
              }}
              onMouseOut={(e) => {
                e.target.style.transform = 'scale(1)';
                e.target.style.boxShadow = '0 4px 15px rgba(247, 183, 49, 0.3)';
              }}
            >
              Open Trading Dashboard →
            </button>
          </div>
        )}
        
        <div style={{
          marginTop: '40px',
          paddingTop: '20px',
          borderTop: '1px solid rgba(255, 255, 255, 0.1)',
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: '15px',
          fontSize: '0.85rem',
          color: '#666',
        }}>
          <div>
            <div style={{ color: '#f7b731', marginBottom: '5px' }}>Governance</div>
            <div>Queen Agent</div>
          </div>
          <div>
            <div style={{ color: '#28a745', marginBottom: '5px' }}>Safety</div>
            <div>Multi-Layer</div>
          </div>
          <div>
            <div style={{ color: '#17a2b8', marginBottom: '5px' }}>Gas</div>
            <div>Optimized</div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
