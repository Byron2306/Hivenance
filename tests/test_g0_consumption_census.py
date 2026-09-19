from types import SimpleNamespace
from strategies.relative_value_lab.g0_consumption_census import model_consumption_census
class Deaf:
 model_id="deaf"
 def forecast(self,features,horizon_seconds=1):return None
class Hearing:
 model_id="hearing"
 def forecast(self,features,horizon_seconds=1):
  return features.values.get("synthesis_context")
def test_census_distinguishes_context_consumers_from_deaf_models():
 c=SimpleNamespace(primary_models=(Deaf(),Hearing()),federated_models=(),worker_models=(),
  medium_trend_models=(),derivatives_trend_models=(),baseline_models=())
 r=model_consumption_census(c)
 assert r["consumers"]==("hearing",)
 assert r["authority"]=="RESEARCH_AUDIT_ONLY" and not r["execution_eligible"]
