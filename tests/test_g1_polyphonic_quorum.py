from types import SimpleNamespace
from strategies.relative_value_lab.g1_polyphonic_bridge import quorum_for_forecast,apply_quorum_gate
from strategies.volatility_breakout.models import FeatureVector,Forecast

def feature(ctx):
 return FeatureVector("BTC/USD",10000,100,None,None,1.2,0.5,None,None,.1,2,1000000,100000000,.01,0,1,1,
  values={"synthesis_context":ctx},complete=True,return_zscore=2,trend_slope=.001,momentum_consistency=.8,atr_pct=.01)

def forecast():
 return Forecast("BTC/USD",10000,60,direction="UP",probability_positive_net=.6,expected_move_bps=20,
  expected_cost_bps=5,expected_net_bps=15,abstain=False,model_id="m",hypothesis="breakout_continuation")

def node(i,family,root,payload):
 return SimpleNamespace(node_id=f"n{i}",organ_id=family.lower(),family=family,lineage_id=f"l{i}",
  evidence_roots=(root,),created_at_ms=10000,uncertainty=.2,payload=payload)

def cycle(nodes):
 return SimpleNamespace(cycle_id="c",world_state_id="w",world_state_hash="sha256:"+"f"*64,
  queen_view=SimpleNamespace(nodes=tuple(nodes)))

def test_same_root_families_do_not_fake_quorum_independence():
 root="sha256:"+"a"*64
 nodes=[node(1,"LIQUIDITY",root,{}),node(2,"HORIZON",root,{"alignment":"ALIGNED_UP"})]
 ctx={"families":("LIQUIDITY","HORIZON"),"family_payloads":{"LIQUIDITY":({},),"HORIZON":({"alignment":"ALIGNED_UP"},)}}
 q=quorum_for_forecast(cycle=cycle(nodes),forecast=forecast(),feature=feature(ctx))
 assert q.independent_root_count==1
 assert q.quorum_formed is False

def test_quorum_gate_can_only_abstain():
 root1="sha256:"+"a"*64;root2="sha256:"+"b"*64
 nodes=[node(1,"LIQUIDITY",root1,{}),node(2,"HORIZON",root2,{"alignment":"ALIGNED_UP"})]
 ctx={"families":("LIQUIDITY","HORIZON"),"family_payloads":{"LIQUIDITY":({},),"HORIZON":({"alignment":"ALIGNED_UP"},)}}
 q=quorum_for_forecast(cycle=cycle(nodes),forecast=forecast(),feature=feature(ctx))
 out=apply_quorum_gate(forecast(),q)
 if q.quorum_formed:
  assert out==forecast()
 else:
  assert out.abstain and out.direction=="ABSTAIN" and out.expected_net_bps is None
