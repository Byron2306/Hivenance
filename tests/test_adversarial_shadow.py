from strategies.volatility_breakout.adversarial_shadow import AdversarialShadowCourt
from strategies.volatility_breakout.shadow_models import ShadowOrderIntent

def _intent():
 return ShadowOrderIntent("s1","f1","z1","p4","c","m","market","kraken","BTC/USD","UP","buy","market","IOC",.1,10,100,None,250,.5,20,5,15,.6,60,1000,1060,1,5,1000,"v","cfg")

def test_adversarial_bundle_is_deterministic_and_nontransmitting():
 c=AdversarialShadowCourt();a=c.build(_intent());b=c.build(_intent())
 assert a.bundle_id==b.bundle_id
 assert {x.control_type for x in a.controls}==set(c.CONTROL_TYPES)
 assert next(x for x in a.controls if x.control_type=="SIGN_INVERTED").direction=="DOWN"
 assert all(x.transmission_status=="NEVER_TRANSMITTED" and not x.execution_wired and not x.live_eligible for x in a.controls)
 assert not a.execution_wired and not a.live_eligible

def test_no_trade_has_no_direction_and_random_is_reproducible():
 c=AdversarialShadowCourt();a=c.build(_intent());b=c.build(_intent())
 no=next(x for x in a.controls if x.control_type=="NO_TRADE")
 ra=next(x for x in a.controls if x.control_type=="DETERMINISTIC_RANDOM")
 rb=next(x for x in b.controls if x.control_type=="DETERMINISTIC_RANDOM")
 assert no.direction is None and ra.direction==rb.direction
