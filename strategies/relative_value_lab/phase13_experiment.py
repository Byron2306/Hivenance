from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .historical_causal_prosecution import PAIRED_MASKS, ADVERSARIAL_ATTACKS


def _digest(value: Any) -> str:
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")
    return "sha256:"+hashlib.sha256(raw).hexdigest()


PHASE13_REQUIRED_BOOKS=(
    "FULL_HIVE_FROZEN",
    "ADAPTIVE_HIVE",
    "PHOENIX_ONLY",
    "CEX_ORACLE_ONLY",
    "SIMPLE_MOMENTUM",
    "SIMPLE_REVERSION",
    "DETERMINISTIC_RANDOM",
    "NO_TRADE",
)

PHASE13_REQUIRED_HORIZONS_SECONDS=(300,900,3600,14400,86400)


@dataclass(frozen=True)
class Phase13ExperimentFreeze:
    schema: str
    freeze_id: str
    books: tuple[str,...]
    horizons_seconds: tuple[int,...]
    paired_masks: tuple[str,...]
    adversarial_attacks: tuple[str,...]
    organ_roster: tuple[str,...]
    model_roster: tuple[str,...]
    queen_epoch_rules_digest: str
    recurrence_bound: int
    comparison_rules_digest: str
    cost_model_digest: str
    multiplicity_method: str
    minimum_samples: int
    minimum_distinct_market_worlds: int
    adaptive_book_can_change_modes: bool
    frozen_book_can_change_modes: bool
    execution_eligible: bool=False
    promotion_eligible: bool=False

    def __post_init__(self)->None:
        if tuple(self.books)!=PHASE13_REQUIRED_BOOKS:
            raise ValueError("phase13_books_not_frozen")
        if tuple(self.horizons_seconds)!=PHASE13_REQUIRED_HORIZONS_SECONDS:
            raise ValueError("phase13_horizons_not_frozen")
        if tuple(self.paired_masks)!=PAIRED_MASKS:
            raise ValueError("phase13_mask_roster_not_frozen")
        if tuple(self.adversarial_attacks)!=ADVERSARIAL_ATTACKS:
            raise ValueError("phase13_attack_roster_not_frozen")
        if self.frozen_book_can_change_modes:
            raise ValueError("phase13_frozen_book_mode_mutation_forbidden")
        if not self.adaptive_book_can_change_modes:
            raise ValueError("phase13_adaptive_book_must_allow_mode_changes")
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("phase13_authority_escalation_forbidden")

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


def build_phase13_freeze(
    *,
    organ_roster: Sequence[str],
    model_roster: Sequence[str],
    queen_epoch_rules: Mapping[str,Any],
    recurrence_bound: int,
    comparison_rules: Mapping[str,Any],
    cost_model: Mapping[str,Any],
    minimum_samples: int=30,
    minimum_distinct_market_worlds: int=20,
    multiplicity_method: str="HOLM_BONFERRONI",
)->Phase13ExperimentFreeze:
    body={
        "books":PHASE13_REQUIRED_BOOKS,
        "horizons_seconds":PHASE13_REQUIRED_HORIZONS_SECONDS,
        "paired_masks":PAIRED_MASKS,
        "adversarial_attacks":ADVERSARIAL_ATTACKS,
        "organ_roster":tuple(sorted({str(x) for x in organ_roster})),
        "model_roster":tuple(sorted({str(x) for x in model_roster})),
        "queen_epoch_rules_digest":_digest(dict(queen_epoch_rules)),
        "recurrence_bound":int(recurrence_bound),
        "comparison_rules_digest":_digest(dict(comparison_rules)),
        "cost_model_digest":_digest(dict(cost_model)),
        "multiplicity_method":str(multiplicity_method),
        "minimum_samples":int(minimum_samples),
        "minimum_distinct_market_worlds":int(minimum_distinct_market_worlds),
        "adaptive_book_can_change_modes":True,
        "frozen_book_can_change_modes":False,
    }
    return Phase13ExperimentFreeze(
        schema="hivenance_phase13_experiment_freeze_v1",
        freeze_id="p13f_"+_digest(body).split(":",1)[1][:24],
        **body,
        execution_eligible=False,
        promotion_eligible=False,
    )
