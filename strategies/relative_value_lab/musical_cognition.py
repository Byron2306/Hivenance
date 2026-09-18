from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .harmony_law import HarmonyBeeMessage, horizon_band
from .waggle_protocol import LineageRegistry, WaggleReceipt


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
class MotifNote:
    """One lawful musical note in the HiveNance score."""

    message_id: str
    receipt_id: str
    hypothesis_id: str
    bee_id: str
    family: str
    lineage_digest: str
    root_lineage_digest: Optional[str]
    message_type: str
    observed_at_ms: int
    horizon_band: str
    direction: str
    expected_move_bps: Optional[float]
    uncertainty: Optional[float]
    pulse_type: Optional[str]
    evidence_root: str
    world_state_id: str
    world_state_hash: str
    independent_voice: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MotifScore:
    """Continuous musical description of one hypothesis motif.

    No categorical belief state is produced.
    """

    schema: str
    score_id: str
    hypothesis_id: str
    note_count: int
    independent_voice_count: int
    families: tuple[str, ...]
    bands: tuple[str, ...]
    phrase_duration_ms: int

    # Rhythm / cadence
    mean_inter_onset_ms: Optional[float]
    median_inter_onset_ms: Optional[float]
    tempo_events_per_minute: Optional[float]
    rhythmic_regularity: float
    syncopation: float
    rest_density: float
    call_response_latency_ms: Optional[int]

    # Polyphony / harmony
    counterpoint_diversity: float
    consonance: float
    dissonance: float
    tension: float

    # Dynamics / modulation
    dynamic_intensity: float
    crescendo: float
    decrescendo: float
    modulation_count: int
    cadence_strength: float

    # Musical memory
    first_note_ms: Optional[int]
    last_note_ms: Optional[int]
    recent_message_types: tuple[str, ...]
    notes_digest: str

    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MusicalCognitionConfig:
    recent_window_notes: int = 8
    minimum_reference_interval_ms: int = 1


class MusicalMotifAccumulator:
    """Listen to lawful bee testimony as music.

    The accumulator does not move hypotheses through states. It measures the
    score that lawful voices create through time: recurrence, rhythm, rests,
    counterpoint, tension, dynamics, modulation and cadence.
    """

    version = "hivenance.musical_motif_accumulator.v1"

    def __init__(
        self,
        *,
        registry: LineageRegistry,
        config: MusicalCognitionConfig | None = None,
    ) -> None:
        self.registry = registry
        self.config = config or MusicalCognitionConfig()
        self._notes: dict[str, list[MotifNote]] = {}

    def ingest(
        self,
        *,
        message: HarmonyBeeMessage,
        receipt: WaggleReceipt,
    ) -> Optional[MotifNote]:
        """Ingest only lawful choir-eligible testimony."""

        if message.message_id != receipt.message_id:
            raise ValueError("message_receipt_identity_mismatch")
        if message.hypothesis_id != receipt.hypothesis_id:
            raise ValueError("hypothesis_identity_mismatch")
        if not receipt.accepted or not receipt.choir_eligible:
            return None
        if receipt.execution_eligible or receipt.promotion_eligible:
            raise ValueError("musical_cognition_authority_violation")

        note = MotifNote(
            message_id=message.message_id,
            receipt_id=receipt.receipt_id,
            hypothesis_id=message.hypothesis_id,
            bee_id=message.bee_id,
            family=message.family,
            lineage_digest=message.lineage_digest,
            root_lineage_digest=receipt.root_lineage_digest,
            message_type=message.message_type,
            observed_at_ms=int(message.observed_at_ms),
            horizon_band=horizon_band(message.horizon_seconds),
            direction=message.direction,
            expected_move_bps=message.expected_move_bps,
            uncertainty=message.uncertainty,
            pulse_type=message.pulse_type,
            evidence_root=message.evidence_root,
            world_state_id=message.world_state_id,
            world_state_hash=message.world_state_hash,
            independent_voice=bool(receipt.independent_vote_eligible),
        )
        bucket = self._notes.setdefault(message.hypothesis_id, [])
        if all(existing.message_id != note.message_id for existing in bucket):
            bucket.append(note)
            bucket.sort(key=lambda item: (item.observed_at_ms, item.message_id))
        return note

    def notes(self, hypothesis_id: str) -> tuple[MotifNote, ...]:
        return tuple(self._notes.get(hypothesis_id, ()))

    def score(self, hypothesis_id: str) -> MotifScore:
        notes = list(self._notes.get(hypothesis_id, ()))
        if not notes:
            return self._empty_score(hypothesis_id)

        times = [note.observed_at_ms for note in notes]
        first_ms = min(times)
        last_ms = max(times)
        duration = max(0, last_ms - first_ms)
        intervals = [
            max(0, b - a)
            for a, b in zip(times, times[1:])
        ]

        mean_ioi: Optional[float] = None
        median_ioi: Optional[float] = None
        tempo: Optional[float] = None
        rhythmic_regularity = 1.0 if len(notes) == 1 else 0.0
        syncopation = 0.0
        rest_density = 0.0

        if intervals:
            mean_ioi = statistics.fmean(intervals)
            median_ioi = statistics.median(intervals)
            reference = max(float(self.config.minimum_reference_interval_ms), float(median_ioi))
            tempo = 60_000.0 / max(reference, 1.0)

            if len(intervals) >= 2 and mean_ioi > 0:
                cv = statistics.pstdev(intervals) / mean_ioi
                rhythmic_regularity = _clamp(1.0 - cv)
            else:
                rhythmic_regularity = 1.0

            # Syncopation is deviation from the phrase's own median pulse.
            deviation = statistics.fmean(
                min(2.0, abs(interval - reference) / reference)
                for interval in intervals
            )
            syncopation = _clamp(deviation / 2.0)

            if duration > 0:
                rest_ms = sum(max(0.0, interval - 1.5 * reference) for interval in intervals)
                rest_density = _clamp(rest_ms / duration)

        independent_roots = {
            note.root_lineage_digest
            for note in notes
            if note.independent_voice and note.root_lineage_digest
        }
        families = sorted({note.family for note in notes})
        bands = sorted({note.horizon_band for note in notes})

        # Counterpoint rewards distinct independent lines without assuming they
        # must agree in direction.
        counterpoint_diversity = _clamp(len(independent_roots) / max(1.0, float(len(notes))))

        consonance, dissonance = self._harmony(notes)
        tension = self._tension(notes, dissonance)
        dynamic_intensity = self._dynamic_intensity(notes, duration, len(independent_roots))
        crescendo, decrescendo = self._dynamics(notes)
        modulation_count = self._modulations(notes)
        call_response_latency = self._call_response_latency(notes)
        cadence_strength = self._cadence(
            notes=notes,
            consonance=consonance,
            dissonance=dissonance,
            rhythmic_regularity=rhythmic_regularity,
            counterpoint_diversity=counterpoint_diversity,
            tension=tension,
            rest_density=rest_density,
        )

        recent = tuple(
            note.message_type
            for note in notes[-max(1, int(self.config.recent_window_notes)) :]
        )
        note_payloads = [note.to_dict() for note in notes]
        notes_digest = _digest(note_payloads)
        body = {
            "hypothesis_id": hypothesis_id,
            "notes_digest": notes_digest,
            "note_count": len(notes),
            "cadence_strength": round(cadence_strength, 6),
            "tension": round(tension, 6),
            "modulation_count": modulation_count,
        }
        return MotifScore(
            schema="hivenance_motif_score_v1",
            score_id="motif_" + _digest(body).split(":", 1)[1][:24],
            hypothesis_id=hypothesis_id,
            note_count=len(notes),
            independent_voice_count=len(independent_roots),
            families=tuple(families),
            bands=tuple(bands),
            phrase_duration_ms=duration,
            mean_inter_onset_ms=None if mean_ioi is None else round(mean_ioi, 3),
            median_inter_onset_ms=None if median_ioi is None else round(float(median_ioi), 3),
            tempo_events_per_minute=None if tempo is None else round(tempo, 6),
            rhythmic_regularity=round(rhythmic_regularity, 6),
            syncopation=round(syncopation, 6),
            rest_density=round(rest_density, 6),
            call_response_latency_ms=call_response_latency,
            counterpoint_diversity=round(counterpoint_diversity, 6),
            consonance=round(consonance, 6),
            dissonance=round(dissonance, 6),
            tension=round(tension, 6),
            dynamic_intensity=round(dynamic_intensity, 6),
            crescendo=round(crescendo, 6),
            decrescendo=round(decrescendo, 6),
            modulation_count=modulation_count,
            cadence_strength=round(cadence_strength, 6),
            first_note_ms=first_ms,
            last_note_ms=last_ms,
            recent_message_types=recent,
            notes_digest=notes_digest,
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )

    def _empty_score(self, hypothesis_id: str) -> MotifScore:
        body = {"hypothesis_id": hypothesis_id, "empty": True}
        return MotifScore(
            schema="hivenance_motif_score_v1",
            score_id="motif_" + _digest(body).split(":", 1)[1][:24],
            hypothesis_id=hypothesis_id,
            note_count=0,
            independent_voice_count=0,
            families=(),
            bands=(),
            phrase_duration_ms=0,
            mean_inter_onset_ms=None,
            median_inter_onset_ms=None,
            tempo_events_per_minute=None,
            rhythmic_regularity=0.0,
            syncopation=0.0,
            rest_density=1.0,
            call_response_latency_ms=None,
            counterpoint_diversity=0.0,
            consonance=0.0,
            dissonance=0.0,
            tension=0.0,
            dynamic_intensity=0.0,
            crescendo=0.0,
            decrescendo=0.0,
            modulation_count=0,
            cadence_strength=0.0,
            first_note_ms=None,
            last_note_ms=None,
            recent_message_types=(),
            notes_digest=_digest([]),
        )

    @staticmethod
    def _harmony(notes: Sequence[MotifNote]) -> tuple[float, float]:
        # One representative direction per independent root + horizon band.
        reps: dict[tuple[str, str], int] = {}
        dissent_weight = 0.0
        for note in notes:
            if note.message_type == "DISSENT":
                dissent_weight += 1.0
            if not note.independent_voice or not note.root_lineage_digest:
                continue
            sign = _direction_sign(note.direction)
            if sign == 0:
                continue
            reps.setdefault((note.root_lineage_digest, note.horizon_band), sign)

        signs = list(reps.values())
        if not signs:
            consonance = 0.0
            directional_dissonance = 0.0
        elif len(signs) == 1:
            consonance = 0.5
            directional_dissonance = 0.0
        else:
            agreement = abs(sum(signs)) / len(signs)
            consonance = _clamp(agreement)
            directional_dissonance = _clamp(1.0 - agreement)

        explicit_dissent = _clamp(dissent_weight / max(1.0, float(len(notes))))
        dissonance = _clamp(0.7 * directional_dissonance + 0.3 * explicit_dissent)
        return consonance, dissonance

    @staticmethod
    def _tension(notes: Sequence[MotifNote], dissonance: float) -> float:
        alarms = sum(
            1
            for note in notes
            if note.message_type == "ALARM"
            or note.pulse_type in {"ALARM_PULSE", "FREEZE_PULSE"}
        )
        abandons = sum(1 for note in notes if note.message_type == "ABANDON")
        alarm_pressure = _clamp((alarms + 0.5 * abandons) / max(1.0, float(len(notes))))
        return _clamp(0.72 * dissonance + 0.28 * alarm_pressure)

    @staticmethod
    def _dynamic_intensity(
        notes: Sequence[MotifNote],
        duration_ms: int,
        independent_voices: int,
    ) -> float:
        if not notes:
            return 0.0
        if duration_ms <= 0:
            density = 1.0
        else:
            events_per_minute = len(notes) * 60_000.0 / duration_ms
            density = _clamp(events_per_minute / 60.0)
        voice_factor = _clamp(independent_voices / 4.0)
        pulse_factor = _clamp(
            sum(1 for note in notes if note.pulse_type) / max(1.0, float(len(notes)))
        )
        return _clamp(0.5 * density + 0.35 * voice_factor + 0.15 * pulse_factor)

    @staticmethod
    def _dynamics(notes: Sequence[MotifNote]) -> tuple[float, float]:
        if len(notes) < 4:
            return 0.0, 0.0
        cut = len(notes) // 2
        early = notes[:cut]
        late = notes[cut:]

        def energy(chunk: Sequence[MotifNote]) -> float:
            voices = len({
                n.root_lineage_digest
                for n in chunk
                if n.independent_voice and n.root_lineage_digest
            })
            emphatic = sum(
                1
                for n in chunk
                if n.message_type in {"FOLLOW", "DISSENT", "ALARM"}
                or n.pulse_type is not None
            )
            return float(len(chunk)) + 0.75 * voices + 0.25 * emphatic

        early_energy = energy(early)
        late_energy = energy(late)
        scale = max(1.0, early_energy, late_energy)
        delta = (late_energy - early_energy) / scale
        return _clamp(max(0.0, delta)), _clamp(max(0.0, -delta))

    @staticmethod
    def _modulations(notes: Sequence[MotifNote]) -> int:
        count = 0
        previous_band: Optional[str] = None
        previous_sign: Optional[int] = None
        previous_world: Optional[str] = None
        for note in notes:
            sign = _direction_sign(note.direction)
            if previous_band is not None and note.horizon_band != previous_band:
                count += 1
            if previous_sign is not None and sign and previous_sign and sign != previous_sign:
                count += 1
            if previous_world is not None and note.world_state_id != previous_world:
                count += 1
            previous_band = note.horizon_band
            if sign:
                previous_sign = sign
            previous_world = note.world_state_id
        return count

    @staticmethod
    def _call_response_latency(notes: Sequence[MotifNote]) -> Optional[int]:
        for idx, note in enumerate(notes):
            if note.message_type not in {"WAGGLE", "SEARCH"}:
                continue
            root = note.root_lineage_digest
            for response in notes[idx + 1 :]:
                if response.message_type not in {"FOLLOW", "DISSENT", "ALARM"}:
                    continue
                if (
                    response.root_lineage_digest
                    and response.root_lineage_digest != root
                ):
                    return max(0, response.observed_at_ms - note.observed_at_ms)
        return None

    @staticmethod
    def _cadence(
        *,
        notes: Sequence[MotifNote],
        consonance: float,
        dissonance: float,
        rhythmic_regularity: float,
        counterpoint_diversity: float,
        tension: float,
        rest_density: float,
    ) -> float:
        if not notes:
            return 0.0

        # A cadence is not "agreement". It is a local tendency toward
        # resolution: multiple lawful voices, coherent timing, manageable
        # tension, and enough space/rest to avoid mistaking chatter for music.
        voice_factor = _clamp(
            len({
                n.root_lineage_digest
                for n in notes
                if n.independent_voice and n.root_lineage_digest
            }) / 3.0
        )
        space = 1.0 - _clamp(abs(rest_density - 0.18) / 0.82)
        return _clamp(
            0.22 * consonance
            + 0.18 * rhythmic_regularity
            + 0.18 * voice_factor
            + 0.14 * counterpoint_diversity
            + 0.12 * (1.0 - dissonance)
            + 0.10 * (1.0 - tension)
            + 0.06 * space
        )
