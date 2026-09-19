from strategies.relative_value_lab.synthesis_runtime import SynthesisRuntime
from strategies.relative_value_lab.world_score import ScoreObservation,CanonicalWorldScore
from strategies.relative_value_lab.comparison_engine import ComparisonEngine,ComparisonReference

def _frame():
 o=ScoreObservation("o","kraken","public_market","BTC/USD",100,100,"sha256:"+"a"*64,{"price":100})
 return CanonicalWorldScore.assemble(observations=[o],assembled_at_ms=100,freshness_window_ms=1000)

def test_shadow_scar_routes_to_temporal_observer_inside_same_cycle():
 r={"schema":"hivenance_adversarial_shadow_learning_v1","learning_id":"shadow:x",
 "status":"PROSPECTIVE_SHADOW_EVIDENCE","authority":"PROSPECTIVE_SHADOW_RESEARCH_ONLY",
 "comparisons":{"candidate_minus_no_trade_bps":5},"unsettled_controls":["TIME_SHIFT_PLACEBO"],
 "execution_eligible":False,"promotion_eligible":False,"interpretation":"comparative only"}
 x=SynthesisRuntime().run(frame=_frame(),now_ms=100,learning_receipts=(r,))
 assert any("TIME_SHIFT_PLACEBO" in o["target"] for o in x.attention_obligations)
 q=next(q for q in x.organ_requests if "TIME_SHIFT_PLACEBO" in q["target"])
 assert q["organ_id"]=="temporal_observer" and q["family"]=="TEMPORAL"
 assert not q["execution_eligible"] and not q["promotion_eligible"]

def test_comparison_is_visible_and_ablatable_on_identical_world():
 f=_frame();root="sha256:"+"b"*64
 refs=(ComparisonReference("r1",50,"BTC/USD",0,{"x":1.0},(root,),True,None),)
 cmp=ComparisonEngine().selected_vs_rejected(observed_at_ms=100,symbol="BTC/USD",references=refs,feature_names=("x",))
 full=SynthesisRuntime().run(frame=f,now_ms=100,comparison_results=(cmp,))
 blind=SynthesisRuntime().run(frame=f,now_ms=100,comparison_results=(cmp,),disabled_organs=("comparison_engine",))
 assert full.world_state_hash==blind.world_state_hash==f.world_state_hash
 assert "COMPARISON" in full.queen_view.families and "COMPARISON" not in blind.queen_view.families
 assert next(r for r in full.organ_receipts if r.organ_id=="comparison_engine").state=="INVOKED"
 assert next(r for r in blind.organ_receipts if r.organ_id=="comparison_engine").state=="DISABLED"
