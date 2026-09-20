import json

from scripts.report_full_organism_census import _load_bundle


def test_census_cli_bundle_schema_guard(tmp_path):
    path=tmp_path/"bundle.json"
    path.write_text(json.dumps({
        "schema":"hivenance_full_organism_census_replay_bundle_v1",
        "outcomes_by_mask":{},
    }))
    payload=_load_bundle(str(path))
    assert payload["schema"]=="hivenance_full_organism_census_replay_bundle_v1"


def test_census_cli_rejects_unknown_bundle_schema(tmp_path):
    import pytest
    path=tmp_path/"bad.json"
    path.write_text(json.dumps({"schema":"wrong"}))
    with pytest.raises(ValueError,match="unsupported_census_bundle_schema"):
        _load_bundle(str(path))
