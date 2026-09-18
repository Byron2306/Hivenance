from __future__ import annotations

import json
from types import SimpleNamespace

from agents.data_store_agent import DataStoreAgent
from strategies.volatility_breakout.rapid_paper_tape import RapidPaperTape


def cfg(**overrides) -> SimpleNamespace:
    base = dict(
        phase2_rapid_paper_notional_usd=5.0,
        phase2_rapid_paper_max_open_trades=4,
        phase2_rapid_paper_min_expected_net_bps=-5.0,
        phase2_rapid_paper_min_probability=0.45,
        phase2_rapid_paper_max_forecast_age_sec=300,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def insert_forecast(
    store: DataStoreAgent,
    *,
    forecast_id: str = "forecast-1",
    now: float = 1_000.0,
    symbol: str = "ETH/USD",
    model_id: str = "breakout_continuation_v1",
    hypothesis: str = "breakout_continuation",
    horizon_seconds: int = 300,
    direction: str = "UP",
    expected_net_bps: float = 12.0,
    probability_positive_net: float = 0.61,
) -> None:
    with store._lock:
        store.conn.execute(
            """
            INSERT INTO hypothesis_forecasts
            (forecast_id, run_id, observation_run_id, ts, target_ts, venue, symbol, model_id,
             hypothesis, horizon_seconds, direction, entry_price, probability_positive_net,
             expected_move_bps, expected_cost_bps, expected_net_bps, raw_score, abstain,
             reason, settled, execution_eligible, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                forecast_id,
                "run-1",
                f"obs-{forecast_id}",
                now - 5.0,
                now + 300.0,
                "kraken",
                symbol,
                model_id,
                hypothesis,
                horizon_seconds,
                direction,
                100.0,
                probability_positive_net,
                20.0,
                8.0,
                expected_net_bps,
                0.8,
                0,
                "test forecast",
                0,
                0,
                json.dumps({"forecast_id": forecast_id, "symbol": symbol}),
            ),
        )
        store.conn.execute(
            """
            INSERT INTO observation_snapshots
            (run_id, ts, venue, symbol, price, quote_volume_24h, spread_bps, depth_usd_25bps,
             volatility_expansion, volume_zscore, book_imbalance, data_quality,
             observation_eligible, execution_eligible, rejection_reasons, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"obs-{forecast_id}",
                now - 5.0,
                "kraken",
                symbol,
                100.0,
                100_000_000.0,
                4.0,
                500_000.0,
                1.4,
                1.2,
                0.1,
                1.0,
                1,
                0,
                "[]",
                "{}",
            ),
        )
        store.conn.commit()


def test_rapid_paper_tape_opens_and_closes_from_settled_forecast() -> None:
    now = [1_000.0]
    store = DataStoreAgent(":memory:")
    insert_forecast(store, now=now[0])
    tape = RapidPaperTape(cfg(), store, now_fn=lambda: now[0])

    opened = tape.open_from_recent_forecasts(limit=10)
    assert opened["opened"] == 1
    assert tape.scorecard()["open"] == 1

    with store._lock:
        store.conn.execute(
            """
            INSERT INTO hypothesis_outcomes
            (forecast_id, settled_ts, exit_price, gross_return_bps, directional_return_bps,
             net_return_bps, positive_net, brier_score, absolute_error_bps, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            ("forecast-1", now[0] + 301.0, 101.0, 100.0, 100.0, 92.0, 1, 0.1, 80.0, "{}"),
        )
        store.conn.commit()

    closed = tape.close_settled()
    assert closed["closed"] == 1
    score = tape.scorecard()
    assert score["closed"] == 1
    assert score["wins"] == 1
    assert score["total_net_bps"] == 92.0
    assert store.conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0] == 1


class VetoCritic:
    hard_veto = True

    def review(self, forecast, *, recent_context):
        return {"status": "REVIEWED", "veto": True, "risks": ["weak_thesis"], "authority": "paper_annotation_only"}


def test_rapid_paper_tape_llm_hard_veto_records_no_open_trade() -> None:
    now = [2_000.0]
    store = DataStoreAgent(":memory:")
    insert_forecast(store, forecast_id="forecast-veto", now=now[0])
    tape = RapidPaperTape(cfg(), store, critic=VetoCritic(), now_fn=lambda: now[0])

    opened = tape.open_from_recent_forecasts(limit=10)
    assert opened["vetoed"] == 1
    score = tape.scorecard()
    assert score["open"] == 0
    assert score["vetoed"] == 1


def test_rapid_paper_tape_direct_settlement_ignores_global_backlog() -> None:
    now = [3_000.0]
    store = DataStoreAgent(":memory:")
    insert_forecast(store, forecast_id="forecast-direct", now=now[0])
    tape = RapidPaperTape(cfg(), store, now_fn=lambda: now[0])
    assert tape.open_from_recent_forecasts(limit=10)["opened"] == 1

    now[0] += 301.0
    with store._lock:
        store.conn.execute(
            """
            INSERT INTO observation_snapshots
            (run_id, ts, venue, symbol, price, quote_volume_24h, spread_bps, depth_usd_25bps,
             volatility_expansion, volume_zscore, book_imbalance, data_quality,
             observation_eligible, execution_eligible, rejection_reasons, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "obs-direct-exit",
                now[0],
                "kraken",
                "ETH/USD",
                101.0,
                100_000_000.0,
                4.0,
                500_000.0,
                1.4,
                1.2,
                0.1,
                1.0,
                1,
                0,
                "[]",
                "{}",
            ),
        )
        store.conn.commit()

    direct = tape.settle_due_open_trades(tolerance_sec=900.0)
    assert direct["closed"] == 1
    score = tape.scorecard()
    assert score["closed"] == 1
    assert score["wins"] == 1
    assert store.conn.execute("SELECT COUNT(*) FROM hypothesis_outcomes").fetchone()[0] == 0


def test_rapid_paper_tape_negative_direct_settlement_mints_memory_crystal() -> None:
    now = [4_000.0]
    store = DataStoreAgent(":memory:")
    insert_forecast(store, forecast_id="forecast-direct-loss", now=now[0])
    tape = RapidPaperTape(cfg(), store, now_fn=lambda: now[0])
    assert tape.open_from_recent_forecasts(limit=10)["opened"] == 1

    now[0] += 301.0
    with store._lock:
        store.conn.execute(
            """
            INSERT INTO observation_snapshots
            (run_id, ts, venue, symbol, price, quote_volume_24h, spread_bps, depth_usd_25bps,
             volatility_expansion, volume_zscore, book_imbalance, data_quality,
             observation_eligible, execution_eligible, rejection_reasons, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "obs-direct-loss",
                now[0],
                "kraken",
                "ETH/USD",
                99.0,
                100_000_000.0,
                4.0,
                500_000.0,
                1.4,
                1.2,
                0.1,
                1.0,
                1,
                0,
                "[]",
                "{}",
            ),
        )
        store.conn.commit()

    direct = tape.settle_due_open_trades(tolerance_sec=900.0)
    assert direct["closed"] == 1
    assert tape.scorecard()["losses"] == 1
    row = store.conn.execute(
        "SELECT crystal_family, phase_scope, payload FROM crystal_registry LIMIT 1"
    ).fetchone()
    assert row[0] == "negative_capability"
    assert row[1] == 2
    assert "rapid_paper_negative_net" in row[2]


def test_rapid_paper_tape_expires_stale_open_without_observation() -> None:
    now = [5_000.0]
    store = DataStoreAgent(":memory:")
    insert_forecast(store, forecast_id="forecast-expire", now=now[0])
    tape = RapidPaperTape(cfg(), store, now_fn=lambda: now[0])
    assert tape.open_from_recent_forecasts(limit=10)["opened"] == 1

    now[0] += 1_301.0
    expired = tape.expire_stale_open_trades(tolerance_sec=900.0)
    assert expired["expired"] == 1
    score = tape.scorecard()
    statuses = {row["status"] for row in score["recent"]}
    assert "EXPIRED_NO_OBSERVATION" in statuses
    assert score["open"] == 0


def test_rapid_paper_tape_skips_symbol_under_data_gap_cooldown() -> None:
    now = [6_000.0]
    store = DataStoreAgent(":memory:")
    insert_forecast(store, forecast_id="forecast-gap-1", now=now[0])
    tape = RapidPaperTape(cfg(), store, now_fn=lambda: now[0])
    assert tape.open_from_recent_forecasts(limit=10)["opened"] == 1
    now[0] += 1_301.0
    assert tape.expire_stale_open_trades(tolerance_sec=900.0)["expired"] == 1

    insert_forecast(store, forecast_id="forecast-gap-2", now=now[0])
    result = tape.open_from_recent_forecasts(limit=10)
    assert result["opened"] == 0
    assert result["skipped"] >= 1
    assert tape.scorecard()["open"] == 0


def test_high_vol_rapid_paper_can_use_short_reentry_cooldowns() -> None:
    now = [6_000.0]
    store = DataStoreAgent(":memory:")
    insert_forecast(store, forecast_id="forecast-short-gap-1", now=now[0])
    tape = RapidPaperTape(
        cfg(
            profile_name="high_vol_low_stakes",
            phase2_rapid_paper_min_cooldown_sec=1,
            phase2_rapid_paper_data_gap_cooldown_sec=5,
            phase2_rapid_paper_loss_cooldown_sec=5,
        ),
        store,
        now_fn=lambda: now[0],
    )
    assert tape.data_gap_cooldown_sec == 5
    assert tape.open_from_recent_forecasts(limit=10)["opened"] == 1
    now[0] += 1_301.0
    assert tape.expire_stale_open_trades(tolerance_sec=900.0)["expired"] == 1

    now[0] += 6.0
    insert_forecast(store, forecast_id="forecast-short-gap-2", now=now[0])
    result = tape.open_from_recent_forecasts(limit=10)

    assert result["opened"] == 1
    assert result["skipped_data_gap"] == 0


def test_rapid_paper_tape_blocks_duplicate_open_symbol_model_direction() -> None:
    now = [7_000.0]
    store = DataStoreAgent(":memory:")
    insert_forecast(store, forecast_id="forecast-dup-1", now=now[0])
    insert_forecast(store, forecast_id="forecast-dup-2", now=now[0])
    tape = RapidPaperTape(cfg(), store, now_fn=lambda: now[0])

    result = tape.open_from_recent_forecasts(limit=10)
    assert result["opened"] == 1
    assert result["skipped_duplicate_open"] == 1
    assert tape.scorecard()["open"] == 1


def test_rapid_paper_tape_respects_max_open_per_symbol() -> None:
    now = [7_500.0]
    store = DataStoreAgent(":memory:")
    insert_forecast(
        store,
        forecast_id="forecast-symbol-cap-1",
        now=now[0],
        symbol="NPC/USD",
        model_id="model-a",
        direction="DOWN",
    )
    insert_forecast(
        store,
        forecast_id="forecast-symbol-cap-2",
        now=now[0],
        symbol="NPC/USD",
        model_id="model-b",
        direction="DOWN",
    )
    tape = RapidPaperTape(
        cfg(phase2_rapid_paper_max_open_per_symbol=1, phase2_rapid_paper_allowed_directions=["UP", "DOWN"]),
        store,
        now_fn=lambda: now[0],
    )

    result = tape.open_from_recent_forecasts(limit=10)

    assert result["opened"] == 1
    assert result["skipped_symbol_cap"] == 1
    assert tape.scorecard()["open"] == 1


def test_rapid_paper_tape_opens_from_small_window_trend_comparison() -> None:
    now = [12_000.0]
    store = DataStoreAgent(":memory:")
    with store._lock:
        for ts, price in ((now[0] - 900.0, 1.00), (now[0], 0.98)):
            store.conn.execute(
                """
                INSERT INTO observation_snapshots
                (run_id, ts, venue, symbol, price, quote_volume_24h, spread_bps, depth_usd_25bps,
                 volatility_expansion, volume_zscore, book_imbalance, data_quality,
                 observation_eligible, execution_eligible, rejection_reasons, payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    f"obs-trend-{ts}",
                    ts,
                    "kraken",
                    "CC/USD",
                    price,
                    1_000_000.0,
                    5.0,
                    100_000.0,
                    1.8,
                    1.0,
                    0.0,
                    1.0,
                    1,
                    0,
                    "[]",
                    "{}",
                ),
            )
        store.conn.commit()
    tape = RapidPaperTape(
        cfg(
            phase2_taker_fee_bps_per_side=10.0,
            phase2_latency_buffer_bps=0.0,
            phase2_small_window_trend_min_abs_move_bps=25.0,
            phase2_small_window_trend_min_net_bps=5.0,
        ),
        store,
        now_fn=lambda: now[0],
    )

    result = tape.open_from_trend_comparisons(limit=3, window_sec=900, hold_sec=300, max_age_sec=1200)

    assert result["opened"] == 1
    opened = result["opened_candidates"][0]
    assert opened["symbol"] == "CC/USD"
    assert opened["direction"] == "DOWN"
    row = store.conn.execute(
        "SELECT model_id, hypothesis, direction, status FROM rapid_paper_tape_trades"
    ).fetchone()
    assert row == (
        "small_window_trend_comparison_v1",
        "recent_delta_volatility",
        "DOWN",
        "OPEN",
    )


def test_rapid_paper_tape_selects_route_policy_for_small_window_costs() -> None:
    now = [15_000.0]
    store = DataStoreAgent(":memory:")
    with store._lock:
        for ts, price in ((now[0] - 300.0, 1.00), (now[0], 1.01)):
            store.conn.execute(
                """
                INSERT INTO observation_snapshots
                (run_id, ts, venue, symbol, price, quote_volume_24h, spread_bps, depth_usd_25bps,
                 volatility_expansion, volume_zscore, book_imbalance, data_quality,
                 observation_eligible, execution_eligible, rejection_reasons, payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    f"route-policy-{ts}",
                    ts,
                    "kraken",
                    "ROUTE/USD",
                    price,
                    750_000.0,
                    6.0,
                    250_000.0,
                    1.5,
                    0.7,
                    0.0,
                    1.0,
                    1,
                    0,
                    "[]",
                    "{}",
                ),
            )
        store.conn.commit()
    tape = RapidPaperTape(
        cfg(
            phase2_taker_fee_bps_per_side=20.0,
            phase2_small_window_maker_fee_bps_per_side=0.0,
            phase2_latency_buffer_bps=0.0,
            phase2_safety_buffer_bps=5.0,
            phase2_small_window_trend_windows_sec=[300],
            phase2_small_window_trend_min_abs_move_bps=10.0,
            phase2_small_window_trend_min_net_bps=1.0,
            phase2_small_window_execution_policies=["maker_probe", "taker_market"],
        ),
        store,
        now_fn=lambda: now[0],
    )

    result = tape.open_from_trend_comparisons(limit=1, windows_sec=(300,), hold_sec=60, max_age_sec=120)

    assert result["opened"] == 1
    opened = result["opened_candidates"][0]
    assert opened["route_policy"] == "maker_probe"
    assert opened["expected_fill_ratio"] < 1.0
    assert opened["expected_cost_bps"] < 20.0
    assert opened["execution_route"]["selected_policy"] == "maker_probe"
    assert opened["microstructure"]["quality_score"] > 0


def test_rapid_paper_tape_ranks_multiple_small_windows_both_directions() -> None:
    now = [20_000.0]
    store = DataStoreAgent(":memory:")
    observations = [
        (now[0] - 3600.0, "CC/USD", 1.00),
        (now[0] - 1800.0, "CC/USD", 1.04),
        (now[0] - 300.0, "CC/USD", 1.08),
        (now[0] - 60.0, "CC/USD", 1.11),
        (now[0], "CC/USD", 1.12),
        (now[0] - 3600.0, "NPC/USD", 1.00),
        (now[0] - 1800.0, "NPC/USD", 0.96),
        (now[0] - 300.0, "NPC/USD", 0.92),
        (now[0] - 60.0, "NPC/USD", 0.90),
        (now[0], "NPC/USD", 0.89),
        (now[0] - 3600.0, "ETH/USD", 100.0),
        (now[0], "ETH/USD", 80.0),
    ]
    with store._lock:
        for ts, symbol, price in observations:
            store.conn.execute(
                """
                INSERT INTO observation_snapshots
                (run_id, ts, venue, symbol, price, quote_volume_24h, spread_bps, depth_usd_25bps,
                 volatility_expansion, volume_zscore, book_imbalance, data_quality,
                 observation_eligible, execution_eligible, rejection_reasons, payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    f"obs-{symbol}-{ts}",
                    ts,
                    "kraken",
                    symbol,
                    price,
                    500_000.0,
                    5.0,
                    100_000.0,
                    2.0,
                    1.0,
                    0.0,
                    1.0,
                    1,
                    0,
                    "[]",
                    "{}",
                ),
            )
        store.conn.commit()
    tape = RapidPaperTape(
        cfg(
            phase2_rapid_paper_allowed_directions=["UP", "DOWN"],
            phase2_rapid_paper_max_open_per_symbol=10,
            phase2_taker_fee_bps_per_side=1.0,
            phase2_latency_buffer_bps=0.0,
            phase2_small_window_trend_windows_sec=[60, 300, 1800, 3600],
            phase2_small_window_trend_min_abs_move_bps=10.0,
            phase2_small_window_trend_min_net_bps=1.0,
        ),
        store,
        now_fn=lambda: now[0],
    )

    result = tape.open_from_trend_comparisons(limit=8, windows_sec=(60, 300, 1800, 3600), hold_sec=60, max_age_sec=120)

    assert result["opened"] >= 2
    opened = result["opened_candidates"]
    assert {row["direction"] for row in opened} >= {"UP", "DOWN"}
    assert {row["window_sec"] for row in opened} & {60, 300, 1800, 3600}
    assert all(row["symbol"] != "ETH/USD" for row in opened)
    assert all(row["health_score"] > 0 for row in opened)


def test_rapid_paper_tape_can_open_micro_reversion_after_spike() -> None:
    now = [25_000.0]
    store = DataStoreAgent(":memory:")
    with store._lock:
        for ts, price in ((now[0] - 300.0, 1.00), (now[0], 1.20)):
            store.conn.execute(
                """
                INSERT INTO observation_snapshots
                (run_id, ts, venue, symbol, price, quote_volume_24h, spread_bps, depth_usd_25bps,
                 volatility_expansion, volume_zscore, book_imbalance, data_quality,
                 observation_eligible, execution_eligible, rejection_reasons, payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    f"micro-reversion-{ts}",
                    ts,
                    "kraken",
                    "WOBBLE/USD",
                    price,
                    500_000.0,
                    5.0,
                    100_000.0,
                    2.0,
                    1.0,
                    0.0,
                    1.0,
                    1,
                    0,
                    "[]",
                    "{}",
                ),
            )
        store.conn.commit()
    tape = RapidPaperTape(
        cfg(
            phase2_rapid_paper_allowed_directions=["UP", "DOWN"],
            phase2_taker_fee_bps_per_side=1.0,
            phase2_latency_buffer_bps=0.0,
            phase2_small_window_signal_lanes=["micro_reversion"],
            phase2_small_window_reversion_capture_ratio=0.35,
            phase2_small_window_reversion_max_capture_bps=80.0,
            phase2_small_window_trend_windows_sec=[300],
            phase2_small_window_trend_min_abs_move_bps=10.0,
            phase2_small_window_trend_min_net_bps=1.0,
        ),
        store,
        now_fn=lambda: now[0],
    )

    result = tape.open_from_trend_comparisons(limit=1, windows_sec=(300,), hold_sec=60, max_age_sec=120)

    assert result["opened"] == 1
    opened = result["opened_candidates"][0]
    assert opened["symbol"] == "WOBBLE/USD"
    assert opened["direction"] == "DOWN"
    assert opened["signal_lane"] == "micro_reversion"
    assert opened["expected_move_bps"] == 80.0


def test_rapid_paper_tape_blocks_unhealthy_dex_route_when_required() -> None:
    now = [30_000.0]
    store = DataStoreAgent(":memory:")
    payload = json.dumps({
        "dex_exit_allowed": False,
        "dex_reason": "ROUNDTRIP_RATIO_BELOW_MIN",
        "dex_route": {"_provider": "paraswap", "roundtrip_ratio": 0.90},
        "gas_drag_pct": 0.02,
    })
    with store._lock:
        for ts, price in ((now[0] - 300.0, 1.00), (now[0], 1.10)):
            store.conn.execute(
                """
                INSERT INTO observation_snapshots
                (run_id, ts, venue, symbol, price, quote_volume_24h, spread_bps, depth_usd_25bps,
                 volatility_expansion, volume_zscore, book_imbalance, data_quality,
                 observation_eligible, execution_eligible, rejection_reasons, payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    f"dex-route-{ts}",
                    ts,
                    "dex_base",
                    "TINY/USD",
                    price,
                    80_000.0,
                    5.0,
                    20_000.0,
                    2.0,
                    1.0,
                    0.0,
                    1.0,
                    1,
                    0,
                    "[]",
                    payload,
                ),
            )
        store.conn.commit()
    tape = RapidPaperTape(
        cfg(
            phase2_taker_fee_bps_per_side=1.0,
            phase2_latency_buffer_bps=0.0,
            phase2_small_window_trend_windows_sec=[300],
            phase2_small_window_trend_min_abs_move_bps=10.0,
            phase2_small_window_trend_min_net_bps=1.0,
            phase2_small_window_healthy_min_score=60.0,
        ),
        store,
        now_fn=lambda: now[0],
    )

    result = tape.open_from_trend_comparisons(limit=1, windows_sec=(300,), hold_sec=60, max_age_sec=120)

    assert result["opened"] == 0
    assert result["skipped_unhealthy"] == 1
    assert result["candidates"][0]["health_score"] < 60.0
    assert "dex_exit_not_clear" in result["candidates"][0]["health_reasons"]


def test_rapid_paper_tape_learns_from_phase6_canary_memory() -> None:
    now = [31_000.0]
    store = DataStoreAgent(":memory:")
    with store._lock:
        for ts, price in ((now[0] - 300.0, 1.00), (now[0], 1.018)):
            store.conn.execute(
                """
                INSERT INTO observation_snapshots
                (run_id, ts, venue, symbol, price, quote_volume_24h, spread_bps, depth_usd_25bps,
                 volatility_expansion, volume_zscore, book_imbalance, data_quality,
                 observation_eligible, execution_eligible, rejection_reasons, payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    f"canary-memory-{ts}",
                    ts,
                    "kraken",
                    "BLESS/USD",
                    price,
                    500_000.0,
                    5.0,
                    100_000.0,
                    1.3,
                    0.5,
                    0.0,
                    1.0,
                    1,
                    0,
                    "[]",
                    "{}",
                ),
            )
        store.conn.commit()
    base_cfg = cfg(
        phase2_taker_fee_bps_per_side=1.0,
        phase2_latency_buffer_bps=0.0,
        phase2_small_window_trend_windows_sec=[300],
        phase2_small_window_trend_min_abs_move_bps=10.0,
        phase2_small_window_trend_min_net_bps=1.0,
        phase2_small_window_healthy_min_score=50.0,
    )
    baseline = RapidPaperTape(base_cfg, store, now_fn=lambda: now[0]).open_from_trend_comparisons(
        limit=1, windows_sec=(300,), hold_sec=60, max_age_sec=120
    )
    assert baseline["opened"] == 1
    with store._lock:
        store.conn.execute("UPDATE rapid_paper_tape_trades SET status='CLOSED'")
        store.conn.commit()

    store.persist_crystal_registry_entry({
        "crystal_id": "phase6-memory-loss-bless-up",
        "created_ts": now[0] - 10,
        "updated_ts": now[0] - 10,
        "crystal_family": "small_window_canary_memory",
        "artifact_class": "small_window_canary_memory_crystal",
        "authority": "paper_research_only",
        "verification_state": "observed_settlement",
        "phase_scope": 6,
        "scope_key": "BLESS/USD|UP|300",
        "symbol": "BLESS/USD",
        "venue": "kraken",
        "regime_hint": "small_window_canary",
        "hypothesis": "recent_delta_volatility",
        "world_state_id": None,
        "applicability_hash": "BLESS/USD|UP|300",
        "evidence_strength": 120.0,
        "drift_status": "negative_memory",
        "expires_ts": None,
        "payload": {
            "schema": "small_window_canary_memory_crystal_v1",
            "symbol": "BLESS/USD",
            "direction": "UP",
            "window_sec": 300,
            "positive_net": False,
            "gross_return_bps": 0.0,
            "net_return_bps": -120.0,
            "settled_ts": now[0] - 10,
        },
    })

    learned = RapidPaperTape(base_cfg, store, now_fn=lambda: now[0]).open_from_trend_comparisons(
        limit=1, windows_sec=(300,), hold_sec=60, max_age_sec=120
    )

    assert learned["opened"] == 0
    assert learned["skipped_unhealthy"] == 1
    candidate = learned["candidates"][0]
    assert candidate["canary_memory"]["samples"] == 1
    assert candidate["canary_memory"]["mean_net_bps"] == -120.0
    assert "canary_negative_memory" in candidate["health_reasons"]
    assert "latest_canary_loss" in candidate["health_reasons"]


def test_rapid_paper_tape_can_disable_forecast_opening_lane() -> None:
    now = [12_500.0]
    store = DataStoreAgent(":memory:")
    insert_forecast(store, forecast_id="forecast-disabled-lane", now=now[0])
    tape = RapidPaperTape(
        cfg(phase2_rapid_paper_forecast_lane_enabled=False),
        store,
        now_fn=lambda: now[0],
    )

    result = tape.open_from_recent_forecasts(limit=10)

    assert result["disabled"] is True
    assert result["opened"] == 0
    assert tape.scorecard()["open"] == 0


def test_repeatable_mover_scorecard_writes_research_import_evidence() -> None:
    now = [13_000.0]
    store = DataStoreAgent(":memory:")
    tape = RapidPaperTape(cfg(), store, now_fn=lambda: now[0])
    with store._lock:
        for index, net_bps in enumerate((20.0, 30.0, 40.0)):
            store.conn.execute(
                """
                INSERT INTO rapid_paper_tape_trades
                (trade_id, source_forecast_id, run_id, venue, symbol, model_id, hypothesis,
                 direction, status, entry_ts, target_ts, settled_ts, updated_ts, entry_price,
                 exit_price, notional_usd, expected_net_bps, expected_cost_bps,
                 probability_positive_net, net_return_bps, positive_net, payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    f"trend-win-{index}",
                    f"trend-source-{index}",
                    "trend-run",
                    "kraken",
                    "CC/USD",
                    "small_window_trend_comparison_v1",
                    "observed_small_window_trend",
                    "DOWN",
                    "CLOSED_WIN",
                    now[0] - 600.0 + index,
                    now[0] - 300.0 + index,
                    now[0] - 290.0 + index,
                    now[0] - 290.0 + index,
                    1.0,
                    0.99,
                    5.0,
                    20.0,
                    5.0,
                    0.6,
                    net_bps,
                    1,
                    "{}",
                ),
            )
        store.conn.commit()

    scorecard = tape.repeatable_mover_scorecard(
        min_samples=3,
        min_win_rate=0.55,
        min_mean_net_bps=5.0,
        min_total_net_bps=10.0,
    )

    assert len(scorecard["promoted"]) == 1
    record = store.get_promotion_records("CC/USD")["CC/USD"]
    assert record["stage"] == "research_import"
    assert record["eligible"] == 1
    assert record["promotion_authority"] == "none"


def test_rapid_paper_tape_blocks_recent_loss_reentry() -> None:
    now = [8_000.0]
    store = DataStoreAgent(":memory:")
    insert_forecast(store, forecast_id="forecast-loss-cooldown-1", now=now[0])
    tape = RapidPaperTape(cfg(), store, now_fn=lambda: now[0])
    assert tape.open_from_recent_forecasts(limit=10)["opened"] == 1

    now[0] += 301.0
    with store._lock:
        store.conn.execute(
            """
            INSERT INTO observation_snapshots
            (run_id, ts, venue, symbol, price, quote_volume_24h, spread_bps, depth_usd_25bps,
             volatility_expansion, volume_zscore, book_imbalance, data_quality,
             observation_eligible, execution_eligible, rejection_reasons, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "obs-loss-cooldown-exit",
                now[0],
                "kraken",
                "ETH/USD",
                99.0,
                100_000_000.0,
                4.0,
                500_000.0,
                1.4,
                1.2,
                0.1,
                1.0,
                1,
                0,
                "[]",
                "{}",
            ),
        )
        store.conn.commit()
    assert tape.settle_due_open_trades(tolerance_sec=900.0)["closed"] == 1

    insert_forecast(store, forecast_id="forecast-loss-cooldown-2", now=now[0])
    result = tape.open_from_recent_forecasts(limit=10)
    assert result["opened"] == 0
    assert result["skipped_recent_loss"] == 1
    assert tape.scorecard()["open"] == 0


def test_rapid_paper_tape_uses_negative_crystals_as_refusal_memory() -> None:
    now = [9_000.0]
    store = DataStoreAgent(":memory:")
    insert_forecast(store, forecast_id="forecast-crystal-refusal", now=now[0])
    scope_key = (
        "breakout_continuation_v1|breakout_continuation|UP|"
        "rapid_paper_unknown_regime|ETH/USD"
    )
    for index in range(2):
        assert store.persist_crystal_registry_entry({
            "crystal_id": f"negative-memory-{index}",
            "created_ts": now[0] - 100.0 + index,
            "updated_ts": now[0] - 100.0 + index,
            "crystal_family": "negative_capability",
            "artifact_class": "negative_capability_crystal",
            "authority": "proposal_only",
            "verification_state": "candidate",
            "phase_scope": 2,
            "scope_key": scope_key,
            "symbol": "ETH/USD",
            "venue": "kraken",
            "regime_hint": "rapid_paper_unknown_regime",
            "hypothesis": "breakout_continuation",
            "world_state_id": None,
            "applicability_hash": scope_key,
            "evidence_strength": 50.0,
            "drift_status": "active_refusal_memory",
            "expires_ts": None,
        })
    tape = RapidPaperTape(cfg(), store, now_fn=lambda: now[0])

    result = tape.open_from_recent_forecasts(limit=10)
    assert result["opened"] == 0
    assert result["skipped_negative_memory"] == 1
    assert tape.scorecard()["open"] == 0


def test_rapid_paper_tape_blocks_bad_model_direction_after_enough_samples() -> None:
    now = [10_000.0]
    store = DataStoreAgent(":memory:")
    tape = RapidPaperTape(cfg(), store, now_fn=lambda: now[0])
    with store._lock:
        for index in range(5):
            store.conn.execute(
                """
                INSERT INTO rapid_paper_tape_trades
                (trade_id, source_forecast_id, run_id, venue, symbol, model_id, hypothesis,
                 direction, status, entry_ts, target_ts, settled_ts, updated_ts, entry_price,
                 exit_price, notional_usd, expected_net_bps, expected_cost_bps,
                 probability_positive_net, net_return_bps, positive_net, payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    f"old-loss-{index}",
                    f"old-forecast-{index}",
                    "old-run",
                    "kraken",
                    "ETH/USD",
                    "breakout_continuation_v1",
                    "breakout_continuation",
                    "UP",
                    "CLOSED_LOSS",
                    now[0] - 5_000.0 + index,
                    now[0] - 4_700.0 + index,
                    now[0] - 4_690.0 + index,
                    now[0] - 4_690.0 + index,
                    100.0,
                    99.0,
                    5.0,
                    12.0,
                    8.0,
                    0.61,
                    -40.0,
                    0,
                    "{}",
                ),
            )
        store.conn.commit()
    insert_forecast(store, forecast_id="forecast-probation", now=now[0])

    result = tape.open_from_recent_forecasts(limit=10)
    assert result["opened"] == 0
    assert result["skipped_model_direction_probation"] == 1
    assert tape.scorecard()["open"] == 0


def test_rapid_paper_tape_champion_scout_prefers_positive_settled_slice() -> None:
    now = [11_000.0]
    store = DataStoreAgent(":memory:")
    for index, net_bps in enumerate((40.0, 55.0, 70.0)):
        forecast_id = f"champion-history-{index}"
        insert_forecast(
            store,
            forecast_id=forecast_id,
            now=now[0] - 1_000.0 + index,
            symbol="NPC/USD",
            model_id="adapter_freqtrade_breakout_v1",
            hypothesis="freqtrade_style_multifactor_breakout",
            horizon_seconds=300,
            direction="UP",
            expected_net_bps=30.0,
        )
        with store._lock:
            store.conn.execute(
                """
                INSERT INTO hypothesis_outcomes
                (forecast_id, settled_ts, exit_price, gross_return_bps, directional_return_bps,
                 net_return_bps, positive_net, brier_score, absolute_error_bps, payload)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (forecast_id, now[0] - 600.0 + index, 101.0, net_bps, net_bps, net_bps, 1, 0.1, 5.0, "{}"),
            )
            store.conn.commit()

    insert_forecast(
        store,
        forecast_id="fresh-unsupported-high-expected",
        now=now[0],
        symbol="ETH/USD",
        model_id="unsupported_high_expected_v1",
        hypothesis="unsupported_high_expected",
        horizon_seconds=300,
        direction="UP",
        expected_net_bps=500.0,
    )
    insert_forecast(
        store,
        forecast_id="fresh-supported-champion",
        now=now[0],
        symbol="NPC/USD",
        model_id="adapter_freqtrade_breakout_v1",
        hypothesis="freqtrade_style_multifactor_breakout",
        horizon_seconds=300,
        direction="UP",
        expected_net_bps=20.0,
    )
    tape = RapidPaperTape(
        cfg(
            phase2_rapid_paper_max_open_trades=2,
            phase2_rapid_paper_champion_scout_enabled=True,
        ),
        store,
        now_fn=lambda: now[0],
    )

    result = tape.open_from_recent_forecasts(limit=10)
    assert result["opened"] == 1
    assert result["skipped_champion_scout"] == 1
    row = store.conn.execute(
        "SELECT source_forecast_id, payload FROM rapid_paper_tape_trades WHERE status='OPEN'"
    ).fetchone()
    assert row[0] == "fresh-supported-champion"
    assert "rapid_champion_scout_receipt_v1" in row[1]
