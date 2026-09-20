from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .world_graph import WorldGraph, WorldGraphNode
from .cognitive_metabolism import CognitiveMetabolismReceipt, recurrence_budget


REQUEST_KINDS = {
    "REFRESH",
    "CHALLENGE",
    "COMPARE",
    "INVITE_INDEPENDENT_CORROBORATION",
    "PRESERVE_COUNTERPOINT",
    "THIN",
    "AMPLIFY",
    "RETIRE_FROM_ACTIVE_SCORE",
    "REHEARSE_EDGE_RESOLUTION",
    "CHANGE_EPOCH",
    "WAIT_REST",
}

RESPONSE_STATES = {
    "ANSWERED",
    "ABSTAINED",
    "REFUSED",
    "NO_CHANGE",
}


def _digest(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class QueenResearchRequest:
    schema: str
    request_id: str
    recurrence_index: int
    request_kind: str
    target: str
    reason: str
    notation_token_id: str | None
    source_receipt_id: str
    world_state_id: str
    world_state_hash: str
    observed_root_digest: str
    required_inputs: tuple[str, ...]
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if self.request_kind not in REQUEST_KINDS:
            raise ValueError("unknown_recursive_queen_request_kind")
        if self.recurrence_index < 0:
            raise ValueError("negative_recurrence_index")
        if not self.world_state_hash.startswith("sha256:"):
            raise ValueError("request_world_state_unbound")
        if not self.observed_root_digest.startswith("sha256:"):
            raise ValueError("request_observed_root_unbound")
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("recursive_request_authority_escalation")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QueenResearchResponse:
    schema: str
    response_id: str
    request_id: str
    recurrence_index: int
    state: str
    organ_id: str
    answer: str
    source_node_ids: tuple[str, ...]
    added_node_ids: tuple[str, ...]
    evidence_roots: tuple[str, ...]
    world_state_id: str
    world_state_hash: str
    observed_root_digest: str
    graph_changed: bool
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if self.state not in RESPONSE_STATES:
            raise ValueError("unknown_recursive_queen_response_state")
        if self.recurrence_index < 0:
            raise ValueError("negative_recurrence_index")
        if any(
            not str(root).startswith("sha256:")
            for root in self.evidence_roots
        ):
            raise ValueError("recursive_response_evidence_unbound")
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("recursive_response_authority_escalation")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QueenRecurrenceStep:
    schema: str
    step_id: str
    recurrence_index: int
    queen_receipt_id_before: str
    queen_receipt_id_after: str
    request: QueenResearchRequest
    response: QueenResearchResponse
    graph_node_count_before: int
    graph_node_count_after: int
    interpretation_changed: bool
    world_state_id: str
    world_state_hash: str
    observed_root_digest: str
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["request"] = self.request.to_dict()
        payload["response"] = self.response.to_dict()
        return payload


@dataclass(frozen=True)
class RecursiveQueenRun:
    schema: str
    run_id: str
    world_state_id: str
    world_state_hash: str
    observed_root_digest: str
    max_recurrences: int
    recurrence_count: int
    stop_reason: str
    steps: tuple[QueenRecurrenceStep, ...]
    initial_queen_receipt_id: str
    final_queen_receipt_id: str
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["steps"] = tuple(step.to_dict() for step in self.steps)
        return payload


def observed_root_digest(graph: WorldGraph) -> str:
    roots = tuple(sorted({
        obs.evidence_root
        for obs in graph.frame.observations
    }))

    return _digest({
        "world_state_id": graph.frame.world_state_id,
        "world_state_hash": graph.frame.world_state_hash,
        "observed_roots": roots,
    })


def build_request(
    *,
    graph: WorldGraph,
    recurrence_index: int,
    request_kind: str,
    target: str,
    reason: str,
    source_receipt_id: str,
    notation_token_id: str | None = None,
    required_inputs: Sequence[str] = (),
) -> QueenResearchRequest:
    root_digest = observed_root_digest(graph)

    body = {
        "recurrence_index": int(recurrence_index),
        "request_kind": request_kind,
        "target": target,
        "reason": reason,
        "source_receipt_id": source_receipt_id,
        "notation_token_id": notation_token_id,
        "world_state_id": graph.frame.world_state_id,
        "world_state_hash": graph.frame.world_state_hash,
        "observed_root_digest": root_digest,
        "required_inputs": tuple(required_inputs),
    }

    return QueenResearchRequest(
        schema="hivenance_queen_research_request_v1",
        request_id="qrr_" + _digest(body).split(":", 1)[1][:24],
        recurrence_index=int(recurrence_index),
        request_kind=str(request_kind),
        target=str(target),
        reason=str(reason),
        notation_token_id=notation_token_id,
        source_receipt_id=str(source_receipt_id),
        world_state_id=graph.frame.world_state_id,
        world_state_hash=graph.frame.world_state_hash,
        observed_root_digest=root_digest,
        required_inputs=tuple(str(x) for x in required_inputs),
    )


def build_response(
    *,
    graph: WorldGraph,
    request: QueenResearchRequest,
    state: str,
    organ_id: str,
    answer: str,
    source_nodes: Sequence[WorldGraphNode] = (),
    added_nodes: Sequence[WorldGraphNode] = (),
) -> QueenResearchResponse:
    root_digest = observed_root_digest(graph)

    if request.world_state_id != graph.frame.world_state_id:
        raise ValueError("recursive_request_world_state_drift")
    if request.world_state_hash != graph.frame.world_state_hash:
        raise ValueError("recursive_request_world_hash_drift")
    if request.observed_root_digest != root_digest:
        raise ValueError("recursive_observed_root_drift")

    roots = tuple(sorted({
        root
        for node in (*source_nodes, *added_nodes)
        for root in node.evidence_roots
    }))

    body = {
        "request_id": request.request_id,
        "state": state,
        "organ_id": organ_id,
        "answer": answer,
        "source_node_ids": sorted(
            node.node_id for node in source_nodes
        ),
        "added_node_ids": sorted(
            node.node_id for node in added_nodes
        ),
        "evidence_roots": roots,
        "world_state_id": graph.frame.world_state_id,
        "world_state_hash": graph.frame.world_state_hash,
        "observed_root_digest": root_digest,
    }

    return QueenResearchResponse(
        schema="hivenance_queen_research_response_v1",
        response_id="qrs_" + _digest(body).split(":", 1)[1][:24],
        request_id=request.request_id,
        recurrence_index=request.recurrence_index,
        state=str(state),
        organ_id=str(organ_id),
        answer=str(answer),
        source_node_ids=tuple(
            sorted(node.node_id for node in source_nodes)
        ),
        added_node_ids=tuple(
            sorted(node.node_id for node in added_nodes)
        ),
        evidence_roots=roots,
        world_state_id=graph.frame.world_state_id,
        world_state_hash=graph.frame.world_state_hash,
        observed_root_digest=root_digest,
        graph_changed=bool(added_nodes),
    )


class RecursiveQueenLoop:
    """Deterministic research recurrence over one immutable observed frame."""

    version = "hivenance.recursive_queen_loop.v1"

    def __init__(self, *, max_recurrences: int = 3) -> None:
        if max_recurrences < 1:
            raise ValueError("max_recurrences_must_be_positive")
        self.max_recurrences = int(max_recurrences)

    @staticmethod
    def assert_same_world(
        graph: WorldGraph,
        *,
        world_state_id: str,
        world_state_hash: str,
        root_digest: str,
    ) -> None:
        if graph.frame.world_state_id != world_state_id:
            raise ValueError("recursive_world_state_id_changed")
        if graph.frame.world_state_hash != world_state_hash:
            raise ValueError("recursive_world_state_hash_changed")
        if observed_root_digest(graph) != root_digest:
            raise ValueError("recursive_observed_root_changed")


# Queen's musical notation is richer than the recursive research protocol.
# Recurrence collapses notation onto a deliberately small bounded verb set.
NOTATION_TO_REQUEST_KIND = {
    # Passive listening / waiting
    "LISTEN": "WAIT_REST",
    "LET_MOTIF_REST": "WAIT_REST",

    # Refresh / revisit existing frozen observations only.
    # This NEVER means fetch later market data inside the recurrence.
    "TRACE_MODULATION": "REFRESH",
    "TRACE_TEMPORAL_TEXTURE": "REFRESH",
    "CHALLENGE_VNS_ECHO": "REFRESH",

    # Adversarial challenge
    "CHALLENGE_CADENCE": "CHALLENGE",
    "RUN_MYSTIQUE_VARIATIONS": "CHALLENGE",
    "CHALLENGE_FRAGILE_CADENCE": "CHALLENGE",
    "CHALLENGE_LEARNED_VOICE": "CHALLENGE",

    # Comparison / relationship analysis
    "TRACE_SHARED_ASSET": "COMPARE",
    "TRACE_PROPAGATION": "COMPARE",
    "TRACE_REGISTER_MODULATION": "COMPARE",

    # Explicit independent corroboration
    "ENTER_WITH_NEW_TIMBRE": "INVITE_INDEPENDENT_CORROBORATION",
    "SEEK_FRESH_EVIDENCE": "INVITE_INDEPENDENT_CORROBORATION",
    "INVITE_INDEPENDENT_CORROBORATION": "INVITE_INDEPENDENT_CORROBORATION",

    # Preserve productive disagreement
    "ANSWER_MOTIF": "PRESERVE_COUNTERPOINT",
    "PRESERVE_COUNTERPOINT": "PRESERVE_COUNTERPOINT",

    # Research density
    "THIN_ORCHESTRATION": "THIN",

    # Research attention amplification
    "AMPLIFY_SEARCH": "AMPLIFY",
    "ACCENT_CRESCENDO": "AMPLIFY",

    # Remove from active research score / isolate
    "HOLD_FREEZE_ACCENT": "RETIRE_FROM_ACTIVE_SCORE",
    "SEAL_SYNTHETIC_CHAMBER": "RETIRE_FROM_ACTIVE_SCORE",

    # Repair/rehearse bounded research structure
    "REHEARSE_EDGE_RESOLUTION": "REHEARSE_EDGE_RESOLUTION",

    # Governance / score rotation
    "REKEY_SCORE": "CHANGE_EPOCH",
    "RETUNE_LEARNED_VOICE": "CHANGE_EPOCH",
}


REQUEST_REQUIRED_INPUTS = {
    "REFRESH": (
        "world_graph",
        "frozen_observations",
    ),
    "CHALLENGE": (
        "world_graph",
        "current_interpretation",
    ),
    "COMPARE": (
        "world_graph",
        "comparison_context",
    ),
    "INVITE_INDEPENDENT_CORROBORATION": (
        "world_graph",
        "lineage_registry",
    ),
    "PRESERVE_COUNTERPOINT": (
        "world_graph",
        "existing_counterpoint",
    ),
    "THIN": (
        "world_graph",
        "cognitive_metabolism",
    ),
    "AMPLIFY": (
        "world_graph",
        "existing_attention_context",
    ),
    "RETIRE_FROM_ACTIVE_SCORE": (
        "world_graph",
        "active_score",
    ),
    "REHEARSE_EDGE_RESOLUTION": (
        "world_graph",
        "edge_chorus",
        "audit_context",
    ),
    "CHANGE_EPOCH": (
        "world_graph",
        "governance_epoch",
    ),
    "WAIT_REST": (
        "world_graph",
    ),
}


def request_kind_for_notation(notation: str) -> str:
    value = str(notation or "").strip().upper()

    try:
        return NOTATION_TO_REQUEST_KIND[value]
    except KeyError as exc:
        raise ValueError(
            f"queen_notation_unmapped:{value}"
        ) from exc


def request_from_notation(
    *,
    graph: WorldGraph,
    recurrence_index: int,
    queen_receipt: Any,
    notation_token: Any,
) -> QueenResearchRequest:
    if str(notation_token.epoch_id) != str(
        getattr(queen_receipt, "epoch_id", "")
    ):
        raise ValueError("notation_epoch_receipt_mismatch")

    if str(notation_token.world_state_id) != str(
        graph.frame.world_state_id
    ):
        raise ValueError("notation_world_state_id_mismatch")

    if str(notation_token.world_state_hash) != str(
        graph.frame.world_state_hash
    ):
        raise ValueError("notation_world_state_hash_mismatch")

    kind = request_kind_for_notation(
        notation_token.notation
    )

    return build_request(
        graph=graph,
        recurrence_index=recurrence_index,
        request_kind=kind,
        target=str(notation_token.issued_to_role),
        reason=(
            f"queen_notation:{notation_token.notation};"
            f"response_class:{notation_token.response_class}"
        ),
        source_receipt_id=str(queen_receipt.receipt_id),
        notation_token_id=str(notation_token.token_id),
        required_inputs=REQUEST_REQUIRED_INPUTS[kind],
    )


def requests_from_queen_receipt(
    *,
    graph: WorldGraph,
    recurrence_index: int,
    queen_receipt: Any,
) -> tuple[QueenResearchRequest, ...]:
    requests = [
        request_from_notation(
            graph=graph,
            recurrence_index=recurrence_index,
            queen_receipt=queen_receipt,
            notation_token=token,
        )
        for token in getattr(
            queen_receipt,
            "notation_tokens",
            (),
        )
    ]

    # Queen may emit several musical phrases that collapse onto the same
    # canonical bounded action. Preserve separate target/reason semantics,
    # but eliminate exact duplicate deterministic requests.
    unique = {
        request.request_id: request
        for request in requests
    }

    return tuple(
        unique[key]
        for key in sorted(unique)
    )


def build_recurrence_step(
    *,
    graph: WorldGraph,
    recurrence_index: int,
    queen_before: Any,
    queen_after: Any,
    request: QueenResearchRequest,
    response: QueenResearchResponse,
    graph_node_count_before: int,
    graph_node_count_after: int,
) -> QueenRecurrenceStep:
    root_digest = observed_root_digest(graph)

    if request.request_id != response.request_id:
        raise ValueError("recurrence_request_response_mismatch")

    if request.recurrence_index != recurrence_index:
        raise ValueError("recurrence_request_index_mismatch")

    if response.recurrence_index != recurrence_index:
        raise ValueError("recurrence_response_index_mismatch")

    if request.world_state_id != graph.frame.world_state_id:
        raise ValueError("recurrence_request_world_drift")

    if response.world_state_id != graph.frame.world_state_id:
        raise ValueError("recurrence_response_world_drift")

    if request.world_state_hash != graph.frame.world_state_hash:
        raise ValueError("recurrence_request_hash_drift")

    if response.world_state_hash != graph.frame.world_state_hash:
        raise ValueError("recurrence_response_hash_drift")

    if request.observed_root_digest != root_digest:
        raise ValueError("recurrence_request_root_drift")

    if response.observed_root_digest != root_digest:
        raise ValueError("recurrence_response_root_drift")

    before_id = str(queen_before.receipt_id)
    after_id = str(queen_after.receipt_id)

    interpretation_before = queen_interpretation_signature(
        queen_before
    )
    interpretation_after = queen_interpretation_signature(
        queen_after
    )

    interpretation_changed = (
        interpretation_before != interpretation_after
    )

    body = {
        "recurrence_index": recurrence_index,
        "queen_before": before_id,
        "queen_after": after_id,
        "request_id": request.request_id,
        "response_id": response.response_id,
        "graph_node_count_before": graph_node_count_before,
        "graph_node_count_after": graph_node_count_after,
        "interpretation_changed": interpretation_changed,
        "interpretation_before": interpretation_before,
        "interpretation_after": interpretation_after,
        "world_state_id": graph.frame.world_state_id,
        "world_state_hash": graph.frame.world_state_hash,
        "observed_root_digest": root_digest,
    }

    return QueenRecurrenceStep(
        schema="hivenance_queen_recurrence_step_v1",
        step_id="qstep_" + _digest(body).split(":", 1)[1][:24],
        recurrence_index=int(recurrence_index),
        queen_receipt_id_before=before_id,
        queen_receipt_id_after=after_id,
        request=request,
        response=response,
        graph_node_count_before=int(graph_node_count_before),
        graph_node_count_after=int(graph_node_count_after),
        interpretation_changed=bool(interpretation_changed),
        world_state_id=graph.frame.world_state_id,
        world_state_hash=graph.frame.world_state_hash,
        observed_root_digest=root_digest,
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
        promotion_eligible=False,
    )


def queen_interpretation_signature(receipt: Any) -> str:
    """Digest Queen semantics, excluding receipt/token identity and clock noise."""

    metric_names = (
        "epoch_consonance",
        "world_state_tension",
        "vns_pulse_energy",
        "vns_syncopation",
        "vns_phrase_energy",
        "vns_measure_novelty",
        "vns_echo_pressure",
        "vns_rest_density",
        "vns_phrase_modulation",
        "temporal_jitter",
        "temporal_drift",
        "temporal_burstiness",
        "temporal_entropy",
        "temporal_cadence_coherence",
        "edge_chorus_quality",
        "edge_mesh_entrainment",
        "edge_settlement",
        "hunt_pressure",
        "correlation_harmony",
        "cascade_strength",
        "cascade_crescendo",
        "hive_pulse_energy",
        "polyphonic_resonance",
        "cross_band_tension",
        "register_diversity",
        "overtone_coherence",
        "resonance_drift",
        "mystique_fragility",
        "mystique_survival_rate",
        "metabolic_cdi",
        "metabolic_strain",
        "cognitive_breath",
        "learned_health",
        "learned_drift_pressure",
        "learned_uncertainty_pressure",
        "learned_dissent",
        "tonal_coherence",
        "timbral_diversity",
        "pitch_convergence",
        "subtle_shift_score",
        "polyphonic_pressure",
    )

    metrics = {
        name: getattr(receipt, name, None)
        for name in metric_names
    }

    triune = tuple(
        sorted(
            (
                str(sheet.mind),
                tuple(sheet.motifs_heard),
                tuple(sheet.dynamics),
                tuple(sheet.cautions),
                tuple(sheet.invitations),
                float(sheet.intensity),
            )
            for sheet in getattr(receipt, "triune_scores", ())
        )
    )

    payload = {
        "metrics": metrics,
        "resonance_texture": getattr(
            receipt,
            "resonance_texture",
            None,
        ),
        "metabolism_texture": getattr(
            receipt,
            "metabolism_texture",
            None,
        ),
        "mystique_contamination_guard": getattr(
            receipt,
            "mystique_contamination_guard",
            None,
        ),
        "learned_voice_count": getattr(
            receipt,
            "learned_voice_count",
            None,
        ),
        "learned_independent_count": getattr(
            receipt,
            "learned_independent_count",
            None,
        ),
        "gestures": tuple(
            sorted(
                getattr(
                    receipt,
                    "conducting_gestures",
                    (),
                )
            )
        ),
        "reasons": tuple(
            sorted(getattr(receipt, "reasons", ()))
        ),
        "triune": triune,
    }

    return _digest(payload)


REQUEST_PRIORITY = {
    "RETIRE_FROM_ACTIVE_SCORE": 0,
    "CHANGE_EPOCH": 1,
    "THIN": 2,
    "CHALLENGE": 3,
    "REHEARSE_EDGE_RESOLUTION": 4,
    "COMPARE": 5,
    "INVITE_INDEPENDENT_CORROBORATION": 6,
    "PRESERVE_COUNTERPOINT": 7,
    "REFRESH": 8,
    "AMPLIFY": 9,
    "WAIT_REST": 10,
}


def select_recursive_request(
    requests: Sequence[QueenResearchRequest],
) -> QueenResearchRequest | None:
    if not requests:
        return None

    unknown = sorted({
        request.request_kind
        for request in requests
        if request.request_kind not in REQUEST_PRIORITY
    })

    if unknown:
        raise ValueError(
            "recursive_request_priority_missing:"
            + ",".join(unknown)
        )

    return sorted(
        requests,
        key=lambda request: (
            REQUEST_PRIORITY[request.request_kind],
            request.request_kind,
            request.target,
            request.request_id,
        ),
    )[0]


class RecursiveQueenLoop:
    """Deterministic research recurrence over one immutable observed frame."""

    version = "hivenance.recursive_queen_loop.v2"

    def __init__(self, *, max_recurrences: int = 3) -> None:
        if max_recurrences < 1:
            raise ValueError(
                "max_recurrences_must_be_positive"
            )
        self.max_recurrences = int(max_recurrences)

    @staticmethod
    def assert_same_world(
        graph: WorldGraph,
        *,
        world_state_id: str,
        world_state_hash: str,
        root_digest: str,
    ) -> None:
        if graph.frame.world_state_id != world_state_id:
            raise ValueError(
                "recursive_world_state_id_changed"
            )
        if graph.frame.world_state_hash != world_state_hash:
            raise ValueError(
                "recursive_world_state_hash_changed"
            )
        if observed_root_digest(graph) != root_digest:
            raise ValueError(
                "recursive_observed_root_changed"
            )

    def run(
        self,
        *,
        graph: WorldGraph,
        initial_queen_receipt: Any,
        dispatch: Any,
        reconduct: Any,
        start_ms: int,
        metabolism: CognitiveMetabolismReceipt | None = None,
    ) -> RecursiveQueenRun:
        world_state_id = graph.frame.world_state_id
        world_state_hash = graph.frame.world_state_hash
        root_digest = observed_root_digest(graph)

        current_queen = initial_queen_receipt
        initial_id = str(initial_queen_receipt.receipt_id)

        steps: list[QueenRecurrenceStep] = []
        budget = recurrence_budget(
            metabolism,
            configured_max=self.max_recurrences,
        )
        if budget.stop_immediately:
            stop_reason = "METABOLIC_INFORMATION_EXHAUSTION"
        else:
            stop_reason = "MAX_RECURRENCES"

        for recurrence_index in range(
            budget.max_recurrences
        ):
            self.assert_same_world(
                graph,
                world_state_id=world_state_id,
                world_state_hash=world_state_hash,
                root_digest=root_digest,
            )

            requests = requests_from_queen_receipt(
                graph=graph,
                recurrence_index=recurrence_index,
                queen_receipt=current_queen,
            )

            request = select_recursive_request(requests)

            if request is None:
                stop_reason = "NO_REQUESTS"
                break

            if request.request_kind == "WAIT_REST":
                stop_reason = "WAIT_REST"
                break

            created_at_ms = (
                int(start_ms)
                + recurrence_index * 2
                + 1
            )

            before_count = len(
                graph.queen_view(
                    created_at_ms=created_at_ms
                ).nodes
            )

            response, response_context = dispatch(
                graph=graph,
                request=request,
                queen_receipt=current_queen,
                recurrence_index=recurrence_index,
                created_at_ms=created_at_ms,
            )

            self.assert_same_world(
                graph,
                world_state_id=world_state_id,
                world_state_hash=world_state_hash,
                root_digest=root_digest,
            )

            after_count = len(
                graph.queen_view(
                    created_at_ms=created_at_ms
                ).nodes
            )

            queen_after = reconduct(
                graph=graph,
                queen_before=current_queen,
                request=request,
                response=response,
                response_context=response_context,
                recurrence_index=recurrence_index,
                now_ms=created_at_ms + 1,
            )

            self.assert_same_world(
                graph,
                world_state_id=world_state_id,
                world_state_hash=world_state_hash,
                root_digest=root_digest,
            )

            step = build_recurrence_step(
                graph=graph,
                recurrence_index=recurrence_index,
                queen_before=current_queen,
                queen_after=queen_after,
                request=request,
                response=response,
                graph_node_count_before=before_count,
                graph_node_count_after=after_count,
            )

            steps.append(step)
            current_queen = queen_after

            if response.state in {
                "ABSTAINED",
                "REFUSED",
            }:
                stop_reason = "RESPONSE_" + response.state
                break

            if not response.graph_changed:
                stop_reason = "NO_GRAPH_CHANGE"
                break

            if not step.interpretation_changed:
                stop_reason = "INTERPRETATION_STABLE"
                break

        body = {
            "world_state_id": world_state_id,
            "world_state_hash": world_state_hash,
            "observed_root_digest": root_digest,
            "max_recurrences": self.max_recurrences,
            "metabolic_max_recurrences": budget.max_recurrences,
            "metabolic_budget_reason": budget.reason,
            "steps": tuple(
                step.step_id
                for step in steps
            ),
            "initial_queen_receipt_id": initial_id,
            "final_queen_receipt_id": str(
                current_queen.receipt_id
            ),
            "stop_reason": stop_reason,
        }

        return RecursiveQueenRun(
            schema="hivenance_recursive_queen_run_v1",
            run_id=(
                "qrun_"
                + _digest(body).split(":", 1)[1][:24]
            ),
            world_state_id=world_state_id,
            world_state_hash=world_state_hash,
            observed_root_digest=root_digest,
            max_recurrences=self.max_recurrences,
            recurrence_count=len(steps),
            stop_reason=stop_reason,
            steps=tuple(steps),
            initial_queen_receipt_id=initial_id,
            final_queen_receipt_id=str(
                current_queen.receipt_id
            ),
            execution_eligible=False,
            promotion_eligible=False,
        )
