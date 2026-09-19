from __future__ import annotations

import builtins
import importlib.util
from pathlib import Path

from agents.kraken_public_rest import KrakenPublicRestClient


def test_asset_pair_normalization_prefers_wsname():
    client=KrakenPublicRestClient()
    client._get=lambda method,params=None:{
        "XXBTZUSD":{
            "altname":"XBTUSD",
            "wsname":"XBT/USD",
            "base":"XXBT",
            "quote":"ZUSD",
            "status":"online",
        }
    }
    markets=client.load_markets()
    assert "BTC/USD" in markets
    assert markets["BTC/USD"]["active"] is True
    assert markets["BTC/USD"]["spot"] is True


def test_ticker_is_ccxt_shaped():
    client=KrakenPublicRestClient()
    calls=[]
    def fake(method,params=None):
        calls.append((method,params))
        if method=="AssetPairs":
            return {
                "XXBTZUSD":{
                    "altname":"XBTUSD","wsname":"XBT/USD",
                    "base":"XXBT","quote":"ZUSD","status":"online",
                }
            }
        if method=="Ticker":
            return {
                "XXBTZUSD":{
                    "a":["101.0"],"b":["100.0"],"c":["100.5"],
                    "v":["10.0","20.0"],"o":"99.5",
                }
            }
        raise AssertionError(method)
    client._get=fake
    ticker=client.fetch_ticker("BTC/USD")
    assert ticker["last"]==100.5
    assert ticker["bid"]==100.0
    assert ticker["ask"]==101.0
    assert ticker["baseVolume"]==20.0
    assert ticker["quoteVolume"]==2010.0


def test_ohlcv_matches_observer_expected_shape():
    client=KrakenPublicRestClient()
    def fake(method,params=None):
        if method=="AssetPairs":
            return {
                "XXBTZUSD":{
                    "altname":"XBTUSD","wsname":"XBT/USD",
                    "base":"XXBT","quote":"ZUSD","status":"online",
                }
            }
        if method=="OHLC":
            return {
                "XXBTZUSD":[
                    [1000,"1","2","0.5","1.5","1.4","3.0",10],
                    [1060,"1.5","2.5","1","2","1.9","4.0",12],
                ],
                "last":1060,
            }
        raise AssertionError(method)
    client._get=fake
    rows=client.fetch_ohlcv("BTC/USD",timeframe="1m",limit=2)
    assert rows==[
        [1000000,1.0,2.0,0.5,1.5,3.0],
        [1060000,1.5,2.5,1.0,2.0,4.0],
    ]


def test_order_book_matches_observer_expected_shape():
    client=KrakenPublicRestClient()
    def fake(method,params=None):
        if method=="AssetPairs":
            return {
                "XXBTZUSD":{
                    "altname":"XBTUSD","wsname":"XBT/USD",
                    "base":"XXBT","quote":"ZUSD","status":"online",
                }
            }
        if method=="Depth":
            return {
                "XXBTZUSD":{
                    "bids":[["100","2","1"]],
                    "asks":[["101","3","1"]],
                }
            }
        raise AssertionError(method)
    client._get=fake
    book=client.fetch_order_book("BTC/USD",limit=5)
    assert book["bids"]==[[100.0,2.0]]
    assert book["asks"]==[[101.0,3.0]]


def test_phase1_observer_imports_without_ccxt_dependency():
    path=Path("scripts/run_phase1_observer.py")
    spec=importlib.util.spec_from_file_location("phase1_observer_test_module",path)
    module=importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    client=module.KrakenPublicRestClient(timeout=1.0)
    assert isinstance(client,KrakenPublicRestClient)
