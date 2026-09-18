from pathlib import Path
from types import SimpleNamespace

from agents.data_store_agent import DataStoreAgent
from strategies.volatility_breakout.current_truth import build_current_truth, format_current_truth


def test_empty_database_truth_is_safe_and_refuses_promotion(tmp_path: Path):
    db_path = tmp_path / "truth.db"
    store = DataStoreAgent(str(db_path))
    cfg = SimpleNamespace()

    report = build_current_truth(store, cfg, db_path)

    assert report["schema"] == "hivenance_current_truth_v1"
    assert report["overall"]["authority"] == "RESEARCH_ONLY"
    assert report["overall"]["live_execution_authorized"] is False
    assert report["overall"]["profit_claim"] == "NOT_PROVEN"
    assert report["safety"]["status"] == "CLEAN"
    assert report["phases"]["2"]["decision"] == "REFUSE"
    assert report["phases"]["3"]["decision"] == "REFUSE"
    assert report["truth_digest"].startswith("sha256:")

    text = format_current_truth(report)
    assert "CURRENT TRUTH" in text
    assert "Live execution authorized: NO" in text


def test_live_order_table_row_triggers_safety_alert(tmp_path: Path):
    db_path = tmp_path / "truth-alert.db"
    store = DataStoreAgent(str(db_path))
    store.conn.execute(
        "INSERT INTO orders (client_order_id, intent_id, venue, symbol, side, order_type, order_id, status, placed_ts) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("client-test", "intent-test", "kraken", "BTC/USD", "BUY", "MARKET", "test-order", "TEST", 1.0),
    )
    store.conn.commit()

    report = build_current_truth(store, SimpleNamespace(), db_path)

    assert report["overall"]["state"] == "SAFETY_ALERT"
    assert report["safety"]["status"] == "ALERT"
    assert report["safety"]["evidence"]["live_order_table_rows"] == 1


def test_materialized_phase2_scorecard_round_trip(tmp_path: Path):
    db_path = tmp_path / "truth-materialized.db"
    store = DataStoreAgent(str(db_path))
    payload = {
        "phase": 2,
        "mode": "compact_recent_hypothesis_research_only",
        "models": [{"model_id": "worker_signal_test", "mean_net_bps": 1.25}],
        "profitability_slice_posteriors": [],
    }

    assert store.persist_materialized_phase_scorecard(
        phase=2,
        mode="compact_recent_hypothesis_research_only",
        payload=payload,
        source_limit=123,
        ttl_sec=60,
    )
    cached = store.get_materialized_phase_scorecard(
        phase=2,
        mode="compact_recent_hypothesis_research_only",
        source_limit=123,
        max_age_sec=60,
    )

    assert cached is not None
    assert cached["models"][0]["model_id"] == "worker_signal_test"
    assert cached["materialized_snapshot"]["fresh"] is True


def test_exact_truth_reuses_full_history_scorecard_until_evidence_changes(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "truth-exact.db"
    store = DataStoreAgent(str(db_path))
    cfg = SimpleNamespace()

    call_counts = {"phase2": 0, "phase3": 0}
    real_phase2 = store.get_hypothesis_scorecard
    real_phase3 = store.get_execution_scorecard

    def counted_phase2():
        call_counts["phase2"] += 1
        return real_phase2()

    def counted_phase3():
        call_counts["phase3"] += 1
        return real_phase3()

    monkeypatch.setattr(store, "get_hypothesis_scorecard", counted_phase2)
    monkeypatch.setattr(store, "get_execution_scorecard", counted_phase3)

    build_current_truth(store, cfg, db_path, exact=True)
    assert call_counts == {"phase2": 1, "phase3": 1}

    # Repeat call with unchanged evidence must reuse the watermark-cached scorecards
    # instead of re-scanning full history.
    build_current_truth(store, cfg, db_path, exact=True)
    assert call_counts == {"phase2": 1, "phase3": 1}

    # New evidence bumps the rowid watermark, which must force a real recompute.
    # The watermark check is shared across phases (forecast/outcome/order rowids
    # together), so any table change conservatively invalidates all cached exact
    # scorecards rather than only the phase whose table actually changed.
    store.conn.execute(
        "INSERT INTO hypothesis_forecasts (forecast_id, model_id, hypothesis, abstain) "
        "VALUES (?, ?, ?, ?)",
        ("forecast-test", "worker_signal_test", "test_hypothesis", 0),
    )
    store.conn.commit()

    build_current_truth(store, cfg, db_path, exact=True)
    assert call_counts == {"phase2": 2, "phase3": 2}


def _narrow_posterior(
    *,
    scenario: str,
    mean_net_bps: float,
    lower_bound_net_bps: float,
    sample_count: int,
    mean_gross_bps: float,
    model_id: str = "worker_signal_test",
    thesis_family: str = "breakout",
    execution_policy_family: str = "marketable_limit",
    symbol: str = "SOL/USD",
    direction: str = "long",
) -> dict:
    return {
        "model_id": model_id,
        "thesis_family": thesis_family,
        "execution_policy_family": execution_policy_family,
        "symbol": symbol,
        "direction": direction,
        "scenario": scenario,
        "posterior_mean_net_bps": mean_net_bps,
        "lower_bound_net_bps": lower_bound_net_bps,
        "sample_count": sample_count,
        "mean_gross_bps": mean_gross_bps,
    }


def _base_negative_broad_scorecard() -> dict:
    # Broad (model, thesis, policy, scenario) aggregates are all unprofitable, so
    # without a narrow-slice override the readiness check must REFUSE.
    negative_row = {"model_id": "worker_signal_test", "completed": 200, "mean_net_bps": -5.0}
    return {
        "rows": [
            {**negative_row, "scenario": "normal"},
            {**negative_row, "scenario": "cost_1_5x"},
            {**negative_row, "scenario": "cost_2x"},
        ],
        "slice_execution_breakdown": [
            {"scenario": "normal", "completed": 200, "mean_net_bps": -5.0},
        ],
        "profitability_slice_posteriors": [],
        "execution_wiring_violations": 0,
        "real_orders_submitted": 0,
        "automatic_recoveries": 0,
    }


def test_compact_phase3_narrow_slice_with_too_few_samples_does_not_grant_allow():
    from strategies.volatility_breakout.current_truth import _compact_phase3_readiness

    scorecard = _base_negative_broad_scorecard()
    scorecard["profitability_slice_posteriors"] = [
        _narrow_posterior(scenario="normal", mean_net_bps=40.0, lower_bound_net_bps=30.0, sample_count=2, mean_gross_bps=60.0),
        _narrow_posterior(scenario="cost_1_5x", mean_net_bps=20.0, lower_bound_net_bps=10.0, sample_count=2, mean_gross_bps=60.0),
        _narrow_posterior(scenario="cost_2x", mean_net_bps=5.0, lower_bound_net_bps=0.0, sample_count=2, mean_gross_bps=60.0),
    ]

    readiness = _compact_phase3_readiness(scorecard)

    assert readiness["ready_for_phase4_review"] is False
    assert "no_positive_primary_execution_policy_at_normal_cost" in readiness["reasons"]
    assert readiness["primary_edge_source"] == "broad_execution_policy_mean"
    assert readiness["narrow_slices_rejected_insufficient_evidence"] > 0


def test_compact_phase3_narrow_slice_with_low_gross_edge_does_not_grant_allow():
    from strategies.volatility_breakout.current_truth import _compact_phase3_readiness

    scorecard = _base_negative_broad_scorecard()
    scorecard["profitability_slice_posteriors"] = [
        _narrow_posterior(scenario="normal", mean_net_bps=2.0, lower_bound_net_bps=0.5, sample_count=50, mean_gross_bps=3.0),
        _narrow_posterior(scenario="cost_1_5x", mean_net_bps=1.0, lower_bound_net_bps=0.2, sample_count=50, mean_gross_bps=3.0),
        _narrow_posterior(scenario="cost_2x", mean_net_bps=0.5, lower_bound_net_bps=0.0, sample_count=50, mean_gross_bps=3.0),
    ]

    readiness = _compact_phase3_readiness(scorecard)

    assert readiness["ready_for_phase4_review"] is False
    assert "no_positive_primary_execution_policy_at_normal_cost" in readiness["reasons"]
    assert readiness["narrow_slices_rejected_insufficient_evidence"] > 0


def test_compact_phase3_narrow_slice_with_adequate_samples_and_gross_edge_grants_allow():
    from strategies.volatility_breakout.current_truth import _compact_phase3_readiness

    scorecard = _base_negative_broad_scorecard()
    scorecard["profitability_slice_posteriors"] = [
        _narrow_posterior(scenario="normal", mean_net_bps=40.0, lower_bound_net_bps=30.0, sample_count=40, mean_gross_bps=60.0),
        _narrow_posterior(scenario="cost_1_5x", mean_net_bps=20.0, lower_bound_net_bps=10.0, sample_count=40, mean_gross_bps=60.0),
        _narrow_posterior(scenario="cost_2x", mean_net_bps=5.0, lower_bound_net_bps=0.0, sample_count=40, mean_gross_bps=60.0),
    ]

    readiness = _compact_phase3_readiness(scorecard)

    assert readiness["ready_for_phase4_review"] is True
    assert readiness["reasons"] == []
    assert readiness["primary_edge_source"] == "narrow_execution_slice_posterior"
    assert readiness["narrow_slices_rejected_insufficient_evidence"] == 0


def test_compact_phase3_small_window_proxy_grants_fast_track_allow():
    from strategies.volatility_breakout.current_truth import _compact_phase3_readiness

    scorecard = _base_negative_broad_scorecard()
    scorecard["rows"].append({
        "model_id": "small_window_trend_comparison_v1",
        "hypothesis": "recent_delta_volatility",
        "order_policy": "marketable_limit",
        "scenario": "normal",
        "completed": 1,
        "mean_net_bps": 42.0,
    })
    scorecard["slice_execution_breakdown"].append({
        "hypothesis": "recent_delta_volatility",
        "order_policy": "marketable_limit",
        "scenario": "normal",
        "completed": 1,
        "mean_net_bps": 42.0,
    })

    readiness = _compact_phase3_readiness(scorecard, min_completed=100)

    assert readiness["ready_for_phase4_review"] is True
    assert readiness["readiness_mode"] == "small_window_proxy_fast_track"
    assert readiness["primary_edge_source"] == "small_window_public_delta_proxy"
    assert readiness["reasons"] == []


def test_dio_phase2_accepts_small_window_recent_delta_gate_without_forecast_posterior(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "dio-small-window.db"))
    readiness = {
        "ready_for_phase3_review": True,
        "small_window_ready_for_phase3": True,
        "readiness_mode": "small_window_recent_delta_tape",
        "reasons": [],
    }
    scorecard = {
        "profitability_slice_posteriors": [],
        "small_window_tape": {
            "schema": "small_window_tape_evidence_v1",
            "opened": 1,
            "slices": [{"symbol": "CC/USD", "direction": "UP", "best_expected_net_bps": 80.0}],
        },
    }
    commons = {
        "adoption_receipts_accepted": 0,
        "adoption_receipts_proposal_only": 0,
    }

    gate = store.build_dio_gate_snapshot_from_evidence(2, readiness=readiness, scorecard=scorecard, commons=commons)

    assert gate["decision"] == "ALLOW"
    assert gate["reasons"] == []
    assert gate["predicates"]["positive_slice_posterior_present"] is True
    assert gate["predicates"]["small_window_recent_delta_slice_present"] is True


def test_dio_phase3_accepts_small_window_proxy_without_execution_posterior(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / "dio-small-window-phase3.db"))
    readiness = {
        "ready_for_phase4_review": True,
        "readiness_mode": "small_window_proxy_fast_track",
        "reasons": [],
    }
    scorecard = {
        "profitability_slice_posteriors": [],
        "coalition_slice_posteriors": [],
        "execution_wiring_violations": 0,
        "rows": [{
            "model_id": "small_window_trend_comparison_v1",
            "hypothesis": "recent_delta_volatility",
            "scenario": "normal",
            "completed": 1,
            "mean_net_bps": 42.0,
        }],
    }
    commons = {
        "adoption_receipts_accepted": 0,
        "adoption_receipts_proposal_only": 0,
    }

    gate = store.build_dio_gate_snapshot_from_evidence(3, readiness=readiness, scorecard=scorecard, commons=commons)

    assert gate["decision"] == "ALLOW"
    assert gate["reasons"] == []
    assert gate["predicates"]["positive_slice_posterior_present"] is True
    assert gate["predicates"]["small_window_execution_proxy_present"] is True
