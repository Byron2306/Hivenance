from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .musical_cognition import MotifNote


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _direction_sign(direction: str) -> int:
    value = str(direction or "").upper()
    if value == "LONG_A_SHORT_B":
        return 1
    if value == "LONG_B_SHORT_A":
        return -1
    return 0


@dataclass(frozen=True)
class BandEntrainment:
    band: str
    note_count: int
    independent_voice_count: int
    direction_alignment: float
    phase_alignment: float
    recurrence_alignment: float
    entrainment: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EntrainmentReceipt:
    schema: str
    receipt_id: str
    hypothesis_id: str
    beat_interval_ms: Optional[float]
    independent_voice_count: int
    source_diversity: float
    phase_alignment: float
    directional_alignment: float
    recurrence_alignment: float
    recruitment_cascade: float
    crescendo_strength: float
    convergence_gain: float
    entrainment_strength: float
    false_unison_risk: float
    bands: tuple[BandEntrainment, ...]
    warnings: tuple[str, ...]
    notes_digest: str
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["bands"] = tuple(b.to_dict() for b in self.bands)
        return payload


@dataclass(frozen=True)
class EntrainmentConfig:
    minimum_notes: int = 2
    phase_tolerance_fraction: float = 0.25
    recent_fraction: float = 0.5


class PolyphonicEntrainment:
    """Measure emergent phase-locking among independent HiveNance voices.

    Entrainment is not a vote. It asks whether distinct evidence lineages that
    began independently increasingly synchronize their timing, recurrence and
    within-band directional expression as a motif develops.

    Cross-horizon directions are never collapsed into one market direction.
    """

    version = "hivenance.polyphonic_entrainment.v1"

    def __init__(self, config: EntrainmentConfig | None = None) -> None:
        self.config = config or EntrainmentConfig()

    def score(self, *, hypothesis_id: str, notes: Sequence[MotifNote]) -> EntrainmentReceipt:
        ordered = sorted(
            [n for n in notes if n.hypothesis_id == hypothesis_id],
            key=lambda n: (n.observed_at_ms, n.message_id),
        )
        if not ordered:
            return self._empty(hypothesis_id)

        beat = self._beat_interval(ordered)
        bands = tuple(
            self._score_band(band, [n for n in ordered if n.horizon_band == band], beat)
            for band in sorted({n.horizon_band for n in ordered})
        )

        independent_roots = {
            n.root_lineage_digest
            for n in ordered
            if n.independent_voice and n.root_lineage_digest
        }
        independent_notes = [
            n for n in ordered
            if n.independent_voice and n.root_lineage_digest
        ]

        source_roots = {n.evidence_root for n in independent_notes if n.evidence_root}
        source_diversity = _clamp(
            len(source_roots) / max(1.0, float(len(independent_roots)))
        )

        phase_alignment = self._weighted_band_metric(bands, "phase_alignment")
        directional_alignment = self._weighted_band_metric(bands, "direction_alignment")
        recurrence_alignment = self._weighted_band_metric(bands, "recurrence_alignment")

        recruitment_cascade = self._recruitment_cascade(independent_notes)
        crescendo_strength = self._crescendo(independent_notes)
        convergence_gain = self._convergence_gain(ordered, beat)

        false_unison_risk = self._false_unison_risk(
            independent_voice_count=len(independent_roots),
            source_diversity=source_diversity,
            notes=independent_notes,
        )

        entrainment_strength = _clamp(
            0.24 * phase_alignment
            + 0.20 * directional_alignment
            + 0.16 * recurrence_alignment
            + 0.16 * recruitment_cascade
            + 0.12 * crescendo_strength
            + 0.12 * max(0.0, convergence_gain)
        )
        entrainment_strength = _clamp(
            entrainment_strength * (1.0 - 0.55 * false_unison_risk)
        )

        warnings: list[str] = []
        if len(independent_roots) < 2:
            warnings.append("insufficient_independent_voices")
        if false_unison_risk >= 0.50:
            warnings.append("false_unison_risk")
        if source_diversity < 0.50 and len(independent_roots) >= 2:
            warnings.append("shared_evidence_root_pressure")
        if convergence_gain < 0:
            warnings.append("voices_diverging_not_entraining")

        notes_digest = _digest([n.to_dict() for n in ordered])
        body = {
            "hypothesis_id": hypothesis_id,
            "notes_digest": notes_digest,
            "entrainment_strength": round(entrainment_strength, 6),
            "false_unison_risk": round(false_unison_risk, 6),
            "convergence_gain": round(convergence_gain, 6),
        }
        return EntrainmentReceipt(
            schema="hivenance_polyphonic_entrainment_v1",
            receipt_id="ent_" + _digest(body).split(":", 1)[1][:24],
            hypothesis_id=hypothesis_id,
            beat_interval_ms=None if beat is None else round(beat, 3),
            independent_voice_count=len(independent_roots),
            source_diversity=round(source_diversity, 6),
            phase_alignment=round(phase_alignment, 6),
            directional_alignment=round(directional_alignment, 6),
            recurrence_alignment=round(recurrence_alignment, 6),
            recruitment_cascade=round(recruitment_cascade, 6),
            crescendo_strength=round(crescendo_strength, 6),
            convergence_gain=round(convergence_gain, 6),
            entrainment_strength=round(entrainment_strength, 6),
            false_unison_risk=round(false_unison_risk, 6),
            bands=bands,
            warnings=tuple(sorted(set(warnings))),
            notes_digest=notes_digest,
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )

    def _empty(self, hypothesis_id: str) -> EntrainmentReceipt:
        notes_digest = _digest([])
        return EntrainmentReceipt(
            schema="hivenance_polyphonic_entrainment_v1",
            receipt_id="ent_" + _digest({"hypothesis_id": hypothesis_id, "empty": True}).split(":", 1)[1][:24],
            hypothesis_id=hypothesis_id,
            beat_interval_ms=None,
            independent_voice_count=0,
            source_diversity=0.0,
            phase_alignment=0.0,
            directional_alignment=0.0,
            recurrence_alignment=0.0,
            recruitment_cascade=0.0,
            crescendo_strength=0.0,
            convergence_gain=0.0,
            entrainment_strength=0.0,
            false_unison_risk=0.0,
            bands=(),
            warnings=("insufficient_independent_voices",),
            notes_digest=notes_digest,
        )

    @staticmethod
    def _beat_interval(notes: Sequence[MotifNote]) -> Optional[float]:
        if len(notes) < 2:
            return None
        times = sorted(n.observed_at_ms for n in notes)
        intervals = [b - a for a, b in zip(times, times[1:]) if b > a]
        if not intervals:
            return None
        return float(statistics.median(intervals))

    def _score_band(
        self,
        band: str,
        notes: Sequence[MotifNote],
        beat: Optional[float],
    ) -> BandEntrainment:
        independent = [
            n for n in notes
            if n.independent_voice and n.root_lineage_digest
        ]
        roots = {n.root_lineage_digest for n in independent if n.root_lineage_digest}

        direction_alignment = self._direction_alignment(independent)
        phase_alignment = self._phase_alignment(independent, beat)
        recurrence_alignment = self._recurrence_alignment(independent, beat)

        voice_factor = _clamp(len(roots) / 3.0)
        entrainment = _clamp(
            0.36 * phase_alignment
            + 0.30 * direction_alignment
            + 0.22 * recurrence_alignment
            + 0.12 * voice_factor
        )
        return BandEntrainment(
            band=band,
            note_count=len(notes),
            independent_voice_count=len(roots),
            direction_alignment=round(direction_alignment, 6),
            phase_alignment=round(phase_alignment, 6),
            recurrence_alignment=round(recurrence_alignment, 6),
            entrainment=round(entrainment, 6),
        )

    @staticmethod
    def _direction_alignment(notes: Sequence[MotifNote]) -> float:
        latest_by_root: dict[str, int] = {}
        for note in notes:
            if not note.root_lineage_digest:
                continue
            sign = _direction_sign(note.direction)
            if sign:
                latest_by_root[note.root_lineage_digest] = sign
        signs = list(latest_by_root.values())
        if not signs:
            return 0.0
        if len(signs) == 1:
            return 0.5
        return _clamp(abs(sum(signs)) / len(signs))

    def _phase_alignment(
        self,
        notes: Sequence[MotifNote],
        beat: Optional[float],
    ) -> float:
        if beat is None or beat <= 0 or len(notes) < 2:
            return 0.0

        first = min(n.observed_at_ms for n in notes)
        phases: list[float] = []
        for note in notes:
            phase = ((note.observed_at_ms - first) % beat) / beat
            angle = 2.0 * math.pi * phase
            phases.append(angle)

        if not phases:
            return 0.0
        x = statistics.fmean(math.cos(a) for a in phases)
        y = statistics.fmean(math.sin(a) for a in phases)
        return _clamp(math.sqrt(x * x + y * y))

    @staticmethod
    def _recurrence_alignment(
        notes: Sequence[MotifNote],
        beat: Optional[float],
    ) -> float:
        if beat is None or beat <= 0:
            return 0.0

        by_root: dict[str, list[int]] = {}
        for note in notes:
            if note.root_lineage_digest:
                by_root.setdefault(note.root_lineage_digest, []).append(note.observed_at_ms)

        scores: list[float] = []
        for times in by_root.values():
            if len(times) < 2:
                continue
            intervals = [b - a for a, b in zip(times, times[1:]) if b > a]
            if not intervals:
                continue
            deviations = [
                abs(interval / beat - round(interval / beat))
                for interval in intervals
            ]
            scores.append(
                _clamp(1.0 - statistics.fmean(min(1.0, d) for d in deviations))
            )
        if not scores:
            return 0.0
        return _clamp(statistics.fmean(scores))

    @staticmethod
    def _recruitment_cascade(notes: Sequence[MotifNote]) -> float:
        first_seen: dict[str, int] = {}
        for note in notes:
            if note.root_lineage_digest and note.root_lineage_digest not in first_seen:
                first_seen[note.root_lineage_digest] = note.observed_at_ms
        if len(first_seen) < 2:
            return 0.0

        ordered = sorted(first_seen.values())
        span = max(1, ordered[-1] - ordered[0])
        density = _clamp((len(ordered) - 1) / 4.0)
        compactness = _clamp(1.0 - span / max(60_000.0, float(span)))
        return _clamp(0.55 * density + 0.45 * compactness)

    @staticmethod
    def _crescendo(notes: Sequence[MotifNote]) -> float:
        if len(notes) < 4:
            return 0.0
        ordered = sorted(notes, key=lambda n: n.observed_at_ms)
        cut = len(ordered) // 2
        early = ordered[:cut]
        late = ordered[cut:]

        def energy(chunk: Sequence[MotifNote]) -> float:
            roots = {
                n.root_lineage_digest
                for n in chunk
                if n.independent_voice and n.root_lineage_digest
            }
            pulses = sum(1 for n in chunk if n.pulse_type is not None)
            follows = sum(1 for n in chunk if n.message_type == "FOLLOW")
            return float(len(chunk)) + 0.75 * len(roots) + 0.25 * pulses + 0.25 * follows

        early_energy = energy(early)
        late_energy = energy(late)
        scale = max(1.0, early_energy, late_energy)
        return _clamp(max(0.0, (late_energy - early_energy) / scale))

    def _convergence_gain(
        self,
        notes: Sequence[MotifNote],
        beat: Optional[float],
    ) -> float:
        if len(notes) < 4:
            return 0.0
        ordered = sorted(notes, key=lambda n: n.observed_at_ms)
        cut = max(2, len(ordered) // 2)
        early = ordered[:cut]
        late = ordered[cut:]

        early_score = self._segment_alignment(early, beat)
        late_score = self._segment_alignment(late, beat)
        return max(-1.0, min(1.0, late_score - early_score))

    def _segment_alignment(
        self,
        notes: Sequence[MotifNote],
        beat: Optional[float],
    ) -> float:
        by_band: dict[str, list[MotifNote]] = {}
        for note in notes:
            by_band.setdefault(note.horizon_band, []).append(note)
        if not by_band:
            return 0.0
        values = []
        for band_notes in by_band.values():
            direction = self._direction_alignment(band_notes)
            phase = self._phase_alignment(band_notes, beat)
            values.append(0.55 * direction + 0.45 * phase)
        return _clamp(statistics.fmean(values))

    @staticmethod
    def _false_unison_risk(
        *,
        independent_voice_count: int,
        source_diversity: float,
        notes: Sequence[MotifNote],
    ) -> float:
        if independent_voice_count < 2:
            return 0.0

        root_counts: dict[str, int] = {}
        evidence_counts: dict[str, int] = {}
        for note in notes:
            if note.root_lineage_digest:
                root_counts[note.root_lineage_digest] = root_counts.get(note.root_lineage_digest, 0) + 1
            if note.evidence_root:
                evidence_counts[note.evidence_root] = evidence_counts.get(note.evidence_root, 0) + 1

        source_reuse = 0.0
        if evidence_counts and notes:
            source_reuse = max(evidence_counts.values()) / len(notes)

        concentration = 0.0
        if root_counts and notes:
            concentration = max(root_counts.values()) / len(notes)

        return _clamp(
            0.55 * (1.0 - source_diversity)
            + 0.30 * source_reuse
            + 0.15 * concentration
        )

    @staticmethod
    def _weighted_band_metric(
        bands: Sequence[BandEntrainment],
        field: str,
    ) -> float:
        weighted = []
        total = 0.0
        for band in bands:
            weight = max(1.0, float(band.independent_voice_count))
            weighted.append(float(getattr(band, field)) * weight)
            total += weight
        if total <= 0:
            return 0.0
        return _clamp(sum(weighted) / total)
