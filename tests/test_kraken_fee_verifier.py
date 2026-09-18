from scripts.verify_kraken_fee_tier import _extract_fee_bps


def test_extract_fee_bps_from_current_kraken_object_shape():
    result = {
        "currency": "ZUSD",
        "fees": {
            "XETHZUSD": {
                "fee": "0.2600",
                "minfee": "0.1000",
                "maxfee": "0.2600",
            }
        },
        "fees_maker": {
            "XETHZUSD": {
                "fee": "0.1600",
                "minfee": "0.0000",
                "maxfee": "0.1600",
            }
        },
    }

    maker_bps, taker_bps, summary = _extract_fee_bps(result, "ETH/USD")

    assert maker_bps == 16.0
    assert taker_bps == 26.0
    assert summary["pair_key"] == "XETHZUSD"
    assert summary["maker_key"] == "XETHZUSD"


def test_extract_fee_bps_from_legacy_list_schedule_shape():
    result = {
        "fees": {"ETHUSD": [[0, 0.26], [50000, 0.24]]},
        "fees_maker": {"ETHUSD": [[0, 0.16], [50000, 0.14]]},
    }

    maker_bps, taker_bps, _summary = _extract_fee_bps(result, "ETH/USD")

    assert maker_bps == 14.0
    assert taker_bps == 24.0


def test_extract_fee_bps_falls_back_to_taker_for_non_maker_taker_pairs():
    result = {"fees": {"FOOUSD": {"fee": "0.4000"}}}

    maker_bps, taker_bps, _summary = _extract_fee_bps(result, "FOO/USD")

    assert maker_bps == 40.0
    assert taker_bps == 40.0
