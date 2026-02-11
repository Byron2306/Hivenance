import React, { useEffect } from 'react';

// This React app immediately redirects to the original Flask dashboard
function App() {
  useEffect(() => {
    // Get the backend URL and redirect to the Flask dashboard
    const backendUrl = process.env.REACT_APP_BACKEND_URL || window.location.origin;
    
    // For external access, the Flask UI is mounted at the backend root
    // We need to access it via /api/ path since that's how the platform routes to backend
    window.location.replace(backendUrl);
  }, []);

  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      background: '#071026',
      color: '#ffd24a',
      fontFamily: "'Segoe UI', sans-serif",
    }}>
      <div style={{
        width: '50px',
        height: '50px',
        border: '4px solid rgba(255, 210, 74, 0.2)',
        borderTopColor: '#ffd24a',
        borderRadius: '50%',
        animation: 'spin 1s linear infinite',
        marginBottom: '20px',
      }} />
      <p>Loading Crypto Swarm Dashboard...</p>
      <p style={{ fontSize: '0.8rem', color: '#888' }}>
        <a href="/" style={{ color: '#ffd24a' }}>Click here if not redirected</a>
      </p>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

export default App;
