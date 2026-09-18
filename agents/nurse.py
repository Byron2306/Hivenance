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


    def review_profit_streak_lab(self, database: str, run_id: str | None = None) -> Dict[str, Any]:
        """Read-only Nurse autopsy for the live public-market profit-streak lab."""
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
        try:
            if run_id is None:
                run = conn.execute(
                    "SELECT run_id,status,started_ts,ended_ts,config_json "
                    "FROM live_streak_runs ORDER BY started_ts DESC LIMIT 1"
                ).fetchone()
            else:
                run = conn.execute(
                    "SELECT run_id,status,started_ts,ended_ts,config_json "
                    "FROM live_streak_runs WHERE run_id=?",
                    (run_id,),
                ).fetchone()
            if not run:
                return {
                    "schema": "hivenance_nurse_profit_streak_review_v1",
                    "status": "NO_STREAK_RUN",
                    "authority": "read_only_learning_review",
                }
            rid = str(run["run_id"])
            try:
                start_usd = float(json.loads(run["config_json"] or "{}").get("start_usd", 1000.0))
            except Exception:
                start_usd = 1000.0

            marks = conn.execute(
                """
                SELECT w.mutation_id,w.equity_usd,w.cumulative_cost_usd
                FROM live_wallet_marks w
                JOIN (
                  SELECT mutation_id,MAX(ts) AS max_ts
                  FROM live_wallet_marks WHERE run_id=? GROUP BY mutation_id
                ) x ON x.mutation_id=w.mutation_id AND x.max_ts=w.ts
                WHERE w.run_id=?
                """,
                (rid, rid),
            ).fetchall()
            actions = conn.execute(
                "SELECT mutation_id,action,reason,votes_json,regime_json,cost_usd "
                "FROM live_paper_actions WHERE run_id=?",
                (rid,),
            ).fetchall()
            sparks = conn.execute(
                "SELECT mutation_id,COUNT(*) AS n,AVG(delta_1s_usd) AS d1,"
                "AVG(delta_3s_usd) AS d3,AVG(delta_5s_usd) AS d5,"
                "AVG(delta_10s_usd) AS d10 "
                "FROM live_streak_events WHERE run_id=? GROUP BY mutation_id",
                (rid,),
            ).fetchall()

            by_mutation: Dict[str, Dict[str, Any]] = {}
            for mark in marks:
                mid = str(mark["mutation_id"])
                by_mutation[mid] = {
                    "mutation_id": mid,
                    "final_equity_usd": round(float(mark["equity_usd"] or 0.0), 6),
                    "net_usd": round(float(mark["equity_usd"] or 0.0) - start_usd, 6),
                    "modeled_cost_usd": round(float(mark["cumulative_cost_usd"] or 0.0), 6),
                    "actions": 0,
                    "buy_actions": 0,
                    "sell_actions": 0,
                    "entry_regimes": {},
                    "mean_entry_positive_votes": None,
                }

            vote_sums: Dict[str, float] = {}
            vote_counts: Dict[str, int] = {}
            for action in actions:
                mid = str(action["mutation_id"])
                bucket = by_mutation.setdefault(mid, {
                    "mutation_id": mid,
                    "final_equity_usd": None,
                    "net_usd": None,
                    "modeled_cost_usd": 0.0,
                    "actions": 0,
                    "buy_actions": 0,
                    "sell_actions": 0,
                    "entry_regimes": {},
                    "mean_entry_positive_votes": None,
                })
                bucket["actions"] += 1
                typ = str(action["action"] or "").upper()
                if typ == "BUY":
                    bucket["buy_actions"] += 1
                elif typ == "SELL":
                    bucket["sell_actions"] += 1
                if typ == "BUY":
                    try:
                        regime = json.loads(action["regime_json"] or "{}")
                    except Exception:
                        regime = {}
                    label = str(regime.get("label") or "unknown")
                    bucket["entry_regimes"][label] = bucket["entry_regimes"].get(label, 0) + 1
                    try:
                        votes = json.loads(action["votes_json"] or "{}")
                    except Exception:
                        votes = {}
                    positive_votes = sum(1 for value in votes.values() if float(value or 0) > 0)
                    vote_sums[mid] = vote_sums.get(mid, 0.0) + positive_votes
                    vote_counts[mid] = vote_counts.get(mid, 0) + 1

            for mid, bucket in by_mutation.items():
                if vote_counts.get(mid):
                    bucket["mean_entry_positive_votes"] = round(
                        vote_sums[mid] / vote_counts[mid], 6
                    )
                cost = float(bucket.get("modeled_cost_usd") or 0.0)
                net = bucket.get("net_usd")
                bucket["cost_to_net_ratio"] = (
                    round(cost / abs(float(net)), 6)
                    if net not in (None, 0, 0.0) else None
                )

            spark_map = {
                str(row["mutation_id"]): {
                    "events": int(row["n"] or 0),
                    "mean_delta_1s_usd": round(float(row["d1"] or 0.0), 6),
                    "mean_delta_3s_usd": round(float(row["d3"] or 0.0), 6),
                    "mean_delta_5s_usd": round(float(row["d5"] or 0.0), 6),
                    "mean_delta_10s_usd": round(float(row["d10"] or 0.0), 6),
                }
                for row in sparks
            }

            observations = []
            for bucket in by_mutation.values():
                mid = bucket["mutation_id"]
                net = bucket.get("net_usd")
                cost = float(bucket.get("modeled_cost_usd") or 0.0)
                action_count = int(bucket.get("actions") or 0)
                if action_count and net is not None and float(net) <= 0 and cost > 0:
                    observations.append({
                        "type": "cost_drag_candidate",
                        "mutation_id": mid,
                        "evidence": {
                            "net_usd": net,
                            "modeled_cost_usd": cost,
                            "actions": action_count,
                        },
                    })
                spark = spark_map.get(mid)
                if spark and spark["events"] > 0:
                    observations.append({
                        "type": "equity_streak_candidate",
                        "mutation_id": mid,
                        "evidence": spark,
                    })

            return {
                "schema": "hivenance_nurse_profit_streak_review_v1",
                "authority": "read_only_learning_review",
                "run_id": rid,
                "run_status": str(run["status"]),
                "online_learning_was_attached": False,
                "review_mode": "post_run_autopsy_from_recorded_evidence",
                "mutations": sorted(
                    by_mutation.values(),
                    key=lambda item: (
                        float(item.get("net_usd") if item.get("net_usd") is not None else -1e18),
                        -int(item.get("actions") or 0),
                    ),
                    reverse=True,
                ),
                "streak_events": spark_map,
                "candidate_learning_observations": observations,
                "promotion_state": "NOT_PROMOTED",
                "notes": (
                    "Nurse did not participate online in this already-running lab. "
                    "This is a deterministic post-run autopsy; no weights, canonical crystals "
                    "or execution authority are changed."
                ),
            }
        finally:
            conn.close()

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

    def review_relative_drizzle_lab(self, database: str, run_id: str | None = None) -> Dict[str, Any]:
        """Read-only autopsy of relative-cheapness + streak drizzle evidence."""
        conn = sqlite3.connect(database)
        conn.row_factory = sqlite3.Row
        try:
            if run_id is None:
                run = conn.execute(
                    "SELECT run_id,status,started_ts,ended_ts,learning_authority,config_json "
                    "FROM relative_runs ORDER BY started_ts DESC LIMIT 1"
                ).fetchone()
            else:
                run = conn.execute(
                    "SELECT run_id,status,started_ts,ended_ts,learning_authority,config_json "
                    "FROM relative_runs WHERE run_id=?",
                    (run_id,),
                ).fetchone()
            if not run:
                return {
                    "schema": "hivenance_nurse_relative_drizzle_review_v1",
                    "status": "NO_RELATIVE_DRIZZLE_RUN",
                    "authority": "read_only_learning_review",
                }
            rid = str(run["run_id"])
            try:
                start_usd = float(json.loads(run["config_json"] or "{}").get("start_usd", 1000.0))
            except Exception:
                start_usd = 1000.0

            marks = conn.execute(
                """
                SELECT w.mutation_id,w.total_equity_usd,w.cumulative_cost_usd,
                       w.switches,w.actions,w.held_asset
                FROM relative_wallet_marks w
                JOIN (
                  SELECT mutation_id,MAX(ts) AS max_ts
                  FROM relative_wallet_marks WHERE run_id=? GROUP BY mutation_id
                ) x ON x.mutation_id=w.mutation_id AND x.max_ts=w.ts
                WHERE w.run_id=?
                """,
                (rid,rid),
            ).fetchall()
            legs = conn.execute(
                """
                SELECT mutation_id,symbol,net_pnl_usd,net_return_bps,duration_sec,
                       exit_reason,entry_context_json,exit_context_json
                FROM relative_legs
                WHERE run_id=? AND status='CLOSED'
                  AND exit_reason='relative_switch'
                """,
                (rid,),
            ).fetchall()
            crystals = conn.execute(
                """
                SELECT mutation_id,crystal_family,symbol,evidence_strength,
                       net_return_bps,duration_sec,cheapness_z,streak_persistence,
                       payload_json
                FROM relative_learning_crystals WHERE run_id=?
                """,
                (rid,),
            ).fetchall()
            decisions = conn.execute(
                """
                SELECT mutation_id,action,COUNT(*) AS n
                FROM relative_decisions
                WHERE run_id=?
                GROUP BY mutation_id,action
                """,
                (rid,),
            ).fetchall()

            final = {}
            for row in marks:
                equity = float(row["total_equity_usd"] or 0.0)
                final[str(row["mutation_id"])] = {
                    "mutation_id": str(row["mutation_id"]),
                    "final_equity_usd": round(equity,6),
                    "net_usd": round(equity-start_usd,6),
                    "modeled_cost_usd": round(float(row["cumulative_cost_usd"] or 0.0),6),
                    "switches": int(row["switches"] or 0),
                    "actions": int(row["actions"] or 0),
                    "held_asset": str(row["held_asset"] or ""),
                }

            by_mutation: Dict[str, Dict[str, Any]] = {}
            by_symbol: Dict[str, Dict[str, Any]] = {}
            by_transition: Dict[str, Dict[str, Any]] = {}
            cheapness_buckets: Dict[str, Dict[str, Any]] = {}
            persistence_buckets: Dict[str, Dict[str, Any]] = {}

            def acc(target: Dict[str, Dict[str, Any]], key: str, net_bps: float, net_usd: float, duration: float):
                bucket = target.setdefault(key,{
                    "samples":0,"wins":0,"net_bps_sum":0.0,"net_usd_sum":0.0,"duration_sum":0.0
                })
                bucket["samples"] += 1
                bucket["wins"] += 1 if net_bps > 0 else 0
                bucket["net_bps_sum"] += net_bps
                bucket["net_usd_sum"] += net_usd
                bucket["duration_sum"] += duration

            for leg in legs:
                mid = str(leg["mutation_id"])
                symbol = str(leg["symbol"])
                net_usd = float(leg["net_pnl_usd"] or 0.0)
                net_bps = float(leg["net_return_bps"] or 0.0)
                duration = float(leg["duration_sec"] or 0.0)
                try:
                    exit_context = json.loads(leg["exit_context_json"] or "{}")
                except Exception:
                    exit_context = {}
                challenger = str(exit_context.get("challenger") or "unknown")
                acc(by_mutation,mid,net_bps,net_usd,duration)
                acc(by_symbol,symbol,net_bps,net_usd,duration)
                acc(by_transition,f"{symbol}->{challenger}",net_bps,net_usd,duration)

            for crystal in crystals:
                mid = str(crystal["mutation_id"])
                net_bps = float(crystal["net_return_bps"] or 0.0)
                duration = float(crystal["duration_sec"] or 0.0)
                cheap = float(crystal["cheapness_z"] or 0.0)
                persistence = float(crystal["streak_persistence"] or 0.0)
                if cheap <= -1.5:
                    ckey = "<=-1.5z"
                elif cheap <= -1.0:
                    ckey = "-1.5..-1.0z"
                elif cheap <= -0.5:
                    ckey = "-1.0..-0.5z"
                else:
                    ckey = ">-0.5z"
                if persistence >= 1.0:
                    pkey = "1.00"
                elif persistence >= 0.75:
                    pkey = "0.75..0.99"
                elif persistence >= 0.50:
                    pkey = "0.50..0.74"
                else:
                    pkey = "<0.50"
                acc(cheapness_buckets,ckey,net_bps,0.0,duration)
                acc(persistence_buckets,pkey,net_bps,0.0,duration)

            def finish(groups: Dict[str, Dict[str, Any]]) -> list[Dict[str, Any]]:
                rows = []
                for key,value in groups.items():
                    n=max(1,int(value["samples"]))
                    rows.append({
                        "key":key,
                        "samples":int(value["samples"]),
                        "wins":int(value["wins"]),
                        "win_rate":round(float(value["wins"])/n,6),
                        "mean_net_return_bps":round(float(value["net_bps_sum"])/n,6),
                        "net_pnl_usd":round(float(value["net_usd_sum"]),6),
                        "mean_duration_sec":round(float(value["duration_sum"])/n,3),
                    })
                return sorted(rows,key=lambda item:(
                    float(item["mean_net_return_bps"]),int(item["samples"])
                ),reverse=True)

            decision_counts: Dict[str, Dict[str, int]] = {}
            for row in decisions:
                decision_counts.setdefault(str(row["mutation_id"]),{})[
                    str(row["action"])
                ] = int(row["n"])

            positives=sum(1 for row in crystals if str(row["crystal_family"])=="positive_capability")
            negatives=sum(1 for row in crystals if str(row["crystal_family"])=="negative_capability")
            strong=[]
            for row in crystals:
                if float(row["evidence_strength"] or 0.0) < 0.5:
                    continue
                try:
                    payload=json.loads(row["payload_json"] or "{}")
                except Exception:
                    payload={}
                strong.append({
                    "mutation_id":str(row["mutation_id"]),
                    "family":str(row["crystal_family"]),
                    "incumbent":str(payload.get("incumbent") or row["symbol"]),
                    "challenger":str(payload.get("challenger") or "unknown"),
                    "evidence_strength":round(float(row["evidence_strength"] or 0.0),6),
                    "cheapness_z":round(float(row["cheapness_z"] or 0.0),6),
                    "streak_persistence":round(float(row["streak_persistence"] or 0.0),6),
                    "net_return_bps":round(float(row["net_return_bps"] or 0.0),6),
                })
            strong.sort(key=lambda item:float(item["evidence_strength"]),reverse=True)

            return {
                "schema":"hivenance_nurse_relative_drizzle_review_v1",
                "authority":"read_only_learning_review",
                "learning_authority":str(run["learning_authority"] or ""),
                "run_id":rid,
                "run_status":str(run["status"]),
                "objective":"tiny_incremental_relative_gains_after_costs",
                "final_scorecard":sorted(final.values(),key=lambda item:float(item["net_usd"]),reverse=True),
                "closed_switch_legs":len(legs),
                "candidate_crystals":len(crystals),
                "positive_candidate_crystals":positives,
                "negative_candidate_crystals":negatives,
                "by_mutation":finish(by_mutation),
                "by_symbol":finish(by_symbol),
                "by_transition":finish(by_transition),
                "by_relative_cheapness":finish(cheapness_buckets),
                "by_streak_persistence":finish(persistence_buckets),
                "decision_counts":decision_counts,
                "strong_candidate_memories":strong[:16],
                "promotion_state":"NOT_PROMOTED",
                "notes":(
                    "Relative-drizzle evidence remains candidate research memory. "
                    "No weights, canonical crystals, live orders or execution authority changed."
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
