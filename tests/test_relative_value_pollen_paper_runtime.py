from __future__ import annotations

from pathlib import Path

from strategies.relative_value_lab.contracts import ForwardRelativeForecast, RelativeMarketState, RELATIVE_VALUE_AUTHORITY
from strategies.relative_value_lab.pollen_paper_runtime import ProspectivePollenPaperRuntime
from strategies.relative_value_lab.polyphonic_quorum import PolyphonicQuorumReceipt


WS="ws-runtime"
WH="sha256:"+"f"*64


def state(ts,spread):
    return RelativeMarketState(
        schema="hivenance_relative_market_state_v1",
        pair_id="A__B",
        timestamp_ms=ts,
        spread=spread,
        spread_zscore=0.0,
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
    )


def forecast(fid="f1",ts=1000):
    return ForwardRelativeForecast(
        schema="hivenance_forward_relative_forecast_v1",
        forecast_id=fid,
        pair_id="A__B",
        timestamp_ms=ts,
        horizon_seconds=10,
        model_id="paper",
        expected_relative_move_bps=10.0,
        prediction_lower_bps=None,
        prediction_upper_bps=None,
        probability_positive_gross=None,
        expected_cost_bps=3.0,
        expected_net_bps=7.0,
        uncertainty=None,
        calibration_state="TEST",
        abstain=False,
        reason="test",
        inputs={"hedge_alpha": 0.0, "hedge_ratio": 1.0},
        direction="LONG_A_SHORT_B",
        authority=RELATIVE_VALUE_AUTHORITY,
        execution_eligible=False,
    )


def quorum(fid="f1",last_note=900,formed=True):
    return PolyphonicQuorumReceipt(
        schema="hivenance_polyphonic_quorum_v1",
        quorum_id=f"q-{fid}-{last_note}",
        hypothesis_id=fid,
        world_state_id=WS,
        world_state_hash=WH,
        note_count=2,
        first_note_ms=800,
        last_note_ms=last_note,
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


def test_runtime_freezes_pre_forecast_quorum_for_treatment(tmp_path: Path):
    runtime=ProspectivePollenPaperRuntime(ledger_path=tmp_path/"ledger.jsonl")
    reg=runtime.register(
        forecast=forecast(),
        state=state(1000,-0.01),
        quorum=quorum(last_note=900),
    )
    assert reg.treatment_eligible_at_registration is True
    batch=runtime.settle(state(11000,-0.009))
    assert len(batch.settlements)==1
    assert batch.comparison.control.selected_count==1
    assert batch.comparison.treatment.selected_count==1
    assert batch.comparison.treatment.cumulative_net_bps==7.0
    assert runtime.pending()==0


def test_runtime_cannot_upgrade_forecast_with_late_quorum():
    runtime=ProspectivePollenPaperRuntime()
    reg=runtime.register(
        forecast=forecast(),
        state=state(1000,-0.01),
        quorum=quorum(last_note=1100),
    )
    assert reg.treatment_eligible_at_registration is False

    # A later perfect quorum is irrelevant because registration was frozen.
    late=quorum(last_note=900)
    assert late.quorum_formed is True

    batch=runtime.settle(state(11000,-0.009))
    assert batch.comparison.control.selected_count==1
    assert batch.comparison.treatment.selected_count==0


def test_runtime_rejects_quorum_for_different_forecast():
    runtime=ProspectivePollenPaperRuntime()
    reg=runtime.register(
        forecast=forecast("f1"),
        state=state(1000,-0.01),
        quorum=quorum(fid="other",last_note=900),
    )
    assert reg.treatment_eligible_at_registration is False


def test_runtime_ledger_remains_research_only(tmp_path: Path):
    path=tmp_path/"ledger.jsonl"
    runtime=ProspectivePollenPaperRuntime(ledger_path=path)
    runtime.register(
        forecast=forecast(),
        state=state(1000,-0.01),
        quorum=quorum(last_note=900),
    )
    runtime.settle(state(11000,-0.009))
    text=path.read_text()
    assert "execution_eligible" in text
    assert '"execution_eligible": false' in text
    assert '"promotion_eligible": false' in text

def test_runtime_settles_raw_prices_with_frozen_relationship():
    runtime=ProspectivePollenPaperRuntime()
    runtime.register(
        forecast=forecast(),
        state=state(1000,0.0),
        quorum=quorum(last_note=900),
    )
    batch=runtime.settle_prices(
        pair_id="A__B",
        timestamp_ms=11000,
        price_a=101.0,
        price_b=100.0,
    )
    assert len(batch.settlements)==1
    assert batch.comparison.control.selected_count==1
    assert batch.comparison.treatment.selected_count==1
