import pytest

from strategies.relative_value_lab.campaign_evidence_registry import (
    CampaignEvidence,
    phase14_campaign_rows,
    registry_manifest,
    validate_campaign_evidence,
    verify_registry_manifest,
)


def _receipt(campaign_id="c1", **changes):
    values=dict(
        campaign_id=campaign_id,
        model_id="worker_signal_rsi_v1",
        horizon_seconds=3600,
        evidence_role="INDEPENDENT_REPLICATION",
        source_commit="abc123",
        freeze_id="p13f_test",
        market_tape_sha256="a"*64,
        forecast_book_sha256="b"*64,
        preoutcome_cohort_sha256="c"*64,
        started_at="2026-09-21T08:52:06+02:00",
        ended_at="2026-09-21T14:52:24+02:00",
        fills=23,
        distinct_symbols=15,
        distinct_worlds=23,
        mean_gross_bps=-95.141,
        median_gross_bps=-99.268,
        mean_net_bps=-149.718,
        median_net_bps=-151.798,
        mean_excess_vs_random_bps=-93.543,
        largest_symbol_fraction=4/23,
    )
    values.update(changes)
    return CampaignEvidence(**values).receipt()


def test_campaign_receipt_is_self_hashing_and_research_only():
    receipt=_receipt()
    validate_campaign_evidence(receipt)
    assert len(receipt["evidence_sha256"])==64
    assert receipt["evidence"]["execution_eligible"] is False
    assert receipt["evidence"]["promotion_eligible"] is False
    assert receipt["evidence"]["authority_effect"]=="NONE_RESEARCH_ONLY"


def test_campaign_receipt_tamper_is_detected():
    receipt=_receipt()
    receipt["evidence"]["mean_net_bps"]=999.0
    with pytest.raises(ValueError, match="hash_mismatch"):
        validate_campaign_evidence(receipt)


def test_campaign_receipt_cannot_grant_execution():
    receipt=_receipt()
    receipt["evidence"]["execution_eligible"]=True
    # Re-hashing by an attacker/operator must not make authority legal.
    from strategies.relative_value_lab.campaign_evidence_registry import _sha256_json
    receipt["evidence_sha256"]=_sha256_json(receipt["evidence"])
    with pytest.raises(ValueError, match="execution_authority_forbidden"):
        validate_campaign_evidence(receipt)


def test_registry_is_deterministic_and_detects_duplicate_campaigns():
    a=_receipt("a")
    b=_receipt("b", evidence_role="DISCOVERY")
    left=registry_manifest([b,a])
    right=registry_manifest([a,b])
    assert left==right
    assert left["campaign_count"]==2
    verify_registry_manifest(left,[a,b])
    with pytest.raises(ValueError, match="duplicate_campaign_id"):
        registry_manifest([a,a])


def test_phase14_rows_preserve_campaign_separation():
    rows=phase14_campaign_rows([_receipt("discovery"),_receipt("replication")])
    assert [row["campaign_id"] for row in rows]==["discovery","replication"]
    assert all(row["fills"]==23 for row in rows)
