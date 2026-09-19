from dataclasses import replace
from types import SimpleNamespace

from strategies.relative_value_lab.g0_forecast_challenge import challenge_forecast
from strategies.volatility_breakout.models import Forecast,FeatureVector

def feature(*,families=(),family_payloads=None):
 return FeatureVector(
  symbol="BTC/USD",timestamp_ms=1_000_000,price=100.0,
  realized_volatility_fast=.01,realized_volatility_baseline=.01,volatility_expansion=1.0,
  volume_zscore=0.0,trade_count_zscore=None,order_flow_imbalance=None,book_imbalance=0.2,
  spread_bps=2.0,depth_usd_25bps=1_000_000.0,quote_volume_24h=100_000_000.0,
  return_5=.01,freshness_sec=0.0,continuity_ratio=1.0,data_quality=1.0,
  values={"synthesis_context":{"cycle_id":"c","world_state_hash":"sha256:"+"a"*64,
   "families":tuple(families),"family_payloads":family_payloads or {}}},
  complete=True,return_zscore=1.2,price_zscore=1.2,range_position=.9,trend_slope=.001,
  atr_pct=.01,reversal_return_1=-.001,momentum_consistency=.8,volume_ratio=1.0)

def fc(hypothesis="baseline_simple_momentum",direction="UP"):
 return Forecast(
  symbol="BTC/USD",timestamp_ms=1_000_000,horizon_seconds=300,model_id="probe",
  hypothesis=hypothesis,direction=direction,probability_positive_net=.55,
  expected_move_bps=20.0,expected_cost_bps=5.0,expected_net_bps=15.0,raw_score=.5,
  uncertainty=.5,calibration_state="BASELINE_FIXED",feature_version="phase2.v1",
  abstain=False,reason="probe",reasons=(),inputs={},execution_eligible=False)

def test_momentum_probe_missing_horizon_is_neutral():
 original=fc()
 out=challenge_forecast(original,feature(families=("LIQUIDITY",)),organ_scope="horizon_context")
 assert out==original

def test_reversion_probe_missing_edge_is_neutral():
 original=fc("baseline_simple_mean_reversion","DOWN")
 out=challenge_forecast(original,feature(families=()),organ_scope="edge_ecology")
 assert out==original

def test_random_negative_control_is_challengeable_but_not_improvable():
 original=fc("baseline_random","UP")
 out=challenge_forecast(original,feature(
  families=("LIQUIDITY","HORIZON"),
  family_payloads={"HORIZON":({"alignment":"ALIGNED_DOWN"},)},
 ),organ_scope="horizon_context")
 assert out.abstain is True
 assert out.probability_positive_net is None
 assert out.expected_move_bps is None
 assert out.expected_net_bps is None
