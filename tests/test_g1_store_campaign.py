import json,sqlite3,threading
from strategies.relative_value_lab.g1_utility_campaign import G1CampaignPolicy,evaluate_store,load_prospective_outcomes

class Store:
 def __init__(self):
  self.conn=sqlite3.connect(":memory:");self._lock=threading.RLock()
  self.conn.execute("""CREATE TABLE phase5_g0_shadow_twin_settlements(
   twin_freeze_id TEXT PRIMARY KEY,settled_ts REAL NOT NULL,payload_sha256 TEXT,
   authority TEXT,execution_eligible INTEGER,promotion_eligible INTEGER,payload TEXT NOT NULL)""")

def test_store_campaign_reads_only_prospective_paired_outcomes():
 s=Store()
 for i in range(35):
  pair={"organ_id":"edge_ecology","evidence_class":"PROSPECTIVE","opportunity_id":f"o{i}",
   "world_state_hash":"sha256:"+str(i).zfill(64),"full_net_bps":12.0,"ablated_net_bps":0.0,
   "delta_bps":12.0,"full_acted":True,"ablated_acted":False,
   "execution_eligible":False,"promotion_eligible":False}
  body={"paired_outcome":pair,"execution_eligible":False,"promotion_eligible":False}
  s.conn.execute("INSERT INTO phase5_g0_shadow_twin_settlements VALUES(?,?,?,?,?,?,?)",
   (f"t{i}",float(i),"h","SYNTHESIS_G0_PROSPECTIVE_SHADOW_ONLY",0,0,json.dumps(body)))
 s.conn.commit()
 rows=load_prospective_outcomes(s)
 assert len(rows)==35
 reports=evaluate_store(s,policy=G1CampaignPolicy(min_pairs=30,min_distinct_worlds=10,extra_cost_stress_bps=5))
 assert len(reports)==1
 r=reports[0]
 assert r.organ_id=="edge_ecology" and r.classification=="PROSPECTIVE_UTILITY_CANDIDATE"
 assert r.full_only_acted==35 and r.ablated_acted==0
 assert not r.execution_eligible and not r.promotion_eligible
