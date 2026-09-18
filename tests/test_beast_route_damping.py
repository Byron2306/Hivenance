from pathlib import Path

from strategies.volatility_breakout.beast_route_damping import HivenanceRouteDampener


def test_route_dampener_suppresses_then_decays(tmp_path: Path):
    path = tmp_path / "damping.json"
    dampener = HivenanceRouteDampener(path=path, suppress_at=500.0, half_life_seconds=10.0)

    route_id = "worker|breakout|volatile|major|BTC/USD|300|UP|*|*"
    first = dampener.record(route_id, "wrong_regime", now=100.0)
    second = dampener.record(route_id, "spread_too_wide", now=101.0)

    assert first.penalty > 0
    assert second.penalty >= 500.0
    assert dampener.suppressed(route_id, now=101.0) is True

    recovered = dampener.score(route_id, now=141.0)
    assert recovered.penalty < second.penalty
    assert HivenanceRouteDampener(path=path, suppress_at=500.0, half_life_seconds=10.0).score(route_id).route_id == route_id


def test_route_id_binds_worker_symbol_regime_and_execution_policy(tmp_path: Path):
    dampener = HivenanceRouteDampener(path=tmp_path / "damping.json")
    candidate = {
        "model_id": "worker_signal_alpha",
        "hypothesis": "breakout_continuation",
        "regime_hint": "volatile_breakout",
        "cohort_bucket": "major",
        "symbol_class": "ultra_liquid_major",
        "symbol": "ETH/USD",
        "horizon_seconds": 900,
        "direction": "UP",
    }

    assert dampener.route_id_from_candidate(candidate, policy="market", scenario="normal").endswith("|market|normal")


def test_record_many_compacts_route_events_in_one_state(tmp_path: Path):
    path = tmp_path / "damping.json"
    dampener = HivenanceRouteDampener(path=path, suppress_at=500.0, half_life_seconds=60.0)
    route_id = "worker|breakout|volatile|major|BTC/USD|300|UP|maker|baseline"

    applied = dampener.record_many({(route_id, "wrong_regime"): 2, (route_id, "success"): 1}, now=100.0)
    score = dampener.score(route_id, now=100.0)

    assert applied == {"applied": 3, "ignored": 0}
    assert score.events == 3
    assert score.penalty == (450.0 * 2) - 35.0
    assert HivenanceRouteDampener(path=path, suppress_at=500.0).suppressed(route_id, now=100.0) is True
