"""create user and session tables

Revision ID: 411be2343bc7
Revises: 3f1caa5b2879
Create Date: 2026-11-11 12:00:00.000000

Adds `recipe.owner_id` as nullable. The next revision fills it in and makes it required:
a database that already has recipes stops here first, so someone can register.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "411be2343bc7"
down_revision: str | Sequence[str] | None = "3f1caa5b2879"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "user",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "user_session",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_user_session_user_id"), "user_session", ["user_id"], unique=False)
    # Batch mode, so SQLite (tests) can add the foreign key by recreating the table.
    with op.batch_alter_table("recipe") as batch:
        batch.add_column(sa.Column("owner_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_recipe_owner_id_user", "user", ["owner_id"], ["id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("recipe") as batch:
        batch.drop_constraint("fk_recipe_owner_id_user", type_="foreignkey")
        batch.drop_column("owner_id")
    op.drop_index(op.f("ix_user_session_user_id"), table_name="user_session")
    op.drop_table("user_session")
    op.drop_table("user")
