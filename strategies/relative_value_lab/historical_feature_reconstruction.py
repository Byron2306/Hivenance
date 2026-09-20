"""Reconstruct today's Phoenix FeatureVector from a frozen historical observation.

Historical reconstruction only. Missing values remain missing.
No settlement/outcome information is permitted.
"""

from __future__ import annotations

import json
import math
from typing import Any, Mapping

from strategies.volatility_breakout.models import (
    FeatureVector,
)

from .historical_reconstruction_input import (
    HistoricalReconstructionInput,
)


def _finite(
    value: Any,
) -> float | None:
    if value is None:
        return None

    try:
        out = float(value)
    except (TypeError, ValueError):
        return None

    return (
        out
        if math.isfinite(out)
        else None
    )


def _payload(
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    raw = observation.get("payload")

    if raw is None:
        return {}

    if isinstance(raw, Mapping):
        return dict(raw)

    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return {}

        return (
            dict(value)
            if isinstance(value, Mapping)
            else {}
        )

    return {}


def _first(
    *values: Any,
) -> Any:
    for value in values:
        if value is not None:
            return value

    return None


def feature_from_reconstruction(
    inp: HistoricalReconstructionInput,
) -> FeatureVector:
    obs = dict(inp.observation)
    payload = _payload(obs)

    values = payload.get("values")

    if not isinstance(values, Mapping):
        values = {}

    values = dict(values)

    # Preserve only pre-decision reconstruction metadata.
    values[
        "historical_reconstruction"
    ] = {
        "reconstruction_id":
            inp.reconstruction_id,
        "freeze_id":
            inp.freeze_id,
        "world_state_id":
            inp.world_state_id,
        "world_state_hash":
            inp.world_state_hash,
        "observation_source":
            inp.observation_source,
        "retrospective_reconstruction_only":
            True,
        "execution_eligible":
            False,
        "promotion_eligible":
            False,
    }

    # g0_hypothesis_adapter checks this binding.
    values[
        "world_state_id"
    ] = inp.world_state_id

    price = _finite(
        _first(
            obs.get("price"),
            payload.get("price"),
        )
    )

    volatility_expansion = _finite(
        _first(
            obs.get(
                "volatility_expansion"
            ),
            payload.get(
                "volatility_expansion"
            ),
            values.get(
                "volatility_expansion"
            ),
        )
    )

    volume_zscore = _finite(
        _first(
            obs.get("volume_zscore"),
            payload.get("volume_zscore"),
            values.get("volume_zscore"),
        )
    )

    book_imbalance = _finite(
        _first(
            obs.get("book_imbalance"),
            payload.get("book_imbalance"),
            values.get("book_imbalance"),
        )
    )

    spread_bps = _finite(
        _first(
            obs.get("spread_bps"),
            payload.get("spread_bps"),
        )
    )

    depth = _finite(
        _first(
            obs.get(
                "depth_usd_25bps"
            ),
            payload.get(
                "depth_usd_25bps"
            ),
        )
    )

    quote_volume = _finite(
        _first(
            obs.get(
                "quote_volume_24h"
            ),
            payload.get(
                "quote_volume_24h"
            ),
        )
    )

    return_5 = _finite(
        _first(
            payload.get("return_5"),
            values.get("return_5"),
        )
    )

    freshness = _finite(
        _first(
            payload.get(
                "freshness_sec"
            ),
            values.get(
                "freshness_sec"
            ),
        )
    )

    continuity = _finite(
        _first(
            payload.get(
                "continuity_ratio"
            ),
            values.get(
                "continuity_ratio"
            ),
        )
    )

    fast_vol = _finite(
        _first(
            payload.get(
                "realized_volatility_fast"
            ),
            payload.get(
                "volatility_fast"
            ),
            values.get(
                "realized_volatility_fast"
            ),
            values.get(
                "volatility_fast"
            ),
        )
    )

    baseline_vol = _finite(
        _first(
            payload.get(
                "realized_volatility_baseline"
            ),
            payload.get(
                "volatility_baseline"
            ),
            values.get(
                "realized_volatility_baseline"
            ),
            values.get(
                "volatility_baseline"
            ),
        )
    )

    data_quality = _finite(
        _first(
            obs.get("data_quality"),
            payload.get("data_quality"),
        )
    )

    if data_quality is None:
        data_quality = 0.0

    # Current FeatureEngine completeness semantics, evaluated solely from
    # frozen pre-decision fields.
    complete = bool(
        price is not None
        and fast_vol is not None
        and baseline_vol is not None
        and spread_bps is not None
        and depth is not None
        and freshness is not None
        and freshness <= 180.0
        and (
            continuity is not None
            and continuity >= 0.95
        )
    )

    regime = (
        values.get("regime_inputs")
        if isinstance(
            values.get(
                "regime_inputs"
            ),
            Mapping,
        )
        else {}
    )

    if not regime:
        regime = {
            "regime_hint":
                inp.regime_state.get(
                    "regime"
                ),
        }

    values[
        "regime_inputs"
    ] = dict(regime)

    values[
        "historical_selector_state"
    ] = dict(
        inp.selector_state
    )

    values[
        "historical_cost_state"
    ] = dict(
        inp.cost_state
    )

    return FeatureVector(
        symbol=inp.symbol,
        timestamp_ms=(
            inp.observed_at_ms
        ),
        price=price,
        realized_volatility_fast=(
            fast_vol
        ),
        realized_volatility_baseline=(
            baseline_vol
        ),
        volatility_expansion=(
            volatility_expansion
        ),
        volume_zscore=(
            volume_zscore
        ),
        trade_count_zscore=_finite(
            _first(
                payload.get(
                    "trade_count_zscore"
                ),
                values.get(
                    "trade_count_zscore"
                ),
            )
        ),
        order_flow_imbalance=_finite(
            _first(
                payload.get(
                    "order_flow_imbalance"
                ),
                values.get(
                    "order_flow_imbalance"
                ),
            )
        ),
        book_imbalance=(
            book_imbalance
        ),
        spread_bps=spread_bps,
        depth_usd_25bps=depth,
        quote_volume_24h=(
            quote_volume
        ),
        return_5=return_5,
        freshness_sec=freshness,
        continuity_ratio=(
            continuity
        ),
        data_quality=(
            float(data_quality)
        ),
        values=values,
        complete=complete,
        return_zscore=_finite(
            _first(
                payload.get(
                    "return_zscore"
                ),
                values.get(
                    "return_zscore"
                ),
            )
        ),
        price_zscore=_finite(
            _first(
                payload.get(
                    "price_zscore"
                ),
                values.get(
                    "price_zscore"
                ),
            )
        ),
        range_position=_finite(
            _first(
                payload.get(
                    "range_position"
                ),
                values.get(
                    "range_position"
                ),
            )
        ),
        trend_slope=_finite(
            _first(
                payload.get(
                    "trend_slope"
                ),
                values.get(
                    "trend_slope"
                ),
            )
        ),
        atr_pct=_finite(
            _first(
                payload.get(
                    "atr_pct"
                ),
                values.get(
                    "atr_pct"
                ),
            )
        ),
        reversal_return_1=_finite(
            _first(
                payload.get(
                    "reversal_return_1"
                ),
                values.get(
                    "reversal_return_1"
                ),
            )
        ),
        momentum_consistency=_finite(
            _first(
                payload.get(
                    "momentum_consistency"
                ),
                values.get(
                    "momentum_consistency"
                ),
            )
        ),
        volume_ratio=_finite(
            _first(
                payload.get(
                    "volume_ratio"
                ),
                values.get(
                    "volume_ratio"
                ),
            )
        ),
    )
