"""Integration tests for API endpoints.

These tests verify API endpoints work correctly end-to-end.
"""

import pytest
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from fastapi.testclient import TestClient
from qzwhatnext.models.task import TaskStatus, TaskCategory, EnergyIntensity
from urllib.parse import urlparse, parse_qs
from unittest.mock import patch, MagicMock


def _connect_google_calendar(test_client: TestClient) -> None:
    """Connect Calendar via OAuth callback (mock token exchange)."""
    auth_url_resp = test_client.get("/auth/google/calendar/auth-url")
    assert auth_url_resp.status_code == 200
    auth_url = auth_url_resp.json()["url"]
    qs = parse_qs(urlparse(auth_url).query)
    state = qs.get("state", [None])[0]
    assert state

    mock_token_resp = MagicMock()
    mock_token_resp.ok = True
    mock_token_resp.json.return_value = {
        # Avoid real token patterns (secret scanner will flag them).
        "access_token": "test_access_token_value",
        "refresh_token": "test_refresh_token_value",
        "expires_in": 3600,
        "scope": "https://www.googleapis.com/auth/calendar",
        "token_type": "Bearer",
    }
    with patch("qzwhatnext.api.app.requests.post", return_value=mock_token_resp):
        cb = test_client.get("/auth/google/calendar/callback", params={"code": "test-code", "state": state})
        assert cb.status_code == 200


def _post_schedule_with_calendar(test_client: TestClient, *, events: Optional[List[Dict]] = None):
    """POST /schedule with Calendar mocks (no network)."""
    with patch("qzwhatnext.api.app.GoogleCredentials.refresh", return_value=None), patch(
        "qzwhatnext.integrations.google_calendar.build",
        return_value=MagicMock(),
    ), patch(
        "qzwhatnext.api.app.GoogleCalendarClient.list_events_in_range",
        return_value=(events or []),
    ):
        return test_client.post("/schedule")


class TestTaskEndpoints:
    """Test task CRUD API endpoints."""
    
    def test_create_task(self, test_client, sample_task_base):
        """Test POST /tasks endpoint."""
        response = test_client.post(
            "/tasks",
            json={
                "title": "Test Task",
                "notes": "Test notes",
                "category": "unknown",
                "estimated_duration_min": 30
            }
        )
        
        assert response.status_code == 201
        data = response.json()
        assert "task" in data
        task = data["task"]
        assert task["title"] == "Test Task"
        assert task["notes"] == "Test notes"
        assert task["category"] == "unknown"
        assert task["status"] == "open"
    
    def test_create_task_with_ai_exclusion_prefix(self, test_client):
        """Test that task with '.' prefix is marked as AI-excluded."""
        response = test_client.post(
            "/tasks",
            json={
                "title": ".Private Task",
                "category": "unknown"
            }
        )
        
        assert response.status_code == 201
        task = response.json()["task"]
        assert task["ai_excluded"] is True
    
    def test_list_tasks(self, test_client):
        """Test GET /tasks endpoint."""
        # Create a task first
        test_client.post(
            "/tasks",
            json={"title": "Task 1", "category": "unknown"}
        )
        
        response = test_client.get("/tasks")
        
        assert response.status_code == 200
        data = response.json()
        assert "tasks" in data
        assert "count" in data
        assert len(data["tasks"]) >= 1
    
    def test_get_task_by_id(self, test_client):
        """Test GET /tasks/{task_id} endpoint."""
        # Create a task first
        create_response = test_client.post(
            "/tasks",
            json={"title": "Get Test Task", "category": "unknown"}
        )
        task_id = create_response.json()["task"]["id"]
        
        response = test_client.get(f"/tasks/{task_id}")
        
        assert response.status_code == 200
        task = response.json()["task"]
        assert task["id"] == task_id
        assert task["title"] == "Get Test Task"
    
    def test_get_nonexistent_task(self, test_client):
        """Test GET /tasks/{task_id} with nonexistent ID."""
        response = test_client.get("/tasks/nonexistent-id")
        
        assert response.status_code == 404
    
    def test_update_task(self, test_client):
        """Test PUT /tasks/{task_id} endpoint."""
        # Create a task first
        create_response = test_client.post(
            "/tasks",
            json={"title": "Original Title", "category": "unknown"}
        )
        task_id = create_response.json()["task"]["id"]
        
        # Update the task
        response = test_client.put(
            f"/tasks/{task_id}",
            json={
                "title": "Updated Title",
                "category": "work"
            }
        )
        
        assert response.status_code == 200
        task = response.json()["task"]
        assert task["title"] == "Updated Title"
        assert task["category"] == "work"
    
    def test_delete_task(self, test_client):
        """Test DELETE /tasks/{task_id} endpoint."""
        # Create a task first
        create_response = test_client.post(
            "/tasks",
            json={"title": "Delete Me", "category": "unknown"}
        )
        task_id = create_response.json()["task"]["id"]
        
        # Delete the task
        response = test_client.delete(f"/tasks/{task_id}")
        
        assert response.status_code == 204
        
        # Verify it's deleted
        get_response = test_client.get(f"/tasks/{task_id}")
        assert get_response.status_code == 404

        # Verify it is not included in list
        list_response = test_client.get("/tasks")
        assert list_response.status_code == 200
        ids = [t["id"] for t in list_response.json()["tasks"]]
        assert task_id not in ids

    def test_restore_task(self, test_client):
        """Test POST /tasks/{task_id}/restore endpoint."""
        create_response = test_client.post(
            "/tasks",
            json={"title": "Restore Me", "category": "unknown"}
        )
        task_id = create_response.json()["task"]["id"]

        delete_response = test_client.delete(f"/tasks/{task_id}")
        assert delete_response.status_code == 204

        restore_response = test_client.post(f"/tasks/{task_id}/restore")
        assert restore_response.status_code == 200
        restored = restore_response.json()["task"]
        assert restored["id"] == task_id

        # Verify it's visible again
        get_response = test_client.get(f"/tasks/{task_id}")
        assert get_response.status_code == 200

    def test_purge_task(self, test_client):
        """Test DELETE /tasks/{task_id}/purge endpoint."""
        create_response = test_client.post(
            "/tasks",
            json={"title": "Purge Me", "category": "unknown"}
        )
        task_id = create_response.json()["task"]["id"]

        purge_response = test_client.delete(f"/tasks/{task_id}/purge")
        assert purge_response.status_code == 204

        # Verify it can't be fetched
        get_response = test_client.get(f"/tasks/{task_id}")
        assert get_response.status_code == 404

        # Verify restore fails
        restore_response = test_client.post(f"/tasks/{task_id}/restore")
        assert restore_response.status_code == 404

    def test_bulk_delete_restore_and_purge(self, test_client):
        """Test bulk task soft delete, restore, and purge endpoints."""
        ids = []
        for title in ["Bulk A", "Bulk B", "Bulk C"]:
            resp = test_client.post("/tasks", json={"title": title, "category": "unknown"})
            assert resp.status_code == 201
            ids.append(resp.json()["task"]["id"])

        nonexistent_id = "nonexistent-id"

        bulk_delete = test_client.post("/tasks/bulk_delete", json={"task_ids": [ids[0], ids[1], nonexistent_id]})
        assert bulk_delete.status_code == 200
        payload = bulk_delete.json()
        assert payload["affected_count"] == 2
        assert nonexistent_id in payload["not_found_ids"]

        # Deleted tasks should 404
        assert test_client.get(f"/tasks/{ids[0]}").status_code == 404
        assert test_client.get(f"/tasks/{ids[1]}").status_code == 404
        assert test_client.get(f"/tasks/{ids[2]}").status_code == 200

        bulk_restore = test_client.post("/tasks/bulk_restore", json={"task_ids": [ids[0], ids[1]]})
        assert bulk_restore.status_code == 200
        assert bulk_restore.json()["affected_count"] == 2

        assert test_client.get(f"/tasks/{ids[0]}").status_code == 200
        assert test_client.get(f"/tasks/{ids[1]}").status_code == 200

        bulk_purge = test_client.post("/tasks/bulk_purge", json={"task_ids": [ids[0], ids[2], nonexistent_id]})
        assert bulk_purge.status_code == 200
        payload = bulk_purge.json()
        assert payload["affected_count"] == 2
        assert nonexistent_id in payload["not_found_ids"]

        assert test_client.get(f"/tasks/{ids[0]}").status_code == 404
        assert test_client.get(f"/tasks/{ids[2]}").status_code == 404

    def test_delete_removes_scheduled_blocks(self, test_client):
        """Deleting a task should remove its scheduled blocks."""
        create_response = test_client.post(
            "/tasks",
            json={"title": "Scheduled Then Deleted", "category": "work", "estimated_duration_min": 30}
        )
        task_id = create_response.json()["task"]["id"]

        _connect_google_calendar(test_client)
        build_response = _post_schedule_with_calendar(test_client)
        assert build_response.status_code == 200

        schedule_before = test_client.get("/schedule")
        assert schedule_before.status_code == 200
        blocks_before = schedule_before.json()["scheduled_blocks"]
        assert any(b["entity_id"] == task_id for b in blocks_before)

        delete_response = test_client.delete(f"/tasks/{task_id}")
        assert delete_response.status_code == 204

        schedule_after = test_client.get("/schedule")
        # If the deleted task was the only scheduled entity, schedule may now be empty.
        # Existing API semantics return 404 when no schedule is available.
        if schedule_after.status_code == 404:
            return
        assert schedule_after.status_code == 200
        blocks_after = schedule_after.json()["scheduled_blocks"]
        assert all(b["entity_id"] != task_id for b in blocks_after)


class TestAddSmartEndpoint:
    """Test POST /tasks/add_smart endpoint."""
    
    def test_add_smart_task_basic(self, test_client):
        """Test basic add_smart task creation."""
        response = test_client.post(
            "/tasks/add_smart",
            json={"notes": "This is a test note"}
        )
        
        assert response.status_code == 201
        task = response.json()["task"]
        assert task["notes"] == "This is a test note"
        assert task["title"]  # Title should be generated (or fallback)
        assert task["status"] == "open"
    
    def test_add_smart_task_with_ai_exclusion(self, test_client):
        """Test that notes starting with '.' mark task as AI-excluded."""
        response = test_client.post(
            "/tasks/add_smart",
            json={"notes": ".Private note"}
        )
        
        assert response.status_code == 201
        task = response.json()["task"]
        assert task["ai_excluded"] is True
        assert task["notes"] == ".Private note"


class TestCaptureEndpoint:
    """Test POST /capture endpoint (single-input recurring capture)."""

    def test_capture_creates_recurring_task_series_and_instances(self, test_client):
        r = test_client.post("/capture", json={"instruction": "take my vitamins every morning"})
        assert r.status_code == 200
        payload = r.json()
        assert payload["action"] == "created"
        assert payload["entity_kind"] == "task_series"
        assert payload["entity_id"]
        assert payload["tasks_created"] >= 1

        # Instances should exist as tasks.
        tasks = test_client.get("/tasks").json()["tasks"]
        assert any("vitamins" in (t["title"] or "").lower() for t in tasks)

    def test_capture_creates_and_updates_recurring_time_block(self, test_client):
        _connect_google_calendar(test_client)

        with patch("qzwhatnext.api.app.GoogleCredentials.refresh", return_value=None), patch(
            "qzwhatnext.integrations.google_calendar.build",
            return_value=MagicMock(),
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.get_calendar_timezone",
            return_value="UTC",
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.create_recurring_time_block_event",
            return_value={"id": "evt_tb_1"},
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.patch_event",
            return_value={"id": "evt_tb_1"},
        ):
            create = test_client.post("/capture", json={"instruction": "kids practice tues at 4:30"})
            assert create.status_code == 200
            created = create.json()
            assert created["entity_kind"] == "time_block"
            assert created["calendar_event_id"] == "evt_tb_1"
            block_id = created["entity_id"]

            upd = test_client.post(
                "/capture",
                json={"entity_id": block_id, "instruction": "kids practice tues at 5pm"},
            )
            assert upd.status_code == 200
            updated = upd.json()
            assert updated["action"] == "updated"
            assert updated["entity_kind"] == "time_block"
            assert updated["entity_id"] == block_id

    def test_capture_weekday_time_without_at_becomes_time_block(self, test_client):
        _connect_google_calendar(test_client)

        with patch("qzwhatnext.api.app.GoogleCredentials.refresh", return_value=None), patch(
            "qzwhatnext.integrations.google_calendar.build",
            return_value=MagicMock(),
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.get_calendar_timezone",
            return_value="UTC",
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.create_recurring_time_block_event",
            return_value={"id": "evt_tb_2"},
        ):
            r = test_client.post("/capture", json={"instruction": "bike ride tues and thurs 2:30pm"})
            assert r.status_code == 200
            payload = r.json()
            assert payload["entity_kind"] == "time_block"
            assert payload["calendar_event_id"] == "evt_tb_2"

    def test_capture_next_weekday_time_creates_one_off_calendar_event(self, test_client):
        _connect_google_calendar(test_client)

        # Freeze "now" so "next Tue" is deterministic.
        from datetime import datetime as _dt

        class _FixedDateTime(_dt):
            @classmethod
            def utcnow(cls):
                # Monday, 2026-01-26
                return _dt(2026, 1, 26, 12, 0, 0)

        with patch("qzwhatnext.api.app.datetime", _FixedDateTime), patch(
            "qzwhatnext.api.app.GoogleCredentials.refresh",
            return_value=None,
        ), patch(
            "qzwhatnext.integrations.google_calendar.build",
            return_value=MagicMock(),
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.get_calendar_timezone",
            return_value="UTC",
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.create_time_block_event",
            return_value={"id": "evt_oneoff_1"},
        ):
            r = test_client.post("/capture", json={"instruction": "bike ride next tues 2:30pm"})
            assert r.status_code == 200
            payload = r.json()
            assert payload["entity_kind"] == "calendar_event"
            assert payload["calendar_event_id"] == "evt_oneoff_1"

    def test_capture_this_weekday_in_past_returns_400(self, test_client):
        _connect_google_calendar(test_client)

        # Freeze "now" so "this Tue" is in the past (today is Wed 2026-01-28).
        from datetime import datetime as _dt

        class _FixedDateTime(_dt):
            @classmethod
            def utcnow(cls):
                return _dt(2026, 1, 28, 12, 0, 0)

        with patch("qzwhatnext.api.app.datetime", _FixedDateTime):
            r = test_client.post("/capture", json={"instruction": "bike ride this tues 2:30pm"})
            assert r.status_code == 400
            assert "already in the past" in (r.json().get("detail") or "").lower()

    def test_capture_next_week_creates_task_with_start_after(self, test_client):
        # Freeze "now" so "next week" is deterministic.
        from datetime import datetime as _dt

        class _FixedDateTime(_dt):
            @classmethod
            def utcnow(cls):
                # Monday, 2026-01-26
                return _dt(2026, 1, 26, 12, 0, 0)

        with patch("qzwhatnext.api.app.datetime", _FixedDateTime):
            r = test_client.post("/capture", json={"instruction": "schedule gutters sometime next week"})
            assert r.status_code == 200
            payload = r.json()
            assert payload["entity_kind"] == "task"
            assert payload["entity_id"]

            tasks = test_client.get("/tasks").json()["tasks"]
            created = [t for t in tasks if "schedule gutters" in (t.get("title") or "").lower()][0]
            assert created["start_after"] == "2026-02-02"
            assert created["due_by"] is None


class TestScheduleEndpoints:
    """Test schedule-related endpoints."""
    
    def test_build_schedule_no_tasks(self, test_client):
        """Test building schedule with no tasks."""
        response = test_client.post("/schedule")
        
        assert response.status_code == 400
        assert "No tasks available" in response.json()["detail"]
    
    def test_build_schedule_with_tasks(self, test_client):
        """Test building schedule with tasks."""
        # Create some tasks first
        test_client.post(
            "/tasks",
            json={"title": "Task 1", "category": "work", "estimated_duration_min": 30}
        )
        test_client.post(
            "/tasks",
            json={"title": "Task 2", "category": "health", "estimated_duration_min": 60}
        )

        _connect_google_calendar(test_client)
        response = _post_schedule_with_calendar(test_client)
        
        assert response.status_code == 200
        data = response.json()
        assert "scheduled_blocks" in data
        assert "overflow_tasks" in data
        assert "start_time" in data
        assert len(data["scheduled_blocks"]) > 0

    def test_build_schedule_requires_calendar_connected(self, test_client):
        """If tasks exist but Calendar is not connected, /schedule should 400."""
        r = test_client.post("/tasks", json={"title": "Needs Calendar", "category": "work", "estimated_duration_min": 30})
        assert r.status_code == 201

        response = test_client.post("/schedule")
        assert response.status_code == 400
        assert "not connected" in response.json()["detail"].lower()

    def test_build_schedule_avoids_non_managed_calendar_busy_time(self, test_client):
        """Non-managed calendar events should reserve time using only start/end windows."""
        r = test_client.post("/tasks", json={"title": "Avoid Busy", "category": "work", "estimated_duration_min": 30})
        assert r.status_code == 201

        _connect_google_calendar(test_client)

        now = datetime.utcnow()
        busy_start = now - timedelta(minutes=5)
        busy_end = now + timedelta(hours=2)
        busy_event = {
            "start": {"dateTime": busy_start.isoformat() + "Z"},
            "end": {"dateTime": busy_end.isoformat() + "Z"},
        }

        build = _post_schedule_with_calendar(test_client, events=[busy_event])
        assert build.status_code == 200
        blocks = build.json()["scheduled_blocks"]
        assert blocks
        first_start = datetime.fromisoformat(blocks[0]["start_time"])
        assert first_start >= busy_end
    
    def test_view_schedule_not_built(self, test_client):
        """Test viewing schedule when none has been built."""
        response = test_client.get("/schedule")
        
        assert response.status_code == 404
        assert "No schedule available" in response.json()["detail"]
    
    def test_view_schedule_after_build(self, test_client):
        """Test viewing schedule after building."""
        # Create a task and build schedule
        test_client.post(
            "/tasks",
            json={"title": "Scheduled Task", "category": "work", "estimated_duration_min": 30}
        )
        _connect_google_calendar(test_client)
        build = _post_schedule_with_calendar(test_client)
        assert build.status_code == 200
        
        response = test_client.get("/schedule")
        
        assert response.status_code == 200
        data = response.json()
        assert "scheduled_blocks" in data
        assert "task_titles" in data


class TestHealthEndpoint:
    """Test health check endpoint."""
    
    def test_health_check(self, test_client):
        """Test GET /health endpoint."""
        response = test_client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data


class TestRootEndpoint:
    """Test root endpoint."""
    
    def test_root_endpoint(self, test_client):
        """Test GET / endpoint returns HTML."""
        response = test_client.get("/")
        
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "qzWhatNext" in response.text
        # Auth UI should be backend-validated (no "token present" optimistic state).
        assert "Signed in (token present)." not in response.text
        assert "Checking session..." in response.text
        assert "Session expired. Please sign in again." in response.text


class TestGoogleCalendarSync:
    def test_sync_calendar_requires_connected_calendar(self, test_client, db_session, test_user_id):
        """If schedule exists but calendar isn't connected, /sync-calendar should 400."""
        # Create a scheduled block directly (since /schedule now requires Calendar).
        from qzwhatnext.database.scheduled_block_repository import ScheduledBlockRepository
        from qzwhatnext.models.scheduled_block import ScheduledBlock, EntityType, ScheduledBy
        import uuid

        repo = ScheduledBlockRepository(db_session)
        now = datetime.utcnow()
        repo.create(
            ScheduledBlock(
                id=str(uuid.uuid4()),
                user_id=test_user_id,
                entity_type=EntityType.TASK,
                entity_id="task_x",
                start_time=now,
                end_time=now + timedelta(minutes=30),
                scheduled_by=ScheduledBy.SYSTEM,
                locked=False,
            )
        )

        sync = test_client.post("/sync-calendar")
        assert sync.status_code == 400
        assert "Google Calendar not connected" in sync.json()["detail"]

    def test_oauth_callback_stores_token_and_syncs(self, test_client):
        """OAuth callback should store refresh token, and /sync-calendar should create events."""
        # Create a task, connect calendar, and build schedule so blocks exist.
        r = test_client.post("/tasks", json={"title": "Calendar Task 2", "category": "work", "estimated_duration_min": 30})
        assert r.status_code == 201
        _connect_google_calendar(test_client)

        build = _post_schedule_with_calendar(test_client, events=[])
        assert build.status_code == 200

        # Mock credential refresh and Calendar client behavior to avoid network.
        with patch("qzwhatnext.api.app.GoogleCredentials.refresh", return_value=None), patch(
            "qzwhatnext.integrations.google_calendar.build",
            return_value=MagicMock(),
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.create_event_from_block",
            return_value={"id": "evt_123", "etag": "etag_1", "updated": "2026-01-26T00:00:00Z"},
        ):
            sync = test_client.post("/sync-calendar")
            assert sync.status_code == 200
            payload = sync.json()
            assert payload["events_created"] >= 1
            assert isinstance(payload["event_ids"], list)

    def test_sync_calendar_idempotent_second_run_does_not_create_again(self, test_client):
        """Second /sync-calendar run should not recreate already-synced events."""
        r = test_client.post("/tasks", json={"title": "Calendar Task 3", "category": "work", "estimated_duration_min": 30})
        assert r.status_code == 201
        _connect_google_calendar(test_client)
        build = _post_schedule_with_calendar(test_client, events=[])
        assert build.status_code == 200

        # First run creates.
        with patch("qzwhatnext.api.app.GoogleCredentials.refresh", return_value=None), patch(
            "qzwhatnext.integrations.google_calendar.build",
            return_value=MagicMock(),
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.list_events_in_range",
            return_value=[],
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.create_event_from_block",
            return_value={"id": "evt_abc", "etag": "etag_a", "updated": "2026-01-26T00:00:00Z"},
        ) as create_mock:
            sync1 = test_client.post("/sync-calendar")
            assert sync1.status_code == 200
            assert create_mock.call_count >= 1

        # Second run should not call create again (it should use persisted calendar_event_id + get_event).
        with patch("qzwhatnext.api.app.GoogleCredentials.refresh", return_value=None), patch(
            "qzwhatnext.integrations.google_calendar.build",
            return_value=MagicMock(),
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.list_events_in_range",
            return_value=[],
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.get_event",
            return_value={
                "id": "evt_abc",
                "etag": "etag_a",
                "updated": "2026-01-26T00:00:00Z",
                "summary": "Calendar Task 3",
                "description": None,
                "start": {"dateTime": "2026-01-26T00:00:00Z"},
                "end": {"dateTime": "2026-01-26T00:30:00Z"},
                "extendedProperties": {"private": {"qzwhatnext_task_id": "x", "qzwhatnext_block_id": "y", "qzwhatnext_managed": "1"}},
            },
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.create_event_from_block",
        ) as create_mock2:
            sync2 = test_client.post("/sync-calendar")
            assert sync2.status_code == 200
            assert create_mock2.call_count == 0

    def test_calendar_edit_imports_and_locks_block(self, test_client):
        """If a managed calendar event time changes, sync imports it and freezes the block."""
        # Create a task, connect calendar, and build schedule so blocks exist.
        r = test_client.post("/tasks", json={"title": "Calendar Task 4", "category": "work", "estimated_duration_min": 30})
        assert r.status_code == 201
        _connect_google_calendar(test_client)
        build = _post_schedule_with_calendar(test_client, events=[])
        assert build.status_code == 200
        blocks = build.json()["scheduled_blocks"]
        assert blocks
        block_id = blocks[0]["id"]

        # Pretend the block is already linked to an event.
        from qzwhatnext.database.scheduled_block_repository import ScheduledBlockRepository
        from qzwhatnext.database.database import get_db
        # Use the overridden db via dependency directly in app tests: call repo on test fixture's session.
        # We can fetch the session through the dependency override by requesting schedule again and using its state;
        # simplest here: call unlock endpoint later to verify lock state.

        # First sync creates and stores metadata.
        with patch("qzwhatnext.api.app.GoogleCredentials.refresh", return_value=None), patch(
            "qzwhatnext.integrations.google_calendar.build",
            return_value=MagicMock(),
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.create_event_from_block",
            return_value={"id": "evt_lock", "etag": "etag_0", "updated": "2026-01-26T00:00:00Z"},
        ):
            sync1 = test_client.post("/sync-calendar")
            assert sync1.status_code == 200

        # Second sync sees a changed etag + updated + time and should lock the block.
        with patch("qzwhatnext.api.app.GoogleCredentials.refresh", return_value=None), patch(
            "qzwhatnext.integrations.google_calendar.build",
            return_value=MagicMock(),
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.get_event",
            return_value={
                "id": "evt_lock",
                "etag": "etag_1",
                "updated": "2026-01-26T01:00:00Z",
                "summary": "Calendar Task 4",
                "description": None,
                "start": {"dateTime": "2026-01-26T02:00:00Z"},
                "end": {"dateTime": "2026-01-26T02:30:00Z"},
                "extendedProperties": {"private": {"qzwhatnext_task_id": "x", "qzwhatnext_block_id": block_id, "qzwhatnext_managed": "1"}},
            },
        ):
            sync2 = test_client.post("/sync-calendar")
            assert sync2.status_code == 200

        schedule_after = test_client.get("/schedule")
        assert schedule_after.status_code == 200
        updated_block = [b for b in schedule_after.json()["scheduled_blocks"] if b["id"] == block_id][0]
        assert updated_block["locked"] is True

    def test_lock_unlock_endpoints_toggle_locked(self, test_client):
        """Lock/unlock endpoints should toggle ScheduledBlock.locked."""
        r = test_client.post("/tasks", json={"title": "Lock Toggle Task", "category": "work", "estimated_duration_min": 30})
        assert r.status_code == 201
        _connect_google_calendar(test_client)
        build = _post_schedule_with_calendar(test_client, events=[])
        assert build.status_code == 200
        block_id = build.json()["scheduled_blocks"][0]["id"]

        lock = test_client.post(f"/schedule/blocks/{block_id}/lock")
        assert lock.status_code == 200
        assert lock.json()["block"]["locked"] is True

        unlock = test_client.post(f"/schedule/blocks/{block_id}/unlock")
        assert unlock.status_code == 200
        assert unlock.json()["block"]["locked"] is False

    def test_sync_calendar_invalid_grant_clears_token_and_forces_reconnect(self, test_client):
        """If Google refresh fails with invalid_grant, the stored calendar token is cleared."""
        # Create a task, connect calendar, and build schedule so blocks exist.
        r = test_client.post("/tasks", json={"title": "Calendar Task invalid_grant", "category": "work", "estimated_duration_min": 30})
        assert r.status_code == 201
        _connect_google_calendar(test_client)
        build = _post_schedule_with_calendar(test_client, events=[])
        assert build.status_code == 200

        # First sync: refresh fails with invalid_grant and should clear stored token row.
        with patch(
            "qzwhatnext.api.app.GoogleCredentials.refresh",
            side_effect=Exception("invalid_grant: Token has been expired or revoked."),
        ):
            sync1 = test_client.post("/sync-calendar")
            assert sync1.status_code == 400
            assert "expired or was revoked" in sync1.json()["detail"]

        # Second sync: should now report not connected (token row cleared).
        sync2 = test_client.post("/sync-calendar")
        assert sync2.status_code == 400
        assert "not connected" in sync2.json()["detail"].lower()

    def test_schedule_rebuild_does_not_duplicate_calendar_events(self, test_client):
        """Rebuilding schedule should reuse prior block IDs so sync updates events instead of duplicating."""
        # Create a task, connect calendar, and build schedule so blocks exist.
        r = test_client.post("/tasks", json={"title": "Calendar Task rebuild", "category": "work", "estimated_duration_min": 30})
        assert r.status_code == 201
        _connect_google_calendar(test_client)
        build1 = _post_schedule_with_calendar(test_client, events=[])
        assert build1.status_code == 200
        block1 = build1.json()["scheduled_blocks"][0]
        block1_id = block1["id"]

        # First sync creates event and persists mapping.
        with patch("qzwhatnext.api.app.GoogleCredentials.refresh", return_value=None), patch(
            "qzwhatnext.integrations.google_calendar.build",
            return_value=MagicMock(),
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.list_events_in_range",
            return_value=[],
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.create_event_from_block",
            return_value={"id": "evt_rebuild", "etag": "etag_r1", "updated": "2026-01-26T00:00:00Z"},
        ) as create_mock:
            sync1 = test_client.post("/sync-calendar")
            assert sync1.status_code == 200
            assert create_mock.call_count >= 1

        # Rebuild schedule (should reuse same block id for this task).
        build2 = _post_schedule_with_calendar(test_client, events=[])
        assert build2.status_code == 200
        block2 = [b for b in build2.json()["scheduled_blocks"] if b["entity_id"] == block1["entity_id"]][0]
        assert block2["id"] == block1_id

        # Second sync should not create a new event.
        with patch("qzwhatnext.api.app.GoogleCredentials.refresh", return_value=None), patch(
            "qzwhatnext.integrations.google_calendar.build",
            return_value=MagicMock(),
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.list_events_in_range",
            return_value=[],
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.get_event",
            return_value={
                "id": "evt_rebuild",
                "etag": "etag_r1",
                "updated": "2026-01-26T00:00:00Z",
                "summary": "Calendar Task rebuild",
                "description": None,
                "start": {"dateTime": block2["start_time"]},
                "end": {"dateTime": block2["end_time"]},
                "extendedProperties": {"private": {"qzwhatnext_task_id": block2["entity_id"], "qzwhatnext_block_id": block2["id"], "qzwhatnext_managed": "1"}},
            },
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.create_event_from_block",
        ) as create_mock2:
            sync2 = test_client.post("/sync-calendar")
            assert sync2.status_code == 200
            assert create_mock2.call_count == 0

    def test_sync_recreates_event_if_deleted_in_calendar(self, test_client):
        """If the user deletes a managed event, sync should recreate it."""
        r = test_client.post("/tasks", json={"title": "Calendar Task deleted", "category": "work", "estimated_duration_min": 30})
        assert r.status_code == 201
        _connect_google_calendar(test_client)
        build = _post_schedule_with_calendar(test_client, events=[])
        assert build.status_code == 200

        # First sync creates the event.
        with patch("qzwhatnext.api.app.GoogleCredentials.refresh", return_value=None), patch(
            "qzwhatnext.integrations.google_calendar.build",
            return_value=MagicMock(),
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.list_events_in_range",
            return_value=[],
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.create_event_from_block",
            return_value={"id": "evt_deleted_1", "etag": "etag_d1", "updated": "2026-01-26T00:00:00Z"},
        ) as create_mock:
            sync1 = test_client.post("/sync-calendar")
            assert sync1.status_code == 200
            assert create_mock.call_count >= 1

        # Second sync: event is "deleted" in Calendar (status cancelled), so we should recreate.
        with patch("qzwhatnext.api.app.GoogleCredentials.refresh", return_value=None), patch(
            "qzwhatnext.integrations.google_calendar.build",
            return_value=MagicMock(),
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.list_events_in_range",
            return_value=[],
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.get_event",
            return_value={"id": "evt_deleted_1", "status": "cancelled"},
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.create_event_from_block",
            return_value={"id": "evt_deleted_2", "etag": "etag_d2", "updated": "2026-01-26T00:10:00Z"},
        ) as create_mock2:
            sync2 = test_client.post("/sync-calendar")
            assert sync2.status_code == 200
            assert create_mock2.call_count >= 1


