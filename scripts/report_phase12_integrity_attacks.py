#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from strategies.relative_value_lab.musical_cognition import MotifNote
from strategies.relative_value_lab.polyphonic_quorum import PolyphonicQuorum
from strategies.relative_value_lab.queen_input_assembly import channel
from strategies.relative_value_lab.world_score import (
    CanonicalWorldScore,
    ScoreBindingClaim,
    ScoreObservation,
    INTERPRETED_NAMESPACE,
)


def _root(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _frame():
    obs=ScoreObservation(
        observation_id="obs_attack",
        source_id="phase12_attack_fixture",
        source_class="public_market_fixture",
        scope="BTC/USD",
        observed_at_ms=1000,
        received_at_ms=1000,
        evidence_root=_root("market"),
        payload={"price":100.0},
    )
    return CanonicalWorldScore.assemble(
        observations=(obs,),
        assembled_at_ms=1000,
        freshness_window_ms=100,
    )


def _note(*,message_id:str,family:str,message_type:str,root_lineage:str,evidence_root:str)->MotifNote:
    return MotifNote(
        message_id=message_id,
        receipt_id="r_"+message_id,
        hypothesis_id="h1",
        bee_id="bee_"+family.lower(),
        family=family,
        lineage_digest=_root("lineage:"+message_id),
        root_lineage_digest=root_lineage,
        message_type=message_type,
        observed_at_ms=1000,
        horizon_band="5m",
        direction="LONG_A_SHORT_B",
        expected_move_bps=10.0,
        uncertainty=0.2,
        pulse_type="TEST",
        evidence_root=evidence_root,
        world_state_id="ws_attack",
        world_state_hash=_root("world"),
        independent_voice=True,
    )


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",type=Path,default=Path("data/phase12_integrity_attacks.json"))
    args=ap.parse_args()

    attacks={}

    frame=_frame()
    matching=ScoreBindingClaim(
        claimant_id="delayed_claim",
        world_state_id=frame.world_state_id,
        world_state_hash=frame.world_state_hash,
        namespace=INTERPRETED_NAMESPACE,
        synthetic=False,
    )
    delayed=CanonicalWorldScore.audit_bindings(
        frame,
        claims=(matching,),
        now_ms=frame.expires_at_ms+1,
    )
    attacks["DELAY_EVIDENCE"]={
        "status":"PASS" if "canonical_score_frame_stale" in delayed.violations and not delayed.all_observed_claimants_bound else "FAIL",
        "attack_resisted":bool("canonical_score_frame_stale" in delayed.violations and not delayed.all_observed_claimants_bound),
        "mechanism":"delayed evidence loses freshness and cannot produce a fully bound current score",
        "violations":delayed.violations,
    }

    stale=CanonicalWorldScore.audit_bindings(
        frame,
        claims=(matching,),
        now_ms=frame.expires_at_ms+10_000,
    )
    attacks["STALE_WORLD_BINDING"]={
        "status":"PASS" if not stale.all_observed_claimants_bound else "FAIL",
        "attack_resisted":not stale.all_observed_claimants_bound,
        "mechanism":"stale canonical world binding is refused as current",
        "violations":stale.violations,
    }

    same_root=_root("same_lineage")
    duplicate_notes=(
        _note(message_id="n1",family="LIQUIDITY",message_type="WAGGLE",root_lineage=same_root,evidence_root=_root("e1")),
        _note(message_id="n2",family="FLOW",message_type="FOLLOW",root_lineage=same_root,evidence_root=_root("e2")),
    )
    dup=PolyphonicQuorum().score(duplicate_notes)
    attacks["DUPLICATE_LINEAGE"]={
        "status":"PASS" if dup.independent_root_count==1 and not dup.quorum_formed else "FAIL",
        "attack_resisted":bool(dup.independent_root_count==1 and not dup.quorum_formed),
        "mechanism":"same root lineage cannot manufacture independent quorum roots",
        "independent_root_count":dup.independent_root_count,
        "quorum_formed":dup.quorum_formed,
        "reasons":dup.reasons,
    }

    false_unison_notes=tuple(
        _note(
            message_id=f"u{i}",
            family=family,
            message_type=("WAGGLE" if i==0 else "FOLLOW"),
            root_lineage=same_root,
            evidence_root=_root("unison:"+str(i)),
        )
        for i,family in enumerate(("LIQUIDITY","FLOW","VOLATILITY"))
    )
    unison=PolyphonicQuorum().score(false_unison_notes)
    attacks["FALSE_UNISON"]={
        "status":"PASS" if unison.independent_root_count==1 and not unison.quorum_formed else "FAIL",
        "attack_resisted":bool(unison.independent_root_count==1 and not unison.quorum_formed),
        "mechanism":"multiple agreeing transforms from one root cannot form independent ensemble lock",
        "independent_root_count":unison.independent_root_count,
        "family_count":unison.family_count,
        "quorum_formed":unison.quorum_formed,
        "reasons":unison.reasons,
    }

    missing=channel(
        name="TEMPORAL_TEXTURE",
        state="ABSENT_DATA",
        reason="phase12_missing_voice_attack",
    )
    attacks["MISSING_VOICE"]={
        "status":"PASS" if missing.state=="ABSENT_DATA" and not missing.evidence_roots else "FAIL",
        "attack_resisted":bool(missing.state=="ABSENT_DATA" and not missing.evidence_roots),
        "mechanism":"missing Queen voice remains explicit absence rather than a synthetic neutral reading",
        "channel_state":missing.state,
        "reason":missing.reason,
    }

    substituted=ScoreBindingClaim(
        claimant_id="root_substitution",
        world_state_id=frame.world_state_id,
        world_state_hash=_root("substituted_world"),
        namespace=INTERPRETED_NAMESPACE,
        synthetic=False,
    )
    root_attack=CanonicalWorldScore.audit_bindings(
        frame,
        claims=(substituted,),
        now_ms=frame.assembled_at_ms,
    )
    attacks["ROOT_SUBSTITUTION"]={
        "status":"PASS" if "root_substitution" in root_attack.refused_claimants else "FAIL",
        "attack_resisted":"root_substitution" in root_attack.refused_claimants,
        "mechanism":"claim with substituted world hash is refused by canonical binding audit",
        "refused_claimants":root_attack.refused_claimants,
        "violations":root_attack.violations,
    }

    failed=sorted(k for k,v in attacks.items() if v.get("status")!="PASS")
    payload={
        "schema":"hivenance_full_organism_census_replay_bundle_v1",
        "source":"report_phase12_integrity_attacks",
        "strict_before":True,
        "outcomes_by_mask":{},
        "invocation_counts":{},
        "adversarial_attacks":attacks,
        "integrity_attack_failures":failed,
        "historical_only":True,
        "execution_eligible":False,
        "promotion_eligible":False,
    }
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(payload,indent=2,sort_keys=True),encoding="utf-8")
    print("HIVENANCE_PHASE12_INTEGRITY_ATTACKS")
    print(json.dumps(payload,indent=2,sort_keys=True))
    return 0 if not failed else 2


if __name__=="__main__":
    raise SystemExit(main())
