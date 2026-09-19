from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .contracts import ForwardRelativeForecast, RelativeMarketState, RELATIVE_VALUE_AUTHORITY
from .pollen_profit_lab import PollenProfitComparison, PollenProfitExperiment
from .polyphonic_quorum import PolyphonicQuorumReceipt
from .settlement import ProspectiveForecastSettler, SettledRelativeForecast


@dataclass(frozen=True)
class RegisteredPaperHypothesis:
    forecast_id: str
    pair_id: str
    forecast_timestamp_ms: int
    horizon_seconds: int
    quorum_id: str | None
    quorum_formed: bool
    quorum_last_note_ms: int | None
    treatment_eligible_at_registration: bool
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PaperSettlementBatch:
    schema: str
    state_timestamp_ms: int
    pair_id: str
    settlements: tuple[SettledRelativeForecast, ...]
    comparison: PollenProfitComparison
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "state_timestamp_ms": self.state_timestamp_ms,
            "pair_id": self.pair_id,
            "settlements": [row.to_dict() for row in self.settlements],
            "comparison": self.comparison.to_dict(),
            "authority": self.authority,
            "execution_eligible": self.execution_eligible,
            "promotion_eligible": self.promotion_eligible,
        }


class ProspectivePollenPaperRuntime:
    """Frozen forecast/quorum registration plus future-only paper settlement.

    Quorum is captured at registration and can never be replaced after the
    future outcome is known. The treatment book therefore cannot acquire
    hindsight selection.
    """

    version = "hivenance.prospective_pollen_paper_runtime.v1"

    def __init__(
        self,
        *,
        ledger_path: Path | None = None,
    ) -> None:
        self.settler = ProspectiveForecastSettler()
        self.experiment = PollenProfitExperiment()
        self.ledger_path = ledger_path
        self._quorum_by_forecast: dict[str, PolyphonicQuorumReceipt | None] = {}
        self._registered: dict[str, RegisteredPaperHypothesis] = {}
        if self.ledger_path is not None:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

    def register(
        self,
        *,
        forecast: ForwardRelativeForecast,
        state: RelativeMarketState,
        quorum: PolyphonicQuorumReceipt | None,
    ) -> RegisteredPaperHypothesis:
        if forecast.forecast_id in self._registered:
            raise ValueError("paper_forecast_already_registered")

        treatment_eligible = bool(
            quorum is not None
            and quorum.quorum_formed
            and quorum.last_note_ms <= forecast.timestamp_ms
            and quorum.hypothesis_id == forecast.forecast_id
        )

        # Freeze a non-qualifying quorum to None. This means a later quorum can
        # never retroactively upgrade the forecast after registration.
        frozen_quorum = quorum if treatment_eligible else None

        self.settler.register(forecast=forecast, state=state)
        self._quorum_by_forecast[forecast.forecast_id] = frozen_quorum

        row = RegisteredPaperHypothesis(
            forecast_id=forecast.forecast_id,
            pair_id=forecast.pair_id,
            forecast_timestamp_ms=forecast.timestamp_ms,
            horizon_seconds=forecast.horizon_seconds,
            quorum_id=None if frozen_quorum is None else frozen_quorum.quorum_id,
            quorum_formed=bool(frozen_quorum and frozen_quorum.quorum_formed),
            quorum_last_note_ms=None if frozen_quorum is None else frozen_quorum.last_note_ms,
            treatment_eligible_at_registration=treatment_eligible,
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )
        self._registered[forecast.forecast_id] = row
        self._append_ledger("REGISTER", row.to_dict())
        return row

    def settle(self, state: RelativeMarketState) -> PaperSettlementBatch:
        rows = self.settler.settle(state)
        for row in rows:
            self.experiment.record(
                settlement=row,
                quorum=self._quorum_by_forecast.get(row.forecast_id),
            )
            self._append_ledger("SETTLE", row.to_dict())

        comparison = self.experiment.summary()
        if rows:
            self._append_ledger("SUMMARY", comparison.to_dict())
        return PaperSettlementBatch(
            schema="hivenance_pollen_paper_settlement_batch_v1",
            state_timestamp_ms=state.timestamp_ms,
            pair_id=state.pair_id,
            settlements=tuple(rows),
            comparison=comparison,
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )

    def pending(self) -> int:
        return self.settler.pending()

    def summary(self) -> PollenProfitComparison:
        return self.experiment.summary()

    def registered(self) -> tuple[RegisteredPaperHypothesis, ...]:
        return tuple(self._registered[key] for key in sorted(self._registered))

    def _append_ledger(self, event: str, payload: dict[str, Any]) -> None:
        if self.ledger_path is None:
            return
        row = {
            "event": event,
            "payload": payload,
            "authority": RELATIVE_VALUE_AUTHORITY,
            "execution_eligible": False,
            "promotion_eligible": False,
        }
        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
