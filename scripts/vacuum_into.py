#!/usr/bin/env python3
"""
Safe, non-destructive compaction of data/swarm_data.db via VACUUM INTO.

WHY VACUUM INTO instead of plain VACUUM:
  - Plain `VACUUM` rewrites the DB file IN PLACE and needs ~2x the current
    file size in free disk space, plus an EXCLUSIVE lock (fails if any other
    connection is writing). With 5+ live background workers writing to this
    DB, an in-place VACUUM is likely to fail or stall.
  - `VACUUM INTO 'newfile.db'` writes a fully compacted copy to a NEW file
    without needing to lock/rewrite the original. It still needs enough free
    space for the new (usually smaller) file, but it's far safer:
      * the original DB is untouched until you explicitly swap it in
      * if it fails partway, you just delete the incomplete new file
      * you can diff row counts between old and new before cutting over

PRECONDITIONS TO CHECK BEFORE RUNNING THIS:
  1. Pause (or confirm quiescence of) the background writers:
       - scripts/run_sovereign_pool_worker.py (both instances)
       - scripts/run_research_acceptance_pipeline.py (+ its restart loop)
       - scripts/run_phase5_shadow_flight.py
       - tmux session `hivenance-phase1` (scripts/run_phase1_observer.py)
     VACUUM INTO takes a read lock for the duration of the copy; a long-held
     write transaction from any of these could still block or slow it down.
  2. Confirm free disk space > current DB size (currently ~19.6 GiB) at the
     destination path. Point OUTPUT_PATH at a location with enough headroom.
  3. This script NEVER deletes or modifies the original swarm_data.db. The
     swap-in step (renaming the compacted file over the original) is a
     separate, manual, explicit step -- do that only after verifying the
     new file's row counts/integrity match.

USAGE:
    python scripts/vacuum_into.py                 # dry-run: just checks space
    python scripts/vacuum_into.py --run            # actually performs VACUUM INTO
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time

DB_PATH = "data/swarm_data.db"
OUTPUT_PATH = "data/swarm_data.compacted.db"


def check_preconditions() -> bool:
    if not os.path.exists(DB_PATH):
        print(f"ERROR: {DB_PATH} not found (run from repo root).")
        return False

    db_size = os.path.getsize(DB_PATH)
    free = shutil.disk_usage(os.path.dirname(os.path.abspath(DB_PATH))).free

    print(f"Current DB size:      {db_size / 1e9:.2f} GB")
    print(f"Free space at target:  {free / 1e9:.2f} GB")

    if os.path.exists(OUTPUT_PATH):
        print(f"ERROR: {OUTPUT_PATH} already exists. Remove or rename it first "
              f"(VACUUM INTO refuses to overwrite an existing file).")
        return False

    # VACUUM INTO only needs room for the new (typically smaller, since it
    # drops free-list pages) file, not 2x like in-place VACUUM. Require at
    # least 1.1x the current size as a safety margin.
    required = db_size * 1.1
    if free < required:
        print(f"ERROR: insufficient free space. Need ~{required / 1e9:.2f} GB, "
              f"have {free / 1e9:.2f} GB.")
        return False

    print("Preconditions OK.")
    return True


def run_vacuum_into() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA busy_timeout=10000")
    start = time.time()
    print(f"Starting VACUUM INTO '{OUTPUT_PATH}' ...")
    conn.execute("VACUUM INTO ?", (OUTPUT_PATH,))
    conn.close()
    elapsed = time.time() - start
    new_size = os.path.getsize(OUTPUT_PATH)
    old_size = os.path.getsize(DB_PATH)
    print(f"Done in {elapsed:.1f}s.")
    print(f"Original: {old_size / 1e9:.2f} GB  ->  Compacted: {new_size / 1e9:.2f} GB "
          f"({(1 - new_size / old_size) * 100:.1f}% smaller)")
    print()
    print("NEXT STEPS (manual, do not automate blindly):")
    print(f"  1. Verify table/row counts match between {DB_PATH} and {OUTPUT_PATH}")
    print(f"     e.g. sqlite3 {DB_PATH} 'SELECT COUNT(*) FROM simulated_orders'")
    print(f"          sqlite3 {OUTPUT_PATH} 'SELECT COUNT(*) FROM simulated_orders'")
    print(f"  2. Stop all writers pointed at {DB_PATH}.")
    print(f"  3. mv {DB_PATH} {DB_PATH}.bak-$(date +%s)")
    print(f"  4. mv {OUTPUT_PATH} {DB_PATH}")
    print(f"  5. Restart the writers, confirm they open the new file cleanly.")
    print(f"  6. Only delete the .bak file once you've confirmed everything works.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true",
                         help="Actually perform VACUUM INTO (default: dry-run precondition check only)")
    args = parser.parse_args()

    if not check_preconditions():
        return 1

    if not args.run:
        print()
        print("Dry-run only. Re-run with --run to actually perform VACUUM INTO.")
        return 0

    run_vacuum_into()
    return 0


if __name__ == "__main__":
    sys.exit(main())
