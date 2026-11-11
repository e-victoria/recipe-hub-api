"""require recipe owner

Revision ID: 678f6d3d70da
Revises: 411be2343bc7
Create Date: 2026-11-11 12:00:01.000000

Recipes made before accounts existed go to the earliest registered user. If there are such
recipes and no users yet, this stops with instructions instead of guessing.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "678f6d3d70da"
down_revision: str | Sequence[str] | None = "411be2343bc7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# SQLite leaves the original slug constraint unnamed; this names it so batch mode can drop it.
NAMING = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def old_slug_constraint() -> str:
    # Postgres named it when the table was created.
    return "recipe_slug_key" if op.get_bind().dialect.name == "postgresql" else "uq_recipe_slug"


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    orphans = conn.execute(sa.text("SELECT count(*) FROM recipe WHERE owner_id IS NULL")).scalar()
    if orphans:
        first_user = conn.execute(
            sa.text('SELECT id FROM "user" ORDER BY created_at, id LIMIT 1')
        ).scalar()
        if first_user is None:
            raise RuntimeError(
                f"{orphans} recipes have no owner and no user exists to give them to. "
                "Run `alembic upgrade 411be2343bc7`, start the API, register your account, "
                "then run `alembic upgrade head` again."
            )
        conn.execute(
            sa.text("UPDATE recipe SET owner_id = :owner WHERE owner_id IS NULL"),
            {"owner": first_user},
        )

    with op.batch_alter_table("recipe", naming_convention=NAMING) as batch:
        batch.alter_column("owner_id", existing_type=sa.Uuid(), nullable=False)
        batch.drop_constraint(old_slug_constraint(), type_="unique")
        batch.create_unique_constraint("uq_recipe_owner_id_slug", ["owner_id", "slug"])


def downgrade() -> None:
    """Downgrade schema.

    Fails if two users have recipes with the same slug, since slugs become global again.
    """
    with op.batch_alter_table("recipe", naming_convention=NAMING) as batch:
        batch.drop_constraint("uq_recipe_owner_id_slug", type_="unique")
        batch.create_unique_constraint(old_slug_constraint(), ["slug"])
        batch.alter_column("owner_id", existing_type=sa.Uuid(), nullable=True)
