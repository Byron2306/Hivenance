import time
import threading
import logging
import argparse
from typing import Any, Dict, List, Optional

import requests
import ipaddress
import socket
from urllib.parse import urlparse

DEFAULT_MIN_SCORE = 0.55


class OpenClawAgent:
    """Minimal local OpenClaw agent for integration and testing.

    - Accepts a `coordinator` reference (optional) so it can publish status
      to the coordinator's `data_cache` or use existing IPC channels.
    - Implements a simple heartbeat loop and graceful stop.
    """

    def __init__(self, coordinator=None, cfg=None):
        self.coordinator = coordinator
        self.cfg = cfg or {}
        self.chat_endpoint = self.cfg.get("openclaw_chat_endpoint") or ""
        self.chat_token = self.cfg.get("openclaw_chat_token") or ""
        self.chat_format = self.cfg.get("openclaw_chat_format") or "hf_space"
        self._stop = threading.Event()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self.run, name="OpenClawAgent", daemon=True)
        self.thread.start()

    def run(self):
        logging.info("OpenClawAgent starting")
        try:
            while not self._stop.is_set():
                # Heartbeat: publish to coordinator data cache if available
                try:
                    if self.coordinator and hasattr(self.coordinator, 'data_cache'):
                        now_ms = int(time.time() * 1000)
                        payload = {'agent': 'openclaw', 'status': 'ok', 'ts': now_ms}
                        self.coordinator.data_cache['openclaw.heartbeat'] = payload
                        if hasattr(self.coordinator, 'share_data'):
                            evt = {
                                'buzz': {'type': 'buzz.agent.heartbeat', 'source': 'AUTONOMOUS', 'ts': now_ms},
                                'payload': payload,
                            }
                            self.coordinator.share_data('buzz.agent.heartbeat', evt)
                except Exception:
                    logging.exception("OpenClawAgent failed to publish heartbeat")
                # TODO: replace with real agent work (network calls, strategy, etc.)
                time.sleep(float(self.cfg.get('heartbeat_sec', 5)))
        except Exception:
            logging.exception("OpenClawAgent encountered an error")
        logging.info("OpenClawAgent stopped")

    def stop(self):
        self._stop.set()
        if self.thread:
            self.thread.join(timeout=2)

    def decide(
        self,
        council_decision: Optional[Dict[str, Any]] = None,
        proposals: Optional[List[Dict[str, Any]]] = None,
        regime_snapshot: Optional[Dict[str, Any]] = None,
        cfg: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Generate an autonomous action using council feedback and hive proposals.

        Prefers council_decision when provided (BUY/SELL above min score, REJECT
        becomes HOLD). Falls back to the strongest proposal above the minimum score.
        Returns a decision dict with action, rationale, score (if available), and
        approved flag for downstream gating.
        """
        min_score = DEFAULT_MIN_SCORE
        try:
            min_score = float(getattr(cfg, "openclaw_autonomy_min_score", min_score) or min_score)
        except Exception:
            min_score = DEFAULT_MIN_SCORE

        if council_decision:
            try:
                direction = str(council_decision.get("direction") or "").upper()
                score = float(council_decision.get("score") or 0.0)
                recommendation = str(council_decision.get("recommendation") or "").upper()
                if recommendation == "REJECT":
                    return {
                        "action": "HOLD",
                        "strategy": "OPENCLAW",
                        "rationale": "COUNCIL_REJECT",
                        "signal_id": council_decision.get("request_id"),
                        "regime": regime_snapshot,
                        "score": score,
                        "approved": False,
                    }
                if direction in ("BUY", "SELL") and score >= min_score:
                    return {
                        "action": direction,
                        "strategy": "OPENCLAW",
                        "rationale": f"COUNCIL_{recommendation} score={score:.2f}",
                        "signal_id": council_decision.get("request_id"),
                        "regime": regime_snapshot,
                        "score": score,
                        "approved": True,
                    }
                if direction in ("BUY", "SELL") and score < min_score:
                    return {
                        "action": "HOLD",
                        "strategy": "OPENCLAW",
                        "rationale": f"COUNCIL_BELOW_THRESHOLD score={score:.2f}",
                        "signal_id": council_decision.get("request_id"),
                        "regime": regime_snapshot,
                        "score": score,
                        "approved": False,
                    }
            except Exception:
                pass

        best = None
        if proposals:
            for proposal in proposals:
                try:
                    action = str(proposal.get("action") or "HOLD").upper()
                    if action not in ("BUY", "SELL"):
                        continue
                    strength = float(proposal.get("signal_strength") or 0.0)
                    if strength < min_score:
                        continue
                    if not best:
                        best = proposal
                        continue
                    best_strength = float(best.get("signal_strength") or 0.0)
                    if strength > best_strength:
                        best = proposal
                        continue
                    if strength == best_strength:
                        ts = float(proposal.get("ts") or 0.0)
                        best_ts = float(best.get("ts") or 0.0)
                        if ts > best_ts:
                            best = proposal
                except Exception:
                    continue

        if best:
            strategy_name = best.get("strategy") or "UNKNOWN"
            return {
                "action": str(best.get("action") or "HOLD").upper(),
                "strategy": "OPENCLAW",
                "rationale": f"HIVE_PROPOSAL {strategy_name}",
                "signal_id": best.get("signal_id"),
                "regime": regime_snapshot,
                "approved": True,
            }

        return {
            "action": "HOLD",
            "strategy": "OPENCLAW",
            "rationale": "HIVE_NO_BUY_SELL",
            "signal_id": None,
            "regime": regime_snapshot,
            "approved": False,
        }

    def chat(
        self,
        message: str,
        endpoint: Optional[str],
        token: Optional[str] = None,
        timeout: int = 30,
        format_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a chat message to a Hugging Face Space endpoint.

        Returns {"response": str, "raw": Any} on success or {"error": code, ...} on failure.
        Supported format_type: "hf_space" (Gradio /predict data payload) or "hf_inference"
        (standard {"inputs": message} payload).
        """
        endpoint = endpoint or self.chat_endpoint
        if not endpoint:
            return {"error": "endpoint_not_configured"}
        if not message:
            return {"error": "message_required"}
        if not self._is_valid_endpoint(endpoint):
            return {"error": "invalid_endpoint"}
        format_type = (format_type or self.chat_format or "hf_space").lower()
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        payload = self._build_payload(message, format_type)
        try:
            resp = requests.post(endpoint, json=payload, headers=headers, timeout=timeout, verify=True)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            return {"error": "request_failed", "detail": str(exc)}

        text = self._extract_response_text(data)
        return {"response": text or "", "raw": data}

    def _build_payload(self, message: str, format_type: str) -> Dict[str, Any]:
        if format_type == "hf_space":
            return {"data": [message]}
        return {"inputs": message}

    def _extract_response_text(self, data: Any) -> Optional[str]:
        if isinstance(data, dict):
            if "generated_text" in data:
                return data.get("generated_text")
            if "data" in data:
                items = data.get("data")
                if isinstance(items, list) and items:
                    return str(items[0])
            if "output" in data:
                return data.get("output")
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                return first.get("generated_text") or first.get("output") or str(first)
            return str(first)
        return None

    def _is_valid_endpoint(self, endpoint: str) -> bool:
        try:
            parsed = urlparse(endpoint)
            if parsed.scheme != "https":
                return False
            if parsed.port not in (None, 443):
                return False
            host = parsed.hostname or ""
            if not host:
                return False
            if host in ("localhost", "127.0.0.1", "::1"):
                return False
            try:
                ip = ipaddress.ip_address(host)
            except ValueError:
                ip = None
            if ip:
                if ip.is_private or ip.is_loopback or ip.is_link_local:
                    return False
                return True
            if not (host.endswith(".hf.space") or host.endswith("huggingface.co")):
                return False
            try:
                resolved = socket.getaddrinfo(host, None)
                for info in resolved:
                    addr = info[4][0]
                    try:
                        ip = ipaddress.ip_address(addr)
                        if ip.is_private or ip.is_loopback or ip.is_link_local:
                            return False
                    except ValueError:
                        continue
            except Exception:
                return False
            return True
        except Exception:
            return False


def main():
    parser = argparse.ArgumentParser(description="Run OpenClawAgent standalone")
    parser.add_argument('--heartbeat', type=float, default=5.0, help='seconds between heartbeats')
    parser.add_argument('--once', action='store_true', help='run one heartbeat then exit')
    args = parser.parse_args()

    agent = OpenClawAgent(cfg={'heartbeat_sec': args.heartbeat})
    if args.once:
        try:
            # single iteration for health checks
            if hasattr(agent, 'coordinator') and agent.coordinator and hasattr(agent.coordinator, 'data_cache'):
                agent.coordinator.data_cache['openclaw.heartbeat'] = {'ts': int(time.time() * 1000), 'status': 'ok'}
            print('OpenClawAgent single heartbeat emitted')
        except Exception:
            print('OpenClawAgent single heartbeat failed')
        return

    try:
        agent.run()
    except KeyboardInterrupt:
        agent.stop()


if __name__ == '__main__':
    main()
