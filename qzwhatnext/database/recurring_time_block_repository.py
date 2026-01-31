"""Repository for RecurringTimeBlock database operations."""

import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from qzwhatnext.database.models import RecurringTimeBlockDB

logger = logging.getLogger(__name__)


class RecurringTimeBlockRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        block_id: Optional[str] = None,
        user_id: str,
        title: str,
        recurrence_preset: dict,
        calendar_event_id: Optional[str],
    ) -> RecurringTimeBlockDB:
        row = RecurringTimeBlockDB(
            id=block_id,
            user_id=user_id,
            title=title,
            recurrence_preset=recurrence_preset,
            calendar_event_id=calendar_event_id,
        )
        try:
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
            return row
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to create recurring time block: {type(e).__name__}: {str(e)}")
            raise

    def get(self, user_id: str, block_id: str) -> Optional[RecurringTimeBlockDB]:
        return (
            self.db.query(RecurringTimeBlockDB)
            .filter(
                RecurringTimeBlockDB.user_id == user_id,
                RecurringTimeBlockDB.id == block_id,
                RecurringTimeBlockDB.deleted_at.is_(None),
            )
            .first()
        )

    def list_active(self, user_id: str) -> List[RecurringTimeBlockDB]:
        return (
            self.db.query(RecurringTimeBlockDB)
            .filter(
                RecurringTimeBlockDB.user_id == user_id,
                RecurringTimeBlockDB.deleted_at.is_(None),
            )
            .order_by(RecurringTimeBlockDB.created_at.desc())
            .all()
        )

    def update_from_instruction(
        self,
        user_id: str,
        block_id: str,
        *,
        title: str,
        recurrence_preset: dict,
        calendar_event_id: Optional[str],
    ) -> Optional[RecurringTimeBlockDB]:
        row = (
            self.db.query(RecurringTimeBlockDB)
            .filter(
                RecurringTimeBlockDB.user_id == user_id,
                RecurringTimeBlockDB.id == block_id,
                RecurringTimeBlockDB.deleted_at.is_(None),
            )
            .first()
        )
        if row is None:
            return None
        row.title = title
        row.recurrence_preset = recurrence_preset
        if calendar_event_id is not None:
            row.calendar_event_id = calendar_event_id
        row.updated_at = datetime.utcnow()
        try:
            self.db.commit()
            self.db.refresh(row)
            return row
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to update recurring time block {block_id}: {type(e).__name__}: {str(e)}")
            raise

    def soft_delete(self, user_id: str, block_id: str) -> bool:
        row = (
            self.db.query(RecurringTimeBlockDB)
            .filter(RecurringTimeBlockDB.user_id == user_id, RecurringTimeBlockDB.id == block_id)
            .first()
        )
        if row is None or row.deleted_at is not None:
            return False
        row.deleted_at = datetime.utcnow()
        try:
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to soft delete recurring time block {block_id}: {type(e).__name__}: {str(e)}")
            raise

