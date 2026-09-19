"""Phase-1 canonical bridge: live public observation -> MarketMemory -> world identity.

This module does not create trading authority. It binds one Phase-1 feature
observation to the append-only MarketMemory, CanonicalScoreFrame and replayable
WorldStatePage so downstream cognition can share one observed root.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from agents.market_memory import MarketMemory
from agents.world_state import WorldStateBuilder
from .world_score import CanonicalScoreFrame, ScoreObservation, CanonicalWorldScore
from .world_graph import WorldGraph, WorldGraphNode
from .contracts import RELATIVE_VALUE_AUTHORITY

AUTHORITY = "PUBLIC_MARKET_RESEARCH_CANONICAL_WORLD_BINDING_ONLY"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _frame_to_dict(frame: CanonicalScoreFrame) -> dict[str, Any]:
    return frame.to_dict()


def frame_from_binding(binding: Mapping[str, Any]) -> CanonicalScoreFrame:
    raw = binding.get("canonical_score_frame")
    if not isinstance(raw, Mapping):
        raise ValueError("canonical_world_binding_frame_missing")
    observations_raw = raw.get("observations") or ()
    observations = tuple(
        ScoreObservation(
            observation_id=str(row["observation_id"]),
            source_id=str(row["source_id"]),
            source_class=str(row["source_class"]),
            scope=str(row["scope"]),
            observed_at_ms=int(row["observed_at_ms"]),
            received_at_ms=int(row["received_at_ms"]),
            evidence_root=str(row["evidence_root"]),
            payload=dict(row.get("payload") or {}),
            namespace=str(row.get("namespace") or "observed_market"),
        )
        for row in observations_raw
    )
    frame = CanonicalScoreFrame(
        schema=str(raw["schema"]),
        world_state_id=str(raw["world_state_id"]),
        world_state_hash=str(raw["world_state_hash"]),
        assembled_at_ms=int(raw["assembled_at_ms"]),
        latest_observation_ms=int(raw["latest_observation_ms"]),
        oldest_observation_ms=int(raw["oldest_observation_ms"]),
        freshness_window_ms=int(raw["freshness_window_ms"]),
        expires_at_ms=int(raw["expires_at_ms"]),
        observation_count=int(raw["observation_count"]),
        sources=tuple(raw.get("sources") or ()),
        scopes=tuple(raw.get("scopes") or ()),
        observed_digest=str(raw["observed_digest"]),
        observations=observations,
        namespace=str(raw.get("namespace") or "observed_market"),
        authority=str(raw.get("authority") or RELATIVE_VALUE_AUTHORITY),
        execution_eligible=bool(raw.get("execution_eligible", False)),
        promotion_eligible=bool(raw.get("promotion_eligible", False)),
    )
    if frame.execution_eligible or frame.promotion_eligible:
        raise ValueError("canonical_world_binding_authority_escalation")
    expected_id = str(binding.get("canonical_world_state_id") or "")
    expected_hash = str(binding.get("canonical_world_state_hash") or "")
    if expected_id and frame.world_state_id != expected_id:
        raise ValueError("canonical_world_binding_id_mismatch")
    if expected_hash and frame.world_state_hash != expected_hash:
        raise ValueError("canonical_world_binding_hash_mismatch")
    return frame


class CanonicalMemoryWorldBridge:
    """Bind a live public observation to the canonical research-memory spine."""

    schema = "hivenance_canonical_memory_world_binding_v1"

    def __init__(
        self,
        memory_path: str | Path = "data/hivenance_market_memory.db",
        *,
        freshness_window_ms: int = 180_000,
    ) -> None:
        self.memory_path = str(memory_path)
        self.freshness_window_ms = max(1_000, int(freshness_window_ms))

    def ingest(
        self,
        *,
        venue: str,
        symbol: str,
        observed_at_ms: int,
        timeframe: str,
        ohlcv: Sequence[Sequence[Any]],
        orderbook: Mapping[str, Any],
        feature_payload: Mapping[str, Any],
        peer_symbols: Sequence[str] = (),
    ) -> dict[str, Any]:
        """Persist public facts idempotently and return one canonical world binding."""
        if not symbol:
            raise ValueError("canonical_bridge_symbol_required")
        if not isinstance(feature_payload, Mapping):
            raise ValueError("canonical_bridge_feature_payload_required")
        observed_at_ms = int(observed_at_ms)
        if int(feature_payload.get("timestamp_ms") or observed_at_ms) != observed_at_ms:
            raise ValueError("canonical_bridge_feature_timestamp_mismatch")

        normalized_rows = tuple(tuple(row) for row in ohlcv)
        future_rows = [
            int(row[0]) for row in normalized_rows
            if len(row) >= 1 and int(row[0]) > observed_at_ms
        ]
        if future_rows:
            raise ValueError("canonical_bridge_future_ohlcv_forbidden")

        source_prefix = str(venue or "unknown").lower()
        memory = MarketMemory(self.memory_path)
        try:
            bar_line_ids = memory.append_bars(
                symbol=str(symbol),
                timeframe=str(timeframe),
                rows=normalized_rows,
                source=f"{source_prefix}_public_ohlcv",
            )
            book_line_id = None
            if isinstance(orderbook, Mapping) and orderbook.get("bids") and orderbook.get("asks"):
                book_line_id = memory.append_order_book(
                    symbol=str(symbol),
                    book=dict(orderbook),
                    effective_ts_ms=observed_at_ms,
                    observed_ts_ms=observed_at_ms,
                    source=f"{source_prefix}_public_order_book",
                )

            live_payload = {
                "schema": "hivenance_phase1_live_feature_observation_v1",
                "ingest_class": "LIVE_PROSPECTIVE_PUBLIC_OBSERVATION",
                "venue": source_prefix,
                "symbol": str(symbol),
                "observed_at_ms": observed_at_ms,
                "timeframe": str(timeframe),
                "feature": dict(feature_payload),
            }
            feature_line_id = memory.append(
                source=f"phase1_observation_swarm:{source_prefix}",
                kind="PHASE1_LIVE_FEATURE_OBSERVATION",
                payload=live_payload,
                effective_ts_ms=observed_at_ms,
                observed_ts_ms=observed_at_ms,
                symbol=str(symbol),
            )

            observation = ScoreObservation(
                observation_id="obs_" + feature_line_id.split(":", 1)[-1][:24],
                source_id=f"phase1_observation_swarm:{source_prefix}",
                source_class="public_market_live_observation",
                scope=str(symbol),
                observed_at_ms=observed_at_ms,
                received_at_ms=observed_at_ms,
                evidence_root=feature_line_id,
                payload=dict(feature_payload),
            )
            frame = CanonicalWorldScore.assemble(
                observations=(observation,),
                assembled_at_ms=observed_at_ms,
                freshness_window_ms=self.freshness_window_ms,
            )

            world_page = None
            world_page_status = "PRESENT"
            world_page_reason = None
            try:
                world_page = WorldStateBuilder(memory).build(
                    str(symbol), observed_at_ms, list(peer_symbols)
                ).to_dict()
            except ValueError as exc:
                world_page_status = "ABSENT_HISTORY"
                world_page_reason = str(exc)

            bar_digest = _digest(bar_line_ids)
            lineage_payload = {
                "feature_memory_line_id": feature_line_id,
                "orderbook_memory_line_id": book_line_id,
                "ohlcv_memory_line_count": len(bar_line_ids),
                "ohlcv_memory_lines_digest": bar_digest,
                "canonical_world_state_id": frame.world_state_id,
                "canonical_world_state_hash": frame.world_state_hash,
                "world_state_page_id": (
                    str(world_page.get("world_state_id")) if isinstance(world_page, dict) else None
                ),
            }
            lineage_digest = _digest(lineage_payload)
            return {
                "schema": self.schema,
                "authority": AUTHORITY,
                "execution_eligible": False,
                "promotion_eligible": False,
                "ingest_class": "LIVE_PROSPECTIVE_PUBLIC_OBSERVATION",
                "venue": source_prefix,
                "symbol": str(symbol),
                "observed_at_ms": observed_at_ms,
                "memory_path": self.memory_path,
                "feature_memory_line_id": feature_line_id,
                "orderbook_memory_line_id": book_line_id,
                "ohlcv_memory_line_count": len(bar_line_ids),
                "ohlcv_memory_lines_digest": bar_digest,
                "canonical_world_state_id": frame.world_state_id,
                "canonical_world_state_hash": frame.world_state_hash,
                "canonical_score_frame": _frame_to_dict(frame),
                "world_state_page_status": world_page_status,
                "world_state_page_reason": world_page_reason,
                "world_state_page": world_page,
                "lineage_digest": lineage_digest,
            }
        finally:
            memory.close()


def validate_binding(
    binding: Mapping[str, Any],
    *,
    symbol: str | None = None,
    observed_at_ms: int | None = None,
) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    if binding.get("schema") != CanonicalMemoryWorldBridge.schema:
        reasons.append("canonical_binding_schema_invalid")
    if binding.get("authority") != AUTHORITY:
        reasons.append("canonical_binding_authority_invalid")
    if binding.get("execution_eligible") is not False:
        reasons.append("canonical_binding_execution_authority_invalid")
    if binding.get("promotion_eligible") is not False:
        reasons.append("canonical_binding_promotion_authority_invalid")
    if binding.get("ingest_class") != "LIVE_PROSPECTIVE_PUBLIC_OBSERVATION":
        reasons.append("canonical_binding_ingest_class_invalid")
    if symbol is not None and str(binding.get("symbol") or "") != str(symbol):
        reasons.append("canonical_binding_symbol_mismatch")
    if observed_at_ms is not None and int(binding.get("observed_at_ms") or -1) != int(observed_at_ms):
        reasons.append("canonical_binding_timestamp_mismatch")
    try:
        frame = frame_from_binding(binding)
        if symbol is not None and str(frame.scopes[0] if frame.scopes else "") != str(symbol):
            reasons.append("canonical_binding_frame_scope_mismatch")
    except Exception as exc:
        reasons.append(f"canonical_binding_frame_invalid:{type(exc).__name__}")
    return not reasons, tuple(reasons)


def world_graph_root_from_binding(
    binding: Mapping[str, Any],
    *,
    created_at_ms: int | None = None,
) -> tuple[WorldGraph, WorldGraphNode]:
    """Create the first interpreted WorldGraph node bound to the canonical frame."""
    frame = frame_from_binding(binding)
    page = binding.get("world_state_page")
    if not isinstance(page, Mapping):
        raise ValueError("canonical_binding_world_state_page_missing")
    feature_root = str(binding.get("feature_memory_line_id") or "")
    if not feature_root.startswith("sha256:"):
        raise ValueError("canonical_binding_feature_root_invalid")
    at = int(created_at_ms if created_at_ms is not None else binding.get("observed_at_ms") or frame.assembled_at_ms)
    graph = WorldGraph(frame)
    node = graph.add_node(
        organ_id="world_state_builder",
        family="WORLD_STATE",
        created_at_ms=at,
        evidence_roots=(feature_root,),
        lineage_id="hivenance.world_state_builder.v1",
        transformation_id="market_memory_to_world_state_page.v1",
        payload={
            "world_state_page": dict(page),
            "canonical_world_state_id": frame.world_state_id,
            "canonical_world_state_hash": frame.world_state_hash,
            "lineage_digest": binding.get("lineage_digest"),
        },
        freshness=1.0 if frame.is_fresh(at) else 0.0,
        uncertainty=0.0,
        synthetic=False,
    )
    return graph, node
