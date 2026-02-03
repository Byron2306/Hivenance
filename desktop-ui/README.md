# Hivenance Desktop UI

A standalone desktop application for the Hivenance Trading Agent system, built with Electron.

## Features

- **Real-time Dashboard**: Monitor wallet balance, active trades, and system status
- **Agent Management**: View status and performance of all trading agents
- **Trade History**: Browse and analyze recent trading activity
- **Performance Metrics**: Track P&L, win rate, and other key metrics
- **System Logs**: Real-time log monitoring with filtering
- **Cross-platform**: Works on Windows, macOS, and Linux

## Prerequisites

- Node.js (v18 or higher)
- npm or yarn
- Running Hivenance backend (Flask server on port 5000)

## Installation

1. Navigate to the desktop-ui directory:
   ```bash
   cd desktop-ui
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

## Running the Application

### Development Mode

Start the application in development mode:

```bash
npm start
```

### Building for Production

Build the application for your platform:

```bash
# For Windows
npm run build:win

# For macOS
npm run build:mac

# For Linux
npm run build:linux

# For all platforms
npm run build
```

The built application will be in the `dist/` directory.

## Configuration

### Backend Connection

The default backend URL is `http://127.0.0.1:5000`. You can change this in the Settings view within the application.

To change the default:
1. Open the application
2. Navigate to Settings
3. Update the Backend URL
4. Click "Save"
5. Test the connection

### Auto-refresh

Enable auto-refresh in Settings to automatically update dashboard data every 5 seconds.

## Project Structure

```
desktop-ui/
├── main.js           # Electron main process
├── preload.js        # Preload script for secure IPC
├── package.json      # Dependencies and build config
├── renderer/         # Frontend files
│   ├── index.html    # Main HTML
│   ├── styles.css    # Styling
│   └── app.js        # Application logic
└── assets/           # Icons and images
    └── icon.png      # Application icon
```

## API Endpoints

The desktop app expects the following API endpoints from the backend:

- `GET /api/status` - System status and configuration
- `GET /api/trades` - Recent trade history
- `GET /api/performance` - Performance metrics
- `GET /api/logs` - System logs

## Security

- Context isolation is enabled
- Node integration is disabled in renderer
- All backend communication goes through the preload script
- Content Security Policy enforced

## Troubleshooting

### Connection Issues

If you can't connect to the backend:
1. Ensure the Flask server is running (`python run_ui_server.py`)
2. Check the backend URL in Settings
3. Verify firewall settings aren't blocking the connection
4. Test connection using the "Test Connection" button

### Build Issues

If build fails:
```bash
# Clear cache and reinstall
rm -rf node_modules
npm install
```

### Performance

For better performance:
- Disable auto-refresh when not actively monitoring
- Clear logs periodically
- Close unused views

## Development

### Adding New Features

1. Update the UI in `renderer/index.html`
2. Add styling in `renderer/styles.css`
3. Implement logic in `renderer/app.js`
4. Add IPC handlers in `main.js` if needed

### Debugging

Open DevTools in the app:
- macOS: `Cmd + Option + I`
- Windows/Linux: `Ctrl + Shift + I`

Or uncomment this line in `main.js`:
```javascript
mainWindow.webContents.openDevTools();
```

## License

MIT
