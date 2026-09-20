from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .historical_causal_prosecution import HistoricalOrganProsecution
from .organ_topology import topology_by_id


def _digest(value: Any) -> str:
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")
    return "sha256:"+hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class OrganUtilityRow:
    organ_id: str
    layer: str
    disposition: str
    availability_state: str
    invoked_count: int
    decision_change_count: int
    paired_world_count: int
    dependence_adjusted_world_count: int
    historical_paired_delta_bps: float | None
    uncertainty_bps: float | None
    utility_state: str
    recommendation: str
    execution_eligible: bool=False
    promotion_eligible: bool=False

    def __post_init__(self)->None:
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("organ_utility_authority_escalation_forbidden")

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


@dataclass(frozen=True)
class OrganUtilityCensus:
    schema: str
    census_id: str
    rows: tuple[OrganUtilityRow,...]
    useful_organs: tuple[str,...]
    harmful_organs: tuple[str,...]
    inert_organs: tuple[str,...]
    underpowered_organs: tuple[str,...]
    mixed_organs: tuple[str,...]
    unavailable_organs: tuple[str,...]
    historical_only: bool=True
    execution_eligible: bool=False
    promotion_eligible: bool=False

    def __post_init__(self)->None:
        if not self.historical_only:
            raise ValueError("organ_utility_census_must_be_historical")
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("organ_utility_census_authority_escalation_forbidden")

    def to_dict(self)->dict[str,Any]:
        payload=asdict(self)
        payload["rows"]=tuple(row.to_dict() for row in self.rows)
        return payload


def _utility_state(row: HistoricalOrganProsecution)->str:
    if not row.available:
        return "UNAVAILABLE"
    if row.invoked_count<=0:
        return "AVAILABLE_NOT_INVOKED"
    if row.decision_change_count<=0:
        return "INERT_ON_TESTED_WORLDS"
    if row.classification=="HISTORICALLY_USEFUL":
        return "HISTORICALLY_USEFUL"
    if row.classification=="HISTORICALLY_HARMFUL":
        return "HISTORICALLY_HARMFUL"
    if row.classification in {"INSUFFICIENT_EVIDENCE","INFLUENTIAL"}:
        return "INFLUENTIAL_UNDERPOWERED"
    if row.classification=="HISTORICALLY_NEUTRAL":
        return "HISTORICALLY_NEUTRAL"
    if row.classification=="HISTORICALLY_MIXED":
        return "HISTORICALLY_MIXED"
    return row.classification


def _recommendation(state:str)->str:
    return {
        "UNAVAILABLE":"WIRE_OR_DOCUMENT_ABSENCE",
        "AVAILABLE_NOT_INVOKED":"CHECK_RUNTIME_ROUTE",
        "INERT_ON_TESTED_WORLDS":"RETAIN_ONLY_IF_GOVERNANCE_OR_FALSIFICATION_ROLE",
        "HISTORICALLY_USEFUL":"RETAIN_FOR_PROSPECTIVE_SHADOW_TEST",
        "HISTORICALLY_HARMFUL":"QUARANTINE_OR_REDESIGN_BEFORE_PROSPECTIVE_USE",
        "INFLUENTIAL_UNDERPOWERED":"RETAIN_AND_GATHER_MORE_INDEPENDENT_WORLDS",
        "HISTORICALLY_NEUTRAL":"REVIEW_COMPLEXITY_VS_GOVERNANCE_VALUE",
        "HISTORICALLY_MIXED":"SEGMENT_OR_REDESIGN_BEFORE_PROSPECTIVE_USE",
    }.get(state,"REVIEW")


def build_organ_utility_census(
    results: Sequence[HistoricalOrganProsecution],
    *,
    topology_aliases: Mapping[str,str]|None=None,
)->OrganUtilityCensus:
    topology=topology_by_id()
    aliases={str(k):str(v) for k,v in dict(topology_aliases or {}).items()}
    rows=[]

    for result in sorted(results,key=lambda x:(x.organ_id,x.mask_id)):
        topo_id=aliases.get(result.organ_id,result.organ_id)
        topo=topology.get(topo_id)
        state=_utility_state(result)
        rows.append(
            OrganUtilityRow(
                organ_id=result.organ_id,
                layer=topo.layer if topo else "UNMAPPED",
                disposition=topo.disposition if topo else "MAP_REQUIRED",
                availability_state=result.classification,
                invoked_count=int(result.invoked_count),
                decision_change_count=int(result.decision_change_count),
                paired_world_count=int(result.paired_world_count),
                dependence_adjusted_world_count=int(result.dependence_adjusted_world_count),
                historical_paired_delta_bps=(
                    None if result.historical_paired_delta_bps is None
                    else round(float(result.historical_paired_delta_bps),8)
                ),
                uncertainty_bps=(
                    None if result.uncertainty_bps is None
                    else round(float(result.uncertainty_bps),8)
                ),
                utility_state=state,
                recommendation=_recommendation(state),
            )
        )

    useful=tuple(sorted(r.organ_id for r in rows if r.utility_state=="HISTORICALLY_USEFUL"))
    harmful=tuple(sorted(r.organ_id for r in rows if r.utility_state=="HISTORICALLY_HARMFUL"))
    inert=tuple(sorted(r.organ_id for r in rows if r.utility_state=="INERT_ON_TESTED_WORLDS"))
    underpowered=tuple(sorted(r.organ_id for r in rows if r.utility_state=="INFLUENTIAL_UNDERPOWERED"))
    mixed=tuple(sorted(r.organ_id for r in rows if r.utility_state=="HISTORICALLY_MIXED"))
    unavailable=tuple(sorted(r.organ_id for r in rows if r.utility_state=="UNAVAILABLE"))

    body={
        "rows":[row.to_dict() for row in rows],
        "useful":useful,
        "harmful":harmful,
        "inert":inert,
        "underpowered":underpowered,
        "unavailable":unavailable,
    }

    return OrganUtilityCensus(
        schema="hivenance_organ_utility_census_v1",
        census_id="ouc_"+_digest(body).split(":",1)[1][:24],
        rows=tuple(rows),
        useful_organs=useful,
        harmful_organs=harmful,
        inert_organs=inert,
        underpowered_organs=underpowered,
        mixed_organs=mixed,
        unavailable_organs=unavailable,
    )
