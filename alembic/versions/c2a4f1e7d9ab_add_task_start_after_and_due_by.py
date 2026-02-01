"""Add start_after and due_by to tasks

Revision ID: c2a4f1e7d9ab
Revises: b7d1a9c3e2f4
Create Date: 2026-02-01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c2a4f1e7d9ab"
down_revision: Union[str, Sequence[str], None] = "b7d1a9c3e2f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("tasks", sa.Column("start_after", sa.Date(), nullable=True))
    op.add_column("tasks", sa.Column("due_by", sa.Date(), nullable=True))
    op.create_index(op.f("ix_tasks_start_after"), "tasks", ["start_after"], unique=False)
    op.create_index(op.f("ix_tasks_due_by"), "tasks", ["due_by"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_tasks_due_by"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_start_after"), table_name="tasks")
    op.drop_column("tasks", "due_by")
    op.drop_column("tasks", "start_after")

