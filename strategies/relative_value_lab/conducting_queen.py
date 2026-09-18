from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .governance_epoch import ResearchGovernanceEpoch, ResearchGovernanceEpochService
from .musical_cognition import MotifNote, MotifScore
from .polyphonic_entrainment import EntrainmentReceipt
from .temporal_texture import TemporalTextureReceipt
from .edge_chorus_harmony import EdgeChorusHarmony
from .market_hunting import MotifHuntMatch
from .colony_correlation import ColonyCorrelationReceipt
from .causal_cascade import CausalCascadeReceipt
from .hive_pulse import HivePulse, HivePulseEngine
from .polyphonic_resonance import PolyphonicResonanceReceipt
from .mystique_variations import MystiqueFalsificationReceipt
from .cognitive_metabolism import CognitiveMetabolismReceipt


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
class VNSSensoryPulse:
    """One sensory accent arriving from the Verified Market Nervous System."""

    pulse_id: str
    observed_at_ms: int
    scope: str
    pulse_class: str
    amplitude: float
    confidence: float
    freshness: float
    evidence_root: str
    world_state_id: str
    world_state_hash: str
    features: Mapping[str, float] = field(default_factory=dict)
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
class TriuneScoreSheet:
    """One voice of the Queen's triple-minded score."""

    mind: str
    score_sheet_id: str
    motifs_heard: tuple[str, ...]
    dynamics: tuple[str, ...]
    cautions: tuple[str, ...]
    invitations: tuple[str, ...]
    intensity: float
    world_state_id: str
    epoch_id: str
    authority: str = RELATIVE_VALUE_AUTHORITY

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QueenNotationToken:
    """Research-only notation emitted by the Queen.

    The token does not authorize trading. It tells a research voice what musical
    role it may perform next inside the active score.
    """

    token_id: str
    issued_to_role: str
    notation: str
    intensity: float
    epoch_id: str
    score_id: str
    world_state_id: str
    world_state_hash: str
    issued_at_ms: int
    expires_at_ms: int
    required_companions: tuple[str, ...]
    response_class: str
    source_score_sheet_ids: tuple[str, ...]
    maximum_uses: int = 1
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QueenPolyphonicReceipt:
    schema: str
    receipt_id: str
    hypothesis_id: str
    epoch_id: str
    score_id: str
    genre_mode: str
    strictness_level: str

    # Continuous governance / musical listening
    epoch_consonance: float
    world_state_tension: float
    vns_pulse_energy: float
    vns_syncopation: float
    temporal_jitter: float
    temporal_drift: float
    temporal_burstiness: float
    temporal_entropy: float
    temporal_cadence_coherence: float
    edge_chorus_quality: float
    edge_mesh_entrainment: float
    edge_settlement: float
    hunt_pressure: float
    correlation_harmony: float
    cascade_strength: float
    cascade_crescendo: float
    hive_pulse_energy: float
    polyphonic_resonance: float
    cross_band_tension: float
    register_diversity: float
    overtone_coherence: float
    resonance_drift: float
    resonance_texture: str
    mystique_fragility: float
    mystique_survival_rate: float
    mystique_contamination_guard: bool
    metabolic_cbr: Optional[float]
    metabolic_tbcr: Optional[float]
    metabolic_cdi: float
    metabolic_strain: float
    cognitive_breath: float
    metabolism_texture: str
    tonal_coherence: float
    timbral_diversity: float
    pitch_convergence: float
    subtle_shift_score: float
    polyphonic_pressure: float

    voice_acoustics: tuple[VoiceAcoustics, ...]
    triune_scores: tuple[TriuneScoreSheet, ...]
    notation_tokens: tuple[QueenNotationToken, ...]
    conducting_gestures: tuple[str, ...]
    reasons: tuple[str, ...]

    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["voice_acoustics"] = tuple(v.to_dict() for v in self.voice_acoustics)
        payload["triune_scores"] = tuple(v.to_dict() for v in self.triune_scores)
        payload["notation_tokens"] = tuple(v.to_dict() for v in self.notation_tokens)
        return payload


class ConductingQueen:
    """Continuous polyphonic conductor for HiveNance research cognition.

    She listens through VNS sensory pulses, lawful motif notes, entrainment,
    harmony and epoch context. She does not collapse the hive to a binary state.

    The Queen continuously emits:
      * Metatron synthesis score;
      * Michael tuning / governance score;
      * Loki adversarial counterpoint score;
      * narrow research notation tokens derived from the current composition.

    Epoch validity constrains notation. It does not prevent listening.
    """

    version = "hivenance.conducting_queen.v2"

    def conduct(
        self,
        *,
        hypothesis_id: str,
        notes: Sequence[MotifNote],
        motif: MotifScore,
        entrainment: EntrainmentReceipt,
        epoch: ResearchGovernanceEpoch,
        vns_pulses: Sequence[VNSSensoryPulse] = (),
        harmonic_context: Mapping[str, float] | None = None,
        temporal_texture: TemporalTextureReceipt | None = None,
        edge_chorus: EdgeChorusHarmony | None = None,
        hunt_matches: Sequence[MotifHuntMatch] = (),
        correlations: Sequence[ColonyCorrelationReceipt] = (),
        cascade: CausalCascadeReceipt | None = None,
        hive_pulses: Sequence[HivePulse] = (),
        polyphonic_resonance: PolyphonicResonanceReceipt | None = None,
        mystique: MystiqueFalsificationReceipt | None = None,
        metabolism: CognitiveMetabolismReceipt | None = None,
        now_ms: int,
        world_state_id: str,
        world_state_hash: str,
        scope: str = "relative_value_lab",
    ) -> QueenPolyphonicReceipt:
        validation = ResearchGovernanceEpochService.validate(
            epoch,
            now_ms=now_ms,
            world_state_id=world_state_id,
            world_state_hash=world_state_hash,
            scope=scope,
        )

        epoch_consonance, world_state_tension = self._epoch_music(validation.reasons)
        acoustics = self._voice_acoustics(notes)
        tonal_coherence = self._tonal_coherence(acoustics)
        timbral_diversity = self._timbral_diversity(acoustics)
        pitch_convergence = self._pitch_convergence(notes)
        subtle_shift = self._subtle_shift_score(notes)

        pulse_energy, pulse_syncopation = self._vns_music(vns_pulses)

        temporal_jitter = float(temporal_texture.jitter_norm) if temporal_texture else 0.0
        temporal_drift = float(temporal_texture.drift_norm) if temporal_texture else 0.0
        temporal_burstiness = float(temporal_texture.burstiness) if temporal_texture else 0.0
        temporal_entropy = float(temporal_texture.entropy_signature) if temporal_texture else 0.0
        temporal_cadence = float(temporal_texture.cadence_coherence) if temporal_texture else motif.rhythmic_regularity

        edge_quality = float(edge_chorus.chorus_quality) if edge_chorus else 0.0
        edge_mesh = float(edge_chorus.mesh_entrainment) if edge_chorus else 0.0
        edge_settlement = float(edge_chorus.settlement) if edge_chorus else 0.0

        hunt_pressure = self._hunt_pressure(hunt_matches)
        correlation_harmony = self._correlation_harmony(correlations)
        cascade_strength = float(cascade.propagation_strength) if cascade else 0.0
        cascade_crescendo = float(cascade.crescendo) if cascade else 0.0
        hive_pulse_energy = self._hive_pulse_energy(hive_pulses, now_ms=now_ms)

        harmonic_context = dict(harmonic_context or {})
        resonance = _clamp(float(harmonic_context.get("resonance", 0.0)))
        discord = _clamp(float(harmonic_context.get("discord", motif.dissonance)))
        harmonic_confidence = _clamp(float(harmonic_context.get("confidence", 0.0)))

        spectrum_resonance = float(polyphonic_resonance.global_resonance) if polyphonic_resonance else resonance
        cross_band_tension = float(polyphonic_resonance.cross_band_tension) if polyphonic_resonance else 0.0
        register_diversity = float(polyphonic_resonance.register_diversity) if polyphonic_resonance else 0.0
        overtone_coherence = float(polyphonic_resonance.overtone_coherence) if polyphonic_resonance else 0.0
        resonance_drift = float(polyphonic_resonance.resonance_drift) if polyphonic_resonance else 0.0
        resonance_texture = polyphonic_resonance.texture if polyphonic_resonance else "UNHEARD"

        mystique_fragility = float(mystique.fragility_score) if mystique else 0.0
        mystique_survival = float(mystique.survival_rate) if mystique else 0.0
        mystique_guard = bool(mystique.contamination_guard_passed) if mystique else True

        metabolic_cbr = metabolism.cbr if metabolism else None
        metabolic_tbcr = metabolism.tbcr if metabolism else None
        metabolic_cdi = float(metabolism.cdi) if metabolism else 0.0
        metabolic_strain = float(metabolism.metabolic_strain) if metabolism else 0.0
        cognitive_breath = float(metabolism.breath) if metabolism else 1.0
        metabolism_texture = metabolism.texture if metabolism else "UNHEARD"

        polyphonic_pressure = _clamp(
            0.12 * motif.dynamic_intensity
            + 0.10 * motif.crescendo
            + 0.15 * entrainment.entrainment_strength
            + 0.10 * pulse_energy
            + 0.08 * tonal_coherence
            + 0.08 * pitch_convergence
            + 0.07 * resonance
            + 0.05 * harmonic_confidence
            + 0.05 * (1.0 - entrainment.false_unison_risk)
            + 0.06 * temporal_cadence
            + 0.04 * (1.0 - temporal_jitter)
            + 0.04 * (1.0 - temporal_burstiness)
            + 0.06 * edge_quality
            + 0.05 * hunt_pressure
            + 0.05 * correlation_harmony
            + 0.06 * cascade_strength
            + 0.06 * cascade_crescendo
            + 0.05 * hive_pulse_energy
            + 0.07 * spectrum_resonance
            + 0.04 * register_diversity
            + 0.04 * overtone_coherence
            + 0.03 * (1.0 - resonance_drift)
            + 0.04 * (1.0 - mystique_fragility)
        )

        triune_scores = self._write_triune_scores(
            hypothesis_id=hypothesis_id,
            motif=motif,
            entrainment=entrainment,
            epoch=epoch,
            epoch_consonance=epoch_consonance,
            world_state_tension=world_state_tension,
            pulse_energy=pulse_energy,
            pulse_syncopation=pulse_syncopation,
            tonal_coherence=tonal_coherence,
            timbral_diversity=timbral_diversity,
            pitch_convergence=pitch_convergence,
            subtle_shift=subtle_shift,
            resonance=resonance,
            discord=discord,
            temporal_texture=temporal_texture,
            edge_chorus=edge_chorus,
            hunt_matches=hunt_matches,
            correlations=correlations,
            cascade=cascade,
            hive_pulses=hive_pulses,
            polyphonic_resonance=polyphonic_resonance,
            mystique=mystique,
            metabolism=metabolism,
            polyphonic_pressure=polyphonic_pressure,
            world_state_id=world_state_id,
        )

        gestures = self._conducting_gestures(
            motif=motif,
            entrainment=entrainment,
            epoch_consonance=epoch_consonance,
            world_state_tension=world_state_tension,
            pulse_energy=pulse_energy,
            pulse_syncopation=pulse_syncopation,
            timbral_diversity=timbral_diversity,
            subtle_shift=subtle_shift,
            resonance=resonance,
            discord=discord,
            temporal_texture=temporal_texture,
            edge_chorus=edge_chorus,
            hunt_matches=hunt_matches,
            correlations=correlations,
            cascade=cascade,
            hive_pulses=hive_pulses,
            polyphonic_resonance=polyphonic_resonance,
            mystique=mystique,
            metabolism=metabolism,
            now_ms=now_ms,
        )

        notation = self._issue_notation(
            triune_scores=triune_scores,
            epoch=epoch,
            epoch_consonance=epoch_consonance,
            world_state_tension=world_state_tension,
            motif=motif,
            entrainment=entrainment,
            pulse_energy=pulse_energy,
            timbral_diversity=timbral_diversity,
            subtle_shift=subtle_shift,
            temporal_texture=temporal_texture,
            edge_chorus=edge_chorus,
            hunt_matches=hunt_matches,
            correlations=correlations,
            cascade=cascade,
            hive_pulses=hive_pulses,
            polyphonic_resonance=polyphonic_resonance,
            mystique=mystique,
            metabolism=metabolism,
            now_ms=now_ms,
            world_state_id=world_state_id,
            world_state_hash=world_state_hash,
        )

        reasons: list[str] = list(validation.reasons)
        if pulse_syncopation > 0.5:
            reasons.append("vns_syncopation_audible")
        if subtle_shift > 0.45:
            reasons.append("timbre_tone_pitch_shift_audible")
        if entrainment.false_unison_risk > 0.45:
            reasons.append("counterfeit_unison_pressure")
        if motif.dissonance > 0.4:
            reasons.append("dissonance_remains_musically_relevant")
        if temporal_jitter > 0.45:
            reasons.append("temporal_jitter_audible")
        if temporal_burstiness > 0.35:
            reasons.append("temporal_burstiness_audible")
        if temporal_drift > 0.45:
            reasons.append("cadence_drift_audible")
        if edge_chorus and edge_chorus.resolution_class != "consonant":
            reasons.append("edge_chorus_" + edge_chorus.resolution_class)
        if hunt_pressure > 0.5:
            reasons.append("motif_hunt_pressure")
        if correlation_harmony > 0.5:
            reasons.append("colony_correlation_harmony")
        if cascade_strength > 0.45:
            reasons.append("cascade_propagation_audible")
        if cascade_crescendo > 0.45:
            reasons.append("cascade_crescendo")
        if hive_pulse_energy > 0.35:
            reasons.append("hive_pulse_accent")
        if cross_band_tension > 0.55:
            reasons.append("cross_band_counterpoint")
        if resonance_drift > 0.45:
            reasons.append("polyphonic_modulation")
        if resonance_texture != "UNHEARD":
            reasons.append("resonance_texture_" + resonance_texture.lower())
        if mystique and mystique_fragility > 0.50:
            reasons.append("mystique_fragility_high")
        if mystique and mystique_survival > 0.75:
            reasons.append("synthetic_variation_survival_high")
        if mystique and not mystique_guard:
            reasons.append("mystique_contamination_guard_failed")
        if metabolism and metabolic_strain > 0.55:
            reasons.append("cognitive_metabolic_strain")
        if metabolism and metabolism.duplicate_pressure > 0.45:
            reasons.append("duplicate_evidence_burn")
        if metabolism and not metabolism.denominator_resolved:
            reasons.append("metabolic_settlement_unresolved")
        if polyphonic_pressure > 0.65:
            reasons.append("polyphonic_crescendo")

        body = {
            "hypothesis_id": hypothesis_id,
            "epoch_id": epoch.epoch_id,
            "score_id": epoch.score_id,
            "notes_digest": motif.notes_digest,
            "entrainment_receipt": entrainment.receipt_id,
            "triune_scores": [s.score_sheet_id for s in triune_scores],
            "notation": [t.token_id for t in notation],
            "pressure": round(polyphonic_pressure, 6),
        }
        return QueenPolyphonicReceipt(
            schema="hivenance_conducting_queen_v2",
            receipt_id="queen_" + _digest(body).split(":", 1)[1][:24],
            hypothesis_id=hypothesis_id,
            epoch_id=epoch.epoch_id,
            score_id=epoch.score_id,
            genre_mode=epoch.genre_mode,
            strictness_level=epoch.strictness_level,
            epoch_consonance=round(epoch_consonance, 6),
            world_state_tension=round(world_state_tension, 6),
            vns_pulse_energy=round(pulse_energy, 6),
            vns_syncopation=round(pulse_syncopation, 6),
            temporal_jitter=round(temporal_jitter, 6),
            temporal_drift=round(temporal_drift, 6),
            temporal_burstiness=round(temporal_burstiness, 6),
            temporal_entropy=round(temporal_entropy, 6),
            temporal_cadence_coherence=round(temporal_cadence, 6),
            edge_chorus_quality=round(edge_quality, 6),
            edge_mesh_entrainment=round(edge_mesh, 6),
            edge_settlement=round(edge_settlement, 6),
            hunt_pressure=round(hunt_pressure, 6),
            correlation_harmony=round(correlation_harmony, 6),
            cascade_strength=round(cascade_strength, 6),
            cascade_crescendo=round(cascade_crescendo, 6),
            hive_pulse_energy=round(hive_pulse_energy, 6),
            polyphonic_resonance=round(spectrum_resonance, 6),
            cross_band_tension=round(cross_band_tension, 6),
            register_diversity=round(register_diversity, 6),
            overtone_coherence=round(overtone_coherence, 6),
            resonance_drift=round(resonance_drift, 6),
            resonance_texture=resonance_texture,
            mystique_fragility=round(mystique_fragility, 6),
            mystique_survival_rate=round(mystique_survival, 6),
            mystique_contamination_guard=mystique_guard,
            metabolic_cbr=metabolic_cbr,
            metabolic_tbcr=metabolic_tbcr,
            metabolic_cdi=round(metabolic_cdi, 6),
            metabolic_strain=round(metabolic_strain, 6),
            cognitive_breath=round(cognitive_breath, 6),
            metabolism_texture=metabolism_texture,
            tonal_coherence=round(tonal_coherence, 6),
            timbral_diversity=round(timbral_diversity, 6),
            pitch_convergence=round(pitch_convergence, 6),
            subtle_shift_score=round(subtle_shift, 6),
            polyphonic_pressure=round(polyphonic_pressure, 6),
            voice_acoustics=tuple(acoustics),
            triune_scores=tuple(triune_scores),
            notation_tokens=tuple(notation),
            conducting_gestures=tuple(gestures),
            reasons=tuple(sorted(set(reasons))),
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )

    @staticmethod
    def _epoch_music(reasons: Sequence[str]) -> tuple[float, float]:
        if not reasons:
            return 1.0, 0.0
        weights = {
            "epoch_not_active": 0.40,
            "epoch_not_started": 0.30,
            "epoch_expired": 0.30,
            "epoch_world_state_drift": 0.55,
            "epoch_scope_mismatch": 0.45,
            "epoch_id_mismatch": 0.50,
            "score_id_mismatch": 0.45,
            "epoch_authority_mismatch": 0.70,
            "epoch_authority_escalation_forbidden": 1.0,
        }
        tension = _clamp(sum(weights.get(reason, 0.20) for reason in set(reasons)))
        return _clamp(1.0 - tension), tension

    @staticmethod
    def _vns_music(pulses: Sequence[VNSSensoryPulse]) -> tuple[float, float]:
        if not pulses:
            return 0.0, 0.0
        ordered = sorted(pulses, key=lambda p: (p.observed_at_ms, p.pulse_id))
        energy = statistics.fmean(
            _clamp(p.amplitude) * _clamp(p.confidence) * _clamp(p.freshness)
            for p in ordered
        )
        if len(ordered) < 3:
            return _clamp(energy), 0.0
        times = [p.observed_at_ms for p in ordered]
        intervals = [b - a for a, b in zip(times, times[1:]) if b > a]
        if len(intervals) < 2:
            return _clamp(energy), 0.0
        mean = statistics.fmean(intervals)
        if mean <= 0:
            return _clamp(energy), 0.0
        cv = statistics.pstdev(intervals) / mean
        return _clamp(energy), _clamp(cv)

    @staticmethod
    def _hunt_pressure(matches: Sequence[MotifHuntMatch]) -> float:
        if not matches:
            return 0.0
        return _clamp(statistics.fmean(float(m.research_priority) for m in matches))

    @staticmethod
    def _correlation_harmony(rows: Sequence[ColonyCorrelationReceipt]) -> float:
        if not rows:
            return 0.0
        independent = [
            float(r.confidence)
            for r in rows
            if not r.shared_lineage and not r.shared_evidence_root
        ]
        if independent:
            return _clamp(statistics.fmean(independent))
        return _clamp(0.5 * statistics.fmean(float(r.confidence) for r in rows))

    @staticmethod
    def _hive_pulse_energy(pulses: Sequence[HivePulse], *, now_ms: int) -> float:
        if not pulses:
            return 0.0
        live = [
            HivePulseEngine.decay(pulse, now_ms=now_ms)
            for pulse in pulses
            if pulse.world_state_id
        ]
        active = [row for row in live if not row.expired]
        if not active:
            return 0.0
        return _clamp(statistics.fmean(
            row.effective_amplitude * row.effective_confidence
            for row in active
        ))

    @staticmethod
    def _voice_acoustics(notes: Sequence[MotifNote]) -> list[VoiceAcoustics]:
        groups: dict[str, list[MotifNote]] = {}
        for note in notes:
            if note.root_lineage_digest:
                groups.setdefault(note.root_lineage_digest, []).append(note)

        profiles: list[VoiceAcoustics] = []
        for root in sorted(groups):
            voice = sorted(groups[root], key=lambda n: (n.observed_at_ms, n.message_id))
            pitches = [
                float(n.expected_move_bps) * (_sign(n.direction) or 1)
                for n in voice if n.expected_move_bps is not None
            ]
            pitch_center = statistics.fmean(pitches) if pitches else None
            pitch_spread = statistics.pstdev(pitches) if len(pitches) >= 2 else (0.0 if pitches else None)

            signs = [_sign(n.direction) for n in voice if _sign(n.direction)]
            if not signs:
                tone_stability = 0.0
            elif len(signs) == 1:
                tone_stability = 0.5
            else:
                flips = sum(1 for a, b in zip(signs, signs[1:]) if a != b)
                tone_stability = _clamp(1.0 - flips / max(1, len(signs) - 1))

            uncertainties = [_clamp(float(n.uncertainty)) for n in voice if n.uncertainty is not None]
            uncertainty = statistics.fmean(uncertainties) if uncertainties else 0.5
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
                timbre_uncertainty=round(float(uncertainty), 6),
                timbre_accent_rate=round(float(accent_rate), 6),
                timbre_evidence_diversity=round(float(evidence_diversity), 6),
                articulation_ms=None if articulation is None else round(float(articulation), 3),
            ))
        return profiles

    @staticmethod
    def _tonal_coherence(acoustics: Sequence[VoiceAcoustics]) -> float:
        if not acoustics:
            return 0.0
        stable = statistics.fmean(a.tone_stability for a in acoustics)
        uncertainty = statistics.fmean(a.timbre_uncertainty for a in acoustics)
        return _clamp(0.72 * stable + 0.28 * (1.0 - uncertainty))

    @staticmethod
    def _timbral_diversity(acoustics: Sequence[VoiceAcoustics]) -> float:
        if len(acoustics) < 2:
            return 0.0
        family_diversity = len({a.family for a in acoustics}) / len(acoustics)
        pair_distances = []
        for idx, left in enumerate(acoustics):
            lv = (left.timbre_uncertainty, left.timbre_accent_rate, left.timbre_evidence_diversity)
            for right in acoustics[idx + 1:]:
                rv = (right.timbre_uncertainty, right.timbre_accent_rate, right.timbre_evidence_diversity)
                pair_distances.append(
                    math.sqrt(sum((a - b) ** 2 for a, b in zip(lv, rv))) / math.sqrt(3.0)
                )
        texture = statistics.fmean(pair_distances) if pair_distances else 0.0
        return _clamp(0.55 * family_diversity + 0.45 * texture)

    @staticmethod
    def _pitch_convergence(notes: Sequence[MotifNote]) -> float:
        by_band: dict[str, list[MotifNote]] = {}
        for note in notes:
            if note.independent_voice and note.root_lineage_digest and note.expected_move_bps is not None:
                by_band.setdefault(note.horizon_band, []).append(note)
        values = []
        for band_notes in by_band.values():
            latest: dict[str, float] = {}
            for note in sorted(band_notes, key=lambda n: n.observed_at_ms):
                sign = _sign(note.direction)
                if sign:
                    latest[note.root_lineage_digest] = float(note.expected_move_bps) * sign
            pitches = list(latest.values())
            if len(pitches) < 2:
                continue
            scale = max(0.25, statistics.fmean(abs(v) for v in pitches))
            values.append(_clamp(1.0 - statistics.pstdev(pitches) / (2.0 * scale)))
        return _clamp(statistics.fmean(values)) if values else 0.0

    @staticmethod
    def _subtle_shift_score(notes: Sequence[MotifNote]) -> float:
        if len(notes) < 4:
            return 0.0
        ordered = sorted(notes, key=lambda n: n.observed_at_ms)
        cut = len(ordered) // 2
        early, late = ordered[:cut], ordered[cut:]

        def signature(chunk: Sequence[MotifNote]) -> tuple[float, float, float]:
            pitches = [
                float(n.expected_move_bps) * (_sign(n.direction) or 1)
                for n in chunk if n.expected_move_bps is not None
            ]
            pitch = statistics.fmean(pitches) if pitches else 0.0
            uncertainty = statistics.fmean(
                [_clamp(float(n.uncertainty)) for n in chunk if n.uncertainty is not None] or [0.5]
            )
            accent = sum(1 for n in chunk if n.pulse_type is not None) / max(1, len(chunk))
            return pitch, uncertainty, accent

        ep, eu, ea = signature(early)
        lp, lu, la = signature(late)
        scale = max(0.25, abs(ep), abs(lp))
        return _clamp(
            0.5 * _clamp(abs(lp - ep) / (2.0 * scale))
            + 0.3 * _clamp(abs(lu - eu))
            + 0.2 * _clamp(abs(la - ea))
        )

    def _write_triune_scores(
        self,
        *,
        hypothesis_id: str,
        motif: MotifScore,
        entrainment: EntrainmentReceipt,
        epoch: ResearchGovernanceEpoch,
        epoch_consonance: float,
        world_state_tension: float,
        pulse_energy: float,
        pulse_syncopation: float,
        tonal_coherence: float,
        timbral_diversity: float,
        pitch_convergence: float,
        subtle_shift: float,
        resonance: float,
        discord: float,
        temporal_texture: TemporalTextureReceipt | None,
        edge_chorus: EdgeChorusHarmony | None,
        hunt_matches: Sequence[MotifHuntMatch],
        correlations: Sequence[ColonyCorrelationReceipt],
        cascade: CausalCascadeReceipt | None,
        hive_pulses: Sequence[HivePulse],
        polyphonic_resonance: PolyphonicResonanceReceipt | None,
        mystique: MystiqueFalsificationReceipt | None,
        metabolism: CognitiveMetabolismReceipt | None,
        polyphonic_pressure: float,
        world_state_id: str,
    ) -> list[TriuneScoreSheet]:
        scores: list[TriuneScoreSheet] = []

        metatron_motifs = [
            f"motif_cadence:{motif.cadence_strength:.3f}",
            f"entrainment:{entrainment.entrainment_strength:.3f}",
            f"polyphonic_pressure:{polyphonic_pressure:.3f}",
            f"vns_energy:{pulse_energy:.3f}",
            f"temporal_cadence:{(temporal_texture.cadence_coherence if temporal_texture else motif.rhythmic_regularity):.3f}",
            f"edge_chorus:{(edge_chorus.chorus_quality if edge_chorus else 0.0):.3f}",
            f"hunt_pressure:{self._hunt_pressure(hunt_matches):.3f}",
            f"correlation_harmony:{self._correlation_harmony(correlations):.3f}",
            f"cascade_strength:{(cascade.propagation_strength if cascade else 0.0):.3f}",
            f"cascade_crescendo:{(cascade.crescendo if cascade else 0.0):.3f}",
            f"register_diversity:{(polyphonic_resonance.register_diversity if polyphonic_resonance else 0.0):.3f}",
            f"overtone_coherence:{(polyphonic_resonance.overtone_coherence if polyphonic_resonance else 0.0):.3f}",
            f"cross_band_tension:{(polyphonic_resonance.cross_band_tension if polyphonic_resonance else 0.0):.3f}",
            f"mystique_survival:{(mystique.survival_rate if mystique else 0.0):.3f}",
            f"mystique_fragility:{(mystique.fragility_score if mystique else 0.0):.3f}",
            f"metabolic_strain:{(metabolism.metabolic_strain if metabolism else 0.0):.3f}",
            f"cognitive_breath:{(metabolism.breath if metabolism else 1.0):.3f}",
        ]
        metatron_dynamics = []
        if motif.crescendo > motif.decrescendo:
            metatron_dynamics.append("crescendo")
        if pulse_syncopation > 0.35:
            metatron_dynamics.append("syncopated_vns")
        if pitch_convergence > 0.55:
            metatron_dynamics.append("pitch_converging")
        if subtle_shift > 0.4:
            metatron_dynamics.append("modulation_emerging")
        if temporal_texture and temporal_texture.burstiness > 0.35:
            metatron_dynamics.append("burst_phrase")
        if temporal_texture and temporal_texture.jitter_norm > 0.45:
            metatron_dynamics.append("jittered_cadence")
        if edge_chorus and edge_chorus.resolution_class != "consonant":
            metatron_dynamics.append("edge_" + edge_chorus.resolution_class)
        if cascade and cascade.depth > 0:
            metatron_dynamics.append("cascade_depth_" + str(cascade.depth))
        if cascade and cascade.crescendo > 0.45:
            metatron_dynamics.append("cascade_crescendo")
        if hive_pulses:
            metatron_dynamics.append("hive_pulse_accent")
        if polyphonic_resonance:
            metatron_dynamics.append("resonance_" + polyphonic_resonance.texture.lower())
        if mystique:
            metatron_dynamics.append("theme_and_variations_tested")
        if metabolism:
            metatron_dynamics.append("metabolism_" + metabolism.texture.lower())
        scores.append(self._score_sheet(
            mind="METATRON",
            motifs=metatron_motifs,
            dynamics=metatron_dynamics,
            cautions=(),
            invitations=("weave_full_score", "listen_across_horizons"),
            intensity=polyphonic_pressure,
            world_state_id=world_state_id,
            epoch=epoch,
        ))

        michael_cautions = [
            f"epoch_consonance:{epoch_consonance:.3f}",
            f"world_state_tension:{world_state_tension:.3f}",
            f"source_diversity:{entrainment.source_diversity:.3f}",
            f"timing_jitter:{(temporal_texture.jitter_norm if temporal_texture else 0.0):.3f}",
            f"timing_drift:{(temporal_texture.drift_norm if temporal_texture else 0.0):.3f}",
            f"burstiness:{(temporal_texture.burstiness if temporal_texture else 0.0):.3f}",
            f"entropy:{(temporal_texture.entropy_signature if temporal_texture else 0.0):.3f}",
            f"edge_mesh:{(edge_chorus.mesh_entrainment if edge_chorus else 0.0):.3f}",
            f"edge_settlement:{(edge_chorus.settlement if edge_chorus else 0.0):.3f}",
        ]
        michael_invites = ["retune_if_world_state_drifts"]
        if epoch_consonance < 0.7:
            michael_invites.append("narrow_notation")
        if timbral_diversity < 0.3:
            michael_invites.append("request_new_timbre")
        if temporal_texture and temporal_texture.cadence_coherence < 0.55:
            michael_invites.append("retune_cadence_baseline")
        if edge_chorus and edge_chorus.chorus_quality < 0.78:
            michael_invites.append("rehearse_edge_chorus")
        if any(r.shared_lineage or r.shared_evidence_root for r in correlations):
            michael_invites.append("discount_dependent_correlation")
        if cascade and any(not edge.accepted for edge in cascade.edges):
            michael_invites.append("repair_cascade_evidence")
        if any(p.authority_effect == "REDUCE_OR_FREEZE_ONLY" for p in hive_pulses):
            michael_invites.append("honour_negative_pulse")
        if polyphonic_resonance and polyphonic_resonance.resonance_drift > 0.45:
            michael_invites.append("retune_polyphonic_registers")
        if mystique and not mystique.contamination_guard_passed:
            michael_invites.append("seal_synthetic_chamber")
        if mystique and not mystique.prospective_evidence_eligible:
            michael_invites.append("keep_synthetic_out_of_prospective_truth")
        if metabolism and not metabolism.denominator_resolved:
            michael_invites.append("keep_burn_denominator_unresolved")
        if metabolism and metabolism.duplicate_pressure > 0.45:
            michael_invites.append("discount_duplicate_rehearsal")
        if metabolism and metabolism.metabolic_strain > 0.55:
            michael_invites.append("thin_orchestration")
        scores.append(self._score_sheet(
            mind="MICHAEL",
            motifs=(f"tonal_coherence:{tonal_coherence:.3f}",),
            dynamics=(f"harmony_resonance:{resonance:.3f}",),
            cautions=michael_cautions,
            invitations=michael_invites,
            intensity=_clamp(0.5 * world_state_tension + 0.5 * (1.0 - epoch_consonance)),
            world_state_id=world_state_id,
            epoch=epoch,
        ))

        loki_cautions = [
            f"false_unison:{entrainment.false_unison_risk:.3f}",
            f"discord:{discord:.3f}",
            f"subtle_shift:{subtle_shift:.3f}",
            f"burstiness:{(temporal_texture.burstiness if temporal_texture else 0.0):.3f}",
            f"jitter:{(temporal_texture.jitter_norm if temporal_texture else 0.0):.3f}",
            f"edge_resolution:{(edge_chorus.resolution_class if edge_chorus else 'unheard')}",
        ]
        loki_invites = ["seek_countermelody", "challenge_apparent_resolution"]
        if pitch_convergence > 0.55:
            loki_invites.append("test_pitch_convergence_for_echo")
        if motif.dissonance > 0.35:
            loki_invites.append("preserve_productive_dissonance")
        if temporal_texture and temporal_texture.burstiness > 0.35:
            loki_invites.append("challenge_burst_for_artifact")
        if temporal_texture and temporal_texture.jitter_norm > 0.45:
            loki_invites.append("challenge_jitter_for_instability")
        if edge_chorus and edge_chorus.resolution_class != "consonant":
            loki_invites.append("challenge_edge_resolution")
        if hunt_matches:
            loki_invites.append("falsify_hunt_motif")
        if correlations:
            loki_invites.append("challenge_correlation_not_causation")
        if cascade:
            loki_invites.append("challenge_propagation_mechanism")
        if hive_pulses:
            loki_invites.append("challenge_pulse_amplification")
        if polyphonic_resonance and polyphonic_resonance.cross_band_tension > 0.55:
            loki_invites.append("preserve_cross_band_counterpoint")
        if mystique:
            loki_invites.append("interrogate_counterfactual_failures")
            if mystique.fragility_score > 0.50:
                loki_invites.append("challenge_fragile_cadence")
            if mystique.critical_dependencies:
                loki_invites.append("attack_critical_dependencies")
        if metabolism:
            if metabolism.information_efficiency < 0.25:
                loki_invites.append("challenge_low_information_rehearsal")
            if metabolism.duplicate_pressure > 0.45:
                loki_invites.append("seek_non_echo_evidence")
        scores.append(self._score_sheet(
            mind="LOKI",
            motifs=(f"counterpoint_diversity:{motif.counterpoint_diversity:.3f}",),
            dynamics=(f"tension:{motif.tension:.3f}",),
            cautions=loki_cautions,
            invitations=loki_invites,
            intensity=_clamp(0.45 * discord + 0.35 * entrainment.false_unison_risk + 0.20 * subtle_shift),
            world_state_id=world_state_id,
            epoch=epoch,
        ))
        return scores

    @staticmethod
    def _score_sheet(
        *,
        mind: str,
        motifs: Sequence[str],
        dynamics: Sequence[str],
        cautions: Sequence[str],
        invitations: Sequence[str],
        intensity: float,
        world_state_id: str,
        epoch: ResearchGovernanceEpoch,
    ) -> TriuneScoreSheet:
        body = {
            "mind": mind,
            "motifs": list(motifs),
            "dynamics": list(dynamics),
            "cautions": list(cautions),
            "invitations": list(invitations),
            "intensity": round(_clamp(intensity), 6),
            "epoch_id": epoch.epoch_id,
            "world_state_id": world_state_id,
        }
        return TriuneScoreSheet(
            mind=mind,
            score_sheet_id="tri_" + _digest(body).split(":", 1)[1][:24],
            motifs_heard=tuple(motifs),
            dynamics=tuple(dynamics),
            cautions=tuple(cautions),
            invitations=tuple(invitations),
            intensity=round(_clamp(intensity), 6),
            world_state_id=world_state_id,
            epoch_id=epoch.epoch_id,
            authority=RELATIVE_VALUE_AUTHORITY,
        )

    def _conducting_gestures(
        self,
        *,
        motif: MotifScore,
        entrainment: EntrainmentReceipt,
        epoch_consonance: float,
        world_state_tension: float,
        pulse_energy: float,
        pulse_syncopation: float,
        timbral_diversity: float,
        subtle_shift: float,
        resonance: float,
        discord: float,
        temporal_texture: TemporalTextureReceipt | None,
        edge_chorus: EdgeChorusHarmony | None,
        hunt_matches: Sequence[MotifHuntMatch],
        correlations: Sequence[ColonyCorrelationReceipt],
        cascade: CausalCascadeReceipt | None,
        hive_pulses: Sequence[HivePulse],
        polyphonic_resonance: PolyphonicResonanceReceipt | None,
        mystique: MystiqueFalsificationReceipt | None,
        metabolism: CognitiveMetabolismReceipt | None,
        now_ms: int,
    ) -> list[str]:
        gestures = ["LISTEN_CONTINUOUSLY"]
        if pulse_energy > 0.35:
            gestures.append("FOLLOW_VNS_PULSE")
        if pulse_syncopation > 0.35:
            gestures.append("ACCENT_SYNCOPATION")
        if entrainment.convergence_gain > 0:
            gestures.append("GUIDE_ENTRAINMENT")
        if motif.crescendo > motif.decrescendo:
            gestures.append("SHAPE_CRESCENDO")
        if discord > resonance:
            gestures.append("HOLD_DISSONANCE_OPEN")
        if subtle_shift > 0.4:
            gestures.append("HEAR_MODULATION")
        if timbral_diversity < 0.3:
            gestures.append("INVITE_NEW_TIMBRE")
        if temporal_texture and temporal_texture.jitter_norm > 0.45:
            gestures.append("FOLLOW_JITTER")
        if temporal_texture and temporal_texture.burstiness > 0.35:
            gestures.append("SHAPE_BURST")
        if temporal_texture and temporal_texture.entropy_signature > 0.75:
            gestures.append("HEAR_ENTROPY")
        if edge_chorus and edge_chorus.chorus_quality < 0.78:
            gestures.append("REHEARSE_EDGE_CHORUS")
        if edge_chorus and edge_chorus.settlement < 0.75:
            gestures.append("HOLD_CODA_OPEN")
        if hunt_matches:
            gestures.append("AMPLIFY_SEARCH")
        if any(r.shared_assets for r in correlations):
            gestures.append("TRACE_SHARED_ASSET")
        if correlations and self._correlation_harmony(correlations) > 0.45:
            gestures.append("WEAVE_COLONY_COUNTERPOINT")
        if cascade and cascade.propagation_strength > 0.30:
            gestures.append("FOLLOW_CASCADE")
        if cascade and cascade.crescendo > 0.40:
            gestures.append("SHAPE_CASCADE_CRESCENDO")
        if cascade and len(cascade.scope_path) > 1:
            gestures.append("EXPAND_LISTENING_SCOPE")
        if self._hive_pulse_energy(hive_pulses, now_ms=now_ms) > 0.30:
            gestures.append("ACCENT_HIVE_PULSE")
        if polyphonic_resonance:
            if polyphonic_resonance.texture == "COUNTERPOINT":
                gestures.append("CONDUCT_COUNTERPOINT")
            elif polyphonic_resonance.texture == "FULL_CHORD":
                gestures.append("SUSTAIN_FULL_CHORD")
            elif polyphonic_resonance.texture == "SUSPENDED":
                gestures.append("HOLD_SUSPENSION")
            elif polyphonic_resonance.texture == "MODULATING":
                gestures.append("FOLLOW_REGISTER_MODULATION")
        if mystique:
            if mystique.fragility_score > 0.50:
                gestures.append("HOLD_FRAGILE_CADENCE")
            elif mystique.survival_rate > 0.75:
                gestures.append("NOTE_SYNTHETIC_ROBUSTNESS")
        if metabolism:
            if metabolism.metabolic_strain > 0.70:
                gestures.append("THIN_ORCHESTRATION")
            if metabolism.unresolved_burn > 0.65:
                gestures.append("LET_MOTIF_REST")
            if metabolism.duplicate_pressure > 0.45:
                gestures.append("INVITE_FRESH_TIMBRE")
            if metabolism.breath > 0.75 and metabolism.evidence_novelty > 0.55:
                gestures.append("SUSTAIN_COGNITIVE_BREATH")
        if any(
            p.authority_effect == "REDUCE_OR_FREEZE_ONLY"
            and not HivePulseEngine.decay(p, now_ms=now_ms).expired
            for p in hive_pulses
        ):
            gestures.append("HOLD_FREEZE_ACCENT")
        if epoch_consonance < 0.8 or world_state_tension > 0.2:
            gestures.append("REKEY_PROGRESSIVELY")
        return list(dict.fromkeys(gestures))

    def _issue_notation(
        self,
        *,
        triune_scores: Sequence[TriuneScoreSheet],
        epoch: ResearchGovernanceEpoch,
        epoch_consonance: float,
        world_state_tension: float,
        motif: MotifScore,
        entrainment: EntrainmentReceipt,
        pulse_energy: float,
        timbral_diversity: float,
        subtle_shift: float,
        temporal_texture: TemporalTextureReceipt | None,
        edge_chorus: EdgeChorusHarmony | None,
        hunt_matches: Sequence[MotifHuntMatch],
        correlations: Sequence[ColonyCorrelationReceipt],
        cascade: CausalCascadeReceipt | None,
        hive_pulses: Sequence[HivePulse],
        polyphonic_resonance: PolyphonicResonanceReceipt | None,
        mystique: MystiqueFalsificationReceipt | None,
        metabolism: CognitiveMetabolismReceipt | None,
        now_ms: int,
        world_state_id: str,
        world_state_hash: str,
    ) -> list[QueenNotationToken]:
        # Notation becomes narrower as epoch/world-state tension increases.
        # Listening continues at all times.
        base_ttl = max(5_000, int((epoch.expires_at_ms - now_ms) * _clamp(epoch_consonance, 0.1, 1.0)))
        expiry = min(epoch.expires_at_ms, now_ms + base_ttl)
        score_ids = tuple(s.score_sheet_id for s in triune_scores)

        phrases: list[tuple[str, str, float, tuple[str, ...], str]] = []

        phrases.append((
            "all_research_voices",
            "LISTEN",
            _clamp(0.35 + 0.45 * pulse_energy),
            ("world_state_bind",),
            "OBSERVE_AND_WAGGLE",
        ))

        if entrainment.convergence_gain > 0:
            phrases.append((
                "independent_counterpoint",
                "ANSWER_MOTIF",
                _clamp(0.35 + 0.5 * entrainment.entrainment_strength),
                ("harmony_law", "lineage_registry"),
                "FOLLOW_OR_DISSENT",
            ))

        if timbral_diversity < 0.35:
            phrases.append((
                "unheard_lineage",
                "ENTER_WITH_NEW_TIMBRE",
                _clamp(0.4 + 0.4 * (1.0 - timbral_diversity)),
                ("harmony_law",),
                "SEARCH_OR_DISSENT",
            ))

        if subtle_shift > 0.35:
            phrases.append((
                "market_hunter",
                "TRACE_MODULATION",
                _clamp(0.35 + 0.5 * subtle_shift),
                ("vns", "world_state_bind"),
                "SEARCH",
            ))

        if motif.dissonance > 0.35 or entrainment.false_unison_risk > 0.4:
            phrases.append((
                "loki_counterpoint",
                "CHALLENGE_CADENCE",
                _clamp(0.4 + 0.4 * max(motif.dissonance, entrainment.false_unison_risk)),
                ("triune_loki", "harmony_law"),
                "DISSENT_OR_SEARCH",
            ))

        if temporal_texture and (
            temporal_texture.jitter_norm > 0.45
            or temporal_texture.burstiness > 0.35
            or temporal_texture.drift_norm > 0.45
        ):
            phrases.append((
                "harmonic_listener",
                "TRACE_TEMPORAL_TEXTURE",
                _clamp(0.35 + 0.25 * temporal_texture.jitter_norm + 0.25 * temporal_texture.burstiness),
                ("vns", "harmonic_governance"),
                "SEARCH_OR_COUNTERPOINT",
            ))

        if edge_chorus and edge_chorus.chorus_quality < 0.78:
            phrases.append((
                "edge_chorus",
                "REHEARSE_EDGE_RESOLUTION",
                _clamp(0.45 + 0.45 * (1.0 - edge_chorus.chorus_quality)),
                ("governance_epoch", "edge_chorus", "audit"),
                "REPAIR_RESEARCH_PHRASE",
            ))

        if hunt_matches:
            phrases.append((
                "market_hunter",
                "AMPLIFY_SEARCH",
                _clamp(0.35 + 0.5 * self._hunt_pressure(hunt_matches)),
                ("vns", "harmony_law", "world_state_bind"),
                "SEARCH_OR_ALARM",
            ))

        if any(r.shared_assets for r in correlations):
            phrases.append((
                "colony_correlator",
                "TRACE_SHARED_ASSET",
                _clamp(0.35 + 0.45 * self._correlation_harmony(correlations)),
                ("lineage_registry", "world_state_bind"),
                "CORRELATE_WITHOUT_CAUSAL_CLAIM",
            ))

        if correlations and self._correlation_harmony(correlations) > 0.45:
            phrases.append((
                "independent_counterpoint",
                "INVITE_INDEPENDENT_CORROBORATION",
                _clamp(0.40 + 0.40 * self._correlation_harmony(correlations)),
                ("harmony_law", "lineage_registry"),
                "FOLLOW_DISSENT_OR_SEARCH",
            ))

        if cascade and cascade.propagation_strength > 0.30:
            phrases.append((
                "cascade_listener",
                "TRACE_PROPAGATION",
                _clamp(0.35 + 0.45 * cascade.propagation_strength),
                ("world_state_bind", "cascade_evidence"),
                "FOLLOW_OR_CHALLENGE_PROPAGATION",
            ))

        if cascade and cascade.crescendo > 0.40:
            phrases.append((
                "hive_pulse",
                "ACCENT_CRESCENDO",
                _clamp(0.35 + 0.50 * cascade.crescendo),
                ("cascade_evidence", "harmony_law"),
                "PULSE_OR_DISSENT",
            ))

        if any(
            p.authority_effect == "REDUCE_OR_FREEZE_ONLY"
            and not HivePulseEngine.decay(p, now_ms=now_ms).expired
            for p in hive_pulses
        ):
            phrases.append((
                "michael_tuning",
                "HOLD_FREEZE_ACCENT",
                0.90,
                ("hive_pulse", "governance_epoch"),
                "REDUCE_OR_FREEZE_RESEARCH_ONLY",
            ))

        if polyphonic_resonance and polyphonic_resonance.texture == "COUNTERPOINT":
            phrases.append((
                "polyphonic_choir",
                "PRESERVE_COUNTERPOINT",
                _clamp(0.40 + 0.40 * polyphonic_resonance.cross_band_tension),
                ("harmonic_governance", "harmony_law"),
                "SING_REGISTER_WITHOUT_COLLAPSE",
            ))

        if polyphonic_resonance and polyphonic_resonance.texture == "MODULATING":
            phrases.append((
                "polyphonic_choir",
                "TRACE_REGISTER_MODULATION",
                _clamp(0.40 + 0.40 * polyphonic_resonance.resonance_drift),
                ("world_state_bind", "harmonic_governance"),
                "SEARCH_OR_DISSENT",
            ))

        if mystique is None and (
            motif.cadence_strength > 0.55
            or entrainment.entrainment_strength > 0.55
        ):
            phrases.append((
                "loki_counterpoint",
                "RUN_MYSTIQUE_VARIATIONS",
                _clamp(0.45 + 0.35 * max(motif.cadence_strength, entrainment.entrainment_strength)),
                ("world_state_bind", "synthetic_namespace", "triune_loki"),
                "SYNTHETIC_FALSIFICATION_ONLY",
            ))

        if mystique and mystique.fragility_score > 0.50:
            phrases.append((
                "loki_counterpoint",
                "CHALLENGE_FRAGILE_CADENCE",
                _clamp(0.45 + 0.45 * mystique.fragility_score),
                ("mystique", "harmony_law"),
                "DISSENT_OR_SEARCH",
            ))

        if mystique and not mystique.contamination_guard_passed:
            phrases.append((
                "michael_tuning",
                "SEAL_SYNTHETIC_CHAMBER",
                1.0,
                ("mystique", "governance_epoch"),
                "RESEARCH_ISOLATION_ONLY",
            ))

        if metabolism and metabolism.metabolic_strain > 0.70:
            phrases.append((
                "cognition_fabric",
                "THIN_ORCHESTRATION",
                _clamp(0.45 + 0.45 * metabolism.metabolic_strain),
                ("cognitive_metabolism", "triune_michael"),
                "REDUCE_RESEARCH_DENSITY",
            ))

        if metabolism and metabolism.unresolved_burn > 0.65:
            phrases.append((
                "motif_choir",
                "LET_MOTIF_REST",
                _clamp(0.45 + 0.40 * metabolism.unresolved_burn),
                ("cognitive_metabolism", "world_state_bind"),
                "REST_AND_AWAIT_FRESH_EVIDENCE",
            ))

        if metabolism and metabolism.duplicate_pressure > 0.45:
            phrases.append((
                "independent_counterpoint",
                "SEEK_FRESH_EVIDENCE",
                _clamp(0.40 + 0.40 * metabolism.duplicate_pressure),
                ("lineage_registry", "harmony_law"),
                "SEARCH_NEW_LINEAGE_OR_REST",
            ))

        if epoch_consonance < 0.75 or world_state_tension > 0.25:
            phrases.append((
                "michael_tuning",
                "REKEY_SCORE",
                _clamp(0.45 + 0.45 * world_state_tension),
                ("governance_epoch", "world_state_bind"),
                "RETUNE_RESEARCH_CONTEXT",
            ))

        tokens: list[QueenNotationToken] = []
        for idx, (role, notation, intensity, companions, response) in enumerate(phrases):
            body = {
                "role": role,
                "notation": notation,
                "intensity": round(intensity, 6),
                "epoch_id": epoch.epoch_id,
                "score_id": epoch.score_id,
                "world_state_id": world_state_id,
                "world_state_hash": world_state_hash,
                "issued_at_ms": now_ms,
                "expires_at_ms": expiry,
                "companions": list(companions),
                "response": response,
                "score_sheet_ids": score_ids,
                "ordinal": idx,
            }
            tokens.append(QueenNotationToken(
                token_id="qnt_" + _digest(body).split(":", 1)[1][:24],
                issued_to_role=role,
                notation=notation,
                intensity=round(_clamp(intensity), 6),
                epoch_id=epoch.epoch_id,
                score_id=epoch.score_id,
                world_state_id=world_state_id,
                world_state_hash=world_state_hash,
                issued_at_ms=int(now_ms),
                expires_at_ms=int(expiry),
                required_companions=tuple(companions),
                response_class=response,
                source_score_sheet_ids=score_ids,
                maximum_uses=1,
                authority=RELATIVE_VALUE_AUTHORITY,
                execution_eligible=False,
                promotion_eligible=False,
            ))
        return tokens