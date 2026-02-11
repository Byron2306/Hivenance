import React, { useEffect, useState, useRef } from 'react';

const API_URL = process.env.REACT_APP_BACKEND_URL || '';

function App() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const iframeRef = useRef(null);

  useEffect(() => {
    // Check if backend is available
    const checkBackend = async () => {
      try {
        const res = await fetch(`${API_URL}/api/status.json`);
        if (res.ok) {
          setLoading(false);
        } else {
          setError('Backend not responding');
          setLoading(false);
        }
      } catch (e) {
        // Still try to load - the Flask UI might work
        setLoading(false);
      }
    };
    checkBackend();
  }, []);

  // Redirect to the Flask dashboard
  useEffect(() => {
    if (!loading && !error) {
      window.location.href = `${API_URL}/api/`;
    }
  }, [loading, error]);

  if (loading) {
    return (
      <div style={styles.loading}>
        <div style={styles.spinner}></div>
        <p style={styles.text}>Loading Hivenance Dashboard...</p>
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  if (error) {
    return (
      <div style={styles.loading}>
        <p style={styles.errorText}>⚠️ {error}</p>
        <button 
          onClick={() => window.location.reload()} 
          style={styles.btn}
        >
          Retry
        </button>
        <p style={styles.text}>
          Or try: <a href={`${API_URL}/api/`} style={styles.link}>Open Dashboard Directly</a>
        </p>
      </div>
    );
  }

  return (
    <div style={styles.loading}>
      <div style={styles.spinner}></div>
      <p style={styles.text}>Redirecting to Dashboard...</p>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

const styles = {
  loading: {
    minHeight: '100vh',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    background: '#071026',
    color: '#ffd24a',
    fontFamily: "'Segoe UI', 'Inter', sans-serif",
  },
  spinner: {
    width: '50px',
    height: '50px',
    border: '4px solid rgba(255, 210, 74, 0.2)',
    borderTopColor: '#ffd24a',
    borderRadius: '50%',
    animation: 'spin 1s linear infinite',
    marginBottom: '20px',
  },
  text: {
    fontSize: '1rem',
    color: '#d9c786',
  },
  errorText: {
    fontSize: '1.2rem',
    color: '#ff6b6b',
    marginBottom: '20px',
  },
  btn: {
    padding: '12px 30px',
    background: '#ffd24a',
    color: '#071026',
    border: 'none',
    borderRadius: '8px',
    fontSize: '1rem',
    fontWeight: 'bold',
    cursor: 'pointer',
    marginBottom: '20px',
  },
  link: {
    color: '#ffd24a',
    textDecoration: 'underline',
  },
};

export default App;
