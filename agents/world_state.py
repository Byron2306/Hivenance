from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from agents.horizon_context import HorizonContextAgent

AUTHORITY="PUBLIC_MARKET_RESEARCH_WORLD_STATE_ONLY_NO_EXECUTION_AUTHORITY"
SCHEMA="hivenance_world_state_page_v1"

def _digest(v:Any)->str:
    raw=json.dumps(v,sort_keys=True,separators=(",",":"),default=str).encode()
    return "sha256:"+hashlib.sha256(raw).hexdigest()

def _ret(rows:list[dict[str,Any]],bars:int)->float|None:
    if bars<=0 or len(rows)<=bars:return None
    a=float(rows[-bars-1]["close"]); b=float(rows[-1]["close"])
    return (b/a-1)*10000 if a>0 and b>0 else None

@dataclass(frozen=True)
class WorldStatePage:
    world_state_id:str
    asof_ts_ms:int
    symbol:str
    selector:dict[str,Any]
    horizon:dict[str,Any]
    temporal:dict[str,Any]
    provenance:dict[str,Any]
    authority:str=AUTHORITY
    execution_eligible:bool=False
    promotion_eligible:bool=False
    def to_dict(self)->dict[str,Any]: return asdict(self)

class WorldStateBuilder:
    """Build one replayable state page from the canonical Market Memory."""

    def __init__(self,memory)->None:
        self.memory=memory
        self.horizon=HorizonContextAgent()

    def _bars_until(self,symbol:str,tf:str,asof:int,limit:int=721)->list[dict[str,Any]]:
        rows=self.memory.bars(symbol,tf,limit=100000)
        rows=[r for r in rows if int(r["open_ts_ms"])<=asof]
        return rows[-limit:]

    def build(self,symbol:str,asof_ts_ms:int,peer_symbols:list[str])->WorldStatePage:
        one=self._bars_until(symbol,"1m",asof_ts_ms)
        h1=self._bars_until(symbol,"1h",asof_ts_ms)
        d1=self._bars_until(symbol,"1d",asof_ts_ms)
        if not one: raise ValueError(f"no 1m memory for {symbol} at {asof_ts_ms}")
        returns={
            "10s":None,"30s":None,
            "2m":_ret(one,2),"5m":_ret(one,5),"15m":_ret(one,15),"1h":_ret(one,60),
        }
        cross={k:[] for k in ("30s","2m","5m","15m","1h")}
        for peer in peer_symbols:
            pr=self._bars_until(peer,"1m",asof_ts_ms)
            for k,bars in (("2m",2),("5m",5),("15m",15),("1h",60)):
                v=_ret(pr,bars)
                if v is not None: cross[k].append(v)
        latest=one[-1]
        daily=d1[-1] if d1 else latest
        context=self.horizon.build(
            symbol=symbol,timestamp=asof_ts_ms/1000.0,returns_bps=returns,
            realized_vol_bps={"30s":None,"5m":None},
            ticker_24h={"open":daily["open"],"last":latest["close"],"high":daily["high"],"low":daily["low"]},
            cross_sectional_returns=cross,
        ).to_dict()
        temporal={
            "15m_bps":_ret(one,15),"1h_bps":_ret(one,60),
            "4h_bps":_ret(h1,4),"24h_bps":_ret(h1,24),
            "7d_bps":_ret(d1,7),"30d_bps":_ret(d1,30),
            "365d_bps":_ret(d1,365),
        }
        selector={
            "quote_volume_proxy":float(daily.get("volume") or 0)*float(latest["close"]),
            "temporal_returns_bps":temporal,
        }
        prov={"memory_schema":"hivenance_market_memory_v1","latest_1m_ts_ms":int(latest["open_ts_ms"]),
              "bars":{"1m":len(one),"1h":len(h1),"1d":len(d1)}}
        body={"symbol":symbol,"asof_ts_ms":int(asof_ts_ms),"selector":selector,"horizon":context,
              "temporal":temporal,"provenance":prov}
        return WorldStatePage(_digest(body),int(asof_ts_ms),symbol,selector,context,temporal,prov)
