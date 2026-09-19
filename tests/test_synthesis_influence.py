import pytest
from strategies.relative_value_lab.synthesis_runtime import SynthesisRuntime
from strategies.relative_value_lab.synthesis_influence import measure_influence
from strategies.relative_value_lab.world_score import ScoreObservation,CanonicalWorldScore
from strategies.relative_value_lab.edge_ecology import EdgeEcology

def _f(root="a"):
 o=ScoreObservation("o","kraken","public_market","BTC/USD",10,10,"sha256:"+root*64,{"price":100})
 return CanonicalWorldScore.assemble(observations=[o],assembled_at_ms=10,freshness_window_ms=100)

def test_edge_is_influential_only_by_same_world_counterfactual():
 f=_f();snap=EdgeEcology().snapshot(timestamp_ms=10,pair_id="BTC/USD",voices=(
  EdgeEcology.flow_voice(taker_buy_volume=60,taker_sell_volume=40),
  EdgeEcology.liquidity_voice(bid_depth=60,ask_depth=40,spread_bps=2),))
 roots={"FLOW":("sha256:"+"b"*64,),"LIQUIDITY":("sha256:"+"c"*64,)}
 rt=SynthesisRuntime();full=rt.run(frame=f,now_ms=10,edge_snapshot=snap,edge_roots=roots)
 blind=rt.run(frame=f,now_ms=10,edge_snapshot=snap,edge_roots=roots,disabled_organs=("edge_ecology",))
 r=measure_influence(organ_id="edge_ecology",full=full,ablated=blind)
 assert r.cognition_changed
 assert set(r.changed_families)=={"FLOW","LIQUIDITY"}
 assert not r.execution_eligible and not r.promotion_eligible

def test_influence_refuses_different_observed_worlds():
 a=SynthesisRuntime().run(frame=_f("a"),now_ms=10)
 b=SynthesisRuntime().run(frame=_f("b"),now_ms=10)
 with pytest.raises(ValueError,match="identical_world"):
  measure_influence(organ_id="x",full=a,ablated=b)
