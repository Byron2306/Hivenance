#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export HIVENANCE_HORIZON_DURATION_SEC="${HIVENANCE_HORIZON_DURATION_SEC:-0}"
export HIVENANCE_HORIZON_INTERVAL_SEC="${HIVENANCE_HORIZON_INTERVAL_SEC:-5.0}"
export HIVENANCE_HORIZON_DB="${HIVENANCE_HORIZON_DB:-$ROOT/data/hivenance_horizon_context.db}"

export HIVENANCE_INVENTORY_DURATION_SEC="${HIVENANCE_INVENTORY_DURATION_SEC:-900}"
export HIVENANCE_INVENTORY_INTERVAL_SEC="${HIVENANCE_INVENTORY_INTERVAL_SEC:-1.0}"
export HIVENANCE_INVENTORY_DB="${HIVENANCE_INVENTORY_DB:-$ROOT/data/live_inventory_drizzle_lab.db}"
export HIVENANCE_INVENTORY_START_USD="${HIVENANCE_INVENTORY_START_USD:-1000}"
export HIVENANCE_INVENTORY_ACTIVE_USD="${HIVENANCE_INVENTORY_ACTIVE_USD:-200}"
export HIVENANCE_INVENTORY_REBALANCE_USD="${HIVENANCE_INVENTORY_REBALANCE_USD:-5}"
export HIVENANCE_INVENTORY_COST_BPS_SIDE="${HIVENANCE_INVENTORY_COST_BPS_SIDE:-4.0}"

echo "Starting long-player Hivenance Horizon..."
bash scripts/launch_termux_hivenance_horizon.sh

# Give Horizon a few public ticks before the drizzle process begins. This is
# context seeding only; inventory admission does not consume Horizon in v1.
sleep 3

echo
echo "Starting inventory-drizzle research lab..."
HIVENANCE_INVENTORY_HORIZON_DB="$HIVENANCE_HORIZON_DB" bash scripts/launch_termux_inventory_drizzle_lab.sh

echo
echo "Dual Hivenance research stack is running."
echo
echo "Long player:"
echo "  tmux attach -t hivenance-horizon"
echo "  Ctrl-b 0 = Horizon live"
echo "  Ctrl-b 1 = Horizon dashboard"
echo
echo "Drizzle player:"
echo "  tmux attach -t hivenance-inventory-drizzle"
echo "  Ctrl-b 0 = inventory live"
echo "  Ctrl-b 1 = Nurse learning"
echo
echo "Horizon continues after the 15-minute drizzle run unless you stop it manually:"
echo "  tmux kill-session -t hivenance-horizon"
echo
echo "PRIVATE ORDERS: 0"
