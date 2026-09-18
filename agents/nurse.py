import time
from typing import Dict, Any


class NurseAgent:
    """Post-trade review agent (lightweight v1)."""

    def __init__(self, coordinator=None, review_interval_sec: int = 120):
        self.coordinator = coordinator
        self.review_interval_sec = review_interval_sec
        self._last_review_ts = 0.0
        self._last_summary = {}
        self._loss_streak = 0
        self._alpha_start_ts = time.time()
        self._last_strategy = None

    def review(self) -> Dict[str, Any]:
        now = time.time()
        if (now - self._last_review_ts) < self.review_interval_sec:
            return self._last_summary or {}
        self._last_review_ts = now

        summary = {
            "ts": int(now * 1000),
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "notes": "No trade history yet",
            "worker_loss_streak": self._loss_streak,
            "alpha_age_minutes": 0.0,
        }
        try:
            ds = self.coordinator.agents.get("data_store") if self.coordinator else None
            if ds:
                trades = ds.get_recent_trades(50) or []
                summary["trades"] = len(trades)
                if trades:
                    summary["notes"] = "Reviewing last 50 trades for drift and anomalies"
        except Exception:
            pass

        # Update loss streak from logging metrics if available
        try:
            log_agent = self.coordinator.agents.get("logging") if self.coordinator else None
            if log_agent and hasattr(log_agent, "metrics"):
                last = (log_agent.metrics or {}).get("last_trade_result")
                if last == "loss":
                    self._loss_streak += 1
                elif last == "win":
                    self._loss_streak = 0
            summary["worker_loss_streak"] = self._loss_streak
        except Exception:
            summary["worker_loss_streak"] = self._loss_streak

        # Alpha age: time since last strategy change (best-effort)
        try:
            strat = None
            if self.coordinator:
                gov = self.coordinator.get_shared_data("buzz.governance.decision")
                if isinstance(gov, dict) and gov.get("payload"):
                    strat = gov["payload"].get("strategy")
                if not strat:
                    council = self.coordinator.get_shared_data("buzz.council.decision")
                    if isinstance(council, dict) and council.get("payload"):
                        strat = council["payload"].get("winner") or council["payload"].get("direction")
            if strat and strat != self._last_strategy:
                self._alpha_start_ts = now
                self._last_strategy = strat
            alpha_age = max(0.0, (now - self._alpha_start_ts) / 60.0)
            summary["alpha_age_minutes"] = alpha_age
        except Exception:
            summary["alpha_age_minutes"] = max(0.0, (now - self._alpha_start_ts) / 60.0)

        summary["risk_metrics"] = {
            "worker_loss_streak": summary.get("worker_loss_streak", 0),
            "alpha_age_minutes": summary.get("alpha_age_minutes", 0.0),
        }

        self._last_summary = summary
        self._emit(summary)
        return summary

    def _emit(self, payload: Dict[str, Any]):
        if not self.coordinator:
            return
        try:
            self.coordinator.share_data("buzz.nurse.review", {
                "buzz": {"type": "buzz.nurse.review", "source": "NURSE", "ts": int(time.time() * 1000)},
                "payload": payload,
            })
        except Exception:
            pass
