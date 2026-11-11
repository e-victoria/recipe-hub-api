import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.main import app

PASSWORD = "correct horse battery"


@pytest.fixture
def db() -> sessionmaker[Session]:
    # One shared in-memory database, reachable from TestClient's worker thread.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def anon(db: sessionmaker[Session]) -> Iterator[TestClient]:
    """A client with no credentials. Rate limits start empty for every test."""
    from app.ratelimit import RateLimits, get_rate_limits

    def override() -> Iterator[Session]:
        with db() as session:
            yield session

    limits = RateLimits()
    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_rate_limits] = lambda: limits
    yield TestClient(app)
    app.dependency_overrides.clear()


Register = Callable[..., dict]
SignedIn = Callable[[str], TestClient]


@pytest.fixture
def register(anon: TestClient) -> Register:
    """Register `email` and return the response: `token`, `expires_at` and `user`."""

    def register(email: str, password: str = PASSWORD) -> dict:
        response = anon.post("/auth/register", json={"email": email, "password": password})
        assert response.status_code == 201, response.text
        return response.json()

    return register


@pytest.fixture
def signed_in(anon: TestClient) -> SignedIn:
    """A client on the same app and overrides, sending `token`."""
    return lambda token: TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def user(register: Register) -> dict:
    """A registered user: the register response (`token`, `expires_at`, `user`)."""
    return register("anna@example.com")


@pytest.fixture
def user_id(user: dict) -> uuid.UUID:
    return uuid.UUID(user["user"]["id"])


@pytest.fixture
def client(user: dict, signed_in: SignedIn) -> TestClient:
    """A client signed in as `user`."""
    return signed_in(user["token"])


@pytest.fixture
def stranger(register: Register, signed_in: SignedIn) -> TestClient:
    """A client signed in as a second user."""
    return signed_in(register("olek@example.com")["token"])
