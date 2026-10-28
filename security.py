"""Password hashing and short-lived API tokens using the Python standard library."""
from __future__ import annotations
import base64, hashlib, hmac, json, secrets, time
from backend.config import TOKEN_SECRET

ITERATIONS = 260_000

def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("Password must contain at least 10 characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(ITERATIONS, base64.urlsafe_b64encode(salt).decode(), base64.urlsafe_b64encode(digest).decode())

def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt_b64, digest_b64 = stored.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_b64.encode())
        expected = base64.urlsafe_b64decode(digest_b64.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")

def issue_token(user_id: int, role: str, username: str, token_version: int = 0, ttl_seconds: int = 8 * 60 * 60) -> str:
    payload = {"sub": user_id, "role": role, "username": username, "ver": token_version, "exp": int(time.time()) + ttl_seconds}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = _b64(hmac.new(TOKEN_SECRET.encode(), body.encode(), hashlib.sha256).digest())
    return body + "." + signature

def verify_token(token: str) -> dict | None:
    try:
        body, signature = token.split(".", 1)
        expected = _b64(hmac.new(TOKEN_SECRET.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None
