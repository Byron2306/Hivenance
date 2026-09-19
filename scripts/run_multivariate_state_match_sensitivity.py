#!/usr/bin/env python3
"""Sensitivity prosecution for the multivariate early/late state match.

Runs the existing matcher over a fixed preregistered caliper ladder. This does
not optimize a caliper. It asks whether the near-zero calendar gap is robust as
matching becomes stricter, while tracking coverage and state balance.
"""
from __future__ import annotations
import argparse,json,subprocess,sys,tempfile
from pathlib import Path
CALIPERS=(1.5,2.0,2.5,3.0,3.5)
def main():
 p=argparse.ArgumentParser();p.add_argument("--database",default="data/hivenance_market_memory.db");p.add_argument("--output",default="data/multivariate_state_match_sensitivity.json");a=p.parse_args()
 rows=[]
 with tempfile.TemporaryDirectory() as td:
  for c in CALIPERS:
   out=Path(td)/f"m_{c}.json"
   cmd=[sys.executable,str(Path(__file__).with_name("run_multivariate_state_match.py")),"--database",a.database,"--output",str(out),"--caliper",str(c)]
   cp=subprocess.run(cmd,capture_output=True,text=True)
   if cp.returncode: raise RuntimeError(cp.stderr or cp.stdout)
   d=json.loads(out.read_text())
   rows.append({"caliper":c,"matched_pairs":d["matched_pairs"],"coverage_early":d["coverage_early"],
    "early_mean_bps":d["early_mean_bps"],"late_mean_bps":d["late_mean_bps"],"paired_gap_bps":d["paired_gap_bps"],
    "median_match_distance":d["median_match_distance"],"balance":d["balance"],"per_symbol":d["per_symbol"]})
 result={"schema":"hivenance_multivariate_state_match_sensitivity_v1","calipers":list(CALIPERS),"results":rows,
  "interpretation_rule":"Robust state explanation requires the calendar gap to remain small across stricter calipers without coverage collapsing and with improving balance.",
  "warning":"fixed sensitivity ladder, historical diagnosis only; no caliper is selected/promoted from these results",
  "execution_eligible":False,"promotion_eligible":False}
 Path(a.output).write_text(json.dumps(result,indent=2))
 print("===== MULTIVARIATE STATE-MATCH SENSITIVITY =====")
 for r in rows:
  print(f"caliper={r['caliper']:.1f} pairs={r['matched_pairs']:3d} coverage={r['coverage_early']:.3f} early={r['early_mean_bps']:+8.3f} late={r['late_mean_bps']:+8.3f} gap={r['paired_gap_bps']:+8.3f} dist={r['median_match_distance']:.3f}")
 print(f"output: {a.output}\nHISTORICAL SENSITIVITY ONLY | PRIVATE ORDERS: 0")
if __name__=="__main__":main()
