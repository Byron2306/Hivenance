#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="${HOME}/Hivenance"
SESSION="${HIVENANCE_TMUX_SESSION:-hivenance12}"
HOURS="${1:-12}"
LOG_DIR="${ROOT}/data/logs"
STAMP="$(date +%Y%m%d_%H%M%S)"
LOG="${LOG_DIR}/phase12_adaptive_${STAMP}.log"

mkdir -p "${LOG_DIR}"
cd "${ROOT}"

if tmux has-session -t "${SESSION}" 2>/dev/null; then
  echo "tmux session already exists: ${SESSION}"
  echo "attach: tmux attach -t ${SESSION}"
  exit 1
fi

CMD="cd '${ROOT}' && PYTHONPATH='${ROOT}' python scripts/run_phase12_adaptive_gauntlet.py --hours '${HOURS}' --pause-sec 15 --quiet-kraken 2>&1 | tee -a '${LOG}'"

tmux new-session -d -s "${SESSION}" "${CMD}"

echo "Hivenance Phase 12 adaptive gauntlet started"
echo "session=${SESSION}"
echo "hours=${HOURS}"
echo "log=${LOG}"
echo "attach: tmux attach -t ${SESSION}"
echo "detach: Ctrl-b d"
echo "stop:   tmux send-keys -t ${SESSION} C-c"
