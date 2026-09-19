"""Interpret custodied public microstructure into the existing Edge organs."""
from __future__ import annotations
from typing import Any
from agents.market_memory import MarketMemory
from .edge_ecology import EdgeEcology
from .world_graph import WorldGraph,WorldGraphNode
from .world_graph_adapters import add_edge_ecology

def _line(memory:MarketMemory,line_id:str)->dict[str,Any]:
 row=memory.conn.execute("SELECT * FROM memory_line WHERE line_id=?",(line_id,)).fetchone()
 if row is None: raise ValueError("memory_line_not_found")
 import json
 d=dict(row);d["payload"]=json.loads(d.pop("payload_json"));return d

def custodied_edge_into_graph(*,memory:MarketMemory,graph:WorldGraph,trade_line_id:str,book_line_id:str,created_at_ms:int,pair_id:str,previous_imbalance:float|None=None,previous_book:dict[str,Any]|None=None)->tuple[WorldGraphNode,WorldGraphNode]:
 trade=_line(memory,trade_line_id);book=_line(memory,book_line_id)
 if trade["kind"]!="PUBLIC_TRADE_FLOW": raise ValueError("trade_line_wrong_kind")
 if book["kind"]!="PUBLIC_ORDER_BOOK": raise ValueError("book_line_wrong_kind")
 if trade["symbol"]!=pair_id or book["symbol"]!=pair_id: raise ValueError("microstructure_symbol_mismatch")
 tp=trade["payload"];bp=book["payload"]
 flow=EdgeEcology.flow_voice(taker_buy_volume=tp["taker_buy_volume"],taker_sell_volume=tp["taker_sell_volume"],previous_imbalance=previous_imbalance)
 prev=previous_book or {}
 liq=EdgeEcology.liquidity_voice(bid_depth=bp["bid_depth"],ask_depth=bp["ask_depth"],spread_bps=bp["spread_bps"],previous_bid_depth=prev.get("bid_depth"),previous_ask_depth=prev.get("ask_depth"))
 snap=EdgeEcology().snapshot(timestamp_ms=created_at_ms,pair_id=pair_id,voices=(flow,liq))
 nodes=add_edge_ecology(graph,snapshot=snap,created_at_ms=created_at_ms,family_source_roots={"FLOW":(trade["payload_sha256"],),"LIQUIDITY":(book["payload_sha256"],)})
 return nodes[0],nodes[1]
