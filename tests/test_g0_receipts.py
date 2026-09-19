from strategies.relative_value_lab.g0_receipts import G0ReceiptLedger,AUTHORITY
from strategies.relative_value_lab.g0_freeze import freeze_g0
from strategies.relative_value_lab.g0_settlement import G0EconomicVerdict

def test_g0_freeze_is_deterministic_and_nonexecuting():
 a=freeze_g0(created_at_ms=1,organs=("edge_ecology",),config={"cost_bps":5})
 b=freeze_g0(created_at_ms=99,organs=("edge_ecology",),config={"cost_bps":5})
 assert a.freeze_id==b.freeze_id
 assert not a.execution_eligible and not a.promotion_eligible

def test_receipts_are_durable_idempotent_and_authority_closed(tmp_path):
 db=tmp_path/"g0.db";l=G0ReceiptLedger(str(db))
 v=G0EconomicVerdict("edge_ecology","HISTORICAL",2,3.0,2,0,0,"HISTORICALLY_USEFUL")
 p=v.to_dict();r1=l.persist(kind="ECONOMIC_HISTORICAL",world_state_hash="sha256:"+"a"*64,payload=p,created_at_ms=1)
 r2=l.persist(kind="ECONOMIC_HISTORICAL",world_state_hash="sha256:"+"a"*64,payload=p,created_at_ms=2)
 assert r1==r2 and len(l.rows())==1
 row=l.rows()[0]["payload"];assert row["authority"]==AUTHORITY
 assert row["execution_eligible"] is False and row["promotion_eligible"] is False
 l.close()
