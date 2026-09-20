from copy import deepcopy

import pytest

from strategies.relative_value_lab.contracts import (
    ForwardRelativeForecast,
)
from strategies.relative_value_lab.historical_envelope_outcome import (
    HistoricalSettlementTape,
)
from strategies.relative_value_lab.historical_prosecution_matrix import (
    HistoricalMatrixCase,
    run_historical_matrix_case,
)
from strategies.relative_value_lab.hypothesis_envelope import (
    HypothesisConclusion,
    build_hypothesis_envelope,
)
from strategies.relative_value_lab.hypothesis_envelope_assembly import (
    FullOrganismEnvelopeInputs,
    assemble_full_organism_envelope,
)
from strategies.relative_value_lab.world_score import (
    CanonicalWorldScore,
    ScoreObservation,
)


ROOT = "sha256:" + "a" * 64


def full_envelope():
    obs = ScoreObservation(
        observation_id="o",
        source_id="kraken",
        source_class="public_market",
        scope="BTC/USD",
        observed_at_ms=1000,
        received_at_ms=1000,
        evidence_root=ROOT,
        payload={"price": 100},
    )

    frame = CanonicalWorldScore.assemble(
        observations=(obs,),
        assembled_at_ms=1000,
        freshness_window_ms=100,
    )

    forecast = ForwardRelativeForecast(
        schema="rv",
        forecast_id="full",
        pair_id="BTC/USD",
        timestamp_ms=1000,
        horizon_seconds=300,
        model_id="full",
        expected_relative_move_bps=10,
        prediction_lower_bps=None,
        prediction_upper_bps=None,
        probability_positive_gross=None,
        expected_cost_bps=2,
        expected_net_bps=8,
        uncertainty=.2,
        calibration_state="TEST",
        abstain=False,
        reason="full",
        direction="UP",
    )

    def b(name):
        return {
            "receipt_id": name,
            "world_state_id":
                frame.world_state_id,
            "world_state_hash":
                frame.world_state_hash,
            "execution_eligible": False,
            "promotion_eligible": False,
        }

    inputs = FullOrganismEnvelopeInputs(
        canonical_score_frame=frame,
        world_state_page=b("world"),
        temporal_lattice=b("temporal"),
        evidence_bees=(b("bee"),),
        comparison_packet=b("comparison"),
        selection_state={
            **b("selection"),
            "selected": (
                "BTC/USD",
            ),
        },
        regime=b("regime"),
        worker_proposals=(b("worker"),),
        phoenix_hypotheses=(b("phoenix"),),
        crystal_learning_context=(b("learning"),),
        quorum=b("quorum"),
        pollen_state=b("pollen"),
        triune_scores=b("triune"),
        queen_receipt=b("queen"),
        queen_epoch=b("epoch"),
        recursive_research=b("recursive"),
        controls=b("controls"),
    )

    return assemble_full_organism_envelope(
        hypothesis_id="h",
        forecast=forecast,
        inputs=inputs,
        world_state_id=frame.world_state_id,
        world_state_hash=frame.world_state_hash,
        frozen_at_ms=1001,
        influence_ids=(),
    )


def case():
    return HistoricalMatrixCase(
        case_id="case-1",
        full_envelope=full_envelope(),
        settlement_tape=HistoricalSettlementTape(
            forecast_timestamp_ms=1000,
            horizon_seconds=300,
            settled_timestamp_ms=301000,
            realized_signed_move_bps=10,
            expected_cost_bps=2,
            source_forecast_id="source",
        ),
        dependence_cluster_id="cluster-1",
    )


def replay(plan, c):
    full = c.full_envelope

    sections = deepcopy(
        full.sections
    )

    sections["controls"] = {
        **dict(
            sections["controls"]
        ),
        "historical_mask":
            plan.mask_id,
        "mask_plan_id":
            plan.plan_id,
    }

    direction = (
        "DOWN"
        if plan.mask_id
        in {
            "NO_FLOW",
            "NO_QUEEN",
            "SIMPLE_REVERSION",
        }
        else "ABSTAIN"
        if plan.force_no_trade
        else "UP"
    )

    conclusion = HypothesisConclusion(
        hypothesis_id=(
            full.hypothesis_id
        ),
        forecast_id=(
            full.forecast_id
            + "-"
            + plan.mask_id
        ),
        symbol=(
            full.conclusion.symbol
        ),
        timestamp_ms=(
            full.conclusion.timestamp_ms
        ),
        horizon_seconds=(
            full.conclusion.horizon_seconds
        ),
        direction=direction,
        abstain=(
            direction == "ABSTAIN"
        ),
        expected_move_bps=(
            full.conclusion.expected_move_bps
        ),
        expected_cost_bps=(
            full.conclusion.expected_cost_bps
        ),
        expected_net_bps=(
            full.conclusion.expected_net_bps
        ),
        uncertainty=(
            full.conclusion.uncertainty
        ),
        influence_ids=(),
    )

    return build_hypothesis_envelope(
        hypothesis_id=(
            full.hypothesis_id
        ),
        forecast_id=(
            conclusion.forecast_id
        ),
        world_state_id=(
            full.world_state_id
        ),
        world_state_hash=(
            full.world_state_hash
        ),
        frozen_at_ms=1002,
        sections=sections,
        declared_influence_ids=(),
        conclusion=conclusion,
    )


def test_one_case_runs_complete_25_mask_roster():
    result = run_historical_matrix_case(
        case=case(),
        replay_mask=replay,
    )

    assert len(
        result.mask_replays
    ) == 25

    assert len(
        result.paired_deltas
    ) == 24

    assert (
        result.mask_replays[0].mask_id
        == "FULL_HIVE"
    )

    assert (
        result.mask_replays[0].envelope.envelope_id
        == result.full_envelope_id
    )


def test_all_counterfactual_envelopes_are_fresh():
    result = run_historical_matrix_case(
        case=case(),
        replay_mask=replay,
    )

    ids = [
        row.envelope.envelope_id
        for row in result.mask_replays
    ]

    assert len(ids) == len(
        set(ids)
    )


def test_matrix_preserves_one_observed_world():
    result = run_historical_matrix_case(
        case=case(),
        replay_mask=replay,
    )

    assert all(
        row.envelope.world_state_id
        == result.world_state_id
        for row in result.mask_replays
    )

    assert all(
        row.envelope.world_state_hash
        == result.world_state_hash
        for row in result.mask_replays
    )


def test_no_trade_is_abstention_counterfactual():
    result = run_historical_matrix_case(
        case=case(),
        replay_mask=replay,
    )

    row = next(
        x
        for x in result.paired_deltas
        if x.mask_id == "NO_TRADE"
    )

    assert row.masked_abstain is True
    assert row.abstention_changed is True


def test_known_direction_change_is_measured():
    result = run_historical_matrix_case(
        case=case(),
        replay_mask=replay,
    )

    row = next(
        x
        for x in result.paired_deltas
        if x.mask_id == "NO_FLOW"
    )

    assert row.direction_changed is True

    # FULL UP on +10 tape -> +8 after cost.
    # Masked DOWN -> -12 after cost.
    assert row.paired_delta_bps == 20


def test_callback_returning_original_full_envelope_for_mask_refuses():
    def bad(plan, c):
        return c.full_envelope

    with pytest.raises(
        ValueError,
        match="did_not_produce_fresh_envelope",
    ):
        run_historical_matrix_case(
            case=case(),
            replay_mask=bad,
        )


def test_cross_world_mask_refuses():
    original = replay

    def bad(plan, c):
        env = original(
            plan,
            c,
        )

        object.__setattr__(
            env,
            "world_state_id",
            "wrong-world",
        )

        return env

    with pytest.raises(
        ValueError,
        match="cross_world_id",
    ):
        run_historical_matrix_case(
            case=case(),
            replay_mask=bad,
        )


def test_matrix_never_grants_authority():
    result = run_historical_matrix_case(
        case=case(),
        replay_mask=replay,
    )

    assert result.execution_eligible is False
    assert result.promotion_eligible is False

    assert all(
        not x.execution_eligible
        and not x.promotion_eligible
        for x in result.mask_replays
    )
