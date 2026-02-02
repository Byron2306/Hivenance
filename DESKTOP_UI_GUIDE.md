# Hivenance Desktop UI Setup

A separate desktop application has been created in the `desktop-ui/` folder.

## Quick Start

### Windows
```bash
cd desktop-ui
start.bat
```

### macOS/Linux
```bash
cd desktop-ui
chmod +x start.sh
./start.sh
```

## Manual Setup

1. **Navigate to desktop-ui folder:**
   ```bash
   cd desktop-ui
   ```

2. **Install dependencies:**
   ```bash
   npm install
   ```

3. **Start the backend (in a separate terminal):**
   ```bash
   python run_ui_server.py
   ```

4. **Launch the desktop app:**
   ```bash
   npm start
   ```

## Features

- ✅ Native desktop application (Windows, macOS, Linux)
- ✅ Real-time dashboard with system metrics
- ✅ Agent status monitoring
- ✅ Trade history viewer
- ✅ Performance analytics
- ✅ Live log streaming
- ✅ Auto-refresh capability
- ✅ Configurable backend connection

## Building for Distribution

To create a standalone executable:

```bash
cd desktop-ui

# For Windows
npm run build:win

# For macOS
npm run build:mac

# For Linux
npm run build:linux
```

The built application will be in `desktop-ui/dist/`

For more details, see `desktop-ui/README.md`
