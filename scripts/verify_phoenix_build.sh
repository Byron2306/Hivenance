#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

cd "$ROOT"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "[1/7] Compile Python sources"
"$PYTHON_BIN" -m compileall -q agents strategies scripts tests

echo "[2/7] Run unit and integration tests"
"$PYTHON_BIN" -m pytest -q --disable-warnings

echo "[3/7] Run phase safety preflights"
for script in \
  scripts/phase0_preflight.py \
  scripts/phase1_preflight.py \
  scripts/phase2_preflight.py \
  scripts/phase3_preflight.py \
  scripts/phase4_preflight.py \
  scripts/phase5_preflight.py \
  scripts/phase6_preflight.py \
  scripts/phase7_preflight.py \
  scripts/phase7_1_preflight.py
do
  TERM="${TERM:-dumb}" "$PYTHON_BIN" "$script" >/dev/null
  echo "  PASS $script"
done

echo "[4/7] Exercise Phase-6 deterministic canary control gate"
PHASE6_SOAK_OUTPUT="$TMP_DIR/phase6_synthetic_soak.json"
"$PYTHON_BIN" scripts/phase6_synthetic_soak.py --round-trips 60 --output "$PHASE6_SOAK_OUTPUT" >/dev/null
"$PYTHON_BIN" - "$PHASE6_SOAK_OUTPUT" <<'PY_PHASE6'
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
campaign = report["campaign"]
gate = campaign["phase7_review_gate"]
assert campaign["kind"] == "deterministic_fake_exchange_safety_control"
assert campaign["market_profitability_evidence"] is False
assert campaign["network_calls"] == 0
assert campaign["credentials_loaded"] is False
assert campaign["completed_round_trips"] >= 60
assert gate["ready_for_phase7_review"] is True
assert gate["reasons"] == []
assert campaign["legacy_orders_rows"] == 0
assert campaign["legacy_fills_rows"] == 0
assert campaign["unknown_orders"] == 0
assert campaign["open_incidents"] == 0
assert campaign["open_positions"] == 0
assert campaign["automatic_scaling"] is False
assert campaign["leverage"] == 1
sabotage = report["ambiguity_sabotage"]
assert sabotage["first_status"] == "HALTED"
assert sabotage["second_status"] == "HALTED"
assert sabotage["add_calls_after_two_cycles"] == 1
print("  PASS Phase-6 synthetic canary control gate and ambiguity halt")
PY_PHASE6

echo "[5/7] Exercise offline Phase-5-only acceptance pipeline"
"$PYTHON_BIN" scripts/run_research_acceptance_pipeline.py \
  --database "$TMP_DIR/acceptance.db" \
  --truth-output "$TMP_DIR/CURRENT_TRUTH.json" \
  --offline --phase5-only --once --phase-timeout-sec 120 >/dev/null

echo "[6/7] Verify truth and safety invariants"
"$PYTHON_BIN" - "$TMP_DIR/CURRENT_TRUTH.json" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
report = json.loads(path.read_text(encoding="utf-8"))
assert report["schema"] == "hivenance_current_truth_v1"
assert report["overall"]["authority"] == "RESEARCH_ONLY"
assert report["overall"]["live_execution_authorized"] is False
assert report["safety"]["status"] == "CLEAN"
assert all(int(value) <= 0 for value in report["safety"]["evidence"].values())
assert str(report["truth_digest"]).startswith("sha256:")
print("  PASS truth schema, research-only authority, zero-order safety, digest")
PY

echo "[7/7] Verify desktop source and packaging contract"
node --check desktop-ui/main.js
node --check desktop-ui/preload.js
node --check desktop-ui/renderer/app.js
if grep -RqiE 'on(click|change|input|submit|load|error|mouseover|mouseout|keydown|keyup)=' desktop-ui/renderer; then
  echo "Inline event handler violates desktop CSP" >&2
  exit 1
fi
"$PYTHON_BIN" - <<'PY_DESKTOP'
import json
from pathlib import Path
pkg = json.loads(Path("desktop-ui/package.json").read_text(encoding="utf-8"))
assert pkg["build"]["electronDist"] == "node_modules/electron/dist"
assert any(item.get("from") == "../static" and item.get("to") == "static" for item in pkg["build"]["extraResources"])
assert "--linux dir" in pkg["scripts"]["build:linux"]
print("  PASS JavaScript syntax, CSP-safe handlers, local Electron, packaged static assets")
PY_DESKTOP

echo "PHOENIX BUILD VERIFICATION: PASS"
