"""Access tokens: required claims, pinned algorithm, revoked by a password change."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from app.database.models import User
from app.security import create_access_token, decode_access_token, hash_password
from sqlalchemy import select


def test_token_carries_required_claims(settings):
    claims = decode_access_token(
        create_access_token(User(id="u1", password_hash="h"), settings), settings
    )
    assert claims["sub"] == "u1"
    assert {"iat", "exp", "ver"} <= claims.keys()


def test_token_missing_claims_rejected(settings):
    exp = datetime.now(UTC) + timedelta(minutes=5)
    token = jwt.encode({"sub": "u1", "exp": exp}, settings.secret_key, algorithm="HS256")
    with pytest.raises(jwt.MissingRequiredClaimError):
        decode_access_token(token, settings)


def test_unsigned_token_rejected(settings):
    token = jwt.encode({"sub": "u1"}, "", algorithm="none")
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(token, settings)


@pytest.mark.asyncio
async def test_password_change_revokes_token(app, auth_client):
    from app.database.session import get_session_factory

    assert (await auth_client.get("/api/v1/sources")).status_code == 200
    async with get_session_factory(app.state.settings)() as session:
        user = await session.scalar(select(User).where(User.username == "admin"))
        assert user is not None
        user.password_hash = hash_password("new-password")
        await session.commit()
    assert (await auth_client.get("/api/v1/sources")).status_code == 401
