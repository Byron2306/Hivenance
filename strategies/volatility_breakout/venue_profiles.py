from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
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
    fee_source: str = "configured_research_profile_unverified"
    fee_verified: bool = False
    economics_receipt_sha256: str = ""

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


def _verified_fee_receipt(cfg: Any) -> tuple[float | None, float | None, str, bool, str]:
    """Read the immutable fee receipt when one has been explicitly configured.

    The receipt binds research costs to an account-tier observation.  A bad or
    missing receipt never blocks research, but deliberately remains unverified.
    """
    configured = str(getattr(cfg, "phase3_venue_economics_receipt", "") or "").strip()
    if not configured:
        return None, None, "configured_research_profile_unverified", False, ""
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
        maker = float(payload["maker_fee_bps"])
        taker = float(payload["taker_fee_bps"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None, None, "configured_research_profile_unverified", False, ""
    verified = (
        str(payload.get("schema") or "") == "hivenance_kraken_fee_verification_receipt_v1"
        and str(payload.get("fee_source") or "") == "kraken_private_trade_volume"
        and bool(payload.get("settings_updated"))
    )
    digest = hashlib.sha256(raw).hexdigest()
    source = str(payload.get("fee_source") or "configured_research_profile")
    pair = str(payload.get("pair") or "unknown_pair")
    return maker, taker, f"{source}:{pair}", verified, digest


def venue_profile(venue: str, cfg: Any) -> VenueProfile:
    """Return an explicit simulation profile.

    Phase 3 models venue constraints, but it does not claim this compact profile
    is a substitute for live instrument metadata. Precision and minimums are
    deliberately conservative defaults and are versioned in every result.
    """
    normalized = str(venue or "kraken").lower()
    receipt_maker, receipt_taker, fee_source, fee_verified, receipt_sha256 = _verified_fee_receipt(cfg)
    maker_fee = receipt_maker if receipt_maker is not None else float(
        getattr(cfg, "phase3_maker_fee_bps", 10.0) or 10.0
    )
    taker_fee = receipt_taker if receipt_taker is not None else float(
        getattr(cfg, "phase3_taker_fee_bps", 20.0) or 20.0
    )
    if normalized.startswith("dex_"):
        # On-chain venues have no CEX-style maker/taker fee schedule. AMM LP
        # fees, slippage, and price impact are already priced into the
        # spread_bps/depth_usd_25bps features DexPublicClient synthesizes
        # from a real aggregator round-trip quote, so charging a Kraken-style
        # taker fee on top would double-count that friction. Gas is a
        # separate, roughly per-trade cost handled via phase2_safety_buffer_bps
        # on the DEX runner scripts, not here. Never live eligible.
        return VenueProfile(
            venue=normalized,
            min_notional_usd=float(getattr(cfg, "phase3_min_notional_usd", 5.0) or 5.0),
            min_quantity=0.00000001,
            quantity_decimals=8,
            price_decimals=8,
            maker_fee_bps=0.0,
            taker_fee_bps=0.0,
            supported_policies=POLICIES,
            profile_version="dex-amm-research.v1",
            fee_source="dex_no_cex_fee_schedule_amm_friction_priced_via_spread_proxy",
            fee_verified=False,
            economics_receipt_sha256="",
        )
    if normalized == "kraken_futures":
        # Derivatives (perpetual futures) fee profile. Substantially cheaper
        # than the Kraken spot schedule, but this deliberately never reuses
        # the spot fee-verification receipt above (that receipt is scoped to
        # "hivenance_kraken_fee_verification_receipt_v1" spot account-tier
        # data and would misrepresent futures economics if applied here).
        # Futures fees stay an unverified configured research default until a
        # dedicated futures fee receipt mechanism exists -- exactly like the
        # spot path, this never becomes live/execution eligible on its own.
        # No live Kraken Futures market-data feed exists in this codebase
        # yet; see derivatives_trend_lab.py for the honesty caveat on the
        # price/momentum data source.
        return VenueProfile(
            venue=normalized,
            min_notional_usd=float(getattr(cfg, "derivatives_trend_min_notional_usd", 10.0) or 10.0),
            min_quantity=0.00000001,
            quantity_decimals=8,
            price_decimals=8,
            maker_fee_bps=float(getattr(cfg, "derivatives_trend_maker_fee_bps", 2.0) or 2.0),
            taker_fee_bps=float(getattr(cfg, "derivatives_trend_taker_fee_bps", 5.0) or 5.0),
            supported_policies=(*POLICIES, "post_only_then_bounded_taker"),
            profile_version="kraken-futures-research.v1",
            fee_source="configured_research_profile_unverified",
            fee_verified=False,
            economics_receipt_sha256="",
        )
    if normalized != "kraken":
        # Research-only fallback. Unknown venues never become live eligible.
        return VenueProfile(
            venue=normalized,
            min_notional_usd=float(getattr(cfg, "phase3_min_notional_usd", 5.0) or 5.0),
            min_quantity=0.00000001,
            quantity_decimals=8,
            price_decimals=8,
            maker_fee_bps=maker_fee,
            taker_fee_bps=taker_fee,
            supported_policies=POLICIES,
            profile_version="generic-research.v1",
            fee_source=fee_source,
            fee_verified=fee_verified,
            economics_receipt_sha256=receipt_sha256,
        )
    return VenueProfile(
        venue="kraken",
        min_notional_usd=float(getattr(cfg, "phase3_min_notional_usd", 5.0) or 5.0),
        min_quantity=0.00000001,
        quantity_decimals=8,
        price_decimals=8,
        maker_fee_bps=maker_fee,
        taker_fee_bps=taker_fee,
        supported_policies=POLICIES,
        profile_version="kraken-spot-account-tier.v1" if fee_verified else "kraken-research.v1",
        fee_source=fee_source,
        fee_verified=fee_verified,
        economics_receipt_sha256=receipt_sha256,
    )
