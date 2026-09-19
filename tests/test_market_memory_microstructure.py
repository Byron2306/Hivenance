from agents.market_memory import MarketMemory

def test_market_memory_custodies_public_flow_and_book(tmp_path):
 m=MarketMemory(tmp_path/"m.db")
 flow=m.append_trade_flow(symbol="BTC/USD",trades=[
  {"timestamp":1000,"price":100,"amount":2,"side":"buy"},
  {"timestamp":1001,"price":101,"amount":1,"side":"sell"}],observed_ts_ms=1002)
 book=m.append_order_book(symbol="BTC/USD",book={"bids":[[99,3],[98,2]],"asks":[[101,4],[102,1]]},effective_ts_ms=1003,observed_ts_ms=1004)
 fl=m.lines(kind="PUBLIC_TRADE_FLOW"); bl=m.lines(kind="PUBLIC_ORDER_BOOK")
 assert fl[0]["line_id"]==flow and fl[0]["payload"]["taker_buy_volume"]==2
 assert fl[0]["payload"]["taker_sell_volume"]==1
 assert bl[0]["line_id"]==book and bl[0]["payload"]["bid_depth"]==5
 assert bl[0]["payload"]["ask_depth"]==5 and bl[0]["payload"]["spread_bps"]>0
 assert fl[0]["execution_eligible"]==0 and bl[0]["promotion_eligible"]==0
 m.close()

def test_public_microstructure_memory_is_idempotent(tmp_path):
 m=MarketMemory(tmp_path/"m.db")
 trades=[{"timestamp":1000,"price":100,"amount":2,"side":"buy"}]
 a=m.append_trade_flow(symbol="BTC/USD",trades=trades,observed_ts_ms=1001)
 b=m.append_trade_flow(symbol="BTC/USD",trades=trades,observed_ts_ms=9999)
 assert a==b and len(m.lines(kind="PUBLIC_TRADE_FLOW"))==1
 m.close()
