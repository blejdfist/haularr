"""Authentication: first-run admin setup and login."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.database.models import User
from app.database.session import SessionDep
from app.security import create_access_token, hash_password, verify_password

auth_router = APIRouter(tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


def _token(user: User, request: Request) -> TokenResponse:
    token = create_access_token({"sub": user.id}, request.app.state.settings)
    return TokenResponse(access_token=token, username=user.username)


@auth_router.post("/auth/login", response_model=TokenResponse)
async def login(body: Credentials, request: Request, session: SessionDep) -> TokenResponse:
    """Exchange a username and password for a bearer token."""
    user = await session.scalar(select(User).where(User.username == body.username))
    if user is None and not await session.scalar(select(func.count()).select_from(User)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin account not set up. POST to /api/v1/auth/setup first.",
        )
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return _token(user, request)


class SetupStatus(BaseModel):
    needed: bool


@auth_router.get("/auth/setup", response_model=SetupStatus)
async def setup_status(session: SessionDep) -> SetupStatus:
    """Whether the admin account still needs to be created (no user exists yet)."""
    return SetupStatus(needed=not await session.scalar(select(func.count()).select_from(User)))


@auth_router.post("/auth/setup", response_model=TokenResponse)
async def setup(body: Credentials, request: Request, session: SessionDep) -> TokenResponse:
    """Create the admin account. Only works while no user exists (409 afterwards)."""
    if await session.scalar(select(func.count()).select_from(User)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Admin account already set up."
        )
    user = User(username=body.username, password_hash=hash_password(body.password), is_admin=True)
    session.add(user)
    await session.commit()
    return _token(user, request)
