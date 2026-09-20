from strategies.relative_value_lab.hypothesis_envelope import (
    REQUIRED_SECTIONS,
    HypothesisConclusion,
    build_hypothesis_envelope,
)
from strategies.relative_value_lab.world_score import (
    CanonicalWorldScore,
    ScoreObservation,
)


ROOT = "sha256:" + "a" * 64


def test_real_canonical_score_frame_can_be_frozen():
    obs = ScoreObservation(
        observation_id="o1",
        source_id="kraken",
        source_class="public_market",
        scope="BTC/USD",
        observed_at_ms=1000,
        received_at_ms=1001,
        evidence_root=ROOT,
        payload={
            "price": 100.0,
        },
    )

    frame = CanonicalWorldScore.assemble(
        observations=(obs,),
        assembled_at_ms=1002,
        freshness_window_ms=10000,
    )

    sections = {
        name: {
            "state": "TEST_PLACEHOLDER",
        }
        for name in REQUIRED_SECTIONS
    }

    sections[
        "canonical_score_frame"
    ] = frame

    conclusion = HypothesisConclusion(
        hypothesis_id="h-real",
        forecast_id="f-real",
        symbol="BTC/USD",
        timestamp_ms=1002,
        horizon_seconds=300,
        direction="ABSTAIN",
        abstain=True,
        expected_move_bps=None,
        expected_cost_bps=None,
        expected_net_bps=None,
        uncertainty=1.0,
        influence_ids=(),
    )

    envelope = build_hypothesis_envelope(
        hypothesis_id="h-real",
        forecast_id="f-real",
        world_state_id=(
            frame.world_state_id
        ),
        world_state_hash=(
            frame.world_state_hash
        ),
        frozen_at_ms=1002,
        sections=sections,
        declared_influence_ids=(),
        conclusion=conclusion,
    )

    frozen_frame = envelope.sections[
        "canonical_score_frame"
    ]

    assert (
        frozen_frame["world_state_id"]
        == frame.world_state_id
    )

    assert (
        frozen_frame["world_state_hash"]
        == frame.world_state_hash
    )

    assert envelope.execution_eligible is False
    assert envelope.promotion_eligible is False
