from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import recipes
from app.db import Base, get_session
from app.main import app
from app.models import Recipe


@pytest.fixture
def db() -> sessionmaker[Session]:
    # One shared in-memory database, reachable from TestClient's worker thread.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def client(db: sessionmaker[Session]) -> Iterator[TestClient]:
    def override() -> Iterator[Session]:
        with db() as session:
            yield session

    app.dependency_overrides[get_session] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def recipe_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "servings": 4,
        "prep_minutes": 20,
        "cook_minutes": 40,
        "translations": [
            {
                "locale": "en",
                "title": "Dumplings",
                "description": "Soft and filling.",
                "ingredients": ["500 g flour", "2 eggs"],
                "steps": ["Mix", "Boil"],
            },
            {"locale": "pl", "title": "Pierogi"},
        ],
    }
    body.update(overrides)
    return body


def test_create_recipe(client: TestClient) -> None:
    response = client.post("/recipes", json=recipe_body())

    assert response.status_code == 201
    data = response.json()
    assert data["slug"] == "dumplings"
    assert data["servings"] == 4
    assert data["created_at"] and data["updated_at"] and data["id"]
    by_locale = {t["locale"]: t for t in data["translations"]}
    assert by_locale["en"]["ingredients"] == ["500 g flour", "2 eggs"]
    assert by_locale["pl"] == {
        "locale": "pl",
        "title": "Pierogi",
        "description": None,
        "ingredients": [],
        "steps": [],
    }


def test_create_recipe_trims_text(client: TestClient) -> None:
    body = recipe_body(
        translations=[{"locale": "en", "title": "  Soup ", "ingredients": [" water "]}]
    )
    data = client.post("/recipes", json=body).json()
    assert data["translations"][0]["title"] == "Soup"
    assert data["translations"][0]["ingredients"] == ["water"]


def test_create_recipe_makes_slugs_unique(client: TestClient) -> None:
    slugs = [client.post("/recipes", json=recipe_body()).json()["slug"] for _ in range(3)]
    assert slugs == ["dumplings", "dumplings-2", "dumplings-3"]


def test_slug_comes_from_english_title_when_present(client: TestClient) -> None:
    body = recipe_body(
        translations=[
            {"locale": "ru", "title": "Борщ"},
            {"locale": "en", "title": "Beet soup"},
        ]
    )
    assert client.post("/recipes", json=body).json()["slug"] == "beet-soup"


def test_create_recipe_retries_when_slug_is_taken_concurrently(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.post("/recipes", json=recipe_body())
    real = recipes.unique_slug
    calls: list[str] = []

    def stale_first(session: Session, title: str) -> str:
        # The first answer is what a request that lost the race would have seen.
        calls.append(title)
        return "dumplings" if len(calls) == 1 else real(session, title)

    monkeypatch.setattr(recipes, "unique_slug", stale_first)
    response = client.post("/recipes", json=recipe_body())

    assert response.status_code == 201
    assert response.json()["slug"] == "dumplings-2"
    assert len(calls) == 2


def test_create_recipe_gives_up_after_repeated_slug_conflicts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.post("/recipes", json=recipe_body())
    monkeypatch.setattr(recipes, "unique_slug", lambda _session, _title: "dumplings")

    assert client.post("/recipes", json=recipe_body()).status_code == 409
    assert len(client.get("/recipes").json()) == 1


@pytest.mark.parametrize(
    "body",
    [
        recipe_body(translations=[]),
        recipe_body(translations=[{"locale": "en", "title": "A"}, {"locale": "en", "title": "B"}]),
        recipe_body(translations=[{"locale": "de", "title": "Knödel"}]),
        recipe_body(translations=[{"locale": "en", "title": "   "}]),
        recipe_body(translations=[{"locale": "en", "title": "Soup", "steps": [""]}]),
        recipe_body(servings=0),
        recipe_body(prep_minutes=-1),
        recipe_body(serving=4),
        recipe_body(translations=[{"locale": "en", "title": "Soup", "steps_": ["Boil"]}]),
    ],
    ids=[
        "no-translations",
        "duplicate-locale",
        "unknown-locale",
        "blank-title",
        "blank-step",
        "zero-servings",
        "negative-minutes",
        "unknown-recipe-field",
        "unknown-translation-field",
    ],
)
def test_create_recipe_rejects_invalid_input(client: TestClient, body: dict[str, Any]) -> None:
    assert client.post("/recipes", json=body).status_code == 422


def test_list_recipes_empty(client: TestClient) -> None:
    response = client.get("/recipes")
    assert response.status_code == 200
    assert response.json() == []


def test_list_recipes_in_requested_locale(client: TestClient) -> None:
    client.post("/recipes", json=recipe_body())

    items = client.get("/recipes", params={"locale": "pl"}).json()

    assert items == [
        {
            "id": items[0]["id"],
            "slug": "dumplings",
            "locale": "pl",
            "title": "Pierogi",
            "description": None,
            "servings": 4,
            "prep_minutes": 20,
            "cook_minutes": 40,
            "created_at": items[0]["created_at"],
        }
    ]


def test_list_recipes_falls_back_to_english_then_any(client: TestClient) -> None:
    client.post("/recipes", json=recipe_body())
    client.post("/recipes", json=recipe_body(translations=[{"locale": "pl", "title": "Żurek"}]))

    items = client.get("/recipes", params={"locale": "ru"}).json()

    assert {i["title"]: i["locale"] for i in items} == {"Dumplings": "en", "Żurek": "pl"}


def test_list_recipes_newest_first_with_paging(
    client: TestClient, db: sessionmaker[Session]
) -> None:
    for day, title in enumerate(["First", "Second", "Third"], start=1):
        body = recipe_body(translations=[{"locale": "en", "title": title}])
        slug = client.post("/recipes", json=body).json()["slug"]
        # SQLite timestamps have 1-second resolution, so set distinct ones explicitly.
        with db() as session, session.begin():
            created = datetime(2026, 1, day, tzinfo=UTC)
            session.execute(update(Recipe).filter_by(slug=slug).values(created_at=created))

    titles = [i["title"] for i in client.get("/recipes").json()]
    page = [i["title"] for i in client.get("/recipes", params={"limit": 1, "offset": 1}).json()]

    assert titles == ["Third", "Second", "First"]
    assert page == ["Second"]


@pytest.mark.parametrize("params", [{"locale": "de"}, {"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_list_recipes_rejects_invalid_params(client: TestClient, params: dict[str, Any]) -> None:
    assert client.get("/recipes", params=params).status_code == 422


def test_openapi_describes_recipes(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert {"get", "post"} <= schema["paths"]["/recipes"].keys()
    assert {"Recipe", "RecipeCreate", "RecipeSummary"} <= schema["components"]["schemas"].keys()


def test_duplicate_locale_has_a_stable_error_type(client: TestClient) -> None:
    body = recipe_body(
        translations=[{"locale": "en", "title": "A"}, {"locale": "en", "title": "B"}]
    )
    errors = client.post("/recipes", json=body).json()["detail"]
    assert [e["type"] for e in errors] == ["duplicate_locale"]


@pytest.mark.parametrize("description", ["", "   ", None])
def test_blank_description_is_stored_as_none(client: TestClient, description: str | None) -> None:
    body = recipe_body(translations=[{"locale": "en", "title": "Soup", "description": description}])
    response = client.post("/recipes", json=body)
    assert response.status_code == 201
    assert response.json()["translations"][0]["description"] is None


def test_slug_without_english_follows_list_fallback_order(client: TestClient) -> None:
    # Sent pl first, but the fallback order is en, ru, pl, so Russian wins.
    body = recipe_body(
        translations=[{"locale": "pl", "title": "Żurek"}, {"locale": "ru", "title": "Борщ"}]
    )
    assert client.post("/recipes", json=body).json()["slug"] == "borshch"

    [item] = client.get("/recipes", params={"locale": "en"}).json()
    assert (item["locale"], item["title"], item["slug"]) == ("ru", "Борщ", "borshch")


def test_list_skips_recipes_without_translations(
    client: TestClient, db: sessionmaker[Session]
) -> None:
    with db() as session, session.begin():
        session.add(Recipe(slug="empty"))
    client.post("/recipes", json=recipe_body())

    response = client.get("/recipes", params={"limit": 1})

    assert response.status_code == 200
    assert [i["slug"] for i in response.json()] == ["dumplings"]
