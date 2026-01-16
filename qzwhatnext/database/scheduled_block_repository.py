"""Repository for ScheduledBlock database operations."""

import logging
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc

from qzwhatnext.models.scheduled_block import ScheduledBlock
from qzwhatnext.database.models import ScheduledBlockDB

logger = logging.getLogger(__name__)


class ScheduledBlockRepository:
    """Repository for ScheduledBlock database operations."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create(self, block: ScheduledBlock) -> ScheduledBlock:
        """Create a new scheduled block."""
        try:
            block_db = ScheduledBlockDB.from_pydantic(block)
            self.db.add(block_db)
            self.db.commit()
            self.db.refresh(block_db)
            logger.debug(f"Created scheduled block {block.id}")
            return block_db.to_pydantic()
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to create scheduled block {block.id}: {type(e).__name__}: {str(e)}")
            raise
    
    def get_all(self, user_id: str) -> List[ScheduledBlock]:
        """Get all scheduled blocks for a user sorted by start_time."""
        blocks_db = self.db.query(ScheduledBlockDB).filter(
            ScheduledBlockDB.user_id == user_id
        ).order_by(ScheduledBlockDB.start_time).all()
        return [block_db.to_pydantic() for block_db in blocks_db]
    
    def delete_all_for_user(self, user_id: str) -> int:
        """Delete all scheduled blocks for a user (used when rebuilding schedule).
        
        Returns:
            Number of blocks deleted
        """
        try:
            deleted_count = self.db.query(ScheduledBlockDB).filter(
                ScheduledBlockDB.user_id == user_id
            ).delete()
            self.db.commit()
            logger.debug(f"Deleted {deleted_count} scheduled blocks for user {user_id}")
            return deleted_count
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to delete scheduled blocks for user {user_id}: {type(e).__name__}: {str(e)}")
            raise
    
    def create_batch(self, blocks: List[ScheduledBlock]) -> List[ScheduledBlock]:
        """Create multiple scheduled blocks in a batch."""
        try:
            blocks_db = [ScheduledBlockDB.from_pydantic(block) for block in blocks]
            self.db.add_all(blocks_db)
            self.db.commit()
            for block_db in blocks_db:
                self.db.refresh(block_db)
            logger.debug(f"Created {len(blocks)} scheduled blocks")
            return [block_db.to_pydantic() for block_db in blocks_db]
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to create scheduled blocks: {type(e).__name__}: {str(e)}")
            raise

