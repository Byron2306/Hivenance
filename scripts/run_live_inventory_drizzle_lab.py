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
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from scripts.run_live_profit_streak_swarm import AUTHORITY, WORKERS, KrakenPublicFeed, SeriesState, _finite

SCHEMA="hivenance_inventory_drizzle_harvest_v1"
LEARNING_AUTHORITY="research_evidence_only_no_execution_or_promotion_authority"
MUTATIONS=(
    "inventory_hold",
    "inventory_naive",
    "inventory_band",
    "inventory_streak",
    "inventory_swarm_streak",
)


def js(value: Any) -> str:
    return json.dumps(value,sort_keys=True,separators=(",",":"),default=str)


def mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def pstdev(values: list[float]) -> float:
    return statistics.pstdev(values) if len(values)>=2 else 0.0


@dataclass
class PairState:
    ratios: deque[float]=field(default_factory=lambda:deque(maxlen=300))

    def add(self,target_price: float,source_price: float) -> None:
        if target_price>0 and source_price>0:
            self.ratios.append(target_price/source_price)

    def ret_bps(self,seconds:int) -> float:
        if len(self.ratios)<=seconds:
            return 0.0
        values=list(self.ratios)
        a,b=values[-(seconds+1)],values[-1]
        return (b/a-1.0)*10000.0 if a>0 else 0.0

    def zscore(self,window:int) -> float:
        values=list(self.ratios)[-window:]
        if len(values)<max(8,window//3):
            return 0.0
        mu=mean(values)
        sd=pstdev(values)
        return (values[-1]-mu)/sd if sd>0 else 0.0

    def drawdown_bps(self,window:int) -> float:
        values=list(self.ratios)[-window:]
        if not values:
            return 0.0
        peak=max(values)
        return (values[-1]/peak-1.0)*10000.0 if peak>0 else 0.0


@dataclass
class InventoryWallet:
    cash: float
    qty: dict[str,float]=field(default_factory=dict)
    cumulative_cost_usd: float=0.0
    rebalances: int=0
    charged_sides: int=0
    setup_actions: int=0

    def gross_asset_value(self,symbol:str,prices:dict[str,float]) -> float:
        return float(self.qty.get(symbol,0.0))*float(prices.get(symbol,0.0))

    def liquidation_equity(
        self,
        prices:dict[str,float],
        spread_bps:dict[str,float],
        fee_bps_side:float,
    ) -> float:
        value=float(self.cash)
        for symbol,qty in self.qty.items():
            price=float(prices.get(symbol,0.0))
            if price<=0 or qty<=0:
                continue
            gross=qty*price
            exit_cost_bps=float(fee_bps_side)+0.5*float(spread_bps.get(symbol,0.0))
            value+=gross*(1.0-exit_cost_bps/10000.0)
        return value


class InventoryDrizzleLab:
    def __init__(self,args:argparse.Namespace) -> None:
        self.args=args
        self.run_id=f"inventory-drizzle-{uuid.uuid4().hex[:12]}"
        self.feed=KrakenPublicFeed(args.symbols)
        self.worker_series={s:SeriesState() for s in args.symbols}
        self.live_series={s:SeriesState() for s in args.symbols}
        self.pairs={(to_s,from_s):PairState() for to_s in args.symbols for from_s in args.symbols if to_s!=from_s}
        self.prices:dict[str,float]={}
        self.wallets={mid:InventoryWallet(float(args.start_usd)) for mid in MUTATIONS}
        self.direct_pairs:set[frozenset[str]]=set()
        self.pending:dict[tuple[str,str,str],int]=defaultdict(int)
        self.last_trade_ts:dict[str,float]=defaultdict(float)
        self.conn=sqlite3.connect(args.database)
        self.conn.row_factory=sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._schema()
        self._load_conversion_graph()

    def _schema(self) -> None:
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS inventory_runs(
          run_id TEXT PRIMARY KEY,started_ts REAL,ended_ts REAL,status TEXT,
          schema TEXT,authority TEXT,learning_authority TEXT,config_json TEXT);
        CREATE TABLE IF NOT EXISTS inventory_route_registry(
          run_id TEXT,from_asset TEXT,to_asset TEXT,direct_market INTEGER,
          route_sides INTEGER,route_label TEXT,
          PRIMARY KEY(run_id,from_asset,to_asset));
        CREATE TABLE IF NOT EXISTS inventory_pair_scores(
          run_id TEXT,mutation_id TEXT,ts REAL,from_symbol TEXT,to_symbol TEXT,
          ratio REAL,cheapness_z REAL,pair_drawdown_bps REAL,
          relative_1s_bps REAL,relative_3s_bps REAL,relative_5s_bps REAL,relative_10s_bps REAL,
          persistence REAL,acceleration REAL,worker_support_delta REAL,family_delta INTEGER,
          route_sides INTEGER,fee_cost_bps REAL,spread_proxy_bps REAL,total_route_cost_bps REAL,
          gross_edge_bps REAL,net_edge_bps REAL,admissible INTEGER,rank INTEGER,context_json TEXT,
          PRIMARY KEY(run_id,mutation_id,ts,from_symbol,to_symbol));
        CREATE TABLE IF NOT EXISTS inventory_trades(
          trade_id TEXT PRIMARY KEY,run_id TEXT,mutation_id TEXT,ts REAL,
          from_symbol TEXT,to_symbol TEXT,trade_usd REAL,route_sides INTEGER,
          route_label TEXT,fee_cost_bps REAL,spread_proxy_bps REAL,total_route_cost_bps REAL,
          modeled_cost_usd REAL,cheapness_z REAL,persistence REAL,
          gross_edge_bps REAL,net_edge_bps REAL,batch_confirmations INTEGER,
          from_value_before REAL,to_value_before REAL,from_value_after REAL,to_value_after REAL,
          entry_ratio REAL,context_json TEXT);
        CREATE TABLE IF NOT EXISTS inventory_signal_outcomes(
          trade_id TEXT PRIMARY KEY,run_id TEXT,mutation_id TEXT,from_symbol TEXT,to_symbol TEXT,
          entry_ts REAL,entry_ratio REAL,total_route_cost_bps REAL,
          settled_10s INTEGER,capture_10s_bps REAL,net_capture_10s_bps REAL,
          settled_30s INTEGER,capture_30s_bps REAL,net_capture_30s_bps REAL,
          settled_60s INTEGER,capture_60s_bps REAL,net_capture_60s_bps REAL,
          last_update_ts REAL);
        CREATE TABLE IF NOT EXISTS inventory_wallet_marks(
          run_id TEXT,mutation_id TEXT,ts REAL,total_equity_usd REAL,cash_usd REAL,
          inventory_gross_usd REAL,cumulative_cost_usd REAL,rebalances INTEGER,
          charged_sides INTEGER,weight_dispersion REAL,max_weight REAL,cycle_latency_ms REAL,
          PRIMARY KEY(run_id,mutation_id,ts));
        CREATE TABLE IF NOT EXISTS inventory_learning_crystals(
          crystal_id TEXT PRIMARY KEY,run_id TEXT,mutation_id TEXT,trade_id TEXT,
          crystal_family TEXT,scope_key TEXT,from_symbol TEXT,to_symbol TEXT,
          evidence_horizon_sec INTEGER,evidence_strength REAL,net_capture_bps REAL,
          cheapness_z REAL,persistence REAL,route_sides INTEGER,
          authority TEXT,promotion_state TEXT,payload_json TEXT,created_ts REAL);
        """)
        self.conn.execute(
            "INSERT INTO inventory_runs VALUES (?,?,?,?,?,?,?,?)",
            (self.run_id,time.time(),None,"RUNNING",SCHEMA,AUTHORITY,LEARNING_AUTHORITY,js(vars(self.args)))
        )
        self.conn.commit()

    @staticmethod
    def _base(symbol:str) -> str:
        return str(symbol).split("/",1)[0].upper()

    def _load_conversion_graph(self) -> None:
        pairs=self.feed._get("AssetPairs",{})
        for info in pairs.values():
            if not isinstance(info,dict):
                continue
            ws=self.feed._canonical_wsname(str(info.get("wsname") or ""))
            parts=ws.split("/")
            if len(parts)==2:
                self.direct_pairs.add(frozenset((parts[0].upper(),parts[1].upper())))
        for from_symbol in self.args.symbols:
            for to_symbol in self.args.symbols:
                if from_symbol==to_symbol:
                    continue
                fa,tb=self._base(from_symbol),self._base(to_symbol)
                direct=frozenset((fa,tb)) in self.direct_pairs
                sides=1 if direct else 2
                self.conn.execute(
                    "INSERT OR REPLACE INTO inventory_route_registry VALUES (?,?,?,?,?,?)",
                    (self.run_id,fa,tb,int(direct),sides,"DIRECT_PAIR" if direct else "ROUTED_VIA_USD")
                )
        self.conn.commit()

    def _route(self,from_symbol:str,to_symbol:str) -> dict[str,Any]:
        direct=frozenset((self._base(from_symbol),self._base(to_symbol))) in self.direct_pairs
        sides=1 if direct else 2
        spread_from=float(self.feed.last_spread_bps.get(from_symbol,0.0))
        spread_to=float(self.feed.last_spread_bps.get(to_symbol,0.0))
        spread_proxy=0.5*(spread_from+spread_to)
        fee_cost=sides*float(self.args.cost_bps_side)
        return {
            "direct":direct,
            "sides":sides,
            "label":"DIRECT_PAIR" if direct else "ROUTED_VIA_USD",
            "fee_cost_bps":fee_cost,
            "spread_proxy_bps":spread_proxy,
            "total_cost_bps":fee_cost+spread_proxy,
            "spread_fidelity":"USD_LEG_PROXY_FOR_DIRECT_MARKETS",
        }

    def warm_start(self) -> None:
        print(f"[{self.run_id}] warming workers and equal-weight inventory basket")
        seeded=self.feed.seed_prices()
        self.prices.update(seeded)
        for symbol in self.args.symbols:
            pair=self.feed.api_pairs.get(symbol,symbol)
            try:
                trades=self.feed.recent_trades(pair,self.args.warm_samples)
            except Exception as exc:
                print(f"  WARN {symbol}: {type(exc).__name__}: {exc}")
                trades=[]
            for trade in trades[-self.args.warm_samples:]:
                self.worker_series[symbol].add(trade["price"],trade["quantity"])
            if seeded.get(symbol):
                if not trades:
                    self.worker_series[symbol].add(seeded[symbol],0.0)
                self.live_series[symbol].add(seeded[symbol],0.0)
            print(f"  {symbol}: worker_warm={len(trades)} latest={seeded.get(symbol)}")
        self._initialize_inventory()

    def _initialize_inventory(self) -> None:
        allocation=float(self.args.inventory_usd)/max(1,len(self.args.symbols))
        for mid,wallet in self.wallets.items():
            for symbol in self.args.symbols:
                price=float(self.prices.get(symbol,0.0))
                if price<=0:
                    continue
                spread=float(self.feed.last_spread_bps.get(symbol,0.0))
                cost_bps=float(self.args.cost_bps_side)+0.5*spread
                cost=allocation*cost_bps/10000.0
                spend=min(allocation,wallet.cash)
                if spend<=cost:
                    continue
                wallet.cash-=spend
                wallet.qty[symbol]=(spend-cost)/price
                wallet.cumulative_cost_usd+=cost
                wallet.setup_actions+=1
                wallet.charged_sides+=1

    def _worker_snapshot(self,symbol:str) -> dict[str,Any]:
        state=self.worker_series[symbol]
        closes,volumes=list(state.prices),list(state.volumes)
        latest=closes[-1] if closes else 0.0
        votes,ready,family_votes={},{},{}
        for wid,family,worker in WORKERS:
            action,ok="HOLD",True
            try:
                proposal=worker.propose(closes,volumes=volumes,latest_price=latest)
                action=str(proposal.get("action") or "HOLD").upper()
                note=str(proposal.get("notes") or "").lower()
                if "not enough" in note or "unavailable" in note or "no rsi data" in note:
                    ok=False
            except Exception:
                ok=False
            vote=1 if action=="BUY" else -1 if action=="SELL" else 0
            votes[wid]=vote
            ready[wid]=ok
            if ok:
                family_votes[family]=family_votes.get(family,0)+vote
        ids=[wid for wid,ok in ready.items() if ok]
        pos=sum(votes[wid]>0 for wid in ids)
        neg=sum(votes[wid]<0 for wid in ids)
        return {
            "votes":votes,
            "ready":ready,
            "support":(pos-neg)/max(1,len(ids)),
            "positive_families":sum(value>0 for value in family_votes.values()),
            "family_votes":family_votes,
        }

    def _score_pair(
        self,
        mid:str,
        from_symbol:str,
        to_symbol:str,
        workers:dict[str,dict[str,Any]],
    ) -> dict[str,Any]:
        pair=self.pairs[(to_symbol,from_symbol)]
        n=max(0,len(pair.ratios)-1)
        def ret(h:int) -> float:
            return pair.ret_bps(h) if n>=h else 0.0
        r1,r3,r5,r10=ret(1),ret(3),ret(5),ret(10)
        cheap=pair.zscore(self.args.relative_window)
        drawdown=pair.drawdown_bps(self.args.relative_window)
        values=[value for h,value in ((1,r1),(3,r3),(5,r5),(10,r10)) if n>=h]
        persistence=sum(value>0 for value in values)/len(values) if values else 0.0
        prior_velocity=r3/3.0 if n>=3 else 0.0
        acceleration=r1-prior_velocity
        support_delta=float(workers[to_symbol]["support"])-float(workers[from_symbol]["support"])
        family_delta=int(workers[to_symbol]["positive_families"])-int(workers[from_symbol]["positive_families"])
        route=self._route(from_symbol,to_symbol)

        cheap_bonus=max(0.0,-cheap)*self.args.cheapness_weight_bps
        gross_edge=(
            0.25*r1+0.30*r3+0.30*r5+0.15*r10
            +cheap_bonus
            +max(0.0,acceleration)*self.args.acceleration_weight
            +support_delta*self.args.worker_delta_weight_bps
            +max(0,family_delta)*self.args.family_delta_weight_bps
        )
        net_edge=gross_edge-float(route["total_cost_bps"])
        rebound=(
            cheap<=-self.args.cheapness_z_min
            and drawdown<=-self.args.relative_drawdown_min_bps
            and r1>self.args.relative_turn_1s_bps
            and acceleration>0.0
        )
        streak=(
            r1>self.args.relative_turn_1s_bps
            and r3>self.args.relative_confirm_3s_bps
            and persistence>=self.args.relative_persistence_min
        )

        if mid=="inventory_naive":
            admissible=n>=self.args.min_live_samples and r1>0
            confirmations=1
        elif mid=="inventory_band":
            admissible=(
                n>=self.args.min_live_samples and rebound
                and net_edge>=self.args.min_net_edge_bps
            )
            confirmations=self.args.batch_confirmations
        elif mid=="inventory_streak":
            admissible=(
                n>=self.args.min_live_samples and rebound and streak
                and net_edge>=self.args.min_net_edge_bps
            )
            confirmations=self.args.batch_confirmations
        elif mid=="inventory_swarm_streak":
            admissible=(
                n>=self.args.min_live_samples and rebound and streak
                and net_edge>=self.args.min_net_edge_bps
                and support_delta>=self.args.swarm_support_delta_min
                and family_delta>=self.args.swarm_family_delta_min
            )
            confirmations=self.args.batch_confirmations
        else:
            admissible=False
            confirmations=999999

        return {
            "from_symbol":from_symbol,"to_symbol":to_symbol,
            "ratio":pair.ratios[-1] if pair.ratios else 0.0,
            "cheapness_z":cheap,"drawdown_bps":drawdown,
            "r1":r1,"r3":r3,"r5":r5,"r10":r10,
            "persistence":persistence,"acceleration":acceleration,
            "support_delta":support_delta,"family_delta":family_delta,
            "gross_edge":gross_edge,"net_edge":net_edge,
            "rebound":rebound,"streak":streak,"admissible":admissible,
            "required_confirmations":confirmations,"route":route,"samples":n,
        }

    def _wallet_weights(self,wallet:InventoryWallet) -> dict[str,float]:
        values={s:wallet.gross_asset_value(s,self.prices) for s in self.args.symbols}
        total=sum(values.values())
        return {s:(v/total if total>0 else 0.0) for s,v in values.items()}

    def _candidate_rows(
        self,
        mid:str,
        wallet:InventoryWallet,
        workers:dict[str,dict[str,Any]],
        ts:float,
    ) -> list[dict[str,Any]]:
        rows=[]
        values={s:wallet.gross_asset_value(s,self.prices) for s in self.args.symbols}
        floor=float(self.args.inventory_floor_usd)
        cap=float(self.args.inventory_usd)*float(self.args.max_asset_weight)
        for from_symbol in self.args.symbols:
            if values.get(from_symbol,0.0)<=floor+self.args.min_trade_usd:
                continue
            for to_symbol in self.args.symbols:
                if to_symbol==from_symbol or values.get(to_symbol,0.0)>=cap:
                    continue
                rows.append(self._score_pair(mid,from_symbol,to_symbol,workers))
        rows.sort(key=lambda row:float(row["net_edge"]),reverse=True)
        for rank,row in enumerate(rows,1):
            route=row["route"]
            self.conn.execute(
                "INSERT OR REPLACE INTO inventory_pair_scores VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    self.run_id,mid,ts,row["from_symbol"],row["to_symbol"],row["ratio"],
                    row["cheapness_z"],row["drawdown_bps"],row["r1"],row["r3"],row["r5"],row["r10"],
                    row["persistence"],row["acceleration"],row["support_delta"],row["family_delta"],
                    route["sides"],route["fee_cost_bps"],route["spread_proxy_bps"],route["total_cost_bps"],
                    row["gross_edge"],row["net_edge"],int(row["admissible"]),rank,
                    js({"rebound":row["rebound"],"streak":row["streak"],"samples":row["samples"]}),
                ),
            )
        return rows

    def _rebalance(self,mid:str,row:dict[str,Any],ts:float,batch_count:int) -> None:
        wallet=self.wallets[mid]
        from_symbol,to_symbol=row["from_symbol"],row["to_symbol"]
        from_price=float(self.prices.get(from_symbol,0.0))
        to_price=float(self.prices.get(to_symbol,0.0))
        if from_price<=0 or to_price<=0:
            return
        from_before=wallet.gross_asset_value(from_symbol,self.prices)
        to_before=wallet.gross_asset_value(to_symbol,self.prices)
        max_source=max(0.0,from_before-self.args.inventory_floor_usd)
        cap=float(self.args.inventory_usd)*float(self.args.max_asset_weight)
        target_room=max(0.0,cap-to_before)
        trade_usd=min(float(self.args.rebalance_usd),max_source,target_room)
        if trade_usd<self.args.min_trade_usd:
            return

        route=row["route"]
        cost_bps=float(route["total_cost_bps"])
        cost=trade_usd*cost_bps/10000.0
        source_qty=trade_usd/from_price
        wallet.qty[from_symbol]=max(0.0,float(wallet.qty.get(from_symbol,0.0))-source_qty)
        wallet.qty[to_symbol]=float(wallet.qty.get(to_symbol,0.0))+max(0.0,trade_usd-cost)/to_price
        wallet.cumulative_cost_usd+=cost
        wallet.rebalances+=1
        wallet.charged_sides+=int(route["sides"])
        trade_id=f"inventory-trade-{uuid.uuid4().hex}"
        from_after=wallet.gross_asset_value(from_symbol,self.prices)
        to_after=wallet.gross_asset_value(to_symbol,self.prices)
        context={
            "rebound":row["rebound"],"streak":row["streak"],
            "support_delta":row["support_delta"],"family_delta":row["family_delta"],
            "route":route,
        }
        self.conn.execute(
            "INSERT INTO inventory_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                trade_id,self.run_id,mid,ts,from_symbol,to_symbol,trade_usd,
                route["sides"],route["label"],route["fee_cost_bps"],route["spread_proxy_bps"],
                route["total_cost_bps"],cost,row["cheapness_z"],row["persistence"],
                row["gross_edge"],row["net_edge"],batch_count,
                from_before,to_before,from_after,to_after,row["ratio"],js(context),
            ),
        )
        self.conn.execute(
            "INSERT INTO inventory_signal_outcomes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                trade_id,self.run_id,mid,from_symbol,to_symbol,ts,row["ratio"],route["total_cost_bps"],
                0,None,None,0,None,None,0,None,None,ts,
            ),
        )
        self.last_trade_ts[mid]=ts

    def _settle_outcomes(self,ts:float) -> None:
        rows=self.conn.execute(
            """
            SELECT * FROM inventory_signal_outcomes
            WHERE run_id=? AND (settled_10s=0 OR settled_30s=0 OR settled_60s=0)
            """,(self.run_id,)
        ).fetchall()
        for row in rows:
            from_symbol=str(row["from_symbol"])
            to_symbol=str(row["to_symbol"])
            from_price=float(self.prices.get(from_symbol,0.0))
            to_price=float(self.prices.get(to_symbol,0.0))
            entry_ratio=float(row["entry_ratio"] or 0.0)
            if from_price<=0 or to_price<=0 or entry_ratio<=0:
                continue
            current_ratio=to_price/from_price
            capture=(current_ratio/entry_ratio-1.0)*10000.0
            net_capture=capture-float(row["total_route_cost_bps"] or 0.0)
            age=ts-float(row["entry_ts"])
            updates=[]
            params=[]
            for horizon,col in ((10,"10s"),(30,"30s"),(60,"60s")):
                settled=int(row[f"settled_{col}"] or 0)
                if not settled and age>=horizon:
                    updates.extend([f"settled_{col}=1",f"capture_{col}_bps=?",f"net_capture_{col}_bps=?"])
                    params.extend([capture,net_capture])
                    if horizon==30:
                        self._emit_learning_crystal(row,net_capture,capture,horizon,ts)
            if updates:
                updates.append("last_update_ts=?")
                params.append(ts)
                params.append(str(row["trade_id"]))
                self.conn.execute(
                    f"UPDATE inventory_signal_outcomes SET {','.join(updates)} WHERE trade_id=?",
                    tuple(params),
                )

    def _emit_learning_crystal(
        self,row:sqlite3.Row,net_capture:float,gross_capture:float,horizon:int,ts:float
    ) -> None:
        trade=self.conn.execute(
            "SELECT * FROM inventory_trades WHERE trade_id=?",(row["trade_id"],)
        ).fetchone()
        if not trade:
            return
        family="positive_capability" if net_capture>0 else "negative_capability"
        strength=min(1.0,abs(net_capture)/max(1.0,float(trade["total_route_cost_bps"] or 1.0)))
        scope=f"{trade['mutation_id']}|{trade['from_symbol']}->{trade['to_symbol']}|route={trade['route_sides']}|cheap={float(trade['cheapness_z'] or 0):.2f}"
        payload={
            "schema":"hivenance_inventory_drizzle_learning_crystal_v1",
            "candidate_only":True,"automatic_promotion":False,
            "from_symbol":trade["from_symbol"],"to_symbol":trade["to_symbol"],
            "trade_usd":trade["trade_usd"],"route_sides":trade["route_sides"],
            "route_label":trade["route_label"],"total_route_cost_bps":trade["total_route_cost_bps"],
            "cheapness_z":trade["cheapness_z"],"streak_persistence":trade["persistence"],
            "gross_edge_bps":trade["gross_edge_bps"],"expected_net_edge_bps":trade["net_edge_bps"],
            "gross_capture_bps":gross_capture,"net_capture_bps":net_capture,
            "evidence_horizon_sec":horizon,
        }
        self.conn.execute(
            "INSERT INTO inventory_learning_crystals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"inventory-crystal-{uuid.uuid4().hex}",self.run_id,trade["mutation_id"],
                trade["trade_id"],family,scope,trade["from_symbol"],trade["to_symbol"],
                horizon,strength,net_capture,trade["cheapness_z"],trade["persistence"],
                trade["route_sides"],LEARNING_AUTHORITY,
                "candidate_learning_memory_not_promoted",js(payload),ts,
            ),
        )

    def cycle(self) -> None:
        started=time.perf_counter()
        fetch_started=time.perf_counter()
        prices,volumes,meta=self.feed.poll()
        fetch_ms=(time.perf_counter()-fetch_started)*1000.0
        self.prices.update(prices)
        ts=time.time()

        workers={}
        for symbol in self.args.symbols:
            price=float(self.prices.get(symbol,0.0))
            if price<=0:
                continue
            volume=float(volumes.get(symbol,0.0))
            self.worker_series[symbol].add(price,volume)
            self.live_series[symbol].add(price,volume)
            workers[symbol]=self._worker_snapshot(symbol)

        for to_symbol in self.args.symbols:
            tp=float(self.prices.get(to_symbol,0.0))
            if tp<=0:
                continue
            for from_symbol in self.args.symbols:
                if to_symbol==from_symbol:
                    continue
                fp=float(self.prices.get(from_symbol,0.0))
                if fp>0:
                    self.pairs[(to_symbol,from_symbol)].add(tp,fp)

        for mid in MUTATIONS:
            if mid=="inventory_hold":
                continue
            wallet=self.wallets[mid]
            rows=self._candidate_rows(mid,wallet,workers,ts)
            chosen=next((row for row in rows if row["admissible"]),None)
            # Reset stale pending candidates for this mutation.
            active_pair=(chosen["from_symbol"],chosen["to_symbol"]) if chosen else None
            for key in list(self.pending):
                if key[0]==mid and (key[1],key[2])!=active_pair:
                    self.pending[key]=0
            if chosen is None:
                continue
            key=(mid,chosen["from_symbol"],chosen["to_symbol"])
            self.pending[key]+=1
            required=int(chosen["required_confirmations"])
            cooldown=self.args.naive_cooldown_sec if mid=="inventory_naive" else self.args.cooldown_sec
            if self.pending[key]<required:
                continue
            if ts-self.last_trade_ts[mid]<cooldown:
                continue
            self._rebalance(mid,chosen,ts,self.pending[key])
            self.pending[key]=0

        self._settle_outcomes(ts)

        cycle_ms=(time.perf_counter()-started)*1000.0
        for mid,wallet in self.wallets.items():
            gross_values=[wallet.gross_asset_value(s,self.prices) for s in self.args.symbols]
            inventory_gross=sum(gross_values)
            weights=[v/inventory_gross for v in gross_values] if inventory_gross>0 else []
            target=1.0/max(1,len(weights))
            dispersion=sum(abs(w-target) for w in weights)/max(1,len(weights)) if weights else 0.0
            max_weight=max(weights) if weights else 0.0
            equity=wallet.liquidation_equity(
                self.prices,self.feed.last_spread_bps,self.args.cost_bps_side
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO inventory_wallet_marks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    self.run_id,mid,ts,equity,wallet.cash,inventory_gross,
                    wallet.cumulative_cost_usd,wallet.rebalances,wallet.charged_sides,
                    dispersion,max_weight,cycle_ms,
                ),
            )
        self.conn.commit()

        if self.args.verbose or int(ts)%10==0:
            hold=self.wallets["inventory_hold"].liquidation_equity(
                self.prices,self.feed.last_spread_bps,self.args.cost_bps_side
            )
            print(
                f"\n[{time.strftime('%H:%M:%S')}] fetch={fetch_ms:.0f}ms cycle={cycle_ms:.0f}ms "
                f"inventory-drizzle"
            )
            for mid,wallet in self.wallets.items():
                equity=wallet.liquidation_equity(
                    self.prices,self.feed.last_spread_bps,self.args.cost_bps_side
                )
                print(
                    f"  {mid:27s} equity={equity:10.4f} net={equity-self.args.start_usd:+8.4f} "
                    f"excess_vs_hold={equity-hold:+8.4f} cost={wallet.cumulative_cost_usd:7.4f} "
                    f"rebalances={wallet.rebalances:3d}"
                )

    def close(self,status:str) -> None:
        ts=time.time()
        self._settle_outcomes(ts)
        # Liquidate all inventory for fully realized final scorekeeping.
        for mid,wallet in self.wallets.items():
            for symbol in self.args.symbols:
                qty=float(wallet.qty.get(symbol,0.0))
                price=float(self.prices.get(symbol,0.0))
                if qty<=0 or price<=0:
                    continue
                gross=qty*price
                spread=float(self.feed.last_spread_bps.get(symbol,0.0))
                cost_bps=float(self.args.cost_bps_side)+0.5*spread
                cost=gross*cost_bps/10000.0
                wallet.cash+=gross-cost
                wallet.cumulative_cost_usd+=cost
                wallet.charged_sides+=1
                wallet.qty[symbol]=0.0
            self.conn.execute(
                "INSERT OR REPLACE INTO inventory_wallet_marks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    self.run_id,mid,ts,wallet.cash,wallet.cash,0.0,
                    wallet.cumulative_cost_usd,wallet.rebalances,wallet.charged_sides,
                    0.0,0.0,0.0,
                ),
            )
        self.conn.execute(
            "UPDATE inventory_runs SET ended_ts=?,status=? WHERE run_id=?",
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
            f"Starting {self.args.duration_sec}s inventory-drizzle lab. "
            f"inventory={self.args.inventory_usd:.2f} USD; rebalance slice={self.args.rebalance_usd:.2f} USD; "
            "equal-weight hold control; no private keys; no orders."
        )
        deadline=time.monotonic()+self.args.duration_sec
        status="COMPLETE"
        try:
            while time.monotonic()<deadline:
                cycle_started=time.monotonic()
                try:
                    self.cycle()
                except (
                    urllib.error.URLError,urllib.error.HTTPError,TimeoutError,
                    RuntimeError,json.JSONDecodeError
                ) as exc:
                    print(f"WARN inventory-drizzle cycle: {type(exc).__name__}: {exc}")
                time.sleep(max(0.0,self.args.interval_sec-(time.monotonic()-cycle_started)))
        except KeyboardInterrupt:
            status="INTERRUPTED"
        finally:
            self.close(status)
        return 0


def parse_args() -> argparse.Namespace:
    p=argparse.ArgumentParser(description="Paper-only relative inventory volatility-harvest lab")
    p.add_argument("--symbols",nargs="+",default=["BTC/USD","ETH/USD","SOL/USD","XRP/USD","ADA/USD","AVAX/USD","DOGE/USD","HYPE/USD"])
    p.add_argument("--database",default="data/live_inventory_drizzle_lab.db")
    p.add_argument("--duration-sec",type=int,default=900)
    p.add_argument("--interval-sec",type=float,default=1.0)
    p.add_argument("--start-usd",type=float,default=1000.0)
    p.add_argument("--inventory-usd",type=float,default=200.0)
    p.add_argument("--rebalance-usd",type=float,default=5.0)
    p.add_argument("--min-trade-usd",type=float,default=1.0)
    p.add_argument("--inventory-floor-usd",type=float,default=5.0)
    p.add_argument("--max-asset-weight",type=float,default=0.25)
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
    p.add_argument("--min-net-edge-bps",type=float,default=0.5)
    p.add_argument("--batch-confirmations",type=int,default=2)
    p.add_argument("--naive-cooldown-sec",type=float,default=1.0)
    p.add_argument("--cooldown-sec",type=float,default=5.0)
    p.add_argument("--swarm-support-delta-min",type=float,default=0.0)
    p.add_argument("--swarm-family-delta-min",type=int,default=1)
    p.add_argument("--verbose",action="store_true")
    args=p.parse_args()
    if args.interval_sec<0.8:
        p.error("--interval-sec must be >= 0.8")
    if args.duration_sec<30:
        p.error("--duration-sec must be >= 30")
    if args.inventory_usd<=0 or args.inventory_usd>args.start_usd:
        p.error("--inventory-usd must be within the paper wallet")
    if args.rebalance_usd<=0:
        p.error("--rebalance-usd must be positive")
    return args


if __name__=="__main__":
    raise SystemExit(InventoryDrizzleLab(parse_args()).run())
