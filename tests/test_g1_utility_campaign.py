from strategies.relative_value_lab.g1_utility_campaign import G1CampaignPolicy,evaluate_organ_utility

def row(i,delta,full=True,blind=False):
 return {"organ_id":"edge_ecology","evidence_class":"PROSPECTIVE","opportunity_id":f"o{i}",
  "world_state_hash":"sha256:"+str(i).zfill(64),"full_net_bps":float(delta),
  "ablated_net_bps":0.0,"delta_bps":float(delta),"full_acted":full,"ablated_acted":blind}

def test_small_lucky_sample_cannot_graduate():
 r=evaluate_organ_utility([row(i,20) for i in range(5)],organ_id="edge_ecology",
  policy=G1CampaignPolicy(min_pairs=30,min_distinct_worlds=10))
 assert r.classification=="INSUFFICIENT_SAMPLE"
 assert "minimum_pairs_not_met" in r.reasons
 assert not r.execution_eligible and not r.promotion_eligible

def test_positive_confident_cost_stress_survivor_becomes_candidate_only():
 xs=[row(i,12+(i%3)) for i in range(40)]
 r=evaluate_organ_utility(xs,organ_id="edge_ecology",
  policy=G1CampaignPolicy(min_pairs=30,min_distinct_worlds=10,extra_cost_stress_bps=5))
 assert r.classification=="PROSPECTIVE_UTILITY_CANDIDATE"
 assert r.ci_lower_bps>0 and r.stressed_mean_delta_bps>0
 assert r.full_only_acted==40 and r.ablated_acted==0
 assert not r.execution_eligible and not r.promotion_eligible

def test_cost_fragile_signal_is_refused_despite_positive_raw_mean():
 xs=[row(i,3+(i%2)) for i in range(40)]
 r=evaluate_organ_utility(xs,organ_id="edge_ecology",
  policy=G1CampaignPolicy(min_pairs=30,min_distinct_worlds=10,extra_cost_stress_bps=5))
 assert r.mean_delta_bps>0 and r.stressed_mean_delta_bps<0
 assert r.classification=="STRESS_FRAGILE"
