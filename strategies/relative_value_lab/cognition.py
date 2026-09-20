from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from strategies.volatility_breakout.models import Forecast
from .contracts import RELATIVE_VALUE_AUTHORITY
from .world_graph import WorldGraph, WorldGraphNode


SCHEMA = "hivenance_cognition_node_v1"

ALLOWED_ROLES = {
    "PRIMARY_HYPOTHESIS",
    "FEDERATED_CANDIDATE",
    "WORKER_PROPOSAL",
    "WORKER_COALITION",
    "REGIME_CONTEXT",
    "MEMORY_CONTEXT",
    "PROFITABILITY_FRONTIER",
    "POSITIVE_THESIS_CRYSTAL",
    "NEGATIVE_CAPABILITY_CRYSTAL",
    "MEDIUM_HORIZON_TREND",
    "DERIVATIVES_TREND",
    "CEX_MULTI_HORIZON_ORACLE",
}


def _digest(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class CognitionNode:
    schema: str
    cognition_id: str
    role: str
    source_id: str
    observed_at_ms: int
    available_at_ms: int
    evidence_roots: tuple[str, ...]
    lineage: tuple[str, ...]
    transformation_version: str
    payload: Mapping[str, Any]
    authority: str = RELATIVE_VALUE_AUTHORITY
    challenger: bool = True
    proposal_only: bool = True
    memory_only: bool = False
    historical_only: bool = False
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def __post_init__(self) -> None:
        if self.schema != SCHEMA:
            raise ValueError("cognition_schema_invalid")
        if self.role not in ALLOWED_ROLES:
            raise ValueError(f"cognition_role_invalid:{self.role}")
        if not self.source_id:
            raise ValueError("cognition_source_id_missing")
        if int(self.available_at_ms) < int(self.observed_at_ms):
            raise ValueError("cognition_available_before_observed")
        if not self.lineage:
            raise ValueError("cognition_lineage_missing")
        if not self.transformation_version:
            raise ValueError("cognition_transformation_missing")
        if any(
            not str(root).startswith("sha256:")
            for root in self.evidence_roots
        ):
            raise ValueError("cognition_evidence_root_invalid")
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("cognition_authority_escalation_forbidden")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_cognition(
    *,
    role: str,
    source_id: str,
    observed_at_ms: int,
    available_at_ms: int,
    evidence_roots: Sequence[str],
    lineage: Sequence[str],
    transformation_version: str,
    payload: Mapping[str, Any],
    challenger: bool = True,
    proposal_only: bool = True,
    memory_only: bool = False,
    historical_only: bool = False,
) -> CognitionNode:
    roots = tuple(sorted(set(str(x) for x in evidence_roots)))
    line = tuple(str(x) for x in lineage)

    body = {
        "schema": SCHEMA,
        "role": str(role),
        "source_id": str(source_id),
        "observed_at_ms": int(observed_at_ms),
        "available_at_ms": int(available_at_ms),
        "evidence_roots": roots,
        "lineage": line,
        "transformation_version": str(transformation_version),
        "payload": dict(payload),
        "authority": RELATIVE_VALUE_AUTHORITY,
        "challenger": bool(challenger),
        "proposal_only": bool(proposal_only),
        "memory_only": bool(memory_only),
        "historical_only": bool(historical_only),
        "execution_eligible": False,
        "promotion_eligible": False,
    }

    cid = "cog_" + _digest(body).split(":", 1)[1][:24]

    return CognitionNode(
        schema=SCHEMA,
        cognition_id=cid,
        role=str(role),
        source_id=str(source_id),
        observed_at_ms=int(observed_at_ms),
        available_at_ms=int(available_at_ms),
        evidence_roots=roots,
        lineage=line,
        transformation_version=str(transformation_version),
        payload=dict(payload),
        authority=RELATIVE_VALUE_AUTHORITY,
        challenger=bool(challenger),
        proposal_only=bool(proposal_only),
        memory_only=bool(memory_only),
        historical_only=bool(historical_only),
        execution_eligible=False,
        promotion_eligible=False,
    )


def forecast_to_cognition(
    forecast: Forecast,
    *,
    role: str,
    evidence_roots: Sequence[str],
    available_at_ms: int | None = None,
) -> CognitionNode:
    if role not in {
        "PRIMARY_HYPOTHESIS",
        "FEDERATED_CANDIDATE",
        "WORKER_PROPOSAL",
        "WORKER_COALITION",
        "MEDIUM_HORIZON_TREND",
        "DERIVATIVES_TREND",
        "CEX_MULTI_HORIZON_ORACLE",
    }:
        raise ValueError(f"forecast_cognition_role_invalid:{role}")

    if forecast.execution_eligible:
        raise ValueError("forecast_execution_authority_forbidden")

    observed = int(forecast.timestamp_ms)
    available = int(
        available_at_ms
        if available_at_ms is not None
        else observed
    )

    payload = {
        "model_id": forecast.model_id,
        "hypothesis": forecast.hypothesis,
        "symbol": forecast.symbol,
        "timestamp_ms": forecast.timestamp_ms,
        "horizon_seconds": forecast.horizon_seconds,
        "direction": forecast.direction,
        "probability_positive_net": forecast.probability_positive_net,
        "expected_move_bps": forecast.expected_move_bps,
        "expected_cost_bps": forecast.expected_cost_bps,
        "expected_net_bps": forecast.expected_net_bps,
        "raw_score": forecast.raw_score,
        "uncertainty": forecast.uncertainty,
        "calibration_state": forecast.calibration_state,
        "feature_version": forecast.feature_version,
        "abstain": forecast.abstain,
        "reason": forecast.reason,
        "reasons": tuple(forecast.reasons),
        "inputs": dict(forecast.inputs or {}),
        "execution_eligible": False,
        "promotion_eligible": False,
    }

    return build_cognition(
        role=role,
        source_id=str(forecast.model_id),
        observed_at_ms=observed,
        available_at_ms=available,
        evidence_roots=evidence_roots,
        lineage=(
            "hivenance.hypothesis_competition",
            str(forecast.model_id),
        ),
        transformation_version=(
            f"forecast.{str(forecast.model_id)}.v1"
        ),
        payload=payload,
        challenger=True,
        proposal_only=True,
        memory_only=False,
        historical_only=False,
    )


def add_cognition(
    graph: WorldGraph,
    *,
    cognition: CognitionNode,
    created_at_ms: int | None = None,
) -> WorldGraphNode:
    created = int(
        cognition.available_at_ms
        if created_at_ms is None
        else created_at_ms
    )

    return graph.add_node(
        organ_id="phoenix_cognition",
        family=cognition.role,
        created_at_ms=created,
        evidence_roots=cognition.evidence_roots,
        lineage_id="|".join(cognition.lineage),
        transformation_id=cognition.transformation_version,
        payload=cognition.to_dict(),
        freshness=1.0,
        uncertainty=max(
            0.0,
            min(
                1.0,
                float(
                    cognition.payload.get("uncertainty")
                    if cognition.payload.get("uncertainty") is not None
                    else 0.5
                ),
            ),
        ),
    )


def add_hypothesis_forecasts(
    graph: WorldGraph,
    *,
    primary_forecasts: Sequence[Forecast],
    federated_forecasts: Sequence[Forecast],
    evidence_roots: Sequence[str],
    created_at_ms: int | None = None,
) -> tuple[WorldGraphNode, ...]:
    nodes: list[WorldGraphNode] = []

    for forecast in primary_forecasts:
        cognition = forecast_to_cognition(
            forecast,
            role="PRIMARY_HYPOTHESIS",
            evidence_roots=evidence_roots,
            available_at_ms=created_at_ms,
        )
        nodes.append(
            add_cognition(
                graph,
                cognition=cognition,
                created_at_ms=created_at_ms,
            )
        )

    for forecast in federated_forecasts:
        cognition = forecast_to_cognition(
            forecast,
            role="FEDERATED_CANDIDATE",
            evidence_roots=evidence_roots,
            available_at_ms=created_at_ms,
        )
        nodes.append(
            add_cognition(
                graph,
                cognition=cognition,
                created_at_ms=created_at_ms,
            )
        )

    return tuple(nodes)


def add_worker_forecasts(
    graph: WorldGraph,
    *,
    worker_forecasts: Sequence[Forecast],
    coalition_forecasts: Sequence[Forecast],
    evidence_roots: Sequence[str],
    created_at_ms: int | None = None,
) -> tuple[WorldGraphNode, ...]:
    """Bind worker and coalition forecasts as proposal-only cognition.

    Raw legacy worker dictionaries never enter the graph directly. Their
    deterministic Phase-2 forecast bridges are the canonical Phase-6 seam.
    """
    nodes: list[WorldGraphNode] = []

    for forecast in worker_forecasts:
        cognition = forecast_to_cognition(
            forecast,
            role="WORKER_PROPOSAL",
            evidence_roots=evidence_roots,
            available_at_ms=created_at_ms,
        )

        nodes.append(
            add_cognition(
                graph,
                cognition=cognition,
                created_at_ms=created_at_ms,
            )
        )

    for forecast in coalition_forecasts:
        cognition = forecast_to_cognition(
            forecast,
            role="WORKER_COALITION",
            evidence_roots=evidence_roots,
            available_at_ms=created_at_ms,
        )

        nodes.append(
            add_cognition(
                graph,
                cognition=cognition,
                created_at_ms=created_at_ms,
            )
        )

    return tuple(nodes)


def add_worker_forecasts(
    graph: WorldGraph,
    *,
    worker_forecasts: Sequence[Forecast],
    coalition_forecasts: Sequence[Forecast],
    evidence_roots: Sequence[str],
    created_at_ms: int | None = None,
) -> tuple[WorldGraphNode, ...]:
    """Bind worker and coalition forecasts as proposal-only cognition.

    Raw legacy worker dictionaries never enter the graph directly. Their
    deterministic Phase-2 forecast bridges are the canonical Phase-6 seam.
    """
    nodes: list[WorldGraphNode] = []

    for forecast in worker_forecasts:
        cognition = forecast_to_cognition(
            forecast,
            role="WORKER_PROPOSAL",
            evidence_roots=evidence_roots,
            available_at_ms=created_at_ms,
        )

        nodes.append(
            add_cognition(
                graph,
                cognition=cognition,
                created_at_ms=created_at_ms,
            )
        )

    for forecast in coalition_forecasts:
        cognition = forecast_to_cognition(
            forecast,
            role="WORKER_COALITION",
            evidence_roots=evidence_roots,
            available_at_ms=created_at_ms,
        )

        nodes.append(
            add_cognition(
                graph,
                cognition=cognition,
                created_at_ms=created_at_ms,
            )
        )

    return tuple(nodes)


def add_specialized_market_context_forecasts(
    graph: WorldGraph,
    *,
    medium_horizon_forecasts: Sequence[Forecast],
    derivatives_trend_forecasts: Sequence[Forecast],
    cex_oracle_forecasts: Sequence[Forecast],
    evidence_roots: Sequence[str],
    created_at_ms: int | None = None,
) -> tuple[WorldGraphNode, ...]:
    """Bind specialized Phoenix market-context models into WorldGraph."""

    nodes: list[WorldGraphNode] = []

    role_sets = (
        ("MEDIUM_HORIZON_TREND", medium_horizon_forecasts),
        ("DERIVATIVES_TREND", derivatives_trend_forecasts),
        ("CEX_MULTI_HORIZON_ORACLE", cex_oracle_forecasts),
    )

    for role, forecasts in role_sets:
        for forecast in forecasts:
            cognition = forecast_to_cognition(
                forecast,
                role=role,
                evidence_roots=evidence_roots,
                available_at_ms=created_at_ms,
            )
            nodes.append(
                add_cognition(
                    graph,
                    cognition=cognition,
                    created_at_ms=created_at_ms,
                )
            )

    return tuple(nodes)


def regime_oracle_to_cognition(
    *,
    oracle: Any,
    frames: Mapping[str, Sequence[Sequence[Any]]],
    observed_at_ms: int,
    evidence_roots: Sequence[str],
    spread_bps: float | None = None,
    available_at_ms: int | None = None,
) -> CognitionNode:
    """Bind deterministic RegimeOracle context into WorldGraph cognition."""

    snapshot = oracle.evaluate_bound_frames(
        {
            str(timeframe): [list(row) for row in rows]
            for timeframe, rows in frames.items()
        },
        observed_at_ms=int(observed_at_ms),
        spread_bps=spread_bps,
    )

    available = int(
        observed_at_ms
        if available_at_ms is None
        else available_at_ms
    )

    return build_cognition(
        role="REGIME_CONTEXT",
        source_id=f"regime_oracle:{oracle.symbol}",
        observed_at_ms=int(observed_at_ms),
        available_at_ms=available,
        evidence_roots=evidence_roots,
        lineage=(
            "hivenance.regime_oracle",
            "bound_frames",
        ),
        transformation_version="regime_oracle.bound_frames.v1",
        payload={
            **snapshot,
            "execution_eligible": False,
            "promotion_eligible": False,
        },
        challenger=True,
        proposal_only=False,
        memory_only=False,
        historical_only=False,
    )


def add_regime_oracle_context(
    graph: WorldGraph,
    *,
    oracle: Any,
    frames: Mapping[str, Sequence[Sequence[Any]]],
    observed_at_ms: int,
    evidence_roots: Sequence[str],
    spread_bps: float | None = None,
    available_at_ms: int | None = None,
) -> WorldGraphNode:
    cognition = regime_oracle_to_cognition(
        oracle=oracle,
        frames=frames,
        observed_at_ms=observed_at_ms,
        evidence_roots=evidence_roots,
        spread_bps=spread_bps,
        available_at_ms=available_at_ms,
    )

    return add_cognition(
        graph,
        cognition=cognition,
        created_at_ms=available_at_ms,
    )


def feature_memory_to_cognition(
    *,
    feature: Any,
    memory_key: str,
    source_id: str,
    evidence_roots: Sequence[str],
    available_at_ms: int | None = None,
) -> CognitionNode | None:
    """Expose existing Phase-2 memory as memory-only cognition.

    The payload is preserved rather than reinterpreted. Missing memory produces
    no node. Memory never becomes evidence, proposal authority, execution
    authority, or promotion authority.
    """
    values = (
        feature.values
        if isinstance(getattr(feature, "values", None), Mapping)
        else {}
    )

    memory = values.get(memory_key)

    if not isinstance(memory, Mapping) or not memory:
        return None

    observed = int(feature.timestamp_ms)
    available = int(
        observed
        if available_at_ms is None
        else available_at_ms
    )

    return build_cognition(
        role="MEMORY_CONTEXT",
        source_id=str(source_id),
        observed_at_ms=observed,
        available_at_ms=available,
        evidence_roots=evidence_roots,
        lineage=(
            "hivenance.phase2.memory",
            str(memory_key),
        ),
        transformation_version=f"{memory_key}.memory_context.v1",
        payload={
            "memory_key": str(memory_key),
            "symbol": str(feature.symbol),
            "timestamp_ms": observed,
            "memory": dict(memory),
            "authority": "research_memory_only",
            "execution_eligible": False,
            "promotion_eligible": False,
        },
        challenger=False,
        proposal_only=False,
        memory_only=True,
        historical_only=True,
    )


def add_phase2_memory_context(
    graph: WorldGraph,
    *,
    feature: Any,
    evidence_roots: Sequence[str],
    available_at_ms: int | None = None,
) -> tuple[WorldGraphNode, ...]:
    """Bind existing regime suppression and worker memory into Queen."""

    specifications = (
        (
            "phase2_regime_suppression",
            "regime_suppression_memory",
        ),
        (
            "phase2_worker_signal_memory",
            "worker_signal_memory",
        ),
    )

    nodes: list[WorldGraphNode] = []

    for memory_key, source_id in specifications:
        cognition = feature_memory_to_cognition(
            feature=feature,
            memory_key=memory_key,
            source_id=source_id,
            evidence_roots=evidence_roots,
            available_at_ms=available_at_ms,
        )

        if cognition is None:
            continue

        nodes.append(
            add_cognition(
                graph,
                cognition=cognition,
                created_at_ms=available_at_ms,
            )
        )

    return tuple(nodes)


def profitability_frontier_to_cognition(
    *,
    feature: Any,
    evidence_roots: Sequence[str],
    available_at_ms: int | None = None,
) -> CognitionNode | None:
    """Expose settled profitability frontier as historical gating cognition."""

    values = (
        feature.values
        if isinstance(getattr(feature, "values", None), Mapping)
        else {}
    )

    frontier = values.get("phase2_profitability_frontier")

    if not isinstance(frontier, Mapping) or not frontier:
        return None

    observed = int(feature.timestamp_ms)
    available = int(
        observed
        if available_at_ms is None
        else available_at_ms
    )

    return build_cognition(
        role="PROFITABILITY_FRONTIER",
        source_id="phase2_profitability_frontier",
        observed_at_ms=observed,
        available_at_ms=available,
        evidence_roots=evidence_roots,
        lineage=(
            "hivenance.hypothesis_swarm",
            "profitability_frontier",
        ),
        transformation_version="phase2_profitability_frontier.context.v1",
        payload={
            "symbol": str(feature.symbol),
            "timestamp_ms": observed,
            "frontier": dict(frontier),
            "authority": "historical_settlement_context_only",
            "execution_eligible": False,
            "promotion_eligible": False,
        },
        challenger=False,
        proposal_only=False,
        memory_only=True,
        historical_only=True,
    )


def add_profitability_frontier_context(
    graph: WorldGraph,
    *,
    feature: Any,
    evidence_roots: Sequence[str],
    available_at_ms: int | None = None,
) -> WorldGraphNode | None:
    cognition = profitability_frontier_to_cognition(
        feature=feature,
        evidence_roots=evidence_roots,
        available_at_ms=available_at_ms,
    )

    if cognition is None:
        return None

    return add_cognition(
        graph,
        cognition=cognition,
        created_at_ms=available_at_ms,
    )


def crystal_row_to_cognition(
    *,
    crystal: Mapping[str, Any],
    role: str,
    observed_at_ms: int,
    evidence_roots: Sequence[str],
    available_at_ms: int | None = None,
) -> CognitionNode:
    if role not in {
        "POSITIVE_THESIS_CRYSTAL",
        "NEGATIVE_CAPABILITY_CRYSTAL",
    }:
        raise ValueError(f"crystal_role_invalid:{role}")

    expected_family = (
        "thesis_capability"
        if role == "POSITIVE_THESIS_CRYSTAL"
        else "negative_capability"
    )

    family = str(crystal.get("crystal_family") or expected_family)

    if family != expected_family:
        raise ValueError(
            f"crystal_family_role_mismatch:{family}:{role}"
        )

    available = int(
        observed_at_ms
        if available_at_ms is None
        else available_at_ms
    )

    crystal_id = str(
        crystal.get("crystal_id")
        or crystal.get("id")
        or crystal.get("learning_id")
        or f"{family}:anonymous"
    )

    return build_cognition(
        role=role,
        source_id=crystal_id,
        observed_at_ms=int(observed_at_ms),
        available_at_ms=available,
        evidence_roots=evidence_roots,
        lineage=(
            "hivenance.crystal_registry",
            family,
        ),
        transformation_version=f"{family}.cognition.v1",
        payload={
            "crystal_family": family,
            "crystal": dict(crystal),
            "authority": "qualified_memory_only",
            "execution_eligible": False,
            "promotion_eligible": False,
        },
        challenger=False,
        proposal_only=False,
        memory_only=True,
        historical_only=True,
    )


def add_crystal_context(
    graph: WorldGraph,
    *,
    thesis_crystals: Sequence[Mapping[str, Any]],
    negative_crystals: Sequence[Mapping[str, Any]],
    observed_at_ms: int,
    evidence_roots: Sequence[str],
    available_at_ms: int | None = None,
) -> tuple[WorldGraphNode, ...]:
    nodes: list[WorldGraphNode] = []

    for crystal in thesis_crystals:
        cognition = crystal_row_to_cognition(
            crystal=crystal,
            role="POSITIVE_THESIS_CRYSTAL",
            observed_at_ms=observed_at_ms,
            evidence_roots=evidence_roots,
            available_at_ms=available_at_ms,
        )
        nodes.append(
            add_cognition(
                graph,
                cognition=cognition,
                created_at_ms=available_at_ms,
            )
        )

    for crystal in negative_crystals:
        cognition = crystal_row_to_cognition(
            crystal=crystal,
            role="NEGATIVE_CAPABILITY_CRYSTAL",
            observed_at_ms=observed_at_ms,
            evidence_roots=evidence_roots,
            available_at_ms=available_at_ms,
        )
        nodes.append(
            add_cognition(
                graph,
                cognition=cognition,
                created_at_ms=available_at_ms,
            )
        )

    return tuple(nodes)


def crystal_memory_summary_to_cognition(
    *,
    feature: Any,
    evidence_roots: Sequence[str],
    available_at_ms: int | None = None,
) -> CognitionNode | None:
    values = (
        feature.values
        if isinstance(getattr(feature, "values", None), Mapping)
        else {}
    )

    memory = values.get("phase2_crystal_memory")

    if not isinstance(memory, Mapping) or not memory:
        return None

    observed = int(feature.timestamp_ms)
    available = int(
        observed
        if available_at_ms is None
        else available_at_ms
    )

    return build_cognition(
        role="MEMORY_CONTEXT",
        source_id="phase2_crystal_memory_summary",
        observed_at_ms=observed,
        available_at_ms=available,
        evidence_roots=evidence_roots,
        lineage=(
            "hivenance.hypothesis_swarm",
            "phase2_crystal_memory",
        ),
        transformation_version="phase2_crystal_memory.summary.v1",
        payload={
            "memory_key": "phase2_crystal_memory",
            "symbol": str(feature.symbol),
            "timestamp_ms": observed,
            "memory": dict(memory),
            "authority": "research_memory_summary_only",
            "execution_eligible": False,
            "promotion_eligible": False,
        },
        challenger=False,
        proposal_only=False,
        memory_only=True,
        historical_only=True,
    )


@dataclass(frozen=True)
class CandidateInfluenceTrace:
    schema: str
    trace_id: str
    world_state_id: str
    conclusion_node_id: str
    influence_node_ids: tuple[str, ...]
    influence_edge_ids: tuple[str, ...]
    influence_families: tuple[str, ...]
    independent_evidence_roots: tuple[str, ...]
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def bind_candidate_influences(
    graph: WorldGraph,
    *,
    conclusion_node: WorldGraphNode,
    influences: Sequence[
        tuple[WorldGraphNode, str]
    ],
) -> CandidateInfluenceTrace:
    """Bind only cognition that actually influenced one conclusion.

    Visibility alone never counts as influence. The caller must explicitly
    nominate each influencing node together with a reason.
    """

    if conclusion_node.node_id not in graph._nodes:
        raise ValueError("influence_conclusion_not_in_graph")

    edge_ids: list[str] = []
    influence_ids: list[str] = []
    families: set[str] = set()
    roots: set[str] = set()

    seen: set[str] = set()

    for node, reason in influences:
        if node.node_id not in graph._nodes:
            raise ValueError("influence_node_not_in_graph")

        if node.world_state_id != conclusion_node.world_state_id:
            raise ValueError("influence_world_state_mismatch")

        if not str(reason).strip():
            raise ValueError("influence_reason_required")

        if node.node_id in seen:
            continue

        seen.add(node.node_id)

        shared_roots = tuple(
            sorted(
                set(node.evidence_roots)
                & set(conclusion_node.evidence_roots)
            )
        )

        edge = graph.add_edge(
            edge_type="INFLUENCES",
            source_node_id=node.node_id,
            target_node_id=conclusion_node.node_id,
            evidence_roots=shared_roots,
            metadata={
                "reason": str(reason),
                "source_family": node.family,
                "target_family": conclusion_node.family,
                "actual_influence": True,
                "authority_effect": "NONE",
            },
        )

        edge_ids.append(edge.edge_id)
        influence_ids.append(node.node_id)
        families.add(node.family)
        roots.update(node.evidence_roots)

    body = {
        "world_state_id": conclusion_node.world_state_id,
        "conclusion_node_id": conclusion_node.node_id,
        "influence_node_ids": sorted(influence_ids),
        "influence_edge_ids": sorted(edge_ids),
    }

    trace_id = "cit_" + _digest(body).split(":", 1)[1][:24]

    return CandidateInfluenceTrace(
        schema="hivenance_candidate_influence_trace_v1",
        trace_id=trace_id,
        world_state_id=conclusion_node.world_state_id,
        conclusion_node_id=conclusion_node.node_id,
        influence_node_ids=tuple(sorted(influence_ids)),
        influence_edge_ids=tuple(sorted(edge_ids)),
        influence_families=tuple(sorted(families)),
        independent_evidence_roots=tuple(sorted(roots)),
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
        promotion_eligible=False,
    )


def candidate_influence_trace(
    graph: WorldGraph,
    *,
    conclusion_node_id: str,
) -> CandidateInfluenceTrace:
    """Reconstruct an operator-readable trace from graph truth."""

    conclusion = graph._nodes.get(conclusion_node_id)

    if conclusion is None:
        raise ValueError("influence_conclusion_not_in_graph")

    edges = [
        edge
        for edge in graph._edges.values()
        if edge.edge_type == "INFLUENCES"
        and edge.target_node_id == conclusion_node_id
        and bool(edge.metadata.get("actual_influence"))
    ]

    nodes = [
        graph._nodes[edge.source_node_id]
        for edge in edges
        if edge.source_node_id in graph._nodes
    ]

    body = {
        "world_state_id": conclusion.world_state_id,
        "conclusion_node_id": conclusion.node_id,
        "influence_node_ids": sorted(
            node.node_id for node in nodes
        ),
        "influence_edge_ids": sorted(
            edge.edge_id for edge in edges
        ),
    }

    return CandidateInfluenceTrace(
        schema="hivenance_candidate_influence_trace_v1",
        trace_id="cit_" + _digest(body).split(":", 1)[1][:24],
        world_state_id=conclusion.world_state_id,
        conclusion_node_id=conclusion.node_id,
        influence_node_ids=tuple(
            sorted(node.node_id for node in nodes)
        ),
        influence_edge_ids=tuple(
            sorted(edge.edge_id for edge in edges)
        ),
        influence_families=tuple(
            sorted({node.family for node in nodes})
        ),
        independent_evidence_roots=tuple(
            sorted({
                root
                for node in nodes
                for root in node.evidence_roots
            })
        ),
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
        promotion_eligible=False,
    )
