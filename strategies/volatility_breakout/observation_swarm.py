from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from .candidate_selector import ObservationOnlyCandidateSelector
from .feature_engine import Phase1FeatureEngine
from .models import CandidateObservation, ObservationRunSummary
from .signal_model import ObservationOnlySignalModel


def _float(value: Any) -> Optional[float]:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _crystal_registry_row(crystal: dict[str, Any], *, phase_scope: int = 1) -> dict[str, Any]:
    return {
        "crystal_id": str(crystal.get("world_state_id") or ""),
        "created_ts": float(int(crystal.get("observation_time_ms") or 0) / 1000.0),
        "updated_ts": float(int(crystal.get("observation_time_ms") or 0) / 1000.0),
        "crystal_family": "market_world_state",
        "artifact_class": str(crystal.get("artifact_class") or "market_world_state_crystal"),
        "authority": str(crystal.get("authority") or "context_only"),
        "verification_state": str(crystal.get("verification_state") or "local_observed"),
        "phase_scope": int(phase_scope),
        "scope_key": f"{crystal.get('venue')}|{crystal.get('symbol')}|{crystal.get('symbol_class')}|{crystal.get('regime_hint')}",
        "symbol": crystal.get("symbol"),
        "venue": crystal.get("venue"),
        "regime_hint": crystal.get("regime_hint"),
        "hypothesis": None,
        "world_state_id": crystal.get("world_state_id"),
        "applicability_hash": crystal.get("applicability_hash"),
        "evidence_strength": crystal.get("data_quality"),
        "drift_status": "fresh" if int(crystal.get("fresh_until_ms") or 0) >= int(time.time() * 1000) else "stale",
        "expires_ts": float(int(crystal.get("fresh_until_ms") or 0) / 1000.0) if crystal.get("fresh_until_ms") else None,
        "payload": crystal,
    }


def _world_state_crystal(
    *,
    cfg: Any,
    venue: str,
    symbol: str,
    observed_at_ms: int,
    features: Any,
    market: dict[str, Any],
    values: dict[str, Any],
) -> dict[str, Any]:
    regime_inputs = values.get('regime_inputs') if isinstance(values.get('regime_inputs'), dict) else {}
    freshness_ttl_sec = max(30, int(getattr(cfg, 'phase1_observation_stale_after_sec', 180) or 180))
    orderbook_digest = _canonical_hash({
        'spread_bps': round(float(features.spread_bps or 0.0), 6),
        'depth_usd_25bps': round(float(features.depth_usd_25bps or 0.0), 6),
        'book_imbalance': round(float(features.book_imbalance or 0.0), 6),
    })
    fee_schedule_digest = _canonical_hash({
        'venue': venue,
        'order_type_pref': getattr(cfg, 'order_type_pref', None),
        'phase2_taker_fee_bps_per_side': getattr(cfg, 'phase2_taker_fee_bps_per_side', None),
        'phase3_taker_fee_bps': getattr(cfg, 'phase3_taker_fee_bps', None),
        'phase3_maker_fee_bps': getattr(cfg, 'phase3_maker_fee_bps', None),
    })
    instrument_metadata_digest = _canonical_hash({
        'active': market.get('active'),
        'type': market.get('type'),
        'spot': market.get('spot'),
        'base': market.get('base'),
        'quote': market.get('quote'),
    })
    crystal = {
        'schema': 'market_world_state_crystal_v1',
        'artifact_class': 'market_world_state_crystal',
        'authority': 'context_only',
        'verification_state': 'local_observed',
        'venue': venue,
        'symbol': symbol,
        'symbol_class': values.get('symbol_class') or 'unknown',
        'cohort_bucket': values.get('cohort_bucket') or 'unknown',
        'observation_time_ms': int(observed_at_ms),
        'trusted_clock': 'system_utc',
        'spread_bps': round(float(features.spread_bps or 0.0), 6),
        'depth_usd_25bps': round(float(features.depth_usd_25bps or 0.0), 6),
        'quote_volume_24h': round(float(features.quote_volume_24h or 0.0), 6),
        'data_quality': round(float(features.data_quality or 0.0), 6),
        'freshness_sec': round(float(features.freshness_sec or 0.0), 6),
        'continuity_ratio': round(float(features.continuity_ratio or 0.0), 6),
        'regime_hint': str(regime_inputs.get('regime_hint') or 'unknown'),
        'regime_confidence': round(float(regime_inputs.get('confidence') or 0.0), 6),
        'volatility_expansion': round(float(features.volatility_expansion or 0.0), 6),
        'orderbook_digest': orderbook_digest,
        'fee_schedule_digest': fee_schedule_digest,
        'instrument_metadata_digest': instrument_metadata_digest,
        'exchange_status': 'active' if market.get('active', True) is not False else 'inactive',
        'execution_environment': 'observation_only',
        'applicability_hash': _canonical_hash({
            'venue': venue,
            'symbol': symbol,
            'symbol_class': values.get('symbol_class') or 'unknown',
            'cohort_bucket': values.get('cohort_bucket') or 'unknown',
            'orderbook_digest': orderbook_digest,
            'fee_schedule_digest': fee_schedule_digest,
            'instrument_metadata_digest': instrument_metadata_digest,
        }),
        'fresh_until_ms': int(observed_at_ms + (freshness_ttl_sec * 1000)),
    }
    crystal['world_state_id'] = _canonical_hash(crystal)
    return crystal


def _cohort_bucket(observation: CandidateObservation) -> str:
    values = observation.values if isinstance(observation.values, dict) else {}
    regime_inputs = values.get('regime_inputs') if isinstance(values.get('regime_inputs'), dict) else {}
    regime = str(regime_inputs.get('regime_hint') or 'unknown')
    tradable_opportunity = float(values.get('tradable_opportunity_score') or 0.0)
    spread_bps = float(observation.spread_bps or 0.0)
    depth_usd = float(observation.depth_usd_25bps or 0.0)
    range_position = values.get('range_position')
    return_zscore = abs(float(values.get('return_zscore') or 0.0))
    if observation.observation_eligible and spread_bps <= 8.0 and depth_usd >= 250_000.0:
        return 'core_liquid'
    if regime == 'stretch_exhaustion' or (range_position is not None and abs(float(range_position) - 0.5) >= 0.42 and return_zscore >= 1.25):
        return 'mean_reversion'
    if regime in {'trend_expansion', 'balanced_transition'} and tradable_opportunity >= 0.55:
        return 'event_driven'
    return 'research_bench'


def _symbol_class(observation: CandidateObservation) -> str:
    values = observation.values if isinstance(observation.values, dict) else {}
    regime_inputs = values.get('regime_inputs') if isinstance(values.get('regime_inputs'), dict) else {}
    regime = str(regime_inputs.get('regime_hint') or 'unknown')
    spread_bps = float(observation.spread_bps or 0.0)
    depth_usd = float(observation.depth_usd_25bps or 0.0)
    volume = float(observation.quote_volume_24h or 0.0)
    return_zscore = abs(float(values.get('return_zscore') or 0.0))
    if spread_bps <= 6.0 and depth_usd >= 500_000.0 and volume >= 100_000_000.0:
        return 'ultra_liquid_major'
    if regime in {'trend_expansion', 'balanced_transition'} and return_zscore >= 1.0 and volume >= 15_000_000.0:
        return 'event_spike_alt'
    if regime in {'stretch_exhaustion', 'quiet_range'} and spread_bps <= 12.0 and depth_usd >= 120_000.0:
        return 'mean_reverting_liquid'
    if spread_bps >= 18.0 or depth_usd < 60_000.0:
        return 'hostile_liquidity'
    return 'general_liquid'


class ObservationSwarmAgent:
    """Public-market observation engine with no imports or calls into execution code."""

    def __init__(self, cfg: Any, client: Any, coordinator: Optional[Any] = None) -> None:
        self.cfg = cfg
        self.client = client
        self.coordinator = coordinator
        self.enabled = bool(getattr(cfg, 'phase1_observation_enabled', True))
        min_interval_sec = max(1, int(getattr(cfg, 'phase1_observation_min_interval_sec', 30) or 30))
        self.interval_sec = max(min_interval_sec, int(getattr(cfg, 'phase1_observation_interval_sec', 120) or 120))
        self.max_symbols = max(1, min(50, int(getattr(cfg, 'phase1_observation_max_symbols', 12) or 12)))
        self.timeframe = str(getattr(cfg, 'phase1_observation_timeframe', '1m') or '1m')
        self.lookback = max(61, int(getattr(cfg, 'phase1_observation_lookback', 121) or 121))
        self.orderbook_depth = max(5, min(500, int(getattr(cfg, 'phase1_observation_orderbook_depth', 50) or 50)))
        self.quote_assets = tuple(str(item).upper() for item in (getattr(cfg, 'phase1_observation_quote_assets', ['USD', 'USDT', 'USDC']) or []))
        self.include = set(str(item).upper() for item in (getattr(cfg, 'phase1_observation_include', []) or []))
        self.exclude = set(str(item).upper() for item in (getattr(cfg, 'phase1_observation_exclude', []) or []))
        self.min_success_ratio = max(0.0, min(1.0, float(getattr(cfg, 'phase1_observation_min_success_ratio', 0.90) or 0.90)))
        self.discovery_pool_multiplier = max(1, min(6, int(getattr(cfg, 'phase1_observation_discovery_pool_multiplier', 3) or 3)))
        self.discovery_min_quote_volume_usd = max(0.0, float(getattr(cfg, 'phase1_observation_discovery_min_quote_volume_usd', 7_500_000.0) or 7_500_000.0))
        self.discovery_max_abs_pct_move = max(0.5, float(getattr(cfg, 'phase1_observation_discovery_max_abs_pct_move', 14.0) or 14.0))
        self.near_eligible_quota = max(0, min(6, int(getattr(cfg, 'phase1_observation_near_eligible_quota', 3) or 3)))
        # Niche/illiquid reservation: the general discovery ranking below weights raw
        # quote-volume (log10) so heavily that small/illiquid-but-volatile pairs can
        # never outrank majors on score alone, no matter how attractive their
        # volatility-vs-cost edge is. This reserves a fixed number of discovery-pool
        # slots for candidates in a niche volume band, ranked purely by volatility
        # (see _niche_edge_score), so they always get a chance at full observation +
        # the (volume-neutral) ObservationOnlyCandidateSelector eligibility/ranking gate.
        self.niche_quota = max(0, min(20, int(getattr(cfg, 'phase1_observation_niche_quota', 6) or 6)))
        self.niche_max_volume_usd = max(0.0, float(getattr(cfg, 'phase1_observation_niche_max_volume_usd', 2_000_000.0) or 2_000_000.0))
        profile_name = str(getattr(cfg, 'profile_name', '') or '')
        self.niche_focus_enabled = bool(
            getattr(cfg, 'phase1_observation_niche_focus_enabled', False)
            or profile_name == 'high_vol_low_stakes'
        )
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._latest: dict[str, Any] = {
            'phase': 1,
            'mode': 'observation_only',
            'enabled': self.enabled,
            'execution_wired': False,
            'orders_submitted': 0,
            'status': 'INITIALIZED' if self.enabled else 'DISABLED',
            'candidates': [],
        }
        self._run_count = 0
        self._last_error: Optional[str] = None

        self.feature_engine = Phase1FeatureEngine(
            timeframe=self.timeframe,
            short_window=int(getattr(cfg, 'phase1_observation_short_window', 5) or 5),
            baseline_window=int(getattr(cfg, 'phase1_observation_baseline_window', 60) or 60),
            stale_after_sec=int(getattr(cfg, 'phase1_observation_stale_after_sec', 180) or 180),
        )
        self.selector = ObservationOnlyCandidateSelector(
            min_listing_age_days=float(getattr(cfg, 'phase1_observation_min_listing_age_days', 90) or 90),
            min_depth_usd_25bps=float(getattr(cfg, 'phase1_observation_min_depth_usd_25bps', 25_000) or 25_000),
            min_quote_volume_24h_usd=float(getattr(cfg, 'phase1_observation_min_quote_volume_usd', 5_000_000) or 5_000_000),
            max_spread_bps=float(getattr(cfg, 'phase1_observation_max_spread_bps', 35) or 35),
            min_data_quality=float(getattr(cfg, 'phase1_observation_min_data_quality', 0.99) or 0.99),
            niche_focus_enabled=self.niche_focus_enabled,
            niche_max_quote_volume_24h_usd=self.niche_max_volume_usd,
            niche_taker_fee_bps_per_side=float(getattr(cfg, 'phase2_taker_fee_bps_per_side', 80.0) or 80.0),
            niche_min_research_richness=float(getattr(cfg, 'phase1_observation_niche_min_research_richness', 0.35) or 0.35),
            niche_min_volatility_to_cost=float(getattr(cfg, 'phase1_observation_niche_min_volatility_to_cost', 0.35) or 0.35),
        )
        self.signal_model = ObservationOnlySignalModel()

    def start(self) -> bool:
        if not self.enabled or self.client is None:
            with self._lock:
                self._latest['status'] = 'UNAVAILABLE' if self.client is None else 'DISABLED'
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name='hivenance-observation-swarm', daemon=True)
        self._thread.start()
        return True

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=max(0.0, timeout))

    def status(self) -> dict[str, Any]:
        with self._lock:
            snapshot = dict(self._latest)
        snapshot.update({
            'thread_alive': bool(self._thread and self._thread.is_alive()),
            'run_count': self._run_count,
            'last_error': self._last_error,
            'interval_sec': self.interval_sec,
            'max_symbols': self.max_symbols,
            'timeframe': self.timeframe,
            'execution_wired': False,
            'orders_submitted': 0,
        })
        return snapshot

    def latest_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._latest, default=str))

    def _loop(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self.run_once()
                self._last_error = None
            except Exception as exc:  # defensive daemon boundary
                self._last_error = f'{type(exc).__name__}: {exc}'
                logging.exception('Observation swarm cycle failed')
                self._publish_health('ERROR', [self._last_error])
            elapsed = time.monotonic() - started
            self._stop.wait(max(1.0, self.interval_sec - elapsed))

    def _publish(self, key: str, payload: dict[str, Any]) -> None:
        if self.coordinator and hasattr(self.coordinator, 'share_data'):
            self.coordinator.share_data(key, {
                'buzz': {
                    'type': key,
                    'source': 'OBSERVATION_SWARM',
                    'ts': int(time.time() * 1000),
                },
                'payload': payload,
            })

    def _publish_health(self, status: str, errors: Iterable[str]) -> None:
        self._publish('buzz.observation.health', {
            'phase': 1,
            'status': status,
            'errors': list(errors),
            'execution_wired': False,
            'orders_submitted': 0,
            'ts': int(time.time() * 1000),
        })

    def _load_markets(self) -> dict[str, Any]:
        if not hasattr(self.client, 'load_markets'):
            return {}
        markets = self.client.load_markets()
        return markets if isinstance(markets, dict) else {}

    def _fetch_tickers(self) -> dict[str, Any]:
        if hasattr(self.client, 'fetch_tickers'):
            tickers = self.client.fetch_tickers()
            return tickers if isinstance(tickers, dict) else {}
        out: dict[str, Any] = {}
        if hasattr(self.client, 'fetch_ticker'):
            for symbol in sorted(self.include):
                try:
                    out[symbol] = self.client.fetch_ticker(symbol)
                except Exception:
                    continue
        return out

    @staticmethod
    def _quote_volume(ticker: dict[str, Any]) -> float:
        quote = _float(ticker.get('quoteVolume'))
        if quote is not None:
            return max(0.0, quote)
        base = _float(ticker.get('baseVolume'))
        last = _float(ticker.get('last'))
        return max(0.0, (base or 0.0) * (last or 0.0))

    @staticmethod
    def _is_stable(asset: str) -> bool:
        return str(asset or '').upper() in {'USD', 'USDT', 'USDC', 'DAI', 'FDUSD', 'PYUSD', 'TUSD'}

    def _discovery_score(self, symbol_u: str, ticker: dict[str, Any]) -> float:
        base, quote = symbol_u.split('/', 1)
        quote = quote.split(':', 1)[0]
        volume = max(0.0, self._quote_volume(ticker))
        if volume < self.discovery_min_quote_volume_usd:
            return -1e9
        volume_score = min(10.0, math.log10(max(1.0, volume)))
        last = _float(ticker.get('last')) or 0.0
        open_ = _float(ticker.get('open'))
        pct = _float(ticker.get('percentage'))
        if pct is None and open_ and open_ > 0 and last > 0:
            pct = ((last - open_) / open_) * 100.0
        pct = abs(float(pct or 0.0))
        motion_score = min(6.0, pct)
        overheating_penalty = max(0.0, pct - self.discovery_max_abs_pct_move) * 0.35
        mid_move_bonus = max(0.0, 1.0 - abs(min(pct, self.discovery_max_abs_pct_move) - 4.0) / 6.0)
        stable_penalty = 0.0
        if self._is_stable(base) and self._is_stable(quote):
            stable_penalty = 4.0
        elif self._is_stable(base) or self._is_stable(quote):
            stable_penalty = 1.0
        liquidity_bonus = 0.0
        if volume >= 100_000_000.0:
            liquidity_bonus += 1.0
        elif volume >= 25_000_000.0:
            liquidity_bonus += 0.45
        return (1.35 * volume_score) + (0.45 * motion_score) + liquidity_bonus + mid_move_bonus - overheating_penalty - stable_penalty

    def _niche_edge_score(self, symbol_u: str, ticker: dict[str, Any]) -> float:
        """Rank niche/illiquid candidates by raw volatility, not size, within a volume
        band that excludes both dead markets (below the discovery floor) and majors
        (above niche_max_volume_usd). Mirrors scripts/niche_pair_scan.py's thesis:
        reward motion, don't reward volume. Returns -1e9 if out of the niche band."""
        volume = max(0.0, self._quote_volume(ticker))
        if volume < self.discovery_min_quote_volume_usd or volume > self.niche_max_volume_usd:
            return -1e9
        last = _float(ticker.get('last')) or 0.0
        open_ = _float(ticker.get('open'))
        pct = _float(ticker.get('percentage'))
        if pct is None and open_ and open_ > 0 and last > 0:
            pct = ((last - open_) / open_) * 100.0
        pct = abs(float(pct or 0.0))
        base, quote = symbol_u.split('/', 1)
        quote = quote.split(':', 1)[0]
        stable_penalty = 4.0 if (self._is_stable(base) and self._is_stable(quote)) else 0.0
        return pct - stable_penalty

    def _discover_symbols(self, markets: dict[str, Any], tickers: dict[str, Any]) -> list[str]:
        candidates: list[tuple[str, float]] = []
        niche_candidates: list[tuple[str, float]] = []
        for symbol, ticker in tickers.items():
            symbol_u = str(symbol).upper()
            if '/' not in symbol_u:
                continue
            base, quote = symbol_u.split('/', 1)
            quote = quote.split(':', 1)[0]
            if self.include and symbol_u not in self.include and base not in self.include:
                continue
            if symbol_u in self.exclude or base in self.exclude:
                continue
            if self.quote_assets and quote not in self.quote_assets:
                continue
            market = markets.get(symbol) or markets.get(symbol_u) or {}
            if market.get('active') is False or market.get('spot') is False:
                continue
            if market.get('type') not in (None, 'spot'):
                continue
            candidates.append((symbol, self._discovery_score(symbol_u, ticker or {})))
            if self.niche_quota > 0:
                niche_score = self._niche_edge_score(symbol_u, ticker or {})
                if niche_score > -1e9:
                    niche_candidates.append((symbol, niche_score))
        candidates.sort(key=lambda item: (-item[1], item[0]))
        niche_candidates.sort(key=lambda item: (-item[1], item[0]))

        selected: list[str] = []
        seen: set[str] = set()
        for symbol, _score in niche_candidates[: self.niche_quota]:
            if symbol in seen:
                continue
            selected.append(symbol)
            seen.add(symbol)
        pool_size = self.max_symbols * self.discovery_pool_multiplier
        for symbol, _score in candidates:
            if len(selected) >= pool_size:
                break
            if symbol in seen:
                continue
            selected.append(symbol)
            seen.add(symbol)
        return selected

    @staticmethod
    def _listing_age_days(market: dict[str, Any], now_ms: int) -> Optional[float]:
        info = market.get('info') if isinstance(market, dict) else {}
        info = info if isinstance(info, dict) else {}
        values = [
            market.get('listingTimestamp') if isinstance(market, dict) else None,
            info.get('listingTimestamp'), info.get('listingTime'), info.get('onboardDate'),
            info.get('listedAt'), info.get('launchTime'),
        ]
        for value in values:
            timestamp = _float(value)
            if timestamp is None:
                continue
            if timestamp < 10_000_000_000:
                timestamp *= 1000.0
            if 0 < timestamp <= now_ms:
                return max(0.0, (now_ms - timestamp) / 86_400_000.0)
        return None

    def run_once(self) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError('phase1 observation is disabled')
        if self.client is None:
            raise RuntimeError('public market-data client unavailable')

        started_ms = int(time.time() * 1000)
        run_id = f'obs-{started_ms}-{uuid.uuid4().hex[:8]}'
        venue = str(getattr(self.cfg, 'exchange', 'unknown') or 'unknown').lower()
        markets = self._load_markets()
        tickers = self._fetch_tickers()
        symbols = self._discover_symbols(markets, tickers)
        errors: list[str] = []
        raw_candidates: list[CandidateObservation] = []

        for symbol in symbols:
            observed_at_ms = int(time.time() * 1000)
            try:
                call_started = time.monotonic()
                ohlcv = self.client.fetch_ohlcv(symbol, timeframe=self.timeframe, limit=self.lookback)
                orderbook = self.client.fetch_order_book(symbol, limit=self.orderbook_depth)
                latency_ms = (time.monotonic() - call_started) * 1000.0
                ticker = tickers.get(symbol) or self.client.fetch_ticker(symbol)
                features = self.feature_engine.build(
                    symbol=symbol,
                    ohlcv=ohlcv,
                    orderbook=orderbook,
                    ticker=ticker or {},
                    observed_at_ms=observed_at_ms,
                )
                forecast = self.signal_model.forecast(features)
                market = markets.get(symbol) or {}
                observation = CandidateObservation(
                    symbol=symbol,
                    venue=venue,
                    timestamp_ms=observed_at_ms,
                    price=features.price,
                    quote_volume_24h=features.quote_volume_24h,
                    spread_bps=features.spread_bps,
                    depth_usd_25bps=features.depth_usd_25bps,
                    listing_age_days=self._listing_age_days(market, observed_at_ms),
                    venue_count=1,
                    data_quality=features.data_quality,
                    freshness_sec=features.freshness_sec,
                    continuity_ratio=features.continuity_ratio,
                    values={
                        'discovery_score': round(self._discovery_score(str(symbol).upper(), ticker or {}), 6),
                        'volatility_fast': features.realized_volatility_fast,
                        'volatility_baseline': features.realized_volatility_baseline,
                        'volatility_expansion': features.volatility_expansion,
                        'volume_zscore': features.volume_zscore,
                        'trade_count_zscore': features.trade_count_zscore,
                        'book_imbalance': features.book_imbalance,
                        'order_flow_imbalance': features.order_flow_imbalance,
                        'return_5': features.return_5,
                        'return_zscore': features.return_zscore,
                        'range_position': features.range_position,
                        'trend_slope': features.trend_slope,
                        'reversal_return_1': features.reversal_return_1,
                        'momentum_consistency': features.momentum_consistency,
                        'volume_ratio': features.volume_ratio,
                        'regime_inputs': dict(features.values.get('regime_inputs') or {}),
                        'fetch_latency_ms': round(latency_ms, 3),
                        'feature_complete': features.complete,
                        'feature_metadata': dict(features.values),
                        'feature_vector': asdict(features),
                        'forecast': asdict(forecast),
                        'market_active': market.get('active'),
                        'market_type': market.get('type'),
                    },
                )
                values = dict(observation.values or {})
                values['cohort_bucket'] = _cohort_bucket(observation)
                values['symbol_class'] = _symbol_class(observation)
                values['market_world_state_crystal'] = _world_state_crystal(
                    cfg=self.cfg,
                    venue=venue,
                    symbol=symbol,
                    observed_at_ms=observed_at_ms,
                    features=features,
                    market=market if isinstance(market, dict) else {},
                    values=values,
                )
                observation = CandidateObservation(
                    **{**asdict(observation), 'values': values}
                )
                raw_candidates.append(observation)
            except Exception as exc:
                errors.append(f'{symbol}:{type(exc).__name__}:{exc}')

        ranked_all = self.selector.rank(raw_candidates)
        eligible_ranked = [item for item in ranked_all if item.observation_eligible]
        near_eligible_ranked = [
            item for item in ranked_all
            if not item.observation_eligible and float((item.values or {}).get('tradable_opportunity_score') or 0.0) >= 0.45
        ]
        selected: list[CandidateObservation] = []
        selected.extend(eligible_ranked[:self.max_symbols])
        remaining_slots = max(0, self.max_symbols - len(selected))
        if remaining_slots > 0 and self.near_eligible_quota > 0:
            selected.extend(near_eligible_ranked[: min(remaining_slots, self.near_eligible_quota)])
            remaining_slots = max(0, self.max_symbols - len(selected))
        if remaining_slots > 0:
            seen = {item.symbol for item in selected}
            for item in ranked_all:
                if item.symbol in seen:
                    continue
                selected.append(item)
                seen.add(item.symbol)
                if len(selected) >= self.max_symbols:
                    break
        ranked = selected[:self.max_symbols]
        completed_ms = int(time.time() * 1000)
        qualities = [item.data_quality for item in ranked]
        mean_quality = sum(qualities) / len(qualities) if qualities else 0.0
        eligible_count = sum(1 for item in ranked if item.observation_eligible)
        # Ranking intentionally caps the output universe, so it cannot measure fetch health.
        # A successful observation is a discovered symbol that produced a feature vector.
        success_ratio = len(raw_candidates) / max(1, len(symbols))
        status = 'HEALTHY' if symbols and success_ratio >= self.min_success_ratio else 'DEGRADED'

        candidate_rows = [asdict(item) for item in ranked]
        for row in candidate_rows:
            row['rejection_reasons'] = list(row.get('rejection_reasons') or [])
            row['execution_eligible'] = False
        summary = ObservationRunSummary(
            run_id=run_id,
            venue=venue,
            started_at_ms=started_ms,
            completed_at_ms=completed_ms,
            symbols_attempted=len(symbols),
            symbols_successful=len(raw_candidates),
            symbols_eligible=eligible_count,
            mean_data_quality=round(mean_quality, 6),
            errors=tuple(errors),
            execution_wired=False,
            orders_submitted=0,
        )
        payload: dict[str, Any] = {
            'phase': 1,
            'mode': 'observation_only',
            'strategy_id': 'hivenance_volatility_breakout_v1_observer',
            'run': asdict(summary),
            'status': status,
            'success_ratio': round(success_ratio, 6),
            'discovery_pool_size': len(symbols),
            'near_eligible_quota': self.near_eligible_quota,
            'niche_focus_enabled': self.niche_focus_enabled,
            'niche_quota': self.niche_quota,
            'niche_max_volume_usd': self.niche_max_volume_usd,
            'timeframe': self.timeframe,
            'lookback': self.lookback,
            'quote_assets': list(self.quote_assets),
            'execution_wired': False,
            'orders_submitted': 0,
            'candidates': candidate_rows,
            'observed_at': datetime.fromtimestamp(completed_ms / 1000.0, tz=timezone.utc).isoformat(),
        }
        payload['world_state_summary'] = {
            'schema': 'market_world_state_crystal_v1',
            'fresh_candidate_count': sum(
                1
                for row in candidate_rows
                if float(
                    (((row.get('values') or {}).get('market_world_state_crystal') or {}).get('fresh_until_ms') or 0)
                ) >= float(completed_ms)
            ),
            'eligible_candidate_count': int(eligible_count),
            'venue': venue,
        }
        payload['dataset_hash'] = _canonical_hash({
            'run': payload['run'],
            'candidates': payload['candidates'],
            'timeframe': payload['timeframe'],
            'world_state_summary': payload['world_state_summary'],
        })
        store = getattr(self.coordinator, 'store', None) if self.coordinator is not None else None
        if store is not None and hasattr(store, 'persist_crystal_registry_entry'):
            for row in candidate_rows:
                values = row.get('values') if isinstance(row.get('values'), dict) else {}
                crystal = values.get('market_world_state_crystal') if isinstance(values.get('market_world_state_crystal'), dict) else {}
                if crystal.get('world_state_id'):
                    try:
                        store.persist_crystal_registry_entry(_crystal_registry_row(crystal, phase_scope=1))
                    except Exception:
                        logging.exception('Failed to persist market world-state crystal')

        with self._lock:
            self._latest = payload
            self._run_count += 1
        self._publish('buzz.observation.snapshot', payload)
        self._publish_health(status, errors)
        return payload
