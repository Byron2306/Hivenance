from __future__ import annotations

from agents.kraken_public_client import KrakenPublicClient


def test_norm_asset_preserves_legitimate_xz_assets():
    assert KrakenPublicClient._norm_asset("XRP") == "XRP"
    assert KrakenPublicClient._norm_asset("XLM") == "XLM"
    assert KrakenPublicClient._norm_asset("XMR") == "XMR"
    assert KrakenPublicClient._norm_asset("ZEC") == "ZEC"


def test_norm_asset_maps_kraken_legacy_aliases_without_truncation():
    assert KrakenPublicClient._norm_asset("XXBT") == "BTC"
    assert KrakenPublicClient._norm_asset("XBT") == "BTC"
    assert KrakenPublicClient._norm_asset("XDG") == "DOGE"
    assert KrakenPublicClient._norm_asset("XXDG") == "DOGE"
    assert KrakenPublicClient._norm_asset("ZUSD") == "USD"
    assert KrakenPublicClient._norm_asset("ZEUR") == "EUR"


def test_load_markets_keeps_canonical_asset_names():
    client = KrakenPublicClient()
    client._get = lambda path, params=None: {
        "XXRPZUSD": {
            "wsname": "XRP/USD",
            "altname": "XRPUSD",
            "base": "XXRP",
            "quote": "ZUSD",
        },
        "XXLMZUSD": {
            "wsname": "XLM/USD",
            "altname": "XLMUSD",
            "base": "XXLM",
            "quote": "ZUSD",
        },
        "XXMRZUSD": {
            "wsname": "XMR/USD",
            "altname": "XMRUSD",
            "base": "XXMR",
            "quote": "ZUSD",
        },
        "XZECZUSD": {
            "wsname": "ZEC/USD",
            "altname": "ZECUSD",
            "base": "XZEC",
            "quote": "ZUSD",
        },
        "XDGZUSD": {
            "wsname": "XDG/USD",
            "altname": "XDGUSD",
            "base": "XDG",
            "quote": "ZUSD",
        },
    }
    markets = client.load_markets()
    assert "XRP/USD" in markets
    assert "XLM/USD" in markets
    assert "XMR/USD" in markets
    assert "ZEC/USD" in markets
    assert "DOGE/USD" in markets
    assert "RP/USD" not in markets
    assert "LM/USD" not in markets
    assert "MR/USD" not in markets
    assert "EC/USD" not in markets
    assert "DG/USD" not in markets
