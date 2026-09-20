#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="${HOME}/Hivenance"
SESSION="${HIVENANCE_TMUX_SESSION:-hivenance12}"
MODE="${1:-12}"
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

if [ "${MODE}" = "continuous" ]; then
  GAUNTLET_ARGS="--continuous"
else
  GAUNTLET_ARGS="--hours '${MODE}'"
fi

CMD="cd '${ROOT}' && PYTHONPATH='${ROOT}' python scripts/run_phase12_adaptive_gauntlet.py ${GAUNTLET_ARGS} --pause-sec 15 --quiet-kraken 2>&1 | tee -a '${LOG}'"

tmux new-session -d -s "${SESSION}" "${CMD}"

echo "Hivenance Phase 12 adaptive gauntlet started"
echo "session=${SESSION}"
echo "mode=${MODE}"
echo "log=${LOG}"
echo "attach: tmux attach -t ${SESSION}"
echo "detach: Ctrl-b d"
echo "stop:   tmux send-keys -t ${SESSION} C-c"
