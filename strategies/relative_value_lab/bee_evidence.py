"""Canonical Phase-5 evidence envelope for HiveNance evidence families."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY

SCHEMA = "hivenance_bee_evidence_v1"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BeeEvidence:
    schema: str
    evidence_id: str
    family: str
    source_kind: str
    source_ids: tuple[str, ...]
    evidence_roots: tuple[str, ...]
    lineage: tuple[str, ...]
    transformation_version: str
    observed_at_ms: int
    available_at_ms: int
    freshness: float
    confidence: float
    missingness: tuple[str, ...] = field(default_factory=tuple)
    abstention: bool = False
    payload: Mapping[str, Any] = field(default_factory=dict)
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if self.schema != SCHEMA:
            raise ValueError("bee_evidence_schema_invalid")
        if int(self.available_at_ms) < int(self.observed_at_ms):
            raise ValueError("bee_evidence_available_before_observation")
        if not 0 <= float(self.freshness) <= 1:
            raise ValueError("bee_evidence_freshness_out_of_range")
        if not 0 <= float(self.confidence) <= 1:
            raise ValueError("bee_evidence_confidence_out_of_range")
        if any(not str(root).startswith("sha256:") for root in self.evidence_roots):
            raise ValueError("bee_evidence_root_unbound")
        if not self.evidence_roots and (not self.abstention or not self.missingness):
            raise ValueError("bee_evidence_present_without_evidence_root")
        if not self.lineage:
            raise ValueError("bee_evidence_lineage_missing")
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("bee_evidence_authority_escalation_forbidden")
        if self.authority != RELATIVE_VALUE_AUTHORITY:
            raise ValueError("bee_evidence_authority_mismatch")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_bee_evidence(
    *,
    family: str,
    source_kind: str,
    source_ids: Sequence[str],
    evidence_roots: Sequence[str],
    lineage: Sequence[str],
    transformation_version: str,
    observed_at_ms: int,
    available_at_ms: int,
    freshness: float,
    confidence: float,
    payload: Mapping[str, Any],
    missingness: Sequence[str] = (),
    abstention: bool = False,
) -> BeeEvidence:
    roots = tuple(sorted(set(map(str, evidence_roots))))
    sources = tuple(sorted(set(map(str, source_ids))))
    lineage_tuple = tuple(map(str, lineage))
    missing = tuple(sorted(set(map(str, missingness))))

    body = {
        "family": family,
        "source_kind": source_kind,
        "source_ids": sources,
        "evidence_roots": roots,
        "lineage": lineage_tuple,
        "transformation_version": transformation_version,
        "observed_at_ms": observed_at_ms,
        "available_at_ms": available_at_ms,
        "freshness": freshness,
        "confidence": confidence,
        "missingness": missing,
        "abstention": abstention,
        "payload": dict(payload),
    }

    return BeeEvidence(
        schema=SCHEMA,
        evidence_id="bee_" + _digest(body).split(":", 1)[1][:24],
        family=family,
        source_kind=source_kind,
        source_ids=sources,
        evidence_roots=roots,
        lineage=lineage_tuple,
        transformation_version=transformation_version,
        observed_at_ms=int(observed_at_ms),
        available_at_ms=int(available_at_ms),
        freshness=float(freshness),
        confidence=float(confidence),
        missingness=missing,
        abstention=bool(abstention),
        payload=dict(payload),
    )


def liquidity_from_feature(feature: Any, *, evidence_root: str) -> BeeEvidence:
    values = feature.values if isinstance(feature.values, dict) else {}

    spread = feature.spread_bps
    depth = feature.depth_usd_25bps
    imbalance = feature.book_imbalance

    missing = []
    if spread is None:
        missing.append("spread_bps_unavailable")
    if depth is None:
        missing.append("depth_usd_25bps_unavailable")
    if imbalance is None:
        missing.append("book_imbalance_unavailable")

    present = spread is not None or depth is not None or imbalance is not None

    return build_bee_evidence(
        family="LIQUIDITY",
        source_kind="PUBLIC_ORDER_BOOK",
        source_ids=(f"{feature.symbol}:{feature.timestamp_ms}",),
        evidence_roots=(evidence_root,) if present else (),
        lineage=("hivenance.feature_engine.phase2.v1", "liquidity.v1"),
        transformation_version="liquidity.spread_depth_imbalance.v1",
        observed_at_ms=int(feature.timestamp_ms),
        available_at_ms=int(feature.timestamp_ms),
        freshness=max(
            0.0,
            min(
                1.0,
                1.0 - (float(feature.freshness_sec or 0.0) / 300.0),
            ),
        ) if present else 0.0,
        confidence=float(feature.data_quality or 0.0) if present else 0.0,
        missingness=missing,
        abstention=not present,
        payload={
            "symbol": feature.symbol,
            "spread_bps": spread,
            "depth_usd_25bps": depth,
            "book_imbalance": imbalance,
            "book_imbalance_is_proxy": bool(
                values.get("book_imbalance_is_proxy", False)
            ),
        },
    )


def volatility_from_feature(feature: Any, *, evidence_root: str) -> BeeEvidence:
    fast = feature.realized_volatility_fast
    baseline = feature.realized_volatility_baseline
    expansion = feature.volatility_expansion

    missing = []
    if fast is None:
        missing.append("realized_volatility_fast_unavailable")
    if baseline is None:
        missing.append("realized_volatility_baseline_unavailable")
    if expansion is None:
        missing.append("volatility_expansion_unavailable")

    present = fast is not None or baseline is not None or expansion is not None

    return build_bee_evidence(
        family="VOLATILITY",
        source_kind="PUBLIC_OHLCV",
        source_ids=(f"{feature.symbol}:{feature.timestamp_ms}",),
        evidence_roots=(evidence_root,) if present else (),
        lineage=("hivenance.feature_engine.phase2.v1", "volatility.v1"),
        transformation_version="volatility.realized_expansion.v1",
        observed_at_ms=int(feature.timestamp_ms),
        available_at_ms=int(feature.timestamp_ms),
        freshness=max(
            0.0,
            min(
                1.0,
                1.0 - (float(feature.freshness_sec or 0.0) / 300.0),
            ),
        ) if present else 0.0,
        confidence=float(feature.data_quality or 0.0) if present else 0.0,
        missingness=missing,
        abstention=not present,
        payload={
            "symbol": feature.symbol,
            "realized_volatility_fast": fast,
            "realized_volatility_baseline": baseline,
            "volatility_expansion": expansion,
        },
    )


def flow_from_feature(feature: Any, *, evidence_root: str) -> BeeEvidence:
    values = feature.values if isinstance(feature.values, dict) else {}

    order_flow = feature.order_flow_imbalance
    book_proxy = feature.book_imbalance
    flow_status = str(
        values.get(
            "order_flow_imbalance_status",
            "UNKNOWN",
        )
    )

    if order_flow is None:
        return build_bee_evidence(
            family="FLOW",
            source_kind="PUBLIC_TRADE_OR_BOOK_DELTA_FLOW",
            source_ids=(),
            evidence_roots=(),
            lineage=(
                "hivenance.feature_engine.phase2.v1",
                "flow.v1",
            ),
            transformation_version="flow.order_flow_imbalance.v1",
            observed_at_ms=int(feature.timestamp_ms),
            available_at_ms=int(feature.timestamp_ms),
            freshness=0.0,
            confidence=0.0,
            missingness=(
                "true_order_flow_unavailable",
                flow_status,
            ),
            abstention=True,
            payload={
                "symbol": feature.symbol,
                "order_flow_imbalance": None,
                "book_imbalance_proxy": book_proxy,
                "book_imbalance_is_proxy": bool(
                    values.get("book_imbalance_is_proxy", False)
                ),
                "status": flow_status,
            },
        )

    return build_bee_evidence(
        family="FLOW",
        source_kind="PUBLIC_TRADE_OR_BOOK_DELTA_FLOW",
        source_ids=(f"{feature.symbol}:{feature.timestamp_ms}",),
        evidence_roots=(evidence_root,),
        lineage=(
            "hivenance.feature_engine.phase2.v1",
            "flow.v1",
        ),
        transformation_version="flow.order_flow_imbalance.v1",
        observed_at_ms=int(feature.timestamp_ms),
        available_at_ms=int(feature.timestamp_ms),
        freshness=max(
            0.0,
            min(
                1.0,
                1.0 - (float(feature.freshness_sec or 0.0) / 300.0),
            ),
        ),
        confidence=float(feature.data_quality or 0.0),
        missingness=(),
        abstention=False,
        payload={
            "symbol": feature.symbol,
            "order_flow_imbalance": order_flow,
            "book_imbalance_proxy": book_proxy,
            "book_imbalance_is_proxy": bool(
                values.get("book_imbalance_is_proxy", False)
            ),
            "status": "PRESENT",
        },
    )


def cross_market_from_comparison(result: Any) -> BeeEvidence:
    """Canonicalize a timestamp-safe CROSS_SECTION ComparisonResult.

    Cross-market evidence remains descriptive. It cannot manufacture direction
    or independent roots beyond the peer observations already bound to result.
    """
    if str(result.comparison_type) != "CROSS_SECTION":
        raise ValueError("cross_market_requires_cross_section_result")

    roots = tuple(str(x) for x in result.evidence_roots)
    matched_n = int(result.matched_n or 0)

    missing = ()
    abstain = False

    if matched_n <= 0 or not roots:
        missing = ("cross_market_peer_set_unavailable",)
        abstain = True
        roots = ()

    confidence = (
        min(1.0, matched_n / 8.0)
        if matched_n > 0
        else 0.0
    )

    return build_bee_evidence(
        family="CROSS_MARKET",
        source_kind="PUBLIC_CROSS_SECTIONAL_MARKET",
        source_ids=tuple(str(x) for x in result.reference_ids),
        evidence_roots=roots,
        lineage=(
            "hivenance.comparison_engine.v1",
            "cross_section.v1",
        ),
        transformation_version="cross_market.cross_section.v1",
        observed_at_ms=int(result.observed_at_ms),
        available_at_ms=int(result.observed_at_ms),
        freshness=1.0 if matched_n > 0 else 0.0,
        confidence=confidence,
        missingness=missing,
        abstention=abstain,
        payload={
            "comparison_id": str(result.comparison_id),
            "comparison_type": str(result.comparison_type),
            "symbol": str(result.symbol),
            "matched_n": matched_n,
            "reference_ids": tuple(result.reference_ids),
            "metrics": dict(result.metrics),
        },
    )


def path_geometry_from_worker_series(
    *,
    symbol: str,
    timestamp_ms: int,
    worker_series: Mapping[str, Any],
    evidence_root: str,
    lookback_points: int = 17,
) -> BeeEvidence:
    """Build timestamp-safe path geometry from closes already known at T."""

    closes_raw = worker_series.get("closes") or []

    try:
        closes = [float(x) for x in closes_raw if x is not None]
    except Exception:
        closes = []

    n = max(5, int(lookback_points))
    if len(closes) < n:
        return build_bee_evidence(
            family="PATH_GEOMETRY",
            source_kind="PUBLIC_OHLCV_PATH",
            source_ids=(),
            evidence_roots=(),
            lineage=(
                "hivenance.worker_series.v1",
                "path_geometry.v1",
            ),
            transformation_version="path_geometry.pre_event_shape.v1",
            observed_at_ms=int(timestamp_ms),
            available_at_ms=int(timestamp_ms),
            freshness=0.0,
            confidence=0.0,
            missingness=("insufficient_path_history",),
            abstention=True,
            payload={
                "symbol": symbol,
                "points_available": len(closes),
                "points_required": n,
            },
        )

    xs = closes[-n:]

    returns_bps = []
    for a, b in zip(xs, xs[1:]):
        if a > 0:
            returns_bps.append(((b / a) - 1.0) * 10000.0)

    if not returns_bps:
        return build_bee_evidence(
            family="PATH_GEOMETRY",
            source_kind="PUBLIC_OHLCV_PATH",
            source_ids=(),
            evidence_roots=(),
            lineage=(
                "hivenance.worker_series.v1",
                "path_geometry.v1",
            ),
            transformation_version="path_geometry.pre_event_shape.v1",
            observed_at_ms=int(timestamp_ms),
            available_at_ms=int(timestamp_ms),
            freshness=0.0,
            confidence=0.0,
            missingness=("path_returns_unavailable",),
            abstention=True,
            payload={"symbol": symbol},
        )

    path = sum(abs(x) for x in returns_bps)
    net = (
        abs(((xs[-1] / xs[0]) - 1.0) * 10000.0)
        if xs[0] > 0
        else 0.0
    )

    efficiency = net / path if path > 0 else 0.0

    signs = [
        1 if x > 0 else -1
        for x in returns_bps
        if x != 0
    ]

    flips = sum(
        1
        for a, b in zip(signs, signs[1:])
        if a != b
    )

    flip_rate = (
        flips / max(1, len(signs) - 1)
        if signs
        else 0.0
    )

    hi = max(xs)
    lo = min(xs)

    range_bps = (
        ((hi / lo) - 1.0) * 10000.0
        if lo > 0
        else 0.0
    )

    range_position = (
        (xs[-1] - lo) / max(hi - lo, 1e-12)
        if hi > lo
        else 0.5
    )

    last4 = returns_bps[-4:]

    acceleration_bps = 0.0
    if len(last4) >= 4:
        acceleration_bps = (
            abs(last4[-1])
            - sum(abs(x) for x in last4[:-1]) / 3.0
        )

    confidence = min(
        1.0,
        len(returns_bps) / max(1.0, float(n - 1)),
    )

    return build_bee_evidence(
        family="PATH_GEOMETRY",
        source_kind="PUBLIC_OHLCV_PATH",
        source_ids=(f"{symbol}:{timestamp_ms}",),
        evidence_roots=(evidence_root,),
        lineage=(
            "hivenance.worker_series.v1",
            "path_geometry.v1",
        ),
        transformation_version="path_geometry.pre_event_shape.v1",
        observed_at_ms=int(timestamp_ms),
        available_at_ms=int(timestamp_ms),
        freshness=1.0,
        confidence=confidence,
        payload={
            "symbol": symbol,
            "lookback_points": n,
            "path_efficiency": efficiency,
            "flip_rate": flip_rate,
            "range_bps": range_bps,
            "range_position": range_position,
            "acceleration_bps": acceleration_bps,
            "path_length_bps": path,
            "net_displacement_bps": net,
        },
    )


def regime_from_feature(
    feature: Any,
    *,
    component_evidence_roots: Sequence[str],
) -> BeeEvidence:
    """Canonical timestamp-safe regime evidence.

    Uses regime classification already derived from the FeatureVector at T.
    Component evidence roots are preserved explicitly so regime testimony
    cannot masquerade as independent evidence.
    """
    values = feature.values if isinstance(feature.values, dict) else {}
    regime = (
        values.get("regime_inputs")
        if isinstance(values.get("regime_inputs"), dict)
        else {}
    )

    roots = tuple(sorted(set(str(x) for x in component_evidence_roots)))

    regime_hint = regime.get("regime_hint")
    confidence = regime.get("confidence")

    missing = []

    if regime_hint is None:
        missing.append("regime_hint_unavailable")
    if confidence is None:
        missing.append("regime_confidence_unavailable")

    if not roots:
        missing.append("regime_component_roots_unavailable")

    present = (
        regime_hint is not None
        and confidence is not None
        and bool(roots)
    )

    return build_bee_evidence(
        family="REGIME",
        source_kind="DERIVED_PUBLIC_MARKET_STATE",
        source_ids=(
            (f"{feature.symbol}:{feature.timestamp_ms}",)
            if present else ()
        ),
        evidence_roots=roots if present else (),
        lineage=(
            "hivenance.feature_engine.phase2.v1",
            "hivenance.regime_classifier.v1",
        ),
        transformation_version="regime.timestamp_safe_classifier.v1",
        observed_at_ms=int(feature.timestamp_ms),
        available_at_ms=int(feature.timestamp_ms),
        freshness=(
            max(
                0.0,
                min(
                    1.0,
                    1.0 - float(feature.freshness_sec or 0.0) / 300.0,
                ),
            )
            if present else 0.0
        ),
        confidence=(
            max(0.0, min(1.0, float(confidence)))
            if confidence is not None else 0.0
        ),
        missingness=missing,
        abstention=not present,
        payload={
            "symbol": feature.symbol,
            "regime_hint": regime_hint,
            "trend_direction": regime.get("trend_direction"),
            "liquidity_state": regime.get("liquidity_state"),
            "participation_state": regime.get("participation_state"),
            "component_evidence_roots": roots,
            "classifier_confidence": confidence,
        },
    )


def derivatives_carry_from_snapshot(
    *,
    symbol: str,
    snapshot: Mapping[str, Any],
    observed_at_ms: int,
    available_at_ms: int,
    evidence_root: str,
) -> BeeEvidence:
    """Canonical public derivatives/carry observation.

    Only timestamp-bound public observations are accepted. Manual carry inputs
    and modeled funding assumptions do not become market evidence here.
    """
    funding = snapshot.get("funding_rate")
    funding_source = str(snapshot.get("funding_rate_source") or "unavailable")
    mark = snapshot.get("mark_price")
    index = snapshot.get("index_price")
    spread = snapshot.get("spread_bps")

    missing = []

    if funding is None:
        missing.append("funding_rate_unavailable")
    if mark is None:
        missing.append("mark_price_unavailable")
    if index is None:
        missing.append("index_price_unavailable")

    basis_bps = None
    try:
        if mark is not None and index is not None and float(index) > 0:
            basis_bps = ((float(mark) / float(index)) - 1.0) * 10000.0
    except Exception:
        basis_bps = None

    if basis_bps is None:
        missing.append("basis_bps_unavailable")

    # At least funding or directly observed mark/index basis must exist.
    present = funding is not None or basis_bps is not None

    if funding_source == "manual_input_no_live_feed":
        present = False
        missing.append("manual_funding_input_not_market_evidence")

    return build_bee_evidence(
        family="DERIVATIVES_CARRY",
        source_kind="PUBLIC_DERIVATIVES_MARKET",
        source_ids=(
            (f"kraken_futures:{symbol}:{observed_at_ms}",)
            if present else ()
        ),
        evidence_roots=(evidence_root,) if present else (),
        lineage=(
            "hivenance.derivatives_observer.v1",
            "derivatives_carry.v1",
        ),
        transformation_version="derivatives.funding_basis.v1",
        observed_at_ms=int(observed_at_ms),
        available_at_ms=int(available_at_ms),
        freshness=1.0 if present else 0.0,
        confidence=(
            max(
                0.0,
                min(1.0, float(snapshot.get("data_quality") or 0.0)),
            )
            if present else 0.0
        ),
        missingness=missing,
        abstention=not present,
        payload={
            "symbol": symbol,
            "funding_rate": funding,
            "funding_rate_source": funding_source,
            "mark_price": mark,
            "index_price": index,
            "basis_bps": basis_bps,
            "spread_bps": spread,
        },
    )


def information_arrival_abstention(
    *,
    symbol: str,
    observed_at_ms: int,
) -> BeeEvidence:
    """Explicit Phase-5 abstention until event-time market information exists."""

    return build_bee_evidence(
        family="INFORMATION_ARRIVAL",
        source_kind="EXTERNAL_EVENT_TIME_FEED",
        source_ids=(),
        evidence_roots=(),
        lineage=(
            "hivenance.phase5",
            "information_arrival.v1",
        ),
        transformation_version="information_arrival.unavailable.v1",
        observed_at_ms=int(observed_at_ms),
        available_at_ms=int(observed_at_ms),
        freshness=0.0,
        confidence=0.0,
        missingness=(
            "timestamp_proven_external_information_feed_unavailable",
        ),
        abstention=True,
        payload={
            "symbol": symbol,
            "status": "UNAVAILABLE",
            "note": (
                "Internal EventSpine events are not external market "
                "information-arrival evidence."
            ),
        },
    )


def slow_capital_onchain_abstention(
    *,
    symbol: str,
    observed_at_ms: int,
) -> BeeEvidence:
    """Explicit abstention until slow-capital/on-chain provenance is complete."""

    return build_bee_evidence(
        family="SLOW_CAPITAL_ONCHAIN",
        source_kind="PUBLIC_ONCHAIN_SLOW_LATENCY",
        source_ids=(),
        evidence_roots=(),
        lineage=(
            "hivenance.phase5",
            "slow_capital_onchain.v1",
        ),
        transformation_version="slow_capital_onchain.unavailable.v1",
        observed_at_ms=int(observed_at_ms),
        available_at_ms=int(observed_at_ms),
        freshness=0.0,
        confidence=0.0,
        missingness=(
            "explicit_slow_latency_timestamp_provenance_unavailable",
        ),
        abstention=True,
        payload={
            "symbol": symbol,
            "status": "UNAVAILABLE",
            "note": (
                "Existing DEX oracle observations are useful research context "
                "but are not yet canonical slow-capital evidence."
            ),
        },
    )
