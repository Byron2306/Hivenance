import time
import math
from typing import Dict, Any, List, Tuple, Optional


class RegimeOracle:
    """Regime detection using lightweight, explainable features with hysteresis."""

    def __init__(
        self,
        symbol: str,
        timeframes: Optional[List[str]] = None,
        min_duration_sec: int = 300,
        confirm_bars: int = 3,
        confidence_threshold: float = 0.15,
    ):
        self.symbol = symbol
        self.timeframes = timeframes or ["1m", "5m", "1h"]
        self.min_duration_sec = min_duration_sec
        self.confirm_bars = confirm_bars
        self.confidence_threshold = confidence_threshold
        self._last_label = None
        self._last_switch_ts = 0.0
        self._confirm_label = None
        self._confirm_count = 0

    def update(self, market_data, execution=None) -> Dict[str, Any]:
        """Compute current regime snapshot."""
        frames = self._fetch_frames(market_data)
        if not frames:
            return {
                "timestamp": int(time.time() * 1000),
                "symbol": self.symbol,
                "regime": self._last_label or "CHOP_RANGE",
                "confidence": 0.0,
                "features": {},
                "regime_change": False,
            }

        features = self._compute_features(frames, execution)
        scores = self._score_regimes(features)
        label, confidence = self._choose_label(scores)
        label, changed = self._apply_hysteresis(label, confidence)

        return {
            "timestamp": int(time.time() * 1000),
            "symbol": self.symbol,
            "regime": label,
            "confidence": confidence,
            "features": features,
            "scores": scores,
            "regime_change": changed,
        }

    def _fetch_frames(self, market_data) -> Dict[str, List[List[float]]]:
        """Return OHLCV frames per timeframe using ccxt client when available."""
        frames = {}
        if not market_data:
            return frames
        client = getattr(market_data, "client", None)
        if not client or not hasattr(client, "fetch_ohlcv"):
            # Fallback: build synthetic OHLCV from closes only
            try:
                times, closes = market_data.fetch_closes(200)
                vols = market_data.fetch_volumes(200) if hasattr(market_data, "fetch_volumes") else [0.0] * len(closes)
                ohlcv = []
                for i, c in enumerate(closes):
                    o = closes[i - 1] if i > 0 else c
                    h = max(o, c)
                    l = min(o, c)
                    v = vols[i] if i < len(vols) else 0.0
                    ts = times[i] if i < len(times) else int(time.time() * 1000)
                    ohlcv.append([ts, o, h, l, c, v])
                frames["1m"] = ohlcv[-200:]
            except Exception:
                pass
            return frames

        for tf in self.timeframes:
            try:
                ohlcv = client.fetch_ohlcv(self.symbol, timeframe=tf, limit=200)
                if ohlcv:
                    frames[tf] = ohlcv
            except Exception:
                continue
        return frames

    def _compute_features(self, frames: Dict[str, List[List[float]]], execution=None) -> Dict[str, float]:
        # Weight fast/slow timeframes
        fast = [tf for tf in frames if tf.endswith("m") and tf != "60m" and tf != "1h"]
        slow = [tf for tf in frames if tf.endswith("h") or tf.endswith("d")]
        if not fast:
            fast = list(frames.keys())
        w_fast = 0.6
        w_slow = 0.4 if slow else 0.0

        def agg(feature_fn) -> float:
            fvals = [feature_fn(frames[tf]) for tf in fast if frames.get(tf)]
            svals = [feature_fn(frames[tf]) for tf in slow if frames.get(tf)]
            fv = sum(fvals) / len(fvals) if fvals else 0.0
            sv = sum(svals) / len(svals) if svals else 0.0
            return fv * w_fast + sv * w_slow

        trend = agg(self._trend_score)
        vol = agg(self._vol_score)
        mean_cross = agg(self._mean_cross_score)
        bb_width = agg(self._bb_width_score)
        wick = agg(self._wick_score)
        spike = agg(self._spike_score)
        volume = agg(self._volume_score)

        spread_pct = self._spread_pct(execution)

        return {
            "trend": trend,
            "vol": vol,
            "spread": spread_pct,
            "mean_cross": mean_cross,
            "bb_width": bb_width,
            "wick": wick,
            "spike": spike,
            "volume": volume,
        }

    def _score_regimes(self, f: Dict[str, float]) -> Dict[str, float]:
        vol = f.get("vol", 0.0)
        wick = f.get("wick", 0.0)
        spread = f.get("spread", 0.0)
        spike = f.get("spike", 0.0)
        trend = f.get("trend", 0.0)
        mean_cross = f.get("mean_cross", 0.0)
        bb_width = f.get("bb_width", 0.0)
        volume = f.get("volume", 0.0)

        scores = {
            "PANIC_VOLATILE": 0.45 * vol + 0.25 * wick + 0.20 * spread + 0.10 * spike,
            "LOW_LIQUIDITY": 0.50 * spread + 0.35 * (1 - volume) + 0.15 * 0.0,
            "TREND_UP": 0.45 * trend + 0.25 * (1 - mean_cross) + 0.20 * (1 - bb_width) + 0.10 * 0.2,
            "TREND_DOWN": 0.45 * trend + 0.25 * (1 - mean_cross) + 0.20 * (1 - bb_width) + 0.10 * 0.2,
            "CHOP_RANGE": 0.45 * (1 - trend) + 0.35 * mean_cross + 0.20 * (1 - bb_width),
            "BREAKOUT": 0.40 * spike + 0.25 * bb_width + 0.20 * volume + 0.15 * trend,
        }
        return scores

    def _choose_label(self, scores: Dict[str, float]) -> Tuple[str, float]:
        if not scores:
            return "CHOP_RANGE", 0.0
        sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_label, top = sorted_scores[0]
        second = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0
        confidence = max(0.0, min(1.0, top - second))
        return top_label, confidence

    def _apply_hysteresis(self, label: str, confidence: float) -> Tuple[str, bool]:
        now = time.time()
        changed = False
        if self._last_label is None:
            self._last_label = label
            self._last_switch_ts = now
            return label, False

        if label == self._last_label:
            self._confirm_label = None
            self._confirm_count = 0
            return label, False

        if confidence < self.confidence_threshold:
            return self._last_label, False

        if self._confirm_label == label:
            self._confirm_count += 1
        else:
            self._confirm_label = label
            self._confirm_count = 1

        if self._confirm_count >= self.confirm_bars:
            if (now - self._last_switch_ts) >= self.min_duration_sec:
                self._last_label = label
                self._last_switch_ts = now
                changed = True
        return self._last_label, changed

    # ---- feature helpers ----
    def _trend_score(self, ohlcv: List[List[float]]) -> float:
        closes = [float(c[4]) for c in ohlcv][-60:]
        if len(closes) < 20:
            return 0.0
        sma20 = sum(closes[-20:]) / 20.0
        sma50 = sum(closes[-50:]) / 50.0 if len(closes) >= 50 else sma20
        slope = (sma20 - sma50) / max(1e-9, closes[-1])
        dir_cons = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i - 1]) / (len(closes) - 1)
        return self._clamp01(abs(slope) * 20.0 + abs(dir_cons - 0.5) * 2.0)

    def _vol_score(self, ohlcv: List[List[float]]) -> float:
        closes = [float(c[4]) for c in ohlcv][-60:]
        if len(closes) < 5:
            return 0.0
        rets = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
        std = math.sqrt(sum(r * r for r in rets) / max(1, len(rets)))
        return self._clamp01(std / 0.02)

    def _mean_cross_score(self, ohlcv: List[List[float]]) -> float:
        closes = [float(c[4]) for c in ohlcv][-60:]
        if len(closes) < 20:
            return 0.0
        sma20 = sum(closes[-20:]) / 20.0
        crosses = 0
        for c in closes[-20:]:
            crosses += 1 if (c - sma20) > 0 else 0
        ratio = abs(crosses - 10) / 10.0
        return self._clamp01(1.0 - ratio)

    def _bb_width_score(self, ohlcv: List[List[float]]) -> float:
        closes = [float(c[4]) for c in ohlcv][-40:]
        if len(closes) < 20:
            return 0.0
        mean = sum(closes) / len(closes)
        var = sum((c - mean) ** 2 for c in closes) / len(closes)
        std = math.sqrt(var)
        width = (std * 4) / max(1e-9, mean)
        return self._clamp01(width / 0.05)

    def _wick_score(self, ohlcv: List[List[float]]) -> float:
        if not ohlcv:
            return 0.0
        vals = []
        for c in ohlcv[-30:]:
            o, h, l, cl = float(c[1]), float(c[2]), float(c[3]), float(c[4])
            body = abs(cl - o)
            wick = max(1e-9, (h - l)) / max(1e-9, (body + 1e-6))
            vals.append(wick)
        return self._clamp01(sum(vals) / len(vals) / 4.0 if vals else 0.0)

    def _spike_score(self, ohlcv: List[List[float]]) -> float:
        closes = [float(c[4]) for c in ohlcv][-30:]
        if len(closes) < 5:
            return 0.0
        rets = [abs(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
        spike = max(rets) if rets else 0.0
        return self._clamp01(spike / 0.03)

    def _volume_score(self, ohlcv: List[List[float]]) -> float:
        vols = [float(c[5]) for c in ohlcv][-30:]
        if not vols:
            return 0.0
        v = vols[-1]
        avg = sum(vols) / len(vols)
        return self._clamp01(v / max(1e-9, avg))

    def _spread_pct(self, execution) -> float:
        try:
            client = getattr(execution, "client", None) if execution else None
            if client and hasattr(client, "fetch_ticker"):
                t = client.fetch_ticker(self.symbol)
                bid = t.get("bid")
                ask = t.get("ask")
                if bid and ask and bid > 0:
                    return self._clamp01((ask - bid) / bid / 0.01)
        except Exception:
            pass
        return 0.0

    def _clamp01(self, v: float) -> float:
        return max(0.0, min(1.0, float(v)))
