from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .world_score import (
    CanonicalScoreFrame,
    INTERPRETED_NAMESPACE,
    SYNTHETIC_NAMESPACE,
)


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


PHASE5_MAJOR_EVIDENCE_FAMILIES = {
    "TEMPORAL_PARTICIPATION",
    "FLOW",
    "LIQUIDITY",
    "VOLATILITY",
    "CROSS_MARKET",
    "PATH_GEOMETRY",
    "REGIME",
    "DERIVATIVES_CARRY",
    "INFORMATION_ARRIVAL",
    "SLOW_CAPITAL_ONCHAIN",
    "EXTERNAL_STATISTICS",
}


def _validate_phase5_queen_evidence(nodes: Sequence["WorldGraphNode"]) -> None:
    """Fail closed if a Phase-5 evidence family bypasses BeeEvidence."""

    violations = []

    for node in nodes:
        if node.synthetic:
            continue

        if node.family not in PHASE5_MAJOR_EVIDENCE_FAMILIES:
            continue

        payload = node.payload if isinstance(node.payload, Mapping) else {}

        if node.organ_id != "bee_evidence":
            violations.append(
                f"{node.family}:noncanonical_organ:{node.organ_id}"
            )
            continue

        if payload.get("schema") != "hivenance_bee_evidence_v1":
            violations.append(
                f"{node.family}:noncanonical_schema:"
                f"{payload.get('schema')}"
            )
            continue

        if payload.get("family") != node.family:
            violations.append(
                f"{node.family}:payload_family_mismatch:"
                f"{payload.get('family')}"
            )

        if payload.get("execution_eligible") is not False:
            violations.append(
                f"{node.family}:execution_authority_not_false"
            )

        if payload.get("promotion_eligible") is not False:
            violations.append(
                f"{node.family}:promotion_authority_not_false"
            )

    if violations:
        raise ValueError(
            "queen_noncanonical_phase5_evidence:"
            + "|".join(sorted(violations))
        )


EDGE_TYPES = {
    "DERIVED_FROM",
    "COMPARES_WITH",
    "CORROBORATES",
    "CONTRADICTS",
    "CHALLENGES",
    "SELECTED_OVER",
    "REJECTED_AGAINST",
    "SAME_ROOT_LINEAGE",
    "TEMPORALLY_PRECEDES",
    "SETTLES",
    "SUPERSEDES",
    "INFLUENCES",
}


@dataclass(frozen=True)
class WorldGraphNode:
    node_id: str
    organ_id: str
    family: str
    world_state_id: str
    world_state_hash: str
    created_at_ms: int
    evidence_roots: tuple[str, ...]
    lineage_id: str
    transformation_id: str
    payload: Mapping[str, Any]
    freshness: float = 1.0
    uncertainty: float = 0.0
    synthetic: bool = False
    namespace: str = INTERPRETED_NAMESPACE
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if not self.world_state_id or not str(self.world_state_hash).startswith("sha256:"):
            raise ValueError("world_graph_node_unbound")
        if self.synthetic and self.namespace != SYNTHETIC_NAMESPACE:
            raise ValueError("synthetic_node_namespace_mismatch")
        if not self.synthetic and self.namespace != INTERPRETED_NAMESPACE:
            raise ValueError("interpreted_node_namespace_mismatch")
        if any(not str(root).startswith("sha256:") for root in self.evidence_roots):
            raise ValueError("world_graph_node_evidence_unbound")
        if not 0.0 <= float(self.freshness) <= 1.0:
            raise ValueError("world_graph_node_freshness_out_of_range")
        if not 0.0 <= float(self.uncertainty) <= 1.0:
            raise ValueError("world_graph_node_uncertainty_out_of_range")
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("world_graph_node_authority_escalation_forbidden")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorldGraphEdge:
    edge_id: str
    edge_type: str
    source_node_id: str
    target_node_id: str
    world_state_id: str
    evidence_roots: tuple[str, ...] = ()
    weight: float = 1.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.edge_type not in EDGE_TYPES:
            raise ValueError("unknown_world_graph_edge_type")
        if not self.source_node_id or not self.target_node_id:
            raise ValueError("world_graph_edge_endpoint_missing")
        if any(not str(root).startswith("sha256:") for root in self.evidence_roots):
            raise ValueError("world_graph_edge_evidence_unbound")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QueenView:
    schema: str
    view_id: str
    world_state_id: str
    world_state_hash: str
    created_at_ms: int
    node_count: int
    edge_count: int
    families: tuple[str, ...]
    active_node_ids: tuple[str, ...]
    stale_node_ids: tuple[str, ...]
    uncertain_node_ids: tuple[str, ...]
    synthetic_node_ids: tuple[str, ...]
    contradiction_edges: tuple[str, ...]
    corroboration_edges: tuple[str, ...]
    same_root_edges: tuple[str, ...]
    missing_expected_families: tuple[str, ...]
    independent_evidence_root_count: int
    nodes: tuple[WorldGraphNode, ...]
    edges: tuple[WorldGraphEdge, ...]
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["nodes"] = tuple(n.to_dict() for n in self.nodes)
        payload["edges"] = tuple(e.to_dict() for e in self.edges)
        return payload


class WorldGraph:
    """Immutable-world, mutable-interpretation graph for Queen cognition.

    The CanonicalScoreFrame remains observed truth. Graph nodes may interpret,
    compare or challenge it, but cannot mutate its digest or gain authority.
    """

    version = "hivenance.world_graph.v1"

    def __init__(self, frame: CanonicalScoreFrame) -> None:
        self.frame = frame
        self._nodes: dict[str, WorldGraphNode] = {}
        self._edges: dict[str, WorldGraphEdge] = {}

    def add_node(
        self,
        *,
        organ_id: str,
        family: str,
        created_at_ms: int,
        evidence_roots: Sequence[str],
        lineage_id: str,
        transformation_id: str,
        payload: Mapping[str, Any],
        freshness: float = 1.0,
        uncertainty: float = 0.0,
        synthetic: bool = False,
    ) -> WorldGraphNode:
        roots = tuple(sorted(set(str(r) for r in evidence_roots)))
        body = {
            "organ_id": organ_id,
            "family": family,
            "world_state_id": self.frame.world_state_id,
            "created_at_ms": int(created_at_ms),
            "evidence_roots": roots,
            "lineage_id": lineage_id,
            "transformation_id": transformation_id,
            "payload": dict(payload),
            "synthetic": bool(synthetic),
        }
        node_id = "wgn_" + _digest(body).split(":", 1)[1][:24]
        node = WorldGraphNode(
            node_id=node_id,
            organ_id=str(organ_id),
            family=str(family),
            world_state_id=self.frame.world_state_id,
            world_state_hash=self.frame.world_state_hash,
            created_at_ms=int(created_at_ms),
            evidence_roots=roots,
            lineage_id=str(lineage_id),
            transformation_id=str(transformation_id),
            payload=dict(payload),
            freshness=float(freshness),
            uncertainty=float(uncertainty),
            synthetic=bool(synthetic),
            namespace=SYNTHETIC_NAMESPACE if synthetic else INTERPRETED_NAMESPACE,
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )
        self._nodes[node_id] = node
        return node

    def add_edge(
        self,
        *,
        edge_type: str,
        source_node_id: str,
        target_node_id: str,
        evidence_roots: Sequence[str] = (),
        weight: float = 1.0,
        metadata: Mapping[str, Any] | None = None,
    ) -> WorldGraphEdge:
        if source_node_id not in self._nodes or target_node_id not in self._nodes:
            raise ValueError("world_graph_edge_endpoint_unknown")
        roots = tuple(sorted(set(str(r) for r in evidence_roots)))
        body = {
            "edge_type": edge_type,
            "source": source_node_id,
            "target": target_node_id,
            "world_state_id": self.frame.world_state_id,
            "evidence_roots": roots,
            "weight": round(float(weight), 9),
            "metadata": dict(metadata or {}),
        }
        edge_id = "wge_" + _digest(body).split(":", 1)[1][:24]
        edge = WorldGraphEdge(
            edge_id=edge_id,
            edge_type=str(edge_type),
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            world_state_id=self.frame.world_state_id,
            evidence_roots=roots,
            weight=float(weight),
            metadata=dict(metadata or {}),
        )
        self._edges[edge_id] = edge
        return edge

    def queen_view(
        self,
        *,
        created_at_ms: int,
        expected_families: Sequence[str] = (),
        stale_below: float = 0.35,
        uncertain_above: float = 0.70,
    ) -> QueenView:
        nodes = tuple(sorted(self._nodes.values(), key=lambda n: n.node_id))

        # Phase-5 exit gate:
        # major evidence families may reach Queen only through canonical
        # BeeEvidence envelopes.
        _validate_phase5_queen_evidence(nodes)

        edges = tuple(sorted(self._edges.values(), key=lambda e: e.edge_id))
        families = tuple(sorted({n.family for n in nodes if not n.synthetic}))
        expected = {str(x) for x in expected_families}
        roots = {root for n in nodes if not n.synthetic for root in n.evidence_roots}
        body = {
            "world_state_id": self.frame.world_state_id,
            "world_state_hash": self.frame.world_state_hash,
            "created_at_ms": int(created_at_ms),
            "nodes": [n.node_id for n in nodes],
            "edges": [e.edge_id for e in edges],
            "expected_families": sorted(expected),
        }
        return QueenView(
            schema="hivenance_queen_world_graph_view_v1",
            view_id="qv_" + _digest(body).split(":", 1)[1][:24],
            world_state_id=self.frame.world_state_id,
            world_state_hash=self.frame.world_state_hash,
            created_at_ms=int(created_at_ms),
            node_count=len(nodes),
            edge_count=len(edges),
            families=families,
            active_node_ids=tuple(n.node_id for n in nodes if n.freshness >= stale_below),
            stale_node_ids=tuple(n.node_id for n in nodes if n.freshness < stale_below),
            uncertain_node_ids=tuple(n.node_id for n in nodes if n.uncertainty > uncertain_above),
            synthetic_node_ids=tuple(n.node_id for n in nodes if n.synthetic),
            contradiction_edges=tuple(e.edge_id for e in edges if e.edge_type == "CONTRADICTS"),
            corroboration_edges=tuple(e.edge_id for e in edges if e.edge_type == "CORROBORATES"),
            same_root_edges=tuple(e.edge_id for e in edges if e.edge_type == "SAME_ROOT_LINEAGE"),
            missing_expected_families=tuple(sorted(expected - set(families))),
            independent_evidence_root_count=len(roots),
            nodes=nodes,
            edges=edges,
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )
