from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class WorkerComponentUtility:
    mask_id: str
    model_id: str
    testable_worlds: int
    changed_worlds: int
    decision_changes: int
    helpful_changes: int
    harmful_changes: int
    mean_delta_bps: float | None
    dependence_adjusted_worlds: int
    positive_cohorts: int
    negative_cohorts: int
    classification: str
    recommendation: str
    execution_eligible: bool=False
    promotion_eligible: bool=False

    def __post_init__(self)->None:
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("worker_component_utility_authority_escalation_forbidden")

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


def classify_worker_component(
    *,
    mask_id: str,
    model_id: str,
    testable_worlds: int,
    changed_worlds: int,
    decision_changes: int,
    helpful_changes: int,
    harmful_changes: int,
    mean_delta_bps: float | None,
    dependence_adjusted_worlds: int,
    positive_cohorts: int,
    negative_cohorts: int,
    minimum_independent_worlds: int=5,
)->WorkerComponentUtility:
    if int(decision_changes)<=0:
        classification="INERT_ON_TESTED_WORLDS"
        recommendation="RETAIN_ONLY_IF_SPECIALIST_OR_GOVERNANCE_VALUE"
    elif int(dependence_adjusted_worlds)<int(minimum_independent_worlds):
        classification="INFLUENTIAL_UNDERPOWERED"
        recommendation="RETAIN_AND_GATHER_MORE_INDEPENDENT_WORLDS"
    elif int(positive_cohorts)>0 and int(negative_cohorts)>0:
        classification="HISTORICALLY_MIXED"
        recommendation="SEGMENT_OR_REDESIGN_BEFORE_PROSPECTIVE_USE"
    elif int(positive_cohorts)>0 and int(negative_cohorts)==0:
        classification="HISTORICALLY_USEFUL"
        recommendation="RETAIN_FOR_PROSPECTIVE_SHADOW_TEST"
    elif int(negative_cohorts)>0 and int(positive_cohorts)==0:
        classification="HISTORICALLY_HARMFUL"
        recommendation="QUARANTINE_OR_REDESIGN_BEFORE_PROSPECTIVE_USE"
    elif mean_delta_bps is not None and float(mean_delta_bps)>0:
        classification="HISTORICALLY_USEFUL"
        recommendation="RETAIN_FOR_PROSPECTIVE_SHADOW_TEST"
    elif mean_delta_bps is not None and float(mean_delta_bps)<0:
        classification="HISTORICALLY_HARMFUL"
        recommendation="QUARANTINE_OR_REDESIGN_BEFORE_PROSPECTIVE_USE"
    else:
        classification="HISTORICALLY_NEUTRAL"
        recommendation="REVIEW_COMPLEXITY_VS_SPECIALIST_VALUE"

    return WorkerComponentUtility(
        mask_id=str(mask_id),
        model_id=str(model_id),
        testable_worlds=int(testable_worlds),
        changed_worlds=int(changed_worlds),
        decision_changes=int(decision_changes),
        helpful_changes=int(helpful_changes),
        harmful_changes=int(harmful_changes),
        mean_delta_bps=None if mean_delta_bps is None else float(mean_delta_bps),
        dependence_adjusted_worlds=int(dependence_adjusted_worlds),
        positive_cohorts=int(positive_cohorts),
        negative_cohorts=int(negative_cohorts),
        classification=classification,
        recommendation=recommendation,
    )
