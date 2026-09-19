from types import SimpleNamespace
from strategies.relative_value_lab.g1_conducting_queen_bridge import queen_receipt_for_forecast,apply_queen_gate
from strategies.relative_value_lab.world_score import ScoreObservation,CanonicalWorldScore
from strategies.volatility_breakout.models import FeatureVector,Forecast

def frame():
 o=ScoreObservation("o","kraken","public_market","BTC/USD",10,10,"sha256:"+"a"*64,{"price":100})
 return CanonicalWorldScore.assemble(observations=(o,),assembled_at_ms=10,freshness_window_ms=1000)
def feature():
 return FeatureVector("BTC/USD",10,100,None,None,1.2,.5,None,None,.1,2,1000000,100000000,.01,0,1,1,
  values={"synthesis_context":{"families":(),"family_payloads":{}}},complete=True)
def forecast():
 return Forecast("BTC/USD",10,60,direction="UP",probability_positive_net=.6,expected_move_bps=20,
  expected_cost_bps=5,expected_net_bps=15,abstain=False,model_id="m",hypothesis="breakout_continuation")
def cycle(f):
 return SimpleNamespace(cycle_id="c",world_state_id=f.world_state_id,world_state_hash=f.world_state_hash,
  queen_view=SimpleNamespace(nodes=()))

def test_real_conducting_queen_can_run_on_lawful_live_minimum():
 f=frame()
 r=queen_receipt_for_forecast(frame=f,cycle=cycle(f),forecast=forecast(),feature=feature(),now_ms=10)
 assert r.execution_eligible is False and r.promotion_eligible is False
 assert r.world_state_tension>=0
 assert all(t.execution_eligible is False for t in r.notation_tokens)

def test_queen_gate_is_veto_only_for_existing_caution_notation():
 q=SimpleNamespace(receipt_id="q",notation_tokens=(SimpleNamespace(notation="CHALLENGE_CADENCE"),),
  conducting_gestures=("HOLD_DISSONANCE_OPEN",),reasons=("dissonance_remains_musically_relevant",))
 out=apply_queen_gate(forecast(),q)
 assert out.abstain and out.direction=="ABSTAIN" and out.expected_net_bps is None
 assert "g1_conducting_queen_caution" in out.reasons

def test_non_cautionary_queen_notation_cannot_boost_forecast():
 x=forecast()
 q=SimpleNamespace(receipt_id="q",notation_tokens=(SimpleNamespace(notation="LISTEN"),),
  conducting_gestures=("LISTEN_CONTINUOUSLY",),reasons=())
 assert apply_queen_gate(x,q)==x
