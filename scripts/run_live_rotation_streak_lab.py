#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
import time
import urllib.error
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_live_profit_streak_swarm import AUTHORITY, WORKERS, KrakenPublicFeed, SeriesState, _finite

LEARNING_AUTHORITY = "research_evidence_only_no_execution_or_promotion_authority"
STABLE = "USD_STABLE_REFUGE"
MUTATIONS = ("stable_control", "rotation_naive", "rotation_hysteresis", "rotation_swarm_hysteresis")


def js(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


@dataclass
class Position:
    leg_id: str
    symbol: str
    qty: float
    notional: float
    entry_price: float
    entry_ts: float
    entry_cost: float
    entry_score: float
    entry_regime: str
    entry_context: dict[str, Any]


@dataclass
class Wallet:
    cash: float
    position: Position | None = None
    costs: float = 0.0
    actions: int = 0

    def equity(self, prices: dict[str, float], side_cost_bps: float) -> float:
        value = self.cash
        if self.position:
            price = prices.get(self.position.symbol, self.position.entry_price)
            gross = self.position.qty * price
            value += gross - gross * side_cost_bps / 10000.0
        return value


class RotationLab:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.run_id = f"rotation-live-{uuid.uuid4().hex[:12]}"
        self.feed = KrakenPublicFeed(args.symbols)
        self.worker_series = {s: SeriesState() for s in args.symbols}
        self.live_series = {s: SeriesState() for s in args.symbols}
        self.prices: dict[str, float] = {}
        self.wallets = {m: Wallet(args.start_usd) for m in MUTATIONS}
        self.conn = sqlite3.connect(args.database)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._schema()

    def _schema(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS rotation_runs(
          run_id TEXT PRIMARY KEY, started_ts REAL, ended_ts REAL, status TEXT,
          authority TEXT, learning_authority TEXT, config_json TEXT);
        CREATE TABLE IF NOT EXISTS rotation_scores(
          run_id TEXT, ts REAL, symbol TEXT, price REAL,
          r1_bps REAL, r3_bps REAL, r5_bps REAL, r10_bps REAL,
          velocity_bps_sec REAL, persistence REAL, retracement_bps REAL,
          rebound INTEGER, positive_votes INTEGER, negative_votes INTEGER,
          ready_votes INTEGER, positive_families INTEGER, worker_support REAL,
          regime TEXT, regime_confidence REAL, raw_score_bps REAL,
          net_score_bps REAL, rank INTEGER, context_json TEXT,
          PRIMARY KEY(run_id, ts, symbol));
        CREATE TABLE IF NOT EXISTS rotation_decisions(
          run_id TEXT, mutation_id TEXT, ts REAL, current_asset TEXT,
          leader_asset TEXT, action TEXT, leader_score_bps REAL,
          incumbent_score_bps REAL, advantage_bps REAL, reason TEXT);
        CREATE TABLE IF NOT EXISTS rotation_legs(
          leg_id TEXT PRIMARY KEY, run_id TEXT, mutation_id TEXT, symbol TEXT,
          status TEXT, entry_ts REAL, exit_ts REAL, entry_price REAL,
          exit_price REAL, notional_usd REAL, entry_cost_usd REAL,
          exit_cost_usd REAL, net_pnl_usd REAL, net_return_bps REAL,
          duration_sec REAL, entry_score_bps REAL, exit_score_bps REAL,
          entry_regime TEXT, exit_regime TEXT, exit_reason TEXT,
          entry_context_json TEXT, exit_context_json TEXT);
        CREATE TABLE IF NOT EXISTS rotation_wallet_marks(
          run_id TEXT, mutation_id TEXT, ts REAL, equity_usd REAL,
          held_asset TEXT, cost_usd REAL, actions INTEGER, cycle_latency_ms REAL,
          PRIMARY KEY(run_id, mutation_id, ts));
        CREATE TABLE IF NOT EXISTS rotation_learning_crystals(
          crystal_id TEXT PRIMARY KEY, run_id TEXT, mutation_id TEXT,
          leg_id TEXT, crystal_family TEXT, scope_key TEXT, symbol TEXT,
          regime TEXT, evidence_strength REAL, net_return_bps REAL,
          duration_sec REAL, authority TEXT, promotion_state TEXT,
          payload_json TEXT, created_ts REAL);
        """)
        self.conn.execute(
            "INSERT INTO rotation_runs VALUES (?,?,?,?,?,?,?)",
            (self.run_id, time.time(), None, "RUNNING", AUTHORITY,
             LEARNING_AUTHORITY, js(vars(self.args))),
        )
        self.conn.commit()

    def warm(self):
        print(f"[{self.run_id}] warm workers, keep one-second detector clock clean")
        seeded = self.feed.seed_prices()
        self.prices.update(seeded)
        for symbol in self.args.symbols:
            pair = self.feed.api_pairs.get(symbol, symbol)
            try:
                trades = self.feed.recent_trades(pair, self.args.warm_samples)
            except Exception as exc:
                print(f"WARN {symbol} warmup: {type(exc).__name__}: {exc}")
                trades = []
            for trade in trades[-self.args.warm_samples:]:
                self.worker_series[symbol].add(trade["price"], trade["quantity"])
            if seeded.get(symbol):
                if not trades:
                    self.worker_series[symbol].add(seeded[symbol], 0.0)
                self.live_series[symbol].add(seeded[symbol], 0.0)
            print(f"  {symbol}: warm={len(trades)} latest={seeded.get(symbol)}")

    def workers(self, symbol: str) -> dict[str, Any]:
        state = self.worker_series[symbol]
        closes, volumes = list(state.prices), list(state.volumes)
        latest = closes[-1] if closes else 0.0
        votes, ready, families = {}, {}, {}
        positive_families = set()
        for wid, family, worker in WORKERS:
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
            votes[wid], ready[wid], families[wid] = vote, ok, family
            if ok and vote > 0:
                positive_families.add(family)
        ids = [wid for wid, ok in ready.items() if ok]
        pos = sum(votes[i] > 0 for i in ids)
        neg = sum(votes[i] < 0 for i in ids)
        return {
            "votes": votes, "ready": ready, "families": families,
            "positive_votes": pos, "negative_votes": neg, "ready_votes": len(ids),
            "positive_families": len(positive_families),
            "support": (pos - neg) / max(1, len(ids)),
        }

    def score(self, symbol: str, worker: dict[str, Any]) -> dict[str, Any]:
        state = self.live_series[symbol]
        p = list(state.prices)
        n = max(0, len(p) - 1)
        def ret(h):
            return state.ret(h) * 10000.0 if n >= h else 0.0
        r1, r3, r5, r10 = ret(1), ret(3), ret(5), ret(10)
        vals = [v for h, v in ((1,r1),(3,r3),(5,r5),(10,r10)) if n >= h]
        persistence = sum(v > 0 for v in vals) / len(vals) if vals else 0.0
        velocities = [v / h for h, v in ((1,r1),(3,r3),(5,r5),(10,r10)) if n >= h]
        velocity = statistics.mean(velocities) if velocities else 0.0
        peak = max(p[-30:]) if p else 0.0
        latest = p[-1] if p else 0.0
        retrace = (latest / peak - 1.0) * 10000.0 if peak > 0 else 0.0
        rebound = retrace <= -self.args.rebound_bps and r1 > 0 and (n < 3 or r3 > 0)
        regime = state.regime() if len(p) >= 12 else {"label":"warming","confidence":0.0}
        label = str(regime.get("label") or "warming")
        regime_bonus = {"bursty":2.0,"mixed":0.0,"meanrev":-2.0,"noise":-3.0,"warming":-1.0}.get(label,0.0)
        rebound_bonus = min(2.0, max(0.0, (-retrace-self.args.rebound_bps)/8.0)) if rebound else 0.0
        raw = (
            0.20*r1 + 0.25*r3 + 0.35*r5 + 0.20*r10
            + float(worker["support"]) * self.args.worker_weight_bps
            + (persistence - 0.5) * self.args.persistence_weight_bps
            + regime_bonus + rebound_bonus
        )
        return {
            "symbol":symbol,"price":latest,"r1":r1,"r3":r3,"r5":r5,"r10":r10,
            "velocity":velocity,"persistence":persistence,"retracement":retrace,
            "rebound":rebound,"regime":label,"regime_confidence":float(regime.get("confidence") or 0),
            "raw":raw,"net":raw-2*self.args.cost_bps_side,"eligible":n>=self.args.min_live_samples,
            "worker":worker,
        }

    def persist_scores(self, ts: float, scores: dict[str, dict[str, Any]]):
        ordered = sorted(scores.values(), key=lambda x: x["net"], reverse=True)
        ranks = {row["symbol"]: i+1 for i,row in enumerate(ordered)}
        for s,row in scores.items():
            w = row["worker"]
            self.conn.execute(
                "INSERT OR REPLACE INTO rotation_scores VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (self.run_id,ts,s,row["price"],row["r1"],row["r3"],row["r5"],row["r10"],
                 row["velocity"],row["persistence"],row["retracement"],int(row["rebound"]),
                 w["positive_votes"],w["negative_votes"],w["ready_votes"],w["positive_families"],
                 w["support"],row["regime"],row["regime_confidence"],row["raw"],row["net"],
                 ranks[s],js({"eligible":row["eligible"],"worker":w})),
            )

    def decision(self, mid: str, scores: dict[str, dict[str, Any]], ts: float) -> dict[str, Any]:
        wallet = self.wallets[mid]
        current = scores.get(wallet.position.symbol) if wallet.position else None
        incumbent = current["net"] if current else 0.0
        eligible = [x for x in scores.values() if x["eligible"]]
        if mid == "stable_control" or not eligible:
            return {"leader":STABLE,"action":"REFUGE" if wallet.position else "STAY_STABLE",
                    "leader_score":0.0,"incumbent":incumbent,"advantage":-incumbent,
                    "reason":"stable_control" if mid=="stable_control" else "warming"}

        if mid == "rotation_naive":
            leader = max(eligible, key=lambda x:x["raw"])
            incumbent_raw = current["raw"] if current else 0.0
            if leader["raw"] < self.args.naive_entry_bps:
                action,reason = ("REFUGE","no_positive_wave") if wallet.position else ("STAY_STABLE","no_positive_wave")
            elif not wallet.position:
                action,reason = "ENTER","strongest_positive_wave"
            elif leader["symbol"] == wallet.position.symbol:
                action,reason = "STAY","incumbent_leads"
            elif leader["raw"] >= incumbent_raw + self.args.naive_switch_bps:
                action,reason = "SWITCH","new_raw_leader"
            else:
                action,reason = "STAY","challenger_too_small"
            return {"leader":leader["symbol"],"action":action,"leader_score":leader["raw"],
                    "incumbent":incumbent_raw,"advantage":leader["raw"]-incumbent_raw,"reason":reason}

        candidates = eligible
        if mid == "rotation_swarm_hysteresis":
            candidates = [
                x for x in eligible
                if x["worker"]["positive_votes"] >= self.args.swarm_votes
                and x["worker"]["positive_families"] >= self.args.swarm_families
            ]
        if not candidates:
            weak = bool(wallet.position and incumbent <= self.args.refuge_bps)
            return {"leader":STABLE,"action":"REFUGE" if weak else ("STAY" if wallet.position else "STAY_STABLE"),
                    "leader_score":0.0,"incumbent":incumbent,"advantage":-incumbent,
                    "reason":"no_admissible_challenger"}
        leader = max(candidates, key=lambda x:x["net"])
        if leader["net"] < self.args.min_net_edge_bps:
            weak = bool(wallet.position and incumbent <= self.args.refuge_bps)
            action = "REFUGE" if weak else ("STAY" if wallet.position else "STAY_STABLE")
            reason = "below_cost_hurdle"
        elif not wallet.position:
            action,reason = "ENTER","leader_survives_cost_hurdle"
        elif leader["symbol"] == wallet.position.symbol:
            action,reason = ("REFUGE","incumbent_exhausted") if incumbent <= self.args.refuge_bps else ("STAY","incumbent_leads")
        elif ts-wallet.position.entry_ts < self.args.min_hold_sec:
            action,reason = "STAY","minimum_hold"
        elif leader["net"]-incumbent >= self.args.switch_hurdle_bps:
            action,reason = "SWITCH","challenger_clears_switch_hurdle"
        elif incumbent <= self.args.refuge_bps:
            action,reason = "REFUGE","incumbent_exhausted_challenger_weak"
        else:
            action,reason = "STAY","switch_advantage_too_small"
        return {"leader":leader["symbol"],"action":action,"leader_score":leader["net"],
                "incumbent":incumbent,"advantage":leader["net"]-incumbent,"reason":reason}

    def enter(self, mid: str, score: dict[str, Any], ts: float, reason: str):
        w = self.wallets[mid]
        if w.position:
            return
        notional = min(self.args.notional_usd, w.cash)
        cost = notional*self.args.cost_bps_side/10000.0
        if notional <= cost or score["price"] <= 0:
            return
        leg = f"rotation-leg-{uuid.uuid4().hex}"
        context = {"reason":reason,"score":{k:v for k,v in score.items() if k!="worker"},"worker":score["worker"]}
        w.position = Position(leg,score["symbol"],(notional-cost)/score["price"],notional,
                              score["price"],ts,cost,score["net"],score["regime"],context)
        w.cash -= notional
        w.costs += cost
        w.actions += 1
        self.conn.execute(
            "INSERT INTO rotation_legs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (leg,self.run_id,mid,score["symbol"],"OPEN",ts,None,score["price"],None,notional,
             cost,None,None,None,None,score["net"],None,score["regime"],None,None,js(context),None),
        )

    def exit(self, mid: str, score: dict[str, Any] | None, ts: float, reason: str):
        w = self.wallets[mid]
        pos = w.position
        if not pos:
            return
        price = self.prices.get(pos.symbol,pos.entry_price)
        gross = pos.qty*price
        exit_cost = gross*self.args.cost_bps_side/10000.0
        proceeds = gross-exit_cost
        w.cash += proceeds
        w.costs += exit_cost
        w.actions += 1
        w.position = None
        net_pnl = proceeds-pos.notional
        net_bps = net_pnl/pos.notional*10000.0
        duration = ts-pos.entry_ts
        ex = score or {"net":0.0,"regime":"unknown","worker":{}}
        exit_context = {"reason":reason,"score":{k:v for k,v in ex.items() if k!="worker"},"worker":ex.get("worker",{})}
        self.conn.execute(
            "UPDATE rotation_legs SET status='CLOSED',exit_ts=?,exit_price=?,exit_cost_usd=?,"
            "net_pnl_usd=?,net_return_bps=?,duration_sec=?,exit_score_bps=?,exit_regime=?,"
            "exit_reason=?,exit_context_json=? WHERE leg_id=?",
            (ts,price,exit_cost,net_pnl,net_bps,duration,ex.get("net",0.0),ex.get("regime","unknown"),
             reason,js(exit_context),pos.leg_id),
        )
        family = "positive_capability" if net_pnl > 0 else "negative_capability"
        entry_score = pos.entry_context.get("score",{})
        scope = f"{mid}|{pos.symbol}|{pos.entry_regime}|families={entry_score.get('positive_families',0)}|rebound={int(bool(entry_score.get('rebound')))}"
        strength = min(1.0,abs(net_bps)/max(1.0,2*self.args.cost_bps_side+self.args.switch_hurdle_bps))
        payload = {
            "schema":"hivenance_rotation_learning_crystal_v1","candidate_only":True,
            "automatic_promotion":False,"mutation_id":mid,"symbol":pos.symbol,
            "entry_regime":pos.entry_regime,"exit_regime":ex.get("regime"),
            "entry_score_bps":pos.entry_score,"exit_score_bps":ex.get("net",0.0),
            "entry_worker":pos.entry_context.get("worker",{}),"exit_worker":ex.get("worker",{}),
            "net_return_bps":net_bps,"net_pnl_usd":net_pnl,"duration_sec":duration,"exit_reason":reason,
        }
        self.conn.execute(
            "INSERT INTO rotation_learning_crystals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"rotation-crystal-{uuid.uuid4().hex}",self.run_id,mid,pos.leg_id,family,scope,pos.symbol,
             pos.entry_regime,strength,net_bps,duration,LEARNING_AUTHORITY,
             "candidate_learning_memory_not_promoted",js(payload),ts),
        )

    def cycle(self):
        started = time.perf_counter()
        fetch_started = time.perf_counter()
        prices,volumes,meta = self.feed.poll()
        fetch_ms = (time.perf_counter()-fetch_started)*1000.0
        self.prices.update(prices)
        ts = time.time()
        scores = {}
        for symbol in self.args.symbols:
            price = self.prices.get(symbol)
            if not price:
                continue
            volume = volumes.get(symbol,0.0)
            self.worker_series[symbol].add(price,volume)
            self.live_series[symbol].add(price,volume)
            scores[symbol] = self.score(symbol,self.workers(symbol))
        self.persist_scores(ts,scores)
        for mid in MUTATIONS:
            w = self.wallets[mid]
            d = self.decision(mid,scores,ts)
            current_asset = w.position.symbol if w.position else STABLE
            current_score = scores.get(w.position.symbol) if w.position else None
            self.conn.execute(
                "INSERT INTO rotation_decisions VALUES (?,?,?,?,?,?,?,?,?,?)",
                (self.run_id,mid,ts,current_asset,d["leader"],d["action"],d["leader_score"],
                 d["incumbent"],d["advantage"],d["reason"]),
            )
            if d["action"] == "REFUGE":
                self.exit(mid,current_score,ts,d["reason"])
            elif d["action"] == "ENTER":
                self.enter(mid,scores[d["leader"]],ts,d["reason"])
            elif d["action"] == "SWITCH":
                self.exit(mid,current_score,ts,d["reason"])
                self.enter(mid,scores[d["leader"]],ts,d["reason"])
        cycle_ms = (time.perf_counter()-started)*1000.0
        for mid in MUTATIONS:
            w = self.wallets[mid]
            held = w.position.symbol if w.position else STABLE
            self.conn.execute(
                "INSERT OR REPLACE INTO rotation_wallet_marks VALUES (?,?,?,?,?,?,?,?)",
                (self.run_id,mid,ts,w.equity(self.prices,self.args.cost_bps_side),held,w.costs,w.actions,cycle_ms),
            )
        self.conn.commit()
        if self.args.verbose or int(ts)%10 == 0:
            leader = max(scores.values(),key=lambda x:x["net"]) if scores else None
            lead = f"{leader['symbol']} {leader['net']:+.2f}bps" if leader else "warming"
            print(f"\n[{time.strftime('%H:%M:%S')}] fetch={fetch_ms:.0f}ms cycle={cycle_ms:.0f}ms leader={lead}")
            for mid in MUTATIONS:
                w=self.wallets[mid]
                held=w.position.symbol if w.position else STABLE
                eq=w.equity(self.prices,self.args.cost_bps_side)
                print(f"  {mid:28s} equity={eq:10.4f} net={eq-self.args.start_usd:+8.4f} cost={w.costs:7.4f} actions={w.actions:3d} held={held}")

    def close(self,status: str):
        ts=time.time()
        for mid in MUTATIONS:
            w=self.wallets[mid]
            if w.position:
                symbol=w.position.symbol
                self.exit(mid,self.score(symbol,self.workers(symbol)),ts,"lab_end_liquidation")
        self.conn.execute("UPDATE rotation_runs SET ended_ts=?,status=? WHERE run_id=?",(time.time(),status,self.run_id))
        self.conn.commit()
        print(f"SQLite: {self.args.database}")
        print(f"run_id: {self.run_id}")
        print(f"LEARNING AUTHORITY: {LEARNING_AUTHORITY}")
        print("PRIVATE ORDERS: 0")
        self.conn.close()

    def run(self):
        self.warm()
        print(f"Starting {self.args.duration_sec}s cross-asset rotation lab; stable refuge={STABLE}; fixed paper notional={self.args.notional_usd:.2f} USD")
        deadline=time.monotonic()+self.args.duration_sec
        status="COMPLETE"
        try:
            while time.monotonic()<deadline:
                began=time.monotonic()
                try:
                    self.cycle()
                except (urllib.error.URLError,urllib.error.HTTPError,TimeoutError,RuntimeError,json.JSONDecodeError) as exc:
                    print(f"WARN public rotation cycle: {type(exc).__name__}: {exc}")
                time.sleep(max(0.0,self.args.interval_sec-(time.monotonic()-began)))
        except KeyboardInterrupt:
            status="INTERRUPTED"
        finally:
            self.close(status)
        return 0


def parse_args():
    p=argparse.ArgumentParser(description="Paper-only Phoenix cross-asset streak rotation lab")
    p.add_argument("--symbols",nargs="+",default=["BTC/USD","ETH/USD","SOL/USD","XRP/USD","ADA/USD","AVAX/USD","DOGE/USD","HYPE/USD"])
    p.add_argument("--database",default="data/live_rotation_streak_lab.db")
    p.add_argument("--duration-sec",type=int,default=900)
    p.add_argument("--interval-sec",type=float,default=1.0)
    p.add_argument("--start-usd",type=float,default=1000.0)
    p.add_argument("--notional-usd",type=float,default=25.0)
    p.add_argument("--cost-bps-side",type=float,default=4.0)
    p.add_argument("--warm-samples",type=int,default=80)
    p.add_argument("--min-live-samples",type=int,default=5)
    p.add_argument("--worker-weight-bps",type=float,default=4.0)
    p.add_argument("--persistence-weight-bps",type=float,default=2.0)
    p.add_argument("--rebound-bps",type=float,default=4.0)
    p.add_argument("--naive-entry-bps",type=float,default=0.5)
    p.add_argument("--naive-switch-bps",type=float,default=0.5)
    p.add_argument("--min-net-edge-bps",type=float,default=1.0)
    p.add_argument("--switch-hurdle-bps",type=float,default=3.0)
    p.add_argument("--refuge-bps",type=float,default=0.0)
    p.add_argument("--min-hold-sec",type=float,default=3.0)
    p.add_argument("--swarm-votes",type=int,default=4)
    p.add_argument("--swarm-families",type=int,default=3)
    p.add_argument("--verbose",action="store_true")
    args=p.parse_args()
    if args.interval_sec<0.8: p.error("--interval-sec must be >= 0.8")
    if args.duration_sec<30: p.error("--duration-sec must be >= 30")
    return args

if __name__=="__main__":
    raise SystemExit(RotationLab(parse_args()).run())
