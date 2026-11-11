import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any, get_args

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app import recipes, schemas
from app.main import app
from app.models import Image, Recipe, User, Video
from app.storage import (
    IMAGE_CONTENT_TYPES,
    MAX_IMAGE_BYTES,
    MAX_VIDEO_BYTES,
    VIDEO_CONTENT_TYPES,
    StoredObject,
    get_storage,
)


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, StoredObject] = {}

    def download_url(self, key: str) -> str:
        return f"https://media.test/{key}"

    def upload_url(self, key: str, content_type: str) -> str:
        return f"https://upload.test/{key}?type={content_type}"

    def head(self, key: str) -> StoredObject | None:
        return self.objects.get(key)

    def delete(self, key: str) -> None:
        del self.objects[key]


@pytest.fixture
def storage(anon: TestClient) -> Iterator[FakeStorage]:
    # Depends on `anon`, which clears all overrides on teardown.
    fake = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: fake
    yield fake


@pytest.fixture(autouse=True)
def _fake_storage(storage: FakeStorage) -> None:
    pass


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


def test_slug_never_shadows_the_new_recipe_page(client: TestClient) -> None:
    body = recipe_body(translations=[{"locale": "en", "title": "New"}])
    assert client.post("/recipes", json=body).json()["slug"] == "new-2"


def test_create_recipe_retries_when_slug_is_taken_concurrently(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.post("/recipes", json=recipe_body())
    real = recipes.unique_slug
    calls: list[str] = []

    def stale_first(session: Session, owner: User, title: str) -> str:
        # The first answer is what a request that lost the race would have seen.
        calls.append(title)
        return "dumplings" if len(calls) == 1 else real(session, owner, title)

    monkeypatch.setattr(recipes, "unique_slug", stale_first)
    response = client.post("/recipes", json=recipe_body())

    assert response.status_code == 201
    assert response.json()["slug"] == "dumplings-2"
    assert len(calls) == 2


def test_create_recipe_gives_up_after_repeated_slug_conflicts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.post("/recipes", json=recipe_body())
    monkeypatch.setattr(recipes, "unique_slug", lambda _session, _owner, _title: "dumplings")

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
            "cover": None,
        }
    ]


def test_list_recipes_has_the_first_image_as_cover(
    client: TestClient, db: sessionmaker[Session]
) -> None:
    client.post("/recipes", json=recipe_body())
    with db() as session, session.begin():
        recipe = session.scalars(select(Recipe)).one()
        recipe.images = [
            Image(position=1, storage_key="r/2.png", content_type="image/png"),
            Image(
                position=0,
                storage_key="r/1.jpg",
                content_type="image/jpeg",
                width=800,
                height=600,
            ),
        ]

    cover = client.get("/recipes").json()[0]["cover"]

    assert cover == {
        "id": cover["id"],
        "url": "https://media.test/r/1.jpg",
        "content_type": "image/jpeg",
        "width": 800,
        "height": 600,
    }


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
    assert "get" in schema["paths"]["/recipes/{slug}"]
    assert {"Recipe", "RecipeCreate", "RecipeDetail", "RecipeSummary"} <= schema["components"][
        "schemas"
    ].keys()


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
    client: TestClient, db: sessionmaker[Session], user_id: uuid.UUID
) -> None:
    with db() as session, session.begin():
        session.add(Recipe(slug="empty", owner_id=user_id))
    client.post("/recipes", json=recipe_body())

    response = client.get("/recipes", params={"limit": 1})

    assert response.status_code == 200
    assert [i["slug"] for i in response.json()] == ["dumplings"]


def test_get_recipe_in_requested_locale(client: TestClient) -> None:
    created = client.post("/recipes", json=recipe_body()).json()

    response = client.get("/recipes/dumplings", params={"locale": "pl"})

    assert response.status_code == 200
    assert response.json() == {
        "id": created["id"],
        "slug": "dumplings",
        "locale": "pl",
        "title": "Pierogi",
        "description": None,
        "ingredients": [],
        "steps": [],
        "servings": 4,
        "prep_minutes": 20,
        "cook_minutes": 40,
        "created_at": created["created_at"],
        "updated_at": created["updated_at"],
        "images": [],
        "videos": [],
    }


def test_get_recipe_has_full_text_in_order(client: TestClient) -> None:
    client.post("/recipes", json=recipe_body())

    data = client.get("/recipes/dumplings").json()

    assert data["locale"] == "en"
    assert data["description"] == "Soft and filling."
    assert data["ingredients"] == ["500 g flour", "2 eggs"]
    assert data["steps"] == ["Mix", "Boil"]


def test_get_recipe_falls_back_like_the_list(client: TestClient) -> None:
    client.post("/recipes", json=recipe_body())

    data = client.get("/recipes/dumplings", params={"locale": "ru"}).json()

    assert (data["locale"], data["title"]) == ("en", "Dumplings")


def test_get_recipe_returns_images_and_videos_in_position_order(
    client: TestClient, db: sessionmaker[Session]
) -> None:
    client.post("/recipes", json=recipe_body())
    with db() as session, session.begin():
        recipe = session.scalars(select(Recipe)).one()
        recipe.images = [
            Image(position=1, storage_key="r/2.png", content_type="image/png"),
            Image(
                position=0,
                storage_key="r/1.jpg",
                content_type="image/jpeg",
                width=800,
                height=600,
            ),
        ]
        recipe.videos = [
            Video(position=1, storage_key="r/2.webm", content_type="video/webm"),
            Video(position=0, storage_key="r/1.mp4", content_type="video/mp4"),
        ]

    data = client.get("/recipes/dumplings").json()

    assert [(i["url"], i["content_type"], i["width"], i["height"]) for i in data["images"]] == [
        ("https://media.test/r/1.jpg", "image/jpeg", 800, 600),
        ("https://media.test/r/2.png", "image/png", None, None),
    ]
    assert [(v["url"], v["content_type"]) for v in data["videos"]] == [
        ("https://media.test/r/1.mp4", "video/mp4"),
        ("https://media.test/r/2.webm", "video/webm"),
    ]
    assert all(i["id"] for i in data["images"] + data["videos"])


def test_get_recipe_unknown_slug_is_404(client: TestClient) -> None:
    assert client.get("/recipes/nope").status_code == 404


def test_get_recipe_without_translations_is_404(
    client: TestClient, db: sessionmaker[Session], user_id: uuid.UUID
) -> None:
    with db() as session, session.begin():
        session.add(Recipe(slug="empty", owner_id=user_id))

    assert client.get("/recipes/empty").status_code == 404


def test_get_recipe_rejects_unknown_locale(client: TestClient) -> None:
    client.post("/recipes", json=recipe_body())
    assert client.get("/recipes/dumplings", params={"locale": "de"}).status_code == 422


MEDIA = [
    pytest.param("images", "image/png", 1000, ".png", id="image"),
    pytest.param("videos", "video/mp4", 1000, ".mp4", id="video"),
]


def upload(
    client: TestClient, storage: FakeStorage, kind: str, content_type: str, size: int = 1000
) -> str:
    """Do what a client does before confirming: get a key and put a file there."""
    body = {"content_type": content_type, "size_bytes": size}
    key = client.post(f"/recipes/dumplings/{kind}/uploads", json=body).json()["storage_key"]
    storage.objects[key] = StoredObject(size, content_type)
    return key


def test_content_type_lists_agree() -> None:
    assert set(get_args(schemas.ImageContentType)) == set(IMAGE_CONTENT_TYPES)
    assert set(get_args(schemas.VideoContentType)) == set(VIDEO_CONTENT_TYPES)


@pytest.mark.parametrize(("kind", "content_type", "size", "extension"), MEDIA)
def test_start_upload(
    client: TestClient, kind: str, content_type: str, size: int, extension: str
) -> None:
    recipe = client.post("/recipes", json=recipe_body()).json()

    response = client.post(
        f"/recipes/dumplings/{kind}/uploads",
        json={"content_type": content_type, "size_bytes": size},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["storage_key"].startswith(f"recipes/{recipe['id']}/")
    assert data["storage_key"].endswith(extension)
    assert data["upload_url"] == f"https://upload.test/{data['storage_key']}?type={content_type}"


@pytest.mark.parametrize(
    ("kind", "body"),
    [
        ("images", {"content_type": "image/gif", "size_bytes": 1}),
        ("images", {"content_type": "video/mp4", "size_bytes": 1}),
        ("images", {"content_type": "image/png", "size_bytes": MAX_IMAGE_BYTES + 1}),
        ("images", {"content_type": "image/png", "size_bytes": 0}),
        ("videos", {"content_type": "video/quicktime", "size_bytes": 1}),
        ("videos", {"content_type": "image/png", "size_bytes": 1}),
        ("videos", {"content_type": "video/mp4", "size_bytes": MAX_VIDEO_BYTES + 1}),
        ("videos", {"content_type": "video/mp4", "size_bytes": 1, "name": "x"}),
    ],
    ids=[
        "gif",
        "image-as-video-type",
        "image-too-large",
        "image-empty",
        "quicktime",
        "video-as-image-type",
        "video-too-large",
        "unknown-field",
    ],
)
def test_start_upload_rejects_invalid_files(
    client: TestClient, kind: str, body: dict[str, Any]
) -> None:
    client.post("/recipes", json=recipe_body())
    assert client.post(f"/recipes/dumplings/{kind}/uploads", json=body).status_code == 422


@pytest.mark.parametrize("kind", ["images", "videos"])
def test_media_routes_404_for_unknown_recipe(client: TestClient, kind: str) -> None:
    content_type = "image/png" if kind == "images" else "video/mp4"
    start = {"content_type": content_type, "size_bytes": 1}
    assert client.post(f"/recipes/nope/{kind}/uploads", json=start).status_code == 404
    assert client.post(f"/recipes/nope/{kind}", json={"storage_key": "k"}).status_code == 404


def test_add_image_uses_what_is_stored(client: TestClient, storage: FakeStorage) -> None:
    client.post("/recipes", json=recipe_body())
    key = upload(client, storage, "images", "image/png", 1234)

    response = client.post(
        "/recipes/dumplings/images", json={"storage_key": key, "width": 800, "height": 600}
    )

    assert response.status_code == 201
    data = response.json()
    assert data["url"] == f"https://media.test/{key}"
    assert (data["content_type"], data["width"], data["height"]) == ("image/png", 800, 600)


def test_add_video_records_size(
    client: TestClient, storage: FakeStorage, db: sessionmaker[Session]
) -> None:
    client.post("/recipes", json=recipe_body())
    key = upload(client, storage, "videos", "video/webm", 4321)

    response = client.post("/recipes/dumplings/videos", json={"storage_key": key})

    assert response.status_code == 201
    assert response.json()["content_type"] == "video/webm"
    with db() as session:
        assert session.scalars(select(Video)).one().size_bytes == 4321


@pytest.mark.parametrize(
    ("kind", "content_type"), [("images", "image/jpeg"), ("videos", "video/mp4")]
)
def test_added_media_keeps_upload_order(
    client: TestClient, storage: FakeStorage, kind: str, content_type: str
) -> None:
    client.post("/recipes", json=recipe_body())
    keys = [upload(client, storage, kind, content_type) for _ in range(3)]
    for key in keys:
        client.post(f"/recipes/dumplings/{kind}", json={"storage_key": key})

    media = client.get("/recipes/dumplings").json()[kind]

    assert [m["url"] for m in media] == [f"https://media.test/{key}" for key in keys]


def test_add_media_rejects_a_key_nothing_was_uploaded_to(client: TestClient) -> None:
    recipe = client.post("/recipes", json=recipe_body()).json()
    key = f"recipes/{recipe['id']}/missing.png"
    assert client.post("/recipes/dumplings/images", json={"storage_key": key}).status_code == 422


def test_add_media_rejects_another_recipes_upload(client: TestClient, storage: FakeStorage) -> None:
    client.post("/recipes", json=recipe_body())
    other = recipe_body(translations=[{"locale": "en", "title": "Soup"}])
    client.post("/recipes", json=other)
    key = upload(client, storage, "images", "image/png")

    assert client.post("/recipes/soup/images", json={"storage_key": key}).status_code == 422


def test_add_media_rejects_the_wrong_kind(client: TestClient, storage: FakeStorage) -> None:
    client.post("/recipes", json=recipe_body())
    key = upload(client, storage, "images", "image/png")

    assert client.post("/recipes/dumplings/videos", json={"storage_key": key}).status_code == 422


def test_add_media_rejects_a_type_changed_after_signing(
    client: TestClient, storage: FakeStorage
) -> None:
    client.post("/recipes", json=recipe_body())
    key = upload(client, storage, "images", "image/png")
    storage.objects[key] = StoredObject(1000, "text/html")

    assert client.post("/recipes/dumplings/images", json={"storage_key": key}).status_code == 422


def test_add_media_deletes_an_oversized_upload(client: TestClient, storage: FakeStorage) -> None:
    client.post("/recipes", json=recipe_body())
    key = upload(client, storage, "images", "image/png")
    storage.objects[key] = StoredObject(MAX_IMAGE_BYTES + 1, "image/png")

    response = client.post("/recipes/dumplings/images", json={"storage_key": key})

    assert response.status_code == 413
    assert key not in storage.objects
    assert client.get("/recipes/dumplings").json()["images"] == []


def test_add_media_twice_conflicts(client: TestClient, storage: FakeStorage) -> None:
    client.post("/recipes", json=recipe_body())
    key = upload(client, storage, "images", "image/png")
    client.post("/recipes/dumplings/images", json={"storage_key": key})

    assert client.post("/recipes/dumplings/images", json={"storage_key": key}).status_code == 409
    assert len(client.get("/recipes/dumplings").json()["images"]) == 1


def test_openapi_describes_media_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for kind in ("images", "videos"):
        assert "post" in paths[f"/recipes/{{slug}}/{kind}"]
        assert "post" in paths[f"/recipes/{{slug}}/{kind}/uploads"]


# Accounts: every recipe route needs a signed-in user and sees only that user's recipes.

ROUTES = [
    ("get", "/recipes", None),
    ("post", "/recipes", recipe_body()),
    ("get", "/recipes/dumplings", None),
    ("post", "/recipes/dumplings/images/uploads", {"content_type": "image/png", "size_bytes": 1}),
    ("post", "/recipes/dumplings/images", {"storage_key": "k"}),
    ("post", "/recipes/dumplings/videos/uploads", {"content_type": "video/mp4", "size_bytes": 1}),
    ("post", "/recipes/dumplings/videos", {"storage_key": "k"}),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_recipe_routes_require_sign_in(
    client: TestClient, anon: TestClient, method: str, path: str, body: Any
) -> None:
    client.post("/recipes", json=recipe_body())
    response = anon.request(method, path, json=body)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.fixture
def stranger(register: Callable[..., dict], signed_in: Callable[[str], TestClient]) -> TestClient:
    return signed_in(register("olek@example.com")["token"])


def test_users_see_only_their_own_recipes(client: TestClient, stranger: TestClient) -> None:
    client.post("/recipes", json=recipe_body())

    assert stranger.get("/recipes").json() == []
    assert stranger.get("/recipes/dumplings").status_code == 404
    assert [r["slug"] for r in client.get("/recipes").json()] == ["dumplings"]


@pytest.mark.parametrize("kind", ["images", "videos"])
def test_media_routes_404_for_another_users_recipe(
    client: TestClient, stranger: TestClient, storage: FakeStorage, kind: str
) -> None:
    client.post("/recipes", json=recipe_body())
    key = upload(client, storage, kind, "image/png" if kind == "images" else "video/mp4")
    start = {"content_type": storage.objects[key].content_type, "size_bytes": 1}

    assert stranger.post(f"/recipes/dumplings/{kind}/uploads", json=start).status_code == 404
    assert stranger.post(f"/recipes/dumplings/{kind}", json={"storage_key": key}).status_code == 404


def test_slugs_are_unique_per_user(client: TestClient, stranger: TestClient) -> None:
    assert client.post("/recipes", json=recipe_body()).json()["slug"] == "dumplings"
    assert stranger.post("/recipes", json=recipe_body()).json()["slug"] == "dumplings"


def test_openapi_marks_recipe_routes_as_secured(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert paths["/recipes"]["get"]["security"]
    assert paths["/recipes/{slug}/images"]["post"]["security"]
