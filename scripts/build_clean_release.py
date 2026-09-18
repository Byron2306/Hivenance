#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXCLUDED_DIR_NAMES = {
    ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache", "__pycache__",
    "node_modules", "dist", ".venv", ".venv-build", ".venv-phase1", ".idea", ".vscode",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".db", ".sqlite", ".sqlite3", ".log", ".zip"}
EXCLUDED_FILE_NAMES = {
    "CURRENT_TRUTH.json", "TEST_CURRENT_TRUTH.json", "OFFLINE_CURRENT_TRUTH.json",
}


def include(path: Path, output: Path) -> bool:
    try:
        path.relative_to(output.parent)
    except ValueError:
        pass
    if path.resolve() == output.resolve():
        return False
    if any(part in EXCLUDED_DIR_NAMES or part.startswith(".venv-") for part in path.parts):
        return False
    if path.name in EXCLUDED_FILE_NAMES:
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    return path.is_file()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a lean Hivenance Phoenix source release")
    parser.add_argument("--output", type=Path, default=ROOT.parent / "Hivenance-Phoenix-clean.zip")
    parser.add_argument("--prefix", default="Hivenance-Phoenix")
    args = parser.parse_args()

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(path for path in ROOT.rglob("*") if include(path, output))
    manifest_files = []

    compression = zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(output, "w", compression=compression, compresslevel=9) as archive:
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            data = path.read_bytes()
            info = zipfile.ZipInfo.from_file(path, arcname=f"{args.prefix}/{rel}")
            info.create_system = 3
            info.external_attr = (stat.S_IMODE(path.stat().st_mode) & 0xFFFF) << 16
            archive.writestr(info, data, compress_type=compression, compresslevel=9)
            manifest_files.append({
                "path": rel,
                "size_bytes": len(data),
                "sha256": sha256_bytes(data),
            })
        manifest = {
            "schema": "hivenance_clean_release_manifest_v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "prefix": args.prefix,
            "file_count": len(manifest_files),
            "uncompressed_bytes": sum(item["size_bytes"] for item in manifest_files),
            "excluded": {
                "directories": sorted(EXCLUDED_DIR_NAMES),
                "suffixes": sorted(EXCLUDED_SUFFIXES),
                "notes": "Databases, logs, virtual environments, node_modules, caches, and nested ZIPs are intentionally excluded.",
            },
            "files": manifest_files,
        }
        manifest_info = zipfile.ZipInfo(f"{args.prefix}/BUILD_MANIFEST.json")
        manifest_info.create_system = 3
        manifest_info.external_attr = 0o644 << 16
        archive.writestr(
            manifest_info,
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            compress_type=compression,
            compresslevel=9,
        )

    archive_sha = hashlib.sha256(output.read_bytes()).hexdigest()
    print(json.dumps({
        "output": str(output),
        "archive_size_bytes": output.stat().st_size,
        "archive_sha256": archive_sha,
        "file_count": len(manifest_files),
        "uncompressed_bytes": manifest["uncompressed_bytes"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
