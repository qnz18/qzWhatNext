"""Repository for User database operations."""

import logging
from typing import Optional
from sqlalchemy.orm import Session

from qzwhatnext.models.user import User
from qzwhatnext.database.models import UserDB

logger = logging.getLogger(__name__)


class UserRepository:
    """Repository for User database operations."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def get(self, user_id: str) -> Optional[User]:
        """Get user by ID."""
        user_db = self.db.query(UserDB).filter(UserDB.id == user_id).first()
        return user_db.to_pydantic() if user_db else None
    
    def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        user_db = self.db.query(UserDB).filter(UserDB.email == email).first()
        return user_db.to_pydantic() if user_db else None
    
    def create_or_update(self, user: User) -> User:
        """Create or update user (upsert).
        
        Args:
            user: User object to create or update
            
        Returns:
            Created or updated User object
        """
        user_db = self.db.query(UserDB).filter(UserDB.id == user.id).first()
        
        if user_db:
            # Update existing user
            user_db.email = user.email
            user_db.name = user.name
            user_db.updated_at = user.updated_at
            try:
                self.db.commit()
                self.db.refresh(user_db)
                logger.debug(f"Updated user {user.id}: {user.email}")
                return user_db.to_pydantic()
            except Exception as e:
                self.db.rollback()
                logger.error(f"Failed to update user {user.id}: {type(e).__name__}: {str(e)}")
                raise
        else:
            # Create new user
            try:
                user_db = UserDB.from_pydantic(user)
                self.db.add(user_db)
                self.db.commit()
                self.db.refresh(user_db)
                logger.debug(f"Created user {user.id}: {user.email}")
                return user_db.to_pydantic()
            except Exception as e:
                self.db.rollback()
                logger.error(f"Failed to create user {user.id}: {type(e).__name__}: {str(e)}")
                raise

