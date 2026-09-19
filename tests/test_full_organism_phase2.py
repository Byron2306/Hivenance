from __future__ import annotations

from dataclasses import asdict, replace

from strategies.relative_value_lab.temporal_lattice import build_temporal_lattice, attach_temporal_lattice
from strategies.relative_value_lab.g0_live_evidence import horizon_from_feature
from strategies.volatility_breakout.models import FeatureVector


def _feature() -> FeatureVector:
    binding = {
        "canonical_world_state_id": "ws_test",
        "canonical_world_state_hash": "sha256:" + "a" * 64,
        "feature_memory_line_id": "sha256:" + "b" * 64,
        "world_state_page": {
            "world_state_id": "sha256:" + "c" * 64,
            "temporal": {
                "15m_bps": -8.0,
                "1h_bps": -15.0,
                "4h_bps": -28.0,
                "24h_bps": -80.0,
                "7d_bps": 120.0,
                "30d_bps": 450.0,
                "365d_bps": 1800.0,
            },
            "horizon": {
                "micro": {"return_10s_bps": None, "return_30s_bps": None},
                "meso": {"return_2m_bps": 6.0, "return_5m_bps": 10.0},
                "macro": {"return_15m_bps": -8.0, "return_1h_bps": -15.0, "return_24h_bps": -80.0},
            },
            "provenance": {"latest_1m_ts_ms": 1000000},
        },
    }
    oracle = {
        "source": "phase1_observation_snapshots",
        "horizons": {
            "1h": {"available": True, "change_bps": -14.0, "age_error_sec": 20.0},
            "5h": {"available": True, "change_bps": -31.0, "age_error_sec": 40.0},
            "24h": {"available": True, "change_bps": -77.0, "age_error_sec": 100.0},
            "7d": {"available": True, "change_bps": 118.0, "age_error_sec": 300.0},
            "30d": {"available": False, "reason": "insufficient_history"},
        },
    }
    return FeatureVector(
        symbol="BTC/USD", timestamp_ms=1000000, price=100.0,
        realized_volatility_fast=.01, realized_volatility_baseline=.01,
        volatility_expansion=1.0, volume_zscore=0.0, trade_count_zscore=None,
        order_flow_imbalance=None, book_imbalance=.1, spread_bps=2.0,
        depth_usd_25bps=100000.0, quote_volume_24h=10000000.0,
        return_5=.001, freshness_sec=0.0, continuity_ratio=1.0,
        data_quality=1.0, complete=True,
        values={
            "canonical_world_binding": binding,
            "cex_market_oracle": oracle,
        },
    )


def test_phase2_lattice_preserves_short_long_conflict_and_missingness():
    lattice = build_temporal_lattice(feature=_feature())
    assert lattice is not None
    assert lattice.micro["2m"]["change_bps"] == 6.0
    assert lattice.micro["5m"]["change_bps"] == 10.0
    assert lattice.meso["24h"]["change_bps"] == -80.0
    assert lattice.macro["365d"]["change_bps"] == 1800.0
    assert lattice.oracle["30d"]["status"] == "MISSING"
    assert lattice.conflict["micro_bias"] == "UP"
    assert lattice.conflict["meso_bias"] == "DOWN"
    assert lattice.conflict["macro_bias"] == "UP"
    assert lattice.conflict["micro_vs_meso"] == "CONFLICT"
    assert lattice.conflict["meso_vs_macro"] == "CONFLICT"


def test_phase2_same_price_history_transforms_do_not_fake_independence():
    lattice = build_temporal_lattice(feature=_feature())
    assert lattice is not None
    roots = {
        row["evidence_root"]
        for group in (lattice.micro, lattice.meso, lattice.macro, lattice.oracle)
        for row in group.values()
        if row["status"] == "PRESENT"
    }
    assert roots == {"sha256:" + "b" * 64}
    lineage = lattice.provenance["lineage_groups"]["PUBLIC_PRICE_HISTORY"]
    assert lineage["independent_evidence_roots"] == 1


def test_phase2_g0_horizon_consumes_long_context_instead_of_truncating_it():
    feature = attach_temporal_lattice(_feature())
    horizon = horizon_from_feature(feature)
    assert horizon is not None
    assert horizon.macro["return_7d_bps"] == 120.0
    assert horizon.macro["return_30d_bps"] == 450.0
    assert horizon.macro["return_365d_bps"] == 1800.0
    assert horizon.macro["oracle_5h_bps"] == -31.0
    assert horizon.macro["oracle_7d_bps"] == 118.0
    assert horizon.macro["temporal_conflict"]["meso_vs_macro"] == "CONFLICT"
    assert horizon.readiness["macro_365d"] is True
    assert horizon.readiness["oracle_30d"] is False


def test_phase2_lattice_keeps_unavailable_micro_horizons_explicit():
    lattice = build_temporal_lattice(feature=_feature())
    assert lattice is not None
    assert lattice.micro["10s"]["status"] == "MISSING"
    assert lattice.micro["30s"]["status"] == "MISSING"
    assert lattice.micro["10s"]["change_bps"] is None
    assert lattice.micro["30s"]["change_bps"] is None
