from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from dataclasses import asdict
from typing import Any, Mapping

from .contracts import (
    ForwardRelativeForecast,
    RelativeMarketState,
    ResearchCouncilReceipt,
    RELATIVE_VALUE_AUTHORITY,
)
from .pair_lab import PairDiagnostics


SYSTEM_INSTRUCTION = """You are a research-only quantitative reviewer inside Hivenance Phoenix.
Review the supplied deterministic evidence. Do not issue BUY, SELL, order, position-size,
capital-allocation, promotion, or execution instructions. Return only JSON with these keys:
contradictions, missing_evidence, alternative_hypotheses, analogous_slices,
suggested_falsification_tests, explanation_confidence.
All list values must be arrays of short strings. explanation_confidence must be 0..1.
Your job is to challenge the evidence, not to authorize action."""


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _strings(value: Any, *, limit: int = 12) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    out = []
    for item in value[:limit]:
        text = str(item).strip()
        if text:
            out.append(text[:500])
    return tuple(out)


class LocalOllamaResearchCouncil:
    """Bounded local advisory inference over deterministic evidence.

    Ollama output is untrusted explanatory evidence. It cannot mutate thresholds,
    promote a model, create order intent, or grant execution authority.
    """

    def __init__(
        self,
        *,
        model: str = "qwen3.5:9b",
        endpoint: str = "http://127.0.0.1:11434/api/chat",
        timeout_sec: float = 20.0,
    ) -> None:
        self.model = str(model)
        self.endpoint = str(endpoint)
        self.timeout_sec = max(1.0, float(timeout_sec))

    def evidence_packet(
        self,
        *,
        state: RelativeMarketState,
        diagnostics: PairDiagnostics,
        forecast: ForwardRelativeForecast,
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "schema": "hivenance_relative_value_council_input_v1",
            "authority": RELATIVE_VALUE_AUTHORITY,
            "state": state.to_dict(),
            "relationship": diagnostics.to_dict(),
            "forecast": forecast.to_dict(),
            "extra_research_context": dict(extra or {}),
            "forbidden_authority": {
                "execution": True,
                "promotion": True,
                "capital_allocation": True,
                "threshold_mutation": True,
            },
        }

    def _call_ollama(self, packet: dict[str, Any]) -> str:
        body = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {
                    "role": "user",
                    "content": json.dumps(packet, sort_keys=True, separators=(",", ":")),
                },
            ],
            "options": {"temperature": 0.1},
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
        message = payload.get("message") if isinstance(payload, dict) else None
        if isinstance(message, dict):
            return str(message.get("content") or "")
        return str(payload.get("response") or "") if isinstance(payload, dict) else ""

    def review(
        self,
        *,
        state: RelativeMarketState,
        diagnostics: PairDiagnostics,
        forecast: ForwardRelativeForecast,
        extra: Mapping[str, Any] | None = None,
    ) -> ResearchCouncilReceipt:
        packet = self.evidence_packet(
            state=state,
            diagnostics=diagnostics,
            forecast=forecast,
            extra=extra,
        )
        subject_id = forecast.forecast_id
        created_at_ms = int(time.time() * 1000)
        try:
            raw = self._call_ollama(packet)
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("ollama response is not a JSON object")
            confidence = parsed.get("explanation_confidence")
            confidence_value = None
            if confidence is not None:
                confidence_value = max(0.0, min(1.0, float(confidence)))
            return ResearchCouncilReceipt(
                schema="hivenance_relative_value_research_council_v1",
                receipt_id="rvc_" + _digest(
                    {"subject": subject_id, "created_at_ms": created_at_ms, "raw": raw}
                ).split(":", 1)[1][:24],
                created_at_ms=created_at_ms,
                subject_id=subject_id,
                adviser_model=f"ollama/{self.model}",
                contradictions=_strings(parsed.get("contradictions")),
                missing_evidence=_strings(parsed.get("missing_evidence")),
                alternative_hypotheses=_strings(parsed.get("alternative_hypotheses")),
                analogous_slices=_strings(parsed.get("analogous_slices")),
                suggested_falsification_tests=_strings(parsed.get("suggested_falsification_tests")),
                explanation_confidence=confidence_value,
                raw_response_digest=_digest(raw),
                authority=RELATIVE_VALUE_AUTHORITY,
                execution_eligible=False,
                promotion_eligible=False,
            )
        except Exception as exc:
            # Local inference is optional. Failure must degrade to an inspectable
            # advisory receipt, never fail or mutate the deterministic pipeline.
            return ResearchCouncilReceipt(
                schema="hivenance_relative_value_research_council_v1",
                receipt_id="rvc_" + _digest(
                    {"subject": subject_id, "created_at_ms": created_at_ms, "error": type(exc).__name__}
                ).split(":", 1)[1][:24],
                created_at_ms=created_at_ms,
                subject_id=subject_id,
                adviser_model=f"ollama/{self.model}",
                contradictions=(),
                missing_evidence=(f"local_adviser_unavailable:{type(exc).__name__}",),
                alternative_hypotheses=(),
                analogous_slices=(),
                suggested_falsification_tests=(),
                explanation_confidence=None,
                raw_response_digest=None,
                authority=RELATIVE_VALUE_AUTHORITY,
                execution_eligible=False,
                promotion_eligible=False,
            )
