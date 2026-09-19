"""Invoke the existing ConductingQueen on lawful Phoenix/Hive motif notes.

The Queen remains research-only. Her causal intervention is veto-only and is
triggered solely by cautionary notation she already emits.
"""
from __future__ import annotations
from dataclasses import replace
from typing import Any
from .conducting_queen import ConductingQueen
from .governance_epoch import ResearchGovernanceEpochService
from .musical_cognition import MusicalMotifAccumulator
from .polyphonic_entrainment import PolyphonicEntrainment
from .g1_polyphonic_bridge import notes_for_forecast

CAUTIONARY_NOTATION=frozenset({
 "CHALLENGE_CADENCE",
 "HOLD_FREEZE_ACCENT",
 "LET_MOTIF_REST",
 "REKEY_SCORE",
 "SEAL_SYNTHETIC_CHAMBER",
 "RETUNE_LEARNED_VOICE",
})

def queen_receipt_for_forecast(*,frame:Any,cycle:Any,forecast:Any,feature:Any,now_ms:int)->Any:
 notes=notes_for_forecast(cycle=cycle,forecast=forecast,feature=feature)
 acc=MusicalMotifAccumulator(registry=None)
 acc._notes[str(forecast.hypothesis)]=list(notes)
 motif=acc.score(str(forecast.hypothesis))
 entrainment=PolyphonicEntrainment().score(hypothesis_id=str(forecast.hypothesis),notes=notes)
 ttl=max(1,int(frame.expires_at_ms)-int(now_ms))
 epoch=ResearchGovernanceEpochService.start_epoch_from_frame(
  frame,started_at_ms=int(now_ms),ttl_ms=ttl,genre_mode="watchful",
  strictness_level="standard",scope="relative_value_lab",reason="g1_live_conducting_queen")
 return ConductingQueen().conduct_against_frame(
  frame=frame,now_ms=int(now_ms),hypothesis_id=str(forecast.hypothesis),
  notes=notes,motif=motif,entrainment=entrainment,epoch=epoch)

def apply_queen_gate(forecast:Any,receipt:Any)->Any:
 if getattr(forecast,"abstain",False):return forecast
 active=tuple(sorted({
  str(t.notation) for t in getattr(receipt,"notation_tokens",())
  if str(t.notation) in CAUTIONARY_NOTATION
 }))
 if not active:return forecast
 inputs=dict(getattr(forecast,"inputs",{}) or {})
 inputs["g1_conducting_queen"]={
  "receipt_id":receipt.receipt_id,
  "notation":active,
  "conducting_gestures":tuple(getattr(receipt,"conducting_gestures",())),
  "reasons":tuple(getattr(receipt,"reasons",())),
  "authority":"RESEARCH_VETO_ONLY",
 }
 return replace(forecast,direction="ABSTAIN",probability_positive_net=None,
  expected_move_bps=None,expected_net_bps=None,abstain=True,
  reason="g1_conducting_queen_caution",
  reasons=tuple(getattr(forecast,"reasons",()))+("g1_conducting_queen_caution",),
  inputs=inputs,execution_eligible=False)
