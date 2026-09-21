from strategies.relative_value_lab.phase14_replication_court import (
    ReplicationContract,
    evaluate_replication_campaign,
    paired_control_summary,
    persistence_summary,
)


def _row(i, net, cost=50.0, symbol=None):
    return {
        "timestamp_ms": 1_000_000 + i,
        "world_state_id": f"w{i}",
        "symbol": symbol or f"S{i % 12}",
        "horizon_seconds": 3600,
        "realized_net_bps": net,
        "realized_cost_bps": cost,
        "filled": True,
    }


def test_incomplete_campaign_cannot_pass_even_when_profitable():
    rows = [_row(i, 20.0) for i in range(23)]
    controls = [_row(i, -20.0) for i in range(23)]
    result = evaluate_replication_campaign(campaign_id="c1", rows=rows, control_rows=controls)
    assert result["classification"] == "REPLICATION_INCOMPLETE"
    assert result["criteria"]["minimum_fills"] is False
    assert result["execution_eligible"] is False
    assert result["promotion_eligible"] is False


def test_complete_adverse_campaign_fails():
    rows = [_row(i, -100.0) for i in range(36)]
    controls = [_row(i, -20.0) for i in range(36)]
    result = evaluate_replication_campaign(campaign_id="c2", rows=rows, control_rows=controls)
    assert result["classification"] == "REPLICATION_FAIL_ON_TESTED_DOMAIN"
    assert result["criteria"]["median_gross_positive"] is False
    assert result["criteria"]["median_net_positive"] is False
    assert result["criteria"]["mean_excess_vs_control_positive"] is False


def test_complete_positive_campaign_is_candidate_only():
    rows = [_row(i, 25.0, cost=10.0) for i in range(36)]
    controls = [_row(i, -10.0, cost=10.0) for i in range(36)]
    result = evaluate_replication_campaign(campaign_id="c3", rows=rows, control_rows=controls)
    assert result["classification"] == "REPLICATION_PASS_CANDIDATE_ONLY"
    assert result["execution_eligible"] is False
    assert result["promotion_eligible"] is False


def test_concentration_gate_blocks_single_symbol_dominance():
    rows = []
    controls = []
    for i in range(40):
        symbol = "DOM" if i < 20 else f"S{i}"
        rows.append(_row(i, 25.0, cost=10.0, symbol=symbol))
        controls.append(_row(i, -10.0, cost=10.0, symbol=symbol))
    result = evaluate_replication_campaign(campaign_id="c4", rows=rows, control_rows=controls)
    assert result["largest_symbol_fraction"] == 0.5
    assert result["criteria"]["symbol_concentration_within_limit"] is False
    assert result["classification"] == "REPLICATION_FAIL_ON_TESTED_DOMAIN"


def test_paired_control_requires_same_world_symbol_time_and_horizon():
    candidate = [_row(1, 10.0, cost=5.0)]
    control = [_row(1, -10.0, cost=5.0), _row(2, 999.0, cost=5.0)]
    result = paired_control_summary(candidate, control)
    assert result["paired_n"] == 1
    assert result["mean_excess_gross_bps"] == 20.0
    assert result["candidate_wins"] == 1


def test_mixed_independent_campaigns_are_dependence_candidate_not_authority():
    summary = persistence_summary([
        {"classification": "REPLICATION_PASS_CANDIDATE_ONLY"},
        {"classification": "REPLICATION_FAIL_ON_TESTED_DOMAIN"},
    ])
    assert summary["classification"] == "REGIME_OR_TEMPORAL_DEPENDENCE_CANDIDATE"
    assert summary["authority_effect"] == "NONE"
    assert summary["execution_eligible"] is False
    assert summary["promotion_eligible"] is False


def test_incomplete_campaign_does_not_count_toward_persistence():
    summary = persistence_summary([
        {"classification": "REPLICATION_PASS_CANDIDATE_ONLY"},
        {"classification": "REPLICATION_INCOMPLETE"},
    ])
    assert summary["classification"] == "INSUFFICIENT_INDEPENDENT_CAMPAIGNS"
    assert summary["campaigns_complete"] == 1
