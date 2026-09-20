"""Lawful pre-T organ reconstruction for Phase-12 historical prosecution.

Only evidence that existed before the historical freeze may be reconstructed.

Current supported reconstructions:
- ComparisonEngine cross-section
- EdgeEcology LIQUIDITY voice
- TemporalParticipationBee
- HorizonContext only when fresh enough at T

Unavailable evidence remains ABSENT_DATA.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from agents.horizon_context import HorizonContext

from .comparison_engine import (
    ComparisonEngine,
    ComparisonReference,
    ComparisonResult,
)
from .edge_ecology import (
    EdgeEcology,
    EdgeEcologySnapshot,
)
from .historical_reconstruction_input import (
    HistoricalReconstructionInput,
)
from .temporal_participation_bee import (
    ParticipationObservation,
    TemporalParticipationBee,
    TemporalParticipationEvidence,
)
from .world_graph_adapters import (
    evidence_root,
)


HORIZON_MAX_AGE_MS = 180_000


@dataclass(frozen=True)
class HistoricalOrganBundle:
    horizon: HorizonContext | None
    horizon_roots: tuple[str, ...]

    edge_snapshot: EdgeEcologySnapshot | None
    edge_roots: Mapping[str, tuple[str, ...]]

    temporal_participation: TemporalParticipationEvidence | None

    comparison_results: tuple[ComparisonResult, ...]

    status: Mapping[str, str]

    horizon_age_ms: int | None

    execution_eligible: bool = False
    promotion_eligible: bool = False


def _connect_ro(path: str | Path):
    p = Path(path)

    if not p.exists():
        return None

    con = sqlite3.connect(
        f"file:{p.resolve()}?mode=ro",
        uri=True,
    )
    con.row_factory = sqlite3.Row

    return con


def _feature_values(
    feature: Any,
) -> dict[str, Any]:
    values = getattr(
        feature,
        "values",
        {},
    )

    return (
        dict(values)
        if isinstance(values, Mapping)
        else {}
    )


def _current_features(
    feature: Any,
) -> dict[str, Any]:
    values = _feature_values(
        feature
    )

    return {
        "volume_zscore":
            feature.volume_zscore,
        "volatility_expansion":
            feature.volatility_expansion,
        "spread_bps":
            feature.spread_bps,
        "book_imbalance":
            feature.book_imbalance,
        "return_zscore":
            feature.return_zscore,
        "tradable_opportunity_score":
            values.get(
                "tradable_opportunity_score"
            ),
    }


def _reconstruct_horizon(
    inp: HistoricalReconstructionInput,
    *,
    horizon_db: str | Path,
) -> tuple[
    HorizonContext | None,
    tuple[str, ...],
    int | None,
    str,
]:
    con = _connect_ro(
        horizon_db
    )

    if con is None:
        return (
            None,
            (),
            None,
            "ABSENT_DATA",
        )

    try:
        row = con.execute(
            """
            SELECT *
            FROM horizon_context
            WHERE symbol = ?
              AND ts <= ?
            ORDER BY ts DESC
            LIMIT 1
            """,
            (
                inp.symbol,
                inp.observed_at_ms
                / 1000.0,
            ),
        ).fetchone()

        if row is None:
            return (
                None,
                (),
                None,
                "ABSENT_DATA",
            )

        d = dict(row)

        age_ms = int(
            inp.observed_at_ms
            - round(
                float(d["ts"])
                * 1000.0
            )
        )

        if (
            age_ms < 0
            or age_ms
            > HORIZON_MAX_AGE_MS
        ):
            return (
                None,
                (),
                age_ms,
                "STALE_AT_T",
            )

        raw = json.loads(
            d["context_json"]
        )

        context = HorizonContext(
            symbol=str(
                raw["symbol"]
            ),
            timestamp=float(
                raw["timestamp"]
            ),
            micro=dict(
                raw.get("micro")
                or {}
            ),
            meso=dict(
                raw.get("meso")
                or {}
            ),
            macro=dict(
                raw.get("macro")
                or {}
            ),
            alignment=str(
                raw.get(
                    "alignment",
                    "NEUTRAL",
                )
            ),
            regime_hint=str(
                raw.get(
                    "regime_hint",
                    "UNKNOWN",
                )
            ),
            relative_strength=dict(
                raw.get(
                    "relative_strength"
                )
                or {}
            ),
            readiness={
                str(k): bool(v)
                for k, v
                in (
                    raw.get(
                        "readiness"
                    )
                    or {}
                ).items()
            },
        )

        root = evidence_root(
            (
                "historical_horizon:"
                + inp.symbol
                + ":"
                + str(d["ts"])
            ),
            raw,
        )

        return (
            context,
            (root,),
            age_ms,
            "INVOKABLE",
        )

    finally:
        con.close()


def _reconstruct_liquidity(
    inp: HistoricalReconstructionInput,
    feature: Any,
) -> tuple[
    EdgeEcologySnapshot | None,
    Mapping[
        str,
        tuple[str, ...],
    ],
    str,
]:
    depth = (
        feature.depth_usd_25bps
    )

    imbalance = (
        feature.book_imbalance
    )

    spread = (
        feature.spread_bps
    )

    if (
        depth is None
        or imbalance is None
        or spread is None
    ):
        return (
            None,
            {},
            "ABSENT_DATA",
        )

    total = max(
        0.0,
        float(depth),
    )

    imb = max(
        -1.0,
        min(
            1.0,
            float(imbalance),
        ),
    )

    # Exact algebraic decomposition:
    #
    # imbalance = (bid - ask)/(bid + ask)
    # total     = bid + ask
    bid_depth = (
        total
        * (1.0 + imb)
        / 2.0
    )

    ask_depth = (
        total
        * (1.0 - imb)
        / 2.0
    )

    voice = (
        EdgeEcology.liquidity_voice(
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            spread_bps=float(
                spread
            ),
            previous_bid_depth=None,
            previous_ask_depth=None,
        )
    )

    snapshot = (
        EdgeEcology().snapshot(
            timestamp_ms=(
                inp.observed_at_ms
            ),
            pair_id=inp.symbol,
            voices=(voice,),
        )
    )

    return (
        snapshot,
        {
            "LIQUIDITY": (
                inp.evidence_root,
            ),
        },
        "INVOKABLE",
    )


def _reconstruct_comparison(
    inp: HistoricalReconstructionInput,
    feature: Any,
    *,
    swarm_db: str | Path,
) -> tuple[
    tuple[ComparisonResult, ...],
    str,
]:
    con = _connect_ro(
        swarm_db
    )

    if con is None:
        return (
            (),
            "ABSENT_DATA",
        )

    try:
        rows = con.execute(
            """
            SELECT *
            FROM observation_universe_snapshots
            WHERE run_id = ?
              AND symbol != ?
              AND ts <= ?
            ORDER BY ts, symbol
            """,
            (
                inp.observation_run_id,
                inp.symbol,
                inp.observed_at_ms
                / 1000.0,
            ),
        ).fetchall()

        refs = []

        for row in rows:
            d = dict(row)

            raw = d.get(
                "payload"
            )

            try:
                payload = json.loads(
                    raw or "{}"
                )
            except Exception:
                payload = {}

            values = (
                payload.get(
                    "values"
                )
                if isinstance(
                    payload.get(
                        "values"
                    ),
                    Mapping,
                )
                else {}
            )

            root = evidence_root(
                (
                    "historical_peer:"
                    + str(
                        d["run_id"]
                    )
                    + ":"
                    + str(
                        d["symbol"]
                    )
                    + ":"
                    + str(
                        d["ts"]
                    )
                ),
                d,
            )

            refs.append(
                ComparisonReference(
                    reference_id=(
                        "hist_"
                        + root.split(
                            ":",
                            1,
                        )[1][:20]
                    ),
                    observed_at_ms=int(
                        round(
                            float(
                                d["ts"]
                            )
                            * 1000.0
                        )
                    ),
                    symbol=str(
                        d["symbol"]
                    ),
                    utc_hour=0,
                    features={
                        "volume_zscore":
                            d.get(
                                "volume_zscore"
                            ),
                        "volatility_expansion":
                            d.get(
                                "volatility_expansion"
                            ),
                        "spread_bps":
                            d.get(
                                "spread_bps"
                            ),
                        "book_imbalance":
                            d.get(
                                "book_imbalance"
                            ),
                        "return_zscore":
                            values.get(
                                "return_zscore"
                            ),
                        "tradable_opportunity_score":
                            values.get(
                                "tradable_opportunity_score"
                            ),
                    },
                    evidence_roots=(
                        root,
                    ),
                    selected=bool(
                        d.get(
                            "selected_for_phase2"
                        )
                    ),
                )
            )

        if not refs:
            return (
                (),
                "ABSENT_DATA",
            )

        result = (
            ComparisonEngine().cross_section(
                observed_at_ms=(
                    inp.observed_at_ms
                ),
                symbol=inp.symbol,
                current_features=(
                    _current_features(
                        feature
                    )
                ),
                peers=refs,
                feature_names=(
                    "volume_zscore",
                    "volatility_expansion",
                    "spread_bps",
                    "book_imbalance",
                    "return_zscore",
                    "tradable_opportunity_score",
                ),
                tolerance_ms=180_000,
            )
        )

        if result.matched_n <= 0:
            return (
                (),
                "ABSENT_DATA",
            )

        return (
            (result,),
            "INVOKABLE",
        )

    finally:
        con.close()


def _reconstruct_temporal_participation(
    inp: HistoricalReconstructionInput,
    feature: Any,
    *,
    swarm_db: str | Path,
) -> tuple[
    TemporalParticipationEvidence | None,
    str,
]:
    volume = (
        feature.quote_volume_24h
    )

    if volume is None:
        return (
            None,
            "ABSENT_DATA",
        )

    con = _connect_ro(
        swarm_db
    )

    if con is None:
        return (
            None,
            "ABSENT_DATA",
        )

    try:
        seen = {}

        for table in (
            "observation_snapshots",
            "observation_universe_snapshots",
        ):
            rows = con.execute(
                f"""
                SELECT
                    run_id,
                    ts,
                    symbol,
                    quote_volume_24h
                FROM "{table}"
                WHERE symbol = ?
                  AND ts < ?
                  AND quote_volume_24h IS NOT NULL
                """,
                (
                    inp.symbol,
                    inp.observed_at_ms
                    / 1000.0,
                ),
            ).fetchall()

            for row in rows:
                d = dict(row)

                key = (
                    str(
                        d["run_id"]
                    ),
                    float(
                        d["ts"]
                    ),
                    str(
                        d["symbol"]
                    ),
                )

                seen[key] = (
                    ParticipationObservation(
                        observed_at_ms=int(
                            round(
                                float(
                                    d["ts"]
                                )
                                * 1000.0
                            )
                        ),
                        volume=float(
                            d[
                                "quote_volume_24h"
                            ]
                        ),
                        realized_move_bps=None,
                    )
                )

        history = tuple(
            sorted(
                seen.values(),
                key=lambda x:
                    x.observed_at_ms,
            )
        )

        evidence = (
            TemporalParticipationBee(
                min_same_hour_samples=5
            ).observe(
                observed_at_ms=(
                    inp.observed_at_ms
                ),
                volume=float(
                    volume
                ),
                history=history,
                realized_move_bps=None,
            )
        )

        return (
            evidence,
            (
                "INVOKABLE"
                if (
                    evidence.historical_same_hour_n
                    >= 5
                )
                else
                "INVOKABLE_LOW_HISTORY"
            ),
        )

    finally:
        con.close()


def reconstruct_historical_organs(
    inp: HistoricalReconstructionInput,
    feature: Any,
    *,
    swarm_db: str | Path = (
        "data/swarm_data.db"
    ),
    horizon_db: str | Path = (
        "data/hivenance_horizon_context.db"
    ),
) -> HistoricalOrganBundle:
    (
        horizon,
        horizon_roots,
        horizon_age_ms,
        horizon_state,
    ) = _reconstruct_horizon(
        inp,
        horizon_db=horizon_db,
    )

    (
        edge_snapshot,
        edge_roots,
        liquidity_state,
    ) = _reconstruct_liquidity(
        inp,
        feature,
    )

    (
        comparison_results,
        comparison_state,
    ) = _reconstruct_comparison(
        inp,
        feature,
        swarm_db=swarm_db,
    )

    (
        temporal,
        temporal_state,
    ) = (
        _reconstruct_temporal_participation(
            inp,
            feature,
            swarm_db=swarm_db,
        )
    )

    return HistoricalOrganBundle(
        horizon=horizon,
        horizon_roots=(
            horizon_roots
        ),
        edge_snapshot=(
            edge_snapshot
        ),
        edge_roots=(
            edge_roots
        ),
        temporal_participation=(
            temporal
        ),
        comparison_results=(
            comparison_results
        ),
        status={
            "horizon_context":
                horizon_state,
            "liquidity":
                liquidity_state,
            "comparison_engine":
                comparison_state,
            "temporal_participation_bee":
                temporal_state,
            "flow":
                "ABSENT_DATA",
            "trend":
                "ABSENT_DATA",
            "volatility":
                "ABSENT_DATA",
            "carry":
                "ABSENT_DATA",
            "learning_memory":
                "NOT_YET_SCHEMA_BOUND",
            "crystals":
                "NOT_YET_SCHEMA_BOUND",
        },
        horizon_age_ms=(
            horizon_age_ms
        ),
        execution_eligible=False,
        promotion_eligible=False,
    )
