from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _digest(payload: Any) -> str:
    raw=json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")
    return "sha256:"+hashlib.sha256(raw).hexdigest()


def _direction(value: float, deadband_bps: float) -> str:
    if value > deadband_bps:
        return "LONG_A_SHORT_B"
    if value < -deadband_bps:
        return "LONG_B_SHORT_A"
    return "ABSTAIN"


@dataclass(frozen=True)
class LearnedModelProvenance:
    model_id: str
    model_version: str
    model_artifact_digest: str
    training_lineage_digest: str
    feature_lineage_digest: str
    training_cutoff_ms: int
    validation_start_ms: int
    validation_end_ms: int
    dependence_group: str
    synthetic_training_used: bool=False

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


@dataclass(frozen=True)
class LearnedCalibration:
    samples: int
    mae_bps: Optional[float]
    rmse_bps: Optional[float]
    sign_accuracy: Optional[float]
    calibration_error: Optional[float]
    baseline_delta_bps: Optional[float]
    leave_one_pair_score: Optional[float]
    leave_one_asset_score: Optional[float]

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


@dataclass(frozen=True)
class LearnedChallengerForecast:
    hypothesis_id: str
    pair_id: str
    horizon_seconds: int
    observed_at_ms: int
    predicted_signed_bps: float
    uncertainty_bps: float
    world_state_id: str
    world_state_hash: str
    evidence_root: str

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


@dataclass(frozen=True)
class LearnedChallengerReceipt:
    schema: str
    receipt_id: str
    hypothesis_id: str
    pair_id: str
    horizon_seconds: int
    observed_at_ms: int
    predicted_signed_bps: float
    direction: str
    uncertainty_bps: float

    model_id: str
    model_version: str
    model_artifact_digest: str
    training_lineage_digest: str
    feature_lineage_digest: str
    dependence_group: str

    calibration_health: float
    baseline_competition_health: float
    generalization_health: float
    freshness: float
    drift_pressure: float
    uncertainty_pressure: float
    voice_health: float

    synthetic_training_used: bool
    prospective_edge_evidence: bool
    independent_vote_eligible: bool
    reasons: tuple[str,...]

    world_state_id: str
    world_state_hash: str
    evidence_root: str

    synthesis_win_probability: float | None = None
    synthesis_edge_positive_probability: float | None = None
    synthesis_uncertainty: float | None = None
    synthesis_change_point_probability: float | None = None

    authority: str=RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool=False
    promotion_eligible: bool=False

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


@dataclass(frozen=True)
class LearnedChallengerConfig:
    """Provisional health scales, not edge thresholds."""

    deadband_bps: float=.05
    stale_after_ms: int=300_000
    calibration_error_reference: float=.25
    minimum_validation_samples: int=80
    uncertainty_reference_bps: float=5.0
    drift_reference: float=.35


class LearnedChallenger:
    """One provenance-bound learned voice in the Phoenix research choir.

    The challenger can disagree, abstain or become stale. It cannot become the
    conductor and cannot manufacture independence from shared training/features.
    """

    version="hivenance.learned_challenger.v1"

    def __init__(self,config:LearnedChallengerConfig|None=None)->None:
        self.config=config or LearnedChallengerConfig()

    @staticmethod
    def _validate_digest(name:str,value:str)->None:
        if not str(value).startswith("sha256:"):
            raise ValueError(f"{name}_must_be_sha256_bound")

    def score(
        self,
        *,
        forecast:LearnedChallengerForecast,
        provenance:LearnedModelProvenance,
        calibration:LearnedCalibration,
        now_ms:int,
        drift_score:float,
        known_dependence_groups:Sequence[str]=(),
        synthesis_state:Mapping[str,Any]|None=None,
    )->LearnedChallengerReceipt:
        for name,value in (
            ("model_artifact_digest",provenance.model_artifact_digest),
            ("training_lineage_digest",provenance.training_lineage_digest),
            ("feature_lineage_digest",provenance.feature_lineage_digest),
            ("world_state_hash",forecast.world_state_hash),
            ("evidence_root",forecast.evidence_root),
        ):
            self._validate_digest(name,value)

        reasons=[]

        if forecast.observed_at_ms < provenance.training_cutoff_ms:
            reasons.append("forecast_precedes_training_cutoff")
        if provenance.validation_end_ms > forecast.observed_at_ms:
            reasons.append("validation_window_overlaps_forecast")

        samples=max(0,int(calibration.samples))
        sample_health=_clamp(samples/max(1,self.config.minimum_validation_samples))

        if calibration.calibration_error is None:
            calibration_fit=.0
            reasons.append("calibration_missing")
        else:
            calibration_fit=_clamp(
                1.0-float(calibration.calibration_error)/max(1e-9,self.config.calibration_error_reference)
            )
        calibration_health=_clamp(.45*sample_health+.55*calibration_fit)

        if calibration.baseline_delta_bps is None:
            baseline_health=.0
            reasons.append("baseline_comparison_missing")
        else:
            # Positive means challenger improves on frozen baseline metric.
            baseline_health=_clamp(.5+.5*math.tanh(float(calibration.baseline_delta_bps)))

        loo_scores=[
            value for value in (
                calibration.leave_one_pair_score,
                calibration.leave_one_asset_score,
            )
            if value is not None
        ]
        if loo_scores:
            generalization=_clamp(sum(_clamp(v) for v in loo_scores)/len(loo_scores))
        else:
            generalization=.0
            reasons.append("generalization_diagnostics_missing")

        age=max(0,int(now_ms)-int(forecast.observed_at_ms))
        freshness=_clamp(1.0-age/max(1,self.config.stale_after_ms))
        if age>self.config.stale_after_ms:
            reasons.append("challenger_stale")

        drift_pressure=_clamp(float(drift_score)/max(1e-9,self.config.drift_reference))
        synthesis_change=None
        synthesis_uncertainty=None
        synthesis_win=None
        synthesis_edge=None
        if synthesis_state is not None:
            synthesis_change=_clamp(float(synthesis_state.get("change_point_probability") or 0.0))
            synthesis_uncertainty=_clamp(float(synthesis_state.get("uncertainty") or 0.0))
            synthesis_win=synthesis_state.get("hierarchical_win_probability")
            synthesis_edge=synthesis_state.get("hierarchical_edge_positive_probability")
            drift_pressure=max(drift_pressure,synthesis_change)
            if synthesis_change>.6:
                reasons.append("synthesis_change_point_pressure_high")
        else:
            reasons.append("synthesis_state_missing")

        if drift_pressure>.6:
            reasons.append("model_drift_audible")

        uncertainty_pressure=_clamp(
            abs(float(forecast.uncertainty_bps))/max(1e-9,self.config.uncertainty_reference_bps)
        )
        if synthesis_uncertainty is not None:
            uncertainty_pressure=max(uncertainty_pressure,synthesis_uncertainty)
        if uncertainty_pressure>.7:
            reasons.append("model_uncertainty_high")

        voice_health=_clamp(
            .24*calibration_health
            +.18*baseline_health
            +.20*generalization
            +.18*freshness
            +.10*(1.0-drift_pressure)
            +.10*(1.0-uncertainty_pressure)
        )

        dependence_known=provenance.dependence_group in set(known_dependence_groups)
        if dependence_known:
            reasons.append("shared_dependence_group")

        if provenance.synthetic_training_used:
            reasons.append("synthetic_training_not_edge_evidence")

        prospective_edge_evidence=(
            not provenance.synthetic_training_used
            and provenance.validation_end_ms < forecast.observed_at_ms
            and samples>=self.config.minimum_validation_samples
        )

        independent_vote_eligible=(
            voice_health>=.55
            and not dependence_known
            and not provenance.synthetic_training_used
            and "forecast_precedes_training_cutoff" not in reasons
            and "validation_window_overlaps_forecast" not in reasons
        )

        direction=_direction(forecast.predicted_signed_bps,self.config.deadband_bps)
        if direction=="ABSTAIN":
            reasons.append("challenger_abstains")

        body={
            "forecast":forecast.to_dict(),
            "provenance":provenance.to_dict(),
            "calibration":calibration.to_dict(),
            "health":round(voice_health,6),
            "reasons":sorted(set(reasons)),
            "synthesis_state":dict(synthesis_state or {}),
        }
        return LearnedChallengerReceipt(
            schema="hivenance_learned_challenger_v1",
            receipt_id="mlc_"+_digest(body).split(":",1)[1][:24],
            hypothesis_id=forecast.hypothesis_id,
            pair_id=forecast.pair_id,
            horizon_seconds=int(forecast.horizon_seconds),
            observed_at_ms=int(forecast.observed_at_ms),
            predicted_signed_bps=round(float(forecast.predicted_signed_bps),6),
            direction=direction,
            uncertainty_bps=round(abs(float(forecast.uncertainty_bps)),6),
            model_id=provenance.model_id,
            model_version=provenance.model_version,
            model_artifact_digest=provenance.model_artifact_digest,
            training_lineage_digest=provenance.training_lineage_digest,
            feature_lineage_digest=provenance.feature_lineage_digest,
            dependence_group=provenance.dependence_group,
            calibration_health=round(calibration_health,6),
            baseline_competition_health=round(baseline_health,6),
            generalization_health=round(generalization,6),
            freshness=round(freshness,6),
            drift_pressure=round(drift_pressure,6),
            uncertainty_pressure=round(uncertainty_pressure,6),
            voice_health=round(voice_health,6),
            synthetic_training_used=provenance.synthetic_training_used,
            prospective_edge_evidence=prospective_edge_evidence,
            independent_vote_eligible=independent_vote_eligible,
            reasons=tuple(sorted(set(reasons))),
            world_state_id=forecast.world_state_id,
            world_state_hash=forecast.world_state_hash,
            evidence_root=forecast.evidence_root,
            synthesis_win_probability=None if synthesis_win is None else round(float(synthesis_win),6),
            synthesis_edge_positive_probability=None if synthesis_edge is None else round(float(synthesis_edge),6),
            synthesis_uncertainty=None if synthesis_uncertainty is None else round(float(synthesis_uncertainty),6),
            synthesis_change_point_probability=None if synthesis_change is None else round(float(synthesis_change),6),
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )