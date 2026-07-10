"""Authentication primitives for the admin panel.

Implemented with the Python standard library only (no passlib / bcrypt / jose),
so the admin login works out of the box without extra pip installs.

- Passwords are hashed with PBKDF2-HMAC-SHA256 and a per-user random salt.
- Session tokens are HMAC-SHA256 signed payloads with an expiry, so no server
  side session store is needed and tokens can be verified statelessly.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Optional

from core.config import settings

# --------------------------------------------------------------------------- #
# Password hashing (PBKDF2-HMAC-SHA256)
# --------------------------------------------------------------------------- #
_PBKDF2_ITERATIONS = 240_000
_HASH_PREFIX = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    """Return a self-describing hash string: pbkdf2_sha256$iters$salt$hash."""
    if not password:
        raise ValueError("Password must not be empty")
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"{_HASH_PREFIX}${_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verification of a password against a stored hash string."""
    if not stored or not password:
        return False
    try:
        prefix, iters_s, salt_hex, hash_hex = stored.split("$")
        if prefix != _HASH_PREFIX:
            return False
        iterations = int(iters_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(dk, expected)


# --------------------------------------------------------------------------- #
# Session tokens (stateless, HMAC-signed)
# --------------------------------------------------------------------------- #
def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign(payload_b64: str) -> str:
    sig = hmac.new(
        settings.secret_key.encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return _b64url_encode(sig)


def create_session_token(username: str, ttl_seconds: Optional[int] = None) -> str:
    """Create a signed token of the form <payload_b64>.<signature_b64>."""
    ttl = ttl_seconds if ttl_seconds is not None else settings.session_ttl_seconds
    payload = {
        "sub": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl,
    }
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{payload_b64}.{_sign(payload_b64)}"


def verify_session_token(token: str) -> Optional[str]:
    """Return the username if the token is valid and unexpired, else None."""
    if not token or "." not in token:
        return None
    try:
        payload_b64, sig = token.split(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(sig, _sign(payload_b64)):
        return None
    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload.get("sub")
