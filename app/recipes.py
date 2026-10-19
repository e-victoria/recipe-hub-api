from collections.abc import Iterable
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import models, schemas
from app.db import get_session
from app.slugs import slugify

router = APIRouter(prefix="/recipes", tags=["recipes"])

SessionDep = Annotated[Session, Depends(get_session)]

# A concurrent create can take the slug between our check and our commit; retry that many times.
SLUG_ATTEMPTS = 3


class Localized(Protocol):
    locale: models.Locale


def pick_translation[T: Localized](translations: Iterable[T], locale: models.Locale) -> T:
    """The requested locale, else English, else the first in locale order (en, ru, pl)."""
    by_locale = {t.locale: t for t in translations}
    for candidate in (locale, models.Locale.en, *models.Locale):
        if candidate in by_locale:
            return by_locale[candidate]
    raise ValueError("no translations to pick from")


def unique_slug(session: Session, title: str) -> str:
    base = slugify(title)
    taken = set(
        session.scalars(
            select(models.Recipe.slug).where(
                or_(models.Recipe.slug == base, models.Recipe.slug.startswith(f"{base}-"))
            )
        )
    )
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


@router.get("", response_model=list[schemas.RecipeSummary], status_code=status.HTTP_200_OK)
def list_recipes(
    session: SessionDep,
    locale: models.Locale = models.Locale.en,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[schemas.RecipeSummary]:
    """Recipes, newest first, with text in `locale` where a translation exists."""
    recipes = session.scalars(
        select(models.Recipe)
        .options(selectinload(models.Recipe.translations))
        # A recipe with no text can't be listed; skip it in SQL so paging stays exact.
        .where(models.Recipe.translations.any())
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


@router.post("", response_model=schemas.Recipe, status_code=status.HTTP_201_CREATED)
def create_recipe(body: schemas.RecipeCreate, session: SessionDep) -> schemas.Recipe:
    # Same rule as the English list, so the slug matches the title shown there.
    slug_source = pick_translation(body.translations, models.Locale.en)
    for _ in range(SLUG_ATTEMPTS):
        recipe = models.Recipe(
            slug=unique_slug(session, slug_source.title),
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
