from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .settlement import SettledRelativeForecast


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class AblationSnapshot:
    """Frozen time-t feature receipt used by all mutation policies."""

    forecast_id: str
    pair_id: str
    forecast_timestamp_ms: int
    expected_net_bps: float
    expected_cost_bps: float
    stability_score: float
    quorum_formed: bool
    ensemble_lock: float
    explicit_dissent: bool
    motion_kind: str
    motion_bps: float
    queen_resolution: str
    pollen_bounty_count: int
    pollen_dissent_bounty: bool
    structural_reputation: float
    motion_reputation: float
    motif_consonance: float
    motif_dissonance: float
    motif_tension: float
    motif_cadence_strength: float
    motif_counterpoint_diversity: float
    entrainment_strength: float
    false_unison_risk: float
    queen_polyphonic_pressure: float
    queen_tonal_coherence: float
    queen_timbral_diversity: float
    queen_pitch_convergence: float
    queen_subtle_shift: float
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AblationVariant:
    variant_id: str
    description: str
    family: str


@dataclass(frozen=True)
class VariantBook:
    variant_id: str
    selected_count: int
    rejected_count: int
    selection_rate: float
    degenerate_select_none: bool
    degenerate_select_all: bool
    winning_count: int
    losing_count: int
    cumulative_net_bps: float
    mean_net_bps: float
    median_net_bps: float
    win_rate: float
    current_positive_streak: int
    longest_positive_streak: int
    max_drawdown_bps: float


@dataclass(frozen=True)
class AblationDelta:
    variant_id: str
    baseline_id: str
    changed_decisions: int
    baseline_only_count: int
    variant_only_count: int
    cumulative_net_delta_bps: float
    mean_net_delta_bps: float


@dataclass(frozen=True)
class AblationFinding:
    variant_id: str
    family: str
    changed_decisions: int
    cumulative_net_delta_bps: float
    status: str
    interpretation: str


@dataclass(frozen=True)
class OrganUtilityFinding:
    organ_id: str
    ablation_variant_id: str
    changed_decisions: int
    cumulative_net_delta_bps: float
    utility_status: str
    interpretation: str


@dataclass(frozen=True)
class VariantStability:
    variant_id: str
    selected_count: int
    first_half_net_bps: float
    second_half_net_bps: float
    first_half_selected: int
    second_half_selected: int
    positive_pair_count: int
    negative_pair_count: int
    zero_pair_count: int
    best_pair_id: str | None
    best_pair_net_bps: float
    worst_pair_id: str | None
    worst_pair_net_bps: float
    net_without_best_pair_bps: float
    survives_best_pair_removal: bool
    both_halves_positive: bool


@dataclass(frozen=True)
class SelectorEquivalenceClass:
    class_id: str
    variant_ids: tuple[str, ...]
    selected_count: int
    selection_rate: float
    decision_digest: str


@dataclass(frozen=True)
class AblationReplayCase:
    forecast_id: str
    pair_id: str
    net_bps: float
    snapshot: Mapping[str, Any]


@dataclass(frozen=True)
class AblationReport:
    schema: str
    report_id: str
    settled_count: int
    books: tuple[VariantBook, ...]
    organ_findings: tuple[OrganUtilityFinding, ...] = ()
    selector_equivalence_classes: tuple[SelectorEquivalenceClass, ...] = ()
    variant_stability: tuple[VariantStability, ...] = ()
    replay_cases: tuple[AblationReplayCase, ...] = ()
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "report_id": self.report_id,
            "settled_count": self.settled_count,
            "books": [asdict(book) for book in self.books],
            "organ_findings": [asdict(item) for item in self.organ_findings],
            "selector_equivalence_classes": [
                asdict(item) for item in self.selector_equivalence_classes
            ],
            "variant_stability": [asdict(item) for item in self.variant_stability],
            "replay_cases": [asdict(item) for item in self.replay_cases],
            "authority": self.authority,
            "execution_eligible": self.execution_eligible,
            "promotion_eligible": self.promotion_eligible,
        }


VARIANTS: tuple[AblationVariant, ...] = (
    AblationVariant("CONTROL_ALL", "Every candidate forecast enters.", "control"),
    AblationVariant("REJECT_ALL", "No candidate forecast enters.", "negative_control"),
    AblationVariant("FULL_HIVE", "Canonical Queen treatment resolution.", "canonical"),
    AblationVariant("NO_QUORUM_GATE", "Ignore quorum; hold only explicit dissent.", "quorum_ablation"),
    AblationVariant("NO_COUNTERPOINT_HOLD", "Quorum admits even with dissent.", "counterpoint_ablation"),
    AblationVariant("NO_QUEEN", "Quorum formation alone admits.", "queen_ablation"),
    AblationVariant("STRUCTURAL_ONLY", "Ignore motion voice and admit structural forecast.", "voice_ablation"),
    AblationVariant("MOTION_FOLLOW_ONLY", "Require motion voice to follow structural direction.", "voice_selection"),
    AblationVariant("MOTION_DISSENT_ONLY", "Admit only when motion voice dissents.", "contrarian"),
    AblationVariant("INVERT_MOTION", "Deliberately treat dissent as confirmation.", "negative_control"),
    AblationVariant("NO_POLLEN", "Same Queen resolution, no bounty requirement.", "pollen_ablation"),
    AblationVariant("POLLEN_PRESENT", "Require at least one Queen-issued bounty.", "pollen_selection"),
    AblationVariant("DISSENT_BOUNTY_ONLY", "Require Queen to issue a dissent bounty.", "pollen_selection"),
    AblationVariant("NO_REPUTATION", "Canonical resolution without historical reputation.", "reputation_ablation"),
    AblationVariant("POLLEN_AND_REPUTATION", "Require canonical resolution, pollen presence and structural reputation >= motion reputation.", "interaction"),
    AblationVariant("QUORUM_PLUS_FOLLOW", "Require quorum and motion FOLLOW, bypass Queen resolution label.", "interaction"),
    AblationVariant("QUORUM_PLUS_EDGE1", "Require quorum, no dissent and expected net edge >= 1 bps.", "interaction"),
    AblationVariant("QUORUM_PLUS_EDGE2", "Require quorum, no dissent and expected net edge >= 2 bps.", "interaction"),
    AblationVariant("FOLLOW_PLUS_EDGE1", "Require motion FOLLOW and expected net edge >= 1 bps.", "interaction"),
    AblationVariant("FOLLOW_PLUS_STABILITY060", "Require motion FOLLOW and stability >= 0.60.", "interaction"),
    AblationVariant("FOLLOW_PLUS_LOW_COST_1", "Require FOLLOW and expected cost <= 1 bps.", "cost_interaction"),
    AblationVariant("FOLLOW_PLUS_LOW_COST_2", "Require FOLLOW and expected cost <= 2 bps.", "cost_interaction"),
    AblationVariant("FOLLOW_EDGE_COST_RATIO_1", "Require FOLLOW and expected edge >= expected cost.", "cost_interaction"),
    AblationVariant("FOLLOW_EDGE_COST_RATIO_2", "Require FOLLOW and expected edge >= 2x expected cost.", "cost_interaction"),
    AblationVariant("FOLLOW_MOTION_GE_EDGE", "Require FOLLOW and |motion| >= expected net edge.", "motion_interaction"),
    AblationVariant("FOLLOW_MOTION_GE_2X_EDGE", "Require FOLLOW and |motion| >= 2x expected net edge.", "motion_interaction"),
    AblationVariant("QUEEN_METRICS_COMPOSITE", "Require strong Queen pressure/tonal/pitch composite.", "interaction"),
    AblationVariant("MUSIC_COMPOSITE", "Require cadence/entrainment with low dissonance and false-unison.", "interaction"),
    AblationVariant("REP_STRUCT_GE_MOTION", "Admit only if structural reputation >= motion reputation.", "reputation_selection"),
    AblationVariant("REP_MOTION_GE_STRUCT", "Admit only if motion reputation >= structural reputation.", "reputation_selection"),
    AblationVariant("EDGE_GT_0", "Any positive expected post-cost edge.", "edge_threshold"),
    AblationVariant("EDGE_GT_1", "Expected post-cost edge >= 1 bps.", "edge_threshold"),
    AblationVariant("EDGE_GT_2", "Expected post-cost edge >= 2 bps.", "edge_threshold"),
    AblationVariant("EDGE_GT_3", "Expected post-cost edge >= 3 bps.", "edge_threshold"),
    AblationVariant("STABILITY_GT_050", "Relationship stability >= 0.50.", "stability_threshold"),
    AblationVariant("STABILITY_GT_060", "Relationship stability >= 0.60.", "stability_threshold"),
    AblationVariant("STABILITY_GT_070", "Relationship stability >= 0.70.", "stability_threshold"),
    AblationVariant("LOCK_GT_060", "Ensemble lock >= 0.60 and no dissent.", "lock_threshold"),
    AblationVariant("LOCK_GT_075", "Ensemble lock >= 0.75 and no dissent.", "lock_threshold"),
    AblationVariant("LOCK_GT_090", "Ensemble lock >= 0.90 and no dissent.", "lock_threshold"),
    AblationVariant("DISSENT_WEAK_HOLD", "Hold dissent only if |motion| >= 0.5 bps.", "dissent_strength"),
    AblationVariant("DISSENT_MEDIUM_HOLD", "Hold dissent only if |motion| >= 1.0 bps.", "dissent_strength"),
    AblationVariant("DISSENT_STRONG_HOLD", "Hold dissent only if |motion| >= 2.0 bps.", "dissent_strength"),
    AblationVariant("FOLLOW_STRONG_ONLY", "Require FOLLOW with |motion| >= 1 bps.", "motion_strength"),
    AblationVariant("FOLLOW_VERY_STRONG_ONLY", "Require FOLLOW with |motion| >= 2 bps.", "motion_strength"),
    AblationVariant("HASH_25", "Deterministic 25% data-blind selector.", "negative_control"),
    AblationVariant("HASH_50", "Deterministic 50% data-blind selector.", "negative_control"),
    AblationVariant("HASH_75", "Deterministic 75% data-blind selector.", "negative_control"),
    AblationVariant("QUEEN_PRESSURE_GT_040", "Queen polyphonic pressure >= 0.40.", "queen_metric"),
    AblationVariant("QUEEN_PRESSURE_GT_055", "Queen polyphonic pressure >= 0.55.", "queen_metric"),
    AblationVariant("QUEEN_TONAL_GT_050", "Queen tonal coherence >= 0.50.", "queen_metric"),
    AblationVariant("QUEEN_PITCH_GT_050", "Queen pitch convergence >= 0.50.", "queen_metric"),
    AblationVariant("CADENCE_GT_050", "Motif cadence strength >= 0.50.", "motif_metric"),
    AblationVariant("CADENCE_GT_065", "Motif cadence strength >= 0.65.", "motif_metric"),
    AblationVariant("DISSONANCE_LT_025", "Motif dissonance < 0.25.", "motif_metric"),
    AblationVariant("TENSION_LT_025", "Motif tension < 0.25.", "motif_metric"),
    AblationVariant("COUNTERPOINT_GT_040", "Counterpoint diversity >= 0.40.", "motif_metric"),
    AblationVariant("ENTRAINMENT_GT_040", "Entrainment >= 0.40.", "entrainment_metric"),
    AblationVariant("ENTRAINMENT_GT_060", "Entrainment >= 0.60.", "entrainment_metric"),
    AblationVariant("FALSE_UNISON_LT_025", "False-unison risk < 0.25.", "entrainment_metric"),

    # Frozen after v4 discovery, intended for prospective v5 confirmation.
    AblationVariant("LOW_COST_050", "Expected cost <= 0.50 bps, independent of motion.", "confirmatory_cost"),
    AblationVariant("LOW_COST_075", "Expected cost <= 0.75 bps, independent of motion.", "confirmatory_cost"),
    AblationVariant("LOW_COST_100", "Expected cost <= 1.00 bps, independent of motion.", "confirmatory_cost"),
    AblationVariant("LOW_COST_125", "Expected cost <= 1.25 bps, independent of motion.", "confirmatory_cost"),
    AblationVariant("FOLLOW_LOW_COST_050", "FOLLOW with expected cost <= 0.50 bps.", "confirmatory_follow_cost"),
    AblationVariant("FOLLOW_LOW_COST_075", "FOLLOW with expected cost <= 0.75 bps.", "confirmatory_follow_cost"),
    AblationVariant("FOLLOW_LOW_COST_100", "FOLLOW with expected cost <= 1.00 bps.", "confirmatory_follow_cost"),
    AblationVariant("FOLLOW_LOW_COST_125", "FOLLOW with expected cost <= 1.25 bps.", "confirmatory_follow_cost"),
    AblationVariant("FOLLOW_LOW_COST_150", "FOLLOW with expected cost <= 1.50 bps.", "confirmatory_follow_cost"),
    AblationVariant("DISSENT_LOW_COST_100", "DISSENT with expected cost <= 1.00 bps.", "confirmatory_negative_control"),
    AblationVariant("FOLLOW_LOW_COST_100_EDGE050", "FOLLOW, cost <= 1 bps, expected net >= 0.5 bps.", "confirmatory_interaction"),
    AblationVariant("FOLLOW_LOW_COST_100_EDGE100", "FOLLOW, cost <= 1 bps, expected net >= 1.0 bps.", "confirmatory_interaction"),
    AblationVariant("FOLLOW_LOW_COST_100_EDGE150", "FOLLOW, cost <= 1 bps, expected net >= 1.5 bps.", "confirmatory_interaction"),
    AblationVariant("FOLLOW_LOW_COST_100_STAB055", "FOLLOW, cost <= 1 bps, stability >= .55.", "confirmatory_interaction"),
    AblationVariant("FOLLOW_LOW_COST_100_STAB065", "FOLLOW, cost <= 1 bps, stability >= .65.", "confirmatory_interaction"),
    AblationVariant("FOLLOW_LOW_COST_100_MOTION050", "FOLLOW, cost <= 1 bps, |motion| >= .5 bps.", "confirmatory_interaction"),
    AblationVariant("FOLLOW_LOW_COST_100_MOTION100", "FOLLOW, cost <= 1 bps, |motion| >= 1 bps.", "confirmatory_interaction"),
    AblationVariant("FOLLOW_LOW_COST_100_MOTION200", "FOLLOW, cost <= 1 bps, |motion| >= 2 bps.", "confirmatory_interaction"),
)


CONFIRMATORY_V5_VARIANTS: tuple[str, ...] = (
    "CONTROL_ALL",
    "REJECT_ALL",
    "FULL_HIVE",
    "MOTION_FOLLOW_ONLY",
    "LOW_COST_050",
    "LOW_COST_075",
    "LOW_COST_100",
    "LOW_COST_125",
    "FOLLOW_LOW_COST_050",
    "FOLLOW_LOW_COST_075",
    "FOLLOW_LOW_COST_100",
    "FOLLOW_LOW_COST_125",
    "FOLLOW_LOW_COST_150",
    "DISSENT_LOW_COST_100",
    "FOLLOW_LOW_COST_100_EDGE050",
    "FOLLOW_LOW_COST_100_EDGE100",
    "FOLLOW_LOW_COST_100_EDGE150",
    "FOLLOW_LOW_COST_100_STAB055",
    "FOLLOW_LOW_COST_100_STAB065",
    "FOLLOW_LOW_COST_100_MOTION050",
    "FOLLOW_LOW_COST_100_MOTION100",
    "FOLLOW_LOW_COST_100_MOTION200",
    "HASH_25",
    "HASH_50",
)


def admit(variant_id: str, s: AblationSnapshot) -> bool:
    vid = str(variant_id).upper()

    if vid == "CONTROL_ALL":
        return True
    if vid == "REJECT_ALL":
        return False
    if vid == "FULL_HIVE":
        return s.queen_resolution == "ADMIT_RESOLVED"
    if vid == "NO_QUORUM_GATE":
        return not s.explicit_dissent
    if vid in {"NO_COUNTERPOINT_HOLD", "NO_QUEEN"}:
        return s.quorum_formed
    if vid == "STRUCTURAL_ONLY":
        return True
    if vid == "MOTION_FOLLOW_ONLY":
        return s.motion_kind == "FOLLOW"
    if vid in {"MOTION_DISSENT_ONLY", "INVERT_MOTION"}:
        return s.motion_kind == "DISSENT"
    if vid in {"NO_POLLEN", "NO_REPUTATION"}:
        return s.queen_resolution == "ADMIT_RESOLVED"
    if vid == "POLLEN_AND_REPUTATION":
        return (
            s.queen_resolution == "ADMIT_RESOLVED"
            and s.pollen_bounty_count > 0
            and s.structural_reputation >= s.motion_reputation
        )
    if vid == "QUORUM_PLUS_FOLLOW":
        return s.quorum_formed and s.motion_kind == "FOLLOW"
    if vid == "QUORUM_PLUS_EDGE1":
        return s.quorum_formed and not s.explicit_dissent and s.expected_net_bps >= 1.0
    if vid == "QUORUM_PLUS_EDGE2":
        return s.quorum_formed and not s.explicit_dissent and s.expected_net_bps >= 2.0
    if vid == "FOLLOW_PLUS_EDGE1":
        return s.motion_kind == "FOLLOW" and s.expected_net_bps >= 1.0
    if vid == "FOLLOW_PLUS_STABILITY060":
        return s.motion_kind == "FOLLOW" and s.stability_score >= 0.60
    if vid == "FOLLOW_PLUS_LOW_COST_1":
        return s.motion_kind == "FOLLOW" and s.expected_cost_bps <= 1.0
    if vid == "FOLLOW_PLUS_LOW_COST_2":
        return s.motion_kind == "FOLLOW" and s.expected_cost_bps <= 2.0
    if vid == "FOLLOW_EDGE_COST_RATIO_1":
        return s.motion_kind == "FOLLOW" and s.expected_net_bps >= s.expected_cost_bps
    if vid == "FOLLOW_EDGE_COST_RATIO_2":
        return s.motion_kind == "FOLLOW" and s.expected_net_bps >= 2.0 * s.expected_cost_bps
    if vid == "FOLLOW_MOTION_GE_EDGE":
        return s.motion_kind == "FOLLOW" and abs(s.motion_bps) >= max(0.0, s.expected_net_bps)
    if vid == "FOLLOW_MOTION_GE_2X_EDGE":
        return s.motion_kind == "FOLLOW" and abs(s.motion_bps) >= 2.0 * max(0.0, s.expected_net_bps)
    if vid == "QUEEN_METRICS_COMPOSITE":
        return (
            s.queen_polyphonic_pressure >= 0.55
            and s.queen_tonal_coherence >= 0.50
            and s.queen_pitch_convergence >= 0.50
        )
    if vid == "MUSIC_COMPOSITE":
        return (
            s.motif_cadence_strength >= 0.60
            and s.entrainment_strength >= 0.50
            and s.motif_dissonance < 0.30
            and s.false_unison_risk < 0.30
        )
    if vid == "POLLEN_PRESENT":
        return s.queen_resolution == "ADMIT_RESOLVED" and s.pollen_bounty_count > 0
    if vid == "DISSENT_BOUNTY_ONLY":
        return s.pollen_dissent_bounty
    if vid == "REP_STRUCT_GE_MOTION":
        return s.queen_resolution == "ADMIT_RESOLVED" and s.structural_reputation >= s.motion_reputation
    if vid == "REP_MOTION_GE_STRUCT":
        return s.queen_resolution == "ADMIT_RESOLVED" and s.motion_reputation >= s.structural_reputation

    if vid.startswith("LOW_COST_"):
        threshold = float(vid.rsplit("_", 1)[1]) / 100.0
        return s.expected_cost_bps <= threshold
    if vid.startswith("FOLLOW_LOW_COST_"):
        parts = vid.split("_")
        # FOLLOW_LOW_COST_<cost hundredths>[_EDGE<threshold>|_STAB<threshold>|_MOTION<threshold>]
        # Accept both EDGE100 and EDGE_100 spellings without positional assumptions.
        if len(parts) < 4 or not parts[3]:
            raise KeyError(f"malformed_follow_low_cost_variant:{variant_id}")
        try:
            cost_threshold = float(parts[3]) / 100.0
        except ValueError as exc:
            raise KeyError(f"malformed_follow_low_cost_cost:{variant_id}") from exc

        if s.motion_kind != "FOLLOW" or s.expected_cost_bps > cost_threshold:
            return False
        if len(parts) == 4:
            return True

        suffix = "_".join(parts[4:])
        for qualifier, value in (
            ("EDGE", s.expected_net_bps),
            ("STAB", s.stability_score),
            ("MOTION", abs(s.motion_bps)),
        ):
            if suffix.startswith(qualifier):
                raw = suffix[len(qualifier):].lstrip("_")
                if not raw:
                    raise KeyError(f"malformed_follow_low_cost_qualifier:{variant_id}")
                try:
                    threshold = float(raw) / 100.0
                except ValueError as exc:
                    raise KeyError(f"malformed_follow_low_cost_threshold:{variant_id}") from exc
                return value >= threshold

        raise KeyError(f"unknown_follow_low_cost_qualifier:{variant_id}")
    if vid == "DISSENT_LOW_COST_100":
        return s.motion_kind == "DISSENT" and s.expected_cost_bps <= 1.0

    if vid.startswith("EDGE_GT_"):
        threshold = float(vid.rsplit("_", 1)[1])
        return s.expected_net_bps >= threshold

    if vid.startswith("STABILITY_GT_"):
        raw = vid.rsplit("_", 1)[1]
        threshold = float(raw) / 100.0
        return s.stability_score >= threshold

    if vid.startswith("LOCK_GT_"):
        raw = vid.rsplit("_", 1)[1]
        threshold = float(raw) / 100.0
        return s.quorum_formed and not s.explicit_dissent and s.ensemble_lock >= threshold

    if vid == "DISSENT_WEAK_HOLD":
        return not (s.explicit_dissent and abs(s.motion_bps) >= 0.5)
    if vid == "DISSENT_MEDIUM_HOLD":
        return not (s.explicit_dissent and abs(s.motion_bps) >= 1.0)
    if vid == "DISSENT_STRONG_HOLD":
        return not (s.explicit_dissent and abs(s.motion_bps) >= 2.0)
    if vid == "FOLLOW_STRONG_ONLY":
        return s.motion_kind == "FOLLOW" and abs(s.motion_bps) >= 1.0
    if vid == "FOLLOW_VERY_STRONG_ONLY":
        return s.motion_kind == "FOLLOW" and abs(s.motion_bps) >= 2.0
    if vid.startswith("HASH_"):
        pct = int(vid.rsplit("_", 1)[1])
        bucket = int(hashlib.sha256(s.forecast_id.encode("utf-8")).hexdigest()[:8], 16) % 100
        return bucket < pct
    if vid.startswith("QUEEN_PRESSURE_GT_"):
        return s.queen_polyphonic_pressure >= float(vid.rsplit("_",1)[1]) / 100.0
    if vid.startswith("QUEEN_TONAL_GT_"):
        return s.queen_tonal_coherence >= float(vid.rsplit("_",1)[1]) / 100.0
    if vid.startswith("QUEEN_PITCH_GT_"):
        return s.queen_pitch_convergence >= float(vid.rsplit("_",1)[1]) / 100.0
    if vid.startswith("CADENCE_GT_"):
        return s.motif_cadence_strength >= float(vid.rsplit("_",1)[1]) / 100.0
    if vid.startswith("DISSONANCE_LT_"):
        return s.motif_dissonance < float(vid.rsplit("_",1)[1]) / 100.0
    if vid.startswith("TENSION_LT_"):
        return s.motif_tension < float(vid.rsplit("_",1)[1]) / 100.0
    if vid.startswith("COUNTERPOINT_GT_"):
        return s.motif_counterpoint_diversity >= float(vid.rsplit("_",1)[1]) / 100.0
    if vid.startswith("ENTRAINMENT_GT_"):
        return s.entrainment_strength >= float(vid.rsplit("_",1)[1]) / 100.0
    if vid.startswith("FALSE_UNISON_LT_"):
        return s.false_unison_risk < float(vid.rsplit("_",1)[1]) / 100.0

    raise KeyError(f"unknown_ablation_variant:{variant_id}")


@dataclass(frozen=True)
class _SettledRow:
    forecast_id: str
    pair_id: str
    net_bps: float
    decisions: Mapping[str, bool]


class RelativeValueAblationLab:
    """Run many prospective mutation policies over one shared settlement stream."""

    version = "hivenance.relative_value_ablation_lab.v1"

    def __init__(self, variants: Sequence[AblationVariant] = VARIANTS) -> None:
        self.variants = tuple(variants)
        self._snapshots: dict[str, AblationSnapshot] = {}
        self._rows: list[_SettledRow] = []
        self._seen: set[str] = set()

    def freeze(self, snapshot: AblationSnapshot) -> None:
        if snapshot.forecast_id in self._snapshots:
            raise ValueError("ablation_forecast_already_frozen")
        self._snapshots[snapshot.forecast_id] = snapshot

    def settle(self, settlement: SettledRelativeForecast) -> None:
        if settlement.forecast_id in self._seen:
            raise ValueError("ablation_forecast_already_settled")
        self._seen.add(settlement.forecast_id)
        if settlement.abstain or settlement.realized_directional_net_bps is None:
            return
        snapshot = self._snapshots.get(settlement.forecast_id)
        if snapshot is None:
            raise ValueError("ablation_snapshot_missing")
        decisions = {
            variant.variant_id: admit(variant.variant_id, snapshot)
            for variant in self.variants
        }
        self._rows.append(_SettledRow(
            forecast_id=settlement.forecast_id,
            pair_id=settlement.pair_id,
            net_bps=float(settlement.realized_directional_net_bps),
            decisions=decisions,
        ))

    @staticmethod
    def _book(variant_id: str, rows: Sequence[float], settled_count: int) -> VariantBook:
        values = [float(v) for v in rows]
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        current = 0
        longest = 0
        for value in values:
            equity += value
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
            if value > 0:
                current += 1
                longest = max(longest, current)
            else:
                current = 0
        wins = sum(v > 0 for v in values)
        selected_count = len(values)
        return VariantBook(
            variant_id=variant_id,
            selected_count=selected_count,
            rejected_count=max(0, settled_count - selected_count),
            selection_rate=round(selected_count / settled_count, 6) if settled_count else 0.0,
            degenerate_select_none=(settled_count > 0 and selected_count == 0),
            degenerate_select_all=(settled_count > 0 and selected_count == settled_count),
            winning_count=wins,
            losing_count=len(values) - wins,
            cumulative_net_bps=round(sum(values), 6),
            mean_net_bps=round(statistics.fmean(values), 6) if values else 0.0,
            median_net_bps=round(statistics.median(values), 6) if values else 0.0,
            win_rate=round(wins / len(values), 6) if values else 0.0,
            current_positive_streak=current,
            longest_positive_streak=longest,
            max_drawdown_bps=round(max_dd, 6),
        )

    def deltas(self, baseline_id: str = "FULL_HIVE") -> tuple[AblationDelta, ...]:
        out = []
        for variant in self.variants:
            if variant.variant_id == baseline_id:
                continue
            changed = 0
            base_only = []
            variant_only = []
            for row in self._rows:
                base = bool(row.decisions.get(baseline_id, False))
                alt = bool(row.decisions.get(variant.variant_id, False))
                if base == alt:
                    continue
                changed += 1
                if base:
                    base_only.append(row.net_bps)
                else:
                    variant_only.append(row.net_bps)
            delta = sum(variant_only) - sum(base_only)
            changed_values = variant_only + [-v for v in base_only]
            out.append(AblationDelta(
                variant_id=variant.variant_id,
                baseline_id=baseline_id,
                changed_decisions=changed,
                baseline_only_count=len(base_only),
                variant_only_count=len(variant_only),
                cumulative_net_delta_bps=round(delta, 6),
                mean_net_delta_bps=round(statistics.fmean(changed_values), 6) if changed_values else 0.0,
            ))
        return tuple(out)

    def findings(
        self,
        *,
        baseline_id: str = "FULL_HIVE",
        minimum_changed_cases: int = 5,
    ) -> tuple[AblationFinding, ...]:
        variants = {variant.variant_id: variant for variant in self.variants}
        out = []
        for delta in self.deltas(baseline_id=baseline_id):
            variant = variants[delta.variant_id]
            if delta.changed_decisions == 0:
                status = "NO_OBSERVED_SELECTION_EFFECT"
                interpretation = (
                    "Removing or mutating this component did not change any "
                    "treatment admissions in the observed sample."
                )
            elif delta.changed_decisions < int(minimum_changed_cases):
                status = "INSUFFICIENT_CHANGED_CASES"
                interpretation = (
                    "The mutation changed admissions, but too few changed cases "
                    "have settled for a useful directional conclusion."
                )
            elif delta.cumulative_net_delta_bps > 0:
                status = "REMOVAL_IMPROVED_THIS_SAMPLE"
                interpretation = (
                    "The mutated policy produced higher cumulative net bps than "
                    "FULL_HIVE over decisions that differed in this sample."
                )
            elif delta.cumulative_net_delta_bps < 0:
                status = "REMOVAL_HURT_THIS_SAMPLE"
                interpretation = (
                    "The mutated policy produced lower cumulative net bps than "
                    "FULL_HIVE over decisions that differed in this sample."
                )
            else:
                status = "NO_NET_DIFFERENCE_THIS_SAMPLE"
                interpretation = (
                    "The mutation changed admissions but produced no cumulative "
                    "net difference in this sample."
                )
            out.append(AblationFinding(
                variant_id=delta.variant_id,
                family=variant.family,
                changed_decisions=delta.changed_decisions,
                cumulative_net_delta_bps=delta.cumulative_net_delta_bps,
                status=status,
                interpretation=interpretation,
            ))
        return tuple(out)


    def variant_stability(self) -> tuple[VariantStability, ...]:
        """Expose temporal and pair concentration of each selector's result."""
        out = []
        midpoint = len(self._rows) // 2
        for variant in self.variants:
            selected = [
                (index, row)
                for index, row in enumerate(self._rows)
                if row.decisions.get(variant.variant_id, False)
            ]
            first = [row.net_bps for index, row in selected if index < midpoint]
            second = [row.net_bps for index, row in selected if index >= midpoint]

            by_pair: dict[str, float] = {}
            for _, row in selected:
                by_pair[row.pair_id] = by_pair.get(row.pair_id, 0.0) + row.net_bps

            ordered_pairs = sorted(by_pair.items(), key=lambda item: (item[1], item[0]))
            worst_pair_id = ordered_pairs[0][0] if ordered_pairs else None
            worst_pair_net = ordered_pairs[0][1] if ordered_pairs else 0.0
            best_pair_id = ordered_pairs[-1][0] if ordered_pairs else None
            best_pair_net = ordered_pairs[-1][1] if ordered_pairs else 0.0
            total = sum(row.net_bps for _, row in selected)
            without_best = total - best_pair_net if ordered_pairs else total

            out.append(VariantStability(
                variant_id=variant.variant_id,
                selected_count=len(selected),
                first_half_net_bps=round(sum(first), 6),
                second_half_net_bps=round(sum(second), 6),
                first_half_selected=len(first),
                second_half_selected=len(second),
                positive_pair_count=sum(value > 0 for value in by_pair.values()),
                negative_pair_count=sum(value < 0 for value in by_pair.values()),
                zero_pair_count=sum(value == 0 for value in by_pair.values()),
                best_pair_id=best_pair_id,
                best_pair_net_bps=round(best_pair_net, 6),
                worst_pair_id=worst_pair_id,
                worst_pair_net_bps=round(worst_pair_net, 6),
                net_without_best_pair_bps=round(without_best, 6),
                survives_best_pair_removal=(without_best > 0),
                both_halves_positive=(sum(first) > 0 and sum(second) > 0),
            ))
        return tuple(out)

    def selector_equivalence_classes(self) -> tuple[SelectorEquivalenceClass, ...]:
        """Group policies that made exactly the same admissions over settled cases.

        This exposes architectural aliases: two differently named organs/policies
        that always select the same rows have no distinguishable selection effect
        in the observed sample.
        """
        groups: dict[str, list[str]] = {}
        metadata: dict[str, tuple[int, float]] = {}
        settled = len(self._rows)
        for variant in self.variants:
            vector = [
                bool(row.decisions.get(variant.variant_id, False))
                for row in self._rows
            ]
            digest = _digest(vector)
            groups.setdefault(digest, []).append(variant.variant_id)
            selected = sum(vector)
            metadata[digest] = (
                selected,
                selected / settled if settled else 0.0,
            )

        out = []
        for index, digest in enumerate(sorted(groups)):
            selected, rate = metadata[digest]
            out.append(SelectorEquivalenceClass(
                class_id=f"selector_eq_{index+1:03d}",
                variant_ids=tuple(sorted(groups[digest])),
                selected_count=selected,
                selection_rate=round(rate, 6),
                decision_digest=digest,
            ))
        return tuple(out)

    def organ_findings(
        self,
        *,
        minimum_changed_cases: int = 8,
    ) -> tuple[OrganUtilityFinding, ...]:
        """Translate policy ablations into conservative organ-utility findings.

        ZERO_SELECTION_EFFECT means the organ currently does not change canonical
        treatment admissions at all. It does not mean the organ has no audit,
        safety, observability, or future research value.
        """
        mapping = (
            ("quorum_gate", "NO_QUORUM_GATE"),
            ("counterpoint_hold", "NO_COUNTERPOINT_HOLD"),
            ("queen_resolution", "NO_QUEEN"),
            ("motion_voice", "STRUCTURAL_ONLY"),
            ("pollen_bounties", "NO_POLLEN"),
            ("reputation", "NO_REPUTATION"),
        )
        deltas = {row.variant_id: row for row in self.deltas()}
        out = []
        for organ_id, variant_id in mapping:
            delta = deltas[variant_id]
            if delta.changed_decisions == 0:
                status = "ZERO_SELECTION_EFFECT"
                interpretation = (
                    "Removing this organ did not change any canonical treatment "
                    "admissions in the observed sample. Treat it as selection-dead "
                    "weight until a future path demonstrates incremental value."
                )
            elif delta.changed_decisions < int(minimum_changed_cases):
                status = "UNRESOLVED_TOO_FEW_CHANGED_CASES"
                interpretation = (
                    "This organ changes admissions, but too few differing cases "
                    "have settled to judge whether the added complexity helps."
                )
            elif delta.cumulative_net_delta_bps > 0:
                status = "HARMFUL_CANDIDATE_THIS_SAMPLE"
                interpretation = (
                    "Removing this organ improved cumulative net bps over the "
                    "cases where its presence changed admission."
                )
            elif delta.cumulative_net_delta_bps < 0:
                status = "USEFUL_CANDIDATE_THIS_SAMPLE"
                interpretation = (
                    "Removing this organ hurt cumulative net bps over the cases "
                    "where its presence changed admission."
                )
            else:
                status = "NO_NET_VALUE_THIS_SAMPLE"
                interpretation = (
                    "The organ changes admissions but produced zero cumulative "
                    "incremental net value over those changed cases."
                )
            out.append(OrganUtilityFinding(
                organ_id=organ_id,
                ablation_variant_id=variant_id,
                changed_decisions=delta.changed_decisions,
                cumulative_net_delta_bps=delta.cumulative_net_delta_bps,
                utility_status=status,
                interpretation=interpretation,
            ))
        return tuple(out)

    def replay_cases(self) -> tuple[AblationReplayCase, ...]:
        """Persist frozen time-t features beside future settlement outcome.

        This makes the prospective sample reusable for later offline mutation
        policies without re-reading future information into the snapshots.
        """
        out = []
        for row in self._rows:
            snapshot = self._snapshots.get(row.forecast_id)
            if snapshot is None:
                continue
            out.append(AblationReplayCase(
                forecast_id=row.forecast_id,
                pair_id=row.pair_id,
                net_bps=round(float(row.net_bps), 6),
                snapshot=snapshot.to_dict(),
            ))
        return tuple(out)

    def report(self) -> AblationReport:
        settled_count = len(self._rows)
        books = []
        for variant in self.variants:
            values = [
                row.net_bps
                for row in self._rows
                if row.decisions.get(variant.variant_id, False)
            ]
            books.append(self._book(variant.variant_id, values, settled_count))
        body = {
            "forecasts": [row.forecast_id for row in self._rows],
            "books": [asdict(book) for book in books],
        }
        return AblationReport(
            schema="hivenance_relative_value_ablation_report_v1",
            report_id="ablate_" + _digest(body).split(":", 1)[1][:24],
            settled_count=settled_count,
            books=tuple(books),
            organ_findings=self.organ_findings(),
            selector_equivalence_classes=self.selector_equivalence_classes(),
            variant_stability=self.variant_stability(),
            replay_cases=self.replay_cases(),
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )