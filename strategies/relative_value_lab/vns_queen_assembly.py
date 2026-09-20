from __future__ import annotations

from typing import Any

from .queen_input_assembly import QueenInputChannel, channel
from .world_graph import WorldGraph, WorldGraphNode


def _frame_roots(graph: WorldGraph) -> tuple[str, ...]:
    return tuple(
        sorted({
            str(obs.evidence_root)
            for obs in graph.frame.observations
            if str(obs.evidence_root).startswith("sha256:")
        })
    )


def _assert_measure_world(graph: WorldGraph, measure: Any) -> None:
    frame = measure.frame

    if frame.world_state_id != graph.frame.world_state_id:
        raise ValueError("vns_measure_world_state_id_mismatch")

    if frame.world_state_hash != graph.frame.world_state_hash:
        raise ValueError("vns_measure_world_state_hash_mismatch")


def add_vns_sensory_node(
    graph: WorldGraph,
    *,
    measure: Any,
    created_at_ms: int | None = None,
) -> WorldGraphNode:
    """Expose canonical VNS pulses without minting new evidence diversity."""

    _assert_measure_world(graph, measure)

    at = int(
        measure.observed_at_ms
        if created_at_ms is None
        else created_at_ms
    )

    return graph.add_node(
        organ_id="vns_score_conductor",
        family="VNS_SENSORY_PULSES",
        created_at_ms=at,
        evidence_roots=_frame_roots(graph),
        lineage_id="hivenance.vns_score_conductor.v1",
        transformation_id="vns_measure_to_sensory_pulses.v1",
        payload={
            "schema": "hivenance_vns_sensory_context_v1",
            "measure_id": measure.measure_id,
            "run_id": measure.run_id,
            "observed_at_ms": measure.observed_at_ms,
            "candidate_count": measure.candidate_count,
            "fresh_candidate_count": measure.fresh_candidate_count,
            "mean_data_quality": measure.mean_data_quality,
            "dataset_hash": measure.dataset_hash,
            "pulse_count": len(measure.pulses),
            "pulses": tuple(
                {
                    "pulse_id": pulse.pulse_id,
                    "observed_at_ms": pulse.observed_at_ms,
                    "scope": pulse.scope,
                    "pulse_class": pulse.pulse_class,
                    "amplitude": pulse.amplitude,
                    "confidence": pulse.confidence,
                    "freshness": pulse.freshness,
                    "derived_evidence_root": pulse.evidence_root,
                    "world_state_id": pulse.world_state_id,
                    "world_state_hash": pulse.world_state_hash,
                }
                for pulse in measure.pulses
            ),
            "authority": measure.authority,
            "execution_eligible": False,
            "promotion_eligible": False,
        },
        freshness=1.0,
        uncertainty=max(
            0.0,
            min(1.0, 1.0 - float(measure.mean_data_quality)),
        ),
    )


def add_vns_phrase_node(
    graph: WorldGraph,
    *,
    measure: Any,
    phrase: Any,
    created_at_ms: int | None = None,
) -> WorldGraphNode:
    """Expose the VNS phrase as derived sensory memory."""

    _assert_measure_world(graph, measure)

    if int(phrase.last_measure_ms or 0) > int(measure.observed_at_ms):
        raise ValueError("vns_phrase_future_of_bound_measure")

    at = int(
        measure.observed_at_ms
        if created_at_ms is None
        else created_at_ms
    )

    return graph.add_node(
        organ_id="vns_score_stream",
        family="VNS_SCORE_STREAM",
        created_at_ms=at,
        evidence_roots=_frame_roots(graph),
        lineage_id="hivenance.vns_score_stream.v1",
        transformation_id="vns_measures_to_phrase.v1",
        payload={
            "schema": phrase.schema,
            "phrase_id": phrase.phrase_id,
            "measure_count": phrase.measure_count,
            "first_measure_ms": phrase.first_measure_ms,
            "last_measure_ms": phrase.last_measure_ms,
            "duration_ms": phrase.duration_ms,
            "mean_pulse_energy": phrase.mean_pulse_energy,
            "pulse_density": phrase.pulse_density,
            "pulse_recurrence": phrase.pulse_recurrence,
            "rest_density": phrase.rest_density,
            "measure_novelty": phrase.measure_novelty,
            "echo_pressure": phrase.echo_pressure,
            "source_churn": phrase.source_churn,
            "attention_churn": phrase.attention_churn,
            "freshness_decay": phrase.freshness_decay,
            "crescendo": phrase.crescendo,
            "decrescendo": phrase.decrescendo,
            "modulation": phrase.modulation,
            "phrase_energy": phrase.phrase_energy,
            "recent_measure_ids": tuple(phrase.recent_measure_ids),
            "authority": phrase.authority,
            "execution_eligible": False,
            "promotion_eligible": False,
        },
        freshness=max(
            0.0,
            min(1.0, 1.0 - float(phrase.freshness_decay)),
        ),
        uncertainty=max(
            0.0,
            min(1.0, float(phrase.echo_pressure)),
        ),
    )


def add_temporal_texture_node(
    graph: WorldGraph,
    *,
    measure: Any,
    phrase: Any,
    created_at_ms: int | None = None,
) -> WorldGraphNode:
    _assert_measure_world(graph, measure)

    texture = phrase.temporal_texture

    at = int(
        measure.observed_at_ms
        if created_at_ms is None
        else created_at_ms
    )

    return graph.add_node(
        organ_id="temporal_texture",
        family="TEMPORAL_TEXTURE",
        created_at_ms=at,
        evidence_roots=_frame_roots(graph),
        lineage_id="hivenance.temporal_texture.v1",
        transformation_id="vns_phrase_to_temporal_texture.v1",
        payload={
            **texture.to_dict(),
            "source_phrase_id": phrase.phrase_id,
            "authority": texture.authority,
            "execution_eligible": False,
            "promotion_eligible": False,
        },
        freshness=max(
            0.0,
            min(1.0, float(texture.persistence)),
        ),
        uncertainty=max(
            0.0,
            min(1.0, 1.0 - float(texture.cadence_coherence)),
        ),
    )


def assemble_vns_channels(
    graph: WorldGraph,
    *,
    measure: Any | None,
    phrase: Any | None,
    created_at_ms: int,
    disabled: frozenset[str] = frozenset(),
) -> tuple[dict[str, QueenInputChannel], tuple[WorldGraphNode, ...]]:
    """Build the first three Phase-7 Queen channels."""

    channels: dict[str, QueenInputChannel] = {}
    nodes: list[WorldGraphNode] = []

    names = {
        "VNS_SENSORY_PULSES",
        "VNS_SCORE_STREAM",
        "TEMPORAL_TEXTURE",
    }

    for name in names & set(disabled):
        channels[name] = channel(
            name=name,
            state="DISABLED_BY_MASK",
            reason="phase7_channel_mask",
        )

    if "VNS_SENSORY_PULSES" not in disabled:
        if measure is None:
            channels["VNS_SENSORY_PULSES"] = channel(
                name="VNS_SENSORY_PULSES",
                state="ABSENT_DATA",
                reason="vns_measure_unavailable",
            )
        else:
            node = add_vns_sensory_node(
                graph,
                measure=measure,
                created_at_ms=created_at_ms,
            )
            nodes.append(node)
            channels["VNS_SENSORY_PULSES"] = channel(
                name="VNS_SENSORY_PULSES",
                state="PRESENT",
                source_nodes=(node,),
                source_receipt_ids=(measure.measure_id,),
                payload={
                    "measure_id": measure.measure_id,
                    "pulse_count": len(measure.pulses),
                },
            )

    if "VNS_SCORE_STREAM" not in disabled:
        if measure is None or phrase is None:
            channels["VNS_SCORE_STREAM"] = channel(
                name="VNS_SCORE_STREAM",
                state="ABSENT_DATA",
                reason="vns_phrase_unavailable",
            )
        else:
            node = add_vns_phrase_node(
                graph,
                measure=measure,
                phrase=phrase,
                created_at_ms=created_at_ms,
            )
            nodes.append(node)
            channels["VNS_SCORE_STREAM"] = channel(
                name="VNS_SCORE_STREAM",
                state="PRESENT",
                source_nodes=(node,),
                source_receipt_ids=(phrase.phrase_id,),
                payload={
                    "phrase_id": phrase.phrase_id,
                    "measure_count": phrase.measure_count,
                    "phrase_energy": phrase.phrase_energy,
                },
            )

    if "TEMPORAL_TEXTURE" not in disabled:
        if measure is None or phrase is None:
            channels["TEMPORAL_TEXTURE"] = channel(
                name="TEMPORAL_TEXTURE",
                state="ABSENT_DATA",
                reason="temporal_texture_unavailable",
            )
        else:
            node = add_temporal_texture_node(
                graph,
                measure=measure,
                phrase=phrase,
                created_at_ms=created_at_ms,
            )
            nodes.append(node)
            channels["TEMPORAL_TEXTURE"] = channel(
                name="TEMPORAL_TEXTURE",
                state="PRESENT",
                source_nodes=(node,),
                source_receipt_ids=(phrase.phrase_id,),
                payload={
                    "sequence_class":
                        phrase.temporal_texture.sequence_class,
                    "cadence_coherence":
                        phrase.temporal_texture.cadence_coherence,
                },
            )

    return channels, tuple(nodes)
