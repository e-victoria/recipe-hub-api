import dataclasses
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, delete, event, inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.settings
from app.db import Base
from app.models import Image, Locale, Recipe, RecipeTranslation

ROOT = Path(__file__).resolve().parent.parent


def sqlite_engine(url: str = "sqlite://") -> Engine:
    engine = create_engine(url)

    # SQLite ignores foreign keys (and so ON DELETE CASCADE) unless asked.
    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn: object, _record: object) -> None:
        dbapi_conn.execute(  # type: ignore[attr-defined]
            "PRAGMA foreign_keys=ON"
        )

    return engine


@pytest.fixture
def session() -> Iterator[Session]:
    engine = sqlite_engine()
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def make_recipe() -> Recipe:
    return Recipe(
        slug="pierogi",
        servings=4,
        translations=[
            RecipeTranslation(
                locale=Locale.en, title="Dumplings", ingredients=["flour"], steps=["Mix"]
            ),
            RecipeTranslation(locale=Locale.pl, title="Pierogi"),
        ],
        images=[
            Image(position=1, storage_key="recipes/a/2.jpg", content_type="image/jpeg"),
            Image(position=0, storage_key="recipes/a/1.jpg", content_type="image/jpeg"),
        ],
    )


def test_recipe_round_trip(session: Session) -> None:
    session.add(make_recipe())
    session.commit()
    session.expunge_all()

    recipe = session.scalars(select(Recipe)).one()
    titles = {t.locale: t.title for t in recipe.translations}
    assert titles == {Locale.en: "Dumplings", Locale.pl: "Pierogi"}
    pl = next(t for t in recipe.translations if t.locale is Locale.pl)
    assert pl.ingredients == [] and pl.steps == []
    assert [i.storage_key for i in recipe.images] == ["recipes/a/1.jpg", "recipes/a/2.jpg"]
    assert recipe.created_at is not None


def test_in_place_list_edits_are_saved(session: Session) -> None:
    session.add(make_recipe())
    session.commit()
    en = session.scalars(select(RecipeTranslation).filter_by(locale=Locale.en)).one()
    en.steps.append("Boil")
    en.ingredients[0] = "500 g flour"
    session.commit()
    session.expunge_all()

    en = session.scalars(select(RecipeTranslation).filter_by(locale=Locale.en)).one()
    assert en.steps == ["Mix", "Boil"]
    assert en.ingredients == ["500 g flour"]


def test_updated_at_changes_and_is_readable_after_close() -> None:
    engine = sqlite_engine()
    Base.metadata.create_all(engine)
    old = datetime(2000, 1, 1)
    with Session(engine, expire_on_commit=False) as session:
        recipe = make_recipe()
        session.add(recipe)
        session.commit()
        # CURRENT_TIMESTAMP has 1-second resolution on SQLite, so start from a known old value.
        session.execute(update(Recipe).values(updated_at=old))
        session.refresh(recipe)
        recipe.servings = 6
        session.commit()
    assert recipe.updated_at > old


def test_locale_is_stored_by_value(session: Session) -> None:
    session.add(make_recipe())
    session.commit()
    stored = session.connection().exec_driver_sql("SELECT locale FROM recipe_translation")
    assert sorted(row[0] for row in stored) == ["en", "pl"]


def test_one_translation_per_locale(session: Session) -> None:
    recipe = make_recipe()
    recipe.translations.append(RecipeTranslation(locale=Locale.en, title="Again"))
    session.add(recipe)
    with pytest.raises(IntegrityError):
        session.commit()


def test_deleting_recipe_deletes_children(session: Session) -> None:
    session.add(make_recipe())
    session.commit()
    session.delete(session.scalars(select(Recipe)).one())
    session.commit()
    assert session.scalars(select(RecipeTranslation)).all() == []
    assert session.scalars(select(Image)).all() == []


def test_database_cascades_without_the_orm(session: Session) -> None:
    session.add(make_recipe())
    session.commit()
    session.execute(delete(Recipe))
    session.commit()
    assert session.scalars(select(RecipeTranslation)).all() == []
    assert session.scalars(select(Image)).all() == []


@pytest.fixture
def use_database_url(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], Config]:
    def use(url: str) -> Config:
        patched = dataclasses.replace(app.settings.settings, database_url=url)
        monkeypatch.setattr(app.settings, "settings", patched)
        return Config(str(ROOT / "alembic.ini"))

    return use


def test_migrations_match_models(tmp_path: Path, use_database_url: Callable[[str], Config]) -> None:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    command.upgrade(use_database_url(url), "head")

    with create_engine(url).connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_migrations_downgrade_cleanly(
    tmp_path: Path, use_database_url: Callable[[str], Config]
) -> None:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    config = use_database_url(url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    assert inspect(create_engine(url)).get_table_names() == ["alembic_version"]


def test_migrations_accept_percent_in_url(
    tmp_path: Path, use_database_url: Callable[[str], Config]
) -> None:
    # URL-encoded passwords contain %, which ConfigParser would treat as interpolation.
    command.upgrade(use_database_url(f"sqlite:///{tmp_path / 'p%40ss.db'}"), "head")
    assert any(tmp_path.iterdir())
