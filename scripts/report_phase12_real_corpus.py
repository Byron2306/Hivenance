from __future__ import annotations

import json

from strategies.relative_value_lab.historical_real_corpus import (
    HistoricalRealCorpus,
)


manifest = HistoricalRealCorpus(
    "data/swarm_data.db"
).manifest()

payload = manifest.to_dict()

payload["cases"] = [
    {
        "case_id": x.case_id,
        "freeze_id": x.freeze_id,
        "settlement_id": x.settlement_id,
        "run_id": x.observation_run_id,
        "symbol": x.symbol,
        "selected": x.selected,
        "selector_rank": x.selector_rank,
        "blind_rank": x.blind_rank,
        "world_state_id": x.world_state_id,
        "world_state_hash": x.world_state_hash,
        "horizon_seconds": x.horizon_seconds,
        "net_opportunity_bps": x.net_opportunity_bps,
        "observation_snapshot": (
            x.observation_snapshot is not None
        ),
        "observation_source": (
            None
            if x.observation_snapshot is None
            else x.observation_snapshot.get(
                "_historical_source_table"
            )
        ),
        "matching_forecasts": len(
            x.matching_forecasts
        ),
        "matching_outcomes": len(
            x.matching_outcomes
        ),
    }
    for x in manifest.cases
]

print("HIVENANCE_PHASE12_REAL_CORPUS")
print(
    json.dumps(
        payload,
        indent=2,
        sort_keys=True,
    )
)
