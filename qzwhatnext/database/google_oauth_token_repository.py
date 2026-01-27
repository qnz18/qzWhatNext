"""Repository for per-user OAuth tokens used by integrations.

Security notes:
- Refresh tokens are secrets: store encrypted-at-rest and never log raw values.
- Callers must ensure values are not leaked to client or logs.
"""

import os
from datetime import datetime
from typing import Optional, Sequence

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from qzwhatnext.database.models import GoogleOAuthTokenDB


PROVIDER_GOOGLE = "google"
PRODUCT_CALENDAR = "calendar"


def _require_fernet() -> Fernet:
    key = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY is not set. "
            "Set it to a Fernet key (base64 urlsafe 32-byte) to enable encrypted token storage."
        )
    # Fernet() accepts bytes or str; keep as str for readability.
    return Fernet(key)


def encrypt_secret(raw: str) -> str:
    f = _require_fernet()
    return f.encrypt(raw.encode("utf-8")).decode("utf-8")


def decrypt_secret(enc: str) -> str:
    f = _require_fernet()
    try:
        return f.decrypt(enc.encode("utf-8")).decode("utf-8")
    except InvalidToken as e:
        raise RuntimeError("Stored token could not be decrypted; TOKEN_ENCRYPTION_KEY may be wrong.") from e


class GoogleOAuthTokenRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(
        self,
        user_id: str,
        provider: str,
        product: str,
    ) -> Optional[GoogleOAuthTokenDB]:
        return (
            self.db.query(GoogleOAuthTokenDB)
            .filter(
                GoogleOAuthTokenDB.user_id == user_id,
                GoogleOAuthTokenDB.provider == provider,
                GoogleOAuthTokenDB.product == product,
            )
            .first()
        )

    def get_google_calendar(self, user_id: str) -> Optional[GoogleOAuthTokenDB]:
        return self.get(user_id=user_id, provider=PROVIDER_GOOGLE, product=PRODUCT_CALENDAR)

    def upsert_google_calendar(
        self,
        user_id: str,
        refresh_token: str,
        scopes: Sequence[str],
        *,
        access_token: Optional[str] = None,
        expiry: Optional[datetime] = None,
    ) -> GoogleOAuthTokenDB:
        row = self.get_google_calendar(user_id)
        if row is None:
            row = GoogleOAuthTokenDB(
                user_id=user_id,
                provider=PROVIDER_GOOGLE,
                product=PRODUCT_CALENDAR,
                scopes=list(scopes),
                refresh_token_encrypted=encrypt_secret(refresh_token),
                access_token_encrypted=encrypt_secret(access_token) if access_token else None,
                expiry=expiry,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            self.db.add(row)
        else:
            row.scopes = list(scopes)
            row.refresh_token_encrypted = encrypt_secret(refresh_token)
            row.access_token_encrypted = encrypt_secret(access_token) if access_token else None
            row.expiry = expiry
            row.updated_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(row)
        return row

    def delete_google_calendar(self, user_id: str) -> int:
        """Delete the stored Google Calendar OAuth token row for a user.

        Returns number of rows deleted (0 or 1).
        """
        affected = (
            self.db.query(GoogleOAuthTokenDB)
            .filter(
                GoogleOAuthTokenDB.user_id == user_id,
                GoogleOAuthTokenDB.provider == PROVIDER_GOOGLE,
                GoogleOAuthTokenDB.product == PRODUCT_CALENDAR,
            )
            .delete(synchronize_session=False)
        )
        self.db.commit()
        return int(affected)

