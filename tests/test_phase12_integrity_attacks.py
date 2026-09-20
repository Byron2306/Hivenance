import hashlib

from strategies.relative_value_lab.musical_cognition import MotifNote
from strategies.relative_value_lab.polyphonic_quorum import PolyphonicQuorum
from strategies.relative_value_lab.world_score import CanonicalWorldScore,ScoreObservation,ScoreBindingClaim,INTERPRETED_NAMESPACE


def root(x):
    return "sha256:"+hashlib.sha256(x.encode()).hexdigest()


def test_same_root_cannot_manufacture_quorum():
    common=root("common")
    notes=[]
    for i,(family,message_type) in enumerate((("LIQUIDITY","WAGGLE"),("FLOW","FOLLOW"),("VOLATILITY","FOLLOW"))):
        notes.append(MotifNote(
            message_id=f"m{i}",receipt_id=f"r{i}",hypothesis_id="h",bee_id=f"b{i}",
            family=family,lineage_digest=root(f"l{i}"),root_lineage_digest=common,
            message_type=message_type,observed_at_ms=1000+i,horizon_band="5m",
            direction="LONG_A_SHORT_B",expected_move_bps=1.0,uncertainty=.1,
            pulse_type="T",evidence_root=root(f"e{i}"),world_state_id="w",
            world_state_hash=root("w"),independent_voice=True,
        ))
    receipt=PolyphonicQuorum().score(notes)
    assert receipt.independent_root_count==1
    assert receipt.quorum_formed is False


def test_stale_and_substituted_world_bindings_fail_closed():
    obs=ScoreObservation(
        observation_id="o",source_id="s",source_class="public",scope="BTC/USD",
        observed_at_ms=1000,received_at_ms=1000,evidence_root=root("e"),payload={},
    )
    frame=CanonicalWorldScore.assemble(observations=(obs,),assembled_at_ms=1000,freshness_window_ms=100)
    stale=CanonicalWorldScore.audit_bindings(
        frame,
        claims=(ScoreBindingClaim("c",frame.world_state_id,frame.world_state_hash,INTERPRETED_NAMESPACE),),
        now_ms=1200,
    )
    assert stale.all_observed_claimants_bound is False
    assert "canonical_score_frame_stale" in stale.violations

    wrong=CanonicalWorldScore.audit_bindings(
        frame,
        claims=(ScoreBindingClaim("x",frame.world_state_id,root("wrong"),INTERPRETED_NAMESPACE),),
        now_ms=1000,
    )
    assert "x" in wrong.refused_claimants
