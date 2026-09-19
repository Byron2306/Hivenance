import pytest
from strategies.relative_value_lab.learning_attention import ResearchAttentionObligation
from strategies.relative_value_lab.learning_attention_router import LearningAttentionRouter
from strategies.relative_value_lab.research_obligation_lifecycle import ResearchObligationLifecycle

def test_obligation_requires_real_evidence_before_resolution():
 o=ResearchAttentionObligation("CHALLENGE","settle shadow control TIME_SHIFT_PLACEBO","unresolved",("shadow:x",))
 q=LearningAttentionRouter().route(o); life=ResearchObligationLifecycle(); r=life.open(o)
 assert r.state=="OPEN" and not r.execution_eligible
 r=life.dispatch(r,q); assert r.state=="DISPATCHED" and r.organ_id=="temporal_observer"
 with pytest.raises(ValueError): life.resolve(r,answer="looks fine",falsified=False)
 with pytest.raises(ValueError): life.attach_evidence(r,"synthetic:guess")
 r=life.attach_evidence(r,"sha256:"+"b"*64); assert r.state=="EVIDENCE_ATTACHED"
 r=life.resolve(r,answer="future horizon settled the placebo",falsified=False)
 assert r.state=="ANSWERED" and not r.execution_eligible and not r.promotion_eligible

def test_falsification_is_terminal_evidence_bound_result():
 o=ResearchAttentionObligation("CHALLENGE","challenge same_root lineage","unresolved",("shadow:y",))
 q=LearningAttentionRouter().route(o); life=ResearchObligationLifecycle()
 r=life.attach_evidence(life.dispatch(life.open(o),q),"sha256:"+"c"*64)
 r=life.resolve(r,answer="independent root contradicted candidate",falsified=True)
 assert r.state=="FALSIFIED" and r.family=="LINEAGE"
