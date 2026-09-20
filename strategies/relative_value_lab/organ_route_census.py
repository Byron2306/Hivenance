from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .organ_topology import ORGANS


@dataclass(frozen=True)
class OrganRouteStatus:
    organ_id: str
    expected_layer: str
    expected_disposition: str
    runtime_seen: bool
    invocation_count: int
    route_state: str
    reason: str
    execution_eligible: bool=False
    promotion_eligible: bool=False

    def __post_init__(self)->None:
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("organ_route_status_authority_escalation_forbidden")

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


@dataclass(frozen=True)
class OrganRouteCensus:
    schema: str
    rows: tuple[OrganRouteStatus,...]
    dead_routes: tuple[str,...]
    active_routes: tuple[str,...]
    optional_routes: tuple[str,...]
    execution_eligible: bool=False
    promotion_eligible: bool=False

    def to_dict(self)->dict[str,Any]:
        return {
            "schema":self.schema,
            "rows":tuple(row.to_dict() for row in self.rows),
            "dead_routes":self.dead_routes,
            "active_routes":self.active_routes,
            "optional_routes":self.optional_routes,
            "execution_eligible":False,
            "promotion_eligible":False,
        }


def build_route_census(
    *,
    invocation_counts: Mapping[str,int],
    runtime_seen_ids: Sequence[str],
    aliases: Mapping[str,str]|None=None,
)->OrganRouteCensus:
    seen={str(x) for x in runtime_seen_ids}
    alias={str(k):str(v) for k,v in dict(aliases or {}).items()}
    rows=[]

    for topo in ORGANS:
        runtime_id=alias.get(topo.organ_id,topo.organ_id)
        count=int(invocation_counts.get(runtime_id,invocation_counts.get(topo.organ_id,0)))
        runtime_seen=(runtime_id in seen) or (topo.organ_id in seen)

        optional=topo.disposition in {
            "KEEP_LOCKED_DOWNSTREAM",
            "RETAIN_RESEARCH_GENERATOR",
            "RETAIN_DISCOVERY_ONLY",
            "RETAIN_MECHANISM_LAYER",
        }

        if count>0:
            state="ACTIVE"
            reason="runtime_invocations_observed"
        elif runtime_seen:
            state="WIRED_NOT_INVOKED"
            reason="runtime_route_present_without_invocation"
        elif optional:
            state="OPTIONAL_OR_DOWNSTREAM"
            reason="route_absence_may_be_expected_in_current_phase"
        else:
            state="DEAD_OR_UNWIRED"
            reason="topology_declares_organ_but_runtime_route_not_observed"

        rows.append(
            OrganRouteStatus(
                organ_id=topo.organ_id,
                expected_layer=topo.layer,
                expected_disposition=topo.disposition,
                runtime_seen=runtime_seen,
                invocation_count=count,
                route_state=state,
                reason=reason,
            )
        )

    dead=tuple(sorted(r.organ_id for r in rows if r.route_state=="DEAD_OR_UNWIRED"))
    active=tuple(sorted(r.organ_id for r in rows if r.route_state=="ACTIVE"))
    optional=tuple(sorted(r.organ_id for r in rows if r.route_state=="OPTIONAL_OR_DOWNSTREAM"))

    return OrganRouteCensus(
        schema="hivenance_organ_route_census_v1",
        rows=tuple(rows),
        dead_routes=dead,
        active_routes=active,
        optional_routes=optional,
    )
