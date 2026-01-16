"""Google OAuth2 client for user authentication."""

import os
import secrets
from typing import Optional, Dict, Tuple
from google.oauth2 import id_token
from google.auth.transport import requests
from dotenv import load_dotenv

load_dotenv()

# Google OAuth configuration
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")


def generate_state() -> str:
    """Generate a random state token for CSRF protection.
    
    Returns:
        Random state token string
    """
    return secrets.token_urlsafe(32)


def verify_google_token(id_token_str: str) -> Optional[Dict]:
    """Verify a Google ID token and extract user information.
    
    Args:
        id_token_str: Google ID token string from OAuth callback
        
    Returns:
        Dictionary with user info (id, email, name), or None if invalid
    """
    try:
        # Verify the token
        idinfo = id_token.verify_oauth2_token(
            id_token_str,
            requests.Request(),
            GOOGLE_OAUTH_CLIENT_ID
        )
        
        # Verify the issuer
        if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
            return None
        
        # Extract user info
        user_info = {
            'id': idinfo['sub'],  # Google user ID
            'email': idinfo.get('email'),
            'name': idinfo.get('name'),
        }
        
        return user_info
    except ValueError:
        # Invalid token
        return None

