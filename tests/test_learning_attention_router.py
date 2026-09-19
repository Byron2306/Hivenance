from strategies.relative_value_lab.learning_attention import ResearchAttentionObligation
from strategies.relative_value_lab.learning_attention_router import LearningAttentionRouter

def test_learning_obligations_wake_existing_flow_and_liquidity_organs():
 r=LearningAttentionRouter()
 f=r.route(ResearchAttentionObligation("OBSERVE","flow root","next falsification",("h1",)))
 l=r.route(ResearchAttentionObligation("OBSERVE","liquidity root","next falsification",("h1",)))
 assert (f.organ_id,f.family)==("edge_ecology","FLOW")
 assert (l.organ_id,l.family)==("edge_ecology","LIQUIDITY")
 fv=r.invoke_edge(f,taker_buy_volume=70,taker_sell_volume=30,previous_imbalance=.6)
 lv=r.invoke_edge(l,bid_depth=120,ask_depth=100,spread_bps=5,previous_bid_depth=90,previous_ask_depth=80)
 assert fv.family=="FLOW" and lv.family=="LIQUIDITY"
 assert not f.execution_eligible and not l.promotion_eligible

def test_supported_claim_routes_to_counterpoint():
 r=LearningAttentionRouter()
 q=r.route(ResearchAttentionObligation("CHALLENGE","state matters","attack historical claim",("h1",)))
 assert (q.organ_id,q.family)==("counterpoint","COUNTERPOINT")
