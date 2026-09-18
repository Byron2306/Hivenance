#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION="${HIVENANCE_DRIZZLE_SESSION:-hivenance-relative-drizzle}"
PY="${HIVENANCE_DRIZZLE_PYTHON:-python}"
DURATION="${HIVENANCE_DRIZZLE_DURATION_SEC:-900}"
INTERVAL="${HIVENANCE_DRIZZLE_INTERVAL_SEC:-1.0}"
DB="${HIVENANCE_DRIZZLE_DB:-$ROOT/data/live_relative_drizzle_lab.db}"
START="${HIVENANCE_DRIZZLE_START_USD:-1000}"
NOTIONAL="${HIVENANCE_DRIZZLE_NOTIONAL_USD:-25}"
COST="${HIVENANCE_DRIZZLE_COST_BPS_SIDE:-4.0}"
SYMBOLS="${HIVENANCE_DRIZZLE_SYMBOLS:-BTC/USD ETH/USD SOL/USD XRP/USD ADA/USD AVAX/USD DOGE/USD HYPE/USD}"

cd "$ROOT"

command -v "$PY" >/dev/null 2>&1 || { echo "Python missing: pkg install python -y" >&2; exit 1; }
command -v tmux >/dev/null 2>&1 || { echo "tmux missing: pkg install tmux -y" >&2; exit 1; }

"$PY" - <<'PY'
from agents.strategy_workers import MomentumWorker, VolatilityExpansionWorker
from agents.nurse import NurseAgent
from scripts.run_live_relative_drizzle_lab import MUTATIONS
assert "relative_hysteresis" in MUTATIONS
print("RELATIVE_DRIZZLE_TERMUX_PREFLIGHT_OK")
PY

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "Session already exists: $SESSION"
  echo "Attach with: tmux attach -t $SESSION"
  exit 0
fi

CMD="'$PY' -u scripts/run_live_relative_drizzle_lab.py --duration-sec '$DURATION' --interval-sec '$INTERVAL' --database '$DB' --start-usd '$START' --notional-usd '$NOTIONAL' --cost-bps-side '$COST' --symbols $SYMBOLS"

tmux new-session -d -s "$SESSION" -n relative-live "cd '$ROOT' && $CMD; status=\$?; echo RELATIVE_DRIZZLE_EXITED_\$status; exec bash"
tmux new-window -t "$SESSION" -n nurse-learning "cd '$ROOT' && while true; do clear; '$PY' scripts/report_live_relative_drizzle_lab.py --database '$DB' --latest || true; sleep 10; done"

tmux select-window -t "$SESSION:relative-live"

echo "Phoenix relative-drizzle lab started."
echo "Session: $SESSION"
echo "Duration: ${DURATION}s | cadence: ${INTERVAL}s | cost model: ${COST} bps/side"
echo "Paper sleeve: ${NOTIONAL} USD continuously held in one coin after initialization"
echo "Stable refuge after initialization: NO"
echo "Database: $DB"
echo "Private API keys loaded: NO"
echo "Orders submitted: 0"
echo
echo "Attach:"
echo "  tmux attach -t $SESSION"
echo "  Ctrl-b 0 = live relative drizzle"
echo "  Ctrl-b 1 = Nurse learning"
