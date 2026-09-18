from __future__ import annotations

from strategies.relative_value_lab.causal_cascade import (
    CascadeEvent,
    CascadeLink,
    CausalCascade,
)
from strategies.relative_value_lab.hive_pulse import HivePulseEngine


WS="ws-1"
WH="sha256:"+"a"*64


def event(event_id, ts, event_class, scope, family, lineage, root, assets=()):
    return CascadeEvent(
        event_id=event_id,
        timestamp_ms=ts,
        event_class=event_class,
        scope=scope,
        world_state_id=WS,
        world_state_hash=WH,
        evidence_root=root,
        family=family,
        lineage_root=lineage,
        asset_ids=tuple(assets),
    )


def test_evidence_bound_chain_forms_crescendo_without_claiming_causal_proof():
    events=[
        event("e1",1000,"aggressor_sell_burst","pair:A/B","microstructure","l1","sha256:"+"1"*64,("A","B")),
        event("e2",3000,"book_depletion","pair:A/B","book","l2","sha256:"+"2"*64,("A","B")),
        event("e3",6000,"relative_excursion","connected_pairs:A","structural","l3","sha256:"+"3"*64,("A","B","C")),
        event("e4",9000,"depth_recovery","asset:A","microstructure","l4","sha256:"+"4"*64,("A",)),
    ]
    links=[
        CascadeLink("e1","e2","sell flow consumes displayed depth","sha256:"+"a"*64,.8),
        CascadeLink("e2","e3","depletion coincides with relative displacement","sha256:"+"b"*64,.7),
        CascadeLink("e3","e4","liquidity replenishment follows excursion","sha256:"+"c"*64,.75),
    ]
    receipt=CausalCascade().build(events=events,links=links)
    assert receipt.depth == 3
    assert receipt.independent_family_count >= 2
    assert receipt.propagation_strength > 0.0
    assert receipt.crescendo > 0.0
    assert receipt.causal_proof is False
    assert receipt.execution_eligible is False


def test_reverse_temporal_link_is_not_accepted():
    events=[
        event("late",5000,"late","pair:A/B","f1","l1","sha256:"+"1"*64),
        event("early",1000,"early","pair:A/B","f2","l2","sha256:"+"2"*64),
    ]
    link=CascadeLink("late","early","impossible_reverse_phrase","sha256:"+"3"*64,.9)
    receipt=CausalCascade().build(events=events,links=[link])
    edge=receipt.edges[0]
    assert edge.accepted is False
    assert "reverse_temporal_order" in edge.reasons
    assert receipt.depth == 0


def test_world_state_mismatch_breaks_propagation_edge():
    left=event("e1",1000,"a","pair:A/B","f1","l1","sha256:"+"1"*64)
    right=CascadeEvent(
        event_id="e2",timestamp_ms=2000,event_class="b",scope="pair:A/B",
        world_state_id="ws-2",world_state_hash="sha256:"+"f"*64,
        evidence_root="sha256:"+"2"*64,family="f2",lineage_root="l2",
    )
    receipt=CausalCascade().build(
        events=[left,right],
        links=[CascadeLink("e1","e2","state drift edge","sha256:"+"3"*64,.8)],
    )
    assert receipt.edges[0].accepted is False
    assert "world_state_mismatch" in receipt.edges[0].reasons


def test_missing_mechanism_evidence_cannot_enter_cascade():
    events=[
        event("e1",1000,"a","pair:A/B","f1","l1","sha256:"+"1"*64),
        event("e2",2000,"b","pair:A/B","f2","l2","sha256:"+"2"*64),
    ]
    receipt=CausalCascade().build(
        events=events,
        links=[CascadeLink("e1","e2","possible mechanism","not-bound",.8)],
    )
    assert receipt.edges[0].accepted is False
    assert "mechanism_evidence_unbound" in receipt.edges[0].reasons


def test_hive_pulse_from_cascade_is_research_only():
    events=[
        event("e1",1000,"a","pair:A/B","f1","l1","sha256:"+"1"*64),
        event("e2",2000,"b","pair:A/B","f2","l2","sha256:"+"2"*64),
        event("e3",3000,"c","asset:A","f3","l3","sha256:"+"3"*64),
    ]
    cascade=CausalCascade().build(
        events=events,
        links=[
            CascadeLink("e1","e2","m1","sha256:"+"4"*64,.8),
            CascadeLink("e2","e3","m2","sha256:"+"5"*64,.8),
        ],
    )
    pulse=HivePulseEngine.from_cascade(
        cascade,
        pulse_class="DISCOVERY_PULSE",
        scope="asset:A",
        issued_at_ms=4000,
        ttl_ms=10000,
        lineage_root="hive",
        evidence_root="sha256:"+"6"*64,
    )
    assert pulse.cascade_depth == cascade.depth
    assert pulse.authority_effect == "ATTENTION_ONLY"
    assert pulse.execution_eligible is False
    assert pulse.promotion_eligible is False


def test_alarm_and_freeze_can_only_reduce_or_freeze():
    for cls in ("ALARM_PULSE","FREEZE_PULSE"):
        pulse=HivePulseEngine.emit(
            pulse_class=cls,scope="pair:A/B",issued_at_ms=1000,ttl_ms=5000,
            severity=.9,confidence=.8,amplitude=.8,world_state_id=WS,
            lineage_root="hive",evidence_root="sha256:"+"7"*64,
        )
        assert pulse.authority_effect == "REDUCE_OR_FREEZE_ONLY"
        assert pulse.execution_eligible is False


def test_pulse_decays_and_expires():
    pulse=HivePulseEngine.emit(
        pulse_class="SEARCH_PULSE",scope="pair:A/B",issued_at_ms=1000,ttl_ms=10000,
        severity=.5,confidence=.8,amplitude=.9,world_state_id=WS,
        lineage_root="hive",evidence_root="sha256:"+"8"*64,
    )
    early=HivePulseEngine.decay(pulse,now_ms=2000)
    late=HivePulseEngine.decay(pulse,now_ms=9000)
    dead=HivePulseEngine.decay(pulse,now_ms=11000)
    assert early.effective_amplitude > late.effective_amplitude
    assert dead.effective_amplitude == 0.0
    assert dead.expired is True
