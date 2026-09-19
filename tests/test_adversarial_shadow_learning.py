from types import SimpleNamespace
from strategies.volatility_breakout.adversarial_shadow import AdversarialShadowCourt
from strategies.volatility_breakout.adversarial_shadow_settlement import settle_adversarial_bundle
from strategies.volatility_breakout.adversarial_shadow_ledger import AdversarialShadowLedger
from strategies.volatility_breakout.adversarial_shadow_learning import adversarial_learning_receipt
from strategies.volatility_breakout.shadow_flight import ShadowSettlementEngine
from strategies.volatility_breakout.shadow_models import ShadowOrderIntent

def _i():return ShadowOrderIntent("s","f","z","p","c","m","market","kraken","BTC/USD","UP","buy","market","IOC",.01,1,100,None,250,.5,10,0,10,.6,61,999,1060,1,2,10000,"v","cfg")
def _cfg():return SimpleNamespace(phase5_shadow_entry_latency_ms=0,phase5_shadow_chase_timeout_sec=30,phase3_max_slippage_bps=0,phase3_maker_fee_bps=0,phase3_taker_fee_bps=0,exchange="kraken")
def test_court_persists_idempotently_and_yields_comparative_learning(tmp_path):
 b=AdversarialShadowCourt().build(_i());e=ShadowSettlementEngine(_cfg())
 tape=[{"ts":1000,"price":100,"spread_bps":0,"depth_usd_25bps":10000,"data_quality":1},{"ts":1060,"price":110,"spread_bps":0,"depth_usd_25bps":10000,"data_quality":1},{"ts":1120,"price":90,"spread_bps":0,"depth_usd_25bps":10000,"data_quality":1}]
 s=settle_adversarial_bundle(bundle=b,engine=e,observations=tape,settled_ts=1121)
 led=AdversarialShadowLedger(tmp_path/"court.db");a=led.persist(s,settled_ts=1121);b2=led.persist(s,settled_ts=1121)
 assert a==b2 and len(led.receipts())==1
 r=adversarial_learning_receipt(s)
 assert r["status"]=="PROSPECTIVE_SHADOW_EVIDENCE"
 assert r["comparisons"]["candidate_minus_no_trade_bps"]>0
 assert r["comparisons"]["candidate_minus_sign_inverted_bps"]>0
 assert not r["execution_eligible"] and not r["promotion_eligible"]
 led.close()
