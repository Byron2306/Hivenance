#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.strategy_workers import (
    BollingerWorker,
    BreakoutWorker,
    MomentumWorker,
    RSI2Worker,
    RSIWorker,
    SMAWorker,
    SupertrendWorker,
    VolatilityExpansionWorker,
)

SCHEMA = "hivenance_live_profit_streak_swarm_lab_v2"
AUTHORITY = "PUBLIC_MARKET_PAPER_ONLY_NO_PRIVATE_KEYS_NO_ORDERS"
KRAKEN_PUBLIC_BASE = "https://api.kraken.com/0/public"

WORKERS = (
    ("sma", "trend", SMAWorker()),
    ("rsi", "mean_reversion", RSIWorker()),
    ("rsi2", "mean_reversion", RSI2Worker()),
    ("breakout", "breakout", BreakoutWorker()),
    ("momentum", "momentum", MomentumWorker()),
    ("bollinger", "mean_reversion", BollingerWorker()),
    ("supertrend", "trend", SupertrendWorker()),
    ("vol_expansion", "breakout", VolatilityExpansionWorker()),
)

MUTATIONS = (
    {"id": "raw_streak", "kind": "control", "description": "Cost-aware persistence only."},
    {"id": "majority5", "kind": "swarm", "description": "Five of eight Phoenix workers support."},
    {"id": "vol_breakout_pair", "kind": "ablation_pair", "description": "VolatilityExpansion + Breakout."},
    {"id": "inferred_regime", "kind": "regime_swarm", "description": "Online inferred-regime threshold."},
    {"id": "entropy_gate", "kind": "diversity", "description": "Majority with low vote entropy."},
    {"id": "no_vol_worker", "kind": "worker_ablation", "description": "Coalition with VolatilityExpansion removed."},
    {"id": "no_reversion_workers", "kind": "family_ablation", "description": "Trend/breakout/momentum families only."},
    {"id": "random30", "kind": "matched_random_control", "description": "Randomly admit 30% of valid candidates."},
)

API_SYMBOL_CANDIDATES = {
    "BTC/USD": ("BTC/USD", "XBT/USD"),
    "DOGE/USD": ("DOGE/USD", "XDG/USD"),
}
API_SYMBOL_ALIASES = {
    "XBT/USD": "BTC/USD",
    "XDG/USD": "DOGE/USD",
}


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _std(values: list[float]) -> float:
    return statistics.pstdev(values) if len(values) >= 2 else 0.0


def _lag1_autocorr(values: list[float]) -> float:
    if len(values) < 4:
        return 0.0
    x, y = values[:-1], values[1:]
    mx, my = statistics.mean(x), statistics.mean(y)
    sx = math.sqrt(sum((v - mx) ** 2 for v in x))
    sy = math.sqrt(sum((v - my) ** 2 for v in y))
    if sx <= 0 or sy <= 0:
        return 0.0
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)


def _entropy(pos: int, neg: int) -> float:
    active = pos + neg
    if active <= 0:
        return 1.0
    p = pos / active
    out = 0.0
    for q in (p, 1.0 - p):
        if q > 0:
            out -= q * math.log(q, 2)
    return out




@dataclass
class SeriesState:
    prices: deque[float] = field(default_factory=lambda: deque(maxlen=180))
    volumes: deque[float] = field(default_factory=lambda: deque(maxlen=180))

    def add(self, price: float, volume: float = 0.0) -> None:
        self.prices.append(float(price))
        self.volumes.append(max(0.0, float(volume)))

    def ret(self, seconds: int) -> float:
        if len(self.prices) <= seconds:
            return 0.0
        p = list(self.prices)
        start, end = p[-(seconds + 1)], p[-1]
        return (end / start - 1.0) if start > 0 else 0.0

    def regime(self) -> dict[str, Any]:
        p = list(self.prices)
        if len(p) < 12:
            return {"label": "warming", "confidence": 0.0}
        rets = [p[i] / p[i - 1] - 1.0 for i in range(1, len(p)) if p[i - 1] > 0]
        short = rets[-5:]
        base = rets[-30:] if len(rets) >= 30 else rets
        short_vol, base_vol = _std(short), _std(base)
        vol_ratio = short_vol / max(base_vol, 1e-12)
        signs = [1 if r > 0 else -1 if r < 0 else 0 for r in short]
        persistence = abs(sum(signs)) / max(1, len(signs))
        autocorr = _lag1_autocorr(base)
        if vol_ratio >= 1.25 and persistence >= 0.60:
            label = "bursty"
            confidence = min(1.0, 0.45 + 0.25 * (vol_ratio - 1.0) + 0.30 * persistence)
        elif autocorr <= -0.25:
            label = "meanrev"
            confidence = min(1.0, 0.55 + abs(autocorr) * 0.45)
        elif persistence <= 0.25 and vol_ratio <= 1.10:
            label = "noise"
            confidence = min(1.0, 0.50 + (0.25 - persistence))
        else:
            label, confidence = "mixed", 0.50
        return {
            "label": label,
            "confidence": round(confidence, 6),
            "vol_ratio": round(vol_ratio, 6),
            "persistence": round(persistence, 6),
            "lag1_autocorr": round(autocorr, 6),
            "move5_bps": round(self.ret(5) * 10000.0, 6),
        }


@dataclass
class Position:
    qty: float
    entry_price: float
    peak_price: float
    entry_ts: float


@dataclass
class PaperWallet:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    cumulative_cost_usd: float = 0.0
    actions: int = 0
    peak_equity_usd: float = 0.0

    def equity(self, prices: dict[str, float], exit_cost_bps_side: float) -> float:
        value = self.cash
        for symbol, pos in self.positions.items():
            price = prices.get(symbol)
            if price is None:
                continue
            gross = pos.qty * price
            value += gross - gross * exit_cost_bps_side / 10000.0
        return value


class KrakenPublicFeed:
    """Stdlib-only Kraken public ticker feed.

    Uses one multi-pair Ticker request per cycle. No auth headers, keys,
    private endpoints, CCXT, or exchange SDKs.
    """

    def __init__(self, symbols: list[str], timeout_sec: float = 8.0) -> None:
        self.symbols = symbols
        self.timeout_sec = timeout_sec
        self.last_prices: dict[str, float] = {}
        self.last_cumulative_volume: dict[str, float] = {}
        self.last_bid: dict[str, float] = {}
        self.last_ask: dict[str, float] = {}
        self.last_spread_bps: dict[str, float] = {}
        self.last_24h_open: dict[str, float] = {}
        self.last_24h_high: dict[str, float] = {}
        self.last_24h_low: dict[str, float] = {}
        self.last_24h_volume: dict[str, float] = {}
        self.api_pairs: dict[str, str] = {}
        self.result_key_to_symbol: dict[str, str] = {}
        self._load_pair_map()

    @staticmethod
    def _canonical_wsname(wsname: str) -> str:
        text = str(wsname or "").upper()
        return text.replace("XBT/", "BTC/").replace("XDG/", "DOGE/")

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params)
        url = f"{KRAKEN_PUBLIC_BASE}/{endpoint}"
        if query:
            url += "?" + query
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Hivenance-Phoenix-Public-Research/1.0",
            },
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
        errors = payload.get("error") or []
        if errors:
            raise RuntimeError(
                f"{';'.join(str(item) for item in errors)} "
                f"endpoint={endpoint} params={params}"
            )
        result = payload.get("result")
        return result if isinstance(result, dict) else {}

    def _load_pair_map(self) -> None:
        pairs = self._get("AssetPairs", {})
        wanted = set(self.symbols)
        for result_key, info in pairs.items():
            if not isinstance(info, dict):
                continue
            wsname = self._canonical_wsname(str(info.get("wsname") or ""))
            if wsname not in wanted:
                continue
            altname = str(info.get("altname") or result_key)
            self.api_pairs[wsname] = altname
            self.result_key_to_symbol[str(result_key)] = wsname

        missing = [symbol for symbol in self.symbols if symbol not in self.api_pairs]
        if missing:
            raise RuntimeError(f"Kraken AssetPairs missing requested symbols: {missing}")

    def _ticker_result(self) -> dict[str, Any]:
        pair_arg = ",".join(self.api_pairs[symbol] for symbol in self.symbols)
        return self._get("Ticker", {"pair": pair_arg})

    def recent_trades(self, symbol: str, count: int = 80) -> list[dict[str, float]]:
        result = self._get("PostTrade", {"symbol": symbol, "count": int(count)})
        out: list[dict[str, float]] = []
        for trade in result.get("trades") or []:
            price = _finite(trade.get("price"))
            qty = max(0.0, _finite(trade.get("quantity")))
            if price > 0:
                out.append({"price": price, "quantity": qty})
        return out
    def seed_prices(self) -> dict[str, float]:
        result = self._ticker_result()
        self._consume_ticker(result, seed_only=True)
        return dict(self.last_prices)

    def _consume_ticker(
        self,
        result: dict[str, Any],
        *,
        seed_only: bool = False,
    ) -> tuple[dict[str, float], dict[str, float], int]:
        incremental_volume: dict[str, float] = {}
        updated = 0

        for result_key, row in result.items():
            symbol = self.result_key_to_symbol.get(str(result_key))
            if not symbol or not isinstance(row, dict):
                continue
            close = row.get("c") or []
            volume = row.get("v") or []
            bid = row.get("b") or []
            ask = row.get("a") or []
            high = row.get("h") or []
            low = row.get("l") or []
            if not close:
                continue
            price = _finite(close[0])
            if price <= 0:
                continue
            cumulative = _finite(volume[0]) if volume else 0.0
            bid_price = _finite(bid[0]) if bid else 0.0
            ask_price = _finite(ask[0]) if ask else 0.0
            if bid_price > 0:
                self.last_bid[symbol] = bid_price
            if ask_price > 0:
                self.last_ask[symbol] = ask_price
            if bid_price > 0 and ask_price >= bid_price:
                mid = (bid_price + ask_price) / 2.0
                self.last_spread_bps[symbol] = ((ask_price - bid_price) / max(mid, 1e-12)) * 10000.0
            open_24h = _finite(row.get("o"))
            if open_24h > 0:
                self.last_24h_open[symbol] = open_24h
            high_24h = _finite(high[0]) if high else 0.0
            low_24h = _finite(low[0]) if low else 0.0
            if high_24h > 0:
                self.last_24h_high[symbol] = high_24h
            if low_24h > 0:
                self.last_24h_low[symbol] = low_24h
            if cumulative > 0:
                self.last_24h_volume[symbol] = cumulative
            previous_cumulative = self.last_cumulative_volume.get(symbol)
            if seed_only or previous_cumulative is None:
                delta_volume = 0.0
            else:
                delta_volume = max(0.0, cumulative - previous_cumulative)
            self.last_cumulative_volume[symbol] = cumulative
            if self.last_prices.get(symbol) != price or delta_volume > 0.0:
                updated += 1
            self.last_prices[symbol] = price
            incremental_volume[symbol] = delta_volume

        return dict(self.last_prices), incremental_volume, updated

    def poll(self) -> tuple[dict[str, float], dict[str, float], dict[str, Any]]:
        result = self._ticker_result()
        prices, volumes, updated = self._consume_ticker(result, seed_only=False)
        return prices, volumes, {
            "ticker_pairs": len(result),
            "tracked_pairs": len(prices),
            "updated_pairs": updated,
            "spread_bps": dict(self.last_spread_bps),
            "transport": "kraken_public_multi_pair_ticker",
        }

class LiveStreakLab:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.run_id = f"streak-live-{uuid.uuid4().hex[:12]}"
        self.rng = random.Random(args.seed)
        self.feed = KrakenPublicFeed(args.symbols)
        self.series = {symbol: SeriesState() for symbol in args.symbols}
        self.wallets = {
            item["id"]: PaperWallet(float(args.start_usd), peak_equity_usd=float(args.start_usd))
            for item in MUTATIONS
        }
        self.last_prices: dict[str, float] = {}
        self.conn = self._open_database(Path(args.database))
        self._write_registry()

    def _open_database(self, path: Path) -> sqlite3.Connection:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS live_streak_runs(
              run_id TEXT PRIMARY KEY, started_ts REAL, ended_ts REAL, schema TEXT,
              authority TEXT, exchange TEXT, symbols_json TEXT, config_json TEXT, status TEXT);
            CREATE TABLE IF NOT EXISTS mutation_registry(
              run_id TEXT, mutation_id TEXT, kind TEXT, description TEXT,
              PRIMARY KEY(run_id, mutation_id));
            CREATE TABLE IF NOT EXISTS live_market_ticks(
              run_id TEXT, ts REAL, symbol TEXT, price REAL, total_volume REAL,
              inferred_regime TEXT, regime_confidence REAL, fetch_latency_ms REAL,
              PRIMARY KEY(run_id, ts, symbol));
            CREATE TABLE IF NOT EXISTS live_worker_votes(
              run_id TEXT, ts REAL, symbol TEXT, worker_id TEXT, family TEXT,
              action TEXT, vote INTEGER, strength REAL, note TEXT, worker_ready INTEGER,
              PRIMARY KEY(run_id, ts, symbol, worker_id));
            CREATE TABLE IF NOT EXISTS live_wallet_marks(
              run_id TEXT, mutation_id TEXT, ts REAL, equity_usd REAL, cash_usd REAL,
              open_positions INTEGER, cumulative_cost_usd REAL, cycle_latency_ms REAL,
              PRIMARY KEY(run_id, mutation_id, ts));
            CREATE TABLE IF NOT EXISTS live_paper_actions(
              run_id TEXT, mutation_id TEXT, ts REAL, symbol TEXT, action TEXT,
              price REAL, notional_usd REAL, cost_usd REAL, reason TEXT,
              votes_json TEXT, regime_json TEXT);
            CREATE TABLE IF NOT EXISTS live_streak_events(
              run_id TEXT, mutation_id TEXT, ts REAL, event TEXT, equity_usd REAL,
              delta_1s_usd REAL, delta_3s_usd REAL, delta_5s_usd REAL, delta_10s_usd REAL,
              detector_latency_ms REAL, context_json TEXT);
            CREATE INDEX IF NOT EXISTS idx_live_ticks_run_ts ON live_market_ticks(run_id, ts);
            CREATE INDEX IF NOT EXISTS idx_live_votes_run_symbol ON live_worker_votes(run_id, symbol, ts);
            CREATE INDEX IF NOT EXISTS idx_live_actions_run_mutation ON live_paper_actions(run_id, mutation_id, ts);
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO live_streak_runs VALUES (?,?,?,?,?,?,?,?,?)",
            (self.run_id, time.time(), None, SCHEMA, AUTHORITY, "kraken_public_posttrade",
             json.dumps(self.args.symbols), json.dumps(vars(self.args), sort_keys=True), "RUNNING"),
        )
        conn.commit()
        return conn

    def _write_registry(self) -> None:
        for item in MUTATIONS:
            self.conn.execute(
                "INSERT OR REPLACE INTO mutation_registry VALUES (?,?,?,?)",
                (self.run_id, item["id"], item["kind"], item["description"]),
            )
        self.conn.commit()

    def warm_start(self) -> None:
        print(f"[{self.run_id}] warming actual Phoenix workers from public Kraken trades; no API key")
        seeded = self.feed.seed_prices()
        self.last_prices.update(seeded)
        for symbol in self.args.symbols:
            warmed = 0
            api_symbol = self.feed.api_pairs.get(symbol, symbol)
            try:
                trades = self.feed.recent_trades(api_symbol, count=80)
            except Exception as exc:
                print(f"  WARN {symbol}: trade warmup failed: {type(exc).__name__}: {exc}")
                trades = []
            state = self.series[symbol]
            for trade in trades[-80:]:
                state.add(trade["price"], trade["quantity"])
                warmed += 1
            if not warmed:
                price = seeded.get(symbol)
                if price:
                    state.add(price, 0.0)
            latest = seeded.get(symbol)
            print(f"  {symbol}: warm_samples={warmed} latest={latest}")

    def _worker_votes(self, symbol: str, ts: float) -> dict[str, int]:
        state = self.series[symbol]
        closes, volumes = list(state.prices), list(state.volumes)
        latest = closes[-1] if closes else 0.0
        votes: dict[str, int] = {}
        for worker_id, family, worker in WORKERS:
            ready, action, strength, note = True, "HOLD", 0.0, ""
            try:
                proposal = worker.propose(closes, volumes=volumes, latest_price=latest)
                action = str(proposal.get("action") or "HOLD").upper()
                strength = _finite(proposal.get("signal_strength"))
                note = str(proposal.get("notes") or "")[:240]
                low = note.lower()
                if "not enough" in low or "no rsi data" in low or "unavailable" in low:
                    ready = False
            except Exception as exc:
                ready, note = False, f"{type(exc).__name__}:{exc}"[:240]
            vote = 1 if action == "BUY" else -1 if action == "SELL" else 0
            votes[worker_id] = vote
            self.conn.execute(
                "INSERT OR REPLACE INTO live_worker_votes VALUES (?,?,?,?,?,?,?,?,?,?)",
                (self.run_id, ts, symbol, worker_id, family, action, vote, strength, note, int(ready)),
            )
        return votes

    def _admit(self, mutation_id: str, votes: dict[str, int], regime: dict[str, Any]) -> tuple[bool, float, str]:
        pos = sum(v > 0 for v in votes.values())
        neg = sum(v < 0 for v in votes.values())
        score = (pos - neg) / max(1, len(votes))
        if mutation_id == "raw_streak":
            return True, score, "raw_persistence"
        if mutation_id == "majority5":
            return pos >= 5, score, f"positive_votes={pos}"
        if mutation_id == "vol_breakout_pair":
            ok = votes.get("vol_expansion", 0) > 0 and votes.get("breakout", 0) > 0
            return ok, score, "vol_expansion+breakout"
        if mutation_id == "inferred_regime":
            label = str(regime.get("label") or "mixed")
            need = 4 if label == "bursty" else 6 if label in {"noise", "meanrev"} else 5
            return pos >= need, score, f"regime={label};need={need};positive={pos}"
        if mutation_id == "entropy_gate":
            ent = _entropy(pos, neg)
            return pos >= 4 and ent <= 0.72, score, f"entropy={ent:.4f};positive={pos}"
        if mutation_id == "no_vol_worker":
            reduced = {k: v for k, v in votes.items() if k != "vol_expansion"}
            rpos = sum(v > 0 for v in reduced.values())
            rneg = sum(v < 0 for v in reduced.values())
            return rpos >= 5, (rpos - rneg) / max(1, len(reduced)), f"vol_ablation;positive={rpos}"
        if mutation_id == "no_reversion_workers":
            keep = ("sma", "breakout", "momentum", "supertrend", "vol_expansion")
            rpos = sum(votes.get(k, 0) > 0 for k in keep)
            rneg = sum(votes.get(k, 0) < 0 for k in keep)
            return rpos >= 4, (rpos - rneg) / len(keep), f"no_reversion;positive={rpos}"
        if mutation_id == "random30":
            return self.rng.random() < 0.30, 0.0, "matched_random_30pct"
        return False, score, "unknown"

    def _candidate(self, state: SeriesState) -> tuple[bool, dict[str, float]]:
        r1, r3, r5 = state.ret(1) * 10000.0, state.ret(3) * 10000.0, state.ret(5) * 10000.0
        min3 = max(float(self.args.confirm_3s_bps), float(self.args.cost_bps_side) * 0.50)
        min5 = max(float(self.args.persist_5s_bps), float(self.args.cost_bps_side))
        return (
            r1 > self.args.spark_1s_bps and r3 > min3 and r5 > min5,
            {"r1_bps": r1, "r3_bps": r3, "r5_bps": r5},
        )

    def _buy(self, mid: str, symbol: str, price: float, ts: float, votes: dict[str, int], regime: dict[str, Any], reason: str) -> None:
        w = self.wallets[mid]
        if symbol in w.positions or len(w.positions) >= self.args.max_positions:
            return
        notional = min(self.args.notional_usd, w.cash)
        cost = notional * self.args.cost_bps_side / 10000.0
        if notional <= cost or notional < 0.01:
            return
        w.positions[symbol] = Position((notional - cost) / price, price, price, ts)
        w.cash -= notional
        w.cumulative_cost_usd += cost
        w.actions += 1
        self.conn.execute(
            "INSERT INTO live_paper_actions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (self.run_id, mid, ts, symbol, "BUY", price, notional, cost, reason,
             json.dumps(votes, sort_keys=True), json.dumps(regime, sort_keys=True)),
        )

    def _sell(self, mid: str, symbol: str, price: float, ts: float, votes: dict[str, int], regime: dict[str, Any], reason: str) -> None:
        w = self.wallets[mid]
        pos = w.positions.get(symbol)
        if pos is None:
            return
        gross = pos.qty * price
        cost = gross * self.args.cost_bps_side / 10000.0
        w.cash += gross - cost
        w.cumulative_cost_usd += cost
        w.actions += 1
        del w.positions[symbol]
        self.conn.execute(
            "INSERT INTO live_paper_actions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (self.run_id, mid, ts, symbol, "SELL", price, gross, cost, reason,
             json.dumps(votes, sort_keys=True), json.dumps(regime, sort_keys=True)),
        )

    def cycle(self) -> None:
        cycle_started = time.perf_counter()
        fetch_started = time.perf_counter()
        prices, volumes, feed_meta = self.feed.poll()
        fetch_ms = (time.perf_counter() - fetch_started) * 1000.0
        self.last_prices.update(prices)
        ts = time.time()

        votes_by_symbol: dict[str, dict[str, int]] = {}
        regimes: dict[str, dict[str, Any]] = {}
        candidates: dict[str, tuple[bool, dict[str, float]]] = {}

        for symbol in self.args.symbols:
            price = self.last_prices.get(symbol)
            if not price:
                continue
            self.series[symbol].add(price, volumes.get(symbol, 0.0))
            regime = self.series[symbol].regime()
            regimes[symbol] = regime
            candidates[symbol] = self._candidate(self.series[symbol])
            votes_by_symbol[symbol] = self._worker_votes(symbol, ts)
            self.conn.execute(
                "INSERT OR REPLACE INTO live_market_ticks VALUES (?,?,?,?,?,?,?,?)",
                (self.run_id, ts, symbol, price, volumes.get(symbol, 0.0),
                 regime.get("label"), regime.get("confidence"), fetch_ms),
            )

        for item in MUTATIONS:
            mid, w = item["id"], self.wallets[item["id"]]
            for symbol, pos in list(w.positions.items()):
                price = self.last_prices.get(symbol)
                if not price:
                    continue
                pos.peak_price = max(pos.peak_price, price)
                state = self.series[symbol]
                r1, r3 = state.ret(1) * 10000.0, state.ret(3) * 10000.0
                retrace = (price / pos.peak_price - 1.0) * 10000.0 if pos.peak_price > 0 else 0.0
                votes = votes_by_symbol.get(symbol, {})
                neg = sum(v < 0 for v in votes.values())
                exhaustion = r1 < -self.args.exit_1s_bps and r3 < 0 and neg >= 3
                hard_retrace = retrace <= -self.args.max_retracement_bps
                stale = ts - pos.entry_ts >= self.args.max_hold_sec
                if exhaustion or hard_retrace or stale:
                    reason = "worker_exhaustion" if exhaustion else "peak_retracement" if hard_retrace else "max_hold"
                    self._sell(mid, symbol, price, ts, votes, regimes.get(symbol, {}), reason)

            for symbol, (candidate, movement) in candidates.items():
                if not candidate or symbol in w.positions:
                    continue
                votes, regime = votes_by_symbol.get(symbol, {}), regimes.get(symbol, {})
                admit, _, why = self._admit(mid, votes, regime)
                if admit:
                    self._buy(
                        mid, symbol, self.last_prices[symbol], ts, votes, regime,
                        f"streak_candidate;{why};movement={json.dumps(movement, sort_keys=True)}",
                    )

        cycle_ms = (time.perf_counter() - cycle_started) * 1000.0
        for item in MUTATIONS:
            mid, w = item["id"], self.wallets[item["id"]]
            equity = w.equity(self.last_prices, self.args.cost_bps_side)
            w.peak_equity_usd = max(w.peak_equity_usd, equity)
            self.conn.execute(
                "INSERT OR REPLACE INTO live_wallet_marks VALUES (?,?,?,?,?,?,?,?)",
                (self.run_id, mid, ts, equity, w.cash, len(w.positions), w.cumulative_cost_usd, cycle_ms),
            )
            rows = self.conn.execute(
                "SELECT ts,equity_usd FROM live_wallet_marks WHERE run_id=? AND mutation_id=? AND ts>=? ORDER BY ts",
                (self.run_id, mid, ts - 12.0),
            ).fetchall()
            def prior(delta: float) -> float | None:
                eligible = [row for row in rows if float(row[0]) <= ts - delta]
                return float(eligible[-1][1]) if eligible else None
            deltas = {}
            for h in (1, 3, 5, 10):
                before = prior(h)
                deltas[h] = equity - before if before is not None else 0.0
            if deltas[1] > 0 and deltas[3] > 0:
                self.conn.execute(
                    "INSERT INTO live_streak_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (self.run_id, mid, ts, "STREAK_SPARK", equity, deltas[1], deltas[3], deltas[5], deltas[10],
                     cycle_ms, json.dumps({"open_positions": list(w.positions), "feed": feed_meta, "authority": AUTHORITY}, sort_keys=True)),
                )

        self.conn.commit()
        if self.args.verbose or int(ts) % max(1, self.args.report_every_sec) == 0:
            self.print_status(fetch_ms, cycle_ms, feed_meta)

    def print_status(self, fetch_ms: float, cycle_ms: float, feed_meta: dict[str, Any]) -> None:
        print(
            f"\n[{time.strftime('%H:%M:%S')}] fetch={fetch_ms:.0f}ms cycle={cycle_ms:.0f}ms "
            f"updated_pairs={feed_meta.get('updated_pairs', 0)} authority={AUTHORITY}"
        )
        for item in MUTATIONS:
            mid, w = item["id"], self.wallets[item["id"]]
            equity = w.equity(self.last_prices, self.args.cost_bps_side)
            print(
                f"  {mid:22s} equity={equity:10.4f} net={equity-self.args.start_usd:+8.4f} "
                f"cost={w.cumulative_cost_usd:7.4f} actions={w.actions:4d} open={len(w.positions)}"
            )

    def close(self, status: str) -> None:
        ts = time.time()
        for item in MUTATIONS:
            mid, w = item["id"], self.wallets[item["id"]]
            for symbol in list(w.positions):
                price = self.last_prices.get(symbol)
                if price:
                    self._sell(mid, symbol, price, ts, {}, self.series[symbol].regime(), "lab_end_liquidation")
        self.conn.execute("UPDATE live_streak_runs SET ended_ts=?,status=? WHERE run_id=?", (time.time(), status, self.run_id))
        self.conn.commit()
        self.print_status(0.0, 0.0, {"updated_pairs": 0})
        print(f"SQLite: {self.args.database}\nrun_id: {self.run_id}\nPRIVATE ORDERS: 0")
        self.conn.close()

    def run(self) -> int:
        self.warm_start()
        print(
            f"Starting {self.args.duration_sec}s Kraken PUBLIC trade-stream lab at ~{self.args.interval_sec:.2f}s cadence. "
            "No CCXT. No API keys. No orders."
        )
        deadline = time.monotonic() + self.args.duration_sec
        status = "COMPLETE"
        try:
            while time.monotonic() < deadline:
                started = time.monotonic()
                try:
                    self.cycle()
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
                    print(f"WARN public feed cycle: {type(exc).__name__}: {exc}")
                time.sleep(max(0.0, self.args.interval_sec - (time.monotonic() - started)))
        except KeyboardInterrupt:
            status = "INTERRUPTED"
        finally:
            self.close(status)
        return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stdlib-only live public Kraken Phoenix profit-streak swarm lab")
    p.add_argument("--symbols", nargs="+", default=["BTC/USD","ETH/USD","SOL/USD","XRP/USD","ADA/USD","AVAX/USD","DOGE/USD","HYPE/USD"])
    p.add_argument("--database", default="data/live_profit_streak_lab.db")
    p.add_argument("--duration-sec", type=int, default=900)
    p.add_argument("--interval-sec", type=float, default=1.0)
    p.add_argument("--start-usd", type=float, default=1000.0)
    p.add_argument("--notional-usd", type=float, default=25.0)
    p.add_argument("--cost-bps-side", type=float, default=4.0)
    p.add_argument("--max-positions", type=int, default=3)
    p.add_argument("--spark-1s-bps", type=float, default=0.5)
    p.add_argument("--confirm-3s-bps", type=float, default=2.0)
    p.add_argument("--persist-5s-bps", type=float, default=4.0)
    p.add_argument("--exit-1s-bps", type=float, default=1.0)
    p.add_argument("--max-retracement-bps", type=float, default=12.0)
    p.add_argument("--max-hold-sec", type=float, default=90.0)
    p.add_argument("--report-every-sec", type=int, default=10)
    p.add_argument("--seed", type=int, default=20260918)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    if args.interval_sec < 0.8:
        p.error("--interval-sec must be >= 0.8")
    if args.duration_sec < 30:
        p.error("--duration-sec must be >= 30")
    return args


if __name__ == "__main__":
    raise SystemExit(LiveStreakLab(parse_args()).run())
