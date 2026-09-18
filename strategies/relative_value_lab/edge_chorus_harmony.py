from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Mapping, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY


def _clamp(v: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(v)))


def _ratio(a: float, b: float) -> float:
    return 1.0 if b <= 0 else a / b


@dataclass(frozen=True)
class EdgeChorusSpec:
    edge_type: str
    required_participants: tuple[str, ...] = ()
    optional_participants: tuple[str, ...] = ()
    expected_sequence: tuple[str, ...] = ()
    timing_tolerances_ms: Mapping[str, tuple[int, int]] = field(default_factory=dict)
    required_audit_events: tuple[str, ...] = ()
    required_state_events: tuple[str, ...] = ()
    required_companions: tuple[str, ...] = ()
    settlement_timeout_ms: int | None = None


@dataclass(frozen=True)
class EdgeChorusObservation:
    action_id: str
    edge_type: str
    observed_participants: tuple[str, ...] = ()
    observed_sequence: tuple[str, ...] = ()
    timestamps_ms: Mapping[str, float] = field(default_factory=dict)
    audit_events: tuple[str, ...] = ()
    state_events: tuple[str, ...] = ()
    vns_events: tuple[str, ...] = ()


@dataclass(frozen=True)
class EdgeChorusHarmony:
    schema: str
    action_id: str
    edge_type: str
    companion_presence: float
    sequence_resolution: float
    mesh_entrainment: float
    audit_closure: float
    settlement: float
    chorus_quality: float
    resolution_class: str
    dissonance_class: str | None
    rationale: tuple[str, ...]
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self):
        return asdict(self)


class EdgeChorus:
    """Musical integrity of one governed research edge."""

    def score(self, spec: EdgeChorusSpec, obs: EdgeChorusObservation) -> EdgeChorusHarmony:
        required = tuple(dict.fromkeys(spec.required_participants + spec.required_companions))
        observed = set(obs.observed_participants)
        companion_presence = _clamp(_ratio(sum(1 for x in required if x in observed), len(required)))

        expected = list(spec.expected_sequence)
        observed_seq = list(obs.observed_sequence)
        if not expected:
            sequence_resolution = 1.0
        else:
            positions = {item: i for i, item in enumerate(observed_seq)}
            earned = 0.0
            for i, item in enumerate(expected):
                if item not in positions:
                    continue
                earned += 0.5
                if i == 0 or (expected[i-1] in positions and positions[expected[i-1]] < positions[item]):
                    earned += 0.5
            sequence_resolution = _clamp(earned / len(expected))

        passed = 0
        total = 0
        for relation, band in spec.timing_tolerances_ms.items():
            if "->" not in relation:
                continue
            left, right = relation.split("->", 1)
            if left not in obs.timestamps_ms or right not in obs.timestamps_ms:
                continue
            total += 1
            delta = float(obs.timestamps_ms[right] - obs.timestamps_ms[left])
            if float(band[0]) <= delta <= float(band[1]):
                passed += 1
        mesh = 0.6 if total == 0 else _clamp(passed / total)
        if any("pulse_instability" in e for e in obs.vns_events):
            mesh = _clamp(mesh - 0.15)

        audit = _clamp(_ratio(
            sum(1 for e in spec.required_audit_events if e in set(obs.audit_events)),
            len(spec.required_audit_events),
        ))
        settlement = _clamp(_ratio(
            sum(1 for e in spec.required_state_events if e in set(obs.state_events)),
            len(spec.required_state_events),
        ))
        if spec.settlement_timeout_ms:
            opened = obs.timestamps_ms.get("edge_opened")
            settled = obs.timestamps_ms.get("edge_settled")
            if opened is None or settled is None:
                settlement = _clamp(settlement - 0.25)
            else:
                lag = float(settled - opened)
                if lag > spec.settlement_timeout_ms:
                    over = lag - spec.settlement_timeout_ms
                    settlement = _clamp(settlement - min(0.7, over / max(1.0, spec.settlement_timeout_ms)))

        quality = _clamp(
            0.28 * companion_presence
            + 0.22 * sequence_resolution
            + 0.20 * mesh
            + 0.15 * audit
            + 0.15 * settlement
        )
        if companion_presence < 0.45 or settlement < 0.35:
            resolution = "fractured"
        elif quality < 0.50 or sequence_resolution < 0.50:
            resolution = "dissonant"
        elif quality < 0.78:
            resolution = "strained"
        else:
            resolution = "consonant"

        dissonance_class = None
        if resolution == "strained":
            dissonance_class = "local_strain"
        elif resolution == "dissonant":
            dissonance_class = "dissonance"
        elif resolution == "fractured":
            dissonance_class = "score_corruption" if quality < 0.2 or settlement < 0.2 else "choral_fracture"

        rationale = []
        missing = [x for x in required if x not in observed]
        if missing:
            rationale.append("missing_companions:" + ",".join(missing))
        if sequence_resolution < 0.75:
            rationale.append("sequence_unresolved")
        if mesh < 0.70:
            rationale.append("mesh_out_of_time")
        if audit < 1.0:
            rationale.append("audit_coda_incomplete")
        if settlement < 0.75:
            rationale.append("settlement_cadence_incomplete")
        if not rationale:
            rationale.append("edge_chorus_resolved_in_harmony")

        return EdgeChorusHarmony(
            schema="hivenance_edge_chorus_harmony_v1",
            action_id=obs.action_id,
            edge_type=obs.edge_type,
            companion_presence=round(companion_presence, 6),
            sequence_resolution=round(sequence_resolution, 6),
            mesh_entrainment=round(mesh, 6),
            audit_closure=round(audit, 6),
            settlement=round(settlement, 6),
            chorus_quality=round(quality, 6),
            resolution_class=resolution,
            dissonance_class=dissonance_class,
            rationale=tuple(rationale),
        )
