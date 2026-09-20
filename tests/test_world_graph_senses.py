import pytest
from agents.horizon_context import HorizonContextAgent
from strategies.relative_value_lab.edge_ecology import EdgeEcology
from strategies.relative_value_lab.temporal_participation_bee import (
    ParticipationObservation,
    TemporalParticipationBee,
)
from strategies.relative_value_lab.world_graph import WorldGraph
from strategies.relative_value_lab.world_graph_adapters import (
    add_edge_ecology,
    add_horizon_context,
    add_temporal_participation,
)
from strategies.relative_value_lab.world_score import CanonicalWorldScore, ScoreObservation


def _root(char):
    return "sha256:" + char * 64


def _frame():
    obs = ScoreObservation(
        observation_id="obs",
        source_id="public",
        source_class="public_market",
        scope="BTC/USD",
        observed_at_ms=10_000,
        received_at_ms=10_001,
        evidence_root=_root("a"),
        payload={"price": 100},
    )
    return CanonicalWorldScore.assemble(observations=[obs], assembled_at_ms=10_002)


def test_existing_senses_and_temporal_bee_enter_same_queen_view():
    graph = WorldGraph(_frame())
    horizon = HorizonContextAgent().build(
        symbol="BTC/USD",
        timestamp=10.0,
        returns_bps={"10s": 1, "30s": 2, "2m": 3, "5m": 4, "15m": 5, "1h": -10},
        realized_vol_bps={"30s": 1, "5m": 10},
        ticker_24h={"open": 100, "last": 102, "high": 103, "low": 99},
        cross_sectional_returns={"30s": [1], "2m": [2], "5m": [3], "15m": [4], "1h": [5]},
    )
    add_horizon_context(graph, context=horizon, created_at_ms=10_003, source_roots=[_root("b")])

    ecology = EdgeEcology()
    snap = ecology.snapshot(
        timestamp_ms=10_000,
        pair_id="BTC/USD",
        voices=[
            ecology.flow_voice(taker_buy_volume=60, taker_sell_volume=40),
            ecology.volatility_voice(returns=[0.01, -0.01, 0.02], baseline_vol=0.01),
        ],
    )
    nodes = add_edge_ecology(
        graph,
        snapshot=snap,
        created_at_ms=10_003,
        family_source_roots={"FLOW": [_root("c")], "VOLATILITY": [_root("b")]},
    )
    assert len(nodes) == 2

    base = 1_700_000_000_000
    hour_ms = 3_600_000
    history = [
        ParticipationObservation(observed_at_ms=base - 24 * hour_ms * i, volume=100 + i)
        for i in range(1, 8)
    ]
    bee = TemporalParticipationBee()
    evidence = bee.observe(observed_at_ms=base, volume=180, history=history)
    add_temporal_participation(graph, evidence=evidence, created_at_ms=base)

    # Phase 5 tightened Queen's boundary: these legacy sense adapters may
    # still construct graph testimony, but major evidence families cannot
    # enter Queen except through canonical BeeEvidence.
    with pytest.raises(
        ValueError,
        match="queen_noncanonical_phase5_evidence",
    ):
        graph.queen_view(
            created_at_ms=base,
            expected_families=(
                "HORIZON",
                "FLOW",
                "VOLATILITY",
                "TEMPORAL_PARTICIPATION",
                "LIQUIDITY",
            ),
        )


def test_temporal_bee_uses_only_prior_same_hour_history():
    base = 1_700_000_000_000
    day = 86_400_000
    history = [
        ParticipationObservation(observed_at_ms=base - day * i, volume=100)
        for i in range(1, 7)
    ]
    history.append(ParticipationObservation(observed_at_ms=base + day, volume=10_000))
    evidence = TemporalParticipationBee().observe(
        observed_at_ms=base,
        volume=200,
        history=history,
    )
    assert evidence.historical_same_hour_n == 6
    assert evidence.volume_ratio_to_same_hour_median == 2.0
    assert evidence.activity_state == "PARTICIPATION_ELEVATED"


def test_worker_realized_move_uses_only_backward_closes():
    from strategies.relative_value_lab.g0_live_evidence import _worker_realized_move_bps

    ws = {
        "closes": [100, 101, 102, 103, 104, 105],
    }

    move = _worker_realized_move_bps(ws, 5)

    assert move == pytest.approx(500.0)


def test_worker_realized_move_refuses_insufficient_history():
    from strategies.relative_value_lab.g0_live_evidence import _worker_realized_move_bps

    ws = {
        "closes": [100, 101, 102],
    }

    assert _worker_realized_move_bps(ws, 5) is None


def test_temporal_move_normalization_ignores_future_history():
    from strategies.relative_value_lab.temporal_participation_bee import (
        ParticipationObservation,
        TemporalParticipationBee,
    )

    base = 1_700_000_000_000
    day = 86_400_000

    prior = [
        ParticipationObservation(
            observed_at_ms=base - day * i,
            volume=100,
            realized_move_bps=10.0,
        )
        for i in range(1, 7)
    ]

    future = ParticipationObservation(
        observed_at_ms=base + day,
        volume=999999,
        realized_move_bps=999999.0,
    )

    bee = TemporalParticipationBee()

    without_future = bee.observe(
        observed_at_ms=base,
        volume=200,
        history=prior,
        realized_move_bps=20.0,
    )

    with_future = bee.observe(
        observed_at_ms=base,
        volume=200,
        history=prior + [future],
        realized_move_bps=20.0,
    )

    assert without_future.move_ratio_to_same_hour_median == pytest.approx(2.0)
    assert with_future.move_ratio_to_same_hour_median == pytest.approx(2.0)
    assert (
        with_future.move_ratio_to_same_hour_median
        == without_future.move_ratio_to_same_hour_median
    )
