import pytest

from strategies.relative_value_lab.external_statistics import (
    CORE_EXTERNAL_METRICS,
    ExternalStatisticsSensorium,
)


def test_external_sensorium_binds_source_and_refuses_future_visibility():
    s=ExternalStatisticsSensorium()
    row=s.observe(
        metric="ETF_NET_FLOW_USD",
        provider="test-provider",
        symbol_scope="BTC",
        observed_at_ms=10,
        available_at_ms=20,
        value=100.0,
        unit="USD",
        source_locator="provider://snapshot/1",
        source_bytes_or_value={"flow":100.0},
        revision_policy="POINT_IN_TIME_CAPTURED",
    )
    assert row.source_digest.startswith("sha256:")
    assert s.feature(metric="ETF_NET_FLOW_USD",symbol_scope="BTC",as_of_ms=20) is None
    assert s.feature(metric="ETF_NET_FLOW_USD",symbol_scope="BTC",as_of_ms=21) is not None


def test_external_sensorium_computes_delta_zscore_percentile_and_ratio():
    s=ExternalStatisticsSensorium()
    for i,value in enumerate((100.0,110.0,120.0,180.0)):
        s.observe(
            metric="FUTURES_OPEN_INTEREST_USD",
            provider="p",
            symbol_scope="BTC",
            observed_at_ms=10+i*10,
            available_at_ms=11+i*10,
            value=value,
            unit="USD",
            source_locator=f"p://oi/{i}",
            source_bytes_or_value=value,
            revision_policy="POINT_IN_TIME_CAPTURED",
        )
        s.observe(
            metric="SPOT_VOLUME_USD",
            provider="p",
            symbol_scope="BTC",
            observed_at_ms=10+i*10,
            available_at_ms=11+i*10,
            value=90.0,
            unit="USD",
            source_locator=f"p://vol/{i}",
            source_bytes_or_value=90.0,
            revision_policy="POINT_IN_TIME_CAPTURED",
        )

    f=s.feature(
        metric="FUTURES_OPEN_INTEREST_USD",
        ratio_metric="SPOT_VOLUME_USD",
        symbol_scope="BTC",
        as_of_ms=100,
    )
    assert f is not None
    assert f.delta==60.0
    assert f.zscore is not None and f.zscore>0
    assert f.percentile==1.0
    assert f.ratio==2.0
    assert f.ratio_name=="FUTURES_OPEN_INTEREST_USD/SPOT_VOLUME_USD"


def test_external_feature_adapts_into_statistics_bee_contract():
    s=ExternalStatisticsSensorium()
    s.observe(
        metric="FUNDING_RATE",
        provider="p",
        symbol_scope="BTC",
        observed_at_ms=10,
        available_at_ms=11,
        value=.0001,
        unit="ratio",
        source_locator="p://funding/1",
        source_bytes_or_value=.0001,
        revision_policy="POINT_IN_TIME_CAPTURED",
    )
    s.observe(
        metric="FUNDING_RATE",
        provider="p",
        symbol_scope="BTC",
        observed_at_ms=20,
        available_at_ms=21,
        value=.0003,
        unit="ratio",
        source_locator="p://funding/2",
        source_bytes_or_value=.0003,
        revision_policy="POINT_IN_TIME_CAPTURED",
    )
    feature=s.feature(metric="FUNDING_RATE",symbol_scope="BTC",as_of_ms=30)
    evidence=s.to_statistical_evidence(
        feature=feature,
        scope="external|BTC|funding",
        transform="DELTA",
    )
    assert evidence.scope=="external|BTC|funding"
    assert evidence.positive is True
    assert evidence.evidence_root.startswith("sha256:")


def test_external_sensorium_refuses_missing_ratio_and_unknown_transform():
    s=ExternalStatisticsSensorium()
    s.observe(
        metric="ETF_NET_FLOW_USD",
        provider="p",
        symbol_scope="BTC",
        observed_at_ms=10,
        available_at_ms=11,
        value=10,
        unit="USD",
        source_locator="p://x",
        source_bytes_or_value=10,
    )
    feature=s.feature(metric="ETF_NET_FLOW_USD",symbol_scope="BTC",as_of_ms=20)
    with pytest.raises(ValueError,match="ratio_missing"):
        s.to_statistical_evidence(feature=feature,scope="x",transform="RATIO_MINUS_ONE")
    with pytest.raises(ValueError,match="transform_unknown"):
        s.to_statistical_evidence(feature=feature,scope="x",transform="MAGIC")


def test_core_external_metric_family_is_locked():
    assert {
        "ETF_NET_FLOW_USD",
        "SPOT_CVD_USD",
        "FUTURES_OPEN_INTEREST_USD",
        "STABLECOIN_EXCHANGE_RESERVE_USD",
        "OPTIONS_25D_SKEW",
        "MACRO_POLICY_PROBABILITY",
    }.issubset(set(CORE_EXTERNAL_METRICS))
