"""Repository for RecurringTaskSeries database operations."""

import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from qzwhatnext.database.models import RecurringTaskSeriesDB

logger = logging.getLogger(__name__)


class RecurringTaskSeriesRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        *,
        user_id: str,
        title_template: str,
        notes_template: Optional[str],
        estimated_duration_min_default: int,
        category_default: str,
        recurrence_preset: dict,
        ai_excluded: bool,
    ) -> RecurringTaskSeriesDB:
        row = RecurringTaskSeriesDB(
            user_id=user_id,
            title_template=title_template,
            notes_template=notes_template,
            estimated_duration_min_default=int(estimated_duration_min_default),
            category_default=str(category_default),
            recurrence_preset=recurrence_preset,
            ai_excluded=bool(ai_excluded),
        )
        try:
            self.db.add(row)
            self.db.commit()
            self.db.refresh(row)
            return row
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to create recurring task series: {type(e).__name__}: {str(e)}")
            raise

    def get(self, user_id: str, series_id: str) -> Optional[RecurringTaskSeriesDB]:
        return (
            self.db.query(RecurringTaskSeriesDB)
            .filter(
                RecurringTaskSeriesDB.user_id == user_id,
                RecurringTaskSeriesDB.id == series_id,
                RecurringTaskSeriesDB.deleted_at.is_(None),
            )
            .first()
        )

    def list_active(self, user_id: str) -> List[RecurringTaskSeriesDB]:
        return (
            self.db.query(RecurringTaskSeriesDB)
            .filter(
                RecurringTaskSeriesDB.user_id == user_id,
                RecurringTaskSeriesDB.deleted_at.is_(None),
            )
            .order_by(RecurringTaskSeriesDB.created_at.desc())
            .all()
        )

    def update_from_instruction(
        self,
        user_id: str,
        series_id: str,
        *,
        title_template: str,
        recurrence_preset: dict,
    ) -> Optional[RecurringTaskSeriesDB]:
        row = (
            self.db.query(RecurringTaskSeriesDB)
            .filter(
                RecurringTaskSeriesDB.user_id == user_id,
                RecurringTaskSeriesDB.id == series_id,
                RecurringTaskSeriesDB.deleted_at.is_(None),
            )
            .first()
        )
        if row is None:
            return None
        row.title_template = title_template
        row.recurrence_preset = recurrence_preset
        row.updated_at = datetime.utcnow()
        try:
            self.db.commit()
            self.db.refresh(row)
            return row
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to update recurring task series {series_id}: {type(e).__name__}: {str(e)}")
            raise

    def soft_delete(self, user_id: str, series_id: str) -> bool:
        row = (
            self.db.query(RecurringTaskSeriesDB)
            .filter(RecurringTaskSeriesDB.user_id == user_id, RecurringTaskSeriesDB.id == series_id)
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
            logger.error(f"Failed to soft delete recurring task series {series_id}: {type(e).__name__}: {str(e)}")
            raise

