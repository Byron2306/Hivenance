#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,sqlite3,threading
from types import SimpleNamespace
from strategies.relative_value_lab.g1_utility_campaign import G1CampaignPolicy,evaluate_store

class Store:
 def __init__(self,path:str):
  self.conn=sqlite3.connect(path)
  self._lock=threading.RLock()

def main()->int:
 ap=argparse.ArgumentParser(description="Report strict prospective G1 organ utility from canonical G0 settlements.")
 ap.add_argument("--db",default="swarm_data.db")
 ap.add_argument("--min-pairs",type=int,default=30)
 ap.add_argument("--min-worlds",type=int,default=10)
 ap.add_argument("--cost-stress-bps",type=float,default=5.0)
 ap.add_argument("--confidence-z",type=float,default=1.96)
 ap.add_argument("--max-drawdown-bps",type=float,default=250.0)
 ap.add_argument("--json",action="store_true")
 args=ap.parse_args()
 store=Store(args.db)
 policy=G1CampaignPolicy(min_pairs=args.min_pairs,min_distinct_worlds=args.min_worlds,
  extra_cost_stress_bps=args.cost_stress_bps,confidence_z=args.confidence_z,
  max_delta_drawdown_bps=args.max_drawdown_bps)
 reports=evaluate_store(store,policy=policy)
 if args.json:
  print(json.dumps([x.to_dict() for x in reports],indent=2,sort_keys=True));return 0
 if not reports:
  print("G1: no settled prospective organ twins yet");return 0
 print("G1 PROSPECTIVE ORGAN UTILITY")
 for r in reports:
  print(f"{r.organ_id:28s} {r.classification:32s} n={r.paired_n:4d} worlds={r.distinct_worlds:4d} "
        f"mean={r.mean_delta_bps:+8.3f}bps CI=[{r.ci_lower_bps:+8.3f},{r.ci_upper_bps:+8.3f}] "
        f"stress={r.stressed_mean_delta_bps:+8.3f} dd={r.max_delta_drawdown_bps:8.3f}")
  if r.reasons:print("  reasons="+",".join(r.reasons))
 return 0

if __name__=="__main__":raise SystemExit(main())
