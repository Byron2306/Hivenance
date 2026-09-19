"""Immutable configuration freeze for a G0 evaluation run."""
from __future__ import annotations
import hashlib,json
from dataclasses import asdict,dataclass
from typing import Any,Mapping,Sequence

def _hash(v:Any)->str:
 raw=json.dumps(v,sort_keys=True,separators=(",",":"),default=str).encode()
 return "sha256:"+hashlib.sha256(raw).hexdigest()

@dataclass(frozen=True)
class G0Freeze:
 freeze_id:str; created_at_ms:int; organs:tuple[str,...]; config:Mapping[str,Any]
 authority:str="SYNTHESIS_G0_RESEARCH_ONLY"
 execution_eligible:bool=False; promotion_eligible:bool=False
 def to_dict(self):return asdict(self)

def freeze_g0(*,created_at_ms:int,organs:Sequence[str],config:Mapping[str,Any])->G0Freeze:
 body={"organs":tuple(organs),"config":dict(config)}
 return G0Freeze(_hash(body),int(created_at_ms),tuple(organs),dict(config))
