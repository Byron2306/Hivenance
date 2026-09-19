import pytest
from strategies.relative_value_lab.learning_attention import ResearchAttentionObligation
from strategies.relative_value_lab.learning_attention_router import LearningAttentionRouter
from strategies.relative_value_lab.research_obligation_lifecycle import ResearchObligationLifecycle
from strategies.relative_value_lab.research_evidence_guards import TemporalEvidence,LineageEvidence,attach_temporal_horizon,attach_independent_lineage

def _dispatch(target):
 o=ResearchAttentionObligation("CHALLENGE",target,"adversarial",("shadow:x",))
 life=ResearchObligationLifecycle()
 return life.dispatch(life.open(o),LearningAttentionRouter().route(o))

def test_temporal_observer_refuses_incomplete_future():
 r=_dispatch("settle shadow control TIME_SHIFT_PLACEBO")
 e=TemporalEvidence("sha256:"+"a"*64,1000,1120)
 with pytest.raises(ValueError,match="future_horizon_incomplete"): attach_temporal_horizon(r,e,required_through_ms=1121)
 r=attach_temporal_horizon(r,TemporalEvidence("sha256:"+"b"*64,1000,1180),required_through_ms=1121)
 assert r.state=="EVIDENCE_ATTACHED"

def test_lineage_guard_requires_distinct_lineage_and_source():
 r=_dispatch("obtain independent lineage")
 with pytest.raises(ValueError,match="same_lineage"): attach_independent_lineage(r,LineageEvidence("sha256:"+"c"*64,"L1","kraken"),challenged_lineage_ids=("L1",),challenged_source_ids=("kraken",))
 with pytest.raises(ValueError,match="same_source"): attach_independent_lineage(r,LineageEvidence("sha256:"+"d"*64,"L2","kraken"),challenged_lineage_ids=("L1",),challenged_source_ids=("kraken",))
 r=attach_independent_lineage(r,LineageEvidence("sha256:"+"e"*64,"L2","coinbase"),challenged_lineage_ids=("L1",),challenged_source_ids=("kraken",))
 assert r.state=="EVIDENCE_ATTACHED" and r.evidence_roots==("sha256:"+"e"*64,)
