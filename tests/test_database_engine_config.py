import os


def test_get_engine_kwargs_sqlite_has_check_same_thread(monkeypatch):
    # Import lazily so monkeypatch can affect env usage deterministically.
    from qzwhatnext.database import database as db

    kwargs = db.get_engine_kwargs("sqlite:///./qzwhatnext.db")
    assert "connect_args" in kwargs
    assert kwargs["connect_args"]["check_same_thread"] is False
    # SQLite should not require pool sizing knobs.
    assert "pool_size" not in kwargs
    assert "max_overflow" not in kwargs
    assert kwargs["pool_pre_ping"] is True


def test_get_engine_kwargs_postgres_has_conservative_pooling(monkeypatch):
    from qzwhatnext.database import database as db

    monkeypatch.setenv("DB_POOL_SIZE", "5")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "5")
    monkeypatch.setenv("DB_POOL_TIMEOUT_SEC", "30")

    kwargs = db.get_engine_kwargs("postgresql+psycopg://u:p@localhost:5432/db")
    assert "connect_args" not in kwargs
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_size"] == 5
    assert kwargs["max_overflow"] == 5
    assert kwargs["pool_timeout"] == 30


def test_sqlite_pragmas_listener_is_guarded():
    # Verify the helper used by the connect event guard behaves as expected.
    from qzwhatnext.database import database as db

    assert db._is_sqlite_url("sqlite:///./qzwhatnext.db") is True
    assert db._is_sqlite_url("postgresql+psycopg://u:p@localhost/db") is False

