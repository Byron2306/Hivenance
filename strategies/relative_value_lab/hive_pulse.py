from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Optional

from .contracts import RELATIVE_VALUE_AUTHORITY
from .causal_cascade import CausalCascadeReceipt


PULSE_CLASSES = {
    "SEARCH_PULSE",
    "DISCOVERY_PULSE",
    "ALARM_PULSE",
    "FREEZE_PULSE",
    "CLEAR_PULSE",
}


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class HivePulse:
    schema: str
    pulse_id: str
    pulse_class: str
    scope: str
    issued_at_ms: int
    expires_at_ms: int
    severity: float
    confidence: float
    amplitude: float
    world_state_id: str
    lineage_root: str
    evidence_root: str
    corroboration_count: int
    independent_family_count: int
    cascade_depth: int
    cascade_id: Optional[str]
    authority_effect: str
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DecayedHivePulse:
    pulse_id: str
    pulse_class: str
    effective_amplitude: float
    effective_confidence: float
    expired: bool
    authority_effect: str
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HivePulseEngine:
    """Fast colony accent with TTL and decay.

    Positive pulses alter research attention only.
    ALARM/FREEZE may reduce or freeze authority, never increase it.
    """

    version = "hivenance.hive_pulse.v1"

    @staticmethod
    def emit(
        *,
        pulse_class: str,
        scope: str,
        issued_at_ms: int,
        ttl_ms: int,
        severity: float,
        confidence: float,
        amplitude: float,
        world_state_id: str,
        lineage_root: str,
        evidence_root: str,
        corroboration_count: int = 0,
        independent_family_count: int = 0,
        cascade: CausalCascadeReceipt | None = None,
    ) -> HivePulse:
        pulse_class = str(pulse_class).upper()
        if pulse_class not in PULSE_CLASSES:
            raise ValueError("unknown_hive_pulse_class")
        if ttl_ms <= 0:
            raise ValueError("pulse_ttl_must_be_positive")
        if not str(evidence_root).startswith("sha256:"):
            raise ValueError("pulse_evidence_root_must_be_sha256_bound")

        authority_effect = (
            "REDUCE_OR_FREEZE_ONLY"
            if pulse_class in {"ALARM_PULSE", "FREEZE_PULSE"}
            else "ATTENTION_ONLY"
        )

        body = {
            "pulse_class": pulse_class,
            "scope": scope,
            "issued_at_ms": int(issued_at_ms),
            "ttl_ms": int(ttl_ms),
            "severity": round(_clamp(severity), 6),
            "confidence": round(_clamp(confidence), 6),
            "amplitude": round(_clamp(amplitude), 6),
            "world_state_id": world_state_id,
            "lineage_root": lineage_root,
            "evidence_root": evidence_root,
            "cascade_id": cascade.cascade_id if cascade else None,
        }
        return HivePulse(
            schema="hivenance_hive_pulse_v1",
            pulse_id="pulse_" + _digest(body).split(":", 1)[1][:24],
            pulse_class=pulse_class,
            scope=scope,
            issued_at_ms=int(issued_at_ms),
            expires_at_ms=int(issued_at_ms + ttl_ms),
            severity=round(_clamp(severity), 6),
            confidence=round(_clamp(confidence), 6),
            amplitude=round(_clamp(amplitude), 6),
            world_state_id=world_state_id,
            lineage_root=lineage_root,
            evidence_root=evidence_root,
            corroboration_count=max(0, int(corroboration_count)),
            independent_family_count=max(0, int(independent_family_count)),
            cascade_depth=int(cascade.depth if cascade else 0),
            cascade_id=cascade.cascade_id if cascade else None,
            authority_effect=authority_effect,
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )

    @staticmethod
    def from_cascade(
        cascade: CausalCascadeReceipt,
        *,
        pulse_class: str,
        scope: str,
        issued_at_ms: int,
        ttl_ms: int,
        lineage_root: str,
        evidence_root: str,
    ) -> HivePulse:
        severity = _clamp(
            0.45 * cascade.propagation_strength
            + 0.35 * cascade.crescendo
            + 0.20 * _clamp(cascade.depth / 4.0)
        )
        confidence = _clamp(
            0.60 * cascade.propagation_strength
            + 0.40 * _clamp(cascade.independent_family_count / 4.0)
        )
        amplitude = _clamp(
            0.55 * cascade.crescendo
            + 0.45 * cascade.propagation_strength
        )
        return HivePulseEngine.emit(
            pulse_class=pulse_class,
            scope=scope,
            issued_at_ms=issued_at_ms,
            ttl_ms=ttl_ms,
            severity=severity,
            confidence=confidence,
            amplitude=amplitude,
            world_state_id=cascade.world_state_id,
            lineage_root=lineage_root,
            evidence_root=evidence_root,
            corroboration_count=max(0, cascade.independent_evidence_roots - 1),
            independent_family_count=cascade.independent_family_count,
            cascade=cascade,
        )

    @staticmethod
    def decay(pulse: HivePulse, *, now_ms: int) -> DecayedHivePulse:
        if now_ms >= pulse.expires_at_ms:
            factor = 0.0
            expired = True
        elif now_ms <= pulse.issued_at_ms:
            factor = 1.0
            expired = False
        else:
            life = max(1, pulse.expires_at_ms - pulse.issued_at_ms)
            elapsed = now_ms - pulse.issued_at_ms
            factor = math.exp(-2.0 * elapsed / life)
            expired = False

        return DecayedHivePulse(
            pulse_id=pulse.pulse_id,
            pulse_class=pulse.pulse_class,
            effective_amplitude=round(_clamp(pulse.amplitude * factor), 6),
            effective_confidence=round(_clamp(pulse.confidence * factor), 6),
            expired=expired,
            authority_effect=pulse.authority_effect,
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )
