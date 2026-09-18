#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sqlite3
import statistics
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import ccxt

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

SCHEMA = "hivenance_live_profit_streak_swarm_lab_v1"
AUTHORITY = "PUBLIC_MARKET_PAPER_ONLY_NO_PRIVATE_KEYS_NO_ORDERS"

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
    {
        "id": "raw_streak",
        "description": "No worker gate. Cost-aware price persistence alone.",
        "kind": "control",
    },
    {
        "id": "majority5",
        "description": "Require five of eight Phoenix workers to support the direction.",
        "kind": "swarm",
    },
    {
        "id": "vol_breakout_pair",
        "description": "Require VolatilityExpansion and Breakout support together.",
        "kind": "ablation_pair",
    },
    {
        "id": "inferred_regime",
        "description": "Dynamic worker threshold from online regime inference; never oracle-labelled.",
        "kind": "regime_swarm",
    },
    {
        "id": "entropy_gate",
        "description": "Require directional majority plus low vote entropy.",
        "kind": "diversity",
    },
    {
        "id": "no_vol_worker",
        "description": "Five-vote coalition with VolatilityExpansion removed.",
        "kind": "worker_ablation",
    },
    {
        "id": "no_reversion_workers",
        "description": "Trend/breakout/momentum families only; require four of five.",
        "kind": "family_ablation",
    },
    {
        "id": "random30",
        "description": "Randomly admit 30 percent of otherwise-valid streak candidates.",
        "kind": "matched_random_control",
    },
)


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
    x = values[:-1]
    y = values[1:]
    mx = statistics.mean(x)
    my = statistics.mean(y)
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
    last_total_volume: float | None = None

    def add(self, price: float, total_volume: float | None = None) -> None:
        incremental = 0.0
        if total_volume is not None and self.last_total_volume is not None:
            incremental = max(0.0, total_volume - self.last_total_volume)
        self.last_total_volume = total_volume if total_volume is not None else self.last_total_volume
        self.prices.append(price)
        self.volumes.append(incremental)

    def ret(self, seconds: int) -> float:
        if len(self.prices) <= seconds:
            return 0.0
        start = list(self.prices)[-(seconds + 1)]
        end = self.prices[-1]
        return (end / start - 1.0) if start > 0 else 0.0

    def regime(self) -> dict[str, Any]:
        p = list(self.prices)
        if len(p) < 12:
            return {"label": "warming", "confidence": 0.0}
        rets = [(p[i] / p[i - 1] - 1.0) for i in range(1, len(p)) if p[i - 1] > 0]
        short = rets[-5:]
        base = rets[-30:] if len(rets) >= 30 else rets
        short_vol = _std(short)
        base_vol = _std(base)
        vol_ratio = short_vol / max(base_vol, 1e-12)
        signs = [1 if r > 0 else -1 if r < 0 else 0 for r in short]
        persistence = abs(sum(signs)) / max(1, len(signs))
        autocorr = _lag1_autocorr(base)
        move5_bps = self.ret(5) * 10000.0
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
            label = "mixed"
            confidence = 0.50
        return {
            "label": label,
            "confidence": round(confidence, 6),
            "vol_ratio": round(vol_ratio, 6),
            "persistence": round(persistence, 6),
            "lag1_autocorr": round(autocorr, 6),
            "move5_bps": round(move5_bps, 6),
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
            hypothetical_exit_cost = gross * exit_cost_bps_side / 10000.0
            value += gross - hypothetical_exit_cost
        return value


class LiveStreakLab:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.run_id = f"streak-live-{uuid.uuid4().hex[:12]}"
        self.rng = random.Random(args.seed)
        self.exchange = ccxt.kraken({"enableRateLimit": True, "timeout": 8000})
        # Deliberately do not read API keys from environment.
        self.exchange.apiKey = ""
        self.exchange.secret = ""
        self.series = {symbol: SeriesState() for symbol in args.symbols}
        self.wallets = {
            mutation["id"]: PaperWallet(cash=float(args.start_usd), peak_equity_usd=float(args.start_usd))
            for mutation in MUTATIONS
        }
        self.vote_history: dict[str, deque[dict[str, int]]] = {
            symbol: deque(maxlen=20) for symbol in args.symbols
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
            CREATE TABLE IF NOT EXISTS live_streak_runs (
                run_id TEXT PRIMARY KEY,
                started_ts REAL,
                ended_ts REAL,
                schema TEXT,
                authority TEXT,
                exchange TEXT,
                symbols_json TEXT,
                config_json TEXT,
                status TEXT
            );
            CREATE TABLE IF NOT EXISTS mutation_registry (
                run_id TEXT,
                mutation_id TEXT,
                kind TEXT,
                description TEXT,
                PRIMARY KEY(run_id, mutation_id)
            );
            CREATE TABLE IF NOT EXISTS live_market_ticks (
                run_id TEXT,
                ts REAL,
                symbol TEXT,
                price REAL,
                total_volume REAL,
                inferred_regime TEXT,
                regime_confidence REAL,
                fetch_latency_ms REAL,
                PRIMARY KEY(run_id, ts, symbol)
            );
            CREATE TABLE IF NOT EXISTS live_worker_votes (
                run_id TEXT,
                ts REAL,
                symbol TEXT,
                worker_id TEXT,
                family TEXT,
                action TEXT,
                vote INTEGER,
                strength REAL,
                note TEXT,
                worker_ready INTEGER,
                PRIMARY KEY(run_id, ts, symbol, worker_id)
            );
            CREATE TABLE IF NOT EXISTS live_wallet_marks (
                run_id TEXT,
                mutation_id TEXT,
                ts REAL,
                equity_usd REAL,
                cash_usd REAL,
                open_positions INTEGER,
                cumulative_cost_usd REAL,
                cycle_latency_ms REAL,
                PRIMARY KEY(run_id, mutation_id, ts)
            );
            CREATE TABLE IF NOT EXISTS live_paper_actions (
                run_id TEXT,
                mutation_id TEXT,
                ts REAL,
                symbol TEXT,
                action TEXT,
                price REAL,
                notional_usd REAL,
                cost_usd REAL,
                reason TEXT,
                votes_json TEXT,
                regime_json TEXT
            );
            CREATE TABLE IF NOT EXISTS live_streak_events (
                run_id TEXT,
                mutation_id TEXT,
                ts REAL,
                event TEXT,
                equity_usd REAL,
                delta_1s_usd REAL,
                delta_3s_usd REAL,
                delta_5s_usd REAL,
                delta_10s_usd REAL,
                detector_latency_ms REAL,
                context_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_live_ticks_run_ts ON live_market_ticks(run_id, ts);
            CREATE INDEX IF NOT EXISTS idx_live_votes_run_symbol ON live_worker_votes(run_id, symbol, ts);
            CREATE INDEX IF NOT EXISTS idx_live_actions_run_mutation ON live_paper_actions(run_id, mutation_id, ts);
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO live_streak_runs VALUES (?,?,?,?,?,?,?,?,?)",
            (
                self.run_id,
                time.time(),
                None,
                SCHEMA,
                AUTHORITY,
                "kraken_public",
                json.dumps(self.args.symbols),
                json.dumps(vars(self.args), sort_keys=True, default=str),
                "RUNNING",
            ),
        )
        conn.commit()
        return conn

    def _write_registry(self) -> None:
        for mutation in MUTATIONS:
            self.conn.execute(
                "INSERT OR REPLACE INTO mutation_registry VALUES (?,?,?,?)",
                (self.run_id, mutation["id"], mutation["kind"], mutation["description"]),
            )
        self.conn.commit()

    def warm_start(self) -> None:
        print(f"[{self.run_id}] public-only warm start for {len(self.args.symbols)} symbols")
        for symbol in self.args.symbols:
            try:
                trades = self.exchange.fetch_trades(symbol, limit=80)
            except Exception as exc:
                print(f"WARN warm-start {symbol}: {type(exc).__name__}: {exc}")
                continue
            state = self.series[symbol]
            for trade in trades[-80:]:
                price = _finite(trade.get("price"))
                amount = _finite(trade.get("amount"))
                if price > 0:
                    state.prices.append(price)
                    state.volumes.append(max(0.0, amount))
            print(f"  {symbol}: {len(state.prices)} public trade samples")

    def _worker_votes(self, symbol: str, ts: float) -> dict[str, int]:
        state = self.series[symbol]
        closes = list(state.prices)
        volumes = list(state.volumes)
        latest = closes[-1] if closes else 0.0
        votes: dict[str, int] = {}
        for worker_id, family, worker in WORKERS:
            ready = True
            action = "HOLD"
            strength = 0.0
            note = ""
            try:
                proposal = worker.propose(closes, volumes=volumes, latest_price=latest)
                action = str(proposal.get("action") or "HOLD").upper()
                strength = _finite(proposal.get("signal_strength"))
                note = str(proposal.get("notes") or "")[:240]
                if "Not enough" in note or "No " in note and "data" in note.lower():
                    ready = False
            except Exception as exc:
                ready = False
                note = f"{type(exc).__name__}:{exc}"[:240]
            vote = 1 if action == "BUY" else -1 if action == "SELL" else 0
            votes[worker_id] = vote
            self.conn.execute(
                "INSERT OR REPLACE INTO live_worker_votes VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    self.run_id, ts, symbol, worker_id, family, action, vote,
                    strength, note, 1 if ready else 0,
                ),
            )
        self.vote_history[symbol].append(dict(votes))
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
            rscore = (rpos - rneg) / max(1, len(reduced))
            return rpos >= 5, rscore, f"vol_ablation;positive={rpos}"
        if mutation_id == "no_reversion_workers":
            keep = ("sma", "breakout", "momentum", "supertrend", "vol_expansion")
            rpos = sum(votes.get(k, 0) > 0 for k in keep)
            rneg = sum(votes.get(k, 0) < 0 for k in keep)
            rscore = (rpos - rneg) / len(keep)
            return rpos >= 4, rscore, f"no_reversion;positive={rpos}"
        if mutation_id == "random30":
            return self.rng.random() < 0.30, 0.0, "matched_random_30pct"
        return False, score, "unknown_mutation"

    def _candidate(self, state: SeriesState) -> tuple[bool, dict[str, float]]:
        r1 = state.ret(1) * 10000.0
        r3 = state.ret(3) * 10000.0
        r5 = state.ret(5) * 10000.0
        # Detection is intentionally fast, but admission remains cost-aware.
        min1 = float(self.args.spark_1s_bps)
        min3 = max(float(self.args.confirm_3s_bps), float(self.args.cost_bps_side) * 0.50)
        min5 = max(float(self.args.persist_5s_bps), float(self.args.cost_bps_side))
        candidate = r1 > min1 and r3 > min3 and r5 > min5
        return candidate, {"r1_bps": r1, "r3_bps": r3, "r5_bps": r5}

    def _paper_buy(
        self,
        mutation_id: str,
        symbol: str,
        price: float,
        ts: float,
        votes: dict[str, int],
        regime: dict[str, Any],
        reason: str,
    ) -> None:
        wallet = self.wallets[mutation_id]
        if symbol in wallet.positions or len(wallet.positions) >= self.args.max_positions:
            return
        notional = min(float(self.args.notional_usd), wallet.cash)
        cost = notional * float(self.args.cost_bps_side) / 10000.0
        if notional <= cost or notional < 0.01:
            return
        qty = (notional - cost) / price
        wallet.cash -= notional
        wallet.cumulative_cost_usd += cost
        wallet.positions[symbol] = Position(qty=qty, entry_price=price, peak_price=price, entry_ts=ts)
        wallet.actions += 1
        self.conn.execute(
            "INSERT INTO live_paper_actions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                self.run_id, mutation_id, ts, symbol, "BUY", price, notional, cost,
                reason, json.dumps(votes, sort_keys=True), json.dumps(regime, sort_keys=True),
            ),
        )

    def _paper_sell(
        self,
        mutation_id: str,
        symbol: str,
        price: float,
        ts: float,
        votes: dict[str, int],
        regime: dict[str, Any],
        reason: str,
    ) -> None:
        wallet = self.wallets[mutation_id]
        pos = wallet.positions.get(symbol)
        if pos is None:
            return
        gross = pos.qty * price
        cost = gross * float(self.args.cost_bps_side) / 10000.0
        wallet.cash += gross - cost
        wallet.cumulative_cost_usd += cost
        wallet.actions += 1
        del wallet.positions[symbol]
        self.conn.execute(
            "INSERT INTO live_paper_actions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                self.run_id, mutation_id, ts, symbol, "SELL", price, gross, cost,
                reason, json.dumps(votes, sort_keys=True), json.dumps(regime, sort_keys=True),
            ),
        )

    def cycle(self) -> None:
        cycle_started = time.perf_counter()
        fetch_started = time.perf_counter()
        tickers = self.exchange.fetch_tickers(self.args.symbols)
        fetch_latency_ms = (time.perf_counter() - fetch_started) * 1000.0
        ts = time.time()

        votes_by_symbol: dict[str, dict[str, int]] = {}
        regimes: dict[str, dict[str, Any]] = {}
        candidates: dict[str, tuple[bool, dict[str, float]]] = {}

        for symbol in self.args.symbols:
            ticker = tickers.get(symbol) or {}
            price = _finite(ticker.get("last") or ticker.get("close"))
            if price <= 0:
                continue
            total_volume = _finite(ticker.get("baseVolume"), default=0.0)
            state = self.series[symbol]
            state.add(price, total_volume)
            self.last_prices[symbol] = price
            regime = state.regime()
            regimes[symbol] = regime
            candidate = self._candidate(state)
            candidates[symbol] = candidate
            votes = self._worker_votes(symbol, ts)
            votes_by_symbol[symbol] = votes
            self.conn.execute(
                "INSERT OR REPLACE INTO live_market_ticks VALUES (?,?,?,?,?,?,?,?)",
                (
                    self.run_id, ts, symbol, price, total_volume,
                    regime.get("label"), regime.get("confidence"), fetch_latency_ms,
                ),
            )

        for mutation in MUTATIONS:
            mid = mutation["id"]
            wallet = self.wallets[mid]

            # First update/exit existing positions. Workers inform exhaustion;
            # the wallet remains the accounting authority.
            for symbol, pos in list(wallet.positions.items()):
                price = self.last_prices.get(symbol)
                if price is None:
                    continue
                pos.peak_price = max(pos.peak_price, price)
                state = self.series[symbol]
                r1 = state.ret(1) * 10000.0
                r3 = state.ret(3) * 10000.0
                r5 = state.ret(5) * 10000.0
                retracement_bps = (price / pos.peak_price - 1.0) * 10000.0 if pos.peak_price > 0 else 0.0
                votes = votes_by_symbol.get(symbol, {})
                neg = sum(v < 0 for v in votes.values())
                exhaustion = r1 < -self.args.exit_1s_bps and r3 < 0 and neg >= 3
                hard_retrace = retracement_bps <= -float(self.args.max_retracement_bps)
                stale = (ts - pos.entry_ts) >= float(self.args.max_hold_sec)
                if exhaustion or hard_retrace or stale:
                    why = (
                        "worker_exhaustion" if exhaustion
                        else "peak_retracement" if hard_retrace
                        else "max_hold"
                    )
                    self._paper_sell(
                        mid, symbol, price, ts, votes,
                        regimes.get(symbol, {}), why,
                    )

            # Admit new candidates after exits.
            for symbol, (is_candidate, movement) in candidates.items():
                if not is_candidate or symbol in wallet.positions:
                    continue
                votes = votes_by_symbol.get(symbol, {})
                regime = regimes.get(symbol, {})
                admit, score, why = self._admit(mid, votes, regime)
                if admit:
                    self._paper_buy(
                        mid, symbol, self.last_prices[symbol], ts,
                        votes, regime,
                        f"streak_candidate;{why};movement={json.dumps(movement, sort_keys=True)}",
                    )

        cycle_latency_ms = (time.perf_counter() - cycle_started) * 1000.0

        # Wallet marks and portfolio-level streak evidence.
        for mutation in MUTATIONS:
            mid = mutation["id"]
            wallet = self.wallets[mid]
            equity = wallet.equity(self.last_prices, float(self.args.cost_bps_side))
            wallet.peak_equity_usd = max(wallet.peak_equity_usd, equity)
            self.conn.execute(
                "INSERT OR REPLACE INTO live_wallet_marks VALUES (?,?,?,?,?,?,?,?)",
                (
                    self.run_id, mid, ts, equity, wallet.cash, len(wallet.positions),
                    wallet.cumulative_cost_usd, cycle_latency_ms,
                ),
            )
            rows = self.conn.execute(
                """
                SELECT ts, equity_usd FROM live_wallet_marks
                WHERE run_id=? AND mutation_id=? AND ts>=?
                ORDER BY ts ASC
                """,
                (self.run_id, mid, ts - 12.0),
            ).fetchall()
            if len(rows) >= 2:
                def prior(delta: float) -> float | None:
                    target = ts - delta
                    eligible = [row for row in rows if float(row[0]) <= target]
                    return float(eligible[-1][1]) if eligible else None
                deltas = {}
                for horizon in (1, 3, 5, 10):
                    before = prior(float(horizon))
                    deltas[horizon] = (equity - before) if before is not None else 0.0
                if deltas[1] > 0 and deltas[3] > 0:
                    self.conn.execute(
                        "INSERT INTO live_streak_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            self.run_id, mid, ts, "STREAK_SPARK", equity,
                            deltas[1], deltas[3], deltas[5], deltas[10],
                            cycle_latency_ms,
                            json.dumps({
                                "open_positions": list(wallet.positions),
                                "authority": AUTHORITY,
                                "cycle_latency_ms": cycle_latency_ms,
                            }, sort_keys=True),
                        ),
                    )

        self.conn.commit()
        if self.args.verbose or int(ts) % max(1, int(self.args.report_every_sec)) == 0:
            self.print_status(ts, fetch_latency_ms, cycle_latency_ms)

    def print_status(self, ts: float, fetch_ms: float, cycle_ms: float) -> None:
        print(
            f"\n[{time.strftime('%H:%M:%S')}] fetch={fetch_ms:.0f}ms cycle={cycle_ms:.0f}ms "
            f"authority={AUTHORITY}"
        )
        for mutation in MUTATIONS:
            mid = mutation["id"]
            wallet = self.wallets[mid]
            equity = wallet.equity(self.last_prices, float(self.args.cost_bps_side))
            print(
                f"  {mid:22s} equity={equity:10.4f} "
                f"net={equity-self.args.start_usd:+8.4f} "
                f"cost={wallet.cumulative_cost_usd:7.4f} "
                f"actions={wallet.actions:4d} open={len(wallet.positions)}"
            )

    def close(self, status: str = "COMPLETE") -> None:
        ts = time.time()
        for mutation in MUTATIONS:
            mid = mutation["id"]
            wallet = self.wallets[mid]
            for symbol in list(wallet.positions):
                price = self.last_prices.get(symbol)
                if price:
                    self._paper_sell(
                        mid, symbol, price, ts,
                        {}, self.series[symbol].regime(), "lab_end_liquidation",
                    )
        self.conn.execute(
            "UPDATE live_streak_runs SET ended_ts=?, status=? WHERE run_id=?",
            (time.time(), status, self.run_id),
        )
        self.conn.commit()
        self.print_final()
        self.conn.close()

    def print_final(self) -> None:
        print("\n=== FINAL PAPER SCORECARD ===")
        for mutation in MUTATIONS:
            mid = mutation["id"]
            wallet = self.wallets[mid]
            equity = wallet.equity(self.last_prices, float(self.args.cost_bps_side))
            print(
                f"{mid:22s} end={equity:.6f} net={equity-self.args.start_usd:+.6f} "
                f"cost={wallet.cumulative_cost_usd:.6f} actions={wallet.actions}"
            )
        print(f"SQLite: {self.args.database}")
        print(f"run_id: {self.run_id}")
        print("PRIVATE ORDERS: 0")

    def run(self) -> int:
        self.warm_start()
        deadline = time.monotonic() + float(self.args.duration_sec)
        print(
            f"Starting {self.args.duration_sec}s live PUBLIC Kraken lab at "
            f"{self.args.interval_sec:.2f}s cadence. No API keys. No orders."
        )
        status = "COMPLETE"
        try:
            while time.monotonic() < deadline:
                started = time.monotonic()
                try:
                    self.cycle()
                except (ccxt.NetworkError, ccxt.ExchangeError) as exc:
                    print(f"WARN cycle: {type(exc).__name__}: {exc}")
                elapsed = time.monotonic() - started
                time.sleep(max(0.0, float(self.args.interval_sec) - elapsed))
        except KeyboardInterrupt:
            status = "INTERRUPTED"
            print("\nInterrupted by operator.")
        finally:
            self.close(status)
        return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Live public-market Phoenix profit-streak swarm lab")
    parser.add_argument(
        "--symbols", nargs="+",
        default=["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "ADA/USD", "AVAX/USD", "DOGE/USD", "HYPE/USD"],
    )
    parser.add_argument("--database", default="data/live_profit_streak_lab.db")
    parser.add_argument("--duration-sec", type=int, default=900)
    parser.add_argument("--interval-sec", type=float, default=1.0)
    parser.add_argument("--start-usd", type=float, default=1000.0)
    parser.add_argument("--notional-usd", type=float, default=25.0)
    parser.add_argument("--cost-bps-side", type=float, default=4.0)
    parser.add_argument("--max-positions", type=int, default=3)
    parser.add_argument("--spark-1s-bps", type=float, default=0.5)
    parser.add_argument("--confirm-3s-bps", type=float, default=2.0)
    parser.add_argument("--persist-5s-bps", type=float, default=4.0)
    parser.add_argument("--exit-1s-bps", type=float, default=1.0)
    parser.add_argument("--max-retracement-bps", type=float, default=12.0)
    parser.add_argument("--max-hold-sec", type=float, default=90.0)
    parser.add_argument("--report-every-sec", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260918)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if args.interval_sec < 0.8:
        parser.error("--interval-sec must be >= 0.8s to avoid abusing the public API")
    if args.duration_sec < 30:
        parser.error("--duration-sec must be >= 30")
    return args


if __name__ == "__main__":
    raise SystemExit(LiveStreakLab(parse_args()).run())
