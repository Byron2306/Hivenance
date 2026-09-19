import pytest
from strategies.relative_value_lab.learning_attention import ResearchAttentionObligation
from strategies.relative_value_lab.learning_attention_router import LearningAttentionRouter
from strategies.relative_value_lab.research_obligation_lifecycle import ResearchObligationLifecycle
from strategies.relative_value_lab.research_obligation_learning import obligation_learning_receipt
from strategies.relative_value_lab.learning_memory import add_learning_receipt
from strategies.relative_value_lab.learning_retrieval import learning_brief
from strategies.relative_value_lab.world_graph import WorldGraph
from strategies.relative_value_lab.world_score import CanonicalWorldScore,ScoreObservation

def test_resolved_obligation_becomes_evidence_bound_learning_visible_to_queen():
 o=ResearchAttentionObligation("CHALLENGE","settle shadow control TIME_SHIFT_PLACEBO","unresolved",("shadow:x",))
 life=ResearchObligationLifecycle();q=LearningAttentionRouter().route(o)
 r=life.attach_evidence(life.dispatch(life.open(o),q),"sha256:"+"b"*64)
 r=life.resolve(r,answer="placebo failed on completed future horizon",falsified=True)
 rec=obligation_learning_receipt(r,created_at_ms=20)
 assert rec["authority"]=="PROSPECTIVE_RESEARCH_ONLY" and rec["source_artifacts"][0]["sha256"]=="b"*64
 obs=ScoreObservation(observation_id="o",source_id="kraken",source_class="public_market",scope="BTC/USD",observed_at_ms=10,received_at_ms=10,evidence_root="sha256:"+"a"*64,payload={"price":100})
 g=WorldGraph(CanonicalWorldScore.assemble(observations=[obs],assembled_at_ms=10,freshness_window_ms=100))
 n=add_learning_receipt(g,rec,created_at_ms=20)
 b=learning_brief(g.queen_view(created_at_ms=21))
 assert rec["learning_id"] in b.learning_ids
 assert not n.execution_eligible and not n.promotion_eligible

def test_unresolved_obligation_cannot_become_learning():
 o=ResearchAttentionObligation("CHALLENGE","x","unresolved",("shadow:x",))
 with pytest.raises(ValueError): obligation_learning_receipt(ResearchObligationLifecycle().open(o),created_at_ms=20)
