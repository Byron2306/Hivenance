#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LOG_DIR="${ROOT_DIR}/logs"
mkdir -p "${LOG_DIR}"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if [ -x "${ROOT_DIR}/.venv/bin/python" ]; then
    PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
elif [ -x "${ROOT_DIR}/.venv-phase1/bin/python3" ]; then
    PYTHON_BIN="${ROOT_DIR}/.venv-phase1/bin/python3"
elif [ -x "${ROOT_DIR}/.venv-phase1/bin/python" ]; then
    PYTHON_BIN="${ROOT_DIR}/.venv-phase1/bin/python"
fi

PIDS=()

cleanup() {
    for pid in "${PIDS[@]:-}"; do
        if kill -0 "${pid}" >/dev/null 2>&1; then
            kill "${pid}" >/dev/null 2>&1 || true
        fi
    done
}
trap cleanup EXIT INT TERM

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

port_open() {
    local port="$1"
    "${PYTHON_BIN}" - "$port" <<'PY'
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(0.2)
try:
    sys.exit(0 if sock.connect_ex(("127.0.0.1", port)) == 0 else 1)
finally:
    sock.close()
PY
}

find_free_port() {
    local start="$1"
    "${PYTHON_BIN}" - "$start" <<'PY'
import socket
import sys

start = int(sys.argv[1])
for port in range(start, 65535):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            continue
        print(port)
        raise SystemExit(0)
raise SystemExit("no free TCP ports found")
PY
}

wait_for_http() {
    local url="$1"
    local name="$2"
    local timeout="${3:-30}"
    local start
    start="$(date +%s)"
    while true; do
        if command_exists curl && curl -fsS "${url}" >/dev/null 2>&1; then
            return 0
        fi
        if [ "$(( $(date +%s) - start ))" -ge "${timeout}" ]; then
            echo "Timed out waiting for ${name} at ${url}"
            return 1
        fi
        sleep 1
    done
}

setting_value() {
    local key="$1"
    "${PYTHON_BIN}" - "${ROOT_DIR}/config/settings.yaml" "${key}" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]
if not path.exists():
    raise SystemExit(0)
for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
    if line.startswith(f"{key}:"):
        print(line.split(":", 1)[1].strip().strip("'\""))
        break
PY
}

echo "============================================"
echo " Hivenance Desktop UI - Launcher"
echo "============================================"
echo ""

cd "${SCRIPT_DIR}"
if [ ! -d "node_modules" ]; then
    echo "Installing desktop dependencies..."
    npm install
    echo ""
fi

cd "${ROOT_DIR}"

BACKEND_PORT="${HIVENANCE_UI_PORT:-${PORT:-}}"
if [ -z "${BACKEND_PORT}" ] || port_open "${BACKEND_PORT}"; then
    BACKEND_PORT="$(find_free_port "${HIVENANCE_BACKEND_PORT_START:-5000}")"
fi

BUZZ_PORT="${BUZZ_PORT:-9009}"
BUZZ_ALREADY_RUNNING=0
if port_open "${BUZZ_PORT}"; then
    BUZZ_ALREADY_RUNNING=1
    echo "BuzzService appears to already be using port ${BUZZ_PORT}; reusing it."
else
    BUZZ_PORT="$(find_free_port "${BUZZ_PORT}")"
fi

SWARMGUARD_PORT="${SWARMGUARD_PORT:-9010}"
SWARMGUARD_ALREADY_RUNNING=0
if port_open "${SWARMGUARD_PORT}"; then
    SWARMGUARD_ALREADY_RUNNING=1
    echo "SwarmGuard appears to already be using port ${SWARMGUARD_PORT}; reusing it."
else
    SWARMGUARD_PORT="$(find_free_port "${SWARMGUARD_PORT}")"
fi

REDIS_PORT="${REDIS_PORT:-6379}"
if port_open "${REDIS_PORT}"; then
    echo "Redis appears to already be using port ${REDIS_PORT}; reusing it."
elif command_exists redis-server; then
    echo "Starting Redis on 127.0.0.1:${REDIS_PORT}..."
    redis-server --bind 127.0.0.1 --port "${REDIS_PORT}" --save "" --appendonly no >"${LOG_DIR}/redis.desktop.log" 2>&1 &
    PIDS+=("$!")
    sleep 1
    if ! port_open "${REDIS_PORT}"; then
        echo "Redis did not start on ${REDIS_PORT}; choosing an alternate port."
        REDIS_PORT="$(find_free_port 6380)"
        redis-server --bind 127.0.0.1 --port "${REDIS_PORT}" --save "" --appendonly no >"${LOG_DIR}/redis.desktop.log" 2>&1 &
        PIDS+=("$!")
        sleep 1
    fi
else
    echo "redis-server is not installed; continuing without starting Redis."
fi

SHARED_SECRET="${BUZZ_SHARED_SECRET:-$(setting_value buzz_shared_secret)}"
if [ -z "${SHARED_SECRET}" ] || [ "${SHARED_SECRET}" = "CHANGE_ME" ]; then
    SHARED_SECRET="$(${PYTHON_BIN} - <<'PYSECRET'
import secrets
print(secrets.token_hex(32))
PYSECRET
)"
    echo "Generated an ephemeral local service secret for this launch."
fi

if [ "${BUZZ_ALREADY_RUNNING}" -eq 0 ]; then
    echo "Starting BuzzService on http://127.0.0.1:${BUZZ_PORT}..."
    BUZZ_SHARED_SECRET="${SHARED_SECRET}" HIVE_SHARED_SECRET="${SHARED_SECRET}" \
        "${PYTHON_BIN}" -m uvicorn buzzservice.service:app --host 127.0.0.1 --port "${BUZZ_PORT}" \
        >"${LOG_DIR}/buzzservice.desktop.log" 2>&1 &
    PIDS+=("$!")
    wait_for_http "http://127.0.0.1:${BUZZ_PORT}/" "BuzzService" 20 || true
fi

if [ "${SWARMGUARD_ALREADY_RUNNING}" -eq 0 ]; then
    echo "Starting SwarmGuard on http://127.0.0.1:${SWARMGUARD_PORT}..."
    SWARMGUARD_HMAC_SECRET="${SHARED_SECRET}" BUZZ_SHARED_SECRET="${SHARED_SECRET}" HIVE_SHARED_SECRET="${SHARED_SECRET}" \
    BUZZ_BASE_URL="http://127.0.0.1:${BUZZ_PORT}" \
        "${PYTHON_BIN}" -m uvicorn swarmguard_service.service:app --host 127.0.0.1 --port "${SWARMGUARD_PORT}" \
        >"${LOG_DIR}/swarmguard.desktop.log" 2>&1 &
    PIDS+=("$!")
    wait_for_http "http://127.0.0.1:${SWARMGUARD_PORT}/docs" "SwarmGuard" 20 || true
fi

BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"
echo "Starting Hivenance backend on ${BACKEND_URL}..."
HIVENANCE_UI_PORT="${BACKEND_PORT}" PORT="${BACKEND_PORT}" \
HIVENANCE_ENABLE_REDIS="1" \
HIVENANCE_REDIS_HOST="localhost" HIVENANCE_REDIS_PORT="${REDIS_PORT}" \
BUZZ_BASE_URL="http://127.0.0.1:${BUZZ_PORT}" BUZZ_SHARED_SECRET="${SHARED_SECRET}" HIVE_SHARED_SECRET="${SHARED_SECRET}" \
    "${PYTHON_BIN}" run_ui_server.py >"${LOG_DIR}/backend.desktop.log" 2>&1 &
PIDS+=("$!")
wait_for_http "${BACKEND_URL}/api/status" "Hivenance backend" 45

echo ""
echo "Backend URL: ${BACKEND_URL}"
echo "Redis:       127.0.0.1:${REDIS_PORT}"
echo "BuzzService: http://127.0.0.1:${BUZZ_PORT}"
echo "SwarmGuard:  http://127.0.0.1:${SWARMGUARD_PORT}"
echo ""
echo "Launching desktop UI..."
echo ""

cd "${SCRIPT_DIR}"
env -u ELECTRON_RUN_AS_NODE HIVENANCE_BACKEND_URL="${BACKEND_URL}" npm start
