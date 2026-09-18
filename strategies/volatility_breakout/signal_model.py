from __future__ import annotations

from .models import FeatureVector, Forecast


class ObservationOnlySignalModel:
    """Phase-1 model that records features and always abstains from trading."""

    def forecast(self, features: FeatureVector, *, horizon_seconds: int = 900) -> Forecast:
        reason = 'phase1_observation_only' if features.complete else 'features_incomplete'
        return Forecast(
            symbol=features.symbol,
            timestamp_ms=features.timestamp_ms,
            horizon_seconds=horizon_seconds,
            abstain=True,
            reason=reason,
        )
