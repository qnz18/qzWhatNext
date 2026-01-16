"""FastAPI dependencies for authentication."""

from datetime import datetime
from fastapi import Depends, HTTPException, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from qzwhatnext.database.database import get_db
from qzwhatnext.database.models import UserDB, ApiTokenDB
from qzwhatnext.auth.jwt import get_user_id_from_token
from qzwhatnext.auth.shortcut_tokens import hash_shortcut_token
from qzwhatnext.models.user import User

# HTTP Bearer token security scheme
security = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    x_shortcut_token: str = Header(default="", alias="X-Shortcut-Token"),
    db: Session = Depends(get_db)
) -> User:
    """Get current authenticated user from JWT token.
    
    Args:
        credentials: HTTP Bearer token credentials
        db: Database session
        
    Returns:
        User object
        
    Raises:
        HTTPException: If token is invalid or user not found
    """
    # 1) Shortcut token auth (for automation clients)
    if x_shortcut_token:
        token_hash = hash_shortcut_token(x_shortcut_token)
        token_db = (
            db.query(ApiTokenDB)
            .filter(ApiTokenDB.token_hash == token_hash, ApiTokenDB.revoked_at.is_(None))
            .first()
        )
        if not token_db:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid shortcut token",
            )
        token_db.last_used_at = datetime.utcnow()
        db.commit()

        user_db = db.query(UserDB).filter(UserDB.id == token_db.user_id).first()
        if not user_db:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user_db.to_pydantic()

    # 2) JWT auth (default)
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    user_id = get_user_id_from_token(token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Get user from database
    user_db = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user_db:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user_db.to_pydantic()

