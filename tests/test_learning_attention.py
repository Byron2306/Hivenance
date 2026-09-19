from strategies.relative_value_lab.learning_retrieval import LearningBrief
from strategies.relative_value_lab.learning_attention import obligations_from_learning

def test_learning_becomes_research_attention_not_authority():
 b=LearningBrief(("h1",),("CANDIDATE",),("state matters",),("coverage incomplete",),("calendar alone",),("flow root","liquidity root"),("HISTORICAL_DISCOVERY_ONLY",))
 o=obligations_from_learning(b)
 assert [(x.action,x.target) for x in o]==[("OBSERVE","flow root"),("OBSERVE","liquidity root"),("CHALLENGE","state matters")]
 assert all(not x.execution_eligible and not x.promotion_eligible for x in o)
