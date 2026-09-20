from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from statistics import mean
from datetime import datetime, timezone

from strategies.volatility_breakout.models import FeatureVector

from strategies.relative_value_lab.world_score import (
    ScoreObservation,
    CanonicalWorldScore,
)
from strategies.relative_value_lab.edge_ecology import (
    EdgeEcology,
)
from strategies.relative_value_lab.synthesis_runtime import (
    SynthesisRuntime,
)
from strategies.relative_value_lab.g0_hypothesis_adapter import (
    bind_synthesis_context,
)
from strategies.relative_value_lab.g0_forecast_challenge import (
    challenge_forecast,
)
from strategies.relative_value_lab.comparison_engine import (
    ComparisonEngine,
    ComparisonReference,
)
from strategies.relative_value_lab.historical_phoenix_replay import (
    default_historical_competition,
)


DB = "data/swarm_data.db"

MASKS = {
    "NO_COMPARISON": {
        "organ_id":
            "comparison_engine",
        "challenge_scope":
            "comparison_engine",
        "disabled_organs": (
            "comparison_engine",
        ),
    },

    "NO_LIQUIDITY": {
        "organ_id":
            "edge_ecology",
        "challenge_scope":
            "edge_ecology",
        "disabled_organs": (
            "edge_ecology",
        ),
    },
    "NO_CRYSTALS": {
        "organ_id":
            "crystals",
        "challenge_scope":
            None,
        "disabled_organs": (
            "crystals",
        ),
    },
    "NO_REGIME": {
        "organ_id":
            "regime_oracle",
        "challenge_scope":
            None,
        "disabled_organs": (
            "regime_oracle",
        ),
    },
    "NO_WORKERS": {
        "organ_id":
            "workers",
        "challenge_scope":
            None,
        "disabled_organs": (
            "workers",
            "worker_coalition",
        ),
    },
}


def digest(value):
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()

    return (
        "sha256:"
        + hashlib.sha256(raw).hexdigest()
    )


def feature_from_payload(payload):
    values = (
        payload.get("values")
        if isinstance(
            payload.get("values"),
            dict,
        )
        else {}
    )

    fv = values.get(
        "feature_vector"
    )

    if not isinstance(fv, dict):
        raise ValueError(
            "historical_feature_vector_missing"
        )

    return FeatureVector(
        **fv
    )


def frame_from_feature(feature):
    body = asdict(feature)

    root = digest(
        body
    )

    obs = ScoreObservation(
        observation_id=(
            digest(
                {
                    "root": root,
                    "symbol":
                        feature.symbol,
                    "timestamp_ms":
                        feature.timestamp_ms,
                }
            )[-24:]
        ),
        source_id="historical_hypothesis_observation",
        source_class="public_market_feature",
        scope=str(
            feature.symbol
        ),
        observed_at_ms=int(
            feature.timestamp_ms
        ),
        received_at_ms=int(
            feature.timestamp_ms
        ),
        evidence_root=root,
        payload=body,
    )

    frame = CanonicalWorldScore.assemble(
        observations=(obs,),
        assembled_at_ms=int(
            feature.timestamp_ms
        ),
        freshness_window_ms=180_000,
    )

    return frame, root


def liquidity_from_feature(
    feature,
):
    if (
        feature.book_imbalance is None
        or feature.depth_usd_25bps is None
        or feature.spread_bps is None
    ):
        return None

    total = max(
        0.0,
        float(
            feature.depth_usd_25bps
        ),
    )

    imbalance = max(
        -1.0,
        min(
            1.0,
            float(
                feature.book_imbalance
            ),
        ),
    )

    bid = (
        total
        * (1.0 + imbalance)
        / 2.0
    )

    ask = (
        total
        * (1.0 - imbalance)
        / 2.0
    )

    return EdgeEcology().snapshot(
        timestamp_ms=int(
            feature.timestamp_ms
        ),
        pair_id=str(
            feature.symbol
        ),
        voices=(
            EdgeEcology.liquidity_voice(
                bid_depth=bid,
                ask_depth=ask,
                spread_bps=float(
                    feature.spread_bps
                ),
            ),
        ),
    )



COMPARISON_FEATURES = (
    "volume_zscore",
    "volatility_expansion",
    "spread_bps",
    "book_imbalance",
    "return_zscore",
    "tradable_opportunity_score",
)


def finite_num(value):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None

    if x != x or abs(x) == float("inf"):
        return None

    return x


def comparison_feature_values(feature):
    values = (
        feature.values
        if isinstance(
            feature.values,
            dict,
        )
        else {}
    )

    return {
        "volume_zscore":
            finite_num(
                feature.volume_zscore
            ),
        "volatility_expansion":
            finite_num(
                feature.volatility_expansion
            ),
        "spread_bps":
            finite_num(
                feature.spread_bps
            ),
        "book_imbalance":
            finite_num(
                feature.book_imbalance
            ),
        "return_zscore":
            finite_num(
                getattr(
                    feature,
                    "return_zscore",
                    None,
                )
            ),
        "tradable_opportunity_score":
            finite_num(
                values.get(
                    "tradable_opportunity_score"
                )
            ),
    }


def comparison_reference(feature):
    root = digest(
        asdict(feature)
    )

    ts = int(
        feature.timestamp_ms
    )

    return ComparisonReference(
        reference_id=(
            "cmpref_"
            + root.split(":", 1)[1][:20]
        ),
        observed_at_ms=ts,
        symbol=str(
            feature.symbol
        ),
        utc_hour=(
            datetime.fromtimestamp(
                ts / 1000.0,
                tz=timezone.utc,
            ).hour
        ),
        features=(
            comparison_feature_values(
                feature
            )
        ),
        evidence_roots=(
            root,
        ),
        selected=None,
        event_label=None,
    )


def build_historical_comparison_refs(con):
    settled_runs = {
        str(row[0])
        for row in con.execute(
            """
            SELECT DISTINCT
                hr.observation_run_id
            FROM hypothesis_runs hr
            JOIN hypothesis_forecasts f
              ON f.run_id=hr.run_id
            JOIN hypothesis_outcomes o
              ON o.forecast_id=f.forecast_id
            """
        )
    }

    out = defaultdict(list)

    rows = con.execute(
        """
        SELECT
            run_id,
            symbol,
            ts,
            payload
        FROM observation_snapshots
        ORDER BY run_id, ts, symbol
        """
    ).fetchall()

    for row in rows:
        run_id = str(
            row["run_id"]
        )

        if run_id not in settled_runs:
            continue

        try:
            payload = json.loads(
                row["payload"]
                or "{}"
            )

            feature = (
                feature_from_payload(
                    payload
                )
            )
        except Exception:
            continue

        out[
            run_id
        ].append(
            comparison_reference(
                feature
            )
        )

    return {
        run_id: tuple(refs)
        for run_id, refs
        in out.items()
    }


def comparison_for_world(
    *,
    observation_run_id,
    feature,
    refs_by_run,
):
    refs = refs_by_run.get(
        observation_run_id,
        (),
    )

    engine = ComparisonEngine()

    result = engine.cross_section(
        observed_at_ms=int(
            feature.timestamp_ms
        ),
        symbol=str(
            feature.symbol
        ),
        current_features=(
            comparison_feature_values(
                feature
            )
        ),
        peers=refs,
        feature_names=(
            COMPARISON_FEATURES
        ),
        tolerance_ms=180_000,
    )

    return result


def raw_market_worlds(con):
    rows = con.execute(
        """
        SELECT
            hr.run_id
                AS hypothesis_run_id,
            hr.observation_run_id,
            f.symbol,
            f.ts AS forecast_ts,
            f.horizon_seconds,
            o.gross_return_bps
        FROM hypothesis_runs hr
        JOIN hypothesis_forecasts f
          ON f.run_id=hr.run_id
        JOIN hypothesis_outcomes o
          ON o.forecast_id=f.forecast_id
        ORDER BY
            hr.started_ts,
            f.symbol,
            f.ts,
            f.horizon_seconds
        """
    ).fetchall()

    grouped = defaultdict(
        list
    )

    for r in rows:
        key = (
            str(
                r["hypothesis_run_id"]
            ),
            str(
                r["observation_run_id"]
            ),
            str(
                r["symbol"]
            ),
            float(
                r["forecast_ts"]
            ),
            int(
                r["horizon_seconds"]
            ),
        )

        grouped[key].append(
            float(
                r["gross_return_bps"]
            )
        )

    for key, gross in grouped.items():
        unique = {
            round(
                x,
                12,
            )
            for x in gross
        }

        if len(unique) != 1:
            raise ValueError(
                "historical_market_move_conflict:"
                + repr(key)
            )

        yield (
            key,
            next(
                iter(unique)
            ),
        )


def historical_crystal_memory(
    con,
    *,
    feature,
):
    """
    Reconstruct only crystal rows that existed and had not expired
    at the historical feature timestamp.

    This intentionally preserves the historical Phase-2 behavior:
    thesis_capability candidate/proposal rows were visible to
    phase2_crystal_memory even though they were not promoted authority.
    """
    ts = float(feature.timestamp_ms) / 1000.0
    symbol = str(feature.symbol)

    values = (
        feature.values
        if isinstance(feature.values, dict)
        else {}
    )

    regime_inputs = (
        values.get("regime_inputs")
        if isinstance(
            values.get("regime_inputs"),
            dict,
        )
        else {}
    )

    regime_hint = str(
        regime_inputs.get("regime_hint")
        or "unknown"
    )

    symbol_class = str(
        values.get("symbol_class")
        or "unknown"
    )

    rows = con.execute(
        """
        SELECT *
        FROM crystal_registry
        WHERE created_ts <= ?
          AND (
                expires_ts IS NULL
                OR expires_ts >= ?
              )
          AND (
                symbol = ?
                OR symbol IS NULL
                OR symbol = ''
                OR symbol = 'unknown'
              )
        ORDER BY created_ts DESC, crystal_id
        """,
        (
            ts,
            ts,
            symbol,
        ),
    ).fetchall()

    thesis = []
    negative = []

    for row in rows:
        d = dict(row)

        payload = d.get("payload")

        if isinstance(payload, str):
            try:
                payload = json.loads(
                    payload
                    or "{}"
                )
            except Exception:
                payload = {}

        if isinstance(payload, dict):
            # Registry scalar columns remain authoritative where present.
            merged = dict(payload)
            merged.update(
                {
                    k: v
                    for k, v
                    in d.items()
                    if v is not None
                }
            )
            d = merged

        family = str(
            d.get("crystal_family")
            or ""
        )

        if family == "thesis_capability":
            if (
                str(
                    d.get("regime_hint")
                    or "unknown"
                )
                == regime_hint
                and str(
                    d.get("symbol")
                    or ""
                )
                in {
                    "",
                    "unknown",
                    symbol,
                }
            ):
                thesis.append(d)

        elif family == "negative_capability":
            if (
                str(
                    d.get("regime_hint")
                    or "unknown"
                )
                == regime_hint
                and str(
                    d.get("symbol_class")
                    or "unknown"
                )
                in {
                    "",
                    "unknown",
                    symbol_class,
                }
            ):
                negative.append(d)

    memory = {
        "positive_recent":
            len(thesis),
        "negative_recent":
            len(negative),
        "support_score":
            round(
                sum(
                    float(
                        x.get(
                            "evidence_strength"
                        )
                        or 0.0
                    )
                    for x in thesis
                ),
                6,
            ),
        "warning_score":
            round(
                sum(
                    float(
                        x.get(
                            "evidence_strength"
                        )
                        or 0.0
                    )
                    for x in negative
                ),
                6,
            ),
        "regime_hint":
            regime_hint,
        "symbol_class":
            symbol_class,
        "symbol":
            symbol,
    }

    return {
        "memory": memory,
        "thesis_n": len(thesis),
        "negative_n": len(negative),
        "crystal_n":
            len(thesis)
            + len(negative),
    }


def with_crystal_memory(
    feature,
    memory,
):
    values = dict(
        feature.values
        or {}
    )

    values[
        "phase2_crystal_memory"
    ] = dict(memory)

    return replace(
        feature,
        values=values,
    )


def without_crystal_memory(
    feature,
):
    values = dict(
        feature.values
        or {}
    )

    values.pop(
        "phase2_crystal_memory",
        None,
    )

    values.pop(
        "phase2_adaptive_thresholds",
        None,
    )

    return replace(
        feature,
        values=values,
    )


def crystal_forecast_pair(
    *,
    con,
    competition,
    feature,
    horizon_seconds,
):
    crystal = historical_crystal_memory(
        con,
        feature=feature,
    )

    full_feature = with_crystal_memory(
        feature,
        crystal["memory"],
    )

    blind_feature = without_crystal_memory(
        feature,
    )

    full = tuple(
        competition.evaluate(
            full_feature,
            (
                int(
                    horizon_seconds
                ),
            ),
        )
    )

    blind = tuple(
        competition.evaluate(
            blind_feature,
            (
                int(
                    horizon_seconds
                ),
            ),
        )
    )

    return (
        crystal,
        full,
        blind,
    )

def without_regime_oracle(feature):
    """
    Disable only the external/persisted regime oracle.

    Deliberately DO NOT delete raw market features from which
    hypothesis_models may infer its local fallback regime.
    That fallback belongs to the current model, not the disabled organ.
    """
    values=dict(feature.values or {})

    values.pop(
        "regime_inputs",
        None,
    )

    # Remove regime-derived adaptive products as well. They may be rebuilt
    # only from information still lawfully available to the blind model.
    values.pop(
        "phase2_regime_suppression",
        None,
    )

    values.pop(
        "phase2_adaptive_thresholds",
        None,
    )

    return replace(
        feature,
        values=values,
    )


def competition_without_workers():
    """
    Current competition with worker forecast organs removed.

    worker_series remains untouched because it is historical market
    evidence, not the worker organ itself.
    """
    competition=default_historical_competition()

    worker_ids={
        model.model_id
        for model in competition.worker_models
    }

    competition.worker_models=()
    competition.worker_coalition_models=()

    competition._all_nonbaseline_models={
        model_id:model
        for model_id,model
        in competition._all_nonbaseline_models.items()
        if model_id not in worker_ids
    }

    return competition, worker_ids

def by_model(forecasts):
    out = {}

    for f in forecasts:
        key = (
            str(
                f.model_id
            ),
            int(
                f.horizon_seconds
            ),
        )

        if key in out:
            raise ValueError(
                "duplicate_current_forecast:"
                + repr(key)
            )

        out[key] = f

    return out


def realized_net(
    forecast,
    market_move_bps,
):
    if (
        forecast.abstain
        or str(
            forecast.direction
        ).upper()
        == "ABSTAIN"
    ):
        return 0.0

    direction = str(
        forecast.direction
    ).upper()

    if direction == "UP":
        sign = 1.0
    elif direction == "DOWN":
        sign = -1.0
    else:
        raise ValueError(
            "invalid_current_direction:"
            + direction
        )

    cost = forecast.expected_cost_bps

    if cost is None:
        raise ValueError(
            "directional_forecast_missing_cost"
        )

    return (
        sign
        * float(
            market_move_bps
        )
        - float(cost)
    )


con = sqlite3.connect(
    DB
)
con.row_factory = sqlite3.Row

runtime = SynthesisRuntime()

comparison_refs_by_run = (
    build_historical_comparison_refs(
        con
    )
)

stats = {
    mask: Counter()
    for mask in MASKS
}

deltas = {
    mask: []
    for mask in MASKS
}

cohort_deltas = {
    mask: defaultdict(
        list
    )
    for mask in MASKS
}

# One historical market world may generate several model forecasts.
# Phase-12 mechanistic utility must not count those model echoes as
# independent evidence. Preserve every forecast delta for diagnostics,
# but normalize the economic result at:
#
#   observation_run + symbol + timestamp + horizon
#
world_deltas = {
    mask: defaultdict(
        list
    )
    for mask in MASKS
}

# One historical market world may generate several model forecasts.
# Phase-12 mechanistic utility must not count those model echoes as
# independent evidence. Preserve every forecast delta for diagnostics,
# but normalize the economic result at:
#
#   observation_run + symbol + timestamp + horizon
#
world_deltas = {
    mask: defaultdict(
        list
    )
    for mask in MASKS
}

examples = {
    mask: []
    for mask in MASKS
}

world_count = 0

for (
    (
        hypothesis_run_id,
        observation_run_id,
        symbol,
        forecast_ts,
        horizon,
    ),
    market_move_bps,
) in raw_market_worlds(con):

    obs = con.execute(
        """
        SELECT payload
        FROM observation_snapshots
        WHERE run_id=?
          AND symbol=?
          AND ts=?
        LIMIT 1
        """,
        (
            observation_run_id,
            symbol,
            forecast_ts,
        ),
    ).fetchone()

    if obs is None:
        continue

    payload = json.loads(
        obs["payload"]
        or "{}"
    )

    feature = feature_from_payload(
        payload
    )

    if (
        int(
            feature.timestamp_ms
        )
        != int(
            round(
                forecast_ts
                * 1000
            )
        )
    ):
        raise ValueError(
            "historical_feature_timestamp_drift"
        )

    frame, root = (
        frame_from_feature(
            feature
        )
    )

    edge = (
        liquidity_from_feature(
            feature
        )
    )

    comparison = (
        comparison_for_world(
            observation_run_id=(
                observation_run_id
            ),
            feature=feature,
            refs_by_run=(
                comparison_refs_by_run
            ),
        )
    )

    comparisons = (
        comparison,
    )

    crystal_context = historical_crystal_memory(
        con,
        feature=feature,
    )

    world_count += 1

    for mask_id, spec in MASKS.items():

        if (
            mask_id
            == "NO_LIQUIDITY"
            and edge is None
        ):
            stats[
                mask_id
            ][
                "not_testable"
            ] += 1
            continue

        if (
            mask_id
            == "NO_COMPARISON"
            and not comparisons
        ):
            stats[
                mask_id
            ][
                "not_testable"
            ] += 1
            continue

        if (
            mask_id
            == "NO_CRYSTALS"
            and int(
                crystal_context.get(
                    "crystal_n",
                    0,
                )
            ) <= 0
        ):
            stats[
                mask_id
            ][
                "not_testable"
            ] += 1
            continue

        if mask_id == "NO_CRYSTALS":
            stats[
                mask_id
            ][
                "crystal_exposed_worlds"
            ] += 1

            stats[
                mask_id
            ][
                "thesis_crystal_rows"
            ] += int(
                crystal_context.get(
                    "thesis_n",
                    0,
                )
            )

            stats[
                mask_id
            ][
                "negative_crystal_rows"
            ] += int(
                crystal_context.get(
                    "negative_n",
                    0,
                )
            )

        competition = (
            default_historical_competition()
        )

        blind_worker_ids = set()

        if mask_id == "NO_WORKERS":
            (
                blind_competition,
                blind_worker_ids,
            ) = competition_without_workers()
        else:
            blind_competition = competition

        full_cycle = runtime.run(
            frame=frame,
            now_ms=int(
                feature.timestamp_ms
            ),
            edge_snapshot=edge,
            edge_roots=(
                {
                    "LIQUIDITY":
                        (root,)
                }
                if edge is not None
                else {}
            ),
            comparison_results=(
                comparisons
            ),
            disabled_organs=(),
        )

        blind_cycle = runtime.run(
            frame=frame,
            now_ms=int(
                feature.timestamp_ms
            ),
            edge_snapshot=edge,
            edge_roots=(
                {
                    "LIQUIDITY":
                        (root,)
                }
                if edge is not None
                else {}
            ),
            comparison_results=(
                comparisons
            ),
            disabled_organs=(
                spec[
                    "disabled_organs"
                ]
            ),
        )

        if (
            full_cycle.world_state_hash
            != blind_cycle.world_state_hash
        ):
            raise ValueError(
                "historical_current_world_drift"
            )

        full_feature = (
            bind_synthesis_context(
                feature,
                full_cycle,
            )
        )

        blind_feature = (
            bind_synthesis_context(
                feature,
                blind_cycle,
            )
        )

        if mask_id == "NO_CRYSTALS":
            full_feature = with_crystal_memory(
                full_feature,
                crystal_context[
                    "memory"
                ],
            )

            blind_feature = without_crystal_memory(
                blind_feature
            )

        elif mask_id == "NO_REGIME":
            blind_feature = without_regime_oracle(
                blind_feature
            )

        full_raw = tuple(
            competition.evaluate(
                full_feature,
                (horizon,),
            )
        )

        blind_raw = tuple(
            blind_competition.evaluate(
                blind_feature,
                (horizon,),
            )
        )

        full_map = by_model(
            full_raw
        )

        blind_map = by_model(
            blind_raw
        )

        if mask_id != "NO_WORKERS":
            if (
                set(full_map)
                != set(blind_map)
            ):
                raise ValueError(
                    "current_forecast_identity_drift"
                )
        else:
            unexpected_blind_only=(
                set(blind_map)
                - set(full_map)
            )

            if unexpected_blind_only:
                raise ValueError(
                    "no_workers_created_forecast_identity:"
                    + repr(
                        sorted(
                            unexpected_blind_only
                        )
                    )
                )

            removed_ids=(
                set(full_map)
                - set(blind_map)
            )

            unexpected_removed={
                identity
                for identity
                in removed_ids
                if identity[0]
                not in blind_worker_ids
            }

            if unexpected_removed:
                raise ValueError(
                    "no_workers_removed_nonworker_forecast:"
                    + repr(
                        sorted(
                            unexpected_removed
                        )
                    )
                )

            stats[
                mask_id
            ][
                "worker_forecasts_removed"
            ] += len(
                removed_ids
            )

        stats[
            mask_id
        ][
            "testable_worlds"
        ] += 1

        world_changed = False

        for identity in sorted(
            full_map
        ):
            if (
                mask_id == "NO_WORKERS"
                and identity not in blind_map
            ):
                a=full_map[identity]

                decision_a=(
                    bool(a.abstain),
                    str(a.direction),
                )

                # Removing a worker forecast means the blind world has
                # no corresponding trade proposal.
                decision_b=(
                    True,
                    "ABSTAIN",
                )

                if decision_a == decision_b:
                    continue

                world_changed=True

                full_net=realized_net(
                    a,
                    market_move_bps,
                )

                blind_net=0.0

                delta=(
                    full_net
                    - blind_net
                )

                stats[
                    mask_id
                ][
                    "decision_changes"
                ] += 1

                if delta > 0:
                    stats[
                        mask_id
                    ][
                        "helpful_changes"
                    ] += 1
                elif delta < 0:
                    stats[
                        mask_id
                    ][
                        "harmful_changes"
                    ] += 1
                else:
                    stats[
                        mask_id
                    ][
                        "neutral_changes"
                    ] += 1

                deltas[
                    mask_id
                ].append(delta)

                cohort_deltas[
                    mask_id
                ][
                    observation_run_id
                ].append(delta)

                world_key=(
                    observation_run_id,
                    symbol,
                    forecast_ts,
                    horizon,
                )

                world_deltas[
                    mask_id
                ][
                    world_key
                ].append(delta)

                if len(
                    examples[
                        mask_id
                    ]
                ) < 12:
                    examples[
                        mask_id
                    ].append({
                        "run":
                            observation_run_id,
                        "symbol":
                            symbol,
                        "horizon":
                            horizon,
                        "model":
                            identity[0],
                        "full": (
                            a.direction,
                            round(
                                full_net,
                                6,
                            ),
                        ),
                        "blind": (
                            "ABSTAIN",
                            0.0,
                        ),
                        "delta_bps":
                            round(
                                delta,
                                6,
                            ),
                        "cause":
                            "worker_forecast_removed",
                    })

                continue

            if mask_id in {
                "NO_CRYSTALS",
                "NO_REGIME",
                "NO_WORKERS",
            }:
                a = full_map[
                    identity
                ]

                b = blind_map[
                    identity
                ]
            else:
                a = challenge_forecast(
                    full_map[identity],
                    full_feature,
                    organ_scope=(
                        spec[
                            "challenge_scope"
                        ]
                    ),
                )

                b = challenge_forecast(
                    blind_map[identity],
                    blind_feature,
                    organ_scope=(
                        spec[
                            "challenge_scope"
                        ]
                    ),
                )

            decision_a = (
                bool(
                    a.abstain
                ),
                str(
                    a.direction
                ),
            )

            decision_b = (
                bool(
                    b.abstain
                ),
                str(
                    b.direction
                ),
            )

            if (
                decision_a
                == decision_b
            ):
                continue

            world_changed = True

            full_net = (
                realized_net(
                    a,
                    market_move_bps,
                )
            )

            blind_net = (
                realized_net(
                    b,
                    market_move_bps,
                )
            )

            delta = (
                full_net
                - blind_net
            )

            stats[
                mask_id
            ][
                "decision_changes"
            ] += 1

            if delta > 0:
                stats[
                    mask_id
                ][
                    "helpful_changes"
                ] += 1
            elif delta < 0:
                stats[
                    mask_id
                ][
                    "harmful_changes"
                ] += 1
            else:
                stats[
                    mask_id
                ][
                    "neutral_changes"
                ] += 1

            if (
                a.abstain
                and not b.abstain
            ):
                if blind_net < 0:
                    stats[
                        mask_id
                    ][
                        "avoided_losses"
                    ] += 1
                elif blind_net > 0:
                    stats[
                        mask_id
                    ][
                        "suppressed_winners"
                    ] += 1

            deltas[
                mask_id
            ].append(
                delta
            )

            cohort_deltas[
                mask_id
            ][
                observation_run_id
            ].append(
                delta
            )

            world_key = (
                observation_run_id,
                symbol,
                float(forecast_ts),
                int(horizon),
            )

            world_deltas[
                mask_id
            ][
                world_key
            ].append(
                delta
            )

            world_key = (
                observation_run_id,
                symbol,
                float(forecast_ts),
                int(horizon),
            )

            world_deltas[
                mask_id
            ][
                world_key
            ].append(
                delta
            )

            if (
                len(
                    examples[
                        mask_id
                    ]
                )
                < 12
            ):
                examples[
                    mask_id
                ].append(
                    {
                        "run":
                            observation_run_id,
                        "symbol":
                            symbol,
                        "horizon":
                            horizon,
                        "model":
                            identity[0],
                        "full":
                            (
                                a.direction,
                                round(
                                    full_net,
                                    6,
                                ),
                            ),
                        "blind":
                            (
                                b.direction,
                                round(
                                    blind_net,
                                    6,
                                ),
                            ),
                        "delta_bps":
                            round(
                                delta,
                                6,
                            ),
                    }
                )

        if world_changed:
            stats[
                mask_id
            ][
                "changed_worlds"
            ] += 1


print(
    "HIVENANCE_PHASE12_INDEPENDENT_HYPOTHESIS_CAUSALITY"
)

print(
    "unique_market_world_horizons=",
    world_count,
)

for mask_id in MASKS:
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
    ):
        print(
            f"  {key}=",
            stats[
                mask_id
            ][key],
        )

    print(
        "  mean_paired_delta_bps=",
        (
            mean(
                deltas[
                    mask_id
                ]
            )
            if deltas[
                mask_id
            ]
            else None
        ),
    )

    cohort_means = {
        run_id:
            mean(values)
        for run_id, values
        in cohort_deltas[
            mask_id
        ].items()
        if values
    }

    print(
        "  dependence_adjusted_worlds=",
        len(
            cohort_means
        ),
    )

    print(
        "  minimum_independent_worlds_met=",
        len(
            cohort_means
        ) >= 5,
    )

    print(
        "  cohort_means=",
        {
            k:
                round(
                    v,
                    6,
                )
            for k, v
            in sorted(
                cohort_means.items()
            )
        },
    )

    print(
        "  positive_cohorts=",
        sum(
            1
            for v
            in cohort_means.values()
            if v > 0
        ),
    )

    print(
        "  negative_cohorts=",
        sum(
            1
            for v
            in cohort_means.values()
            if v < 0
        ),
    )

    print(
        "  zero_cohorts=",
        sum(
            1
            for v
            in cohort_means.values()
            if v == 0
        ),
    )

    print(
        "  examples=",
        examples[
            mask_id
        ],
    )

print()
print(
    "HIVENANCE_PHASE12_WORLD_NORMALIZED_CAUSALITY"
)

for mask_id in MASKS:
    per_world = {
        world_key:
            mean(model_deltas)
        for world_key, model_deltas
        in world_deltas[
            mask_id
        ].items()
        if model_deltas
    }

    per_cohort_worlds = defaultdict(
        list
    )

    for world_key, world_delta in per_world.items():
        observation_run_id = (
            world_key[0]
        )

        per_cohort_worlds[
            observation_run_id
        ].append(
            world_delta
        )

    normalized_cohort_means = {
        run_id:
            mean(values)
        for run_id, values
        in per_cohort_worlds.items()
        if values
    }

    world_values = tuple(
        per_world.values()
    )

    # Conservative companion metric:
    # for each world use the least favourable changed-model delta.
    conservative_world = {
        world_key:
            min(model_deltas)
        for world_key, model_deltas
        in world_deltas[
            mask_id
        ].items()
        if model_deltas
    }

    conservative_cohort_means = {
        run_id:
            mean(
                [
                    delta
                    for world_key, delta
                    in conservative_world.items()
                    if world_key[0]
                    == run_id
                ]
            )
        for run_id
        in {
            world_key[0]
            for world_key
            in conservative_world
        }
    }

    print()
    print(mask_id)

    print(
        "  changed_market_worlds=",
        len(
            per_world
        ),
    )

    print(
        "  positive_worlds=",
        sum(
            1
            for x
            in world_values
            if x > 0
        ),
    )

    print(
        "  negative_worlds=",
        sum(
            1
            for x
            in world_values
            if x < 0
        ),
    )

    print(
        "  zero_worlds=",
        sum(
            1
            for x
            in world_values
            if x == 0
        ),
    )

    print(
        "  world_normalized_mean_delta_bps=",
        (
            mean(
                world_values
            )
            if world_values
            else None
        ),
    )

    print(
        "  dependence_adjusted_worlds=",
        len(
            normalized_cohort_means
        ),
    )

    print(
        "  normalized_cohort_means=",
        {
            k:
                round(
                    v,
                    6,
                )
            for k, v
            in sorted(
                normalized_cohort_means.items()
            )
        },
    )

    print(
        "  positive_cohorts=",
        sum(
            1
            for x
            in normalized_cohort_means.values()
            if x > 0
        ),
    )

    print(
        "  negative_cohorts=",
        sum(
            1
            for x
            in normalized_cohort_means.values()
            if x < 0
        ),
    )

    print(
        "  conservative_cohort_means=",
        {
            k:
                round(
                    v,
                    6,
                )
            for k, v
            in sorted(
                conservative_cohort_means.items()
            )
        },
    )

    print(
        "  conservative_positive_cohorts=",
        sum(
            1
            for x
            in conservative_cohort_means.values()
            if x > 0
        ),
    )

    print(
        "  minimum_independent_worlds_met=",
        len(
            normalized_cohort_means
        ) >= 5,
    )

    if not per_world:
        classification = (
            "NO_CAUSAL_EFFECT"
        )
    elif (
        len(
            normalized_cohort_means
        ) < 5
    ):
        classification = (
            "INSUFFICIENT_INDEPENDENT_WORLDS"
        )
    elif (
        all(
            x > 0
            for x
            in normalized_cohort_means.values()
        )
        and all(
            x > 0
            for x
            in conservative_cohort_means.values()
        )
    ):
        classification = (
            "HISTORICALLY_USEFUL_CANDIDATE"
        )
    elif all(
        x < 0
        for x
        in normalized_cohort_means.values()
    ):
        classification = (
            "HISTORICALLY_HARMFUL_CANDIDATE"
        )
    else:
        classification = (
            "HISTORICALLY_MIXED"
        )

    print(
        "  world_normalized_classification=",
        classification,
    )

print()
print(
    "HIVENANCE_PHASE12_WORLD_NORMALIZED_CAUSALITY"
)

for mask_id in MASKS:
    per_world = {
        world_key:
            mean(model_deltas)
        for world_key, model_deltas
        in world_deltas[
            mask_id
        ].items()
        if model_deltas
    }

    per_cohort_worlds = defaultdict(
        list
    )

    for world_key, world_delta in per_world.items():
        observation_run_id = (
            world_key[0]
        )

        per_cohort_worlds[
            observation_run_id
        ].append(
            world_delta
        )

    normalized_cohort_means = {
        run_id:
            mean(values)
        for run_id, values
        in per_cohort_worlds.items()
        if values
    }

    world_values = tuple(
        per_world.values()
    )

    # Conservative companion metric:
    # for each world use the least favourable changed-model delta.
    conservative_world = {
        world_key:
            min(model_deltas)
        for world_key, model_deltas
        in world_deltas[
            mask_id
        ].items()
        if model_deltas
    }

    conservative_cohort_means = {
        run_id:
            mean(
                [
                    delta
                    for world_key, delta
                    in conservative_world.items()
                    if world_key[0]
                    == run_id
                ]
            )
        for run_id
        in {
            world_key[0]
            for world_key
            in conservative_world
        }
    }

    print()
    print(mask_id)

    print(
        "  changed_market_worlds=",
        len(
            per_world
        ),
    )

    print(
        "  positive_worlds=",
        sum(
            1
            for x
            in world_values
            if x > 0
        ),
    )

    print(
        "  negative_worlds=",
        sum(
            1
            for x
            in world_values
            if x < 0
        ),
    )

    print(
        "  zero_worlds=",
        sum(
            1
            for x
            in world_values
            if x == 0
        ),
    )

    print(
        "  world_normalized_mean_delta_bps=",
        (
            mean(
                world_values
            )
            if world_values
            else None
        ),
    )

    print(
        "  dependence_adjusted_worlds=",
        len(
            normalized_cohort_means
        ),
    )

    print(
        "  normalized_cohort_means=",
        {
            k:
                round(
                    v,
                    6,
                )
            for k, v
            in sorted(
                normalized_cohort_means.items()
            )
        },
    )

    print(
        "  positive_cohorts=",
        sum(
            1
            for x
            in normalized_cohort_means.values()
            if x > 0
        ),
    )

    print(
        "  negative_cohorts=",
        sum(
            1
            for x
            in normalized_cohort_means.values()
            if x < 0
        ),
    )

    print(
        "  conservative_cohort_means=",
        {
            k:
                round(
                    v,
                    6,
                )
            for k, v
            in sorted(
                conservative_cohort_means.items()
            )
        },
    )

    print(
        "  conservative_positive_cohorts=",
        sum(
            1
            for x
            in conservative_cohort_means.values()
            if x > 0
        ),
    )

    print(
        "  minimum_independent_worlds_met=",
        len(
            normalized_cohort_means
        ) >= 5,
    )

    if not per_world:
        classification = (
            "NO_CAUSAL_EFFECT"
        )
    elif (
        len(
            normalized_cohort_means
        ) < 5
    ):
        classification = (
            "INSUFFICIENT_INDEPENDENT_WORLDS"
        )
    elif (
        all(
            x > 0
            for x
            in normalized_cohort_means.values()
        )
        and all(
            x > 0
            for x
            in conservative_cohort_means.values()
        )
    ):
        classification = (
            "HISTORICALLY_USEFUL_CANDIDATE"
        )
    elif all(
        x < 0
        for x
        in normalized_cohort_means.values()
    ):
        classification = (
            "HISTORICALLY_HARMFUL_CANDIDATE"
        )
    else:
        classification = (
            "HISTORICALLY_MIXED"
        )

    print(
        "  world_normalized_classification=",
        classification,
    )

print()
print(
    "historical_reconstruction_only=True"
)
print(
    "old_forecast_direction_used_as_input=False"
)
print(
    "current_model_replay=True"
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

con.close()
