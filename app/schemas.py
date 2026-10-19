import uuid
from datetime import datetime
from typing import Annotated

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

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Minutes = Annotated[int, Field(ge=0)]


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
