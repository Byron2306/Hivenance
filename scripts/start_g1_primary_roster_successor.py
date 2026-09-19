#!/usr/bin/env python3
from __future__ import annotations
import json,os,sqlite3,sys,threading
from pathlib import Path

# Same Termux/Python 3.14 native-extension safeguard as the one-shot runner.
if os.environ.get("PREFIX") and not os.environ.get("HIVENANCE_G1_PRELOAD_DONE"):
    libpython=Path(os.environ["PREFIX"])/"lib"/f"libpython{sys.version_info.major}.{sys.version_info.minor}.so"
    if libpython.exists():
        env=dict(os.environ)
        existing=env.get("LD_PRELOAD","").strip()
        env["LD_PRELOAD"]=str(libpython) if not existing else str(libpython)+":"+existing
        env["HIVENANCE_G1_PRELOAD_DONE"]="1"
        os.execve(sys.executable,[sys.executable,*sys.argv],env)

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from dataclasses import replace
from main import load_config,apply_phase0_safety_policy
from strategies.relative_value_lab.g1_campaign_freeze import (
    get_latest_g1_campaign_freeze,freeze_g1_campaign_successor,policy_from_freeze,
)
from strategies.relative_value_lab.g1_research_target import (
    get_latest_g1_research_target,freeze_g1_research_target_successor,PRIMARY_MODEL_IDS,
)

class Store:
    def __init__(self,path:str):
        self.conn=sqlite3.connect(path)
        self._lock=threading.RLock()

def main()->int:
    cfg=apply_phase0_safety_policy(load_config())
    store=Store(str(getattr(cfg,"db_path","swarm_data.db") or "swarm_data.db"))
    predecessor=get_latest_g1_campaign_freeze(store)
    if predecessor is None:
        raise RuntimeError("g1_predecessor_campaign_missing")
    previous_target=get_latest_g1_research_target(store)
    target=freeze_g1_research_target_successor(
        store,cfg,model_ids=PRIMARY_MODEL_IDS,order_policy="market",
        predecessor_target_id=(previous_target or {}).get("target_id"),
    )
    # Seven simultaneous organ hypotheses: predeclare Bonferroni family-wise
    # alpha=.05 via the equivalent two-sided z ~= 2.690 before future outcomes.
    old_policy=policy_from_freeze(predecessor)
    successor_policy=replace(old_policy,confidence_z=2.690)
    successor=freeze_g1_campaign_successor(
        store,policy=successor_policy,organs=tuple(predecessor.get("organs") or ()),
        research_target_id=str(target["target_id"]),
        predecessor_campaign_id=str(predecessor["campaign_id"]),
    )
    print(json.dumps({
        "predecessor_campaign_id":predecessor["campaign_id"],
        "predecessor_disposition":"COVERAGE_NULL_RAW_PHOENIX_ABSTAIN",
        "successor_campaign":successor,
        "research_target":target,
        "model_ids":list(PRIMARY_MODEL_IDS),
        "multiplicity":{
            "method":"BONFERRONI",
            "family_size":7,
            "family_alpha":0.05,
            "two_sided_confidence_z":2.690,
        },
        "execution_eligible":False,
        "promotion_eligible":False,
    },indent=2,sort_keys=True,default=str))
    return 0

if __name__=="__main__":raise SystemExit(main())
