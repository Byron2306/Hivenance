from strategies.relative_value_lab.g0_forecast_challenge import challenge_forecast
from strategies.volatility_breakout.models import FeatureVector,Forecast
def fv(families):
 return FeatureVector("BTC/USD",10,100,None,None,1.5,1,1,.5,.2,2,1000000,100000000,.01,0,1,1,
  values={"synthesis_context":{"cycle_id":"c","world_state_hash":"sha256:"+"a"*64,"families":families}},complete=True)
def fc():
 return Forecast("BTC/USD",10,60,direction="UP",probability_positive_net=.6,expected_move_bps=20,
  expected_cost_bps=5,expected_net_bps=15,abstain=False,model_id="m",hypothesis="breakout_continuation")
def test_missing_semantic_corroboration_can_only_abstain():
 x=challenge_forecast(fc(),fv(("FLOW",)))
 assert x.abstain and x.direction=="ABSTAIN" and x.expected_net_bps is None
 assert "g0_liquidity_not_corroborated" in x.reasons
def test_present_corroboration_leaves_existing_forecast_unchanged():
 x=fc();assert challenge_forecast(x,fv(("FLOW","LIQUIDITY")))==x
