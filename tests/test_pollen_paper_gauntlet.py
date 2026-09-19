from __future__ import annotations

from types import SimpleNamespace

from scripts.run_pollen_paper_gauntlet import (
    _ensemble,
    _pair_cost_bps,
    _world_frame,
)
from strategies.relative_value_lab.pollen_economy import QueenPollenEconomy


class FakeFeed:
    def __init__(self):
        self.last_prices={"A/USD":101.0,"B/USD":100.0}
        self.last_bid={"A/USD":100.9,"B/USD":99.9}
        self.last_ask={"A/USD":101.1,"B/USD":100.1}
        self.last_spread_bps={"A/USD":2.0,"B/USD":3.0}


def test_pair_cost_is_observed_round_trip_spread_plus_explicit_extra():
    feed=FakeFeed()
    assert _pair_cost_bps(feed,"A/USD","B/USD",1.5)==6.5


def test_world_frame_is_pair_observed_and_research_only():
    feed=FakeFeed()
    frame=_world_frame(
        pair_id="A/USD__B/USD",
        symbol_a="A/USD",
        symbol_b="B/USD",
        now_ms=1000,
        feed=feed,
    )
    assert frame.observation_count==2
    assert set(frame.scopes)=={"symbol:A/USD","symbol:B/USD"}
    assert frame.execution_eligible is False
    assert frame.promotion_eligible is False


def test_live_ensemble_can_form_with_counterpoint_without_agreement():
    feed=FakeFeed()
    frame=_world_frame(
        pair_id="A/USD__B/USD",
        symbol_a="A/USD",
        symbol_b="B/USD",
        now_ms=1000,
        feed=feed,
    )
    forecast=SimpleNamespace(
        forecast_id="f-live",
        direction="LONG_B_SHORT_A",
        expected_relative_move_bps=-8.0,
        uncertainty=2.0,
        horizon_seconds=30,
    )
    diagnostics=SimpleNamespace(
        stability_score=.8,
        half_life_seconds=20.0,
        hedge_alpha=0.0,
        hedge_ratio=1.0,
        spread_last=0.01,
        ou_equilibrium=0.0,
    )
    economy=QueenPollenEconomy()
    (
        quorum,
        issue,
        motion_bps,
        motion_kind,
        treatment_admitted,
        treatment_resolution,
        music_metrics,
    )=_ensemble(
        forecast=forecast,
        diagnostics=diagnostics,
        frame=frame,
        pair_id="A/USD__B/USD",
        symbol_a="A/USD",
        symbol_b="B/USD",
        previous_a=100.0,
        previous_b=100.0,
        current_a=101.0,
        current_b=100.0,
        now_ms=1000,
        economy=economy,
    )
    assert motion_bps>0
    assert motion_kind=="DISSENT"
    assert quorum.explicit_dissent_present is True
    assert quorum.quorum_formed is True
    assert quorum.execution_eligible is False
    assert quorum.promotion_eligible is False
    assert len(issue.bounty_ids)>=1

def test_live_ensemble_follow_can_be_resolved_for_treatment():
    feed=FakeFeed()
    frame=_world_frame(
        pair_id="A/USD__B/USD",
        symbol_a="A/USD",
        symbol_b="B/USD",
        now_ms=1000,
        feed=feed,
    )
    forecast=SimpleNamespace(
        forecast_id="f-follow",
        direction="LONG_A_SHORT_B",
        expected_relative_move_bps=8.0,
        uncertainty=2.0,
        horizon_seconds=30,
    )
    diagnostics=SimpleNamespace(
        stability_score=.8,
        half_life_seconds=20.0,
        hedge_alpha=0.0,
        hedge_ratio=1.0,
        spread_last=0.01,
        ou_equilibrium=0.0,
    )
    economy=QueenPollenEconomy()
    (
        quorum,
        issue,
        motion_bps,
        motion_kind,
        treatment_admitted,
        treatment_resolution,
        music_metrics,
    )=_ensemble(
        forecast=forecast,
        diagnostics=diagnostics,
        frame=frame,
        pair_id="A/USD__B/USD",
        symbol_a="A/USD",
        symbol_b="B/USD",
        previous_a=100.0,
        previous_b=100.0,
        current_a=101.0,
        current_b=100.0,
        now_ms=1000,
        economy=economy,
    )
    assert motion_kind == "FOLLOW"
    assert quorum.quorum_formed is True
    assert quorum.explicit_dissent_present is False
    assert treatment_admitted is True
    assert treatment_resolution == "ADMIT_RESOLVED"