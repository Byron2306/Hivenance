import React, { useEffect } from 'react';

// Redirect to the original Flask dashboard
function App() {
  useEffect(() => {
    // Redirect to Flask dashboard
    window.location.replace('/api/');
  }, []);

  return (
    <div style={styles.container}>
      <div style={styles.spinner}></div>
      <p style={styles.text}>Redirecting to Dashboard...</p>
      <p style={styles.link}>
        <a href="/api/" style={{color: '#ffd24a'}}>Click here if not redirected</a>
      </p>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

const styles = {
  container: {
    width: '100vw',
    height: '100vh',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    background: '#071026',
    color: '#ffd24a',
    fontFamily: "'Segoe UI', sans-serif",
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
    marginBottom: '10px',
  },
  link: {
    fontSize: '0.9rem',
  },
};

export default App;
