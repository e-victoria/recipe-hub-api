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


class User(Base):
    """One person's account. Family members are profiles inside it, not logins."""

    __tablename__ = "user"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Stored trimmed and lowercased, so lookups are exact matches.
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sessions: Mapped[list["UserSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserSession(Base):
    """A signed-in device. Only a hash of its token is stored, so a database leak can't sign in."""

    __tablename__ = "user_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="sessions")


class Recipe(Base):
    """Language-neutral recipe data. Text lives in RecipeTranslation."""

    __tablename__ = "recipe"
    # Slugs only need to be unique per owner: each user's URLs are their own.
    __table_args__ = (UniqueConstraint("owner_id", "slug"),)
    # Fetch server-set timestamps after INSERT and UPDATE, so they are readable after commit.
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(200))
    servings: Mapped[int | None] = mapped_column(Integer)
    prep_minutes: Mapped[int | None] = mapped_column(Integer)
    cook_minutes: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped[User] = relationship()
    translations: Mapped[list["RecipeTranslation"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan"
    )
    images: Mapped[list["Image"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", order_by="Image.position"
    )
    videos: Mapped[list["Video"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", order_by="Video.position"
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


class Video(Base):
    """Metadata for an object in S3, like Image."""

    __tablename__ = "video"
    __table_args__ = (Index("ix_video_recipe_id_position", "recipe_id", "position"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    recipe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recipe.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    recipe: Mapped[Recipe] = relationship(back_populates="videos")
