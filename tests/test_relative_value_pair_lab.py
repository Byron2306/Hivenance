from __future__ import annotations

import math
import random

from strategies.relative_value_lab.pair_lab import PairRelationshipLab
from strategies.relative_value_lab.pair_graph import RelativeValueGraph


def _mean_reverting_pair(n=300,seed=7):
    rng=random.Random(seed)
    base=100.0
    spread=0.0
    a=[]
    b=[]
    for _ in range(n):
        base*=math.exp(rng.gauss(0,0.0015))
        spread=0.92*spread+rng.gauss(0,0.0010)
        b.append(base)
        a.append(math.exp(math.log(base)+spread))
    return a,b


def _diverging_pair(n=300):
    a=[]
    b=[]
    pa,pb=100.0,100.0
    for i in range(n):
        pa*=1.0008
        pb*=0.9998
        a.append(pa)
        b.append(pb)
    return a,b


def test_pair_lab_estimates_mean_reversion_and_half_life():
    a,b=_mean_reverting_pair()
    lab=PairRelationshipLab(min_samples=60,min_stability_score=0.20)
    diag,crystal=lab.analyze(
        symbol_a="DOGE/USD",
        symbol_b="SOL/USD",
        prices_a=a,
        prices_b=b,
        sample_interval_sec=1.0,
        venue="kraken",
        observed_at_ms=123,
        direct_route_available=True,
    )
    assert diag.samples==300
    assert diag.hedge_ratio is not None and diag.hedge_ratio>0
    assert diag.ar1_phi is not None and 0<diag.ar1_phi<1
    assert diag.half_life_seconds is not None and diag.half_life_seconds>0
    assert diag.ou_mean_reversion_speed_per_sec is not None
    assert crystal.half_life_seconds==diag.half_life_seconds
    assert crystal.execution_eligible is False


def test_pair_lab_rejects_diverging_or_nonreverting_relationship():
    a,b=_diverging_pair()
    lab=PairRelationshipLab(min_samples=60)
    diag,_=lab.analyze(
        symbol_a="A/USD",
        symbol_b="B/USD",
        prices_a=a,
        prices_b=b,
        sample_interval_sec=1.0,
    )
    assert diag.eligible is False
    assert diag.rejection_reasons


def test_pair_lab_rejects_insufficient_history():
    lab=PairRelationshipLab(min_samples=60)
    diag,_=lab.analyze(
        symbol_a="A/USD",
        symbol_b="B/USD",
        prices_a=[1,2,3,4,5],
        prices_b=[1,2,3,4,5],
        sample_interval_sec=1.0,
    )
    assert diag.eligible is False
    assert "insufficient_synchronized_history" in diag.rejection_reasons


def test_relative_value_graph_builds_unique_edges():
    a,b=_mean_reverting_pair()
    c=[v*1.01 for v in b]
    graph=RelativeValueGraph(PairRelationshipLab(min_samples=60,min_stability_score=0.20))
    edges,crystals,diagnostics=graph.analyze_basket(
        prices={"A/USD":a,"B/USD":b,"C/USD":c},
        sample_interval_sec=1.0,
        direct_routes={frozenset(("A/USD","B/USD"))},
    )
    assert len(edges)==3
    assert len(crystals)==3
    assert len(diagnostics)==3
    edge=next(e for e in edges if set((e.symbol_a,e.symbol_b))=={"A/USD","B/USD"})
    assert edge.direct_route_available is True


def test_timestamped_graph_aligns_on_common_buckets():
    a,b=_mean_reverting_pair(n=120)
    points_a=[(1000.0+i*5.0,price) for i,price in enumerate(a)]
    points_b=[(1000.8+i*5.0,price) for i,price in enumerate(b)]
    # Add an unmatched extra observation to prove pairwise intersection rather
    # than naïve list-position alignment.
    points_a.append((1000.0+120*5.0,a[-1]))
    graph=RelativeValueGraph(PairRelationshipLab(min_samples=60,min_stability_score=0.20))
    edges,crystals,diagnostics=graph.analyze_timestamped_basket(
        points={"A/USD":points_a,"B/USD":points_b},
        sample_interval_sec=5.0,
    )
    assert len(edges)==1
    diag=next(iter(diagnostics.values()))
    assert diag.samples==120
    assert next(iter(crystals.values())).execution_eligible is False
