from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .world_graph import QueenView, WorldGraphNode


CHANNEL_STATES = {
    "PRESENT",
    "ABSENT_DATA",
    "DISABLED_BY_MASK",
    "NOT_APPLICABLE",
    "ERROR",
}

REQUIRED_CHANNELS = (
    "VNS_SENSORY_PULSES",
    "VNS_SCORE_STREAM",
    "TEMPORAL_TEXTURE",
    "EDGE_CHORUS",
    "MOTIF_NOTES",
    "MOTIF_ACCUMULATOR",
    "POLYPHONIC_ENTRAINMENT",
    "MARKET_HUNTING",
    "COLONY_CORRELATION",
    "CAUSAL_CASCADE",
    "HIVE_PULSE",
    "POLYPHONIC_RESONANCE",
    "HARMONIC_CONTEXT",
    "MYSTIQUE_CHALLENGE",
    "COGNITIVE_METABOLISM",
    "LEARNED_CHALLENGER",
    "GOVERNANCE_EPOCH",
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
class QueenInputChannel:
    name: str
    state: str
    source_node_ids: tuple[str, ...]
    source_receipt_ids: tuple[str, ...]
    evidence_roots: tuple[str, ...]
    payload: Mapping[str, Any]
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.name not in REQUIRED_CHANNELS:
            raise ValueError(f"queen_input_channel_unknown:{self.name}")
        if self.state not in CHANNEL_STATES:
            raise ValueError(f"queen_input_channel_state_invalid:{self.state}")
        if self.state == "PRESENT":
            if not self.source_node_ids and not self.source_receipt_ids:
                raise ValueError(
                    f"queen_input_present_without_source:{self.name}"
                )
        if any(
            not str(root).startswith("sha256:")
            for root in self.evidence_roots
        ):
            raise ValueError(
                f"queen_input_channel_evidence_root_invalid:{self.name}"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QueenInputAssembly:
    schema: str
    assembly_id: str
    world_state_id: str
    world_state_hash: str
    created_at_ms: int
    channels: tuple[QueenInputChannel, ...]
    present_channels: tuple[str, ...]
    absent_channels: tuple[str, ...]
    disabled_channels: tuple[str, ...]
    error_channels: tuple[str, ...]
    completeness_ratio: float
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        names = tuple(channel.name for channel in self.channels)

        if len(names) != len(set(names)):
            raise ValueError("queen_input_duplicate_channel")

        if set(names) != set(REQUIRED_CHANNELS):
            raise ValueError("queen_input_required_channel_set_incomplete")

        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("queen_input_authority_escalation_forbidden")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["channels"] = tuple(
            channel.to_dict()
            for channel in self.channels
        )
        return payload


def channel(
    *,
    name: str,
    state: str,
    source_nodes: Sequence[WorldGraphNode] = (),
    source_receipt_ids: Sequence[str] = (),
    payload: Mapping[str, Any] | None = None,
    reason: str | None = None,
) -> QueenInputChannel:
    roots = {
        root
        for node in source_nodes
        for root in node.evidence_roots
    }

    return QueenInputChannel(
        name=str(name),
        state=str(state),
        source_node_ids=tuple(
            sorted(node.node_id for node in source_nodes)
        ),
        source_receipt_ids=tuple(
            sorted(str(x) for x in source_receipt_ids)
        ),
        evidence_roots=tuple(sorted(roots)),
        payload=dict(payload or {}),
        reason=reason,
    )


def assemble_queen_inputs(
    *,
    queen_view: QueenView,
    created_at_ms: int,
    channels: Mapping[str, QueenInputChannel],
) -> QueenInputAssembly:
    completed: list[QueenInputChannel] = []

    for name in REQUIRED_CHANNELS:
        item = channels.get(name)

        if item is None:
            item = channel(
                name=name,
                state="ABSENT_DATA",
                reason="channel_not_supplied",
            )

        if item.name != name:
            raise ValueError(
                f"queen_input_channel_name_mismatch:{name}:{item.name}"
            )

        completed.append(item)

    present = tuple(
        item.name for item in completed
        if item.state == "PRESENT"
    )

    absent = tuple(
        item.name for item in completed
        if item.state in {"ABSENT_DATA", "NOT_APPLICABLE"}
    )

    disabled = tuple(
        item.name for item in completed
        if item.state == "DISABLED_BY_MASK"
    )

    errors = tuple(
        item.name for item in completed
        if item.state == "ERROR"
    )

    completeness = (
        len(present) / len(REQUIRED_CHANNELS)
        if REQUIRED_CHANNELS
        else 1.0
    )

    body = {
        "world_state_id": queen_view.world_state_id,
        "world_state_hash": queen_view.world_state_hash,
        "created_at_ms": int(created_at_ms),
        "channels": [
            item.to_dict()
            for item in completed
        ],
    }

    digest = _digest(body)

    return QueenInputAssembly(
        schema="hivenance_queen_input_assembly_v1",
        assembly_id="qia_" + digest.split(":", 1)[1][:24],
        world_state_id=queen_view.world_state_id,
        world_state_hash=queen_view.world_state_hash,
        created_at_ms=int(created_at_ms),
        channels=tuple(completed),
        present_channels=present,
        absent_channels=absent,
        disabled_channels=disabled,
        error_channels=errors,
        completeness_ratio=round(completeness, 6),
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
        promotion_eligible=False,
    )
