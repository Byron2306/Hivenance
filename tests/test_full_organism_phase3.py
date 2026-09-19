from __future__ import annotations

from dataclasses import replace

from strategies.relative_value_lab.full_comparison_packet import (
    build_full_comparison_packet,
    attach_full_comparison_packet,
    comparison_results_from_feature,
)
from strategies.volatility_breakout.models import FeatureVector


def _binding(root: str, temporal: dict) -> dict:
    return {
        "canonical_world_state_id": "ws_" + root[-8:],
        "canonical_world_state_hash": root,
        "feature_memory_line_id": root,
        "world_state_page": {
            "world_state_id": root,
            "temporal": temporal,
            "provenance": {"latest_1m_ts_ms": 0},
        },
    }


def _candidate(symbol: str, ts: int, root_char: str, *, selected: bool, score: float, conflict: bool) -> dict:
    root = "sha256:" + root_char * 64
    temporal = (
        {"15m_bps": 10, "1h_bps": 20, "24h_bps": 30, "7d_bps": -50, "30d_bps": -80, "365d_bps": -100}
        if conflict else
        {"15m_bps": 10, "1h_bps": 20, "24h_bps": 30, "7d_bps": 50, "30d_bps": 80, "365d_bps": 100}
    )
    fv = {
        "symbol": symbol,
        "timestamp_ms": ts,
        "volume_zscore": score,
        "volatility_expansion": 1.0 + score,
        "spread_bps": 2.0 + score,
        "book_imbalance": 0.1 * score,
        "return_zscore": score,
        "values": {},
    }
    return {
        "symbol": symbol,
        "timestamp_ms": ts,
        "volume_zscore": score,
        "volatility_expansion": 1.0 + score,
        "spread_bps": 2.0 + score,
        "selected_for_phase2": selected,
        "values": {
            "feature_vector": fv,
            "tradable_opportunity_score": score,
            "canonical_world_binding": _binding(root, temporal),
        },
    }


class Store:
    def __init__(self):
        prior_ts = 1_000_000
        current_ts = 2_000_000
        self.runs = [
            {
                "run_id": "current",
                "payload": {
                    "run": {"run_id": "current"},
                    "comparison_universe": [
                        _candidate("BTC/USD", current_ts, "a", selected=True, score=0.9, conflict=False),
                        _candidate("ETH/USD", current_ts, "b", selected=True, score=0.7, conflict=True),
                        _candidate("SOL/USD", current_ts, "c", selected=False, score=0.4, conflict=False),
                    ],
                },
            },
            {
                "run_id": "prior",
                "payload": {
                    "run": {"run_id": "prior"},
                    "comparison_universe": [
                        _candidate("BTC/USD", prior_ts, "d", selected=True, score=0.8, conflict=True),
                        _candidate("ETH/USD", prior_ts, "e", selected=False, score=0.3, conflict=False),
                        _candidate("SOL/USD", prior_ts, "f", selected=False, score=0.2, conflict=False),
                    ],
                },
            },
        ]

    def get_observation_runs(self, limit=250):
        return self.runs[:limit]


def _feature() -> FeatureVector:
    return FeatureVector(
        symbol="BTC/USD", timestamp_ms=2_000_000, price=100.0,
        realized_volatility_fast=.01, realized_volatility_baseline=.01,
        volatility_expansion=1.9, volume_zscore=.9,
        trade_count_zscore=None, order_flow_imbalance=None, book_imbalance=.09,
        spread_bps=2.9, depth_usd_25bps=100000.0, quote_volume_24h=10000000.0,
        return_5=.001, freshness_sec=0.0, continuity_ratio=1.0, data_quality=1.0,
        complete=True, return_zscore=.9,
        values={"tradable_opportunity_score": .9},
    )


def test_phase3_packet_composes_all_supported_comparison_families_pre_outcome():
    packet = build_full_comparison_packet(Store(), _feature())
    assert packet["comparison_types"] == [
        "SELF_SAME_UTC_HOUR",
        "CROSS_SECTION",
        "SELECTED_VS_REJECTED",
        "NEAREST_PRIOR_STATES",
        "EVENT_VS_CONTROL",
    ]
    results = {row["comparison_type"]: row for row in packet["results"]}
    assert results["CROSS_SECTION"]["matched_n"] == 2
    assert results["SELECTED_VS_REJECTED"]["matched_n"] == 3
    assert results["NEAREST_PRIOR_STATES"]["matched_n"] == 1
    assert results["EVENT_VS_CONTROL"]["matched_n"] == 3
    assert packet["execution_eligible"] is False
    assert packet["promotion_eligible"] is False


def test_phase3_selected_rejected_uses_only_prior_universe():
    packet = build_full_comparison_packet(Store(), _feature())
    row = next(x for x in packet["results"] if x["comparison_type"] == "SELECTED_VS_REJECTED")
    metric = row["metrics"]["tradable_opportunity_score"]
    assert metric["selected_n"] == 1
    assert metric["rejected_n"] == 2
    # Current-run rejected SOL must not leak into the prior comparison.
    assert row["matched_n"] == 3


def test_phase3_controls_are_declared_not_observed_evidence():
    packet = build_full_comparison_packet(Store(), _feature())
    for key in ("NO_TRADE", "DETERMINISTIC_RANDOM", "TIME_SHIFT_PLACEBO", "SIMPLE_NESTED_MODEL"):
        assert packet["control_declarations"][key]["status"] == "DECLARED_PROSPECTIVE_CONTROL"
        assert packet["control_declarations"][key]["authority"] == "CONTROL_ONLY"
    roots = {
        root
        for row in packet["results"]
        for root in row["evidence_roots"]
    }
    assert all(root.startswith("sha256:") for root in roots)


def test_phase3_feature_roundtrip_exposes_all_comparison_results_to_g0():
    enriched = attach_full_comparison_packet(_feature(), Store())
    results = comparison_results_from_feature(enriched)
    assert len(results) == 5
    assert results[0].comparison_type == "SELF_SAME_UTC_HOUR"
    assert all(r.execution_eligible is False and r.promotion_eligible is False for r in results)
