from __future__ import annotations

import json
from dataclasses import dataclass

from strategies.volatility_breakout.venue_profiles import venue_profile


@dataclass
class Config:
    phase3_min_notional_usd: float = 5.0
    phase3_maker_fee_bps: float = 10.0
    phase3_taker_fee_bps: float = 20.0
    phase3_venue_economics_receipt: str = ""


def test_verified_kraken_receipt_overrides_loose_fee_settings(tmp_path):
    receipt = tmp_path / "fees.json"
    receipt.write_text(json.dumps({
        "schema": "hivenance_kraken_fee_verification_receipt_v1",
        "fee_source": "kraken_private_trade_volume",
        "settings_updated": True,
        "pair": "ETH/USD",
        "maker_fee_bps": 40.0,
        "taker_fee_bps": 80.0,
    }), encoding="utf-8")
    cfg = Config(phase3_venue_economics_receipt=str(receipt))

    profile = venue_profile("kraken", cfg)

    assert profile.maker_fee_bps == 40.0
    assert profile.taker_fee_bps == 80.0
    assert profile.fee_verified is True
    assert profile.economics_receipt_sha256
    assert profile.profile_version == "kraken-spot-account-tier.v1"


def test_missing_receipt_remains_explicitly_unverified():
    profile = venue_profile("kraken", Config())

    assert profile.maker_fee_bps == 10.0
    assert profile.taker_fee_bps == 20.0
    assert profile.fee_verified is False
