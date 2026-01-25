"""Add google_oauth_tokens table for per-user Google integrations

Revision ID: 7b2c9f1f6c20
Revises: 3f4d2b8c7a11
Create Date: 2026-01-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7b2c9f1f6c20"
down_revision: Union[str, Sequence[str], None] = "3f4d2b8c7a11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "google_oauth_tokens",
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("product", sa.String(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.String(), nullable=False),
        sa.Column("access_token_encrypted", sa.String(), nullable=True),
        sa.Column("expiry", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "provider", "product"),
    )
    op.create_index(op.f("ix_google_oauth_tokens_user_id"), "google_oauth_tokens", ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_google_oauth_tokens_user_id"), table_name="google_oauth_tokens")
    op.drop_table("google_oauth_tokens")

