import time
import json
import sqlite3
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


    def review_rotation_lab(self, database: str, run_id: str | None = None) -> Dict[str, Any]:
        """Read-only post-run learning review for the paper rotation lab.

        The method never changes weights, crystals, order authority or production
        state. It reports candidate learning evidence for human/research review.
        """
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
        try:
            if run_id is None:
                row = conn.execute(
                    "SELECT run_id,status,started_ts,ended_ts,learning_authority "
                    "FROM rotation_runs ORDER BY started_ts DESC LIMIT 1"
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT run_id,status,started_ts,ended_ts,learning_authority "
                    "FROM rotation_runs WHERE run_id=?",
                    (run_id,),
                ).fetchone()
            if not row:
                return {
                    "schema": "hivenance_nurse_rotation_review_v1",
                    "status": "NO_ROTATION_RUN",
                    "authority": "read_only_learning_review",
                }

            rid = str(row["run_id"])
            legs = conn.execute(
                "SELECT mutation_id,symbol,net_pnl_usd,net_return_bps,duration_sec,"
                "entry_regime,exit_reason,entry_context_json "
                "FROM rotation_legs WHERE run_id=? AND status='CLOSED'",
                (rid,),
            ).fetchall()
            crystals = conn.execute(
                "SELECT mutation_id,crystal_family,symbol,regime,evidence_strength,"
                "net_return_bps,duration_sec,payload_json "
                "FROM rotation_learning_crystals WHERE run_id=?",
                (rid,),
            ).fetchall()
            decisions = conn.execute(
                "SELECT mutation_id,action,COUNT(*) AS n "
                "FROM rotation_decisions WHERE run_id=? "
                "GROUP BY mutation_id,action",
                (rid,),
            ).fetchall()

            by_mutation: Dict[str, Dict[str, Any]] = {}
            by_regime: Dict[str, Dict[str, Any]] = {}
            by_symbol: Dict[str, Dict[str, Any]] = {}
            rebound = {"samples": 0, "net_bps": 0.0, "wins": 0}
            non_rebound = {"samples": 0, "net_bps": 0.0, "wins": 0}

            def bucket(target: Dict[str, Dict[str, Any]], key: str) -> Dict[str, Any]:
                return target.setdefault(key, {
                    "samples": 0,
                    "wins": 0,
                    "net_pnl_usd": 0.0,
                    "net_return_bps_sum": 0.0,
                    "duration_sec_sum": 0.0,
                })

            for leg in legs:
                net = float(leg["net_pnl_usd"] or 0.0)
                net_bps = float(leg["net_return_bps"] or 0.0)
                duration = float(leg["duration_sec"] or 0.0)
                for target, key in (
                    (by_mutation, str(leg["mutation_id"] or "unknown")),
                    (by_regime, str(leg["entry_regime"] or "unknown")),
                    (by_symbol, str(leg["symbol"] or "unknown")),
                ):
                    b = bucket(target, key)
                    b["samples"] += 1
                    b["wins"] += 1 if net > 0 else 0
                    b["net_pnl_usd"] += net
                    b["net_return_bps_sum"] += net_bps
                    b["duration_sec_sum"] += duration
                try:
                    payload = json.loads(leg["entry_context_json"] or "{}")
                except Exception:
                    payload = {}
                was_rebound = bool((payload.get("score") or {}).get("rebound"))
                rb = rebound if was_rebound else non_rebound
                rb["samples"] += 1
                rb["net_bps"] += net_bps
                rb["wins"] += 1 if net > 0 else 0

            def finish(groups: Dict[str, Dict[str, Any]]) -> list[Dict[str, Any]]:
                out = []
                for key, value in groups.items():
                    n = max(1, int(value["samples"]))
                    out.append({
                        "key": key,
                        "samples": int(value["samples"]),
                        "wins": int(value["wins"]),
                        "win_rate": round(float(value["wins"]) / n, 6),
                        "net_pnl_usd": round(float(value["net_pnl_usd"]), 6),
                        "mean_net_return_bps": round(float(value["net_return_bps_sum"]) / n, 6),
                        "mean_duration_sec": round(float(value["duration_sec_sum"]) / n, 3),
                    })
                return sorted(out, key=lambda item: (
                    float(item["mean_net_return_bps"]),
                    int(item["samples"]),
                ), reverse=True)

            decision_counts: Dict[str, Dict[str, int]] = {}
            for item in decisions:
                decision_counts.setdefault(str(item["mutation_id"]), {})[
                    str(item["action"])
                ] = int(item["n"])

            positive = sum(1 for item in crystals if str(item["crystal_family"]) == "positive_capability")
            negative = sum(1 for item in crystals if str(item["crystal_family"]) == "negative_capability")
            strong = [
                {
                    "mutation_id": str(item["mutation_id"]),
                    "family": str(item["crystal_family"]),
                    "symbol": str(item["symbol"]),
                    "regime": str(item["regime"]),
                    "evidence_strength": round(float(item["evidence_strength"] or 0.0), 6),
                    "net_return_bps": round(float(item["net_return_bps"] or 0.0), 6),
                    "duration_sec": round(float(item["duration_sec"] or 0.0), 3),
                }
                for item in crystals
                if float(item["evidence_strength"] or 0.0) >= 0.5
            ]
            strong.sort(key=lambda item: float(item["evidence_strength"]), reverse=True)

            def rebound_summary(value: Dict[str, Any]) -> Dict[str, Any]:
                n = max(1, int(value["samples"]))
                return {
                    "samples": int(value["samples"]),
                    "win_rate": round(float(value["wins"]) / n, 6),
                    "mean_net_return_bps": round(float(value["net_bps"]) / n, 6),
                }

            return {
                "schema": "hivenance_nurse_rotation_review_v1",
                "authority": "read_only_learning_review",
                "learning_authority": str(row["learning_authority"] or ""),
                "run_id": rid,
                "run_status": str(row["status"]),
                "closed_legs": len(legs),
                "candidate_crystals": len(crystals),
                "positive_candidate_crystals": positive,
                "negative_candidate_crystals": negative,
                "by_mutation": finish(by_mutation),
                "by_regime": finish(by_regime),
                "by_symbol": finish(by_symbol),
                "rebound_after_retrace": rebound_summary(rebound),
                "non_rebound": rebound_summary(non_rebound),
                "decision_counts": decision_counts,
                "strong_candidate_memories": strong[:12],
                "promotion_state": "NOT_PROMOTED",
                "notes": (
                    "Rotation evidence is descriptive research memory only. "
                    "No weights, live authority, canonical crystals or execution policy were changed."
                ),
            }
        finally:
            conn.close()

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
