from agents.market_memory import MarketMemory
from agents.public_microstructure_observer import observe_public_microstructure

class FakePublic:
 def fetch_trades(self,symbol,limit=200):
  return [{"timestamp":1000,"price":100,"amount":2,"side":"buy"},{"timestamp":1001,"price":101,"amount":1,"side":"sell"}]
 def fetch_order_book(self,symbol,limit=25):
  return {"symbol":symbol,"bids":[[99,3]],"asks":[[101,4]]}

def test_observer_custodies_before_returning(tmp_path):
 m=MarketMemory(tmp_path/"m.db")
 r=observe_public_microstructure(client=FakePublic(),memory=m,symbol="BTC/USD",observed_ts_ms=1002)
 assert len(m.lines(kind="PUBLIC_TRADE_FLOW"))==1
 assert len(m.lines(kind="PUBLIC_ORDER_BOOK"))==1
 assert r.trade_payload_sha256.startswith("sha256:")
 assert r.book_payload_sha256.startswith("sha256:")
 assert r.trade_payload_sha256!=r.book_payload_sha256
 assert not r.execution_eligible and not r.promotion_eligible
 m.close()
