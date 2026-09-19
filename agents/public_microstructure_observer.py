"""Public microstructure observer: fetch once, custody first, interpret later."""
from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Any
from agents.market_memory import MarketMemory

@dataclass(frozen=True)
class CustodiedMicrostructure:
 symbol:str
 observed_ts_ms:int
 trade_line_id:str
 trade_payload_sha256:str
 book_line_id:str
 book_payload_sha256:str
 execution_eligible:bool=False
 promotion_eligible:bool=False

def observe_public_microstructure(*,client:Any,memory:MarketMemory,symbol:str,trade_limit:int=200,book_limit:int=25,observed_ts_ms:int|None=None)->CustodiedMicrostructure:
 ts=int(observed_ts_ms or time.time()*1000)
 trades=client.fetch_trades(symbol,limit=trade_limit)
 book=client.fetch_order_book(symbol,limit=book_limit)
 trade_id=memory.append_trade_flow(symbol=symbol,trades=trades,observed_ts_ms=ts)
 book_id=memory.append_order_book(symbol=symbol,book=book,effective_ts_ms=ts,observed_ts_ms=ts)
 trade=memory.conn.execute("SELECT payload_sha256 FROM memory_line WHERE line_id=?",(trade_id,)).fetchone()
 depth=memory.conn.execute("SELECT payload_sha256 FROM memory_line WHERE line_id=?",(book_id,)).fetchone()
 return CustodiedMicrostructure(symbol,ts,trade_id,str(trade["payload_sha256"]),book_id,str(depth["payload_sha256"]))
