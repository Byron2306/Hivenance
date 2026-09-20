from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class OrganTopology:
    organ_id: str
    layer: str
    responsibility: str
    consumes: tuple[str, ...]
    emits: tuple[str, ...]
    allowed_influence: tuple[str, ...]
    forbidden_authority: tuple[str, ...]
    disposition: str
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ORGANS: tuple[OrganTopology, ...] = (
    OrganTopology(
        "feature_engine", "OBSERVATION",
        "derive deterministic market features from timestamped public data",
        ("PUBLIC_MARKET_DATA",), ("FEATURE_VECTOR", "DETERMINISTIC_REGIME_HINT"),
        ("RESEARCH_CONTEXT", "HYPOTHESIS_LAYER"),
        ("EXECUTION", "PROMOTION", "LEARNING_AUTHORITY"),
        "RETAIN_CANONICAL",
    ),
    OrganTopology(
        "external_statistics_sensorium", "OBSERVATION",
        "capture timestamped external crypto/macro statistics with source custody",
        ("EXTERNAL_PUBLIC_DATA",), ("EXTERNAL_STATISTICS",),
        ("STATISTICS_BEE", "RESEARCH_CONTEXT"),
        ("EXECUTION", "PROMOTION", "RETROACTIVE_HISTORY_REWRITE"),
        "RETAIN_CANONICAL",
    ),
    OrganTopology(
        "statistics_bee", "STATISTICS",
        "maintain point-in-time sufficient statistics over settled evidence",
        ("SETTLED_OUTCOMES", "EXTERNAL_STATISTICS"), ("STATISTICAL_SYNTHESIS",),
        ("SYNTHESIS_BEE", "HYPOTHESIS_LAYER", "ML_CHALLENGER", "QUEEN"),
        ("EXECUTION", "PROMOTION", "DIRECTION_ORIGINATION"),
        "RETAIN_CANONICAL",
    ),
    OrganTopology(
        "bayesian_regime_filter", "STATISTICS",
        "maintain posterior market-regime state and transition pressure",
        ("FEATURE_VECTOR", "STATISTICAL_SYNTHESIS"), ("REGIME_CONTEXT",),
        ("RESEARCH_CONTEXT", "HYPOTHESIS_LAYER", "ML_CHALLENGER", "QUEEN"),
        ("EXECUTION", "PROMOTION"),
        "MERGE_WITH_DETERMINISTIC_REGIME_CONTEXT",
    ),
    OrganTopology(
        "stochastic_calibration", "STATISTICS",
        "maintain volatility, conformal coverage, calibration, and drift state",
        ("FORECASTS", "SETTLED_OUTCOMES", "FEATURE_VECTOR"), ("CALIBRATION_CONTEXT",),
        ("ML_CHALLENGER", "SYNTHESIS_BEE", "QUEEN"),
        ("EXECUTION", "PROMOTION", "ALPHA_ORIGINATION"),
        "RETAIN_CANONICAL",
    ),
    OrganTopology(
        "research_context", "CONTEXT",
        "publish one sealed point-in-time context packet to all research organs",
        ("OBSERVATION", "STATISTICS", "REGIME", "LEARNING", "CRYSTALS", "EXTERNAL", "CALIBRATION"),
        ("RESEARCH_CONTEXT",),
        ("HYPOTHESIS_LAYER", "WORKERS", "ML_CHALLENGER", "QUEEN"),
        ("EXECUTION", "PROMOTION", "WORLD_MUTATION"),
        "RETAIN_CANONICAL_BUS",
    ),
    OrganTopology(
        "hypothesis_competition", "HYPOTHESIS",
        "run independent research hypotheses and baselines on the same context",
        ("FEATURE_VECTOR", "RESEARCH_CONTEXT"), ("FORECAST_CANDIDATES",),
        ("LEARNING_GATE", "STATISTICS_GATE", "QUEEN"),
        ("EXECUTION", "PROMOTION"),
        "RETAIN_CANONICAL",
    ),
    OrganTopology(
        "strategy_workers", "HYPOTHESIS",
        "provide diverse deterministic strategy voices such as RSI/SMA/breakout/momentum",
        ("WORKER_SERIES", "RESEARCH_CONTEXT"), ("WORKER_FORECASTS",),
        ("HYPOTHESIS_COMPETITION", "WORKER_COALITION"),
        ("EXECUTION", "PROMOTION", "DIRECT_QUEEN_OVERRIDE"),
        "RETAIN_SPECIALIST_VOICES",
    ),
    OrganTopology(
        "worker_coalition", "HYPOTHESIS",
        "aggregate worker disagreement as a research challenger/veto voice",
        ("WORKER_FORECASTS", "RESEARCH_CONTEXT"), ("COALITION_FORECAST",),
        ("HYPOTHESIS_COMPETITION", "QUEEN"),
        ("EXECUTION", "PROMOTION", "ALPHA_MONOPOLY"),
        "RETAIN_AS_CHALLENGER",
    ),
    OrganTopology(
        "coin_selector", "SELECTION",
        "rank and freeze candidate universe before outcome knowledge exists",
        ("OBSERVATION", "RESEARCH_CONTEXT"), ("FROZEN_SELECTION_COHORT",),
        ("HYPOTHESIS_LAYER", "SELECTION_REGRET"),
        ("EXECUTION", "PROMOTION", "POST_SELECTION_RERANK"),
        "RETAIN_PRE_HYPOTHESIS",
    ),
    OrganTopology(
        "learning_memory", "LEARNING",
        "store qualified settled learning receipts and applicability metadata",
        ("SETTLED_OUTCOMES", "CAUSAL_ABLATIONS"), ("LEARNING_CONTEXT",),
        ("SYNTHESIS_BEE", "HYPOTHESIS_LAYER", "CRYSTALS", "QUEEN"),
        ("EXECUTION", "PROMOTION", "OBSERVED_TRUTH_MUTATION"),
        "RETAIN_CANONICAL_MEMORY",
    ),
    OrganTopology(
        "crystals", "LEARNING",
        "store stabilized reusable abstractions after recurrence and transfer tests",
        ("LEARNING_CONTEXT", "TRANSFER_TESTS"), ("CRYSTAL_CONTEXT",),
        ("RESEARCH_CONTEXT", "QUEEN"),
        ("EXECUTION", "PROMOTION_WITHOUT_GATE", "RAW_HISTORY_REWRITE"),
        "RETAIN_DOWNSTREAM_OF_LEARNING",
    ),
    OrganTopology(
        "ml_challenger", "ML",
        "provide provenance-bound probabilistic dissent with calibration and drift health",
        ("RESEARCH_CONTEXT", "MODEL_ARTIFACT", "CALIBRATION_CONTEXT"), ("LEARNED_CHALLENGER",),
        ("QUEEN", "HYPOTHESIS_VETO"),
        ("EXECUTION", "PROMOTION", "SOLE_DECISION_AUTHORITY"),
        "RETAIN_CHALLENGER",
    ),
    OrganTopology(
        "metatron_anomaly", "ML",
        "detect novel or unusual feature constellations",
        ("FEATURE_VECTOR", "RESEARCH_CONTEXT"), ("NOVELTY_STATE",),
        ("ML_CHALLENGER", "SYNTHESIS_BEE", "QUEEN"),
        ("EXECUTION", "PROMOTION", "DIRECTION_ORIGINATION"),
        "RETAIN_ANOMALY_SPECIALIST",
    ),
    OrganTopology(
        "market_hunting", "RESEARCH",
        "detect motifs worthy of further testing and create research attention",
        ("WORLD_GRAPH", "RESEARCH_CONTEXT"), ("RESEARCH_MOTIFS",),
        ("QUEEN", "RESEARCH_OBLIGATIONS"),
        ("EXECUTION", "PROMOTION", "ALPHA_CLAIM"),
        "RETAIN_RESEARCH_GENERATOR",
    ),
    OrganTopology(
        "colony_correlation", "RESEARCH",
        "link cross-time/pair events while explicitly withholding causal claims",
        ("EVENTS",), ("CORRELATION_RECEIPTS",),
        ("MARKET_HUNTING", "CAUSAL_CASCADE", "QUEEN"),
        ("EXECUTION", "PROMOTION", "CAUSAL_CLAIM"),
        "RETAIN_DISCOVERY_ONLY",
    ),
    OrganTopology(
        "causal_cascade", "RESEARCH",
        "test explicit mechanism-bound propagation links",
        ("EVENTS", "MECHANISM_EVIDENCE"), ("CASCADE_RECEIPTS",),
        ("QUEEN", "LEARNING"),
        ("EXECUTION", "PROMOTION", "PHILOSOPHICAL_CAUSAL_PROOF"),
        "RETAIN_MECHANISM_LAYER",
    ),
    OrganTopology(
        "mystique", "FALSIFICATION",
        "challenge observed interpretations in synthetic counterfactual worlds",
        ("QUEEN_SCORE",), ("FALSIFICATION_RECEIPT",),
        ("QUEEN", "LEARNING"),
        ("EXECUTION", "PROMOTION", "SYNTHETIC_TO_OBSERVED_CONTAMINATION"),
        "RETAIN_FALSIFIER",
    ),
    OrganTopology(
        "polyphonic_quorum", "GOVERNANCE",
        "measure provenance-diverse coordinated participation, not majority vote",
        ("MOTIF_NOTES",), ("QUORUM_RECEIPT",),
        ("QUEEN", "POLLEN"),
        ("EXECUTION", "PROMOTION", "DIRECTIONAL_MAJORITY_RULE"),
        "RETAIN_GOVERNANCE_HEALTH",
    ),
    OrganTopology(
        "pollen_economy", "META_LEARNING",
        "score information contribution and reputation after prospective settlement",
        ("CLAIMS", "SETTLED_OUTCOMES", "QUORUM_RECEIPTS"), ("REPUTATION_STATE",),
        ("RESEARCH_PRIORITIZATION", "QUEEN"),
        ("EXECUTION", "PROMOTION", "DIRECT_DIRECTIONAL_WEIGHT"),
        "RETAIN_META_LEARNING_ONLY",
    ),
    OrganTopology(
        "cognitive_metabolism", "META_COGNITION",
        "measure cognition cost, context burn, and information efficiency",
        ("COGNITION_EVENTS",), ("METABOLIC_STATE",),
        ("QUEEN", "RECURSIVE_QUEEN"),
        ("EXECUTION", "PROMOTION", "DIRECTION_ORIGINATION"),
        "RETAIN_COST_GOVERNOR",
    ),
    OrganTopology(
        "vns_temporal_texture", "TRANSPORT_HEALTH",
        "measure cadence, timing, sequence and nervous-system transport quality",
        ("VNS_EVENTS",), ("TEMPORAL_CONTEXT",),
        ("QUEEN", "QUORUM", "SYNTHESIS_BEE"),
        ("EXECUTION", "PROMOTION", "ALPHA_ORIGINATION"),
        "RETAIN_TRANSPORT_HEALTH",
    ),
    OrganTopology(
        "recursive_queen", "META_COGNITION",
        "request bounded refresh/challenge/compare work without mutating observed truth",
        ("QUEEN_RECEIPT", "WORLD_GRAPH"), ("RESEARCH_REQUESTS",),
        ("MYSTIQUE", "COMPARISON", "INDEPENDENT_CORROBORATION"),
        ("EXECUTION", "PROMOTION", "UNBOUNDED_RECURSION"),
        "RETAIN_BOUNDED",
    ),
    OrganTopology(
        "conducting_queen", "GOVERNANCE",
        "integrate research voices and emit bounded notation/veto decisions",
        ("QUEEN_INPUT_ASSEMBLY", "RESEARCH_CONTEXT"), ("QUEEN_RECEIPT", "RESEARCH_NOTATION"),
        ("HYPOTHESIS_VETO", "RESEARCH_REQUESTS"),
        ("DIRECT_ORDER_EXECUTION", "SELF_PROMOTION", "WORLD_MUTATION"),
        "RETAIN_FINAL_RESEARCH_CONDUCTOR",
    ),
    OrganTopology(
        "execution_canary_growth", "EXECUTION",
        "downstream execution, canary and controlled growth after independent gates",
        ("PROMOTED_CANDIDATE", "RISK_GATES", "HUMAN/GOVERNANCE_AUTHORITY"), ("EXECUTION_RECEIPTS",),
        ("SETTLEMENT", "LEARNING"),
        ("UNGATED_EXECUTION", "LEARNING_TO_EXECUTION_SHORTCUT"),
        "KEEP_LOCKED_DOWNSTREAM",
    ),
)


def topology_by_id() -> dict[str, OrganTopology]:
    return {organ.organ_id: organ for organ in ORGANS}


def validate_topology() -> None:
    ids = [organ.organ_id for organ in ORGANS]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate_organ_topology_id")
    for organ in ORGANS:
        if organ.execution_eligible or organ.promotion_eligible:
            raise ValueError("organ_topology_authority_escalation:" + organ.organ_id)
        if not organ.responsibility or not organ.layer:
            raise ValueError("organ_topology_incomplete:" + organ.organ_id)
