from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Optional, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .governance_epoch import (
    EpochValidation,
    ResearchGovernanceEpoch,
    ResearchGovernanceEpochService,
)
from .musical_cognition import MotifNote, MotifScore
from .polyphonic_entrainment import EntrainmentReceipt


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _sign(direction: str) -> int:
    value = str(direction or "").upper()
    if value == "LONG_A_SHORT_B":
        return 1
    if value == "LONG_B_SHORT_A":
        return -1
    return 0


@dataclass(frozen=True)
class VoiceAcoustics:
    root_lineage_digest: str
    family: str
    note_count: int
    bands: tuple[str, ...]
    pitch_center_bps: Optional[float]
    pitch_spread_bps: Optional[float]
    tone_stability: float
    timbre_uncertainty: float
    timbre_accent_rate: float
    timbre_evidence_diversity: float
    articulation_ms: Optional[float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TriuneListening:
    metatron_synthesis: tuple[str, ...]
    michael_validation: tuple[str, ...]
    loki_counterpoint: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QueenConductingReceipt:
    schema: str
    receipt_id: str
    hypothesis_id: str
    epoch_id: str
    score_id: str
    genre_mode: str
    strictness_level: str
    epoch_valid: bool
    voice_acoustics: tuple[VoiceAcoustics, ...]
    triune: TriuneListening
    conducting_cues: tuple[str, ...]
    tonal_coherence: float
    timbral_diversity: float
    pitch_convergence: float
    subtle_shift_score: float
    reasons: tuple[str, ...]
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["voice_acoustics"] = tuple(v.to_dict() for v in self.voice_acoustics)
        payload["triune"] = self.triune.to_dict()
        return payload


class ConductingQueen:
    """Triune-minded musical conductor for HiveNance research cognition.

    The Queen listens and shapes research attention. She does not predict,
    trade, promote, or create authority. The governance epoch is the score she
    must obey.
    """

    version = "hivenance.conducting_queen.v1"

    def conduct(
        self,
        *,
        hypothesis_id: str,
        notes: Sequence[MotifNote],
        motif: MotifScore,
        entrainment: EntrainmentReceipt,
        epoch: ResearchGovernanceEpoch,
        now_ms: int,
        world_state_id: str,
        world_state_hash: str,
        scope: str = "relative_value_lab",
    ) -> QueenConductingReceipt:
        epoch_validation = ResearchGovernanceEpochService.validate(
            epoch,
            now_ms=now_ms,
            world_state_id=world_state_id,
            world_state_hash=world_state_hash,
            scope=scope,
        )

        acoustics = self._voice_acoustics(notes)
        tonal_coherence = self._tonal_coherence(acoustics)
        timbral_diversity = self._timbral_diversity(acoustics)
        pitch_convergence = self._pitch_convergence(notes)
        subtle_shift = self._subtle_shift_score(notes, acoustics)

        triune = self._triune_listen(
            motif=motif,
            entrainment=entrainment,
            epoch_validation=epoch_validation,
            tonal_coherence=tonal_coherence,
            timbral_diversity=timbral_diversity,
            pitch_convergence=pitch_convergence,
            subtle_shift=subtle_shift,
        )
        cues = self._conducting_cues(
            epoch_validation=epoch_validation,
            motif=motif,
            entrainment=entrainment,
            tonal_coherence=tonal_coherence,
            timbral_diversity=timbral_diversity,
            pitch_convergence=pitch_convergence,
            subtle_shift=subtle_shift,
        )

        reasons: list[str] = []
        if not epoch_validation.valid:
            reasons.extend(epoch_validation.reasons)
        if entrainment.false_unison_risk >= 0.5:
            reasons.append("counterfeit_harmony_risk")
        if motif.dissonance > motif.consonance:
            reasons.append("dissonance_dominant")
        if subtle_shift >= 0.5:
            reasons.append("subtle_acoustic_shift_detected")
        if timbral_diversity < 0.2 and len(acoustics) >= 2:
            reasons.append("timbral_narrowing")
        if pitch_convergence > 0.65 and entrainment.source_diversity >= 0.5:
            reasons.append("independent_pitch_convergence")

        body = {
            "hypothesis_id": hypothesis_id,
            "epoch_id": epoch.epoch_id,
            "score_id": epoch.score_id,
            "epoch_valid": epoch_validation.valid,
            "notes_digest": motif.notes_digest,
            "entrainment_receipt": entrainment.receipt_id,
            "cues": cues,
            "reasons": sorted(set(reasons)),
        }
        return QueenConductingReceipt(
            schema="hivenance_conducting_queen_v1",
            receipt_id="queen_" + _digest(body).split(":", 1)[1][:24],
            hypothesis_id=hypothesis_id,
            epoch_id=epoch.epoch_id,
            score_id=epoch.score_id,
            genre_mode=epoch.genre_mode,
            strictness_level=epoch.strictness_level,
            epoch_valid=epoch_validation.valid,
            voice_acoustics=tuple(acoustics),
            triune=triune,
            conducting_cues=tuple(cues),
            tonal_coherence=round(tonal_coherence, 6),
            timbral_diversity=round(timbral_diversity, 6),
            pitch_convergence=round(pitch_convergence, 6),
            subtle_shift_score=round(subtle_shift, 6),
            reasons=tuple(sorted(set(reasons))),
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )

    @staticmethod
    def _voice_acoustics(notes: Sequence[MotifNote]) -> list[VoiceAcoustics]:
        groups: dict[str, list[MotifNote]] = {}
        for note in notes:
            if not note.root_lineage_digest:
                continue
            groups.setdefault(note.root_lineage_digest, []).append(note)

        profiles: list[VoiceAcoustics] = []
        for root in sorted(groups):
            voice = sorted(groups[root], key=lambda n: (n.observed_at_ms, n.message_id))
            pitches = [
                float(n.expected_move_bps) * (_sign(n.direction) or 1)
                for n in voice
                if n.expected_move_bps is not None
            ]
            pitch_center = statistics.fmean(pitches) if pitches else None
            pitch_spread = statistics.pstdev(pitches) if len(pitches) >= 2 else (0.0 if pitches else None)

            signs = [_sign(n.direction) for n in voice if _sign(n.direction) != 0]
            if not signs:
                tone_stability = 0.0
            elif len(signs) == 1:
                tone_stability = 0.5
            else:
                flips = sum(1 for a, b in zip(signs, signs[1:]) if a != b)
                tone_stability = _clamp(1.0 - flips / max(1, len(signs) - 1))

            uncertainties = [
                _clamp(float(n.uncertainty))
                for n in voice
                if n.uncertainty is not None
            ]
            timbre_uncertainty = statistics.fmean(uncertainties) if uncertainties else 0.5
            accent_rate = sum(1 for n in voice if n.pulse_type is not None) / max(1, len(voice))
            evidence_diversity = len({n.evidence_root for n in voice if n.evidence_root}) / max(1, len(voice))

            times = [n.observed_at_ms for n in voice]
            intervals = [b - a for a, b in zip(times, times[1:]) if b > a]
            articulation = statistics.median(intervals) if intervals else None

            profiles.append(VoiceAcoustics(
                root_lineage_digest=root,
                family=voice[0].family,
                note_count=len(voice),
                bands=tuple(sorted({n.horizon_band for n in voice})),
                pitch_center_bps=None if pitch_center is None else round(pitch_center, 6),
                pitch_spread_bps=None if pitch_spread is None else round(float(pitch_spread), 6),
                tone_stability=round(tone_stability, 6),
                timbre_uncertainty=round(float(timbre_uncertainty), 6),
                timbre_accent_rate=round(float(accent_rate), 6),
                timbre_evidence_diversity=round(float(evidence_diversity), 6),
                articulation_ms=None if articulation is None else round(float(articulation), 3),
            ))
        return profiles

    @staticmethod
    def _tonal_coherence(acoustics: Sequence[VoiceAcoustics]) -> float:
        if not acoustics:
            return 0.0
        stabilities = [a.tone_stability for a in acoustics]
        uncertainty_penalty = statistics.fmean(a.timbre_uncertainty for a in acoustics)
        return _clamp(0.72 * statistics.fmean(stabilities) + 0.28 * (1.0 - uncertainty_penalty))

    @staticmethod
    def _timbral_diversity(acoustics: Sequence[VoiceAcoustics]) -> float:
        if len(acoustics) < 2:
            return 0.0
        families = len({a.family for a in acoustics}) / len(acoustics)
        texture = []
        for a in acoustics:
            texture.append((
                a.timbre_uncertainty,
                a.timbre_accent_rate,
                a.timbre_evidence_diversity,
            ))
        pair_distances = []
        for idx, left in enumerate(texture):
            for right in texture[idx + 1:]:
                distance = math.sqrt(sum((x - y) ** 2 for x, y in zip(left, right))) / math.sqrt(3.0)
                pair_distances.append(_clamp(distance))
        texture_diversity = statistics.fmean(pair_distances) if pair_distances else 0.0
        return _clamp(0.55 * families + 0.45 * texture_diversity)

    @staticmethod
    def _pitch_convergence(notes: Sequence[MotifNote]) -> float:
        # Convergence is assessed only within horizon band.
        by_band: dict[str, list[MotifNote]] = {}
        for n in notes:
            if n.independent_voice and n.root_lineage_digest and n.expected_move_bps is not None:
                by_band.setdefault(n.horizon_band, []).append(n)

        scores = []
        for band_notes in by_band.values():
            latest: dict[str, float] = {}
            for n in sorted(band_notes, key=lambda x: x.observed_at_ms):
                sign = _sign(n.direction)
                if sign:
                    latest[n.root_lineage_digest] = float(n.expected_move_bps) * sign
            values = list(latest.values())
            if len(values) < 2:
                continue
            scale = max(0.25, statistics.fmean(abs(v) for v in values))
            dispersion = statistics.pstdev(values) / scale
            scores.append(_clamp(1.0 - dispersion / 2.0))
        return _clamp(statistics.fmean(scores)) if scores else 0.0

    @staticmethod
    def _subtle_shift_score(
        notes: Sequence[MotifNote],
        acoustics: Sequence[VoiceAcoustics],
    ) -> float:
        if len(notes) < 4:
            return 0.0
        ordered = sorted(notes, key=lambda n: n.observed_at_ms)
        cut = len(ordered) // 2
        early = ordered[:cut]
        late = ordered[cut:]

        def signature(chunk: Sequence[MotifNote]) -> tuple[float, float, float]:
            pitches = [
                float(n.expected_move_bps) * (_sign(n.direction) or 1)
                for n in chunk
                if n.expected_move_bps is not None
            ]
            pitch = statistics.fmean(pitches) if pitches else 0.0
            uncertainty = statistics.fmean(
                [_clamp(float(n.uncertainty)) for n in chunk if n.uncertainty is not None]
                or [0.5]
            )
            accent = sum(1 for n in chunk if n.pulse_type is not None) / max(1, len(chunk))
            return pitch, uncertainty, accent

        ep, eu, ea = signature(early)
        lp, lu, la = signature(late)
        pitch_scale = max(0.25, abs(ep), abs(lp))
        pitch_shift = _clamp(abs(lp - ep) / (2.0 * pitch_scale))
        uncertainty_shift = _clamp(abs(lu - eu))
        accent_shift = _clamp(abs(la - ea))
        return _clamp(0.5 * pitch_shift + 0.3 * uncertainty_shift + 0.2 * accent_shift)

    @staticmethod
    def _triune_listen(
        *,
        motif: MotifScore,
        entrainment: EntrainmentReceipt,
        epoch_validation: EpochValidation,
        tonal_coherence: float,
        timbral_diversity: float,
        pitch_convergence: float,
        subtle_shift: float,
    ) -> TriuneListening:
        metatron: list[str] = []
        michael: list[str] = []
        loki: list[str] = []

        if entrainment.entrainment_strength > 0.6:
            metatron.append("hear_emergent_entrainment")
        if motif.crescendo > motif.decrescendo:
            metatron.append("hear_crescendo")
        if motif.cadence_strength > 0.6:
            metatron.append("hear_approaching_cadence")
        if tonal_coherence > 0.65:
            metatron.append("hear_tonal_coherence")

        if epoch_validation.valid:
            michael.append("epoch_in_tune")
        else:
            michael.append("epoch_out_of_tune")
            michael.extend(epoch_validation.reasons)
        if entrainment.source_diversity < 0.5:
            michael.append("source_diversity_thin")
        if timbral_diversity < 0.2:
            michael.append("timbre_too_narrow")

        if entrainment.false_unison_risk >= 0.5:
            loki.append("counterfeit_unison")
        if motif.dissonance > motif.consonance:
            loki.append("preserve_dissonance")
        if subtle_shift >= 0.5:
            loki.append("hidden_timbre_or_pitch_shift")
        if pitch_convergence > 0.65 and entrainment.source_diversity < 0.5:
            loki.append("pitch_convergence_may_be_echo")

        return TriuneListening(
            metatron_synthesis=tuple(metatron or ["listen"]),
            michael_validation=tuple(michael or ["hold_tuning"]),
            loki_counterpoint=tuple(loki or ["seek_counterpoint"]),
        )

    @staticmethod
    def _conducting_cues(
        *,
        epoch_validation: EpochValidation,
        motif: MotifScore,
        entrainment: EntrainmentReceipt,
        tonal_coherence: float,
        timbral_diversity: float,
        pitch_convergence: float,
        subtle_shift: float,
    ) -> list[str]:
        if not epoch_validation.valid:
            return ["REST", "REKEY_EPOCH"]

        cues: list[str] = ["LISTEN"]
        if entrainment.false_unison_risk >= 0.5:
            cues.extend(["DIMINUENDO_ECHO", "INVITE_COUNTERPOINT"])
        if motif.dissonance > motif.consonance:
            cues.append("SUSTAIN_DISSONANCE")
        if entrainment.convergence_gain > 0.15 and entrainment.crescendo_strength > 0:
            cues.append("FOLLOW_CRESCENDO")
        if pitch_convergence > 0.65 and entrainment.source_diversity >= 0.5:
            cues.append("MARK_CADENCE")
        if subtle_shift >= 0.5:
            cues.append("LISTEN_FOR_MODULATION")
        if timbral_diversity < 0.2 and len(entrainment.bands) > 0:
            cues.append("INVITE_NEW_TIMBRE")
        if tonal_coherence > 0.7 and motif.cadence_strength > 0.65:
            cues.append("SUSTAIN_PHRASE")
        return list(dict.fromkeys(cues))
