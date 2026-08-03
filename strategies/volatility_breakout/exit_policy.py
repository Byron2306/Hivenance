from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchExitPolicy:
    initial_stop_r: float = 1.0
    target_r: float = 1.5
    trailing_activation_r: float = 1.0
    maximum_holding_seconds: int = 900

    def validate(self) -> None:
        if self.initial_stop_r <= 0 or self.target_r <= 0:
            raise ValueError("risk multiples must be positive")
        if self.maximum_holding_seconds <= 0:
            raise ValueError("maximum_holding_seconds must be positive")
