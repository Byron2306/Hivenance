"""Queen-facing retrieval of qualified Hive learning.

This is an attention/read seam only. It never promotes historical memory into
observed truth or execution authority.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any,Mapping,Sequence
from .world_graph import QueenView,WorldGraphNode

@dataclass(frozen=True)
class LearningBrief:
 learning_ids: tuple[str,...]
 statuses: tuple[str,...]
 supported_claims: tuple[str,...]
 limitations: tuple[str,...]
 weakened_explanations: tuple[str,...]
 next_falsifications: tuple[str,...]
 authorities: tuple[str,...]
 execution_eligible: bool=False
 promotion_eligible: bool=False
 def to_dict(self)->dict[str,Any]:
  return {"learning_ids":self.learning_ids,"statuses":self.statuses,"supported_claims":self.supported_claims,
   "limitations":self.limitations,"weakened_explanations":self.weakened_explanations,
   "next_falsifications":self.next_falsifications,"authorities":self.authorities,
   "execution_eligible":False,"promotion_eligible":False}

def learning_brief(view:QueenView)->LearningBrief:
 nodes=[n for n in view.nodes if n.family=="LEARNING"]
 ids=[];statuses=[];claims=[];limits=[];weak=[];nxt=[];auth=[]
 for n in nodes:
  p=dict(n.payload);ids.append(str(p.get("learning_id",n.node_id)));statuses.append(str(p.get("status","UNKNOWN")));auth.append(str(p.get("authority",n.authority)))
  it=p.get("interpretation") or {}
  if isinstance(it,Mapping):
   if it.get("supported"):claims.append(str(it["supported"]))
   for k,v in it.items():
    if k!="supported" and v:limits.append(f"{k}: {v}")
  weak.extend(str(x) for x in p.get("falsified_or_weakened_explanations",()))
  nxt.extend(str(x) for x in p.get("next_falsification",()))
  if str(p.get("authority",""))=="PROSPECTIVE_SHADOW_RESEARCH_ONLY":
   comparisons=p.get("comparisons") if isinstance(p.get("comparisons"),Mapping) else {}
   for name,delta in comparisons.items():
    claims.append(f"{name}={delta} bps")
   for control in p.get("unsettled_controls",()):
    nxt.append(f"settle shadow control {control}")
 def uq(xs):return tuple(dict.fromkeys(xs))
 return LearningBrief(uq(ids),uq(statuses),uq(claims),uq(limits),uq(weak),uq(nxt),uq(auth))


from .learning_applicability import (
    LiveResearchContext,
    applicability_from_receipt,
    evaluate_learning_applicability,
)


@dataclass(frozen=True)
class ApplicabilityLearningBrief:
    applicable_learning_ids: tuple[str, ...]
    supported_learning_ids: tuple[str, ...]
    contradicted_learning_ids: tuple[str, ...]
    regime_dependent_learning_ids: tuple[str, ...]

    rejected_learning_ids: tuple[str, ...]
    decayed_learning_ids: tuple[str, ...]
    superseded_learning_ids: tuple[str, ...]
    incomplete_learning_ids: tuple[str, ...]

    applicability_decision_ids: tuple[str, ...]

    supported_claims: tuple[str, ...]
    contradictions: tuple[str, ...]
    next_falsifications: tuple[str, ...]

    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "applicable_learning_ids":
                self.applicable_learning_ids,
            "supported_learning_ids":
                self.supported_learning_ids,
            "contradicted_learning_ids":
                self.contradicted_learning_ids,
            "regime_dependent_learning_ids":
                self.regime_dependent_learning_ids,
            "rejected_learning_ids":
                self.rejected_learning_ids,
            "decayed_learning_ids":
                self.decayed_learning_ids,
            "superseded_learning_ids":
                self.superseded_learning_ids,
            "incomplete_learning_ids":
                self.incomplete_learning_ids,
            "applicability_decision_ids":
                self.applicability_decision_ids,
            "supported_claims":
                self.supported_claims,
            "contradictions":
                self.contradictions,
            "next_falsifications":
                self.next_falsifications,
            "execution_eligible": False,
            "promotion_eligible": False,
        }


def applicability_learning_brief(
    view: QueenView,
    *,
    context: LiveResearchContext,
    max_age_ms: int | None = None,
) -> ApplicabilityLearningBrief:
    """Return only applicability-safe learning as influential context."""

    applicable = []
    supported = []
    contradicted = []
    regime_dependent = []

    rejected = []
    decayed = []
    superseded = []
    incomplete = []

    decisions = []
    claims = []
    contradictions = []
    next_tests = []

    for node in view.nodes:
        if node.family != "LEARNING":
            continue

        payload = dict(node.payload)

        learning_id = str(
            payload.get(
                "learning_id",
                node.node_id,
            )
        )

        declared_state = str(
            payload.get(
                "learning_state",
                payload.get(
                    "applicability_state",
                    payload.get("state", "SUPPORTED"),
                ),
            )
        ).upper()

        is_superseded = bool(
            payload.get("superseded", False)
            or payload.get("superseded_by")
        )

        applicability = applicability_from_receipt(
            payload
        )

        decision = evaluate_learning_applicability(
            learning_id=learning_id,
            applicability=applicability,
            context=context,
            max_age_ms=max_age_ms,
            superseded=is_superseded,
            declared_state=declared_state,
        )

        decisions.append(
            decision.decision_id
        )

        if not decision.applicable:
            if decision.state == "DECAYED":
                decayed.append(learning_id)

            elif decision.state == "SUPERSEDED":
                superseded.append(
                    learning_id
                )

            elif decision.state == "INCOMPLETE":
                incomplete.append(
                    learning_id
                )

            else:
                rejected.append(
                    learning_id
                )

            continue

        applicable.append(learning_id)

        interpretation = payload.get(
            "interpretation"
        )

        if decision.state == "CONTRADICTED":
            contradicted.append(
                learning_id
            )

            if isinstance(
                interpretation,
                Mapping,
            ):
                value = (
                    interpretation.get(
                        "contradicted"
                    )
                    or interpretation.get(
                        "supported"
                    )
                )

                if value:
                    contradictions.append(
                        str(value)
                    )

            else:
                contradictions.append(
                    str(
                        payload.get(
                            "contradiction",
                            learning_id,
                        )
                    )
                )

        elif (
            decision.state
            == "REGIME_DEPENDENT"
        ):
            regime_dependent.append(
                learning_id
            )

        else:
            supported.append(
                learning_id
            )

            if isinstance(
                interpretation,
                Mapping,
            ):
                value = interpretation.get(
                    "supported"
                )

                if value:
                    claims.append(
                        str(value)
                    )

        for item in payload.get(
            "next_falsification",
            (),
        ):
            next_tests.append(str(item))

    def uq(values):
        return tuple(
            dict.fromkeys(values)
        )

    return ApplicabilityLearningBrief(
        applicable_learning_ids=uq(
            applicable
        ),
        supported_learning_ids=uq(
            supported
        ),
        contradicted_learning_ids=uq(
            contradicted
        ),
        regime_dependent_learning_ids=uq(
            regime_dependent
        ),
        rejected_learning_ids=uq(
            rejected
        ),
        decayed_learning_ids=uq(
            decayed
        ),
        superseded_learning_ids=uq(
            superseded
        ),
        incomplete_learning_ids=uq(
            incomplete
        ),
        applicability_decision_ids=uq(
            decisions
        ),
        supported_claims=uq(claims),
        contradictions=uq(
            contradictions
        ),
        next_falsifications=uq(
            next_tests
        ),
        execution_eligible=False,
        promotion_eligible=False,
    )
