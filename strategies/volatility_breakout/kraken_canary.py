from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
import urllib.parse
from typing import Any, Mapping, Optional

import requests


class KrakenApiError(RuntimeError):
    pass


class KrakenRestClient:
    """Small, explicit Kraken Spot REST client for the isolated canary plane.

    Credentials are accepted only by constructor and are never serialized. The
    caller owns policy and persistence. This client only implements the narrow
    endpoints needed for validation, reconciliation, IOC orders and dead-man
    cancellation.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        base_url: str = "https://api.kraken.com",
        timeout_sec: float = 10.0,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.api_key = str(api_key or "").strip()
        self.api_secret = str(api_secret or "").strip()
        if not self.api_key or not self.api_secret:
            raise ValueError("Kraken API key and secret are required")
        try:
            base64.b64decode(self.api_secret)
        except Exception as exc:
            raise ValueError("Kraken API secret must be base64 encoded") from exc
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = float(timeout_sec)
        self.session = session or requests.Session()
        self._nonce_lock = threading.Lock()
        self._last_nonce = 0

    def _nonce(self) -> int:
        with self._nonce_lock:
            candidate = int(time.time_ns() // 1_000_000)
            self._last_nonce = max(candidate, self._last_nonce + 1)
            return self._last_nonce

    def _sign(self, path: str, payload: Mapping[str, Any]) -> str:
        encoded = urllib.parse.urlencode(payload)
        nonce = str(payload["nonce"])
        digest = hashlib.sha256((nonce + encoded).encode("utf-8")).digest()
        message = path.encode("utf-8") + digest
        secret = base64.b64decode(self.api_secret)
        return base64.b64encode(hmac.new(secret, message, hashlib.sha512).digest()).decode("ascii")

    def public(self, path: str, params: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        response = self.session.get(
            f"{self.base_url}{path}", params=dict(params or {}), timeout=self.timeout_sec
        )
        response.raise_for_status()
        body = response.json()
        errors = body.get("error") or []
        if errors:
            raise KrakenApiError("; ".join(map(str, errors)))
        return body.get("result") or {}

    def private(self, path: str, payload: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        body = dict(payload or {})
        body["nonce"] = self._nonce()
        headers = {
            "API-Key": self.api_key,
            "API-Sign": self._sign(path, body),
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Hivenance-Phoenix-Phase6/1.0",
        }
        response = self.session.post(
            f"{self.base_url}{path}", data=body, headers=headers, timeout=self.timeout_sec
        )
        response.raise_for_status()
        parsed = response.json()
        errors = parsed.get("error") or []
        if errors:
            raise KrakenApiError("; ".join(map(str, errors)))
        return parsed.get("result") or {}

    def system_status(self) -> dict[str, Any]:
        return self.public("/0/public/SystemStatus")

    def asset_pairs(self, pair: str) -> dict[str, Any]:
        return self.public("/0/public/AssetPairs", {"pair": pair})

    def api_key_info(self) -> dict[str, Any]:
        return self.private("/0/private/GetApiKeyInfo")

    def balances(self) -> dict[str, Any]:
        return self.private("/0/private/Balance")

    def open_orders(self) -> dict[str, Any]:
        return self.private("/0/private/OpenOrders", {"trades": "true"})

    def trades_history(self, *, start: Optional[float] = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": "all", "trades": "true"}
        if start is not None:
            payload["start"] = str(int(start))
        return self.private("/0/private/TradesHistory", payload)

    def query_orders(self, txids: list[str]) -> dict[str, Any]:
        if not txids:
            return {}
        return self.private("/0/private/QueryOrders", {"txid": ",".join(txids), "trades": "true"})

    def validate_order(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = dict(payload)
        body["validate"] = "true"
        return self.private("/0/private/AddOrder", body)

    def add_order(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = dict(payload)
        body.pop("validate", None)
        return self.private("/0/private/AddOrder", body)

    def cancel_order(self, txid: str) -> dict[str, Any]:
        return self.private("/0/private/CancelOrder", {"txid": txid})

    def cancel_all(self) -> dict[str, Any]:
        return self.private("/0/private/CancelAll")

    def cancel_all_after(self, timeout_sec: int) -> dict[str, Any]:
        return self.private("/0/private/CancelAllOrdersAfter", {"timeout": int(timeout_sec)})
