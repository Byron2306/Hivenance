from __future__ import annotations

import math
from dataclasses import replace
from typing import Iterable

from .models import CandidateObservation


class ObservationOnlyCandidateSelector:
    """Ranks assets for research observation while permanently denying execution."""

    def __init__(
        self,
        *,
        min_listing_age_days: float = 90,
        min_depth_usd_25bps: float = 25_000,
        min_quote_volume_24h_usd: float = 5_000_000,
        max_spread_bps: float = 35,
        min_data_quality: float = 0.99,
        niche_focus_enabled: bool = False,
        niche_max_quote_volume_24h_usd: float = 2_000_000,
        niche_taker_fee_bps_per_side: float = 80.0,
        niche_min_research_richness: float = 0.35,
        niche_min_volatility_to_cost: float = 0.35,
    ) -> None:
        self.min_listing_age_days = max(0.0, float(min_listing_age_days))
        self.min_depth_usd_25bps = max(0.0, float(min_depth_usd_25bps))
        self.min_quote_volume_24h_usd = max(0.0, float(min_quote_volume_24h_usd))
        self.max_spread_bps = max(0.0, float(max_spread_bps))
        self.min_data_quality = max(0.0, min(1.0, float(min_data_quality)))
        self.niche_focus_enabled = bool(niche_focus_enabled)
        self.niche_max_quote_volume_24h_usd = max(0.0, float(niche_max_quote_volume_24h_usd))
        self.niche_taker_fee_bps_per_side = max(0.0, float(niche_taker_fee_bps_per_side))
        self.niche_min_research_richness = max(0.0, min(1.0, float(niche_min_research_richness)))
        self.niche_min_volatility_to_cost = max(0.0, float(niche_min_volatility_to_cost))

    def evaluate(self, observation: CandidateObservation) -> CandidateObservation:
        reasons: list[str] = []
        if observation.listing_age_days is not None and observation.listing_age_days < self.min_listing_age_days:
            reasons.append('listing_too_new')
        if (observation.quote_volume_24h or 0.0) < self.min_quote_volume_24h_usd:
            reasons.append('insufficient_quote_volume')
        if (observation.depth_usd_25bps or 0.0) < self.min_depth_usd_25bps:
            reasons.append('insufficient_executable_depth')
        if observation.spread_bps is None:
            reasons.append('spread_unavailable')
        elif observation.spread_bps > self.max_spread_bps:
            reasons.append('spread_too_wide')
        if observation.data_quality < self.min_data_quality:
            reasons.append('data_quality_below_phase1_gate')
        if observation.freshness_sec is None:
            reasons.append('freshness_unavailable')
        if observation.continuity_ratio is None or observation.continuity_ratio < 0.95:
            reasons.append('candle_continuity_below_gate')

        observation_eligible = not reasons
        values = dict(observation.values or {})
        volume_score = min(1.0, (observation.quote_volume_24h or 0.0) / max(1.0, self.min_quote_volume_24h_usd * 10.0))
        depth_score = min(1.0, (observation.depth_usd_25bps or 0.0) / max(1.0, self.min_depth_usd_25bps * 10.0))
        spread_score = 0.0 if observation.spread_bps is None else max(0.0, 1.0 - observation.spread_bps / max(1.0, self.max_spread_bps))
        expansion = float(values.get('volatility_expansion') or 0.0)
        expansion_score = min(1.0, expansion / 3.0)
        volume_zscore = float(values.get('volume_zscore') or 0.0)
        return_zscore = abs(float(values.get('return_zscore') or 0.0))
        trend_slope = abs(float(values.get('trend_slope') or 0.0))
        range_position = values.get('range_position')
        range_extreme_score = 0.0
        if range_position is not None:
            try:
                range_extreme_score = min(1.0, abs(float(range_position) - 0.5) * 2.0)
            except (TypeError, ValueError):
                range_extreme_score = 0.0
        regime_inputs = values.get('regime_inputs') if isinstance(values.get('regime_inputs'), dict) else {}
        regime_hint = str(regime_inputs.get('regime_hint') or '')
        regime_confidence = float(regime_inputs.get('confidence') or 0.0)
        regime_bonus = 0.0
        if regime_hint in {'trend_expansion', 'stretch_exhaustion'}:
            regime_bonus = 0.20 + 0.20 * min(1.0, regime_confidence)
        elif regime_hint == 'balanced_transition':
            regime_bonus = 0.08 + 0.12 * min(1.0, regime_confidence)
        trend_score = min(1.0, trend_slope * 20_000.0)
        participation_score = min(1.0, max(0.0, volume_zscore + 0.5) / 3.0)
        stretch_score = min(1.0, return_zscore / 3.0)
        research_richness_score = max(
            0.0,
            min(
                1.0,
                0.28 * expansion_score
                + 0.22 * participation_score
                + 0.18 * stretch_score
                + 0.10 * trend_score
                + 0.10 * range_extreme_score
                + regime_bonus,
            ),
        )
        tradability_pressure = 0.0
        if observation.spread_bps is not None:
            tradability_pressure += min(1.0, observation.spread_bps / max(1.0, self.max_spread_bps * 0.6))
        if observation.depth_usd_25bps is not None:
            tradability_pressure += min(
                1.0,
                max(0.0, self.min_depth_usd_25bps * 2.0 - float(observation.depth_usd_25bps)) / max(1.0, self.min_depth_usd_25bps * 2.0),
            )
        tradability_penalty = min(1.0, tradability_pressure / 2.0)
        tradable_opportunity_score = research_richness_score * (1.0 - 0.65 * tradability_penalty)
        fast_vol_bps = max(0.0, float(values.get('volatility_fast') or 0.0) * 10_000.0)
        round_trip_cost_bps = max(
            0.000001,
            float(observation.spread_bps or 0.0) + (2.0 * self.niche_taker_fee_bps_per_side),
        )
        volatility_to_cost = fast_vol_bps / round_trip_cost_bps
        volatility_to_cost_score = min(1.0, volatility_to_cost / max(0.000001, self.niche_min_volatility_to_cost * 3.0))
        in_niche_band = (
            self.niche_focus_enabled
            and (observation.quote_volume_24h or 0.0) <= self.niche_max_quote_volume_24h_usd
        )
        niche_research_score = max(
            0.0,
            min(
                1.0,
                0.50 * research_richness_score
                + 0.30 * volatility_to_cost_score
                + 0.20 * spread_score,
            ),
        )
        niche_research_candidate = (
            in_niche_band
            and research_richness_score >= self.niche_min_research_richness
            and volatility_to_cost >= self.niche_min_volatility_to_cost
            and observation.data_quality >= self.min_data_quality
        )
        score = (
            0.28 * observation.data_quality
            + 0.12 * volume_score
            + 0.15 * depth_score
            + 0.15 * spread_score
            + 0.30 * tradable_opportunity_score
        )
        if self.niche_focus_enabled:
            score = (
                0.22 * observation.data_quality
                + 0.10 * volume_score
                + 0.10 * depth_score
                + 0.13 * spread_score
                + 0.20 * tradable_opportunity_score
                + 0.25 * niche_research_score
            )
        values.update({
            'research_richness_score': round(research_richness_score, 6),
            'tradable_opportunity_score': round(tradable_opportunity_score, 6),
            'tradability_penalty': round(tradability_penalty, 6),
            'niche_research_candidate': bool(niche_research_candidate),
            'niche_research_score': round(niche_research_score, 6),
            'volatility_to_cost': round(volatility_to_cost, 6),
            'volatility_to_cost_score': round(volatility_to_cost_score, 6),
            'opportunity_components': {
                'expansion_score': round(expansion_score, 6),
                'participation_score': round(participation_score, 6),
                'stretch_score': round(stretch_score, 6),
                'trend_score': round(trend_score, 6),
                'range_extreme_score': round(range_extreme_score, 6),
                'regime_hint': regime_hint or None,
                'regime_confidence': round(regime_confidence, 6),
                'tradability_penalty': round(tradability_penalty, 6),
            },
        })
        if niche_research_candidate:
            values['symbol_class'] = 'niche_high_volatility'
            values['cohort_bucket'] = 'niche_research'
        return replace(
            observation,
            score=round(max(0.0, min(1.0, score)), 6),
            eligible=observation_eligible,
            observation_eligible=observation_eligible,
            execution_eligible=False,
            rejection_reasons=tuple(reasons),
            values=values,
        )

    def rank(self, observations: Iterable[CandidateObservation]) -> list[CandidateObservation]:
        evaluated = [self.evaluate(item) for item in observations]
        if self.niche_focus_enabled:
            ordered = sorted(
                evaluated,
                key=lambda item: (
                    not bool((item.values or {}).get('niche_research_candidate')),
                    not item.observation_eligible,
                    -float((item.values or {}).get('niche_research_score') or 0.0),
                    -item.score,
                    item.spread_bps if item.spread_bps is not None else float('inf'),
                    -(item.depth_usd_25bps or 0.0),
                ),
            )
        else:
            ordered = sorted(
                evaluated,
                key=lambda item: (
                    not item.observation_eligible,
                    -item.score,
                    item.spread_bps if item.spread_bps is not None else float('inf'),
                    -(item.depth_usd_25bps or 0.0),
                ),
            )
        # Seed the shortlist with distinct regime buckets so the research bench
        # does not collapse into one repeated market condition every cycle.
        seeded: list[CandidateObservation] = []
        seen_symbols: set[str] = set()
        seen_regimes: set[str] = set()
        for item in ordered:
            values = item.values if isinstance(item.values, dict) else {}
            regime_inputs = values.get('regime_inputs') if isinstance(values.get('regime_inputs'), dict) else {}
            regime = str(regime_inputs.get('regime_hint') or 'unknown')
            if regime in seen_regimes:
                continue
            seeded.append(item)
            seen_symbols.add(item.symbol)
            seen_regimes.add(regime)
        for item in ordered:
            if item.symbol in seen_symbols:
                continue
            seeded.append(item)
            seen_symbols.add(item.symbol)
        return seeded
