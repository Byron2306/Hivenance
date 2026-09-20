from __future__ import annotations

from typing import Any, Sequence

from .queen_input_assembly import QueenInputChannel, channel
from .world_graph import WorldGraph, WorldGraphNode


def _valid_roots(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted({
        str(value)
        for value in values
        if str(value).startswith("sha256:")
    }))


def _assert_world(
    graph: WorldGraph,
    *,
    world_state_id: str,
    label: str,
) -> None:
    if str(world_state_id) != str(graph.frame.world_state_id):
        raise ValueError(f"{label}_world_state_mismatch")


def add_market_hunting_node(
    graph: WorldGraph,
    *,
    matches: Sequence[Any],
    created_at_ms: int,
) -> WorldGraphNode:
    if not matches:
        raise ValueError("market_hunting_matches_required")

    for match in matches:
        _assert_world(
            graph,
            world_state_id=match.world_state_id,
            label="market_hunting",
        )

    roots = _valid_roots([
        root
        for match in matches
        for root in match.evidence_roots
    ])

    return graph.add_node(
        organ_id="motif_hunter",
        family="MARKET_HUNTING",
        created_at_ms=int(created_at_ms),
        evidence_roots=roots,
        lineage_id="hivenance.motif_hunter.v1",
        transformation_id="hunt_observations_to_matches.v1",
        payload={
            "schema": "hivenance_market_hunting_context_v1",
            "match_count": len(matches),
            "matches": tuple(match.to_dict() for match in matches),
            "execution_eligible": False,
            "promotion_eligible": False,
        },
        freshness=1.0,
        uncertainty=0.0,
    )


def add_colony_correlation_node(
    graph: WorldGraph,
    *,
    correlations: Sequence[Any],
    source_events: Sequence[Any],
    created_at_ms: int,
) -> WorldGraphNode:
    if not correlations:
        raise ValueError("colony_correlation_receipts_required")
    if not source_events:
        raise ValueError("colony_correlation_source_events_required")

    event_ids = {
        str(event.event_id)
        for event in source_events
    }

    referenced = {
        str(event_id)
        for receipt in correlations
        for event_id in (
            receipt.left_event_id,
            receipt.right_event_id,
        )
    }

    if not referenced.issubset(event_ids):
        raise ValueError("colony_correlation_source_event_missing")

    roots = _valid_roots([
        event.evidence_root
        for event in source_events
        if getattr(event, "evidence_root", None)
    ])

    # Correlation remains descriptive only. causal_claim must stay false.
    if any(bool(receipt.causal_claim) for receipt in correlations):
        raise ValueError("colony_correlation_causal_claim_forbidden")

    return graph.add_node(
        organ_id="colony_correlator",
        family="COLONY_CORRELATION",
        created_at_ms=int(created_at_ms),
        evidence_roots=roots,
        lineage_id="hivenance.colony_correlation.v1",
        transformation_id="correlation_events_to_receipts.v1",
        payload={
            "schema": "hivenance_colony_correlation_context_v1",
            "correlation_count": len(correlations),
            "source_event_ids": tuple(sorted(event_ids)),
            "correlations": tuple(
                receipt.to_dict()
                for receipt in correlations
            ),
            "causal_claim": False,
            "execution_eligible": False,
            "promotion_eligible": False,
        },
        freshness=1.0,
        uncertainty=max(
            0.0,
            min(
                1.0,
                1.0 - max(
                    float(receipt.confidence)
                    for receipt in correlations
                ),
            ),
        ),
    )


def add_causal_cascade_node(
    graph: WorldGraph,
    *,
    cascade: Any,
    events: Sequence[Any],
    links: Sequence[Any],
    created_at_ms: int,
) -> WorldGraphNode:
    if not events:
        raise ValueError("causal_cascade_events_required")

    _assert_world(
        graph,
        world_state_id=cascade.world_state_id,
        label="causal_cascade",
    )

    for event in events:
        _assert_world(
            graph,
            world_state_id=event.world_state_id,
            label="causal_cascade_event",
        )
        if event.world_state_hash != graph.frame.world_state_hash:
            raise ValueError(
                "causal_cascade_event_world_state_hash_mismatch"
            )

    roots = _valid_roots(
        [
            event.evidence_root
            for event in events
        ]
        + [
            link.mechanism_evidence_root
            for link in links
        ]
    )

    if bool(cascade.causal_proof):
        raise ValueError("causal_cascade_proof_claim_forbidden")

    return graph.add_node(
        organ_id="causal_cascade",
        family="CAUSAL_CASCADE",
        created_at_ms=int(created_at_ms),
        evidence_roots=roots,
        lineage_id="hivenance.causal_cascade.v1",
        transformation_id="cascade_events_and_links_to_receipt.v1",
        payload={
            **cascade.to_dict(),
            "source_event_ids": tuple(
                sorted(event.event_id for event in events)
            ),
            "mechanism_evidence_roots": tuple(
                sorted({
                    link.mechanism_evidence_root
                    for link in links
                    if str(
                        link.mechanism_evidence_root
                    ).startswith("sha256:")
                })
            ),
            "causal_proof": False,
            "execution_eligible": False,
            "promotion_eligible": False,
        },
        freshness=1.0,
        uncertainty=max(
            0.0,
            min(
                1.0,
                1.0 - float(cascade.propagation_strength),
            ),
        ),
    )


def add_hive_pulse_node(
    graph: WorldGraph,
    *,
    pulses: Sequence[Any],
    created_at_ms: int,
) -> WorldGraphNode:
    if not pulses:
        raise ValueError("hive_pulses_required")

    for pulse in pulses:
        _assert_world(
            graph,
            world_state_id=pulse.world_state_id,
            label="hive_pulse",
        )

        if pulse.execution_eligible or pulse.promotion_eligible:
            raise ValueError("hive_pulse_authority_escalation")

        if pulse.authority_effect not in {
            "ATTENTION_ONLY",
            "REDUCE_OR_FREEZE_ONLY",
        }:
            raise ValueError("hive_pulse_authority_effect_invalid")

    roots = _valid_roots([
        pulse.evidence_root
        for pulse in pulses
    ])

    return graph.add_node(
        organ_id="hive_pulse",
        family="HIVE_PULSE",
        created_at_ms=int(created_at_ms),
        evidence_roots=roots,
        lineage_id="hivenance.hive_pulse.v1",
        transformation_id="attention_state_to_hive_pulses.v1",
        payload={
            "schema": "hivenance_hive_pulse_context_v1",
            "pulse_count": len(pulses),
            "pulses": tuple(
                pulse.to_dict()
                for pulse in pulses
            ),
            "execution_eligible": False,
            "promotion_eligible": False,
        },
        freshness=1.0,
        uncertainty=max(
            0.0,
            min(
                1.0,
                1.0 - max(float(pulse.confidence) for pulse in pulses),
            ),
        ),
    )


def assemble_attention_channels(
    graph: WorldGraph,
    *,
    hunt_matches: Sequence[Any] | None = None,
    correlations: Sequence[Any] | None = None,
    correlation_events: Sequence[Any] | None = None,
    cascade: Any | None = None,
    cascade_events: Sequence[Any] | None = None,
    cascade_links: Sequence[Any] | None = None,
    hive_pulses: Sequence[Any] | None = None,
    created_at_ms: int,
    disabled: frozenset[str] = frozenset(),
) -> tuple[
    dict[str, QueenInputChannel],
    tuple[WorldGraphNode, ...],
]:
    channels: dict[str, QueenInputChannel] = {}
    nodes: list[WorldGraphNode] = []

    names = {
        "MARKET_HUNTING",
        "COLONY_CORRELATION",
        "CAUSAL_CASCADE",
        "HIVE_PULSE",
    }

    for name in names & set(disabled):
        channels[name] = channel(
            name=name,
            state="DISABLED_BY_MASK",
            reason="phase7_channel_mask",
        )

    hunts = tuple(hunt_matches or ())
    corrs = tuple(correlations or ())
    corr_events = tuple(correlation_events or ())
    c_events = tuple(cascade_events or ())
    c_links = tuple(cascade_links or ())
    pulses = tuple(hive_pulses or ())

    if "MARKET_HUNTING" not in disabled:
        if not hunts:
            channels["MARKET_HUNTING"] = channel(
                name="MARKET_HUNTING",
                state="ABSENT_DATA",
                reason="no_hunt_matches",
            )
        else:
            node = add_market_hunting_node(
                graph,
                matches=hunts,
                created_at_ms=created_at_ms,
            )
            nodes.append(node)
            channels["MARKET_HUNTING"] = channel(
                name="MARKET_HUNTING",
                state="PRESENT",
                source_nodes=(node,),
                source_receipt_ids=tuple(
                    match.match_id for match in hunts
                ),
                payload={
                    "match_count": len(hunts),
                    "max_research_priority": max(
                        float(match.research_priority)
                        for match in hunts
                    ),
                },
            )

    if "COLONY_CORRELATION" not in disabled:
        if not corrs:
            channels["COLONY_CORRELATION"] = channel(
                name="COLONY_CORRELATION",
                state="ABSENT_DATA",
                reason="no_correlation_receipts",
            )
        elif not corr_events:
            channels["COLONY_CORRELATION"] = channel(
                name="COLONY_CORRELATION",
                state="ERROR",
                reason="correlation_source_events_missing",
            )
        else:
            node = add_colony_correlation_node(
                graph,
                correlations=corrs,
                source_events=corr_events,
                created_at_ms=created_at_ms,
            )
            nodes.append(node)
            channels["COLONY_CORRELATION"] = channel(
                name="COLONY_CORRELATION",
                state="PRESENT",
                source_nodes=(node,),
                source_receipt_ids=tuple(
                    receipt.correlation_id
                    for receipt in corrs
                ),
                payload={
                    "correlation_count": len(corrs),
                    "causal_claim": False,
                },
            )

    if "CAUSAL_CASCADE" not in disabled:
        if cascade is None:
            channels["CAUSAL_CASCADE"] = channel(
                name="CAUSAL_CASCADE",
                state="NOT_APPLICABLE",
                reason="no_supported_propagation_path",
            )
        elif not c_events:
            channels["CAUSAL_CASCADE"] = channel(
                name="CAUSAL_CASCADE",
                state="ERROR",
                reason="cascade_source_events_missing",
            )
        else:
            node = add_causal_cascade_node(
                graph,
                cascade=cascade,
                events=c_events,
                links=c_links,
                created_at_ms=created_at_ms,
            )
            nodes.append(node)
            channels["CAUSAL_CASCADE"] = channel(
                name="CAUSAL_CASCADE",
                state="PRESENT",
                source_nodes=(node,),
                source_receipt_ids=(cascade.cascade_id,),
                payload={
                    "cascade_id": cascade.cascade_id,
                    "depth": cascade.depth,
                    "breadth": cascade.breadth,
                    "propagation_strength":
                        cascade.propagation_strength,
                    "causal_proof": False,
                },
            )

    if "HIVE_PULSE" not in disabled:
        if not pulses:
            channels["HIVE_PULSE"] = channel(
                name="HIVE_PULSE",
                state="ABSENT_DATA",
                reason="no_active_hive_pulses",
            )
        else:
            node = add_hive_pulse_node(
                graph,
                pulses=pulses,
                created_at_ms=created_at_ms,
            )
            nodes.append(node)
            channels["HIVE_PULSE"] = channel(
                name="HIVE_PULSE",
                state="PRESENT",
                source_nodes=(node,),
                source_receipt_ids=tuple(
                    pulse.pulse_id
                    for pulse in pulses
                ),
                payload={
                    "pulse_count": len(pulses),
                    "authority_effects": tuple(sorted({
                        pulse.authority_effect
                        for pulse in pulses
                    })),
                },
            )

    return channels, tuple(nodes)
