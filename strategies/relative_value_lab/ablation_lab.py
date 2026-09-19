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
class AblationReport:
    schema: str
    report_id: str
    settled_count: int
    books: tuple[VariantBook, ...]
    organ_findings: tuple[OrganUtilityFinding, ...] = ()
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
            "authority": self.authority,
            "execution_eligible": self.execution_eligible,
            "promotion_eligible": self.promotion_eligible,
        }


VARIANTS: tuple[AblationVariant, ...] = (
    AblationVariant("CONTROL_ALL", "Every candidate forecast enters.", "control"),
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
)


def admit(variant_id: str, s: AblationSnapshot) -> bool:
    vid = str(variant_id).upper()

    if vid == "CONTROL_ALL":
        return True
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
    if vid == "POLLEN_PRESENT":
        return s.queen_resolution == "ADMIT_RESOLVED" and s.pollen_bounty_count > 0
    if vid == "DISSENT_BOUNTY_ONLY":
        return s.pollen_dissent_bounty
    if vid == "REP_STRUCT_GE_MOTION":
        return s.queen_resolution == "ADMIT_RESOLVED" and s.structural_reputation >= s.motion_reputation
    if vid == "REP_MOTION_GE_STRUCT":
        return s.queen_resolution == "ADMIT_RESOLVED" and s.motion_reputation >= s.structural_reputation

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
        return VariantBook(
            variant_id=variant_id,
            selected_count=len(values),
            rejected_count=max(0, settled_count - len(values)),
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
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )