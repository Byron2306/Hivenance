from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .queen_input_assembly import QueenInputAssembly


EXTENSION_CHANNELS = (
    "STATISTICAL_SYNTHESIS",
    "REGIME_CONTEXT",
    "EXTERNAL_STATISTICS",
    "CALIBRATION_CONTEXT",
    "RESEARCH_CONTEXT",
)


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class QueenExtensionChannel:
    name: str
    state: str
    evidence_roots: tuple[str, ...]
    payload: Mapping[str, Any]
    reason: str | None = None
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if self.name not in EXTENSION_CHANNELS:
            raise ValueError("queen_input_v2_unknown_extension_channel")
        if self.state not in {"PRESENT", "ABSENT_DATA", "DISABLED_BY_MASK", "ERROR"}:
            raise ValueError("queen_input_v2_invalid_channel_state")
        if any(not str(root).startswith("sha256:") for root in self.evidence_roots):
            raise ValueError("queen_input_v2_invalid_evidence_root")
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("queen_input_v2_authority_escalation_forbidden")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["payload"] = dict(self.payload)
        return payload


@dataclass(frozen=True)
class QueenInputAssemblyV2:
    schema: str
    assembly_id: str
    base_v1_assembly_id: str
    world_state_id: str
    world_state_hash: str
    created_at_ms: int
    base_channels: int
    extension_channels: tuple[QueenExtensionChannel, ...]
    present_extensions: tuple[str, ...]
    absent_extensions: tuple[str, ...]
    disabled_extensions: tuple[str, ...]
    error_extensions: tuple[str, ...]
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        names = tuple(x.name for x in self.extension_channels)
        if len(names) != len(set(names)):
            raise ValueError("queen_input_v2_duplicate_extension_channel")
        if set(names) != set(EXTENSION_CHANNELS):
            raise ValueError("queen_input_v2_extension_set_incomplete")
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("queen_input_v2_authority_escalation_forbidden")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["extension_channels"] = tuple(x.to_dict() for x in self.extension_channels)
        return payload


def extension_channel(
    *,
    name: str,
    state: str,
    payload: Mapping[str, Any] | None = None,
    evidence_roots: Sequence[str] = (),
    reason: str | None = None,
) -> QueenExtensionChannel:
    return QueenExtensionChannel(
        name=str(name),
        state=str(state),
        evidence_roots=tuple(sorted(set(map(str, evidence_roots)))),
        payload=dict(payload or {}),
        reason=reason,
    )


def assemble_queen_inputs_v2(
    *,
    base: QueenInputAssembly,
    extensions: Mapping[str, QueenExtensionChannel],
    created_at_ms: int,
) -> QueenInputAssemblyV2:
    completed: list[QueenExtensionChannel] = []
    for name in EXTENSION_CHANNELS:
        item = extensions.get(name)
        if item is None:
            item = extension_channel(
                name=name,
                state="ABSENT_DATA",
                reason="extension_channel_not_supplied",
            )
        if item.name != name:
            raise ValueError("queen_input_v2_extension_name_mismatch")
        completed.append(item)

    present = tuple(x.name for x in completed if x.state == "PRESENT")
    absent = tuple(x.name for x in completed if x.state == "ABSENT_DATA")
    disabled = tuple(x.name for x in completed if x.state == "DISABLED_BY_MASK")
    errors = tuple(x.name for x in completed if x.state == "ERROR")

    body = {
        "base_v1_assembly_id": base.assembly_id,
        "world_state_id": base.world_state_id,
        "world_state_hash": base.world_state_hash,
        "created_at_ms": int(created_at_ms),
        "extensions": [x.to_dict() for x in completed],
    }

    return QueenInputAssemblyV2(
        schema="hivenance_queen_input_assembly_v2",
        assembly_id="qiav2_" + _digest(body).split(":", 1)[1][:24],
        base_v1_assembly_id=base.assembly_id,
        world_state_id=base.world_state_id,
        world_state_hash=base.world_state_hash,
        created_at_ms=int(created_at_ms),
        base_channels=len(base.channels),
        extension_channels=tuple(completed),
        present_extensions=present,
        absent_extensions=absent,
        disabled_extensions=disabled,
        error_extensions=errors,
    )
