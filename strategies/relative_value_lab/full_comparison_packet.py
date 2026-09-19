"""Phase-3 timestamp-safe full comparison packet.

Composes all supported observed comparison families around one current feature.
Comparisons remain descriptive/challenging only and never originate direction.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .comparison_engine import ComparisonEngine, ComparisonReference, ComparisonResult

AUTHORITY="PUBLIC_MARKET_RESEARCH_COMPARISON_PACKET_ONLY_NO_EXECUTION_AUTHORITY"
SCHEMA="hivenance_full_comparison_packet_v1"
FEATURE_NAMES=(
    "volume_zscore",
    "volatility_expansion",
    "spread_bps",
    "book_imbalance",
    "return_zscore",
    "tradable_opportunity_score",
)


def _digest(v:Any)->str:
    return "sha256:"+hashlib.sha256(
        json.dumps(v,sort_keys=True,separators=(",",":"),default=str).encode()
    ).hexdigest()


def _num(v:Any)->float|None:
    try:
        x=float(v)
        return x if x==x and abs(x)!=float("inf") else None
    except (TypeError,ValueError):
        return None


def _root(row:Mapping[str,Any])->str|None:
    values=row.get("values") if isinstance(row.get("values"),Mapping) else {}
    binding=values.get("canonical_world_binding") if isinstance(values.get("canonical_world_binding"),Mapping) else {}
    if not binding:
        fv=values.get("feature_vector") if isinstance(values.get("feature_vector"),Mapping) else {}
        fvv=fv.get("values") if isinstance(fv.get("values"),Mapping) else {}
        binding=fvv.get("canonical_world_binding") if isinstance(fvv.get("canonical_world_binding"),Mapping) else {}
    root=str(binding.get("feature_memory_line_id") or "")
    return root if root.startswith("sha256:") else None


def _temporal_conflict_label(row:Mapping[str,Any])->str|None:
    values=row.get("values") if isinstance(row.get("values"),Mapping) else {}
    binding=values.get("canonical_world_binding") if isinstance(values.get("canonical_world_binding"),Mapping) else {}
    page=binding.get("world_state_page") if isinstance(binding.get("world_state_page"),Mapping) else {}
    temporal=page.get("temporal") if isinstance(page.get("temporal"),Mapping) else {}
    def group(keys:Sequence[str])->int:
        signs=[]
        for key in keys:
            x=_num(temporal.get(key))
            if x is None or abs(x)<=1.0:continue
            signs.append(1 if x>0 else -1)
        if not signs:return 0
        if all(s>0 for s in signs):return 1
        if all(s<0 for s in signs):return -1
        return 2
    short=group(("15m_bps","1h_bps","24h_bps"))
    long=group(("7d_bps","30d_bps","365d_bps"))
    if short in {1,-1} and long in {1,-1}:
        return "NON_CONFLICT" if short==long else "CONFLICT"
    if short==2 or long==2:return "CONFLICT"
    return None


def _features(row:Mapping[str,Any])->dict[str,Any]:
    values=row.get("values") if isinstance(row.get("values"),Mapping) else {}
    fv=values.get("feature_vector") if isinstance(values.get("feature_vector"),Mapping) else {}
    return {
        "volume_zscore":_num(fv.get("volume_zscore",row.get("volume_zscore"))),
        "volatility_expansion":_num(fv.get("volatility_expansion",row.get("volatility_expansion"))),
        "spread_bps":_num(fv.get("spread_bps",row.get("spread_bps"))),
        "book_imbalance":_num(fv.get("book_imbalance",values.get("book_imbalance"))),
        "return_zscore":_num(fv.get("return_zscore",values.get("return_zscore"))),
        "tradable_opportunity_score":_num(values.get("tradable_opportunity_score")),
    }


def _reference(row:Mapping[str,Any], *, selected_default:bool|None=None)->ComparisonReference|None:
    root=_root(row)
    if root is None:
        return None
    ts=int(row.get("timestamp_ms") or 0)
    if ts<=0:
        ts=int(float(row.get("ts") or 0.0)*1000)
    if ts<=0:return None
    symbol=str(row.get("symbol") or "")
    if not symbol:return None
    selected=row.get("selected_for_phase2")
    if not isinstance(selected,bool):selected=selected_default
    return ComparisonReference(
        reference_id="cmpref_"+root.split(":",1)[-1][:20],
        observed_at_ms=ts,
        symbol=symbol,
        utc_hour=datetime.fromtimestamp(ts/1000.0,tz=timezone.utc).hour,
        features=_features(row),
        evidence_roots=(root,),
        selected=selected,
        event_label=_temporal_conflict_label(row),
    )


def _current_features(feature:Any)->dict[str,Any]:
    values=feature.values if isinstance(getattr(feature,"values",None),dict) else {}
    return {
        "volume_zscore":_num(feature.volume_zscore),
        "volatility_expansion":_num(feature.volatility_expansion),
        "spread_bps":_num(feature.spread_bps),
        "book_imbalance":_num(feature.book_imbalance),
        "return_zscore":_num(getattr(feature,"return_zscore",None)),
        "tradable_opportunity_score":_num(values.get("tradable_opportunity_score")),
    }


def build_full_comparison_packet(data_store:Any, feature:Any)->dict[str,Any]:
    engine=ComparisonEngine()
    observed_at_ms=int(feature.timestamp_ms)
    symbol=str(feature.symbol)
    runs=[]
    try:runs=data_store.get_observation_runs(limit=250)
    except Exception:runs=[]

    current_refs=[]
    prior_refs=[]
    current_run_id=None
    selected_rejected_history_runs=0
    for run in runs:
        payload=run.get("payload") if isinstance(run.get("payload"),dict) else {}
        universe=payload.get("comparison_universe") if isinstance(payload.get("comparison_universe"),list) else None
        if universe is None:
            universe=payload.get("candidates") if isinstance(payload.get("candidates"),list) else []
            default_selected=True
        else:
            default_selected=None
            selected_rejected_history_runs+=1
        refs=[]
        for row in universe:
            if not isinstance(row,Mapping):continue
            ref=_reference(row,selected_default=default_selected)
            if ref is not None:refs.append(ref)
        if any(r.observed_at_ms==observed_at_ms for r in refs):
            current_refs.extend(r for r in refs if r.observed_at_ms<=observed_at_ms)
            current_run_id=str((payload.get("run") or {}).get("run_id") or run.get("run_id") or current_run_id or "")
        prior_refs.extend(r for r in refs if r.observed_at_ms<observed_at_ms)

    # De-duplicate by reference identity.
    def dedupe(refs):
        out={}
        for r in refs:out[(r.reference_id,r.symbol,r.observed_at_ms)]=r
        return list(out.values())
    current_refs=dedupe(current_refs)
    prior_refs=dedupe(prior_refs)

    cf=_current_features(feature)
    hour=datetime.fromtimestamp(observed_at_ms/1000.0,tz=timezone.utc).hour
    results=[]
    results.append(engine.same_utc_hour_baseline(
        observed_at_ms=observed_at_ms,symbol=symbol,utc_hour=hour,
        current_features=cf,references=prior_refs,feature_names=FEATURE_NAMES,
    ))
    results.append(engine.cross_section(
        observed_at_ms=observed_at_ms,symbol=symbol,current_features=cf,
        peers=current_refs,feature_names=FEATURE_NAMES,tolerance_ms=180_000,
    ))
    results.append(engine.selected_vs_rejected(
        observed_at_ms=observed_at_ms,symbol=symbol,references=prior_refs,
        feature_names=FEATURE_NAMES,
    ))
    results.append(engine.nearest_prior_states(
        observed_at_ms=observed_at_ms,symbol=symbol,current_features=cf,
        references=[r for r in prior_refs if r.symbol==symbol],
        feature_names=FEATURE_NAMES,k=10,
    ))

    conflict_refs=[r for r in prior_refs if r.event_label in {"CONFLICT","NON_CONFLICT"}]
    results.append(engine.event_vs_control(
        observed_at_ms=observed_at_ms,symbol=symbol,references=conflict_refs,
        event_label="CONFLICT",control_label="NON_CONFLICT",
        feature_names=FEATURE_NAMES,
    ))

    external_event_available=any(
        r.event_label not in {None,"CONFLICT","NON_CONFLICT"} for r in prior_refs
    )
    declarations={
        "EXTERNAL_EVENT_VS_CONTROL":{
            "status":"AVAILABLE" if external_event_available else "ABSENT_EVENT_PROVENANCE",
            "authority":"DESCRIPTIVE_ONLY",
        },
        "NO_TRADE":{
            "status":"DECLARED_PROSPECTIVE_CONTROL",
            "authority":"CONTROL_ONLY",
        },
        "DETERMINISTIC_RANDOM":{
            "status":"DECLARED_PROSPECTIVE_CONTROL",
            "authority":"CONTROL_ONLY",
        },
        "TIME_SHIFT_PLACEBO":{
            "status":"DECLARED_PROSPECTIVE_CONTROL",
            "authority":"CONTROL_ONLY",
        },
        "SIMPLE_NESTED_MODEL":{
            "status":"DECLARED_PROSPECTIVE_CONTROL",
            "authority":"CONTROL_ONLY",
        },
    }
    body={
        "symbol":symbol,
        "observed_at_ms":observed_at_ms,
        "results":[r.to_dict() for r in results],
        "control_declarations":declarations,
        "current_reference_n":len(current_refs),
        "prior_reference_n":len(prior_refs),
    }
    return {
        "schema":SCHEMA,
        "packet_id":_digest(body),
        "symbol":symbol,
        "observed_at_ms":observed_at_ms,
        "current_run_id":current_run_id,
        "comparison_types":[r.comparison_type for r in results],
        "results":[r.to_dict() for r in results],
        "control_declarations":declarations,
        "current_reference_n":len(current_refs),
        "prior_reference_n":len(prior_refs),
        "selected_rejected_history_runs":selected_rejected_history_runs,
        "authority":AUTHORITY,
        "execution_eligible":False,
        "promotion_eligible":False,
    }


def attach_full_comparison_packet(feature:Any,data_store:Any)->Any:
    packet=build_full_comparison_packet(data_store,feature)
    values=dict(feature.values or {})
    values["full_comparison_packet"]=packet
    return type(feature)(**{**asdict(feature),"values":values})


def comparison_results_from_feature(feature:Any)->tuple[ComparisonResult,...]:
    values=feature.values if isinstance(getattr(feature,"values",None),dict) else {}
    packet=values.get("full_comparison_packet") if isinstance(values.get("full_comparison_packet"),dict) else {}
    out=[]
    for raw in packet.get("results") or ():
        if not isinstance(raw,Mapping):continue
        out.append(ComparisonResult(
            schema=str(raw.get("schema") or "hivenance_comparison_result_v1"),
            comparison_id=str(raw.get("comparison_id") or ""),
            comparison_type=str(raw.get("comparison_type") or ""),
            observed_at_ms=int(raw.get("observed_at_ms") or 0),
            symbol=str(raw.get("symbol") or ""),
            reference_ids=tuple(raw.get("reference_ids") or ()),
            metrics=dict(raw.get("metrics") or {}),
            evidence_roots=tuple(raw.get("evidence_roots") or ()),
            matched_n=int(raw.get("matched_n") or 0),
            authority=str(raw.get("authority") or ""),
            execution_eligible=False,
            promotion_eligible=False,
        ))
    return tuple(out)
