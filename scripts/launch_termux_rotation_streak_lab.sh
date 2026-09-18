#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION="${HIVENANCE_ROTATION_SESSION:-hivenance-rotation-live}"
PY="${HIVENANCE_ROTATION_PYTHON:-python}"
DURATION="${HIVENANCE_ROTATION_DURATION_SEC:-900}"
INTERVAL="${HIVENANCE_ROTATION_INTERVAL_SEC:-1.0}"
DB="${HIVENANCE_ROTATION_DB:-$ROOT/data/live_rotation_streak_lab.db}"
START="${HIVENANCE_ROTATION_START_USD:-1000}"
NOTIONAL="${HIVENANCE_ROTATION_NOTIONAL_USD:-25}"
COST="${HIVENANCE_ROTATION_COST_BPS_SIDE:-4.0}"
SYMBOLS="${HIVENANCE_ROTATION_SYMBOLS:-BTC/USD ETH/USD SOL/USD XRP/USD ADA/USD AVAX/USD DOGE/USD HYPE/USD}"

cd "$ROOT"

command -v "$PY" >/dev/null 2>&1 || { echo "Python missing: pkg install python -y" >&2; exit 1; }
command -v tmux >/dev/null 2>&1 || { echo "tmux missing: pkg install tmux -y" >&2; exit 1; }

"$PY" - <<'PY'
from agents.strategy_workers import MomentumWorker, VolatilityExpansionWorker
from agents.nurse import NurseAgent
print("ROTATION_TERMUX_PREFLIGHT_OK")
PY

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "Session already exists: $SESSION"
  echo "Attach with: tmux attach -t $SESSION"
  exit 0
fi

CMD="'$PY' -u scripts/run_live_rotation_streak_lab.py --duration-sec '$DURATION' --interval-sec '$INTERVAL' --database '$DB' --start-usd '$START' --notional-usd '$NOTIONAL' --cost-bps-side '$COST' --symbols $SYMBOLS"

tmux new-session -d -s "$SESSION" -n rotation-live "cd '$ROOT' && $CMD; status=\$?; echo ROTATION_LAB_EXITED_\$status; exec bash"
tmux new-window -t "$SESSION" -n nurse-learning "cd '$ROOT' && while true; do clear; '$PY' scripts/report_live_rotation_streak_lab.py --database '$DB' --latest || true; sleep 10; done"

tmux select-window -t "$SESSION:rotation-live"

echo "Phoenix cross-asset rotation lab started."
echo "Session: $SESSION"
echo "Duration: ${DURATION}s | cadence: ${INTERVAL}s | cost model: ${COST} bps/side"
echo "Stable refuge: USD paper cash"
echo "Paper notional: ${NOTIONAL} USD"
echo "Database: $DB"
echo "Private API keys loaded: NO"
echo "Orders submitted: 0"
echo
echo "Attach:"
echo "  tmux attach -t $SESSION"
echo "  Ctrl-b 0 = live rotation"
echo "  Ctrl-b 1 = Nurse learning"
