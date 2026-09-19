from strategies.relative_value_lab.edge_ecology import EdgeEcology
from strategies.relative_value_lab.metatron_ml_challenger import MetatronMLChallenger


def test_flow_detects_exhaustion_without_granting_authority():
    v = EdgeEcology.flow_voice(taker_buy_volume=51, taker_sell_volume=49, previous_imbalance=0.60)
    assert v.state == "AGGRESSIVE_FLOW_EXHAUSTING"
    assert v.execution_eligible is False
    assert v.promotion_eligible is False


def test_flow_detects_persistence():
    v = EdgeEcology.flow_voice(taker_buy_volume=85, taker_sell_volume=15, previous_imbalance=0.50)
    assert v.state == "DIRECTIONAL_FLOW_PERSISTENT"


def test_liquidity_recovery_is_independent_voice():
    v = EdgeEcology.liquidity_voice(
        bid_depth=800, ask_depth=700, spread_bps=4,
        previous_bid_depth=500, previous_ask_depth=500,
    )
    assert v.state == "LIQUIDITY_RECOVERING"
    assert v.family == "LIQUIDITY"


def test_snapshot_rejects_fake_diversity():
    ecology = EdgeEcology()
    a = ecology.flow_voice(taker_buy_volume=60, taker_sell_volume=40)
    try:
        ecology.snapshot(timestamp_ms=1, pair_id="A/B", voices=[a, a])
    except ValueError as exc:
        assert str(exc) == "edge_ecology_duplicate_family"
    else:
        raise AssertionError("duplicate families must be rejected")


def test_metatron_ml_challenger_is_research_only_and_deterministic():
    rows = [[i / 100.0, (i % 7) / 10.0, (i % 3) / 5.0] for i in range(1, 180)]
    a = MetatronMLChallenger(seed=2306)
    b = MetatronMLChallenger(seed=2306)
    a.fit(rows)
    b.fit(rows)
    ca = a.challenge([4.0, 4.0, 4.0])
    cb = b.challenge([4.0, 4.0, 4.0])
    assert ca == cb
    assert ca.research_only is True
    assert ca.execution_eligible is False
    assert ca.promotion_eligible is False
