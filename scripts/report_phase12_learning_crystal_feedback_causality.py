from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict
from statistics import mean
from types import SimpleNamespace
from typing import Any, Iterable, Mapping

from strategies.volatility_breakout.hypothesis_competition import HypothesisCompetition
from strategies.volatility_breakout.learning_crystal_feedback import (
    attach_learning_feedback,
    compile_learning_feedback,
    learning_crystal_rows,
)
from strategies.volatility_breakout.models import FeatureVector, Forecast
from strategies.volatility_breakout.research_reuse import ResearchReuseGovernor

DB = "data/swarm_data.db"
MASKS = ("NO_LEARNING", "NO_CRYSTALS", "NO_WORKERS")


class HistoricalReuseStore:
    """Read-only point-in-time reuse view over the historical DB."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def persist_research_reuse_receipt(self, payload: Mapping[str, Any]) -> bool:
        return True

    def get_research_reuse_stats(
        self,
        *,
        model_id: str,
        symbol: str,
        horizon_seconds: int,
        regime_hint: str,
        limit: int = 25,
        cutoff_ts: float | None = None,
    ) -> dict[str, Any]:
        rows = self.conn.execute(
            """
            SELECT o.net_return_bps, o.positive_net, o.settled_ts
            FROM hypothesis_outcomes o
            JOIN hypothesis_forecasts f ON f.forecast_id=o.forecast_id
            WHERE f.model_id=?
              AND f.symbol=?
              AND f.horizon_seconds=?
              AND f.settled=1
              AND f.abstain=0
              AND COALESCE(
                    json_extract(f.payload, '$.inputs.regime_hint'),
                    json_extract(f.payload, '$.inputs.regime_inputs.regime_hint'),
                    'unknown'
                  )=?
              AND (? IS NULL OR o.settled_ts <= ?)
            ORDER BY o.settled_ts DESC
            LIMIT ?
            """,
            (
                str(model_id),
                str(symbol),
                int(horizon_seconds),
                str(regime_hint or "unknown"),
                cutoff_ts,
                cutoff_ts,
                int(limit),
            ),
        ).fetchall()
        return _stats(rows)

    def get_research_transform_reuse_stats(
        self,
        *,
        model_id: str,
        horizon_seconds: int,
        regime_hint: str,
        cohort_bucket: str,
        symbol_class: str,
        limit: int = 50,
        cutoff_ts: float | None = None,
    ) -> dict[str, Any]:
        rows = self.conn.execute(
            """
            SELECT o.net_return_bps, o.positive_net, o.settled_ts
            FROM hypothesis_outcomes o
            JOIN hypothesis_forecasts f ON f.forecast_id=o.forecast_id
            WHERE f.model_id=?
              AND f.horizon_seconds=?
              AND COALESCE(
                    json_extract(f.payload, '$.inputs.regime_hint'),
                    json_extract(f.payload, '$.inputs.regime_inputs.regime_hint'),
                    'unknown'
                  )=?
              AND COALESCE(json_extract(f.payload, '$.inputs.symbol_class'), 'unknown')=?
              AND f.abstain=0
              AND (? IS NULL OR o.settled_ts <= ?)
            ORDER BY o.settled_ts DESC
            LIMIT ?
            """,
            (
                str(model_id),
                int(horizon_seconds),
                str(regime_hint or "unknown"),
                str(symbol_class or "unknown"),
                cutoff_ts,
                cutoff_ts,
                int(limit),
            ),
        ).fetchall()
        if rows:
            out = _stats(rows)
            out["match_type"] = "symbol_class"
            return out

        rows = self.conn.execute(
            """
            SELECT o.net_return_bps, o.positive_net, o.settled_ts
            FROM hypothesis_outcomes o
            JOIN hypothesis_forecasts f ON f.forecast_id=o.forecast_id
            WHERE f.model_id=?
              AND f.horizon_seconds=?
              AND COALESCE(
                    json_extract(f.payload, '$.inputs.regime_hint'),
                    json_extract(f.payload, '$.inputs.regime_inputs.regime_hint'),
                    'unknown'
                  )=?
              AND COALESCE(json_extract(f.payload, '$.inputs.cohort_bucket'), 'unknown')=?
              AND f.abstain=0
              AND (? IS NULL OR o.settled_ts <= ?)
            ORDER BY o.settled_ts DESC
            LIMIT ?
            """,
            (
                str(model_id),
                int(horizon_seconds),
                str(regime_hint or "unknown"),
                str(cohort_bucket or "unknown"),
                cutoff_ts,
                cutoff_ts,
                int(limit),
            ),
        ).fetchall()
        out = _stats(rows)
        out["match_type"] = "cohort" if rows else "none"
        return out


def _stats(rows: Iterable[sqlite3.Row]) -> dict[str, Any]:
    rows = list(rows)
    if not rows:
        return {
            "sample_count": 0,
            "mean_realized_net_bps": None,
            "win_rate": None,
            "latest_settled_ts": None,
        }
    nets = [float(row[0]) for row in rows if row[0] is not None]
    wins = [int(row[1] or 0) for row in rows]
    settled = [float(row[2]) for row in rows if row[2] is not None]
    return {
        "sample_count": len(rows),
        "mean_realized_net_bps": (sum(nets) / len(nets)) if nets else None,
        "win_rate": (sum(wins) / len(wins)) if wins else None,
        "latest_settled_ts": max(settled) if settled else None,
    }


def feature_from_payload(payload: Mapping[str, Any]) -> FeatureVector:
    values = payload.get("values") if isinstance(payload.get("values"), dict) else {}
    fv = values.get("feature_vector")
    if not isinstance(fv, dict):
        raise ValueError("historical_feature_vector_missing")
    return FeatureVector(**fv)


def raw_worlds(conn: sqlite3.Connection):
    rows = conn.execute(
        """
        SELECT hr.run_id AS hypothesis_run_id,
               hr.observation_run_id,
               f.symbol,
               f.ts AS forecast_ts,
               f.horizon_seconds,
               o.gross_return_bps
        FROM hypothesis_runs hr
        JOIN hypothesis_forecasts f ON f.run_id=hr.run_id
        JOIN hypothesis_outcomes o ON o.forecast_id=f.forecast_id
        ORDER BY f.ts, hr.started_ts, f.symbol, f.horizon_seconds
        """
    ).fetchall()

    grouped: dict[tuple[Any, ...], list[float]] = defaultdict(list)
    for row in rows:
        key = (
            str(row["hypothesis_run_id"]),
            str(row["observation_run_id"]),
            str(row["symbol"]),
            float(row["forecast_ts"]),
            int(row["horizon_seconds"]),
        )
        grouped[key].append(float(row["gross_return_bps"]))

    for key, values in grouped.items():
        unique = {round(x, 12) for x in values}
        if len(unique) != 1:
            raise ValueError("historical_market_move_conflict:" + repr(key))
        yield key, next(iter(unique))


def by_model(forecasts: Iterable[Forecast]) -> dict[tuple[str, int], Forecast]:
    out: dict[tuple[str, int], Forecast] = {}
    for forecast in forecasts:
        key = (str(forecast.model_id), int(forecast.horizon_seconds))
        if key in out:
            raise ValueError("duplicate_current_forecast:" + repr(key))
        out[key] = forecast
    return out


def realized_net(forecast: Forecast, market_move_bps: float) -> float:
    if forecast.abstain or str(forecast.direction).upper() == "ABSTAIN":
        return 0.0
    direction = str(forecast.direction).upper()
    if direction == "UP":
        sign = 1.0
    elif direction == "DOWN":
        sign = -1.0
    else:
        raise ValueError("invalid_current_direction:" + direction)
    if forecast.expected_cost_bps is None:
        raise ValueError("directional_forecast_missing_cost")
    return sign * float(market_move_bps) - float(forecast.expected_cost_bps)


def competition(*, workers: bool) -> HypothesisCompetition:
    return HypothesisCompetition(
        SimpleNamespace(
            exchange="kraken",
            phase2_worker_signal_federation_enabled=bool(workers),
            phase2_worker_coalition_enabled=bool(workers),
            medium_trend_phase2_model_enabled=False,
            derivatives_trend_phase2_model_enabled=False,
            phase2_transform_reuse_enabled=True,
        )
    )


def learning_governor(store: HistoricalReuseStore) -> ResearchReuseGovernor:
    return ResearchReuseGovernor(
        SimpleNamespace(
            exchange="kraken",
            phase2_transform_reuse_enabled=True,
            phase2_reuse_min_samples=5,
            phase2_reuse_min_mean_net_bps=2.0,
            phase2_reuse_min_win_rate=0.50,
            phase2_transform_reuse_min_samples=8,
            phase2_transform_reuse_min_mean_net_bps=2.0,
            phase2_transform_reuse_min_win_rate=0.50,
        ),
        store,
    )


def compile_feature(
    feature: FeatureVector,
    *,
    comp: HypothesisCompetition,
    governor: ResearchReuseGovernor,
    crystals: list[dict[str, Any]],
    enable_learning: bool,
    enable_crystals: bool,
) -> tuple[FeatureVector, dict[str, Any]]:
    if not enable_learning:
        return feature, {
            "support_score": 0.0,
            "warning_score": 0.0,
            "positive_priors": 0,
            "negative_priors": 0,
            "crystal_reuse_count": 0,
            "authority": "RESEARCH_PRIOR_ONLY",
        }

    feedback = compile_learning_feedback(
        feature,
        model_ids=comp.all_model_ids,
        horizons=(int(feature.values.get("_historical_horizon_seconds") or 0),),
        reuse_governor=governor,
        max_age_sec=86400.0,
        min_samples_for_reuse=5,
        reusable_crystals=(crystals if enable_crystals else ()),
    )
    return attach_learning_feedback(feature, feedback), feedback


def remember_crystals(
    feature: FeatureVector,
    feedback: Mapping[str, Any],
    *,
    venue: str,
    registry: dict[str, dict[str, Any]],
) -> None:
    for row in learning_crystal_rows(feature, feedback, venue=venue, expiry_sec=86400.0):
        payload = dict(row.get("payload") or {})
        payload["crystal_id"] = row.get("crystal_id")
        payload["expires_ts"] = row.get("expires_ts")
        payload["authority"] = row.get("authority")
        payload["applicability_hash"] = row.get("applicability_hash")
        key = str(payload.get("applicability_key") or row.get("applicability_hash") or "")
        if key:
            registry[key] = payload


def compare_maps(
    *,
    full: dict[tuple[str, int], Forecast],
    blind: dict[tuple[str, int], Forecast],
    market_move_bps: float,
    mask_id: str,
    stats: Counter,
    world_bucket: list[float],
) -> None:
    identities = sorted(set(full) | set(blind))
    for identity in identities:
        a = full.get(identity)
        b = blind.get(identity)

        if a is None:
            continue

        if b is None:
            # Only NO_WORKERS is allowed to remove model identities.
            if mask_id != "NO_WORKERS":
                raise ValueError("forecast_identity_drift:" + repr((mask_id, identity)))
            b_net = 0.0
            b_decision = (True, "ABSTAIN")
        else:
            b_net = realized_net(b, market_move_bps)
            b_decision = (bool(b.abstain), str(b.direction))

        a_net = realized_net(a, market_move_bps)
        a_decision = (bool(a.abstain), str(a.direction))

        if a_decision == b_decision:
            continue

        delta = a_net - b_net
        stats["decision_changes"] += 1
        world_bucket.append(delta)

        if delta > 0:
            stats["helpful_changes"] += 1
        elif delta < 0:
            stats["harmful_changes"] += 1
        else:
            stats["neutral_changes"] += 1

        if a.abstain and b is not None and not b.abstain:
            if b_net < 0:
                stats["avoided_losses"] += 1
            elif b_net > 0:
                stats["suppressed_winners"] += 1


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    store = HistoricalReuseStore(conn)

    full_comp = competition(workers=True)
    no_workers_comp = competition(workers=False)

    full_governor = learning_governor(store)
    no_crystal_governor = learning_governor(store)
    no_workers_governor = learning_governor(store)

    full_registry: dict[str, dict[str, Any]] = {}
    no_workers_registry: dict[str, dict[str, Any]] = {}

    stats = {mask: Counter() for mask in MASKS}
    world_deltas = {mask: defaultdict(list) for mask in MASKS}
    cohort_deltas = {mask: defaultdict(list) for mask in MASKS}

    worlds = 0
    learning_exposed_worlds = 0
    crystal_reused_worlds = 0

    for (
        (
            _hypothesis_run_id,
            observation_run_id,
            symbol,
            forecast_ts,
            horizon,
        ),
        market_move_bps,
    ) in raw_worlds(conn):
        obs = conn.execute(
            """
            SELECT payload
            FROM observation_snapshots
            WHERE run_id=? AND symbol=? AND ts=?
            LIMIT 1
            """,
            (observation_run_id, symbol, forecast_ts),
        ).fetchone()
        if obs is None:
            continue

        payload = json.loads(obs["payload"] or "{}")
        feature = feature_from_payload(payload)
        if int(feature.timestamp_ms) != int(round(forecast_ts * 1000)):
            raise ValueError("historical_feature_timestamp_drift")

        values = dict(feature.values or {})
        values["_historical_horizon_seconds"] = int(horizon)
        feature = FeatureVector(**{**asdict(feature), "values": values})
        worlds += 1

        full_feature, full_feedback = compile_feature(
            feature,
            comp=full_comp,
            governor=full_governor,
            crystals=list(full_registry.values()),
            enable_learning=True,
            enable_crystals=True,
        )
        no_learning_feature, _ = compile_feature(
            feature,
            comp=full_comp,
            governor=full_governor,
            crystals=(),
            enable_learning=False,
            enable_crystals=False,
        )
        no_crystal_feature, no_crystal_feedback = compile_feature(
            feature,
            comp=full_comp,
            governor=no_crystal_governor,
            crystals=(),
            enable_learning=True,
            enable_crystals=False,
        )
        no_workers_feature, no_workers_feedback = compile_feature(
            feature,
            comp=no_workers_comp,
            governor=no_workers_governor,
            crystals=list(no_workers_registry.values()),
            enable_learning=True,
            enable_crystals=True,
        )

        if int(full_feedback.get("positive_priors") or 0) or int(full_feedback.get("negative_priors") or 0):
            learning_exposed_worlds += 1
        if int(full_feedback.get("crystal_reuse_count") or 0):
            crystal_reused_worlds += 1

        full_map = by_model(full_comp.evaluate(full_feature, (horizon,)))
        variants = {
            "NO_LEARNING": by_model(full_comp.evaluate(no_learning_feature, (horizon,))),
            "NO_CRYSTALS": by_model(full_comp.evaluate(no_crystal_feature, (horizon,))),
            "NO_WORKERS": by_model(no_workers_comp.evaluate(no_workers_feature, (horizon,))),
        }

        world_key = (observation_run_id, symbol, float(forecast_ts), int(horizon))

        for mask_id, blind_map in variants.items():
            stats[mask_id]["testable_worlds"] += 1
            deltas: list[float] = []
            compare_maps(
                full=full_map,
                blind=blind_map,
                market_move_bps=market_move_bps,
                mask_id=mask_id,
                stats=stats[mask_id],
                world_bucket=deltas,
            )
            if deltas:
                stats[mask_id]["changed_worlds"] += 1
                world_deltas[mask_id][world_key].extend(deltas)
                cohort_deltas[mask_id][observation_run_id].append(mean(deltas))

        remember_crystals(
            feature,
            full_feedback,
            venue="kraken",
            registry=full_registry,
        )
        remember_crystals(
            feature,
            no_workers_feedback,
            venue="kraken",
            registry=no_workers_registry,
        )

    print("HIVENANCE_PHASE12_7C9_REPAIRED_HISTORICAL_CAUSALITY")
    print("historical_reconstruction_only=True")
    print("future_settlement_cutoff_enforced=True")
    print("prospective_usefulness_proved=False")
    print("execution_eligible=False")
    print("promotion_eligible=False")
    print("unique_market_world_horizons=", worlds)
    print("learning_exposed_worlds=", learning_exposed_worlds)
    print("crystal_reused_worlds=", crystal_reused_worlds)
    print("final_full_learning_crystals=", len(full_registry))

    for mask_id in MASKS:
        per_world = {
            key: mean(values)
            for key, values in world_deltas[mask_id].items()
            if values
        }
        normalized_cohorts: dict[str, float] = {}
        grouped = defaultdict(list)
        for key, value in per_world.items():
            grouped[key[0]].append(value)
        normalized_cohorts = {
            run_id: mean(values)
            for run_id, values in grouped.items()
            if values
        }
        conservative = {
            key: min(values)
            for key, values in world_deltas[mask_id].items()
            if values
        }
        conservative_grouped = defaultdict(list)
        for key, value in conservative.items():
            conservative_grouped[key[0]].append(value)
        conservative_cohorts = {
            run_id: mean(values)
            for run_id, values in conservative_grouped.items()
            if values
        }

        if not per_world:
            classification = "NO_CAUSAL_EFFECT"
        elif len(normalized_cohorts) < 5:
            classification = "INSUFFICIENT_INDEPENDENT_WORLDS"
        elif (
            all(x > 0 for x in normalized_cohorts.values())
            and all(x > 0 for x in conservative_cohorts.values())
        ):
            classification = "HISTORICALLY_USEFUL_CANDIDATE"
        elif all(x < 0 for x in normalized_cohorts.values()):
            classification = "HISTORICALLY_HARMFUL_CANDIDATE"
        else:
            classification = "HISTORICALLY_MIXED"

        print()
        print(mask_id)
        for key in (
            "testable_worlds",
            "changed_worlds",
            "decision_changes",
            "helpful_changes",
            "harmful_changes",
            "neutral_changes",
            "avoided_losses",
            "suppressed_winners",
        ):
            print(f"  {key}=", stats[mask_id][key])
        print("  changed_market_worlds=", len(per_world))
        print("  world_normalized_mean_delta_bps=", mean(per_world.values()) if per_world else None)
        print("  dependence_adjusted_worlds=", len(normalized_cohorts))
        print("  minimum_independent_worlds_met=", len(normalized_cohorts) >= 5)
        print("  normalized_cohort_means=", {k: round(v, 6) for k, v in sorted(normalized_cohorts.items())})
        print("  conservative_cohort_means=", {k: round(v, 6) for k, v in sorted(conservative_cohorts.items())})
        print("  positive_cohorts=", sum(1 for x in normalized_cohorts.values() if x > 0))
        print("  negative_cohorts=", sum(1 for x in normalized_cohorts.values() if x < 0))
        print("  world_normalized_classification=", classification)

    conn.close()


if __name__ == "__main__":
    main()
