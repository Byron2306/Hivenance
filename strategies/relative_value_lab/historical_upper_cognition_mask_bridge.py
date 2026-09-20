"""Executable Phase-12 upper-cognition masks.

Masks are applied before upper cognition executes. No frozen Queen receipt or
HypothesisEnvelope is edited to manufacture a counterfactual.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .historical_mask_application import (
    HistoricalReplayConfig,
    apply_mask_to_replay_config,
)
from .historical_mask_engine import (
    HistoricalMaskPlan,
)


EXECUTABLE_UPPER_MASKS = {
    "FULL_HIVE",
    "NO_VNS_PHRASE",
    "NO_TEMPORAL_TEXTURE",
    "NO_QUORUM",
    "NO_QUEEN",
    "NO_MYSTIQUE",
    "NO_METABOLISM",
    "NO_POLLEN",
}


@dataclass(frozen=True)
class UpperCognitionReplayState:
    mask_id: str

    invoke_queen: bool
    quorum_enabled: bool
    pollen_enabled: bool

    queen_kwargs: Mapping[str, Any]

    removed_channels: tuple[str, ...]
    disabled_organs: tuple[str, ...]

    execution_eligible: bool = False
    promotion_eligible: bool = False


@dataclass(frozen=True)
class UpperCognitionReplayResult:
    mask_id: str
    queen_invoked: bool
    queen_receipt: Any | None

    quorum_enabled: bool
    pollen_enabled: bool

    removed_channels: tuple[str, ...]
    disabled_organs: tuple[str, ...]

    execution_eligible: bool = False
    promotion_eligible: bool = False


def prepare_upper_cognition_replay(
    *,
    mask: HistoricalMaskPlan,
    queen_kwargs: Mapping[str, Any],
) -> UpperCognitionReplayState:
    if mask.mask_id not in EXECUTABLE_UPPER_MASKS:
        raise ValueError(
            "historical_mask_not_executable_on_upper_cognition:"
            + mask.mask_id
        )

    config = apply_mask_to_replay_config(
        base=HistoricalReplayConfig(),
        mask=mask,
    )

    kwargs = dict(queen_kwargs)

    channels = {
        str(x)
        for x in config.disabled_channels
    }

    organs = {
        str(x)
        for x in config.disabled_organs
    }

    if "vns_phrase_stream" in channels:
        kwargs["vns_phrase"] = None

    if "temporal_texture" in channels:
        kwargs["temporal_texture"] = None

    if (
        "polyphonic_resonance"
        in channels
        or "polyphonic_quorum"
        in organs
    ):
        kwargs["polyphonic_resonance"] = None

    if (
        "mystique_counterfactual_challenge"
        in channels
        or "mystique" in organs
    ):
        kwargs["mystique"] = None

    if (
        "cognitive_metabolism"
        in channels
        or "cognitive_metabolism"
        in organs
    ):
        kwargs["metabolism"] = None

    invoke_queen = (
        "conducting_queen"
        not in organs
    )

    quorum_enabled = (
        "polyphonic_quorum"
        not in organs
    )

    pollen_enabled = not bool(
        {
            "pollen_economy",
            "pollen_reputation",
        }
        & organs
    )

    return UpperCognitionReplayState(
        mask_id=mask.mask_id,
        invoke_queen=invoke_queen,
        quorum_enabled=quorum_enabled,
        pollen_enabled=pollen_enabled,
        queen_kwargs=kwargs,
        removed_channels=tuple(
            sorted(channels)
        ),
        disabled_organs=tuple(
            sorted(organs)
        ),
        execution_eligible=False,
        promotion_eligible=False,
    )


def run_upper_cognition_replay(
    *,
    mask: HistoricalMaskPlan,
    queen_kwargs: Mapping[str, Any],
    queen_runner: Callable[..., Any],
) -> UpperCognitionReplayResult:
    state = prepare_upper_cognition_replay(
        mask=mask,
        queen_kwargs=queen_kwargs,
    )

    receipt = None

    if state.invoke_queen:
        receipt = queen_runner(
            **dict(state.queen_kwargs)
        )

    return UpperCognitionReplayResult(
        mask_id=state.mask_id,
        queen_invoked=state.invoke_queen,
        queen_receipt=receipt,
        quorum_enabled=state.quorum_enabled,
        pollen_enabled=state.pollen_enabled,
        removed_channels=(
            state.removed_channels
        ),
        disabled_organs=(
            state.disabled_organs
        ),
        execution_eligible=False,
        promotion_eligible=False,
    )
