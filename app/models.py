import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# JSONB on Postgres, JSON elsewhere (tests). MutableList tracks in-place edits like .append().
StringList = MutableList.as_mutable(JSON().with_variant(JSONB(), "postgresql"))


class Locale(enum.StrEnum):
    en = "en"
    ru = "ru"
    pl = "pl"


class Recipe(Base):
    """Language-neutral recipe data. Text lives in RecipeTranslation."""

    __tablename__ = "recipe"
    # Fetch server-set timestamps after INSERT and UPDATE, so they are readable after commit.
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(200), unique=True)
    servings: Mapped[int | None] = mapped_column(Integer)
    prep_minutes: Mapped[int | None] = mapped_column(Integer)
    cook_minutes: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    translations: Mapped[list["RecipeTranslation"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan"
    )
    images: Mapped[list["Image"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", order_by="Image.position"
    )


class RecipeTranslation(Base):
    __tablename__ = "recipe_translation"
    __table_args__ = (UniqueConstraint("recipe_id", "locale"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recipe.id", ondelete="CASCADE"))
    locale: Mapped[Locale] = mapped_column(
        Enum(Locale, name="locale", values_callable=lambda e: [m.value for m in e])
    )
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    # Ordered lists of strings, e.g. ["200 g flour", "2 eggs"].
    ingredients: Mapped[list[str]] = mapped_column(StringList, default=list)
    steps: Mapped[list[str]] = mapped_column(StringList, default=list)

    recipe: Mapped[Recipe] = relationship(back_populates="translations")


class Image(Base):
    """Metadata for an object in S3. The bytes never touch the database."""

    __tablename__ = "image"
    __table_args__ = (Index("ix_image_recipe_id_position", "recipe_id", "position"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    recipe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recipe.id", ondelete="CASCADE"))
    # Display order; the lowest is the cover. Not unique, so reordering needs no swaps.
    position: Mapped[int] = mapped_column(Integer, default=0)
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    recipe: Mapped[Recipe] = relationship(back_populates="images")
