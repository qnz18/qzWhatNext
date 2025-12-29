from __future__ import annotations

import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv
import requests
from todoist_api_python.api import TodoistAPI

from .models import TaskRaw

# Load .env file from project root if it exists
_project_root = Path(__file__).parent.parent
load_dotenv(_project_root / ".env")


def _get_api_token() -> str:
    """
    Retrieves Todoist API token from environment variable or .env file.
    
    Checks in this order:
    1. TODOIST_API_TOKEN environment variable (set in shell)
    2. .env file in project root
    
    Raises ValueError if token is not set (security: never hardcode tokens).
    """
    token = os.getenv("TODOIST_API_TOKEN")
    if not token:
        raise ValueError(
            "TODOIST_API_TOKEN is not set.\n\n"
            "To get your token:\n"
            "1. Go to https://app.todoist.com/app/settings/integrations\n"
            "2. Scroll to 'API token' and copy it\n\n"
            "To save it (choose one):\n"
            "  Option A: Create a .env file in the project root:\n"
            "    echo 'TODOIST_API_TOKEN=your_token_here' > .env\n\n"
            "  Option B: Export in your shell:\n"
            "    export TODOIST_API_TOKEN=your_token_here\n"
        )
    return token


def get_tasks() -> List[TaskRaw]:
    """
    Fetches tasks from Todoist API.
    
    Returns:
        List of TaskRaw objects mapped from Todoist API response.
        
    Raises:
        ValueError: If API token is not configured.
        RuntimeError: If API request fails (wraps HTTPError or other request exceptions).
    """
    api_token = _get_api_token()
    api = TodoistAPI(api_token)
    
    try:
        # get_tasks() returns Iterator[list[Task]], so we need to flatten it
        todoist_tasks_iterator = api.get_tasks()
        # Flatten the iterator of lists into a single list of tasks
        all_todoist_tasks = []
        for task_list in todoist_tasks_iterator:
            all_todoist_tasks.extend(task_list)
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(
            f"Failed to fetch tasks from Todoist API: {e}. "
            "Check your API token and network connection."
        ) from e
    except requests.exceptions.RequestException as e:
        raise RuntimeError(
            f"Network error while fetching tasks from Todoist API: {e}. "
            "Check your network connection."
        ) from e
    
    # Map Todoist API response to TaskRaw format
    tasks: List[TaskRaw] = []
    for task in all_todoist_tasks:
        # Extract due date: Todoist SDK v3.1.0 returns Due object with 'date' attribute
        # due can be None or a Due object with a 'date' attribute (ISO8601 string)
        due_str: str | None = None
        if task.due:
            # Due object has a 'date' attribute (ApiDue type, which is a string)
            if hasattr(task.due, "date"):
                due_str = str(task.due.date)
        
        tasks.append(
            TaskRaw(
                id=str(task.id),
                content=task.content,
                description=task.description or "",
                due=due_str,
                priority=task.priority,
                labels=task.labels or [],
                project_id=str(task.project_id),
                created_at=task.created_at,
            )
        )
    
    return tasks