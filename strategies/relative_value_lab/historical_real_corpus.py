"""Read-only adapter for the real Phase-12 historical prosecution corpus.

Authoritative source:
    data/swarm_data.db

The initial cohort is the Phase-4 frozen selector cohort:
    full_organism_selector_freezes
      JOIN full_organism_selector_settlements_v3 USING freeze_id

This module reconstructs historical inputs only. It never claims that today's
Phase-11 envelopes existed prospectively at the original timestamps.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


def _json(value: Any) -> dict[str, Any]:
    if value is None:
        return {}

    if isinstance(value, Mapping):
        return dict(value)

    if isinstance(value, bytes):
        value = value.decode(
            "utf-8",
            errors="replace",
        )

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "historical_corpus_invalid_json_payload"
            ) from exc

        if not isinstance(parsed, dict):
            raise ValueError(
                "historical_corpus_payload_not_object"
            )

        return parsed

    raise TypeError(
        "historical_corpus_payload_type_invalid"
    )


@dataclass(frozen=True)
class HistoricalCorpusCase:
    case_id: str

    freeze_id: str
    settlement_id: str

    observation_run_id: str

    symbol: str
    selected: bool

    selector_rank: int
    blind_rank: int | None
    blind_selected: bool | None

    observed_ts: float
    target_ts: float
    settled_ts: float

    horizon_seconds: int

    world_state_id: str
    world_state_hash: str
    evidence_root: str

    entry_price: float
    exit_price: float

    predicted_roundtrip_cost_bps: float | None
    net_opportunity_bps: float | None
    gross_absolute_move_bps: float | None

    regime: str | None

    freeze_payload: Mapping[str, Any]
    settlement_payload: Mapping[str, Any]

    observation_snapshot: Mapping[str, Any] | None

    matching_forecasts: tuple[
        Mapping[str, Any],
        ...
    ]

    matching_outcomes: tuple[
        Mapping[str, Any],
        ...
    ]

    historical_reconstruction_only: bool = True
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class HistoricalCorpusManifest:
    schema: str

    database_path: str

    case_count: int
    selected_count: int
    rejected_count: int

    distinct_observation_runs: int
    distinct_world_states: int
    distinct_symbols: int

    observation_snapshot_coverage: int
    primary_observation_coverage: int
    universe_observation_coverage: int
    forecast_context_case_coverage: int
    outcome_context_case_coverage: int

    world_binding_mismatches: int
    horizon_mismatches: int
    timestamp_mismatches: int

    cases: tuple[
        HistoricalCorpusCase,
        ...
    ]

    historical_reconstruction_only: bool = True
    prospective_envelopes_claimed: bool = False
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HistoricalRealCorpus:
    def __init__(
        self,
        database_path: str | Path = (
            "data/swarm_data.db"
        ),
    ) -> None:
        self.path = Path(
            database_path
        )

    def _connect(self):
        if not self.path.exists():
            raise FileNotFoundError(
                self.path
            )

        con = sqlite3.connect(
            "file:"
            + str(
                self.path.resolve()
            )
            + "?mode=ro",
            uri=True,
        )

        con.row_factory = sqlite3.Row

        return con

    @staticmethod
    def _columns(
        con: sqlite3.Connection,
        table: str,
    ) -> set[str]:
        return {
            str(row["name"])
            for row in con.execute(
                f'PRAGMA table_info("{table}")'
            )
        }

    @staticmethod
    def _nearest_observation(
        con: sqlite3.Connection,
        *,
        run_id: str,
        symbol: str,
        observed_ts: float,
    ) -> dict[str, Any] | None:
        def timestamp(row):
            d = dict(row)

            for key in (
                "observed_ts",
                "ts",
                "timestamp",
                "created_ts",
                "custody_ts",
            ):
                if (
                    key in d
                    and d[key] is not None
                ):
                    return float(
                        d[key]
                    )

            for key in (
                "observed_at_ms",
                "timestamp_ms",
                "created_at_ms",
            ):
                if (
                    key in d
                    and d[key] is not None
                ):
                    return (
                        float(d[key])
                        / 1000.0
                    )

            payload = _json(
                d.get("payload")
            )

            for key in (
                "observed_ts",
                "ts",
                "custody_ts",
            ):
                if payload.get(key) is not None:
                    return float(
                        payload[key]
                    )

            for key in (
                "observed_at_ms",
                "timestamp_ms",
            ):
                if payload.get(key) is not None:
                    return (
                        float(
                            payload[key]
                        )
                        / 1000.0
                    )

            return float("-inf")

        for table in (
            "observation_snapshots",
            "observation_universe_snapshots",
        ):
            cols = (
                HistoricalRealCorpus._columns(
                    con,
                    table,
                )
            )

            if not {
                "run_id",
                "symbol",
            }.issubset(cols):
                continue

            rows = con.execute(
                f"""
                SELECT *
                FROM "{table}"
                WHERE run_id = ?
                  AND symbol = ?
                """,
                (
                    run_id,
                    symbol,
                ),
            ).fetchall()

            eligible = [
                row
                for row in rows
                if timestamp(row)
                <= float(observed_ts)
            ]

            if not eligible:
                continue

            chosen = max(
                eligible,
                key=timestamp,
            )

            out = dict(chosen)
            out[
                "_historical_source_table"
            ] = table

            return out

        return None

    @staticmethod
    def _forecast_context(
        con: sqlite3.Connection,
        *,
        observation_run_id: str,
        symbol: str,
        horizon_seconds: int,
        observed_ts: float,
    ) -> tuple[
        tuple[dict[str, Any], ...],
        tuple[dict[str, Any], ...],
    ]:
        forecast_cols = (
            HistoricalRealCorpus._columns(
                con,
                "hypothesis_forecasts",
            )
        )

        required = {
            "forecast_id",
            "observation_run_id",
            "symbol",
            "horizon_seconds",
            "ts",
        }

        if not required.issubset(
            forecast_cols
        ):
            return (), ()

        rows = con.execute(
            """
            SELECT *
            FROM hypothesis_forecasts
            WHERE observation_run_id = ?
              AND symbol = ?
              AND horizon_seconds = ?
              AND ts <= ?
            ORDER BY ts, forecast_id
            """,
            (
                observation_run_id,
                symbol,
                int(horizon_seconds),
                float(observed_ts),
            ),
        ).fetchall()

        forecasts = tuple(
            dict(row)
            for row in rows
        )

        if not forecasts:
            return (), ()

        ids = [
            row["forecast_id"]
            for row in forecasts
        ]

        placeholders = ",".join(
            "?"
            for _ in ids
        )

        outcomes = con.execute(
            f"""
            SELECT *
            FROM hypothesis_outcomes
            WHERE forecast_id IN (
                {placeholders}
            )
            ORDER BY forecast_id
            """,
            ids,
        ).fetchall()

        return (
            forecasts,
            tuple(
                dict(row)
                for row in outcomes
            ),
        )

    def load_cases(
        self,
    ) -> tuple[
        HistoricalCorpusCase,
        ...
    ]:
        con = self._connect()

        try:
            rows = con.execute(
                """
                SELECT
                    s.settlement_id,
                    s.freeze_id,
                    s.settled_ts,
                    s.symbol
                        AS settlement_symbol,
                    s.selected
                        AS settlement_selected,
                    s.selector_rank
                        AS settlement_selector_rank,
                    s.regime,
                    s.payload
                        AS settlement_payload,

                    f.run_id,
                    f.observed_ts,
                    f.target_ts,
                    f.symbol
                        AS freeze_symbol,
                    f.selector_rank
                        AS freeze_selector_rank,
                    f.selector_score,
                    f.selected
                        AS freeze_selected,
                    f.blind_rank,
                    f.blind_selected,
                    f.payload
                        AS freeze_payload
                FROM
                    full_organism_selector_settlements_v3 s
                JOIN
                    full_organism_selector_freezes f
                ON
                    f.freeze_id = s.freeze_id
                ORDER BY
                    f.selector_rank,
                    f.symbol,
                    f.freeze_id
                """
            ).fetchall()

            out = []

            for row in rows:
                d = dict(row)

                freeze = _json(
                    d["freeze_payload"]
                )

                settlement = _json(
                    d[
                        "settlement_payload"
                    ]
                )

                symbol = str(
                    d["freeze_symbol"]
                )

                if (
                    symbol
                    != str(
                        d[
                            "settlement_symbol"
                        ]
                    )
                ):
                    raise ValueError(
                        "historical_corpus_symbol_mismatch:"
                        + str(
                            d["freeze_id"]
                        )
                    )

                selected = bool(
                    d["freeze_selected"]
                )

                if (
                    selected
                    != bool(
                        d[
                            "settlement_selected"
                        ]
                    )
                ):
                    raise ValueError(
                        "historical_corpus_selection_mismatch:"
                        + str(
                            d["freeze_id"]
                        )
                    )

                world_id = str(
                    settlement.get(
                        "canonical_world_state_id",
                        freeze.get(
                            "canonical_world_state_id",
                            "",
                        ),
                    )
                )

                world_hash = str(
                    settlement.get(
                        "canonical_world_state_hash",
                        freeze.get(
                            "canonical_world_state_hash",
                            "",
                        ),
                    )
                )

                freeze_world_id = str(
                    freeze.get(
                        "canonical_world_state_id",
                        world_id,
                    )
                )

                freeze_world_hash = str(
                    freeze.get(
                        "canonical_world_state_hash",
                        world_hash,
                    )
                )

                if (
                    world_id
                    != freeze_world_id
                    or world_hash
                    != freeze_world_hash
                ):
                    raise ValueError(
                        "historical_corpus_world_binding_mismatch:"
                        + str(
                            d["freeze_id"]
                        )
                    )

                horizon = int(
                    freeze.get(
                        "horizon_seconds",
                        round(
                            (
                                float(
                                    d["target_ts"]
                                )
                                - float(
                                    d[
                                        "observed_ts"
                                    ]
                                )
                            )
                        ),
                    )
                )

                expected_target = (
                    float(
                        d["observed_ts"]
                    )
                    + horizon
                )

                if abs(
                    expected_target
                    - float(
                        d["target_ts"]
                    )
                ) > 1e-6:
                    raise ValueError(
                        "historical_corpus_horizon_timestamp_mismatch:"
                        + str(
                            d["freeze_id"]
                        )
                    )

                obs = (
                    self._nearest_observation(
                        con,
                        run_id=str(
                            d["run_id"]
                        ),
                        symbol=symbol,
                        observed_ts=float(
                            d["observed_ts"]
                        ),
                    )
                )

                (
                    forecasts,
                    outcomes,
                ) = self._forecast_context(
                    con,
                    observation_run_id=str(
                        d["run_id"]
                    ),
                    symbol=symbol,
                    horizon_seconds=horizon,
                    observed_ts=float(
                        d["observed_ts"]
                    ),
                )

                entry = settlement.get(
                    "entry_price",
                    freeze.get(
                        "price",
                    ),
                )

                exit_price = (
                    settlement.get(
                        "exit_price"
                    )
                )

                if (
                    entry is None
                    or exit_price is None
                ):
                    raise ValueError(
                        "historical_corpus_price_missing:"
                        + str(
                            d["freeze_id"]
                        )
                    )

                case_id = (
                    "phase12:"
                    + str(
                        d["freeze_id"]
                    )
                )

                out.append(
                    HistoricalCorpusCase(
                        case_id=case_id,
                        freeze_id=str(
                            d["freeze_id"]
                        ),
                        settlement_id=str(
                            d[
                                "settlement_id"
                            ]
                        ),
                        observation_run_id=str(
                            d["run_id"]
                        ),
                        symbol=symbol,
                        selected=selected,
                        selector_rank=int(
                            d[
                                "freeze_selector_rank"
                            ]
                        ),
                        blind_rank=(
                            None
                            if d[
                                "blind_rank"
                            ]
                            is None
                            else int(
                                d[
                                    "blind_rank"
                                ]
                            )
                        ),
                        blind_selected=(
                            None
                            if d[
                                "blind_selected"
                            ]
                            is None
                            else bool(
                                d[
                                    "blind_selected"
                                ]
                            )
                        ),
                        observed_ts=float(
                            d["observed_ts"]
                        ),
                        target_ts=float(
                            d["target_ts"]
                        ),
                        settled_ts=float(
                            d["settled_ts"]
                        ),
                        horizon_seconds=(
                            horizon
                        ),
                        world_state_id=(
                            world_id
                        ),
                        world_state_hash=(
                            world_hash
                        ),
                        evidence_root=str(
                            settlement.get(
                                "evidence_root",
                                freeze.get(
                                    "evidence_root",
                                    "",
                                ),
                            )
                        ),
                        entry_price=float(
                            entry
                        ),
                        exit_price=float(
                            exit_price
                        ),
                        predicted_roundtrip_cost_bps=(
                            None
                            if freeze.get(
                                "predicted_roundtrip_cost_bps"
                            )
                            is None
                            else float(
                                freeze[
                                    "predicted_roundtrip_cost_bps"
                                ]
                            )
                        ),
                        net_opportunity_bps=(
                            None
                            if settlement.get(
                                "net_opportunity_bps"
                            )
                            is None
                            else float(
                                settlement[
                                    "net_opportunity_bps"
                                ]
                            )
                        ),
                        gross_absolute_move_bps=(
                            None
                            if settlement.get(
                                "gross_absolute_move_bps"
                            )
                            is None
                            else float(
                                settlement[
                                    "gross_absolute_move_bps"
                                ]
                            )
                        ),
                        regime=(
                            None
                            if d["regime"]
                            is None
                            else str(
                                d["regime"]
                            )
                        ),
                        freeze_payload=freeze,
                        settlement_payload=(
                            settlement
                        ),
                        observation_snapshot=(
                            obs
                        ),
                        matching_forecasts=(
                            forecasts
                        ),
                        matching_outcomes=(
                            outcomes
                        ),
                        historical_reconstruction_only=True,
                        execution_eligible=False,
                        promotion_eligible=False,
                    )
                )

            return tuple(out)

        finally:
            con.close()

    def manifest(
        self,
    ) -> HistoricalCorpusManifest:
        cases = self.load_cases()

        return HistoricalCorpusManifest(
            schema=(
                "hivenance_phase12_real_historical_corpus_manifest_v1"
            ),
            database_path=str(
                self.path
            ),
            case_count=len(cases),
            selected_count=sum(
                1
                for x in cases
                if x.selected
            ),
            rejected_count=sum(
                1
                for x in cases
                if not x.selected
            ),
            distinct_observation_runs=len(
                {
                    x.observation_run_id
                    for x in cases
                }
            ),
            distinct_world_states=len(
                {
                    x.world_state_id
                    for x in cases
                }
            ),
            distinct_symbols=len(
                {
                    x.symbol
                    for x in cases
                }
            ),
            observation_snapshot_coverage=sum(
                1
                for x in cases
                if x.observation_snapshot
                is not None
            ),
            primary_observation_coverage=sum(
                1
                for x in cases
                if x.observation_snapshot
                is not None
                and x.observation_snapshot.get(
                    "_historical_source_table"
                )
                == "observation_snapshots"
            ),
            universe_observation_coverage=sum(
                1
                for x in cases
                if x.observation_snapshot
                is not None
                and x.observation_snapshot.get(
                    "_historical_source_table"
                )
                == "observation_universe_snapshots"
            ),
            forecast_context_case_coverage=sum(
                1
                for x in cases
                if x.matching_forecasts
            ),
            outcome_context_case_coverage=sum(
                1
                for x in cases
                if x.matching_outcomes
            ),
            world_binding_mismatches=0,
            horizon_mismatches=0,
            timestamp_mismatches=0,
            cases=cases,
            historical_reconstruction_only=True,
            prospective_envelopes_claimed=False,
            execution_eligible=False,
            promotion_eligible=False,
        )
