from strategies.relative_value_lab.g0_forecast_challenge import challenge_forecast
from strategies.volatility_breakout.models import FeatureVector,Forecast

def fv(ctx):
 return FeatureVector("BTC/USD",10,100,None,None,1.2,0.5,None,None,.1,2,1000000,100000000,.01,0,1,1,
  values={"synthesis_context":ctx},complete=True,return_zscore=2,trend_slope=.001,momentum_consistency=.8,atr_pct=.01)
def fc():
 return Forecast("BTC/USD",10,60,direction="UP",probability_positive_net=.6,expected_move_bps=20,
  expected_cost_bps=5,expected_net_bps=15,abstain=False,model_id="m",hypothesis="breakout_continuation")

def test_negative_shadow_learning_can_veto_but_not_create_alpha():
 ctx={"families":("LEARNING",),"family_payloads":{"LEARNING":({
  "comparisons":{"candidate_minus_no_trade_bps":-3.0}},)}}
 x=challenge_forecast(fc(),fv(ctx),organ_scope="learning_memory")
 assert x.abstain and x.expected_net_bps is None
 assert "g0_learning_prior_no_trade_superior" in x.reasons

def test_positive_learning_does_not_boost_forecast():
 original=fc()
 ctx={"families":("LEARNING",),"family_payloads":{"LEARNING":({
  "comparisons":{"candidate_minus_no_trade_bps":8.0}},)}}
 assert challenge_forecast(original,fv(ctx),organ_scope="learning_memory")==original

def test_same_hour_comparison_can_only_veto_weak_participation():
 ctx={"families":("COMPARISON",),"family_payloads":{"COMPARISON":({
  "matched_n":8,"metrics":{"volume_zscore":{"delta":-0.7}}},)}}
 x=challenge_forecast(fc(),fv(ctx),organ_scope="comparison_engine")
 assert x.abstain
 assert "g0_comparison_participation_below_same_hour_baseline" in x.reasons
