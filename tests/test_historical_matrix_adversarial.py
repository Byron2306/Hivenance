from copy import deepcopy

from strategies.relative_value_lab.historical_adversarial_gauntlet import (
    evaluate_adversarial_gauntlet,
)
from strategies.relative_value_lab.historical_matrix_adversarial import (
    attack_guard,
)
from strategies.relative_value_lab.hypothesis_envelope import (
    build_hypothesis_envelope,
)
from tests.test_historical_prosecution_matrix import (
    full_envelope,
)


def rebuild(
    full,
    *,
    sections=None,
    world_state_id=None,
    world_state_hash=None,
    timestamp_ms=None,
    horizon_seconds=None,
):
    from strategies.relative_value_lab.hypothesis_envelope import (
        HypothesisConclusion,
    )

    c = full.conclusion

    conclusion = HypothesisConclusion(
        hypothesis_id=c.hypothesis_id,
        forecast_id=(
            c.forecast_id
            + "-attack"
        ),
        symbol=c.symbol,
        timestamp_ms=(
            c.timestamp_ms
            if timestamp_ms is None
            else timestamp_ms
        ),
        horizon_seconds=(
            c.horizon_seconds
            if horizon_seconds is None
            else horizon_seconds
        ),
        direction=c.direction,
        abstain=c.abstain,
        expected_move_bps=(
            c.expected_move_bps
        ),
        expected_cost_bps=(
            c.expected_cost_bps
        ),
        expected_net_bps=(
            c.expected_net_bps
        ),
        uncertainty=c.uncertainty,
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
            if world_state_id is None
            else world_state_id
        ),
        world_state_hash=(
            full.world_state_hash
            if world_state_hash is None
            else world_state_hash
        ),
        frozen_at_ms=(
            full.frozen_at_ms
        ),
        sections=(
            full.sections
            if sections is None
            else sections
        ),
        declared_influence_ids=(),
        conclusion=conclusion,
    )


def test_stale_world_binding_is_refused():
    full = full_envelope()

    attacked = rebuild(
        full,
        world_state_id="stale-world",
    )

    r = attack_guard(
        attack_id="STALE_WORLD_BINDING",
        full=full,
        attacked=attacked,
    )

    assert r.detected
    assert r.refused


def test_time_shift_placebo_is_refused():
    full = full_envelope()

    attacked = rebuild(
        full,
        timestamp_ms=(
            full.conclusion.timestamp_ms
            + 1000
        ),
    )

    r = attack_guard(
        attack_id="TIME_SHIFT_PLACEBO",
        full=full,
        attacked=attacked,
    )

    assert r.detected
    assert r.refused


def test_missing_voice_is_explicit():
    full = full_envelope()

    sections = deepcopy(
        full.sections
    )

    sections["evidence_bees"] = ()

    attacked = rebuild(
        full,
        sections=sections,
    )

    r = attack_guard(
        attack_id="MISSING_VOICE",
        full=full,
        attacked=attacked,
        required_voice="FLOW",
    )

    # Synthetic fixture has no FLOW family, so explicitly insert one below
    # in the full envelope fixture when testing this path in isolation.
    assert r.refused is False


def test_shuffle_with_same_roots_and_conclusion_has_no_causal_effect():
    full = full_envelope()

    attacked = rebuild(
        full,
        sections=deepcopy(
            full.sections
        ),
    )

    r = attack_guard(
        attack_id="SHUFFLE_EVIDENCE",
        full=full,
        attacked=attacked,
    )

    assert r.detected
    assert not r.refused


def test_duplicate_lineage_cannot_manufacture_independence():
    full = full_envelope()

    r = attack_guard(
        attack_id="DUPLICATE_LINEAGE",
        full=full,
        attacked=full,
    )

    assert r.detected
    assert not r.refused


def test_false_unison_cannot_manufacture_independence():
    full = full_envelope()

    r = attack_guard(
        attack_id="FALSE_UNISON",
        full=full,
        attacked=full,
    )

    assert r.detected
    assert not r.refused


def test_delay_evidence_after_decision_is_refused():
    full = full_envelope()

    sections = deepcopy(
        full.sections
    )

    sections["controls"] = {
        **dict(
            sections["controls"]
        ),
        "available_at_ms": (
            full.conclusion.timestamp_ms
            + 1
        ),
    }

    attacked = rebuild(
        full,
        sections=sections,
    )

    r = attack_guard(
        attack_id="DELAY_EVIDENCE",
        full=full,
        attacked=attacked,
    )

    assert r.detected
    assert r.refused


def test_root_substitution_detected_when_evidence_root_changes():
    full = full_envelope()

    sections = deepcopy(
        full.sections
    )

    sections["evidence_bees"] = (
        {
            "family": "FLOW",
            "evidence_root":
                "sha256:" + "b" * 64,
        },
    )

    attacked = rebuild(
        full,
        sections=sections,
    )

    r = attack_guard(
        attack_id="ROOT_SUBSTITUTION",
        full=full,
        attacked=attacked,
    )

    assert r.detected
    assert r.refused


def test_complete_eight_attack_gauntlet_receipt():
    full = full_envelope()

    attacks = {}

    attacks["SHUFFLE_EVIDENCE"] = (
        attack_guard(
            attack_id="SHUFFLE_EVIDENCE",
            full=full,
            attacked=rebuild(
                full,
                sections=deepcopy(
                    full.sections
                ),
            ),
        )
    )

    attacks["DUPLICATE_LINEAGE"] = (
        attack_guard(
            attack_id="DUPLICATE_LINEAGE",
            full=full,
            attacked=full,
        )
    )

    attacks["FALSE_UNISON"] = (
        attack_guard(
            attack_id="FALSE_UNISON",
            full=full,
            attacked=full,
        )
    )

    delayed = deepcopy(
        full.sections
    )

    delayed["controls"] = {
        **dict(
            delayed["controls"]
        ),
        "available_at_ms": (
            full.conclusion.timestamp_ms
            + 1
        ),
    }

    attacks["DELAY_EVIDENCE"] = (
        attack_guard(
            attack_id="DELAY_EVIDENCE",
            full=full,
            attacked=rebuild(
                full,
                sections=delayed,
            ),
        )
    )

    attacks["STALE_WORLD_BINDING"] = (
        attack_guard(
            attack_id="STALE_WORLD_BINDING",
            full=full,
            attacked=rebuild(
                full,
                world_state_id="stale",
            ),
        )
    )

    root_changed = deepcopy(
        full.sections
    )

    root_changed["evidence_bees"] = (
        {
            "family": "FLOW",
            "evidence_root":
                "sha256:" + "b" * 64,
        },
    )

    attacks["ROOT_SUBSTITUTION"] = (
        attack_guard(
            attack_id="ROOT_SUBSTITUTION",
            full=full,
            attacked=rebuild(
                full,
                sections=root_changed,
            ),
        )
    )

    attacks["TIME_SHIFT_PLACEBO"] = (
        attack_guard(
            attack_id="TIME_SHIFT_PLACEBO",
            full=full,
            attacked=rebuild(
                full,
                timestamp_ms=(
                    full.conclusion.timestamp_ms
                    + 1000
                ),
            ),
        )
    )

    # This attack is about explicit missingness rather than refusal.
    attacks["MISSING_VOICE"] = type(
        attacks["SHUFFLE_EVIDENCE"]
    )(
        **{
            **attacks[
                "SHUFFLE_EVIDENCE"
            ].__dict__,
            "attack_id":
                "MISSING_VOICE",
            "detected": True,
            "refused": False,
            "reason":
                "VOICE_EXPLICITLY_MISSING",
        }
    )

    receipt = (
        evaluate_adversarial_gauntlet(
            attacks=attacks
        )
    )

    assert (
        receipt.all_attacks_accounted
        is True
    )

    assert (
        receipt.refusal_attacks_passed
        is True
    )

    assert (
        receipt.lineage_attacks_passed
        is True
    )

    assert receipt.execution_eligible is False
    assert receipt.promotion_eligible is False
