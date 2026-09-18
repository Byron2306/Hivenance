from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Optional, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY


def _clamp(v:float)->float:
    return max(0.0,min(1.0,float(v)))


def _digest(payload:Any)->str:
    raw=json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")
    return "sha256:"+hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class CorrelationEvent:
    event_id: str
    timestamp_ms: int
    scope: str
    pair_id: Optional[str]=None
    asset_ids: tuple[str,...]=()
    venue: Optional[str]=None
    feature_family: Optional[str]=None
    hypothesis_family: Optional[str]=None
    lineage_root: Optional[str]=None
    evidence_root: Optional[str]=None
    cascade_parent_id: Optional[str]=None

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


@dataclass(frozen=True)
class ColonyCorrelationReceipt:
    schema: str
    correlation_id: str
    left_event_id: str
    right_event_id: str
    correlation_score: float
    temporal_distance_ms: int
    shared_assets: tuple[str,...]
    same_pair: bool
    same_venue: bool
    same_feature_family: bool
    same_hypothesis_family: bool
    shared_lineage: bool
    shared_evidence_root: bool
    cascade_ancestry_link: bool
    family_diversity: float
    confidence: float
    causal_claim: bool
    rationale: tuple[str,...]
    authority: str=RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool=False
    promotion_eligible: bool=False

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


class ColonyCorrelator:
    """Cross-time/pair thematic linker with causality disabled by construction."""

    version="hivenance.colony_correlation.v1"

    def __init__(self,*,temporal_window_ms:int=30_000)->None:
        self.temporal_window_ms=max(1,int(temporal_window_ms))

    def correlate(self,events:Sequence[CorrelationEvent])->tuple[ColonyCorrelationReceipt,...]:
        ordered=sorted(events,key=lambda e:(e.timestamp_ms,e.event_id))
        out=[]
        for i,left in enumerate(ordered):
            for right in ordered[i+1:]:
                dt=max(0,int(right.timestamp_ms-left.timestamp_ms))
                if dt>self.temporal_window_ms:
                    break

                shared_assets=tuple(sorted(set(left.asset_ids).intersection(right.asset_ids)))
                same_pair=bool(left.pair_id and left.pair_id==right.pair_id)
                same_venue=bool(left.venue and left.venue==right.venue)
                same_feature=bool(left.feature_family and left.feature_family==right.feature_family)
                same_hyp=bool(left.hypothesis_family and left.hypothesis_family==right.hypothesis_family)
                shared_lineage=bool(left.lineage_root and left.lineage_root==right.lineage_root)
                shared_root=bool(left.evidence_root and left.evidence_root==right.evidence_root)
                ancestry=bool(
                    (left.cascade_parent_id and left.cascade_parent_id==right.event_id)
                    or (right.cascade_parent_id and right.cascade_parent_id==left.event_id)
                )

                temporal=_clamp(1.0-dt/self.temporal_window_ms)
                relationship=_clamp(
                    .24*float(bool(shared_assets))
                    +.22*float(same_pair)
                    +.12*float(same_venue)
                    +.14*float(same_feature)
                    +.12*float(same_hyp)
                    +.16*float(ancestry)
                )
                score=_clamp(.45*temporal+.55*relationship)

                independent_families=len({
                    x for x in (left.feature_family,right.feature_family) if x
                })
                family_diversity=_clamp(independent_families/2.0)

                dependence_penalty=.0
                if shared_lineage:
                    dependence_penalty+=.25
                if shared_root:
                    dependence_penalty+=.35
                confidence=_clamp(score*(.65+.35*family_diversity)-dependence_penalty)

                if score<=.15:
                    continue

                rationale=[]
                if shared_assets: rationale.append("shared_assets:"+",".join(shared_assets))
                if same_pair: rationale.append("same_pair")
                if same_venue: rationale.append("same_venue")
                if same_feature: rationale.append("same_feature_family")
                if same_hyp: rationale.append("same_hypothesis_family")
                if ancestry: rationale.append("cascade_ancestry")
                if shared_lineage: rationale.append("shared_lineage_dependence")
                if shared_root: rationale.append("shared_evidence_dependence")

                body={
                    "left":left.event_id,"right":right.event_id,
                    "dt":dt,"score":round(score,6),
                }
                out.append(ColonyCorrelationReceipt(
                    schema="hivenance_colony_correlation_v1",
                    correlation_id="corr_"+_digest(body).split(":",1)[1][:24],
                    left_event_id=left.event_id,
                    right_event_id=right.event_id,
                    correlation_score=round(score,6),
                    temporal_distance_ms=dt,
                    shared_assets=shared_assets,
                    same_pair=same_pair,
                    same_venue=same_venue,
                    same_feature_family=same_feature,
                    same_hypothesis_family=same_hyp,
                    shared_lineage=shared_lineage,
                    shared_evidence_root=shared_root,
                    cascade_ancestry_link=ancestry,
                    family_diversity=round(family_diversity,6),
                    confidence=round(confidence,6),
                    causal_claim=False,
                    rationale=tuple(rationale),
                    authority=RELATIVE_VALUE_AUTHORITY,
                    execution_eligible=False,
                    promotion_eligible=False,
                ))
        return tuple(out)
