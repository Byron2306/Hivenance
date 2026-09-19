from strategies.relative_value_lab.learning_memory import add_learning_receipt
from strategies.relative_value_lab.world_graph import WorldGraph
from strategies.relative_value_lab.world_score import CanonicalWorldScore, ScoreObservation

def _graph():
 obs=ScoreObservation(observation_id="obs-learning",source_id="kraken",source_class="public_market",scope="BTC/USD",observed_at_ms=1000,received_at_ms=1001,evidence_root="sha256:"+"a"*64,payload={"price":100.0})
 frame=CanonicalWorldScore.assemble(observations=[obs],assembled_at_ms=1002,freshness_window_ms=15000)
 return WorldGraph(frame)

def test_learning_receipt_is_interpreted_and_non_authoritative():
 graph=_graph()
 r={"schema":"hivenance_learning_receipt_v1","learning_id":"x","created_at_ms":1003,
 "authority":"HISTORICAL_DISCOVERY_ONLY","source_artifacts":[{"sha256":"b"*64}],
 "execution_eligible":False,"promotion_eligible":False,"status":"HISTORICAL_STATE_CONDITIONAL_CANDIDATE"}
 n=add_learning_receipt(graph,r)
 assert n.family=="LEARNING"
 assert n.namespace=="interpreted_research"
 assert n.evidence_roots==("sha256:"+"b"*64,)
 assert not n.execution_eligible and not n.promotion_eligible
 v=graph.queen_view(created_at_ms=1004,expected_families=("LEARNING",))
 assert any(x.node_id==n.node_id for x in v.nodes)
 assert v.missing_expected_families==()
