"""Request/response models for authentication endpoints."""

from pydantic import BaseModel, Field


class GoogleOAuthCallbackRequest(BaseModel):
    """Request model for Google OAuth callback."""
    id_token: str = Field(..., description="Google ID token from OAuth flow")


class GoogleOAuthCodeExchangeRequest(BaseModel):
    """Request model for Google OAuth authorization-code exchange."""

    code: str = Field(..., description="Google OAuth authorization code from GIS code client")


class AuthResponse(BaseModel):
    """Response model for authentication."""
    access_token: str
    token_type: str = "bearer"
    user: dict

