import dataclasses
import uuid
from collections.abc import Iterator
from urllib.parse import parse_qs, urlsplit

import pytest
from moto import mock_aws

import app.storage
from app.storage import (
    PRESIGN_SECONDS,
    ImageStorage,
    UnsupportedImageType,
    image_key,
    make_client,
)

BUCKET = "test-images"


@pytest.fixture(autouse=True)
def isolated_aws(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep the developer's shell (.env exported, AWS profiles) out of the tests.
    for name in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_ENDPOINT_URL", "AWS_ENDPOINT_URL_S3"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    use_settings(monkeypatch, s3_endpoint_url=None, s3_region="us-east-1")


def use_settings(monkeypatch: pytest.MonkeyPatch, **changes: object) -> None:
    patched = dataclasses.replace(app.storage.settings, **changes)
    monkeypatch.setattr(app.storage, "settings", patched)


@pytest.fixture
def storage() -> Iterator[ImageStorage]:
    with mock_aws():
        client = make_client()
        client.create_bucket(Bucket=BUCKET)
        yield ImageStorage(client, BUCKET)


def query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def test_image_key_is_namespaced_by_recipe() -> None:
    recipe_id = uuid.uuid4()
    key = image_key(recipe_id, "image/webp")
    prefix, rid, name = key.split("/")
    assert (prefix, rid) == ("recipes", str(recipe_id))
    assert name.endswith(".webp")
    assert key != image_key(recipe_id, "image/webp")


def test_image_key_rejects_other_types() -> None:
    with pytest.raises(UnsupportedImageType):
        image_key(uuid.uuid4(), "image/gif")


def test_put_and_delete(storage: ImageStorage) -> None:
    storage.put("recipes/x/1.png", b"png-bytes", "image/png")
    obj = storage.client.get_object(Bucket=BUCKET, Key="recipes/x/1.png")
    assert obj["Body"].read() == b"png-bytes"
    assert obj["ContentType"] == "image/png"

    storage.delete("recipes/x/1.png")
    assert storage.client.list_objects_v2(Bucket=BUCKET).get("KeyCount") == 0


def test_upload_url_signs_content_type_and_expires(storage: ImageStorage) -> None:
    url = storage.upload_url("recipes/x/1.jpg", "image/jpeg")
    params = query(url)
    assert urlsplit(url).hostname == f"{BUCKET}.s3.amazonaws.com"
    assert urlsplit(url).path == "/recipes/x/1.jpg"
    assert params["X-Amz-Algorithm"] == "AWS4-HMAC-SHA256"
    assert params["X-Amz-Expires"] == str(PRESIGN_SECONDS)
    assert "content-type" in params["X-Amz-SignedHeaders"].split(";")


def test_download_url(storage: ImageStorage) -> None:
    url = storage.download_url("recipes/x/1.jpg")
    assert urlsplit(url).path == "/recipes/x/1.jpg"
    assert query(url)["X-Amz-Expires"] == str(PRESIGN_SECONDS)


def test_local_endpoint_uses_path_style(monkeypatch: pytest.MonkeyPatch) -> None:
    use_settings(monkeypatch, s3_endpoint_url="http://localhost:9000")
    url = ImageStorage(make_client(), BUCKET).download_url("recipes/x/1.jpg")
    assert url.startswith(f"http://localhost:9000/{BUCKET}/recipes/x/1.jpg?")
