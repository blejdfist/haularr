"""Authentication and security utilities."""

from __future__ import annotations

import contextlib
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

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


def create_access_token(data: dict, settings: Settings) -> str:
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str, settings: Settings) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])


# ---------------------------------------------------------------------------
# Master encryption key (for credential secrets at rest)
# ---------------------------------------------------------------------------


def get_or_create_master_key(config_dir: Path) -> bytes:
    """Return persistent 32-byte master key; create on first run (mode 0600)."""
    key_path = config_dir / ".master_key"
    if key_path.exists():
        raw = key_path.read_bytes()
        if len(raw) == 32:
            return raw
    key_bytes = secrets.token_bytes(32)
    config_dir.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key_bytes)
    with contextlib.suppress(OSError):  # Windows may not support chmod
        os.chmod(key_path, 0o600)
    return key_bytes


def encrypt_secret(plaintext: str, master_key: bytes) -> str:
    """Simple XOR-based encryption placeholder; replace with Fernet in prod."""
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
        user_id = decode_access_token(credentials.credentials, settings).get("sub")
        if user_id:
            async with get_session_factory(settings)() as session:
                user = await session.get(User, user_id)
    except JWTError:
        pass
    if user is None:  # bad/expired token, or the user was deleted
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return AuthUser(id=user.id, username=user.username, is_admin=user.is_admin)
