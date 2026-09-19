from strategies.relative_value_lab.learning_attention import ResearchAttentionObligation
from strategies.relative_value_lab.learning_attention_router import LearningAttentionRouter

def _o(target,action="CHALLENGE"):
 return ResearchAttentionObligation(action,target,"adversarial recurrence",("shadow:x",))

def test_adversarial_requests_route_to_responsible_organs():
 r=LearningAttentionRouter()
 cases={
  "settle shadow control TIME_SHIFT_PLACEBO":("temporal_observer","TEMPORAL"),
  "challenge same_root lineage":("lineage_guard","LINEAGE"),
  "obtain independent lineage":("lineage_guard","LINEAGE"),
  "stress observed cost assumptions":("edge_ecology","LIQUIDITY"),
  "refresh stale evidence":("public_observer","REFRESH"),
 }
 for target,expected in cases.items():
  q=r.route(_o(target))
  assert (q.organ_id,q.family)==expected
  assert not q.execution_eligible and not q.promotion_eligible

def test_unknown_challenge_still_falls_back_to_hypothesis_swarm():
 q=LearningAttentionRouter().route(_o("challenge unexplained mechanism"))
 assert (q.organ_id,q.family)==("hypothesis_swarm","HYPOTHESIS")
