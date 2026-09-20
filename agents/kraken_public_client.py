"""Minimal Kraken public REST client implementing the ccxt-like surface Phase 1 needs.

Public endpoints only. No credentials, no order methods, no private API.
"""
from __future__ import annotations
import json,time,urllib.parse,urllib.request
from typing import Any

class KrakenPublicClient:
 def __init__(self,timeout:float=12.0,progress:bool=False)->None:
  self.timeout=float(timeout)
  self.progress=bool(progress)
  self.base="https://api.kraken.com/0/public"
  self._pairs:dict[str,dict[str,Any]]|None=None
  self._api_by_symbol:dict[str,str]={}

 def _get(self,path:str,params:dict[str,Any]|None=None)->dict[str,Any]:
  q=urllib.parse.urlencode(params or {})
  if self.progress:
   label=path
   pair=(params or {}).get("pair")
   if pair:
    sample=str(pair)
    if len(sample)>72: sample=sample[:69]+"..."
    label+=f" pair={sample}"
   print(f"[Kraken] GET {label}",flush=True)
  url=self.base+"/"+path+("?"+q if q else "")
  req=urllib.request.Request(url,headers={"User-Agent":"HiveNance-G1-PublicResearch/1.0"})
  with urllib.request.urlopen(req,timeout=self.timeout) as r:
   payload=json.loads(r.read().decode("utf-8"))
  errors=payload.get("error") or []
  if errors: raise RuntimeError("kraken_public_error:"+",".join(map(str,errors)))
  return payload.get("result") or {}

 @staticmethod
 def _norm_asset(x:str)->str:
  x=str(x or "").upper()
  aliases={
   "XXBT":"BTC","XBT":"BTC",
   "XETH":"ETH",
   "XDG":"DOGE","XXDG":"DOGE",
   "ZUSD":"USD","ZUSDT":"USDT","ZUSDC":"USDC",
   "ZEUR":"EUR","ZGBP":"GBP","ZJPY":"JPY","ZCAD":"CAD","ZAUD":"AUD",
  }
  if x in aliases:
   return aliases[x]
  # Kraken internal asset ids sometimes carry a single synthetic X/Z prefix
  # (for example XXBT or ZUSD). Never strip those letters generically because
  # legitimate assets such as XRP, XLM, XMR and ZEC begin with X/Z.
  if len(x)==4 and x[0] in {"X","Z"}:
   candidate=x[1:]
   return aliases.get(x,aliases.get(candidate,candidate))
  return x

 def load_markets(self)->dict[str,dict[str,Any]]:
  if self._pairs is not None:return self._pairs
  raw=self._get("AssetPairs")
  markets={}
  for api_name,row in raw.items():
   ws=str(row.get("wsname") or "")
   alt=str(row.get("altname") or "")
   if "/" in ws:
    base,quote=ws.split("/",1)
   else:
    base=self._norm_asset(row.get("base") or "")
    quote=self._norm_asset(row.get("quote") or "")
   base=self._norm_asset(base);quote=self._norm_asset(quote)
   if not base or not quote:continue
   symbol=f"{base}/{quote}"
   markets[symbol]={"symbol":symbol,"base":base,"quote":quote,"active":True,"spot":True,"type":"spot","info":row}
   self._api_by_symbol[symbol]=api_name
   if alt:self._api_by_symbol[alt]=api_name
  self._pairs=markets
  return markets

 def _api_pair(self,symbol:str)->str:
  if not self._api_by_symbol:self.load_markets()
  if symbol in self._api_by_symbol:return self._api_by_symbol[symbol]
  return symbol.replace("/","")

 def fetch_tickers(self)->dict[str,dict[str,Any]]:
  markets=self.load_markets()
  out={}
  # Kraken accepts comma-separated pairs. Batch to keep URLs sane.
  symbols=list(markets)
  for start in range(0,len(symbols),80):
   batch=symbols[start:start+80]
   lookup={self._api_pair(s):s for s in batch}
   raw=self._get("Ticker",{"pair":",".join(lookup)})
   for key,row in raw.items():
    # Result keys may use exchange-internal names; match by direct or alt normalization.
    symbol=lookup.get(key)
    if symbol is None:
     for s in batch:
      if self._api_pair(s)==key: symbol=s;break
    if symbol is None:continue
    last=float((row.get("c") or [0])[0] or 0)
    vol=float((row.get("v") or [0,0])[-1] or 0)
    vwap=float((row.get("p") or [last,last])[-1] or last)
    bid=float((row.get("b") or [0])[0] or 0);ask=float((row.get("a") or [0])[0] or 0)
    out[symbol]={"symbol":symbol,"last":last,"bid":bid,"ask":ask,
     "quoteVolume":vol*vwap,"baseVolume":vol,"info":row}
  return out

 def fetch_ticker(self,symbol:str)->dict[str,Any]:
  raw=self._get("Ticker",{"pair":self._api_pair(symbol)})
  row=next(iter(raw.values()))
  last=float((row.get("c") or [0])[0] or 0)
  vol=float((row.get("v") or [0,0])[-1] or 0)
  vwap=float((row.get("p") or [last,last])[-1] or last)
  return {"symbol":symbol,"last":last,"bid":float((row.get("b") or [0])[0] or 0),
   "ask":float((row.get("a") or [0])[0] or 0),"quoteVolume":vol*vwap,"baseVolume":vol,"info":row}

 def fetch_ohlcv(self,symbol:str,timeframe:str="1m",limit:int=121)->list[list[float]]:
  mins={"1m":1,"5m":5,"15m":15,"30m":30,"1h":60,"4h":240,"1d":1440,"1w":10080}.get(str(timeframe),1)
  raw=self._get("OHLC",{"pair":self._api_pair(symbol),"interval":mins})
  rows=next((v for k,v in raw.items() if k!="last"),[])
  out=[]
  for r in rows[-int(limit):]:
   # Kraken: time, open, high, low, close, vwap, volume, count
   out.append([int(float(r[0])*1000),float(r[1]),float(r[2]),float(r[3]),float(r[4]),float(r[6])])
  return out

 def fetch_order_book(self,symbol:str,limit:int=50)->dict[str,Any]:
  raw=self._get("Depth",{"pair":self._api_pair(symbol),"count":int(limit)})
  row=next(iter(raw.values()))
  return {"symbol":symbol,
   "bids":[[float(x[0]),float(x[1])] for x in (row.get("bids") or [])],
   "asks":[[float(x[0]),float(x[1])] for x in (row.get("asks") or [])],
   "timestamp":int(time.time()*1000)}
