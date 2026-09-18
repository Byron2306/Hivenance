#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategies.relative_value_lab.evaluation import WalkForwardPrediction
from strategies.relative_value_lab.harmonic_governance import (
    HarmonicForecastGovernance,
    group_prediction_choirs,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phoenix Harmonic Forecast Governance")
    parser.add_argument(
        "--predictions",
        type=Path,
        default=Path("data/relative_value_walk_forward_predictions.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/relative_value_harmonic_governance_report.json"),
    )
    parser.add_argument(
        "--receipts-output",
        type=Path,
        default=Path("data/relative_value_harmonic_receipts.jsonl"),
    )
    return parser.parse_args()


def load_predictions(path: Path) -> list[WalkForwardPrediction]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(WalkForwardPrediction(**json.loads(line)))
    return rows


def main() -> int:
    args = parse_args()
    predictions = load_predictions(args.predictions)
    grouped = group_prediction_choirs(predictions)
    governance = HarmonicForecastGovernance()

    receipts = []
    by_state = defaultdict(int)
    gated_by_horizon = defaultdict(list)

    for (pair_id, timestamp_ms), rows in sorted(grouped.items(), key=lambda item: (item[0][1], item[0][0])):
        receipt = governance.score(
            pair_id=pair_id,
            timestamp_ms=timestamp_ms,
            predictions=rows,
        )
        receipts.append(receipt)
        by_state[receipt.state] += 1

        if receipt.state == "RESONANT" and receipt.direction != "ABSTAIN":
            sign = 1.0 if receipt.direction == "LONG_A_SHORT_B" else -1.0
            seen = set()
            for row in rows:
                key = (row.horizon_seconds, row.realized_signed_bps)
                if key in seen:
                    continue
                seen.add(key)
                gated_by_horizon[row.horizon_seconds].append(
                    sign * float(row.realized_signed_bps)
                )

    args.receipts_output.parent.mkdir(parents=True, exist_ok=True)
    with args.receipts_output.open("w", encoding="utf-8") as handle:
        for receipt in receipts:
            handle.write(json.dumps(receipt.to_dict(), sort_keys=True) + "\n")

    gated = {}
    for horizon, values in sorted(gated_by_horizon.items()):
        gated[str(horizon)] = {
            "samples": len(values),
            "mean_directional_gross_bps": statistics.fmean(values) if values else None,
            "median_directional_gross_bps": statistics.median(values) if values else None,
            "positive_rate": (
                sum(1 for value in values if value > 0.0) / len(values)
                if values else None
            ),
        }

    report = {
        "schema": "hivenance_harmonic_forecast_governance_report_v1",
        "predictions": len(predictions),
        "choirs": len(receipts),
        "states": dict(sorted(by_state.items())),
        "resonant_gated_outcomes": gated,
        "authority": "research_evidence_only_no_execution_or_promotion_authority",
        "execution_authority": "none",
        "orders_submitted": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("Phoenix Harmonic Forecast Governance")
    print(f"predictions={len(predictions)} choirs={len(receipts)}")
    print("states=" + json.dumps(dict(sorted(by_state.items())), sort_keys=True))
    print()
    print("Resonant-gated directional gross")
    print("--------------------------------")
    for horizon, row in sorted(gated.items(), key=lambda item: int(item[0])):
        mean = row["mean_directional_gross_bps"]
        pos = row["positive_rate"]
        print(
            f"{int(horizon):>4d}s n={row['samples']:5d} "
            f"mean_gross={'n/a' if mean is None else f'{mean:.4f}'} "
            f"positive={'n/a' if pos is None else f'{pos:.4f}'}"
        )
    print()
    print(f"report={args.output}")
    print(f"receipts={args.receipts_output}")
    print("PRIVATE ORDERS: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
