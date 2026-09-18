from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY


OBSERVED_NAMESPACE = "observed_market"
INTERPRETED_NAMESPACE = "interpreted_research"
SYNTHETIC_NAMESPACE = "synthetic_counterfactual"


def _digest(payload: Any) -> str:
    raw=json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")
    return "sha256:"+hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ScoreObservation:
    observation_id: str
    source_id: str
    source_class: str
    scope: str
    observed_at_ms: int
    received_at_ms: int
    evidence_root: str
    payload: Mapping[str,Any]
    namespace: str=OBSERVED_NAMESPACE

    def __post_init__(self)->None:
        if self.namespace != OBSERVED_NAMESPACE:
            raise ValueError("score_observation_must_be_observed_namespace")
        if not str(self.evidence_root).startswith("sha256:"):
            raise ValueError("score_observation_evidence_unbound")
        if int(self.received_at_ms) < int(self.observed_at_ms):
            raise ValueError("score_observation_received_before_observed")

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScoreInterpretation:
    interpretation_id: str
    organ_id: str
    parent_world_state_id: str
    parent_world_state_hash: str
    created_at_ms: int
    evidence_roots: tuple[str,...]
    payload: Mapping[str,Any]
    namespace: str=INTERPRETED_NAMESPACE
    authority: str=RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool=False
    promotion_eligible: bool=False

    def __post_init__(self)->None:
        if self.namespace != INTERPRETED_NAMESPACE:
            raise ValueError("score_interpretation_namespace_invalid")
        if not str(self.parent_world_state_hash).startswith("sha256:"):
            raise ValueError("score_interpretation_parent_unbound")
        if any(not str(root).startswith("sha256:") for root in self.evidence_roots):
            raise ValueError("score_interpretation_evidence_unbound")

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


@dataclass(frozen=True)
class CanonicalScoreFrame:
    schema: str
    world_state_id: str
    world_state_hash: str
    assembled_at_ms: int
    latest_observation_ms: int
    oldest_observation_ms: int
    freshness_window_ms: int
    expires_at_ms: int
    observation_count: int
    sources: tuple[str,...]
    scopes: tuple[str,...]
    observed_digest: str
    observations: tuple[ScoreObservation,...]
    namespace: str=OBSERVED_NAMESPACE
    authority: str=RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool=False
    promotion_eligible: bool=False

    def to_dict(self)->dict[str,Any]:
        payload=asdict(self)
        payload["observations"]=tuple(o.to_dict() for o in self.observations)
        return payload

    @property
    def binding(self)->tuple[str,str]:
        return self.world_state_id,self.world_state_hash

    def is_fresh(self,now_ms:int)->bool:
        return int(now_ms) <= int(self.expires_at_ms)


@dataclass(frozen=True)
class ScoreBindingClaim:
    claimant_id: str
    world_state_id: str
    world_state_hash: str
    namespace: str
    synthetic: bool=False

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScoreBindingAudit:
    schema: str
    frame_id: str
    bound_claimants: tuple[str,...]
    refused_claimants: tuple[str,...]
    synthetic_claimants: tuple[str,...]
    violations: tuple[str,...]
    all_observed_claimants_bound: bool
    authority: str=RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool=False
    promotion_eligible: bool=False

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


class CanonicalWorldScore:
    """Build and validate one immutable observed score page.

    The frame contains observed public-market evidence only. Interpretations and
    synthetic variations may bind to it, but can never mutate its digest.
    """

    version="hivenance.canonical_world_score.v1"

    @staticmethod
    def assemble(
        *,
        observations:Sequence[ScoreObservation],
        assembled_at_ms:int,
        freshness_window_ms:int=15_000,
    )->CanonicalScoreFrame:
        if not observations:
            raise ValueError("canonical_score_requires_observations")
        if freshness_window_ms <= 0:
            raise ValueError("freshness_window_must_be_positive")

        ordered=tuple(sorted(
            observations,
            key=lambda o:(int(o.observed_at_ms),o.source_id,o.observation_id),
        ))

        future=[
            o.observation_id for o in ordered
            if int(o.observed_at_ms) > int(assembled_at_ms)
        ]
        if future:
            raise ValueError("future_observation_forbidden:"+",".join(future))

        ids=[o.observation_id for o in ordered]
        if len(ids)!=len(set(ids)):
            raise ValueError("duplicate_observation_id")

        source_payloads:dict[tuple[str,int,str],str]={}
        for obs in ordered:
            key=(obs.source_id,int(obs.observed_at_ms),obs.scope)
            digest=_digest(obs.payload)
            prior=source_payloads.get(key)
            if prior is not None and prior != digest:
                raise ValueError("conflicting_same_source_observation")
            source_payloads[key]=digest

        observed_body={
            "namespace":OBSERVED_NAMESPACE,
            "observations":[o.to_dict() for o in ordered],
        }
        observed_digest=_digest(observed_body)
        latest=max(int(o.observed_at_ms) for o in ordered)
        oldest=min(int(o.observed_at_ms) for o in ordered)
        expires=latest+int(freshness_window_ms)

        frame_body={
            "observed_digest":observed_digest,
            "latest_observation_ms":latest,
            "oldest_observation_ms":oldest,
            "freshness_window_ms":int(freshness_window_ms),
            "sources":sorted({o.source_id for o in ordered}),
            "scopes":sorted({o.scope for o in ordered}),
        }
        world_hash=_digest(frame_body)
        world_id="ws_"+world_hash.split(":",1)[1][:24]

        return CanonicalScoreFrame(
            schema="hivenance_canonical_world_score_v1",
            world_state_id=world_id,
            world_state_hash=world_hash,
            assembled_at_ms=int(assembled_at_ms),
            latest_observation_ms=latest,
            oldest_observation_ms=oldest,
            freshness_window_ms=int(freshness_window_ms),
            expires_at_ms=expires,
            observation_count=len(ordered),
            sources=tuple(sorted({o.source_id for o in ordered})),
            scopes=tuple(sorted({o.scope for o in ordered})),
            observed_digest=observed_digest,
            observations=ordered,
            namespace=OBSERVED_NAMESPACE,
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )

    @staticmethod
    def interpretation(
        frame:CanonicalScoreFrame,
        *,
        interpretation_id:str,
        organ_id:str,
        created_at_ms:int,
        evidence_roots:Sequence[str],
        payload:Mapping[str,Any],
    )->ScoreInterpretation:
        return ScoreInterpretation(
            interpretation_id=interpretation_id,
            organ_id=organ_id,
            parent_world_state_id=frame.world_state_id,
            parent_world_state_hash=frame.world_state_hash,
            created_at_ms=int(created_at_ms),
            evidence_roots=tuple(evidence_roots),
            payload=dict(payload),
            namespace=INTERPRETED_NAMESPACE,
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )

    @staticmethod
    def audit_bindings(
        frame:CanonicalScoreFrame,
        *,
        claims:Sequence[ScoreBindingClaim],
        now_ms:int,
    )->ScoreBindingAudit:
        violations=[]
        bound=[]
        refused=[]
        synthetic=[]

        if not frame.is_fresh(now_ms):
            violations.append("canonical_score_frame_stale")

        for claim in claims:
            if claim.synthetic or claim.namespace == SYNTHETIC_NAMESPACE:
                synthetic.append(claim.claimant_id)
                # Synthetic branches may cite the parent frame but never count as
                # observed claimants in binding completeness.
                if (
                    claim.world_state_id != frame.world_state_id
                    or claim.world_state_hash != frame.world_state_hash
                ):
                    violations.append("synthetic_parent_binding_drift:"+claim.claimant_id)
                continue

            if claim.namespace not in {OBSERVED_NAMESPACE,INTERPRETED_NAMESPACE}:
                refused.append(claim.claimant_id)
                violations.append("unknown_claim_namespace:"+claim.claimant_id)
                continue

            if (
                claim.world_state_id == frame.world_state_id
                and claim.world_state_hash == frame.world_state_hash
            ):
                bound.append(claim.claimant_id)
            else:
                refused.append(claim.claimant_id)
                violations.append("world_score_binding_drift:"+claim.claimant_id)

        return ScoreBindingAudit(
            schema="hivenance_score_binding_audit_v1",
            frame_id=frame.world_state_id,
            bound_claimants=tuple(sorted(bound)),
            refused_claimants=tuple(sorted(refused)),
            synthetic_claimants=tuple(sorted(synthetic)),
            violations=tuple(sorted(set(violations))),
            all_observed_claimants_bound=not refused and "canonical_score_frame_stale" not in violations,
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )
