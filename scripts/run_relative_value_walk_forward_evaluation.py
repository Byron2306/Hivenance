#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategies.relative_value_lab.dataset import RelativeValueExample
from strategies.relative_value_lab.evaluation import RelativeValueWalkForwardEvaluator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phoenix relative-value walk-forward evaluation")
    parser.add_argument("--dataset", type=Path, default=Path("data/relative_value_forecast_dataset.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/relative_value_walk_forward_report.json"))
    parser.add_argument("--predictions-output", type=Path, default=Path("data/relative_value_walk_forward_predictions.jsonl"))
    parser.add_argument("--minimum-train-samples", type=int, default=80)
    parser.add_argument("--ridge-alpha", type=float, default=8.0)
    parser.add_argument("--ridge-refit-sec", type=float, default=60.0)
    parser.add_argument("--horizons", nargs="+", type=int, default=[10, 30, 60, 120])
    return parser.parse_args()


def load_examples(path: Path) -> list[RelativeValueExample]:
    examples: list[RelativeValueExample] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        examples.append(RelativeValueExample(**payload))
    return examples


def main() -> int:
    args = parse_args()
    examples = load_examples(args.dataset)
    def progress(event, payload):
        if event == "horizon_start":
            print(f"evaluating {payload['horizon_seconds']}s horizon...")
        elif event == "horizon_complete":
            print(
                f"completed {payload['horizon_seconds']}s horizon "
                f"predictions={payload['predictions']}"
            )

    evaluator = RelativeValueWalkForwardEvaluator(
        horizons_seconds=args.horizons,
        ridge_alpha=args.ridge_alpha,
        minimum_train_samples=args.minimum_train_samples,
        ridge_refit_interval_ms=int(max(0.0, args.ridge_refit_sec) * 1000.0),
        progress_callback=progress,
    )
    predictions, metrics = evaluator.evaluate(examples)

    args.predictions_output.parent.mkdir(parents=True, exist_ok=True)
    with args.predictions_output.open("w", encoding="utf-8") as handle:
        for row in predictions:
            handle.write(json.dumps(row.to_dict(), sort_keys=True, ensure_ascii=True) + "\n")

    report = {
        "schema": "hivenance_relative_value_walk_forward_report_v1",
        "dataset": str(args.dataset),
        "examples": len(examples),
        "predictions": len(predictions),
        "horizons_seconds": list(evaluator.horizons_seconds),
        "ridge_alpha": args.ridge_alpha,
        "minimum_train_samples": args.minimum_train_samples,
        "ridge_refit_sec": args.ridge_refit_sec,
        "metrics": [metric.to_dict() for metric in metrics],
        "authority": "research_evidence_only_no_execution_or_promotion_authority",
        "execution_authority": "none",
        "orders_submitted": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    print("Phoenix Relative-Value Walk-Forward Evaluation")
    print(f"examples={len(examples)} predictions={len(predictions)}")
    print()
    print("Model metrics")
    print("-------------")
    for metric in metrics:
        def fmt(value):
            return "n/a" if value is None else f"{value:.4f}"
        print(
            f"{metric.horizon_seconds:>4d}s {metric.model_id:40s} "
            f"n={metric.samples:5d} sign={fmt(metric.sign_accuracy):>8s} "
            f"mae={fmt(metric.mae_bps):>8s} "
            f"gross={fmt(metric.mean_directional_gross_bps):>8s} "
            f"after_spread={fmt(metric.mean_directional_after_spread_proxy_bps):>8s}"
        )
    print()
    print(f"report={args.output}")
    print("PRIVATE ORDERS: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())