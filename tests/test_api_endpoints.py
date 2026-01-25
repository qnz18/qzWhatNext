"""Integration tests for API endpoints.

These tests verify API endpoints work correctly end-to-end.
"""

import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from qzwhatnext.models.task import TaskStatus, TaskCategory, EnergyIntensity
from urllib.parse import urlparse, parse_qs
from unittest.mock import patch, MagicMock


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

        build_response = test_client.post("/schedule")
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
        
        response = test_client.post("/schedule")
        
        assert response.status_code == 200
        data = response.json()
        assert "scheduled_blocks" in data
        assert "overflow_tasks" in data
        assert "start_time" in data
        assert len(data["scheduled_blocks"]) > 0
    
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
        test_client.post("/schedule")
        
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
    def test_sync_calendar_requires_connected_calendar(self, test_client):
        """If schedule exists but calendar isn't connected, /sync-calendar should 400."""
        # Create a task and build schedule so blocks exist.
        r = test_client.post("/tasks", json={"title": "Calendar Task", "category": "work", "estimated_duration_min": 30})
        assert r.status_code == 201
        build = test_client.post("/schedule")
        assert build.status_code == 200

        sync = test_client.post("/sync-calendar")
        assert sync.status_code == 400
        assert "Google Calendar not connected" in sync.json()["detail"]

    def test_oauth_callback_stores_token_and_syncs(self, test_client):
        """OAuth callback should store refresh token, and /sync-calendar should create events."""
        # Create a task and build schedule so blocks exist.
        r = test_client.post("/tasks", json={"title": "Calendar Task 2", "category": "work", "estimated_duration_min": 30})
        assert r.status_code == 201
        build = test_client.post("/schedule")
        assert build.status_code == 200

        # Start OAuth to obtain a valid signed state.
        start = test_client.get("/auth/google/calendar/start", allow_redirects=False)
        assert start.status_code == 302
        loc = start.headers["location"]
        qs = parse_qs(urlparse(loc).query)
        state = qs.get("state", [None])[0]
        assert state

        # Mock Google's token exchange response.
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
            assert "Google Calendar connected" in cb.text or "already connected" in cb.text

        # Mock credential refresh and Calendar client behavior to avoid network.
        with patch("qzwhatnext.api.app.GoogleCredentials.refresh", return_value=None), patch(
            "qzwhatnext.integrations.google_calendar.build",
            return_value=MagicMock(),
        ), patch(
            "qzwhatnext.api.app.GoogleCalendarClient.create_event_from_block",
            return_value={"id": "evt_123"},
        ):
            sync = test_client.post("/sync-calendar")
            assert sync.status_code == 200
            payload = sync.json()
            assert payload["events_created"] >= 1
            assert isinstance(payload["event_ids"], list)


