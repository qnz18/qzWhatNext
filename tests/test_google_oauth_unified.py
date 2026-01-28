from unittest.mock import MagicMock, patch

from qzwhatnext.database.google_oauth_token_repository import GoogleOAuthTokenRepository, PROVIDER_GOOGLE, PRODUCT_CALENDAR
from qzwhatnext.database.models import GoogleOAuthTokenDB


def test_google_code_exchange_logs_in_and_stores_calendar_refresh_token(test_client, db_session, test_user_id):
    mock_token_resp = MagicMock()
    mock_token_resp.ok = True
    mock_token_resp.json.return_value = {
        "access_token": "test_access_token_value",
        "refresh_token": "test_refresh_token_value",
        "expires_in": 3600,
        "scope": "openid email profile https://www.googleapis.com/auth/calendar",
        "token_type": "Bearer",
        "id_token": "test_id_token_value",
    }

    with patch("qzwhatnext.api.app.requests.post", return_value=mock_token_resp), patch(
        "qzwhatnext.api.app.verify_google_token",
        return_value={"id": test_user_id, "email": "test@example.com", "name": "Test User"},
    ):
        r = test_client.post(
            "/auth/google/code-exchange",
            json={"code": "test-code"},
            headers={"X-Requested-With": "XmlHttpRequest", "Origin": "http://testserver"},
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload["access_token"]
        assert payload["token_type"] == "bearer"
        assert payload["user"]["id"] == test_user_id

    row = (
        db_session.query(GoogleOAuthTokenDB)
        .filter(
            GoogleOAuthTokenDB.user_id == test_user_id,
            GoogleOAuthTokenDB.provider == PROVIDER_GOOGLE,
            GoogleOAuthTokenDB.product == PRODUCT_CALENDAR,
        )
        .first()
    )
    assert row is not None
    assert isinstance(row.refresh_token_encrypted, str)
    assert row.refresh_token_encrypted


def test_google_code_exchange_reuses_existing_refresh_token_when_missing(test_client, db_session, test_user_id):
    # Seed an existing Calendar token row.
    repo = GoogleOAuthTokenRepository(db_session)
    repo.upsert_google_calendar(user_id=test_user_id, refresh_token="seed_refresh_token_value", scopes=["https://www.googleapis.com/auth/calendar"])

    mock_token_resp = MagicMock()
    mock_token_resp.ok = True
    # No refresh_token returned (common on subsequent grants).
    mock_token_resp.json.return_value = {
        "access_token": "test_access_token_value",
        "expires_in": 3600,
        "scope": "openid email profile https://www.googleapis.com/auth/calendar",
        "token_type": "Bearer",
        "id_token": "test_id_token_value",
    }

    with patch("qzwhatnext.api.app.requests.post", return_value=mock_token_resp), patch(
        "qzwhatnext.api.app.verify_google_token",
        return_value={"id": test_user_id, "email": "test@example.com", "name": "Test User"},
    ), patch("qzwhatnext.api.app.GoogleCredentials.refresh", return_value=None):
        r = test_client.post(
            "/auth/google/code-exchange",
            json={"code": "test-code"},
            headers={"X-Requested-With": "XmlHttpRequest", "Origin": "http://testserver"},
        )
        assert r.status_code == 200

    row = repo.get_google_calendar(test_user_id)
    assert row is not None
