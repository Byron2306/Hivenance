import React, { useEffect, useState } from 'react';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

function App() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await fetch(`${API_URL}/api/status`);
        if (res.ok) {
          const data = await res.json();
          setStatus(data);
        }
      } catch (e) {
        console.error('Status fetch error:', e);
      }
      setLoading(false);
    };
    
    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div style={styles.container}>
        <div style={styles.spinner}></div>
        <p>Loading Hivenance...</p>
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <iframe 
        src={`${API_URL}/api/`}
        style={styles.iframe}
        title="Hivenance Dashboard"
        frameBorder="0"
      />
    </div>
  );
}

const styles = {
  container: {
    width: '100vw',
    height: '100vh',
    margin: 0,
    padding: 0,
    overflow: 'hidden',
    background: '#071026',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    color: '#ffd24a',
    fontFamily: "'Segoe UI', sans-serif",
  },
  iframe: {
    width: '100%',
    height: '100%',
    border: 'none',
  },
  spinner: {
    width: '50px',
    height: '50px',
    border: '4px solid rgba(255, 210, 74, 0.2)',
    borderTopColor: '#ffd24a',
    borderRadius: '50%',
    animation: 'spin 1s linear infinite',
  },
};

export default App;
