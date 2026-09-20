from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

from strategies.volatility_breakout.models import Forecast


BOOK_MODEL_IDS={
    "CEX_ORACLE_ONLY":{"candidate_cex_multi_horizon_oracle_v1"},
    "SIMPLE_MOMENTUM":{"baseline_simple_momentum_v1"},
    "SIMPLE_REVERSION":{"baseline_simple_mean_reversion_v1"},
    "DETERMINISTIC_RANDOM":{"baseline_deterministic_random_v1"},
    "NO_TRADE":{"baseline_no_trade_v1"},
}


@dataclass(frozen=True)
class Phase13ForecastBookRow:
    freeze_id: str
    book_id: str
    world_state_id: str
    world_state_hash: str
    symbol: str
    timestamp_ms: int
    horizon_seconds: int
    model_id: str
    direction: str
    abstain: bool
    probability_positive_net: float | None
    expected_move_bps: float | None
    expected_cost_bps: float | None
    expected_net_bps: float | None
    envelope_id: str | None
    entry_price: float | None = None
    regime: str | None = None
    execution_eligible: bool=False
    promotion_eligible: bool=False

    def __post_init__(self)->None:
        if self.execution_eligible or self.promotion_eligible:
            raise ValueError("phase13_book_authority_escalation_forbidden")
        if not str(self.world_state_hash).startswith("sha256:"):
            raise ValueError("phase13_book_world_hash_required")

    def to_dict(self)->dict[str,Any]:
        return asdict(self)


def _rows(
    *,
    freeze_id:str,
    book_id:str,
    world_state_id:str,
    world_state_hash:str,
    forecasts:Iterable[Forecast],
    envelope_id:str|None=None,
    entry_price:float|None=None,
    regime:str|None=None,
)->list[Phase13ForecastBookRow]:
    out=[]
    for forecast in forecasts:
        out.append(Phase13ForecastBookRow(
            freeze_id=str(freeze_id),
            book_id=str(book_id),
            world_state_id=str(world_state_id),
            world_state_hash=str(world_state_hash),
            symbol=str(forecast.symbol),
            timestamp_ms=int(forecast.timestamp_ms),
            horizon_seconds=int(forecast.horizon_seconds),
            model_id=str(forecast.model_id),
            direction=str(forecast.direction),
            abstain=bool(forecast.abstain),
            probability_positive_net=forecast.probability_positive_net,
            expected_move_bps=forecast.expected_move_bps,
            expected_cost_bps=forecast.expected_cost_bps,
            expected_net_bps=forecast.expected_net_bps,
            envelope_id=envelope_id,
            entry_price=(None if entry_price is None else float(entry_price)),
            regime=(None if regime is None else str(regime)),
            execution_eligible=False,
            promotion_eligible=False,
        ))
    return out


def route_phase13_forecast_books(
    *,
    freeze_id:str,
    world_state_id:str,
    world_state_hash:str,
    frozen_full_forecasts:Sequence[Forecast],
    adaptive_forecasts:Sequence[Forecast],
    phoenix_primary_ids:Sequence[str],
    envelope_id:str|None=None,
    entry_price:float|None=None,
    regime:str|None=None,
)->tuple[Phase13ForecastBookRow,...]:
    rows=[]
    rows.extend(_rows(
        freeze_id=freeze_id,book_id="FULL_HIVE_FROZEN",
        world_state_id=world_state_id,world_state_hash=world_state_hash,
        forecasts=frozen_full_forecasts,envelope_id=envelope_id,entry_price=entry_price,regime=regime,
    ))
    rows.extend(_rows(
        freeze_id=freeze_id,book_id="ADAPTIVE_HIVE",
        world_state_id=world_state_id,world_state_hash=world_state_hash,
        forecasts=adaptive_forecasts,envelope_id=envelope_id,entry_price=entry_price,regime=regime,
    ))

    full_by_model={}
    for forecast in frozen_full_forecasts:
        full_by_model.setdefault(str(forecast.model_id),[]).append(forecast)

    primary=set(str(x) for x in phoenix_primary_ids)
    rows.extend(_rows(
        freeze_id=freeze_id,book_id="PHOENIX_ONLY",
        world_state_id=world_state_id,world_state_hash=world_state_hash,
        forecasts=[
            forecast
            for model_id,forecasts in full_by_model.items()
            if model_id in primary
            for forecast in forecasts
        ],
        envelope_id=envelope_id,entry_price=entry_price,regime=regime,
    ))

    for book_id,model_ids in BOOK_MODEL_IDS.items():
        rows.extend(_rows(
            freeze_id=freeze_id,book_id=book_id,
            world_state_id=world_state_id,world_state_hash=world_state_hash,
            forecasts=[
                forecast
                for model_id,forecasts in full_by_model.items()
                if model_id in model_ids
                for forecast in forecasts
            ],
            envelope_id=envelope_id,entry_price=entry_price,regime=regime,
        ))

    return tuple(rows)
