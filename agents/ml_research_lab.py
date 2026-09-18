from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional


class MLResearchLabAgent:
    """Offline-only model candidate registry and model-card forge."""

    FAMILIES = ("freqai", "finrl_crypto", "macrohft", "webcryptoagent")

    def __init__(self, cfg: Any):
        self.cfg = cfg
        self.card_dir = getattr(cfg, "ml_model_card_dir", "data/model_cards") or "data/model_cards"
        os.makedirs(self.card_dir, exist_ok=True)
        self.proposals_created = 0
        self.last_candidate_id = ""
        self.last_verdict = ""

    def status(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "enabled": bool(getattr(self.cfg, "ml_research_lab_enabled", True)),
            "name": "ML_RESEARCH_LAB",
            "mode": "offline_proposals_only",
            "families": self.enabled_families(),
            "card_dir": self.card_dir,
            "proposals_created": self.proposals_created,
            "last_candidate_id": self.last_candidate_id,
            "last_verdict": self.last_verdict,
            "policy": self.policy(),
        }

    def policy(self) -> Dict[str, Any]:
        return {
            "live_execution": "blocked",
            "allowed_outputs": ["proposal", "feature_importance", "model_card", "queen_review_packet"],
            "required_gates": ["layer3_evidence", "walk_forward", "pbo", "leakage", "offline_only", "negative_case_replay"],
            "max_pbo": float(getattr(self.cfg, "ml_max_pbo", 0.20) or 0.20),
            "min_oos_trades": int(getattr(self.cfg, "ml_min_oos_trades", 25) or 25),
            "max_drawdown_pct": float(getattr(self.cfg, "promotion_max_drawdown_pct", 5.0) or 5.0),
        }

    def default_blueprints(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        symbol = symbol or getattr(self.cfg, "symbol", "ETH/USD")
        objectives = {
            "freqai": "regime_aware_return_filter",
            "finrl_crypto": "risk_adjusted_policy_candidate",
            "macrohft": "memory_augmented_micro_regime_proposal",
            "webcryptoagent": "contextual_risk_and_narrative_proposal",
        }
        return [
            self.propose(family, symbol=symbol, objective=objectives.get(family), persist=False)
            for family in self.enabled_families()
        ]

    def enabled_families(self) -> List[str]:
        configured = getattr(self.cfg, "ml_model_families_enabled", None)
        if not configured:
            return list(self.FAMILIES)
        allowed = {str(family).strip().lower() for family in configured if str(family).strip()}
        return [family for family in self.FAMILIES if family in allowed]

    def propose(
        self,
        family: str,
        symbol: Optional[str] = None,
        objective: Optional[str] = None,
        features: Optional[List[str]] = None,
        metrics: Optional[Dict[str, Any]] = None,
        persist: bool = True,
    ) -> Dict[str, Any]:
        family = self._family(family)
        symbol = symbol or getattr(self.cfg, "symbol", "ETH/USD")
        objective = objective or self._default_objective(family)
        features = features or self._default_features(family)
        metrics = metrics or {}
        validation = self.validate(metrics)
        now = time.time()
        candidate_id = self._candidate_id(family, symbol, objective, features)
        validation_receipt = validation.get("validation_receipt") or {}
        card = {
            "candidate_id": candidate_id,
            "family": family,
            "symbol": symbol,
            "objective": objective,
            "status": "offline_proposal",
            "verdict": validation["verdict"],
            "created_ts": now,
            "updated_ts": now,
            "execution_authority": "none",
            "live_allowed": False,
            "feature_sets": features,
            "training_boundary": {
                "mode": "offline_only",
                "data_sources": self._data_sources(family),
                "forbidden": ["wallet_keys", "live_order_authority", "direct_execution"],
            },
            "validation": validation,
            "validation_receipt": validation_receipt,
            "layer3_evidence_id": validation_receipt.get("layer3_evidence_id") or metrics.get("layer3_evidence_id") or metrics.get("evidence_id"),
            "walk_forward_windows": validation_receipt.get("walk_forward_windows") or metrics.get("walk_forward_windows") or [],
            "pbo_score": validation_receipt.get("pbo_score", metrics.get("pbo")),
            "leakage_report": validation_receipt.get("leakage_report") or metrics.get("leakage_report") or {},
            "negative_case_replay": validation_receipt.get("negative_case_replay") or metrics.get("negative_case_replay") or {},
            "model_card": self._model_card(family, symbol, objective, features, validation),
            "local_inference_forge": self._forge_contract(family),
            "crystallized_compute": self._crystal_contract(family),
            "phoenix_review": {
                "next_required_phase": 2,
                "requires_external_evidence_id": True,
                "allowed_decision": "candidate_proposal_only",
                "promotion_authority": "none",
            },
        }
        if persist:
            paths = self.write_model_card(card)
            card["model_card_path"] = paths["json"]
            card["model_card_markdown_path"] = paths["markdown"]
            self.proposals_created += 1
            self.last_candidate_id = candidate_id
            self.last_verdict = validation["verdict"]
        return card

    def validation_runner(
        self,
        evidence: Dict[str, Any],
        features: Optional[List[str]] = None,
        report: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build a candidate validation receipt from a persisted Layer 3 evidence record."""
        evidence = evidence or {}
        report = report or {}
        metrics = evidence.get("metrics") or {}
        raw_metrics = evidence.get("raw_metrics") or {}
        gates = evidence.get("gates") or {}
        features = features or []

        evidence_id = evidence.get("evidence_id")
        evidence_verdict = evidence.get("verdict")
        walk_forward_gate = gates.get("walk_forward") or {}
        walk_forward_passed = bool(walk_forward_gate.get("pass"))
        walk_forward_windows = (
            report.get("walk_forward_windows")
            or raw_metrics.get("walk_forward_windows")
            or (evidence.get("raw") or {}).get("walk_forward_windows")
            or []
        )
        if not walk_forward_windows and walk_forward_passed:
            walk_forward_windows = [{
                "source": "layer3_evidence_gate",
                "run_id": evidence.get("run_id"),
                "verified": True,
            }]

        pbo = self._float(
            report.get("pbo")
            if "pbo" in report
            else report.get("pbo_score", raw_metrics.get("pbo", raw_metrics.get("pbo_score"))),
            default=None,
        )

        leakage_report = self._leakage_report(evidence, features, report.get("leakage_report"))
        negative_case_replay = self._negative_case_replay(evidence, report.get("negative_case_replay"))
        oos_trades = self._int(
            report.get("oos_trades")
            or report.get("out_of_sample_trades")
            or raw_metrics.get("oos_trades")
            or raw_metrics.get("out_of_sample_trades")
            or (metrics.get("trades") if walk_forward_passed else 0),
            default=0,
        )

        receipt = {
            "runner": "ml_research_lab.validation_runner.v1",
            "created_ts": time.time(),
            "layer3_evidence_id": evidence_id,
            "layer3_evidence_verified": bool(evidence_id),
            "layer3_evidence_verdict": evidence_verdict,
            "layer3_gate_snapshot": gates,
            "walk_forward_passed": walk_forward_passed,
            "walk_forward_windows": walk_forward_windows,
            "pbo_score": pbo,
            "pbo_source": "validation_report_or_layer3_raw_metrics" if pbo is not None else "missing",
            "leakage_report": leakage_report,
            "negative_case_replay": negative_case_replay,
            "oos_trades": oos_trades,
            "max_drawdown_pct": metrics.get("max_drawdown_pct"),
            "evidence_metrics": metrics,
        }
        return {
            "layer3_evidence_id": evidence_id,
            "evidence_id": evidence_id,
            "layer3_evidence_verified": bool(evidence_id),
            "walk_forward_passed": walk_forward_passed,
            "walk_forward_windows": walk_forward_windows,
            "pbo": pbo,
            "pbo_score": pbo,
            "leakage_detected": bool(leakage_report.get("leakage_detected")),
            "leakage_report": leakage_report,
            "negative_case_replay_passed": bool(negative_case_replay.get("pass")),
            "negative_case_replay": negative_case_replay,
            "oos_trades": oos_trades,
            "max_drawdown_pct": metrics.get("max_drawdown_pct"),
            "validation_receipt": receipt,
        }

    def validate(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        policy = self.policy()
        pbo = self._float(metrics.get("pbo"), default=None)
        oos_trades = self._int(metrics.get("oos_trades") or metrics.get("out_of_sample_trades"), default=0)
        max_dd = self._float(metrics.get("max_drawdown_pct"), default=None)
        leakage = bool(metrics.get("leakage_detected", False))
        walk_forward = bool(metrics.get("walk_forward_passed") or metrics.get("walk_forward"))
        layer3_id = metrics.get("layer3_evidence_id") or metrics.get("evidence_id")
        layer3 = bool(layer3_id) and bool(metrics.get("layer3_evidence_verified"))
        gates = {
            "offline_only": {"pass": True, "required": True, "value": True},
            "layer3_evidence": {"pass": layer3, "required": "verified_evidence_id", "value": layer3_id},
            "walk_forward": {"pass": walk_forward, "required": True, "value": walk_forward},
            "pbo": {"pass": pbo is not None and pbo <= policy["max_pbo"], "required": f"<= {policy['max_pbo']}", "value": pbo},
            "leakage": {"pass": not leakage, "required": "no_leakage_detected", "value": leakage},
            "oos_trades": {"pass": oos_trades >= policy["min_oos_trades"], "required": policy["min_oos_trades"], "value": oos_trades},
            "drawdown": {"pass": max_dd is not None and max_dd <= policy["max_drawdown_pct"], "required": policy["max_drawdown_pct"], "value": max_dd},
            "negative_case_replay": {
                "pass": bool(metrics.get("negative_case_replay_passed")),
                "required": "stress_or_negative_case_receipt_passed",
                "value": bool(metrics.get("negative_case_replay_passed")),
            },
        }
        required = ("offline_only", "layer3_evidence", "walk_forward", "pbo", "leakage", "oos_trades", "drawdown", "negative_case_replay")
        if all(gates[k]["pass"] for k in required):
            verdict = "phoenix_phase2_candidate_ready"
        elif any(gates[k]["pass"] for k in ("walk_forward", "pbo", "layer3_evidence")):
            verdict = "research_collecting"
        else:
            verdict = "proposal_only"
        return {"verdict": verdict, "gates": gates, "metrics": metrics, "validation_receipt": metrics.get("validation_receipt") or {}}

    def write_model_card(self, card: Dict[str, Any]) -> Dict[str, str]:
        candidate_id = card.get("candidate_id")
        json_path = os.path.join(self.card_dir, f"{candidate_id}.json")
        md_path = os.path.join(self.card_dir, f"{candidate_id}.md")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(card, f, indent=2, sort_keys=True, default=str)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(self._markdown(card))
        return {"json": json_path, "markdown": md_path}

    def _model_card(self, family: str, symbol: str, objective: str, features: List[str], validation: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "intended_use": "offline_research_signal_proposal",
            "out_of_scope": ["live_orders", "wallet_control", "unreviewed_position_sizing"],
            "model_family": family,
            "symbol_scope": symbol,
            "objective": objective,
            "features": features,
            "validation_summary": validation,
            "risk_notes": self._risk_notes(family),
        }

    def _forge_contract(self, family: str) -> Dict[str, Any]:
        return {
            "inspired_by": "EdgeK BEAST local inference forge",
            "mode": "local_first_shadow",
            "teacher_identity_separate_from_runtime": True,
            "outputs": ["candidate_card", "feature_receipt", "validation_receipt"],
            "cloud_disabled_replay_required": family in ("freqai", "finrl_crypto", "macrohft"),
        }

    def _crystal_contract(self, family: str) -> Dict[str, Any]:
        return {
            "inspired_by": "EdgeK BEAST crystallized compute",
            "crystallize": ["feature_pipeline", "validation_split", "model_card", "negative_case"],
            "reuse_boundary": "same_symbol_same_feature_schema_same_evidence_window",
            "promotion_channel": "candidate_only_until_phoenix_phase2",
            "staleness_inputs": ["feature_schema_hash", "market_regime", "layer3_evidence_id", "data_window"],
        }

    def _markdown(self, card: Dict[str, Any]) -> str:
        validation = card.get("validation") or {}
        gates = validation.get("gates") or {}
        lines = [
            f"# Model Card: {card.get('candidate_id')}",
            "",
            f"- Family: `{card.get('family')}`",
            f"- Symbol: `{card.get('symbol')}`",
            f"- Objective: `{card.get('objective')}`",
            f"- Status: `{card.get('status')}`",
            f"- Verdict: `{card.get('verdict')}`",
            "- Live Allowed: `false`",
            "",
            "## Gates",
        ]
        for name, row in gates.items():
            lines.append(f"- `{name}`: {'PASS' if row.get('pass') else 'WAIT'} (value={row.get('value')}, required={row.get('required')})")
        lines.extend([
            "",
            "## Validation Receipt",
            json.dumps(card.get("validation_receipt") or {}, indent=2, sort_keys=True, default=str),
            "",
            "## Boundary",
            "This candidate may produce research proposals only. It cannot place orders, control wallets, or bypass Queen/SwarmGuard review.",
            "",
            "## Local Inference Forge",
            json.dumps(card.get("local_inference_forge") or {}, indent=2, sort_keys=True),
            "",
            "## Crystallized Compute",
            json.dumps(card.get("crystallized_compute") or {}, indent=2, sort_keys=True),
            "",
        ])
        return "\n".join(lines)

    def _family(self, family: str) -> str:
        family = str(family or "freqai").strip().lower()
        return family if family in self.FAMILIES else "freqai"

    def _default_objective(self, family: str) -> str:
        return {
            "freqai": "adaptive_feature_return_filter",
            "finrl_crypto": "risk_adjusted_policy_candidate",
            "macrohft": "memory_augmented_micro_regime_proposal",
            "webcryptoagent": "contextual_risk_and_narrative_proposal",
        }.get(family, "adaptive_feature_return_filter")

    def _default_features(self, family: str) -> List[str]:
        common = ["layer3_evidence", "regime", "drawdown", "volume", "spread", "slippage"]
        if family == "webcryptoagent":
            return common + ["news_context", "onchain_context", "wallet_flow_context", "narrative_risk"]
        if family == "finrl_crypto":
            return common + ["portfolio_state", "reward_drawdown_penalty", "transaction_cost"]
        if family == "macrohft":
            return common + ["micro_regime_memory", "latency_bucket", "order_flow_proxy"]
        return common + ["freqai_feature_window", "indicator_stack", "target_horizon"]

    def _data_sources(self, family: str) -> List[str]:
        if family == "webcryptoagent":
            return ["market_bee", "layer3_evidence", "public_context", "onchain_watch_only"]
        return ["market_bee", "layer3_evidence", "replay_results", "paper_trades"]

    def _risk_notes(self, family: str) -> List[str]:
        notes = ["overfitting", "regime_shift", "data_leakage", "transaction_cost_underestimate"]
        if family == "webcryptoagent":
            notes.append("llm_context_reproducibility")
        if family == "finrl_crypto":
            notes.append("reward_hacking")
        return notes

    def _leakage_report(self, evidence: Dict[str, Any], features: List[str], report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        report = dict(report or {})
        forbidden = {"future_return", "future_price", "label", "target", "wallet_keys", "live_order_authority"}
        feature_hits = sorted({str(f) for f in features if str(f).lower() in forbidden})
        raw = evidence.get("raw") or {}
        raw_metrics = evidence.get("raw_metrics") or {}
        explicit_leakage = bool(
            report.get("leakage_detected")
            or raw_metrics.get("leakage_detected")
            or raw.get("leakage_detected")
        )
        leakage_detected = explicit_leakage or bool(feature_hits)
        return {
            "pass": not leakage_detected,
            "leakage_detected": leakage_detected,
            "forbidden_feature_hits": feature_hits,
            "checks": {
                "forbidden_features": not bool(feature_hits),
                "explicit_layer3_flag": not explicit_leakage,
                "walk_forward_boundary_present": bool((evidence.get("gates") or {}).get("walk_forward", {}).get("pass")),
            },
            "source": report.get("source") or "ml_research_lab.validation_runner.v1",
        }

    def _negative_case_replay(self, evidence: Dict[str, Any], report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if isinstance(report, dict) and report:
            return {
                "pass": bool(report.get("pass")),
                "source": report.get("source") or "external_validation_report",
                "cases": report.get("cases") or [],
                "notes": report.get("notes") or [],
            }
        gates = evidence.get("gates") or {}
        metrics = evidence.get("metrics") or {}
        cases = [
            {"name": "fee_model_present", "pass": bool((gates.get("fee_model") or {}).get("pass"))},
            {"name": "slippage_model_present", "pass": bool((gates.get("slippage_model") or {}).get("pass"))},
            {"name": "drawdown_within_policy", "pass": bool((gates.get("max_drawdown") or {}).get("pass")), "value": metrics.get("max_drawdown_pct")},
            {"name": "positive_net_after_costs", "pass": bool((gates.get("positive_net") or {}).get("pass")), "value": metrics.get("net_profit_pct")},
        ]
        return {
            "pass": all(bool(case.get("pass")) for case in cases),
            "source": "layer3_cost_and_drawdown_gate_replay",
            "cases": cases,
            "notes": ["Derived from Layer 3 fee, slippage, drawdown, and net-profit gates."],
        }

    def _candidate_id(self, family: str, symbol: str, objective: str, features: List[str]) -> str:
        raw = json.dumps({"family": family, "symbol": symbol, "objective": objective, "features": features}, sort_keys=True)
        return f"ml-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"

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
