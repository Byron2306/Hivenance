"""Phase-2 full temporal lattice for one canonical market world.

The lattice preserves horizon values separately and records common lineage so
price-derived transforms cannot manufacture independent corroboration.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from typing import Any, Mapping

AUTHORITY="PUBLIC_MARKET_RESEARCH_TEMPORAL_LATTICE_ONLY_NO_EXECUTION_AUTHORITY"
SCHEMA="hivenance_full_temporal_lattice_v1"

MICRO=("10s","30s","2m","5m")
MESO=("15m","1h","4h","24h")
MACRO=("7d","30d","365d")
ORACLE=("1h","5h","24h","7d","30d")


def _digest(v:Any)->str:
    raw=json.dumps(v,sort_keys=True,separators=(",",":"),default=str).encode()
    return "sha256:"+hashlib.sha256(raw).hexdigest()


def _num(v:Any)->float|None:
    try:
        x=float(v)
        return x if x==x and abs(x)!=float("inf") else None
    except (TypeError,ValueError):
        return None


def _sign(v:Any, threshold_bps:float=1.0)->int:
    x=_num(v)
    if x is None:return 0
    if x>threshold_bps:return 1
    if x<-threshold_bps:return -1
    return 0


def _entry(*,label:str,value:Any,source:str,evidence_root:str|None,
           age_error_sec:Any=None)->dict[str,Any]:
    x=_num(value)
    return {
        "label":label,
        "status":"PRESENT" if x is not None else "MISSING",
        "change_bps":x,
        "source":source,
        "evidence_root":evidence_root,
        "lineage_group":"PUBLIC_PRICE_HISTORY",
        "age_error_sec":_num(age_error_sec),
        "independent_root_units":1 if x is not None and evidence_root else 0,
    }


def _group_bias(entries:Mapping[str,Mapping[str,Any]])->str:
    signs=[_sign(row.get("change_bps")) for row in entries.values()
           if row.get("status")=="PRESENT"]
    nz=[x for x in signs if x]
    if not nz:return "NEUTRAL_OR_MISSING"
    if all(x>0 for x in nz):return "UP"
    if all(x<0 for x in nz):return "DOWN"
    return "CONFLICT"


def _cross_bias(a:str,b:str)->str:
    aa=a if a in {"UP","DOWN"} else None
    bb=b if b in {"UP","DOWN"} else None
    if aa is None or bb is None:return "UNRESOLVED"
    return "ALIGNED" if aa==bb else "CONFLICT"


@dataclass(frozen=True)
class TemporalLattice:
    lattice_id:str
    symbol:str
    observed_at_ms:int
    canonical_world_state_id:str
    canonical_world_state_hash:str
    micro:dict[str,Any]
    meso:dict[str,Any]
    macro:dict[str,Any]
    oracle:dict[str,Any]
    conflict:dict[str,Any]
    provenance:dict[str,Any]
    authority:str=AUTHORITY
    execution_eligible:bool=False
    promotion_eligible:bool=False
    def to_dict(self)->dict[str,Any]:return asdict(self)


def build_temporal_lattice(*,feature:Any)->TemporalLattice|None:
    values=feature.values if isinstance(getattr(feature,"values",None),dict) else {}
    binding=values.get("canonical_world_binding") if isinstance(values.get("canonical_world_binding"),dict) else {}
    page=binding.get("world_state_page") if isinstance(binding.get("world_state_page"),dict) else {}
    if not binding or not page:
        return None
    temporal=page.get("temporal") if isinstance(page.get("temporal"),dict) else {}
    horizon=page.get("horizon") if isinstance(page.get("horizon"),dict) else {}
    oracle_ctx=values.get("cex_market_oracle") if isinstance(values.get("cex_market_oracle"),dict) else {}
    oracle_h=oracle_ctx.get("horizons") if isinstance(oracle_ctx.get("horizons"),dict) else {}
    root=str(binding.get("feature_memory_line_id") or "") or None

    # WorldState's HorizonContext preserves short-horizon values inside groups.
    h_micro=horizon.get("micro") if isinstance(horizon.get("micro"),dict) else {}
    h_meso=horizon.get("meso") if isinstance(horizon.get("meso"),dict) else {}
    h_macro=horizon.get("macro") if isinstance(horizon.get("macro"),dict) else {}

    micro={
        "10s":_entry(label="10s",value=h_micro.get("return_10s_bps"),source="world_state",evidence_root=root),
        "30s":_entry(label="30s",value=h_micro.get("return_30s_bps"),source="world_state",evidence_root=root),
        "2m":_entry(label="2m",value=h_meso.get("return_2m_bps"),source="world_state",evidence_root=root),
        "5m":_entry(label="5m",value=h_meso.get("return_5m_bps"),source="world_state",evidence_root=root),
    }
    meso={
        "15m":_entry(label="15m",value=temporal.get("15m_bps",h_macro.get("return_15m_bps")),source="world_state",evidence_root=root),
        "1h":_entry(label="1h",value=temporal.get("1h_bps",h_macro.get("return_1h_bps")),source="world_state",evidence_root=root),
        "4h":_entry(label="4h",value=temporal.get("4h_bps"),source="world_state",evidence_root=root),
        "24h":_entry(label="24h",value=temporal.get("24h_bps",h_macro.get("return_24h_bps")),source="world_state",evidence_root=root),
    }
    macro={
        "7d":_entry(label="7d",value=temporal.get("7d_bps"),source="world_state",evidence_root=root),
        "30d":_entry(label="30d",value=temporal.get("30d_bps"),source="world_state",evidence_root=root),
        "365d":_entry(label="365d",value=temporal.get("365d_bps"),source="world_state",evidence_root=root),
    }
    oracle={}
    for label in ORACLE:
        row=oracle_h.get(label) if isinstance(oracle_h.get(label),dict) else {}
        oracle[label]=_entry(
            label=label,
            value=row.get("change_bps") if row.get("available") else None,
            source="cex_market_oracle_context",
            evidence_root=root,
            age_error_sec=row.get("age_error_sec"),
        )

    micro_bias=_group_bias(micro)
    meso_bias=_group_bias(meso)
    macro_bias=_group_bias(macro)
    oracle_bias=_group_bias(oracle)
    conflict={
        "micro_bias":micro_bias,
        "meso_bias":meso_bias,
        "macro_bias":macro_bias,
        "oracle_bias":oracle_bias,
        "micro_vs_meso":_cross_bias(micro_bias,meso_bias),
        "meso_vs_macro":_cross_bias(meso_bias,macro_bias),
        "short_vs_long":_cross_bias(
            meso_bias if meso_bias in {"UP","DOWN"} else micro_bias,
            macro_bias,
        ),
        "world_vs_oracle":_cross_bias(
            meso_bias if meso_bias in {"UP","DOWN"} else macro_bias,
            oracle_bias,
        ),
    }
    provenance={
        "canonical_world_state_id":binding.get("canonical_world_state_id"),
        "canonical_world_state_hash":binding.get("canonical_world_state_hash"),
        "feature_memory_line_id":root,
        "world_state_page_id":page.get("world_state_id"),
        "world_state_provenance":page.get("provenance"),
        "oracle_source":oracle_ctx.get("source"),
        "lineage_groups":{
            "PUBLIC_PRICE_HISTORY":{
                "independent_evidence_roots":1 if root else 0,
                "note":"All horizon returns derived from the same underlying public price-history lineage; transforms are not independent witnesses.",
            }
        },
    }
    body={
        "symbol":str(feature.symbol),
        "observed_at_ms":int(feature.timestamp_ms),
        "canonical_world_state_hash":binding.get("canonical_world_state_hash"),
        "micro":micro,"meso":meso,"macro":macro,"oracle":oracle,
        "conflict":conflict,"provenance":provenance,
    }
    return TemporalLattice(
        lattice_id=_digest(body),
        symbol=str(feature.symbol),
        observed_at_ms=int(feature.timestamp_ms),
        canonical_world_state_id=str(binding.get("canonical_world_state_id") or ""),
        canonical_world_state_hash=str(binding.get("canonical_world_state_hash") or ""),
        micro=micro,meso=meso,macro=macro,oracle=oracle,
        conflict=conflict,provenance=provenance,
    )


def attach_temporal_lattice(feature:Any)->Any:
    lattice=build_temporal_lattice(feature=feature)
    if lattice is None:return feature
    values=dict(feature.values or {})
    values["full_temporal_lattice"]=lattice.to_dict()
    return type(feature)(**{**asdict(feature),"values":values})
