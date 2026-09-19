import pytest
from strategies.relative_value_lab.g0_settlement import G0PairedOutcome,G0SettlementBook

def row(org,kind,oid,full,blind):
 return G0PairedOutcome(org,kind,oid,"sha256:"+"a"*64,full,blind)

def test_historical_and_prospective_usefulness_never_bleed_together():
 b=G0SettlementBook()
 b.add(row("edge_ecology","HISTORICAL","h1",5,1));b.add(row("edge_ecology","HISTORICAL","h2",4,2))
 b.add(row("edge_ecology","PROSPECTIVE","p1",-1,1))
 h=b.verdict("edge_ecology","HISTORICAL");p=b.verdict("edge_ecology","PROSPECTIVE")
 assert h.classification=="HISTORICALLY_USEFUL" and h.mean_delta_bps==3
 assert p.classification=="INFLUENTIAL" and p.mean_delta_bps==-2
 assert not h.execution_eligible and not p.promotion_eligible

def test_positive_prospective_pairs_can_earn_prospective_label_without_execution_authority():
 b=G0SettlementBook();b.add(row("x","PROSPECTIVE","p1",3,1));b.add(row("x","PROSPECTIVE","p2",2,1))
 v=b.verdict("x","PROSPECTIVE")
 assert v.classification=="PROSPECTIVELY_USEFUL" and v.paired_n==2 and v.positive_pairs==2
 assert not v.execution_eligible and not v.promotion_eligible

def test_duplicate_or_unbound_outcomes_refuse():
 b=G0SettlementBook();r=row("x","HISTORICAL","1",1,0);b.add(r)
 with pytest.raises(ValueError,match="duplicate"):b.add(r)
 with pytest.raises(ValueError,match="world_state"):b.add(G0PairedOutcome("x","HISTORICAL","2","bad",1,0))
