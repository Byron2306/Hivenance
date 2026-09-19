from strategies.relative_value_lab.learning_memory import add_learning_receipt
from strategies.relative_value_lab.learning_retrieval import learning_brief
from strategies.relative_value_lab.world_graph import WorldGraph
from strategies.relative_value_lab.world_score import CanonicalWorldScore,ScoreObservation

def test_prospective_shadow_learning_reaches_queen_without_authority():
 o=ScoreObservation(observation_id="o",source_id="kraken",source_class="public_market",scope="BTC/USD",observed_at_ms=10,received_at_ms=10,evidence_root="sha256:"+"a"*64,payload={"price":100})
 g=WorldGraph(CanonicalWorldScore.assemble(observations=[o],assembled_at_ms=10,freshness_window_ms=100))
 r={"schema":"hivenance_adversarial_shadow_learning_v1","learning_id":"shadow:x","status":"PROSPECTIVE_SHADOW_EVIDENCE","authority":"PROSPECTIVE_SHADOW_RESEARCH_ONLY","candidate_net_return_bps":5,"comparisons":{"candidate_minus_no_trade_bps":5,"candidate_minus_sign_inverted_bps":10},"unsettled_controls":["TIME_SHIFT_PLACEBO"],"execution_eligible":False,"promotion_eligible":False,"interpretation":"Comparative shadow evidence only; not live execution authority."}
 n=add_learning_receipt(g,r,created_at_ms=10)
 assert n.family=="LEARNING" and n.payload["authority"]=="PROSPECTIVE_SHADOW_RESEARCH_ONLY"
 b=learning_brief(g.queen_view(created_at_ms=11))
 assert "shadow:x" in b.learning_ids
 assert not n.execution_eligible and not n.promotion_eligible
