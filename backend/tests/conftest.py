"""Pytest configuration and fixtures."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def temp_config_dir(tmp_path):
    """Create a temporary config directory for test settings."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return config_dir


@pytest.fixture
def settings(temp_config_dir):
    from app.settings import Settings

    s = Settings(
        config_dir=temp_config_dir,
        static_dir=temp_config_dir / "nonexistent",  # No frontend in tests
        secret_key="test-secret-key-for-testing-only-32chars",
    )
    return s


@pytest_asyncio.fixture
async def app(settings):
    """Create the FastAPI app with test settings and run migrations."""
    from app.database.models import Base

    # Create tables directly (faster than Alembic for tests, avoids async loop issues)
    from app.database.session import close_engine, get_engine
    from app.main import create_app

    os.environ["HAULARR_CONFIG_DIR"] = str(settings.config_dir)
    settings.config_dir.mkdir(parents=True, exist_ok=True)

    engine = get_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    application = create_app(settings)
    application.state.settings = settings

    # Initialize master key
    from app.security import get_or_create_master_key

    application.state.master_key = get_or_create_master_key(settings.config_dir)

    yield application

    # Cleanup
    await close_engine()


@pytest_asyncio.fixture
async def client(app):
    """Create an async HTTP client for the test app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def auth_client(app):
    """Create an authenticated async HTTP client (admin account pre-set up)."""
    from app.database.models import User
    from app.database.session import get_session_factory
    from app.security import create_access_token, hash_password

    settings = app.state.settings
    user = User(username="admin", password_hash=hash_password("testpass123"), is_admin=True)
    async with get_session_factory(settings)() as session:
        session.add(user)
        await session.commit()
    token = create_access_token(user, settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as c:
        yield c


@pytest_asyncio.fixture
async def db_session(settings):
    """Create a database session for direct DB testing."""
    from app.database.session import close_engine, get_engine, get_session_factory

    # Ensure engine is created
    get_engine(settings)

    factory = get_session_factory(settings)
    async with factory() as session:
        yield session

    await close_engine()
