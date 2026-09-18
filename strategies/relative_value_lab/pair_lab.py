from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

from .contracts import PairRelationshipCrystal, RELATIVE_VALUE_AUTHORITY


def _finite(value: Any) -> Optional[float]:
    try:
        number=float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _hash(payload: Any) -> str:
    encoded=json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")
    return "sha256:"+hashlib.sha256(encoded).hexdigest()


def _mean(values: Sequence[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _variance(values: Sequence[float]) -> float:
    if len(values)<2:
        return 0.0
    return statistics.pvariance(values)


def _correlation(x: Sequence[float],y: Sequence[float]) -> Optional[float]:
    if len(x)!=len(y) or len(x)<3:
        return None
    mx,my=_mean(x),_mean(y)
    num=sum((a-mx)*(b-my) for a,b in zip(x,y))
    dx=sum((a-mx)**2 for a in x)
    dy=sum((b-my)**2 for b in y)
    denom=math.sqrt(dx*dy)
    return num/denom if denom>0 else None


def _ols(y: Sequence[float],x: Sequence[float]) -> tuple[Optional[float],Optional[float],Optional[float]]:
    if len(y)!=len(x) or len(x)<3:
        return None,None,None
    mx,my=_mean(x),_mean(y)
    denom=sum((v-mx)**2 for v in x)
    if denom<=0:
        return None,None,None
    beta=sum((vx-mx)*(vy-my) for vx,vy in zip(x,y))/denom
    alpha=my-beta*mx
    fitted=[alpha+beta*v for v in x]
    sst=sum((v-my)**2 for v in y)
    sse=sum((v-f)**2 for v,f in zip(y,fitted))
    r2=1.0-(sse/sst) if sst>0 else None
    return alpha,beta,r2


def _ar1(values: Sequence[float]) -> tuple[Optional[float],Optional[float],Optional[float]]:
    """Fit x_t = a + phi*x_(t-1) + eps via OLS."""
    if len(values)<6:
        return None,None,None
    y=list(values[1:])
    x=list(values[:-1])
    alpha,phi,r2=_ols(y,x)
    return alpha,phi,r2


def _half_life(phi: Optional[float], sample_interval_sec: float) -> Optional[float]:
    if phi is None or not (0.0<phi<1.0):
        return None
    decay=-math.log(phi)
    if decay<=0:
        return None
    return math.log(2.0)/decay*float(sample_interval_sec)


def _returns(log_prices: Sequence[float]) -> list[float]:
    return [b-a for a,b in zip(log_prices,log_prices[1:])]


@dataclass(frozen=True)
class PairDiagnostics:
    pair_id: str
    samples: int
    correlation_returns: Optional[float]
    hedge_alpha: Optional[float]
    hedge_ratio: Optional[float]
    hedge_r2: Optional[float]
    spread_mean: Optional[float]
    spread_std: Optional[float]
    spread_last: Optional[float]
    spread_zscore: Optional[float]
    ar1_intercept: Optional[float]
    ar1_phi: Optional[float]
    ar1_r2: Optional[float]
    ou_mean_reversion_speed_per_sec: Optional[float]
    ou_equilibrium: Optional[float]
    half_life_seconds: Optional[float]
    structural_break_score: Optional[float]
    structural_break_state: str
    stability_score: float
    eligible: bool
    rejection_reasons: tuple[str,...]

    def to_dict(self) -> dict[str,Any]:
        return self.__dict__.copy()


class PairRelationshipLab:
    """Transparent relative-value relationship estimator.

    This is a research filter, not a profitability model. It estimates whether a
    pair has behaved like a bounded mean-reverting relationship over the supplied
    synchronized history.
    """

    def __init__(
        self,
        *,
        min_samples: int = 60,
        min_return_correlation: float = 0.10,
        max_half_life_fraction: float = 0.50,
        max_structural_break_score: float = 3.0,
        min_stability_score: float = 0.45,
    ) -> None:
        self.min_samples=max(20,int(min_samples))
        self.min_return_correlation=float(min_return_correlation)
        self.max_half_life_fraction=max(0.05,min(1.0,float(max_half_life_fraction)))
        self.max_structural_break_score=max(0.1,float(max_structural_break_score))
        self.min_stability_score=max(0.0,min(1.0,float(min_stability_score)))

    @staticmethod
    def pair_id(symbol_a: str,symbol_b: str) -> str:
        return "__".join(sorted((str(symbol_a),str(symbol_b))))

    @staticmethod
    def _clean_prices(values: Iterable[Any]) -> list[float]:
        out=[]
        for value in values:
            number=_finite(value)
            if number is not None and number>0:
                out.append(number)
        return out

    @staticmethod
    def _structural_break(spread: Sequence[float]) -> tuple[Optional[float],str]:
        if len(spread)<20:
            return None,"INSUFFICIENT_DATA"
        cut=len(spread)//2
        left=list(spread[:cut])
        right=list(spread[cut:])
        if len(left)<5 or len(right)<5:
            return None,"INSUFFICIENT_DATA"
        pooled_std=math.sqrt(max(1e-18,(_variance(left)+_variance(right))/2.0))
        mean_shift=abs(_mean(right)-_mean(left))/pooled_std
        left_var=max(1e-18,_variance(left))
        right_var=max(1e-18,_variance(right))
        variance_shift=abs(math.log(right_var/left_var))
        score=mean_shift+0.5*variance_shift
        if score>=3.0:
            state="BREAK_LIKELY"
        elif score>=1.5:
            state="WATCH"
        else:
            state="STABLE"
        return score,state

    def analyze(
        self,
        *,
        symbol_a: str,
        symbol_b: str,
        prices_a: Sequence[Any],
        prices_b: Sequence[Any],
        sample_interval_sec: float,
        venue: str = "unknown",
        observed_at_ms: int = 0,
        direct_route_available: bool = False,
    ) -> tuple[PairDiagnostics,PairRelationshipCrystal]:
        a=self._clean_prices(prices_a)
        b=self._clean_prices(prices_b)
        n=min(len(a),len(b))
        reasons=[]
        if n<self.min_samples:
            reasons.append("insufficient_synchronized_history")
        a=a[-n:] if n else []
        b=b[-n:] if n else []

        log_a=[math.log(v) for v in a]
        log_b=[math.log(v) for v in b]
        corr=_correlation(_returns(log_a),_returns(log_b)) if n>=3 else None
        alpha,beta,hedge_r2=_ols(log_a,log_b) if n>=3 else (None,None,None)

        spread=[]
        if alpha is not None and beta is not None:
            spread=[ya-(alpha+beta*xb) for ya,xb in zip(log_a,log_b)]

        spread_mean=_mean(spread) if spread else None
        spread_std=math.sqrt(_variance(spread)) if len(spread)>=2 else None
        spread_last=spread[-1] if spread else None
        spread_z=None
        if spread_last is not None and spread_mean is not None and spread_std and spread_std>0:
            spread_z=(spread_last-spread_mean)/spread_std

        ar_alpha,phi,ar_r2=_ar1(spread)
        half_life=_half_life(phi,sample_interval_sec)
        kappa=None
        equilibrium=None
        if phi is not None and 0.0<phi<1.0:
            kappa=-math.log(phi)/max(1e-9,float(sample_interval_sec))
            if ar_alpha is not None and abs(1.0-phi)>1e-12:
                equilibrium=ar_alpha/(1.0-phi)

        break_score,break_state=self._structural_break(spread)

        if corr is None or abs(corr)<self.min_return_correlation:
            reasons.append("weak_return_relationship")
        if beta is None or beta<=0:
            reasons.append("invalid_or_nonpositive_hedge_ratio")
        if phi is None:
            reasons.append("mean_reversion_unavailable")
        elif not (0.0<phi<1.0):
            reasons.append("spread_not_mean_reverting_ar1")
        max_half_life=n*float(sample_interval_sec)*self.max_half_life_fraction if n else 0.0
        if half_life is None:
            reasons.append("half_life_unavailable")
        elif max_half_life>0 and half_life>max_half_life:
            reasons.append("half_life_too_long_for_window")
        if break_score is None:
            reasons.append("structural_break_unavailable")
        elif break_score>self.max_structural_break_score:
            reasons.append("structural_break_too_large")

        corr_score=min(1.0,abs(float(corr or 0.0)))
        fit_score=max(0.0,min(1.0,float(hedge_r2 or 0.0)))
        reversion_score=0.0
        if phi is not None and 0.0<phi<1.0:
            # Prefer meaningful but not implausibly instantaneous reversion.
            reversion_score=max(0.0,min(1.0,1.0-phi))
            reversion_score=min(1.0,reversion_score*10.0)
        half_life_score=0.0
        if half_life is not None and max_half_life>0:
            half_life_score=max(0.0,min(1.0,1.0-half_life/max_half_life))
        break_component=0.0 if break_score is None else max(0.0,min(1.0,1.0-break_score/self.max_structural_break_score))

        stability=(
            0.20*corr_score+
            0.20*fit_score+
            0.25*reversion_score+
            0.20*half_life_score+
            0.15*break_component
        )
        if stability<self.min_stability_score:
            reasons.append("stability_score_below_floor")

        eligible=(len(reasons)==0)
        pid=self.pair_id(symbol_a,symbol_b)
        diagnostics=PairDiagnostics(
            pair_id=pid,
            samples=n,
            correlation_returns=corr,
            hedge_alpha=alpha,
            hedge_ratio=beta,
            hedge_r2=hedge_r2,
            spread_mean=spread_mean,
            spread_std=spread_std,
            spread_last=spread_last,
            spread_zscore=spread_z,
            ar1_intercept=ar_alpha,
            ar1_phi=phi,
            ar1_r2=ar_r2,
            ou_mean_reversion_speed_per_sec=kappa,
            ou_equilibrium=equilibrium,
            half_life_seconds=half_life,
            structural_break_score=break_score,
            structural_break_state=break_state,
            stability_score=round(stability,6),
            eligible=eligible,
            rejection_reasons=tuple(sorted(set(reasons))),
        )
        payload={
            "pair_id":pid,
            "symbol_a":symbol_a,
            "symbol_b":symbol_b,
            "venue":venue,
            "observed_at_ms":int(observed_at_ms),
            "sample_interval_sec":float(sample_interval_sec),
            "samples":n,
            "diagnostics":diagnostics.to_dict(),
        }
        crystal=PairRelationshipCrystal(
            schema="hivenance_pair_relationship_crystal_v1",
            pair_id=pid,
            base_symbol=symbol_a,
            quote_symbol=symbol_b,
            venue=venue,
            observed_at_ms=int(observed_at_ms),
            lookback_seconds=int(max(0,n-1)*float(sample_interval_sec)),
            direct_route_available=bool(direct_route_available),
            relationship_method="log_price_ols_spread_ar1_ou_proxy_v1",
            hedge_ratio=beta,
            correlation=corr,
            spread_definition="log(A)-alpha-beta*log(B)",
            stationarity_score=round(reversion_score,6),
            mean_reversion_speed=kappa,
            half_life_seconds=half_life,
            structural_break_state=break_state,
            stability_score=round(stability,6),
            freshness_sec=0.0,
            evidence_root=_hash(payload),
            authority=RELATIVE_VALUE_AUTHORITY,
            execution_eligible=False,
        )
        return diagnostics,crystal
