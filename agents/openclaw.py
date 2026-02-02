import time
import threading
import logging
import argparse
from typing import Any, Dict, List, Optional

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
