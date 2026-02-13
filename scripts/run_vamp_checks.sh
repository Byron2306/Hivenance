#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[checks] python compile"
python3 -m compileall agents backend swarmguard_service buzzservice main.py SWARM.py >/tmp/vamp_compile.log

echo "[checks] backend test suite"
python3 backend_test.py >/tmp/vamp_backend_test.log

echo "[checks] pytest"
pytest -q >/tmp/vamp_pytest.log

echo "[checks] smoke startup"
nohup python3 start_vamp.py >/tmp/vamp_live_smoke.log 2>&1 &
PID=$!
cleanup() {
  kill "$PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT
sleep 12

for ep in /api/trades.json /api/learning/status.json /api/analytics.json /api/intents.json; do
  code=$(curl -s -o /tmp/vamp_ep.json -w '%{http_code}' "http://127.0.0.1:5000${ep}")
  if [[ "$code" != "200" ]]; then
    echo "[checks] FAIL ${ep} -> ${code}"
    exit 1
  fi
  echo "[checks] OK ${ep}"
done

wallet_code=$(curl -s -o /tmp/vamp_wallet.json -w '%{http_code}' "http://127.0.0.1:5000/api/wallet.json")
if [[ "$wallet_code" != "200" && "$wallet_code" != "400" ]]; then
  echo "[checks] FAIL /api/wallet.json -> ${wallet_code}"
  exit 1
fi
echo "[checks] wallet endpoint code=${wallet_code}"

echo "[checks] complete"
