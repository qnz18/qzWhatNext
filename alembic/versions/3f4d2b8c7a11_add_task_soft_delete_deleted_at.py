"""Add deleted_at to tasks for soft delete

Revision ID: 3f4d2b8c7a11
Revises: 9ca209918cf6
Create Date: 2026-01-25

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3f4d2b8c7a11"
down_revision: Union[str, Sequence[str], None] = "9ca209918cf6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("tasks", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.create_index(op.f("ix_tasks_deleted_at"), "tasks", ["deleted_at"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_tasks_deleted_at"), table_name="tasks")
    op.drop_column("tasks", "deleted_at")

