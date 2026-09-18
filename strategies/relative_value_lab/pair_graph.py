from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any, Mapping, Sequence

from .contracts import PairRelationshipCrystal, RELATIVE_VALUE_AUTHORITY
from .pair_lab import PairDiagnostics, PairRelationshipLab


@dataclass(frozen=True)
class PairGraphEdge:
    pair_id: str
    symbol_a: str
    symbol_b: str
    stability_score: float
    eligible: bool
    half_life_seconds: float | None
    spread_zscore: float | None
    direct_route_available: bool
    rejection_reasons: tuple[str,...]
    authority: str=RELATIVE_VALUE_AUTHORITY


class RelativeValueGraph:
    """Build a research graph across every unique pair in a synchronized basket."""

    def __init__(self,lab: PairRelationshipLab | None=None) -> None:
        self.lab=lab or PairRelationshipLab()

    def analyze_basket(
        self,
        *,
        prices: Mapping[str,Sequence[Any]],
        sample_interval_sec: float,
        venue: str="unknown",
        observed_at_ms: int=0,
        direct_routes: set[frozenset[str]] | None=None,
    ) -> tuple[list[PairGraphEdge],dict[str,PairRelationshipCrystal],dict[str,PairDiagnostics]]:
        routes=direct_routes or set()
        edges=[]
        crystals={}
        diagnostics={}
        for symbol_a,symbol_b in combinations(sorted(prices),2):
            direct=frozenset((symbol_a,symbol_b)) in routes
            diag,crystal=self.lab.analyze(
                symbol_a=symbol_a,
                symbol_b=symbol_b,
                prices_a=prices[symbol_a],
                prices_b=prices[symbol_b],
                sample_interval_sec=sample_interval_sec,
                venue=venue,
                observed_at_ms=observed_at_ms,
                direct_route_available=direct,
            )
            diagnostics[diag.pair_id]=diag
            crystals[crystal.pair_id]=crystal
            edges.append(PairGraphEdge(
                pair_id=diag.pair_id,
                symbol_a=symbol_a,
                symbol_b=symbol_b,
                stability_score=diag.stability_score,
                eligible=diag.eligible,
                half_life_seconds=diag.half_life_seconds,
                spread_zscore=diag.spread_zscore,
                direct_route_available=direct,
                rejection_reasons=diag.rejection_reasons,
            ))
        edges.sort(key=lambda e:(e.eligible,e.stability_score),reverse=True)
        return edges,crystals,diagnostics
