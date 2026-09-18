from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.market_intelligence import MarketTriuneMind, assess_market_campaign


def _context(*, videos: int = 0, web: int = 0, measurement_started: bool = False):
    return {
        "campaign_id": "CMP-TESTMARKET01",
        "hypothesis": {
            "gates": {
                "publication": "operator_approval_required",
                "electronic_sales_outreach": "blocked",
            }
        },
        "registry_observation": {
            "observed_at": "2026-08-08T12:00:00+00:00",
            "signals": {"attack_score": 82, "route_state": "PUBLIC_CONTACT_ROUTE", "seasonal_trigger": True},
        },
        "live_signals": {
            "search": {"finished_at": "2026-08-08T12:00:00+00:00"},
            "depth": {
                "returned_videos": 10,
                "relevant_videos": videos,
                "returned_news_or_blog_items": 10,
                "relevant_news_or_blog_items": web,
                "median_views_in_sample": 12000,
            },
            "provider_state": {
                "youtube_public": "connected",
                "web_news_rss": "connected",
                "facebook_instagram": "pending",
                "linkedin": "not_connected",
            },
        },
        "measurement": {
            "measurement_window": {"started_at": "2026-08-08T12:00:00+00:00" if measurement_started else None},
            "acquisition": {"clicks": 0},
            "leads": {"enquiries": 0, "qualified_leads": 0},
            "commerce": {"paid_orders": 0},
        },
    }


def test_market_lane_has_no_crypto_publication_or_commerce_authority():
    receipt = assess_market_campaign(_context(videos=8, web=7, measurement_started=True))

    assert "crypto" in receipt["explicitly_excluded_domains"]
    assert receipt["authority"]["publication"] == "operator_only"
    assert receipt["authority"]["direct_outreach"] == "consent_gate_only"
    assert receipt["authority"]["commerce"] == "none"
    assert all(worker["publication_authority"] == "none" for worker in receipt["workers"])
    assert all(worker["outreach_authority"] == "none" for worker in receipt["workers"])


def test_thin_live_evidence_is_challenged_instead_of_treated_as_proof():
    receipt = assess_market_campaign(_context(videos=1, web=0))

    challenges = {
        challenge["challenge"]
        for assessment in receipt["triune_assessments"]
        for challenge in assessment["loki"]["challenges"]
    }
    assert "thin_live_sample" in challenges
    assert receipt["council"]["decision"] in {"REFINE", "HOLD"}


def test_permission_first_hypothesis_is_vetoed_without_outreach_authority():
    receipt = assess_market_campaign(_context(videos=8, web=7))
    candidate = next(item for item in receipt["hypothesis_competition"] if item["hypothesis_family"] == "permission_first_partnership")
    assessment = MarketTriuneMind().assess(_context(videos=8, web=7), candidate, receipt["workers"])

    assert assessment["final_verdict"] == "VETO"
    assert "outreach_permission_missing" in {item["challenge"] for item in assessment["loki"]["challenges"]}
