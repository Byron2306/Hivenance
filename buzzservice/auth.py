from __future__ import annotations
import hmac
import hashlib


def sign_body(body_bytes: bytes, shared_secret: str) -> str:
    return hmac.new(shared_secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()


def verify_signature(body_bytes: bytes, signature_hex: str, shared_secret: str) -> bool:
    expected = sign_body(body_bytes, shared_secret)
    return hmac.compare_digest(expected, signature_hex)
