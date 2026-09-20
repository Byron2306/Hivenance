"""Executable Phase-12 middle-layer and control masks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .historical_mask_application import (
    HistoricalReplayConfig,
    apply_mask_to_replay_config,
)
from .historical_mask_engine import (
    HistoricalMaskPlan,
)


EXECUTABLE_MIDDLE_MASKS = {
    "FULL_HIVE",
    "NO_LONG_HORIZON_LATTICE",
    "NO_CEX_ORACLE",
    "NO_COIN_SELECTOR",
    "NO_REGIME",
    "NO_WORKERS",
    "NO_CRYSTALS",
    "SIMPLE_MOMENTUM",
    "SIMPLE_REVERSION",
    "DETERMINISTIC_RANDOM",
    "NO_TRADE",
}


def _digest(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class HistoricalMiddleReplayState:
    mask_id: str

    context: Mapping[str, Any]

    model_substitution: str | None
    force_no_trade: bool

    disabled_organs: tuple[str, ...]

    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def prepare_middle_replay(
    *,
    mask: HistoricalMaskPlan,
    context: Mapping[str, Any],
) -> HistoricalMiddleReplayState:
    if mask.mask_id not in (
        EXECUTABLE_MIDDLE_MASKS
    ):
        raise ValueError(
            "historical_mask_not_executable_on_middle_replay:"
            + mask.mask_id
        )

    config = apply_mask_to_replay_config(
        base=HistoricalReplayConfig(),
        mask=mask,
    )

    ctx = dict(context)

    disabled = set(
        config.disabled_organs
    )

    if "long_horizon_lattice" in disabled:
        ctx["long_horizon_lattice"] = None

    if "cex_multi_horizon_oracle" in disabled:
        ctx["cex_oracle"] = None

    if "coin_selector" in disabled:
        ctx["coin_selector"] = None

    if "regime_oracle" in disabled:
        ctx["regime"] = None

    if (
        "workers" in disabled
        or "worker_coalition" in disabled
    ):
        ctx["worker_proposals"] = ()
        ctx["worker_coalition"] = None

    if "crystals" in disabled:
        ctx["positive_crystals"] = ()
        ctx["negative_crystals"] = ()

    return HistoricalMiddleReplayState(
        mask_id=mask.mask_id,
        context=ctx,
        model_substitution=(
            config.model_substitution
        ),
        force_no_trade=(
            config.force_no_trade
        ),
        disabled_organs=tuple(
            sorted(disabled)
        ),
        execution_eligible=False,
        promotion_eligible=False,
    )


def deterministic_control_direction(
    *,
    model_substitution: str,
    world_state_hash: str,
) -> str:
    """Deterministic research control, not a learned market model."""

    model = str(
        model_substitution
    ).upper()

    if model not in {
        "SIMPLE_MOMENTUM",
        "SIMPLE_REVERSION",
        "DETERMINISTIC_RANDOM",
    }:
        raise ValueError(
            "unknown_historical_control_model"
        )

    if model == "DETERMINISTIC_RANDOM":
        value = int(
            _digest(
                {
                    "model": model,
                    "world_state_hash":
                        world_state_hash,
                }
            ).split(":", 1)[1][:16],
            16,
        )

        return (
            "UP"
            if value % 2 == 0
            else "DOWN"
        )

    raise ValueError(
        "control_model_requires_market_context:"
        + model
    )


def simple_control_direction(
    *,
    model_substitution: str,
    context: Mapping[str, Any],
    world_state_hash: str,
) -> str:
    model = str(
        model_substitution
    ).upper()

    if model == "DETERMINISTIC_RANDOM":
        return deterministic_control_direction(
            model_substitution=model,
            world_state_hash=(
                world_state_hash
            ),
        )

    returns = context.get(
        "control_returns"
    )

    if not isinstance(
        returns,
        (tuple, list),
    ) or not returns:
        return "ABSTAIN"

    xs = [
        float(x)
        for x in returns
    ]

    signal = sum(xs)

    if signal == 0.0:
        return "ABSTAIN"

    if model == "SIMPLE_MOMENTUM":
        return (
            "UP"
            if signal > 0.0
            else "DOWN"
        )

    if model == "SIMPLE_REVERSION":
        return (
            "DOWN"
            if signal > 0.0
            else "UP"
        )

    raise ValueError(
        "unknown_historical_control_model"
    )
