"""Hivenance Ember Sleeve research package, Phoenix Phases 1 through 5.

Keep package import lightweight. Heavy orchestration classes are resolved lazily
so leaf contracts such as models.py can be imported without recursively loading
HypothesisCompetition and its cross-package adapters.
"""

from .candidate_selector import ObservationOnlyCandidateSelector
from .cost_model import CostEstimate, ResearchCostModel
from .feature_engine import Phase1FeatureEngine
from .execution_engine import DeterministicExecutionSimulator
from .execution_lab import ExecutionLabAgent
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


_LAZY_EXPORTS = {
    "HypothesisCompetition": (".hypothesis_competition", "HypothesisCompetition"),
    "HypothesisSwarmAgent": (".hypothesis_swarm", "HypothesisSwarmAgent"),
}


def __getattr__(name):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attr_name = target
    from importlib import import_module
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


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
