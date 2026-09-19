from __future__ import annotations

import hashlib
import json
import statistics
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Sequence

from .contracts import RELATIVE_VALUE_AUTHORITY
from .temporal_texture import TemporalTexture, TemporalTextureReceipt
from .vns_score_conductor import VNSMeasure


def _clamp(v:float)->float:
    return max(0.0,min(1.0,float(v)))


def _digest(payload:Any)->str:
    raw=json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")
    return "sha256:"+hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class VNSScorePhrase:
    schema:str
    phrase_id:str
    measure_count:int
    first_measure_ms:int
    last_measure_ms:int
    duration_ms:int
    temporal_texture:TemporalTextureReceipt
    mean_pulse_energy:float
    pulse_density:float
    pulse_recurrence:float
    rest_density:float
    measure_novelty:float
    echo_pressure:float
    source_churn:float
    freshness_decay:float
    crescendo:float
    decrescendo:float
    modulation:float
    phrase_energy:float
    recent_measure_ids:tuple[str,...]
    authority:str=RELATIVE_VALUE_AUTHORITY
    execution_eligible:bool=False
    promotion_eligible:bool=False

    def to_dict(self)->dict[str,Any]:
        payload=asdict(self)
        payload["temporal_texture"]=self.temporal_texture.to_dict()
        return payload


class VNSScoreStream:
    """Remember canonical VNS measures as a musical phrase, not a lifecycle."""

    version="hivenance.vns_score_stream.v1"

    def __init__(self,*,max_measures:int=32,temporal:TemporalTexture|None=None)->None:
        self._measures:deque[VNSMeasure]=deque(maxlen=max(4,int(max_measures)))
        self.temporal=temporal or TemporalTexture()

    def append(self,measure:VNSMeasure)->VNSScorePhrase:
        if self._measures and measure.observed_at_ms < self._measures[-1].observed_at_ms:
            raise ValueError("vns_measure_time_reversal")
        if any(m.measure_id==measure.measure_id for m in self._measures):
            return self.phrase()
        self._measures.append(measure)
        return self.phrase()

    def measures(self)->tuple[VNSMeasure,...]:
        return tuple(self._measures)

    @staticmethod
    def _pulse_energy(measure:VNSMeasure)->float:
        if not measure.pulses:
            return 0.0
        return _clamp(statistics.fmean(
            float(p.amplitude)*float(p.confidence)*float(p.freshness)
            for p in measure.pulses
        ))

    @staticmethod
    def _scope_signature(measure:VNSMeasure)->set[str]:
        return set(measure.frame.scopes)

    @staticmethod
    def _source_signature(measure:VNSMeasure)->set[str]:
        return set(measure.frame.sources)

    @staticmethod
    def _pulse_signature(measure:VNSMeasure)->set[tuple[str,str]]:
        return {(p.scope,p.pulse_class) for p in measure.pulses}

    @staticmethod
    def _jaccard_distance(a:set[Any],b:set[Any])->float:
        union=a|b
        if not union:
            return 0.0
        return 1.0-(len(a&b)/len(union))

    def phrase(self)->VNSScorePhrase:
        rows=list(self._measures)
        if not rows:
            texture=self.temporal.score(())
            return VNSScorePhrase(
                schema="hivenance_vns_score_phrase_v1",
                phrase_id="phrase_empty",
                measure_count=0,
                first_measure_ms=0,last_measure_ms=0,duration_ms=0,
                temporal_texture=texture,
                mean_pulse_energy=0.0,pulse_density=0.0,pulse_recurrence=0.0,
                rest_density=1.0,measure_novelty=0.0,echo_pressure=0.0,
                source_churn=0.0,freshness_decay=0.0,crescendo=0.0,
                decrescendo=0.0,modulation=0.0,phrase_energy=0.0,
                recent_measure_ids=(),
            )

        timestamps=[m.observed_at_ms for m in rows]
        texture=self.temporal.score(timestamps)
        energies=[self._pulse_energy(m) for m in rows]
        pulse_density=sum(1 for m in rows if m.pulses)/len(rows)
        rest_density=sum(1 for m in rows if not m.pulses)/len(rows)

        pulse_recurrence_vals=[]
        novelty_vals=[]
        source_churn_vals=[]
        freshness_vals=[]
        modulation_vals=[]
        for prev,curr in zip(rows,rows[1:]):
            ps=self._pulse_signature(prev)
            cs=self._pulse_signature(curr)
            if ps or cs:
                pulse_recurrence_vals.append(1.0-self._jaccard_distance(ps,cs))
            novelty_vals.append(self._jaccard_distance(
                set(prev.frame.observed_digest),
                set(curr.frame.observed_digest),
            ))
            source_churn_vals.append(self._jaccard_distance(
                self._source_signature(prev),self._source_signature(curr)
            ))
            prev_fresh=prev.fresh_candidate_count/max(1,prev.candidate_count)
            curr_fresh=curr.fresh_candidate_count/max(1,curr.candidate_count)
            freshness_vals.append(max(0.0,prev_fresh-curr_fresh))
            modulation_vals.append(self._jaccard_distance(
                self._scope_signature(prev),self._scope_signature(curr)
            ))

        # Digest novelty is binary-ish at the frame level; temper it with source/scope continuity.
        frame_changes=sum(
            1 for a,b in zip(rows,rows[1:])
            if a.frame.observed_digest!=b.frame.observed_digest
        )
        raw_novelty=frame_changes/max(1,len(rows)-1)
        measure_novelty=_clamp(
            .65*raw_novelty
            +.20*(statistics.fmean(source_churn_vals) if source_churn_vals else 0.0)
            +.15*(statistics.fmean(modulation_vals) if modulation_vals else 0.0)
        )
        pulse_recurrence=statistics.fmean(pulse_recurrence_vals) if pulse_recurrence_vals else 0.0
        echo_pressure=_clamp(pulse_recurrence*(1.0-measure_novelty))
        source_churn=statistics.fmean(source_churn_vals) if source_churn_vals else 0.0
        freshness_decay=statistics.fmean(freshness_vals) if freshness_vals else 0.0
        modulation=statistics.fmean(modulation_vals) if modulation_vals else 0.0

        if len(energies)>=2:
            cut=max(1,len(energies)//2)
            early=statistics.fmean(energies[:cut])
            late=statistics.fmean(energies[cut:])
            crescendo=_clamp(max(0.0,late-early))
            decrescendo=_clamp(max(0.0,early-late))
        else:
            crescendo=decrescendo=0.0

        mean_energy=statistics.fmean(energies)
        phrase_energy=_clamp(
            .35*mean_energy
            +.20*pulse_density
            +.15*measure_novelty
            +.15*texture.cadence_coherence
            +.10*(1.0-echo_pressure)
            +.05*(1.0-freshness_decay)
        )

        body={
            "measure_ids":[m.measure_id for m in rows],
            "last_world":rows[-1].frame.world_state_hash,
            "energy":round(phrase_energy,6),
        }
        return VNSScorePhrase(
            schema="hivenance_vns_score_phrase_v1",
            phrase_id="phrase_"+_digest(body).split(":",1)[1][:24],
            measure_count=len(rows),
            first_measure_ms=rows[0].observed_at_ms,
            last_measure_ms=rows[-1].observed_at_ms,
            duration_ms=max(0,rows[-1].observed_at_ms-rows[0].observed_at_ms),
            temporal_texture=texture,
            mean_pulse_energy=round(mean_energy,6),
            pulse_density=round(pulse_density,6),
            pulse_recurrence=round(pulse_recurrence,6),
            rest_density=round(rest_density,6),
            measure_novelty=round(measure_novelty,6),
            echo_pressure=round(echo_pressure,6),
            source_churn=round(source_churn,6),
            freshness_decay=round(freshness_decay,6),
            crescendo=round(crescendo,6),
            decrescendo=round(decrescendo,6),
            modulation=round(modulation,6),
            phrase_energy=round(phrase_energy,6),
            recent_measure_ids=tuple(m.measure_id for m in rows[-8:]),
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
            promotion_eligible=False,
        )
