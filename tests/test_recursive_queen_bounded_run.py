from dataclasses import dataclass

from strategies.relative_value_lab.recursive_queen_loop import (
    RecursiveQueenLoop,
    QueenResearchResponse,
    observed_root_digest,
    select_recursive_request,
)
from strategies.relative_value_lab.vns_score_conductor import (
    VNSScoreConductor,
)
from strategies.relative_value_lab.world_graph import WorldGraph


def cycle():
    return {
        "run": {
            "run_id": "bounded-r1",
            "venue": "kraken",
            "completed_at_ms": 3000,
        },
        "candidates": [{
            "symbol": "BTC/USD",
            "venue": "kraken",
            "timestamp_ms": 2900,
            "price": 100.0,
            "spread_bps": 5.0,
            "depth_usd_25bps": 100000.0,
            "quote_volume_24h": 50000000.0,
            "data_quality": 1.0,
            "freshness_sec": 1.0,
            "continuity_ratio": 1.0,
            "observation_eligible": True,
        }],
        "world_state_summary": {
            "fresh_candidate_count": 1,
        },
        "dataset_hash": "bounded-r1",
    }


@dataclass(frozen=True)
class Token:
    token_id: str
    issued_to_role: str
    notation: str
    epoch_id: str
    world_state_id: str
    world_state_hash: str
    response_class: str


@dataclass(frozen=True)
class Queen:
    receipt_id: str
    epoch_id: str
    notation_tokens: tuple[Token, ...]
    mystique_fragility: float = 0.0
    mystique_survival_rate: float = 0.0
    conducting_gestures: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    triune_scores: tuple = ()


def setup_graph():
    measure = VNSScoreConductor().conduct_cycle(
        cycle()
    )
    return WorldGraph(measure.frame)


def queen(graph, receipt_id, notation, fragility=0.0):
    return Queen(
        receipt_id=receipt_id,
        epoch_id="epoch-1",
        notation_tokens=(
            Token(
                token_id="tok-" + receipt_id,
                issued_to_role="loki_counterpoint",
                notation=notation,
                epoch_id="epoch-1",
                world_state_id=graph.frame.world_state_id,
                world_state_hash=graph.frame.world_state_hash,
                response_class="DISSENT_OR_SEARCH",
            ),
        ),
        mystique_fragility=fragility,
        conducting_gestures=(
            ("CHALLENGE",)
            if fragility
            else ()
        ),
    )


def test_request_priority_prefers_challenge_over_wait():
    graph = setup_graph()

    q = Queen(
        receipt_id="q0",
        epoch_id="epoch-1",
        notation_tokens=(
            Token(
                "wait",
                "all_research_voices",
                "LISTEN",
                "epoch-1",
                graph.frame.world_state_id,
                graph.frame.world_state_hash,
                "OBSERVE_AND_WAGGLE",
            ),
            Token(
                "challenge",
                "loki_counterpoint",
                "CHALLENGE_CADENCE",
                "epoch-1",
                graph.frame.world_state_id,
                graph.frame.world_state_hash,
                "DISSENT_OR_SEARCH",
            ),
        ),
    )

    from strategies.relative_value_lab.recursive_queen_loop import (
        requests_from_queen_receipt,
    )

    requests = requests_from_queen_receipt(
        graph=graph,
        recurrence_index=0,
        queen_receipt=q,
    )

    selected = select_recursive_request(requests)

    assert selected.request_kind == "CHALLENGE"


def test_loop_stops_at_deterministic_maximum():
    graph = setup_graph()
    initial_root = observed_root_digest(graph)

    initial = queen(
        graph,
        "q0",
        "CHALLENGE_CADENCE",
    )

    counter = {"n": 0}

    def dispatch(
        *,
        graph,
        request,
        queen_receipt,
        recurrence_index,
        created_at_ms,
    ):
        counter["n"] += 1

        node = graph.add_node(
            organ_id="bounded-test",
            family="CHALLENGE",
            created_at_ms=created_at_ms,
            evidence_roots=tuple(
                obs.evidence_root
                for obs in graph.frame.observations
            ),
            lineage_id="bounded-test",
            transformation_id=(
                f"bounded-test.{recurrence_index}"
            ),
            payload={
                "recurrence_index": recurrence_index,
            },
        )

        response = QueenResearchResponse(
            schema="hivenance_queen_research_response_v1",
            response_id=f"response-{recurrence_index}",
            request_id=request.request_id,
            recurrence_index=recurrence_index,
            state="ANSWERED",
            organ_id="bounded-test",
            answer="bounded response",
            source_node_ids=(),
            added_node_ids=(node.node_id,),
            evidence_roots=node.evidence_roots,
            world_state_id=graph.frame.world_state_id,
            world_state_hash=graph.frame.world_state_hash,
            observed_root_digest=observed_root_digest(
                graph
            ),
            graph_changed=True,
        )

        return response, {
            "recurrence_index": recurrence_index,
        }

    def reconduct(
        *,
        graph,
        queen_before,
        request,
        response,
        response_context,
        recurrence_index,
        now_ms,
    ):
        return queen(
            graph,
            f"q{recurrence_index + 1}",
            "CHALLENGE_CADENCE",
            fragility=(
                float(recurrence_index + 1) / 10.0
            ),
        )

    run = RecursiveQueenLoop(
        max_recurrences=3
    ).run(
        graph=graph,
        initial_queen_receipt=initial,
        dispatch=dispatch,
        reconduct=reconduct,
        start_ms=4000,
    )

    assert run.recurrence_count == 3
    assert run.stop_reason == "MAX_RECURRENCES"
    assert counter["n"] == 3
    assert len(run.steps) == 3

    assert observed_root_digest(graph) == initial_root

    assert all(
        step.interpretation_changed
        for step in run.steps
    )

    assert run.execution_eligible is False
    assert run.promotion_eligible is False


def test_wait_rest_stops_without_dispatch():
    graph = setup_graph()

    initial = queen(
        graph,
        "q0",
        "LISTEN",
    )

    called = {"dispatch": False}

    def dispatch(**kwargs):
        called["dispatch"] = True
        raise AssertionError(
            "WAIT_REST must not dispatch"
        )

    def reconduct(**kwargs):
        raise AssertionError(
            "WAIT_REST must not reconduct"
        )

    run = RecursiveQueenLoop(
        max_recurrences=3
    ).run(
        graph=graph,
        initial_queen_receipt=initial,
        dispatch=dispatch,
        reconduct=reconduct,
        start_ms=4000,
    )

    assert run.recurrence_count == 0
    assert run.stop_reason == "WAIT_REST"
    assert called["dispatch"] is False


def test_no_graph_change_stops_recurrence():
    graph = setup_graph()

    initial = queen(
        graph,
        "q0",
        "CHALLENGE_CADENCE",
    )

    def dispatch(
        *,
        graph,
        request,
        queen_receipt,
        recurrence_index,
        created_at_ms,
    ):
        response = QueenResearchResponse(
            schema="hivenance_queen_research_response_v1",
            response_id="no-change",
            request_id=request.request_id,
            recurrence_index=recurrence_index,
            state="NO_CHANGE",
            organ_id="test",
            answer="nothing new",
            source_node_ids=(),
            added_node_ids=(),
            evidence_roots=(),
            world_state_id=graph.frame.world_state_id,
            world_state_hash=graph.frame.world_state_hash,
            observed_root_digest=observed_root_digest(
                graph
            ),
            graph_changed=False,
        )

        return response, None

    def reconduct(
        *,
        graph,
        queen_before,
        **kwargs,
    ):
        return queen_before

    run = RecursiveQueenLoop(
        max_recurrences=3
    ).run(
        graph=graph,
        initial_queen_receipt=initial,
        dispatch=dispatch,
        reconduct=reconduct,
        start_ms=4000,
    )

    assert run.recurrence_count == 1
    assert run.stop_reason == "NO_GRAPH_CHANGE"


def test_semantically_identical_queen_stops_as_stable():
    graph = setup_graph()

    initial = queen(
        graph,
        "q0",
        "CHALLENGE_CADENCE",
    )

    def dispatch(
        *,
        graph,
        request,
        recurrence_index,
        created_at_ms,
        **kwargs,
    ):
        node = graph.add_node(
            organ_id="test",
            family="CHALLENGE",
            created_at_ms=created_at_ms,
            evidence_roots=tuple(
                obs.evidence_root
                for obs in graph.frame.observations
            ),
            lineage_id="test",
            transformation_id="test",
            payload={"x": 1},
        )

        return QueenResearchResponse(
            schema="hivenance_queen_research_response_v1",
            response_id="response",
            request_id=request.request_id,
            recurrence_index=recurrence_index,
            state="ANSWERED",
            organ_id="test",
            answer="answer",
            source_node_ids=(),
            added_node_ids=(node.node_id,),
            evidence_roots=node.evidence_roots,
            world_state_id=graph.frame.world_state_id,
            world_state_hash=graph.frame.world_state_hash,
            observed_root_digest=observed_root_digest(
                graph
            ),
            graph_changed=True,
        ), None

    def reconduct(
        *,
        graph,
        queen_before,
        **kwargs,
    ):
        # Different receipt identity, same semantics.
        return Queen(
            receipt_id="different-id",
            epoch_id=queen_before.epoch_id,
            notation_tokens=queen_before.notation_tokens,
            mystique_fragility=(
                queen_before.mystique_fragility
            ),
            mystique_survival_rate=(
                queen_before.mystique_survival_rate
            ),
            conducting_gestures=(
                queen_before.conducting_gestures
            ),
            reasons=queen_before.reasons,
            triune_scores=queen_before.triune_scores,
        )

    run = RecursiveQueenLoop(
        max_recurrences=3
    ).run(
        graph=graph,
        initial_queen_receipt=initial,
        dispatch=dispatch,
        reconduct=reconduct,
        start_ms=4000,
    )

    assert run.recurrence_count == 1
    assert run.stop_reason == "INTERPRETATION_STABLE"
    assert run.steps[0].interpretation_changed is False
