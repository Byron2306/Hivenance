import time
import math
from typing import List, Optional, Dict, Any

from agents.strategy import sma, rsi


class BaseWorker:
    name = "WORKER"

    def propose(self, closes: List[float], volumes: Optional[List[float]] = None, latest_price: float = 0.0) -> Dict[str, Any]:
        raise NotImplementedError

    def _signal_id(self) -> str:
        return f"sig-{self.name}-{int(time.time()*1000)}"


class SMAWorker(BaseWorker):
    name = "WORKER-SMA"

    def __init__(self, fast: int = 20, slow: int = 50):
        self.fast = fast
        self.slow = slow

    def propose(self, closes, volumes=None, latest_price=0.0):
        if len(closes) < self.slow + 2:
            return self._proposal("HOLD", 0.0, "Not enough candles")
        fast_s = sma(closes, self.fast)
        slow_s = sma(closes, self.slow)
        f1, f2 = fast_s[-2], fast_s[-1]
        s1, s2 = slow_s[-2], slow_s[-1]
        if f1 is None or f2 is None or s1 is None or s2 is None:
            return self._proposal("HOLD", 0.0, "Insufficient SMA data")
        crossed_up = (f1 <= s1) and (f2 > s2)
        crossed_down = (f1 >= s1) and (f2 < s2)
        delta = abs(f2 - s2) / max(1e-9, latest_price) if latest_price else 0.0
        base_strength = min(1.0, delta * 25.0)
        if crossed_up:
            return self._proposal("BUY", base_strength, "SMA bullish crossover")
        if crossed_down:
            return self._proposal("SELL", base_strength, "SMA bearish crossover")
        # Use proximity between SMAs to show setup strength even when HOLD
        return self._proposal("HOLD", base_strength, "No crossover")

    def _proposal(self, action, strength, note):
        return {
            "strategy": self.name,
            "action": action,
            "signal_strength": strength,
            "edge": strength,
            "risk": 0.5,
            "invalidation": None,
            "notes": note,
            "signal_id": self._signal_id(),
            "ts": int(time.time() * 1000),
        }


class RSIWorker(BaseWorker):
    name = "WORKER-RSI"

    def __init__(self, window: int = 14, oversold: int = 30, overbought: int = 70):
        self.window = window
        self.oversold = oversold
        self.overbought = overbought

    def propose(self, closes, volumes=None, latest_price=0.0):
        rsi_vals = rsi(closes, self.window)
        if len(rsi_vals) < 2 or rsi_vals[-1] is None:
            return self._proposal("HOLD", 0.0, "No RSI data yet")
        curr = rsi_vals[-1]
        # strength is higher when closer to oversold/overbought bands
        dist = min(abs(curr - self.oversold), abs(curr - self.overbought))
        base_strength = max(0.0, min(1.0, 1.0 - (dist / 30.0)))
        if curr <= self.oversold:
            return self._proposal("BUY", max(base_strength, 0.6), f"RSI oversold {curr:.1f}")
        if curr >= self.overbought:
            return self._proposal("SELL", max(base_strength, 0.6), f"RSI overbought {curr:.1f}")
        return self._proposal("HOLD", base_strength, f"RSI neutral {curr:.1f}")

    def _proposal(self, action, strength, note):
        return {
            "strategy": self.name,
            "action": action,
            "signal_strength": strength,
            "edge": strength,
            "risk": 0.4,
            "invalidation": None,
            "notes": note,
            "signal_id": self._signal_id(),
            "ts": int(time.time() * 1000),
        }


class BreakoutWorker(BaseWorker):
    name = "WORKER-BREAKOUT"

    def __init__(self, lookback: int = 20):
        self.lookback = lookback

    def propose(self, closes, volumes=None, latest_price=0.0):
        if len(closes) < self.lookback + 1:
            return self._proposal("HOLD", 0.0, "Not enough candles for breakout")
        window = closes[-(self.lookback + 1):-1]
        high = max(window)
        low = min(window)
        last = closes[-1]
        span = max(1e-9, high - low)
        proximity = 1.0 - min(1.0, min(abs(high - last), abs(last - low)) / span)
        base_strength = max(0.0, min(1.0, proximity))
        if last > high:
            strength = min(1.0, (last - high) / max(1e-9, last) * 50.0)
            return self._proposal("BUY", max(base_strength, strength), "Breakout above range")
        if last < low:
            strength = min(1.0, (low - last) / max(1e-9, last) * 50.0)
            return self._proposal("SELL", max(base_strength, strength), "Breakdown below range")
        return self._proposal("HOLD", base_strength, "No breakout")

    def _proposal(self, action, strength, note):
        return {
            "strategy": self.name,
            "action": action,
            "signal_strength": strength,
            "edge": strength,
            "risk": 0.6,
            "invalidation": None,
            "notes": note,
            "signal_id": self._signal_id(),
            "ts": int(time.time() * 1000),
        }


class MomentumWorker(BaseWorker):
    name = "WORKER-MOMENTUM"

    def __init__(self, lookback: int = 5, threshold: float = 0.003):
        self.lookback = lookback
        self.threshold = threshold

    def propose(self, closes, volumes=None, latest_price=0.0):
        if len(closes) < self.lookback + 1:
            return self._proposal("HOLD", 0.0, "Not enough candles for momentum")
        start = closes[-(self.lookback + 1)]
        end = closes[-1]
        ret = (end - start) / max(1e-9, start)
        strength = min(1.0, abs(ret) / self.threshold) if self.threshold > 0 else 0.0
        if ret > self.threshold:
            return self._proposal("BUY", strength, f"Momentum up {ret*100:.2f}%")
        if ret < -self.threshold:
            return self._proposal("SELL", strength, f"Momentum down {ret*100:.2f}%")
        return self._proposal("HOLD", strength, "Momentum flat")

    def _proposal(self, action, strength, note):
        return {
            "strategy": self.name,
            "action": action,
            "signal_strength": strength,
            "edge": strength,
            "risk": 0.5,
            "invalidation": None,
            "notes": note,
            "signal_id": self._signal_id(),
            "ts": int(time.time() * 1000),
        }
