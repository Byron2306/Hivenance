import time
import math
from typing import List, Optional, Dict, Any

from agents.strategy import sma, rsi
from agents.market_data import TrendAnalysis


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

class RSI2Worker(BaseWorker):
    name = "WORKER-RSI2"

    def __init__(self, window: int = 2, oversold: int = 10, overbought: int = 90):
        self.window = window
        self.oversold = oversold
        self.overbought = overbought

    def propose(self, closes, volumes=None, latest_price=0.0):
        rsi_vals = rsi(closes, self.window)
        if len(rsi_vals) < 2 or rsi_vals[-1] is None:
            return self._proposal("HOLD", 0.0, "No RSI2 data yet")
        curr = rsi_vals[-1]
        
        # Larry Connors RSI-2 strategy logic:
        # Buy when RSI(2) < 10
        # Sell when RSI(2) > 90
        
        strength = 0.0
        if curr <= self.oversold:
            strength = min(1.0, (self.oversold - curr) / max(1e-9, self.oversold) + 0.5)
            return self._proposal("BUY", strength, f"RSI2 oversold {curr:.1f}")
        if curr >= self.overbought:
            strength = min(1.0, (curr - self.overbought) / max(1e-9, 100 - self.overbought) + 0.5)
            return self._proposal("SELL", strength, f"RSI2 overbought {curr:.1f}")
            
        return self._proposal("HOLD", 0.0, f"RSI2 neutral {curr:.1f}")

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


class BollingerWorker(BaseWorker):
    name = "WORKER-BOLLINGER"

    def __init__(self, window: int = 20, num_std: float = 2.0):
        self.window = window
        self.num_std = num_std

    def propose(self, closes, volumes=None, latest_price=0.0):
        if len(closes or []) < self.window + 2:
            return self._proposal("HOLD", 0.0, "Not enough candles for Bollinger")
        window = [float(x) for x in closes[-self.window:]]
        mid = sum(window) / self.window
        variance = sum((x - mid) ** 2 for x in window) / self.window
        std = math.sqrt(max(0.0, variance))
        upper = mid + self.num_std * std
        lower = mid - self.num_std * std
        last = float(closes[-1])
        band_width = max(1e-9, upper - lower)
        pos = (last - lower) / band_width
        volume_surge = 0.0
        try:
            volume_surge = float(TrendAnalysis.volume_surge(volumes or []))
        except Exception:
            volume_surge = 0.0
        if last <= lower:
            strength = min(1.0, (lower - last) / max(1e-9, band_width) + 0.55)
            return self._proposal("BUY", strength, f"Bollinger lower band touch pos={pos:.2f}", lower, mid, upper)
        if last >= upper:
            strength = min(1.0, (last - upper) / max(1e-9, band_width) + 0.55)
            return self._proposal("SELL", strength, f"Bollinger upper band touch pos={pos:.2f}", lower, mid, upper)
        if pos < 0.2 and volume_surge < 1.5:
            return self._proposal("BUY", min(0.65, 0.2 - pos + 0.35), f"Bollinger mean-reversion setup pos={pos:.2f}", lower, mid, upper)
        if pos > 0.8 and volume_surge < 1.5:
            return self._proposal("SELL", min(0.65, pos - 0.8 + 0.35), f"Bollinger mean-reversion fade pos={pos:.2f}", lower, mid, upper)
        squeeze = min(1.0, band_width / max(1e-9, mid))
        return self._proposal("HOLD", max(0.0, min(1.0, 1.0 - squeeze * 20.0)), "Bollinger neutral", lower, mid, upper)

    def _proposal(self, action, strength, note, lower=None, mid=None, upper=None):
        return {
            "strategy": self.name,
            "action": action,
            "signal_strength": strength,
            "edge": strength,
            "risk": 0.45,
            "invalidation": "Band walk with rising volume" if action in ("BUY", "SELL") else None,
            "notes": note,
            "bands": {"lower": lower, "mid": mid, "upper": upper},
            "signal_id": self._signal_id(),
            "ts": int(time.time() * 1000),
        }


class SupertrendWorker(BaseWorker):
    name = "WORKER-SUPERTREND"

    def __init__(self, atr_window: int = 10, multiplier: float = 3.0):
        self.atr_window = atr_window
        self.multiplier = multiplier

    def propose(self, closes, volumes=None, latest_price=0.0):
        if len(closes or []) < self.atr_window + 3:
            return self._proposal("HOLD", 0.0, "Not enough candles for Supertrend")
        vals = [float(x) for x in closes]
        atr = self._atr(vals)
        if atr <= 0:
            return self._proposal("HOLD", 0.0, "Supertrend ATR unavailable")
        prev = vals[-2]
        last = vals[-1]
        basis = sum(vals[-self.atr_window:]) / self.atr_window
        upper = basis + self.multiplier * atr
        lower = basis - self.multiplier * atr
        trend_up = last > basis and last > prev
        trend_down = last < basis and last < prev
        distance = abs(last - basis) / max(1e-9, self.multiplier * atr)
        strength = max(0.0, min(1.0, distance))
        if trend_up and last > upper:
            return self._proposal("BUY", max(0.6, strength), f"Supertrend bullish break above {upper:.6f}", upper, lower, basis)
        if trend_down and last < lower:
            return self._proposal("SELL", max(0.6, strength), f"Supertrend bearish break below {lower:.6f}", upper, lower, basis)
        if trend_up:
            return self._proposal("BUY", min(0.75, max(0.45, strength)), "Supertrend bullish continuation", upper, lower, basis)
        if trend_down:
            return self._proposal("SELL", min(0.75, max(0.45, strength)), "Supertrend bearish continuation", upper, lower, basis)
        return self._proposal("HOLD", strength * 0.5, "Supertrend neutral", upper, lower, basis)

    def _atr(self, closes: List[float]) -> float:
        changes = [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))]
        window = changes[-self.atr_window:]
        return sum(window) / len(window) if window else 0.0

    def _proposal(self, action, strength, note, upper=None, lower=None, basis=None):
        return {
            "strategy": self.name,
            "action": action,
            "signal_strength": strength,
            "edge": strength,
            "risk": 0.55,
            "invalidation": "Close crosses Supertrend basis" if action in ("BUY", "SELL") else None,
            "notes": note,
            "supertrend": {"upper": upper, "lower": lower, "basis": basis},
            "signal_id": self._signal_id(),
            "ts": int(time.time() * 1000),
        }


class VolatilityExpansionWorker(BaseWorker):
    name = "WORKER-VOL-EXPANSION"

    def __init__(
        self,
        min_expansion: float = 1.15,
        min_volume_surge: float = 0.85,
        min_return: float = 0.002,
        max_drawdown: float = 0.08,
    ):
        self.min_expansion = min_expansion
        self.min_volume_surge = min_volume_surge
        self.min_return = min_return
        self.max_drawdown = max_drawdown

    def propose(self, closes, volumes=None, latest_price=0.0):
        if len(closes or []) < 50:
            return self._proposal("HOLD", 0.0, "Not enough candles for volatility expansion")
        ctx = TrendAnalysis.market_context(closes, volumes or [])
        expansion = float(ctx.get("volatility_expansion") or 0.0)
        volume_surge = float(ctx.get("volume_surge") or 0.0)
        ret_5 = float(ctx.get("return_5") or 0.0)
        drawdown = float(ctx.get("max_drawdown") or 0.0)

        exp_score = min(1.0, max(0.0, (expansion - 1.0) / max(0.01, self.min_expansion)))
        vol_score = min(1.0, volume_surge / max(0.01, self.min_volume_surge))
        ret_score = min(1.0, abs(ret_5) / max(1e-9, self.min_return * 4.0))
        risk_penalty = min(0.45, drawdown / max(1e-9, self.max_drawdown) * 0.25)
        strength = max(0.0, min(1.0, 0.40 * exp_score + 0.30 * vol_score + 0.30 * ret_score - risk_penalty))

        if expansion >= self.min_expansion and volume_surge >= self.min_volume_surge:
            if ret_5 >= self.min_return and drawdown <= self.max_drawdown:
                return self._proposal("BUY", max(0.55, strength), f"Volatility expansion up {ret_5*100:.2f}%")
            if ret_5 <= -self.min_return:
                return self._proposal("SELL", max(0.55, strength), f"Volatility expansion down {ret_5*100:.2f}%")
        return self._proposal("HOLD", strength, "Volatility not clean enough")

    def _proposal(self, action, strength, note):
        return {
            "strategy": self.name,
            "action": action,
            "signal_strength": strength,
            "edge": strength,
            "risk": 0.7,
            "invalidation": "Volume fades or quote quality deteriorates",
            "notes": note,
            "signal_id": self._signal_id(),
            "ts": int(time.time() * 1000),
        }

class ExitRiskWorker(BaseWorker):
    name = "WORKER-EXIT-RISK"

    def __init__(self, hard_stop_pct: float = 0.025, take_profit_pct: float = 0.04, trailing_window: int = 12):
        self.hard_stop_pct = hard_stop_pct
        self.take_profit_pct = take_profit_pct
        self.trailing_window = trailing_window

    def propose(self, closes, volumes=None, latest_price=0.0):
        if len(closes or []) < max(20, self.trailing_window + 2):
            return self._proposal("HOLD", 0.0, "Not enough candles for exit risk")
        ret_5 = TrendAnalysis.short_return(closes, 5)
        ret_15 = TrendAnalysis.short_return(closes, 15)
        drawdown = TrendAnalysis.max_drawdown(closes, self.trailing_window)
        vol_surge = TrendAnalysis.volume_surge(volumes or [])
        strength = min(1.0, max(abs(ret_5), drawdown) / max(1e-9, self.hard_stop_pct))

        if ret_5 <= -self.hard_stop_pct or drawdown >= self.hard_stop_pct:
            return self._proposal("SELL", max(0.65, strength), f"Exit risk stop drawdown {drawdown*100:.2f}%")
        if ret_15 >= self.take_profit_pct and ret_5 < 0 and vol_surge >= 0.8:
            return self._proposal("SELL", max(0.6, strength), f"Profit fade after {ret_15*100:.2f}% move")
        return self._proposal("HOLD", strength * 0.5, "No exit risk")

    def _proposal(self, action, strength, note):
        return {
            "strategy": self.name,
            "action": action,
            "signal_strength": strength,
            "edge": strength,
            "risk": 0.35,
            "invalidation": None,
            "notes": note,
            "signal_id": self._signal_id(),
            "ts": int(time.time() * 1000),
        }


class ProtectionWorker(BaseWorker):
    name = "WORKER-PROTECTION"

    def __init__(self, warn_drawdown_pct: float = 0.035, block_drawdown_pct: float = 0.05):
        self.warn_drawdown_pct = warn_drawdown_pct
        self.block_drawdown_pct = block_drawdown_pct

    def propose(self, closes, volumes=None, latest_price=0.0):
        if len(closes or []) < 2:
            return self._proposal("HOLD", 0.0, "Waiting for enough candles for protection checks", "WARMING_UP")
        drawdown = TrendAnalysis.max_drawdown(closes, min(20, len(closes)))
        strength = min(1.0, max(0.0, drawdown / max(1e-9, self.block_drawdown_pct)))
        if drawdown >= self.block_drawdown_pct:
            return self._proposal("HOLD", strength, f"Protection block drawdown {drawdown*100:.2f}%", "BLOCK")
        if drawdown >= self.warn_drawdown_pct:
            return self._proposal("HOLD", strength, f"Protection warning drawdown {drawdown*100:.2f}%", "WARN")
        return self._proposal("HOLD", strength, f"Protection clear drawdown {drawdown*100:.2f}%", "CLEAR")

    def _proposal(self, action, strength, note, state="CLEAR"):
        max_position_pct = 0.0 if state == "BLOCK" else (0.02 if state == "WARN" else None)
        return {
            "strategy": self.name,
            "action": action,
            "signal_strength": strength,
            "edge": 0.0,
            "risk": min(1.0, max(0.0, strength)),
            "invalidation": None,
            "notes": note,
            "protection": {
                "state": state,
                "entry_allowed": state != "BLOCK",
                "max_position_pct": max_position_pct,
                "cooldown_secs": 300 if state == "BLOCK" else (120 if state == "WARN" else 0),
            },
            "signal_id": self._signal_id(),
            "ts": int(time.time() * 1000),
        }


class LatencyTrackerWorker(BaseWorker):
    name = "WORKER-LATENCY"

    def __init__(self, warn_latency_ms: int = 1500, block_latency_ms: int = 5000):
        self.signal_timestamps = {}  # signal_id -> ts
        self.last_latency_ms = 0
        self.warn_latency_ms = warn_latency_ms
        self.block_latency_ms = block_latency_ms

    def propose(self, closes, volumes=None, latest_price=0.0):
        risk = min(1.0, max(0.0, float(self.last_latency_ms or 0) / max(1.0, float(self.block_latency_ms))))
        if self.last_latency_ms >= self.block_latency_ms:
            state = "BLOCK"
        elif self.last_latency_ms >= self.warn_latency_ms:
            state = "WARN"
        else:
            state = "CLEAR"
        return self._proposal("HOLD", risk, f"Latency {int(self.last_latency_ms or 0)}ms", state)

    def record_signal(self, signal_id: str):
        if signal_id:
            self.signal_timestamps[signal_id] = time.time()

    def record_execution(self, signal_id: str):
        if signal_id in self.signal_timestamps:
            latency = time.time() - self.signal_timestamps.pop(signal_id)
            self.last_latency_ms = int(latency * 1000)
            return latency
        return None

    def _proposal(self, action, strength, note, state="CLEAR"):
        return {
            "strategy": self.name,
            "action": action,
            "signal_strength": strength,
            "edge": strength,
            "risk": min(1.0, max(0.0, strength)),
            "invalidation": None,
            "notes": note,
            "latency": {
                "state": state,
                "last_latency_ms": int(self.last_latency_ms or 0),
                "warn_latency_ms": self.warn_latency_ms,
                "block_latency_ms": self.block_latency_ms,
            },
            "signal_id": self._signal_id(),
            "ts": int(time.time() * 1000),
        }
