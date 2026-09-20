from __future__ import annotations

from collections import Counter

from strategies.relative_value_lab.historical_real_corpus import (
    HistoricalRealCorpus,
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


MASKS = {
    "NO_COMPARISON": {
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
        "challenge_scope":
            "edge_ecology",
        # In this corpus LIQUIDITY is the only lawful EdgeEcology voice,
        # so disabling edge_ecology is precisely the liquidity ablation.
        "disabled_organs": (
            "edge_ecology",
        ),
        "availability_key":
            "liquidity",
        "availability_states": {
            "INVOKABLE",
        },
    },
    "NO_TEMPORAL_PARTICIPATION": {
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


def surface(f):
    return (
        bool(f.abstain),
        str(f.direction),
        f.expected_move_bps,
        f.expected_net_bps,
        f.probability_positive_net,
        str(f.reason),
    )


def decision_surface(f):
    return (
        bool(f.abstain),
        str(f.direction),
    )


def by_model(replay):
    out = {}

    for f in replay.forecasts:
        key = (
            f.model_id,
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

summary = {
    mask: Counter()
    for mask in MASKS
}

changed_examples = {
    mask: []
    for mask in MASKS
}

for index, case in enumerate(
    cases,
    1,
):
    inp = (
        reconstruction_input_from_case(
            case
        )
    )

    feature = (
        feature_from_reconstruction(
            inp
        )
    )

    bundle = (
        reconstruct_historical_organs(
            inp,
            feature,
        )
    )

    # One competition instance per historical world.
    # FULL and masks therefore use identical current model configuration.
    competition = (
        default_historical_competition()
    )

    # Raw competition is identical across masks. Each organ is then
    # prosecuted independently using the exact veto-only semantics from
    # g0_live_loop.py.
    raw_full = replay_historical_phoenix(
        inp,
        organ_bundle=bundle,
        competition=competition,
    )

    print(
        f"{index:02d}/48 "
        f"{case.symbol:<14}",
        end="",
    )

    for mask_name, spec in MASKS.items():
        state = bundle.status[
            spec[
                "availability_key"
            ]
        ]

        if (
            state
            not in spec[
                "availability_states"
            ]
        ):
            summary[
                mask_name
            ][
                "not_testable"
            ] += 1

            print(
                f" {mask_name}=N/A",
                end="",
            )

            continue

        full = (
            replay_historical_phoenix(
                inp,
                organ_bundle=bundle,
                competition=competition,
                challenge_scope=(
                    spec["challenge_scope"]
                ),
            )
        )

        masked = (
            replay_historical_phoenix(
                inp,
                organ_bundle=bundle,
                competition=competition,
                disabled_organs=(
                    spec[
                        "disabled_organs"
                    ]
                ),
                challenge_scope=(
                    spec["challenge_scope"]
                ),
            )
        )

        full_models = by_model(
            full
        )

        if (
            masked.world_state_id
            != full.world_state_id
            or masked.world_state_hash
            != full.world_state_hash
        ):
            raise ValueError(
                "paired_ablation_world_drift:"
                + mask_name
                + ":"
                + case.symbol
            )

        masked_models = by_model(
            masked
        )

        if (
            set(masked_models)
            != set(full_models)
        ):
            summary[
                mask_name
            ][
                "forecast_identity_changed"
            ] += 1

        identities = sorted(
            set(full_models)
            | set(masked_models)
        )

        changed_models = 0
        decision_changes = 0
        direction_changes = 0
        abstention_changes = 0
        expected_net_changes = 0

        for identity in identities:
            a = full_models.get(
                identity
            )

            b = masked_models.get(
                identity
            )

            if (
                a is None
                or b is None
            ):
                changed_models += 1
                decision_changes += 1
                continue

            if surface(a) != surface(b):
                changed_models += 1

            if (
                decision_surface(a)
                != decision_surface(b)
            ):
                decision_changes += 1

            if (
                str(a.direction)
                != str(b.direction)
            ):
                direction_changes += 1

            if (
                bool(a.abstain)
                != bool(b.abstain)
            ):
                abstention_changes += 1

            if (
                a.expected_net_bps
                != b.expected_net_bps
            ):
                expected_net_changes += 1

        summary[
            mask_name
        ][
            "testable_worlds"
        ] += 1

        summary[
            mask_name
        ][
            "changed_models"
        ] += changed_models

        summary[
            mask_name
        ][
            "decision_changes"
        ] += decision_changes

        summary[
            mask_name
        ][
            "direction_changes"
        ] += direction_changes

        summary[
            mask_name
        ][
            "abstention_changes"
        ] += abstention_changes

        summary[
            mask_name
        ][
            "expected_net_changes"
        ] += expected_net_changes

        changed = (
            changed_models > 0
        )

        if changed:
            summary[
                mask_name
            ][
                "changed_worlds"
            ] += 1

            if (
                len(
                    changed_examples[
                        mask_name
                    ]
                )
                < 10
            ):
                changed_examples[
                    mask_name
                ].append(
                    {
                        "symbol":
                            case.symbol,
                        "changed_models":
                            changed_models,
                        "decision_changes":
                            decision_changes,
                        "direction_changes":
                            direction_changes,
                        "abstention_changes":
                            abstention_changes,
                        "expected_net_changes":
                            expected_net_changes,
                    }
                )

        print(
            f" {mask_name}="
            f"{'Δ' if changed else '='}",
            end="",
        )

    print()


print()
print(
    "HIVENANCE_PHASE12_REAL_ORGAN_CAUSALITY"
)

for mask_name in MASKS:
    row = summary[
        mask_name
    ]

    print()
    print(mask_name)

    for key in (
        "testable_worlds",
        "not_testable",
        "changed_worlds",
        "changed_models",
        "decision_changes",
        "direction_changes",
        "abstention_changes",
        "expected_net_changes",
        "forecast_identity_changed",
    ):
        print(
            f"  {key}=",
            row[key],
        )

    print(
        "  examples=",
        changed_examples[
            mask_name
        ],
    )

print()
print(
    "NO_HORIZON testable_worlds=0"
)
print(
    "NO_HORIZON reason=no_fresh_pre_t_horizon_context"
)
print(
    "execution_eligible=False"
)
print(
    "promotion_eligible=False"
)
