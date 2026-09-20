from __future__ import annotations

from collections import Counter
from statistics import mean

from strategies.relative_value_lab.historical_real_corpus import (
    HistoricalRealCorpus,
)
from strategies.relative_value_lab.historical_real_settlement_tape import (
    real_settlement_truth,
)
from strategies.relative_value_lab.historical_reconstruction_input import (
    reconstruction_input_from_case,
)
from strategies.relative_value_lab.historical_feature_reconstruction import (
    feature_from_reconstruction,
)
from strategies.relative_value_lab.historical_organ_reconstruction import (
    reconstruct_historical_organs,
)
from strategies.relative_value_lab.historical_phoenix_replay import (
    default_historical_competition,
    replay_historical_phoenix,
)
from strategies.relative_value_lab.historical_forecast_outcome import (
    forecast_outcome_on_real_tape,
)
from strategies.relative_value_lab.historical_paired_world import (
    score_historical_pair,
)


MASKS = {
    "NO_COMPARISON": {
        "organ_id":
            "comparison_engine",
        "disabled_organs": (
            "comparison_engine",
        ),
        "challenge_scope":
            "comparison_engine",
        "availability_key":
            "comparison_engine",
        "availability_states": {
            "INVOKABLE",
        },
    },

    "NO_LIQUIDITY": {
        "organ_id":
            "edge_ecology",
        "disabled_organs": (
            "edge_ecology",
        ),
        "challenge_scope":
            "edge_ecology",
        "availability_key":
            "liquidity",
        "availability_states": {
            "INVOKABLE",
        },
    },

    "NO_TEMPORAL_PARTICIPATION": {
        "organ_id":
            "temporal_participation_bee",
        "disabled_organs": (
            "temporal_participation_bee",
        ),
        "challenge_scope":
            "temporal_participation_bee",
        "availability_key":
            "temporal_participation_bee",
        "availability_states": {
            "INVOKABLE",
            "INVOKABLE_LOW_HISTORY",
        },
    },
}


def by_model(replay):
    out = {}

    for f in replay.forecasts:
        key = (
            str(f.model_id),
            int(f.horizon_seconds),
        )

        if key in out:
            raise ValueError(
                "duplicate_forecast_identity:"
                + repr(key)
            )

        out[key] = f

    return out


cases = HistoricalRealCorpus(
    "data/swarm_data.db"
).load_cases()

results = {
    mask: []
    for mask in MASKS
}

stats = {
    mask: Counter()
    for mask in MASKS
}

for case in cases:
    inp = reconstruction_input_from_case(
        case
    )

    feature = feature_from_reconstruction(
        inp
    )

    bundle = reconstruct_historical_organs(
        inp,
        feature,
    )

    truth = real_settlement_truth(
        case
    )

    for mask_id, spec in MASKS.items():
        if (
            bundle.status[
                spec["availability_key"]
            ]
            not in spec[
                "availability_states"
            ]
        ):
            stats[
                mask_id
            ]["not_testable"] += 1

            continue

        competition = (
            default_historical_competition()
        )

        full = replay_historical_phoenix(
            inp,
            organ_bundle=bundle,
            competition=competition,
            challenge_scope=(
                spec["challenge_scope"]
            ),
        )

        blind = replay_historical_phoenix(
            inp,
            organ_bundle=bundle,
            competition=competition,
            disabled_organs=(
                spec["disabled_organs"]
            ),
            challenge_scope=(
                spec["challenge_scope"]
            ),
        )

        if (
            full.world_state_id
            != blind.world_state_id
            or full.world_state_hash
            != blind.world_state_hash
        ):
            raise ValueError(
                "outcome_prosecution_world_drift"
            )

        fm = by_model(
            full
        )

        bm = by_model(
            blind
        )

        if set(fm) != set(bm):
            raise ValueError(
                "outcome_prosecution_forecast_identity_drift"
            )

        stats[
            mask_id
        ]["testable_worlds"] += 1

        world_changed = False

        for identity in sorted(fm):
            a = fm[identity]
            b = bm[identity]

            a_decision = (
                bool(a.abstain),
                str(a.direction),
            )

            b_decision = (
                bool(b.abstain),
                str(b.direction),
            )

            if a_decision == b_decision:
                continue

            world_changed = True

            full_outcome = (
                forecast_outcome_on_real_tape(
                    forecast=a,
                    truth=truth,
                    world_state_id=(
                        case.world_state_id
                    ),
                    world_state_hash=(
                        case.world_state_hash
                    ),
                )
            )

            blind_outcome = (
                forecast_outcome_on_real_tape(
                    forecast=b,
                    truth=truth,
                    world_state_id=(
                        case.world_state_id
                    ),
                    world_state_hash=(
                        case.world_state_hash
                    ),
                )
            )

            pair = score_historical_pair(
                mask_id=mask_id,
                full=full_outcome,
                masked=blind_outcome,
            )

            results[
                mask_id
            ].append(
                (
                    case,
                    identity,
                    pair,
                )
            )

            stats[
                mask_id
            ]["decision_changes"] += 1

            delta = float(
                pair.paired_delta_bps
            )

            if delta > 0:
                stats[
                    mask_id
                ]["helpful_changes"] += 1
            elif delta < 0:
                stats[
                    mask_id
                ]["harmful_changes"] += 1
            else:
                stats[
                    mask_id
                ]["neutral_changes"] += 1

            # Most current challenges are vetoes:
            # FULL abstains, organ-blind path trades.
            if (
                full_outcome.abstain
                and not blind_outcome.abstain
            ):
                blind_net = float(
                    blind_outcome.realized_net_bps
                )

                if blind_net < 0:
                    stats[
                        mask_id
                    ]["avoided_losses"] += 1
                elif blind_net > 0:
                    stats[
                        mask_id
                    ]["suppressed_winners"] += 1
                else:
                    stats[
                        mask_id
                    ]["suppressed_flat"] += 1

        if world_changed:
            stats[
                mask_id
            ]["changed_worlds"] += 1


print(
    "HIVENANCE_PHASE12_REAL_ORGAN_OUTCOMES"
)

for mask_id, spec in MASKS.items():
    rows = results[
        mask_id
    ]

    deltas = [
        float(pair.paired_delta_bps)
        for _, _, pair in rows
        if pair.paired_delta_bps
        is not None
    ]

    # All 48 Phase-4 cases belong to one observation cohort/run.
    dependence_clusters = {
        case.observation_run_id
        for case, _, _ in rows
    }

    print()
    print(mask_id)

    for key in (
        "testable_worlds",
        "not_testable",
        "changed_worlds",
        "decision_changes",
        "helpful_changes",
        "harmful_changes",
        "neutral_changes",
        "avoided_losses",
        "suppressed_winners",
        "suppressed_flat",
    ):
        print(
            f"  {key}=",
            stats[mask_id][key],
        )

    print(
        "  mean_paired_delta_bps=",
        (
            mean(deltas)
            if deltas
            else None
        ),
    )

    print(
        "  dependence_adjusted_worlds=",
        len(
            dependence_clusters
        ),
    )

    print(
        "  minimum_independent_worlds_met=",
        len(
            dependence_clusters
        ) >= 5,
    )

    print(
        "  provisional_classification=",
        (
            "INSUFFICIENT_INDEPENDENT_WORLDS"
            if (
                rows
                and len(
                    dependence_clusters
                ) < 5
            )
            else (
                "NO_CAUSAL_EFFECT"
                if not rows
                else "READY_FOR_AGGREGATION"
            )
        ),
    )

    print(
        "  changed_examples=",
        [
            {
                "symbol":
                    case.symbol,
                "model":
                    identity[0],
                "full":
                    (
                        pair.full_direction,
                        pair.full_net_bps,
                    ),
                "blind":
                    (
                        pair.masked_direction,
                        pair.masked_net_bps,
                    ),
                "delta_bps":
                    pair.paired_delta_bps,
            }
            for case, identity, pair
            in rows[:10]
        ],
    )

print()
print(
    "historical_reconstruction_only=True"
)
print(
    "prospective_usefulness_proved=False"
)
print(
    "execution_eligible=False"
)
print(
    "promotion_eligible=False"
)
