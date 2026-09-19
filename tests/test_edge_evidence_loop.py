from strategies.relative_value_lab.edge_evidence_loop import EdgeEvidenceObservation,observe_into_graph
from strategies.relative_value_lab.learning_attention import ResearchAttentionObligation
from strategies.relative_value_lab.learning_attention_router import LearningAttentionRouter
from strategies.relative_value_lab.world_graph import WorldGraph
from strategies.relative_value_lab.world_score import CanonicalWorldScore,ScoreObservation

def _g():
 o=ScoreObservation(observation_id="o",source_id="kraken",source_class="public_market",scope="BTC/USD",observed_at_ms=1,received_at_ms=2,evidence_root="sha256:"+"a"*64,payload={"price":1})
 return WorldGraph(CanonicalWorldScore.assemble(observations=[o],assembled_at_ms=3,freshness_window_ms=100))

def test_awakened_flow_enters_same_queen_world_with_real_root():
 g=_g();r=LearningAttentionRouter().route(ResearchAttentionObligation("OBSERVE","flow root","falsify",("h1",)))
 n=observe_into_graph(g,r,EdgeEvidenceObservation("kraken-trades","sha256:"+"b"*64,{"taker_buy_volume":70,"taker_sell_volume":30,"previous_imbalance":.6}),timestamp_ms=4,pair_id="BTC/USD")
 v=g.queen_view(created_at_ms=5,expected_families=("FLOW",))
 assert n.family=="FLOW" and n.evidence_roots==("sha256:"+"b"*64,)
 assert "FLOW" in v.families and v.independent_evidence_root_count==1

def test_awakened_liquidity_enters_same_queen_world_with_distinct_root():
 g=_g();r=LearningAttentionRouter().route(ResearchAttentionObligation("OBSERVE","liquidity root","falsify",("h1",)))
 n=observe_into_graph(g,r,EdgeEvidenceObservation("kraken-book","sha256:"+"c"*64,{"bid_depth":120,"ask_depth":100,"spread_bps":5,"previous_bid_depth":90,"previous_ask_depth":80}),timestamp_ms=4,pair_id="BTC/USD")
 assert n.family=="LIQUIDITY" and n.evidence_roots==("sha256:"+"c"*64,)
