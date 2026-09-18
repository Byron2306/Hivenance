from .pair_lab import PairDiagnostics, PairRelationshipLab
from .pair_graph import PairGraphEdge, RelativeValueGraph
from .forecast import OUMeanReversionForecaster, OUForecastConfig
from .research_council import LocalOllamaResearchCouncil
from .harmonic_governance import (
    HarmonicForecastGovernance,
    HarmonicGovernanceConfig,
    HarmonicForecastReceipt,
    HarmonicForecastVoice,
    HarmonicSpectrum,
)
from .harmony_law import (
    HarmonyBeeMessage,
    HarmonyLaw,
    HarmonyLawConfig,
    HarmonyLawDecision,
    HarmonyChorusDecision,
    horizon_band,
    make_message_id,
)
from .waggle_protocol import (
    BeeLineage,
    LineageRegistry,
    WaggleProtocol,
    WaggleReceipt,
    WaggleChorusSnapshot,
)
from .musical_cognition import (
    MotifNote,
    MotifScore,
    MusicalCognitionConfig,
    MusicalMotifAccumulator,
)
from .polyphonic_entrainment import (
    BandEntrainment,
    EntrainmentReceipt,
    EntrainmentConfig,
    PolyphonicEntrainment,
)
from .dataset import RelativeValueDatasetBuilder, RelativeValueExample, DatasetBuildSummary
from .evaluation import (
    ExpandingRidgeModel,
    RelativeValueWalkForwardEvaluator,
    WalkForwardPrediction,
    ModelMetrics,
)
from .settlement import ProspectiveForecastSettler, SettledRelativeForecast
"""Phoenix Relative-Value Laboratory.

Research-only package for pair structure, forward relative-return forecasting,
microstructure evidence, and bounded advisory inference.
"""

from .microstructure import MicrostructureSnapshot, SequentialMicrostructureEngine
from .contracts import (
    PairRelationshipCrystal,
    RelativeMarketState,
    ForwardRelativeForecast,
    ResearchCouncilReceipt,
    RELATIVE_VALUE_AUTHORITY,
)

__all__ = [
    "PairRelationshipCrystal",
    "RelativeMarketState",
    "ForwardRelativeForecast",
    "ResearchCouncilReceipt",
    "RELATIVE_VALUE_AUTHORITY",
    "MicrostructureSnapshot",
    "SequentialMicrostructureEngine",
    "PairDiagnostics",
    "PairRelationshipLab",
    "PairGraphEdge",
    "RelativeValueGraph",
    "OUMeanReversionForecaster",
    "OUForecastConfig",
    "LocalOllamaResearchCouncil",
    "HarmonicForecastGovernance",
    "HarmonicGovernanceConfig",
    "HarmonicForecastReceipt",
    "HarmonicForecastVoice",
    "HarmonicSpectrum",
    "HarmonyBeeMessage",
    "HarmonyLaw",
    "HarmonyLawConfig",
    "HarmonyLawDecision",
    "HarmonyChorusDecision",
    "horizon_band",
    "make_message_id",
    "BeeLineage",
    "LineageRegistry",
    "WaggleProtocol",
    "WaggleReceipt",
    "WaggleChorusSnapshot",
    "MotifNote",
    "MotifScore",
    "MusicalCognitionConfig",
    "MusicalMotifAccumulator",
    "BandEntrainment",
    "EntrainmentReceipt",
    "EntrainmentConfig",
    "PolyphonicEntrainment",
    "RelativeValueDatasetBuilder",
    "RelativeValueExample",
    "DatasetBuildSummary",
    "ExpandingRidgeModel",
    "RelativeValueWalkForwardEvaluator",
    "WalkForwardPrediction",
    "ModelMetrics",
    "ProspectiveForecastSettler",
    "SettledRelativeForecast",
]