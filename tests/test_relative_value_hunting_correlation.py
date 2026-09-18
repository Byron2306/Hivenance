from __future__ import annotations

from strategies.relative_value_lab.market_hunting import HuntObservation, MotifHunter
from strategies.relative_value_lab.colony_correlation import CorrelationEvent, ColonyCorrelator


WS="ws-1"
WH="sha256:"+"a"*64


def test_relative_excursion_hunt_emits_search_not_action():
    obs=HuntObservation(
        observation_id="o1",timestamp_ms=1000,scope="pair:A/B",
        pair_id="A/B",asset_ids=("A","B"),venue="kraken",
        family="microstructure",
        features={
            "abs_spread_zscore":2.4,
            "flow_exhaustion":.7,
            "relationship_stability":.8,
        },
        evidence_root="sha256:"+"1"*64,
        world_state_id=WS,world_state_hash=WH,
    )
    matches=MotifHunter().hunt([obs])
    assert len(matches)==1
    m=matches[0]
    assert m.output_message_type=="SEARCH"
    assert m.execution_eligible is False
    assert m.promotion_eligible is False


def test_structural_break_hunt_emits_alarm_not_direction():
    obs=HuntObservation(
        observation_id="o2",timestamp_ms=1000,scope="pair:A/B",
        pair_id="A/B",
        features={"structural_break_pressure":.8,"relationship_instability":.7},
        evidence_root="sha256:"+"2"*64,
        world_state_id=WS,world_state_hash=WH,
    )
    matches=MotifHunter().hunt([obs])
    assert len(matches)==1
    assert matches[0].output_message_type=="ALARM"
    assert "direction" not in matches[0].to_dict()


def test_missing_features_do_not_create_hunt_match():
    obs=HuntObservation(
        observation_id="o3",timestamp_ms=1000,scope="pair:A/B",
        features={"abs_spread_zscore":3.0},
        evidence_root="sha256:"+"3"*64,
        world_state_id=WS,world_state_hash=WH,
    )
    assert MotifHunter().hunt([obs])==()


def test_colony_correlation_links_shared_asset_across_pairs_without_causality():
    events=[
        CorrelationEvent(
            event_id="e1",timestamp_ms=1000,scope="pair:A/B",
            pair_id="A/B",asset_ids=("A","B"),venue="kraken",
            feature_family="microstructure",hypothesis_family="reversal",
            lineage_root="l1",evidence_root="r1",
        ),
        CorrelationEvent(
            event_id="e2",timestamp_ms=5000,scope="pair:A/C",
            pair_id="A/C",asset_ids=("A","C"),venue="kraken",
            feature_family="structural",hypothesis_family="reversal",
            lineage_root="l2",evidence_root="r2",
        ),
    ]
    rows=ColonyCorrelator(temporal_window_ms=10000).correlate(events)
    assert len(rows)==1
    r=rows[0]
    assert r.shared_assets==("A",)
    assert r.same_pair is False
    assert r.family_diversity==1.0
    assert r.causal_claim is False
    assert r.execution_eligible is False


def test_shared_lineage_and_evidence_reduce_correlation_confidence():
    independent=[
        CorrelationEvent(
            event_id="a",timestamp_ms=1000,scope="pair:A/B",pair_id="A/B",
            asset_ids=("A","B"),feature_family="f1",lineage_root="l1",evidence_root="r1",
        ),
        CorrelationEvent(
            event_id="b",timestamp_ms=2000,scope="pair:A/B",pair_id="A/B",
            asset_ids=("A","B"),feature_family="f2",lineage_root="l2",evidence_root="r2",
        ),
    ]
    dependent=[
        CorrelationEvent(
            event_id="c",timestamp_ms=1000,scope="pair:A/B",pair_id="A/B",
            asset_ids=("A","B"),feature_family="f1",lineage_root="same",evidence_root="same",
        ),
        CorrelationEvent(
            event_id="d",timestamp_ms=2000,scope="pair:A/B",pair_id="A/B",
            asset_ids=("A","B"),feature_family="f2",lineage_root="same",evidence_root="same",
        ),
    ]
    corr=ColonyCorrelator(temporal_window_ms=10000)
    i=corr.correlate(independent)[0]
    d=corr.correlate(dependent)[0]
    assert d.shared_lineage is True
    assert d.shared_evidence_root is True
    assert d.confidence < i.confidence
    assert d.causal_claim is False


def test_temporally_distant_events_do_not_correlate():
    events=[
        CorrelationEvent(event_id="e1",timestamp_ms=1000,scope="pair:A/B",pair_id="A/B",asset_ids=("A","B")),
        CorrelationEvent(event_id="e2",timestamp_ms=50000,scope="pair:A/B",pair_id="A/B",asset_ids=("A","B")),
    ]
    assert ColonyCorrelator(temporal_window_ms=10000).correlate(events)==()
