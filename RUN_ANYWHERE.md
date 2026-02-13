# Run Hivenance / VAMP without Codespaces

If you ran out of Codespace time, the easiest replacement is Docker on your own machine.

## Option 1 (recommended): Docker Compose (local laptop/desktop)

### 1) Prerequisites
- Docker Desktop (or Docker Engine + Compose plugin)
- Git

### 2) Clone and configure
```bash
git clone <your-fork-or-repo-url>
cd Hivenance
cp config/settings.yaml config/settings.local.yaml
```

Create a local `.env` file at repo root (optional but recommended):
```bash
cat > .env <<'ENV'
WALLETCONNECT_PROJECT_ID=
ONEINCH_API_KEY=
# Optional Telegram QUEEN gate
QUEEN_TELEGRAM_ENABLED=false
QUEEN_TELEGRAM_BOT_TOKEN=
QUEEN_TELEGRAM_CHAT_ID=
ENV
```

### 3) Start services
```bash
cd docker
docker compose up --build
```

### 4) Open the app
- Flask UI: `http://localhost:5000/api/`
- Health endpoint: `http://localhost:5000/`

### 5) Stop services
```bash
docker compose down
```

---

## One-command local live install (recommended for your PC)

From repo root:

```bash
chmod +x install_live.sh
./install_live.sh
```

Then edit `.env.live` with your real keys/wallet values and start live mode:

```bash
source .venv/bin/activate
export CRYPTSWARM_SETTINGS_PATH=config/settings.live.yaml
export CRYPTSWARM_LIVE=1
python3 start_vamp.py
```

Open `http://localhost:5000/` (or legacy `http://localhost:5000/api/`).

---

## Option 2: Python-only local run (no Docker)

### 1) Install deps
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Start app
```bash
python3 main.py
```

Or run full local stack (main + BuzzService + SwarmGuard):
```bash
python3 start_vamp.py
```

Then open `http://localhost:5000/api/`.

> Notes:
> - Redis/network features are optional for basic startup and may log warnings if Redis is absent.
> - Wallet/on-chain monitoring requires valid RPC/env credentials.

---

## Validation commands (full VAMP backend checks)

From repo root:

```bash
python3 backend_test.py
pytest -q
python3 -m compileall agents backend swarmguard_service buzzservice main.py SWARM.py
git fsck --full
```

Frontend build check (if npm registry access is available):
```bash
cd frontend
npm install
npm run build
```

---

## Lowest-friction hosted alternative to Codespaces

If you want a cloud dev machine quickly:
- Gitpod (browser IDE, GitHub sign-in)
- Replit (Nix/Container project)

For long-running deployment (not IDE), use:
- Render (Docker web service)
- Railway (Docker service)

Use `docker/docker-compose.yml` as the reference runtime contract for ports, env vars, and mounted state.
