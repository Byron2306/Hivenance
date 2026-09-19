#!/usr/bin/env python3
"""Freeze and verify the local Phase-0 evidence manifest.

Reads only existing research evidence. Does not modify G0/G1 evidence tables.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Termux/Python 3.14 cryptography preload guard before importing main.
if os.environ.get("PREFIX") and not os.environ.get("HIVENANCE_PHASE0_PRELOAD_DONE"):
    libpython = Path(os.environ["PREFIX"]) / "lib" / f"libpython{sys.version_info.major}.{sys.version_info.minor}.so"
    if libpython.exists():
        env = dict(os.environ)
        existing = env.get("LD_PRELOAD", "").strip()
        env["LD_PRELOAD"] = str(libpython) if not existing else str(libpython) + ":" + existing
        env["HIVENANCE_PHASE0_PRELOAD_DONE"] = "1"
        os.execve(sys.executable, [sys.executable, *sys.argv], env)

from main import apply_phase0_safety_policy, load_config
from strategies.relative_value_lab.full_organism_phase0 import (
    build_phase0_evidence_manifest,
    validate_phase0_manifest,
)


def _git_head() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    ap.add_argument(
        "--output",
        default="data/HIVENANCE_FULL_ORGANISM_PHASE0_EVIDENCE_MANIFEST.json",
    )
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()

    cfg = apply_phase0_safety_policy(load_config())
    db_path = Path(str(args.db or getattr(cfg, "db_path", "data/swarm_data.db")))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    if not db_path.exists():
        raise SystemExit(f"PHASE0_REFUSE database_missing: {db_path}")

    manifest = build_phase0_evidence_manifest(
        root=ROOT,
        db_path=db_path,
        git_head=_git_head(),
    )
    valid, reasons = validate_phase0_manifest(manifest)

    if not args.verify_only:
        out = Path(args.output)
        if not out.is_absolute():
            out = ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        # This file is a fingerprint/index. It never updates the evidence tables.
        out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print("HIVENANCE_FULL_ORGANISM_PHASE0")
    print(json.dumps({
        "status": "PASS" if valid else "REFUSE",
        "phase": 0,
        "branch": manifest.get("branch"),
        "git_head": manifest.get("git_head"),
        "campaign_id": manifest["campaign_identity"].get("campaign_id"),
        "research_target_id": manifest["campaign_identity"].get("research_target_id"),
        "campaign_identity_valid": manifest["campaign_identity"].get("valid"),
        "evidence_root": manifest.get("evidence_root"),
        "tables": {
            row["table"]: {
                "exists": row["exists"],
                "row_count": row["row_count"],
                "content_sha256": row["content_sha256"],
            }
            for row in manifest.get("tables") or ()
        },
        "execution_eligible": False,
        "promotion_eligible": False,
        "mutates_evidence": False,
        "reasons": list(reasons),
    }, indent=2, sort_keys=True))
    if valid:
        print("HIVENANCE_FULL_ORGANISM_PHASE0_LOCKED")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
