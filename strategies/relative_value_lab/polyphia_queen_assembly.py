from __future__ import annotations

from typing import Any, Sequence

from .queen_input_assembly import QueenInputChannel, channel
from .world_graph import WorldGraph, WorldGraphNode


def _roots_from_notes(notes: Sequence[Any]) -> tuple[str, ...]:
    return tuple(sorted({
        str(note.evidence_root)
        for note in notes
        if str(getattr(note, "evidence_root", "")).startswith("sha256:")
    }))


def _assert_note_world(
    graph: WorldGraph,
    notes: Sequence[Any],
) -> None:
    for note in notes:
        if note.world_state_id != graph.frame.world_state_id:
            raise ValueError("motif_note_world_state_id_mismatch")
        if note.world_state_hash != graph.frame.world_state_hash:
            raise ValueError("motif_note_world_state_hash_mismatch")


def add_motif_notes_node(
    graph: WorldGraph,
    *,
    notes: Sequence[Any],
    created_at_ms: int,
) -> WorldGraphNode:
    _assert_note_world(graph, notes)

    return graph.add_node(
        organ_id="musical_motif_accumulator",
        family="MOTIF_NOTES",
        created_at_ms=int(created_at_ms),
        evidence_roots=_roots_from_notes(notes),
        lineage_id="hivenance.musical_motif_notes.v1",
        transformation_id="waggle_receipts_to_motif_notes.v1",
        payload={
            "schema": "hivenance_motif_notes_context_v1",
            "note_count": len(notes),
            "notes": tuple(note.to_dict() for note in notes),
            "receipt_ids": tuple(
                sorted({str(note.receipt_id) for note in notes})
            ),
            "execution_eligible": False,
            "promotion_eligible": False,
        },
    )


def add_motif_accumulator_node(
    graph: WorldGraph,
    *,
    notes: Sequence[Any],
    motif: Any,
    created_at_ms: int,
) -> WorldGraphNode:
    _assert_note_world(graph, notes)

    return graph.add_node(
        organ_id="musical_motif_accumulator",
        family="MOTIF_ACCUMULATOR",
        created_at_ms=int(created_at_ms),
        evidence_roots=_roots_from_notes(notes),
        lineage_id="hivenance.musical_motif_accumulator.v1",
        transformation_id="motif_notes_to_motif_score.v1",
        payload={
            **motif.to_dict(),
            "execution_eligible": False,
            "promotion_eligible": False,
        },
        freshness=1.0,
        uncertainty=max(
            0.0,
            min(1.0, float(motif.tension)),
        ),
    )


def add_entrainment_node(
    graph: WorldGraph,
    *,
    notes: Sequence[Any],
    entrainment: Any,
    created_at_ms: int,
) -> WorldGraphNode:
    _assert_note_world(graph, notes)

    return graph.add_node(
        organ_id="polyphonic_entrainment",
        family="POLYPHONIC_ENTRAINMENT",
        created_at_ms=int(created_at_ms),
        evidence_roots=_roots_from_notes(notes),
        lineage_id="hivenance.polyphonic_entrainment.v1",
        transformation_id="motif_notes_to_entrainment.v1",
        payload={
            **entrainment.to_dict(),
            "execution_eligible": False,
            "promotion_eligible": False,
        },
        freshness=1.0,
        uncertainty=max(
            0.0,
            min(1.0, float(entrainment.false_unison_risk)),
        ),
    )


def add_edge_chorus_node(
    graph: WorldGraph,
    *,
    edge_chorus: Any,
    source_nodes: Sequence[WorldGraphNode],
    created_at_ms: int,
) -> WorldGraphNode:
    if not source_nodes:
        raise ValueError("edge_chorus_source_nodes_required")

    roots = tuple(sorted({
        root
        for node in source_nodes
        for root in node.evidence_roots
    }))

    return graph.add_node(
        organ_id="edge_chorus",
        family="EDGE_CHORUS",
        created_at_ms=int(created_at_ms),
        evidence_roots=roots,
        lineage_id="hivenance.edge_chorus.v1",
        transformation_id="governed_edge_to_chorus_harmony.v1",
        payload={
            **edge_chorus.to_dict(),
            "source_node_ids": tuple(
                sorted(node.node_id for node in source_nodes)
            ),
            "execution_eligible": False,
            "promotion_eligible": False,
        },
        freshness=1.0,
        uncertainty=max(
            0.0,
            min(1.0, 1.0 - float(edge_chorus.chorus_quality)),
        ),
    )


def assemble_polyphia_channels(
    graph: WorldGraph,
    *,
    notes: Sequence[Any] | None,
    motif: Any | None,
    entrainment: Any | None,
    edge_chorus: Any | None,
    edge_source_nodes: Sequence[WorldGraphNode] = (),
    created_at_ms: int,
    disabled: frozenset[str] = frozenset(),
) -> tuple[dict[str, QueenInputChannel], tuple[WorldGraphNode, ...]]:
    channels: dict[str, QueenInputChannel] = {}
    nodes: list[WorldGraphNode] = []

    names = {
        "EDGE_CHORUS",
        "MOTIF_NOTES",
        "MOTIF_ACCUMULATOR",
        "POLYPHONIC_ENTRAINMENT",
    }

    for name in names & set(disabled):
        channels[name] = channel(
            name=name,
            state="DISABLED_BY_MASK",
            reason="phase7_channel_mask",
        )

    safe_notes = tuple(notes or ())

    if "MOTIF_NOTES" not in disabled:
        if not safe_notes:
            channels["MOTIF_NOTES"] = channel(
                name="MOTIF_NOTES",
                state="ABSENT_DATA",
                reason="no_lawful_motif_notes",
            )
        else:
            node = add_motif_notes_node(
                graph,
                notes=safe_notes,
                created_at_ms=created_at_ms,
            )
            nodes.append(node)
            channels["MOTIF_NOTES"] = channel(
                name="MOTIF_NOTES",
                state="PRESENT",
                source_nodes=(node,),
                source_receipt_ids=tuple(
                    note.receipt_id for note in safe_notes
                ),
                payload={"note_count": len(safe_notes)},
            )

    if "MOTIF_ACCUMULATOR" not in disabled:
        if motif is None or not safe_notes:
            channels["MOTIF_ACCUMULATOR"] = channel(
                name="MOTIF_ACCUMULATOR",
                state="ABSENT_DATA",
                reason="motif_score_unavailable",
            )
        else:
            node = add_motif_accumulator_node(
                graph,
                notes=safe_notes,
                motif=motif,
                created_at_ms=created_at_ms,
            )
            nodes.append(node)
            channels["MOTIF_ACCUMULATOR"] = channel(
                name="MOTIF_ACCUMULATOR",
                state="PRESENT",
                source_nodes=(node,),
                source_receipt_ids=(motif.score_id,),
                payload={
                    "score_id": motif.score_id,
                    "note_count": motif.note_count,
                    "independent_voice_count":
                        motif.independent_voice_count,
                    "cadence_strength": motif.cadence_strength,
                    "tension": motif.tension,
                },
            )

    if "POLYPHONIC_ENTRAINMENT" not in disabled:
        if entrainment is None or not safe_notes:
            channels["POLYPHONIC_ENTRAINMENT"] = channel(
                name="POLYPHONIC_ENTRAINMENT",
                state="ABSENT_DATA",
                reason="entrainment_unavailable",
            )
        else:
            node = add_entrainment_node(
                graph,
                notes=safe_notes,
                entrainment=entrainment,
                created_at_ms=created_at_ms,
            )
            nodes.append(node)
            channels["POLYPHONIC_ENTRAINMENT"] = channel(
                name="POLYPHONIC_ENTRAINMENT",
                state="PRESENT",
                source_nodes=(node,),
                source_receipt_ids=(entrainment.receipt_id,),
                payload={
                    "receipt_id": entrainment.receipt_id,
                    "independent_voice_count":
                        entrainment.independent_voice_count,
                    "source_diversity":
                        entrainment.source_diversity,
                    "false_unison_risk":
                        entrainment.false_unison_risk,
                    "entrainment_strength":
                        entrainment.entrainment_strength,
                },
            )

    if "EDGE_CHORUS" not in disabled:
        if edge_chorus is None:
            channels["EDGE_CHORUS"] = channel(
                name="EDGE_CHORUS",
                state="NOT_APPLICABLE",
                reason="no_governed_edge_open",
            )
        elif not edge_source_nodes:
            channels["EDGE_CHORUS"] = channel(
                name="EDGE_CHORUS",
                state="ERROR",
                reason="edge_chorus_source_nodes_missing",
            )
        else:
            node = add_edge_chorus_node(
                graph,
                edge_chorus=edge_chorus,
                source_nodes=edge_source_nodes,
                created_at_ms=created_at_ms,
            )
            nodes.append(node)
            channels["EDGE_CHORUS"] = channel(
                name="EDGE_CHORUS",
                state="PRESENT",
                source_nodes=(node,),
                source_receipt_ids=(edge_chorus.action_id,),
                payload={
                    "action_id": edge_chorus.action_id,
                    "chorus_quality": edge_chorus.chorus_quality,
                    "resolution_class":
                        edge_chorus.resolution_class,
                },
            )

    return channels, tuple(nodes)
