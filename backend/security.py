import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt

# PBKDF2-HMAC-SHA256 with a per-password random salt. Hashes are stored as
# "pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>" so the iteration count
# can be raised later without invalidating existing passwords.
PBKDF2_ITERATIONS = 600_000
ALGORITHM = "HS256"


# Development-only fallback. Non-development environments must provide a
# stable JWT_SECRET so tokens survive restarts and work across workers.
_FALLBACK_SECRET = secrets.token_urlsafe(48)


def _secret() -> bytes:
    secret = os.getenv("JWT_SECRET")
    environment = os.getenv("APP_ENV", "development").lower()
    if not secret:
        if environment not in {"development", "dev", "test"}:
            raise RuntimeError("JWT_SECRET must be configured outside development.")
        secret = _FALLBACK_SECRET
    return secret.encode()


def access_token_expire_minutes() -> int:
    return int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, digest = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), int(iterations)
        ).hex()
        return hmac.compare_digest(candidate, digest)
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: str) -> str:
    issued_at = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=access_token_expire_minutes()),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Return the user id encoded in a valid, unexpired token, else None."""
    try:
        payload = jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except jwt.InvalidTokenError:
        return None
    user_id = payload.get("sub")
    return user_id if isinstance(user_id, str) else None
