"""Canonical Phase-12 historical ablation mask specifications.

Masks operate on historical replay inputs/runtimes. They MUST NOT mutate a
previously frozen FULL_HIVE envelope into a synthetic counterfactual.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from .contracts import RELATIVE_VALUE_AUTHORITY
from .historical_causal_prosecution import (
    PAIRED_MASKS,
)


def _digest(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class HistoricalMaskPlan:
    schema: str
    mask_id: str
    plan_id: str

    disabled_organs: tuple[str, ...]
    disabled_channels: tuple[str, ...]
    disabled_evidence_families: tuple[str, ...]

    model_substitution: str | None
    force_no_trade: bool

    preserves_observed_world: bool
    requires_fresh_replay: bool

    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if self.mask_id not in PAIRED_MASKS:
            raise ValueError(
                "unknown_historical_mask"
            )

        if not self.preserves_observed_world:
            raise ValueError(
                "historical_mask_must_preserve_world"
            )

        if not self.requires_fresh_replay:
            raise ValueError(
                "historical_mask_requires_fresh_replay"
            )

        if self.execution_eligible:
            raise ValueError(
                "historical_mask_execution_forbidden"
            )

        if self.promotion_eligible:
            raise ValueError(
                "historical_mask_promotion_forbidden"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_MASK_DEFINITIONS = {
    "FULL_HIVE": {
        "organs": (),
        "channels": (),
        "families": (),
        "model": None,
        "no_trade": False,
    },

    "NO_LONG_HORIZON_LATTICE": {
        "organs": ("long_horizon_lattice",),
        "channels": (),
        "families": (),
        "model": None,
        "no_trade": False,
    },

    "NO_CEX_ORACLE": {
        "organs": ("cex_multi_horizon_oracle",),
        "channels": (),
        "families": (),
        "model": None,
        "no_trade": False,
    },

    "NO_COMPARISON": {
        "organs": ("comparison_engine",),
        "channels": (),
        "families": (),
        "model": None,
        "no_trade": False,
    },

    "NO_COIN_SELECTOR": {
        "organs": ("coin_selector",),
        "channels": (),
        "families": (),
        "model": None,
        "no_trade": False,
    },

    "NO_REGIME": {
        "organs": ("regime_oracle",),
        "channels": (),
        "families": ("REGIME",),
        "model": None,
        "no_trade": False,
    },

    "NO_FLOW": {
        "organs": (),
        "channels": (),
        "families": ("FLOW",),
        "model": None,
        "no_trade": False,
    },

    "NO_LIQUIDITY": {
        "organs": (),
        "channels": (),
        "families": ("LIQUIDITY",),
        "model": None,
        "no_trade": False,
    },

    "NO_VOLATILITY": {
        "organs": (),
        "channels": (),
        "families": ("VOLATILITY",),
        "model": None,
        "no_trade": False,
    },

    "NO_CROSS_MARKET": {
        "organs": (),
        "channels": (),
        "families": ("CROSS_MARKET",),
        "model": None,
        "no_trade": False,
    },

    "NO_TEMPORAL_PARTICIPATION": {
        "organs": ("temporal_participation_bee",),
        "channels": (),
        "families": ("TEMPORAL_PARTICIPATION",),
        "model": None,
        "no_trade": False,
    },

    "NO_WORKERS": {
        "organs": ("workers", "worker_coalition"),
        "channels": (),
        "families": (),
        "model": None,
        "no_trade": False,
    },

    "NO_CRYSTALS": {
        "organs": ("crystals",),
        "channels": (),
        "families": (),
        "model": None,
        "no_trade": False,
    },

    "NO_LEARNING": {
        "organs": ("learning_memory",),
        "channels": ("learned_challenger_receipts",),
        "families": ("LEARNING",),
        "model": None,
        "no_trade": False,
    },

    "NO_VNS_PHRASE": {
        "organs": (),
        "channels": ("vns_phrase_stream",),
        "families": (),
        "model": None,
        "no_trade": False,
    },

    "NO_TEMPORAL_TEXTURE": {
        "organs": (),
        "channels": ("temporal_texture",),
        "families": (),
        "model": None,
        "no_trade": False,
    },

    "NO_QUORUM": {
        "organs": ("polyphonic_quorum",),
        "channels": ("polyphonic_resonance",),
        "families": (),
        "model": None,
        "no_trade": False,
    },

    "NO_QUEEN": {
        "organs": ("conducting_queen",),
        "channels": (),
        "families": (),
        "model": None,
        "no_trade": False,
    },

    "NO_MYSTIQUE": {
        "organs": ("mystique",),
        "channels": ("mystique_counterfactual_challenge",),
        "families": (),
        "model": None,
        "no_trade": False,
    },

    "NO_METABOLISM": {
        "organs": ("cognitive_metabolism",),
        "channels": ("cognitive_metabolism",),
        "families": (),
        "model": None,
        "no_trade": False,
    },

    "NO_POLLEN": {
        "organs": (
            "pollen_economy",
            "pollen_reputation",
        ),
        "channels": (),
        "families": (),
        "model": None,
        "no_trade": False,
    },

    "SIMPLE_MOMENTUM": {
        "organs": (),
        "channels": (),
        "families": (),
        "model": "SIMPLE_MOMENTUM",
        "no_trade": False,
    },

    "SIMPLE_REVERSION": {
        "organs": (),
        "channels": (),
        "families": (),
        "model": "SIMPLE_REVERSION",
        "no_trade": False,
    },

    "DETERMINISTIC_RANDOM": {
        "organs": (),
        "channels": (),
        "families": (),
        "model": "DETERMINISTIC_RANDOM",
        "no_trade": False,
    },

    "NO_TRADE": {
        "organs": (),
        "channels": (),
        "families": (),
        "model": None,
        "no_trade": True,
    },
}


def historical_mask_plan(
    mask_id: str,
) -> HistoricalMaskPlan:
    mask_id = str(
        mask_id
    ).upper()

    if mask_id not in PAIRED_MASKS:
        raise ValueError(
            "unknown_historical_mask:"
            + mask_id
        )

    definition = _MASK_DEFINITIONS[
        mask_id
    ]

    body = {
        "mask_id": mask_id,
        "disabled_organs":
            sorted(
                definition["organs"]
            ),
        "disabled_channels":
            sorted(
                definition["channels"]
            ),
        "disabled_evidence_families":
            sorted(
                definition["families"]
            ),
        "model_substitution":
            definition["model"],
        "force_no_trade":
            bool(
                definition["no_trade"]
            ),
    }

    return HistoricalMaskPlan(
        schema=(
            "hivenance_historical_mask_plan_v1"
        ),
        mask_id=mask_id,
        plan_id=(
            "hmask_"
            + _digest(body).split(
                ":",
                1,
            )[1][:24]
        ),
        disabled_organs=tuple(
            body["disabled_organs"]
        ),
        disabled_channels=tuple(
            body["disabled_channels"]
        ),
        disabled_evidence_families=tuple(
            body[
                "disabled_evidence_families"
            ]
        ),
        model_substitution=(
            definition["model"]
        ),
        force_no_trade=bool(
            definition["no_trade"]
        ),
        preserves_observed_world=True,
        requires_fresh_replay=True,
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
        promotion_eligible=False,
    )


def all_historical_mask_plans(
) -> tuple[HistoricalMaskPlan, ...]:
    return tuple(
        historical_mask_plan(mask)
        for mask in PAIRED_MASKS
    )


def assert_no_envelope_mutation_counterfactual(
    *,
    source_envelope_id: str,
    requested_mask_id: str,
) -> None:
    """Explicit guard against fabricating a masked envelope post-freeze."""

    del source_envelope_id

    mask = historical_mask_plan(
        requested_mask_id
    )

    if mask.requires_fresh_replay:
        raise ValueError(
            "historical_mask_requires_runtime_replay_not_envelope_mutation"
        )
