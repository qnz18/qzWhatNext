"""Integration tests for API endpoints.

These tests verify API endpoints work correctly end-to-end.
"""

import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from qzwhatnext.models.task import TaskStatus, TaskCategory, EnergyIntensity


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


