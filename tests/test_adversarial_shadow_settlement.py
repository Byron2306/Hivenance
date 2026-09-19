from types import SimpleNamespace
from strategies.volatility_breakout.adversarial_shadow import AdversarialShadowCourt
from strategies.volatility_breakout.adversarial_shadow_settlement import settle_adversarial_bundle
from strategies.volatility_breakout.shadow_flight import ShadowSettlementEngine
from strategies.volatility_breakout.shadow_models import ShadowOrderIntent

def _i():
 return ShadowOrderIntent("s","f","z","p4","c","m","market","kraken","BTC/USD","UP","buy","market","IOC",.01,1,100,None,250,.5,10,0,10,.6,61,999,1060,1,2,10000,"v","cfg")
def _cfg(): return SimpleNamespace(phase5_shadow_entry_latency_ms=0,phase5_shadow_chase_timeout_sec=30,phase3_max_slippage_bps=0,phase3_maker_fee_bps=0,phase3_taker_fee_bps=0,exchange="kraken")
def test_candidate_and_controls_share_public_tape():
 b=AdversarialShadowCourt().build(_i());e=ShadowSettlementEngine(_cfg())
 tape=[{"ts":1000,"price":100,"spread_bps":0,"depth_usd_25bps":10000,"data_quality":1},{"ts":1060,"price":110,"spread_bps":0,"depth_usd_25bps":10000,"data_quality":1},{"ts":1120,"price":90,"spread_bps":0,"depth_usd_25bps":10000,"data_quality":1},{"ts":1180,"price":80,"spread_bps":0,"depth_usd_25bps":10000,"data_quality":1}]
 r=settle_adversarial_bundle(bundle=b,engine=e,observations=tape,settled_ts=1181)
 assert r.candidate is not None and r.candidate.net_return_bps>0
 inv=next(x for x in r.controls if x.control_type=="SIGN_INVERTED")
 no=next(x for x in r.controls if x.control_type=="NO_TRADE")
 shift=next(x for x in r.controls if x.control_type=="TIME_SHIFT_PLACEBO")
 assert inv.net_return_bps<0 and no.net_return_bps==0
 assert shift.net_return_bps<0
 assert not r.execution_wired and all(not x.execution_wired for x in r.controls)
def test_time_shift_refuses_to_fake_missing_future():
 b=AdversarialShadowCourt().build(_i());e=ShadowSettlementEngine(_cfg())
 tape=[{"ts":1000,"price":100,"spread_bps":0,"depth_usd_25bps":10000,"data_quality":1},{"ts":1060,"price":110,"spread_bps":0,"depth_usd_25bps":10000,"data_quality":1}]
 r=settle_adversarial_bundle(bundle=b,engine=e,observations=tape,settled_ts=1061)
 shift=next(x for x in r.controls if x.control_type=="TIME_SHIFT_PLACEBO")
 assert shift.status=="UNSETTLED"
