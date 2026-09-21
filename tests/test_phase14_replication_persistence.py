from strategies.relative_value_lab.phase14_scientific_gate import (
    independent_campaign_replication_summary,
    model_horizon_regime_persistence,
)


def test_replication_detects_sign_reversal_without_granting_authority():
    result=independent_campaign_replication_summary([
        {
            "campaign_id":"discovery",
            "fills":31,
            "distinct_symbols":15,
            "mean_gross_bps":87.0,
            "median_gross_bps":60.0,
            "mean_net_bps":32.0,
            "median_net_bps":10.0,
            "mean_excess_vs_random_bps":40.0,
            "largest_symbol_fraction":0.20,
        },
        {
            "campaign_id":"replication",
            "fills":30,
            "distinct_symbols":15,
            "mean_gross_bps":-95.0,
            "median_gross_bps":-99.0,
            "mean_net_bps":-149.0,
            "median_net_bps":-151.0,
            "mean_excess_vs_random_bps":-93.0,
            "largest_symbol_fraction":0.18,
        },
    ])
    assert result["classification"]=="REGIME_OR_TEMPORAL_INSTABILITY_DETECTED"
    assert result["sign_reversal"] is True
    assert result["authority_effect"]=="NONE_RESEARCH_ONLY"
    assert result["execution_eligible"] is False
    assert result["promotion_eligible"] is False


def test_incomplete_replication_is_not_promoted():
    result=independent_campaign_replication_summary([
        {
            "campaign_id":"replication",
            "fills":23,
            "distinct_symbols":15,
            "mean_net_bps":-149.718,
            "median_gross_bps":-99.268,
            "median_net_bps":-151.798,
            "mean_excess_vs_random_bps":-93.543,
            "largest_symbol_fraction":4/23,
        },
    ])
    assert result["classification"]=="INSUFFICIENT_INDEPENDENT_REPLICATION"
    assert result["sufficient_campaigns"]==0
    assert result["passing_campaigns"]==0


def test_repeated_support_requires_independently_sufficient_campaigns():
    good={
        "fills":35,
        "distinct_symbols":12,
        "mean_gross_bps":30.0,
        "median_gross_bps":20.0,
        "mean_net_bps":8.0,
        "median_net_bps":5.0,
        "mean_excess_vs_random_bps":12.0,
        "largest_symbol_fraction":0.20,
    }
    result=independent_campaign_replication_summary([
        dict(good,campaign_id="a"),
        dict(good,campaign_id="b"),
    ])
    assert result["classification"]=="REPEATED_PROSPECTIVE_SUPPORT"
    assert result["authority_effect"]=="NONE_RESEARCH_ONLY"


def test_model_horizon_regime_persistence_is_diagnostic_only():
    result=model_horizon_regime_persistence([
        {"model_id":"rsi","horizon_seconds":3600,"regime":"TREND","world_state_id":"w1","realized_net_bps":10},
        {"model_id":"rsi","horizon_seconds":3600,"regime":"TREND","world_state_id":"w2","realized_net_bps":-5},
        {"model_id":"rsi","horizon_seconds":900,"regime":"RANGE","world_state_id":"w3","realized_net_bps":3},
    ])
    assert result["post_hoc_activation_forbidden"] is True
    assert result["execution_eligible"] is False
    assert len(result["cells"])==2
    trend=[x for x in result["cells"] if x["horizon_seconds"]==3600][0]
    assert trend["distinct_worlds"]==2
    assert trend["authority_effect"]=="NONE_RESEARCH_ONLY"
