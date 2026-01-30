from __future__ import annotations
import json
import requests
from typing import Dict, Any
from .auth import sign_body


class BuzzServiceClient:
    def __init__(self, base_url: str, shared_secret: str, service_name: str = "swarmguard", timeout: float = 3.0):
        self.base_url = base_url.rstrip("/")
        self.shared_secret = shared_secret
        self.service_name = service_name
        self.timeout = timeout

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        sig = sign_body(body, self.shared_secret)
        headers = {"x-hive-service": self.service_name, "x-hive-sig": sig, "content-type": "application/json"}
        r = requests.post(self.base_url + path, data=body, headers=headers, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def lock(self, account: str, amount: int, reason: str, request_id: str) -> Dict[str, Any]:
        return self._post("/v1/stakes/lock", {"account": account, "amount": amount, "reason": reason, "request_id": request_id})

    def release(self, account: str, amount: int, reason: str, request_id: str) -> Dict[str, Any]:
        return self._post("/v1/stakes/release", {"account": account, "amount": amount, "reason": reason, "request_id": request_id})

    def slash(self, account: str, amount: int, reason: str, request_id: str) -> Dict[str, Any]:
        return self._post("/v1/stakes/slash", {"account": account, "amount": amount, "reason": reason, "request_id": request_id})

    def admin_credit(self, account: str, amount: int, reason: str, request_id: str) -> Dict[str, Any]:
        return self._post("/v1/admin/credit", {"account": account, "amount": amount, "reason": reason, "request_id": request_id})
