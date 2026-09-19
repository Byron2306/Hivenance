from agents.market_memory import MarketMemory
from strategies.relative_value_lab.custodied_edge_interpreter import custodied_edge_into_graph
from strategies.relative_value_lab.world_graph import WorldGraph
from strategies.relative_value_lab.world_score import CanonicalWorldScore,ScoreObservation

def test_custodied_facts_become_distinct_edge_roots(tmp_path):
 m=MarketMemory(tmp_path/"m.db")
 tid=m.append_trade_flow(symbol="BTC/USD",trades=[{"timestamp":10,"price":100,"amount":3,"side":"buy"},{"timestamp":11,"price":100,"amount":1,"side":"sell"}],observed_ts_ms=12)
 bid=m.append_order_book(symbol="BTC/USD",book={"bids":[[99,5]],"asks":[[101,4]]},effective_ts_ms=12,observed_ts_ms=12)
 root=ScoreObservation(observation_id="o",source_id="kraken",source_class="public_market",scope="BTC/USD",observed_at_ms=12,received_at_ms=12,evidence_root="sha256:"+"a"*64,payload={"price":100})
 g=WorldGraph(CanonicalWorldScore.assemble(observations=[root],assembled_at_ms=12,freshness_window_ms=100))
 f,l=custodied_edge_into_graph(memory=m,graph=g,trade_line_id=tid,book_line_id=bid,created_at_ms=12,pair_id="BTC/USD")
 assert f.family=="FLOW" and l.family=="LIQUIDITY"
 assert f.evidence_roots!=l.evidence_roots
 v=g.queen_view(created_at_ms=13,expected_families=("FLOW","LIQUIDITY"))
 assert set(("FLOW","LIQUIDITY")).issubset(v.families)
 assert v.independent_evidence_root_count==2
 m.close()

def test_interpreter_refuses_wrong_memory_kind(tmp_path):
 m=MarketMemory(tmp_path/"m.db")
 tid=m.append_trade_flow(symbol="BTC/USD",trades=[{"timestamp":10,"price":100,"amount":1,"side":"buy"}],observed_ts_ms=12)
 root=ScoreObservation(observation_id="o",source_id="kraken",source_class="public_market",scope="BTC/USD",observed_at_ms=12,received_at_ms=12,evidence_root="sha256:"+"a"*64,payload={"price":100})
 g=WorldGraph(CanonicalWorldScore.assemble(observations=[root],assembled_at_ms=12,freshness_window_ms=100))
 import pytest
 with pytest.raises(ValueError,match="book_line_wrong_kind"):
  custodied_edge_into_graph(memory=m,graph=g,trade_line_id=tid,book_line_id=tid,created_at_ms=12,pair_id="BTC/USD")
 m.close()
