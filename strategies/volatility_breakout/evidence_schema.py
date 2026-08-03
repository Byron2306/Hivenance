from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional


@dataclass(frozen=True)
class ObservationEvidence:
    experiment_id: str
    run_id: str
    symbol: str
    venue: str
    observed_at_ms: int
    dataset_hash: str
    code_commit: str
    config_hash: str
    forecast_horizon_seconds: int
    data_quality: float
    observation_eligible: bool
    predicted_net_bps: Optional[float] = None
    realized_forward_bps: Optional[float] = None
    all_in_cost_bps: Optional[float] = None
    execution_eligible: bool = False
    order_submitted: bool = False

    def to_dict(self) -> dict:
        row = asdict(self)
        if row['execution_eligible'] or row['order_submitted']:
            raise ValueError('Phase-1 evidence may not authorize or record submitted orders')
        return row
