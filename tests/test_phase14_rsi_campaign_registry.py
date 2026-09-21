import json

from scripts.build_phase14_campaign_registry import main


def test_build_phase14_campaign_registry(tmp_path,monkeypatch):
    out=tmp_path/"registry.json"
    monkeypatch.setattr(
        "sys.argv",
        ["build_phase14_campaign_registry.py","--out",str(out)],
    )
    assert main()==0
    payload=json.loads(out.read_text())
    assert payload["registry"]["campaign_count"]==2
    assert payload["replication_court"]["classification"]=="REGIME_OR_TEMPORAL_INSTABILITY_DETECTED"
    assert payload["authority_effect"]=="NONE_RESEARCH_ONLY"
    assert payload["execution_eligible"] is False
    assert payload["promotion_eligible"] is False
    discovery=payload["receipts"][0]["evidence"]
    replication=payload["receipts"][1]["evidence"]
    assert discovery["market_tape_sha256"] is None
    assert replication["preoutcome_cohort_sha256"]=="95fef558d8722404fbe3f03020a3eead7308cefc2706e6284a0ab1e75385c301"
