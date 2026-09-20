from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .learning_applicability import (
    LearningApplicability,
    applicability_from_receipt,
)


def _digest(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _scope_key(
    applicability: LearningApplicability,
) -> tuple[Any, ...]:
    return (
        applicability.model_id,
        applicability.symbol,
        applicability.horizon_seconds,
        applicability.forecast_id,
        applicability.hypothesis_family,
        applicability.direction,
        applicability.regime,
    )


@dataclass(frozen=True)
class SupersessionRecord:
    older_learning_id: str
    newer_learning_id: str
    scope_key: tuple[Any, ...]
    older_settled_at_ms: int
    newer_settled_at_ms: int


@dataclass(frozen=True)
class LearningSupersessionReceipt:
    schema: str
    receipt_id: str
    records: tuple[SupersessionRecord, ...]
    superseded_learning_ids: tuple[str, ...]
    surviving_learning_ids: tuple[str, ...]
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_learning_supersession(
    receipts: Sequence[Mapping[str, Any]],
) -> LearningSupersessionReceipt:
    """Newest settled item wins only within the exact same applicability scope."""

    parsed = []

    for receipt in receipts:
        learning_id = str(
            receipt.get("learning_id") or ""
        )

        if not learning_id:
            raise ValueError(
                "learning_supersession_missing_learning_id"
            )

        applicability = applicability_from_receipt(
            receipt
        )

        if applicability.settled_at_ms is None:
            raise ValueError(
                "learning_supersession_requires_settled_at"
            )

        parsed.append(
            (
                learning_id,
                applicability,
                int(applicability.settled_at_ms),
            )
        )

    grouped: dict[
        tuple[Any, ...],
        list[tuple[str, LearningApplicability, int]],
    ] = {}

    for row in parsed:
        grouped.setdefault(
            _scope_key(row[1]),
            [],
        ).append(row)

    records: list[SupersessionRecord] = []
    survivors: set[str] = set()
    superseded: set[str] = set()

    for scope, rows in grouped.items():
        ordered = sorted(
            rows,
            key=lambda row: (
                row[2],
                row[0],
            ),
        )

        newest = ordered[-1]
        survivors.add(newest[0])

        for older in ordered[:-1]:
            superseded.add(older[0])

            records.append(
                SupersessionRecord(
                    older_learning_id=older[0],
                    newer_learning_id=newest[0],
                    scope_key=scope,
                    older_settled_at_ms=older[2],
                    newer_settled_at_ms=newest[2],
                )
            )

    body = {
        "records": [
            asdict(row)
            for row in records
        ],
        "superseded": sorted(superseded),
        "survivors": sorted(survivors),
    }

    return LearningSupersessionReceipt(
        schema=(
            "hivenance_learning_supersession_v1"
        ),
        receipt_id=(
            "lsup_"
            + _digest(body).split(":", 1)[1][:24]
        ),
        records=tuple(records),
        superseded_learning_ids=tuple(
            sorted(superseded)
        ),
        surviving_learning_ids=tuple(
            sorted(survivors)
        ),
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
        promotion_eligible=False,
    )
