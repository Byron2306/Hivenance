from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Optional, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _digest(payload: Any) -> str:
    raw=json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")
    return "sha256:"+hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class MetabolicObservation:
    observation_id: str
    timestamp_ms: int
    context_units_consumed: float
    model_evaluations: int
    tool_evaluations: int
    independent_evidence_units: float
    duplicate_evidence_units: float
    useful_settled_information_units: float
    information_gain_units: float
    baseline_confidence: float
    current_confidence: float
    world_state_id: str
    world_state_hash: str

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


@dataclass(frozen=True)
class CognitiveMetabolismReceipt:
    schema: str
    receipt_id: str
    observation_id: str

    # Metatron-derived names, adapted to research cognition.
    cbr: Optional[float]
    tbcr: Optional[float]
    cdi: float

    information_efficiency: float
    evidence_novelty: float
    duplicate_pressure: float
    unresolved_burn: float
    metabolic_strain: float
    breath: float
    texture: str
    denominator_resolved: bool
    reasons: tuple[str,...]

    context_units_consumed: float
    model_evaluations: int
    tool_evaluations: int
    useful_settled_information_units: float
    information_gain_units: float

    authority: str=RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool=False
    promotion_eligible: bool=False

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


@dataclass(frozen=True)
class CognitiveMetabolismConfig:
    """Provisional engineering scales, not discovered market constants."""

    context_reference_units: float=1000.0
    evaluation_reference_count: float=20.0
    information_reference_units: float=1.0
    duplicate_reference_ratio: float=0.5


class CognitiveMetabolism:
    """Listen to the energetic cost of research cognition.

    CBR and TBCR retain Metatron's exhaustion semantics but use useful settled
    information as the denominator. If settlement is absent, ratios remain
    unresolved instead of being cosmetically divided by one.

    Metabolism is descriptive. It changes attention, breath and orchestration,
    never execution or promotion authority.
    """

    version="hivenance.cognitive_metabolism.v1"

    def __init__(self,config:CognitiveMetabolismConfig|None=None)->None:
        self.config=config or CognitiveMetabolismConfig()

    def score(self,observation:MetabolicObservation)->CognitiveMetabolismReceipt:
        context=max(0.0,float(observation.context_units_consumed))
        model_evals=max(0,int(observation.model_evaluations))
        tool_evals=max(0,int(observation.tool_evaluations))
        total_evals=model_evals+tool_evals

        independent=max(0.0,float(observation.independent_evidence_units))
        duplicate=max(0.0,float(observation.duplicate_evidence_units))
        settled=max(0.0,float(observation.useful_settled_information_units))
        info_gain=max(0.0,float(observation.information_gain_units))

        denominator_resolved=settled>0.0
        cbr=(context/settled) if denominator_resolved else None
        tbcr=(total_evals/settled) if denominator_resolved else None

        baseline=_clamp(observation.baseline_confidence)
        current=_clamp(observation.current_confidence)
        cdi=0.0 if baseline<=0.0 else _clamp((baseline-current)/baseline)

        information_efficiency=_clamp(
            (info_gain/max(context,1.0))*self.config.context_reference_units
        )

        evidence_total=independent+duplicate
        evidence_novelty=(
            _clamp(independent/evidence_total)
            if evidence_total>0.0 else 0.0
        )
        duplicate_pressure=(
            _clamp(duplicate/evidence_total)
            if evidence_total>0.0 else 0.0
        )

        context_burn_norm=_clamp(context/max(1.0,self.config.context_reference_units))
        eval_burn_norm=_clamp(total_evals/max(1.0,self.config.evaluation_reference_count))

        # Before settlement, accumulated effort is audible as unresolved burn.
        unresolved_burn=0.0
        if not denominator_resolved:
            unresolved_burn=_clamp(
                0.45*context_burn_norm
                +0.35*eval_burn_norm
                +0.20*(1.0-information_efficiency)
            )

        metabolic_strain=_clamp(
            0.24*context_burn_norm
            +0.20*eval_burn_norm
            +0.18*cdi
            +0.16*duplicate_pressure
            +0.12*(1.0-information_efficiency)
            +0.10*unresolved_burn
        )

        # Breath is not "permission"; it is spare cognitive capacity.
        breath=_clamp(
            1.0
            -0.55*metabolic_strain
            -0.20*duplicate_pressure
            -0.15*cdi
            +0.10*evidence_novelty
        )

        if not denominator_resolved and unresolved_burn>=0.65:
            texture="UNSETTLED_FATIGUE"
        elif metabolic_strain>=0.75:
            texture="OVERREHEARSING"
        elif metabolic_strain>=0.55:
            texture="FATIGUED"
        elif duplicate_pressure>=0.55 and information_efficiency<0.35:
            texture="ECHO_BURN"
        elif breath>=0.75 and evidence_novelty>=0.55:
            texture="BREATHING"
        else:
            texture="SUSTAINED"

        reasons=[]
        if not denominator_resolved:
            reasons.append("settlement_denominator_unresolved")
        if cdi>0.35:
            reasons.append("confidence_degrading")
        if duplicate_pressure>0.45:
            reasons.append("duplicate_evidence_burn")
        if information_efficiency<0.25 and context_burn_norm>0.50:
            reasons.append("high_context_low_information")
        if eval_burn_norm>0.70 and info_gain<self.config.information_reference_units:
            reasons.append("high_evaluation_low_information")
        if evidence_novelty>0.65:
            reasons.append("fresh_independent_evidence")

        body={
            "observation":observation.to_dict(),
            "cbr":None if cbr is None else round(cbr,6),
            "tbcr":None if tbcr is None else round(tbcr,6),
            "cdi":round(cdi,6),
            "texture":texture,
        }
        return CognitiveMetabolismReceipt(
            schema="hivenance_cognitive_metabolism_v1",
            receipt_id="metab_"+_digest(body).split(":",1)[1][:24],
            observation_id=observation.observation_id,
            cbr=None if cbr is None else round(cbr,6),
            tbcr=None if tbcr is None else round(tbcr,6),
            cdi=round(cdi,6),
            information_efficiency=round(information_efficiency,6),
            evidence_novelty=round(evidence_novelty,6),
            duplicate_pressure=round(duplicate_pressure,6),
            unresolved_burn=round(unresolved_burn,6),
            metabolic_strain=round(metabolic_strain,6),
            breath=round(breath,6),
            texture=texture,
            denominator_resolved=denominator_resolved,
            reasons=tuple(sorted(set(reasons))),
            context_units_consumed=round(context,6),
            model_evaluations=model_evals,
            tool_evaluations=tool_evals,
            useful_settled_information_units=round(settled,6),
            information_gain_units=round(info_gain,6),
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )
