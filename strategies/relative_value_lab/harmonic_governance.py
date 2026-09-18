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
    return _clamp(entropy)


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
class HarmonicHorizonState:
    horizon_seconds: int
    band: str
    state: str
    direction: str
    resonance_score: float
    discord_score: float
    confidence: float
    independent_families: tuple[str, ...]
    forecast_jitter: float
    direction_flip_rate: float
    forecast_drift: float
    confidence_burstiness: float
    forecast_entropy: float

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
    independent_families: tuple[str, ...]
    voices: tuple[HarmonicForecastVoice, ...]
    horizon_states: tuple[HarmonicHorizonState, ...]
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
        payload["horizon_states"] = tuple(state.to_dict() for state in self.horizon_states)
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
    """Per-horizon harmonic governance for Phoenix.

    Market direction exists only inside a horizon state. The global receipt
    describes coherence among voices and horizons and intentionally has no
    market-direction field.

    Controls remain dissent references and never vote.
    """

    version = "phoenix.harmonic_forecast_governance.v2"

    def __init__(
        self,
        config: HarmonicGovernanceConfig | None = None,
        *,
        model_families: Mapping[str, str] | None = None,
    ) -> None:
        self.config = config or HarmonicGovernanceConfig()
        self.model_families = dict(CANDIDATE_FAMILIES)
        self.model_families.update(dict(model_families or {}))
        self._history: dict[tuple[str, int], deque[dict[str, Any]]] = defaultdict(
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
        return _clamp((statistics.pstdev(magnitudes) / mean) / 2.0)

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
        horizon_seconds: int,
        timestamp_ms: int,
        aggregate_signed_bps: float,
        aggregate_sign: int,
        instantaneous_agreement: float,
    ) -> dict[str, float]:
        history = self._history[(pair_id, horizon_seconds)]
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

    def _score_horizon(
        self,
        *,
        pair_id: str,
        timestamp_ms: int,
        horizon_seconds: int,
        voices: Sequence[HarmonicForecastVoice],
    ) -> HarmonicHorizonState:
        selected = [
            voice for voice in voices
            if voice.horizon_seconds == horizon_seconds and voice.independent
        ]
        families = sorted({voice.family for voice in selected})
        signs = [voice.sign for voice in selected]
        values = [voice.predicted_signed_bps for voice in selected]

        agreement = self._agreement(signs)
        entropy = _entropy(signs)
        dispersion = self._magnitude_dispersion(values)
        aggregate = statistics.fmean(values) if values else 0.0
        aggregate_sign = _sign(aggregate, self.config.deadband_bps)

        cadence = self._cadence_features(
            pair_id=pair_id,
            horizon_seconds=horizon_seconds,
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
        resonance = _clamp(
            self.config.resonance_weight_agreement * agreement
            + self.config.resonance_weight_stability * stability
            + self.config.resonance_weight_low_jitter * (1.0 - cadence["forecast_jitter"])
            + self.config.resonance_weight_low_entropy * (1.0 - entropy)
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
        history_factor = _clamp(len(self._history[(pair_id, horizon_seconds)]) / 8.0)
        confidence = _clamp(0.60 * family_factor + 0.40 * history_factor)

        direction = self._direction(signs)
        if len(families) < self.config.min_independent_families:
            state = "INSUFFICIENT"
        elif discord > self.config.max_discord:
            state = "DISCORDANT"
        elif cadence["forecast_drift"] >= 0.65:
            state = "DRIFTING"
        elif (
            resonance >= self.config.min_resonance
            and discord <= self.config.max_discord
            and confidence >= self.config.min_confidence
        ):
            state = "RESONANT"
        else:
            state = "MIXED"

        return HarmonicHorizonState(
            horizon_seconds=int(horizon_seconds),
            band=self._band(horizon_seconds),
            state=state,
            direction=direction,
            resonance_score=round(resonance, 6),
            discord_score=round(discord, 6),
            confidence=round(confidence, 6),
            independent_families=tuple(families),
            forecast_jitter=round(cadence["forecast_jitter"], 6),
            direction_flip_rate=round(cadence["direction_flip_rate"], 6),
            forecast_drift=round(cadence["forecast_drift"], 6),
            confidence_burstiness=round(cadence["confidence_burstiness"], 6),
            forecast_entropy=round(entropy, 6),
        )

    @staticmethod
    def _mean(states: Sequence[HarmonicHorizonState], field: str) -> float:
        return (
            statistics.fmean(float(getattr(state, field)) for state in states)
            if states else 0.0
        )

    @staticmethod
    def _band_score(
        states: Sequence[HarmonicHorizonState],
        band: str,
    ) -> Optional[float]:
        selected = [state.resonance_score for state in states if state.band == band]
        return round(statistics.fmean(selected), 6) if selected else None

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
        horizons = sorted({voice.horizon_seconds for voice in independent})

        horizon_states = tuple(
            self._score_horizon(
                pair_id=pair_id,
                timestamp_ms=timestamp_ms,
                horizon_seconds=horizon,
                voices=independent,
            )
            for horizon in horizons
        )

        resonance = self._mean(horizon_states, "resonance_score")
        discord = self._mean(horizon_states, "discord_score")
        confidence = self._mean(horizon_states, "confidence")
        forecast_jitter = self._mean(horizon_states, "forecast_jitter")
        flip_rate = self._mean(horizon_states, "direction_flip_rate")
        drift = self._mean(horizon_states, "forecast_drift")
        burstiness = self._mean(horizon_states, "confidence_burstiness")
        entropy = self._mean(horizon_states, "forecast_entropy")

        if not horizon_states:
            state = "INSUFFICIENT"
        elif all(item.state == "INSUFFICIENT" for item in horizon_states):
            state = "INSUFFICIENT"
        elif any(item.state == "DRIFTING" for item in horizon_states):
            state = "DRIFTING"
        elif discord > self.config.max_discord:
            state = "DISCORDANT"
        elif resonance >= self.config.min_resonance and confidence >= self.config.min_confidence:
            state = "RESONANT"
        else:
            state = "MIXED"

        spectrum = HarmonicSpectrum(
            micro=self._band_score(horizon_states, "micro"),
            meso=self._band_score(horizon_states, "meso"),
            macro=self._band_score(horizon_states, "macro"),
            global_score=round(resonance, 6),
        )

        state_by_horizon = {item.horizon_seconds: item for item in horizon_states}
        control_map: dict[str, Any] = {}
        for control in controls:
            key = f"{control.model_id}:{control.horizon_seconds}s"
            horizon_state = state_by_horizon.get(control.horizon_seconds)
            agrees = False
            if horizon_state is not None:
                agrees = (
                    horizon_state.direction == "LONG_A_SHORT_B" and control.sign > 0
                ) or (
                    horizon_state.direction == "LONG_B_SHORT_A" and control.sign < 0
                )
            control_map[key] = {
                "predicted_signed_bps": round(control.predicted_signed_bps, 6),
                "sign": control.sign,
                "agrees_with_same_horizon_direction": agrees,
            }

        reasons: list[str] = []
        if not horizon_states:
            reasons.append("no_registered_horizon_voices")
        if any(item.state == "INSUFFICIENT" for item in horizon_states):
            reasons.append("one_or_more_horizons_insufficient")
        if resonance < self.config.min_resonance:
            reasons.append("global_resonance_below_floor")
        if discord > self.config.max_discord:
            reasons.append("global_discord_above_ceiling")
        if confidence < self.config.min_confidence:
            reasons.append("global_confidence_below_floor")

        body = {
            "pair_id": pair_id,
            "timestamp_ms": int(timestamp_ms),
            "families": families,
            "state": state,
            "resonance": round(resonance, 6),
            "discord": round(discord, 6),
            "confidence": round(confidence, 6),
            "horizon_states": [item.to_dict() for item in horizon_states],
            "spectrum": spectrum.to_dict(),
        }
        return HarmonicForecastReceipt(
            schema="hivenance_harmonic_forecast_governance_v2",
            receipt_id="hfg_" + _digest(body).split(":", 1)[1][:24],
            pair_id=pair_id,
            timestamp_ms=int(timestamp_ms),
            state=state,
            resonance_score=round(resonance, 6),
            discord_score=round(discord, 6),
            confidence=round(confidence, 6),
            independent_families=tuple(families),
            voices=tuple(voices + controls),
            horizon_states=horizon_states,
            spectrum=spectrum,
            forecast_jitter=round(forecast_jitter, 6),
            direction_flip_rate=round(flip_rate, 6),
            forecast_drift=round(drift, 6),
            confidence_burstiness=round(burstiness, 6),
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
