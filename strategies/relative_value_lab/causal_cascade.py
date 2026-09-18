from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Optional, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class CascadeEvent:
    event_id: str
    timestamp_ms: int
    event_class: str
    scope: str
    world_state_id: str
    world_state_hash: str
    evidence_root: str
    family: Optional[str] = None
    lineage_root: Optional[str] = None
    pair_id: Optional[str] = None
    asset_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CascadeLink:
    source_event_id: str
    target_event_id: str
    mechanism: str
    mechanism_evidence_root: str
    confidence: float
    relation_class: str = "hypothesized_propagation"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CascadeEdge:
    source_event_id: str
    target_event_id: str
    mechanism: str
    lag_ms: int
    confidence: float
    lineage_independent: bool
    evidence_independent: bool
    valid_temporal_order: bool
    accepted: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CausalCascadeReceipt:
    schema: str
    cascade_id: str
    world_state_id: str
    root_event_ids: tuple[str, ...]
    terminal_event_ids: tuple[str, ...]
    edges: tuple[CascadeEdge, ...]
    depth: int
    breadth: int
    independent_family_count: int
    independent_evidence_roots: int
    scope_path: tuple[str, ...]
    propagation_strength: float
    crescendo: float
    unresolved_links: tuple[str, ...]
    causal_proof: bool
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["edges"] = tuple(edge.to_dict() for edge in self.edges)
        return payload


class CausalCascade:
    """Evidence-bound propagation graph.

    Correlation may motivate a CascadeLink, but correlation alone never creates
    one. Accepted links require temporal order, same world state, explicit
    mechanism semantics, and a mechanism evidence root.

    causal_proof remains false: the receipt describes supported propagation,
    not philosophical or statistical proof of causality.
    """

    version = "hivenance.causal_cascade.v1"

    def build(
        self,
        *,
        events: Sequence[CascadeEvent],
        links: Sequence[CascadeLink],
    ) -> CausalCascadeReceipt:
        event_map = {event.event_id: event for event in events}
        world_states = {event.world_state_id for event in events}
        world_hashes = {event.world_state_hash for event in events}

        accepted_edges: list[CascadeEdge] = []
        unresolved: list[str] = []

        for link in links:
            reasons: list[str] = []
            source = event_map.get(link.source_event_id)
            target = event_map.get(link.target_event_id)
            if source is None or target is None:
                unresolved.append(f"{link.source_event_id}->{link.target_event_id}:missing_event")
                continue

            if (
                source.world_state_id != target.world_state_id
                or source.world_state_hash != target.world_state_hash
            ):
                reasons.append("world_state_mismatch")

            lag = int(target.timestamp_ms - source.timestamp_ms)
            temporal = lag >= 0
            if not temporal:
                reasons.append("reverse_temporal_order")

            if not str(link.mechanism or "").strip():
                reasons.append("mechanism_missing")
            if not str(link.mechanism_evidence_root or "").startswith("sha256:"):
                reasons.append("mechanism_evidence_unbound")

            lineage_independent = bool(
                source.lineage_root
                and target.lineage_root
                and source.lineage_root != target.lineage_root
            )
            evidence_independent = bool(
                source.evidence_root
                and target.evidence_root
                and source.evidence_root != target.evidence_root
                and link.mechanism_evidence_root not in {source.evidence_root, target.evidence_root}
            )

            accepted_edges.append(CascadeEdge(
                source_event_id=source.event_id,
                target_event_id=target.event_id,
                mechanism=link.mechanism,
                lag_ms=lag,
                confidence=round(_clamp(link.confidence), 6),
                lineage_independent=lineage_independent,
                evidence_independent=evidence_independent,
                valid_temporal_order=temporal,
                accepted=not reasons,
                reasons=tuple(reasons),
            ))

        accepted = [edge for edge in accepted_edges if edge.accepted]
        outgoing: dict[str, list[str]] = {}
        incoming: dict[str, list[str]] = {}
        for edge in accepted:
            outgoing.setdefault(edge.source_event_id, []).append(edge.target_event_id)
            incoming.setdefault(edge.target_event_id, []).append(edge.source_event_id)

        roots = sorted(
            event.event_id for event in events
            if event.event_id in outgoing and event.event_id not in incoming
        )
        terminals = sorted(
            event.event_id for event in events
            if event.event_id in incoming and event.event_id not in outgoing
        )

        def longest_from(node: str, seen: set[str]) -> int:
            if node in seen:
                return 0
            children = outgoing.get(node, [])
            if not children:
                return 0
            return 1 + max(longest_from(child, seen | {node}) for child in children)

        depth = max((longest_from(root, set()) for root in roots), default=0)
        breadth = max((len(children) for children in outgoing.values()), default=0)

        families = {
            event.family for event in events
            if event.family and (event.event_id in outgoing or event.event_id in incoming)
        }
        evidence_roots = {
            event.evidence_root for event in events
            if event.evidence_root and (event.event_id in outgoing or event.event_id in incoming)
        }

        scope_order = {"pair": 0, "connected_pairs": 1, "asset": 2, "market": 3}
        scopes: list[str] = []
        for event in sorted(events, key=lambda e: (e.timestamp_ms, e.event_id)):
            scope_key = event.scope.split(":", 1)[0]
            if scope_key not in scopes:
                scopes.append(scope_key)
        scope_path = tuple(sorted(scopes, key=lambda s: scope_order.get(s, 99)))

        if accepted:
            mean_conf = sum(edge.confidence for edge in accepted) / len(accepted)
            independence = sum(
                0.5 * float(edge.lineage_independent) + 0.5 * float(edge.evidence_independent)
                for edge in accepted
            ) / len(accepted)
            depth_factor = _clamp(depth / 4.0)
            breadth_factor = _clamp(breadth / 4.0)
            propagation_strength = _clamp(
                0.45 * mean_conf
                + 0.25 * independence
                + 0.20 * depth_factor
                + 0.10 * breadth_factor
            )
            crescendo = _clamp(
                0.40 * depth_factor
                + 0.25 * breadth_factor
                + 0.20 * _clamp(len(families) / 4.0)
                + 0.15 * mean_conf
            )
        else:
            propagation_strength = 0.0
            crescendo = 0.0

        body = {
            "events": [event.to_dict() for event in events],
            "edges": [edge.to_dict() for edge in accepted_edges],
            "world_states": sorted(world_states),
            "world_hashes": sorted(world_hashes),
        }
        world_state_id = next(iter(world_states)) if len(world_states) == 1 else ""
        return CausalCascadeReceipt(
            schema="hivenance_causal_cascade_v1",
            cascade_id="cascade_" + _digest(body).split(":", 1)[1][:24],
            world_state_id=world_state_id,
            root_event_ids=tuple(roots),
            terminal_event_ids=tuple(terminals),
            edges=tuple(accepted_edges),
            depth=depth,
            breadth=breadth,
            independent_family_count=len(families),
            independent_evidence_roots=len(evidence_roots),
            scope_path=scope_path,
            propagation_strength=round(propagation_strength, 6),
            crescendo=round(crescendo, 6),
            unresolved_links=tuple(unresolved),
            causal_proof=False,
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )
