from strategies.relative_value_lab.historical_causal_prosecution import HistoricalOrganProsecution
from strategies.relative_value_lab.organ_utility_census import build_organ_utility_census


def row(organ_id,classification,delta,changes=3,invoked=10):
    return HistoricalOrganProsecution(
        organ_id=organ_id,
        mask_id="NO_WORKERS" if organ_id=="strategy_workers" else "NO_STATISTICS",
        available=True,
        invoked_count=invoked,
        non_default_output_count=invoked,
        paired_world_count=20,
        dependence_adjusted_world_count=10,
        decision_change_count=changes,
        direction_change_count=1,
        abstention_change_count=1,
        selection_change_count=0,
        full_hive_mean_net_bps=2.0,
        ablated_mean_net_bps=1.0,
        historical_paired_delta_bps=delta,
        uncertainty_bps=1.0,
        classification=classification,
    )


def test_census_separates_useful_harmful_and_inert_organs():
    census=build_organ_utility_census(
        (
            row("strategy_workers","HISTORICALLY_USEFUL",3.0),
            row("statistics_bee","HISTORICALLY_HARMFUL",-1.0),
            row("ml_challenger","INVOKED",None,changes=0),
        ),
        topology_aliases={"ml_challenger":"ml_challenger"},
    )
    assert census.useful_organs==("strategy_workers",)
    assert census.harmful_organs==("statistics_bee",)
    assert census.inert_organs==("ml_challenger",)
    assert census.historical_only is True
    assert census.execution_eligible is False


def test_harmful_recommendation_is_quarantine_not_delete():
    census=build_organ_utility_census(
        (row("statistics_bee","HISTORICALLY_HARMFUL",-2.0),)
    )
    item=census.rows[0]
    assert item.recommendation=="QUARANTINE_OR_REDESIGN_BEFORE_PROSPECTIVE_USE"
