from __future__ import annotations

import hmac
import hashlib
import json
import os
import time
import sqlite3
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from buzzservice.client import BuzzServiceClient
from .enforce import enforce
from .idempotency_db import IdempotencyDB
from .rules_v1 import load_rules


HMAC_SHARED_SECRET = os.environ.get("SWARMGUARD_HMAC_SECRET", "")
if not HMAC_SHARED_SECRET or HMAC_SHARED_SECRET == "CHANGE_ME":
    raise RuntimeError("SWARMGUARD_HMAC_SECRET is required and may not use the placeholder value")
BUZZ_BASE_URL = os.environ.get("BUZZ_BASE_URL", "http://localhost:9009")
BUZZ_ACCOUNT = os.environ.get("BUZZ_ACCOUNT", "hivenance-system")
BUZZ_SERVICE_NAME = os.environ.get("BUZZ_SERVICE_NAME", "swarmguard")
BUZZ_FAIL_OPEN = os.environ.get("BUZZ_FAIL_OPEN", "0") == "1"
IDEMPOTENCY_DB_PATH = os.environ.get("SWARMGUARD_DB", "swarmguard.db")
RULES_PATH = os.environ.get("SWARMGUARD_RULES_PATH", "config/swarmguard_rules_v1.json")

app = FastAPI(title="SwarmGuard v1", version="1.0")
rules = load_rules(RULES_PATH)
idem = IdempotencyDB(IDEMPOTENCY_DB_PATH)
buzz = BuzzServiceClient(BUZZ_BASE_URL, HMAC_SHARED_SECRET, service_name=BUZZ_SERVICE_NAME)


class OracleRegime(BaseModel):
    name: str
    confidence: float = 0.5


class EnforceReq(BaseModel):
    request_id: str = Field(..., description="Idempotency key for this enforce call")
    symbol: str
    council_decision: Dict[str, Any]
    oracle_regime: OracleRegime
    action: str = "PLACE_ORDER"
    risk: Optional[Dict[str, Any]] = None


def _default_risk_metrics() -> Dict[str, Any]:
    return {
        "order_unconfirmed_ms": 0,
        "api_failures_60s": 0,
        "override_attempt": False,
        "override_reason": "",
        "alpha_age_minutes": 0,
        "worker_loss_streak": 0,
    }


def _merge_risk(req_risk: Optional[Dict[str, Any]], council: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    metrics = _default_risk_metrics()
    if req_risk and isinstance(req_risk, dict):
        metrics.update(req_risk.get("metrics", {}) or {})
    if council and isinstance(council, dict):
        c_risk = (council.get("risk") or {}).get("metrics") or {}
        for k, v in c_risk.items():
            metrics.setdefault(k, v)
    return metrics


def _verify_hmac(body_bytes: bytes, signature_hex: str) -> None:
    if not signature_hex:
        raise HTTPException(status_code=401, detail="Missing auth signature")
    mac = hmac.new(HMAC_SHARED_SECRET.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, signature_hex):
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")


@app.post("/rules/enforce")
async def rules_enforce(req: Request):
    raw = await req.body()
    sig = req.headers.get("x-hive-sig", "")
    svc = req.headers.get("x-hive-service", "")
    if not sig or not svc:
        raise HTTPException(status_code=401, detail="Missing auth headers")
    _verify_hmac(raw, sig)

    data = json.loads(raw.decode("utf-8"))
    payload = EnforceReq(**data)

    existing = idem.get(payload.request_id)
    if existing is not None:
        return existing

    allowed, permit, reasons = enforce(
        rules=rules,
        council=payload.council_decision,
        oracle=payload.oracle_regime.model_dump(),
    )
    risk_metrics = _merge_risk(payload.risk, payload.council_decision)

    result: Dict[str, Any] = {
        "type": "ENFORCEMENT_RESULT",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(time.time()))),
        "symbol": payload.symbol,
        "allowed": allowed,
        "permit": permit if allowed else None,
        "reason_codes": reasons,
        "request_id": payload.request_id,
        "risk": {
            "triggered": [],
            "vetoed": False if allowed else True,
            "evidence": risk_metrics,
        },
    }

    if allowed:
        rec = str(payload.council_decision.get("recommendation", "ALLOW_SMALL"))
        stake_amount = int(rules.get("buzz_staking", {}).get(rec, 0))
        stake_req_id = f"buzz-{payload.request_id}"
        try:
            receipt = buzz.lock(BUZZ_ACCOUNT, stake_amount, rec, stake_req_id)
            result["buzz"] = {
                "stake_required": True,
                "stake_amount": stake_amount,
                "stake_reason": rec,
                "ledger_request_id": stake_req_id,
                "receipt": receipt,
            }
        except Exception as exc:
            if not BUZZ_FAIL_OPEN:
                raise HTTPException(status_code=503, detail=f"BuzzService unavailable: {exc}")
            result["buzz"] = {
                "stake_required": True,
                "stake_amount": stake_amount,
                "stake_reason": rec,
                "ledger_request_id": stake_req_id,
                "receipt": {"status": "deferred", "error": str(exc)},
            }

    try:
        idem.put_atomic(payload.request_id, result, int(time.time()))
    except sqlite3.IntegrityError:
        stored = idem.get(payload.request_id)
        return stored if stored else result

    return result
