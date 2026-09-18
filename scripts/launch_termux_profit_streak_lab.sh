#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION="${HIVENANCE_STREAK_SESSION:-hivenance-streak-live}"
VENV="${HIVENANCE_STREAK_VENV:-$ROOT/.venv-streak-termux}"
DURATION="${HIVENANCE_STREAK_DURATION_SEC:-900}"
INTERVAL="${HIVENANCE_STREAK_INTERVAL_SEC:-1.0}"
DB="${HIVENANCE_STREAK_DB:-$ROOT/data/live_profit_streak_lab.db}"
COST="${HIVENANCE_STREAK_COST_BPS_SIDE:-4.0}"
NOTIONAL="${HIVENANCE_STREAK_NOTIONAL_USD:-25}"
START="${HIVENANCE_STREAK_START_USD:-1000}"
SYMBOLS="${HIVENANCE_STREAK_SYMBOLS:-BTC/USD ETH/USD SOL/USD XRP/USD ADA/USD AVAX/USD DOGE/USD HYPE/USD}"

cd "$ROOT"

if ! command -v python >/dev/null 2>&1; then
  echo "Python missing. In Termux run: pkg install python -y" >&2
  exit 1
fi
if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux missing. In Termux run: pkg install tmux -y" >&2
  exit 1
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "Creating lightweight Termux lab venv: $VENV"
  python -m venv "$VENV"
fi

PY="$VENV/bin/python"
PIP="$VENV/bin/pip"

if ! "$PY" - <<'PY' >/dev/null 2>&1
import ccxt, requests
PY
then
  echo "Installing lightweight public-market dependencies..."
  "$PIP" install --upgrade pip
  "$PIP" install ccxt requests
fi

mkdir -p "$(dirname "$DB")"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "Session already exists: $SESSION"
  echo "Attach with: tmux attach -t $SESSION"
  exit 0
fi

CMD="'$PY' -u scripts/run_live_profit_streak_swarm.py --duration-sec '$DURATION' --interval-sec '$INTERVAL' --database '$DB' --start-usd '$START' --notional-usd '$NOTIONAL' --cost-bps-side '$COST' --symbols $SYMBOLS"

tmux new-session -d -s "$SESSION" -n streak-live "cd '$ROOT' && $CMD; status=\$?; echo LIVE_LAB_EXITED_\$status; exec bash"
tmux new-window -t "$SESSION" -n report "cd '$ROOT' && while true; do clear; '$PY' scripts/report_live_profit_streak_swarm.py --database '$DB' --latest || true; sleep 10; done"

tmux select-window -t "$SESSION:streak-live"

echo "Phoenix live public-market streak lab started."
echo "Session: $SESSION"
echo "Duration: ${DURATION}s | cadence: ${INTERVAL}s | cost model: ${COST} bps/side"
echo "Database: $DB"
echo "Authority: PUBLIC MARKET + FAKE WALLETS ONLY"
echo "Private API keys loaded: NO"
echo "Orders submitted: 0"
echo
echo "Attach:"
echo "  tmux attach -t $SESSION"
echo
echo "Switch windows:"
echo "  Ctrl-b 0   live lab"
echo "  Ctrl-b 1   rolling report"
