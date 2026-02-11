import React from 'react';

// Embed the original Flask dashboard in a full-screen iframe
function App() {
  // The backend Flask UI is accessible via the /api path
  const backendUrl = process.env.REACT_APP_BACKEND_URL || '';
  const dashboardUrl = `${backendUrl}/api/`;

  return (
    <iframe
      src={dashboardUrl}
      title="Crypto Swarm Dashboard"
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100%',
        height: '100%',
        border: 'none',
        margin: 0,
        padding: 0,
        overflow: 'hidden',
      }}
    />
  );
}

export default App;
