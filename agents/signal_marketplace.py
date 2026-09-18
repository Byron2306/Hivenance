from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Optional


class SignalMarketplaceAgent:
    """Sandboxed validator/miner scoring for worker proposals."""

    def __init__(self, cfg: Any):
        self.cfg = cfg
        self.rounds_seen = 0
        self.last_round_id = ""
        self.last_verdict = ""

    def status(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "name": "SIGNAL_MARKETPLACE",
            "mode": "simulated_rewards_only",
            "rounds_seen": self.rounds_seen,
            "last_round_id": self.last_round_id,
            "last_verdict": self.last_verdict,
            "policy": self.policy(),
        }

    def policy(self) -> Dict[str, Any]:
        return {
            "live_execution_authority": "none",
            "promotion_authority": "none",
            "scaling_authority": "none",
            "default_state": "dormant",
            "reward_currency": "simulated_points",
            "min_originality_score": float(getattr(self.cfg, "signal_marketplace_min_originality", 0.35) or 0.35),
            "max_drawdown_score": float(getattr(self.cfg, "signal_marketplace_max_drawdown", 0.45) or 0.45),
            "min_stability_score": float(getattr(self.cfg, "signal_marketplace_min_stability", 0.20) or 0.20),
            "min_realized_samples": int(getattr(self.cfg, "signal_marketplace_min_realized_samples", 25) or 25),
            "reward_scale": float(getattr(self.cfg, "signal_marketplace_reward_scale", 100.0) or 100.0),
            "weights": {
                "strength": float(getattr(self.cfg, "signal_marketplace_weight_strength", 0.25) or 0.25),
                "realized_outcome": float(getattr(self.cfg, "signal_marketplace_weight_realized_outcome", 0.25) or 0.25),
                "originality": float(getattr(self.cfg, "signal_marketplace_weight_originality", 0.20) or 0.20),
                "stability": float(getattr(self.cfg, "signal_marketplace_weight_stability", 0.15) or 0.15),
                "win_rate": float(getattr(self.cfg, "signal_marketplace_weight_win_rate", 0.15) or 0.15),
                "drawdown_penalty": float(getattr(self.cfg, "signal_marketplace_weight_drawdown_penalty", 0.35) or 0.35),
            },
        }

    def score_round(
        self,
        proposals: List[Dict[str, Any]],
        perf_by_worker: Optional[Dict[str, Any]] = None,
        symbol: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        proposals = [dict(p or {}) for p in (proposals or [])]
        perf_by_worker = perf_by_worker or {}
        context = context or {}
        now = time.time()
        submissions = [self._submission(p, symbol=symbol) for p in proposals]
        signatures = [s.get("signature") for s in submissions]
        scores = []
        for submission in submissions:
            worker = submission.get("worker")
            perf = perf_by_worker.get(worker) or perf_by_worker.get(str(worker or "").upper()) or {}
            scores.append(self._score_submission(submission, perf, signatures))
        total_reward = sum(float(s.get("simulated_reward") or 0.0) for s in scores)
        eliminated = len([s for s in scores if s.get("eliminated")])
        verdict = "sandbox_round_scored" if scores and eliminated < len(scores) else "sandbox_collecting"
        round_id = self._round_id(symbol, submissions, context)
        result = {
            "round_id": round_id,
            "source": "signal_marketplace",
            "symbol": symbol,
            "created_ts": now,
            "updated_ts": now,
            "status": "simulated_rewards_only",
            "verdict": verdict,
            "submissions": submissions,
            "scores": scores,
            "summary": {
                "submitted": len(submissions),
                "eligible": len(scores) - eliminated,
                "eliminated": eliminated,
                "total_simulated_reward": round(total_reward, 6),
            },
            "gates": self._round_gates(scores),
            "context": context,
            "execution_authority": "none",
            "live_allowed": False,
            "promotion_authority": "none",
            "scaling_authority": "none",
            "phoenix_status": "SANDBOX_ONLY",
        }
        self.rounds_seen += 1
        self.last_round_id = round_id
        self.last_verdict = verdict
        return result

    def _submission(self, proposal: Dict[str, Any], symbol: Optional[str]) -> Dict[str, Any]:
        worker = proposal.get("worker") or proposal.get("strategy") or proposal.get("source") or "UNKNOWN"
        payload = {
            "worker": str(worker),
            "symbol": proposal.get("symbol") or symbol,
            "action": str(proposal.get("action") or proposal.get("signal") or "HOLD").upper(),
            "signal_strength": self._float(proposal.get("signal_strength", proposal.get("edge", proposal.get("confidence"))), default=0.0),
            "risk": self._float(proposal.get("risk"), default=0.0),
            "signal_id": proposal.get("signal_id"),
            "ts": proposal.get("ts") or int(time.time() * 1000),
            "notes": proposal.get("notes") or proposal.get("reason"),
        }
        signature = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()
        payload["signature"] = signature
        payload["signed"] = True
        payload["signature_scheme"] = "sha256_payload_receipt"
        return payload

    def _score_submission(self, submission: Dict[str, Any], perf: Dict[str, Any], signatures: List[str]) -> Dict[str, Any]:
        policy = self.policy()
        strength = max(0.0, min(1.0, self._float(submission.get("signal_strength"), default=0.0) or 0.0))
        total = max(0, self._int(perf.get("total"), default=0))
        wins = max(0, self._int(perf.get("wins"), default=0))
        losses = max(0, self._int(perf.get("losses"), default=0))
        win_rate = (wins / total) if total else 0.0
        realized = self._realized_outcome_score(perf, total, wins, losses)
        drawdown_score = self._drawdown_score(perf, losses, total)
        stability = self._stability_score(perf)
        originality = self._originality_score(submission.get("signature"), signatures)
        weights = policy["weights"]
        reward_score = max(0.0,
            (weights["strength"] * strength)
            + (weights["realized_outcome"] * realized["score"])
            + (weights["originality"] * originality)
            + (weights["stability"] * stability)
            + (weights["win_rate"] * win_rate)
            - (weights["drawdown_penalty"] * drawdown_score)
        )
        eliminated_reasons = []
        if originality < policy["min_originality_score"]:
            eliminated_reasons.append("PLAGIARISM_OR_DUPLICATE_SIGNAL")
        if drawdown_score > policy["max_drawdown_score"]:
            eliminated_reasons.append("DRAWDOWN_ELIMINATION")
        if stability < policy["min_stability_score"]:
            eliminated_reasons.append("LOW_STABILITY")
        eliminated = bool(eliminated_reasons)
        return {
            "worker": submission.get("worker"),
            "signature": submission.get("signature"),
            "signal_id": submission.get("signal_id"),
            "action": submission.get("action"),
            "scores": {
                "strength": strength,
                "win_rate": win_rate,
                "realized_outcome": realized["score"],
                "originality": originality,
                "stability": stability,
                "drawdown": drawdown_score,
                "reward_score": round(reward_score, 6),
            },
            "realized_outcome": realized,
            "eliminated": eliminated,
            "elimination_reasons": eliminated_reasons,
            "simulated_reward": 0.0 if eliminated else round(reward_score * policy["reward_scale"], 6),
        }

    def _round_gates(self, scores: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        submitted = len(scores)
        duplicates = len([s for s in scores if "PLAGIARISM_OR_DUPLICATE_SIGNAL" in (s.get("elimination_reasons") or [])])
        drawdown_eliminated = len([s for s in scores if "DRAWDOWN_ELIMINATION" in (s.get("elimination_reasons") or [])])
        rewarded = len([s for s in scores if float(s.get("simulated_reward") or 0.0) > 0.0])
        realized = len([s for s in scores if (s.get("realized_outcome") or {}).get("status") == "ready"])
        return {
            "signed_submissions": {"pass": submitted > 0, "value": submitted, "required": "> 0"},
            "plagiarism_check": {"pass": duplicates == 0, "value": duplicates, "required": 0},
            "drawdown_elimination": {"pass": True, "value": drawdown_eliminated, "required": "eliminate_high_drawdown"},
            "realized_outcome_scoring": {"pass": realized > 0 or submitted == 0, "value": realized, "required": "long_horizon_worker_stats"},
            "reward_simulation": {"pass": rewarded > 0 or submitted == 0, "value": rewarded, "required": "simulated_only"},
            "sandbox_only": {"pass": True, "value": True, "required": True},
        }

    def _originality_score(self, signature: Optional[str], signatures: List[str]) -> float:
        if not signature:
            return 0.0
        return 0.0 if signatures.count(signature) > 1 else 1.0

    def _stability_score(self, perf: Dict[str, Any]) -> float:
        recent = perf.get("recent") or []
        if isinstance(recent, str):
            try:
                recent = json.loads(recent or "[]")
            except Exception:
                recent = []
        if not recent:
            return 0.5
        vals = [1.0 if bool(v) else 0.0 for v in list(recent)[-20:]]
        if not vals:
            return 0.5
        mean = sum(vals) / len(vals)
        variance = sum((v - mean) ** 2 for v in vals) / len(vals)
        return round(max(0.0, min(1.0, mean * (1.0 - variance))), 6)

    def _drawdown_score(self, perf: Dict[str, Any], losses: int, total: int) -> float:
        if perf.get("drawdown") is not None:
            return max(0.0, min(1.0, self._float(perf.get("drawdown"), default=0.0) or 0.0))
        if perf.get("max_drawdown_pct") is not None:
            return max(0.0, min(1.0, (self._float(perf.get("max_drawdown_pct"), default=0.0) or 0.0) / 100.0))
        return (losses / total) if total else 0.0

    def _realized_outcome_score(self, perf: Dict[str, Any], total: int, wins: int, losses: int) -> Dict[str, Any]:
        required = self.policy()["min_realized_samples"]
        if total < required:
            return {
                "status": "pending",
                "score": 0.5,
                "samples": total,
                "required": required,
                "wins": wins,
                "losses": losses,
            }
        win_rate = wins / max(1, total)
        loss_penalty = losses / max(1, total)
        score = max(0.0, min(1.0, (0.75 * win_rate) + (0.25 * (1.0 - loss_penalty))))
        return {
            "status": "ready",
            "score": round(score, 6),
            "samples": total,
            "required": required,
            "wins": wins,
            "losses": losses,
        }

    def _round_id(self, symbol: Optional[str], submissions: List[Dict[str, Any]], context: Dict[str, Any]) -> str:
        raw = json.dumps({"symbol": symbol, "submissions": submissions, "context": context}, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _float(self, value: Any, default: Optional[float] = 0.0) -> Optional[float]:
        try:
            if value is None or value == "":
                return default
            return float(value)
        except Exception:
            return default

    def _int(self, value: Any, default: int = 0) -> int:
        try:
            return int(float(value))
        except Exception:
            return default
