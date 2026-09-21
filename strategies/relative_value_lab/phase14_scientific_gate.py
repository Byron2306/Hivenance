from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class Phase14BookResult:
    book_id: str
    settled_n: int
    distinct_worlds: int
    mean_net_bps: float | None
    median_net_bps: float | None
    ci95_low_bps: float | None
    ci95_high_bps: float | None
    max_drawdown_bps: float | None
    positive_worlds: int
    negative_worlds: int
    classification: str

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


def _drawdown(values: Sequence[float])->float|None:
    if not values:
        return None
    equity=0.0
    peak=0.0
    worst=0.0
    for value in values:
        equity+=float(value)
        peak=max(peak,equity)
        worst=min(worst,equity-peak)
    return worst


def summarize_book(
    *,
    book_id: str,
    realized_net_bps: Sequence[float],
    world_ids: Sequence[str],
    minimum_samples: int,
    minimum_distinct_market_worlds: int,
)->Phase14BookResult:
    values=[float(x) for x in realized_net_bps]
    distinct=len(set(str(x) for x in world_ids))
    n=len(values)
    mean_value=statistics.mean(values) if values else None
    median_value=statistics.median(values) if values else None
    if len(values)>=2:
        se=statistics.stdev(values)/math.sqrt(len(values))
        lo=float(mean_value)-1.96*se
        hi=float(mean_value)+1.96*se
    else:
        lo=hi=None

    if n<int(minimum_samples) or distinct<int(minimum_distinct_market_worlds):
        classification="INSUFFICIENT_EVIDENCE"
    elif lo is not None and lo>0:
        classification="PROSPECTIVELY_USEFUL_CANDIDATE"
    elif hi is not None and hi<0:
        classification="NOT_USEFUL_ON_TESTED_DOMAIN"
    else:
        classification="PROSPECTIVELY_MIXED_OR_UNRESOLVED"

    return Phase14BookResult(
        book_id=str(book_id),
        settled_n=n,
        distinct_worlds=distinct,
        mean_net_bps=mean_value,
        median_net_bps=median_value,
        ci95_low_bps=lo,
        ci95_high_bps=hi,
        max_drawdown_bps=_drawdown(values),
        positive_worlds=sum(1 for x in values if x>0),
        negative_worlds=sum(1 for x in values if x<0),
        classification=classification,
    )


def validate_phase14_input(
    *,
    expected_freeze_id: str,
    receipt_freeze_ids: Sequence[str],
)->None:
    ids={str(x) for x in receipt_freeze_ids if str(x)}
    if ids!={str(expected_freeze_id)}:
        raise ValueError("phase14_freeze_mismatch")



def clustered_world_summary(
    rows: Sequence[Mapping[str,Any]],
) -> dict[str,Any]:
    by_world: dict[str,list[float]]={}
    for row in rows:
        if row.get("realized_net_bps") is None:
            continue
        world=str(row.get("world_state_id") or "")
        by_world.setdefault(world,[]).append(float(row["realized_net_bps"]))
    means=[
        statistics.mean(values)
        for values in by_world.values()
        if values
    ]
    if not means:
        return {"worlds":0,"mean_bps":None,"ci95_low_bps":None,"ci95_high_bps":None}
    mu=statistics.mean(means)
    if len(means)>=2:
        se=statistics.stdev(means)/math.sqrt(len(means))
        lo=mu-1.96*se
        hi=mu+1.96*se
    else:
        lo=hi=None
    return {
        "worlds":len(means),
        "mean_bps":mu,
        "ci95_low_bps":lo,
        "ci95_high_bps":hi,
    }


def approximate_two_sided_pvalue(mean_value: float | None, values: Sequence[float]) -> float | None:
    xs=[float(x) for x in values]
    if mean_value is None or len(xs)<2:
        return None
    sd=statistics.stdev(xs)
    if sd<=0:
        return 0.0 if float(mean_value)!=0 else 1.0
    z=abs(float(mean_value))/(sd/math.sqrt(len(xs)))
    # Normal-tail approximation via erfc.
    return math.erfc(z/math.sqrt(2.0))


def holm_bonferroni(pvalues: Mapping[str,float|None]) -> dict[str,Any]:
    valid=sorted(
        ((key,float(value)) for key,value in pvalues.items() if value is not None),
        key=lambda item:item[1],
    )
    m=len(valid)
    adjusted={}
    running=0.0
    for rank,(key,p) in enumerate(valid,1):
        adj=min(1.0,(m-rank+1)*p)
        running=max(running,adj)
        adjusted[key]=running
    for key,value in pvalues.items():
        if value is None:
            adjusted[key]=None
    return adjusted


def slice_summary(
    rows: Sequence[Mapping[str,Any]],
    field: str,
) -> dict[str,Any]:
    grouped: dict[str,list[float]]={}
    for row in rows:
        if row.get("realized_net_bps") is None:
            continue
        key=str(row.get(field) or "UNKNOWN")
        grouped.setdefault(key,[]).append(float(row["realized_net_bps"]))
    return {
        key:{
            "n":len(values),
            "mean_net_bps":statistics.mean(values),
            "median_net_bps":statistics.median(values),
            "positive":sum(1 for x in values if x>0),
            "negative":sum(1 for x in values if x<0),
        }
        for key,values in sorted(grouped.items())
    }


def cost_stress_summary(
    rows: Sequence[Mapping[str,Any]],
    multiples: Sequence[float]=(1.0,1.25,1.5,2.0),
) -> dict[str,Any]:
    out={}
    for multiple in multiples:
        values=[]
        for row in rows:
            realized=row.get("realized_net_bps")
            cost=row.get("realized_cost_bps",row.get("expected_cost_bps"))
            if realized is None:
                continue
            base=float(realized)
            if cost is not None:
                base-=max(0.0,float(multiple)-1.0)*float(cost)
            values.append(base)
        out[str(float(multiple))]={
            "n":len(values),
            "mean_net_bps":statistics.mean(values) if values else None,
            "median_net_bps":statistics.median(values) if values else None,
        }
    return out


def fill_realism_summary(rows: Sequence[Mapping[str,Any]]) -> dict[str,Any]:
    attempted=[row for row in rows if not bool(row.get("abstain",False))]
    filled=[
        row for row in attempted
        if str(row.get("fill_status") or "").upper() not in {"MISSED_FILL","UNFILLED",""}
        or bool(row.get("filled",False))
    ]
    missed=[
        row for row in attempted
        if str(row.get("fill_status") or "").upper() in {"MISSED_FILL","UNFILLED"}
    ]
    return {
        "attempted":len(attempted),
        "filled":len(filled),
        "missed_fill":len(missed),
        "fill_rate":(len(filled)/len(attempted)) if attempted else None,
    }


def selection_regret_summary(rows: Sequence[Mapping[str,Any]]) -> dict[str,Any]:
    selected=[
        float(row["realized_net_bps"])
        for row in rows
        if row.get("realized_net_bps") is not None and row.get("selected") is True
    ]
    rejected=[
        float(row["realized_net_bps"])
        for row in rows
        if row.get("realized_net_bps") is not None and row.get("selected") is False
    ]
    selected_mean=statistics.mean(selected) if selected else None
    rejected_mean=statistics.mean(rejected) if rejected else None
    return {
        "selected_n":len(selected),
        "rejected_n":len(rejected),
        "selected_mean_bps":selected_mean,
        "rejected_mean_bps":rejected_mean,
        "selected_minus_rejected_bps":(
            None if selected_mean is None or rejected_mean is None
            else selected_mean-rejected_mean
        ),
    }


def temporal_drift_summary(rows: Sequence[Mapping[str,Any]]) -> dict[str,Any]:
    ordered=sorted(
        [row for row in rows if row.get("realized_net_bps") is not None],
        key=lambda row:float(row.get("timestamp_ms") or row.get("timestamp") or 0),
    )
    if len(ordered)<4:
        return {"classification":"INSUFFICIENT_EVIDENCE","first_half_mean_bps":None,"second_half_mean_bps":None}
    mid=len(ordered)//2
    a=[float(row["realized_net_bps"]) for row in ordered[:mid]]
    b=[float(row["realized_net_bps"]) for row in ordered[mid:]]
    am=statistics.mean(a);bm=statistics.mean(b)
    return {
        "classification":"STABLE_SIGN" if (am>=0)==(bm>=0) else "SIGN_REVERSAL",
        "first_half_mean_bps":am,
        "second_half_mean_bps":bm,
        "delta_bps":bm-am,
    }


def organ_marginal_utility(
    rows: Sequence[Mapping[str,Any]],
) -> dict[str,Any]:
    full_by_key={}
    masked: dict[str,dict[tuple[str,str,int],float]]={}
    for row in rows:
        if row.get("realized_net_bps") is None:
            continue
        key=(
            str(row.get("world_state_id") or ""),
            str(row.get("symbol") or ""),
            int(row.get("horizon_seconds") or 0),
        )
        book=str(row.get("book_id") or "")
        value=float(row["realized_net_bps"])
        if book=="FULL_HIVE_FROZEN":
            full_by_key[key]=value
        elif book.startswith("NO_"):
            masked.setdefault(book,{})[key]=value
    out={}
    for book,values in sorted(masked.items()):
        deltas=[
            full_by_key[key]-masked_value
            for key,masked_value in values.items()
            if key in full_by_key
        ]
        out[book]={
            "paired_n":len(deltas),
            "mean_full_minus_mask_bps":statistics.mean(deltas) if deltas else None,
            "positive_pairs":sum(1 for x in deltas if x>0),
            "negative_pairs":sum(1 for x in deltas if x<0),
        }
    return out


def negative_control_summary(rows: Sequence[Mapping[str,Any]]) -> dict[str,Any]:
    controls={"DETERMINISTIC_RANDOM","NO_TRADE","SIMPLE_MOMENTUM","SIMPLE_REVERSION"}
    out={}
    for control in sorted(controls):
        values=[
            float(row["realized_net_bps"])
            for row in rows
            if str(row.get("book_id") or "")==control
            and row.get("realized_net_bps") is not None
        ]
        out[control]={
            "n":len(values),
            "mean_net_bps":statistics.mean(values) if values else None,
            "median_net_bps":statistics.median(values) if values else None,
        }
    return out


def independent_campaign_replication_summary(
    campaigns: Sequence[Mapping[str, Any]],
    *,
    minimum_fills: int = 30,
    minimum_distinct_symbols: int = 10,
    maximum_single_symbol_fraction: float = 0.30,
) -> dict[str, Any]:
    """Compare already-frozen campaign results without granting authority.

    Each campaign is an independent evidence unit. Missing/insufficient campaigns
    remain visible rather than being pooled until a desired answer appears.
    """
    normalized=[]
    signs=[]
    for raw in campaigns:
        fills=int(raw.get("fills") or 0)
        symbols=int(raw.get("distinct_symbols") or 0)
        mean_gross=raw.get("mean_gross_bps")
        median_gross=raw.get("median_gross_bps")
        mean_net=raw.get("mean_net_bps")
        median_net=raw.get("median_net_bps")
        excess=raw.get("mean_excess_vs_random_bps")
        concentration=raw.get("largest_symbol_fraction")
        sufficient=(
            fills >= int(minimum_fills)
            and symbols >= int(minimum_distinct_symbols)
            and concentration is not None
            and float(concentration) <= float(maximum_single_symbol_fraction)
        )
        economic_pass=(
            sufficient
            and median_gross is not None and float(median_gross) > 0
            and median_net is not None and float(median_net) > 0
            and excess is not None and float(excess) > 0
        )
        if mean_net is not None:
            signs.append(1 if float(mean_net)>0 else (-1 if float(mean_net)<0 else 0))
        normalized.append({
            "campaign_id":str(raw.get("campaign_id") or ""),
            "fills":fills,
            "distinct_symbols":symbols,
            "mean_gross_bps":mean_gross,
            "median_gross_bps":median_gross,
            "mean_net_bps":mean_net,
            "median_net_bps":median_net,
            "mean_excess_vs_random_bps":excess,
            "largest_symbol_fraction":concentration,
            "sufficient":sufficient,
            "economic_pass":economic_pass,
        })

    sufficient_n=sum(1 for row in normalized if row["sufficient"])
    pass_n=sum(1 for row in normalized if row["economic_pass"])
    sign_reversal=bool(signs) and any(x>0 for x in signs) and any(x<0 for x in signs)

    if not normalized or sufficient_n==0:
        classification="INSUFFICIENT_INDEPENDENT_REPLICATION"
    elif sign_reversal:
        classification="REGIME_OR_TEMPORAL_INSTABILITY_DETECTED"
    elif sufficient_n>=2 and pass_n==sufficient_n:
        classification="REPEATED_PROSPECTIVE_SUPPORT"
    elif pass_n==0 and sufficient_n>=1:
        classification="NOT_REPLICATED_ON_TESTED_CAMPAIGNS"
    else:
        classification="MIXED_OR_UNRESOLVED_REPLICATION"

    return {
        "campaigns":normalized,
        "campaign_count":len(normalized),
        "sufficient_campaigns":sufficient_n,
        "passing_campaigns":pass_n,
        "sign_reversal":sign_reversal,
        "classification":classification,
        "authority_effect":"NONE_RESEARCH_ONLY",
        "execution_eligible":False,
        "promotion_eligible":False,
    }


def model_horizon_regime_persistence(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarize evidence at the authority lattice grain.

    This is diagnostic only. It never turns a post-hoc slice into ACTIVE authority.
    """
    grouped: dict[tuple[str,int,str],list[float]]={}
    worlds: dict[tuple[str,int,str],set[str]]={}
    for row in rows:
        value=row.get("realized_net_bps")
        if value is None:
            continue
        key=(
            str(row.get("model_id") or ""),
            int(row.get("horizon_seconds") or 0),
            str(row.get("regime") or "UNKNOWN"),
        )
        grouped.setdefault(key,[]).append(float(value))
        worlds.setdefault(key,set()).add(str(row.get("world_state_id") or ""))

    cells=[]
    for key in sorted(grouped):
        values=grouped[key]
        model_id,horizon,regime=key
        cells.append({
            "model_id":model_id,
            "horizon_seconds":horizon,
            "regime":regime,
            "n":len(values),
            "distinct_worlds":len(worlds[key]),
            "mean_net_bps":statistics.mean(values),
            "median_net_bps":statistics.median(values),
            "positive":sum(1 for x in values if x>0),
            "negative":sum(1 for x in values if x<0),
            "authority_effect":"NONE_RESEARCH_ONLY",
        })
    return {
        "grain":["model_id","horizon_seconds","regime"],
        "cells":cells,
        "post_hoc_activation_forbidden":True,
        "execution_eligible":False,
        "promotion_eligible":False,
    }
