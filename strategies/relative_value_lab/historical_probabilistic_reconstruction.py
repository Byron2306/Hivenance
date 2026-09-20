from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from typing import Any, Mapping, Sequence

from strategies.volatility_breakout.models import FeatureVector

from .hypothesis_statistics_bridge import bind_statistical_contexts
from .probabilistic_regime import BayesianRegimeFilter
from .regime_context import build_regime_context
from .statistical_synthesis import StatisticalEvidence, StatisticsBee, SynthesisBee
from .statistics_feedback_bridge import hypothesis_scope


def _root(value: Any) -> str:
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")
    return "sha256:"+hashlib.sha256(raw).hexdigest()


def deterministic_regime_payload(feature: FeatureVector) -> dict[str, Any]:
    values=feature.values if isinstance(feature.values,Mapping) else {}
    regime=values.get("regime_inputs")
    if isinstance(regime,Mapping):
        return dict(regime)
    return {
        "regime_hint":"unknown",
        "confidence":0.0,
    }


def deterministic_regime_likelihoods(payload: Mapping[str, Any]) -> dict[str,float]:
    hint=str(payload.get("regime_hint") or "unknown")
    confidence=max(0.0,min(1.0,float(payload.get("confidence") or 0.0)))
    mapping={
        "trend_expansion":"TREND",
        "stretch_exhaustion":"MEAN_REVERSION",
        "quiet_range":"MEAN_REVERSION",
        "balanced_transition":"TRANSITION",
        "hostile_liquidity":"STRESS",
    }
    target=mapping.get(hint)
    states=("TREND","MEAN_REVERSION","TRANSITION","STRESS")
    if target is None:
        return {state:1.0 for state in states}
    floor=max(0.05,(1.0-confidence)/3.0)
    peak=max(floor,0.55+0.40*confidence)
    return {
        state:(peak if state==target else floor)
        for state in states
    }


class HistoricalStatisticsReconstructor:
    """Point-in-time statistical reconstruction from settled historical forecasts."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.bee=StatisticsBee()
        self.synthesis=SynthesisBee()
        rows=conn.execute(
            """
            SELECT
                f.forecast_id,
                f.model_id,
                f.symbol,
                f.horizon_seconds,
                f.ts AS forecast_ts,
                COALESCE(
                    json_extract(f.payload, '$.inputs.regime_hint'),
                    json_extract(f.payload, '$.inputs.regime_inputs.regime_hint'),
                    'unknown'
                ) AS regime_hint,
                o.net_return_bps,
                o.settled_ts
            FROM hypothesis_outcomes o
            JOIN hypothesis_forecasts f
              ON f.forecast_id=o.forecast_id
            WHERE f.abstain=0
              AND o.settled_ts IS NOT NULL
              AND o.net_return_bps IS NOT NULL
            ORDER BY o.settled_ts, f.forecast_id
            """
        ).fetchall()
        loaded=0
        for row in rows:
            observed_ms=int(round(float(row["forecast_ts"])*1000.0))
            available_ms=int(round(float(row["settled_ts"])*1000.0))
            if available_ms < observed_ms:
                continue
            model_id=str(row["model_id"])
            symbol=str(row["symbol"])
            horizon=int(row["horizon_seconds"])
            regime=str(row["regime_hint"] or "unknown")
            net=float(row["net_return_bps"])
            root=_root({
                "forecast_id":row["forecast_id"],
                "settled_ts":row["settled_ts"],
                "net_return_bps":net,
            })
            evidence_id="histstat:"+str(row["forecast_id"])
            scopes=(
                hypothesis_scope(
                    model_id=model_id,
                    symbol=symbol,
                    horizon_seconds=horizon,
                    regime=regime,
                    scope_kind="exact",
                ),
                hypothesis_scope(
                    model_id=model_id,
                    symbol=symbol,
                    horizon_seconds=horizon,
                    regime="*",
                    scope_kind="model_symbol_horizon",
                ),
                hypothesis_scope(
                    model_id=model_id,
                    symbol="*",
                    horizon_seconds=horizon,
                    regime=regime,
                    scope_kind="model_horizon_regime",
                ),
                hypothesis_scope(
                    model_id=model_id,
                    symbol="*",
                    horizon_seconds=horizon,
                    regime="*",
                    scope_kind="model_horizon",
                ),
            )
            for scope in scopes:
                self.bee.ingest(
                    StatisticalEvidence(
                        evidence_id=evidence_id,
                        scope=scope,
                        observed_at_ms=observed_ms,
                        available_at_ms=available_ms,
                        realized_bps=net,
                        positive=bool(net>0.0),
                        evidence_root=root,
                    )
                )
            loaded+=1
        self.loaded_rows=loaded

    def states_for(
        self,
        feature: FeatureVector,
        *,
        model_ids: Sequence[str],
        horizon_seconds: int,
    ) -> dict[str,Any]:
        regime=str(deterministic_regime_payload(feature).get("regime_hint") or "unknown")
        out={}
        for model_id in model_ids:
            scopes=(
                (
                    hypothesis_scope(
                        model_id=str(model_id),
                        symbol=str(feature.symbol),
                        horizon_seconds=int(horizon_seconds),
                        regime=regime,
                        scope_kind="exact",
                    ),
                    1.0,
                ),
                (
                    hypothesis_scope(
                        model_id=str(model_id),
                        symbol=str(feature.symbol),
                        horizon_seconds=int(horizon_seconds),
                        regime="*",
                        scope_kind="model_symbol_horizon",
                    ),
                    0.75,
                ),
                (
                    hypothesis_scope(
                        model_id=str(model_id),
                        symbol="*",
                        horizon_seconds=int(horizon_seconds),
                        regime=regime,
                        scope_kind="model_horizon_regime",
                    ),
                    0.55,
                ),
                (
                    hypothesis_scope(
                        model_id=str(model_id),
                        symbol="*",
                        horizon_seconds=int(horizon_seconds),
                        regime="*",
                        scope_kind="model_horizon",
                    ),
                    0.35,
                ),
            )

            consumed=[]
            snapshots=[]
            for scope,specificity in scopes:
                snap=self.bee.snapshot(
                    scope=scope,
                    as_of_ms=int(feature.timestamp_ms),
                    exclude_evidence_ids=tuple(consumed),
                )
                snapshots.append((snap,specificity))
                consumed.extend(snap.source_evidence_ids)

            exact=snapshots[0][0]
            broader=tuple(
                (snap,specificity)
                for snap,specificity in snapshots[1:]
                if snap.n>0
            )
            out[str(model_id)]=self.synthesis.synthesize(
                exact=exact,
                broader=broader,
            )
        return out

    def bind(
        self,
        feature: FeatureVector,
        *,
        model_ids: Sequence[str],
        horizon_seconds: int,
    ) -> FeatureVector:
        return bind_statistical_contexts(
            feature,
            self.states_for(
                feature,
                model_ids=model_ids,
                horizon_seconds=horizon_seconds,
            ),
        )


class HistoricalBayesianRegimeReconstructor:
    """Sequential prior-only Bayesian regime reconstruction.

    Current timestamp evidence is staged and is only consumed once a later
    timestamp is encountered, preventing same-time cross-horizon leakage.
    """

    def __init__(self) -> None:
        self.filters: dict[str,BayesianRegimeFilter]={}
        self.pending: dict[str,tuple[int,dict[str,Any],str]]={}

    def _flush_before(self, symbol: str, timestamp_ms: int) -> None:
        pending=self.pending.get(symbol)
        if pending is None:
            return
        observed_ms,payload,evidence_root=pending
        if int(observed_ms) >= int(timestamp_ms):
            return
        filt=self.filters.setdefault(symbol,BayesianRegimeFilter())
        filt.update(
            likelihoods=deterministic_regime_likelihoods(payload),
            as_of_ms=int(observed_ms)+1,
            evidence_available_at_ms=int(observed_ms),
            source_evidence_ids=(f"regime:{symbol}:{observed_ms}",),
            evidence_roots=(evidence_root,),
        )
        del self.pending[symbol]

    def context_for(self, feature: FeatureVector):
        symbol=str(feature.symbol)
        ts=int(feature.timestamp_ms)
        self._flush_before(symbol,ts)
        filt=self.filters.get(symbol)
        posterior=filt.last.to_dict() if filt is not None and filt.last is not None else {}
        return build_regime_context(
            as_of_ms=ts,
            deterministic=deterministic_regime_payload(feature),
            bayesian=posterior,
        )

    def stage(self, feature: FeatureVector) -> None:
        symbol=str(feature.symbol)
        ts=int(feature.timestamp_ms)
        payload=deterministic_regime_payload(feature)
        existing=self.pending.get(symbol)
        if existing is not None and int(existing[0])==ts:
            if dict(existing[1]) != dict(payload):
                raise ValueError("historical_same_time_regime_conflict")
            return
        self.pending[symbol]=(
            ts,
            payload,
            _root({
                "symbol":symbol,
                "timestamp_ms":ts,
                "regime":payload,
            }),
        )


def bind_regime_context(feature: FeatureVector, context: Any) -> FeatureVector:
    values=dict(feature.values or {})
    values["regime_context"]=context.to_dict() if hasattr(context,"to_dict") else dict(context)
    return replace(feature,values=values)
