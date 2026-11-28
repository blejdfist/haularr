"""Authentication and security utilities."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.database.models import User
from app.settings import Settings

ALGORITHM = "HS256"

http_bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Password hashing (using bcrypt directly, not passlib)
# ---------------------------------------------------------------------------


def hash_password(plain: str) -> str:
    """Hash a password using bcrypt. Truncates to 72 bytes (bcrypt max)."""
    password_bytes = plain.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password_bytes, salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against a bcrypt hash."""
    password_bytes = plain.encode("utf-8")[:72]
    hashed_bytes = hashed.encode("utf-8")
    try:
        return bcrypt.checkpw(password_bytes, hashed_bytes)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JWT tokens
# ---------------------------------------------------------------------------


def _require_secret(settings: Settings) -> str:
    if not settings.secret_key:
        raise RuntimeError("JWT secret key is not configured")
    return settings.secret_key


def _password_version(password_hash: str, settings: Settings) -> str:
    """Opaque keyed digest of the password hash; a password change invalidates old tokens."""
    key = _require_secret(settings).encode()
    return hmac.new(key, password_hash.encode(), hashlib.sha256).hexdigest()[:16]


def create_access_token(user: User, settings: Settings) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": user.id,
        "ver": _password_version(user.password_hash, settings),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(claims, _require_secret(settings), algorithm=ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> dict:
    """Verify signature and expiry; raises jwt.PyJWTError on any invalid token."""
    return jwt.decode(
        token,
        _require_secret(settings),
        algorithms=[ALGORITHM],
        options={"require": ["exp", "iat", "sub", "ver"]},
        leeway=30,
    )


def token_matches_user(claims: dict, user: User, settings: Settings) -> bool:
    """False once the user's password has changed since the token was issued."""
    return hmac.compare_digest(claims["ver"], _password_version(user.password_hash, settings))


# ---------------------------------------------------------------------------
# Master encryption key (for credential secrets at rest)
# ---------------------------------------------------------------------------


def _create_private_file(path: Path, data: bytes) -> bool:
    """Create `path` with mode 0600 from the start; False if it already exists."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return True


def get_or_create_master_key(config_dir: Path) -> bytes:
    """Return persistent 32-byte master key; create on first run (mode 0600)."""
    key_path = config_dir / ".master_key"
    if key_path.exists():
        raw = key_path.read_bytes()
        if len(raw) == 32:
            return raw
    key_bytes = secrets.token_bytes(32)
    config_dir.mkdir(parents=True, exist_ok=True)
    if _create_private_file(key_path, key_bytes):
        return key_bytes
    return key_path.read_bytes()  # lost a creation race: use the winner's key


def get_or_create_jwt_secret(config_dir: Path) -> str:
    """Return persistent JWT signing secret; create on first run (mode 0600)."""
    path = config_dir / ".jwt_secret"
    if path.exists() and (existing := path.read_text().strip()):
        return existing
    path.unlink(missing_ok=True)  # empty/blank file: replace it
    secret = secrets.token_urlsafe(48)
    config_dir.mkdir(parents=True, exist_ok=True)
    if _create_private_file(path, secret.encode()):
        return secret
    return path.read_text().strip()  # lost a creation race: use the winner's secret


def encrypt_secret(plaintext: str, master_key: bytes) -> str:
    """Encrypt a secret with Fernet, keyed from the master key; returns a urlsafe token."""
    import base64

    from cryptography.fernet import Fernet

    # Derive a Fernet key from master_key
    fernet_key = base64.urlsafe_b64encode(master_key)
    f = Fernet(fernet_key)
    return f.encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str, master_key: bytes) -> str:
    import base64

    from cryptography.fernet import Fernet

    fernet_key = base64.urlsafe_b64encode(master_key)
    f = Fernet(fernet_key)
    return f.decrypt(ciphertext.encode()).decode()


# ---------------------------------------------------------------------------
# FastAPI dependency — authenticated user
# ---------------------------------------------------------------------------


class AuthUser:
    def __init__(self, id: str, username: str, is_admin: bool) -> None:
        self.id = id
        self.username = username
        self.is_admin = is_admin


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(http_bearer)],
) -> AuthUser:
    # Get settings from app state (not a fresh Settings() call)
    settings: Settings = request.app.state.settings
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    from app.database.models import User
    from app.database.session import get_session_factory

    user = None
    try:
        claims = decode_access_token(credentials.credentials, settings)
        async with get_session_factory(settings)() as session:
            user = await session.get(User, claims["sub"])
        if user is not None and not token_matches_user(claims, user, settings):
            user = None
    except jwt.PyJWTError:
        pass
    if user is None:  # bad/expired token, user deleted, or password changed
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return AuthUser(id=user.id, username=user.username, is_admin=user.is_admin)
