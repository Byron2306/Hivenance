from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from typing import Any, Optional, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .harmonic_governance import HarmonicForecastReceipt, HarmonicHorizonState
from .polyphonic_entrainment import EntrainmentReceipt
from .temporal_texture import TemporalTextureReceipt
from .causal_cascade import CausalCascadeReceipt
from .hive_pulse import HivePulse, HivePulseEngine


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class RegisterResonance:
    band: str
    horizons: tuple[int, ...]
    horizon_directions: tuple[tuple[int, str], ...]
    harmonic_resonance: float
    entrainment: float
    temporal_coherence: float
    pulse_energy: float
    cascade_crescendo: float
    resonance: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RegisterRelationship:
    left_horizon: int
    right_horizon: int
    relation: str
    tension: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PolyphonicResonanceReceipt:
    schema: str
    receipt_id: str
    pair_id: str
    timestamp_ms: int
    register_resonances: tuple[RegisterResonance, ...]
    relationships: tuple[RegisterRelationship, ...]
    register_diversity: float
    rhythmic_phase_coherence: float
    cross_band_tension: float
    overtone_coherence: float
    resonance_drift: float
    global_resonance: float
    texture: str
    reasons: tuple[str, ...]
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["register_resonances"] = tuple(x.to_dict() for x in self.register_resonances)
        payload["relationships"] = tuple(x.to_dict() for x in self.relationships)
        return payload


class PolyphonicResonance:
    """Global relationship listener with no global market direction.

    Micro, meso and macro remain distinct registers. Contrary directions are
    preserved as counterpoint tension rather than collapsed into a winner.
    """

    version = "hivenance.polyphonic_resonance.v1"

    def __init__(self, history_size: int = 24) -> None:
        self._history: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=max(4, int(history_size)))
        )

    @staticmethod
    def _pulse_energy(
        pulses: Sequence[HivePulse],
        *,
        now_ms: int,
    ) -> float:
        active = [
            HivePulseEngine.decay(pulse, now_ms=now_ms)
            for pulse in pulses
        ]
        live = [row for row in active if not row.expired]
        if not live:
            return 0.0
        return _clamp(statistics.fmean(
            row.effective_amplitude * row.effective_confidence
            for row in live
        ))

    @staticmethod
    def _entrainment_by_band(receipt: EntrainmentReceipt) -> dict[str, float]:
        return {band.band: float(band.entrainment) for band in receipt.bands}

    @staticmethod
    def _horizons_by_band(
        states: Sequence[HarmonicHorizonState],
    ) -> dict[str, list[HarmonicHorizonState]]:
        out: dict[str, list[HarmonicHorizonState]] = defaultdict(list)
        for state in states:
            out[state.band].append(state)
        return out

    @staticmethod
    def _relationships(
        states: Sequence[HarmonicHorizonState],
    ) -> tuple[RegisterRelationship, ...]:
        ordered = sorted(states, key=lambda x: x.horizon_seconds)
        out: list[RegisterRelationship] = []
        for i, left in enumerate(ordered):
            for right in ordered[i + 1:]:
                if "ABSTAIN" in {left.direction, right.direction}:
                    relation = "suspended"
                    tension = 0.35
                elif left.direction == right.direction:
                    relation = "parallel"
                    tension = 0.0
                else:
                    relation = "contrary"
                    # Contrary motion is audible tension, not a failure.
                    confidence = min(left.confidence, right.confidence)
                    tension = _clamp(0.45 + 0.35 * confidence)
                out.append(RegisterRelationship(
                    left_horizon=left.horizon_seconds,
                    right_horizon=right.horizon_seconds,
                    relation=relation,
                    tension=round(tension, 6),
                ))
        return tuple(out)

    @staticmethod
    def _overtone_coherence(
        states: Sequence[HarmonicHorizonState],
    ) -> float:
        active = [
            state for state in states
            if state.direction != "ABSTAIN"
        ]
        if len(active) < 2:
            return 0.0

        # Overtone coherence rewards stable, confident registers whether they
        # move in parallel or contrary motion. It does not reward same direction
        # specifically.
        values = [
            _clamp(
                0.45 * state.resonance_score
                + 0.35 * state.confidence
                + 0.20 * (1.0 - state.forecast_jitter)
            )
            for state in active
        ]
        dispersion = statistics.pstdev(values) if len(values) > 1 else 0.0
        return _clamp(statistics.fmean(values) * (1.0 - min(1.0, dispersion)))

    @staticmethod
    def _texture(
        *,
        register_count: int,
        cross_band_tension: float,
        global_resonance: float,
        resonance_drift: float,
    ) -> str:
        if register_count < 2:
            return "SPARSE"
        if resonance_drift > 0.45:
            return "MODULATING"
        if cross_band_tension > 0.55 and global_resonance >= 0.50:
            return "COUNTERPOINT"
        if global_resonance >= 0.70 and cross_band_tension < 0.35:
            return "FULL_CHORD"
        if cross_band_tension > 0.55:
            return "SUSPENDED"
        return "POLYPHONIC"

    def score(
        self,
        *,
        harmonic: HarmonicForecastReceipt,
        entrainment: EntrainmentReceipt,
        temporal_texture: TemporalTextureReceipt | None = None,
        cascade: CausalCascadeReceipt | None = None,
        hive_pulses: Sequence[HivePulse] = (),
        now_ms: Optional[int] = None,
    ) -> PolyphonicResonanceReceipt:
        now_ms = int(harmonic.timestamp_ms if now_ms is None else now_ms)
        states = tuple(harmonic.horizon_states)
        by_band = self._horizons_by_band(states)
        entrainment_map = self._entrainment_by_band(entrainment)
        pulse_energy = self._pulse_energy(hive_pulses, now_ms=now_ms)
        temporal_coherence = (
            float(temporal_texture.cadence_coherence)
            if temporal_texture is not None
            else _clamp(1.0 - harmonic.forecast_jitter)
        )
        cascade_crescendo = float(cascade.crescendo) if cascade else 0.0

        registers: list[RegisterResonance] = []
        for band in ("micro", "meso", "macro"):
            band_states = by_band.get(band, [])
            if not band_states:
                continue
            harmonic_resonance = statistics.fmean(
                state.resonance_score for state in band_states
            )
            band_entrainment = float(entrainment_map.get(band, 0.0))
            resonance = _clamp(
                0.40 * harmonic_resonance
                + 0.25 * band_entrainment
                + 0.15 * temporal_coherence
                + 0.10 * pulse_energy
                + 0.10 * cascade_crescendo
            )
            registers.append(RegisterResonance(
                band=band,
                horizons=tuple(sorted(state.horizon_seconds for state in band_states)),
                horizon_directions=tuple(
                    sorted(
                        (state.horizon_seconds, state.direction)
                        for state in band_states
                    )
                ),
                harmonic_resonance=round(harmonic_resonance, 6),
                entrainment=round(band_entrainment, 6),
                temporal_coherence=round(temporal_coherence, 6),
                pulse_energy=round(pulse_energy, 6),
                cascade_crescendo=round(cascade_crescendo, 6),
                resonance=round(resonance, 6),
            ))

        relationships = self._relationships(states)
        cross_band = [
            rel.tension for rel in relationships
            if self._band_for_horizon(rel.left_horizon) != self._band_for_horizon(rel.right_horizon)
        ]
        cross_band_tension = (
            statistics.fmean(cross_band) if cross_band else 0.0
        )

        register_diversity = _clamp(len(registers) / 3.0)

        phase_values = [
            band.phase_alignment
            for band in entrainment.bands
            if band.band in {register.band for register in registers}
        ]
        rhythmic_phase = (
            statistics.fmean(phase_values) if phase_values else 0.0
        )

        overtone = self._overtone_coherence(states)

        if registers:
            mean_register = statistics.fmean(register.resonance for register in registers)
            global_resonance = _clamp(
                0.45 * mean_register
                + 0.20 * register_diversity
                + 0.15 * rhythmic_phase
                + 0.20 * overtone
            )
        else:
            global_resonance = 0.0

        history = self._history[harmonic.pair_id]
        prior = list(history)
        if len(prior) >= 3:
            reference = statistics.fmean(prior[-3:])
            resonance_drift = _clamp(abs(global_resonance - reference))
        else:
            resonance_drift = 0.0
        history.append(global_resonance)

        texture = self._texture(
            register_count=len(registers),
            cross_band_tension=cross_band_tension,
            global_resonance=global_resonance,
            resonance_drift=resonance_drift,
        )

        reasons: list[str] = []
        if len(registers) < 2:
            reasons.append("insufficient_register_diversity")
        if cross_band_tension > 0.55:
            reasons.append("cross_band_counterpoint_audible")
        if resonance_drift > 0.45:
            reasons.append("resonance_modulation_audible")
        if pulse_energy > 0.35:
            reasons.append("hive_pulse_in_resonance")
        if cascade_crescendo > 0.40:
            reasons.append("cascade_crescendo_in_resonance")

        body = {
            "pair_id": harmonic.pair_id,
            "timestamp_ms": harmonic.timestamp_ms,
            "registers": [register.to_dict() for register in registers],
            "relationships": [rel.to_dict() for rel in relationships],
            "global_resonance": round(global_resonance, 6),
            "texture": texture,
        }
        return PolyphonicResonanceReceipt(
            schema="hivenance_polyphonic_resonance_v1",
            receipt_id="poly_" + _digest(body).split(":", 1)[1][:24],
            pair_id=harmonic.pair_id,
            timestamp_ms=harmonic.timestamp_ms,
            register_resonances=tuple(registers),
            relationships=relationships,
            register_diversity=round(register_diversity, 6),
            rhythmic_phase_coherence=round(rhythmic_phase, 6),
            cross_band_tension=round(cross_band_tension, 6),
            overtone_coherence=round(overtone, 6),
            resonance_drift=round(resonance_drift, 6),
            global_resonance=round(global_resonance, 6),
            texture=texture,
            reasons=tuple(sorted(set(reasons))),
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )

    @staticmethod
    def _band_for_horizon(horizon_seconds: int) -> str:
        if horizon_seconds <= 10:
            return "micro"
        if horizon_seconds <= 60:
            return "meso"
        return "macro"
