# Quick Start Guide for Desktop UI

## Installation

1. Open a terminal in the `desktop-ui` folder
2. Install dependencies:
   ```bash
   npm install
   ```

## Running

1. **Start your Flask backend first:**
   ```bash
   cd ..
   python run_ui_server.py
   ```

2. **In a new terminal, start the desktop app:**
   ```bash
   cd desktop-ui
   npm start
   ```

The desktop application will launch and connect to your backend at `http://127.0.0.1:5001`.

## First Time Setup

1. The app should connect automatically if your backend is running
2. Check the connection status indicator (green dot = connected)
3. If not connected, go to Settings and verify the backend URL
4. Click "Test Connection" to verify

## Tips

- Enable "Auto-refresh" in Settings for real-time updates
- Use the navigation sidebar to switch between views
- Press F12 to open DevTools for debugging
- The app remembers your settings between sessions

Enjoy your Hivenance Desktop UI!

## Phase 2 research-only runner

From the repository root, run:

```bash
python scripts/run_phase2_hypotheses.py --once
```

Then open **Hypotheses** in the desktop console. All Phase-2 forecasts remain non-executable.
