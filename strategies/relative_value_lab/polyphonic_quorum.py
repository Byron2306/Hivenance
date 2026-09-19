from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .musical_cognition import MotifNote


def _clamp(v:float)->float:
    return max(0.0,min(1.0,float(v)))


def _digest(payload:Any)->str:
    raw=json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")
    return "sha256:"+hashlib.sha256(raw).hexdigest()


ROLE_BY_MESSAGE={
    "WAGGLE":"CALL",
    "SEARCH":"CALL",
    "FOLLOW":"RESPONSE",
    "DISSENT":"COUNTERPOINT",
    "ALARM":"COUNTERPOINT",
    "ABANDON":"RESOLUTION",
    "SETTLE":"RESOLUTION",
}


@dataclass(frozen=True)
class PolyphonicQuorumConfig:
    minimum_independent_roots:int=2
    minimum_families:int=2
    minimum_roles:int=2
    phase_window_ms:int=15_000
    call_response_window_ms:int=30_000
    ensemble_lock_threshold:float=0.58


@dataclass(frozen=True)
class PolyphonicQuorumReceipt:
    schema:str
    quorum_id:str
    hypothesis_id:str
    world_state_id:str
    world_state_hash:str
    note_count:int
    independent_root_count:int
    family_count:int
    evidence_root_count:int
    roles_present:tuple[str,...]
    message_types:tuple[str,...]
    directional_counterpoint_present:bool
    explicit_dissent_present:bool
    world_binding:float
    phase_lock:float
    choreography:float
    role_coverage:float
    lineage_independence:float
    evidence_diversity:float
    counterpoint_preservation:float
    ensemble_lock:float
    quorum_formed:bool
    reasons:tuple[str,...]
    authority:str=RELATIVE_VALUE_AUTHORITY
    execution_eligible:bool=False
    promotion_eligible:bool=False

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


class PolyphonicQuorum:
    """Metatron-style quorum as ensemble lock, never majority agreement.

    A quorum exists when independent voices are bound to the same score page,
    temporally coordinated, role-complete enough to perform a research phrase,
    and provenance-diverse. Supporting and dissenting voices may coexist.
    """

    version="hivenance.polyphonic_quorum.v1"

    def __init__(self,config:PolyphonicQuorumConfig|None=None)->None:
        self.config=config or PolyphonicQuorumConfig()

    @staticmethod
    def _sign(direction:str)->int:
        value=str(direction or "").upper()
        if value=="LONG_A_SHORT_B":
            return 1
        if value=="LONG_B_SHORT_A":
            return -1
        return 0

    def score(self,notes:Sequence[MotifNote])->PolyphonicQuorumReceipt:
        rows=tuple(sorted(notes,key=lambda n:(n.observed_at_ms,n.message_id)))
        if not rows:
            return self._empty()

        hypothesis_id=rows[0].hypothesis_id
        world_pairs={(n.world_state_id,n.world_state_hash) for n in rows}
        world_binding=1.0 if len(world_pairs)==1 else 0.0
        world_state_id=rows[0].world_state_id if len(world_pairs)==1 else "mixed"
        world_state_hash=rows[0].world_state_hash if len(world_pairs)==1 else "mixed"

        roots={
            n.root_lineage_digest for n in rows
            if n.independent_voice and n.root_lineage_digest
        }
        families={n.family for n in rows if n.independent_voice}
        evidence_roots={n.evidence_root for n in rows if n.evidence_root}
        roles={ROLE_BY_MESSAGE.get(n.message_type,"VOICE") for n in rows}
        message_types={n.message_type for n in rows}

        times=[n.observed_at_ms for n in rows]
        span=max(times)-min(times) if len(times)>1 else 0
        phase_lock=_clamp(1.0-(span/max(1,self.config.phase_window_ms)))

        calls=[n for n in rows if ROLE_BY_MESSAGE.get(n.message_type)=="CALL"]
        responses=[n for n in rows if ROLE_BY_MESSAGE.get(n.message_type) in {"RESPONSE","COUNTERPOINT"}]
        call_response=0.0
        if calls and responses:
            latencies=[]
            for call in calls:
                for response in responses:
                    if response.observed_at_ms>=call.observed_at_ms and response.root_lineage_digest!=call.root_lineage_digest:
                        latencies.append(response.observed_at_ms-call.observed_at_ms)
            if latencies:
                best=min(latencies)
                call_response=_clamp(1.0-(best/max(1,self.config.call_response_window_ms)))

        role_coverage=_clamp(len(roles)/max(1,self.config.minimum_roles))
        lineage_independence=_clamp(len(roots)/max(1,self.config.minimum_independent_roots))
        family_diversity=_clamp(len(families)/max(1,self.config.minimum_families))
        evidence_diversity=_clamp(len(evidence_roots)/max(1,len(rows)))
        choreography=_clamp(0.55*phase_lock+0.45*call_response)

        signs={self._sign(n.direction) for n in rows if self._sign(n.direction)}
        directional_counterpoint=len(signs)>1
        explicit_dissent=any(n.message_type in {"DISSENT","ALARM"} for n in rows)
        counterpoint_preservation=1.0 if (directional_counterpoint or explicit_dissent) else 0.5

        ensemble_lock=_clamp(
            0.20*world_binding
            +0.18*choreography
            +0.16*role_coverage
            +0.16*lineage_independence
            +0.12*family_diversity
            +0.10*evidence_diversity
            +0.08*counterpoint_preservation
        )

        reasons=[]
        if len(world_pairs)!=1:
            reasons.append("mixed_world_score_pages")
        if len(roots)<self.config.minimum_independent_roots:
            reasons.append("insufficient_independent_roots")
        if len(families)<self.config.minimum_families:
            reasons.append("insufficient_family_diversity")
        if len(roles)<self.config.minimum_roles:
            reasons.append("insufficient_choreographic_roles")
        if phase_lock<0.35:
            reasons.append("voices_out_of_phase")
        if not calls:
            reasons.append("no_call_voice")
        if calls and not responses:
            reasons.append("call_unanswered")
        if explicit_dissent:
            reasons.append("counterpoint_preserved")

        quorum_formed=bool(
            world_binding==1.0
            and len(roots)>=self.config.minimum_independent_roots
            and len(families)>=self.config.minimum_families
            and len(roles)>=self.config.minimum_roles
            and ensemble_lock>=self.config.ensemble_lock_threshold
        )

        body={
            "hypothesis_id":hypothesis_id,
            "world":(world_state_id,world_state_hash),
            "messages":[n.message_id for n in rows],
            "ensemble_lock":round(ensemble_lock,6),
            "quorum_formed":quorum_formed,
        }
        return PolyphonicQuorumReceipt(
            schema="hivenance_polyphonic_quorum_v1",
            quorum_id="quorum_"+_digest(body).split(":",1)[1][:24],
            hypothesis_id=hypothesis_id,
            world_state_id=world_state_id,
            world_state_hash=world_state_hash,
            note_count=len(rows),
            independent_root_count=len(roots),
            family_count=len(families),
            evidence_root_count=len(evidence_roots),
            roles_present=tuple(sorted(roles)),
            message_types=tuple(sorted(message_types)),
            directional_counterpoint_present=directional_counterpoint,
            explicit_dissent_present=explicit_dissent,
            world_binding=round(world_binding,6),
            phase_lock=round(phase_lock,6),
            choreography=round(choreography,6),
            role_coverage=round(role_coverage,6),
            lineage_independence=round(lineage_independence,6),
            evidence_diversity=round(evidence_diversity,6),
            counterpoint_preservation=round(counterpoint_preservation,6),
            ensemble_lock=round(ensemble_lock,6),
            quorum_formed=quorum_formed,
            reasons=tuple(sorted(set(reasons))),
        )

    def _empty(self)->PolyphonicQuorumReceipt:
        return PolyphonicQuorumReceipt(
            schema="hivenance_polyphonic_quorum_v1",
            quorum_id="quorum_empty",
            hypothesis_id="",
            world_state_id="",
            world_state_hash="",
            note_count=0,
            independent_root_count=0,
            family_count=0,
            evidence_root_count=0,
            roles_present=(),
            message_types=(),
            directional_counterpoint_present=False,
            explicit_dissent_present=False,
            world_binding=0.0,
            phase_lock=0.0,
            choreography=0.0,
            role_coverage=0.0,
            lineage_independence=0.0,
            evidence_diversity=0.0,
            counterpoint_preservation=0.0,
            ensemble_lock=0.0,
            quorum_formed=False,
            reasons=("no_voices",),
        )
