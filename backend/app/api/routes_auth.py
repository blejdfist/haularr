"""Authentication routes — login, setup, token refresh."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.security import (
    RequireAuth,
    create_access_token,
    hash_password,
    verify_password,
)
from app.settings import Settings, get_settings

auth_router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class SetupRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


@auth_router.post("/auth/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request) -> TokenResponse:
    settings: Settings = request.app.state.settings
    if body.username != settings.admin_username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if not settings.admin_password_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin account not set up. POST to /api/v1/auth/setup first.",
        )
    if not verify_password(body.password, settings.admin_password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    token = create_access_token({"sub": body.username}, settings)
    return TokenResponse(access_token=token, username=body.username)


@auth_router.post("/auth/setup", response_model=TokenResponse)
async def setup(body: SetupRequest, request: Request) -> TokenResponse:
    """Initial admin account setup. Only works if no password hash is set."""
    settings: Settings = request.app.state.settings
    if settings.admin_password_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Admin account already set up.",
        )
    # Persist the hash
    import json
    from pathlib import Path

    env_path = settings.config_dir / ".admin.env"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    pw_hash = hash_password(body.password)
    env_path.write_text(
        f"HAULARR_ADMIN_USERNAME={body.username}\n"
        f"HAULARR_ADMIN_PASSWORD_HASH={pw_hash}\n",
        encoding="utf-8",
    )
    # Update in-memory
    settings.admin_username = body.username
    settings.admin_password_hash = pw_hash

    token = create_access_token({"sub": body.username}, settings)
    return TokenResponse(access_token=token, username=body.username)


@auth_router.get("/auth/me")
async def me(user: RequireAuth) -> dict:
    return {"username": user.username}
