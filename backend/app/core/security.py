from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import get_settings


def hash_pin(pin: str) -> str:
    # bcrypt caps at 72 bytes; PINs are 4-6 digits so truncation never happens
    return bcrypt.hashpw(pin.encode()[:72], bcrypt.gensalt(rounds=12)).decode()


def verify_pin(pin: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pin.encode()[:72], hashed.encode())
    except Exception:
        return False


def hash_phone(phone: str) -> str:
    """Parent phones are never stored in clear text."""
    salt = get_settings().jwt_secret.encode()
    digits = "".join(ch for ch in phone if ch.isdigit())[-10:]  # "+91 98765 00000" == "9876500000"
    return hmac.new(salt, digits.encode(), hashlib.sha256).hexdigest()


def client_uuid() -> str:
    return secrets.token_hex(16)


def make_token(sub: str, kind: str, ttl_minutes: int | None = None) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": sub, "kind": kind, "iat": now,
               "exp": now + timedelta(minutes=ttl_minutes or s.jwt_ttl_minutes)}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
