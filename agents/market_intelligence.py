from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


def _clip(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return low


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _age_score(iso_value: Any, stale_days: float = 45.0) -> float:
    if not iso_value:
        return 0.0
    try:
        observed = datetime.fromisoformat(str(iso_value).replace("Z", "+00:00"))
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (datetime.now(timezone.utc) - observed).total_seconds() / 86400.0)
        return _clip(1.0 - age_days / stale_days)
    except ValueError:
        return 0.0


class MarketWorkerFederation:
    """Independent market observers. They can propose tests, never publish or contact."""

    def observe(self, context: Mapping[str, Any]) -> list[dict[str, Any]]:
        live = context.get("live_signals") if isinstance(context.get("live_signals"), Mapping) else {}
        depth = live.get("depth") if isinstance(live.get("depth"), Mapping) else {}
        registry = context.get("registry_observation") if isinstance(context.get("registry_observation"), Mapping) else {}
        registry_signals = registry.get("signals") if isinstance(registry.get("signals"), Mapping) else {}
        measurement = context.get("measurement") if isinstance(context.get("measurement"), Mapping) else {}
        acquisition = measurement.get("acquisition") if isinstance(measurement.get("acquisition"), Mapping) else {}
        leads = measurement.get("leads") if isinstance(measurement.get("leads"), Mapping) else {}
        commerce = measurement.get("commerce") if isinstance(measurement.get("commerce"), Mapping) else {}

        raw_video = int(_number(depth.get("returned_videos")))
        relevant_video = int(_number(depth.get("relevant_videos")))
        raw_web = int(_number(depth.get("returned_news_or_blog_items")))
        relevant_web = int(_number(depth.get("relevant_news_or_blog_items")))
        video_ratio = relevant_video / max(raw_video, 1)
        web_ratio = relevant_web / max(raw_web, 1)
        visibility = _clip(math.log10(_number(depth.get("median_views_in_sample"), 0.0) + 1.0) / 5.0)
        registry_strength = _clip(_number(registry_signals.get("attack_score")) / 100.0)
        route_strength = 1.0 if registry_signals.get("route_state") not in {None, "", "RESEARCH_ONLY"} else 0.25
        registry_freshness = _age_score(registry.get("observed_at"), 120.0)
        live_freshness = _age_score((live.get("search") or {}).get("finished_at"), 14.0)
        clicks = _number(acquisition.get("clicks"))
        enquiries = _number(leads.get("enquiries"))
        qualified = _number(leads.get("qualified_leads"))
        paid = _number(commerce.get("paid_orders"))
        measured_strength = _clip((clicks * 0.04) + (enquiries * 0.20) + (qualified * 0.30) + (paid * 0.50))

        return [
            self._proposal(
                "REGISTRY_WORKER",
                "buyer_route",
                0.55 * registry_strength + 0.25 * route_strength + 0.20 * registry_freshness,
                0.25 if route_strength >= 1.0 else 0.60,
                [f"attack_score={_number(registry_signals.get('attack_score')):.1f}", f"route_state={registry_signals.get('route_state') or 'unknown'}"],
            ),
            self._proposal(
                "YOUTUBE_WORKER",
                "social_video",
                0.50 * video_ratio + 0.30 * visibility + 0.20 * live_freshness,
                0.35 + 0.40 * (1.0 - video_ratio),
                [f"relevant={relevant_video}/{raw_video}", f"median_views={int(_number(depth.get('median_views_in_sample')))}"],
            ),
            self._proposal(
                "WEB_BLOG_WORKER",
                "web_news_blogs",
                0.65 * web_ratio + 0.20 * _clip(relevant_web / 8.0) + 0.15 * live_freshness,
                0.35 + 0.45 * (1.0 - web_ratio),
                [f"relevant={relevant_web}/{raw_web}", "rss_synopses_are_discovery_leads_only"],
            ),
            self._proposal(
                "SOCIAL_COVERAGE_WORKER",
                "cross_platform_social",
                self._social_strength(live, video_ratio),
                self._social_risk(live),
                [f"providers={json.dumps(live.get('provider_state') or {}, sort_keys=True)}"],
            ),
            self._proposal(
                "OUTCOME_MEMORY_WORKER",
                "measured_response",
                measured_strength,
                0.20 if measured_strength > 0 else 0.75,
                [f"clicks={int(clicks)}", f"enquiries={int(enquiries)}", f"qualified={int(qualified)}", f"paid={int(paid)}"],
            ),
        ]

    @staticmethod
    def _social_strength(live: Mapping[str, Any], video_ratio: float) -> float:
        providers = live.get("provider_state") if isinstance(live.get("provider_state"), Mapping) else {}
        connected = sum(1 for state in providers.values() if state == "connected")
        return _clip(0.65 * video_ratio + 0.35 * connected / max(len(providers), 1))

    @staticmethod
    def _social_risk(live: Mapping[str, Any]) -> float:
        providers = live.get("provider_state") if isinstance(live.get("provider_state"), Mapping) else {}
        unavailable = sum(1 for state in providers.values() if state != "connected")
        return _clip(0.25 + unavailable / max(len(providers), 1) * 0.65)

    @staticmethod
    def _proposal(worker: str, family: str, strength: float, risk: float, evidence: Iterable[str]) -> dict[str, Any]:
        strength = _clip(strength)
        return {
            "worker": worker,
            "family": family,
            "recommendation": "TEST" if strength >= 0.58 else ("REFINE" if strength >= 0.30 else "HOLD"),
            "signal_strength": round(strength, 6),
            "risk": round(_clip(risk), 6),
            "evidence": list(evidence),
            "authority": "observation_and_proposal_only",
            "publication_authority": "none",
            "outreach_authority": "none",
        }


class MarketRegimeOracle:
    """Classifies the attention environment without forecasting revenue."""

    def classify(self, context: Mapping[str, Any], workers: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        proposals = list(workers)
        by_name = {item["worker"]: item for item in proposals}
        outcome = _number((by_name.get("OUTCOME_MEMORY_WORKER") or {}).get("signal_strength"))
        youtube = _number((by_name.get("YOUTUBE_WORKER") or {}).get("signal_strength"))
        web = _number((by_name.get("WEB_BLOG_WORKER") or {}).get("signal_strength"))
        registry = _number((by_name.get("REGISTRY_WORKER") or {}).get("signal_strength"))
        seasonal = bool(((context.get("registry_observation") or {}).get("signals") or {}).get("seasonal_trigger"))
        if outcome >= 0.45:
            regime = "MEASURED_RESPONSE"
        elif seasonal and max(youtube, web, registry) >= 0.55:
            regime = "SEASONAL_OPPORTUNITY"
        elif youtube < 0.28 and web < 0.28:
            regime = "LOW_SIGNAL"
        elif max(youtube, web) >= 0.52 and min(youtube, web) < 0.30:
            regime = "CHANNEL_SPECIFIC_ATTENTION"
        else:
            regime = "ACTIVE_RESEARCH"
        confidence = _clip(max(outcome, registry * 0.85, (youtube + web) / 2.0))
        return {
            "schema": "hivenance_market_regime_oracle_v1",
            "regime": regime,
            "confidence": round(confidence, 6),
            "features": {"registry": registry, "youtube": youtube, "web_blogs": web, "measured_outcome": outcome, "seasonal": seasonal},
            "authority": "classification_only",
            "commercial_claim_authority": "none",
        }


class MarketHypothesisCompetition:
    FAMILIES = (
        ("proof_demo", "Show the real before-to-after artifact and the human approval boundary."),
        ("problem_education", "Teach one buyer pain with a short evidence-led article or post."),
        ("faceless_search_video", "Answer a live search question with a proof-bearing short video."),
        ("permission_first_partnership", "Ask a relevant public route for consent to receive one proof example."),
    )

    def compete(self, context: Mapping[str, Any], workers: Iterable[Mapping[str, Any]], oracle: Mapping[str, Any]) -> list[dict[str, Any]]:
        by_family = {item["family"]: item for item in workers}
        registry = _number((by_family.get("buyer_route") or {}).get("signal_strength"))
        youtube = _number((by_family.get("social_video") or {}).get("signal_strength"))
        web = _number((by_family.get("web_news_blogs") or {}).get("signal_strength"))
        outcome = _number((by_family.get("measured_response") or {}).get("signal_strength"))
        regime = str(oracle.get("regime") or "LOW_SIGNAL")
        scores = {
            "proof_demo": 0.34 * registry + 0.26 * max(youtube, web) + 0.20 * outcome + 0.20,
            "problem_education": 0.45 * web + 0.25 * registry + 0.15 * youtube + 0.15,
            "faceless_search_video": 0.50 * youtube + 0.20 * web + 0.15 * registry + 0.15,
            "permission_first_partnership": 0.58 * registry + 0.12 * max(youtube, web) + 0.10 * outcome + 0.20,
        }
        if regime == "LOW_SIGNAL":
            scores["problem_education"] += 0.08
            scores["permission_first_partnership"] -= 0.10
        if regime == "MEASURED_RESPONSE":
            scores["proof_demo"] += 0.10
        candidates = [
            {
                "hypothesis_family": family,
                "hypothesis": statement,
                "score": round(_clip(scores[family]), 6),
                "success_event": "qualified_reply_or_inbound_pilot_request",
                "measurement_required": True,
                "authority": "controlled_test_proposal_only",
            }
            for family, statement in self.FAMILIES
        ]
        return sorted(candidates, key=lambda item: item["score"], reverse=True)


class MarketTriuneMind:
    def assess(self, context: Mapping[str, Any], candidate: Mapping[str, Any], workers: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        proposals = list(workers)
        source_strengths = [_number(item.get("signal_strength")) for item in proposals[:4]]
        source_diversity = sum(1 for value in source_strengths if value >= 0.25) / max(len(source_strengths), 1)
        live = context.get("live_signals") if isinstance(context.get("live_signals"), Mapping) else {}
        depth = live.get("depth") if isinstance(live.get("depth"), Mapping) else {}
        relevant = int(_number(depth.get("relevant_videos"))) + int(_number(depth.get("relevant_news_or_blog_items")))
        freshness = _age_score((live.get("search") or {}).get("finished_at"), 14.0)
        michael_score = _clip(0.35 * _number(candidate.get("score")) + 0.25 * source_diversity + 0.20 * _clip(relevant / 10.0) + 0.20 * freshness)
        challenges: list[dict[str, Any]] = []

        def challenge(name: str, risk: float, note: str) -> None:
            challenges.append({"challenge": name, "risk": risk, "note": note})

        if relevant < 3:
            challenge("thin_live_sample", 0.66, "fewer than three relevant live items survived the relevance gate")
        if source_diversity < 0.50:
            challenge("single_channel_story", 0.58, "the opportunity is not corroborated across enough channels")
        measurement = context.get("measurement") if isinstance(context.get("measurement"), Mapping) else {}
        if not (measurement.get("measurement_window") or {}).get("started_at"):
            challenge("no_campaign_outcome_yet", 0.42, "market attention has not yet settled into measured response")
        gates = (context.get("hypothesis") or {}).get("gates") or {}
        if candidate.get("hypothesis_family") == "permission_first_partnership" and gates.get("electronic_sales_outreach") != "allowed":
            challenge("outreach_permission_missing", 0.92, "only a compliant once-off consent request may be prepared")
        loki_risk = max([_number(item["risk"]) for item in challenges] + [0.0])
        harmony = _clip(0.50 * michael_score + 0.35 * _number(candidate.get("score")) + 0.15 * (1.0 - loki_risk))
        verdict = "ALLOW_CONTROLLED_TEST"
        if loki_risk >= 0.85:
            verdict = "VETO"
        elif michael_score < 0.45 or loki_risk >= 0.58:
            verdict = "CHALLENGE_AND_REFINE"
        return {
            "schema": "hivenance_market_triune_mind_v1",
            "candidate_family": candidate.get("hypothesis_family"),
            "michael": {"role": "MICHAEL_VALIDATOR", "validation_score": round(michael_score, 6), "source_diversity": source_diversity, "relevant_live_items": relevant},
            "loki": {"role": "LOKI_ADVERSARY", "risk_score": round(loki_risk, 6), "challenges": challenges, "alternative_hypothesis": "observed attention may reflect general education interest rather than buyer intent"},
            "metatron": {"role": "METATRON_SYNTHESIS", "harmony_score": round(harmony, 6)},
            "final_verdict": verdict,
            "authority": "research_admission_only",
            "publication_authority": "none",
            "outreach_authority": "none",
        }


class MarketAinurCouncil:
    def consult(self, context: Mapping[str, Any], workers: Iterable[Mapping[str, Any]], oracle: Mapping[str, Any], assessments: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        proposals = list(workers)
        triune = list(assessments)
        live = context.get("live_signals") if isinstance(context.get("live_signals"), Mapping) else {}
        depth = live.get("depth") if isinstance(live.get("depth"), Mapping) else {}
        measurement = context.get("measurement") if isinstance(context.get("measurement"), Mapping) else {}
        witnesses = [
            self._witness("Manwe", "cadence", _age_score((live.get("search") or {}).get("finished_at"), 14.0), "fresh search and observation cadence"),
            self._witness("Varda", "truth", sum(_number(item.get("signal_strength")) for item in proposals[:3]) / 3.0, "registry, web and video relevance"),
            self._witness("Vaire", "chronology", _number(oracle.get("confidence")), f"regime={oracle.get('regime')}"),
            self._witness("Mandos", "settled memory", 1.0 if (measurement.get("measurement_window") or {}).get("started_at") else 0.20, "measured campaign outcomes"),
            self._witness("Ulmo", "signal depth", _clip((_number(depth.get("relevant_videos")) + _number(depth.get("relevant_news_or_blog_items"))) / 12.0), "relevant cross-channel sample depth"),
        ]
        eligible = [item for item in triune if item.get("final_verdict") == "ALLOW_CONTROLLED_TEST"]
        challenged = [item for item in triune if item.get("final_verdict") == "CHALLENGE_AND_REFINE"]
        selectable = eligible or challenged
        best = max(selectable, key=lambda item: _number((item.get("metatron") or {}).get("harmony_score")), default={})
        harmony = sum(item["score"] for item in witnesses) / max(len(witnesses), 1)
        if eligible and harmony >= 0.58:
            decision = "TEST"
        elif challenged or harmony >= 0.35:
            decision = "REFINE"
        else:
            decision = "HOLD"
        return {
            "schema": "hivenance_market_ainur_council_v1",
            "witnesses": witnesses,
            "harmony_index": round(harmony, 6),
            "decision": decision,
            "selected_family": best.get("candidate_family"),
            "canonical_runtime_state": "harmonic" if harmony >= 0.70 else ("strained" if harmony >= 0.35 else "muted"),
            "authority": "campaign_research_routing_only",
            "publication_authority": "operator_only",
            "outreach_authority": "consent_gate_only",
            "commerce_authority": "none",
        }

    @staticmethod
    def _witness(name: str, domain: str, score: float, basis: str) -> dict[str, Any]:
        score = _clip(score)
        return {"witness": name, "domain": domain, "score": round(score, 6), "judgment": "LAWFUL" if score >= 0.55 else ("WITHHELD" if score >= 0.25 else "DISSONANT"), "basis": basis}


def assess_market_campaign(context: Mapping[str, Any]) -> dict[str, Any]:
    workers = MarketWorkerFederation().observe(context)
    oracle = MarketRegimeOracle().classify(context, workers)
    candidates = MarketHypothesisCompetition().compete(context, workers, oracle)
    triune = [MarketTriuneMind().assess(context, candidate, workers) for candidate in candidates]
    council = MarketAinurCouncil().consult(context, workers, oracle, triune)
    return {
        "schema": "hivenance_non_crypto_market_intelligence_v1",
        "campaign_id": context.get("campaign_id"),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "lane": "professional_services_market_intelligence",
        "explicitly_excluded_domains": ["crypto", "trading", "wallets", "orders", "price_prediction"],
        "context_root": _stable_hash(context),
        "workers": workers,
        "oracle": oracle,
        "hypothesis_competition": candidates,
        "triune_assessments": triune,
        "council": council,
        "next_action": {
            "TEST": "prepare one bounded channel test and require operator release",
            "REFINE": "improve query precision or source diversity before release",
            "HOLD": "collect stronger observations before producing more campaign assets",
        }[council["decision"]],
        "authority": {
            "research": "allowed",
            "campaign_test": "operator_approval_required",
            "publication": "operator_only",
            "direct_outreach": "consent_gate_only",
            "commerce": "none",
        },
    }
