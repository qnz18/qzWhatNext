"""Todoist integration for qzWhatNext."""

import os
from datetime import datetime
from typing import List, Optional
import requests
from dotenv import load_dotenv

from qzwhatnext.models.task import Task, TaskStatus, TaskCategory, EnergyIntensity
from qzwhatnext.engine.ai_exclusion import is_ai_excluded

load_dotenv()

TODOIST_API_BASE = "https://api.todoist.com/rest/v2"


class TodoistClient:
    """Client for Todoist API integration."""
    
    def __init__(self, api_token: Optional[str] = None):
        """Initialize Todoist client.
        
        Args:
            api_token: Todoist API token. If None, reads from TODOIST_API_TOKEN env var.
        """
        self.api_token = api_token or os.getenv("TODOIST_API_TOKEN")
        if not self.api_token:
            raise ValueError("Todoist API token is required. Set TODOIST_API_TOKEN env var.")
        
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }
    
    def fetch_active_tasks(self) -> List[dict]:
        """Fetch all active (non-completed) tasks from Todoist.
        
        Returns:
            List of Todoist task dictionaries
            
        Raises:
            requests.RequestException: If API call fails
        """
        url = f"{TODOIST_API_BASE}/tasks"
        params = {"filter": "view all"}  # Get all active tasks
        
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise Exception(f"Failed to fetch tasks from Todoist: {e}") from e
    
    def normalize_task(self, todoist_task: dict) -> Task:
        """Normalize a Todoist task to qzWhatNext Task model.
        
        Args:
            todoist_task: Todoist task dictionary from API
            
        Returns:
            Normalized Task object
        """
        # Parse dates (handle timezone-aware and naive datetimes)
        created_at_str = todoist_task["created_at"]
        if created_at_str.endswith("Z"):
            created_at_str = created_at_str.replace("Z", "+00:00")
        created_at = datetime.fromisoformat(created_at_str)
        
        updated_at_str = todoist_task["updated_at"]
        if updated_at_str.endswith("Z"):
            updated_at_str = updated_at_str.replace("Z", "+00:00")
        updated_at = datetime.fromisoformat(updated_at_str)
        
        deadline = None
        if todoist_task.get("due"):
            due_date = todoist_task["due"].get("date")
            if due_date:
                if due_date.endswith("Z"):
                    due_date = due_date.replace("Z", "+00:00")
                deadline = datetime.fromisoformat(due_date)
        
        # Check for AI exclusion (period prefix)
        title = todoist_task.get("content", "")
        ai_excluded = title.startswith('.') if title else False
        
        # Map Todoist priority to our risk/impact (Todoist: 1=normal, 4=urgent)
        # For minimal MVP, use simple mapping
        priority = todoist_task.get("priority", 1)
        risk_score = min(0.3 + (priority - 1) * 0.2, 1.0)
        impact_score = min(0.3 + (priority - 1) * 0.2, 1.0)
        
        # Infer category from task content (simple keyword matching for MVP)
        # This is a placeholder - in full version, AI would do this
        category = self._infer_category(title, todoist_task.get("description", ""))
        
        # Default duration (30 minutes)
        # In full version, AI would estimate this
        estimated_duration_min = 30
        
        # Default energy intensity
        energy_intensity = EnergyIntensity.MEDIUM
        
        # Extract dependencies from task content or labels (simplified for MVP)
        dependencies = []
        
        task = Task(
            id=todoist_task["id"],
            source="todoist",
            title=title,
            notes=todoist_task.get("description"),
            status=TaskStatus.OPEN if todoist_task.get("is_completed", False) is False else TaskStatus.COMPLETED,
            created_at=created_at,
            updated_at=updated_at,
            deadline=deadline,
            estimated_duration_min=estimated_duration_min,
            duration_confidence=0.5,  # Default confidence for MVP
            category=category,
            energy_intensity=energy_intensity,
            risk_score=risk_score,
            impact_score=impact_score,
            dependencies=dependencies,
            flexibility_window=None,
            ai_excluded=ai_excluded,
            manual_priority_locked=False,
            user_locked=False,
            manually_scheduled=False,
        )
        
        return task
    
    def _infer_category(self, title: str, description: str) -> TaskCategory:
        """Simple category inference from keywords (MVP placeholder).
        
        In full version, AI would do this with confidence scores.
        For MVP, use simple keyword matching.
        """
        text = (title + " " + description).lower()
        
        # Child-related keywords
        if any(word in text for word in ["child", "kid", "school", "homework", "pickup", "dropoff"]):
            return TaskCategory.CHILD
        
        # Health-related keywords
        if any(word in text for word in ["doctor", "appointment", "health", "exercise", "workout", "gym", "medication"]):
            return TaskCategory.HEALTH
        
        # Work-related keywords
        if any(word in text for word in ["meeting", "work", "project", "deadline", "client", "email", "call"]):
            return TaskCategory.WORK
        
        # Home-related keywords
        if any(word in text for word in ["clean", "repair", "maintenance", "grocery", "shopping", "laundry"]):
            return TaskCategory.HOME
        
        # Family/social keywords
        if any(word in text for word in ["family", "dinner", "party", "birthday", "visit"]):
            return TaskCategory.FAMILY
        
        # Default
        return TaskCategory.OTHER
    
    def import_tasks(self) -> List[Task]:
        """Import and normalize all active tasks from Todoist.
        
        Returns:
            List of normalized Task objects
        """
        todoist_tasks = self.fetch_active_tasks()
        normalized_tasks = [self.normalize_task(task) for task in todoist_tasks]
        return normalized_tasks

