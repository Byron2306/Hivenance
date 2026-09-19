from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .conducting_queen import QueenPolyphonicReceipt
from .pollen_economy import (
    MetatronQuorumChamber,
    PollenBounty,
    PollenSettlementReceipt,
    ProspectivePollenOutcome,
    QueenPollenEconomy,
)
from .polyphonic_quorum import PolyphonicQuorumReceipt
from .settlement import SettledRelativeForecast


def _digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class QueenPollenIssueReceipt:
    schema: str
    issue_id: str
    queen_receipt_id: str
    hypothesis_id: str
    bounty_ids: tuple[str, ...]
    bounty_types: tuple[str, ...]
    world_state_id: str
    world_state_hash: str
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class QueenPollenConductor:
    """Translate existing Queen notation into bounded research bounties.

    This does not generate trading instructions. It allocates research attention
    to roles already invited by the Queen's score.
    """

    version = "hivenance.queen_pollen_conductor.v1"

    _NOTATION_TO_BOUNTY = {
        "CHALLENGE_CADENCE": "POLLEN_DISSENT",
        "INVITE_INDEPENDENT_CORROBORATION": "POLLEN_CORROBORATE",
        "ENTER_WITH_NEW_TIMBRE": "POLLEN_NOVELTY",
        "AMPLIFY_SEARCH": "POLLEN_SEARCH",
        "TRACE_MODULATION": "POLLEN_SEARCH",
        "TRACE_TEMPORAL_TEXTURE": "POLLEN_SEARCH",
        "TRACE_PROPAGATION": "POLLEN_SEARCH",
        "TRACE_SHARED_ASSET": "POLLEN_SEARCH",
        "REHEARSE_EDGE_RESOLUTION": "POLLEN_SETTLE",
        "HOLD_CODA_OPEN": "POLLEN_SETTLE",
        "THIN_ORCHESTRATION": "POLLEN_EFFICIENCY",
        "INVITE_FRESH_TIMBRE": "POLLEN_NOVELTY",
    }

    def issue(
        self,
        *,
        queen: QueenPolyphonicReceipt,
        economy: QueenPollenEconomy,
        reward_scale: float = 10.0,
        maximum_bounties: int = 4,
    ) -> QueenPollenIssueReceipt:
        tokens = tuple(queen.notation_tokens)
        if not tokens:
            return QueenPollenIssueReceipt(
                schema="hivenance_queen_pollen_issue_v1",
                issue_id="qpollen_empty",
                queen_receipt_id=queen.receipt_id,
                hypothesis_id=queen.hypothesis_id,
                bounty_ids=(),
                bounty_types=(),
                world_state_id="",
                world_state_hash="",
            )

        issued: list[PollenBounty] = []
        seen_types: set[str] = set()
        for token in tokens:
            bounty_type = self._NOTATION_TO_BOUNTY.get(token.notation)
            if bounty_type is None:
                response = str(token.response_class or "").upper()
                if "DISSENT" in response or "CHALLENGE" in response:
                    bounty_type = "POLLEN_FALSIFY"
                elif "SEARCH" in response:
                    bounty_type = "POLLEN_SEARCH"
                elif "SETTLE" in response or "RESOLUTION" in response:
                    bounty_type = "POLLEN_SETTLE"
                else:
                    continue
            if bounty_type in seen_types:
                continue

            pool = max(1.0, float(reward_scale) * max(0.1, float(token.intensity)))
            issued.append(economy.issue_bounty(
                bounty_type=bounty_type,
                hypothesis_id=queen.hypothesis_id,
                world_state_id=token.world_state_id,
                world_state_hash=token.world_state_hash,
                horizon_band="score_phrase",
                issued_at_ms=int(token.issued_at_ms),
                expires_at_ms=max(int(token.issued_at_ms) + 1, int(token.expires_at_ms)),
                reward_pool=pool,
                challenge_required=bounty_type in {"POLLEN_DISSENT", "POLLEN_FALSIFY"},
            ))
            seen_types.add(bounty_type)
            if len(issued) >= max(1, int(maximum_bounties)):
                break

        world_state_id = tokens[0].world_state_id
        world_state_hash = tokens[0].world_state_hash
        body = {
            "queen_receipt_id": queen.receipt_id,
            "bounties": [b.bounty_id for b in issued],
            "world_state_id": world_state_id,
            "world_state_hash": world_state_hash,
        }
        return QueenPollenIssueReceipt(
            schema="hivenance_queen_pollen_issue_v1",
            issue_id="qpollen_" + _digest(body).split(":", 1)[1][:24],
            queen_receipt_id=queen.receipt_id,
            hypothesis_id=queen.hypothesis_id,
            bounty_ids=tuple(b.bounty_id for b in issued),
            bounty_types=tuple(b.bounty_type for b in issued),
            world_state_id=world_state_id,
            world_state_hash=world_state_hash,
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )


@dataclass(frozen=True)
class PollenProfitBook:
    settled_count: int
    selected_count: int
    abstained_count: int
    winning_count: int
    losing_count: int
    cumulative_net_bps: float
    mean_net_bps: float
    median_net_bps: float
    win_rate: float
    current_positive_streak: int
    longest_positive_streak: int
    max_drawdown_bps: float


@dataclass(frozen=True)
class PollenProfitComparison:
    schema: str
    comparison_id: str
    control: PollenProfitBook
    treatment: PollenProfitBook
    selection_rate: float
    cumulative_delta_bps: float
    mean_delta_bps: float
    authority: str = RELATIVE_VALUE_AUTHORITY
    execution_eligible: bool = False
    promotion_eligible: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["control"] = asdict(self.control)
        payload["treatment"] = asdict(self.treatment)
        return payload


@dataclass(frozen=True)
class _OutcomeRow:
    forecast_id: str
    net_bps: float
    treatment_selected: bool


class PollenProfitExperiment:
    """Prospective A/B ledger for Pollen/Quorum selection.

    Control records every resolved non-abstaining paper settlement.
    Treatment records the same settlement only if quorum had already formed.
    No future result is visible when treatment selection is made.
    """

    version = "hivenance.pollen_profit_experiment.v1"

    def __init__(self) -> None:
        self._rows: list[_OutcomeRow] = []
        self._seen: set[str] = set()

    def record(
        self,
        *,
        settlement: SettledRelativeForecast,
        quorum: PolyphonicQuorumReceipt | None,
    ) -> None:
        if settlement.forecast_id in self._seen:
            raise ValueError("pollen_profit_forecast_already_recorded")
        self._seen.add(settlement.forecast_id)

        if settlement.abstain or settlement.realized_directional_net_bps is None:
            return

        selected = bool(quorum is not None and quorum.quorum_formed)
        self._rows.append(_OutcomeRow(
            forecast_id=settlement.forecast_id,
            net_bps=float(settlement.realized_directional_net_bps),
            treatment_selected=selected,
        ))

    @staticmethod
    def _book(values: Sequence[float], *, settled_count: int) -> PollenProfitBook:
        rows = [float(v) for v in values]
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        current = 0
        longest = 0
        for value in rows:
            equity += value
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
            if value > 0:
                current += 1
                longest = max(longest, current)
            else:
                current = 0

        wins = sum(v > 0 for v in rows)
        losses = sum(v <= 0 for v in rows)
        selected = len(rows)
        return PollenProfitBook(
            settled_count=int(settled_count),
            selected_count=selected,
            abstained_count=max(0, int(settled_count) - selected),
            winning_count=wins,
            losing_count=losses,
            cumulative_net_bps=round(sum(rows), 6),
            mean_net_bps=round(statistics.fmean(rows), 6) if rows else 0.0,
            median_net_bps=round(statistics.median(rows), 6) if rows else 0.0,
            win_rate=round(wins / selected, 6) if selected else 0.0,
            current_positive_streak=current,
            longest_positive_streak=longest,
            max_drawdown_bps=round(max_dd, 6),
        )

    def summary(self) -> PollenProfitComparison:
        control_values = [row.net_bps for row in self._rows]
        treatment_values = [row.net_bps for row in self._rows if row.treatment_selected]
        total = len(self._rows)
        control = self._book(control_values, settled_count=total)
        treatment = self._book(treatment_values, settled_count=total)
        selection_rate = len(treatment_values) / total if total else 0.0
        body = {
            "forecasts": [row.forecast_id for row in self._rows],
            "selected": [row.forecast_id for row in self._rows if row.treatment_selected],
            "control_net": control.cumulative_net_bps,
            "treatment_net": treatment.cumulative_net_bps,
        }
        return PollenProfitComparison(
            schema="hivenance_pollen_profit_comparison_v1",
            comparison_id="pcomp_" + _digest(body).split(":", 1)[1][:24],
            control=control,
            treatment=treatment,
            selection_rate=round(selection_rate, 6),
            cumulative_delta_bps=round(treatment.cumulative_net_bps - control.cumulative_net_bps, 6),
            mean_delta_bps=round(treatment.mean_net_bps - control.mean_net_bps, 6),
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )


def settle_pollen_from_forecast(
    *,
    economy: QueenPollenEconomy,
    bounty: PollenBounty,
    settlement: SettledRelativeForecast,
    quorum: PolyphonicQuorumReceipt | None,
    information_gain: float = 1.0,
) -> PollenSettlementReceipt:
    """Bind Pollen redistribution to an actual prospective paper settlement."""
    outcome = ProspectivePollenOutcome.from_settled_forecast(
        hypothesis_id=bounty.hypothesis_id,
        settlement=settlement,
        information_gain=information_gain,
    )
    return economy.settle(
        bounty=bounty,
        outcome=outcome,
        quorum=quorum,
    )
