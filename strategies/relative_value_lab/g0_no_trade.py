"""Explicit research-only NO_TRADE leg for prospective G0 twins."""
from __future__ import annotations
import hashlib,json
from typing import Any,Mapping

def _hash(x:Any)->str:
 return "sha256:"+hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()

def no_trade_intent(*,forecast:Mapping[str,Any],reason:str)->dict[str,Any]:
 ts=float(forecast.get("ts") or (float(forecast.get("timestamp_ms") or 0)/1000.0))
 target=float(forecast.get("target_ts") or (float(forecast.get("target_timestamp_ms") or 0)/1000.0))
 if ts<=0 or target<=ts: raise ValueError("no_trade_forecast_timestamps_invalid")
 body={"forecast_id":str(forecast.get("forecast_id") or ""),"symbol":str(forecast.get("symbol") or ""),
  "model_id":str(forecast.get("model_id") or ""),"created_ts":ts,"target_ts":target,
  "g0_no_trade":True,"reason":str(reason or "ABSTAIN"),"transmission_status":"NEVER_TRANSMITTED",
  "live_eligible":False,"execution_wired":False,"execution_eligible":False,"promotion_eligible":False}
 body["shadow_intent_id"]="g0_no_trade_"+_hash(body).split(":",1)[1][:24]
 return body

def no_trade_settlement(intent:Mapping[str,Any],*,settled_ts:float)->dict[str,Any]:
 return {"shadow_intent_id":intent.get("shadow_intent_id"),"forecast_id":intent.get("forecast_id"),
  "symbol":intent.get("symbol"),"status":"ABSTAIN_NO_TRADE","gross_return_bps":0.0,
  "realized_cost_bps":0.0,"net_return_bps":0.0,"settled_ts":float(settled_ts),
  "transmission_status":"NEVER_TRANSMITTED","private_endpoint_called":False,
  "execution_eligible":False,"promotion_eligible":False}
