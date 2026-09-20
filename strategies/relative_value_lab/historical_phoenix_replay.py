"""Real Phoenix forecast replay over a frozen historical reconstruction.

This module deliberately does NOT create a synthetic forecasting rule.

The decision path is the existing HiveNance path:

    HistoricalReconstructionInput
        -> FeatureVector
        -> SynthesisRuntime
        -> bind_synthesis_context
        -> HypothesisCompetition
        -> Forecast

The CanonicalScoreFrame preserves the original frozen Phase-4 world identity.
No future settlement information is supplied to the replay.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

from strategies.volatility_breakout.hypothesis_competition import (
    HypothesisCompetition,
)
from strategies.volatility_breakout.models import (
    FeatureVector,
    Forecast,
)

from .g0_hypothesis_adapter import (
    bind_synthesis_context,
)
from .g0_forecast_challenge import (
    challenge_forecast,
)
from .historical_feature_reconstruction import (
    feature_from_reconstruction,
)
from .historical_reconstruction_input import (
    HistoricalReconstructionInput,
)
from .synthesis_runtime import (
    SynthesisCycle,
    SynthesisRuntime,
)
from .world_score import (
    CanonicalScoreFrame,
    ScoreObservation,
)


def _digest(
    value: Any,
) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")

    return (
        "sha256:"
        + hashlib.sha256(raw).hexdigest()
    )


@dataclass(frozen=True)
class HistoricalPhoenixReplay:
    schema: str

    reconstruction_id: str
    world_state_id: str
    world_state_hash: str

    symbol: str
    horizon_seconds: int

    frame: CanonicalScoreFrame
    cycle: SynthesisCycle

    base_feature: FeatureVector
    synthesis_feature: FeatureVector

    forecasts: tuple[Forecast, ...]

    forecasts_total: int
    non_abstain_forecasts: int
    abstentions: int

    retrospective_reconstruction_only: bool = True
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "reconstruction_id":
                self.reconstruction_id,
            "world_state_id":
                self.world_state_id,
            "world_state_hash":
                self.world_state_hash,
            "symbol":
                self.symbol,
            "horizon_seconds":
                self.horizon_seconds,
            "frame":
                self.frame.to_dict(),
            "cycle":
                self.cycle.to_dict(),
            "base_feature":
                asdict(
                    self.base_feature
                ),
            "synthesis_feature":
                asdict(
                    self.synthesis_feature
                ),
            "forecasts": tuple(
                asdict(x)
                for x in self.forecasts
            ),
            "forecasts_total":
                self.forecasts_total,
            "non_abstain_forecasts":
                self.non_abstain_forecasts,
            "abstentions":
                self.abstentions,
            "retrospective_reconstruction_only":
                True,
            "execution_eligible":
                False,
            "promotion_eligible":
                False,
        }


def frame_from_reconstruction(
    inp: HistoricalReconstructionInput,
) -> CanonicalScoreFrame:
    """Preserve the original historical world binding.

    We do not call CanonicalWorldScore.assemble() here because doing so would
    generate a new 2026 Phase-12 world digest rather than preserve the frozen
    Phase-4 canonical world identity.

    The observed payload remains exactly the pre-decision observation package.
    """

    observation_payload = dict(
        inp.observation
    )

    obs = ScoreObservation(
        observation_id=(
            "historical:"
            + inp.freeze_id
        ),
        source_id=(
            inp.observation_source
        ),
        source_class=(
            "FROZEN_HISTORICAL_MARKET_OBSERVATION"
        ),
        scope=inp.symbol,
        observed_at_ms=(
            inp.observed_at_ms
        ),
        received_at_ms=(
            inp.observed_at_ms
        ),
        evidence_root=(
            inp.evidence_root
        ),
        payload=observation_payload,
    )

    digest = _digest(
        {
            "freeze_id":
                inp.freeze_id,
            "evidence_root":
                inp.evidence_root,
            "observation":
                observation_payload,
        }
    )

    return CanonicalScoreFrame(
        schema=(
            "hivenance_historical_bound_world_score_v1"
        ),
        world_state_id=(
            inp.world_state_id
        ),
        world_state_hash=(
            inp.world_state_hash
        ),
        assembled_at_ms=(
            inp.observed_at_ms
        ),
        latest_observation_ms=(
            inp.observed_at_ms
        ),
        oldest_observation_ms=(
            inp.observed_at_ms
        ),
        freshness_window_ms=(
            inp.horizon_seconds
            * 1000
        ),
        expires_at_ms=(
            inp.target_at_ms
        ),
        observation_count=1,
        sources=(
            inp.observation_source,
        ),
        scopes=(
            inp.symbol,
        ),
        observed_digest=digest,
        observations=(obs,),
        execution_eligible=False,
        promotion_eligible=False,
    )


def default_historical_competition(
) -> HypothesisCompetition:
    """Current Phoenix competition with normal research defaults.

    No model is added here. SimpleNamespace allows HypothesisCompetition's
    existing defaults to remain authoritative.
    """

    cfg = SimpleNamespace(
        exchange="kraken",
    )

    return HypothesisCompetition(
        cfg
    )


def replay_historical_phoenix(
    inp: HistoricalReconstructionInput,
    *,
    runtime: SynthesisRuntime | None = None,
    competition: HypothesisCompetition | None = None,
    disabled_organs: Sequence[str] = (),
    organ_bundle: Any | None = None,
    challenge_scope: str | None = None,
) -> HistoricalPhoenixReplay:
    runtime = (
        runtime
        or SynthesisRuntime()
    )

    competition = (
        competition
        or default_historical_competition()
    )

    frame = frame_from_reconstruction(
        inp
    )

    feature = (
        feature_from_reconstruction(
            inp
        )
    )

    # At this gate we prove the genuine synthesis/forecast seam.
    #
    # Organs requiring richer historical inputs are NOT manufactured.
    # They therefore remain AVAILABLE_NOT_INVOKED in SynthesisRuntime.
    cycle = runtime.run(
        frame=frame,
        now_ms=(
            inp.observed_at_ms
        ),
        horizon=(
            None
            if organ_bundle is None
            else organ_bundle.horizon
        ),
        horizon_roots=(
            ()
            if organ_bundle is None
            else organ_bundle.horizon_roots
        ),
        edge_snapshot=(
            None
            if organ_bundle is None
            else organ_bundle.edge_snapshot
        ),
        edge_roots=(
            None
            if organ_bundle is None
            else organ_bundle.edge_roots
        ),
        temporal_participation=(
            None
            if organ_bundle is None
            else organ_bundle.temporal_participation
        ),
        learning_receipts=(),
        comparison_results=(
            ()
            if organ_bundle is None
            else organ_bundle.comparison_results
        ),
        disabled_organs=tuple(
            disabled_organs
        ),
    )

    if (
        cycle.world_state_id
        != inp.world_state_id
        or cycle.world_state_hash
        != inp.world_state_hash
    ):
        raise ValueError(
            "historical_phoenix_world_binding_drift"
        )

    synthesis_feature = (
        bind_synthesis_context(
            feature,
            cycle,
        )
    )

    raw_forecasts = tuple(
        competition.evaluate(
            synthesis_feature,
            (
                inp.horizon_seconds,
            ),
        )
    )

    forecasts = (
        tuple(
            challenge_forecast(
                forecast,
                synthesis_feature,
                organ_scope=challenge_scope,
            )
            for forecast in raw_forecasts
        )
        if challenge_scope is not None
        else raw_forecasts
    )

    for forecast in forecasts:
        if (
            forecast.symbol
            != inp.symbol
        ):
            raise ValueError(
                "historical_phoenix_symbol_drift"
            )

        if (
            int(
                forecast.horizon_seconds
            )
            != int(
                inp.horizon_seconds
            )
        ):
            raise ValueError(
                "historical_phoenix_horizon_drift"
            )

        if (
            int(
                forecast.timestamp_ms
            )
            != int(
                inp.observed_at_ms
            )
        ):
            raise ValueError(
                "historical_phoenix_timestamp_drift"
            )

        if forecast.execution_eligible:
            raise ValueError(
                "historical_phoenix_execution_authority_forbidden"
            )

    return HistoricalPhoenixReplay(
        schema=(
            "hivenance_historical_phoenix_replay_v1"
        ),
        reconstruction_id=(
            inp.reconstruction_id
        ),
        world_state_id=(
            inp.world_state_id
        ),
        world_state_hash=(
            inp.world_state_hash
        ),
        symbol=inp.symbol,
        horizon_seconds=(
            inp.horizon_seconds
        ),
        frame=frame,
        cycle=cycle,
        base_feature=feature,
        synthesis_feature=(
            synthesis_feature
        ),
        forecasts=forecasts,
        forecasts_total=(
            len(forecasts)
        ),
        non_abstain_forecasts=sum(
            1
            for x in forecasts
            if not x.abstain
        ),
        abstentions=sum(
            1
            for x in forecasts
            if x.abstain
        ),
        retrospective_reconstruction_only=True,
        execution_eligible=False,
        promotion_eligible=False,
    )
