from __future__ import annotations

import math
import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from agents.data_store_agent import DataStoreAgent
from strategies.volatility_breakout.candidate_selector import ObservationOnlyCandidateSelector
from strategies.volatility_breakout.feature_engine import Phase1FeatureEngine
from strategies.volatility_breakout.models import CandidateObservation
from strategies.volatility_breakout.observation_swarm import ObservationSwarmAgent


@dataclass
class FakeConfig:
    exchange: str = 'kraken'
    phase1_observation_enabled: bool = True
    phase1_observation_interval_sec: int = 120
    phase1_observation_max_symbols: int = 2
    phase1_observation_quote_assets: tuple[str, ...] = ('USD',)
    phase1_observation_include: tuple[str, ...] = ()
    phase1_observation_exclude: tuple[str, ...] = ()
    phase1_observation_timeframe: str = '1m'
    phase1_observation_lookback: int = 121
    phase1_observation_orderbook_depth: int = 50
    phase1_observation_short_window: int = 5
    phase1_observation_baseline_window: int = 60
    phase1_observation_stale_after_sec: int = 180
    phase1_observation_min_success_ratio: float = 0.9
    phase1_observation_min_listing_age_days: float = 90.0
    phase1_observation_min_quote_volume_usd: float = 5_000_000.0
    phase1_observation_min_depth_usd_25bps: float = 25_000.0
    phase1_observation_max_spread_bps: float = 35.0
    phase1_observation_min_data_quality: float = 0.99
    phase1_observation_discovery_min_quote_volume_usd: float = 7_500_000.0
    phase1_observation_discovery_max_abs_pct_move: float = 14.0
    phase1_observation_near_eligible_quota: int = 3


class FakeClient:
    def __init__(self) -> None:
        self.orders = []
        now = int(time.time() * 1000)
        self._ohlcv = {}
        for index, symbol in enumerate(('BTC/USD', 'ETH/USD')):
            rows = []
            base_price = 50_000.0 if symbol.startswith('BTC') else 3_000.0
            for i in range(121):
                ts = now - (120 - i) * 60_000
                price = base_price * (1.0 + 0.0002 * i + 0.0001 * math.sin(i))
                volume = 1_000.0 + i * 5.0 + (200.0 if i >= 116 else 0.0)
                rows.append([ts, price, price * 1.001, price * 0.999, price, volume])
            self._ohlcv[symbol] = rows

    def load_markets(self):
        return {
            'BTC/USD': {'active': True, 'spot': True, 'type': 'spot'},
            'ETH/USD': {'active': True, 'spot': True, 'type': 'spot'},
            'BAD/USD': {'active': False, 'spot': True, 'type': 'spot'},
        }

    def fetch_tickers(self):
        return {
            'BTC/USD': {'last': 51_200.0, 'quoteVolume': 800_000_000.0},
            'ETH/USD': {'last': 3_070.0, 'quoteVolume': 500_000_000.0},
            'BAD/USD': {'last': 1.0, 'quoteVolume': 900_000_000.0},
        }

    def fetch_ohlcv(self, symbol, timeframe='1m', limit=121):
        return self._ohlcv[symbol][-limit:]

    def fetch_order_book(self, symbol, limit=50):
        mid = 51_200.0 if symbol.startswith('BTC') else 3_070.0
        bids = [[mid * (1 - 0.0002 * (i + 1)), 20.0] for i in range(limit)]
        asks = [[mid * (1 + 0.0002 * (i + 1)), 18.0] for i in range(limit)]
        return {'bids': bids, 'asks': asks}

    def fetch_ticker(self, symbol):
        return self.fetch_tickers()[symbol]


class CaptureCoordinator:
    def __init__(self, store: DataStoreAgent) -> None:
        self.events = []
        self.store = store

    def share_data(self, key, event):
        self.events.append((key, event))
        self.store.handle_event(event)


def test_phase1_observer_collects_and_never_executes(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / 'obs.db'))
    coordinator = CaptureCoordinator(store)
    client = FakeClient()
    observer = ObservationSwarmAgent(FakeConfig(), client, coordinator=coordinator)

    payload = observer.run_once()

    assert payload['mode'] == 'observation_only'
    assert payload['execution_wired'] is False
    assert payload['orders_submitted'] == 0
    assert len(payload['candidates']) == 2
    assert all(row['execution_eligible'] is False for row in payload['candidates'])
    assert client.orders == []
    assert any(key == 'buzz.observation.snapshot' for key, _ in coordinator.events)

    rows = store.get_observation_snapshots(limit=10)
    runs = store.get_observation_runs(limit=10)
    universe = store.get_observation_universe(days=7.0, limit_per_cohort=5)
    assert len(rows) == 2
    assert len(runs) == 1
    assert all(row['execution_eligible'] is False for row in rows)
    assert runs[0]['orders_submitted'] == 0
    assert universe['cohorts']
    assert any(item.get('cohort_bucket') for group in universe['cohorts'].values() for item in group)
    assert all(
        (json.loads(row.get('payload') or '{}').get('values', {}).get('symbol_class'))
        for row in rows
    )


def test_quality_marks_stale_and_gapped_data_incomplete():
    engine = Phase1FeatureEngine(timeframe='1m', short_window=5, baseline_window=60, stale_after_sec=120)
    now = int(time.time() * 1000)
    rows = []
    for i in range(61):
        ts = now - (180 + (60 - i) * 120) * 1000
        rows.append([ts, 100, 101, 99, 100 + i * 0.01, 1000])
    features = engine.build(
        symbol='TEST/USD',
        ohlcv=rows,
        orderbook={'bids': [[100, 1000]], 'asks': [[100.1, 1000]]},
        ticker={'last': 100.05, 'quoteVolume': 20_000_000},
        observed_at_ms=now,
    )
    assert features.complete is False
    assert features.data_quality < 0.99
    assert features.freshness_sec > 120
    assert (features.continuity_ratio or 0.0) < 0.95


def test_selector_separates_observation_from_execution():
    selector = ObservationOnlyCandidateSelector(
        min_depth_usd_25bps=25_000,
        min_quote_volume_24h_usd=5_000_000,
        max_spread_bps=35,
        min_data_quality=0.99,
    )
    candidate = CandidateObservation(
        symbol='GOOD/USD', venue='kraken', timestamp_ms=1, price=10.0,
        quote_volume_24h=50_000_000, spread_bps=5.0, depth_usd_25bps=500_000,
        listing_age_days=None, venue_count=1, data_quality=1.0, freshness_sec=1.0,
        continuity_ratio=1.0, values={'volatility_expansion': 2.0},
    )
    result = selector.evaluate(candidate)
    assert result.observation_eligible is True
    assert result.execution_eligible is False


def test_selector_penalizes_untradable_but_exciting_candidates():
    selector = ObservationOnlyCandidateSelector(
        min_depth_usd_25bps=25_000,
        min_quote_volume_24h_usd=5_000_000,
        max_spread_bps=35,
        min_data_quality=0.99,
    )
    clean = CandidateObservation(
        symbol='CLEAN/USD', venue='kraken', timestamp_ms=1, price=10.0,
        quote_volume_24h=20_000_000, spread_bps=4.0, depth_usd_25bps=300_000,
        listing_age_days=None, venue_count=1, data_quality=1.0, freshness_sec=1.0,
        continuity_ratio=1.0,
        values={
            'volatility_expansion': 1.4,
            'volume_zscore': 1.0,
            'return_zscore': 1.3,
            'trend_slope': 0.00005,
            'range_position': 0.8,
            'regime_inputs': {'regime_hint': 'trend_expansion', 'confidence': 0.8},
        },
    )
    exciting_bad = CandidateObservation(
        symbol='WILD/USD', venue='kraken', timestamp_ms=1, price=10.0,
        quote_volume_24h=20_000_000, spread_bps=30.0, depth_usd_25bps=2_000,
        listing_age_days=None, venue_count=1, data_quality=1.0, freshness_sec=1.0,
        continuity_ratio=1.0,
        values={
            'volatility_expansion': 2.6,
            'volume_zscore': 2.5,
            'return_zscore': 2.4,
            'trend_slope': 0.00012,
            'range_position': 0.98,
            'regime_inputs': {'regime_hint': 'trend_expansion', 'confidence': 0.9},
        },
    )
    clean_eval = selector.evaluate(clean)
    wild_eval = selector.evaluate(exciting_bad)
    assert clean_eval.values['research_richness_score'] < wild_eval.values['research_richness_score']
    assert clean_eval.values['tradable_opportunity_score'] > wild_eval.values['tradable_opportunity_score']
    assert wild_eval.values['tradability_penalty'] > 0.5


def test_selector_diversifies_regime_seed_before_filling_rest():
    selector = ObservationOnlyCandidateSelector()
    rows = [
        CandidateObservation(
            symbol='TREND1/USD', venue='kraken', timestamp_ms=1, price=10.0,
            quote_volume_24h=20_000_000, spread_bps=4.0, depth_usd_25bps=300_000,
            listing_age_days=None, venue_count=1, data_quality=1.0, freshness_sec=1.0,
            continuity_ratio=1.0, score=0.95, eligible=True, observation_eligible=True,
            values={'regime_inputs': {'regime_hint': 'trend_expansion'}},
        ),
        CandidateObservation(
            symbol='TREND2/USD', venue='kraken', timestamp_ms=1, price=10.0,
            quote_volume_24h=19_000_000, spread_bps=5.0, depth_usd_25bps=250_000,
            listing_age_days=None, venue_count=1, data_quality=1.0, freshness_sec=1.0,
            continuity_ratio=1.0, score=0.94, eligible=True, observation_eligible=True,
            values={'regime_inputs': {'regime_hint': 'trend_expansion'}},
        ),
        CandidateObservation(
            symbol='RANGE/USD', venue='kraken', timestamp_ms=1, price=10.0,
            quote_volume_24h=18_000_000, spread_bps=6.0, depth_usd_25bps=240_000,
            listing_age_days=None, venue_count=1, data_quality=1.0, freshness_sec=1.0,
            continuity_ratio=1.0, score=0.80, eligible=True, observation_eligible=True,
            values={'regime_inputs': {'regime_hint': 'quiet_range'}},
        ),
    ]
    ranked = selector.rank(rows)
    assert ranked[0].symbol == 'TREND1/USD'
    assert ranked[1].symbol == 'RANGE/USD'


def test_discovery_score_penalizes_overheated_low_quality_names():
    observer = ObservationSwarmAgent(FakeConfig(), FakeClient())
    liquid_orderly = observer._discovery_score('BTC/USD', {'last': 50_000.0, 'open': 48_500.0, 'quoteVolume': 120_000_000.0})
    overheated = observer._discovery_score('WILD/USD', {'last': 1.0, 'open': 0.7, 'quoteVolume': 20_000_000.0})
    illiquid = observer._discovery_score('TINY/USD', {'last': 1.0, 'open': 0.98, 'quoteVolume': 2_000_000.0})
    assert liquid_orderly > overheated
    assert illiquid < 0.0


def test_phase1_observer_assigns_cohort_bucket():
    observer = ObservationSwarmAgent(FakeConfig(), FakeClient())
    payload = observer.run_once()
    assert all((row.get('values') or {}).get('cohort_bucket') in {
        'core_liquid', 'event_driven', 'mean_reversion', 'research_bench'
    } for row in payload['candidates'])


def test_observer_keeps_near_eligible_research_bench_when_strict_winners_are_few(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / 'bench.db'))
    coordinator = CaptureCoordinator(store)
    client = FakeClient()
    observer = ObservationSwarmAgent(FakeConfig(), client, coordinator=coordinator)

    ranked = [
        CandidateObservation(
            symbol='GOOD/USD', venue='kraken', timestamp_ms=1, price=10.0,
            quote_volume_24h=20_000_000, spread_bps=4.0, depth_usd_25bps=300_000,
            listing_age_days=None, venue_count=1, data_quality=1.0, freshness_sec=1.0,
            continuity_ratio=1.0, observation_eligible=True, eligible=True, score=0.90,
            values={'tradable_opportunity_score': 0.85},
        ),
        CandidateObservation(
            symbol='ALMOST/USD', venue='kraken', timestamp_ms=1, price=10.0,
            quote_volume_24h=20_000_000, spread_bps=12.0, depth_usd_25bps=20_000,
            listing_age_days=None, venue_count=1, data_quality=1.0, freshness_sec=1.0,
            continuity_ratio=1.0, observation_eligible=False, eligible=False, score=0.70,
            rejection_reasons=('insufficient_executable_depth',), values={'tradable_opportunity_score': 0.62},
        ),
        CandidateObservation(
            symbol='NOPE/USD', venue='kraken', timestamp_ms=1, price=10.0,
            quote_volume_24h=4_000_000, spread_bps=40.0, depth_usd_25bps=5_000,
            listing_age_days=None, venue_count=1, data_quality=1.0, freshness_sec=1.0,
            continuity_ratio=1.0, observation_eligible=False, eligible=False, score=0.20,
            rejection_reasons=('spread_too_wide',), values={'tradable_opportunity_score': 0.10},
        ),
    ]
    observer.selector.rank = lambda _raw: ranked  # type: ignore[method-assign]
    observer._discover_symbols = lambda *_args, **_kwargs: ['GOOD/USD', 'ALMOST/USD', 'NOPE/USD']  # type: ignore[method-assign]
    observer._load_markets = lambda: client.load_markets()  # type: ignore[method-assign]
    observer._fetch_tickers = lambda: {  # type: ignore[method-assign]
        'GOOD/USD': {'last': 10.0, 'quoteVolume': 20_000_000.0},
        'ALMOST/USD': {'last': 10.0, 'quoteVolume': 20_000_000.0},
        'NOPE/USD': {'last': 10.0, 'quoteVolume': 4_000_000.0},
    }
    client.fetch_ohlcv = lambda symbol, timeframe='1m', limit=121: client._ohlcv['BTC/USD'][-limit:]  # type: ignore[method-assign]
    client.fetch_order_book = lambda symbol, limit=50: {  # type: ignore[method-assign]
        'bids': [[10.0, 1000.0]],
        'asks': [[10.01, 1000.0]],
    }
    client.fetch_ticker = lambda symbol: {'last': 10.0, 'quoteVolume': 20_000_000.0}  # type: ignore[method-assign]
    observer.feature_engine.build = lambda **_kwargs: observer.feature_engine.unavailable(_kwargs['symbol'], 1)  # type: ignore[method-assign]

    payload = observer.run_once()
    symbols = [row['symbol'] for row in payload['candidates']]
    assert 'GOOD/USD' in symbols
    assert 'ALMOST/USD' in symbols


def test_unavailable_microstructure_fields_remain_none():
    engine = Phase1FeatureEngine(timeframe='1m', short_window=5, baseline_window=60)
    unavailable = engine.unavailable('NONE/USD', 1)
    assert unavailable.trade_count_zscore is None
    assert unavailable.order_flow_imbalance is None
    assert unavailable.complete is False


def test_readiness_gate_stays_closed_until_evidence_age_met(tmp_path: Path):
    store = DataStoreAgent(str(tmp_path / 'readiness.db'))
    coordinator = CaptureCoordinator(store)
    observer = ObservationSwarmAgent(FakeConfig(), FakeClient(), coordinator=coordinator)
    observer.run_once()

    readiness = store.get_observation_readiness(
        required_days=7,
        min_mean_quality=0.5,
        min_success_ratio=0.5,
    )
    assert readiness['ready_for_phase2_review'] is False
    assert readiness['execution_eligible'] is False
    assert readiness['orders_submitted'] == 0
    assert 'insufficient_observation_days' in readiness['reasons']


def test_feature_engine_emits_regime_inputs():
    engine = Phase1FeatureEngine(timeframe='1m', short_window=5, baseline_window=60)
    now = int(time.time() * 1000)
    rows = []
    price = 100.0
    for i in range(121):
        ts = now - (120 - i) * 60_000
        if i < 100:
            price *= 1.0004
            volume = 1_000.0 + i * 3.0
        else:
            price *= 1.0025
            volume = 2_500.0 + i * 10.0
        rows.append([ts, price * 0.999, price * 1.002, price * 0.998, price, volume])

    features = engine.build(
        symbol='TEST/USD',
        ohlcv=rows,
        orderbook={
            'bids': [[price * (1 - 0.00015 * (i + 1)), 25.0] for i in range(50)],
            'asks': [[price * (1 + 0.00015 * (i + 1)), 22.0] for i in range(50)],
        },
        ticker={'last': price, 'quoteVolume': 50_000_000},
        observed_at_ms=now,
    )

    regime_inputs = features.values.get('regime_inputs')
    assert isinstance(regime_inputs, dict)
    assert regime_inputs['regime_hint'] in {
        'trend_expansion',
        'stretch_exhaustion',
        'hostile_liquidity',
        'quiet_range',
        'balanced_transition',
    }
    assert regime_inputs['trend_direction'] in {'up', 'down', 'flat'}
    assert regime_inputs['liquidity_state'] in {'deep', 'fragile', 'normal'}
    assert regime_inputs['participation_state'] in {'expanding', 'soft', 'normal'}
    assert 0.2 <= regime_inputs['confidence'] <= 0.95
