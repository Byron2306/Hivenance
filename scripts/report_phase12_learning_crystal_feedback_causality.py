from __future__ import annotations

import argparse
import bisect
import hashlib
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
from strategies.relative_value_lab.historical_causal_prosecution import HistoricalWorldOutcome
from strategies.relative_value_lab.historical_probabilistic_reconstruction import (
    HistoricalBayesianRegimeReconstructor,
    HistoricalStatisticsReconstructor,
    bind_regime_context,
)

DB = "data/swarm_data.db"
MASKS = ("NO_LEARNING", "NO_CRYSTALS", "NO_WORKERS", "NO_STATISTICS", "NO_BAYES")
STATISTICAL_ATTACKS = (
    "SHUFFLE_EVIDENCE",
    "TIME_SHIFT_PLACEBO",
    "POOLED_GLOBAL_CONTEXT",
    "NEGATIVE_EDGE_ONLY",
    "CHANGE_POINT_ONLY",
    "UNCERTAINTY_ONLY",
    "NO_NEGATIVE_EDGE_GATE",
    "NO_CHANGE_POINT_GATE",
    "NO_UNCERTAINTY_GATE",
)


class HistoricalReuseStore:
    """In-memory point-in-time reuse index over the historical DB.

    The corpus is loaded once. Every lookup then uses a binary search on
    settled_ts so no future outcome can enter a historical decision.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        evidence_lag_sec: float = 0.0,
        strict_before: bool = True,
    ) -> None:
        self.evidence_lag_sec = max(0.0, float(evidence_lag_sec))
        self.strict_before = bool(strict_before)
        self.exact: dict[tuple[str, str, int, str], list[tuple[float, float, int]]] = defaultdict(list)
        self.symbol_class: dict[tuple[str, int, str, str], list[tuple[float, float, int]]] = defaultdict(list)
        self.cohort: dict[tuple[str, int, str, str], list[tuple[float, float, int]]] = defaultdict(list)

        rows = conn.execute(
            """
            SELECT
                f.model_id,
                f.symbol,
                f.horizon_seconds,
                COALESCE(
                    json_extract(f.payload, '$.inputs.regime_hint'),
                    json_extract(f.payload, '$.inputs.regime_inputs.regime_hint'),
                    'unknown'
                ) AS regime_hint,
                COALESCE(
                    json_extract(f.payload, '$.inputs.symbol_class'),
                    'unknown'
                ) AS symbol_class,
                COALESCE(
                    json_extract(f.payload, '$.inputs.cohort_bucket'),
                    'unknown'
                ) AS cohort_bucket,
                o.net_return_bps,
                o.positive_net,
                o.settled_ts
            FROM hypothesis_outcomes o
            JOIN hypothesis_forecasts f
              ON f.forecast_id=o.forecast_id
            WHERE f.abstain=0
              AND o.settled_ts IS NOT NULL
            ORDER BY o.settled_ts
            """
        ).fetchall()

        for row in rows:
            settled_ts = float(row["settled_ts"])
            net = float(row["net_return_bps"] or 0.0)
            positive = int(row["positive_net"] or 0)
            model_id = str(row["model_id"])
            symbol = str(row["symbol"])
            horizon = int(row["horizon_seconds"])
            regime = str(row["regime_hint"] or "unknown")
            symbol_class = str(row["symbol_class"] or "unknown")
            cohort_bucket = str(row["cohort_bucket"] or "unknown")
            point = (settled_ts, net, positive)

            self.exact[
                (model_id, symbol, horizon, regime)
            ].append(point)
            self.symbol_class[
                (model_id, horizon, regime, symbol_class)
            ].append(point)
            self.cohort[
                (model_id, horizon, regime, cohort_bucket)
            ].append(point)

        self.loaded_rows = len(rows)

    def persist_research_reuse_receipt(self, payload: Mapping[str, Any]) -> bool:
        return True

    def _slice(
        self,
        rows: list[tuple[float, float, int]],
        *,
        cutoff_ts: float | None,
        limit: int,
    ) -> list[tuple[float, float, int]]:
        if not rows:
            return []
        if cutoff_ts is None:
            hi = len(rows)
        else:
            effective_cutoff = float(cutoff_ts) - self.evidence_lag_sec
            if self.strict_before:
                hi = bisect.bisect_left(
                    rows,
                    (effective_cutoff, float("-inf"), -1),
                )
            else:
                hi = bisect.bisect_right(
                    rows,
                    (effective_cutoff, float("inf"), 1),
                )
        lo = max(0, hi - int(limit))
        return rows[lo:hi]

    @staticmethod
    def _stats_from_points(
        rows: list[tuple[float, float, int]],
    ) -> dict[str, Any]:
        if not rows:
            return {
                "sample_count": 0,
                "mean_realized_net_bps": None,
                "win_rate": None,
                "latest_settled_ts": None,
            }
        return {
            "sample_count": len(rows),
            "mean_realized_net_bps": sum(x[1] for x in rows) / len(rows),
            "win_rate": sum(x[2] for x in rows) / len(rows),
            "latest_settled_ts": rows[-1][0],
        }

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
        key = (
            str(model_id),
            str(symbol),
            int(horizon_seconds),
            str(regime_hint or "unknown"),
        )
        rows = self._slice(
            self.exact.get(key, []),
            cutoff_ts=cutoff_ts,
            limit=limit,
        )
        return self._stats_from_points(rows)

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
        sc_key = (
            str(model_id),
            int(horizon_seconds),
            str(regime_hint or "unknown"),
            str(symbol_class or "unknown"),
        )
        rows = self._slice(
            self.symbol_class.get(sc_key, []),
            cutoff_ts=cutoff_ts,
            limit=limit,
        )
        if rows:
            out = self._stats_from_points(rows)
            out["match_type"] = "symbol_class"
            return out

        cohort_key = (
            str(model_id),
            int(horizon_seconds),
            str(regime_hint or "unknown"),
            str(cohort_bucket or "unknown"),
        )
        rows = self._slice(
            self.cohort.get(cohort_key, []),
            cutoff_ts=cutoff_ts,
            limit=limit,
        )
        out = self._stats_from_points(rows)
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
    warning_floor: float = 0.60,
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
    threshold = max(0.0, min(1.0, float(warning_floor)))
    priors = feedback.get("priors") if isinstance(feedback.get("priors"), dict) else {}
    adjusted = {}
    for key, prior in priors.items():
        row = dict(prior) if isinstance(prior, dict) else {}
        if float(row.get("warning_score") or 0.0) < threshold:
            row["warning_score"] = 0.0
        adjusted[key] = row
    feedback = dict(feedback)
    feedback["priors"] = adjusted
    feedback["warning_score"] = max(
        [float(x.get("warning_score") or 0.0) for x in adjusted.values()] or [0.0]
    )
    feedback["negative_priors"] = sum(
        1 for x in adjusted.values()
        if float(x.get("warning_score") or 0.0) > 0.0
    )
    feedback["audit_warning_floor"] = threshold
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
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        default=DB,
        help="Path to historical HiveNance SQLite corpus",
    )
    parser.add_argument(
        "--evidence-lag-sec",
        type=float,
        default=0.0,
        help="Require learning evidence to have settled this many seconds before the forecast",
    )
    parser.add_argument(
        "--allow-equal-settlement-ts",
        action="store_true",
        help="Allow settled_ts == forecast_ts; default is strict settled_ts < forecast_ts",
    )
    parser.add_argument(
        "--warning-floor",
        type=float,
        default=0.60,
        help="Only warnings at or above this score may influence the replay",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=250,
        help="Emit progress every N reconstructed market worlds",
    )
    parser.add_argument(
        "--census-json-out",
        default=None,
        help="Optional path to write FULL_HIVE and replay-mask world outcomes for the organism census",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    store = HistoricalReuseStore(
        conn,
        evidence_lag_sec=args.evidence_lag_sec,
        strict_before=not args.allow_equal_settlement_ts,
    )

    observation_payloads = {
        (str(row["run_id"]), str(row["symbol"]), float(row["ts"])): row["payload"]
        for row in conn.execute(
            """
            SELECT run_id, symbol, ts, payload
            FROM observation_snapshots
            """
        ).fetchall()
    }

    full_comp = competition(workers=True)
    no_workers_comp = competition(workers=False)
    historical_statistics = HistoricalStatisticsReconstructor(conn)
    historical_bayes = HistoricalBayesianRegimeReconstructor()

    print(
        f"audit_strict_before={not args.allow_equal_settlement_ts} "
        f"evidence_lag_sec={args.evidence_lag_sec} "
        f"warning_floor={args.warning_floor}",
        flush=True,
    )
    print(
        f"preloaded_reuse_outcomes={store.loaded_rows} "
        f"preloaded_statistical_outcomes={historical_statistics.loaded_rows} "
        f"observation_snapshots={len(observation_payloads)}",
        flush=True,
    )

    full_governor = learning_governor(store)
    no_crystal_governor = learning_governor(store)
    no_workers_governor = learning_governor(store)

    full_registry: dict[str, dict[str, Any]] = {}
    no_workers_registry: dict[str, dict[str, Any]] = {}

    stats = {mask: Counter() for mask in MASKS}
    world_deltas = {mask: defaultdict(list) for mask in MASKS}
    cohort_deltas = {mask: defaultdict(list) for mask in MASKS}
    attack_stats = {attack: Counter() for attack in STATISTICAL_ATTACKS}
    attack_world_deltas = {attack: defaultdict(list) for attack in STATISTICAL_ATTACKS}

    worlds = 0
    learning_exposed_worlds = 0
    learning_prior_evidence_worlds = 0
    learning_candidate_worlds = 0
    learning_scaffolded_worlds = 0
    learning_advisory_worlds = 0
    learning_no_prior_worlds = 0
    learning_prior_sample_counts = Counter()
    learning_lifecycles = Counter()
    learning_age_samples: list[float] = []
    crystal_reused_worlds = 0
    statistical_context_worlds = 0
    statistical_effective_n_samples: list[float] = []
    statistical_edge_probability_samples: list[float] = []
    bayes_context_worlds = 0
    bayes_disagreement_samples: list[float] = []
    bayes_change_probability_samples: list[float] = []
    previous_statistics_by_model: dict[str, Any] = {}
    previous_statistics_timestamp_ms: int | None = None
    statistical_veto_reasons = Counter()
    statistical_trigger_overlap = Counter()
    census_outcomes = {
        "FULL_HIVE": [],
        "NO_LEARNING": [],
        "NO_CRYSTALS": [],
        "NO_WORKERS": [],
        "NO_STATISTICS": [],
        "NO_BAYES": [],
    }

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
        raw_payload = observation_payloads.get(
            (observation_run_id, symbol, float(forecast_ts))
        )
        if raw_payload is None:
            continue

        payload = json.loads(raw_payload or "{}")
        feature = feature_from_payload(payload)
        if int(feature.timestamp_ms) != int(round(forecast_ts * 1000)):
            raise ValueError("historical_feature_timestamp_drift")

        values = dict(feature.values or {})
        values["_historical_horizon_seconds"] = int(horizon)
        feature = FeatureVector(**{**asdict(feature), "values": values})
        worlds += 1
        if args.progress_every > 0 and worlds % args.progress_every == 0:
            print(
                f"progress worlds={worlds} "
                f"learning_exposed={learning_exposed_worlds} "
                f"crystal_reused={crystal_reused_worlds} "
                f"crystals={len(full_registry)}",
                flush=True,
            )

        full_feature, full_feedback = compile_feature(
            feature,
            comp=full_comp,
            governor=full_governor,
            crystals=list(full_registry.values()),
            enable_learning=True,
            enable_crystals=True,
            warning_floor=args.warning_floor,
        )
        no_learning_feature, _ = compile_feature(
            feature,
            comp=full_comp,
            governor=full_governor,
            crystals=(),
            enable_learning=False,
            enable_crystals=False,
            warning_floor=args.warning_floor,
        )
        no_crystal_feature, no_crystal_feedback = compile_feature(
            feature,
            comp=full_comp,
            governor=no_crystal_governor,
            crystals=(),
            enable_learning=True,
            enable_crystals=False,
            warning_floor=args.warning_floor,
        )
        no_workers_feature, no_workers_feedback = compile_feature(
            feature,
            comp=no_workers_comp,
            governor=no_workers_governor,
            crystals=list(no_workers_registry.values()),
            enable_learning=True,
            enable_crystals=True,
            warning_floor=args.warning_floor,
        )

        regime_context = historical_bayes.context_for(feature)

        full_feature = bind_regime_context(full_feature, regime_context)
        no_learning_feature = bind_regime_context(no_learning_feature, regime_context)
        no_crystal_feature = bind_regime_context(no_crystal_feature, regime_context)
        no_workers_feature = bind_regime_context(no_workers_feature, regime_context)

        no_bayes_feature = full_feature
        no_bayes_values = dict(no_bayes_feature.values or {})
        no_bayes_values.pop("regime_context", None)
        no_bayes_feature = FeatureVector(**{**asdict(no_bayes_feature), "values": no_bayes_values})

        full_feature = historical_statistics.bind(
            full_feature,
            model_ids=full_comp.all_model_ids,
            horizon_seconds=int(horizon),
        )
        no_learning_feature = historical_statistics.bind(
            no_learning_feature,
            model_ids=full_comp.all_model_ids,
            horizon_seconds=int(horizon),
        )
        no_crystal_feature = historical_statistics.bind(
            no_crystal_feature,
            model_ids=full_comp.all_model_ids,
            horizon_seconds=int(horizon),
        )
        no_workers_feature = historical_statistics.bind(
            no_workers_feature,
            model_ids=no_workers_comp.all_model_ids,
            horizon_seconds=int(horizon),
        )
        no_bayes_feature = historical_statistics.bind(
            no_bayes_feature,
            model_ids=full_comp.all_model_ids,
            horizon_seconds=int(horizon),
        )
        no_statistics_feature = bind_regime_context(
            compile_feature(
                feature,
                comp=full_comp,
                governor=full_governor,
                crystals=list(full_registry.values()),
                enable_learning=True,
                enable_crystals=True,
                warning_floor=args.warning_floor,
            )[0],
            regime_context,
        )

        stats_map = (
            full_feature.values.get("phase2_statistical_hypothesis_context_by_model")
            if isinstance(full_feature.values, dict)
            else None
        )
        if isinstance(stats_map, dict):
            positive_depth = False
            for row in stats_map.values():
                if not isinstance(row, dict):
                    continue
                n_eff = float(row.get("effective_sample_size") or 0.0)
                if n_eff > 0.0:
                    positive_depth = True
                    statistical_effective_n_samples.append(n_eff)
                edge_p = row.get("edge_positive_probability")
                if edge_p is not None:
                    statistical_edge_probability_samples.append(float(edge_p))
            if positive_depth:
                statistical_context_worlds += 1

        regime_payload = regime_context.to_dict()
        if regime_payload.get("dominant_posterior_regime"):
            bayes_context_worlds += 1
            bayes_disagreement_samples.append(
                float(regime_payload.get("disagreement_score") or 0.0)
            )
            bayes_change_probability_samples.append(
                float(regime_payload.get("change_point_probability") or 0.0)
            )

        priors = full_feedback.get("priors") if isinstance(full_feedback.get("priors"), dict) else {}
        world_has_prior_evidence = False
        world_has_candidate = False
        world_has_scaffolded = False
        world_has_advisory = False
        world_all_no_prior = bool(priors)
        for prior in priors.values():
            if not isinstance(prior, dict):
                continue
            sample_count = int(prior.get("sample_count") or 0)
            lifecycle = str(prior.get("lifecycle") or "UNKNOWN")
            learning_prior_sample_counts[str(sample_count)] += 1
            learning_lifecycles[lifecycle] += 1
            if sample_count > 0:
                world_has_prior_evidence = True
                world_all_no_prior = False
            age_sec = prior.get("age_sec")
            if age_sec is not None:
                learning_age_samples.append(float(age_sec))
            if lifecycle == "DETERMINISTIC_RESEARCH_REUSE_CANDIDATE":
                world_has_candidate = True
            elif lifecycle == "SCAFFOLDED":
                world_has_scaffolded = True
            elif lifecycle == "ADVISORY":
                world_has_advisory = True

        if world_has_prior_evidence:
            learning_prior_evidence_worlds += 1
        if world_has_candidate:
            learning_candidate_worlds += 1
        if world_has_scaffolded:
            learning_scaffolded_worlds += 1
        if world_has_advisory:
            learning_advisory_worlds += 1
        if world_all_no_prior:
            learning_no_prior_worlds += 1

        if int(full_feedback.get("positive_priors") or 0) or int(full_feedback.get("negative_priors") or 0):
            learning_exposed_worlds += 1
        if int(full_feedback.get("crystal_reuse_count") or 0):
            crystal_reused_worlds += 1

        full_map = by_model(full_comp.evaluate(full_feature, (horizon,)))
        variants = {
            "NO_LEARNING": by_model(full_comp.evaluate(no_learning_feature, (horizon,))),
            "NO_CRYSTALS": by_model(full_comp.evaluate(no_crystal_feature, (horizon,))),
            "NO_WORKERS": by_model(no_workers_comp.evaluate(no_workers_feature, (horizon,))),
            "NO_STATISTICS": by_model(full_comp.evaluate(no_statistics_feature, (horizon,))),
            "NO_BAYES": by_model(full_comp.evaluate(no_bayes_feature, (horizon,))),
        }

        attack_variants = {}
        full_values = dict(full_feature.values or {})
        current_stats = full_values.get("phase2_statistical_hypothesis_context_by_model")
        if isinstance(current_stats, dict) and current_stats:
            model_ids = sorted(current_stats)
            rows = [
                dict(current_stats[model_id])
                for model_id in model_ids
                if isinstance(current_stats.get(model_id), dict)
            ]
            rotated = {}
            if len(model_ids) > 1:
                for idx, model_id in enumerate(model_ids):
                    donor = model_ids[(idx + 1) % len(model_ids)]
                    rotated[model_id] = dict(current_stats[donor])
            else:
                rotated = {model_ids[0]: dict(current_stats[model_ids[0]])}
            shuffled_values = dict(full_values)
            shuffled_values["phase2_statistical_hypothesis_context_by_model"] = rotated
            shuffled_feature = FeatureVector(**{**asdict(full_feature), "values": shuffled_values})
            attack_variants["SHUFFLE_EVIDENCE"] = by_model(
                full_comp.evaluate(shuffled_feature, (horizon,))
            )

            if rows:
                pooled = {
                    "schema":"hivenance_hypothesis_statistical_context_v1",
                    "state_id":"pooled-global",
                    "as_of_ms":int(feature.timestamp_ms),
                    "win_probability":mean(
                        float(row.get("win_probability") or .5)
                        for row in rows
                    ),
                    "edge_positive_probability":(
                        mean(
                            float(row["edge_positive_probability"])
                            for row in rows
                            if row.get("edge_positive_probability") is not None
                        )
                        if any(row.get("edge_positive_probability") is not None for row in rows)
                        else None
                    ),
                    "uncertainty":mean(
                        float(row.get("uncertainty") or 0.0)
                        for row in rows
                    ),
                    "change_point_probability":mean(
                        float(row.get("change_point_probability") or 0.0)
                        for row in rows
                    ),
                    "effective_sample_size":mean(
                        float(row.get("effective_sample_size") or 0.0)
                        for row in rows
                    ),
                    "authority":"RESEARCH_CONTEXT_ONLY",
                    "execution_eligible":False,
                    "promotion_eligible":False,
                }
                pooled_values = dict(full_values)
                pooled_values["phase2_statistical_hypothesis_context_by_model"] = {
                    model_id:dict(pooled)
                    for model_id in model_ids
                }
                pooled_feature = FeatureVector(**{**asdict(full_feature), "values": pooled_values})
                attack_variants["POOLED_GLOBAL_CONTEXT"] = by_model(
                    full_comp.evaluate(pooled_feature, (horizon,))
                )

                def component_feature(component):
                    mapped={}
                    for model_id in model_ids:
                        raw=dict(current_stats[model_id])
                        if component=="edge":
                            raw["uncertainty"]=0.0
                            raw["change_point_probability"]=0.0
                        elif component=="change":
                            raw["uncertainty"]=0.0
                            raw["edge_positive_probability"]=None
                            raw["effective_sample_size"]=0.0
                        elif component=="uncertainty":
                            raw["change_point_probability"]=0.0
                            raw["edge_positive_probability"]=None
                            raw["effective_sample_size"]=0.0
                        elif component=="no_edge":
                            raw["edge_positive_probability"]=None
                            raw["effective_sample_size"]=0.0
                        elif component=="no_change":
                            raw["change_point_probability"]=0.0
                        elif component=="no_uncertainty":
                            raw["uncertainty"]=0.0
                        mapped[model_id]=raw
                    values=dict(full_values)
                    values["phase2_statistical_hypothesis_context_by_model"]=mapped
                    return FeatureVector(**{**asdict(full_feature),"values":values})

                attack_variants["NEGATIVE_EDGE_ONLY"] = by_model(
                    full_comp.evaluate(component_feature("edge"), (horizon,))
                )
                attack_variants["CHANGE_POINT_ONLY"] = by_model(
                    full_comp.evaluate(component_feature("change"), (horizon,))
                )
                attack_variants["UNCERTAINTY_ONLY"] = by_model(
                    full_comp.evaluate(component_feature("uncertainty"), (horizon,))
                )
                attack_variants["NO_NEGATIVE_EDGE_GATE"] = by_model(
                    full_comp.evaluate(component_feature("no_edge"), (horizon,))
                )
                attack_variants["NO_CHANGE_POINT_GATE"] = by_model(
                    full_comp.evaluate(component_feature("no_change"), (horizon,))
                )
                attack_variants["NO_UNCERTAINTY_GATE"] = by_model(
                    full_comp.evaluate(component_feature("no_uncertainty"), (horizon,))
                )

            if (
                previous_statistics_by_model
                and previous_statistics_timestamp_ms is not None
                and int(previous_statistics_timestamp_ms) < int(feature.timestamp_ms)
            ):
                shifted_values = dict(full_values)
                shifted_values["phase2_statistical_hypothesis_context_by_model"] = {
                    str(model_id): dict(payload)
                    for model_id, payload in previous_statistics_by_model.items()
                }
                shifted_feature = FeatureVector(**{**asdict(full_feature), "values": shifted_values})
                attack_variants["TIME_SHIFT_PLACEBO"] = by_model(
                    full_comp.evaluate(shifted_feature, (horizon,))
                )

            if (
                previous_statistics_timestamp_ms is None
                or int(feature.timestamp_ms) > int(previous_statistics_timestamp_ms)
            ):
                previous_statistics_by_model = {
                    str(model_id): dict(payload)
                    for model_id, payload in current_stats.items()
                    if isinstance(payload, dict)
                }
                previous_statistics_timestamp_ms = int(feature.timestamp_ms)

        historical_bayes.stage(feature)

        world_hash = "sha256:" + hashlib.sha256(
            str(raw_payload).encode("utf-8")
        ).hexdigest()
        timestamp_ms = int(feature.timestamp_ms)

        for identity, forecast in full_map.items():
            model_id, model_horizon = identity
            census_outcomes["FULL_HIVE"].append(
                HistoricalWorldOutcome(
                    world_state_id=str(observation_run_id),
                    world_state_hash=world_hash,
                    symbol=str(symbol),
                    timestamp_ms=timestamp_ms,
                    horizon_seconds=int(model_horizon),
                    direction=str(forecast.direction),
                    abstain=bool(forecast.abstain),
                    selected=None,
                    realized_net_bps=realized_net(forecast, market_move_bps),
                    envelope_id=str(model_id),
                ).to_dict()
            )

        for mask_id, blind_map in variants.items():
            identities = sorted(set(full_map) | set(blind_map))
            for identity in identities:
                model_id, model_horizon = identity
                blind = blind_map.get(identity)
                if blind is None:
                    if mask_id != "NO_WORKERS":
                        continue
                    census_outcomes[mask_id].append(
                        HistoricalWorldOutcome(
                            world_state_id=str(observation_run_id),
                            world_state_hash=world_hash,
                            symbol=str(symbol),
                            timestamp_ms=timestamp_ms,
                            horizon_seconds=int(model_horizon),
                            direction="ABSTAIN",
                            abstain=True,
                            selected=None,
                            realized_net_bps=0.0,
                            envelope_id=str(model_id),
                        ).to_dict()
                    )
                    continue
                census_outcomes[mask_id].append(
                    HistoricalWorldOutcome(
                        world_state_id=str(observation_run_id),
                        world_state_hash=world_hash,
                        symbol=str(symbol),
                        timestamp_ms=timestamp_ms,
                        horizon_seconds=int(model_horizon),
                        direction=str(blind.direction),
                        abstain=bool(blind.abstain),
                        selected=None,
                        realized_net_bps=realized_net(blind, market_move_bps),
                        envelope_id=str(model_id),
                    ).to_dict()
                )

        world_key = (observation_run_id, symbol, float(forecast_ts), int(horizon))

        no_stats_map = variants.get("NO_STATISTICS", {})
        raw_stats_map = (
            full_feature.values.get("phase2_statistical_hypothesis_context_by_model")
            if isinstance(full_feature.values, dict)
            else {}
        )
        for identity, full_forecast in full_map.items():
            blind = no_stats_map.get(identity)
            if blind is None:
                continue
            if full_forecast.abstain and not blind.abstain:
                reason = str(full_forecast.reason or "unknown")
                if reason.startswith("statistical_synthesis_"):
                    statistical_veto_reasons[reason] += 1

                model_id = str(identity[0])
                raw = raw_stats_map.get(model_id) if isinstance(raw_stats_map, dict) else None
                if isinstance(raw, dict):
                    triggers=[]
                    if float(raw.get("uncertainty") or 0.0) >= 0.82:
                        triggers.append("UNCERTAINTY")
                    if float(raw.get("change_point_probability") or 0.0) >= 0.78:
                        triggers.append("CHANGE_POINT")
                    edge_p=raw.get("edge_positive_probability")
                    if (
                        edge_p is not None
                        and float(raw.get("effective_sample_size") or 0.0) >= 5.0
                        and float(edge_p) <= 0.35
                    ):
                        triggers.append("NEGATIVE_EDGE")
                    statistical_trigger_overlap["+".join(triggers) if triggers else "NONE"] += 1

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

        for attack_id, attacked_map in attack_variants.items():
            attack_stats[attack_id]["testable_worlds"] += 1
            deltas = []
            compare_maps(
                full=full_map,
                blind=attacked_map,
                market_move_bps=market_move_bps,
                mask_id=attack_id,
                stats=attack_stats[attack_id],
                world_bucket=deltas,
            )
            if deltas:
                attack_stats[attack_id]["changed_worlds"] += 1
                attack_world_deltas[attack_id][world_key].extend(deltas)

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
    print("learning_prior_evidence_worlds=", learning_prior_evidence_worlds)
    print("learning_candidate_worlds=", learning_candidate_worlds)
    print("learning_scaffolded_worlds=", learning_scaffolded_worlds)
    print("learning_advisory_worlds=", learning_advisory_worlds)
    print("learning_no_prior_worlds=", learning_no_prior_worlds)
    print("learning_prior_sample_counts=", dict(sorted(learning_prior_sample_counts.items(), key=lambda x: int(x[0]))))
    print("learning_lifecycles=", dict(sorted(learning_lifecycles.items())))
    if learning_age_samples:
        print("learning_evidence_age_sec_min=", round(min(learning_age_samples), 6))
        print("learning_evidence_age_sec_mean=", round(mean(learning_age_samples), 6))
        print("learning_evidence_age_sec_max=", round(max(learning_age_samples), 6))
    else:
        print("learning_evidence_age_sec_min=", None)
        print("learning_evidence_age_sec_mean=", None)
        print("learning_evidence_age_sec_max=", None)
    print("crystal_reused_worlds=", crystal_reused_worlds)
    print("final_full_learning_crystals=", len(full_registry))
    print("statistical_context_worlds=", statistical_context_worlds)
    print(
        "statistical_effective_n_min=",
        round(min(statistical_effective_n_samples), 6)
        if statistical_effective_n_samples else None,
    )
    print(
        "statistical_effective_n_mean=",
        round(mean(statistical_effective_n_samples), 6)
        if statistical_effective_n_samples else None,
    )
    print(
        "statistical_effective_n_max=",
        round(max(statistical_effective_n_samples), 6)
        if statistical_effective_n_samples else None,
    )
    print(
        "statistical_edge_probability_mean=",
        round(mean(statistical_edge_probability_samples), 6)
        if statistical_edge_probability_samples else None,
    )
    print("bayes_context_worlds=", bayes_context_worlds)
    print(
        "bayes_disagreement_mean=",
        round(mean(bayes_disagreement_samples), 6)
        if bayes_disagreement_samples else None,
    )
    print(
        "bayes_disagreement_max=",
        round(max(bayes_disagreement_samples), 6)
        if bayes_disagreement_samples else None,
    )
    print(
        "bayes_change_probability_mean=",
        round(mean(bayes_change_probability_samples), 6)
        if bayes_change_probability_samples else None,
    )

    print()
    print("STATISTICAL_VETO_REASONS")
    for reason,count in sorted(statistical_veto_reasons.items()):
        print(f"  {reason}=", count)

    print()
    print("STATISTICAL_TRIGGER_OVERLAP")
    for trigger_set,count in sorted(statistical_trigger_overlap.items()):
        print(f"  {trigger_set}=", count)

    print()
    print("STATISTICAL_ADVERSARIAL_ATTACKS")
    for attack_id in STATISTICAL_ATTACKS:
        per_world = {
            key: mean(values)
            for key, values in attack_world_deltas[attack_id].items()
            if values
        }
        grouped = defaultdict(list)
        for key, value in per_world.items():
            grouped[key[0]].append(value)
        cohorts = {
            run_id: mean(values)
            for run_id, values in grouped.items()
            if values
        }
        print(attack_id)
        print("  testable_worlds=", attack_stats[attack_id]["testable_worlds"])
        print("  changed_worlds=", attack_stats[attack_id]["changed_worlds"])
        print("  decision_changes=", attack_stats[attack_id]["decision_changes"])
        print("  full_minus_attack_mean_delta_bps=", mean(per_world.values()) if per_world else None)
        print("  dependence_adjusted_worlds=", len(cohorts))
        print("  positive_cohorts=", sum(1 for x in cohorts.values() if x > 0))
        print("  negative_cohorts=", sum(1 for x in cohorts.values() if x < 0))

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

    if args.census_json_out:
        bundle = {
            "schema": "hivenance_full_organism_census_replay_bundle_v1",
            "source": "report_phase12_learning_crystal_feedback_causality",
            "strict_before": not args.allow_equal_settlement_ts,
            "evidence_lag_sec": float(args.evidence_lag_sec),
            "warning_floor": float(args.warning_floor),
            "outcomes_by_mask": census_outcomes,
            "invocation_counts": {
                "NO_LEARNING": int(stats["NO_LEARNING"]["testable_worlds"]),
                "NO_CRYSTALS": int(stats["NO_CRYSTALS"]["testable_worlds"]),
                "NO_WORKERS": int(stats["NO_WORKERS"]["testable_worlds"]),
                "NO_STATISTICS": int(stats["NO_STATISTICS"]["testable_worlds"]),
                "NO_BAYES": int(stats["NO_BAYES"]["testable_worlds"]),
            },
        }
        with open(args.census_json_out, "w", encoding="utf-8") as fh:
            json.dump(bundle, fh, sort_keys=True, indent=2)
        print("census_json_out=", args.census_json_out)

    conn.close()


if __name__ == "__main__":
    main()
