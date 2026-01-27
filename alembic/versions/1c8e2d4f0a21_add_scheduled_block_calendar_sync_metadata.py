"""Add ScheduledBlock calendar sync metadata fields

Revision ID: 1c8e2d4f0a21
Revises: 7b2c9f1f6c20
Create Date: 2026-01-26

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1c8e2d4f0a21"
down_revision: Union[str, Sequence[str], None] = "7b2c9f1f6c20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("scheduled_blocks", sa.Column("calendar_event_etag", sa.String(), nullable=True))
    op.add_column("scheduled_blocks", sa.Column("calendar_event_updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("scheduled_blocks", "calendar_event_updated_at")
    op.drop_column("scheduled_blocks", "calendar_event_etag")

