import json,sqlite3,threading
from strategies.relative_value_lab.g1_campaign_freeze import freeze_g1_campaign
from strategies.relative_value_lab.g1_utility_campaign import G1CampaignPolicy
from scripts.report_g1_campaign_status import Store

def test_status_store_uses_same_canonical_db_shape(tmp_path):
 path=str(tmp_path/"x.db")
 s=Store(path)
 s.conn.execute("""CREATE TABLE phase5_g0_shadow_twins(
 twin_freeze_id TEXT PRIMARY KEY,organ_id TEXT,opportunity_id TEXT,world_state_hash TEXT,
 frozen_at_ms INTEGER,target_ts REAL,status TEXT,authority TEXT,execution_eligible INTEGER,
 promotion_eligible INTEGER,payload_sha256 TEXT,payload TEXT)""")
 s.conn.execute("""CREATE TABLE phase5_g0_shadow_twin_settlements(
 twin_freeze_id TEXT PRIMARY KEY,settled_ts REAL,payload_sha256 TEXT,authority TEXT,
 execution_eligible INTEGER,promotion_eligible INTEGER,payload TEXT)""")
 freeze_g1_campaign(s,policy=G1CampaignPolicy(min_pairs=30,min_distinct_worlds=10),
  organs=("edge_ecology",),created_ts=1.0)
 s.conn.execute("INSERT INTO phase5_g0_shadow_twins VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
  ("t1","edge_ecology","o1","sha256:"+"a"*64,1,2.0,"FROZEN","x",0,0,"h","{}"))
 s.conn.commit()
 row=s.conn.execute("SELECT organ_id,status,COUNT(*) FROM phase5_g0_shadow_twins GROUP BY organ_id,status").fetchone()
 assert row==("edge_ecology","FROZEN",1)
