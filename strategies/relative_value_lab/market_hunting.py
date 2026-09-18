from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY


def _digest(payload: Any) -> str:
    raw=json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")
    return "sha256:"+hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class HuntObservation:
    observation_id: str
    timestamp_ms: int
    scope: str
    pair_id: Optional[str]=None
    asset_ids: tuple[str,...]=()
    venue: Optional[str]=None
    family: Optional[str]=None
    features: Mapping[str,float]=field(default_factory=dict)
    evidence_root: str=""
    world_state_id: str=""
    world_state_hash: str=""

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


@dataclass(frozen=True)
class MotifHuntRule:
    rule_id: str
    motif_name: str
    required_features: tuple[str,...]
    output_message_type: str
    research_priority: float
    falsification_note: str
    false_positive_notes: tuple[str,...]=()
    scope_class: str="pair"

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


@dataclass(frozen=True)
class MotifHuntMatch:
    schema: str
    match_id: str
    rule_id: str
    motif_name: str
    observation_ids: tuple[str,...]
    scope: str
    output_message_type: str
    research_priority: float
    evidence_roots: tuple[str,...]
    world_state_id: str
    rationale: tuple[str,...]
    falsification_note: str
    authority: str=RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool=False
    promotion_eligible: bool=False

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


class MotifHunter:
    """Deterministic proactive motif hunter.

    Hunt matches direct research attention. They do not choose market direction,
    promote models, or grant execution authority.
    """

    version="hivenance.motif_hunter.v1"

    def __init__(self,rules:Sequence[MotifHuntRule]|None=None)->None:
        self.rules=tuple(rules or self.default_rules())

    @staticmethod
    def default_rules()->tuple[MotifHuntRule,...]:
        return (
            MotifHuntRule(
                rule_id="relative_excursion_flow_exhaustion",
                motif_name="relative_excursion_with_flow_exhaustion",
                required_features=("abs_spread_zscore","flow_exhaustion","relationship_stability"),
                output_message_type="SEARCH",
                research_priority=.70,
                falsification_note="displacement persists while flow re-accelerates or relationship stability breaks",
                false_positive_notes=("thin_book","stale_relationship"),
            ),
            MotifHuntRule(
                rule_id="depth_depletion_recovery",
                motif_name="depth_depletion_then_recovery",
                required_features=("depth_depletion","depth_recovery"),
                output_message_type="SEARCH",
                research_priority=.65,
                falsification_note="recovery fails to persist into subsequent public observations",
                false_positive_notes=("quote_flicker","venue_fragmentation"),
            ),
            MotifHuntRule(
                rule_id="structural_break",
                motif_name="relationship_modulation",
                required_features=("structural_break_pressure","relationship_instability"),
                output_message_type="ALARM",
                research_priority=.90,
                falsification_note="relationship diagnostics return to baseline without persistent break evidence",
                false_positive_notes=("temporary_volatility_shock",),
            ),
            MotifHuntRule(
                rule_id="discord_spike",
                motif_name="forecast_family_dissonance_spike",
                required_features=("forecast_discord","lineage_diversity"),
                output_message_type="SEARCH",
                research_priority=.60,
                falsification_note="discord resolves without new external evidence",
                false_positive_notes=("clone_pressure","insufficient_families"),
            ),
            MotifHuntRule(
                rule_id="context_burn",
                motif_name="high_cognition_low_information",
                required_features=("context_burn","information_gain_deficit"),
                output_message_type="ALARM",
                research_priority=.55,
                falsification_note="fresh independent evidence materially increases information gain",
                false_positive_notes=("cold_start",),
            ),
        )

    @staticmethod
    def _matched(rule:MotifHuntRule,obs:HuntObservation)->tuple[bool,tuple[str,...]]:
        missing=[f for f in rule.required_features if f not in obs.features]
        if missing:
            return False,tuple("missing:"+x for x in missing)
        f=obs.features
        rid=rule.rule_id
        if rid=="relative_excursion_flow_exhaustion":
            ok=abs(float(f["abs_spread_zscore"]))>=2.0 and float(f["flow_exhaustion"])>=.5 and float(f["relationship_stability"])>=.6
        elif rid=="depth_depletion_recovery":
            ok=float(f["depth_depletion"])>=.5 and float(f["depth_recovery"])>=.35
        elif rid=="structural_break":
            ok=float(f["structural_break_pressure"])>=.6 and float(f["relationship_instability"])>=.5
        elif rid=="discord_spike":
            ok=float(f["forecast_discord"])>=.5 and float(f["lineage_diversity"])>=.5
        elif rid=="context_burn":
            ok=float(f["context_burn"])>=.7 and float(f["information_gain_deficit"])>=.6
        else:
            ok=False
        rationale=tuple(f"{name}={float(f[name]):.3f}" for name in rule.required_features)
        return ok,rationale

    def hunt(self,observations:Sequence[HuntObservation])->tuple[MotifHuntMatch,...]:
        matches=[]
        for obs in observations:
            for rule in self.rules:
                ok,rationale=self._matched(rule,obs)
                if not ok:
                    continue
                body={
                    "rule_id":rule.rule_id,
                    "observation_id":obs.observation_id,
                    "scope":obs.scope,
                    "world_state_id":obs.world_state_id,
                    "evidence_root":obs.evidence_root,
                }
                matches.append(MotifHuntMatch(
                    schema="hivenance_motif_hunt_match_v1",
                    match_id="hunt_"+_digest(body).split(":",1)[1][:24],
                    rule_id=rule.rule_id,
                    motif_name=rule.motif_name,
                    observation_ids=(obs.observation_id,),
                    scope=obs.scope,
                    output_message_type=rule.output_message_type,
                    research_priority=rule.research_priority,
                    evidence_roots=(obs.evidence_root,),
                    world_state_id=obs.world_state_id,
                    rationale=rationale,
                    falsification_note=rule.falsification_note,
                    authority=RELATIVE_VALUE_AUTHORITY,
                    execution_eligible=False,
                    promotion_eligible=False,
                ))
        return tuple(matches)
