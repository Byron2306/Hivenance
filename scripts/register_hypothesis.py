#!/usr/bin/env python3
"""CLI to pre-register a new trading hypothesis before any data collection.

Usage:
    python scripts/register_hypothesis.py --spec path/to/spec.json [--registry-dir data/hypothesis_registry]

The spec file (JSON) must contain: hypothesis_id, title, description,
symbols (list), directions (list), entry_rule_summary, exit_rule_summary,
predicted_edge_bps, predicted_edge_rationale, registered_by.

Registration is immutable: re-running with the same hypothesis_id fails
on purpose. This is a deliberate friction point -- it forces a genuinely
new hypothesis_id (and therefore a fresh, honest specification) any time
the design changes, instead of allowing a spec to be quietly edited after
its author has already seen results.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from strategies.volatility_breakout.hypothesis_registry import register_hypothesis  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path, help="Path to the hypothesis spec JSON file")
    parser.add_argument(
        "--registry-dir",
        type=Path,
        default=ROOT / "data" / "hypothesis_registry",
        help="Directory to store pre-registered hypothesis records",
    )
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text())
    required = [
        "hypothesis_id", "title", "description", "symbols", "directions",
        "entry_rule_summary", "exit_rule_summary", "predicted_edge_bps",
        "predicted_edge_rationale", "registered_by",
    ]
    missing = [key for key in required if key not in spec]
    if missing:
        print(f"spec file is missing required fields: {missing}", file=sys.stderr)
        return 2

    try:
        record = register_hypothesis(
            registry_dir=args.registry_dir,
            hypothesis_id=str(spec["hypothesis_id"]),
            title=str(spec["title"]),
            description=str(spec["description"]),
            symbols=tuple(spec["symbols"]),
            directions=tuple(spec["directions"]),
            entry_rule_summary=str(spec["entry_rule_summary"]),
            exit_rule_summary=str(spec["exit_rule_summary"]),
            predicted_edge_bps=float(spec["predicted_edge_bps"]),
            predicted_edge_rationale=str(spec["predicted_edge_rationale"]),
            registered_by=str(spec["registered_by"]),
        )
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(record.to_dict(), indent=2, sort_keys=True))
    print(f"\nRegistered '{record.hypothesis_id}' at {args.registry_dir / (record.hypothesis_id + '.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
