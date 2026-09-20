"""Executable Phase-12 masks over the existing SynthesisRuntime.

This is deliberately narrow. A mask is called executable here only when the
current runtime can isolate it without fabricating semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .edge_ecology import EdgeEcologySnapshot
from .historical_mask_engine import (
    HistoricalMaskPlan,
)
from .historical_mask_application import (
    HistoricalReplayConfig,
    apply_mask_to_replay_config,
)
from .synthesis_runtime import (
    SynthesisCycle,
    SynthesisRuntime,
)


EXECUTABLE_SYNTHESIS_MASKS = {
    "FULL_HIVE",
    "NO_COMPARISON",
    "NO_TEMPORAL_PARTICIPATION",
    "NO_LEARNING",
    "NO_FLOW",
    "NO_LIQUIDITY",
    "NO_VOLATILITY",
}


@dataclass(frozen=True)
class HistoricalMaskedSynthesisRun:
    mask_id: str
    executable: bool
    cycle: SynthesisCycle
    removed_families: tuple[str, ...]
    disabled_organs: tuple[str, ...]

    execution_eligible: bool = False
    promotion_eligible: bool = False


def _filtered_edge_snapshot(
    snapshot: EdgeEcologySnapshot | None,
    *,
    disabled_families: tuple[str, ...],
) -> EdgeEcologySnapshot | None:
    if snapshot is None:
        return None

    disabled = {
        str(x).upper()
        for x in disabled_families
    }

    voices = tuple(
        voice
        for voice in snapshot.voices
        if str(voice.family).upper()
        not in disabled
    )

    if not voices:
        return None

    return EdgeEcologySnapshot(
        timestamp_ms=int(
            snapshot.timestamp_ms
        ),
        pair_id=str(
            snapshot.pair_id
        ),
        voices=voices,
        hypothesis=str(
            snapshot.hypothesis
        ),
        authority=snapshot.authority,
        execution_eligible=False,
        promotion_eligible=False,
    )


def _filtered_edge_roots(
    roots: Mapping[
        str,
        tuple[str, ...] | list[str],
    ] | None,
    *,
    disabled_families: tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    disabled = {
        str(x).upper()
        for x in disabled_families
    }

    return {
        str(family): tuple(values)
        for family, values
        in (roots or {}).items()
        if str(family).upper()
        not in disabled
    }


def run_masked_synthesis(
    *,
    runtime: SynthesisRuntime,
    mask: HistoricalMaskPlan,
    runtime_inputs: Mapping[str, Any],
) -> HistoricalMaskedSynthesisRun:
    if mask.mask_id not in (
        EXECUTABLE_SYNTHESIS_MASKS
    ):
        raise ValueError(
            "historical_mask_not_executable_on_synthesis_runtime:"
            + mask.mask_id
        )

    config = apply_mask_to_replay_config(
        base=HistoricalReplayConfig(),
        mask=mask,
    )

    inputs = dict(
        runtime_inputs
    )

    runtime_disabled = set(
        inputs.pop(
            "disabled_organs",
            (),
        )
    )

    # Canonical Phase-12 organ IDs -> actual current SynthesisRuntime IDs.
    organ_mapping = {
        "comparison_engine":
            "comparison_engine",
        "temporal_participation_bee":
            "temporal_participation_bee",
        "learning_memory":
            "learning_memory",
    }

    for organ in config.disabled_organs:
        mapped = organ_mapping.get(
            organ
        )

        if mapped is not None:
            runtime_disabled.add(
                mapped
            )

    edge_snapshot = (
        inputs.get(
            "edge_snapshot"
        )
    )

    edge_roots = (
        inputs.get(
            "edge_roots"
        )
    )

    filtered_snapshot = (
        _filtered_edge_snapshot(
            edge_snapshot,
            disabled_families=(
                config.disabled_evidence_families
            ),
        )
    )

    filtered_roots = (
        _filtered_edge_roots(
            edge_roots,
            disabled_families=(
                config.disabled_evidence_families
            ),
        )
    )

    # If every edge voice has been removed, disable edge_ecology cleanly rather
    # than pretending an empty snapshot is a real reading.
    if (
        edge_snapshot is not None
        and filtered_snapshot is None
    ):
        runtime_disabled.add(
            "edge_ecology"
        )

    inputs["edge_snapshot"] = (
        filtered_snapshot
    )

    inputs["edge_roots"] = (
        filtered_roots
    )

    inputs["disabled_organs"] = tuple(
        sorted(
            runtime_disabled
        )
    )

    cycle = runtime.run(
        **inputs
    )

    return HistoricalMaskedSynthesisRun(
        mask_id=mask.mask_id,
        executable=True,
        cycle=cycle,
        removed_families=tuple(
            sorted(
                config.disabled_evidence_families
            )
        ),
        disabled_organs=tuple(
            sorted(
                runtime_disabled
            )
        ),
        execution_eligible=False,
        promotion_eligible=False,
    )
