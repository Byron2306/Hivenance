import pytest
from agents.public_microstructure_observer import CustodiedMicrostructure
from strategies.relative_value_lab.learning_attention import ResearchAttentionObligation
from strategies.relative_value_lab.learning_attention_router import LearningAttentionRouter
from strategies.relative_value_lab.research_obligation_lifecycle import ResearchObligationLifecycle
from strategies.relative_value_lab.research_obligation_evidence import attach_microstructure

def test_public_observer_can_satisfy_dispatched_obligation_with_custodied_roots():
 o=ResearchAttentionObligation("REFRESH","refresh stale evidence","stale",("shadow:x",))
 q=LearningAttentionRouter().route(o); life=ResearchObligationLifecycle()
 r=life.dispatch(life.open(o),q)
 m=CustodiedMicrostructure("BTC/USD",10,"t","sha256:"+"a"*64,"b","sha256:"+"b"*64)
 r=attach_microstructure(r,m)
 assert r.state=="EVIDENCE_ATTACHED"
 assert len(r.evidence_roots)==2
 r=life.resolve(r,answer="public evidence refreshed",falsified=False)
 assert r.state=="ANSWERED" and not r.execution_eligible

def test_wrong_owner_cannot_consume_microstructure_as_its_answer():
 o=ResearchAttentionObligation("CHALLENGE","settle shadow control TIME_SHIFT_PLACEBO","unresolved",("shadow:x",))
 q=LearningAttentionRouter().route(o); life=ResearchObligationLifecycle()
 r=life.dispatch(life.open(o),q)
 m=CustodiedMicrostructure("BTC/USD",10,"t","sha256:"+"a"*64,"b","sha256:"+"b"*64)
 with pytest.raises(ValueError): attach_microstructure(r,m)
