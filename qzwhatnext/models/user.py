"""User data model for qzWhatNext."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class User(BaseModel):
    """User model for qzWhatNext."""
    
    id: str = Field(..., description="Unique user identifier (Google user ID)")
    email: str = Field(..., description="User email address")
    name: Optional[str] = Field(None, description="User display name")
    created_at: datetime = Field(..., description="User creation timestamp")
    updated_at: datetime = Field(..., description="User last update timestamp")
    
    class Config:
        """Pydantic configuration."""
        use_enum_values = True

