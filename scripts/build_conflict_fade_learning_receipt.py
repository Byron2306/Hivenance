#!/usr/bin/env python3
"""Build a machine-readable learning receipt from HiveNance research artifacts.

This is memory, not authority. It preserves observations, falsified explanations,
limitations, and next falsification steps without promoting a strategy.
"""
from __future__ import annotations
import argparse,hashlib,json,time
from pathlib import Path
def digest(p):
 b=Path(p).read_bytes();return hashlib.sha256(b).hexdigest()
def main():
 p=argparse.ArgumentParser()
 p.add_argument("--match-sensitivity",default="data/multivariate_state_match_sensitivity.json")
 p.add_argument("--match",default="data/multivariate_state_match.json")
 p.add_argument("--participation",default="data/temporal_participation_fold_decomposition.json")
 p.add_argument("--path",default="data/path_geometry_regime_autopsy.json")
 p.add_argument("--cross-market",default="data/cross_market_propagation_autopsy.json")
 p.add_argument("--output",default="data/learning_receipt_conflict_fade.json");a=p.parse_args()
 sens=json.loads(Path(a.match_sensitivity).read_text());match=json.loads(Path(a.match).read_text())
 sources=[a.match_sensitivity,a.match,a.participation,a.path,a.cross_market]
 rows=sens["results"]
 receipt={
  "schema":"hivenance_learning_receipt_v1",
  "learning_id":"conflict_fade_world_state_conditionality_2026_09_19",
  "created_at_ms":int(time.time()*1000),
  "hypothesis":{"name":"1h_24h_conflict_fade","claim":"Historical behavior of the frozen 1h-vs-24h conflict fade appears conditional on observable world state rather than calendar time alone."},
  "observations":{
   "raw_calendar_gap_bps":24.901,
   "state_match_caliper_3":{"matched_pairs":match["matched_pairs"],"coverage_early":match["coverage_early"],"paired_gap_bps":match["paired_gap_bps"]},
   "sensitivity":[{"caliper":r["caliper"],"pairs":r["matched_pairs"],"coverage":r["coverage_early"],"gap_bps":r["paired_gap_bps"]} for r in rows]
  },
  "interpretation":{
   "supported":"At moderate common-support calipers, matching on observed pre-event market state substantially reduces the early/late calendar gap.",
   "not_supported":"The current evidence does not establish a durable profitable edge, a causal state variable, a production threshold, or prospective usefulness.",
   "strict_match_warning":"At calipers 1.5 and 2.0 coverage collapses, so their large negative gaps are not stable population estimates.",
   "common_support_warning":"Even caliper 3.0 covers only 41.4% of early events and retains imperfect balance, especially |24h| displacement."
  },
  "falsified_or_weakened_explanations":[
   "simple UTC/participation composition explains the regime split",
   "local path geometry alone explains the regime split",
   "simple cross-market breadth/leadership alone explains the regime split",
   "a single asset explains the transition"
  ],
  "status":"HISTORICAL_STATE_CONDITIONAL_CANDIDATE",
  "authority":"HISTORICAL_DISCOVERY_ONLY",
  "next_falsification":[
   "independent flow evidence root",
   "independent liquidity evidence root",
   "prospectively freeze state representation before evaluation",
   "settle selected and rejected candidates plus no-trade/random controls"
  ],
  "source_artifacts":[{"path":x,"sha256":digest(x)} for x in sources],
  "execution_eligible":False,"promotion_eligible":False
 }
 Path(a.output).write_text(json.dumps(receipt,indent=2))
 print("===== HIVENANCE LEARNING RECEIPT =====")
 print("status",receipt["status"]);print("authority",receipt["authority"])
 print("sensitivity",receipt["observations"]["sensitivity"])
 print("output",a.output);print("MEMORY ONLY | EXECUTION: FALSE | PROMOTION: FALSE")
if __name__=="__main__":main()
