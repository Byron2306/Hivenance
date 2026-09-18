from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from strategies.volatility_breakout.medium_horizon_trend_lab import ensure_schema, run_medium_horizon_trend_lab
from strategies.volatility_breakout.hypothesis_competition import HypothesisCompetition
from strategies.volatility_breakout.models import FeatureVector


def _cfg(receipt: Path | str = "") -> SimpleNamespace:
    return SimpleNamespace(
        phase3_venue_economics_receipt=str(receipt),
        phase3_maker_fee_bps=10.0,
        phase3_taker_fee_bps=20.0,
        medium_trend_symbols=["BTC/USD"],
        medium_trend_horizons_seconds=[3600],
        medium_trend_lookbacks_seconds=[3600],
        medium_trend_min_history_points=2,
        medium_trend_min_data_quality=0.99,
        medium_trend_max_spread_bps=40.0,
        medium_trend_min_momentum_bps=20.0,
        medium_trend_slippage_bps=2.0,
        medium_trend_cost_stress_multiplier=1.5,
        medium_trend_min_entries_per_slice=2,
        medium_trend_min_lower_bound_net_bps=5.0,
        medium_trend_allow_unverified_fees=False,
    )


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


def _insert_trend(conn: sqlite3.Connection) -> None:
    _schema(conn)
    price = 100.0
    for idx in range(10):
        price += 2.0
        conn.execute(
            """
            INSERT INTO observation_snapshots
            (run_id, ts, venue, symbol, price, spread_bps, data_quality, payload)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            ("run", float(idx * 3600), "kraken", "BTC/USD", price, 4.0, 1.0, json.dumps({})),
        )
    conn.commit()


def test_medium_horizon_trend_lab_accepts_verified_positive_slice(tmp_path: Path) -> None:
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
    conn = sqlite3.connect(":memory:")
    _insert_trend(conn)

    summary = run_medium_horizon_trend_lab(conn, _cfg(receipt), now_ts=1_800_000_000.0)

    assert summary["accepted_slice_count"] >= 1
    assert summary["fee_verified"] is True
    row = conn.execute("SELECT accepted, payload FROM medium_horizon_trend_receipts ORDER BY accepted DESC LIMIT 1").fetchone()
    assert row[0] == 1
    payload = json.loads(row[1])
    assert payload["execution_authority"] == "none"
    assert payload["fee_source"] == "kraken_private_trade_volume:ETH/USD"


def test_medium_horizon_trend_lab_refuses_unverified_fee_profile() -> None:
    conn = sqlite3.connect(":memory:")
    _insert_trend(conn)

    summary = run_medium_horizon_trend_lab(conn, _cfg(), now_ts=1_800_000_000.0)

    assert summary["accepted_slice_count"] == 0
    rows = conn.execute("SELECT accepted FROM medium_horizon_trend_receipts").fetchall()
    assert rows
    assert {row[0] for row in rows} == {0}


def test_medium_horizon_trend_model_emits_prospective_daily_forecast(tmp_path: Path) -> None:
    receipt = tmp_path / "fee.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": "hivenance_kraken_fee_verification_receipt_v1",
                "fee_source": "kraken_private_trade_volume",
                "settings_updated": True,
                "pair": "ETH/USD",
                "maker_fee_bps": 40.0,
                "taker_fee_bps": 80.0,
            }
        ),
        encoding="utf-8",
    )
    cfg = _cfg(receipt)
    cfg.medium_trend_phase2_model_enabled = True
    competition = HypothesisCompetition(cfg)
    feature = FeatureVector(
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
        values={
            "medium_horizon_trend": {
                "lookback_momentum_bps": 120.0,
                "accepted_slices": {
                    "86400": {
                        "UP": {
                            "entries": 21,
                            "mean_net_bps": 222.9,
                            "lower_bound_net_bps": 199.5,
                            "policy": "passive_post_only",
                            "direction": "UP",
                            "spot_executable": True,
                            "receipt_id": "mtrend-test",
                        }
                    }
                },
            }
        },
    )

    forecasts = competition.evaluate_medium_trend(feature, [86400])

    assert len(forecasts) == 1
    forecast = forecasts[0]
    assert forecast.model_id == "medium_horizon_trend_v1"
    assert forecast.abstain is False
    assert forecast.direction == "UP"
    assert forecast.expected_cost_bps and forecast.expected_cost_bps > 80.0
    assert forecast.inputs["selected_receipt"]["receipt_id"] == "mtrend-test"


def test_medium_horizon_trend_model_emits_down_forecast_for_negative_momentum(tmp_path: Path) -> None:
    receipt = tmp_path / "fee.json"
    receipt.write_text(
        json.dumps(
            {
                "schema": "hivenance_kraken_fee_verification_receipt_v1",
                "fee_source": "kraken_private_trade_volume",
                "settings_updated": True,
                "pair": "ETH/USD",
                "maker_fee_bps": 40.0,
                "taker_fee_bps": 80.0,
            }
        ),
        encoding="utf-8",
    )
    cfg = _cfg(receipt)
    cfg.medium_trend_phase2_model_enabled = True
    competition = HypothesisCompetition(cfg)
    feature = FeatureVector(
        symbol="BTC/USD",
        timestamp_ms=1_800_000_000_000,
        price=95.0,
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
        values={
            "medium_horizon_trend": {
                "lookback_momentum_bps": -120.0,
                "accepted_slices": {
                    "86400": {
                        "DOWN": {
                            "entries": 21,
                            "mean_net_bps": 180.0,
                            "lower_bound_net_bps": 150.0,
                            "policy": "passive_post_only",
                            "direction": "DOWN",
                            "spot_executable": False,
                            "receipt_id": "mtrend-test-down",
                        }
                    }
                },
            }
        },
    )

    forecasts = competition.evaluate_medium_trend(feature, [86400])

    assert len(forecasts) == 1
    forecast = forecasts[0]
    assert forecast.abstain is False
    assert forecast.direction == "DOWN"
    assert forecast.inputs["selected_receipt"]["receipt_id"] == "mtrend-test-down"


def test_medium_horizon_trend_lab_produces_nonoverlapping_holdout_gated_slices() -> None:
    conn = sqlite3.connect(":memory:")
    _schema(conn)
    price = 100.0
    # Hourly observations with a strong, steady uptrend so a 24h horizon and
    # 4h lookback would otherwise create many overlapping trade windows.
    for idx in range(80):
        price += 3.0
        conn.execute(
            """
            INSERT INTO observation_snapshots
            (run_id, ts, venue, symbol, price, spread_bps, data_quality, payload)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            ("run", float(idx * 3600), "kraken", "BTC/USD", price, 4.0, 1.0, json.dumps({})),
        )
    conn.commit()

    cfg = _cfg()
    cfg.medium_trend_horizons_seconds = [86400]
    cfg.medium_trend_lookbacks_seconds = [14400]
    cfg.medium_trend_min_history_points = 5
    cfg.medium_trend_min_entries_per_slice = 2
    cfg.medium_trend_allow_unverified_fees = True

    summary = run_medium_horizon_trend_lab(conn, cfg, now_ts=1_800_000_000.0)

    up_receipts = [
        row
        for row in conn.execute(
            "SELECT payload FROM medium_horizon_trend_receipts WHERE symbol='BTC/USD' AND policy='passive_post_only'"
        ).fetchall()
    ]
    payloads = [json.loads(row[0]) for row in up_receipts]
    up_payload = next(p for p in payloads if p["direction"] == "UP")
    down_payload = next(p for p in payloads if p["direction"] == "DOWN")

    # 80 hourly rows with a 24h horizon means a naive per-row scan would
    # produce dozens of overlapping trades; de-overlapping should collapse
    # that down to only a handful of independent, non-overlapping windows.
    assert up_payload["raw_overlapping_entries"] > up_payload["entries"]
    assert up_payload["entries"] <= 8
    assert up_payload["train_entries"] + up_payload["holdout_entries"] == up_payload["entries"]
    # The acceptance gate must be driven by the holdout (out-of-sample) lower
    # bound, not an in-sample statistic computed over the same data used to
    # discover the edge -- both figures must be reported for transparency.
    assert up_payload["train_entries"] > 0
    assert up_payload["holdout_entries"] < up_payload["entries"]
    assert up_payload["lower_bound_net_bps"] is not None
    assert up_payload["in_sample_lower_bound_net_bps"] is not None
    # A monotonic uptrend has no qualifying negative-momentum entries.
    assert down_payload["entries"] == 0
    assert down_payload["accepted"] is False
    assert down_payload["spot_executable"] is False
    assert up_payload["spot_executable"] is True
    assert summary["accepted_slice_count"] >= 1
