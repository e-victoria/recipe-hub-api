from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.models import User, UserSession

PASSWORD = "correct horse battery"  # What the `register` fixture uses by default.

# The limits this API promises; see app/auth.py.
LOGIN_FAILURES_ALLOWED = 5
REGISTRATIONS_PER_ADDRESS = 10


def login(client: TestClient, email: str, password: str = PASSWORD) -> Any:
    return client.post("/auth/login", json={"email": email, "password": password})


# Registration


def test_register_returns_a_session_for_the_new_user(anon: TestClient) -> None:
    response = anon.post("/auth/register", json={"email": "anna@example.com", "password": PASSWORD})

    assert response.status_code == 201
    data = response.json()
    assert set(data) == {"token", "expires_at", "user"}
    assert len(data["token"]) >= 32
    assert set(data["user"]) == {"id", "email", "created_at"}
    assert data["user"]["email"] == "anna@example.com"
    expires = datetime.fromisoformat(data["expires_at"])
    assert timedelta(days=29) < expires - datetime.now(UTC) <= timedelta(days=30)


def test_register_signs_the_user_in(
    anon: TestClient, register: Callable[..., dict], signed_in: Callable[[str], TestClient]
) -> None:
    token = register("anna@example.com")["token"]
    assert signed_in(token).get("/auth/me").status_code == 200


def test_register_normalizes_email(anon: TestClient, register: Callable[..., dict]) -> None:
    assert register("  Anna@Example.COM ")["user"]["email"] == "anna@example.com"


def test_register_existing_email_conflicts(anon: TestClient, register: Callable[..., dict]) -> None:
    register("anna@example.com")
    response = anon.post("/auth/register", json={"email": "ANNA@example.com", "password": PASSWORD})
    assert response.status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"email": "anna", "password": PASSWORD},
        {"email": "anna@", "password": PASSWORD},
        {"email": "an na@example.com", "password": PASSWORD},
        {"email": "a" * 250 + "@x.io", "password": PASSWORD},
        {"email": "anna@example.com", "password": "short12"},
        {"email": "anna@example.com", "password": "x" * 129},
        {"email": "anna@example.com"},
        {"email": "anna@example.com", "password": PASSWORD, "name": "Anna"},
    ],
    ids=[
        "no-at",
        "no-domain",
        "space",
        "too-long-email",
        "short-password",
        "long-password",
        "no-password",
        "unknown-field",
    ],
)
def test_register_rejects_invalid_input(anon: TestClient, body: dict[str, Any]) -> None:
    assert anon.post("/auth/register", json=body).status_code == 422


def test_password_and_token_are_stored_hashed(
    anon: TestClient, db: sessionmaker[Session], register: Callable[..., dict]
) -> None:
    token = register("anna@example.com")["token"]

    with db() as session:
        user = session.scalars(select(User)).one()
        stored = session.scalars(select(UserSession)).one()
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash
    assert stored.token_hash != token
    assert token not in stored.token_hash


def test_register_is_rate_limited_per_address(
    anon: TestClient, register: Callable[..., dict]
) -> None:
    for n in range(REGISTRATIONS_PER_ADDRESS):
        register(f"user{n}@example.com")

    response = anon.post("/auth/register", json={"email": "late@example.com", "password": PASSWORD})
    assert response.status_code == 429


# Login


def test_login_returns_a_new_session(
    anon: TestClient, user: dict, signed_in: Callable[[str], TestClient]
) -> None:
    response = login(anon, "anna@example.com")

    assert response.status_code == 200
    data = response.json()
    assert data["user"] == user["user"]
    assert data["token"] != user["token"]
    assert signed_in(data["token"]).get("/auth/me").status_code == 200


def test_login_ignores_email_case_and_spaces(anon: TestClient, user: dict) -> None:
    assert login(anon, " ANNA@example.com ").status_code == 200


def test_login_failures_look_the_same(anon: TestClient, user: dict) -> None:
    wrong_password = login(anon, "anna@example.com", "wrong password")
    unknown_email = login(anon, "nobody@example.com")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_login_locks_after_repeated_failures(
    anon: TestClient, user: dict, register: Callable[..., dict]
) -> None:
    for _ in range(LOGIN_FAILURES_ALLOWED):
        assert login(anon, "anna@example.com", "wrong password").status_code == 401

    # Locked even with the right password, so guessing can't continue.
    assert login(anon, "anna@example.com").status_code == 429
    # Other accounts are unaffected.
    register("olek@example.com")
    assert login(anon, "olek@example.com").status_code == 200


def test_successful_login_clears_failures(anon: TestClient, user: dict) -> None:
    for _ in range(LOGIN_FAILURES_ALLOWED - 1):
        login(anon, "anna@example.com", "wrong password")
    assert login(anon, "anna@example.com").status_code == 200

    for _ in range(LOGIN_FAILURES_ALLOWED - 1):
        login(anon, "anna@example.com", "wrong password")
    assert login(anon, "anna@example.com").status_code == 200


# Current user and sessions


def test_me_returns_the_signed_in_user(client: TestClient, user: dict) -> None:
    response = client.get("/auth/me")
    assert response.status_code == 200
    assert response.json() == user["user"]


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer not-a-real-token"}, {"Authorization": "Basic YTpi"}],
    ids=["no-token", "unknown-token", "wrong-scheme"],
)
def test_me_requires_a_valid_token(anon: TestClient, headers: dict[str, str]) -> None:
    response = anon.get("/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_expired_session_is_rejected(client: TestClient, db: sessionmaker[Session]) -> None:
    with db() as session, session.begin():
        past = datetime.now(UTC) - timedelta(seconds=1)
        session.execute(update(UserSession).values(expires_at=past))

    assert client.get("/auth/me").status_code == 401


def test_logout_ends_only_that_session(
    anon: TestClient, client: TestClient, user: dict, signed_in: Callable[[str], TestClient]
) -> None:
    other = signed_in(login(anon, "anna@example.com").json()["token"])

    assert client.post("/auth/logout").status_code == 204

    assert client.get("/auth/me").status_code == 401
    assert other.get("/auth/me").status_code == 200


def test_logout_requires_a_token(anon: TestClient) -> None:
    assert anon.post("/auth/logout").status_code == 401


def test_openapi_describes_auth(anon: TestClient) -> None:
    schema = anon.get("/openapi.json").json()
    for path in ("/auth/register", "/auth/login", "/auth/logout"):
        assert "post" in schema["paths"][path]
    assert "get" in schema["paths"]["/auth/me"]
    schemes = schema["components"]["securitySchemes"].values()
    assert any(s["type"] == "http" and s["scheme"] == "bearer" for s in schemes)
