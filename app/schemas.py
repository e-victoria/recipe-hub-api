import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)
from pydantic_core import PydanticCustomError

from app.models import Locale
from app.storage import MAX_IMAGE_BYTES, MAX_VIDEO_BYTES

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Minutes = Annotated[int, Field(ge=0)]
Pixels = Annotated[int, Field(ge=1)]
# Keep in step with IMAGE_CONTENT_TYPES and VIDEO_CONTENT_TYPES in app/storage.py.
ImageContentType = Literal["image/jpeg", "image/png", "image/webp"]
VideoContentType = Literal["video/mp4", "video/webm"]


def _blank_to_none(value: object) -> object:
    return None if isinstance(value, str) and not value.strip() else value


# A form field left empty arrives as "" and means "no description".
OptionalText = Annotated[Text | None, BeforeValidator(_blank_to_none)]


class RecipeTranslationIn(BaseModel):
    # Reject unknown fields so a misspelled one fails loudly instead of being dropped.
    model_config = ConfigDict(extra="forbid")

    locale: Locale
    title: Title
    description: OptionalText = None
    ingredients: list[Text] = []
    steps: list[Text] = []


class RecipeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    servings: Annotated[int, Field(ge=1)] | None = None
    prep_minutes: Minutes | None = None
    cook_minutes: Minutes | None = None
    translations: Annotated[list[RecipeTranslationIn], Field(min_length=1)]

    @field_validator("translations")
    @classmethod
    def one_per_locale(cls, value: list[RecipeTranslationIn]) -> list[RecipeTranslationIn]:
        locales = [t.locale for t in value]
        if len(set(locales)) != len(locales):
            # A stable error type clients can map to a translated message.
            raise PydanticCustomError("duplicate_locale", "each locale may appear only once")
        return value


class RecipeTranslationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    locale: Locale
    title: str
    description: str | None
    ingredients: list[str]
    steps: list[str]


class Recipe(BaseModel):
    """A recipe with every translation it has."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    servings: int | None
    prep_minutes: int | None
    cook_minutes: int | None
    created_at: datetime
    updated_at: datetime
    translations: list[RecipeTranslationOut]


class RecipeSummary(BaseModel):
    """A recipe for lists, in one locale. `locale` says which one the text is in."""

    id: uuid.UUID
    slug: str
    locale: Locale
    title: str
    description: str | None
    servings: int | None
    prep_minutes: int | None
    cook_minutes: int | None
    created_at: datetime


class RecipeImage(BaseModel):
    """`url` is presigned and expires; fetch the recipe again for a fresh one."""

    id: uuid.UUID
    url: str
    content_type: str
    width: int | None
    height: int | None


class RecipeVideo(BaseModel):
    """`url` is presigned and expires; fetch the recipe again for a fresh one."""

    id: uuid.UUID
    url: str
    content_type: str


class ImageUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: ImageContentType
    size_bytes: Annotated[int, Field(ge=1, le=MAX_IMAGE_BYTES)]


class VideoUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: VideoContentType
    size_bytes: Annotated[int, Field(ge=1, le=MAX_VIDEO_BYTES)]


class MediaUpload(BaseModel):
    """PUT the file to `upload_url` with the same Content-Type, then confirm `storage_key`."""

    storage_key: str
    upload_url: str


class ImageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storage_key: str
    width: Pixels | None = None
    height: Pixels | None = None


class VideoCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storage_key: str


class RecipeDetail(BaseModel):
    """A full recipe in one locale. `locale` says which one the text is in."""

    id: uuid.UUID
    slug: str
    locale: Locale
    title: str
    description: str | None
    ingredients: list[str]
    steps: list[str]
    servings: int | None
    prep_minutes: int | None
    cook_minutes: int | None
    created_at: datetime
    updated_at: datetime
    # In display order; the first image is the cover.
    images: list[RecipeImage]
    videos: list[RecipeVideo]


# Accounts

# Deliberately loose: the only real check is sending mail to it, which comes with verification.
Email = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, to_lower=True, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    ),
]
# Not stripped: spaces are part of a password. The cap keeps hashing cheap to refuse.
NewPassword = Annotated[str, StringConstraints(min_length=8, max_length=128)]
Password = Annotated[str, StringConstraints(min_length=1, max_length=128)]


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Email
    password: NewPassword


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Email
    password: Password


class User(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    created_at: datetime


class AuthSession(BaseModel):
    """Send `token` as `Authorization: Bearer <token>` until `expires_at`."""

    token: str
    expires_at: datetime
    user: User
