from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class Phase14BookResult:
    book_id: str
    settled_n: int
    distinct_worlds: int
    mean_net_bps: float | None
    median_net_bps: float | None
    ci95_low_bps: float | None
    ci95_high_bps: float | None
    max_drawdown_bps: float | None
    positive_worlds: int
    negative_worlds: int
    classification: str

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


def _drawdown(values: Sequence[float])->float|None:
    if not values:
        return None
    equity=0.0
    peak=0.0
    worst=0.0
    for value in values:
        equity+=float(value)
        peak=max(peak,equity)
        worst=min(worst,equity-peak)
    return worst


def summarize_book(
    *,
    book_id: str,
    realized_net_bps: Sequence[float],
    world_ids: Sequence[str],
    minimum_samples: int,
    minimum_distinct_market_worlds: int,
)->Phase14BookResult:
    values=[float(x) for x in realized_net_bps]
    distinct=len(set(str(x) for x in world_ids))
    n=len(values)
    mean_value=statistics.mean(values) if values else None
    median_value=statistics.median(values) if values else None
    if len(values)>=2:
        se=statistics.stdev(values)/math.sqrt(len(values))
        lo=float(mean_value)-1.96*se
        hi=float(mean_value)+1.96*se
    else:
        lo=hi=None

    if n<int(minimum_samples) or distinct<int(minimum_distinct_market_worlds):
        classification="INSUFFICIENT_EVIDENCE"
    elif lo is not None and lo>0:
        classification="PROSPECTIVELY_USEFUL_CANDIDATE"
    elif hi is not None and hi<0:
        classification="NOT_USEFUL_ON_TESTED_DOMAIN"
    else:
        classification="PROSPECTIVELY_MIXED_OR_UNRESOLVED"

    return Phase14BookResult(
        book_id=str(book_id),
        settled_n=n,
        distinct_worlds=distinct,
        mean_net_bps=mean_value,
        median_net_bps=median_value,
        ci95_low_bps=lo,
        ci95_high_bps=hi,
        max_drawdown_bps=_drawdown(values),
        positive_worlds=sum(1 for x in values if x>0),
        negative_worlds=sum(1 for x in values if x<0),
        classification=classification,
    )


def validate_phase14_input(
    *,
    expected_freeze_id: str,
    receipt_freeze_ids: Sequence[str],
)->None:
    ids={str(x) for x in receipt_freeze_ids if str(x)}
    if ids!={str(expected_freeze_id)}:
        raise ValueError("phase14_freeze_mismatch")
