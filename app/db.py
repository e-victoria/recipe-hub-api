import functools
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.settings import settings


class Base(DeclarativeBase):
    pass


@functools.cache
def get_engine() -> Engine:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return create_engine(settings.database_url, pool_pre_ping=True)


@functools.cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    with _session_factory()() as session:
        yield session
