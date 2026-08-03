from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Tuple

from pydantic import BaseModel, Field, ValidationError


CRITICAL_TYPES = {
    "buzz.kill.trigger",
    "buzz.security.event",
    "buzz.config.error",
    "buzz.config.rollback",
    "buzz.system.error",
}


class BuzzEnvelope(BaseModel):
    type: str
    source: str = "SYSTEM"
    ts: int = Field(default_factory=lambda: int(time.time() * 1000))
    seq: int | None = None
    id: str | None = None
    correlation_id: str | None = None
    severity: str = "info"
    phoenix_phase: int | None = None


class EventSpineAgent:
    """Typed event envelope boundary for buzz events."""

    def __init__(self):
        self.validated_count = 0
        self.invalid_count = 0
        self.critical_count = 0
        self.last_error = ""
        self.last_event_type = ""
        self.last_critical = {}

    def normalize(self, key: str, event: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        alerts: List[Dict[str, Any]] = []
        try:
            if not key.startswith("buzz.") or not isinstance(event, dict):
                return event, alerts
            buzz = dict(event.get("buzz") or {})
            payload = event.get("payload") if "payload" in event else {}
            buzz.setdefault("type", key)
            buzz.setdefault("source", self._source_from_key(key))
            buzz.setdefault("ts", int(time.time() * 1000))
            buzz.setdefault("severity", self._severity_for(buzz.get("type"), payload))
            buzz.setdefault("correlation_id", self._correlation_id(buzz, payload))
            buzz.setdefault("id", self._event_id(buzz, payload))
            envelope = BuzzEnvelope(**buzz)
            out = dict(event)
            out["buzz"] = envelope.dict(exclude_none=True)
            out.setdefault("payload", payload if isinstance(payload, dict) else {"value": payload})
            self.validated_count += 1
            self.last_event_type = envelope.type
            if envelope.type in CRITICAL_TYPES or envelope.severity in ("error", "critical"):
                self.critical_count += 1
                self.last_critical = out
                alerts.append(self._critical_alert(out))
            return out, alerts
        except ValidationError as e:
            self.invalid_count += 1
            self.last_error = str(e)
            alert = self._invalid_alert(key, event, self.last_error)
            return event, [alert]
        except Exception as e:
            self.invalid_count += 1
            self.last_error = str(e)
            alert = self._invalid_alert(key, event, self.last_error)
            return event, [alert]

    def status(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "validated_count": self.validated_count,
            "invalid_count": self.invalid_count,
            "critical_count": self.critical_count,
            "last_event_type": self.last_event_type,
            "last_error": self.last_error,
        }

    def _source_from_key(self, key: str) -> str:
        parts = str(key or "").split(".")
        return parts[1].upper() if len(parts) > 1 and parts[1] else "SYSTEM"

    def _severity_for(self, typ: Any, payload: Any) -> str:
        if isinstance(payload, dict) and payload.get("severity"):
            return str(payload.get("severity")).lower()
        typ = str(typ or "")
        if typ in ("buzz.kill.trigger", "buzz.config.error", "buzz.system.error"):
            return "critical"
        if typ == "buzz.security.event":
            return "error"
        if typ.endswith(".alert"):
            return "warning"
        return "info"

    def _correlation_id(self, buzz: Dict[str, Any], payload: Any) -> str:
        if buzz.get("correlation_id"):
            return str(buzz.get("correlation_id"))
        if isinstance(payload, dict):
            for key in (
                "observation_id", "forecast_id", "simulation_id", "validation_run_id",
                "champion_id", "freeze_id", "shadow_intent_id", "canary_intent_id",
                "intent_id", "client_order_id", "order_id", "fill_id", "approval_id",
                "proposal_id", "incident_id", "request_id", "run_id",
            ):
                if payload.get(key):
                    return str(payload.get(key))
        return str(buzz.get("seq") or buzz.get("ts") or int(time.time() * 1000))

    def _event_id(self, buzz: Dict[str, Any], payload: Any) -> str:
        if buzz.get("id"):
            return str(buzz.get("id"))
        raw = json.dumps(
            {
                "type": buzz.get("type"),
                "source": buzz.get("source"),
                "ts": buzz.get("ts"),
                "seq": buzz.get("seq"),
                "payload": payload,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _critical_alert(self, event: Dict[str, Any]) -> Dict[str, Any]:
        buzz = event.get("buzz") or {}
        payload = event.get("payload") or {}
        reason = ""
        if isinstance(payload, dict):
            reason = payload.get("reason") or payload.get("details") or payload.get("error") or ""
        alert_buzz = {
            "type": "buzz.system.alert",
            "source": "EVENT_SPINE",
            "ts": int(time.time() * 1000),
            "severity": buzz.get("severity") or "warning",
            "correlation_id": buzz.get("correlation_id"),
        }
        alert_payload = {
            "severity": buzz.get("severity") or "warning",
            "type": buzz.get("type") or "buzz.unknown",
            "details": reason or f"Critical event observed: {buzz.get('type')}",
            "recommended_action": "review_event_spine_alert",
            "event_id": buzz.get("id"),
        }
        alert_buzz["id"] = self._event_id(alert_buzz, alert_payload)
        return {
            "buzz": alert_buzz,
            "payload": alert_payload,
        }

    def _invalid_alert(self, key: str, event: Dict[str, Any], error: str) -> Dict[str, Any]:
        alert_buzz = {
            "type": "buzz.config.error",
            "source": "EVENT_SPINE",
            "ts": int(time.time() * 1000),
            "severity": "error",
            "correlation_id": key,
        }
        alert_payload = {
            "severity": "error",
            "type": "event_validation_failed",
            "details": error,
            "recommended_action": "inspect_event_publisher",
            "event_key": key,
            "event_preview": str(event)[:500],
        }
        alert_buzz["id"] = self._event_id(alert_buzz, alert_payload)
        return {
            "buzz": alert_buzz,
            "payload": alert_payload,
        }
