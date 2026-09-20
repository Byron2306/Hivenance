from strategies.relative_value_lab.hypothesis_statistics_bridge import (
    bind_statistical_context,
    bind_statistical_contexts,
    statistical_hypothesis_gate,
)
from strategies.volatility_breakout.models import FeatureVector, Forecast


def feature():
    return FeatureVector(
        symbol="BTC/USD",
        timestamp_ms=1000,
        price=100.0,
        realized_volatility_fast=.01,
        realized_volatility_baseline=.01,
        volatility_expansion=1.0,
        volume_zscore=0.0,
        trade_count_zscore=None,
        order_flow_imbalance=None,
        book_imbalance=0.0,
        spread_bps=2.0,
        depth_usd_25bps=1_000_000.0,
        quote_volume_24h=100_000_000.0,
        return_5=.001,
        freshness_sec=0.0,
        continuity_ratio=1.0,
        data_quality=1.0,
        values={},
        complete=True,
    )


def forecast():
    return Forecast(
        symbol="BTC/USD",
        timestamp_ms=1000,
        horizon_seconds=60,
        direction="UP",
        probability_positive_net=.6,
        expected_move_bps=12.0,
        expected_cost_bps=4.0,
        expected_net_bps=8.0,
        abstain=False,
        reason="candidate",
        model_id="m1",
        hypothesis="h1",
        reasons=(),
        inputs={},
        execution_eligible=False,
    )


def test_statistical_context_binds_before_hypothesis_without_authority():
    f=bind_statistical_context(
        feature(),
        {
            "state_id":"s1",
            "as_of_ms":900,
            "hierarchical_win_probability":.62,
            "hierarchical_edge_positive_probability":.66,
            "uncertainty":.2,
            "change_point_probability":.1,
            "effective_sample_size":20,
        },
    )
    ctx=f.values["phase2_statistical_hypothesis_context"]
    assert ctx["state_id"]=="s1"
    assert ctx["authority"]=="RESEARCH_CONTEXT_ONLY"
    assert ctx["execution_eligible"] is False


def test_high_uncertainty_is_context_only_not_independent_veto():
    f=bind_statistical_context(
        feature(),
        {
            "state_id":"s2",
            "as_of_ms":900,
            "hierarchical_win_probability":.8,
            "hierarchical_edge_positive_probability":.9,
            "uncertainty":.95,
            "change_point_probability":.1,
            "effective_sample_size":50,
        },
    )
    out=statistical_hypothesis_gate(forecast(),f)
    assert out.abstain is False
    assert out.direction=="UP"
    assert out.inputs["statistical_hypothesis_context"]["uncertainty"]==.95
    assert out.execution_eligible is False


def test_strong_positive_statistics_only_annotate_currently():
    f=bind_statistical_context(
        feature(),
        {
            "state_id":"s3",
            "as_of_ms":900,
            "hierarchical_win_probability":.85,
            "hierarchical_edge_positive_probability":.9,
            "uncertainty":.1,
            "change_point_probability":.05,
            "effective_sample_size":100,
        },
    )
    original=forecast()
    out=statistical_hypothesis_gate(original,f)
    assert out.abstain is False
    assert out.direction==original.direction
    assert out.probability_positive_net==original.probability_positive_net
    assert "statistical_hypothesis_context" in out.inputs


def test_negative_edge_probability_requires_sample_depth_before_veto():
    shallow=bind_statistical_context(
        feature(),
        {
            "state_id":"s4",
            "as_of_ms":900,
            "hierarchical_win_probability":.3,
            "hierarchical_edge_positive_probability":.1,
            "uncertainty":.2,
            "change_point_probability":.1,
            "effective_sample_size":1,
        },
    )
    assert statistical_hypothesis_gate(forecast(),shallow).abstain is False

    deep=bind_statistical_context(
        feature(),
        {
            "state_id":"s5",
            "as_of_ms":900,
            "hierarchical_win_probability":.3,
            "hierarchical_edge_positive_probability":.1,
            "uncertainty":.2,
            "change_point_probability":.1,
            "effective_sample_size":12,
        },
    )
    out=statistical_hypothesis_gate(forecast(),deep)
    assert out.abstain is True
    assert out.reason=="statistical_synthesis_negative_edge_veto"



def test_model_specific_statistics_do_not_cross_contaminate_forecasts():
    f=bind_statistical_contexts(
        feature(),
        {
            "m1":{
                "state_id":"m1s",
                "as_of_ms":900,
                "hierarchical_win_probability":.2,
                "hierarchical_edge_positive_probability":.1,
                "uncertainty":.2,
                "change_point_probability":.1,
                "effective_sample_size":20,
            },
            "m2":{
                "state_id":"m2s",
                "as_of_ms":900,
                "hierarchical_win_probability":.8,
                "hierarchical_edge_positive_probability":.9,
                "uncertainty":.1,
                "change_point_probability":.05,
                "effective_sample_size":20,
            },
        },
    )
    m1=forecast()
    m2=Forecast(**{**m1.__dict__,"model_id":"m2"})
    out1=statistical_hypothesis_gate(m1,f)
    out2=statistical_hypothesis_gate(m2,f)
    assert out1.abstain is True
    assert out1.reason=="statistical_synthesis_negative_edge_veto"
    assert out2.abstain is False
    assert out2.inputs["statistical_hypothesis_context"]["state_id"]=="m2s"



def test_change_point_remains_secondary_veto():
    f=bind_statistical_context(
        feature(),
        {
            "state_id":"s-change",
            "as_of_ms":900,
            "hierarchical_win_probability":.55,
            "hierarchical_edge_positive_probability":.8,
            "uncertainty":.1,
            "change_point_probability":.95,
            "effective_sample_size":20,
        },
    )
    out=statistical_hypothesis_gate(forecast(),f)
    assert out.abstain is True
    assert out.reason=="statistical_synthesis_change_point_veto"


def test_negative_edge_precedes_change_point_when_both_fire():
    f=bind_statistical_context(
        feature(),
        {
            "state_id":"s-both",
            "as_of_ms":900,
            "hierarchical_win_probability":.2,
            "hierarchical_edge_positive_probability":.1,
            "uncertainty":.1,
            "change_point_probability":.95,
            "effective_sample_size":20,
        },
    )
    out=statistical_hypothesis_gate(forecast(),f)
    assert out.abstain is True
    assert out.reason=="statistical_synthesis_negative_edge_veto"
