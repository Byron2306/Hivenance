from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VenueProfile:
    venue: str
    min_notional_usd: float
    min_quantity: float
    quantity_decimals: int
    price_decimals: int
    maker_fee_bps: float
    taker_fee_bps: float
    supported_policies: tuple[str, ...]
    profile_version: str

    def round_quantity(self, quantity: float) -> float:
        factor = 10 ** self.quantity_decimals
        return math.floor(max(0.0, float(quantity)) * factor) / factor

    def round_price(self, price: float) -> float:
        return round(max(0.0, float(price)), self.price_decimals)


POLICIES = (
    "market",
    "marketable_limit",
    "passive_post_only",
    "passive_then_chase",
)


def venue_profile(venue: str, cfg: Any) -> VenueProfile:
    """Return an explicit simulation profile.

    Phase 3 models venue constraints, but it does not claim this compact profile
    is a substitute for live instrument metadata. Precision and minimums are
    deliberately conservative defaults and are versioned in every result.
    """
    normalized = str(venue or "kraken").lower()
    if normalized != "kraken":
        # Research-only fallback. Unknown venues never become live eligible.
        return VenueProfile(
            venue=normalized,
            min_notional_usd=float(getattr(cfg, "phase3_min_notional_usd", 5.0) or 5.0),
            min_quantity=0.00000001,
            quantity_decimals=8,
            price_decimals=8,
            maker_fee_bps=float(getattr(cfg, "phase3_maker_fee_bps", 10.0) or 10.0),
            taker_fee_bps=float(getattr(cfg, "phase3_taker_fee_bps", 20.0) or 20.0),
            supported_policies=POLICIES,
            profile_version="generic-research.v1",
        )
    return VenueProfile(
        venue="kraken",
        min_notional_usd=float(getattr(cfg, "phase3_min_notional_usd", 5.0) or 5.0),
        min_quantity=0.00000001,
        quantity_decimals=8,
        price_decimals=8,
        maker_fee_bps=float(getattr(cfg, "phase3_maker_fee_bps", 10.0) or 10.0),
        taker_fee_bps=float(getattr(cfg, "phase3_taker_fee_bps", 20.0) or 20.0),
        supported_policies=POLICIES,
        profile_version="kraken-research.v1",
    )
