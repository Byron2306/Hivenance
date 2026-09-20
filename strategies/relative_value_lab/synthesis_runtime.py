"""Thin research-only runtime joining the canonical WorldGraph cognition spine.

This module deliberately does not grant order, execution, or promotion authority.
It makes invocation/influence inspectable so G0 can ablate organs against an
identical observation tape.
"""
from __future__ import annotations

from .bee_evidence import BeeEvidence
import hashlib,json
from dataclasses import asdict,dataclass
from typing import Any,Mapping,Sequence
from .world_graph import WorldGraph,QueenView
from .world_score import CanonicalScoreFrame
from .world_graph_adapters import add_horizon_context,add_temporal_participation,add_bee_evidence
from .bee_evidence import build_bee_evidence
from .learning_memory import add_learning_receipt
from .learning_retrieval import learning_brief
from .learning_attention import obligations_from_learning
from .learning_attention_router import LearningAttentionRouter
from .comparison_engine import add_comparison_result
from .statistical_synthesis import ProbabilisticSynthesisState
from .regime_context import RegimeContext

def _digest(v:Any)->str:
 raw=json.dumps(v,sort_keys=True,separators=(",",":"),default=str).encode()
 return "sha256:"+hashlib.sha256(raw).hexdigest()

@dataclass(frozen=True)
class OrganReceipt:
 organ_id:str; state:str; input_roots:tuple[str,...]; output_node_ids:tuple[str,...]
 changed_graph:bool; details:Mapping[str,Any]
 execution_eligible:bool=False; promotion_eligible:bool=False
 def to_dict(self): return asdict(self)

@dataclass(frozen=True)
class SynthesisCycle:
 cycle_id:str; world_state_id:str; world_state_hash:str; queen_view:QueenView
 organ_receipts:tuple[OrganReceipt,...]; learning:Mapping[str,Any]
 attention_obligations:tuple[Mapping[str,Any],...]=(); organ_requests:tuple[Mapping[str,Any],...]=()
 execution_eligible:bool=False; promotion_eligible:bool=False
 def to_dict(self): return {"cycle_id":self.cycle_id,"world_state_id":self.world_state_id,
  "world_state_hash":self.world_state_hash,"queen_view":self.queen_view.to_dict(),
  "organ_receipts":tuple(x.to_dict() for x in self.organ_receipts),"learning":dict(self.learning),
  "attention_obligations":self.attention_obligations,"organ_requests":self.organ_requests,
  "execution_eligible":False,"promotion_eligible":False}

class SynthesisRuntime:
 """Compose already-existing organs over one immutable observed frame."""

 def run(self,*,frame:CanonicalScoreFrame,now_ms:int,horizon:Any|None=None,
         horizon_roots:Sequence[str]=(),edge_snapshot:Any|None=None,
         edge_roots:Mapping[str,Sequence[str]]|None=None,
         temporal_participation:Any|None=None,
         learning_receipts:Sequence[Mapping[str,Any]]=(),comparison_results:Sequence[Any]=(),
         statistical_state:ProbabilisticSynthesisState|None=None,
         regime_context:RegimeContext|None=None,
         external_context:Mapping[str,Any]|None=None,
         calibration_context:Mapping[str,Any]|None=None,
         ml_challengers:Sequence[Any]=(),
         disabled_organs:Sequence[str]=())->SynthesisCycle:
  disabled={str(x) for x in disabled_organs};g=WorldGraph(frame);rs=[]

  def receipt(organ,state,roots=(),nodes=(),**details):
   rs.append(OrganReceipt(organ,state,tuple(sorted(set(roots))),
     tuple(n.node_id for n in nodes),bool(nodes),details))

  if horizon is None or "horizon_context" in disabled:
   receipt("horizon_context","DISABLED" if "horizon_context" in disabled else "AVAILABLE_NOT_INVOKED")
  else:
   n=add_horizon_context(g,context=horizon,created_at_ms=now_ms,source_roots=horizon_roots)
   receipt("horizon_context","INVOKED",horizon_roots,(n,))

  if edge_snapshot is None or "edge_ecology" in disabled:
   receipt("edge_ecology","DISABLED" if "edge_ecology" in disabled else "AVAILABLE_NOT_INVOKED")
  else:
   roots=edge_roots or {}
   ns=[]
   for voice in edge_snapshot.voices:
    family=str(voice.family).upper()
    source_roots=tuple(sorted(set(map(str,roots.get(family,())))))
    if not source_roots:
     raise ValueError(f"edge_voice_missing_source_roots:{family}")

    payload={
     "pair_id":edge_snapshot.pair_id,
     "timestamp_ms":edge_snapshot.timestamp_ms,
     **voice.to_dict(),
    }

    evidence=build_bee_evidence(
     family=family,
     source_kind="EDGE_ECOLOGY_DERIVED_FROM_PUBLIC_MARKET",
     source_ids=(
      f"{edge_snapshot.pair_id}:{edge_snapshot.timestamp_ms}:{family}",
     ),
     evidence_roots=source_roots,
     lineage=(
      "hivenance.edge_ecology.v1",
      f"{family.lower()}.v1",
     ),
     transformation_version=f"edge_ecology.{family.lower()}_to_bee_evidence.v1",
     observed_at_ms=int(edge_snapshot.timestamp_ms),
     available_at_ms=max(
      int(edge_snapshot.timestamp_ms),
      int(now_ms),
     ),
     freshness=1.0,
     confidence=max(
      0.0,
      min(1.0,float(voice.confidence)),
     ),
     missingness=(),
     abstention=False,
     payload=payload,
    )

    ns.append(
     add_bee_evidence(
      g,
      evidence=evidence,
      created_at_ms=now_ms,
     )
    )

   receipt(
    "edge_ecology",
    "INVOKED",
    (r for xs in roots.values() for r in xs),
    ns,
   )

  if temporal_participation is None or "temporal_participation_bee" in disabled:
   receipt(
    "temporal_participation_bee",
    "DISABLED" if "temporal_participation_bee" in disabled
    else "AVAILABLE_NOT_INVOKED"
   )
  else:
   same_hour_n=int(
    getattr(
     temporal_participation,
     "historical_same_hour_n",
     0,
    )
   )
   ratio=getattr(
    temporal_participation,
    "volume_ratio_to_same_hour_median",
    None,
   )

   missingness=()
   if ratio is None:
    missingness=("same_hour_baseline_insufficient",)

   confidence=(
    0.0
    if ratio is None
    else max(
     0.05,
     min(
      1.0,
      1.0-(1.0/max(1.0,float(same_hour_n)**0.5)),
     ),
    )
   )

   bee=BeeEvidence(
    schema="hivenance_bee_evidence_v1",
    evidence_id=str(
     temporal_participation.evidence_id
    ),
    family="TEMPORAL_PARTICIPATION",
    source_kind="historical_reconstruction",
    source_ids=(
     str(
      temporal_participation.evidence_id
     ),
    ),
    evidence_roots=(
     str(
      temporal_participation.evidence_root
     ),
    ),
    lineage=(
     "hivenance.temporal_participation_bee.v1",
    ),
    transformation_version=(
     "utc_same_hour_participation.v1"
    ),
    observed_at_ms=int(
     temporal_participation.observed_at_ms
    ),
    available_at_ms=int(
     temporal_participation.observed_at_ms
    ),
    freshness=1.0,
    confidence=confidence,
    missingness=missingness,
    abstention=bool(
     ratio is None
    ),
    payload=temporal_participation.to_dict(),
    execution_eligible=False,
    promotion_eligible=False,
   )

   n=add_bee_evidence(
    g,
    evidence=bee,
    created_at_ms=now_ms,
   )

   receipt(
    "temporal_participation_bee",
    "INVOKED",
    (
     temporal_participation.evidence_root,
    ),
    (n,),
    canonical_phase5_family=(
     "TEMPORAL_PARTICIPATION"
    ),
    canonical_graph_organ=(
     "bee_evidence"
    ),
   )

  learned=[]
  if "learning_memory" in disabled:
   receipt("learning_memory","DISABLED")
  else:
   for x in learning_receipts: learned.append(add_learning_receipt(g,x,created_at_ms=now_ms))
   receipt("learning_memory","INVOKED" if learned else "AVAILABLE_NOT_INVOKED",
           (r for n in learned for r in n.evidence_roots),learned,count=len(learned))

  statistical=[]
  if statistical_state is None or "statistics_bee" in disabled:
   receipt(
    "statistics_bee",
    "DISABLED" if "statistics_bee" in disabled else "AVAILABLE_NOT_INVOKED",
   )
  else:
   if int(statistical_state.as_of_ms)>int(now_ms):
    raise ValueError("statistics_state_from_future")
   node=g.add_node(
    organ_id="STATISTICS_BEE",
    family="STATISTICAL_SYNTHESIS",
    created_at_ms=now_ms,
    evidence_roots=statistical_state.evidence_roots,
    lineage_id=statistical_state.state_id,
    transformation_id=statistical_state.schema,
    payload=statistical_state.to_dict(),
    freshness=1.0,
    uncertainty=float(statistical_state.uncertainty),
    synthetic=False,
   )
   statistical.append(node)
   receipt(
    "statistics_bee",
    "INVOKED",
    statistical_state.evidence_roots,
    statistical,
    state_id=statistical_state.state_id,
    effective_sample_size=statistical_state.effective_sample_size,
    change_point_probability=statistical_state.change_point_probability,
   )

  regime_nodes=[]
  if regime_context is None or "regime_context" in disabled:
   receipt(
    "regime_context",
    "DISABLED" if "regime_context" in disabled else "AVAILABLE_NOT_INVOKED",
   )
  else:
   if int(regime_context.as_of_ms)>int(now_ms):
    raise ValueError("regime_context_from_future")
   roots=tuple(sorted(set(
    str(root)
    for root in tuple(regime_context.provenance.get("evidence_roots") or ())
    if str(root).startswith("sha256:")
   )))
   node=g.add_node(
    organ_id="REGIME_CONTEXT",
    family="REGIME_CONTEXT",
    created_at_ms=now_ms,
    evidence_roots=roots,
    lineage_id=regime_context.context_id,
    transformation_id=regime_context.schema,
    payload=regime_context.to_dict(),
    freshness=1.0,
    uncertainty=max(
     float(regime_context.posterior_entropy or 0.0),
     float(regime_context.disagreement_score),
     float(regime_context.change_point_probability),
    ),
    synthetic=False,
   )
   regime_nodes.append(node)
   receipt(
    "regime_context",
    "INVOKED",
    roots,
    regime_nodes,
    context_id=regime_context.context_id,
    dominant_posterior_regime=regime_context.dominant_posterior_regime,
    disagreement_score=regime_context.disagreement_score,
    change_point_probability=regime_context.change_point_probability,
   )

  external_nodes=[]
  if external_context is None or "external_statistics" in disabled:
   receipt(
    "external_statistics",
    "DISABLED" if "external_statistics" in disabled else "AVAILABLE_NOT_INVOKED",
   )
  else:
   ext=dict(external_context)
   ext_roots=tuple(sorted({
    str(root)
    for item in tuple(ext.get("features") or ())
    if isinstance(item,Mapping)
    for root in (item.get("evidence_root"),)
    if root and str(root).startswith("sha256:")
   }))
   node=g.add_node(
    organ_id="EXTERNAL_STATISTICS",
    family="EXTERNAL_STATISTICS",
    created_at_ms=now_ms,
    evidence_roots=ext_roots,
    lineage_id=str(ext.get("sensorium_id") or "external_statistics"),
    transformation_id=str(ext.get("schema") or "hivenance_external_statistics_context_v1"),
    payload=ext,
    freshness=1.0,
    uncertainty=max(0.0,min(1.0,float(ext.get("uncertainty") or 0.0))),
    synthetic=False,
   )
   external_nodes.append(node)
   receipt("external_statistics","INVOKED",ext_roots,external_nodes)

  calibration_nodes=[]
  if calibration_context is None or "calibration_context" in disabled:
   receipt(
    "calibration_context",
    "DISABLED" if "calibration_context" in disabled else "AVAILABLE_NOT_INVOKED",
   )
  else:
   cal=dict(calibration_context)
   cal_roots=tuple(sorted({
    str(root) for root in tuple(cal.get("evidence_roots") or ())
    if str(root).startswith("sha256:")
   }))
   node=g.add_node(
    organ_id="CALIBRATION_CONTEXT",
    family="CALIBRATION_CONTEXT",
    created_at_ms=now_ms,
    evidence_roots=cal_roots,
    lineage_id=str(cal.get("health_id") or cal.get("interval_id") or "calibration_context"),
    transformation_id=str(cal.get("schema") or "hivenance_calibration_context_v1"),
    payload=cal,
    freshness=1.0,
    uncertainty=max(
     0.0,min(1.0,float(cal.get("overall_drift_score") or cal.get("coverage_error") or 0.0))
    ),
    synthetic=False,
   )
   calibration_nodes.append(node)
   receipt("calibration_context","INVOKED",cal_roots,calibration_nodes)

  ml_nodes=[]
  if "ml_challenger" in disabled:
   receipt("ml_challenger","DISABLED")
  elif not ml_challengers:
   receipt("ml_challenger","AVAILABLE_NOT_INVOKED")
  else:
   ml_roots=[]
   for challenger in ml_challengers:
    payload=challenger.to_dict() if hasattr(challenger,"to_dict") else dict(challenger)
    root=str(payload.get("evidence_root") or "")
    roots=(root,) if root.startswith("sha256:") else ()
    ml_roots.extend(roots)
    node=g.add_node(
     organ_id="ML_CHALLENGER",
     family="ML_CHALLENGER",
     created_at_ms=now_ms,
     evidence_roots=roots,
     lineage_id=str(payload.get("forecast_id") or payload.get("receipt_id") or payload.get("model_id") or "ml_challenger"),
     transformation_id=str(payload.get("schema") or "hivenance_ml_challenger_context_v1"),
     payload=payload,
     freshness=max(0.0,min(1.0,float(payload.get("freshness") or 1.0))),
     uncertainty=max(0.0,min(1.0,float(payload.get("uncertainty_pressure") or payload.get("synthesis_uncertainty") or 0.0))),
     synthetic=False,
    )
    ml_nodes.append(node)
   receipt("ml_challenger","INVOKED",ml_roots,ml_nodes,count=len(ml_nodes))

  compared=[]
  if "comparison_engine" in disabled:
   receipt("comparison_engine","DISABLED")
  else:
   for result in comparison_results: compared.append(add_comparison_result(g,result=result,created_at_ms=now_ms))
   receipt("comparison_engine","INVOKED" if compared else "AVAILABLE_NOT_INVOKED",
           (r for n in compared for r in n.evidence_roots),compared,count=len(compared))

  view=g.queen_view(created_at_ms=now_ms,expected_families=("HORIZON","FLOW","LIQUIDITY","TEMPORAL_PARTICIPATION","LEARNING","COMPARISON","STATISTICAL_SYNTHESIS","REGIME_CONTEXT","EXTERNAL_STATISTICS","CALIBRATION_CONTEXT","ML_CHALLENGER"))
  brief=learning_brief(view)
  learning_context=dict(brief.to_dict())
  learning_context["probabilistic_synthesis"]=(
   statistical_state.to_dict() if statistical_state is not None and "statistics_bee" not in disabled
   else None
  )
  obligations=obligations_from_learning(brief)
  router=LearningAttentionRouter()
  requests=tuple(router.route(o) for o in obligations)
  body={"world_state_id":frame.world_state_id,"world_state_hash":frame.world_state_hash,
        "organs":[x.to_dict() for x in rs],"nodes":[n.node_id for n in view.nodes]}
  return SynthesisCycle("syn_"+_digest(body).split(":",1)[1][:24],frame.world_state_id,
    frame.world_state_hash,view,tuple(rs),learning_context,
    tuple(o.to_dict() for o in obligations),tuple(r.to_dict() for r in requests),False,False)
