from pathlib import Path
from types import SimpleNamespace

import json

from strategies.relative_value_lab.phase13_runtime import Phase13Runtime
from strategies.volatility_breakout.models import FeatureVector


def _feature():
    return FeatureVector(
        symbol="BTC/USD",timestamp_ms=1000,price=100.0,
        realized_volatility_fast=.01,realized_volatility_baseline=.01,
        volatility_expansion=1.0,volume_zscore=0.0,trade_count_zscore=0.0,
        order_flow_imbalance=0.0,book_imbalance=0.0,spread_bps=2.0,
        depth_usd_25bps=100000.0,quote_volume_24h=1000000.0,return_5=.001,
        freshness_sec=1.0,continuity_ratio=1.0,data_quality=1.0,
        values={"market_world_state_crystal":{
            "world_state_id":"w1","world_state_hash":"sha256:"+"a"*64
        }},
    )


def test_phase13_runtime_persists_same_world_books(tmp_path:Path):
    freeze=tmp_path/"freeze.json"
    freeze.write_text(json.dumps({
        "freeze_id":"p13f_test",
        "horizons_seconds":[300,900],
    }))
    census=tmp_path/"census.json"
    census.write_text(json.dumps({"organ_runtime_control":{
        "statistics_bee":{"mode":"SHADOW"},
        "strategy_workers":{"mode":"QUARANTINED"},
    }}))
    cfg=SimpleNamespace(
        exchange="kraken",
        phase2_worker_signal_federation_enabled=True,
        phase2_worker_coalition_enabled=True,
        medium_trend_phase2_model_enabled=False,
        derivatives_trend_phase2_model_enabled=False,
    )
    runtime=Phase13Runtime(
        cfg,freeze_path=freeze,census_path=census,ledger_path=tmp_path/"books.db"
    )
    try:
        result=runtime.process_feature(_feature())
        assert result["freeze_id"]=="p13f_test"
        assert result["inserted"]>0
        assert result["frozen_modes"]["statistics_bee"]=="ACTIVE"
        assert result["adaptive_modes"]["statistics_bee"]=="SHADOW"
    finally:
        runtime.close()
