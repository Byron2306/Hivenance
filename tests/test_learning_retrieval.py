from strategies.relative_value_lab.learning_memory import add_learning_receipt
from strategies.relative_value_lab.learning_retrieval import learning_brief
from strategies.relative_value_lab.world_graph import WorldGraph
from strategies.relative_value_lab.world_score import CanonicalWorldScore,ScoreObservation

def test_queen_learning_brief_preserves_uncertainty_and_next_tests():
 o=ScoreObservation(observation_id="o",source_id="kraken",source_class="public_market",scope="BTC/USD",observed_at_ms=1,received_at_ms=2,evidence_root="sha256:"+"a"*64,payload={"price":1})
 g=WorldGraph(CanonicalWorldScore.assemble(observations=[o],assembled_at_ms=3,freshness_window_ms=100))
 r={"schema":"hivenance_learning_receipt_v1","learning_id":"h1","created_at_ms":4,"authority":"HISTORICAL_DISCOVERY_ONLY",
 "source_artifacts":[{"sha256":"b"*64}],"execution_eligible":False,"promotion_eligible":False,"status":"HISTORICAL_STATE_CONDITIONAL_CANDIDATE",
 "interpretation":{"supported":"state matters","common_support_warning":"coverage incomplete"},
 "falsified_or_weakened_explanations":["calendar alone"],"next_falsification":["flow root","liquidity root"]}
 add_learning_receipt(g,r);b=learning_brief(g.queen_view(created_at_ms=5,expected_families=("LEARNING",)))
 assert b.learning_ids==("h1",);assert b.supported_claims==("state matters",)
 assert "common_support_warning: coverage incomplete" in b.limitations
 assert b.next_falsifications==("flow root","liquidity root")
 assert b.execution_eligible is False and b.promotion_eligible is False
