from __future__ import annotations

import json
import sqlite3
from collections import defaultdict

DB = "data/swarm_data.db"

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

rows = con.execute(
    """
    SELECT
        hr.run_id AS hypothesis_run_id,
        hr.observation_run_id,
        f.forecast_id,
        f.symbol,
        f.ts AS forecast_ts,
        f.target_ts,
        f.horizon_seconds,
        f.model_id,
        f.direction,
        f.abstain,
        f.expected_cost_bps,
        o.settled_ts,
        o.exit_price,
        o.gross_return_bps,
        o.directional_return_bps,
        o.net_return_bps,
        o.payload AS outcome_payload
    FROM hypothesis_runs hr
    JOIN hypothesis_forecasts f
      ON f.run_id = hr.run_id
    JOIN hypothesis_outcomes o
      ON o.forecast_id = f.forecast_id
    ORDER BY
        hr.started_ts,
        f.symbol,
        f.ts,
        f.horizon_seconds,
        f.model_id
    """
).fetchall()

groups = defaultdict(list)

for r in rows:
    key = (
        str(r["hypothesis_run_id"]),
        str(r["observation_run_id"]),
        str(r["symbol"]),
        float(r["forecast_ts"]),
        int(r["horizon_seconds"]),
    )
    groups[key].append(r)

print(
    "HIVENANCE_PHASE12_HYPOTHESIS_WORLD_CANDIDATES"
)
print(
    "settled_forecast_rows=",
    len(rows),
)
print(
    "unique_world_horizons=",
    len(groups),
)

by_run = defaultdict(
    lambda: {
        "candidate_worlds": 0,
        "observation_bound": 0,
        "missing_observation": 0,
        "market_move_consistent": 0,
        "market_move_conflict": 0,
        "symbols": set(),
        "horizons": set(),
        "examples": [],
    }
)

for key, xs in groups.items():
    (
        hypothesis_run_id,
        observation_run_id,
        symbol,
        forecast_ts,
        horizon,
    ) = key

    stats = by_run[
        observation_run_id
    ]

    stats["candidate_worlds"] += 1
    stats["symbols"].add(symbol)
    stats["horizons"].add(horizon)

    gross_values = {
        round(
            float(x["gross_return_bps"]),
            12,
        )
        for x in xs
        if x["gross_return_bps"]
        is not None
    }

    if len(gross_values) == 1:
        stats[
            "market_move_consistent"
        ] += 1
    else:
        stats[
            "market_move_conflict"
        ] += 1

    obs = con.execute(
        """
        SELECT
            ts,
            symbol,
            payload
        FROM observation_snapshots
        WHERE run_id=?
          AND symbol=?
          AND ts<=?
        ORDER BY ts DESC
        LIMIT 1
        """,
        (
            observation_run_id,
            symbol,
            forecast_ts,
        ),
    ).fetchone()

    if obs is None:
        stats[
            "missing_observation"
        ] += 1
        continue

    stats[
        "observation_bound"
    ] += 1

    if len(
        stats["examples"]
    ) < 3:
        payload = {}

        try:
            payload = json.loads(
                obs["payload"] or "{}"
            )
        except Exception:
            pass

        values = (
            payload.get("values")
            if isinstance(
                payload.get("values"),
                dict,
            )
            else {}
        )

        fv = (
            values.get("feature_vector")
            if isinstance(
                values.get(
                    "feature_vector"
                ),
                dict,
            )
            else {}
        )

        stats["examples"].append(
            {
                "symbol":
                    symbol,
                "forecast_ts":
                    forecast_ts,
                "observation_ts":
                    float(obs["ts"]),
                "age_sec":
                    round(
                        forecast_ts
                        - float(obs["ts"]),
                        6,
                    ),
                "horizon_seconds":
                    horizon,
                "model_rows":
                    len(xs),
                "gross_return_bps":
                    (
                        next(
                            iter(
                                gross_values
                            )
                        )
                        if (
                            len(
                                gross_values
                            )
                            == 1
                        )
                        else None
                    ),
                "feature_vector_present":
                    bool(fv),
                "feature_vector_keys":
                    sorted(
                        fv.keys()
                    )[:30],
            }
        )


for run_id, stats in by_run.items():
    print()
    print(run_id)

    print(
        "  candidate_worlds=",
        stats[
            "candidate_worlds"
        ],
    )
    print(
        "  observation_bound=",
        stats[
            "observation_bound"
        ],
    )
    print(
        "  missing_observation=",
        stats[
            "missing_observation"
        ],
    )
    print(
        "  market_move_consistent=",
        stats[
            "market_move_consistent"
        ],
    )
    print(
        "  market_move_conflict=",
        stats[
            "market_move_conflict"
        ],
    )
    print(
        "  symbols=",
        len(
            stats["symbols"]
        ),
    )
    print(
        "  horizons=",
        sorted(
            stats["horizons"]
        ),
    )
    print(
        "  examples=",
        stats["examples"],
    )

eligible = [
    run_id
    for run_id, stats
    in by_run.items()
    if (
        stats[
            "candidate_worlds"
        ] > 0
        and stats[
            "observation_bound"
        ]
        == stats[
            "candidate_worlds"
        ]
        and stats[
            "market_move_conflict"
        ] == 0
    )
]

print()
print(
    "eligible_independent_cohorts=",
    len(eligible),
)
print(
    "eligible_run_ids=",
    eligible,
)
print(
    "execution_eligible=False"
)
print(
    "promotion_eligible=False"
)

con.close()
