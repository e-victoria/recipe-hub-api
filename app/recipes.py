from collections.abc import Container, Iterable
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import models, schemas
from app.auth import CurrentUser
from app.db import get_session
from app.slugs import slugify
from app.storage import (
    IMAGE_CONTENT_TYPES,
    MAX_IMAGE_BYTES,
    MAX_VIDEO_BYTES,
    VIDEO_CONTENT_TYPES,
    ImageStorage,
    StoredObject,
    get_storage,
    image_key,
    video_key,
)

router = APIRouter(prefix="/recipes", tags=["recipes"])

SessionDep = Annotated[Session, Depends(get_session)]
StorageDep = Annotated[ImageStorage, Depends(get_storage)]

# A concurrent create can take the slug between our check and our commit; retry that many times.
SLUG_ATTEMPTS = 3

# Clients put slugs after /recipes/, so a slug must not equal a fixed page there.
RESERVED_SLUGS = {"new"}


class Localized(Protocol):
    locale: models.Locale


def pick_translation[T: Localized](translations: Iterable[T], locale: models.Locale) -> T:
    """The requested locale, else English, else the first in locale order (en, ru, pl)."""
    by_locale = {t.locale: t for t in translations}
    for candidate in (locale, models.Locale.en, *models.Locale):
        if candidate in by_locale:
            return by_locale[candidate]
    raise ValueError("no translations to pick from")


def unique_slug(session: Session, owner: models.User, title: str) -> str:
    base = slugify(title)
    taken = RESERVED_SLUGS | set(
        session.scalars(
            select(models.Recipe.slug).where(
                models.Recipe.owner_id == owner.id,
                or_(models.Recipe.slug == base, models.Recipe.slug.startswith(f"{base}-")),
            )
        )
    )
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


def find_recipe(session: Session, owner: models.User, slug: str) -> models.Recipe:
    """The owner's recipe. Someone else's is a 404, so clients can't probe for slugs."""
    recipe = session.scalars(
        select(models.Recipe)
        .options(
            selectinload(models.Recipe.translations),
            selectinload(models.Recipe.images),
            selectinload(models.Recipe.videos),
        )
        .where(models.Recipe.owner_id == owner.id, models.Recipe.slug == slug)
    ).one_or_none()
    # A recipe with no text can't be shown, so it doesn't exist as far as clients can tell.
    if recipe is None or not recipe.translations:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="recipe not found")
    return recipe


def image_out(image: models.Image, storage: ImageStorage) -> schemas.RecipeImage:
    return schemas.RecipeImage(
        id=image.id,
        url=storage.download_url(image.storage_key),
        content_type=image.content_type,
        width=image.width,
        height=image.height,
    )


def video_out(video: models.Video, storage: ImageStorage) -> schemas.RecipeVideo:
    return schemas.RecipeVideo(
        id=video.id,
        url=storage.download_url(video.storage_key),
        content_type=video.content_type,
    )


def uploaded_object(
    storage: ImageStorage,
    recipe: models.Recipe,
    key: str,
    content_types: Container[str],
    max_bytes: int,
) -> StoredObject:
    """Check the stored object itself: a signed URL can't limit what is uploaded through it."""
    stored = storage.head(key) if key.startswith(f"recipes/{recipe.id}/") else None
    if stored is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="upload not found")
    if stored.content_type not in content_types:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="wrong file type")
    if stored.size_bytes > max_bytes:
        storage.delete(key)
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail="file too large")
    return stored


def next_position(media: Iterable[models.Image | models.Video]) -> int:
    return max((item.position for item in media), default=-1) + 1


def commit_media(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail="upload already added") from None


@router.get("", response_model=list[schemas.RecipeSummary], status_code=status.HTTP_200_OK)
def list_recipes(
    session: SessionDep,
    user: CurrentUser,
    locale: models.Locale = models.Locale.en,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[schemas.RecipeSummary]:
    """Recipes, newest first, with text in `locale` where a translation exists."""
    recipes = session.scalars(
        select(models.Recipe)
        .options(selectinload(models.Recipe.translations))
        # A recipe with no text can't be listed; skip it in SQL so paging stays exact.
        .where(models.Recipe.owner_id == user.id, models.Recipe.translations.any())
        .order_by(models.Recipe.created_at.desc(), models.Recipe.id)
        .limit(limit)
        .offset(offset)
    )
    summaries = []
    for recipe in recipes:
        text = pick_translation(recipe.translations, locale)
        summaries.append(
            schemas.RecipeSummary(
                id=recipe.id,
                slug=recipe.slug,
                locale=text.locale,
                title=text.title,
                description=text.description,
                servings=recipe.servings,
                prep_minutes=recipe.prep_minutes,
                cook_minutes=recipe.cook_minutes,
                created_at=recipe.created_at,
            )
        )
    return summaries


@router.get("/{slug}", response_model=schemas.RecipeDetail, status_code=status.HTTP_200_OK)
def get_recipe(
    slug: str,
    session: SessionDep,
    storage: StorageDep,
    user: CurrentUser,
    locale: models.Locale = models.Locale.en,
) -> schemas.RecipeDetail:
    """One recipe with its media, with text in `locale` where a translation exists."""
    recipe = find_recipe(session, user, slug)
    text = pick_translation(recipe.translations, locale)
    return schemas.RecipeDetail(
        id=recipe.id,
        slug=recipe.slug,
        locale=text.locale,
        title=text.title,
        description=text.description,
        ingredients=text.ingredients,
        steps=text.steps,
        servings=recipe.servings,
        prep_minutes=recipe.prep_minutes,
        cook_minutes=recipe.cook_minutes,
        created_at=recipe.created_at,
        updated_at=recipe.updated_at,
        images=[image_out(image, storage) for image in recipe.images],
        videos=[video_out(video, storage) for video in recipe.videos],
    )


@router.post("", response_model=schemas.Recipe, status_code=status.HTTP_201_CREATED)
def create_recipe(
    body: schemas.RecipeCreate, session: SessionDep, user: CurrentUser
) -> schemas.Recipe:
    # Same rule as the English list, so the slug matches the title shown there.
    slug_source = pick_translation(body.translations, models.Locale.en)
    for _ in range(SLUG_ATTEMPTS):
        recipe = models.Recipe(
            owner_id=user.id,
            slug=unique_slug(session, user, slug_source.title),
            servings=body.servings,
            prep_minutes=body.prep_minutes,
            cook_minutes=body.cook_minutes,
            translations=[models.RecipeTranslation(**t.model_dump()) for t in body.translations],
        )
        session.add(recipe)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            continue
        return schemas.Recipe.model_validate(recipe)
    raise HTTPException(status.HTTP_409_CONFLICT, detail="could not allocate a unique slug")


@router.post(
    "/{slug}/images/uploads",
    response_model=schemas.MediaUpload,
    status_code=status.HTTP_201_CREATED,
)
def start_image_upload(
    slug: str,
    body: schemas.ImageUploadRequest,
    session: SessionDep,
    storage: StorageDep,
    user: CurrentUser,
) -> schemas.MediaUpload:
    """A URL to upload an image to. Add it to the recipe afterwards with POST /images."""
    key = image_key(find_recipe(session, user, slug).id, body.content_type)
    return schemas.MediaUpload(
        storage_key=key, upload_url=storage.upload_url(key, body.content_type)
    )


@router.post(
    "/{slug}/images", response_model=schemas.RecipeImage, status_code=status.HTTP_201_CREATED
)
def add_image(
    slug: str,
    body: schemas.ImageCreate,
    session: SessionDep,
    storage: StorageDep,
    user: CurrentUser,
) -> schemas.RecipeImage:
    """Add an uploaded image after the recipe's other images."""
    recipe = find_recipe(session, user, slug)
    stored = uploaded_object(
        storage, recipe, body.storage_key, IMAGE_CONTENT_TYPES, MAX_IMAGE_BYTES
    )
    image = models.Image(
        position=next_position(recipe.images),
        storage_key=body.storage_key,
        content_type=stored.content_type,
        size_bytes=stored.size_bytes,
        width=body.width,
        height=body.height,
    )
    recipe.images.append(image)
    commit_media(session)
    return image_out(image, storage)


@router.post(
    "/{slug}/videos/uploads",
    response_model=schemas.MediaUpload,
    status_code=status.HTTP_201_CREATED,
)
def start_video_upload(
    slug: str,
    body: schemas.VideoUploadRequest,
    session: SessionDep,
    storage: StorageDep,
    user: CurrentUser,
) -> schemas.MediaUpload:
    """A URL to upload a video to. Add it to the recipe afterwards with POST /videos."""
    key = video_key(find_recipe(session, user, slug).id, body.content_type)
    return schemas.MediaUpload(
        storage_key=key, upload_url=storage.upload_url(key, body.content_type)
    )


@router.post(
    "/{slug}/videos", response_model=schemas.RecipeVideo, status_code=status.HTTP_201_CREATED
)
def add_video(
    slug: str,
    body: schemas.VideoCreate,
    session: SessionDep,
    storage: StorageDep,
    user: CurrentUser,
) -> schemas.RecipeVideo:
    """Add an uploaded video after the recipe's other videos."""
    recipe = find_recipe(session, user, slug)
    stored = uploaded_object(
        storage, recipe, body.storage_key, VIDEO_CONTENT_TYPES, MAX_VIDEO_BYTES
    )
    video = models.Video(
        position=next_position(recipe.videos),
        storage_key=body.storage_key,
        content_type=stored.content_type,
        size_bytes=stored.size_bytes,
    )
    recipe.videos.append(video)
    commit_media(session)
    return video_out(video, storage)
