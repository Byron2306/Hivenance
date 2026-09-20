from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .historical_causal_prosecution import PAIRED_MASKS
from .historical_middle_mask_bridge import EXECUTABLE_MIDDLE_MASKS
from .historical_synthesis_mask_bridge import EXECUTABLE_SYNTHESIS_MASKS
from .historical_upper_cognition_mask_bridge import EXECUTABLE_UPPER_MASKS


@dataclass(frozen=True)
class HistoricalMaskRoute:
    mask_id: str
    domains: tuple[str,...]

    @property
    def executable(self)->bool:
        return bool(self.domains)


def mask_route(mask_id:str)->HistoricalMaskRoute:
    mask_id=str(mask_id).upper()
    if mask_id not in PAIRED_MASKS:
        raise ValueError("unknown_historical_mask:"+mask_id)
    domains=[]
    if mask_id in EXECUTABLE_MIDDLE_MASKS:
        domains.append("MIDDLE")
    if mask_id in EXECUTABLE_SYNTHESIS_MASKS:
        domains.append("SYNTHESIS")
    if mask_id in EXECUTABLE_UPPER_MASKS:
        domains.append("UPPER")
    return HistoricalMaskRoute(mask_id,tuple(domains))


def full_mask_coverage()->dict[str,Any]:
    routes={mask:mask_route(mask) for mask in PAIRED_MASKS}
    missing=tuple(mask for mask,row in routes.items() if not row.executable)
    return {
        "schema":"hivenance_phase12_mask_route_coverage_v1",
        "routes":{mask:row.domains for mask,row in routes.items()},
        "missing_masks":missing,
        "all_masks_have_executable_route":not missing,
        "execution_eligible":False,
        "promotion_eligible":False,
    }
