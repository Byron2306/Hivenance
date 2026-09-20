from strategies.relative_value_lab.organ_route_census import build_route_census


def test_route_census_separates_active_from_dead_routes():
    census=build_route_census(
        invocation_counts={"statistics_bee":10,"strategy_workers":4},
        runtime_seen_ids=("statistics_bee","strategy_workers","ml_challenger"),
    )
    assert "statistics_bee" in census.active_routes
    assert "strategy_workers" in census.active_routes
    ml=next(row for row in census.rows if row.organ_id=="ml_challenger")
    assert ml.route_state=="WIRED_NOT_INVOKED"


def test_execution_downstream_is_not_mislabeled_dead():
    census=build_route_census(
        invocation_counts={},
        runtime_seen_ids=(),
    )
    row=next(row for row in census.rows if row.organ_id=="execution_canary_growth")
    assert row.route_state=="OPTIONAL_OR_DOWNSTREAM"



def test_unmeasured_route_is_not_declared_dead():
    census=build_route_census(
        invocation_counts={"strategy_workers":4},
        runtime_seen_ids=("strategy_workers",),
        measured_ids=("strategy_workers",),
    )
    statistics=next(row for row in census.rows if row.organ_id=="statistics_bee")
    assert statistics.route_state=="NOT_MEASURED"
    assert "statistics_bee" in census.unmeasured_routes
    assert "statistics_bee" not in census.dead_routes
