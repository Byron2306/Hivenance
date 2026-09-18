#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from scripts.run_live_profit_streak_swarm import KrakenPublicFeed
from strategies.relative_value_lab.pair_graph import RelativeValueGraph
from strategies.relative_value_lab.pair_lab import PairRelationshipLab


def _load_price_points(
    database: Path,
    symbols: list[str],
    *,
    lookback_sec: int,
) -> tuple[dict[str,list[tuple[float,float]]], float | None, float | None]:
    conn=sqlite3.connect(database)
    conn.row_factory=sqlite3.Row
    try:
        now=time.time()
        cutoff=now-float(lookback_sec)
        out={}
        global_min=None
        global_max=None
        for symbol in symbols:
            rows=conn.execute(
                """
                SELECT ts,price FROM horizon_ticks
                WHERE symbol=? AND ts>=?
                ORDER BY ts ASC
                """,
                (symbol,cutoff),
            ).fetchall()
            points=[]
            for row in rows:
                ts=float(row["ts"] or 0.0)
                price=float(row["price"] or 0.0)
                if ts>0 and price>0:
                    points.append((ts,price))
                    global_min=ts if global_min is None else min(global_min,ts)
                    global_max=ts if global_max is None else max(global_max,ts)
            out[symbol]=points
        return out,global_min,global_max
    finally:
        conn.close()


def _direct_routes(symbols:list[str]) -> set[frozenset[str]]:
    feed=KrakenPublicFeed(symbols)
    pairs=feed._get("AssetPairs",{})
    routes=set()
    for info in pairs.values():
        if not isinstance(info,dict):
            continue
        ws=feed._canonical_wsname(str(info.get("wsname") or ""))
        if "/" not in ws:
            continue
        left,right=ws.split("/",1)
        # We store routes in the same symbol-name space used by the scanner when
        # possible. For USD-quoted symbols this catches direct base/base markets
        # only when Kraken exposes one with a recognizable wsname.
        routes.add(frozenset((left.upper(),right.upper())))
    return routes


def _route_set_for_symbols(symbols:list[str],raw:set[frozenset[str]]) -> set[frozenset[str]]:
    bases={s:s.split("/",1)[0].upper() for s in symbols}
    out=set()
    for a in symbols:
        for b in symbols:
            if a>=b:
                continue
            if frozenset((bases[a],bases[b])) in raw:
                out.add(frozenset((a,b)))
    return out


def _ensure_schema(conn:sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pair_lab_runs(
          run_id TEXT PRIMARY KEY,
          created_ts REAL,
          horizon_database TEXT,
          lookback_sec INTEGER,
          sample_interval_sec REAL,
          symbol_count INTEGER,
          pair_count INTEGER,
          eligible_pair_count INTEGER,
          config_json TEXT
        );
        CREATE TABLE IF NOT EXISTS pair_relationships(
          run_id TEXT,
          pair_id TEXT,
          symbol_a TEXT,
          symbol_b TEXT,
          stability_score REAL,
          eligible INTEGER,
          half_life_seconds REAL,
          spread_zscore REAL,
          direct_route_available INTEGER,
          structural_break_state TEXT,
          rejection_reasons_json TEXT,
          diagnostics_json TEXT,
          crystal_json TEXT,
          PRIMARY KEY(run_id,pair_id)
        );
        """
    )


def main() -> int:
    p=argparse.ArgumentParser(description="Analyze Horizon history as Phoenix relative-value pair relationships")
    p.add_argument("--horizon-database",default="data/hivenance_horizon_context.db")
    p.add_argument("--database",default="data/relative_value_pair_lab.db")
    p.add_argument("--symbols",nargs="+",default=[
        "BTC/USD","ETH/USD","SOL/USD","XRP/USD",
        "ADA/USD","AVAX/USD","DOGE/USD","HYPE/USD",
    ])
    p.add_argument("--lookback-sec",type=int,default=3600)
    p.add_argument("--sample-interval-sec",type=float,default=5.0)
    p.add_argument("--min-samples",type=int,default=60)
    p.add_argument("--min-return-correlation",type=float,default=0.10)
    p.add_argument("--min-stability-score",type=float,default=0.45)
    args=p.parse_args()

    horizon=Path(args.horizon_database)
    if not horizon.exists():
        print(f"Horizon database not found: {horizon}")
        return 2

    points,oldest_ts,newest_ts=_load_price_points(horizon,args.symbols,lookback_sec=args.lookback_sec)
    usable={s:v for s,v in points.items() if len(v)>=args.min_samples}
    if len(usable)<2:
        counts=", ".join(f"{s}={len(v)}" for s,v in points.items())
        freshness="unknown"
        if newest_ts is not None:
            freshness=f"{max(0.0,time.time()-newest_ts):.1f}s old"
        print(f"Not enough warmed symbols for pair analysis. {counts}")
        print(f"latest_horizon_tick={freshness}")
        return 3

    try:
        raw_routes=_direct_routes(list(usable))
        routes=_route_set_for_symbols(list(usable),raw_routes)
    except Exception as exc:
        routes=set()
        print(f"WARN direct-route discovery unavailable: {type(exc).__name__}: {exc}")

    lab=PairRelationshipLab(
        min_samples=args.min_samples,
        min_return_correlation=args.min_return_correlation,
        min_stability_score=args.min_stability_score,
    )
    graph=RelativeValueGraph(lab)
    observed_at_ms=int(time.time()*1000)
    edges,crystals,diagnostics=graph.analyze_timestamped_basket(
        points=usable,
        sample_interval_sec=args.sample_interval_sec,
        venue="kraken",
        observed_at_ms=observed_at_ms,
        direct_routes=routes,
    )

    run_id=f"pairlab-{observed_at_ms}"
    db=Path(args.database)
    db.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(db)
    try:
        _ensure_schema(conn)
        eligible=sum(1 for edge in edges if edge.eligible)
        config={
            "symbols":list(usable),
            "timestamp_alignment":"common_floor_buckets_latest_sample",
            "oldest_tick_ts":oldest_ts,
            "newest_tick_ts":newest_ts,
            "newest_tick_age_sec":None if newest_ts is None else max(0.0,time.time()-newest_ts),
            "requested_symbols":args.symbols,
            "min_samples":args.min_samples,
            "min_return_correlation":args.min_return_correlation,
            "min_stability_score":args.min_stability_score,
        }
        conn.execute(
            """
            INSERT INTO pair_lab_runs(
              run_id, created_ts, horizon_database, lookback_sec,
              sample_interval_sec, symbol_count, pair_count,
              eligible_pair_count, config_json
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,time.time(),str(horizon),args.lookback_sec,args.sample_interval_sec,
                len(usable),len(edges),eligible,json.dumps(config,sort_keys=True),
            ),
        )
        for edge in edges:
            diag=diagnostics[edge.pair_id]
            crystal=crystals[edge.pair_id]
            conn.execute(
                "INSERT INTO pair_relationships VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,edge.pair_id,edge.symbol_a,edge.symbol_b,
                    edge.stability_score,int(edge.eligible),edge.half_life_seconds,
                    edge.spread_zscore,int(edge.direct_route_available),
                    diag.structural_break_state,
                    json.dumps(list(diag.rejection_reasons),sort_keys=True),
                    json.dumps(diag.to_dict(),sort_keys=True,default=str),
                    json.dumps(crystal.to_dict(),sort_keys=True,default=str),
                ),
            )
        conn.commit()
    finally:
        conn.close()

    print(f"Phoenix Pair Laboratory // {run_id}")
    print(f"warmed_symbols={len(usable)} pairs={len(edges)} eligible={sum(1 for e in edges if e.eligible)}")
    print(f"lookback={args.lookback_sec}s sample_interval={args.sample_interval_sec:.1f}s")
    if newest_ts is not None:
        print(f"latest_horizon_tick_age={max(0.0,time.time()-newest_ts):.1f}s timestamp_alignment=common_buckets")
    print()
    print("Ranked pair relationships")
    print("-------------------------")
    for edge in edges:
        half="n/a" if edge.half_life_seconds is None else f"{edge.half_life_seconds:.1f}s"
        z="n/a" if edge.spread_zscore is None else f"{edge.spread_zscore:+.2f}z"
        status="ELIGIBLE" if edge.eligible else "REFUSE"
        reasons=",".join(edge.rejection_reasons[:3]) if edge.rejection_reasons else "-"
        print(
            f"{edge.pair_id:24s} {status:8s} "
            f"stability={edge.stability_score:.3f} half={half:>8s} "
            f"spread={z:>8s} direct={int(edge.direct_route_available)} "
            f"reasons={reasons}"
        )
    print()
    print(f"SQLite: {db}")
    print("AUTHORITY: research_evidence_only_no_execution_or_promotion_authority")
    print("PRIVATE ORDERS: 0")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
