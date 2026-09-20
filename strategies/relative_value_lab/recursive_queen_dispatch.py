from __future__ import annotations

from typing import Any, Sequence

from .mystique_variations import (
    MystiqueCounterfactualVariations,
    MystiqueObservedScore,
)
from .recursive_queen_loop import (
    QueenResearchRequest,
    QueenResearchResponse,
    build_response,
    observed_root_digest,
)
from .world_graph import WorldGraph, WorldGraphNode


def _source_roots(
    nodes: Sequence[WorldGraphNode],
) -> tuple[str, ...]:
    return tuple(sorted({
        root
        for node in nodes
        for root in node.evidence_roots
    }))


def _assert_request_world(
    graph: WorldGraph,
    request: QueenResearchRequest,
) -> None:
    if request.world_state_id != graph.frame.world_state_id:
        raise ValueError("dispatch_world_state_id_mismatch")

    if request.world_state_hash != graph.frame.world_state_hash:
        raise ValueError("dispatch_world_state_hash_mismatch")

    if request.observed_root_digest != observed_root_digest(graph):
        raise ValueError("dispatch_observed_root_mismatch")


def dispatch_challenge(
    *,
    graph: WorldGraph,
    request: QueenResearchRequest,
    queen_receipt: Any,
    source_nodes: Sequence[WorldGraphNode],
    created_at_ms: int,
) -> tuple[
    QueenResearchResponse,
    WorldGraphNode,
    Any,
]:
    """Answer one CHALLENGE using Mystique on the frozen graph.

    Synthetic Mystique roots remain inside the payload. The graph node inherits
    only observed roots from the lawful source nodes.
    """

    _assert_request_world(graph, request)

    if request.request_kind != "CHALLENGE":
        raise ValueError("challenge_dispatch_requires_challenge_request")

    if not source_nodes:
        raise ValueError("challenge_dispatch_source_nodes_required")

    roots = _source_roots(source_nodes)

    if not roots:
        raise ValueError("challenge_dispatch_observed_roots_required")

    metrics = {
        "motif_strength": max(
            0.0,
            min(
                1.0,
                float(
                    getattr(
                        queen_receipt,
                        "polyphonic_pressure",
                        0.0,
                    )
                ),
            ),
        ),
        "relationship_stability": max(
            0.0,
            min(
                1.0,
                1.0 - float(
                    getattr(
                        queen_receipt,
                        "world_state_tension",
                        0.0,
                    )
                ),
            ),
        ),
        "flow_support": max(
            0.0,
            min(
                1.0,
                float(
                    getattr(
                        queen_receipt,
                        "hunt_pressure",
                        0.0,
                    )
                ),
            ),
        ),
        "depth_recovery": max(
            0.0,
            min(
                1.0,
                float(
                    getattr(
                        queen_receipt,
                        "edge_settlement",
                        0.0,
                    )
                ),
            ),
        ),
        "timing_coherence": max(
            0.0,
            min(
                1.0,
                float(
                    getattr(
                        queen_receipt,
                        "temporal_cadence_coherence",
                        0.0,
                    )
                ),
            ),
        ),
        "lineage_diversity": max(
            0.0,
            min(
                1.0,
                float(
                    getattr(
                        queen_receipt,
                        "timbral_diversity",
                        0.0,
                    )
                ),
            ),
        ),
        "horizon_compatibility": max(
            0.0,
            min(
                1.0,
                float(
                    getattr(
                        queen_receipt,
                        "register_diversity",
                        0.0,
                    )
                ),
            ),
        ),
        "cost_clearance": max(
            0.0,
            min(
                1.0,
                float(
                    getattr(
                        queen_receipt,
                        "edge_chorus_quality",
                        0.0,
                    )
                ),
            ),
        ),
    }

    parent = MystiqueObservedScore(
        score_id=str(queen_receipt.receipt_id),
        hypothesis_id=str(queen_receipt.hypothesis_id),
        world_state_id=graph.frame.world_state_id,
        world_state_hash=graph.frame.world_state_hash,
        observed_at_ms=int(created_at_ms),
        metrics=metrics,
        evidence_roots=roots,
        lineage_roots=tuple(
            sorted({
                str(node.lineage_id)
                for node in source_nodes
            })
        ),
    )

    mystique = MystiqueCounterfactualVariations().challenge(parent)

    if mystique.prospective_evidence_eligible:
        raise ValueError("mystique_became_prospective_evidence")

    if not mystique.contamination_guard_passed:
        raise ValueError("mystique_contamination_guard_failed")

    challenge_node = graph.add_node(
        organ_id="mystique",
        family="MYSTIQUE_CHALLENGE",
        created_at_ms=int(created_at_ms),
        evidence_roots=roots,
        lineage_id=(
            "hivenance.mystique_counterfactual_variations.v1"
        ),
        transformation_id=(
            "queen_request_to_mystique_challenge.v1"
        ),
        payload={
            "request_id": request.request_id,
            "queen_receipt_id": queen_receipt.receipt_id,
            "mystique": mystique.to_dict(),
            "synthetic_evidence_roots": (
                mystique.synthetic_evidence_roots
            ),
            "synthetic_roots_are_observed_evidence": False,
            "execution_eligible": False,
            "promotion_eligible": False,
        },
        freshness=1.0,
        uncertainty=float(mystique.fragility_score),
    )

    response = build_response(
        graph=graph,
        request=request,
        state="ANSWERED",
        organ_id="mystique",
        answer=(
            "synthetic counterfactual challenge completed; "
            f"fragility={mystique.fragility_score:.6f}; "
            f"survival={mystique.survival_rate:.6f}"
        ),
        source_nodes=source_nodes,
        added_nodes=(challenge_node,),
    )

    return response, challenge_node, mystique
