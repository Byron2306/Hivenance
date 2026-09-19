"""G1 prospective organ-utility campaign over canonical G0 twin settlements.

G1 never authorizes execution or promotion. It upgrades descriptive G0 outcomes
into a stricter prospective research verdict using predeclared sample, uncertainty,
cost-stress, and drawdown gates.
"""
from __future__ import annotations
import hashlib,json,math
from dataclasses import asdict,dataclass
from statistics import mean,stdev
from typing import Any,Iterable,Mapping

AUTHORITY="SYNTHESIS_G1_PROSPECTIVE_RESEARCH_ONLY"

def _json(x:Any)->str:return json.dumps(x,sort_keys=True,separators=(",",":"),default=str)
def _hash(x:Any)->str:return "sha256:"+hashlib.sha256(_json(x).encode()).hexdigest()

@dataclass(frozen=True)
class G1CampaignPolicy:
 min_pairs:int=30
 confidence_z:float=1.96
 extra_cost_stress_bps:float=5.0
 min_mean_delta_bps:float=0.0
 max_delta_drawdown_bps:float=250.0
 min_distinct_worlds:int=10
 def to_dict(self)->dict[str,Any]:return asdict(self)

@dataclass(frozen=True)
class G1OrganUtilityReport:
 organ_id:str
 paired_n:int
 distinct_worlds:int
 mean_delta_bps:float
 median_delta_bps:float
 ci_lower_bps:float
 ci_upper_bps:float
 stressed_mean_delta_bps:float
 positive_pairs:int
 negative_pairs:int
 zero_pairs:int
 full_acted:int
 ablated_acted:int
 full_only_acted:int
 ablated_only_acted:int
 neither_acted:int
 max_delta_drawdown_bps:float
 classification:str
 reasons:tuple[str,...]
 policy:Mapping[str,Any]
 report_id:str
 authority:str=AUTHORITY
 execution_eligible:bool=False
 promotion_eligible:bool=False
 def to_dict(self)->dict[str,Any]:return asdict(self)

def _median(xs:list[float])->float:
 if not xs:return 0.0
 ys=sorted(xs);n=len(ys);m=n//2
 return ys[m] if n%2 else (ys[m-1]+ys[m])/2.0

def _drawdown(xs:list[float])->float:
 equity=0.0;peak=0.0;worst=0.0
 for x in xs:
  equity+=float(x);peak=max(peak,equity);worst=max(worst,peak-equity)
 return worst

def _ci(xs:list[float],z:float)->tuple[float,float]:
 if not xs:return (0.0,0.0)
 m=mean(xs)
 if len(xs)<2:return (m,m)
 se=stdev(xs)/math.sqrt(len(xs));margin=float(z)*se
 return m-margin,m+margin

def _stressed_delta(row:Mapping[str,Any],extra_cost_bps:float)->float:
 full=float(row.get("full_net_bps") or 0.0)
 blind=float(row.get("ablated_net_bps") or 0.0)
 if bool(row.get("full_acted")):full-=float(extra_cost_bps)
 if bool(row.get("ablated_acted")):blind-=float(extra_cost_bps)
 return full-blind

def load_prospective_outcomes(data_store:Any,*,organ_id:str|None=None,
 campaign_id:str|None=None,target_id:str|None=None)->tuple[dict[str,Any],...]:
 if not getattr(data_store,"conn",None):return ()
 try:
  with data_store._lock:
   cur=data_store.conn.execute("""SELECT s.settled_ts,s.payload,t.payload
    FROM phase5_g0_shadow_twin_settlements s
    LEFT JOIN phase5_g0_shadow_twins t ON t.twin_freeze_id=s.twin_freeze_id
    ORDER BY s.settled_ts""")
   rows=cur.fetchall()
 except Exception:return ()
 out=[]
 for settled_ts,raw,twin_raw in rows:
  try:p=json.loads(raw or "{}")
  except Exception:continue
  try:twin=json.loads(twin_raw or "{}")
  except Exception:twin={}
  pair=p.get("paired_outcome") if isinstance(p.get("paired_outcome"),dict) else {}
  if str(pair.get("evidence_class") or "")!="PROSPECTIVE":continue
  if organ_id and str(pair.get("organ_id") or "")!=str(organ_id):continue
  if campaign_id and str(pair.get("research_campaign_id") or "")!=str(campaign_id):continue
  if target_id and str(pair.get("research_target_id") or "")!=str(target_id):continue
  q=dict(pair);q["settled_ts"]=float(settled_ts)
  fi=twin.get("full_intent") if isinstance(twin.get("full_intent"),dict) else {}
  q["model_id"]=str(fi.get("model_id") or "")
  q["horizon_seconds"]=int(fi.get("horizon_seconds") or 0)
  q["symbol"]=str(fi.get("symbol") or "")
  out.append(q)
 return tuple(out)

def evaluate_organ_utility(rows:Iterable[Mapping[str,Any]],*,organ_id:str,policy:G1CampaignPolicy|None=None)->G1OrganUtilityReport:
 policy=policy or G1CampaignPolicy()
 xs=[dict(x) for x in rows if str(x.get("organ_id") or "")==str(organ_id) and str(x.get("evidence_class") or "")=="PROSPECTIVE"]
 ds=[float(x.get("delta_bps") if x.get("delta_bps") is not None else float(x.get("full_net_bps") or 0)-float(x.get("ablated_net_bps") or 0)) for x in xs]
 stressed=[_stressed_delta(x,policy.extra_cost_stress_bps) for x in xs]
 lo,hi=_ci(ds,policy.confidence_z);m=mean(ds) if ds else 0.0;sm=mean(stressed) if stressed else 0.0
 worlds=len({str(x.get("world_state_hash") or "") for x in xs if x.get("world_state_hash")})
 dd=_drawdown(ds)
 reasons=[]
 if len(xs)<policy.min_pairs:reasons.append("minimum_pairs_not_met")
 if worlds<policy.min_distinct_worlds:reasons.append("minimum_distinct_worlds_not_met")
 if m<=policy.min_mean_delta_bps:reasons.append("mean_delta_not_positive")
 if lo<=0:reasons.append("confidence_lower_bound_not_positive")
 if sm<=0:reasons.append("cost_stress_not_survived")
 if dd>policy.max_delta_drawdown_bps:reasons.append("delta_drawdown_above_limit")
 cls="PROSPECTIVE_UTILITY_CANDIDATE" if not reasons else (
  "INSUFFICIENT_SAMPLE" if "minimum_pairs_not_met" in reasons or "minimum_distinct_worlds_not_met" in reasons
  else "STRESS_FRAGILE" if "cost_stress_not_survived" in reasons
  else "UNCERTAIN_OR_NONPOSITIVE")
 body={"organ_id":organ_id,"paired_n":len(xs),"worlds":worlds,"mean":m,"ci":[lo,hi],"stress":sm,
  "drawdown":dd,"classification":cls,"reasons":reasons,"policy":policy.to_dict()}
 return G1OrganUtilityReport(str(organ_id),len(xs),worlds,m,_median(ds),lo,hi,sm,
  sum(x>0 for x in ds),sum(x<0 for x in ds),sum(x==0 for x in ds),
  sum(bool(x.get("full_acted")) for x in xs),sum(bool(x.get("ablated_acted")) for x in xs),
  sum(bool(x.get("full_acted")) and not bool(x.get("ablated_acted")) for x in xs),
  sum(bool(x.get("ablated_acted")) and not bool(x.get("full_acted")) for x in xs),
  sum(not bool(x.get("full_acted")) and not bool(x.get("ablated_acted")) for x in xs),
  dd,cls,tuple(reasons),policy.to_dict(),_hash(body),AUTHORITY,False,False)

def evaluate_store(data_store:Any,*,policy:G1CampaignPolicy|None=None,
 campaign_id:str|None=None,target_id:str|None=None)->tuple[G1OrganUtilityReport,...]:
 rows=load_prospective_outcomes(data_store,campaign_id=campaign_id,target_id=target_id)
 organs=sorted({str(x.get("organ_id") or "") for x in rows if x.get("organ_id")})
 return tuple(evaluate_organ_utility(rows,organ_id=o,policy=policy) for o in organs)


def evaluate_store_stratified(data_store:Any,*,policy:G1CampaignPolicy|None=None,
 campaign_id:str|None=None,target_id:str|None=None)->dict[str,tuple[G1OrganUtilityReport,...]]:
 rows=load_prospective_outcomes(data_store,campaign_id=campaign_id,target_id=target_id)
 result={}
 for key_fn,label in (
  (lambda x:str(x.get("model_id") or "unknown"),"by_model"),
  (lambda x:str(int(x.get("horizon_seconds") or 0)),"by_horizon"),
 ):
  groups={}
  for row in rows:groups.setdefault(key_fn(row),[]).append(row)
  reports=[]
  for group,group_rows in sorted(groups.items()):
   for organ in sorted({str(x.get("organ_id") or "") for x in group_rows if x.get("organ_id")}):
    r=evaluate_organ_utility(group_rows,organ_id=organ,policy=policy)
    d=r.to_dict();d["stratum"]=group;reports.append(d)
  result[label]=tuple(reports)
 return result
