from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from statistics import mean


DB = "data/swarm_data.db"

TABLES = (
    (
        1,
        "full_organism_selector_settlements",
    ),
    (
        2,
        "full_organism_selector_settlements_v2",
    ),
    (
        3,
        "full_organism_selector_settlements_v3",
    ),
)


def load_best_settlements(con):
    by_freeze = {}

    for version, table in TABLES:
        rows = con.execute(
            f"""
            SELECT
                s.settlement_id,
                s.freeze_id,
                s.settled_ts,
                s.payload AS settlement_payload,

                f.run_id,
                f.observed_ts,
                f.target_ts,
                f.symbol,
                f.selector_rank,
                f.selector_score,
                f.selected,
                f.blind_rank,
                f.blind_selected,
                f.payload AS freeze_payload
            FROM "{table}" s
            JOIN full_organism_selector_freezes f
              ON f.freeze_id=s.freeze_id
            ORDER BY
                f.run_id,
                f.symbol,
                f.freeze_id
            """
        ).fetchall()

        for row in rows:
            freeze_id = str(
                row["freeze_id"]
            )

            current = by_freeze.get(
                freeze_id
            )

            if (
                current is None
                or version
                > current["version"]
            ):
                by_freeze[
                    freeze_id
                ] = {
                    "version": version,
                    "table": table,
                    "row": row,
                }

    return tuple(
        by_freeze.values()
    )


def economic_truth(item):
    row = item["row"]

    freeze = json.loads(
        row["freeze_payload"]
        or "{}"
    )

    settlement = json.loads(
        row["settlement_payload"]
        or "{}"
    )

    entry = settlement.get(
        "entry_price"
    )

    exit_price = settlement.get(
        "exit_price"
    )

    cost = settlement.get(
        "realized_roundtrip_cost_bps"
    )

    if (
        entry is None
        or exit_price is None
        or cost is None
    ):
        raise ValueError(
            "selector_settlement_missing_economic_truth:"
            + str(
                row["freeze_id"]
            )
        )

    entry = float(entry)
    exit_price = float(
        exit_price
    )
    cost = float(cost)

    if entry <= 0:
        raise ValueError(
            "selector_entry_price_invalid:"
            + str(
                row["freeze_id"]
            )
        )

    signed_move = (
        (
            exit_price
            / entry
        )
        - 1.0
    ) * 10_000.0

    return {
        "freeze_id":
            str(
                row["freeze_id"]
            ),
        "settlement_id":
            str(
                row["settlement_id"]
            ),
        "run_id":
            str(
                row["run_id"]
            ),
        "symbol":
            str(
                row["symbol"]
            ),
        "observed_ts":
            float(
                row["observed_ts"]
            ),
        "target_ts":
            float(
                row["target_ts"]
            ),
        "selector_rank":
            int(
                row["selector_rank"]
            ),
        "selector_score":
            float(
                row["selector_score"]
            ),
        "selected":
            bool(
                row["selected"]
            ),
        "blind_rank":
            (
                None
                if row["blind_rank"]
                is None
                else int(
                    row["blind_rank"]
                )
            ),
        "blind_selected":
            (
                None
                if row[
                    "blind_selected"
                ]
                is None
                else bool(
                    row[
                        "blind_selected"
                    ]
                )
            ),
        "signed_move_bps":
            signed_move,
        "absolute_move_bps":
            abs(
                signed_move
            ),
        "cost_bps":
            cost,
        "net_opportunity_bps":
            abs(
                signed_move
            )
            - cost,
        "version":
            int(
                item["version"]
            ),
        "source_table":
            item["table"],
        "world_state_hash":
            str(
                settlement.get(
                    "canonical_world_state_hash",
                    freeze.get(
                        "canonical_world_state_hash",
                        "",
                    ),
                )
            ),
        "evidence_root":
            str(
                settlement.get(
                    "evidence_root",
                    freeze.get(
                        "evidence_root",
                        "",
                    ),
                )
            ),
    }


def mean_or_none(xs):
    return (
        mean(xs)
        if xs
        else None
    )


con = sqlite3.connect(
    DB
)
con.row_factory = sqlite3.Row

items = load_best_settlements(
    con
)

truth = [
    economic_truth(item)
    for item in items
]

print(
    "HIVENANCE_PHASE12_COINSELECTOR_MULTICOHORT"
)

print(
    "unique_freezes=",
    len(truth),
)

print(
    "source_versions=",
    {
        version:
            sum(
                1
                for x in truth
                if x["version"]
                == version
            )
        for version
        in (1,2,3)
    },
)

by_run = defaultdict(
    list
)

for row in truth:
    by_run[
        row["run_id"]
    ].append(
        row
    )

cohort_deltas = {}
cohort_selector = {}
cohort_blind = {}

all_selector = []
all_blind = []

for run_id, rows in sorted(
    by_run.items()
):
    selector_rows = [
        x
        for x in rows
        if x["selected"]
    ]

    blind_rows = [
        x
        for x in rows
        if x["blind_selected"]
        is True
    ]

    rejected_rows = [
        x
        for x in rows
        if not x["selected"]
    ]

    blind_rejected = [
        x
        for x in rows
        if x["blind_selected"]
        is False
    ]

    selector_net = [
        x[
            "net_opportunity_bps"
        ]
        for x in selector_rows
    ]

    blind_net = [
        x[
            "net_opportunity_bps"
        ]
        for x in blind_rows
    ]

    selector_mean = (
        mean_or_none(
            selector_net
        )
    )

    blind_mean = (
        mean_or_none(
            blind_net
        )
    )

    delta = (
        None
        if (
            selector_mean
            is None
            or blind_mean
            is None
        )
        else (
            selector_mean
            - blind_mean
        )
    )

    if selector_net:
        all_selector.extend(
            selector_net
        )

    if blind_net:
        all_blind.extend(
            blind_net
        )

    if delta is not None:
        cohort_deltas[
            run_id
        ] = delta

        cohort_selector[
            run_id
        ] = selector_mean

        cohort_blind[
            run_id
        ] = blind_mean

    print()
    print(run_id)

    print(
        "  rows=",
        len(rows),
    )

    print(
        "  versions=",
        sorted({
            x["version"]
            for x in rows
        }),
    )

    print(
        "  selector_selected=",
        len(
            selector_rows
        ),
    )

    print(
        "  blind_selected=",
        len(
            blind_rows
        ),
    )

    print(
        "  selector_rejected=",
        len(
            rejected_rows
        ),
    )

    print(
        "  blind_rejected=",
        len(
            blind_rejected
        ),
    )

    print(
        "  selector_mean_net_opportunity_bps=",
        selector_mean,
    )

    print(
        "  blind_mean_net_opportunity_bps=",
        blind_mean,
    )

    print(
        "  selector_minus_blind_bps=",
        delta,
    )

    print(
        "  selector_positive_opportunities=",
        sum(
            x[
                "net_opportunity_bps"
            ] > 0
            for x in selector_rows
        ),
    )

    print(
        "  blind_positive_opportunities=",
        sum(
            x[
                "net_opportunity_bps"
            ] > 0
            for x in blind_rows
        ),
    )


dependence_adjusted = len(
    cohort_deltas
)

positive_cohorts = sum(
    x > 0
    for x in cohort_deltas.values()
)

negative_cohorts = sum(
    x < 0
    for x in cohort_deltas.values()
)

zero_cohorts = sum(
    x == 0
    for x in cohort_deltas.values()
)

print()
print(
    "===== COINSELECTOR DEPENDENCE-NORMALIZED RESULT ====="
)

print(
    "cohort_selector_means=",
    {
        k:
            round(v,6)
        for k,v
        in sorted(
            cohort_selector.items()
        )
    },
)

print(
    "cohort_blind_means=",
    {
        k:
            round(v,6)
        for k,v
        in sorted(
            cohort_blind.items()
        )
    },
)

print(
    "cohort_deltas_bps=",
    {
        k:
            round(v,6)
        for k,v
        in sorted(
            cohort_deltas.items()
        )
    },
)

print(
    "dependence_adjusted_worlds=",
    dependence_adjusted,
)

print(
    "positive_cohorts=",
    positive_cohorts,
)

print(
    "negative_cohorts=",
    negative_cohorts,
)

print(
    "zero_cohorts=",
    zero_cohorts,
)

print(
    "minimum_independent_worlds_met=",
    dependence_adjusted >= 5,
)

print(
    "pooled_selector_mean_net_bps=",
    mean_or_none(
        all_selector
    ),
)

print(
    "pooled_blind_mean_net_bps=",
    mean_or_none(
        all_blind
    ),
)

if (
    all_selector
    and all_blind
):
    print(
        "pooled_selector_minus_blind_bps=",
        mean(
            all_selector
        )
        - mean(
            all_blind
        ),
    )

if not cohort_deltas:
    classification = (
        "NO_COMPARABLE_COHORTS"
    )
elif dependence_adjusted < 5:
    if positive_cohorts == dependence_adjusted:
        classification = (
            "POSITIVE_BUT_INSUFFICIENT_INDEPENDENCE"
        )
    elif negative_cohorts == dependence_adjusted:
        classification = (
            "NEGATIVE_BUT_INSUFFICIENT_INDEPENDENCE"
        )
    else:
        classification = (
            "MIXED_AND_INSUFFICIENT_INDEPENDENCE"
        )
elif positive_cohorts == dependence_adjusted:
    classification = (
        "HISTORICALLY_USEFUL_CANDIDATE"
    )
elif negative_cohorts == dependence_adjusted:
    classification = (
        "HISTORICALLY_HARMFUL_CANDIDATE"
    )
else:
    classification = (
        "HISTORICALLY_MIXED"
    )

print(
    "classification=",
    classification,
)

print(
    "historical_selection_effect_only=True"
)

print(
    "directional_trading_edge_claimed=False"
)

print(
    "prospective_profitability_proved=False"
)

print(
    "execution_eligible=False"
)

print(
    "promotion_eligible=False"
)

con.close()
