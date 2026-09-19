from agents.kraken_public_rest import KrakenPublicRestClient
from strategies.relative_value_lab.edge_ecology import EdgeEcology
from strategies.relative_value_lab.metatron_ml_challenger import MetatronMLChallenger


def test_public_trade_normalization_without_network():
    c=KrakenPublicRestClient()
    c._markets={"BTC/USD":{"id":"XXBTZUSD","symbol":"BTC/USD"}}
    c._symbol_to_pair={"BTC/USD":"XXBTZUSD"}
    c._get=lambda method,params=None: {"XXBTZUSD":[["100","0.5",123.0,"b","m",""],["99","0.25",124.0,"s","l",""]],"last":"x"}
    rows=c.fetch_trades("BTC/USD")
    assert rows[0]["side"]=="buy" and rows[1]["side"]=="sell"
    assert rows[0]["amount"]==0.5 and rows[0]["timestamp"]==123000


def test_ecology_and_ml_never_gain_execution_authority():
    eco=EdgeEcology()
    flow=eco.flow_voice(taker_buy_volume=51,taker_sell_volume=49,previous_imbalance=.7)
    liq=eco.liquidity_voice(bid_depth=700,ask_depth=650,spread_bps=4,previous_bid_depth=500,previous_ask_depth=500)
    snap=eco.snapshot(timestamp_ms=1,pair_id="BTC/USD",voices=[flow,liq])
    assert snap.execution_eligible is False and snap.promotion_eligible is False
    model=MetatronMLChallenger(seed=2306)
    model.fit([[i/100,(i%5)/10] for i in range(1,100)])
    challenge=model.challenge([.5,.2])
    assert challenge.research_only and not challenge.execution_eligible and not challenge.promotion_eligible
