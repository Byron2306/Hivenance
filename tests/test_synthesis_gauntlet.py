from strategies.relative_value_lab.synthesis_gauntlet import SynthesisGauntlet
from strategies.relative_value_lab.world_score import ScoreObservation,CanonicalWorldScore
from strategies.relative_value_lab.edge_ecology import EdgeEcology

def _frame():
 o=ScoreObservation("o","kraken","public_market","BTC/USD",10,10,"sha256:"+"a"*64,{"price":100})
 return CanonicalWorldScore.assemble(observations=[o],assembled_at_ms=10,freshness_window_ms=100)

def test_g0_classifies_invoked_influential_and_available_without_economic_claims():
 f=_frame();snap=EdgeEcology().snapshot(timestamp_ms=10,pair_id="BTC/USD",voices=(
  EdgeEcology.flow_voice(taker_buy_volume=60,taker_sell_volume=40),
  EdgeEcology.liquidity_voice(bid_depth=60,ask_depth=40,spread_bps=2),))
 r=SynthesisGauntlet().run(frame=f,now_ms=10,edge_snapshot=snap,
  edge_roots={"FLOW":("sha256:"+"b"*64,),"LIQUIDITY":("sha256:"+"c"*64,)})
 v={x.organ_id:x for x in r.verdicts}
 assert v["edge_ecology"].classification=="INFLUENTIAL"
 assert v["horizon_context"].classification=="AVAILABLE"
 assert v["learning_memory"].classification=="AVAILABLE"
 assert r.world_state_hash==f.world_state_hash
 assert not r.execution_eligible and not r.promotion_eligible
 assert all(x.classification not in {"USEFUL","PROFITABLE"} for x in r.verdicts)

def test_g0_refuses_external_ablation_mask():
 import pytest
 with pytest.raises(ValueError,match="owns_ablation_mask"):
  SynthesisGauntlet().run(frame=_frame(),now_ms=10,disabled_organs=("edge_ecology",))
