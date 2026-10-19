import functools
import uuid

import boto3
from botocore.client import BaseClient
from botocore.config import Config

from app.settings import settings

# Image types we accept, mapped to the file extension used in storage keys.
IMAGE_CONTENT_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
PRESIGN_SECONDS = 15 * 60


class UnsupportedImageType(ValueError):
    pass


def image_key(recipe_id: uuid.UUID, content_type: str) -> str:
    try:
        ext = IMAGE_CONTENT_TYPES[content_type]
    except KeyError:
        raise UnsupportedImageType(content_type) from None
    return f"recipes/{recipe_id}/{uuid.uuid4()}.{ext}"


def make_client() -> BaseClient:
    # Local S3-compatible servers need path-style URLs; AWS uses its default (virtual-hosted).
    addressing = "path" if settings.s3_endpoint_url else "auto"
    return boto3.client(
        "s3",
        region_name=settings.s3_region,
        endpoint_url=settings.s3_endpoint_url,
        config=Config(signature_version="s3v4", s3={"addressing_style": addressing}),
    )


class ImageStorage:
    def __init__(self, client: BaseClient, bucket: str) -> None:
        self.client = client
        self.bucket = bucket

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def upload_url(self, key: str, content_type: str) -> str:
        """Presigned PUT so clients upload straight to the bucket."""
        return self.client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=PRESIGN_SECONDS,
        )

    def download_url(self, key: str) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=PRESIGN_SECONDS,
        )


@functools.cache
def get_storage() -> ImageStorage:
    """FastAPI dependency. One shared client: creating clients isn't thread-safe, using one is."""
    return ImageStorage(make_client(), settings.s3_bucket)
