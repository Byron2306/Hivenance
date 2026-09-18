import time
import json
import os
import ast
import operator
from collections import deque
from typing import Any, Dict, List, Optional


class SwarmGuard:
    """
    Phase 1 SwarmGuard:
    - Liquidity-aware size cap
    - Spread/fee veto
    - Regime-based gating
    """

    def __init__(self, cfg: Any, coordinator: Optional[Any] = None):
        self.cfg = cfg
        self.coordinator = coordinator
        self.k = float(getattr(cfg, "liquidity_k", 0.08) or 0.08)
        self.m = float(getattr(cfg, "liquidity_m", 0.02) or 0.02)
        self.expected_move_min = float(getattr(cfg, "expected_move_min_pct", 0.003) or 0.003)
        self.fee_buffer = float(getattr(cfg, "fee_buffer_pct", 0.0015) or 0.0015)
        self.spread_guard_pct = float(getattr(cfg, "spread_guard_pct", 0.01) or 0.01)
        # Phase 2 controls
        self.max_trades_per_hour = int(getattr(cfg, "swarmguard_max_trades_per_hour", 12) or 12)
        self.min_trade_interval_sec = int(getattr(cfg, "swarmguard_min_trade_interval_sec", 120) or 120)
        self.consensus_min = int(getattr(cfg, "swarmguard_consensus_min", 3) or 3)
        self.consensus_penalty = float(getattr(cfg, "swarmguard_consensus_penalty", 0.7) or 0.7)
        self.weight_decay = float(getattr(cfg, "swarmguard_weight_decay", 0.9) or 0.9)
        self.weight_floor = float(getattr(cfg, "swarmguard_weight_floor", 0.4) or 0.4)
        self.small_trade_usd = float(getattr(cfg, "swarmguard_small_trade_usd", 0.0) or 0.0)
        self.small_trade_bypass = bool(getattr(cfg, "swarmguard_small_trade_bypass", False))
        self.dex_min_output_ratio = float(getattr(cfg, "dex_min_output_ratio", getattr(cfg, "onchain_min_output_ratio", 0.90)) or 0.90)
        self.dex_max_price_impact_pct = float(getattr(cfg, "dex_max_price_impact_pct", 0.02) or 0.02)
        self.dex_max_gas_drag_pct = float(getattr(cfg, "dex_max_gas_drag_pct", 0.01) or 0.01)
        self.dex_min_liquidity_usd = float(getattr(cfg, "dex_min_liquidity_usd", 0.0) or 0.0)

        self._trade_times = deque()
        self._last_trade_ts = 0.0
        self._weights: Dict[str, float] = {}
        self._rulebook = self._load_rulebook()
        self._risk_rules = self._load_risk_rules()
        self._risk_register = self._load_risk_register()
        self._risk_agent_map = self._load_risk_agent_map()
        self._buzz_client = None
        self._buzz_account = getattr(self.cfg, "buzz_account", None)
        self._buzz_secret = getattr(self.cfg, "buzz_shared_secret", None)
        self._buzz_url = getattr(self.cfg, "buzz_base_url", None)
        self._override_last_stake = {"amount": 0, "ts": 0, "request_id": None}
        if self._buzz_url and self._buzz_secret:
            try:
                from buzzservice.client import BuzzServiceClient
                self._buzz_client = BuzzServiceClient(self._buzz_url, self._buzz_secret, service_name="swarmguard")
            except Exception:
                self._buzz_client = None

    def _load_rulebook(self) -> Optional[Dict[str, Any]]:
        path = getattr(self.cfg, "swarmguard_rules_path", "config/swarmguard_rules_v1.json")
        try:
            if path and os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            return None
        return None

    def _load_risk_rules(self) -> List[Dict[str, Any]]:
        path = getattr(self.cfg, "swarmguard_risk_rules_path", "config/swarmguard_rules.json")
        try:
            if path and os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data.get("swarmguard_rules", []) if isinstance(data, dict) else []
        except Exception:
            return []
        return []

    def _load_risk_register(self) -> Dict[str, Any]:
        path = getattr(self.cfg, "swarmguard_risk_register_path", "config/risk_register.json")
        try:
            if path and os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
        return {}

    def _load_risk_agent_map(self) -> Dict[str, Any]:
        path = getattr(self.cfg, "swarmguard_risk_map_path", "config/risk_agent_control_map.json")
        try:
            if path and os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
        return {}

    def _safe_eval(self, expr: str, names: Dict[str, Any]) -> float:
        allowed_ops = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Mod: operator.mod,
        }

        def _eval(node: ast.AST) -> float:
            if isinstance(node, ast.Expression):
                return _eval(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return float(node.value)
            if isinstance(node, ast.Num):
                return float(node.n)
            if isinstance(node, ast.Name):
                return float(names.get(node.id, 0.0))
            if isinstance(node, ast.BinOp) and type(node.op) in allowed_ops:
                return allowed_ops[type(node.op)](_eval(node.left), _eval(node.right))
            raise ValueError("unsafe expression")

        try:
            tree = ast.parse(expr, mode="eval")
            return float(_eval(tree))
        except Exception:
            return 0.0

    def _eval_trigger(self, trigger: Dict[str, Any], evidence: Dict[str, Any]) -> bool:
        for key, cond in (trigger or {}).items():
            left_val = evidence.get(key)
            if isinstance(cond, bool):
                if bool(left_val) != cond:
                    return False
                continue
            if isinstance(cond, (int, float)):
                if float(left_val or 0.0) != float(cond):
                    return False
                continue
            if isinstance(cond, str):
                txt = cond.strip()
                if txt[:1] in ("<", ">", "=", "!"):
                    op = None
                    for sym in ("<=", ">=", "==", "!=", "<", ">"):
                        if txt.startswith(sym):
                            op = sym
                            rhs = txt[len(sym):].strip()
                            break
                    if not op:
                        return False
                    right_val = self._safe_eval(rhs, evidence)
                    l = float(left_val or 0.0)
                    if op == "<" and not (l < right_val):
                        return False
                    if op == "<=" and not (l <= right_val):
                        return False
                    if op == ">" and not (l > right_val):
                        return False
                    if op == ">=" and not (l >= right_val):
                        return False
                    if op == "==" and not (l == right_val):
                        return False
                    if op == "!=" and not (l != right_val):
                        return False
                else:
                    if str(left_val).upper() != txt.upper():
                        return False
                continue
            if left_val != cond:
                return False
        return True

    def _normalize_regime(self, regime: str) -> str:
        r = (regime or "").upper()
        if "CHAOTIC" in r or "PANIC" in r or "ILLIQ" in r:
            return "CHAOTIC"
        if "TREND" in r or "BREAKOUT" in r:
            return "TRENDING"
        if "CHOP" in r or "RANGE" in r or "MEAN" in r:
            return "RANGING"
        return "RANGING"

    def _rulebook_enforce(
        self,
        council_decision: Optional[Dict[str, Any]],
        regime_snapshot: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        rb = self._rulebook or {}
        thresholds = rb.get("svs_thresholds", {}) if isinstance(rb, dict) else {}
        caps = rb.get("regime_caps", {}) if isinstance(rb, dict) else {}
        buzz = rb.get("buzz_staking", {}) if isinstance(rb, dict) else {}

        if not council_decision:
            return {"allowed": False, "reason": "NO_COUNCIL_DECISION"}
        if not regime_snapshot:
            return {"allowed": False, "reason": "NO_ORACLE_REGIME"}

        score = float(council_decision.get("score") or 0.0)
        margin = float(council_decision.get("margin") or 0.0)
        distinct = int(council_decision.get("distinct_workers") or 0)
        rec = council_decision.get("recommendation")
        if not rec:
            if score < float(thresholds.get("small_from", 0.55)):
                rec = "REJECT"
            elif score < float(thresholds.get("normal_from", 0.70)):
                rec = "ALLOW_SMALL"
            elif score < float(thresholds.get("scale_from", 0.82)):
                rec = "ALLOW_NORMAL"
            else:
                rec = "ALLOW_SCALE"
        regime_name = self._normalize_regime((regime_snapshot or {}).get("regime") or "")

        if score < float(thresholds.get("reject_below", 0.55)):
            return {"allowed": False, "reason": "SVS_SCORE_TOO_LOW"}
        if margin < float(thresholds.get("min_margin", 0.15)):
            return {"allowed": False, "reason": "SVS_MARGIN_TOO_LOW"}
        min_distinct = int(thresholds.get("min_distinct_workers", 2))
        if distinct < min_distinct:
            # allow 1 worker only in TRENDING with strong score
            if not (regime_name == "TRENDING" and score >= float(thresholds.get("normal_from", 0.70))):
                return {"allowed": False, "reason": "NOT_ENOUGH_WORKER_DIVERSITY"}

        allowed_recs = (caps.get(regime_name, {}) or {}).get("allowed_recommendations", [])
        if allowed_recs and rec not in allowed_recs:
            return {"allowed": False, "reason": "RECOMMENDATION_BLOCKED_BY_REGIME"}

        permit = {
            "max_position_pct": (caps.get(regime_name, {}) or {}).get("max_position_pct"),
            "max_notional_usdt": (caps.get(regime_name, {}) or {}).get("max_notional_usdt"),
            "max_slippage_bps": (caps.get(regime_name, {}) or {}).get("max_slippage_bps"),
            "cooldown_secs": (caps.get(regime_name, {}) or {}).get("cooldown_secs"),
        }
        stake = buzz.get(rec)
        out = {
            "allowed": True,
            "recommendation": rec,
            "permit": permit,
            "buzz": {
                "stake_required": True if stake is not None else False,
                "stake_amount": stake,
                "stake_reason": rec,
            },
            "reason_codes": ["SVS_OK", "REGIME_OK", "LIMITS_APPLIED"],
        }
        # Attempt stake lock (fail-closed if configured)
        if self._buzz_client and stake is not None and self._buzz_account:
            try:
                receipt = self._buzz_client.lock(
                    account=self._buzz_account,
                    amount=int(stake),
                    reason=str(rec),
                    request_id=f"buzz-{int(time.time())}",
                )
                out["buzz"]["receipt"] = receipt
            except Exception as e:
                return {"allowed": False, "reason": f"BUZZ_SERVICE_UNAVAILABLE: {e}"}
        return out

    def _regime_veto(self, regime: str, strategy: str, action: str) -> Optional[str]:
        r = (regime or "").upper()
        s = (strategy or "").upper()
        a = (action or "").upper()
        if a in ("", "HOLD"):
            return None
        if "CHAOTIC" in r or "PANIC" in r or "ILLIQ" in r:
            return "REGIME_UNSAFE"
        if "CHOP" in r or "MEAN_REVERT" in r:
            if "BREAKOUT" in s:
                return "REGIME_BLOCK_BREAKOUT"
        if r.startswith("TREND"):
            if "RSI" in s:
                return "REGIME_BLOCK_RSI"
        return None

    def _liquidity_cap(self, position_size: float, avg_vol: Optional[float], best_bid_vol: Optional[float], wallet_cap: Optional[float]) -> float:
        cap = position_size
        if wallet_cap and wallet_cap > 0:
            cap = min(cap, float(wallet_cap))
        if best_bid_vol and best_bid_vol > 0:
            cap = min(cap, self.k * float(best_bid_vol))
        if avg_vol and avg_vol > 0:
            cap = min(cap, self.m * float(avg_vol))
        return max(0.0, cap)

    def _compute_evidence(
        self,
        decision: Dict[str, Any],
        position_size: float,
        latest_price: float,
        volumes: Optional[List[float]],
        orderbook: Optional[Dict[str, Any]],
        exec_quality: Optional[Dict[str, Any]],
        regime_snapshot: Optional[Dict[str, Any]],
        proposals: Optional[List[Dict[str, Any]]],
        council_decision: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        evidence: Dict[str, Any] = {}
        action = (decision or {}).get("action") or ""
        strategy = (decision or {}).get("strategy") or ""
        svs = float((decision or {}).get("svs") or 0.0)
        symbol = (decision or {}).get("symbol") or (council_decision or {}).get("symbol") or getattr(self.cfg, "symbol", None)
        evidence["symbol"] = symbol

        required_position_usd = 0.0
        try:
            required_position_usd = float(position_size or 0.0) * float(latest_price or 0.0)
        except Exception:
            required_position_usd = 0.0
        evidence["required_position_usd"] = required_position_usd

        spread_pct = None
        try:
            if exec_quality and isinstance(exec_quality, dict):
                spread_pct = exec_quality.get("spread_pct")
            if spread_pct is not None:
                spread_pct = float(spread_pct)
        except Exception:
            spread_pct = None
        evidence["spread_pct"] = spread_pct

        # top of book depth (USD)
        top_depth_usd = None
        try:
            if orderbook and orderbook.get("bids") and latest_price:
                top_bid_vol = sum([float(b[1]) for b in orderbook.get("bids", [])[:3]])
                top_depth_usd = float(top_bid_vol) * float(latest_price)
        except Exception:
            top_depth_usd = None
        evidence["top_of_book_depth_usd"] = top_depth_usd

        # order size vs depth
        order_pct = None
        try:
            if top_depth_usd and required_position_usd:
                order_pct = float(required_position_usd) / float(top_depth_usd)
        except Exception:
            order_pct = None
        evidence["order_size_pct_of_depth"] = order_pct

        # expected net return proxy
        try:
            expected_move = svs * self.expected_move_min
            fee_drag = (spread_pct or 0.0) + self.fee_buffer
            evidence["expected_net_return"] = expected_move - fee_drag
        except Exception:
            evidence["expected_net_return"] = None

        # proposal consensus
        same_dir = 0
        try:
            if proposals:
                same_dir = len([p for p in proposals if (p.get("action") or "").upper() == action])
        except Exception:
            same_dir = 0
        evidence["same_direction_workers"] = same_dir

        # overtrading
        evidence["trades_per_hour"] = len(self._trade_times)
        try:
            evidence["max_allowed"] = int(getattr(self.cfg, "swarmguard_max_trades_per_hour", 12) or 12)
        except Exception:
            evidence["max_allowed"] = 12

        # optional signals
        try:
            evidence["worker_loss_streak"] = int((decision or {}).get("loss_streak") or (decision or {}).get("worker_loss_streak") or 0)
        except Exception:
            evidence["worker_loss_streak"] = 0
        try:
            evidence["alpha_age_hours"] = float((decision or {}).get("alpha_age_hours") or 0.0)
        except Exception:
            evidence["alpha_age_hours"] = 0.0
        try:
            evidence["order_unconfirmed_ms"] = int(exec_quality.get("order_unconfirmed_ms")) if exec_quality else 0
        except Exception:
            evidence["order_unconfirmed_ms"] = 0
        try:
            if exec_quality:
                if "api_failures_60s" in exec_quality:
                    evidence["api_failures"] = int(exec_quality.get("api_failures_60s") or 0)
                else:
                    evidence["api_failures"] = int(exec_quality.get("api_failures") or 0)
            else:
                evidence["api_failures"] = 0
        except Exception:
            evidence["api_failures"] = 0
        try:
            if exec_quality:
                for k in (
                    "quote_output_ratio",
                    "min_output_ratio",
                    "price_impact_pct",
                    "gas_drag_pct",
                    "gas_usd",
                    "route_liquidity_usd",
                    "liquidity_usd",
                ):
                    if k in exec_quality:
                        evidence[k] = exec_quality.get(k)
        except Exception:
            pass
        try:
            evidence["override_attempt"] = bool((decision or {}).get("override_attempt") or False)
        except Exception:
            evidence["override_attempt"] = False
        evidence["override_request"] = evidence.get("override_attempt")
        try:
            evidence["override_reason"] = str((decision or {}).get("override_reason") or "")
        except Exception:
            evidence["override_reason"] = ""
        try:
            evidence["override_request"] = bool((decision or {}).get("override_request") or False)
        except Exception:
            evidence["override_request"] = False
        try:
            evidence["override_used_in_live_mode"] = bool((decision or {}).get("override_used_in_live_mode") or False)
        except Exception:
            evidence["override_used_in_live_mode"] = False

        evidence["oracle_regime"] = self._normalize_regime((regime_snapshot or {}).get("regime") or "")
        evidence["strategy"] = strategy
        evidence["action"] = action

        # merge in risk metrics from council decision (if present)
        try:
            if council_decision and isinstance(council_decision, dict):
                c_risk = (council_decision.get("risk") or {}).get("metrics") or {}
                if isinstance(c_risk, dict):
                    if "worker_loss_streak" in c_risk:
                        evidence["worker_loss_streak"] = int(c_risk.get("worker_loss_streak") or evidence.get("worker_loss_streak") or 0)
                    if "alpha_age_minutes" in c_risk:
                        evidence["alpha_age_hours"] = float(c_risk.get("alpha_age_minutes") or 0.0) / 60.0
        except Exception:
            pass
        try:
            pair_state = self._pair_protection_state(symbol)
            if pair_state:
                evidence["pair_protection_state"] = pair_state.get("state")
                evidence["pair_protection_reason"] = pair_state.get("reason")
                evidence["pair_protection_allowed"] = bool(pair_state.get("allowed", True))
        except Exception:
            pass
        return evidence

    def _apply_risk_rules(
        self,
        evidence: Dict[str, Any],
        position_size: float,
        latest_price: float,
    ) -> Dict[str, Any]:
        """Evaluate risk rules and return {veto_reason, cap_size, triggered}."""
        triggered: List[str] = []
        veto_reason = None
        cap_size = None
        stake_required = False
        stake_amount = None
        slash_required = False

        # SG-LIQ-GATE-01
        try:
            depth = evidence.get("top_of_book_depth_usd")
            required = evidence.get("required_position_usd")
            if depth and required and depth < float(required) * 10:
                veto_reason = "LIQUIDITY_TOO_THIN"
                triggered.append("SG-LIQ-GATE-01")
        except Exception:
            pass

        # SG-DEPTH-CAP-02
        try:
            pct = evidence.get("order_size_pct_of_depth")
            if pct and float(pct) > 0.05:
                triggered.append("SG-DEPTH-CAP-02")
                if latest_price and evidence.get("top_of_book_depth_usd"):
                    cap_usd = 0.05 * float(evidence.get("top_of_book_depth_usd"))
                    cap_size = min(cap_size, cap_usd / float(latest_price)) if cap_size else (cap_usd / float(latest_price))
        except Exception:
            pass

        # SG-FEE-FILTER-01
        try:
            enr = evidence.get("expected_net_return")
            if enr is not None and float(enr) <= 0:
                veto_reason = "FEE_DRAG"
                triggered.append("SG-FEE-FILTER-01")
        except Exception:
            pass

        # SG-REGIME-GATE-01
        try:
            if evidence.get("oracle_regime") == "CHAOTIC":
                if "BREAKOUT" in (evidence.get("strategy") or "").upper():
                    veto_reason = "REGIME_BLOCK_BREAKOUT"
                    triggered.append("SG-REGIME-GATE-01")
        except Exception:
            pass

        # SG-WORKER-WEIGHT-DECAY-01
        try:
            if int(evidence.get("worker_loss_streak") or 0) >= 3:
                triggered.append("SG-WORKER-WEIGHT-DECAY-01")
        except Exception:
            pass

        # SG-DIVERSITY-CAP-01
        try:
            if int(evidence.get("same_direction_workers") or 0) > 2:
                triggered.append("SG-DIVERSITY-CAP-01")
        except Exception:
            pass

        # SG-COOLDOWN-01 (overtrading)
        try:
            max_allowed = int(getattr(self.cfg, "swarmguard_max_trades_per_hour", 12) or 12)
            if int(evidence.get("trades_per_hour") or 0) > max_allowed:
                veto_reason = "OVERTRADE_CAP"
                triggered.append("SG-COOLDOWN-01")
        except Exception:
            pass

        # SG-LEARNING-DECAY-01
        try:
            if float(evidence.get("alpha_age_hours") or 0.0) > 72:
                triggered.append("SG-LEARNING-DECAY-01")
        except Exception:
            pass

        # SG-EXEC-CONFIRM-01
        try:
            if int(evidence.get("order_unconfirmed_ms") or 0) > 5000:
                veto_reason = "EXEC_UNCONFIRMED"
                triggered.append("SG-EXEC-CONFIRM-01")
        except Exception:
            pass

        # SG-KILL-API-01
        try:
            if int(evidence.get("api_failures") or 0) >= 3:
                veto_reason = "API_FAILURES"
                triggered.append("SG-KILL-API-01")
        except Exception:
            pass

        # SG-PAIR-PROTECT-01
        try:
            if evidence.get("pair_protection_allowed") is False:
                veto_reason = "PAIR_PROTECTED"
                triggered.append("SG-PAIR-PROTECT-01")
        except Exception:
            pass

        # DEX route quality gates for on-chain / small-cap execution.
        try:
            qr = evidence.get("quote_output_ratio")
            min_qr = evidence.get("min_output_ratio") or self.dex_min_output_ratio
            if qr is not None and float(qr) < float(min_qr):
                veto_reason = "DEX_QUOTE_TOO_LOW"
                triggered.append("SG-DEX-QUOTE-01")
        except Exception:
            pass
        try:
            impact = evidence.get("price_impact_pct")
            if impact is not None and float(impact) > self.dex_max_price_impact_pct:
                veto_reason = "DEX_PRICE_IMPACT"
                triggered.append("SG-DEX-IMPACT-01")
        except Exception:
            pass
        try:
            gas_drag = evidence.get("gas_drag_pct")
            if gas_drag is not None and float(gas_drag) > self.dex_max_gas_drag_pct:
                veto_reason = "DEX_GAS_DRAG"
                triggered.append("SG-DEX-GAS-01")
        except Exception:
            pass
        try:
            liq = evidence.get("route_liquidity_usd")
            if liq is None:
                liq = evidence.get("liquidity_usd")
            if self.dex_min_liquidity_usd > 0 and liq is not None and float(liq) < self.dex_min_liquidity_usd:
                veto_reason = "DEX_LIQUIDITY_TOO_THIN"
                triggered.append("SG-DEX-LIQ-01")
        except Exception:
            pass

        # Additional declarative rules from config (best-effort)
        try:
            for rule in self._risk_rules or []:
                rid = rule.get("rule_id") or "SG-RULE"
                if rid in triggered:
                    continue
                trig = rule.get("trigger") or {}
                if not self._eval_trigger(trig, evidence):
                    continue
                triggered.append(rid)
                act = rule.get("action") or ""
                if act in ("REJECT_TRADE", "REJECT_SIGNAL", "GLOBAL_PAUSE", "PAUSE_TRADING", "RETRY_OR_ABORT"):
                    veto_reason = veto_reason or "RISK_RULE"
                elif act == "REDUCE_POSITION":
                    if latest_price and evidence.get("top_of_book_depth_usd"):
                        try:
                            cap_usd = 0.05 * float(evidence.get("top_of_book_depth_usd"))
                            cap_size = min(cap_size, cap_usd / float(latest_price)) if cap_size else (cap_usd / float(latest_price))
                        except Exception:
                            pass
                elif act == "CAP_EXPOSURE":
                    # handled later via consensus penalty
                    pass
                elif act == "DISABLE_BREAKOUT_WORKERS":
                    if "BREAKOUT" in (evidence.get("strategy") or "").upper():
                        veto_reason = veto_reason or "REGIME_BLOCK_BREAKOUT"
                elif act in ("DECAY_WORKER_WEIGHT", "DECAY_LEARNED_WEIGHTS"):
                    # handled later via weight decay
                    pass
                elif act == "REQUIRE_BUZZ_STAKE":
                    stake_required = True
                    stake_amount = rule.get("stake_required") or stake_amount
                elif act == "SLASH_100_PERCENT":
                    slash_required = True
                    veto_reason = veto_reason or "OVERRIDE_SLASH"
        except Exception:
            pass

        return {
            "veto_reason": veto_reason,
            "cap_size": cap_size,
            "triggered": triggered,
            "vetoed": True if veto_reason else False,
            "stake_required": stake_required,
            "stake_amount": stake_amount,
            "slash_required": slash_required,
        }

    def _risk_message(self, rule_id: str) -> str:
        msgs = {
            "SG-LIQ-GATE-01": "Top-of-book depth too thin for required position.",
            "SG-DEPTH-CAP-02": "Order size is too large vs depth; capping.",
            "SG-FEE-FILTER-01": "Expected net return <= 0 after spread/fees.",
            "SG-REGIME-GATE-01": "Regime is CHAOTIC; breakout workers disabled.",
            "SG-WORKER-WEIGHT-DECAY-01": "Worker loss streak exceeded; decay weight.",
            "SG-DIVERSITY-CAP-01": "Too many workers in same direction; cap exposure.",
            "SG-COOLDOWN-01": "Overtrading threshold exceeded; cooldown.",
            "SG-LEARNING-DECAY-01": "Alpha too old; decay learned weights.",
            "SG-EXEC-CONFIRM-01": "Order confirmation latency too high.",
            "SG-KILL-API-01": "API failure threshold exceeded; global pause.",
            "SG-PAIR-PROTECT-01": "Pair protection is active for this symbol.",
            "SG-DEX-QUOTE-01": "DEX quote output is below the required minimum.",
            "SG-DEX-IMPACT-01": "DEX route price impact is too high.",
            "SG-DEX-GAS-01": "Gas drag is too high for expected edge.",
            "SG-DEX-LIQ-01": "DEX route liquidity is too thin.",
            "SG-OVERRIDE-STAKE-01": "Override requested; BUZZ stake required.",
            "SG-OVERRIDE-SLASH-01": "Override used in live mode; slash required.",
        }
        return msgs.get(rule_id, "Risk rule triggered.")

    def _pair_protection_state(self, symbol: Optional[str]) -> Optional[Dict[str, Any]]:
        if not symbol or not self.coordinator:
            return None
        try:
            ds = self.coordinator.agents.get("data_store") if getattr(self.coordinator, "agents", None) else None
            if not ds or not hasattr(ds, "get_pair_protections"):
                return None
            rows = ds.get_pair_protections(symbol) or {}
            return rows.get(symbol)
        except Exception:
            return None

    def _enforce_overtrading(self) -> Optional[str]:
        now = time.time()
        # clean old
        cutoff = now - 3600
        while self._trade_times and self._trade_times[0] < cutoff:
            self._trade_times.popleft()
        if self.max_trades_per_hour and len(self._trade_times) >= self.max_trades_per_hour:
            return "OVERTRADE_CAP"
        if self.min_trade_interval_sec and (now - self._last_trade_ts) < self.min_trade_interval_sec:
            return "COOLDOWN_ACTIVE"
        return None

    def record_trade(self):
        now = time.time()
        self._trade_times.append(now)
        self._last_trade_ts = now

    def safety_reset(self, reason: str = "UI_RESET") -> bool:
        """Clear internal throttles/weights and recent override stake bookkeeping."""
        try:
            self._trade_times.clear()
            self._last_trade_ts = 0.0
            self._weights = {}
            self._override_last_stake = {"amount": 0, "ts": 0, "request_id": None}
            # Emit a soft audit message if possible
            try:
                if self.coordinator:
                    self.coordinator.share_data("buzz.swarmguard.reset", {
                        "buzz": {"type": "buzz.swarmguard.reset", "source": "SWARMGUARD", "ts": int(time.time() * 1000)},
                        "payload": {"reason": reason},
                    })
            except Exception:
                pass
            return True
        except Exception:
            return False

    def evaluate(
        self,
        decision: Dict[str, Any],
        position_size: float,
        latest_price: float,
        volumes: Optional[List[float]],
        orderbook: Optional[Dict[str, Any]],
        exec_quality: Optional[Dict[str, Any]],
        regime_snapshot: Optional[Dict[str, Any]],
        base_free: float,
        quote_free: float,
        proposals: Optional[List[Dict[str, Any]]] = None,
        council_decision: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return SwarmGuard decision and adjusted size."""
        action = (decision or {}).get("action") or "HOLD"
        strategy = (decision or {}).get("strategy") or ""
        svs = float((decision or {}).get("svs") or 0.0)
        regime = (regime_snapshot or {}).get("regime") or ""
        # small-trade bypass guard
        notional = 0.0
        try:
            if latest_price and position_size:
                notional = float(position_size) * float(latest_price)
        except Exception:
            notional = 0.0
        is_small_trade = bool(self.small_trade_bypass and self.small_trade_usd and notional > 0 and notional <= self.small_trade_usd)
        small_cap = None
        try:
            if latest_price and self.small_trade_usd:
                small_cap = float(self.small_trade_usd) / float(latest_price)
        except Exception:
            small_cap = None

        # Overtrading caps
        ot = self._enforce_overtrading() if action in ("BUY", "SELL") else None
        if ot:
            return {"decision": "VETO", "reason": ot, "position_size": 0.0}

        # Rulebook enforcement (SVS + regime + caps)
        rulebook = None
        if action in ("BUY", "SELL"):
            try:
                rulebook = self._rulebook_enforce(council_decision, regime_snapshot)
                if rulebook and not rulebook.get("allowed", True):
                    return {"decision": "VETO", "reason": rulebook.get("reason", "RULEBOOK_DENY"), "position_size": 0.0, "rulebook": rulebook}
            except Exception:
                rulebook = None

        # Risk register / rulebook v2 enforcement (best-effort)
        evidence = self._compute_evidence(
            decision,
            position_size,
            latest_price,
            volumes,
            orderbook,
            exec_quality,
            regime_snapshot,
            proposals,
            council_decision=council_decision,
        )
        risk_eval = self._apply_risk_rules(evidence, position_size, latest_price)
        risk_detail = []
        try:
            for rid in (risk_eval.get("triggered") or []):
                risk_detail.append({
                    "rule_id": rid,
                    "severity": "VETO" if risk_eval.get("veto_reason") else "INFO",
                    "message": self._risk_message(rid),
                    "evidence_keys": list(evidence.keys()),
                })
        except Exception:
            risk_detail = []

        # Override stake requirement handling
        try:
            if risk_eval.get("stake_required"):
                stake_amt = int(risk_eval.get("stake_amount") or 0)
                if not self._buzz_client or not self._buzz_account or stake_amt <= 0:
                    return {
                        "decision": "VETO",
                        "reason": "VETO_OVERRIDE_NO_STAKE",
                        "position_size": 0.0,
                        "risk": {
                            "vetoed": True,
                            "triggered": risk_detail + [{
                                "rule_id": "SG-OVERRIDE-STAKE-01",
                                "severity": "VETO",
                                "message": "Override intent detected but no BUZZ stake can be locked; vetoing.",
                                "evidence_keys": ["override_attempt"],
                            }],
                            "evidence": evidence,
                        },
                        "evidence": evidence,
                    }
                try:
                    req_id = f"override-{int(time.time())}"
                    receipt = self._buzz_client.lock(
                        account=self._buzz_account,
                        amount=stake_amt,
                        reason="OVERRIDE",
                        request_id=req_id,
                    )
                    self._override_last_stake = {"amount": stake_amt, "ts": time.time(), "request_id": req_id}
                    risk_detail.append({
                        "rule_id": "SG-OVERRIDE-STAKE-01",
                        "severity": "INFO",
                        "message": f"Override stake locked ({stake_amt}).",
                        "evidence_keys": ["override_attempt"],
                        "receipt": receipt,
                    })
                except Exception:
                    return {
                        "decision": "VETO",
                        "reason": "VETO_OVERRIDE_NO_STAKE",
                        "position_size": 0.0,
                        "risk": {"vetoed": True, "triggered": risk_detail, "evidence": evidence},
                        "evidence": evidence,
                    }
        except Exception:
            pass

        # Override slash handling (best-effort)
        try:
            if risk_eval.get("slash_required"):
                amt = int(self._override_last_stake.get("amount") or 0)
                if self._buzz_client and self._buzz_account and amt > 0:
                    req_id = f"slash-{int(time.time())}"
                    receipt = self._buzz_client.slash(
                        account=self._buzz_account,
                        amount=amt,
                        reason="OVERRIDE_SLASH",
                        request_id=req_id,
                    )
                    risk_detail.append({
                        "rule_id": "SG-OVERRIDE-SLASH-01",
                        "severity": "VETO",
                        "message": "Override used in live mode; stake slashed.",
                        "evidence_keys": ["override_used_in_live_mode"],
                        "receipt": receipt,
                    })
                else:
                    return {
                        "decision": "VETO",
                        "reason": "VETO_OVERRIDE_NO_STAKE",
                        "position_size": 0.0,
                        "risk": {"vetoed": True, "triggered": risk_detail, "evidence": evidence},
                        "evidence": evidence,
                    }
        except Exception:
            pass
        if risk_eval.get("veto_reason"):
            if is_small_trade and small_cap:
                return {
                    "decision": "THROTTLE",
                    "reason": f"SMALL_TRADE_BYPASS_{risk_eval.get('veto_reason')}",
                    "position_size": min(position_size, small_cap),
                    "risk": {"vetoed": True, "triggered": risk_detail, "evidence": evidence},
                    "evidence": evidence,
                }
            return {
                "decision": "VETO",
                "reason": risk_eval.get("veto_reason"),
                "position_size": 0.0,
                "risk": {"vetoed": True, "triggered": risk_detail, "evidence": evidence},
                "evidence": evidence,
            }

        # Regime gating
        veto = self._regime_veto(regime, strategy, action)
        if veto:
            # decay worker weight on repeated regime mismatches
            w = self._weights.get(strategy, 1.0)
            w = max(self.weight_floor, w * self.weight_decay)
            self._weights[strategy] = w
            if is_small_trade and small_cap:
                return {"decision": "THROTTLE", "reason": f"SMALL_TRADE_BYPASS_{veto}", "position_size": min(position_size, small_cap)}
            return {"decision": "VETO", "reason": veto, "position_size": 0.0}

        # Spread/fee veto (use exec_quality spread if available)
        spread_pct = None
        try:
            if exec_quality and isinstance(exec_quality, dict):
                spread_pct = exec_quality.get("spread_pct")
            if spread_pct is not None:
                spread_pct = float(spread_pct)
                if spread_pct > self.spread_guard_pct:
                    return {"decision": "VETO", "reason": "SPREAD_TOO_WIDE", "position_size": 0.0}
        except Exception:
            pass

        # Expected net return check (proxy)
        try:
            expected_move = svs * self.expected_move_min
            fee_drag = (spread_pct or 0.0) + self.fee_buffer
            if expected_move <= fee_drag and action in ("BUY", "SELL"):
                w = self._weights.get(strategy, 1.0)
                w = max(self.weight_floor, w * self.weight_decay)
                self._weights[strategy] = w
                if is_small_trade and small_cap:
                    return {"decision": "THROTTLE", "reason": "SMALL_TRADE_BYPASS_FEE_DRAG", "position_size": min(position_size, small_cap)}
                return {"decision": "VETO", "reason": "FEE_DRAG", "position_size": 0.0}
        except Exception:
            pass

        # Consensus penalty (correlated failure guard)
        consensus_mult = 1.0
        try:
            if proposals:
                same_action = [p for p in proposals if (p.get("action") or "").upper() == action]
                if action in ("BUY", "SELL") and len(same_action) >= self.consensus_min:
                    consensus_mult = self.consensus_penalty
        except Exception:
            consensus_mult = 1.0
        # Apply diversity cap rule if triggered
        try:
            if risk_eval and "SG-DIVERSITY-CAP-01" in (risk_eval.get("triggered") or []):
                consensus_mult = min(consensus_mult, self.consensus_penalty)
        except Exception:
            pass

        # Apply worker weight decay multiplier
        weight = self._weights.get(strategy, 1.0)
        try:
            if risk_eval and "SG-WORKER-WEIGHT-DECAY-01" in (risk_eval.get("triggered") or []):
                weight = max(self.weight_floor, weight * self.weight_decay)
                self._weights[strategy] = weight
            if risk_eval and "SG-LEARNING-DECAY-01" in (risk_eval.get("triggered") or []):
                weight = max(self.weight_floor, weight * self.weight_decay)
                self._weights[strategy] = weight
        except Exception:
            pass
        adj_size = float(position_size) * float(weight) * float(consensus_mult)

        # Liquidity-aware cap
        avg_vol = None
        try:
            if volumes:
                avg_vol = sum(volumes[-60:]) / max(1, len(volumes[-60:]))
        except Exception:
            avg_vol = None

        best_bid_vol = None
        try:
            if orderbook and orderbook.get("bids"):
                best_bid_vol = sum([float(b[1]) for b in orderbook.get("bids", [])[:3]])
        except Exception:
            best_bid_vol = None

        wallet_cap = float(getattr(self.cfg, "max_position_base", 0.0) or 0.0)
        capped = self._liquidity_cap(adj_size, avg_vol, best_bid_vol, wallet_cap)

        # Apply rulebook caps (max_notional / max_position_pct) if available
        if rulebook and rulebook.get("permit") and latest_price:
            permit = rulebook.get("permit") or {}
            max_notional = permit.get("max_notional_usdt")
            max_pos_pct = permit.get("max_position_pct")
            try:
                cap_base = None
                if max_notional and latest_price:
                    cap_base = float(max_notional) / float(latest_price)
                if max_pos_pct:
                    equity_usd = float(base_free or 0.0) * float(latest_price or 0.0) + float(quote_free or 0.0)
                    cap_usd = equity_usd * float(max_pos_pct)
                    cap_base = min(cap_base, cap_usd / float(latest_price)) if cap_base else (cap_usd / float(latest_price))
                if cap_base is not None:
                    capped = min(capped, cap_base)
            except Exception:
                pass
        # Apply depth cap if triggered
        try:
            if risk_eval and risk_eval.get("cap_size") is not None:
                capped = min(capped, float(risk_eval.get("cap_size")))
        except Exception:
            pass
        if capped <= 0:
            if is_small_trade and small_cap:
                return {"decision": "THROTTLE", "reason": "SMALL_TRADE_BYPASS_LIQUIDITY", "position_size": min(position_size, small_cap)}
            return {"decision": "VETO", "reason": "LIQUIDITY_TOO_THIN", "position_size": 0.0}
        if capped < position_size:
            out = {"decision": "THROTTLE", "reason": "LIQUIDITY_CAP", "position_size": capped, "weight": weight, "consensus_mult": consensus_mult}
            if rulebook:
                out["rulebook"] = rulebook
            return out

        out = {
            "decision": "APPROVE",
            "reason": "OK",
            "position_size": capped,
            "weight": weight,
            "consensus_mult": consensus_mult,
            "risk": {"vetoed": False, "triggered": risk_detail, "evidence": evidence},
            "evidence": evidence,
        }
        if rulebook:
            out["rulebook"] = rulebook
        return out

    def emit(self, payload: Dict[str, Any]):
        try:
            if self.coordinator:
                self.coordinator.share_data("buzz.swarmguard.decision", payload)
        except Exception:
            pass
