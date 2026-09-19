from strategies.relative_value_lab.learning_memory import add_learning_receipt
def test_learning_receipt_is_interpreted_and_non_authoritative(world_graph):
 r={"schema":"hivenance_learning_receipt_v1","learning_id":"x","created_at_ms":world_graph.frame.asof_ms,
 "authority":"HISTORICAL_DISCOVERY_ONLY","source_artifacts":[{"sha256":"a"*64}],
 "execution_eligible":False,"promotion_eligible":False,"status":"HISTORICAL_STATE_CONDITIONAL_CANDIDATE"}
 n=add_learning_receipt(world_graph,r)
 assert n.family=="LEARNING";assert n.namespace=="INTERPRETED";assert not n.execution_eligible;assert not n.promotion_eligible
 v=world_graph.queen_view(expected_families=("LEARNING",))
 assert any(x["node_id"]=="learning:x" for x in v.nodes)
