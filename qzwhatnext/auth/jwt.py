"""JWT token generation and validation for qzWhatNext."""

import os
import jwt
from datetime import datetime, timedelta
from typing import Optional, Dict
from dotenv import load_dotenv

load_dotenv()

# JWT configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))


def create_access_token(user_id: str) -> str:
    """Create a JWT access token for a user.
    
    Args:
        user_id: User ID to encode in token
        
    Returns:
        Encoded JWT token string
    """
    payload = {
        "sub": user_id,  # Subject (user ID)
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.utcnow(),  # Issued at
    }
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return token


def decode_access_token(token: str) -> Optional[Dict]:
    """Decode and validate a JWT access token.
    
    Args:
        token: JWT token string to decode
        
    Returns:
        Decoded token payload (dict with 'sub' key for user_id), or None if invalid
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def get_user_id_from_token(token: str) -> Optional[str]:
    """Extract user ID from a JWT token.
    
    Args:
        token: JWT token string
        
    Returns:
        User ID string, or None if token is invalid
    """
    payload = decode_access_token(token)
    if payload:
        return payload.get("sub")
    return None

