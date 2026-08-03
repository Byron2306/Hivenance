#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "${PYTHON_BIN}" ]; then
    if [ -x "${ROOT_DIR}/.venv-phase1/bin/python3" ]; then
        PYTHON_BIN="${ROOT_DIR}/.venv-phase1/bin/python3"
    elif [ -x "${ROOT_DIR}/.venv-phase1/bin/python" ]; then
        PYTHON_BIN="${ROOT_DIR}/.venv-phase1/bin/python"
    elif [ -x "${ROOT_DIR}/.venv/bin/python" ]; then
        PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
    else
        PYTHON_BIN="python3"
    fi
fi

cd "${ROOT_DIR}"
exec env -u ELECTRON_RUN_AS_NODE PYTHON_BIN="${PYTHON_BIN}" ./desktop-ui/start.sh
