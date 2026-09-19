from __future__ import annotations

from types import SimpleNamespace

from strategies.relative_value_lab.conducting_queen import QueenNotationToken
from strategies.relative_value_lab.pollen_economy import QueenPollenEconomy
from strategies.relative_value_lab.pollen_profit_lab import (
    PollenProfitExperiment,
    QueenPollenConductor,
)
from strategies.relative_value_lab.polyphonic_quorum import PolyphonicQuorumReceipt
from strategies.relative_value_lab.settlement import SettledRelativeForecast
from strategies.relative_value_lab.contracts import RELATIVE_VALUE_AUTHORITY


WS="ws-profit"
WH="sha256:"+"f"*64


def token(*,notation="CHALLENGE_CADENCE",issued=1000,expires=5000,intensity=.8):
    return QueenNotationToken(
        token_id="tok-"+notation,
        issued_to_role="loki_counterpoint",
        notation=notation,
        intensity=intensity,
        epoch_id="epoch-1",
        score_id="score-1",
        world_state_id=WS,
        world_state_hash=WH,
        issued_at_ms=issued,
        expires_at_ms=expires,
        required_companions=("harmony_law",),
        response_class="DISSENT_OR_SEARCH",
        source_score_sheet_ids=("tri-1",),
        maximum_uses=1,
    )


def queen_receipt(tokens):
    return SimpleNamespace(
        receipt_id="queen-1",
        hypothesis_id="h1",
        notation_tokens=tuple(tokens),
    )


def quorum(*,formed=True,last_note_ms=900):
    return PolyphonicQuorumReceipt(
        schema="hivenance_polyphonic_quorum_v1",
        quorum_id=f"q-{formed}-{last_note_ms}",
        hypothesis_id="h1",
        world_state_id=WS,
        world_state_hash=WH,
        note_count=2,
        first_note_ms=500,
        last_note_ms=last_note_ms,
        independent_root_count=2,
        family_count=2,
        evidence_root_count=2,
        roles_present=("CALL","COUNTERPOINT"),
        message_types=("DISSENT","WAGGLE"),
        directional_counterpoint_present=True,
        explicit_dissent_present=True,
        world_binding=1.0,
        phase_lock=.9,
        choreography=.9,
        role_coverage=1.0,
        lineage_independence=1.0,
        evidence_diversity=1.0,
        counterpoint_preservation=1.0,
        ensemble_lock=.9,
        quorum_formed=formed,
        reasons=("counterpoint_preserved",),
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
        promotion_eligible=False,
    )


def settled(fid,net,forecast_ts=1000):
    return SettledRelativeForecast(
        schema="hivenance_settled_relative_forecast_v1",
        forecast_id=fid,
        pair_id="A__B",
        model_id="paper-test",
        forecast_timestamp_ms=forecast_ts,
        target_timestamp_ms=forecast_ts+60_000,
        settled_timestamp_ms=forecast_ts+61_000,
        horizon_seconds=60,
        direction="LONG_A_SHORT_B",
        entry_spread=1.0,
        settled_spread=1.001,
        predicted_signed_move_bps=10.0,
        realized_signed_move_bps=10.0,
        realized_directional_gross_bps=net+4.0,
        expected_cost_bps=4.0,
        realized_directional_net_bps=float(net),
        forecast_error_bps=0.0,
        abstain=False,
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
    )


def test_queen_notation_issues_research_pollen_bounties():
    economy=QueenPollenEconomy()
    receipt=QueenPollenConductor().issue(
        queen=queen_receipt([
            token(notation="CHALLENGE_CADENCE"),
            token(notation="AMPLIFY_SEARCH",intensity=.6),
        ]),
        economy=economy,
    )
    assert receipt.bounty_types == ("POLLEN_DISSENT","POLLEN_SEARCH")
    assert len(receipt.bounty_ids) == 2
    assert receipt.execution_eligible is False
    assert receipt.promotion_eligible is False


def test_profit_experiment_requires_quorum_before_forecast_timestamp():
    exp=PollenProfitExperiment()
    exp.record(settlement=settled("f1",8.0,forecast_ts=1000),quorum=quorum(last_note_ms=900))
    exp.record(settlement=settled("f2",9.0,forecast_ts=1000),quorum=quorum(last_note_ms=1100))
    summary=exp.summary()
    assert summary.control.selected_count == 2
    assert summary.treatment.selected_count == 1
    assert summary.treatment.cumulative_net_bps == 8.0
    assert summary.selection_rate == .5


def test_profit_experiment_tracks_positive_streak_and_drawdown():
    exp=PollenProfitExperiment()
    exp.record(settlement=settled("f1",6.0),quorum=quorum())
    exp.record(settlement=settled("f2",4.0),quorum=quorum())
    exp.record(settlement=settled("f3",-3.0),quorum=quorum(formed=False))
    exp.record(settlement=settled("f4",5.0),quorum=quorum())
    summary=exp.summary()

    assert summary.control.cumulative_net_bps == 12.0
    assert summary.control.longest_positive_streak == 2
    assert summary.control.max_drawdown_bps == 3.0

    assert summary.treatment.selected_count == 3
    assert summary.treatment.cumulative_net_bps == 15.0
    assert summary.treatment.longest_positive_streak == 3
    assert summary.treatment.max_drawdown_bps == 0.0
    assert summary.cumulative_delta_bps == 3.0
    assert summary.execution_eligible is False
    assert summary.promotion_eligible is False
