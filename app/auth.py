import functools
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pwdlib import PasswordHash
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app import models, schemas
from app.db import get_session
from app.ratelimit import RateLimits, get_rate_limits
from app.settings import settings

router = APIRouter(prefix="/auth", tags=["auth"])

SessionDep = Annotated[Session, Depends(get_session)]
LimitsDep = Annotated[RateLimits, Depends(get_rate_limits)]

# Argon2id with pwdlib's recommended parameters.
passwords = PasswordHash.recommended()
# auto_error=False so a missing token gets our 401 (with WWW-Authenticate), not FastAPI's 403.
bearer = HTTPBearer(auto_error=False)


def unauthorized(detail: str = "not signed in") -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail=detail, headers={"WWW-Authenticate": "Bearer"}
    )


def token_hash(token: str) -> str:
    # Tokens are long and random, so a fast hash is enough; it only hides them from DB readers.
    return hashlib.sha256(token.encode()).hexdigest()


@functools.cache
def dummy_hash() -> str:
    """Verified against when the email is unknown, so both failures take as long."""
    return passwords.hash(secrets.token_urlsafe())


def get_current_session(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> models.UserSession:
    if credentials is None:
        raise unauthorized()
    found = session.scalars(
        select(models.UserSession)
        .options(joinedload(models.UserSession.user))
        .where(
            models.UserSession.token_hash == token_hash(credentials.credentials),
            # Compared in SQL: SQLite returns naive datetimes, which Python can't compare to aware.
            models.UserSession.expires_at > datetime.now(UTC),
        )
    ).one_or_none()
    if found is None:
        raise unauthorized()
    return found


def get_current_user(
    current: Annotated[models.UserSession, Depends(get_current_session)],
) -> models.User:
    return current.user


CurrentSession = Annotated[models.UserSession, Depends(get_current_session)]
CurrentUser = Annotated[models.User, Depends(get_current_user)]


def start_session(session: Session, user: models.User) -> schemas.AuthSession:
    now = datetime.now(UTC)
    # Drop this user's expired sessions while we're here, so the table doesn't grow forever.
    session.execute(
        delete(models.UserSession).where(
            models.UserSession.user_id == user.id, models.UserSession.expires_at <= now
        )
    )
    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(days=settings.session_days)
    session.add(
        models.UserSession(user_id=user.id, token_hash=token_hash(token), expires_at=expires_at)
    )
    session.commit()
    return schemas.AuthSession(
        token=token, expires_at=expires_at, user=schemas.User.model_validate(user)
    )


def too_many_attempts() -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS, detail="too many attempts, try again later"
    )


@router.post("/register", response_model=schemas.AuthSession, status_code=status.HTTP_201_CREATED)
def register(
    body: schemas.RegisterRequest, request: Request, session: SessionDep, limits: LimitsDep
) -> schemas.AuthSession:
    """Create an account and sign in to it."""
    # Behind a proxy this is the proxy's address unless uvicorn runs with --proxy-headers.
    address = request.client.host if request.client else "unknown"
    if limits.register.blocked(address):
        raise too_many_attempts()
    limits.register.hit(address)

    user = models.User(email=body.email, password_hash=passwords.hash(body.password))
    session.add(user)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="email already registered") from None
    return start_session(session, user)


@router.post("/login", response_model=schemas.AuthSession, status_code=status.HTTP_200_OK)
def login(
    body: schemas.LoginRequest, session: SessionDep, limits: LimitsDep
) -> schemas.AuthSession:
    """Sign in. Every failure gets the same answer, so it doesn't reveal which emails exist."""
    if limits.login.blocked(body.email):
        raise too_many_attempts()

    user = session.scalars(select(models.User).where(models.User.email == body.email)).one_or_none()
    valid, new_hash = passwords.verify_and_update(
        body.password, user.password_hash if user else dummy_hash()
    )
    if user is None or not valid:
        limits.login.hit(body.email)
        raise unauthorized("invalid email or password")

    limits.login.reset(body.email)
    if new_hash:  # Stored with older parameters; upgrade it now that we know the password.
        user.password_hash = new_hash
    return start_session(session, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def logout(current: CurrentSession, session: SessionDep) -> Response:
    """End this session. Other devices stay signed in."""
    session.delete(current)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=schemas.User, status_code=status.HTTP_200_OK)
def me(user: CurrentUser) -> schemas.User:
    return schemas.User.model_validate(user)
