from __future__ import annotations
import json
import time
import sqlite3
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request, HTTPException
import os
from pydantic import BaseModel, Field
from .db import BuzzDB
from .auth import verify_signature

# Configure via env in real deployment
HMAC_SHARED_SECRET = os.environ.get("BUZZ_SHARED_SECRET", "") or os.environ.get("HIVE_SHARED_SECRET", "") or "CHANGE_ME"
db = BuzzDB("buzzservice.db")

app = FastAPI(title="BuzzService v1", version="1.0")


class LockReq(BaseModel):
    account: str
    amount: int
    reason: str = ""
    request_id: str = Field(..., description="Idempotency key")


class ReleaseReq(BaseModel):
    account: str
    amount: int
    reason: str = ""
    request_id: str = Field(..., description="Idempotency key")


class SlashReq(BaseModel):
    account: str
    amount: int
    reason: str = ""
    request_id: str = Field(..., description="Idempotency key")


class CreditReq(BaseModel):
    account: str
    amount: int
    reason: str = ""
    request_id: str = Field(..., description="Idempotency key")


async def require_hmac(req: Request) -> bytes:
    raw = await req.body()
    sig = req.headers.get("x-hive-sig", "")
    svc = req.headers.get("x-hive-service", "")
    if not sig or not svc:
        raise HTTPException(401, "Missing auth headers")
    if not verify_signature(raw, sig, HMAC_SHARED_SECRET):
        raise HTTPException(401, "Invalid signature")
    return raw


def idem_return_or_none(request_id: str) -> Optional[Dict[str, Any]]:
    return db.idem_get(request_id)


def idem_store(request_id: str, response: Dict[str, Any]) -> Dict[str, Any]:
    try:
        db.idem_put_atomic(request_id, response, int(time.time()))
    except sqlite3.IntegrityError:
        existing = db.idem_get(request_id)
        return existing if existing else response
    return response


@app.get("/v1/accounts/{account}")
def get_account(account: str):
    return {"type": "ACCOUNT", **db.get_account(account)}


@app.get("/v1/ledger/{account}")
def get_ledger(account: str, limit: int = 100):
    return {"type": "LEDGER", "account": account, "entries": db.get_ledger(account, limit=limit)}

@app.get("/")
def root():
    return {
        "service": "BuzzService",
        "version": "1.0",
        "endpoints": [
            "/v1/accounts/{account}",
            "/v1/ledger/{account}",
            "/v1/stakes/lock",
            "/v1/stakes/release",
            "/v1/stakes/slash",
            "/v1/admin/credit",
        ],
    }

@app.get("/buzz")
def buzz_alias():
    return {"detail": "Use the UI at /buzz on the main app (port 5000)."}


@app.post("/v1/admin/credit")
async def admin_credit(req: Request):
    raw = await require_hmac(req)
    data = CreditReq(**json.loads(raw.decode("utf-8")))

    existing = idem_return_or_none(data.request_id)
    if existing is not None:
        return existing

    try:
        bal = db.credit(data.account, data.amount, request_id=data.request_id, ref=data.reason)
    except Exception as e:
        raise HTTPException(400, str(e))

    resp = {
        "type": "CREDIT_RECEIPT",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "account": data.account,
        "amount": data.amount,
        "reason": data.reason,
        "balance": bal,
        "request_id": data.request_id
    }
    return idem_store(data.request_id, resp)


@app.post("/v1/stakes/lock")
async def lock_stake(req: Request):
    raw = await require_hmac(req)
    data = LockReq(**json.loads(raw.decode("utf-8")))

    existing = idem_return_or_none(data.request_id)
    if existing is not None:
        return existing

    try:
        bal = db.lock(data.account, data.amount, request_id=data.request_id, ref=data.reason)
    except Exception as e:
        raise HTTPException(400, str(e))

    resp = {
        "type": "STAKE_LOCKED",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "account": data.account,
        "amount": data.amount,
        "reason": data.reason,
        "balance": bal,
        "lock_id": f"lock-{data.request_id}",
        "request_id": data.request_id
    }
    return idem_store(data.request_id, resp)


@app.post("/v1/stakes/release")
async def release_stake(req: Request):
    raw = await require_hmac(req)
    data = ReleaseReq(**json.loads(raw.decode("utf-8")))

    existing = idem_return_or_none(data.request_id)
    if existing is not None:
        return existing

    try:
        bal = db.release(data.account, data.amount, request_id=data.request_id, ref=data.reason)
    except Exception as e:
        raise HTTPException(400, str(e))

    resp = {
        "type": "STAKE_RELEASED",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "account": data.account,
        "amount": data.amount,
        "reason": data.reason,
        "balance": bal,
        "lock_id": f"lock-{data.request_id}",
        "request_id": data.request_id
    }
    return idem_store(data.request_id, resp)


@app.post("/v1/stakes/slash")
async def slash_stake(req: Request):
    raw = await require_hmac(req)
    data = SlashReq(**json.loads(raw.decode("utf-8")))

    existing = idem_return_or_none(data.request_id)
    if existing is not None:
        return existing

    try:
        bal = db.slash(data.account, data.amount, request_id=data.request_id, ref=data.reason)
    except Exception as e:
        raise HTTPException(400, str(e))

    resp = {
        "type": "STAKE_SLASHED",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "account": data.account,
        "amount": data.amount,
        "reason": data.reason,
        "balance": bal,
        "lock_id": f"lock-{data.request_id}",
        "request_id": data.request_id
    }
    return idem_store(data.request_id, resp)
