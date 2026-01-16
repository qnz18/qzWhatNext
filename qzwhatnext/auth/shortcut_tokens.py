"""Shortcut token utilities (long-lived tokens for iOS Shortcuts, etc.).

These tokens are intended for automation clients that can't easily perform
Google OAuth and refresh JWTs. We never store the raw token—only a hash.
"""

import hashlib
import hmac
import os
import secrets


def _pepper_bytes() -> bytes:
    # Prefer dedicated secret, fall back to JWT secret, then a dev-only constant.
    pepper = (
        os.getenv("SHORTCUT_TOKEN_PEPPER")
        or os.getenv("JWT_SECRET_KEY")
        or "dev-shortcut-token-pepper-change-me"
    )
    return pepper.encode("utf-8")


def hash_shortcut_token(token: str) -> str:
    """Hash a shortcut token for storage/lookup (HMAC-SHA256)."""
    mac = hmac.new(_pepper_bytes(), token.encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()


def generate_shortcut_token() -> str:
    """Generate a new random shortcut token to hand to the user once."""
    # URL-safe, copy/paste friendly
    return secrets.token_urlsafe(32)

