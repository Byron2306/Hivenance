import time
from typing import List, Dict, Any, Tuple, Optional


class StrategyCouncil:
    """Collects and normalizes strategy proposals."""

    def __init__(self, coordinator=None):
        self.coordinator = coordinator
        self._last_pack = None

    def collect(
        self,
        workers: List[Any],
        closes: List[float],
        volumes: List[float],
        latest_price: float,
        symbol: str,
        regime_snapshot: Optional[Dict[str, Any]] = None,
        perf_by_worker: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        proposals = []
        ts_ms = int(time.time() * 1000)
        for w in workers:
            try:
                p = w.propose(closes, volumes, latest_price)
                if not p:
                    p = {
                        "strategy": getattr(w, "name", "WORKER"),
                        "action": "HOLD",
                        "signal_strength": 0.0,
                        "edge": 0.0,
                        "risk": 0.5,
                        "notes": "No signal",
                        "signal_id": f"sig-{getattr(w, 'name', 'WORKER')}-{ts_ms}",
                    }
                p.setdefault("symbol", symbol)
                p.setdefault("ts", ts_ms)
                proposals.append(p)
                self._emit_proposal(p)
            except Exception:
                # still emit a placeholder so UI remains complete
                p = {
                    "strategy": getattr(w, "name", "WORKER"),
                    "action": "HOLD",
                    "signal_strength": 0.0,
                    "edge": 0.0,
                    "risk": 0.5,
                    "notes": "Proposal error",
                    "signal_id": f"sig-{getattr(w, 'name', 'WORKER')}-{ts_ms}",
                    "symbol": symbol,
                    "ts": ts_ms,
                }
                proposals.append(p)
                self._emit_proposal(p)
        pack = {
            "symbol": symbol,
            "count": len(proposals),
            "proposals": proposals,
            "regime": (regime_snapshot or {}).get("regime"),
            "regime_confidence": (regime_snapshot or {}).get("confidence"),
            "ts": ts_ms,
        }
        # SVS decision object
        decision = self._svs_decision(proposals, regime_snapshot or {}, perf_by_worker or {}, symbol, ts_ms)
        if decision:
            pack["decision"] = decision
            self._emit_decision(decision)
        self._emit_pack(pack)
        self._last_pack = pack
        return proposals, pack

    def _svs_decision(
        self,
        proposals: List[Dict[str, Any]],
        regime_snapshot: Dict[str, Any],
        perf_by_worker: Dict[str, Dict[str, Any]],
        symbol: str,
        ts_ms: int,
    ) -> Optional[Dict[str, Any]]:
        if not proposals:
            return None

        # Normalize regime
        regime_raw = (regime_snapshot or {}).get("regime") or "RANGING"
        r = str(regime_raw).upper()
        if "CHAOTIC" in r or "PANIC" in r or "ILLIQ" in r:
            regime_name = "CHAOTIC"
        elif "TREND" in r or "BREAKOUT" in r:
            regime_name = "TRENDING"
        elif "CHOP" in r or "RANGE" in r or "MEAN" in r:
            regime_name = "RANGING"
        else:
            regime_name = "RANGING"

        align = {
            "WORKER-RSI": {"TRENDING": 0.6, "RANGING": 1.0, "CHAOTIC": 0.2},
            "WORKER-BREAKOUT": {"TRENDING": 1.0, "RANGING": 0.5, "CHAOTIC": 0.2},
            "WORKER-MOMENTUM": {"TRENDING": 1.0, "RANGING": 0.4, "CHAOTIC": 0.1},
            "WORKER-SMA": {"TRENDING": 0.9, "RANGING": 0.6, "CHAOTIC": 0.2},
        }

        contributors = []
        buy_scores = []
        sell_scores = []
        distinct = set()

        for p in proposals:
            worker = p.get("strategy") or "WORKER"
            side = (p.get("action") or "HOLD").upper()
            if side not in ("BUY", "SELL"):
                continue
            distinct.add(worker)
            c = max(0.0, min(1.0, float(p.get("signal_strength") or 0.0)))
            a = align.get(worker, {}).get(regime_name, 0.6)
            perf = perf_by_worker.get(worker) if perf_by_worker else None
            if perf:
                try:
                    avg_r = float(perf.get("avg_r_multiple") or 0.0)
                    dd = float(perf.get("drawdown") or 0.0)
                    pen = float(perf.get("recent_penalties") or 0.0)
                    pwt = max(0.5, min(1.2, 0.8 + (avg_r * 2.0) - (dd * 1.5) - (pen * 0.05)))
                except Exception:
                    pwt = 1.0
            else:
                pwt = 1.0
            s = c * a * pwt
            contributors.append({
                "worker": worker,
                "side": side,
                "raw_conf": c,
                "align": a,
                "perf": pwt,
                "score": s,
            })
            if side == "BUY":
                buy_scores.append(s)
            else:
                sell_scores.append(s)

        if not contributors:
            return None

        s_buy = sum(buy_scores)
        s_sell = sum(sell_scores)
        s_total = s_buy + s_sell
        direction = "BUY" if s_buy > s_sell else "SELL"
        s_dir = max(s_buy, s_sell)
        margin = (s_dir - min(s_buy, s_sell)) / max(1e-9, s_total)
        max_score_possible = 3.6
        score = max(0.0, min(1.0, s_dir / max_score_possible))

        # Recommendation bands
        if score < 0.55:
            recommendation = "REJECT"
        elif score < 0.70:
            recommendation = "ALLOW_SMALL"
        elif score < 0.82:
            recommendation = "ALLOW_NORMAL"
        else:
            recommendation = "ALLOW_SCALE"
        if regime_name == "CHAOTIC":
            recommendation = "ALLOW_SMALL" if recommendation != "REJECT" else recommendation

        return {
            "type": "COUNCIL_DECISION",
            "ts": ts_ms,
            "symbol": symbol,
            "direction": direction,
            "score": score,
            "margin": margin,
            "distinct_workers": len(distinct),
            "regime": {
                "name": regime_name,
                "confidence": float((regime_snapshot or {}).get("confidence") or 0.0),
            },
            "contributors": contributors,
            "recommendation": recommendation,
            "risk_hints": {
                "max_position_pct": 0.06 if regime_name != "CHAOTIC" else 0.02,
                "max_slippage_bps": 20,
                "order_type": "LIMIT",
                "ttl_secs": 120,
                "cooldown_secs": 90,
            },
            "risk": {
                "metrics": {
                    "worker_loss_streak": 0,
                    "alpha_age_minutes": 0,
                }
            },
            "request_id": f"dec-{ts_ms}",
        }

    def _emit_proposal(self, proposal: Dict[str, Any]):
        if not self.coordinator:
            return
        try:
            self.coordinator.share_data("buzz.strategy.proposal", {
                "buzz": {"type": "buzz.strategy.proposal", "source": proposal.get("strategy", "COUNCIL"), "ts": int(time.time() * 1000)},
                "payload": proposal,
            })
        except Exception:
            pass

    def _emit_pack(self, pack: Dict[str, Any]):
        if not self.coordinator:
            return
        try:
            self.coordinator.share_data("buzz.council.pack", {
                "buzz": {"type": "buzz.council.pack", "source": "COUNCIL", "ts": int(time.time() * 1000)},
                "payload": pack,
            })
        except Exception:
            pass

    def _emit_decision(self, decision: Dict[str, Any]):
        if not self.coordinator:
            return
        try:
            self.coordinator.share_data("buzz.council.decision", {
                "buzz": {"type": "buzz.council.decision", "source": "COUNCIL", "ts": int(time.time() * 1000)},
                "payload": decision,
            })
        except Exception:
            pass
