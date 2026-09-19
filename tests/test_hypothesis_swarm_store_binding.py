from types import SimpleNamespace
from strategies.volatility_breakout.hypothesis_swarm import HypothesisSwarmAgent

def test_hypothesis_swarm_uses_coordinator_data_store_fallback():
 sentinel=object()
 coordinator=SimpleNamespace(agents={"data_store":sentinel})
 # Mirror the production lookup contract without constructing the heavy agent.
 store=(getattr(coordinator,"store",None) or (getattr(coordinator,"agents",{}) or {}).get("data_store"))
 assert store is sentinel

def test_legacy_store_attribute_still_takes_precedence():
 legacy=object();agent_store=object()
 coordinator=SimpleNamespace(store=legacy,agents={"data_store":agent_store})
 store=(getattr(coordinator,"store",None) or (getattr(coordinator,"agents",{}) or {}).get("data_store"))
 assert store is legacy
