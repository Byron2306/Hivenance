#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,sqlite3,threading,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
 sys.path.insert(0,str(ROOT))
from collections import defaultdict
from strategies.relative_value_lab.g1_campaign_freeze import get_latest_g1_campaign_freeze,policy_from_freeze
from strategies.relative_value_lab.g1_utility_campaign import evaluate_store,load_prospective_outcomes
from main import load_config,apply_phase0_safety_policy

class Store:
 def __init__(self,path:str):
  self.conn=sqlite3.connect(path);self._lock=threading.RLock()

def main()->int:
 ap=argparse.ArgumentParser(description="Show frozen G1 campaign progress and organ utility status.")
 ap.add_argument("--db",default=None,help="SQLite path; defaults to configured cfg.db_path")
 ap.add_argument("--json",action="store_true")
 args=ap.parse_args()
 cfg=apply_phase0_safety_policy(load_config())
 db_path=str(args.db or getattr(cfg,"db_path","swarm_data.db") or "swarm_data.db")
 print(f"[G1 STATUS] db={db_path}")
 s=Store(db_path)
 frozen=get_latest_g1_campaign_freeze(s)
 if frozen is None:
  print("G1: campaign not frozen yet; run one Phase-5 shadow cycle first.")
  return 0
 policy=policy_from_freeze(frozen)
 organs=tuple(frozen.get("organs") or ())
 counts=defaultdict(lambda:{"frozen":0,"settled":0,"pending":0})
 campaign_id=str(frozen.get("campaign_id") or "") if frozen.get("research_target_id") else None
 target_id=str(frozen.get("research_target_id") or "") or None
 try:
  with s._lock:
   rows=s.conn.execute("SELECT organ_id,status,payload FROM phase5_g0_shadow_twins").fetchall()
  for organ,status,raw in rows:
   try:p=json.loads(raw or "{}")
   except Exception:continue
   if campaign_id and str(p.get("research_campaign_id") or "")!=campaign_id:continue
   if target_id and str(p.get("research_target_id") or "")!=target_id:continue
   counts[str(organ)]["frozen"]+=1
   if str(status)=="SETTLED":counts[str(organ)]["settled"]+=1
   else:counts[str(organ)]["pending"]+=1
 except Exception:
  pass
 reports={r.organ_id:r for r in evaluate_store(s,policy=policy,campaign_id=campaign_id,target_id=target_id)}
 payload={"campaign_id":frozen.get("campaign_id"),"created_ts":frozen.get("created_ts"),
  "policy":policy.to_dict(),"organs":[],"execution_eligible":False,"promotion_eligible":False}
 for organ in organs:
  r=reports.get(organ)
  row={"organ_id":organ,**counts[organ]}
  if r:
   row.update({"paired_n":r.paired_n,"distinct_worlds":r.distinct_worlds,
    "mean_delta_bps":r.mean_delta_bps,"ci_lower_bps":r.ci_lower_bps,"ci_upper_bps":r.ci_upper_bps,
    "stressed_mean_delta_bps":r.stressed_mean_delta_bps,"classification":r.classification,
    "reasons":r.reasons,"pairs_remaining":max(0,policy.min_pairs-r.paired_n),
    "worlds_remaining":max(0,policy.min_distinct_worlds-r.distinct_worlds)})
  else:
   row.update({"paired_n":0,"distinct_worlds":0,"classification":"INSUFFICIENT_SAMPLE",
    "reasons":("no_settled_prospective_twins",),"pairs_remaining":policy.min_pairs,
    "worlds_remaining":policy.min_distinct_worlds})
  payload["organs"].append(row)
 if args.json:
  print(json.dumps(payload,indent=2,sort_keys=True));return 0
 print(f"G1 CAMPAIGN {payload['campaign_id']}")
 print("authority=SYNTHESIS_G1_PROSPECTIVE_RESEARCH_ONLY execution=false promotion=false")
 print(f"policy: min_pairs={policy.min_pairs} min_worlds={policy.min_distinct_worlds} "
       f"z={policy.confidence_z} cost_stress={policy.extra_cost_stress_bps:g}bps "
       f"max_dd={policy.max_delta_drawdown_bps:g}bps")
 for row in payload["organs"]:
  print(f"{row['organ_id']:30s} {row['classification']:32s} "
        f"born={row['frozen']:4d} pending={row['pending']:4d} settled={row['settled']:4d} "
        f"pairs_left={row['pairs_remaining']:3d} worlds_left={row['worlds_remaining']:3d}")
  if row.get("paired_n"):
   print(f"  mean={row['mean_delta_bps']:+.3f}bps "
         f"CI=[{row['ci_lower_bps']:+.3f},{row['ci_upper_bps']:+.3f}] "
         f"stress={row['stressed_mean_delta_bps']:+.3f}bps")
   if row.get("reasons"):print("  reasons="+",".join(row["reasons"]))
 return 0

if __name__=="__main__":raise SystemExit(main())
