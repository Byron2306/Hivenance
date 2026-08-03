#!/usr/bin/env python3
"""Production runner template for Hivenance Hummingbot Strategy V2 sidecars.

This script is intentionally conservative. It validates and logs the executor
config that Hivenance produced, then exits unless `--dry-run=false` is supplied.
Use it as the command template target:

  python3 scripts/hummingbot_sidecar_runner.py --config {config_path} --dry-run=false --mode docker-compose

The Docker compose mode starts the optional `hummingbot-sidecar` service defined
in `docker/docker-compose.yml`. It requires Docker CLI access from the process
that runs this script.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time


SUPPORTED_TYPES = {
    "position_executor",
    "twap_executor",
    "grid_executor",
    "dca_executor",
    "xemm_executor",
    "arbitrage_executor",
}


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    config = payload.get("config") or {}
    if config.get("type") not in SUPPORTED_TYPES:
        raise ValueError(f"unsupported executor config type: {config.get('type')}")
    if not config.get("trading_pair"):
        raise ValueError("missing trading_pair")
    return payload


def run_live_placeholder(payload: dict) -> int:
    executor_id = payload.get("executor_id")
    config = payload.get("config") or {}
    print(json.dumps({
        "event": "hummingbot_sidecar_ready",
        "executor_id": executor_id,
        "executor_type": config.get("type"),
        "trading_pair": config.get("trading_pair"),
        "ts": int(time.time() * 1000),
    }, sort_keys=True))
    print("No live Hummingbot runtime is wired in this template.", file=sys.stderr)
    return 0


def run_docker_compose(args, payload: dict) -> int:
    if not shutil.which("docker"):
        print("docker CLI is not available; cannot control Hummingbot sidecar service", file=sys.stderr)
        return 127
    env = os.environ.copy()
    env["HIVENANCE_HB_CONFIG_PATH"] = os.path.abspath(args.config)
    env["HIVENANCE_HB_EXECUTOR_ID"] = str(payload.get("executor_id") or "")
    command = ["docker", "compose", "-f", args.compose_file, "--profile", "hummingbot", "up", "-d", args.service]
    print(json.dumps({
        "event": "hummingbot_sidecar_compose_start",
        "executor_id": payload.get("executor_id"),
        "config_path": env["HIVENANCE_HB_CONFIG_PATH"],
        "command": " ".join(command),
    }, sort_keys=True))
    code = subprocess.call(command, env=env)
    if code == 0 or not shutil.which("docker-compose"):
        return code
    fallback = ["docker-compose", "-f", args.compose_file, "up", "-d", args.service]
    print(json.dumps({
        "event": "hummingbot_sidecar_compose_fallback",
        "command": " ".join(fallback),
        "executor_id": payload.get("executor_id"),
    }, sort_keys=True))
    return subprocess.call(fallback, env=env)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=os.getenv("HIVENANCE_HB_CONFIG_PATH", ""))
    parser.add_argument("--dry-run", default="true")
    parser.add_argument("--mode", choices=["validate", "process", "docker-compose"], default="validate")
    parser.add_argument("--compose-file", default="docker/docker-compose.yml")
    parser.add_argument("--service", default="hummingbot-sidecar")
    args = parser.parse_args()
    if not args.config:
        print("missing --config or HIVENANCE_HB_CONFIG_PATH", file=sys.stderr)
        return 2
    payload = load_config(args.config)
    print(json.dumps({
        "event": "hivenance_hummingbot_config_loaded",
        "executor_id": payload.get("executor_id"),
        "config_path": args.config,
        "dry_run": str(args.dry_run).lower() != "false",
        "mode": args.mode,
    }, sort_keys=True))
    if str(args.dry_run).lower() != "false" or args.mode == "validate":
        return 0
    if args.mode == "docker-compose":
        return run_docker_compose(args, payload)
    return run_live_placeholder(payload)


if __name__ == "__main__":
    raise SystemExit(main())
