#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/byron/Downloads/Hivenance_Phoenix_Phase7_1_Integration_Reconciliation"
cd "$ROOT"

exec "$ROOT/.venv-phase1/bin/python3" run_ui_server.py
