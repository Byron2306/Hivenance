from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .evaluation import WalkForwardPrediction


CANDIDATE_FAMILIES = {
    "relative_value_ou_mean_reversion_v1": "structural",
    "relative_value_expanding_ridge_v1": "statistical",
}
CONTROL_MODELS = {
    "baseline_zero_v1",
    "baseline_continuation_v1",
    "baseline_reversal_v1",
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _sigmoid(value: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-value))
    except OverflowError:
        return 0.0 if value < 0 else 1.0


def _digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _sign(value: float, deadband_bps: float) -> int:
    if value > deadband_bps:
        return 1
    if value < -deadband_bps:
        return -1
    return 0


def _entropy(signs: Sequence[int]) -> float:
    active = [value for value in signs if value != 0]
    if not active:
        return 0.0
    counts = [sum(1 for value in active if value > 0), sum(1 for value in active if value < 0)]
    total = float(sum(counts))
    entropy = 0.0
    for count in counts:
        if count <= 0:
            continue
        probability = count / total
        entropy -= probability * math.log(probability, 2)
    return _clamp(entropy)  # binary entropy max = 1


@dataclass(frozen=True)
class HarmonicForecastVoice:
    model_id: str
    family: str
    horizon_seconds: int
    predicted_signed_bps: float
    sign: int
    independent: bool
    control: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HarmonicSpectrum:
    micro: Optional[float]
    meso: Optional[float]
    macro: Optional[float]
    global_score: Optional[float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HarmonicForecastReceipt:
    schema: str
    receipt_id: str
    pair_id: str
    timestamp_ms: int
    state: str
    resonance_score: float
    discord_score: float
    confidence: float
    direction: str
    independent_families: tuple[str, ...]
    voices: tuple[HarmonicForecastVoice, ...]
    spectrum: HarmonicSpectrum
    forecast_jitter: float
    direction_flip_rate: float
    forecast_drift: float
    confidence_burstiness: float
    forecast_entropy: float
    control_dissent: Mapping[str, Any] = field(default_factory=dict)
    reasons: tuple[str, ...] = field(default_factory=tuple)
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["spectrum"] = self.spectrum.to_dict()
        return payload


@dataclass(frozen=True)
class HarmonicGovernanceConfig:
    deadband_bps: float = 0.05
    history_size: int = 24
    min_independent_families: int = 2
    min_resonance: float = 0.62
    max_discord: float = 0.48
    min_confidence: float = 0.45
    resonance_weight_agreement: float = 0.42
    resonance_weight_stability: float = 0.24
    resonance_weight_low_jitter: float = 0.18
    resonance_weight_low_entropy: float = 0.16


class HarmonicForecastGovernance:
    """Phoenix adaptation of Metatron's Harmonic Governance concepts.

    It governs forecast coherence, cadence and dissent. It does not generate a
    market forecast, mutate a threshold, promote a model, or grant execution
    authority.

    Candidate forecasts are collapsed to one vote per independent model family
    before resonance is computed. Controls are preserved as dissent references
    but do not vote.
    """

    version = "phoenix.harmonic_forecast_governance.v1"

    def __init__(
        self,
        config: HarmonicGovernanceConfig | None = None,
        *,
        model_families: Mapping[str, str] | None = None,
    ) -> None:
        self.config = config or HarmonicGovernanceConfig()
        self.model_families = dict(CANDIDATE_FAMILIES)
        self.model_families.update(dict(model_families or {}))
        self._history: dict[str, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=max(4, int(self.config.history_size)))
        )

    @staticmethod
    def _band(horizon_seconds: int) -> str:
        if horizon_seconds <= 10:
            return "micro"
        if horizon_seconds <= 60:
            return "meso"
        return "macro"

    def _collapse_family_voices(
        self,
        rows: Sequence[WalkForwardPrediction],
    ) -> tuple[list[HarmonicForecastVoice], list[HarmonicForecastVoice]]:
        candidates: dict[tuple[str, int], list[WalkForwardPrediction]] = defaultdict(list)
        controls: list[HarmonicForecastVoice] = []
        for row in rows:
            if row.model_id in CONTROL_MODELS:
                controls.append(HarmonicForecastVoice(
                    model_id=row.model_id,
                    family="control",
                    horizon_seconds=row.horizon_seconds,
                    predicted_signed_bps=float(row.predicted_signed_bps),
                    sign=_sign(float(row.predicted_signed_bps), self.config.deadband_bps),
                    independent=False,
                    control=True,
                ))
                continue
            family = self.model_families.get(row.model_id)
            if not family:
                # Unknown challenger is explicit but does not silently earn
                # independent-family status until registered.
                family = f"unregistered:{row.model_id}"
            candidates[(family, row.horizon_seconds)].append(row)

        voices: list[HarmonicForecastVoice] = []
        for (family, horizon), family_rows in sorted(candidates.items()):
            predicted = statistics.fmean(float(row.predicted_signed_bps) for row in family_rows)
            voices.append(HarmonicForecastVoice(
                model_id="+".join(sorted({row.model_id for row in family_rows})),
                family=family,
                horizon_seconds=horizon,
                predicted_signed_bps=predicted,
                sign=_sign(predicted, self.config.deadband_bps),
                independent=not family.startswith("unregistered:"),
                control=False,
            ))
        return voices, controls

    @staticmethod
    def _agreement(signs: Sequence[int]) -> float:
        active = [value for value in signs if value != 0]
        if not active:
            return 0.0
        return abs(sum(active)) / len(active)

    @staticmethod
    def _magnitude_dispersion(values: Sequence[float]) -> float:
        magnitudes = [abs(float(value)) for value in values if math.isfinite(float(value))]
        if len(magnitudes) < 2:
            return 0.0
        mean = statistics.fmean(magnitudes)
        if mean <= 1e-12:
            return 0.0
        cv = statistics.pstdev(magnitudes) / mean
        return _clamp(cv / 2.0)

    @staticmethod
    def _direction(signs: Sequence[int]) -> str:
        active = [value for value in signs if value != 0]
        if not active:
            return "ABSTAIN"
        total = sum(active)
        if total > 0:
            return "LONG_A_SHORT_B"
        if total < 0:
            return "LONG_B_SHORT_A"
        return "ABSTAIN"

    def _cadence_features(
        self,
        *,
        pair_id: str,
        timestamp_ms: int,
        aggregate_signed_bps: float,
        aggregate_sign: int,
        instantaneous_agreement: float,
    ) -> dict[str, float]:
        history = self._history[pair_id]
        prior = list(history)
        values = [float(row["aggregate_signed_bps"]) for row in prior]
        signs = [int(row["aggregate_sign"]) for row in prior if int(row["aggregate_sign"]) != 0]
        agreements = [float(row["agreement"]) for row in prior]

        jitter = 0.0
        if len(values) >= 2:
            deltas = [b - a for a, b in zip(values, values[1:])]
            scale = max(0.25, statistics.fmean(abs(v) for v in values))
            jitter = _clamp(statistics.pstdev(deltas) / max(scale, 1e-9))

        flip_rate = 0.0
        if len(signs) >= 2:
            flips = sum(1 for a, b in zip(signs, signs[1:]) if a != b)
            flip_rate = flips / (len(signs) - 1)

        drift = 0.0
        if len(values) >= 6:
            cut = len(values) // 2
            early = statistics.fmean(values[:cut])
            late = statistics.fmean(values[cut:])
            scale = max(0.25, statistics.fmean(abs(v) for v in values))
            drift = _clamp(abs(late - early) / (2.0 * scale))

        burstiness = 0.0
        if agreements:
            high = sum(1 for value in agreements[-8:] if value >= 0.80)
            baseline = sum(1 for value in agreements if value >= 0.80) / len(agreements)
            recent = high / min(8, len(agreements))
            burstiness = _clamp(max(0.0, recent - baseline))

        history.append({
            "timestamp_ms": int(timestamp_ms),
            "aggregate_signed_bps": float(aggregate_signed_bps),
            "aggregate_sign": int(aggregate_sign),
            "agreement": float(instantaneous_agreement),
        })
        return {
            "forecast_jitter": jitter,
            "direction_flip_rate": flip_rate,
            "forecast_drift": drift,
            "confidence_burstiness": burstiness,
        }

    def _band_resonance(self, voices: Sequence[HarmonicForecastVoice], band: str) -> Optional[float]:
        selected = [
            voice for voice in voices
            if voice.independent and self._band(voice.horizon_seconds) == band
        ]
        families = {voice.family for voice in selected}
        if len(families) < 2:
            return None
        signs = [voice.sign for voice in selected]
        agreement = self._agreement(signs)
        dispersion = self._magnitude_dispersion([voice.predicted_signed_bps for voice in selected])
        return round(_clamp(0.75 * agreement + 0.25 * (1.0 - dispersion)), 6)

    def score(
        self,
        *,
        pair_id: str,
        timestamp_ms: int,
        predictions: Sequence[WalkForwardPrediction],
    ) -> HarmonicForecastReceipt:
        rows = [
            row for row in predictions
            if row.pair_id == pair_id and row.timestamp_ms == timestamp_ms
        ]
        voices, controls = self._collapse_family_voices(rows)
        independent = [voice for voice in voices if voice.independent]
        families = sorted({voice.family for voice in independent})

        # Global choir: exactly one vote per independent family, irrespective
        # of how many horizons/models that family emits.
        family_predictions: dict[str, list[float]] = defaultdict(list)
        for voice in independent:
            family_predictions[voice.family].append(float(voice.predicted_signed_bps))
        family_values = {
            family: statistics.fmean(values)
            for family, values in family_predictions.items()
        }
        signs = [
            _sign(family_values[family], self.config.deadband_bps)
            for family in sorted(family_values)
        ]
        agreement = self._agreement(signs)
        entropy = _entropy(signs)
        dispersion = self._magnitude_dispersion(list(family_values.values()))

        aggregate = 0.0
        if family_values:
            aggregate = statistics.fmean(family_values.values())
        aggregate_sign = _sign(aggregate, self.config.deadband_bps)

        cadence = self._cadence_features(
            pair_id=pair_id,
            timestamp_ms=timestamp_ms,
            aggregate_signed_bps=aggregate,
            aggregate_sign=aggregate_sign,
            instantaneous_agreement=agreement,
        )
        stability = 1.0 - _clamp(
            0.45 * cadence["direction_flip_rate"]
            + 0.35 * cadence["forecast_drift"]
            + 0.20 * cadence["confidence_burstiness"]
        )
        low_jitter = 1.0 - cadence["forecast_jitter"]
        low_entropy = 1.0 - entropy

        resonance = _clamp(
            self.config.resonance_weight_agreement * agreement
            + self.config.resonance_weight_stability * stability
            + self.config.resonance_weight_low_jitter * low_jitter
            + self.config.resonance_weight_low_entropy * low_entropy
        )
        discord = _clamp(
            0.38 * (1.0 - agreement)
            + 0.20 * entropy
            + 0.16 * dispersion
            + 0.12 * cadence["direction_flip_rate"]
            + 0.08 * cadence["forecast_drift"]
            + 0.06 * cadence["forecast_jitter"]
        )

        family_factor = _clamp(len(families) / max(1.0, float(self.config.min_independent_families)))
        history_factor = _clamp(len(self._history[pair_id]) / 8.0)
        registered_factor = (
            sum(1 for voice in independent if not voice.family.startswith("unregistered:"))
            / max(1, len(independent))
        )
        confidence = _clamp(0.45 * family_factor + 0.35 * history_factor + 0.20 * registered_factor)

        reasons: list[str] = []
        if len(families) < self.config.min_independent_families:
            reasons.append("insufficient_independent_forecast_families")
        if resonance < self.config.min_resonance:
            reasons.append("harmonic_resonance_below_floor")
        if discord > self.config.max_discord:
            reasons.append("harmonic_discord_above_ceiling")
        if confidence < self.config.min_confidence:
            reasons.append("harmonic_confidence_below_floor")
        direction = self._direction(signs)
        if direction == "ABSTAIN":
            reasons.append("no_harmonic_direction")

        if "insufficient_independent_forecast_families" in reasons:
            state = "INSUFFICIENT"
        elif discord > self.config.max_discord:
            state = "DISCORDANT"
        elif cadence["forecast_drift"] >= 0.65:
            state = "DRIFTING"
        elif not reasons:
            state = "RESONANT"
        else:
            state = "MIXED"

        spectrum = HarmonicSpectrum(
            micro=self._band_resonance(independent, "micro"),
            meso=self._band_resonance(independent, "meso"),
            macro=self._band_resonance(independent, "macro"),
            global_score=round(resonance, 6),
        )

        control_map: dict[str, Any] = {}
        for control in controls:
            key = f"{control.model_id}:{control.horizon_seconds}s"
            control_map[key] = {
                "predicted_signed_bps": round(control.predicted_signed_bps, 6),
                "sign": control.sign,
                "agrees_with_harmonic_direction": (
                    direction == "LONG_A_SHORT_B" and control.sign > 0
                ) or (
                    direction == "LONG_B_SHORT_A" and control.sign < 0
                ),
            }

        body = {
            "pair_id": pair_id,
            "timestamp_ms": int(timestamp_ms),
            "families": families,
            "resonance": round(resonance, 6),
            "discord": round(discord, 6),
            "confidence": round(confidence, 6),
            "direction": direction,
            "state": state,
            "spectrum": spectrum.to_dict(),
            "cadence": cadence,
        }
        return HarmonicForecastReceipt(
            schema="hivenance_harmonic_forecast_governance_v1",
            receipt_id="hfg_" + _digest(body).split(":", 1)[1][:24],
            pair_id=pair_id,
            timestamp_ms=int(timestamp_ms),
            state=state,
            resonance_score=round(resonance, 6),
            discord_score=round(discord, 6),
            confidence=round(confidence, 6),
            direction=direction,
            independent_families=tuple(families),
            voices=tuple(voices + controls),
            spectrum=spectrum,
            forecast_jitter=round(cadence["forecast_jitter"], 6),
            direction_flip_rate=round(cadence["direction_flip_rate"], 6),
            forecast_drift=round(cadence["forecast_drift"], 6),
            confidence_burstiness=round(cadence["confidence_burstiness"], 6),
            forecast_entropy=round(entropy, 6),
            control_dissent=control_map,
            reasons=tuple(sorted(set(reasons))),
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )


def group_prediction_choirs(
    predictions: Iterable[WalkForwardPrediction],
) -> dict[tuple[str, int], list[WalkForwardPrediction]]:
    grouped: dict[tuple[str, int], list[WalkForwardPrediction]] = defaultdict(list)
    for row in predictions:
        grouped[(row.pair_id, row.timestamp_ms)].append(row)
    return grouped