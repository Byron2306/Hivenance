from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

from strategies.volatility_breakout.derivatives_trend_lab import run_derivatives_trend_lab
from strategies.volatility_breakout.hypothesis_competition import HypothesisCompetition
from strategies.volatility_breakout.models import FeatureVector, Forecast


def _cfg(**overrides) -> SimpleNamespace:
    base = dict(
        phase3_venue_economics_receipt="",
        derivatives_trend_symbols=["BTC/USD"],
        derivatives_trend_horizons_seconds=[86400],
        derivatives_trend_lookbacks_seconds=[3600],
        derivatives_trend_min_history_points=2,
        derivatives_trend_min_data_quality=0.99,
        derivatives_trend_max_spread_bps=40.0,
        derivatives_trend_min_momentum_bps=20.0,
        derivatives_trend_breakout_lookback_multiplier=1.0,
        derivatives_trend_min_vol_expansion_ratio=0.0,
        derivatives_trend_vol_baseline_multiplier=4.0,
        derivatives_trend_min_market_breadth=0.50,
        derivatives_trend_slippage_bps=2.0,
        derivatives_trend_cost_stress_multiplier=1.5,
        derivatives_trend_min_entries_per_slice=2,
        derivatives_trend_min_lower_bound_net_bps=5.0,
        derivatives_trend_post_only_fill_probability=0.75,
        derivatives_trend_funding_drag_bps_per_8h=1.0,
        derivatives_trend_max_concurrent_positions=1,
        derivatives_trend_maker_fee_bps=2.0,
        derivatives_trend_taker_fee_bps=5.0,
        derivatives_trend_allow_unverified_fees=False,
        derivatives_trend_phase2_model_enabled=True,
        derivatives_trend_ml_veto_enabled=True,
        derivatives_trend_ml_veto_max_failure_probability=0.50,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE observation_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            ts REAL,
            venue TEXT,
            symbol TEXT,
            price REAL,
            quote_volume_24h REAL,
            spread_bps REAL,
            depth_usd_25bps REAL,
            volatility_expansion REAL,
            volume_zscore REAL,
            book_imbalance REAL,
            data_quality REAL,
            observation_eligible INTEGER,
            execution_eligible INTEGER DEFAULT 0,
            rejection_reasons TEXT,
            payload TEXT
        )
        """
    )


def _insert_series(conn: sqlite3.Connection, symbol: str, prices: list[float], *, start_ts: float = 0.0, step: float = 3600.0) -> None:
    for idx, price in enumerate(prices):
        conn.execute(
            """
            INSERT INTO observation_snapshots
            (run_id, ts, venue, symbol, price, spread_bps, data_quality, payload)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            ("run", start_ts + idx * step, "kraken", symbol, price, 4.0, 1.0, json.dumps({})),
        )
    conn.commit()


def _monotonic_uptrend(n: int = 40, start: float = 100.0, step: float = 3.0) -> list[float]:
    return [start + step * idx for idx in range(n)]


def test_derivatives_trend_lab_refuses_unverified_fee_profile() -> None:
    conn = sqlite3.connect(":memory:")
    _schema(conn)
    _insert_series(conn, "BTC/USD", _monotonic_uptrend())

    summary = run_derivatives_trend_lab(conn, _cfg(), now_ts=1_800_000_000.0)

    assert summary["accepted_slice_count"] == 0
    assert summary["price_data_source"] == "kraken_spot_price_proxy_pending_futures_feed"
    assert summary["product"] == "perpetual_future"
    rows = conn.execute("SELECT accepted FROM derivatives_trend_receipts").fetchall()
    assert rows
    assert {row[0] for row in rows} == {0}


def test_derivatives_trend_lab_accepts_with_unverified_override() -> None:
    conn = sqlite3.connect(":memory:")
    _schema(conn)
    _insert_series(conn, "BTC/USD", _monotonic_uptrend(n=120))

    cfg = _cfg(derivatives_trend_allow_unverified_fees=True)
    summary = run_derivatives_trend_lab(conn, cfg, now_ts=1_800_000_000.0)

    assert summary["accepted_slice_count"] >= 1
    payloads = [
        json.loads(row[0])
        for row in conn.execute(
            "SELECT payload FROM derivatives_trend_receipts WHERE symbol='BTC/USD' AND policy='post_only_then_bounded_taker'"
        ).fetchall()
    ]
    up_payload = next(p for p in payloads if p["direction"] == "UP")
    down_payload = next(p for p in payloads if p["direction"] == "DOWN")
    assert up_payload["accepted"] is True
    assert up_payload["leverage"] == 1
    assert up_payload["execution_authority"] == "none"
    assert up_payload["price_data_source"] == "kraken_spot_price_proxy_pending_futures_feed"
    # A strictly monotonic uptrend has no qualifying negative-momentum entries.
    assert down_payload["entries"] == 0
    assert down_payload["accepted"] is False
    # De-overlap + chronological holdout must still be enforced, exactly like
    # the medium-horizon-trend lab.
    assert up_payload["raw_overlapping_entries"] >= up_payload["entries"]
    assert up_payload["train_entries"] + up_payload["holdout_entries"] == up_payload["entries"]
    assert up_payload["lower_bound_net_bps"] is not None
    assert up_payload["in_sample_lower_bound_net_bps"] is not None


def test_derivatives_trend_lab_volatility_expansion_gate_blocks_uniform_series() -> None:
    """A perfectly uniform-step uptrend has no volatility expansion (recent
    realized vol ~= baseline vol), so the default ratio gate must reject
    every candidate even though momentum and breakout both pass.
    """
    conn = sqlite3.connect(":memory:")
    _schema(conn)
    _insert_series(conn, "BTC/USD", _monotonic_uptrend(n=60, step=3.0))

    cfg = _cfg(
        derivatives_trend_allow_unverified_fees=True,
        derivatives_trend_min_vol_expansion_ratio=1.15,
    )
    summary = run_derivatives_trend_lab(conn, cfg, now_ts=1_800_000_000.0)

    assert summary["accepted_slice_count"] == 0
    payloads = [
        json.loads(row[0])
        for row in conn.execute(
            "SELECT payload FROM derivatives_trend_receipts WHERE symbol='BTC/USD' AND policy='post_only_then_bounded_taker'"
        ).fetchall()
    ]
    up_payload = next(p for p in payloads if p["direction"] == "UP")
    assert up_payload["entries"] == 0


def test_derivatives_trend_lab_market_breadth_gate_blocks_lone_dissenter() -> None:
    """With two tracked symbols, an UP candidate on BTC/USD must be rejected
    when its only peer (ETH/USD) is trending DOWN over the same lookback.
    """
    conn = sqlite3.connect(":memory:")
    _schema(conn)
    _insert_series(conn, "BTC/USD", _monotonic_uptrend(n=40, step=3.0))
    _insert_series(conn, "ETH/USD", [200.0 - 2.0 * idx for idx in range(40)])

    cfg = _cfg(
        derivatives_trend_symbols=["BTC/USD", "ETH/USD"],
        derivatives_trend_allow_unverified_fees=True,
        derivatives_trend_min_vol_expansion_ratio=0.0,
        derivatives_trend_min_market_breadth=0.50,
    )
    summary = run_derivatives_trend_lab(conn, cfg, now_ts=1_800_000_000.0)

    payloads = [
        json.loads(row[0])
        for row in conn.execute(
            "SELECT payload FROM derivatives_trend_receipts WHERE symbol='BTC/USD' AND policy='post_only_then_bounded_taker'"
        ).fetchall()
    ]
    up_payload = next(p for p in payloads if p["direction"] == "UP")
    # ETH/USD trends DOWN the whole time, so BTC/USD's UP candidates always
    # fail the >=50% market-breadth requirement (0 of 1 peers agree).
    assert up_payload["entries"] == 0
    assert summary["accepted_slice_count"] == 0


def _feature(**values_overrides) -> FeatureVector:
    return FeatureVector(
        symbol="BTC/USD",
        timestamp_ms=1_800_000_000_000,
        price=105.0,
        realized_volatility_fast=0.01,
        realized_volatility_baseline=0.008,
        volatility_expansion=1.2,
        volume_zscore=0.5,
        trade_count_zscore=0.0,
        order_flow_imbalance=0.0,
        book_imbalance=0.0,
        spread_bps=2.0,
        depth_usd_25bps=1_000_000.0,
        quote_volume_24h=100_000_000.0,
        return_5=0.01,
        freshness_sec=5.0,
        continuity_ratio=1.0,
        data_quality=1.0,
        complete=True,
        values=values_overrides,
    )


def test_derivatives_trend_model_emits_prospective_forecast() -> None:
    cfg = _cfg()
    competition = HypothesisCompetition(cfg)
    feature = _feature(
        derivatives_trend={
            "lookback_momentum_bps": 90.0,
            "accepted_slices": {
                "86400": {
                    "UP": {
                        "entries": 12,
                        "mean_net_bps": 150.0,
                        "lower_bound_net_bps": 120.0,
                        "policy": "post_only_then_bounded_taker",
                        "direction": "UP",
                        "receipt_id": "dtrend-test",
                    }
                }
            },
        }
    )

    forecasts = competition.evaluate_derivatives_trend(feature, [86400])

    assert len(forecasts) == 1
    forecast = forecasts[0]
    assert forecast.model_id == "derivatives_trend_v1"
    assert forecast.abstain is False
    assert forecast.direction == "UP"
    assert forecast.inputs["selected_receipt"]["receipt_id"] == "dtrend-test"
    assert forecast.inputs["leverage"] == 1


def test_derivatives_trend_model_abstains_without_accepted_slice() -> None:
    cfg = _cfg()
    competition = HypothesisCompetition(cfg)
    feature = _feature(derivatives_trend={"lookback_momentum_bps": 90.0, "accepted_slices": {}})

    forecasts = competition.evaluate_derivatives_trend(feature, [86400])

    assert len(forecasts) == 1
    assert forecasts[0].abstain is True
    assert "no_accepted_derivatives_trend_slice" in forecasts[0].reasons


class _FakeCoalitionModel:
    model_id = "worker_coalition_meta_v1"

    def __init__(self, forecast: Forecast) -> None:
        self._forecast = forecast

    def forecast(self, features: FeatureVector, *, horizon_seconds: int = 900) -> Forecast:
        return self._forecast


def _accepted_up_feature() -> FeatureVector:
    return _feature(
        derivatives_trend={
            "lookback_momentum_bps": 90.0,
            "accepted_slices": {
                "86400": {
                    "UP": {
                        "entries": 12,
                        "mean_net_bps": 150.0,
                        "lower_bound_net_bps": 120.0,
                        "policy": "post_only_then_bounded_taker",
                        "direction": "UP",
                        "receipt_id": "dtrend-test",
                    }
                }
            },
        }
    )


def test_ml_coalition_vetoes_opposing_direction() -> None:
    cfg = _cfg()
    competition = HypothesisCompetition(cfg)
    opposing = Forecast(
        symbol="BTC/USD",
        timestamp_ms=1_800_000_000_000,
        horizon_seconds=86400,
        direction="DOWN",
        probability_positive_net=0.65,
        abstain=False,
        model_id="worker_coalition_meta_v1",
        hypothesis="worker_coalition",
    )
    competition.worker_coalition_models = (_FakeCoalitionModel(opposing),)

    forecasts = competition.evaluate_derivatives_trend(_accepted_up_feature(), [86400])

    assert len(forecasts) == 1
    forecast = forecasts[0]
    assert forecast.abstain is True
    assert forecast.reason == "ml_coalition_veto"
    assert forecast.inputs["ml_coalition_forecast"]["direction"] == "DOWN"


def test_ml_coalition_vetoes_high_failure_probability() -> None:
    cfg = _cfg()
    competition = HypothesisCompetition(cfg)
    low_confidence = Forecast(
        symbol="BTC/USD",
        timestamp_ms=1_800_000_000_000,
        horizon_seconds=86400,
        direction="UP",
        probability_positive_net=0.30,
        abstain=False,
        model_id="worker_coalition_meta_v1",
        hypothesis="worker_coalition",
    )
    competition.worker_coalition_models = (_FakeCoalitionModel(low_confidence),)

    forecasts = competition.evaluate_derivatives_trend(_accepted_up_feature(), [86400])

    assert len(forecasts) == 1
    assert forecasts[0].abstain is True
    assert forecasts[0].reason == "ml_coalition_veto"


def test_ml_coalition_agreement_does_not_veto() -> None:
    cfg = _cfg()
    competition = HypothesisCompetition(cfg)
    agreeing = Forecast(
        symbol="BTC/USD",
        timestamp_ms=1_800_000_000_000,
        horizon_seconds=86400,
        direction="UP",
        probability_positive_net=0.70,
        abstain=False,
        model_id="worker_coalition_meta_v1",
        hypothesis="worker_coalition",
    )
    competition.worker_coalition_models = (_FakeCoalitionModel(agreeing),)

    forecasts = competition.evaluate_derivatives_trend(_accepted_up_feature(), [86400])

    assert len(forecasts) == 1
    assert forecasts[0].abstain is False
    assert forecasts[0].direction == "UP"


def test_ml_coalition_abstain_does_not_veto() -> None:
    cfg = _cfg()
    competition = HypothesisCompetition(cfg)
    coalition_abstain = Forecast(
        symbol="BTC/USD",
        timestamp_ms=1_800_000_000_000,
        horizon_seconds=86400,
        direction="ABSTAIN",
        abstain=True,
        model_id="worker_coalition_meta_v1",
        hypothesis="worker_coalition",
        reason="insufficient_worker_agreement",
    )
    competition.worker_coalition_models = (_FakeCoalitionModel(coalition_abstain),)

    forecasts = competition.evaluate_derivatives_trend(_accepted_up_feature(), [86400])

    assert len(forecasts) == 1
    assert forecasts[0].abstain is False
    assert forecasts[0].direction == "UP"


def test_derivatives_trend_venue_profile_never_reuses_spot_receipt(tmp_path) -> None:
    from strategies.volatility_breakout.venue_profiles import venue_profile

    receipt = tmp_path / "fee.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": "hivenance_kraken_fee_verification_receipt_v1",
                "fee_source": "kraken_private_trade_volume",
                "settings_updated": True,
                "pair": "ETH/USD",
                "maker_fee_bps": 1.0,
                "taker_fee_bps": 2.0,
            }
        ),
        encoding="utf-8",
    )
    cfg = _cfg(phase3_venue_economics_receipt=str(receipt))

    profile = venue_profile("kraken_futures", cfg)

    # A verified spot fee receipt must never be treated as verification for a
    # different product (derivatives). Futures fees stay a configured,
    # explicitly unverified research default.
    assert profile.fee_verified is False
    assert profile.fee_source == "configured_research_profile_unverified"
    assert profile.maker_fee_bps == 2.0
    assert profile.taker_fee_bps == 5.0
