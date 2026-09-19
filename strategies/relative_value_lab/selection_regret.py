"""Phase-4 CoinSelector prospective freeze, settlement, and regret analysis.

This phase measures opportunity selection, not directional forecasting.
Selected and rejected candidates are frozen before outcome and settled with the
same direction-neutral future-move and friction convention.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass, asdict
from typing import Any, Mapping, Sequence

AUTHORITY="PUBLIC_MARKET_RESEARCH_SELECTION_REGRET_ONLY_NO_EXECUTION_AUTHORITY"
FREEZE_SCHEMA="hivenance_selector_opportunity_freeze_v1"
SETTLEMENT_SCHEMA="hivenance_selector_opportunity_settlement_v2"
REPORT_SCHEMA="hivenance_selector_regret_report_v2"
DEFAULT_HORIZON_SECONDS=300


def _json(v:Any)->str:
    return json.dumps(v,sort_keys=True,separators=(",",":"),default=str)


def _digest(v:Any)->str:
    return "sha256:"+hashlib.sha256(_json(v).encode()).hexdigest()


def _num(v:Any, default:float|None=None)->float|None:
    try:
        x=float(v)
        return x if math.isfinite(x) else default
    except (TypeError,ValueError):
        return default


def _regime(row:Mapping[str,Any])->str:
    values=row.get("values") if isinstance(row.get("values"),Mapping) else {}
    ri=values.get("regime_inputs") if isinstance(values.get("regime_inputs"),Mapping) else {}
    return str(ri.get("regime_hint") or "unknown")


def _canonical_binding(row:Mapping[str,Any])->Mapping[str,Any]:
    values=row.get("values") if isinstance(row.get("values"),Mapping) else {}
    binding=values.get("canonical_world_binding") if isinstance(values.get("canonical_world_binding"),Mapping) else {}
    return binding


def _blind_rank(world_hash:str,symbol:str)->str:
    return hashlib.sha256(f"{world_hash}|{symbol}|selector_blind_v1".encode()).hexdigest()


def _cost_proxy_bps(row:Mapping[str,Any], *, taker_fee_bps_per_side:float) -> float:
    spread=max(0.0,float(_num(row.get("spread_bps"),0.0) or 0.0))
    depth=max(0.0,float(_num(row.get("depth_usd_25bps"),0.0) or 0.0))
    # Fixed research notional keeps selected/rejected economics identical.
    notional=10.0
    impact=25.0*math.sqrt(min(1.0,notional/max(depth,notional,1e-9)))
    return spread + 2.0*max(0.0,float(taker_fee_bps_per_side)) + 2.0*impact


def ensure_tables(store:Any)->None:
    with store._lock:
        store.conn.execute("""
        CREATE TABLE IF NOT EXISTS full_organism_selector_freezes(
            freeze_id TEXT PRIMARY KEY,
            run_id TEXT,
            observed_ts REAL,
            target_ts REAL,
            symbol TEXT,
            selector_rank INTEGER,
            selector_score REAL,
            selected INTEGER,
            blind_rank INTEGER,
            blind_selected INTEGER,
            payload TEXT
        )""")
        store.conn.execute("CREATE INDEX IF NOT EXISTS idx_selector_freezes_target ON full_organism_selector_freezes(target_ts)")
        store.conn.execute("CREATE INDEX IF NOT EXISTS idx_selector_freezes_run ON full_organism_selector_freezes(run_id)")
        store.conn.execute("""
        CREATE TABLE IF NOT EXISTS full_organism_selector_settlements(
            settlement_id TEXT PRIMARY KEY,
            freeze_id TEXT UNIQUE,
            settled_ts REAL,
            symbol TEXT,
            selected INTEGER,
            selector_rank INTEGER,
            regime TEXT,
            payload TEXT
        )""")
        store.conn.execute("CREATE INDEX IF NOT EXISTS idx_selector_settle_symbol ON full_organism_selector_settlements(symbol,settled_ts)")
        # V2 corrects the Phase-4 clock domain: settlement eligibility is based
        # on observer custody time (observation_runs.completed_ts), not candle timestamp.
        # V1 is retained immutably as superseded experimental evidence.
        store.conn.execute("""
        CREATE TABLE IF NOT EXISTS full_organism_selector_settlements_v2(
            settlement_id TEXT PRIMARY KEY,
            freeze_id TEXT UNIQUE,
            settled_ts REAL,
            symbol TEXT,
            selected INTEGER,
            selector_rank INTEGER,
            regime TEXT,
            payload TEXT
        )""")
        store.conn.execute("CREATE INDEX IF NOT EXISTS idx_selector_settle_v2_symbol ON full_organism_selector_settlements_v2(symbol,settled_ts)")
        store.conn.commit()


def freeze_selector_universe(
    *,
    store:Any,
    run_id:str,
    comparison_universe:Sequence[Mapping[str,Any]],
    observed_at_ms:int,
    shortlist_size:int,
    horizon_seconds:int=DEFAULT_HORIZON_SECONDS,
    taker_fee_bps_per_side:float=20.0,
)->dict[str,Any]:
    ensure_tables(store)
    observed_ts=float(observed_at_ms)/1000.0
    target_ts=observed_ts+int(horizon_seconds)
    rows=[dict(x) for x in comparison_universe if isinstance(x,Mapping)]
    # Freeze selector-blind counterfactual over exact same candidate universe.
    blind_order=sorted(
        rows,
        key=lambda r: _blind_rank(
            str((_canonical_binding(r).get("canonical_world_state_hash") or "")),
            str(r.get("symbol") or ""),
        ),
    )
    blind_selected={str(r.get("symbol") or "") for r in blind_order[:max(0,int(shortlist_size))]}
    blind_rank_by_symbol={str(r.get("symbol") or ""):i for i,r in enumerate(blind_order,start=1)}

    created=0
    selected_count=0
    rejected_count=0
    with store._lock:
        for row in rows:
            symbol=str(row.get("symbol") or "")
            if not symbol:continue
            binding=_canonical_binding(row)
            world_id=str(binding.get("canonical_world_state_id") or "")
            world_hash=str(binding.get("canonical_world_state_hash") or "")
            root=str(binding.get("feature_memory_line_id") or "")
            selected=bool(row.get("selected_for_phase2"))
            selector_rank=int(row.get("comparison_rank") or 0)
            selector_score=float(_num(row.get("score"),0.0) or 0.0)
            payload={
                "schema":FREEZE_SCHEMA,
                "authority":AUTHORITY,
                "run_id":str(run_id),
                "symbol":symbol,
                "venue":str(row.get("venue") or ""),
                "observed_at_ms":int(observed_at_ms),
                "observed_ts":observed_ts,
                "target_ts":target_ts,
                "horizon_seconds":int(horizon_seconds),
                "reference_price":_num(row.get("price")),
                "spread_bps":_num(row.get("spread_bps"),0.0),
                "depth_usd_25bps":_num(row.get("depth_usd_25bps"),0.0),
                "data_quality":_num(row.get("data_quality"),0.0),
                "selector_rank":selector_rank,
                "selector_score":selector_score,
                "selected":selected,
                "rejection_reasons":list(row.get("rejection_reasons") or ()),
                "regime":_regime(row),
                "canonical_world_state_id":world_id,
                "canonical_world_state_hash":world_hash,
                "evidence_root":root,
                "predicted_roundtrip_cost_bps":_cost_proxy_bps(
                    row,taker_fee_bps_per_side=taker_fee_bps_per_side
                ),
                "blind_rank":blind_rank_by_symbol.get(symbol),
                "blind_selected":symbol in blind_selected,
                "execution_eligible":False,
                "promotion_eligible":False,
            }
            freeze_id=_digest({
                "run_id":run_id,"symbol":symbol,"observed_at_ms":observed_at_ms,
                "world_hash":world_hash,"selector_rank":selector_rank,
                "selected":selected,"horizon_seconds":int(horizon_seconds),
            })
            payload["freeze_id"]=freeze_id
            cur=store.conn.execute(
                """INSERT OR IGNORE INTO full_organism_selector_freezes
                (freeze_id,run_id,observed_ts,target_ts,symbol,selector_rank,selector_score,selected,blind_rank,blind_selected,payload)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    freeze_id,str(run_id),observed_ts,target_ts,symbol,selector_rank,selector_score,
                    1 if selected else 0,int(blind_rank_by_symbol.get(symbol) or 0),
                    1 if symbol in blind_selected else 0,_json(payload),
                ),
            )
            if int(cur.rowcount or 0)>0:created+=1
            selected_count+=1 if selected else 0
            rejected_count+=0 if selected else 1
        store.conn.commit()
    return {
        "schema":"hivenance_selector_freeze_summary_v1",
        "run_id":str(run_id),"created":created,"universe_n":len(rows),
        "selected_n":selected_count,"rejected_n":rejected_count,
        "horizon_seconds":int(horizon_seconds),
        "authority":AUTHORITY,"execution_eligible":False,"promotion_eligible":False,
    }


def _future_observations(store:Any, symbol:str, created_ts:float, target_ts:float, tolerance_sec:float)->list[dict[str,Any]]:
    """Return snapshots by *custody time*, not market-candle timestamp.

    The observation row's ts is a market timestamp and may remain fixed while
    repeated public snapshots are collected inside the same candle. Prospective
    settlement therefore joins to observation_runs.completed_ts, which records
    when HiveNance actually possessed that snapshot.
    """
    with store._lock:
        cur=store.conn.execute(
            """SELECT u.run_id,r.completed_ts,u.ts,u.price,u.spread_bps,u.depth_usd_25bps,u.data_quality,u.payload
               FROM observation_universe_snapshots u
               JOIN observation_runs r ON r.run_id=u.run_id
               WHERE u.symbol=? AND r.completed_ts>? AND r.completed_ts<=?
               ORDER BY r.completed_ts ASC""",
            (symbol,float(created_ts),float(target_ts+tolerance_sec)),
        )
        rows=cur.fetchall()
    out=[]
    for run_id,custody_ts,market_ts,price,spread,depth,quality,raw in rows:
        out.append({
            "run_id":str(run_id),
            "ts":float(custody_ts),
            "custody_ts":float(custody_ts),
            "market_ts":float(market_ts or 0.0),
            "price":_num(price),"spread_bps":_num(spread,0.0),
            "depth_usd_25bps":_num(depth,0.0),"data_quality":_num(quality,0.0),
        })
    return out

def settle_mature_selector_freezes(
    *,
    store:Any,
    now_ts:float,
    tolerance_sec:float=180.0,
    limit:int=2000,
)->dict[str,Any]:
    ensure_tables(store)
    with store._lock:
        cur=store.conn.execute(
            """SELECT f.payload FROM full_organism_selector_freezes f
               LEFT JOIN full_organism_selector_settlements_v2 s ON s.freeze_id=f.freeze_id
               WHERE s.freeze_id IS NULL AND f.target_ts<=?
               ORDER BY f.target_ts ASC LIMIT ?""",
            (float(now_ts),max(1,int(limit))),
        )
        raw_rows=[r[0] for r in cur.fetchall()]
    examined=settled=deferred=0
    status_counts={}
    for raw in raw_rows:
        examined+=1
        try:p=json.loads(raw or "{}")
        except Exception:continue
        symbol=str(p.get("symbol") or "")
        obs=_future_observations(store,symbol,float(p.get("observed_ts") or 0),float(p.get("target_ts") or 0),float(tolerance_sec))
        target=float(p.get("target_ts") or 0)
        exits=[x for x in obs if float(x.get("ts") or 0)>=target and _num(x.get("price")) is not None]
        if not exits:
            deferred+=1
            status_counts["future_tape_required"]=status_counts.get("future_tape_required",0)+1
            continue
        entry=float(_num(p.get("reference_price"),0.0) or 0.0)
        exit_row=exits[0]
        exit_price=float(_num(exit_row.get("price"),0.0) or 0.0)
        if entry<=0 or exit_price<=0:
            deferred+=1
            status_counts["invalid_price"]=status_counts.get("invalid_price",0)+1
            continue
        gross_abs=abs((exit_price/entry)-1.0)*10000.0
        predicted_cost=float(_num(p.get("predicted_roundtrip_cost_bps"),0.0) or 0.0)
        # Realized cost uses the same model for both selected and rejected, with
        # exit spread/depth updating from the later public snapshot.
        entry_spread=float(_num(p.get("spread_bps"),0.0) or 0.0)
        exit_spread=float(_num(exit_row.get("spread_bps"),0.0) or 0.0)
        entry_depth=max(0.0,float(_num(p.get("depth_usd_25bps"),0.0) or 0.0))
        exit_depth=max(0.0,float(_num(exit_row.get("depth_usd_25bps"),0.0) or 0.0))
        notional=10.0
        entry_impact=25.0*math.sqrt(min(1.0,notional/max(entry_depth,notional,1e-9)))
        exit_impact=25.0*math.sqrt(min(1.0,notional/max(exit_depth,notional,1e-9)))
        # Fees are frozen into predicted cost. Preserve their component by
        # replacing only the entry-spread/impact proxy with observed exit terms.
        entry_variable=entry_spread+2.0*entry_impact
        fixed_fee=max(0.0,predicted_cost-entry_variable)
        realized_cost=entry_spread+exit_spread+entry_impact+exit_impact+fixed_fee
        net_opportunity=gross_abs-realized_cost
        settlement={
            "schema":SETTLEMENT_SCHEMA,
            "authority":AUTHORITY,
            "freeze_id":p["freeze_id"],"run_id":p["run_id"],"symbol":symbol,
            "selected":bool(p.get("selected")),"selector_rank":int(p.get("selector_rank") or 0),
            "selector_score":float(p.get("selector_score") or 0.0),
            "blind_rank":int(p.get("blind_rank") or 0),"blind_selected":bool(p.get("blind_selected")),
            "regime":str(p.get("regime") or "unknown"),
            "observed_ts":float(p.get("observed_ts") or 0),"target_ts":target,
            "exit_ts":float(exit_row["ts"]),"exit_custody_ts":float(exit_row["custody_ts"]),
            "exit_market_ts":float(exit_row.get("market_ts") or 0.0),
            "exit_observation_run_id":str(exit_row.get("run_id") or ""),
            "settlement_clock":"OBSERVATION_RUN_COMPLETED_TS",
            "entry_price":entry,"exit_price":exit_price,
            "gross_absolute_move_bps":gross_abs,
            "realized_roundtrip_cost_bps":realized_cost,
            "net_opportunity_bps":net_opportunity,
            "profitable_opportunity":net_opportunity>0,
            "canonical_world_state_id":p.get("canonical_world_state_id"),
            "canonical_world_state_hash":p.get("canonical_world_state_hash"),
            "evidence_root":p.get("evidence_root"),
            "execution_eligible":False,"promotion_eligible":False,
        }
        sid=_digest({"freeze_id":p["freeze_id"],"exit_ts":exit_row["ts"],"schema":SETTLEMENT_SCHEMA})
        settlement["settlement_id"]=sid
        with store._lock:
            store.conn.execute(
                """INSERT OR IGNORE INTO full_organism_selector_settlements_v2
                (settlement_id,freeze_id,settled_ts,symbol,selected,selector_rank,regime,payload)
                VALUES(?,?,?,?,?,?,?,?)""",
                (sid,p["freeze_id"],float(now_ts),symbol,1 if p.get("selected") else 0,
                 int(p.get("selector_rank") or 0),str(p.get("regime") or "unknown"),_json(settlement)),
            )
            store.conn.commit()
        settled+=1
        status_counts["settled"]=status_counts.get("settled",0)+1
    return {
        "examined":examined,"settled":settled,"deferred":deferred,
        "status_counts":status_counts,"execution_eligible":False,"promotion_eligible":False,
    }


def selector_regret_report(store:Any, *, run_id:str|None=None)->dict[str,Any]:
    ensure_tables(store)
    q="""SELECT s.payload FROM full_organism_selector_settlements_v2 s
         JOIN full_organism_selector_freezes f ON f.freeze_id=s.freeze_id"""
    args=[]
    if run_id:
        q+=" WHERE f.run_id=?";args=[str(run_id)]
    with store._lock:
        rows=store.conn.execute(q,args).fetchall()
    settled=[]
    for (raw,) in rows:
        try:p=json.loads(raw or "{}")
        except Exception:continue
        settled.append(p)
    selected=[x for x in settled if x.get("selected") is True]
    rejected=[x for x in settled if x.get("selected") is False]
    blind_selected=[x for x in settled if x.get("blind_selected") is True]

    def mean(xs,key):
        vals=[float(x.get(key) or 0.0) for x in xs]
        return sum(vals)/len(vals) if vals else 0.0
    selected_mean=mean(selected,"net_opportunity_bps")
    rejected_mean=mean(rejected,"net_opportunity_bps")
    blind_mean=mean(blind_selected,"net_opportunity_bps")

    k=len(selected)
    ranked=sorted(settled,key=lambda x:int(x.get("selector_rank") or 10**9))
    topk_actual=ranked[:k] if k else []
    oracle=sorted(settled,key=lambda x:float(x.get("net_opportunity_bps") or 0.0),reverse=True)[:k] if k else []
    selector_topk=mean(topk_actual,"net_opportunity_bps")
    oracle_topk=mean(oracle,"net_opportunity_bps")
    ranking_regret=max(0.0,oracle_topk-selector_topk)

    positive_rejected=[x for x in rejected if float(x.get("net_opportunity_bps") or 0.0)>0]
    positive_all=[x for x in settled if float(x.get("net_opportunity_bps") or 0.0)>0]
    captured=sum(1 for x in selected if float(x.get("net_opportunity_bps") or 0.0)>0)
    opportunity_capture=captured/len(positive_all) if positive_all else 0.0
    missed_rate=len(positive_rejected)/len(positive_all) if positive_all else 0.0

    regimes={}
    for rg in sorted({str(x.get("regime") or "unknown") for x in settled}):
        a=[x for x in selected if str(x.get("regime") or "unknown")==rg]
        b=[x for x in rejected if str(x.get("regime") or "unknown")==rg]
        regimes[rg]={
            "selected_n":len(a),"rejected_n":len(b),
            "selected_mean_net_opportunity_bps":mean(a,"net_opportunity_bps"),
            "rejected_mean_net_opportunity_bps":mean(b,"net_opportunity_bps"),
            "selector_delta_bps":mean(a,"net_opportunity_bps")-mean(b,"net_opportunity_bps") if a and b else None,
        }

    return {
        "schema":REPORT_SCHEMA,"authority":AUTHORITY,
        "settlement_schema":SETTLEMENT_SCHEMA,
        "settlement_clock":"OBSERVATION_RUN_COMPLETED_TS",
        "supersedes_settlement_schema":"hivenance_selector_opportunity_settlement_v1",
        "run_id":run_id,
        "settled_n":len(settled),"selected_n":len(selected),"rejected_n":len(rejected),
        "selected_mean_net_opportunity_bps":selected_mean,
        "rejected_mean_net_opportunity_bps":rejected_mean,
        "selected_minus_rejected_bps":selected_mean-rejected_mean if selected and rejected else None,
        "blind_selected_mean_net_opportunity_bps":blind_mean,
        "selector_minus_blind_bps":selected_mean-blind_mean if selected and blind_selected else None,
        "opportunity_capture_rate":opportunity_capture,
        "missed_opportunity_rate":missed_rate,
        "ranking_regret_bps":ranking_regret,
        "selector_topk_mean_bps":selector_topk,
        "oracle_topk_mean_bps":oracle_topk,
        "regime_specific":regimes,
        "execution_eligible":False,"promotion_eligible":False,
    }
