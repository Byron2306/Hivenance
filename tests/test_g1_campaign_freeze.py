import sqlite3,threading,pytest
from strategies.relative_value_lab.g1_campaign_freeze import freeze_g1_campaign,get_g1_campaign_freeze,policy_from_freeze
from strategies.relative_value_lab.g1_utility_campaign import G1CampaignPolicy

class Store:
 def __init__(self):self.conn=sqlite3.connect(":memory:");self._lock=threading.RLock()

def test_g1_campaign_policy_is_content_frozen_before_outcomes():
 s=Store();p=G1CampaignPolicy(min_pairs=30,min_distinct_worlds=10,extra_cost_stress_bps=5)
 a=freeze_g1_campaign(s,policy=p,organs=("edge_ecology","conducting_queen"),created_ts=1.0)
 b=freeze_g1_campaign(s,policy=p,organs=("conducting_queen","edge_ecology"),created_ts=2.0)
 assert a["campaign_id"]==b["campaign_id"] and b["created"] is False
 frozen=get_g1_campaign_freeze(s)
 assert policy_from_freeze(frozen)==p
 assert frozen["execution_eligible"] is False and frozen["promotion_eligible"] is False

def test_silent_threshold_change_is_refused():
 s=Store()
 freeze_g1_campaign(s,policy=G1CampaignPolicy(min_pairs=30),organs=("edge_ecology",),created_ts=1.0)
 with pytest.raises(ValueError,match="already_frozen"):
  freeze_g1_campaign(s,policy=G1CampaignPolicy(min_pairs=5),organs=("edge_ecology",),created_ts=2.0)
