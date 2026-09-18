from .pair_lab import PairDiagnostics, PairRelationshipLab
from .pair_graph import PairGraphEdge, RelativeValueGraph
from .forecast import OUMeanReversionForecaster, OUForecastConfig
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
]