"""Audit whether synthesis context can causally reach Phoenix forecast formation."""
from __future__ import annotations
import inspect
from typing import Any
from strategies.volatility_breakout import hypothesis_models

SYNTHESIS_KEY="synthesis_context"

def model_consumption_census(competition:Any)->dict[str,Any]:
 rows=[]
 for model in (*getattr(competition,"primary_models",()),*getattr(competition,"federated_models",()),
               *getattr(competition,"worker_models",()),*getattr(competition,"medium_trend_models",()),
               *getattr(competition,"derivatives_trend_models",()),*getattr(competition,"baseline_models",())):
  cls=type(model)
  try:src=inspect.getsource(cls.forecast)
  except Exception:src=""
  rows.append({"model_id":str(getattr(model,"model_id",cls.__name__)),
   "reads_synthesis_context":SYNTHESIS_KEY in src,
   "forecast_owner":f"{cls.__module__}.{cls.__name__}"})
 return {"schema":"hivenance_g0_model_consumption_census_v1","models":tuple(rows),
  "consumers":tuple(x["model_id"] for x in rows if x["reads_synthesis_context"]),
  "authority":"RESEARCH_AUDIT_ONLY","execution_eligible":False,"promotion_eligible":False}
