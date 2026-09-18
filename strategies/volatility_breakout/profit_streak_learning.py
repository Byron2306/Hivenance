from __future__ import annotations

from collections import defaultdict
from statistics import mean, median
from typing import Any, Iterable, Mapping


class ProfitStreakLearningLayer:
    """Summarise completed streak receipts into inspectable streak families.

    Research-only. The layer produces evidence summaries and has no order,
    promotion, capital-stage, or model-authority side effects.
    """

    authority = "research_summary_only_no_execution_authority"

    def __init__(self, *, family_fields: tuple[str, ...] = ("symbol", "direction", "model_id", "regime")) -> None:
        self.family_fields = family_fields

    @staticmethod
    def _context(receipt: Mapping[str, Any]) -> dict[str, Any]:
        context = {}
        for key in ("context_start", "context_peak", "context_end"):
            value = receipt.get(key) or {}
            if isinstance(value, Mapping):
                for field, item in value.items():
                    context.setdefault(str(field), item)
        return context

    def family_key(self, receipt: Mapping[str, Any]) -> tuple[str, ...]:
        context = self._context(receipt)
        return tuple(str(context.get(field, "unknown")) for field in self.family_fields)

    def summarise(self, receipts: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        families: dict[tuple[str, ...], list[Mapping[str, Any]]] = defaultdict(list)
        all_receipts = list(receipts)
        for receipt in all_receipts:
            families[self.family_key(receipt)].append(receipt)

        summaries = []
        for key, items in families.items():
            nets = [float(item.get("net_advance_usd") or 0.0) for item in items]
            durations = [float(item.get("duration_sec") or 0.0) for item in items]
            retracements = [float(item.get("max_retracement_usd") or 0.0) for item in items]
            costs = [float(item.get("cost_usd") or 0.0) for item in items]
            velocities = [float(item.get("profit_velocity_usd_per_sec") or 0.0) for item in items]
            profitable = [value > 0.0 for value in nets]
            contexts = [self._context(item) for item in items]

            summaries.append({
                "family": dict(zip(self.family_fields, key)),
                "samples": len(items),
                "profitable_samples": sum(profitable),
                "profitable_rate": sum(profitable) / len(items) if items else 0.0,
                "total_net_advance_usd": sum(nets),
                "mean_net_advance_usd": mean(nets) if nets else 0.0,
                "median_net_advance_usd": median(nets) if nets else 0.0,
                "mean_duration_sec": mean(durations) if durations else 0.0,
                "median_duration_sec": median(durations) if durations else 0.0,
                "mean_max_retracement_usd": mean(retracements) if retracements else 0.0,
                "mean_cost_usd": mean(costs) if costs else 0.0,
                "mean_profit_velocity_usd_per_sec": mean(velocities) if velocities else 0.0,
                "observed_context_fields": sorted({field for context in contexts for field in context}),
            })

        summaries.sort(
            key=lambda row: (
                float(row["total_net_advance_usd"]),
                float(row["profitable_rate"]),
                int(row["samples"]),
            ),
            reverse=True,
        )
        return {
            "schema": "hivenance_profit_streak_learning_report_v1",
            "authority": self.authority,
            "family_fields": list(self.family_fields),
            "total_streaks": len(all_receipts),
            "families": summaries,
        }
