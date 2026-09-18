#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION="${HIVENANCE_HORIZON_SESSION:-hivenance-horizon}"
PY="${HIVENANCE_HORIZON_PYTHON:-python}"
INTERVAL="${HIVENANCE_HORIZON_INTERVAL_SEC:-5.0}"
DURATION="${HIVENANCE_HORIZON_DURATION_SEC:-0}"
DB="${HIVENANCE_HORIZON_DB:-$ROOT/data/hivenance_horizon_context.db}"
SYMBOLS="${HIVENANCE_HORIZON_SYMBOLS:-BTC/USD ETH/USD SOL/USD XRP/USD ADA/USD AVAX/USD DOGE/USD HYPE/USD}"

cd "$ROOT"

command -v "$PY" >/dev/null 2>&1 || { echo "Python missing: pkg install python -y" >&2; exit 1; }
command -v tmux >/dev/null 2>&1 || { echo "tmux missing: pkg install tmux -y" >&2; exit 1; }

"$PY" - <<'PY'
from agents.horizon_context import HorizonContextAgent, AUTHORITY
assert "NO_EXECUTION_AUTHORITY" in AUTHORITY
print("HIVENANCE_HORIZON_PREFLIGHT_OK")
PY

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "Session already exists: $SESSION"
  echo "Attach with: tmux attach -t $SESSION"
  exit 0
fi

CMD="'$PY' -u scripts/run_hivenance_horizon_observer.py --duration-sec '$DURATION' --interval-sec '$INTERVAL' --database '$DB' --symbols $SYMBOLS"

tmux new-session -d -s "$SESSION" -n horizon-live "cd '$ROOT' && $CMD; status=\$?; echo HORIZON_EXITED_\$status; exec bash"
tmux new-window -t "$SESSION" -n horizon-report "cd '$ROOT' && while true; do clear; '$PY' scripts/report_hivenance_horizon_observer.py --database '$DB' || true; sleep 15; done"

tmux select-window -t "$SESSION:horizon-live"

echo "Hivenance Horizon started."
echo "Session: $SESSION"
echo "Cadence: ${INTERVAL}s"
echo "Duration: ${DURATION}s (0 = continuous)"
echo "Database: $DB"
echo "Micro: 10s / 30s"
echo "Meso: 2m / 5m"
echo "Macro: 15m / 1h + Kraken 24h public context"
echo "Execution authority: NONE"
echo "Private API keys loaded: NO"
echo "Orders submitted: 0"
echo
echo "Attach:"
echo "  tmux attach -t $SESSION"
echo "  Ctrl-b 0 = live horizon context"
echo "  Ctrl-b 1 = horizon dashboard"
