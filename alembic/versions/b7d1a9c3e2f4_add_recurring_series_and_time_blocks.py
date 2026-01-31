"""Add recurring task series and recurring time blocks

Revision ID: b7d1a9c3e2f4
Revises: 3f4d2b8c7a11, 1c8e2d4f0a21
Create Date: 2026-01-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7d1a9c3e2f4"
down_revision: Union[str, Sequence[str], None] = ("3f4d2b8c7a11", "1c8e2d4f0a21")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "recurring_task_series",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title_template", sa.String(), nullable=False),
        sa.Column("notes_template", sa.String(), nullable=True),
        sa.Column("estimated_duration_min_default", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("category_default", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("recurrence_preset", sa.JSON(), nullable=False),
        sa.Column("ai_excluded", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index(op.f("ix_recurring_task_series_user_id"), "recurring_task_series", ["user_id"], unique=False)
    op.create_index(op.f("ix_recurring_task_series_deleted_at"), "recurring_task_series", ["deleted_at"], unique=False)

    op.create_table(
        "recurring_time_blocks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("recurrence_preset", sa.JSON(), nullable=False),
        sa.Column("calendar_event_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index(op.f("ix_recurring_time_blocks_user_id"), "recurring_time_blocks", ["user_id"], unique=False)
    op.create_index(op.f("ix_recurring_time_blocks_calendar_event_id"), "recurring_time_blocks", ["calendar_event_id"], unique=False)
    op.create_index(op.f("ix_recurring_time_blocks_deleted_at"), "recurring_time_blocks", ["deleted_at"], unique=False)

    op.add_column("tasks", sa.Column("recurrence_series_id", sa.String(), nullable=True))
    op.add_column("tasks", sa.Column("recurrence_occurrence_start", sa.DateTime(), nullable=True))
    op.create_index(op.f("ix_tasks_recurrence_series_id"), "tasks", ["recurrence_series_id"], unique=False)
    op.create_index(op.f("ix_tasks_recurrence_occurrence_start"), "tasks", ["recurrence_occurrence_start"], unique=False)
    op.create_foreign_key(
        "fk_tasks_recurrence_series_id",
        "tasks",
        "recurring_task_series",
        ["recurrence_series_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_task_recurrence_occurrence",
        "tasks",
        ["user_id", "recurrence_series_id", "recurrence_occurrence_start"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_task_recurrence_occurrence", "tasks", type_="unique")
    op.drop_constraint("fk_tasks_recurrence_series_id", "tasks", type_="foreignkey")
    op.drop_index(op.f("ix_tasks_recurrence_occurrence_start"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_recurrence_series_id"), table_name="tasks")
    op.drop_column("tasks", "recurrence_occurrence_start")
    op.drop_column("tasks", "recurrence_series_id")

    op.drop_index(op.f("ix_recurring_time_blocks_deleted_at"), table_name="recurring_time_blocks")
    op.drop_index(op.f("ix_recurring_time_blocks_calendar_event_id"), table_name="recurring_time_blocks")
    op.drop_index(op.f("ix_recurring_time_blocks_user_id"), table_name="recurring_time_blocks")
    op.drop_table("recurring_time_blocks")

    op.drop_index(op.f("ix_recurring_task_series_deleted_at"), table_name="recurring_task_series")
    op.drop_index(op.f("ix_recurring_task_series_user_id"), table_name="recurring_task_series")
    op.drop_table("recurring_task_series")

