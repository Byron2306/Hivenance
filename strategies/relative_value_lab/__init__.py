"""Phoenix Relative-Value Laboratory.

Research-only package for pair structure, forward relative-return forecasting,
microstructure evidence, and bounded advisory inference.
"""

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
]
