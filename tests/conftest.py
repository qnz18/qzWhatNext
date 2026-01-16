"""Pytest fixtures and configuration for qzWhatNext tests."""

import pytest
import os
import tempfile
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from unittest.mock import patch
import uuid

from qzwhatnext.database.database import Base, get_db
from qzwhatnext.database.repository import TaskRepository
from qzwhatnext.models.task import Task, TaskStatus, TaskCategory, EnergyIntensity


# Use in-memory SQLite database for tests
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="function")
def db_session(test_user_id):
    """Create a database session for testing.
    
    Uses an in-memory SQLite database that is created fresh for each test.
    Also creates a test user in the database.
    """
    from sqlalchemy import event
    from sqlalchemy.engine import Engine
    from qzwhatnext.database.models import UserDB
    from datetime import datetime
    
    # Create engine with StaticPool for in-memory database
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )
    
    # Enable SQLite foreign keys and WAL mode
    @event.listens_for(Engine, "connect")
    def set_sqlite_pragmas(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    
    # Create session
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    
    # Create test user (required for foreign key constraints)
    now = datetime.utcnow()
    test_user_db = UserDB(
        id=test_user_id,
        email="test@example.com",
        name="Test User",
        created_at=now,
        updated_at=now,
    )
    session.add(test_user_db)
    session.commit()
    
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def task_repository(db_session: Session):
    """Create a TaskRepository instance for testing."""
    return TaskRepository(db_session)


@pytest.fixture
def test_user_id():
    """Test user ID for multi-user testing."""
    return "test-user-123"


@pytest.fixture
def sample_task_base(test_user_id):
    """Base task data for creating test tasks.
    
    Returns a dict with default task attributes that can be overridden.
    """
    now = datetime.utcnow()
    return {
        "id": str(uuid.uuid4()),
        "user_id": test_user_id,
        "source_type": "api",
        "source_id": None,
        "title": "Test Task",
        "notes": "Test notes",
        "status": TaskStatus.OPEN,
        "created_at": now,
        "updated_at": now,
        "deadline": None,
        "estimated_duration_min": 30,
        "duration_confidence": 0.5,
        "category": TaskCategory.UNKNOWN,
        "energy_intensity": EnergyIntensity.MEDIUM,
        "risk_score": 0.3,
        "impact_score": 0.3,
        "dependencies": [],
        "flexibility_window": None,
        "ai_excluded": False,
        "manual_priority_locked": False,
        "user_locked": False,
        "manually_scheduled": False,
    }


@pytest.fixture
def sample_task(sample_task_base):
    """Create a sample Task object for testing."""
    return Task(**sample_task_base)


@pytest.fixture
def ai_excluded_task(sample_task_base):
    """Create a task that is AI-excluded (title starts with period)."""
    return Task(**{**sample_task_base, "title": ".Private Task", "ai_excluded": True})


@pytest.fixture
def task_with_deadline(sample_task_base):
    """Create a task with urgent deadline (< 24 hours)."""
    deadline = datetime.utcnow() + timedelta(hours=12)
    return Task(**{**sample_task_base, "deadline": deadline})


@pytest.fixture
def task_with_high_risk(sample_task_base):
    """Create a task with high risk score."""
    return Task(**{**sample_task_base, "risk_score": 0.8})


@pytest.fixture
def task_with_high_impact(sample_task_base):
    """Create a task with high impact score."""
    return Task(**{**sample_task_base, "impact_score": 0.8})


@pytest.fixture
def child_task(sample_task_base):
    """Create a child category task."""
    return Task(**{**sample_task_base, "category": TaskCategory.CHILD})


@pytest.fixture
def health_task(sample_task_base):
    """Create a health category task."""
    return Task(**{**sample_task_base, "category": TaskCategory.HEALTH})


@pytest.fixture
def work_task(sample_task_base):
    """Create a work category task."""
    return Task(**{**sample_task_base, "category": TaskCategory.WORK})


@pytest.fixture
def family_task(sample_task_base):
    """Create a family category task."""
    return Task(**{**sample_task_base, "category": TaskCategory.FAMILY})


@pytest.fixture
def home_task(sample_task_base):
    """Create a home category task."""
    return Task(**{**sample_task_base, "category": TaskCategory.HOME})


@pytest.fixture
def manually_scheduled_task(sample_task_base):
    """Create a manually scheduled task."""
    return Task(**{**sample_task_base, "manually_scheduled": True})


@pytest.fixture
def user_locked_task(sample_task_base):
    """Create a user-locked task."""
    return Task(**{**sample_task_base, "user_locked": True})


@pytest.fixture
def test_user(test_user_id):
    """Create a test user object."""
    from qzwhatnext.models.user import User
    from datetime import datetime
    now = datetime.utcnow()
    return User(
        id=test_user_id,
        email="test@example.com",
        name="Test User",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def test_client(db_session: Session, test_user):
    """Create a FastAPI test client with overridden database dependency and authentication."""
    from qzwhatnext.api.app import app
    from qzwhatnext.database.database import get_db
    from qzwhatnext.auth.dependencies import get_current_user
    
    # Override the get_db dependency to use our test database session
    def override_get_db():
        try:
            yield db_session
        finally:
            pass  # Don't close the session here, let the fixture handle it
    
    # Override authentication to return test user
    def override_get_current_user():
        return test_user
    
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    
    with TestClient(app) as client:
        yield client
    
    # Clean up dependency overrides
    app.dependency_overrides.clear()

