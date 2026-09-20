from strategies.relative_value_lab.historical_causal_prosecution import PAIRED_MASKS
from strategies.relative_value_lab.phase12_mask_router import full_mask_coverage,mask_route


def test_every_phase12_mask_has_executable_route():
    coverage=full_mask_coverage()
    assert coverage["all_masks_have_executable_route"] is True
    assert coverage["missing_masks"]==()


def test_full_hive_may_route_through_multiple_layers():
    row=mask_route("FULL_HIVE")
    assert set(row.domains)=={"MIDDLE","SYNTHESIS","UPPER"}


def test_all_frozen_masks_are_routable():
    for mask in PAIRED_MASKS:
        assert mask_route(mask).executable
