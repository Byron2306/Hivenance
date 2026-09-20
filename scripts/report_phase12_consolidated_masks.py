#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from strategies.relative_value_lab.historical_real_corpus import HistoricalRealCorpus
from strategies.relative_value_lab.historical_reconstruction_input import reconstruction_input_from_case
from strategies.relative_value_lab.historical_feature_reconstruction import feature_from_reconstruction
from strategies.relative_value_lab.historical_organ_reconstruction import reconstruct_historical_organs
from strategies.relative_value_lab.historical_phoenix_replay import (
    default_historical_competition,
    replay_historical_phoenix,
)
from strategies.relative_value_lab.historical_real_settlement_tape import real_settlement_truth
from strategies.relative_value_lab.historical_forecast_outcome import forecast_outcome_on_real_tape


CONTROL_MODELS={
    "SIMPLE_MOMENTUM":"baseline_simple_momentum_v1",
    "SIMPLE_REVERSION":"baseline_simple_mean_reversion_v1",
    "DETERMINISTIC_RANDOM":"baseline_deterministic_random_v1",
    "NO_TRADE":"baseline_no_trade_v1",
}

# These masks have canonical implementations, but this historical corpus does
# not contain the complete pre-T state required to prosecute them without
# manufacturing evidence. They remain first-class Phase-13 shadow targets.
EXPLICIT_UNAVAILABLE={
    "NO_LONG_HORIZON_LATTICE":"no_fresh_pre_t_horizon_context_on_corpus",
    "NO_CEX_ORACLE":"no_frozen_full_hive_selection_layer_for_oracle_removal",
    "NO_COIN_SELECTOR":"selector_already_conditioned_the_frozen_corpus",
    "NO_REGIME":"no_complete_pre_t_regime_oracle_state_for_same_world_ablation",
    "NO_FLOW":"no_pre_t_flow_voice_reconstructable_on_corpus",
    "NO_VOLATILITY":"no_pre_t_volatility_voice_reconstructable_on_corpus",
    "NO_CROSS_MARKET":"no_pre_t_cross_market_voice_reconstructable_on_corpus",
    "NO_EXTERNAL":"no_pre_t_external_statistics_context_on_corpus",
    "NO_CONFORMAL":"no_pre_t_calibration_context_on_corpus",
    "NO_ML":"no_pre_t_ml_challenger_receipt_on_corpus",
    "NO_VNS_PHRASE":"no_pre_t_vns_phrase_stream_on_corpus",
    "NO_TEMPORAL_TEXTURE":"no_pre_t_temporal_texture_on_corpus",
    "NO_QUORUM":"no_pre_t_polyphonic_quorum_receipt_on_corpus",
    "NO_QUEEN":"no_pre_t_conducting_queen_receipt_on_corpus",
    "NO_MYSTIQUE":"no_pre_t_mystique_challenge_on_corpus",
    "NO_METABOLISM":"no_pre_t_cognitive_metabolism_receipt_on_corpus",
    "NO_POLLEN":"no_pre_t_pollen_state_on_corpus",
}


def _outcome_dict(outcome, *, selected):
    row=outcome.to_dict()
    row["selected"]=bool(selected)
    return row


def _model_map(replay):
    return {
        (str(f.model_id),int(f.horizon_seconds)):f
        for f in replay.forecasts
    }


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--db",default="data/swarm_data.db")
    ap.add_argument("--out",type=Path,default=Path("data/phase12_consolidated_masks.json"))
    args=ap.parse_args()

    cases=HistoricalRealCorpus(args.db).load_cases()
    outcomes=defaultdict(list)
    invocation_counts=defaultdict(int)
    availability_counts=defaultdict(int)

    for case in cases:
        inp=reconstruction_input_from_case(case)
        feature=feature_from_reconstruction(inp)
        bundle=reconstruct_historical_organs(inp,feature)
        truth=real_settlement_truth(case)
        competition=default_historical_competition()

        full=replay_historical_phoenix(
            inp,organ_bundle=bundle,competition=competition
        )
        full_map=_model_map(full)

        for forecast in full.forecasts:
            out=forecast_outcome_on_real_tape(
                forecast=forecast,truth=truth,
                world_state_id=case.world_state_id,
                world_state_hash=case.world_state_hash,
            )
            outcomes["FULL_HIVE"].append(_outcome_dict(out,selected=case.selected))

        # Lawfully reconstructable same-world masks.
        mask_specs={
            "NO_COMPARISON":(
                "comparison_engine",
                ("INVOKABLE",),
                "comparison_engine",
                ("comparison_engine",),
            ),
            "NO_LIQUIDITY":(
                "liquidity",
                ("INVOKABLE",),
                "edge_ecology",
                ("edge_ecology",),
            ),
            "NO_TEMPORAL_PARTICIPATION":(
                "temporal_participation_bee",
                ("INVOKABLE","INVOKABLE_LOW_HISTORY"),
                "temporal_participation_bee",
                ("temporal_participation_bee",),
            ),
        }
        for mask_id,(availability_key,allowed,scope,disabled) in mask_specs.items():
            state=str(bundle.status.get(availability_key) or "ABSENT_DATA")
            if state not in allowed:
                continue
            availability_counts[mask_id]+=1
            masked=replay_historical_phoenix(
                inp,organ_bundle=bundle,competition=competition,
                challenge_scope=scope,disabled_organs=disabled,
            )
            invocation_counts[mask_id]+=1
            for forecast in masked.forecasts:
                out=forecast_outcome_on_real_tape(
                    forecast=forecast,truth=truth,
                    world_state_id=case.world_state_id,
                    world_state_hash=case.world_state_hash,
                )
                outcomes[mask_id].append(_outcome_dict(out,selected=case.selected))

        # Controls are existing frozen baseline models, scored on exactly the
        # same future tape. No synthetic directions are introduced here.
        for control_id,model_id in CONTROL_MODELS.items():
            forecast=full_map.get((model_id,int(inp.horizon_seconds)))
            if forecast is None:
                continue
            out=forecast_outcome_on_real_tape(
                forecast=forecast,truth=truth,
                world_state_id=case.world_state_id,
                world_state_hash=case.world_state_hash,
            )
            outcomes[control_id].append(_outcome_dict(out,selected=case.selected))
            invocation_counts[control_id]+=1

    payload={
        "schema":"hivenance_full_organism_census_replay_bundle_v1",
        "source":"report_phase12_consolidated_masks",
        "strict_before":True,
        "outcomes_by_mask":dict(outcomes),
        "invocation_counts":dict(invocation_counts),
        "explicit_unavailable_masks":EXPLICIT_UNAVAILABLE,
        "control_masks_prosecuted":{
            control:{
                "model_id":model,
                "rows":len(outcomes.get(control,())),
                "historical_only":True,
                "execution_eligible":False,
                "promotion_eligible":False,
            }
            for control,model in CONTROL_MODELS.items()
        },
        "availability_counts":dict(availability_counts),
        "historical_only":True,
        "prospective_usefulness_proved":False,
        "execution_eligible":False,
        "promotion_eligible":False,
    }
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(payload,indent=2,sort_keys=True),encoding="utf-8")
    print("HIVENANCE_PHASE12_CONSOLIDATED_MASKS")
    print("cases=",len(cases))
    print("paired_masks=",sorted(k for k in outcomes if k.startswith("NO_") and k not in CONTROL_MODELS))
    print("controls=",{k:len(outcomes.get(k,())) for k in CONTROL_MODELS})
    print("explicit_unavailable_masks=",sorted(EXPLICIT_UNAVAILABLE))
    print("out=",args.out)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
