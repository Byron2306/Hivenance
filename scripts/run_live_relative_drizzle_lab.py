#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import sys
import time
import urllib.error
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_live_profit_streak_swarm import AUTHORITY, WORKERS, KrakenPublicFeed, SeriesState, _finite

LEARNING_AUTHORITY = "research_evidence_only_no_execution_or_promotion_authority"
SCHEMA = "hivenance_relative_drizzle_rotation_v1"
MUTATIONS = (
    "relative_naive",
    "relative_streak",
    "relative_hysteresis",
    "relative_swarm_hysteresis",
)


def js(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def pstdev(values: list[float]) -> float:
    return statistics.pstdev(values) if len(values) >= 2 else 0.0


@dataclass
class PairState:
    ratios: deque[float] = field(default_factory=lambda: deque(maxlen=180))

    def add(self, challenger_price: float, incumbent_price: float) -> None:
        if challenger_price > 0 and incumbent_price > 0:
            self.ratios.append(challenger_price / incumbent_price)

    def ret_bps(self, seconds: int) -> float:
        if len(self.ratios) <= seconds:
            return 0.0
        values = list(self.ratios)
        a, b = values[-(seconds + 1)], values[-1]
        return (b / a - 1.0) * 10000.0 if a > 0 else 0.0

    def zscore(self, window: int = 30) -> float:
        values = list(self.ratios)[-window:]
        if len(values) < max(8, window // 3):
            return 0.0
        mu = mean(values)
        sd = pstdev(values)
        if sd <= 0:
            return 0.0
        return (values[-1] - mu) / sd

    def drawdown_bps(self, window: int = 30) -> float:
        values = list(self.ratios)[-window:]
        if not values:
            return 0.0
        peak = max(values)
        return (values[-1] / peak - 1.0) * 10000.0 if peak > 0 else 0.0


@dataclass
class Holding:
    leg_id: str
    symbol: str
    qty: float
    entry_price_usd: float
    entry_ts: float
    entry_value_usd: float
    entry_context: dict[str, Any]


@dataclass
class Sleeve:
    reserve_cash: float
    holding: Holding | None = None
    cumulative_cost_usd: float = 0.0
    switches: int = 0
    actions: int = 0

    def marked_value(self, prices: dict[str, float]) -> float:
        if self.holding is None:
            return self.reserve_cash
        price = prices.get(self.holding.symbol, self.holding.entry_price_usd)
        return self.reserve_cash + self.holding.qty * price


class RelativeDrizzleLab:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.run_id = f"relative-drizzle-{uuid.uuid4().hex[:12]}"
        self.feed = KrakenPublicFeed(args.symbols)
        self.worker_series = {symbol: SeriesState() for symbol in args.symbols}
        self.live_series = {symbol: SeriesState() for symbol in args.symbols}
        self.pair_states = {
            (a, b): PairState()
            for a in args.symbols
            for b in args.symbols
            if a != b
        }
        self.prices: dict[str, float] = {}
        reserve = float(args.start_usd)
        self.sleeves = {mid: Sleeve(reserve_cash=reserve) for mid in MUTATIONS}
        self.started = {mid: False for mid in MUTATIONS}
        self.conn = sqlite3.connect(args.database)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._schema()

    def _schema(self) -> None:
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS relative_runs(
          run_id TEXT PRIMARY KEY,
          started_ts REAL,
          ended_ts REAL,
          status TEXT,
          schema TEXT,
          authority TEXT,
          learning_authority TEXT,
          config_json TEXT
        );
        CREATE TABLE IF NOT EXISTS relative_pair_scores(
          run_id TEXT,
          mutation_id TEXT,
          ts REAL,
          incumbent TEXT,
          challenger TEXT,
          ratio REAL,
          cheapness_z REAL,
          pair_drawdown_bps REAL,
          relative_1s_bps REAL,
          relative_3s_bps REAL,
          relative_5s_bps REAL,
          relative_10s_bps REAL,
          relative_velocity_bps_sec REAL,
          relative_acceleration_bps_sec REAL,
          streak_persistence REAL,
          worker_support_delta REAL,
          positive_family_delta INTEGER,
          gross_edge_bps REAL,
          switch_cost_bps REAL,
          net_edge_bps REAL,
          admissible INTEGER,
          rank INTEGER,
          context_json TEXT,
          PRIMARY KEY(run_id, mutation_id, ts, incumbent, challenger)
        );
        CREATE TABLE IF NOT EXISTS relative_decisions(
          run_id TEXT,
          mutation_id TEXT,
          ts REAL,
          incumbent TEXT,
          challenger TEXT,
          action TEXT,
          gross_edge_bps REAL,
          net_edge_bps REAL,
          cheapness_z REAL,
          streak_persistence REAL,
          reason TEXT,
          context_json TEXT
        );
        CREATE TABLE IF NOT EXISTS relative_legs(
          leg_id TEXT PRIMARY KEY,
          run_id TEXT,
          mutation_id TEXT,
          symbol TEXT,
          status TEXT,
          entry_ts REAL,
          exit_ts REAL,
          entry_price_usd REAL,
          exit_price_usd REAL,
          entry_value_usd REAL,
          exit_value_usd REAL,
          entry_cost_usd REAL,
          exit_cost_usd REAL,
          net_pnl_usd REAL,
          net_return_bps REAL,
          duration_sec REAL,
          exit_reason TEXT,
          entry_context_json TEXT,
          exit_context_json TEXT
        );
        CREATE TABLE IF NOT EXISTS relative_wallet_marks(
          run_id TEXT,
          mutation_id TEXT,
          ts REAL,
          held_asset TEXT,
          total_equity_usd REAL,
          sleeve_value_usd REAL,
          reserve_cash_usd REAL,
          cumulative_cost_usd REAL,
          switches INTEGER,
          actions INTEGER,
          cycle_latency_ms REAL,
          PRIMARY KEY(run_id, mutation_id, ts)
        );
        CREATE TABLE IF NOT EXISTS relative_learning_crystals(
          crystal_id TEXT PRIMARY KEY,
          run_id TEXT,
          mutation_id TEXT,
          leg_id TEXT,
          crystal_family TEXT,
          scope_key TEXT,
          symbol TEXT,
          evidence_strength REAL,
          net_return_bps REAL,
          duration_sec REAL,
          cheapness_z REAL,
          streak_persistence REAL,
          authority TEXT,
          promotion_state TEXT,
          payload_json TEXT,
          created_ts REAL
        );
        """)
        self.conn.execute(
            "INSERT INTO relative_runs VALUES (?,?,?,?,?,?,?,?)",
            (
                self.run_id, time.time(), None, "RUNNING", SCHEMA, AUTHORITY,
                LEARNING_AUTHORITY, js(vars(self.args)),
            ),
        )
        self.conn.commit()

    def warm_start(self) -> None:
        print(f"[{self.run_id}] warming Phoenix workers; relative clock remains clean")
        seeded = self.feed.seed_prices()
        self.prices.update(seeded)
        for symbol in self.args.symbols:
            pair = self.feed.api_pairs.get(symbol, symbol)
            try:
                trades = self.feed.recent_trades(pair, self.args.warm_samples)
            except Exception as exc:
                print(f"  WARN {symbol}: {type(exc).__name__}: {exc}")
                trades = []
            for trade in trades[-self.args.warm_samples:]:
                self.worker_series[symbol].add(trade["price"], trade["quantity"])
            if seeded.get(symbol):
                if not trades:
                    self.worker_series[symbol].add(seeded[symbol], 0.0)
                self.live_series[symbol].add(seeded[symbol], 0.0)
            print(f"  {symbol}: worker_warm={len(trades)} latest={seeded.get(symbol)}")

    def _worker_snapshot(self, symbol: str) -> dict[str, Any]:
        state = self.worker_series[symbol]
        closes, volumes = list(state.prices), list(state.volumes)
        latest = closes[-1] if closes else 0.0
        votes: dict[str, int] = {}
        ready: dict[str, bool] = {}
        families: dict[str, str] = {}
        family_votes: dict[str, int] = {}
        for worker_id, family, worker in WORKERS:
            action, ok = "HOLD", True
            try:
                proposal = worker.propose(closes, volumes=volumes, latest_price=latest)
                action = str(proposal.get("action") or "HOLD").upper()
                note = str(proposal.get("notes") or "").lower()
                if "not enough" in note or "unavailable" in note or "no rsi data" in note:
                    ok = False
            except Exception:
                ok = False
            vote = 1 if action == "BUY" else -1 if action == "SELL" else 0
            votes[worker_id] = vote
            ready[worker_id] = ok
            families[worker_id] = family
            if ok:
                family_votes[family] = family_votes.get(family, 0) + vote
        ids = [wid for wid, ok in ready.items() if ok]
        pos = sum(votes[wid] > 0 for wid in ids)
        neg = sum(votes[wid] < 0 for wid in ids)
        support = (pos - neg) / max(1, len(ids))
        positive_families = sum(value > 0 for value in family_votes.values())
        return {
            "votes": votes,
            "ready": ready,
            "families": families,
            "family_votes": family_votes,
            "positive_votes": pos,
            "negative_votes": neg,
            "support": support,
            "positive_families": positive_families,
        }

    def _absolute_seed_score(self, symbol: str, worker: dict[str, Any]) -> float:
        state = self.live_series[symbol]
        n = max(0, len(state.prices) - 1)
        if n < self.args.min_live_samples:
            return -1e18
        r1 = state.ret(1) * 10000.0
        r3 = state.ret(3) * 10000.0 if n >= 3 else 0.0
        r5 = state.ret(5) * 10000.0 if n >= 5 else 0.0
        return (
            0.25 * r1
            + 0.30 * r3
            + 0.45 * r5
            + float(worker.get("support") or 0.0) * self.args.seed_worker_weight_bps
        )

    def _pair_score(
        self,
        incumbent: str,
        challenger: str,
        incumbent_worker: dict[str, Any],
        challenger_worker: dict[str, Any],
        mutation_id: str,
    ) -> dict[str, Any]:
        pair = self.pair_states[(challenger, incumbent)]
        n = max(0, len(pair.ratios) - 1)
        r1 = pair.ret_bps(1) if n >= 1 else 0.0
        r3 = pair.ret_bps(3) if n >= 3 else 0.0
        r5 = pair.ret_bps(5) if n >= 5 else 0.0
        r10 = pair.ret_bps(10) if n >= 10 else 0.0
        cheapness_z = pair.zscore(self.args.relative_window)
        drawdown_bps = pair.drawdown_bps(self.args.relative_window)

        available = [
            value for horizon, value in ((1,r1),(3,r3),(5,r5),(10,r10))
            if n >= horizon
        ]
        persistence = (
            sum(value > 0 for value in available) / len(available)
            if available else 0.0
        )
        velocities = [
            value / horizon for horizon, value in ((1,r1),(3,r3),(5,r5),(10,r10))
            if n >= horizon
        ]
        velocity = mean(velocities)
        prior_velocity = r3 / 3.0 if n >= 3 else 0.0
        acceleration = r1 - prior_velocity

        support_delta = (
            float(challenger_worker.get("support") or 0.0)
            - float(incumbent_worker.get("support") or 0.0)
        )
        family_delta = (
            int(challenger_worker.get("positive_families") or 0)
            - int(incumbent_worker.get("positive_families") or 0)
        )

        cheap_bonus = max(0.0, -cheapness_z) * self.args.cheapness_weight_bps
        rebound_turn = (
            cheapness_z <= -self.args.cheapness_z_min
            and drawdown_bps <= -self.args.relative_drawdown_min_bps
            and r1 > self.args.relative_turn_1s_bps
            and acceleration > 0.0
        )
        streak_alive = (
            r1 > self.args.relative_turn_1s_bps
            and r3 > self.args.relative_confirm_3s_bps
            and persistence >= self.args.relative_persistence_min
        )

        gross_edge = (
            0.25 * r1
            + 0.30 * r3
            + 0.30 * r5
            + 0.15 * r10
            + cheap_bonus
            + max(0.0, acceleration) * self.args.acceleration_weight
            + support_delta * self.args.worker_delta_weight_bps
            + max(0, family_delta) * self.args.family_delta_weight_bps
        )

        # Switching a held coin into another coin is conservatively modelled as
        # incumbent -> quote plus quote -> challenger: two charged sides.
        switch_cost_bps = 2.0 * self.args.cost_bps_side
        net_edge = gross_edge - switch_cost_bps

        if mutation_id == "relative_naive":
            admissible = n >= self.args.min_live_samples and r1 > 0
        elif mutation_id == "relative_streak":
            admissible = n >= self.args.min_live_samples and streak_alive
        elif mutation_id == "relative_hysteresis":
            admissible = (
                n >= self.args.min_live_samples
                and rebound_turn
                and streak_alive
                and net_edge >= self.args.min_net_relative_edge_bps
            )
        else:
            admissible = (
                n >= self.args.min_live_samples
                and rebound_turn
                and streak_alive
                and net_edge >= self.args.min_net_relative_edge_bps
                and support_delta >= self.args.swarm_support_delta_min
                and family_delta >= self.args.swarm_family_delta_min
            )

        return {
            "incumbent": incumbent,
            "challenger": challenger,
            "ratio": pair.ratios[-1] if pair.ratios else 0.0,
            "cheapness_z": cheapness_z,
            "drawdown_bps": drawdown_bps,
            "r1": r1, "r3": r3, "r5": r5, "r10": r10,
            "velocity": velocity,
            "acceleration": acceleration,
            "persistence": persistence,
            "support_delta": support_delta,
            "family_delta": family_delta,
            "gross_edge": gross_edge,
            "switch_cost_bps": switch_cost_bps,
            "net_edge": net_edge,
            "rebound_turn": rebound_turn,
            "streak_alive": streak_alive,
            "admissible": admissible,
            "samples": n,
        }

    def _start_sleeve(
        self,
        mutation_id: str,
        symbol: str,
        worker: dict[str, Any],
        ts: float,
    ) -> None:
        sleeve = self.sleeves[mutation_id]
        if sleeve.holding is not None:
            return
        price = self.prices.get(symbol)
        if not price or price <= 0:
            return
        notional = min(self.args.notional_usd, sleeve.reserve_cash)
        entry_cost = notional * self.args.cost_bps_side / 10000.0
        spend = notional
        qty = (spend - entry_cost) / price
        sleeve.reserve_cash -= spend
        sleeve.cumulative_cost_usd += entry_cost
        sleeve.actions += 1
        leg_id = f"relative-leg-{uuid.uuid4().hex}"
        context = {
            "type": "initial_anchor",
            "worker": worker,
            "absolute_seed_score": self._absolute_seed_score(symbol, worker),
        }
        sleeve.holding = Holding(
            leg_id=leg_id,
            symbol=symbol,
            qty=qty,
            entry_price_usd=price,
            entry_ts=ts,
            entry_value_usd=notional,
            entry_context=context,
        )
        self.started[mutation_id] = True
        self.conn.execute(
            "INSERT INTO relative_legs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                leg_id,self.run_id,mutation_id,symbol,"OPEN",ts,None,price,None,
                notional,None,entry_cost,None,None,None,None,None,js(context),None,
            ),
        )

    def _close_leg(
        self,
        mutation_id: str,
        ts: float,
        reason: str,
        exit_context: dict[str, Any],
        *,
        charge_exit_cost: bool,
    ) -> tuple[float, float, float]:
        sleeve = self.sleeves[mutation_id]
        holding = sleeve.holding
        if holding is None:
            return 0.0, 0.0, 0.0
        price = self.prices.get(holding.symbol, holding.entry_price_usd)
        gross = holding.qty * price
        exit_cost = gross * self.args.cost_bps_side / 10000.0 if charge_exit_cost else 0.0
        proceeds = gross - exit_cost
        if charge_exit_cost:
            sleeve.cumulative_cost_usd += exit_cost
            sleeve.actions += 1
        net_pnl = proceeds - holding.entry_value_usd
        net_bps = net_pnl / holding.entry_value_usd * 10000.0 if holding.entry_value_usd > 0 else 0.0
        duration = max(0.0, ts - holding.entry_ts)
        self.conn.execute(
            """
            UPDATE relative_legs
            SET status='CLOSED',exit_ts=?,exit_price_usd=?,exit_value_usd=?,
                exit_cost_usd=?,net_pnl_usd=?,net_return_bps=?,duration_sec=?,
                exit_reason=?,exit_context_json=?
            WHERE leg_id=?
            """,
            (
                ts,price,proceeds,exit_cost,net_pnl,net_bps,duration,
                reason,js(exit_context),holding.leg_id,
            ),
        )
        return proceeds, net_bps, duration

    def _learn_leg(
        self,
        mutation_id: str,
        holding: Holding,
        pair_score: dict[str, Any],
        net_bps: float,
        duration: float,
        ts: float,
    ) -> None:
        family = "positive_capability" if net_bps > 0 else "negative_capability"
        strength = min(
            1.0,
            abs(net_bps) / max(1.0, 2*self.args.cost_bps_side + self.args.min_net_relative_edge_bps),
        )
        scope_key = (
            f"{mutation_id}|{holding.symbol}|cheap={pair_score.get('cheapness_z',0):.2f}|"
            f"persist={pair_score.get('persistence',0):.2f}"
        )
        payload = {
            "schema": "hivenance_relative_drizzle_learning_crystal_v1",
            "candidate_only": True,
            "automatic_promotion": False,
            "incumbent": holding.symbol,
            "challenger": pair_score.get("challenger"),
            "cheapness_z": pair_score.get("cheapness_z"),
            "pair_drawdown_bps": pair_score.get("drawdown_bps"),
            "relative_1s_bps": pair_score.get("r1"),
            "relative_3s_bps": pair_score.get("r3"),
            "relative_5s_bps": pair_score.get("r5"),
            "relative_10s_bps": pair_score.get("r10"),
            "streak_persistence": pair_score.get("persistence"),
            "relative_acceleration_bps_sec": pair_score.get("acceleration"),
            "gross_edge_bps": pair_score.get("gross_edge"),
            "switch_cost_bps": pair_score.get("switch_cost_bps"),
            "net_edge_bps": pair_score.get("net_edge"),
            "worker_support_delta": pair_score.get("support_delta"),
            "positive_family_delta": pair_score.get("family_delta"),
            "leg_net_return_bps": net_bps,
            "duration_sec": duration,
        }
        self.conn.execute(
            "INSERT INTO relative_learning_crystals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"relative-crystal-{uuid.uuid4().hex}",self.run_id,mutation_id,
                holding.leg_id,family,scope_key,holding.symbol,strength,net_bps,
                duration,float(pair_score.get("cheapness_z") or 0.0),
                float(pair_score.get("persistence") or 0.0),LEARNING_AUTHORITY,
                "candidate_learning_memory_not_promoted",js(payload),ts,
            ),
        )

    def _switch(
        self,
        mutation_id: str,
        pair_score: dict[str, Any],
        workers: dict[str, dict[str, Any]],
        ts: float,
    ) -> None:
        sleeve = self.sleeves[mutation_id]
        old = sleeve.holding
        if old is None:
            return
        challenger = str(pair_score["challenger"])
        challenger_price = self.prices.get(challenger)
        if not challenger_price or challenger_price <= 0:
            return

        proceeds, net_bps, duration = self._close_leg(
            mutation_id, ts, "relative_switch", pair_score, charge_exit_cost=True
        )
        self._learn_leg(mutation_id, old, pair_score, net_bps, duration, ts)

        entry_cost = proceeds * self.args.cost_bps_side / 10000.0
        investable = max(0.0, proceeds - entry_cost)
        sleeve.cumulative_cost_usd += entry_cost
        sleeve.actions += 1
        sleeve.switches += 1
        qty = investable / challenger_price if challenger_price > 0 else 0.0
        leg_id = f"relative-leg-{uuid.uuid4().hex}"
        context = {
            "type": "relative_switch",
            "from_symbol": old.symbol,
            "pair_score": pair_score,
            "challenger_worker": workers.get(challenger, {}),
            "incumbent_worker": workers.get(old.symbol, {}),
        }
        sleeve.holding = Holding(
            leg_id=leg_id,
            symbol=challenger,
            qty=qty,
            entry_price_usd=challenger_price,
            entry_ts=ts,
            entry_value_usd=proceeds,
            entry_context=context,
        )
        self.conn.execute(
            "INSERT INTO relative_legs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                leg_id,self.run_id,mutation_id,challenger,"OPEN",ts,None,
                challenger_price,None,proceeds,None,entry_cost,None,None,None,
                None,None,js(context),None,
            ),
        )

    def _initial_anchor(
        self,
        workers: dict[str, dict[str, Any]],
    ) -> str | None:
        scored = [
            (self._absolute_seed_score(symbol, workers[symbol]), symbol)
            for symbol in self.args.symbols
            if symbol in workers
        ]
        scored = [item for item in scored if item[0] > -1e17]
        if not scored:
            return None
        scored.sort(reverse=True)
        return scored[0][1]

    def _pair_candidates(
        self,
        mutation_id: str,
        incumbent: str,
        workers: dict[str, dict[str, Any]],
        ts: float,
    ) -> list[dict[str, Any]]:
        rows = []
        for challenger in self.args.symbols:
            if challenger == incumbent:
                continue
            row = self._pair_score(
                incumbent, challenger, workers[incumbent], workers[challenger], mutation_id
            )
            rows.append(row)
        rows.sort(key=lambda item: float(item["net_edge"]), reverse=True)
        for rank,row in enumerate(rows,1):
            self.conn.execute(
                "INSERT OR REPLACE INTO relative_pair_scores VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    self.run_id,mutation_id,ts,incumbent,row["challenger"],row["ratio"],
                    row["cheapness_z"],row["drawdown_bps"],row["r1"],row["r3"],row["r5"],row["r10"],
                    row["velocity"],row["acceleration"],row["persistence"],row["support_delta"],
                    row["family_delta"],row["gross_edge"],row["switch_cost_bps"],row["net_edge"],
                    int(row["admissible"]),rank,
                    js({"rebound_turn":row["rebound_turn"],"streak_alive":row["streak_alive"],"samples":row["samples"]}),
                ),
            )
        return rows

    def cycle(self) -> None:
        started = time.perf_counter()
        fetch_started = time.perf_counter()
        prices, volumes, meta = self.feed.poll()
        fetch_ms = (time.perf_counter() - fetch_started) * 1000.0
        self.prices.update(prices)
        ts = time.time()

        workers: dict[str, dict[str, Any]] = {}
        for symbol in self.args.symbols:
            price = self.prices.get(symbol)
            if not price:
                continue
            volume = volumes.get(symbol, 0.0)
            self.worker_series[symbol].add(price, volume)
            self.live_series[symbol].add(price, volume)
            workers[symbol] = self._worker_snapshot(symbol)

        for challenger in self.args.symbols:
            cp = self.prices.get(challenger)
            if not cp:
                continue
            for incumbent in self.args.symbols:
                if challenger == incumbent:
                    continue
                ip = self.prices.get(incumbent)
                if ip:
                    self.pair_states[(challenger, incumbent)].add(cp, ip)

        anchor = self._initial_anchor(workers)
        for mutation_id in MUTATIONS:
            sleeve = self.sleeves[mutation_id]
            if sleeve.holding is None:
                if not self.started[mutation_id] and anchor:
                    self._start_sleeve(mutation_id, anchor, workers[anchor], ts)
                    self.conn.execute(
                        "INSERT INTO relative_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            self.run_id,mutation_id,ts,"UNINITIALIZED",anchor,"INITIALIZE",
                            0.0,0.0,0.0,0.0,"initial_anchor_after_live_warmup",
                            js({"anchor_worker":workers[anchor]}),
                        ),
                    )
                continue

            incumbent = sleeve.holding.symbol
            rows = self._pair_candidates(mutation_id, incumbent, workers, ts)
            best = rows[0] if rows else None
            admissible = [row for row in rows if row["admissible"]]
            chosen = admissible[0] if admissible else None

            action = "HOLD"
            reason = "no_challenger_clears_relative_hurdle"
            challenger = best["challenger"] if best else incumbent
            gross_edge = best["gross_edge"] if best else 0.0
            net_edge = best["net_edge"] if best else 0.0
            cheapness = best["cheapness_z"] if best else 0.0
            persistence = best["persistence"] if best else 0.0

            held_for = ts - sleeve.holding.entry_ts
            if chosen is not None:
                challenger = chosen["challenger"]
                gross_edge = chosen["gross_edge"]
                net_edge = chosen["net_edge"]
                cheapness = chosen["cheapness_z"]
                persistence = chosen["persistence"]
                if held_for < self.args.min_hold_sec:
                    reason = "minimum_hold_hysteresis"
                elif (
                    mutation_id in {"relative_hysteresis","relative_swarm_hysteresis"}
                    and chosen["net_edge"] < self.args.switch_hurdle_bps
                ):
                    reason = "net_edge_below_switch_hurdle"
                else:
                    action = "SWITCH"
                    reason = "relative_drizzle_edge_confirmed"

            self.conn.execute(
                "INSERT INTO relative_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    self.run_id,mutation_id,ts,incumbent,challenger,action,
                    gross_edge,net_edge,cheapness,persistence,reason,
                    js(best or {}),
                ),
            )
            if action == "SWITCH" and chosen is not None:
                self._switch(mutation_id, chosen, workers, ts)

        cycle_ms = (time.perf_counter() - started) * 1000.0
        for mutation_id in MUTATIONS:
            sleeve = self.sleeves[mutation_id]
            held = sleeve.holding.symbol if sleeve.holding else "UNINITIALIZED"
            sleeve_value = 0.0
            if sleeve.holding:
                sleeve_value = sleeve.holding.qty * self.prices.get(
                    sleeve.holding.symbol, sleeve.holding.entry_price_usd
                )
            total_equity = sleeve.reserve_cash + sleeve_value
            self.conn.execute(
                "INSERT OR REPLACE INTO relative_wallet_marks VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    self.run_id,mutation_id,ts,held,total_equity,sleeve_value,
                    sleeve.reserve_cash,sleeve.cumulative_cost_usd,sleeve.switches,
                    sleeve.actions,cycle_ms,
                ),
            )
        self.conn.commit()

        if self.args.verbose or int(ts) % 10 == 0:
            print(
                f"\n[{time.strftime('%H:%M:%S')}] fetch={fetch_ms:.0f}ms "
                f"cycle={cycle_ms:.0f}ms relative-drizzle"
            )
            for mutation_id in MUTATIONS:
                sleeve = self.sleeves[mutation_id]
                held = sleeve.holding.symbol if sleeve.holding else "UNINITIALIZED"
                equity = sleeve.marked_value(self.prices)
                print(
                    f"  {mutation_id:28s} equity={equity:10.4f} "
                    f"net={equity-self.args.start_usd:+8.4f} "
                    f"cost={sleeve.cumulative_cost_usd:7.4f} "
                    f"switches={sleeve.switches:3d} held={held}"
                )

    def close(self, status: str) -> None:
        # Final liquidation is for comparable USD scorekeeping only. It is explicitly
        # marked lab_end_liquidation and not counted as a rotation switch.
        ts = time.time()
        for mutation_id in MUTATIONS:
            sleeve = self.sleeves[mutation_id]
            holding = sleeve.holding
            if holding is None:
                continue
            exit_context = {"reason":"lab_end_liquidation","scorekeeping_only":True}
            proceeds, net_bps, duration = self._close_leg(
                mutation_id,ts,"lab_end_liquidation",exit_context,charge_exit_cost=True
            )
            sleeve.reserve_cash += proceeds
            sleeve.holding = None
        self.conn.execute(
            "UPDATE relative_runs SET ended_ts=?,status=? WHERE run_id=?",
            (time.time(),status,self.run_id),
        )
        self.conn.commit()
        print(f"\nSQLite: {self.args.database}")
        print(f"run_id: {self.run_id}")
        print(f"LEARNING AUTHORITY: {LEARNING_AUTHORITY}")
        print("PRIVATE ORDERS: 0")
        self.conn.close()

    def run(self) -> int:
        self.warm_start()
        print(
            f"Starting {self.args.duration_sec}s relative-drizzle lab. "
            f"One continuously-held paper sleeve after initialization; "
            f"notional={self.args.notional_usd:.2f} USD; no private keys; no orders."
        )
        deadline = time.monotonic() + self.args.duration_sec
        status = "COMPLETE"
        try:
            while time.monotonic() < deadline:
                cycle_started = time.monotonic()
                try:
                    self.cycle()
                except (
                    urllib.error.URLError,
                    urllib.error.HTTPError,
                    TimeoutError,
                    RuntimeError,
                    json.JSONDecodeError,
                ) as exc:
                    print(f"WARN relative-drizzle cycle: {type(exc).__name__}: {exc}")
                time.sleep(max(0.0,self.args.interval_sec-(time.monotonic()-cycle_started)))
        except KeyboardInterrupt:
            status = "INTERRUPTED"
        finally:
            self.close(status)
        return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Paper-only relative cheapness + streak drizzle lab")
    p.add_argument("--symbols",nargs="+",default=["BTC/USD","ETH/USD","SOL/USD","XRP/USD","ADA/USD","AVAX/USD","DOGE/USD","HYPE/USD"])
    p.add_argument("--database",default="data/live_relative_drizzle_lab.db")
    p.add_argument("--duration-sec",type=int,default=900)
    p.add_argument("--interval-sec",type=float,default=1.0)
    p.add_argument("--start-usd",type=float,default=1000.0)
    p.add_argument("--notional-usd",type=float,default=25.0)
    p.add_argument("--cost-bps-side",type=float,default=4.0)
    p.add_argument("--warm-samples",type=int,default=80)
    p.add_argument("--min-live-samples",type=int,default=10)
    p.add_argument("--relative-window",type=int,default=30)
    p.add_argument("--cheapness-z-min",type=float,default=0.35)
    p.add_argument("--relative-drawdown-min-bps",type=float,default=3.0)
    p.add_argument("--relative-turn-1s-bps",type=float,default=0.25)
    p.add_argument("--relative-confirm-3s-bps",type=float,default=0.75)
    p.add_argument("--relative-persistence-min",type=float,default=0.60)
    p.add_argument("--cheapness-weight-bps",type=float,default=1.5)
    p.add_argument("--acceleration-weight",type=float,default=0.50)
    p.add_argument("--worker-delta-weight-bps",type=float,default=2.0)
    p.add_argument("--family-delta-weight-bps",type=float,default=0.75)
    p.add_argument("--seed-worker-weight-bps",type=float,default=2.0)
    p.add_argument("--min-net-relative-edge-bps",type=float,default=0.5)
    p.add_argument("--switch-hurdle-bps",type=float,default=1.0)
    p.add_argument("--min-hold-sec",type=float,default=2.0)
    p.add_argument("--swarm-support-delta-min",type=float,default=0.0)
    p.add_argument("--swarm-family-delta-min",type=int,default=1)
    p.add_argument("--verbose",action="store_true")
    args = p.parse_args()
    if args.interval_sec < 0.8:
        p.error("--interval-sec must be >= 0.8")
    if args.duration_sec < 30:
        p.error("--duration-sec must be >= 30")
    if args.notional_usd <= 0 or args.start_usd <= 0:
        p.error("paper balances must be positive")
    return args


if __name__ == "__main__":
    raise SystemExit(RelativeDrizzleLab(parse_args()).run())
