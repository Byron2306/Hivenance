from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from agents.horizon_context import HorizonContext
from .edge_ecology import EdgeEcologySnapshot
from .world_graph import WorldGraph, WorldGraphNode


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def evidence_root(source_id: str, payload: Mapping[str, Any]) -> str:
    return _digest({"source_id": str(source_id), "payload": dict(payload)})


def add_horizon_context(
    graph: WorldGraph,
    *,
    context: HorizonContext,
    created_at_ms: int,
    source_roots: Sequence[str],
) -> WorldGraphNode:
    """Bind existing Horizon cognition to the current immutable world."""
    readiness = context.readiness
    ready = sum(1 for value in readiness.values() if value)
    total = max(1, len(readiness))
    freshness = ready / total
    uncertainty = 1.0 - freshness
    return graph.add_node(
        organ_id="horizon_context",
        family="HORIZON",
        created_at_ms=created_at_ms,
        evidence_roots=source_roots,
        lineage_id="hivenance.horizon_context.v1",
        transformation_id="horizon.micro_meso_macro.v1",
        payload=context.to_dict(),
        freshness=freshness,
        uncertainty=uncertainty,
    )


def add_edge_ecology(
    graph: WorldGraph,
    *,
    snapshot: EdgeEcologySnapshot,
    created_at_ms: int,
    family_source_roots: Mapping[str, Sequence[str]],
) -> tuple[WorldGraphNode, ...]:
    """Expose existing Edge voices as separate graph testimony.

    Source roots are supplied by the caller so shared candle/book/flow roots stay
    visible. Different transforms never manufacture independent evidence.
    """
    nodes: list[WorldGraphNode] = []
    for voice in snapshot.voices:
        roots = tuple(family_source_roots.get(voice.family, ()))
        if not roots:
            raise ValueError(f"edge_voice_missing_source_roots:{voice.family}")
        node = graph.add_node(
            organ_id="edge_ecology",
            family=voice.family,
            created_at_ms=created_at_ms,
            evidence_roots=roots,
            lineage_id=f"hivenance.edge_ecology.{voice.family.lower()}.v1",
            transformation_id=f"edge_voice.{voice.family.lower()}.v1",
            payload={
                "pair_id": snapshot.pair_id,
                "timestamp_ms": snapshot.timestamp_ms,
                **voice.to_dict(),
            },
            freshness=1.0,
            uncertainty=max(0.0, min(1.0, 1.0 - float(voice.confidence))),
        )
        nodes.append(node)

    # Make shared evidence roots explicit to Queen instead of letting correlated
    # transforms masquerade as independent witnesses.
    for i, left in enumerate(nodes):
        for right in nodes[i + 1:]:
            shared = tuple(sorted(set(left.evidence_roots) & set(right.evidence_roots)))
            if shared:
                graph.add_edge(
                    edge_type="SAME_ROOT_LINEAGE",
                    source_node_id=left.node_id,
                    target_node_id=right.node_id,
                    evidence_roots=shared,
                    metadata={"reason": "shared_underlying_observation_root"},
                )
    return tuple(nodes)
