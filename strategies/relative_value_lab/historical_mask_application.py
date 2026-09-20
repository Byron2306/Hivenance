"""Apply canonical Phase-12 mask plans to historical replay configuration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .historical_mask_engine import (
    HistoricalMaskPlan,
)


@dataclass(frozen=True)
class HistoricalReplayConfig:
    disabled_organs: tuple[str, ...] = ()
    disabled_channels: tuple[str, ...] = ()
    disabled_evidence_families: tuple[str, ...] = ()

    model_substitution: str | None = None
    force_no_trade: bool = False

    historical_only: bool = True
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def apply_mask_to_replay_config(
    *,
    base: HistoricalReplayConfig,
    mask: HistoricalMaskPlan,
) -> HistoricalReplayConfig:

    if not base.historical_only:
        raise ValueError(
            "phase12_mask_requires_historical_replay"
        )

    return HistoricalReplayConfig(
        disabled_organs=tuple(
            sorted(
                set(
                    base.disabled_organs
                )
                | set(
                    mask.disabled_organs
                )
            )
        ),
        disabled_channels=tuple(
            sorted(
                set(
                    base.disabled_channels
                )
                | set(
                    mask.disabled_channels
                )
            )
        ),
        disabled_evidence_families=tuple(
            sorted(
                set(
                    base.disabled_evidence_families
                )
                | set(
                    mask.disabled_evidence_families
                )
            )
        ),
        model_substitution=(
            mask.model_substitution
            if mask.model_substitution
            is not None
            else base.model_substitution
        ),
        force_no_trade=bool(
            base.force_no_trade
            or mask.force_no_trade
        ),
        historical_only=True,
        execution_eligible=False,
        promotion_eligible=False,
    )


def filter_evidence_families(
    evidence: Sequence[Any],
    *,
    disabled_families:
        Sequence[str],
) -> tuple[Any, ...]:
    disabled = {
        str(x).upper()
        for x in disabled_families
    }

    out = []

    for item in evidence:
        if hasattr(item, "family"):
            family = str(
                item.family
            ).upper()

        elif isinstance(
            item,
            Mapping,
        ):
            family = str(
                item.get(
                    "family",
                    "",
                )
            ).upper()

        else:
            family = ""

        if family in disabled:
            continue

        out.append(item)

    return tuple(out)
