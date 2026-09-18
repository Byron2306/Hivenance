"""Hivenance Ember Sleeve research package, Phoenix Phases 1 through 5."""

from .candidate_selector import ObservationOnlyCandidateSelector
from .cost_model import CostEstimate, ResearchCostModel
from .feature_engine import Phase1FeatureEngine
from .execution_engine import DeterministicExecutionSimulator
from .execution_lab import ExecutionLabAgent
from .hypothesis_competition import HypothesisCompetition
from .hypothesis_swarm import HypothesisSwarmAgent
from .models import (
    CandidateObservation,
    FeatureVector,
    Forecast,
    HypothesisRunSummary,
    ObservationRunSummary,
)
from .observation_swarm import ObservationSwarmAgent
from .signal_model import ObservationOnlySignalModel
from .shadow_flight import ShadowIntentBuilder, ShadowSettlementEngine, build_freeze_from_phase4
from .shadow_lab import ShadowFlightAgent

__all__ = [
    "CandidateObservation",
    "CostEstimate",
    "FeatureVector",
    "DeterministicExecutionSimulator",
    "ExecutionLabAgent",
    "Forecast",
    "HypothesisCompetition",
    "HypothesisRunSummary",
    "HypothesisSwarmAgent",
    "ObservationRunSummary",
    "ObservationOnlyCandidateSelector",
    "Phase1FeatureEngine",
    "ObservationOnlySignalModel",
    "ObservationSwarmAgent",
    "ResearchCostModel",
    "ShadowFlightAgent",
    "ShadowIntentBuilder",
    "ShadowSettlementEngine",
    "build_freeze_from_phase4",
]
