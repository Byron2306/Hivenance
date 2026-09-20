from strategies.relative_value_lab.synthesis_runtime import SynthesisRuntime
from strategies.relative_value_lab.world_score import ScoreObservation,CanonicalWorldScore
from strategies.relative_value_lab.edge_ecology import EdgeEcology

def frame():
 o=ScoreObservation("o","kraken","public_market","BTC/USD",10,10,"sha256:"+"a"*64,{"price":100})
 return CanonicalWorldScore.assemble(observations=[o],assembled_at_ms=10,freshness_window_ms=100)

def test_synthesis_runtime_preserves_world_and_supports_same_tape_ablation():
 f=frame();snap=EdgeEcology().snapshot(timestamp_ms=10,pair_id="BTC/USD",voices=(
  EdgeEcology.flow_voice(taker_buy_volume=60,taker_sell_volume=40),
  EdgeEcology.liquidity_voice(bid_depth=60,ask_depth=40,spread_bps=2),))
 roots={"FLOW":("sha256:"+"b"*64,),"LIQUIDITY":("sha256:"+"c"*64,)}
 full=SynthesisRuntime().run(frame=f,now_ms=10,edge_snapshot=snap,edge_roots=roots)
 blind=SynthesisRuntime().run(frame=f,now_ms=10,edge_snapshot=snap,edge_roots=roots,disabled_organs=("edge_ecology",))
 assert full.world_state_id==blind.world_state_id==f.world_state_id
 assert full.world_state_hash==blind.world_state_hash==f.world_state_hash
 assert {"FLOW","LIQUIDITY"}.issubset(set(full.queen_view.families))
 assert "FLOW" not in blind.queen_view.families
 assert not full.execution_eligible and not full.promotion_eligible
 assert next(x for x in blind.organ_receipts if x.organ_id=="edge_ecology").state=="DISABLED"

def test_learning_enters_same_cycle_without_authority_gain():
 f=frame();r={"schema":"hivenance_adversarial_shadow_learning_v1","learning_id":"shadow:x",
 "status":"PROSPECTIVE_SHADOW_EVIDENCE","authority":"PROSPECTIVE_SHADOW_RESEARCH_ONLY",
 "candidate_net_return_bps":5,"comparisons":{"candidate_minus_no_trade_bps":5},
 "unsettled_controls":["TIME_SHIFT_PLACEBO"],"execution_eligible":False,"promotion_eligible":False,
 "interpretation":"comparative only"}
 x=SynthesisRuntime().run(frame=f,now_ms=10,learning_receipts=(r,))
 assert "LEARNING" in x.queen_view.families
 assert "shadow:x" in x.learning["learning_ids"]
 assert any("TIME_SHIFT_PLACEBO" in z for z in x.learning["next_falsifications"])


def test_synthesis_runtime_phase5_edge_families_are_canonical_bee_evidence():
    f=frame()
    snap=EdgeEcology().snapshot(
        timestamp_ms=10,
        pair_id="BTC/USD",
        voices=(
            EdgeEcology.flow_voice(
                taker_buy_volume=60,
                taker_sell_volume=40,
            ),
            EdgeEcology.liquidity_voice(
                bid_depth=60,
                ask_depth=40,
                spread_bps=2,
            ),
        ),
    )
    roots={
        "FLOW":("sha256:"+"b"*64,),
        "LIQUIDITY":("sha256:"+"c"*64,),
    }

    cycle=SynthesisRuntime().run(
        frame=f,
        now_ms=10,
        edge_snapshot=snap,
        edge_roots=roots,
    )

    nodes=[
        node for node in cycle.queen_view.nodes
        if node.family in {"FLOW","LIQUIDITY"}
    ]

    assert len(nodes)==2

    for node in nodes:
        assert node.organ_id=="bee_evidence"
        assert node.payload["schema"]=="hivenance_bee_evidence_v1"
        assert node.payload["family"]==node.family
        assert node.payload["execution_eligible"] is False
        assert node.payload["promotion_eligible"] is False
