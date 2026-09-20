import pytest

from strategies.relative_value_lab.recursive_queen_loop import (
    RecursiveQueenLoop,
    build_request,
    build_response,
    observed_root_digest,
)
from strategies.relative_value_lab.vns_score_conductor import (
    VNSScoreConductor,
)
from strategies.relative_value_lab.world_graph import WorldGraph


def cycle(price=100.0, run_id="r1", completed=3000):
    return {
        "run": {
            "run_id": run_id,
            "venue": "kraken",
            "completed_at_ms": completed,
        },
        "candidates": [{
            "symbol": "BTC/USD",
            "venue": "kraken",
            "timestamp_ms": completed - 100,
            "price": price,
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
        "dataset_hash": run_id,
    }


def graph():
    measure = VNSScoreConductor().conduct_cycle(cycle())
    return WorldGraph(measure.frame)


def test_request_binds_same_immutable_world():
    g = graph()

    request = build_request(
        graph=g,
        recurrence_index=0,
        request_kind="CHALLENGE",
        target="motif-1",
        reason="false_unison_pressure",
        source_receipt_id="queen-1",
    )

    assert request.world_state_id == g.frame.world_state_id
    assert request.world_state_hash == g.frame.world_state_hash
    assert request.observed_root_digest == observed_root_digest(g)
    assert request.execution_eligible is False
    assert request.promotion_eligible is False


def test_response_cannot_follow_world_drift():
    g1 = graph()

    request = build_request(
        graph=g1,
        recurrence_index=0,
        request_kind="REFRESH",
        target="vns",
        reason="freshness_decay",
        source_receipt_id="queen-1",
    )

    measure2 = VNSScoreConductor().conduct_cycle(
        cycle(price=110.0, run_id="r2", completed=6000)
    )
    g2 = WorldGraph(measure2.frame)

    with pytest.raises(
        ValueError,
        match="recursive_request_world",
    ):
        build_response(
            graph=g2,
            request=request,
            state="ANSWERED",
            organ_id="public_observer",
            answer="newer market observation",
        )


def test_response_can_add_derived_node_without_changing_observed_root():
    g = graph()

    before = observed_root_digest(g)

    source = g.add_node(
        organ_id="test-source",
        family="TEST",
        created_at_ms=3000,
        evidence_roots=tuple(
            obs.evidence_root
            for obs in g.frame.observations
        ),
        lineage_id="test",
        transformation_id="test.v1",
        payload={"value": 1},
    )

    request = build_request(
        graph=g,
        recurrence_index=0,
        request_kind="COMPARE",
        target="test",
        reason="compare_context",
        source_receipt_id="queen-1",
    )

    derived = g.add_node(
        organ_id="comparison",
        family="COMPARISON",
        created_at_ms=3001,
        evidence_roots=source.evidence_roots,
        lineage_id="comparison",
        transformation_id="comparison.v1",
        payload={"comparison": "changed interpretation"},
    )

    response = build_response(
        graph=g,
        request=request,
        state="ANSWERED",
        organ_id="comparison_engine",
        answer="comparison added",
        source_nodes=(source,),
        added_nodes=(derived,),
    )

    after = observed_root_digest(g)

    assert before == after
    assert response.graph_changed is True
    assert response.added_node_ids == (derived.node_id,)


def test_loop_has_deterministic_positive_max_recurrence():
    loop = RecursiveQueenLoop(max_recurrences=3)
    assert loop.max_recurrences == 3

    with pytest.raises(
        ValueError,
        match="max_recurrences_must_be_positive",
    ):
        RecursiveQueenLoop(max_recurrences=0)


def test_same_world_guard_accepts_graph_interpretation_growth():
    g = graph()

    root = observed_root_digest(g)

    g.add_node(
        organ_id="challenge",
        family="CHALLENGE",
        created_at_ms=3001,
        evidence_roots=tuple(
            obs.evidence_root
            for obs in g.frame.observations
        ),
        lineage_id="challenge",
        transformation_id="challenge.v1",
        payload={"challenged": True},
    )

    RecursiveQueenLoop.assert_same_world(
        g,
        world_state_id=g.frame.world_state_id,
        world_state_hash=g.frame.world_state_hash,
        root_digest=root,
    )


def test_same_world_guard_refuses_different_observation_frame():
    g1 = graph()
    root = observed_root_digest(g1)

    measure2 = VNSScoreConductor().conduct_cycle(
        cycle(price=120.0, run_id="r2", completed=6000)
    )
    g2 = WorldGraph(measure2.frame)

    with pytest.raises(
        ValueError,
        match="recursive_world_state",
    ):
        RecursiveQueenLoop.assert_same_world(
            g2,
            world_state_id=g1.frame.world_state_id,
            world_state_hash=g1.frame.world_state_hash,
            root_digest=root,
        )


from dataclasses import dataclass

from strategies.relative_value_lab.recursive_queen_loop import (
    REQUEST_REQUIRED_INPUTS,
    request_from_notation,
    request_kind_for_notation,
    requests_from_queen_receipt,
)


@dataclass(frozen=True)
class FakeNotation:
    token_id: str
    issued_to_role: str
    notation: str
    epoch_id: str
    world_state_id: str
    world_state_hash: str
    response_class: str


@dataclass(frozen=True)
class FakeQueenReceipt:
    receipt_id: str
    epoch_id: str
    notation_tokens: tuple[FakeNotation, ...]


def test_real_queen_notation_maps_to_bounded_request_language():
    expected = {
        "LISTEN": "WAIT_REST",
        "CHALLENGE_CADENCE": "CHALLENGE",
        "TRACE_SHARED_ASSET": "COMPARE",
        "INVITE_INDEPENDENT_CORROBORATION":
            "INVITE_INDEPENDENT_CORROBORATION",
        "PRESERVE_COUNTERPOINT": "PRESERVE_COUNTERPOINT",
        "THIN_ORCHESTRATION": "THIN",
        "AMPLIFY_SEARCH": "AMPLIFY",
        "HOLD_FREEZE_ACCENT": "RETIRE_FROM_ACTIVE_SCORE",
        "REHEARSE_EDGE_RESOLUTION":
            "REHEARSE_EDGE_RESOLUTION",
        "REKEY_SCORE": "CHANGE_EPOCH",
        "LET_MOTIF_REST": "WAIT_REST",
    }

    for notation, kind in expected.items():
        assert request_kind_for_notation(notation) == kind


def test_unmapped_queen_notation_fails_closed():
    with pytest.raises(
        ValueError,
        match="queen_notation_unmapped",
    ):
        request_kind_for_notation(
            "MAGIC_NEW_MARKET_EVIDENCE"
        )


def test_notation_token_becomes_world_bound_request():
    g = graph()

    token = FakeNotation(
        token_id="tok-1",
        issued_to_role="loki_counterpoint",
        notation="CHALLENGE_CADENCE",
        epoch_id="epoch-1",
        world_state_id=g.frame.world_state_id,
        world_state_hash=g.frame.world_state_hash,
        response_class="DISSENT_OR_SEARCH",
    )

    queen = FakeQueenReceipt(
        receipt_id="queen-1",
        epoch_id="epoch-1",
        notation_tokens=(token,),
    )

    request = request_from_notation(
        graph=g,
        recurrence_index=1,
        queen_receipt=queen,
        notation_token=token,
    )

    assert request.request_kind == "CHALLENGE"
    assert request.target == "loki_counterpoint"
    assert request.notation_token_id == "tok-1"
    assert (
        request.required_inputs
        == REQUEST_REQUIRED_INPUTS["CHALLENGE"]
    )
    assert request.world_state_id == g.frame.world_state_id
    assert request.execution_eligible is False


def test_refresh_request_cannot_mean_later_market_data():
    g = graph()

    token = FakeNotation(
        token_id="tok-refresh",
        issued_to_role="market_hunter",
        notation="TRACE_MODULATION",
        epoch_id="epoch-1",
        world_state_id=g.frame.world_state_id,
        world_state_hash=g.frame.world_state_hash,
        response_class="SEARCH",
    )

    queen = FakeQueenReceipt(
        receipt_id="queen-1",
        epoch_id="epoch-1",
        notation_tokens=(token,),
    )

    request = request_from_notation(
        graph=g,
        recurrence_index=1,
        queen_receipt=queen,
        notation_token=token,
    )

    assert request.request_kind == "REFRESH"
    assert "frozen_observations" in request.required_inputs
    assert "future_observations" not in request.required_inputs


def test_notation_world_mismatch_is_refused():
    g = graph()

    token = FakeNotation(
        token_id="tok-bad",
        issued_to_role="market_hunter",
        notation="AMPLIFY_SEARCH",
        epoch_id="epoch-1",
        world_state_id="wrong-world",
        world_state_hash=g.frame.world_state_hash,
        response_class="SEARCH",
    )

    queen = FakeQueenReceipt(
        receipt_id="queen-1",
        epoch_id="epoch-1",
        notation_tokens=(token,),
    )

    with pytest.raises(
        ValueError,
        match="notation_world_state_id_mismatch",
    ):
        request_from_notation(
            graph=g,
            recurrence_index=1,
            queen_receipt=queen,
            notation_token=token,
        )


def test_receipt_translates_all_tokens_deterministically():
    g = graph()

    tokens = (
        FakeNotation(
            "tok-1",
            "loki",
            "CHALLENGE_CADENCE",
            "epoch-1",
            g.frame.world_state_id,
            g.frame.world_state_hash,
            "DISSENT_OR_SEARCH",
        ),
        FakeNotation(
            "tok-2",
            "market_hunter",
            "AMPLIFY_SEARCH",
            "epoch-1",
            g.frame.world_state_id,
            g.frame.world_state_hash,
            "SEARCH_OR_ALARM",
        ),
    )

    queen = FakeQueenReceipt(
        receipt_id="queen-1",
        epoch_id="epoch-1",
        notation_tokens=tokens,
    )

    first = requests_from_queen_receipt(
        graph=g,
        recurrence_index=1,
        queen_receipt=queen,
    )

    second = requests_from_queen_receipt(
        graph=g,
        recurrence_index=1,
        queen_receipt=queen,
    )

    assert first == second
    assert {
        request.request_kind
        for request in first
    } == {"CHALLENGE", "AMPLIFY"}
