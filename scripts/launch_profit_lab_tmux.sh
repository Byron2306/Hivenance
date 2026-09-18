#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION="${HIVENANCE_PROFIT_LAB_SESSION:-hivenance-profit-lab}"
PY="$ROOT/.venv-phase1/bin/python"
DB="${HIVENANCE_PROFIT_LAB_DB:-data/swarm_data.db}"
EXCHANGE="${HIVENANCE_PROFIT_LAB_EXCHANGE:-kraken}"
RAPID_DIRECTIONS="${HIVENANCE_RAPID_DIRECTIONS:-UP,DOWN}"
RAPID_FRESH_SEC="${HIVENANCE_RAPID_FRESH_SEC:-900}"
RAPID_DURATION_SEC="${HIVENANCE_RAPID_DURATION_SEC:-7200}"
RAPID_INTERVAL_SEC="${HIVENANCE_RAPID_INTERVAL_SEC:-30}"
RAPID_LLM_ARGS=""
RAPID_SCOUT_ARGS=""

if [[ "${HIVENANCE_RAPID_LLM:-0}" == "1" ]]; then
  RAPID_LLM_ARGS="--llm --ollama-model ${HIVENANCE_RAPID_OLLAMA_MODEL:-beast-crystal-qwen25-05b:latest}"
fi

if [[ "${HIVENANCE_RAPID_CHAMPION_SCOUT:-1}" == "1" ]]; then
  RAPID_SCOUT_ARGS="--champion-scout"
fi

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is required for the profit lab launcher" >&2
  exit 1
fi

if [[ ! -x "$PY" ]]; then
  echo "missing virtualenv python at $PY" >&2
  exit 1
fi

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "profit lab session already exists: $SESSION"
  tmux list-windows -t "$SESSION"
  exit 0
fi

tmux new-session -d -s "$SESSION" -n observer \
  "cd '$ROOT' && '$PY' -u scripts/run_phase1_observer.py --exchange '$EXCHANGE'; echo OBSERVER_EXITED_\$?; exec bash"

tmux new-window -t "$SESSION" -n hypotheses \
  "cd '$ROOT' && '$PY' -u scripts/run_phase2_hypotheses.py --exchange '$EXCHANGE' --database '$DB' --compact-scorecard --report-only; echo HYPOTHESES_EXITED_\$?; exec bash"

tmux new-window -t "$SESSION" -n sovereign \
  "cd '$ROOT' && '$PY' -u scripts/run_sovereign_pool_worker.py --database '$DB' --poll-sec 10 --limit 100; echo SOVEREIGN_EXITED_\$?; exec bash"

tmux new-window -t "$SESSION" -n rapid-tape \
  "cd '$ROOT' && '$PY' -u scripts/run_rapid_paper_tape.py --database '$DB' --database-only --loose --fresh-window-sec '$RAPID_FRESH_SEC' --duration-sec '$RAPID_DURATION_SEC' --interval-sec '$RAPID_INTERVAL_SEC' --skip-settlement --directions '$RAPID_DIRECTIONS' $RAPID_LLM_ARGS $RAPID_SCOUT_ARGS; echo RAPID_TAPE_EXITED_\$?; exec bash"

tmux select-window -t "$SESSION:rapid-tape"
echo "started $SESSION"
echo "attach with: tmux attach -t $SESSION"
echo "rapid tape directions: $RAPID_DIRECTIONS; private orders: 0; live canary: not started"
echo "champion scout: ${HIVENANCE_RAPID_CHAMPION_SCOUT:-1}"
