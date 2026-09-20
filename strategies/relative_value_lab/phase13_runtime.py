from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

from strategies.volatility_breakout.hypothesis_competition import HypothesisCompetition
from strategies.volatility_breakout.models import FeatureVector, Forecast

from .phase13_book_ledger import Phase13BookLedger
from .phase13_book_router import route_phase13_forecast_books
from .phase13_runtime_modes import build_phase13_mode_snapshot


def _sha(value:Any)->str:
    return "sha256:"+hashlib.sha256(
        json.dumps(value,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")
    ).hexdigest()


def _world_binding(feature:FeatureVector)->tuple[str,str]:
    values=feature.values if isinstance(feature.values,dict) else {}
    candidates=[
        values.get("market_world_state_crystal"),
        values.get("full_temporal_lattice"),
    ]
    for row in candidates:
        if not isinstance(row,Mapping):
            continue
        world_id=str(
            row.get("world_state_id")
            or row.get("canonical_world_state_id")
            or ""
        )
        world_hash=str(
            row.get("world_state_hash")
            or row.get("canonical_world_state_hash")
            or ""
        )
        if world_id and world_hash.startswith("sha256:"):
            return world_id,world_hash
    raise ValueError("phase13_canonical_world_binding_missing")


class Phase13Runtime:
    """Same-world Phase-13 frozen/adaptive forecast-book producer."""

    def __init__(
        self,
        cfg:Any,
        *,
        freeze_path:str|Path="data/phase13_experiment_freeze.json",
        census_path:str|Path="data/full_organism_census.json",
        ledger_path:str|Path="data/hivenance_phase13_books.db",
    )->None:
        self.cfg=cfg
        self.freeze_path=Path(freeze_path)
        self.census_path=Path(census_path)
        if not self.freeze_path.exists():
            raise FileNotFoundError(self.freeze_path)
        self.freeze=json.loads(self.freeze_path.read_text(encoding="utf-8"))
        self.freeze_id=str(self.freeze.get("freeze_id") or "")
        if not self.freeze_id:
            raise ValueError("phase13_freeze_id_missing")
        self.horizons=tuple(int(x) for x in self.freeze.get("horizons_seconds") or ())
        if not self.horizons:
            raise ValueError("phase13_horizons_missing")
        self.ledger=Phase13BookLedger(ledger_path)

        control={}
        if self.census_path.exists():
            payload=json.loads(self.census_path.read_text(encoding="utf-8"))
            control=dict(payload.get("organ_runtime_control") or {})
        modes=build_phase13_mode_snapshot(adaptive_control=control)

        frozen_cfg=copy.copy(cfg)
        frozen_cfg.phase12_organ_runtime_modes=dict(modes.frozen_modes)
        adaptive_cfg=copy.copy(cfg)
        adaptive_cfg.phase12_organ_runtime_modes=dict(modes.adaptive_modes)

        self.frozen_modes=dict(modes.frozen_modes)
        self.adaptive_modes=dict(modes.adaptive_modes)
        self.frozen_competition=HypothesisCompetition(frozen_cfg)
        self.adaptive_competition=HypothesisCompetition(adaptive_cfg)

    def refresh_adaptive_modes(self)->None:
        if not self.census_path.exists():
            return
        payload=json.loads(self.census_path.read_text(encoding="utf-8"))
        control=dict(payload.get("organ_runtime_control") or {})
        modes=build_phase13_mode_snapshot(adaptive_control=control)
        adaptive_cfg=copy.copy(self.cfg)
        adaptive_cfg.phase12_organ_runtime_modes=dict(modes.adaptive_modes)
        self.adaptive_modes=dict(modes.adaptive_modes)
        self.adaptive_competition=HypothesisCompetition(adaptive_cfg)

    def process_feature(self,feature:FeatureVector)->dict[str,Any]:
        world_id,world_hash=_world_binding(feature)

        frozen_forecasts=tuple(self.frozen_competition.evaluate(feature,self.horizons))
        adaptive_forecasts=tuple(self.adaptive_competition.evaluate(feature,self.horizons))

        rows=route_phase13_forecast_books(
            freeze_id=self.freeze_id,
            world_state_id=world_id,
            world_state_hash=world_hash,
            frozen_full_forecasts=frozen_forecasts,
            adaptive_forecasts=adaptive_forecasts,
            phoenix_primary_ids=self.frozen_competition.primary_ids,
        )

        inserted=self.ledger.persist_forecasts(rows)
        return {
            "freeze_id":self.freeze_id,
            "world_state_id":world_id,
            "world_state_hash":world_hash,
            "frozen_forecasts":len(frozen_forecasts),
            "adaptive_forecasts":len(adaptive_forecasts),
            "book_rows":len(rows),
            "inserted":inserted,
            "frozen_modes":dict(self.frozen_modes),
            "adaptive_modes":dict(self.adaptive_modes),
            "execution_eligible":False,
            "promotion_eligible":False,
        }

    def close(self)->None:
        self.ledger.close()
