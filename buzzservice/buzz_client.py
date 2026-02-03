from __future__ import annotations

import os
from typing import Any, Dict

from .db import BuzzDB


class BuzzServiceClient:
    """Lightweight local BuzzService client backed by `BuzzDB`.

    This is a minimal implementation used by the local dev service. It
    implements the `lock` operation used by `buzzservice.service`.
    """

    def __init__(self, base_url: str | None = None, shared_secret: str | None = None, service_name: str = "swarmguard") -> None:
        db_path = os.environ.get("BUZZ_DB", "buzzservice.db")
        self.db = BuzzDB(db_path)

    def lock(self, account: str, amount: int, reason: str, request_id: str) -> Dict[str, Any]:
        if amount <= 0:
            # No-op lock for zero stake; return a deferred-like receipt
            return {"status": "ok", "account": account, "locked": 0, "note": "no stake required"}
        return self.db.lock(account, amount, request_id, ref=reason)

    def release(self, account: str, amount: int, request_id: str, ref: str = "") -> Dict[str, Any]:
        return self.db.release(account, amount, request_id, ref=ref)

    def credit(self, account: str, amount: int, request_id: str, ref: str = "") -> Dict[str, Any]:
        return self.db.credit(account, amount, request_id, ref=ref)
