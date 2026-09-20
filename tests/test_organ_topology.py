from strategies.relative_value_lab.organ_topology import ORGANS, topology_by_id, validate_topology


def test_organ_topology_is_unique_and_non_authoritative():
    validate_topology()
    ids=[x.organ_id for x in ORGANS]
    assert len(ids)==len(set(ids))
    assert all(x.execution_eligible is False for x in ORGANS)
    assert all(x.promotion_eligible is False for x in ORGANS)


def test_strategy_workers_and_statistics_have_distinct_jobs():
    by=topology_by_id()
    assert by["strategy_workers"].layer=="HYPOTHESIS"
    assert by["statistics_bee"].layer=="STATISTICS"
    assert "DIRECTION_ORIGINATION" in by["statistics_bee"].forbidden_authority
    assert "HYPOTHESIS_COMPETITION" in by["strategy_workers"].allowed_influence


def test_queen_and_pollen_cannot_become_directional_shortcuts():
    by=topology_by_id()
    assert "DIRECT_ORDER_EXECUTION" in by["conducting_queen"].forbidden_authority
    assert "DIRECT_DIRECTIONAL_WEIGHT" in by["pollen_economy"].forbidden_authority
