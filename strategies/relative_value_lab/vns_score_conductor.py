from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional, Sequence

from .conducting_queen import VNSSensoryPulse
from .contracts import RELATIVE_VALUE_AUTHORITY
from .world_score import CanonicalScoreFrame, CanonicalWorldScore, ScoreObservation


def _digest(payload: Any) -> str:
    raw=json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")
    return "sha256:"+hashlib.sha256(raw).hexdigest()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float) -> float:
    return max(0.0,min(1.0,float(value)))


OBSERVED_FIELDS=(
    "symbol",
    "venue",
    "timestamp_ms",
    "price",
    "quote_volume_24h",
    "spread_bps",
    "depth_usd_25bps",
    "listing_age_days",
    "venue_count",
    "data_quality",
    "freshness_sec",
    "continuity_ratio",
    "observation_eligible",
)


@dataclass(frozen=True)
class VNSMeasure:
    schema: str
    measure_id: str
    run_id: str
    observed_at_ms: int
    frame: CanonicalScoreFrame
    pulses: tuple[VNSSensoryPulse,...]
    candidate_count: int
    fresh_candidate_count: int
    mean_data_quality: float
    dataset_hash: str
    authority: str=RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool=False
    promotion_eligible: bool=False

    def to_dict(self)->dict[str,Any]:
        payload=asdict(self)
        payload["frame"]=self.frame.to_dict()
        payload["pulses"]=tuple(asdict(pulse) for pulse in self.pulses)
        return payload


class VNSScoreConductor:
    """Compile public observation cycles into canonical measures and VNS accents.

    Only observation-safe fields enter the Canonical Score Frame. Forecasts,
    regime interpretations, hypotheses and synthetic material are intentionally
    excluded from the observed namespace.
    """

    version="hivenance.vns_score_conductor.v1"

    def __init__(
        self,
        *,
        freshness_window_ms:int=15_000,
        pulse_floor:float=.12,
    )->None:
        self.freshness_window_ms=max(1,int(freshness_window_ms))
        self.pulse_floor=_clamp(pulse_floor)
        self._previous_by_scope:dict[str,dict[str,float]]={}

    @staticmethod
    def _observation_payload(candidate:Mapping[str,Any])->dict[str,Any]:
        observed={key:candidate.get(key) for key in OBSERVED_FIELDS if key in candidate}
        values=candidate.get("values") if isinstance(candidate.get("values"),dict) else {}
        crystal=values.get("market_world_state_crystal") if isinstance(values.get("market_world_state_crystal"),dict) else {}
        # These are public-observation-derived microstructure/context fields.
        for key in (
            "spread_bps",
            "depth_usd_25bps",
            "quote_volume_24h",
            "data_quality",
            "freshness_sec",
            "continuity_ratio",
            "volatility_expansion",
            "orderbook_digest",
            "instrument_metadata_digest",
            "exchange_status",
            "fresh_until_ms",
        ):
            if key in crystal:
                observed["crystal_"+key]=crystal.get(key)

        # Explicit contamination guard.
        observed.pop("forecast",None)
        observed.pop("hypothesis",None)
        observed.pop("regime_hint",None)
        return observed

    @staticmethod
    def _evidence_root(candidate:Mapping[str,Any])->str:
        values=candidate.get("values") if isinstance(candidate.get("values"),dict) else {}
        crystal=values.get("market_world_state_crystal") if isinstance(values.get("market_world_state_crystal"),dict) else {}
        crystal_id=str(crystal.get("world_state_id") or "")
        if crystal_id:
            return crystal_id if crystal_id.startswith("sha256:") else "sha256:"+crystal_id
        return _digest(VNSScoreConductor._observation_payload(candidate))

    @classmethod
    def observations_from_cycle(
        cls,
        payload:Mapping[str,Any],
    )->tuple[ScoreObservation,...]:
        run=payload.get("run") if isinstance(payload.get("run"),dict) else {}
        run_id=str(run.get("run_id") or "unknown-run")
        completed_ms=int(run.get("completed_at_ms") or run.get("completed_ms") or 0)
        rows=payload.get("candidates") if isinstance(payload.get("candidates"),list) else []
        observations=[]
        for index,row in enumerate(rows):
            if not isinstance(row,dict):
                continue
            symbol=str(row.get("symbol") or "unknown")
            venue=str(row.get("venue") or run.get("venue") or "unknown")
            observed_at=int(row.get("timestamp_ms") or completed_ms)
            received_at=max(observed_at,completed_ms or observed_at)
            source_id=f"{venue}:{symbol}:phase1_public_observer"
            scope=f"symbol:{symbol}"
            observations.append(ScoreObservation(
                observation_id=f"{run_id}:{index}:{symbol}",
                source_id=source_id,
                source_class="public_market_observer",
                scope=scope,
                observed_at_ms=observed_at,
                received_at_ms=received_at,
                evidence_root=cls._evidence_root(row),
                payload=cls._observation_payload(row),
            ))
        return tuple(observations)

    @staticmethod
    def _candidate_state(candidate:Mapping[str,Any])->dict[str,float]:
        return {
            "price":_float(candidate.get("price")),
            "spread_bps":_float(candidate.get("spread_bps")),
            "depth_usd_25bps":_float(candidate.get("depth_usd_25bps")),
            "data_quality":_float(candidate.get("data_quality")),
            "freshness_sec":_float(candidate.get("freshness_sec")),
            "continuity_ratio":_float(candidate.get("continuity_ratio")),
        }

    def _pulses(
        self,
        *,
        frame:CanonicalScoreFrame,
        candidates:Sequence[Mapping[str,Any]],
        observed_at_ms:int,
    )->tuple[VNSSensoryPulse,...]:
        pulses=[]
        for candidate in candidates:
            if not isinstance(candidate,Mapping):
                continue
            symbol=str(candidate.get("symbol") or "unknown")
            venue=str(candidate.get("venue") or "unknown")
            scope=f"symbol:{symbol}"
            current=self._candidate_state(candidate)
            previous=self._previous_by_scope.get(scope)

            if previous is not None:
                prev_price=max(abs(previous.get("price",0.0)),1e-9)
                price_move=abs(current["price"]-previous.get("price",0.0))/prev_price
                prev_spread=max(abs(previous.get("spread_bps",0.0)),1e-9)
                spread_shift=abs(current["spread_bps"]-previous.get("spread_bps",0.0))/prev_spread
                prev_depth=max(abs(previous.get("depth_usd_25bps",0.0)),1e-9)
                depth_shift=abs(current["depth_usd_25bps"]-previous.get("depth_usd_25bps",0.0))/prev_depth

                accent=_clamp(
                    .40*min(1.0,price_move*100.0)
                    +.30*min(1.0,spread_shift)
                    +.30*min(1.0,depth_shift)
                )
                if accent>=self.pulse_floor:
                    pulse_class=(
                        "spread"
                        if spread_shift>=max(price_move*100.0,depth_shift)
                        else "depth" if depth_shift>=price_move*100.0 else "flow"
                    )
                    confidence=_clamp(
                        .55*current["data_quality"]
                        +.25*current["continuity_ratio"]
                        +.20*(1.0-min(1.0,current["freshness_sec"]/180.0))
                    )
                    pulses.append(VNSSensoryPulse(
                        pulse_id="vns_"+_digest({
                            "scope":scope,
                            "observed_at_ms":observed_at_ms,
                            "class":pulse_class,
                            "frame":frame.world_state_hash,
                        }).split(":",1)[1][:24],
                        observed_at_ms=int(observed_at_ms),
                        scope=scope,
                        pulse_class=pulse_class,
                        amplitude=round(accent,6),
                        confidence=round(confidence,6),
                        freshness=_clamp(1.0-min(1.0,current["freshness_sec"]/180.0)),
                        evidence_root=_digest({
                            "venue":venue,
                            "symbol":symbol,
                            "current":current,
                            "previous":previous,
                            "frame":frame.world_state_hash,
                        }),
                        world_state_id=frame.world_state_id,
                        world_state_hash=frame.world_state_hash,
                    ))

            self._previous_by_scope[scope]=current

        return tuple(sorted(pulses,key=lambda p:(p.scope,p.pulse_class,p.pulse_id)))

    def conduct_cycle(
        self,
        payload:Mapping[str,Any],
    )->VNSMeasure:
        run=payload.get("run") if isinstance(payload.get("run"),dict) else {}
        run_id=str(run.get("run_id") or "unknown-run")
        completed_ms=int(run.get("completed_at_ms") or run.get("completed_ms") or 0)
        if completed_ms<=0:
            raise ValueError("observation_cycle_missing_completed_at_ms")

        observations=self.observations_from_cycle(payload)
        if not observations:
            raise ValueError("observation_cycle_has_no_candidates")

        frame=CanonicalWorldScore.assemble(
            observations=observations,
            assembled_at_ms=completed_ms,
            freshness_window_ms=self.freshness_window_ms,
        )
        candidates=tuple(
            row for row in (payload.get("candidates") or [])
            if isinstance(row,Mapping)
        )
        pulses=self._pulses(
            frame=frame,
            candidates=candidates,
            observed_at_ms=completed_ms,
        )

        qualities=[
            _float(row.get("data_quality"))
            for row in candidates
            if row.get("data_quality") is not None
        ]
        summary=payload.get("world_state_summary") if isinstance(payload.get("world_state_summary"),dict) else {}
        dataset_hash=str(payload.get("dataset_hash") or "")

        body={
            "run_id":run_id,
            "frame":frame.world_state_hash,
            "pulses":[asdict(pulse) for pulse in pulses],
            "dataset_hash":dataset_hash,
        }
        return VNSMeasure(
            schema="hivenance_vns_measure_v1",
            measure_id="measure_"+_digest(body).split(":",1)[1][:24],
            run_id=run_id,
            observed_at_ms=completed_ms,
            frame=frame,
            pulses=pulses,
            candidate_count=len(candidates),
            fresh_candidate_count=int(summary.get("fresh_candidate_count") or 0),
            mean_data_quality=round(statistics.fmean(qualities),6) if qualities else 0.0,
            dataset_hash=dataset_hash,
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )
