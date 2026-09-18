#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION="${HIVENANCE_INVENTORY_SESSION:-hivenance-inventory-drizzle}"
PY="${HIVENANCE_INVENTORY_PYTHON:-python}"
DURATION="${HIVENANCE_INVENTORY_DURATION_SEC:-900}"
INTERVAL="${HIVENANCE_INVENTORY_INTERVAL_SEC:-1.0}"
DB="${HIVENANCE_INVENTORY_DB:-$ROOT/data/live_inventory_drizzle_lab.db}"
HORIZON_DB="${HIVENANCE_INVENTORY_HORIZON_DB:-$ROOT/data/hivenance_horizon_context.db}"
START="${HIVENANCE_INVENTORY_START_USD:-1000}"
ACTIVE="${HIVENANCE_INVENTORY_ACTIVE_USD:-200}"
SLICE="${HIVENANCE_INVENTORY_REBALANCE_USD:-5}"
COST="${HIVENANCE_INVENTORY_COST_BPS_SIDE:-4.0}"
MAKER_COST="${HIVENANCE_INVENTORY_MAKER_COST_BPS_SIDE:--1.0}"
SYMBOLS="${HIVENANCE_INVENTORY_SYMBOLS:-BTC/USD ETH/USD SOL/USD XRP/USD ADA/USD AVAX/USD DOGE/USD HYPE/USD}"

cd "$ROOT"

command -v "$PY" >/dev/null 2>&1 || { echo "Python missing: pkg install python -y" >&2; exit 1; }
command -v tmux >/dev/null 2>&1 || { echo "tmux missing: pkg install tmux -y" >&2; exit 1; }

"$PY" - <<'PY'
from agents.nurse import NurseAgent
from scripts.run_live_inventory_drizzle_lab import MUTATIONS
assert "inventory_hold" in MUTATIONS
assert "inventory_swarm_streak" in MUTATIONS
print("INVENTORY_DRIZZLE_TERMUX_PREFLIGHT_OK")
PY

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "Session already exists: $SESSION"
  echo "Attach with: tmux attach -t $SESSION"
  exit 0
fi

CMD="'$PY' -u scripts/run_live_inventory_drizzle_lab.py --duration-sec '$DURATION' --interval-sec '$INTERVAL' --database '$DB' --horizon-database '$HORIZON_DB' --start-usd '$START' --inventory-usd '$ACTIVE' --rebalance-usd '$SLICE' --cost-bps-side '$COST' --maker-cost-bps-side '$MAKER_COST' --symbols $SYMBOLS"

tmux new-session -d -s "$SESSION" -n inventory-live "cd '$ROOT' && $CMD; status=\$?; echo INVENTORY_DRIZZLE_EXITED_\$status; exec bash"
tmux new-window -t "$SESSION" -n nurse-learning "cd '$ROOT' && while true; do clear; '$PY' scripts/report_live_inventory_drizzle_lab.py --database '$DB' --latest || true; sleep 10; done"

tmux select-window -t "$SESSION:inventory-live"

echo "Phoenix inventory-drizzle lab started."
echo "Session: $SESSION"
echo "Duration: ${DURATION}s | cadence: ${INTERVAL}s | fee model: ${COST} bps/side"
echo "Active equal-weight inventory: ${ACTIVE} USD"
echo "Rebalance slice: ${SLICE} USD"
echo "Maker counterfactual cost/side: $MAKER_COST (<0 = break-even only)"
echo "Benchmark: equal-weight inventory_hold"
echo "Direct pair graph: Kraken public AssetPairs"
echo "Private API keys loaded: NO"
echo "Orders submitted: 0"
echo
echo "Attach:"
echo "  tmux attach -t $SESSION"
echo "  Ctrl-b 0 = inventory drizzle"
echo "  Ctrl-b 1 = Nurse learning"
