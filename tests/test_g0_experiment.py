import pytest
from strategies.relative_value_lab.g0_experiment import G0ExperimentRunner
from strategies.relative_value_lab.g0_receipts import G0ReceiptLedger
from strategies.relative_value_lab.g0_settlement import G0PairedOutcome
from strategies.relative_value_lab.world_score import ScoreObservation,CanonicalWorldScore
from strategies.relative_value_lab.edge_ecology import EdgeEcology

def frame():
 o=ScoreObservation("o","kraken","public_market","BTC/USD",10,10,"sha256:"+"a"*64,{"price":100})
 return CanonicalWorldScore.assemble(observations=[o],assembled_at_ms=10,freshness_window_ms=100)

def test_end_to_end_g0_freezes_ablates_settles_and_persists(tmp_path):
 f=frame();snap=EdgeEcology().snapshot(timestamp_ms=10,pair_id="BTC/USD",voices=(
  EdgeEcology.flow_voice(taker_buy_volume=60,taker_sell_volume=40),
  EdgeEcology.liquidity_voice(bid_depth=60,ask_depth=40,spread_bps=2),))
 l=G0ReceiptLedger(str(tmp_path/"g0.db"));r=G0ExperimentRunner(ledger=l)
 outcome=G0PairedOutcome("edge_ecology","PROSPECTIVE","p1",f.world_state_hash,3,1)
 x=r.run(created_at_ms=10,config={"cost_model":"already_net"},organs=("edge_ecology",),
  paired_outcomes=(outcome,),frame=f,now_ms=10,edge_snapshot=snap,
  edge_roots={"FLOW":("sha256:"+"b"*64,),"LIQUIDITY":("sha256:"+"c"*64,)})
 assert x.ablation["verdicts"][0]["classification"]=="INFLUENTIAL"
 assert x.economic_verdicts[0]["classification"]=="PROSPECTIVELY_USEFUL"
 assert len(x.receipt_ids)==3 and len(l.rows())==3
 assert not x.execution_eligible and not x.promotion_eligible
 l.close()

def test_g0_refuses_settlement_from_different_world(tmp_path):
 f=frame();l=G0ReceiptLedger(str(tmp_path/"g0.db"));r=G0ExperimentRunner(ledger=l)
 bad=G0PairedOutcome("edge_ecology","HISTORICAL","h1","sha256:"+"f"*64,1,0)
 with pytest.raises(ValueError,match="world_mismatch"):
  r.run(created_at_ms=10,config={},organs=("edge_ecology",),paired_outcomes=(bad,),frame=f,now_ms=10)
 l.close()
