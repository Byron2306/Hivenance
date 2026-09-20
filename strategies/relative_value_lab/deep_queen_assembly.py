from __future__ import annotations

from typing import Any, Sequence

from .queen_input_assembly import QueenInputChannel, channel
from .world_graph import WorldGraph, WorldGraphNode


def _roots(
    nodes: Sequence[WorldGraphNode],
) -> tuple[str, ...]:
    return tuple(sorted({
        root
        for node in nodes
        for root in node.evidence_roots
    }))


def _require_sources(
    nodes: Sequence[WorldGraphNode],
    label: str,
) -> None:
    if not nodes:
        raise ValueError(f"{label}_source_nodes_required")


def _assert_world(
    graph: WorldGraph,
    *,
    world_state_id: str,
    world_state_hash: str,
    label: str,
) -> None:
    if str(world_state_id) != str(graph.frame.world_state_id):
        raise ValueError(f"{label}_world_state_id_mismatch")

    if str(world_state_hash) != str(graph.frame.world_state_hash):
        raise ValueError(f"{label}_world_state_hash_mismatch")


def add_harmonic_context_node(
    graph: WorldGraph,
    *,
    harmonic: Any,
    source_nodes: Sequence[WorldGraphNode],
    created_at_ms: int,
) -> WorldGraphNode:
    _require_sources(source_nodes, "harmonic_context")

    return graph.add_node(
        organ_id="harmonic_governance",
        family="HARMONIC_CONTEXT",
        created_at_ms=int(created_at_ms),
        evidence_roots=_roots(source_nodes),
        lineage_id="phoenix.harmonic_forecast_governance.v2",
        transformation_id="forecast_voices_to_harmonic_context.v1",
        payload={
            **harmonic.to_dict(),
            "source_node_ids": tuple(
                sorted(node.node_id for node in source_nodes)
            ),
            "execution_eligible": False,
            "promotion_eligible": False,
        },
        freshness=1.0,
        uncertainty=max(
            0.0,
            min(1.0, float(harmonic.discord_score)),
        ),
    )


def add_polyphonic_resonance_node(
    graph: WorldGraph,
    *,
    resonance: Any,
    source_nodes: Sequence[WorldGraphNode],
    created_at_ms: int,
) -> WorldGraphNode:
    _require_sources(source_nodes, "polyphonic_resonance")

    return graph.add_node(
        organ_id="polyphonic_resonance",
        family="POLYPHONIC_RESONANCE",
        created_at_ms=int(created_at_ms),
        evidence_roots=_roots(source_nodes),
        lineage_id="hivenance.polyphonic_resonance.v1",
        transformation_id="harmonic_polyphia_to_resonance.v1",
        payload={
            **resonance.to_dict(),
            "source_node_ids": tuple(
                sorted(node.node_id for node in source_nodes)
            ),
            "execution_eligible": False,
            "promotion_eligible": False,
        },
        freshness=1.0,
        uncertainty=max(
            0.0,
            min(1.0, float(resonance.cross_band_tension)),
        ),
    )


def add_mystique_node(
    graph: WorldGraph,
    *,
    mystique: Any,
    source_nodes: Sequence[WorldGraphNode],
    created_at_ms: int,
) -> WorldGraphNode:
    _require_sources(source_nodes, "mystique")

    if not mystique.contamination_guard_passed:
        raise ValueError("mystique_contamination_guard_failed")

    if not mystique.observed_namespace_untouched:
        raise ValueError("mystique_observed_namespace_mutated")

    if mystique.prospective_evidence_eligible:
        raise ValueError("mystique_prospective_evidence_forbidden")

    # Critical boundary:
    # synthetic_evidence_roots are deliberately NOT WorldGraph evidence_roots.
    return graph.add_node(
        organ_id="mystique",
        family="MYSTIQUE_CHALLENGE",
        created_at_ms=int(created_at_ms),
        evidence_roots=_roots(source_nodes),
        lineage_id="hivenance.mystique_counterfactual_variations.v1",
        transformation_id="observed_score_to_counterfactual_challenge.v1",
        payload={
            **mystique.to_dict(),
            "source_node_ids": tuple(
                sorted(node.node_id for node in source_nodes)
            ),
            "synthetic_roots_are_observed_evidence": False,
            "execution_eligible": False,
            "promotion_eligible": False,
        },
        freshness=1.0,
        uncertainty=max(
            0.0,
            min(1.0, float(mystique.fragility_score)),
        ),
    )


def add_metabolism_node(
    graph: WorldGraph,
    *,
    metabolism: Any,
    source_nodes: Sequence[WorldGraphNode],
    created_at_ms: int,
) -> WorldGraphNode:
    _require_sources(source_nodes, "cognitive_metabolism")

    return graph.add_node(
        organ_id="cognitive_metabolism",
        family="COGNITIVE_METABOLISM",
        created_at_ms=int(created_at_ms),
        evidence_roots=_roots(source_nodes),
        lineage_id="hivenance.cognitive_metabolism.v1",
        transformation_id="research_consumption_to_metabolic_receipt.v1",
        payload={
            **metabolism.to_dict(),
            "source_node_ids": tuple(
                sorted(node.node_id for node in source_nodes)
            ),
            "market_evidence": False,
            "execution_eligible": False,
            "promotion_eligible": False,
        },
        freshness=1.0,
        uncertainty=max(
            0.0,
            min(1.0, float(metabolism.metabolic_strain)),
        ),
    )


def add_learned_challenger_node(
    graph: WorldGraph,
    *,
    receipts: Sequence[Any],
    source_nodes: Sequence[WorldGraphNode],
    created_at_ms: int,
) -> WorldGraphNode:
    if not receipts:
        raise ValueError("learned_challenger_receipts_required")

    _require_sources(source_nodes, "learned_challenger")

    for receipt in receipts:
        _assert_world(
            graph,
            world_state_id=receipt.world_state_id,
            world_state_hash=receipt.world_state_hash,
            label="learned_challenger",
        )

        if receipt.execution_eligible or receipt.promotion_eligible:
            raise ValueError(
                "learned_challenger_authority_escalation"
            )

    # The model artifact/training/feature digests remain model provenance.
    # They do not become independent market evidence roots here.
    return graph.add_node(
        organ_id="learned_challenger",
        family="LEARNED_CHALLENGER",
        created_at_ms=int(created_at_ms),
        evidence_roots=_roots(source_nodes),
        lineage_id="hivenance.learned_challenger.v1",
        transformation_id="learned_forecast_to_challenger_receipt.v1",
        payload={
            "schema": "hivenance_learned_challenger_context_v1",
            "receipt_count": len(receipts),
            "receipts": tuple(
                receipt.to_dict()
                for receipt in receipts
            ),
            "source_node_ids": tuple(
                sorted(node.node_id for node in source_nodes)
            ),
            "market_evidence_roots_inherited_from_sources": True,
            "model_provenance_is_independent_market_evidence": False,
            "execution_eligible": False,
            "promotion_eligible": False,
        },
        freshness=min(
            float(receipt.freshness)
            for receipt in receipts
        ),
        uncertainty=max(
            float(receipt.uncertainty_pressure)
            for receipt in receipts
        ),
    )


def add_governance_epoch_node(
    graph: WorldGraph,
    *,
    epoch: Any,
    validation: Any,
    created_at_ms: int,
) -> WorldGraphNode:
    _assert_world(
        graph,
        world_state_id=epoch.world_state_id,
        world_state_hash=epoch.world_state_hash,
        label="governance_epoch",
    )

    if not validation.valid:
        raise ValueError("governance_epoch_invalid")

    roots = tuple(sorted({
        obs.evidence_root
        for obs in graph.frame.observations
    }))

    return graph.add_node(
        organ_id="research_governance_epoch",
        family="GOVERNANCE_EPOCH",
        created_at_ms=int(created_at_ms),
        evidence_roots=roots,
        lineage_id="hivenance.research_governance_epoch.v1",
        transformation_id="world_state_to_governance_epoch.v1",
        payload={
            "epoch": epoch.to_dict(),
            "validation": validation.to_dict(),
            "execution_eligible": False,
            "promotion_eligible": False,
        },
        freshness=1.0,
        uncertainty=0.0,
    )


def assemble_deep_channels(
    graph: WorldGraph,
    *,
    harmonic: Any | None = None,
    harmonic_sources: Sequence[WorldGraphNode] = (),
    resonance: Any | None = None,
    resonance_sources: Sequence[WorldGraphNode] = (),
    mystique: Any | None = None,
    mystique_sources: Sequence[WorldGraphNode] = (),
    metabolism: Any | None = None,
    metabolism_sources: Sequence[WorldGraphNode] = (),
    learned_receipts: Sequence[Any] | None = None,
    learned_sources: Sequence[WorldGraphNode] = (),
    epoch: Any | None = None,
    epoch_validation: Any | None = None,
    created_at_ms: int,
    disabled: frozenset[str] = frozenset(),
) -> tuple[
    dict[str, QueenInputChannel],
    tuple[WorldGraphNode, ...],
]:
    channels: dict[str, QueenInputChannel] = {}
    nodes: list[WorldGraphNode] = []

    names = {
        "POLYPHONIC_RESONANCE",
        "HARMONIC_CONTEXT",
        "MYSTIQUE_CHALLENGE",
        "COGNITIVE_METABOLISM",
        "LEARNED_CHALLENGER",
        "GOVERNANCE_EPOCH",
    }

    for name in names & set(disabled):
        channels[name] = channel(
            name=name,
            state="DISABLED_BY_MASK",
            reason="phase7_channel_mask",
        )

    if "HARMONIC_CONTEXT" not in disabled:
        if harmonic is None:
            channels["HARMONIC_CONTEXT"] = channel(
                name="HARMONIC_CONTEXT",
                state="ABSENT_DATA",
                reason="harmonic_receipt_unavailable",
            )
        elif not harmonic_sources:
            channels["HARMONIC_CONTEXT"] = channel(
                name="HARMONIC_CONTEXT",
                state="ERROR",
                reason="harmonic_source_nodes_missing",
            )
        else:
            node = add_harmonic_context_node(
                graph,
                harmonic=harmonic,
                source_nodes=harmonic_sources,
                created_at_ms=created_at_ms,
            )
            nodes.append(node)
            channels["HARMONIC_CONTEXT"] = channel(
                name="HARMONIC_CONTEXT",
                state="PRESENT",
                source_nodes=(node,),
                source_receipt_ids=(harmonic.receipt_id,),
                payload={
                    "receipt_id": harmonic.receipt_id,
                    "state": harmonic.state,
                    "resonance_score": harmonic.resonance_score,
                    "discord_score": harmonic.discord_score,
                },
            )

    if "POLYPHONIC_RESONANCE" not in disabled:
        if resonance is None:
            channels["POLYPHONIC_RESONANCE"] = channel(
                name="POLYPHONIC_RESONANCE",
                state="ABSENT_DATA",
                reason="polyphonic_resonance_unavailable",
            )
        elif not resonance_sources:
            channels["POLYPHONIC_RESONANCE"] = channel(
                name="POLYPHONIC_RESONANCE",
                state="ERROR",
                reason="resonance_source_nodes_missing",
            )
        else:
            node = add_polyphonic_resonance_node(
                graph,
                resonance=resonance,
                source_nodes=resonance_sources,
                created_at_ms=created_at_ms,
            )
            nodes.append(node)
            channels["POLYPHONIC_RESONANCE"] = channel(
                name="POLYPHONIC_RESONANCE",
                state="PRESENT",
                source_nodes=(node,),
                source_receipt_ids=(resonance.receipt_id,),
                payload={
                    "receipt_id": resonance.receipt_id,
                    "global_resonance":
                        resonance.global_resonance,
                    "cross_band_tension":
                        resonance.cross_band_tension,
                    "texture": resonance.texture,
                },
            )

    if "MYSTIQUE_CHALLENGE" not in disabled:
        if mystique is None:
            channels["MYSTIQUE_CHALLENGE"] = channel(
                name="MYSTIQUE_CHALLENGE",
                state="NOT_APPLICABLE",
                reason="counterfactual_challenge_not_requested",
            )
        elif not mystique_sources:
            channels["MYSTIQUE_CHALLENGE"] = channel(
                name="MYSTIQUE_CHALLENGE",
                state="ERROR",
                reason="mystique_source_nodes_missing",
            )
        else:
            node = add_mystique_node(
                graph,
                mystique=mystique,
                source_nodes=mystique_sources,
                created_at_ms=created_at_ms,
            )
            nodes.append(node)
            channels["MYSTIQUE_CHALLENGE"] = channel(
                name="MYSTIQUE_CHALLENGE",
                state="PRESENT",
                source_nodes=(node,),
                source_receipt_ids=(mystique.receipt_id,),
                payload={
                    "receipt_id": mystique.receipt_id,
                    "fragility_score":
                        mystique.fragility_score,
                    "survival_rate":
                        mystique.survival_rate,
                    "prospective_evidence_eligible": False,
                },
            )

    if "COGNITIVE_METABOLISM" not in disabled:
        if metabolism is None:
            channels["COGNITIVE_METABOLISM"] = channel(
                name="COGNITIVE_METABOLISM",
                state="ABSENT_DATA",
                reason="metabolic_receipt_unavailable",
            )
        elif not metabolism_sources:
            channels["COGNITIVE_METABOLISM"] = channel(
                name="COGNITIVE_METABOLISM",
                state="ERROR",
                reason="metabolism_source_nodes_missing",
            )
        else:
            node = add_metabolism_node(
                graph,
                metabolism=metabolism,
                source_nodes=metabolism_sources,
                created_at_ms=created_at_ms,
            )
            nodes.append(node)
            channels["COGNITIVE_METABOLISM"] = channel(
                name="COGNITIVE_METABOLISM",
                state="PRESENT",
                source_nodes=(node,),
                source_receipt_ids=(metabolism.receipt_id,),
                payload={
                    "receipt_id": metabolism.receipt_id,
                    "texture": metabolism.texture,
                    "metabolic_strain":
                        metabolism.metabolic_strain,
                    "breath": metabolism.breath,
                },
            )

    learned = tuple(learned_receipts or ())

    if "LEARNED_CHALLENGER" not in disabled:
        if not learned:
            channels["LEARNED_CHALLENGER"] = channel(
                name="LEARNED_CHALLENGER",
                state="ABSENT_DATA",
                reason="learned_challenger_receipts_unavailable",
            )
        elif not learned_sources:
            channels["LEARNED_CHALLENGER"] = channel(
                name="LEARNED_CHALLENGER",
                state="ERROR",
                reason="learned_source_nodes_missing",
            )
        else:
            node = add_learned_challenger_node(
                graph,
                receipts=learned,
                source_nodes=learned_sources,
                created_at_ms=created_at_ms,
            )
            nodes.append(node)
            channels["LEARNED_CHALLENGER"] = channel(
                name="LEARNED_CHALLENGER",
                state="PRESENT",
                source_nodes=(node,),
                source_receipt_ids=tuple(
                    receipt.receipt_id
                    for receipt in learned
                ),
                payload={
                    "receipt_count": len(learned),
                    "independent_vote_eligible_count": sum(
                        1
                        for receipt in learned
                        if receipt.independent_vote_eligible
                    ),
                },
            )

    if "GOVERNANCE_EPOCH" not in disabled:
        if epoch is None or epoch_validation is None:
            channels["GOVERNANCE_EPOCH"] = channel(
                name="GOVERNANCE_EPOCH",
                state="ABSENT_DATA",
                reason="governance_epoch_unavailable",
            )
        elif not epoch_validation.valid:
            channels["GOVERNANCE_EPOCH"] = channel(
                name="GOVERNANCE_EPOCH",
                state="ERROR",
                reason="governance_epoch_invalid",
            )
        else:
            node = add_governance_epoch_node(
                graph,
                epoch=epoch,
                validation=epoch_validation,
                created_at_ms=created_at_ms,
            )
            nodes.append(node)
            channels["GOVERNANCE_EPOCH"] = channel(
                name="GOVERNANCE_EPOCH",
                state="PRESENT",
                source_nodes=(node,),
                source_receipt_ids=(
                    epoch.epoch_id,
                    epoch_validation.validation_id,
                ),
                payload={
                    "epoch_id": epoch.epoch_id,
                    "score_id": epoch.score_id,
                    "genre_mode": epoch.genre_mode,
                    "strictness_level":
                        epoch.strictness_level,
                    "valid": True,
                },
            )

    return channels, tuple(nodes)
