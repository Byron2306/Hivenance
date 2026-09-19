"""Bridge Phoenix forecast + SynthesisCycle testimony into existing PolyphonicQuorum.

The Phoenix forecast is a non-independent CALL. Graph testimony becomes RESPONSE
or COUNTERPOINT depending on whether its existing semantic challenge would veto
that forecast. Evidence independence comes only from graph evidence roots.
"""
from __future__ import annotations
import hashlib,json
from typing import Any
from .musical_cognition import MotifNote
from .polyphonic_quorum import PolyphonicQuorum
from .g0_forecast_challenge import challenge_forecast

def _digest(x:Any)->str:
 return "sha256:"+hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()

_SCOPE_BY_FAMILY={
 "LIQUIDITY":"edge_ecology","FLOW":"edge_ecology","HORIZON":"horizon_context",
 "TEMPORAL_PARTICIPATION":"temporal_participation_bee","LEARNING":"learning_memory",
 "COMPARISON":"comparison_engine",
}

def quorum_for_forecast(*,cycle:Any,forecast:Any,feature:Any)->Any:
 notes=[]
 fid=_digest({"cycle":cycle.cycle_id,"model":forecast.model_id,"horizon":forecast.horizon_seconds})
 notes.append(MotifNote(
  message_id="call_"+fid[-16:],receipt_id=fid,hypothesis_id=str(forecast.hypothesis),
  bee_id="phoenix_hypothesis",family="PHOENIX_FORECAST",lineage_digest=fid,
  root_lineage_digest=None,message_type="WAGGLE",observed_at_ms=int(forecast.timestamp_ms),
  horizon_band=str(forecast.horizon_seconds),direction="",
  expected_move_bps=forecast.expected_move_bps,uncertainty=forecast.uncertainty,
  pulse_type="FORECAST_CALL",evidence_root=cycle.world_state_hash,
  world_state_id=cycle.world_state_id,world_state_hash=cycle.world_state_hash,
  independent_voice=False))
 for n in cycle.queen_view.nodes:
  if not n.evidence_roots:continue
  scope=_SCOPE_BY_FAMILY.get(str(n.family))
  if not scope:continue
  challenged=challenge_forecast(forecast,feature,organ_scope=scope)
  vetoed=bool(challenged.abstain and not forecast.abstain)
  roots=tuple(sorted(set(n.evidence_roots)))
  lineage=_digest({"family":n.family,"roots":roots})
  notes.append(MotifNote(
   message_id="note_"+n.node_id[-16:],receipt_id=n.node_id,hypothesis_id=str(forecast.hypothesis),
   bee_id=str(n.organ_id),family=str(n.family),lineage_digest=str(n.lineage_id),
   root_lineage_digest=lineage,message_type="DISSENT" if vetoed else "FOLLOW",
   observed_at_ms=int(n.created_at_ms),horizon_band=str(forecast.horizon_seconds),direction="",
   expected_move_bps=None,uncertainty=float(n.uncertainty),pulse_type="COUNTERPOINT" if vetoed else "RESPONSE",
   evidence_root=roots[0],world_state_id=cycle.world_state_id,world_state_hash=cycle.world_state_hash,
   independent_voice=True))
 return PolyphonicQuorum().score(tuple(notes))
