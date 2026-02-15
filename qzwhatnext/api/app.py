"""FastAPI web application for qzWhatNext."""

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone, date, time
from zoneinfo import ZoneInfo
from typing import List, Optional, Dict, Tuple
from urllib.parse import urlencode, urlparse, urlunparse

import jwt
import requests
from fastapi import FastAPI, HTTPException, Depends, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials as GoogleCredentials
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from qzwhatnext.models.task import Task, TaskStatus, TaskCategory, EnergyIntensity
from qzwhatnext.models.scheduled_block import ScheduledBlock
from qzwhatnext.models.task_factory import create_task_base, determine_ai_exclusion
from qzwhatnext.api.auth_models import (
    GoogleOAuthCallbackRequest,
    GoogleOAuthCodeExchangeRequest,
    AuthResponse,
)
from qzwhatnext.integrations.google_calendar import (
    GoogleCalendarClient,
    PRIVATE_KEY_BLOCK_ID,
    PRIVATE_KEY_MANAGED,
    PRIVATE_KEY_TASK_ID,
    PRIVATE_KEY_TIME_BLOCK_ID,
)
from qzwhatnext.integrations.google_sheets import GoogleSheetsClient
from qzwhatnext.engine.ranking import stack_rank
from qzwhatnext.engine.scheduler import schedule_tasks, SchedulingResult
from qzwhatnext.engine.inference import infer_category, generate_title, estimate_duration
from qzwhatnext.database.database import get_db, init_db
from qzwhatnext.database.repository import TaskRepository
from qzwhatnext.database.recurring_task_series_repository import RecurringTaskSeriesRepository
from qzwhatnext.database.recurring_time_block_repository import RecurringTimeBlockRepository
from qzwhatnext.database.google_oauth_token_repository import (
    GoogleOAuthTokenRepository,
    decrypt_secret,
)
from qzwhatnext.database.user_repository import UserRepository
from qzwhatnext.database.scheduled_block_repository import ScheduledBlockRepository
from qzwhatnext.database.models import ApiTokenDB
from qzwhatnext.auth.jwt import create_access_token
from qzwhatnext.auth.google_oauth import verify_google_token
from qzwhatnext.auth.dependencies import get_current_user
from qzwhatnext.auth.shortcut_tokens import generate_shortcut_token, hash_shortcut_token
from qzwhatnext.models.user import User
from qzwhatnext.recurrence.interpret import interpret_capture_instruction
from qzwhatnext.recurrence.deterministic_parser import RecurrenceParseError
from qzwhatnext.recurrence.materialize import materialize_recurring_tasks
from qzwhatnext.recurrence.rrule_export import preset_to_rrule

# Initialize logger
logger = logging.getLogger(__name__)


# Helper functions
def _build_task_titles_dict(tasks: List[Task], scheduled_blocks: List[ScheduledBlock]) -> Dict[str, str]:
    """Build a dictionary mapping task IDs to task titles for scheduled blocks.
    
    Args:
        tasks: List of tasks
        scheduled_blocks: List of scheduled blocks to extract task IDs from
        
    Returns:
        Dictionary mapping entity_id to task title for task-type blocks
    """
    task_dict = {task.id: task for task in tasks}
    task_titles = {}
    for block in scheduled_blocks:
        if block.entity_type == "task" and block.entity_id in task_dict:
            task_titles[block.entity_id] = task_dict[block.entity_id].title
    return task_titles


def _public_url_for(request: Request, endpoint_name: str) -> str:
    """Create an absolute URL honoring reverse-proxy scheme headers (Cloud Run)."""
    url = str(request.url_for(endpoint_name))
    forwarded_proto = request.headers.get("x-forwarded-proto")
    if forwarded_proto:
        parsed = urlparse(url)
        url = urlunparse(parsed._replace(scheme=forwarded_proto))
    return url


def _parse_rfc3339(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse RFC3339 datetime string to timezone-aware datetime when possible."""
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        return None


def _to_utc_naive(dt: Optional[datetime]) -> Optional[datetime]:
    """Convert datetime to UTC-naive (or pass through naive datetimes)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _to_rfc3339_z(dt: datetime) -> str:
    """Convert datetime to RFC3339 string with trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _event_private(event: dict) -> dict:
    return ((event.get("extendedProperties") or {}).get("private") or {})


def _event_time_window_utc_naive(event: dict) -> Optional[Tuple[datetime, datetime]]:
    """Extract an event's [start, end) window as UTC-naive datetimes.

    Only uses start/end time fields; ignores summary/description/attendees.
    Handles both timed events (dateTime) and all-day events (date).
    """
    if not isinstance(event, dict):
        return None
    if (event.get("status") or "").lower() == "cancelled":
        return None

    start = event.get("start") or {}
    end = event.get("end") or {}

    start_str = start.get("dateTime")
    end_str = end.get("dateTime")
    if start_str and end_str:
        s = _to_utc_naive(_parse_rfc3339(start_str))
        e = _to_utc_naive(_parse_rfc3339(end_str))
        if s is None or e is None or e <= s:
            return None
        return (s, e)

    # All-day events: Google represents end date as exclusive.
    start_date = start.get("date")
    end_date = end.get("date")
    if start_date and end_date:
        try:
            sd = date.fromisoformat(start_date)
            ed = date.fromisoformat(end_date)
        except Exception:
            return None
        s = datetime(sd.year, sd.month, sd.day)
        e = datetime(ed.year, ed.month, ed.day)
        if e <= s:
            return None
        return (s, e)

    return None


def _encode_calendar_oauth_state(user_id: str) -> str:
    """Signed state token binding OAuth callback to a user (short-lived)."""
    secret = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
    payload = {
        "sub": user_id,
        "purpose": "google_calendar_oauth",
        "jti": str(uuid.uuid4()),
        "exp": datetime.utcnow() + timedelta(minutes=10),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, secret, algorithm=os.getenv("JWT_ALGORITHM", "HS256"))


def _decode_calendar_oauth_state(state: str) -> str:
    secret = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
    try:
        payload = jwt.decode(
            state,
            secret,
            algorithms=[os.getenv("JWT_ALGORITHM", "HS256")],
            options={"require": ["exp", "sub"]},
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid OAuth state") from e
    if payload.get("purpose") != "google_calendar_oauth":
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    return str(user_id)


# Initialize FastAPI app
app = FastAPI(
    title="qzWhatNext API",
    description="Continuously tells you what you should be doing right now and immediately next",
    version="0.1.0"
)

# Add CORS middleware to allow frontend requests
# Must be added before other middleware/routes
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    """Initialize database and logging on application startup."""
    # Configure logging format if not already configured
    if not logging.root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    init_db()

# Note: Schedule is now persisted in database via ScheduledBlockRepository


# Request/Response models
class TaskCreateRequest(BaseModel):
    """Request model for creating a task."""
    title: str
    notes: Optional[str] = None
    deadline: Optional[datetime] = None
    start_after: Optional[date] = None
    due_by: Optional[date] = None
    estimated_duration_min: int = 30
    category: TaskCategory = TaskCategory.UNKNOWN
    source_type: str = "api"
    source_id: Optional[str] = None
    
    @field_validator('category', mode='before')
    @classmethod
    def validate_category(cls, v):
        """Convert invalid categories to UNKNOWN."""
        if v is None:
            return TaskCategory.UNKNOWN
        
        # If it's already a TaskCategory enum, return it
        if isinstance(v, TaskCategory):
            return v
        
        # Try to convert string to enum
        try:
            return TaskCategory(str(v).lower())
        except (ValueError, AttributeError):
            # Invalid category - default to UNKNOWN
            return TaskCategory.UNKNOWN


class TaskUpdateRequest(BaseModel):
    """Request model for updating a task."""
    title: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[TaskStatus] = None
    deadline: Optional[datetime] = None
    start_after: Optional[date] = None
    due_by: Optional[date] = None
    estimated_duration_min: Optional[int] = None
    category: Optional[TaskCategory] = None
    energy_intensity: Optional[EnergyIntensity] = None
    risk_score: Optional[float] = None
    impact_score: Optional[float] = None
    ai_excluded: Optional[bool] = None
    
    @field_validator('category', mode='before')
    @classmethod
    def validate_category(cls, v):
        """Convert invalid categories to UNKNOWN if provided."""
        if v is None:
            return None  # Keep None for optional fields
        
        # If it's already a TaskCategory enum, return it
        if isinstance(v, TaskCategory):
            return v
        
        # Try to convert string to enum
        try:
            return TaskCategory(str(v).lower())
        except (ValueError, AttributeError):
            # Invalid category - default to UNKNOWN
            return TaskCategory.UNKNOWN


class TaskAddSmartRequest(BaseModel):
    """Request model for iOS Shortcut task creation (notes only, auto-generates timestamp title)."""
    notes: str


class TaskResponse(BaseModel):
    """Response model for task."""
    task: Task


class TaskListResponse(BaseModel):
    """Response model for task list."""
    tasks: List[Task]
    count: int


class BulkTaskIdsRequest(BaseModel):
    """Request model for bulk task actions based on explicit IDs."""
    task_ids: List[str] = Field(..., min_length=1, description="List of task IDs to operate on")


class BulkActionResponse(BaseModel):
    """Response model for bulk delete/restore/purge actions."""
    affected_count: int
    not_found_ids: List[str] = Field(default_factory=list)


class ImportSheetsRequest(BaseModel):
    """Request model for importing from Google Sheets."""
    spreadsheet_id: str
    range_name: str = "Sheet1!A1:E10"
    has_header: bool = True


class ImportSheetsResponse(BaseModel):
    """Response model for Google Sheets import."""
    imported_count: int
    tasks: List[Task]
    duplicates_detected: int = 0


class CaptureRequest(BaseModel):
    """Single-input capture request.

    The backend auto-determines whether this becomes:
    - a recurring task series (materialized into Task instances), or
    - a recurring calendar/time block (Google Calendar recurring event),
    - a one-off Task, or
    - a one-off Calendar event.

    If entity_id is provided, the request updates that existing entity.
    """

    instruction: str = Field(..., min_length=1)
    entity_id: Optional[str] = Field(None, description="Optional id of an existing recurring series/time block to update")


class CaptureResponse(BaseModel):
    """Single-input capture response."""

    action: str = Field(..., description="created or updated")
    entity_kind: str = Field(..., description="task_series, time_block, task, or calendar_event")
    entity_id: str
    tasks_created: int = 0
    calendar_event_id: Optional[str] = None


class ScheduleResponse(BaseModel):
    """Response for schedule view."""
    scheduled_blocks: List[ScheduledBlock]
    overflow_tasks: List[Task]
    start_time: Optional[datetime]
    task_titles: Dict[str, str] = Field(default_factory=dict, description="Map of entity_id to task title")
    time_zone: Optional[str] = Field(
        None,
        description="User's Google Calendar timezone for display/scheduling (if available)",
    )


class SyncResponse(BaseModel):
    """Response for calendar sync."""
    events_created: int
    event_ids: List[str]


class ScheduledBlockResponse(BaseModel):
    """Response model for scheduled block operations."""
    block: ScheduledBlock


class ShortcutTokenStatusResponse(BaseModel):
    """Response for shortcut token status."""
    active: bool
    token_prefix: Optional[str] = None
    created_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None


class ShortcutTokenCreateResponse(BaseModel):
    """Response for creating a new shortcut token (token returned once)."""
    token: str
    token_prefix: str
    created_at: datetime


@app.get("/", response_class=HTMLResponse)
async def root():
    """Root endpoint with basic UI."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>qzWhatNext</title>
        <script src="https://accounts.google.com/gsi/client" async defer></script>
        <style>
            body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
            button { padding: 10px 20px; margin: 5px; cursor: pointer; }
            .section { margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background-color: #f2f2f2; position: sticky; top: 0; z-index: 10; }
            td.notes { max-width: 300px; word-wrap: break-word; white-space: normal; }
            .tasks-container { max-height: 500px; overflow-y: auto; border: 1px solid #ddd; border-radius: 5px; margin-top: 10px; }
            input, textarea, select { width: 100%; padding: 8px; margin: 5px 0; box-sizing: border-box; }
            label { display: block; margin-top: 10px; font-weight: bold; }
            .form-group { margin: 10px 0; }
            .muted { color: #666; font-size: 0.9em; }
            .row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
            .row.grow { align-items: flex-start; }
            .row .spacer { flex: 1 1 auto; }
            .row .wrap { flex: 1 1 260px; min-width: 220px; }
            .task-select { width: auto; margin: 0; }
            th.select-col, td.select-col { width: 44px; text-align: center; }
            #tasksUpdated { display: inline-block; }
            .tasks-actions { display: block; margin-top: 6px; }
            .tasks-actions label { white-space: nowrap; display: inline-flex; align-items: center; gap: 6px; font-weight: normal; margin-top: 0; }
            .tasks-actions-bottom { margin-top: 10px; display: flex; gap: 10px; justify-content: flex-start; flex-wrap: wrap; }
            .tasks-actions-bottom button { width: auto; padding: 6px 12px; font-size: 0.9em; }
            tr.task-row { cursor: pointer; }
            tr.task-row.highlighted { background-color: #fff3cd; }
        </style>
    </head>
    <body>
        <h1>qzWhatNext</h1>
        <p>Continuously tells you what you should be doing right now and immediately next.</p>

        <div class="section">
            <h2>Sign in</h2>
            <div class="row">
                <div id="gsi-button"></div>
                <button onclick="signOut()">Sign out</button>
            </div>
            <div id="authStatus" class="muted"></div>
            <div id="userInfo" class="muted"></div>
            <div class="row" style="margin-top: 10px;">
                <button id="copyJwtBtn" onclick="copyJwt()" disabled>Copy JWT</button>
                <span id="jwtStatus" class="muted"></span>
            </div>
        </div>

        <div class="section">
            <h2>Tasks</h2>
            <div class="row">
                <button onclick="viewTasks()">Refresh Tasks</button>
                <span id="tasksUpdated" class="muted wrap"></span>
            </div>
            <div class="tasks-actions">
                <label>
                    <input type="checkbox" id="selectAllTasks" onchange="toggleSelectAllTasks(this.checked)">
                    Select all
                </label>
            </div>
            <div id="tasks"></div>
            <div id="taskEditorPanel" style="margin-top: 12px; padding: 10px; border: 1px solid #e5e5e5; border-radius: 6px;">
                <div class="row" style="align-items: end;">
                    <div class="wrap">
                        <label>Task editor</label>
                        <div class="muted">Click a task above to load it here.</div>
                        <input type="hidden" id="editTaskId">
                    </div>
                    <button type="button" onclick="saveTaskEdits()">Save</button>
                </div>

                <div class="row" style="margin-top: 10px;">
                    <div class="wrap" style="min-width: 260px;">
                        <label for="editTaskTitle">Title</label>
                        <input type="text" id="editTaskTitle">
                    </div>
                    <div class="wrap" style="min-width: 200px;">
                        <label for="editTaskStatus">Status</label>
                        <select id="editTaskStatus">
                            <option value="open" selected>open</option>
                            <option value="completed">completed</option>
                        </select>
                    </div>
                    <div class="wrap" style="min-width: 180px;">
                        <label for="editTaskDuration">Duration (min)</label>
                        <input type="number" id="editTaskDuration" min="1" value="30">
                    </div>
                </div>

                <div class="row" style="margin-top: 8px;">
                    <div class="wrap" style="min-width: 220px;">
                        <label for="editTaskCategory">Category</label>
                        <select id="editTaskCategory">
                            <option value="work">Work</option>
                            <option value="child">Child</option>
                            <option value="family">Family</option>
                            <option value="health">Health</option>
                            <option value="personal">Personal</option>
                            <option value="ideas">Ideas</option>
                            <option value="home">Home</option>
                            <option value="admin">Admin</option>
                            <option value="unknown" selected>Unknown</option>
                        </select>
                    </div>
                    <div class="wrap" style="min-width: 220px;">
                        <label for="editTaskEnergy">Energy</label>
                        <select id="editTaskEnergy">
                            <option value="low">low</option>
                            <option value="medium" selected>medium</option>
                            <option value="high">high</option>
                        </select>
                    </div>
                    <div class="wrap" style="min-width: 180px;">
                        <label for="editTaskRisk">Risk (0-1)</label>
                        <input type="number" id="editTaskRisk" min="0" max="1" step="0.01" placeholder="(blank clears)">
                    </div>
                    <div class="wrap" style="min-width: 180px;">
                        <label for="editTaskImpact">Impact (0-1)</label>
                        <input type="number" id="editTaskImpact" min="0" max="1" step="0.01" placeholder="(blank clears)">
                    </div>
                </div>

                <div class="row" style="margin-top: 8px;">
                    <div class="wrap" style="min-width: 220px;">
                        <label for="editTaskStartAfter">Start after (YYYY-MM-DD)</label>
                        <input type="date" id="editTaskStartAfter">
                    </div>
                    <div class="wrap" style="min-width: 220px;">
                        <label for="editTaskDueBy">Due by (YYYY-MM-DD)</label>
                        <input type="date" id="editTaskDueBy">
                    </div>
                    <div class="wrap" style="min-width: 360px;">
                        <label for="editTaskDependencies">Dependencies (comma-separated ids)</label>
                        <input type="text" id="editTaskDependencies" placeholder="id1, id2, id3">
                    </div>
                </div>

                <div class="form-group" style="margin-top: 8px;">
                    <label for="editTaskNotes">Notes</label>
                    <textarea id="editTaskNotes" rows="2" placeholder="(blank clears)"></textarea>
                </div>
            </div>
        </div>

        <div class="section">
            <h2>Actions</h2>
            <div class="row">
                <div class="wrap">
                    <label for="scheduleHorizonDays">Schedule horizon</label>
                    <select id="scheduleHorizonDays">
                        <option value="7" selected>7 days</option>
                        <option value="14">14 days</option>
                        <option value="30">30 days</option>
                    </select>
                </div>
            </div>
            <button onclick="buildSchedule()">Build Schedule</button>
            <button onclick="syncCalendar()">Sync to Google Calendar</button>
            <button onclick="viewSchedule()">View Schedule</button>
            <button onclick="viewTasks()">View All Tasks</button>
        </div>
        
        <div class="section">
            <h2>Schedule</h2>
            <div id="scheduleFilterInfo" class="muted" style="margin-bottom: 8px;"></div>
            <div id="schedule"></div>
        </div>

        <div class="section">
            <h2>Capture (single input)</h2>
            <p class="muted">Type what you need. qzWhatNext will decide whether to create a recurring task series, a recurring time block, or (for “this/next”) a one-off.</p>
            <div id="captureForm">
                <div class="form-group">
                    <label for="captureInstruction">Instruction *</label>
                    <textarea id="captureInstruction" rows="2" placeholder="e.g., take my vitamins every morning&#10;e.g., kids practice tues at 4:30&#10;e.g., bed time every day 11pm to 7am" required></textarea>
                </div>
                <div class="form-group">
                    <label for="captureEntityId">Update existing (optional entity_id)</label>
                    <input type="text" id="captureEntityId" placeholder="Paste an entity_id returned by a previous capture to update it">
                </div>
                <button type="button" onclick="captureInstruction()">Capture</button>
                <div id="captureResult" class="muted" style="margin-top: 8px; padding: 8px; border: 1px solid #ddd; border-radius: 5px; min-height: 18px;">
                    Result will appear here.
                </div>
            </div>
        </div>
        
        <div class="section">
            <h2>Create Task</h2>
            <form id="createTaskForm" onsubmit="createTask(event)">
                <div class="form-group">
                    <label for="taskTitle">Title *</label>
                    <input type="text" id="taskTitle" required>
                </div>
                <div class="form-group">
                    <label for="taskNotes">Notes</label>
                    <textarea id="taskNotes" rows="3"></textarea>
                </div>
                <div class="form-group">
                    <label for="taskDuration">Duration (minutes)</label>
                    <input type="number" id="taskDuration" value="30" min="1">
                </div>
                <div class="form-group">
                    <label for="taskCategory">Category</label>
                    <select id="taskCategory">
                        <option value="work">Work</option>
                        <option value="child">Child</option>
                        <option value="family">Family</option>
                        <option value="health">Health</option>
                        <option value="personal">Personal</option>
                        <option value="ideas">Ideas</option>
                        <option value="home">Home</option>
                        <option value="admin">Admin</option>
                        <option value="unknown" selected>Unknown</option>
                    </select>
                </div>
                <button type="submit">Create Task</button>
            </form>
        </div>
        
        <div class="section">
            <h2>Import from Google Sheets</h2>
            <form id="importSheetsForm" onsubmit="importFromSheets(event)">
                <div class="form-group">
                    <label for="spreadsheetId">Spreadsheet URL or ID *</label>
                    <input type="text" id="spreadsheetId" required value="https://docs.google.com/spreadsheets/d/1Jf-Ktb_yujoNoUv_aNHCrNM_4xlYU_LPMDlPavuYCuc/edit?usp=sharing" placeholder="Paste full URL from 'Copy link' or just the spreadsheet ID">
                    <small>You can paste the full Google Sheets URL (from "Copy link" button) or just the spreadsheet ID</small>
                </div>
                <div class="form-group">
                    <label for="rangeName">Range</label>
                    <input type="text" id="rangeName" value="Sheet1!A1:E10" placeholder="Sheet1!A1:E10">
                </div>
                <div class="form-group">
                    <label>
                        <input type="checkbox" id="hasHeader" checked> Has header row
                    </label>
                </div>
                <button type="submit">Import Tasks</button>
            </form>
        </div>

        <div class="section">
            <h2>iOS Shortcut Token</h2>
            <p class="muted">Generate a long-lived token for iOS Shortcuts. Keep it secret. You can revoke it anytime.</p>
            <div class="row">
                <button onclick="createShortcutToken()">Create / Rotate Token</button>
                <button onclick="revokeShortcutToken()">Revoke Token</button>
                <button onclick="loadShortcutTokenStatus()">Refresh Status</button>
            </div>
            <div id="shortcutTokenStatus" class="muted"></div>
            <pre id="shortcutTokenValue" style="white-space: pre-wrap;"></pre>
        </div>

        <div class="section">
            <h2>Status</h2>
            <div id="status"></div>
        </div>
        
        <script>
            const ACCESS_TOKEN_KEY = "qz_access_token";
            let authVersion = 0;
            let currentUserEmail = null;
            const activeRequestControllers = new Set();

            function isStale(version) {
                return version !== authVersion;
            }

            function bumpAuthVersion() {
                authVersion += 1;
                for (const controller of activeRequestControllers) {
                    try { controller.abort(); } catch (e) { /* ignore */ }
                }
                activeRequestControllers.clear();
            }

            function beginRequest(version) {
                const controller = new AbortController();
                activeRequestControllers.add(controller);
                return {
                    signal: controller.signal,
                    done: () => activeRequestControllers.delete(controller),
                    version: version
                };
            }

            function getAccessToken() {
                return localStorage.getItem(ACCESS_TOKEN_KEY);
            }

            function setAccessToken(token) {
                if (token) {
                    localStorage.setItem(ACCESS_TOKEN_KEY, token);
                } else {
                    localStorage.removeItem(ACCESS_TOKEN_KEY);
                }
                // Keep JWT UI in sync with auth state.
                if (typeof setJwtUiState === 'function') {
                    setJwtUiState();
                }
            }

            function setAuthStatus(message) {
                const el = document.getElementById('authStatus');
                if (el) el.textContent = message || '';
            }

            function setUserInfo(message) {
                const el = document.getElementById('userInfo');
                if (el) el.textContent = message || '';
            }

            function onAuthFailure(message, version = authVersion) {
                if (isStale(version)) return;
                // Token exists locally but is invalid/expired server-side.
                // Clear it to keep UI state consistent with the backend.
                bumpAuthVersion();
                setAccessToken(null);
                currentUserEmail = null;
                setUserInfo('');
                setAuthStatus(message || 'Session expired. Please sign in again.');
                const tasksDiv = document.getElementById('tasks');
                if (tasksDiv) tasksDiv.innerHTML = '<p>Not signed in. Click Sign in to load tasks.</p>';
                const tasksUpdated = document.getElementById('tasksUpdated');
                if (tasksUpdated) tasksUpdated.textContent = '';
                const scheduleDiv = document.getElementById('schedule');
                if (scheduleDiv) scheduleDiv.innerHTML = '';
            }

            function setJwtUiState() {
                const btn = document.getElementById('copyJwtBtn');
                const status = document.getElementById('jwtStatus');
                if (!btn || !status) return;

                const token = getAccessToken();
                if (token) {
                    btn.disabled = false;
                    status.textContent = 'JWT ready (copy-only)';
                } else {
                    btn.disabled = true;
                    status.textContent = 'Not signed in';
                }
            }

            async function copyJwt() {
                const status = document.getElementById('jwtStatus');
                const token = getAccessToken();
                if (!token) {
                    if (status) status.textContent = 'Not signed in';
                    return;
                }

                try {
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                        await navigator.clipboard.writeText(token);
                    } else {
                        // Fallback for older browsers / non-clipboard contexts
                        const el = document.createElement('textarea');
                        el.value = token;
                        el.setAttribute('readonly', '');
                        el.style.position = 'absolute';
                        el.style.left = '-9999px';
                        document.body.appendChild(el);
                        el.select();
                        document.execCommand('copy');
                        document.body.removeChild(el);
                    }
                    if (status) status.textContent = 'JWT copied to clipboard';
                } catch (e) {
                    if (status) status.textContent = 'Copy failed';
                    console.error('Copy JWT failed:', e);
                }
            }

            async function apiFetch(path, options = {}, version = authVersion) {
                const token = getAccessToken();
                const headers = Object.assign({}, options.headers || {});
                if (token) {
                    headers['Authorization'] = `Bearer ${token}`;
                }
                const req = beginRequest(version);
                try {
                    const response = await fetch(path, Object.assign({}, options, { headers, signal: req.signal }));
                    if (response.status === 401 || response.status === 403) {
                        let detail = '';
                        try {
                            const err = await response.clone().json();
                            detail = (err && err.detail) ? String(err.detail) : '';
                        } catch (e) {
                            // ignore parse failure
                        }
                        const msg = detail || 'Session expired. Please sign in again.';
                        onAuthFailure(msg, version);
                        throw new Error(msg);
                    }
                    return response;
                } finally {
                    req.done();
                }
            }

            async function refreshMe(version = authVersion) {
                try {
                    const response = await apiFetch('/auth/me', {}, version);
                    const data = await response.json();
                    if (isStale(version)) return null;
                    const u = data.user || data;
                    if (u && u.email) {
                        currentUserEmail = u.email;
                        setUserInfo(`Signed in as ${u.email}`);
                    } else {
                        currentUserEmail = null;
                        setUserInfo('Signed in.');
                    }
                    return u;
                } catch (e) {
                    if (!isStale(version)) {
                        currentUserEmail = null;
                        setUserInfo('');
                    }
                    return null;
                }
            }

            function showSignedOutUi(message) {
                setAuthStatus(message || 'Not signed in.');
                setUserInfo('');
                setJwtUiState();
                const tasksDiv = document.getElementById('tasks');
                if (tasksDiv) tasksDiv.innerHTML = '<p>Sign in to load tasks.</p>';
                const tasksUpdated = document.getElementById('tasksUpdated');
                if (tasksUpdated) tasksUpdated.textContent = '';
                const scheduleDiv = document.getElementById('schedule');
                if (scheduleDiv) scheduleDiv.innerHTML = '';
                const shortcutStatus = document.getElementById('shortcutTokenStatus');
                if (shortcutStatus) shortcutStatus.textContent = '';
                const shortcutVal = document.getElementById('shortcutTokenValue');
                if (shortcutVal) shortcutVal.textContent = '';
            }

            async function syncSessionOnLoad() {
                const version = authVersion;
                if (!getAccessToken()) {
                    showSignedOutUi('Not signed in.');
                    return;
                }
                setAuthStatus('Checking session...');
                await refreshMe(version);
                if (isStale(version)) return;
                if (!getAccessToken()) {
                    // Token was cleared during refresh (expired/invalid)
                    showSignedOutUi('Session expired. Please sign in again.');
                    return;
                }
                setAuthStatus('Signed in.');
                await viewTasks(version);
                // Load schedule on refresh so it doesn't appear to "disappear".
                try { await viewSchedule(version); } catch (e) { /* ignore */ }
                await loadShortcutTokenStatus(version);
            }

            async function loadAuthConfig() {
                const res = await fetch('/auth/config');
                if (!res.ok) return null;
                return await res.json();
            }

            async function handleGoogleCodeResponse(response) {
                try {
                    const preLoginVersion = authVersion;
                    setAuthStatus('Signing in...');
                    const code = response && response.code;
                    if (!code) {
                        const err = response && response.error ? String(response.error) : 'No OAuth code received.';
                        throw new Error(err);
                    }

                    const res = await fetch('/auth/google/code-exchange', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            // CSRF signal required by our backend for popup code model.
                            'X-Requested-With': 'XmlHttpRequest'
                        },
                        body: JSON.stringify({ code })
                    });

                    if (!res.ok) {
                        const errBody = await res.json().catch(() => ({}));
                        throw new Error(errBody.detail || 'Failed to authenticate');
                    }

                    const data = await res.json();
                    if (isStale(preLoginVersion)) return;
                    // Invalidate any in-flight requests tied to the old auth state.
                    bumpAuthVersion();
                    setAccessToken(data.access_token);
                    const version = authVersion;
                    setAuthStatus('Signed in.');
                    await refreshMe(version);
                    if (isStale(version)) return;
                    await viewTasks(version);
                    try { await viewSchedule(version); } catch (e) { /* ignore */ }
                    await loadShortcutTokenStatus(version);
                } catch (e) {
                    console.error('Auth error:', e);
                    setAuthStatus('Auth error: ' + (e && e.message ? e.message : String(e)));
                }
            }

            async function handleGoogleCredentialResponse(response) {
                try {
                    const preLoginVersion = authVersion;
                    setAuthStatus('Signing in...');
                    const idToken = response && response.credential;
                    if (!idToken) {
                        throw new Error('No Google ID token received.');
                    }

                    const res = await fetch('/auth/google/callback', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ id_token: idToken })
                    });

                    if (!res.ok) {
                        const err = await res.json().catch(() => ({}));
                        throw new Error(err.detail || 'Failed to authenticate');
                    }

                    const data = await res.json();
                    if (isStale(preLoginVersion)) return;
                    // Invalidate any in-flight requests tied to the old auth state.
                    bumpAuthVersion();
                    setAccessToken(data.access_token);
                    const version = authVersion;
                    setAuthStatus('Signed in.');
                    await refreshMe(version);
                    if (isStale(version)) return;
                    await viewTasks(version);
                    try { await viewSchedule(version); } catch (e) { /* ignore */ }
                    await loadShortcutTokenStatus(version);
                } catch (e) {
                    console.error('Auth error:', e);
                    setAuthStatus('Auth error: ' + (e && e.message ? e.message : String(e)));
                }
            }

            async function initGoogleSignIn() {
                const cfg = await loadAuthConfig();
                const clientId = cfg && cfg.google_oauth_client_id;
                if (!clientId) {
                    setAuthStatus('Missing GOOGLE_OAUTH_CLIENT_ID on the server. Set it in your .env and restart.');
                    return;
                }
                if (!window.google || !google.accounts) {
                    setAuthStatus('Google sign-in library not loaded yet. Refresh in a second.');
                    return;
                }
                setJwtUiState();
                const unified = !!(cfg && cfg.google_unified_oauth_enabled);
                const container = document.getElementById("gsi-button");
                if (unified) {
                    if (!google.accounts.oauth2 || !google.accounts.oauth2.initCodeClient) {
                        setAuthStatus('Google OAuth library not loaded yet. Refresh in a second.');
                        return;
                    }
                    // Request unified consent: identity + Calendar in one flow.
                    const codeClient = google.accounts.oauth2.initCodeClient({
                        client_id: clientId,
                        scope: 'openid email profile https://www.googleapis.com/auth/calendar',
                        ux_mode: 'popup',
                        callback: handleGoogleCodeResponse,
                        // Force account chooser to avoid accidental wrong-account grants.
                        select_account: true,
                        error_callback: (err) => {
                            const t = err && err.type ? String(err.type) : 'unknown';
                            setAuthStatus('Auth error: ' + t);
                        }
                    });

                    // Render our own button (GIS code client does not provide a styled button helper).
                    if (container) {
                        container.innerHTML = '';
                        const btn = document.createElement('button');
                        btn.id = 'google-auth-button';
                        btn.textContent = 'Sign in with Google';
                        btn.style.padding = '10px 16px';
                        btn.style.border = '1px solid #dadce0';
                        btn.style.borderRadius = '4px';
                        btn.style.background = '#fff';
                        btn.style.cursor = 'pointer';
                        btn.onclick = () => codeClient.requestCode();
                        container.appendChild(btn);
                    }
                } else {
                    if (!google.accounts.id || !google.accounts.id.initialize) {
                        setAuthStatus('Google sign-in library not loaded yet. Refresh in a second.');
                        return;
                    }
                    google.accounts.id.initialize({
                        client_id: clientId,
                        callback: handleGoogleCredentialResponse,
                        // Don't auto-select account - force user to choose
                        auto_select: false,
                        // Cancel One Tap prompt to force button click for account selection
                        cancel_on_tap_outside: true
                    });
                    google.accounts.id.renderButton(
                        container,
                        { 
                            theme: "outline", 
                            size: "large",
                            text: "signin_with",
                            shape: "rectangular"
                        }
                    );
                }
                // Don't auto-prompt - users must click the button to sign in.
                // Also: don't claim "Signed in" unless the backend validates the session.
                if (getAccessToken()) {
                    setAuthStatus('Checking session...');
                    await syncSessionOnLoad();
                } else {
                    showSignedOutUi('Not signed in.');
                }
            }

            function signOut() {
                // Ensure any in-flight requests can’t update the UI after logout.
                bumpAuthVersion();
                setAccessToken(null);
                setAuthStatus('Signed out.');
                setUserInfo('');
                currentUserEmail = null;
                document.getElementById('tasks').innerHTML = '<p>Signed out. Sign in to load tasks.</p>';
                const tasksUpdated = document.getElementById('tasksUpdated');
                if (tasksUpdated) tasksUpdated.textContent = '';
                document.getElementById('schedule').innerHTML = '';
                const shortcutStatus = document.getElementById('shortcutTokenStatus');
                if (shortcutStatus) shortcutStatus.textContent = '';
                const shortcutVal = document.getElementById('shortcutTokenValue');
                if (shortcutVal) shortcutVal.textContent = '';
            }

            async function loadShortcutTokenStatus(version = authVersion) {
                const el = document.getElementById('shortcutTokenStatus');
                const val = document.getElementById('shortcutTokenValue');
                val.textContent = '';
                try {
                    const res = await apiFetch('/auth/shortcut-token', {}, version);
                    const data = await res.json();
                    if (isStale(version)) return;
                    if (!data.active) {
                        el.textContent = 'No active shortcut token.';
                        return;
                    }
                    el.textContent = `Active token prefix: ${data.token_prefix || ''} (created ${data.created_at || ''})`;
                } catch (e) {
                    if (!isStale(version)) {
                        el.textContent = 'Error: ' + (e && e.message ? e.message : String(e));
                    }
                }
            }

            async function createShortcutToken(version = authVersion) {
                const el = document.getElementById('shortcutTokenStatus');
                const val = document.getElementById('shortcutTokenValue');
                val.textContent = '';
                try {
                    el.textContent = 'Creating token...';
                    const res = await apiFetch('/auth/shortcut-token', { method: 'POST' }, version);
                    const data = await res.json();
                    if (isStale(version)) return;
                    el.textContent = `Created token prefix: ${data.token_prefix}. Copy the token below (shown once).`;
                    val.textContent = data.token;
                } catch (e) {
                    if (!isStale(version)) {
                        el.textContent = 'Error: ' + (e && e.message ? e.message : String(e));
                    }
                }
            }

            async function revokeShortcutToken(version = authVersion) {
                const el = document.getElementById('shortcutTokenStatus');
                const val = document.getElementById('shortcutTokenValue');
                val.textContent = '';
                try {
                    el.textContent = 'Revoking token...';
                    await apiFetch('/auth/shortcut-token', { method: 'DELETE' }, version);
                    if (isStale(version)) return;
                    el.textContent = 'Token revoked.';
                } catch (e) {
                    if (!isStale(version)) {
                        el.textContent = 'Error: ' + (e && e.message ? e.message : String(e));
                    }
                }
            }

            async function captureInstruction() {
                const version = authVersion;
                const status = document.getElementById('status');
                const result = document.getElementById('captureResult');
                const instructionEl = document.getElementById('captureInstruction');
                const entityIdEl = document.getElementById('captureEntityId');

                const instruction = (instructionEl && instructionEl.value) ? instructionEl.value.trim() : '';
                const entityId = (entityIdEl && entityIdEl.value) ? entityIdEl.value.trim() : '';

                if (!instruction) {
                    if (result) result.textContent = 'Instruction is required.';
                    return;
                }

                if (status) status.innerHTML = 'Capturing...';
                if (result) result.textContent = 'Capturing...';

                const payload = entityId ? { instruction, entity_id: entityId } : { instruction };

                try {
                    const response = await apiFetch('/capture', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    }, version);

                    const data = await response.json();
                    if (isStale(version)) return;
                    if (!response.ok) {
                        throw new Error((data && data.detail) ? String(data.detail) : 'Failed to capture');
                    }

                    const msgParts = [
                        `${data.action}: ${data.entity_kind}`,
                        `entity_id=${data.entity_id}`,
                    ];
                    if (data.tasks_created) msgParts.push(`tasks_created=${data.tasks_created}`);
                    if (data.calendar_event_id) msgParts.push(`calendar_event_id=${data.calendar_event_id}`);

                    if (result) result.textContent = msgParts.join(' · ');
                    if (status) status.innerHTML = 'Capture ok.';

                    // Refresh task list when we may have created task instances.
                    await viewTasks(version);
                } catch (e) {
                    if (!isStale(version)) {
                        const msg = e && e.message ? e.message : String(e);
                        console.error('Capture failed:', e);
                        if (result) result.textContent = 'Error: ' + msg;
                        if (status) status.innerHTML = 'Error: ' + msg;
                    }
                }
            }

            async function createTask(event) {
                event.preventDefault();
                const version = authVersion;
                const status = document.getElementById('status');
                status.innerHTML = 'Creating task...';
                
                const taskData = {
                    title: document.getElementById('taskTitle').value,
                    notes: document.getElementById('taskNotes').value || null,
                    estimated_duration_min: parseInt(document.getElementById('taskDuration').value) || 30,
                    category: document.getElementById('taskCategory').value
                };
                
                try {
                    const response = await apiFetch('/tasks', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(taskData)
                    }, version);
                    
                    if (!response.ok) {
                        const error = await response.json();
                        throw new Error(error.detail || 'Failed to create task');
                    }
                    
                    const data = await response.json();
                    if (isStale(version)) return;
                    status.innerHTML = `Task created: "${data.task.title}"`;
                    document.getElementById('createTaskForm').reset();
                    await viewTasks(version);
                } catch (error) {
                    if (!isStale(version)) {
                        status.innerHTML = 'Error: ' + error.message;
                    }
                }
            }
            
            async function importFromSheets(event) {
                event.preventDefault();
                const version = authVersion;
                const status = document.getElementById('status');
                status.innerHTML = 'Importing from Google Sheets...';
                
                const importData = {
                    spreadsheet_id: document.getElementById('spreadsheetId').value,
                    range_name: document.getElementById('rangeName').value || 'Sheet1!A1:E10',
                    has_header: document.getElementById('hasHeader').checked
                };
                
                try {
                    // Use full URL to avoid any origin issues
                    const apiUrl = window.location.origin + '/import/sheets';
                    const response = await apiFetch(apiUrl, {
                        method: 'POST',
                        headers: { 
                            'Content-Type': 'application/json',
                            'Accept': 'application/json'
                        },
                        body: JSON.stringify(importData),
                        mode: 'cors',
                        credentials: 'same-origin'
                    }, version);
                    
                    if (!response.ok) {
                        const error = await response.json();
                        throw new Error(error.detail || 'Failed to import from Google Sheets');
                    }
                    
                    const data = await response.json();
                    if (isStale(version)) return;
                    status.innerHTML = `Imported ${data.imported_count} tasks${data.duplicates_detected > 0 ? ` (${data.duplicates_detected} duplicates detected)` : ''}`;
                    document.getElementById('importSheetsForm').reset();
                    await viewTasks(version);
                } catch (error) {
                    console.error('Import error:', error);
                    if (!isStale(version)) {
                        status.innerHTML = 'Error: ' + error.message + '. Check server console for details.';
                    }
                }
            }
            
            async function buildSchedule() {
                const version = authVersion;
                const status = document.getElementById('status');
                status.innerHTML = 'Building schedule...';
                try {
                    const horizonEl = document.getElementById('scheduleHorizonDays');
                    const horizon = horizonEl ? parseInt(horizonEl.value || '7', 10) : 7;
                    const url = `/schedule?horizon_days=${encodeURIComponent(String(horizon))}`;
                    const response = await apiFetch(url, { method: 'POST' }, version);
                    const data = await response.json();
                    if (isStale(version)) return;
                    status.innerHTML = `Schedule built: ${data.scheduled_blocks.length} blocks, ${data.overflow_tasks.length} overflow`;
                    // Use the build response directly so we can capture the calendar timezone for display.
                    lastScheduleData = data;
                    renderSchedule(data);
                } catch (error) {
                    if (!isStale(version)) {
                        status.innerHTML = 'Error: ' + error.message;
                    }
                }
            }
            
            function connectGoogleCalendar(version = authVersion) {
                return new Promise((resolve, reject) => {
                    if (isStale(version)) return reject(new Error('Auth changed; please try again.'));
                    // Important: popups can't attach Authorization headers to backend routes.
                    // Fetch the Google consent URL with JWT, then open Google directly.
                    apiFetch('/auth/google/calendar/auth-url', {}, version).then(async (res) => {
                        let payload = null;
                        try { payload = await res.json(); } catch (e) { /* ignore */ }
                        if (!res.ok) {
                            const detail = (payload && payload.detail) ? String(payload.detail) : `Failed to start calendar connect (HTTP ${res.status})`;
                            throw new Error(detail);
                        }
                        const url = payload && payload.url ? String(payload.url) : '';
                        if (!url) throw new Error('Missing calendar auth URL from server.');

                        const w = window.open(url, 'qz_google_calendar_oauth', 'width=520,height=700');
                        if (!w) throw new Error('Popup blocked. Please allow popups and try again.');

                        let done = false;
                        const cleanup = () => {
                            window.removeEventListener('message', onMessage);
                            clearInterval(poll);
                            done = true;
                            try { w.close(); } catch (e) { /* ignore */ }
                        };

                        const onMessage = (event) => {
                            const data = event && event.data;
                            if (data && data.type === 'qz_google_calendar_connected') {
                                cleanup();
                                resolve(true);
                            }
                        };

                        window.addEventListener('message', onMessage);
                        const poll = setInterval(() => {
                            if (done) return;
                            if (isStale(version)) {
                                cleanup();
                                reject(new Error('Auth changed; please try again.'));
                                return;
                            }
                            if (w.closed) {
                                cleanup();
                                reject(new Error('Google Calendar connection window was closed.'));
                            }
                        }, 500);
                    }).catch((e) => {
                        reject(e instanceof Error ? e : new Error(String(e)));
                    });
                });
            }

            async function syncCalendar() {
                const version = authVersion;
                const status = document.getElementById('status');
                status.innerHTML = 'Syncing to Google Calendar...';
                try {
                    // First attempt
                    let response = await apiFetch('/sync-calendar', { method: 'POST' }, version);
                    let data = null;
                    try { data = await response.clone().json(); } catch (e) { /* ignore */ }

                    if (!response.ok) {
                        const detail = (data && data.detail) ? String(data.detail) : `Sync failed (HTTP ${response.status})`;
                        const needsReconnect =
                            response.status === 400 &&
                            (detail.includes('Google Calendar not connected') ||
                             detail.includes('authorization expired') ||
                             detail.includes('expired or was revoked'));
                        if (needsReconnect) {
                            status.innerHTML = 'Connecting Google Calendar...';
                            await connectGoogleCalendar(version);
                            if (isStale(version)) return;
                            // Retry after connect
                            response = await apiFetch('/sync-calendar', { method: 'POST' }, version);
                            data = await response.json();
                            if (!response.ok) {
                                const retryDetail = (data && data.detail) ? String(data.detail) : `Sync failed (HTTP ${response.status})`;
                                throw new Error(retryDetail);
                            }
                        } else {
                            throw new Error(detail);
                        }
                    } else {
                        data = await response.json();
                    }
                    if (isStale(version)) return;
                    status.innerHTML = `Synced ${data.events_created} events to Google Calendar`;
                } catch (error) {
                    if (!isStale(version)) {
                        status.innerHTML = 'Error: ' + error.message;
                    }
                }
            }
            
            async function viewTasks(version = authVersion) {
                const tasksDiv = document.getElementById('tasks');
                try {
                    const tasksUpdated = document.getElementById('tasksUpdated');
                    if (tasksUpdated && !isStale(version)) tasksUpdated.textContent = 'Refreshing...';
                    const response = await apiFetch('/tasks', {}, version);
                    let data = null;
                    try {
                        data = await response.json();
                    } catch (e) {
                        // Non-JSON error response (or network issue)
                        throw new Error(`Failed to load tasks (HTTP ${response.status})`);
                    }
                    if (isStale(version)) return;

                    if (!response.ok) {
                        const detail = (data && data.detail) ? String(data.detail) : `Failed to load tasks (HTTP ${response.status})`;
                        throw new Error(detail);
                    }

                    if (!data || !Array.isArray(data.tasks)) {
                        throw new Error('Unexpected response from /tasks');
                    }
                    
                    if (data.tasks.length === 0) {
                        selectedTaskIds.clear();
                        lastRenderedTaskIds = [];
                        updateTaskSelectionUi();
                        tasksDiv.innerHTML = '<p>No tasks yet. Create a task or import from Google Sheets.</p>';
                        if (tasksUpdated) tasksUpdated.textContent = `Last refreshed: ${new Date().toLocaleString()}`;
                        return;
                    }
                    
                    lastRenderedTaskIds = (data.tasks || []).map(t => t.id);
                    // Drop any selections that are no longer visible
                    selectedTaskIds = new Set(Array.from(selectedTaskIds).filter(id => lastRenderedTaskIds.includes(id)));

                    let html = `<p><strong>Total tasks: ${data.count}</strong></p>`;
                    html += '<div class="tasks-container"><table><tr><th class="select-col">Sel</th><th>Title</th><th>Category</th><th>Duration</th><th>Status</th><th>Notes</th></tr>';
                    data.tasks.forEach(task => {
                        const notes = task.notes ? task.notes.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;') : '';
                        const checked = selectedTaskIds.has(task.id) ? 'checked' : '';
                        const hl = (highlightedTaskId && highlightedTaskId === task.id) ? 'highlighted' : '';
                        html += `<tr class="task-row ${hl}" data-task-id="${task.id}" onclick="highlightTask('${task.id}')">
                            <td class="select-col"><input type="checkbox" class="task-select" ${checked} onclick="event.stopPropagation()" onchange="toggleTaskSelection('${task.id}', this.checked)"></td>
                            <td>${task.title}</td>
                            <td>${task.category || 'N/A'}</td>
                            <td>${task.estimated_duration_min || 30} min</td>
                            <td>${task.status || 'OPEN'}</td>
                            <td class="notes">${notes || 'N/A'}</td>
                        </tr>`;
                    });
                    html += '</table></div>';

                    html += `
                        <div class="tasks-actions-bottom">
                            <button onclick="deleteSelectedTasks()">Delete selected</button>
                            <button onclick="purgeSelectedTasks()">Purge selected</button>
                        </div>
                    `;
                    
                    tasksDiv.innerHTML = html;
                    updateTaskSelectionUi();
                    if (highlightedTaskId) applyTaskRowHighlight(highlightedTaskId);
                    if (tasksUpdated) tasksUpdated.textContent = `Last refreshed: ${new Date().toLocaleString()}`;
                } catch (error) {
                    if (isStale(version)) return;
                    tasksDiv.innerHTML = 'Error: ' + error.message;
                    const tasksUpdated = document.getElementById('tasksUpdated');
                    if (tasksUpdated) tasksUpdated.textContent = 'Refresh failed.';
                }
            }

            // ----- Task Edit (UI) -----
            let currentEditTaskId = null;
            let highlightedTaskId = null;
            let lastScheduleData = null;
            let lastScheduleTimeZone = null; // persisted best-effort from last schedule fetch

            function getBrowserTimeZone() {
                try {
                    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
                    return tz || null;
                } catch (e) {
                    return null;
                }
            }

            function getUiTimeZone() {
                // Prefer last-known calendar timezone (from /schedule response), else localStorage, else browser.
                if (lastScheduleTimeZone) return lastScheduleTimeZone;
                try {
                    const stored = window.localStorage ? window.localStorage.getItem('qz_calendar_time_zone') : null;
                    if (stored) return stored;
                } catch (e) { /* ignore */ }
                return getBrowserTimeZone() || 'UTC';
            }

            function formatDateTimeInTz(isoString) {
                if (!isoString) return '';
                const tz = getUiTimeZone();
                try {
                    const d = new Date(isoString);
                    if (isNaN(d.getTime())) return String(isoString);
                    return new Intl.DateTimeFormat(undefined, {
                        timeZone: tz,
                        year: 'numeric',
                        month: '2-digit',
                        day: '2-digit',
                        hour: 'numeric',
                        minute: '2-digit',
                    }).format(d);
                } catch (e) {
                    try { return new Date(isoString).toLocaleString(); } catch (_) { return String(isoString); }
                }
            }

            function _getVal(id) {
                const el = document.getElementById(id);
                return el ? el.value : '';
            }

            function _setVal(id, v) {
                const el = document.getElementById(id);
                if (el) el.value = (v === null || v === undefined) ? '' : String(v);
            }

            function _setText(id, v) {
                const el = document.getElementById(id);
                if (el) el.textContent = (v === null || v === undefined) ? '' : String(v);
            }

            async function loadTaskForEdit() {
                const version = authVersion;
                const status = document.getElementById('status');
                const taskId = _getVal('editTaskId').trim();
                if (!taskId) return;
                status.innerHTML = 'Loading task...';
                try {
                    const res = await apiFetch(`/tasks/${encodeURIComponent(taskId)}`, {}, version);
                    const data = await res.json();
                    if (isStale(version)) return;
                    if (!res.ok) {
                        throw new Error((data && data.detail) ? String(data.detail) : `Failed to load task (HTTP ${res.status})`);
                    }
                    const t = data.task;
                    currentEditTaskId = t.id;

                    // Protected (read-only)
                    _setText('editTaskIdRO', t.id);
                    _setText('editTaskUserIdRO', t.user_id);
                    _setText('editTaskSourceRO', `${t.source_type || ''}${t.source_id ? ' · ' + t.source_id : ''}`);
                    _setText('editTaskCreatedAtRO', t.created_at ? formatDateTimeInTz(t.created_at) : '');
                    _setText('editTaskUpdatedAtRO', t.updated_at ? formatDateTimeInTz(t.updated_at) : '');
                    _setText('editTaskRecurrenceRO', `${t.recurrence_series_id || ''}${t.recurrence_occurrence_start ? ' · ' + t.recurrence_occurrence_start : ''}`);
                    _setText('editTaskAiExcludedRO', t.ai_excluded ? 'true' : 'false');

                    // Editable
                    _setVal('editTaskTitle', t.title || '');
                    _setVal('editTaskNotes', t.notes || '');
                    _setVal('editTaskStatus', t.status || 'open');
                    _setVal('editTaskDuration', t.estimated_duration_min || 30);
                    _setVal('editTaskCategory', t.category || 'unknown');
                    _setVal('editTaskEnergy', t.energy_intensity || 'medium');
                    _setVal('editTaskRisk', t.risk_score != null ? t.risk_score : '');
                    _setVal('editTaskImpact', t.impact_score != null ? t.impact_score : '');
                    _setVal('editTaskDependencies', Array.isArray(t.dependencies) ? t.dependencies.join(', ') : '');
                    _setVal('editTaskStartAfter', t.start_after || '');
                    _setVal('editTaskDueBy', t.due_by || '');

                    status.innerHTML = 'Task loaded.';
                } catch (e) {
                    if (!isStale(version)) {
                        status.innerHTML = 'Error: ' + (e && e.message ? e.message : String(e));
                    }
                }
            }

            function applyTaskRowHighlight(taskId) {
                const rows = document.querySelectorAll('tr.task-row');
                rows.forEach((r) => {
                    const rid = r.getAttribute('data-task-id');
                    if (rid && rid === taskId) r.classList.add('highlighted');
                    else r.classList.remove('highlighted');
                });
            }

            async function highlightTask(taskId) {
                highlightedTaskId = taskId;
                _setVal('editTaskId', taskId);
                applyTaskRowHighlight(taskId);
                try { await loadTaskForEdit(); } catch (_) { /* ignore */ }
                refreshScheduleView();
                // Scroll editor into view (best-effort)
                try {
                    const panel = document.getElementById('taskEditorPanel');
                    if (panel) panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                } catch (_) { /* ignore */ }
            }

            async function saveTaskEdits() {
                const version = authVersion;
                const status = document.getElementById('status');
                if (!currentEditTaskId) {
                    status.innerHTML = 'Error: load a task first.';
                    return;
                }
                status.innerHTML = 'Saving task...';
                try {
                    const payload = {
                        title: _getVal('editTaskTitle'),
                        notes: _getVal('editTaskNotes') || null,
                        status: _getVal('editTaskStatus') || null,
                        estimated_duration_min: parseInt(_getVal('editTaskDuration') || '30', 10),
                        category: _getVal('editTaskCategory') || null,
                        energy_intensity: _getVal('editTaskEnergy') || null,
                        risk_score: (_getVal('editTaskRisk') === '') ? null : parseFloat(_getVal('editTaskRisk')),
                        impact_score: (_getVal('editTaskImpact') === '') ? null : parseFloat(_getVal('editTaskImpact')),
                        dependencies: (_getVal('editTaskDependencies') || '').split(',').map(s => s.trim()).filter(Boolean),
                        start_after: _getVal('editTaskStartAfter') || null,
                        due_by: _getVal('editTaskDueBy') || null,
                    };

                    const res = await apiFetch(`/tasks/${encodeURIComponent(currentEditTaskId)}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
                    }, version);
                    const data = await res.json();
                    if (isStale(version)) return;
                    if (!res.ok) {
                        throw new Error((data && data.detail) ? String(data.detail) : `Failed to save task (HTTP ${res.status})`);
                    }
                    status.innerHTML = 'Task saved.';
                    await viewTasks(version);
                    // Reload to refresh protected/derived fields (e.g., ai_excluded).
                    _setVal('editTaskId', currentEditTaskId);
                    await loadTaskForEdit();
                } catch (e) {
                    if (!isStale(version)) {
                        status.innerHTML = 'Error: ' + (e && e.message ? e.message : String(e));
                    }
                }
            }

            let selectedTaskIds = new Set();
            let lastRenderedTaskIds = [];

            function updateTaskSelectionUi() {
                const selectAll = document.getElementById('selectAllTasks');
                if (selectAll) {
                    const total = lastRenderedTaskIds.length;
                    const selected = selectedTaskIds.size;
                    selectAll.checked = total > 0 && selected === total;
                    selectAll.indeterminate = selected > 0 && selected < total;
                }
            }

            function toggleTaskSelection(taskId, checked) {
                if (checked) selectedTaskIds.add(taskId);
                else selectedTaskIds.delete(taskId);
                updateTaskSelectionUi();
                refreshScheduleView();
            }

            function toggleSelectAllTasks(checked) {
                if (checked) {
                    lastRenderedTaskIds.forEach(id => selectedTaskIds.add(id));
                } else {
                    lastRenderedTaskIds.forEach(id => selectedTaskIds.delete(id));
                }
                // Update visible checkboxes without refetching
                const boxes = document.querySelectorAll('input.task-select');
                boxes.forEach(b => { b.checked = checked; });
                updateTaskSelectionUi();
                refreshScheduleView();
            }

            async function deleteSelectedTasks() {
                const version = authVersion;
                const status = document.getElementById('status');
                const ids = Array.from(selectedTaskIds);
                if (ids.length === 0) {
                    status.innerHTML = 'No tasks selected.';
                    return;
                }
                if (!confirm(`Delete ${ids.length} selected task(s)? (Undoable via restore endpoint)`)) return;
                try {
                    status.innerHTML = 'Deleting selected tasks...';
                    const response = await apiFetch('/tasks/bulk_delete', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ task_ids: ids }),
                    }, version);
                    const data = await response.json();
                    if (isStale(version)) return;
                    selectedTaskIds.clear();
                    status.innerHTML = `Deleted ${data.affected_count} task(s).` + (data.not_found_ids && data.not_found_ids.length ? ` Not found: ${data.not_found_ids.length}.` : '');
                    await viewTasks(version);
                } catch (e) {
                    if (!isStale(version)) status.innerHTML = 'Error: ' + (e && e.message ? e.message : String(e));
                }
            }

            async function purgeSelectedTasks() {
                const version = authVersion;
                const status = document.getElementById('status');
                const ids = Array.from(selectedTaskIds);
                if (ids.length === 0) {
                    status.innerHTML = 'No tasks selected.';
                    return;
                }
                if (!confirm(`Purge ${ids.length} selected task(s)? This is irreversible.`)) return;
                try {
                    status.innerHTML = 'Purging selected tasks...';
                    const response = await apiFetch('/tasks/bulk_purge', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ task_ids: ids }),
                    }, version);
                    const data = await response.json();
                    if (isStale(version)) return;
                    selectedTaskIds.clear();
                    status.innerHTML = `Purged ${data.affected_count} task(s).` + (data.not_found_ids && data.not_found_ids.length ? ` Not found: ${data.not_found_ids.length}.` : '');
                    await viewTasks(version);
                } catch (e) {
                    if (!isStale(version)) status.innerHTML = 'Error: ' + (e && e.message ? e.message : String(e));
                }
            }
            
            function _filterScheduleBlocksForHighlightedTask(blocks) {
                if (!highlightedTaskId) return [];
                const taskBlocks = (blocks || []).filter(b => b.entity_type === 'task' && b.entity_id === highlightedTaskId);
                if (taskBlocks.length === 0) return [];

                const toMs = (iso) => {
                    try { return new Date(iso).getTime(); } catch (_) { return NaN; }
                };
                const taskStarts = new Set(taskBlocks.map(b => toMs(b.start_time)));
                const taskEnds = new Set(taskBlocks.map(b => toMs(b.end_time)));

                const adjacentTransitions = (blocks || []).filter((b) => {
                    if (b.entity_type !== 'transition') return false;
                    const s = toMs(b.start_time);
                    const e = toMs(b.end_time);
                    // Transition ends at task start OR starts at task end
                    return taskStarts.has(e) || taskEnds.has(s);
                });

                const keep = new Map();
                [...taskBlocks, ...adjacentTransitions].forEach(b => keep.set(b.id, b));
                return Array.from(keep.values()).sort((a, b) => new Date(a.start_time) - new Date(b.start_time));
            }

            function renderSchedule(data) {
                const scheduleDiv = document.getElementById('schedule');
                const filterInfo = document.getElementById('scheduleFilterInfo');
                if (!scheduleDiv) return;

                const selectAll = document.getElementById('selectAllTasks');
                const showAll = !!(selectAll && selectAll.checked);

                const tz = (data && data.time_zone) ? String(data.time_zone) : null;
                if (tz) {
                    lastScheduleTimeZone = tz;
                    try { if (window.localStorage) window.localStorage.setItem('qz_calendar_time_zone', tz); } catch (_) { /* ignore */ }
                }

                if (!data || !Array.isArray(data.scheduled_blocks)) {
                    scheduleDiv.innerHTML = '<p>Unexpected response from /schedule</p>';
                    if (filterInfo) filterInfo.textContent = '';
                    return;
                }

                const allBlocks = data.scheduled_blocks || [];
                let blocksToRender = [];

                if (showAll) {
                    blocksToRender = allBlocks;
                    if (filterInfo) filterInfo.textContent = `Showing all schedule blocks (Select all enabled). Timezone: ${getUiTimeZone()}`;
                } else if (highlightedTaskId) {
                    blocksToRender = _filterScheduleBlocksForHighlightedTask(allBlocks);
                    const title = (data.task_titles && data.task_titles[highlightedTaskId]) ? data.task_titles[highlightedTaskId] : highlightedTaskId;
                    if (filterInfo) filterInfo.textContent = `Showing schedule blocks for highlighted task: ${title}. Timezone: ${getUiTimeZone()}`;
                } else {
                    if (filterInfo) filterInfo.textContent = `Click a task to see its schedule blocks. Timezone: ${getUiTimeZone()}`;
                    scheduleDiv.innerHTML = '<p>No task selected. Click a task to see its scheduled blocks.</p>';
                    return;
                }

                if (blocksToRender.length === 0) {
                    scheduleDiv.innerHTML = '<p>No schedule blocks for this selection. Build a schedule first, or pick a different task.</p>';
                    return;
                }

                let html = '<table><tr><th>Start</th><th>End</th><th>Task</th><th>Freeze</th></tr>';
                blocksToRender.forEach(block => {
                    let taskName = 'Unknown';
                    if (block.entity_type === 'task' && data.task_titles && data.task_titles[block.entity_id]) {
                        taskName = data.task_titles[block.entity_id];
                    } else if (block.entity_type === 'transition') {
                        taskName = 'Transition';
                    } else {
                        taskName = block.entity_id;
                    }
                    const checked = block.locked ? 'checked' : '';
                    html += `<tr>
                        <td>${formatDateTimeInTz(block.start_time)}</td>
                        <td>${formatDateTimeInTz(block.end_time)}</td>
                        <td>${taskName}</td>
                        <td><input type="checkbox" ${checked} onchange="toggleFreeze('${block.id}', this.checked)"></td>
                    </tr>`;
                });
                html += '</table>';

                // Only show overflow in "all blocks" mode to avoid confusion when filtered.
                if (showAll && data.overflow_tasks && data.overflow_tasks.length > 0) {
                    html += `<p><strong>Overflow tasks (${data.overflow_tasks.length}):</strong></p><ul>`;
                    data.overflow_tasks.forEach(task => { html += `<li>${task.title}</li>`; });
                    html += '</ul>';
                }

                scheduleDiv.innerHTML = html;
            }

            function refreshScheduleView() {
                if (lastScheduleData) {
                    renderSchedule(lastScheduleData);
                }
            }

            async function viewSchedule(version = authVersion) {
                const scheduleDiv = document.getElementById('schedule');
                try {
                    const response = await apiFetch('/schedule', {}, version);
                    const data = await response.json();
                    if (isStale(version)) return;

                    lastScheduleData = data;
                    renderSchedule(data);
                } catch (error) {
                    if (isStale(version)) return;
                    // Treat "no schedule" as a normal empty state, not an error.
                    const msg = error && error.message ? String(error.message) : String(error);
                    if (msg && msg.toLowerCase().includes('no schedule available')) {
                        scheduleDiv.innerHTML = '<p>No schedule available. Build a schedule first.</p>';
                        return;
                    }
                    scheduleDiv.innerHTML = 'Error: ' + msg;
                }
            }

            async function toggleFreeze(blockId, checked) {
                const version = authVersion;
                const status = document.getElementById('status');
                try {
                    status.innerHTML = checked ? 'Freezing block...' : 'Unfreezing block...';
                    const path = checked ? `/schedule/blocks/${blockId}/lock` : `/schedule/blocks/${blockId}/unlock`;
                    const response = await apiFetch(path, { method: 'POST' }, version);
                    let data = null;
                    try { data = await response.json(); } catch (e) { /* ignore */ }
                    if (!response.ok) {
                        const detail = (data && data.detail) ? String(data.detail) : `Failed (HTTP ${response.status})`;
                        throw new Error(detail);
                    }
                    if (isStale(version)) return;
                    status.innerHTML = checked ? 'Block frozen.' : 'Block unfrozen.';
                    await viewSchedule(version);
                } catch (e) {
                    if (!isStale(version)) status.innerHTML = 'Error: ' + (e && e.message ? e.message : String(e));
                    // Refresh schedule to revert UI checkbox to server state.
                    try { await viewSchedule(version); } catch (_) { /* ignore */ }
                }
            }
            
            // Load tasks on page load
            window.onload = async function() {
                await initGoogleSignIn();
                // initGoogleSignIn() calls syncSessionOnLoad() when a token exists.
                // If not signed in, it will show signed-out UI.
            };
        </script>
    </body>
    </html>
    """


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "version": "0.1.0"}


@app.get("/favicon.ico")
async def favicon():
    """Handle favicon requests to prevent 404 errors."""
    return Response(status_code=204)  # No Content


# Frontend config (safe to expose)
@app.get("/auth/config")
async def auth_config():
    """Return public auth configuration needed by the browser UI."""
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    # Unified consent requires the server to be able to exchange auth codes and store refresh tokens.
    unified_enabled = bool(
        client_id
        and os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
        and os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
    )
    return {
        "google_oauth_client_id": client_id,
        "google_unified_oauth_enabled": unified_enabled,
    }


# Authentication endpoints
@app.post("/auth/google/callback", response_model=AuthResponse)
async def google_oauth_callback(
    request: GoogleOAuthCallbackRequest,
    db: Session = Depends(get_db)
):
    """Handle Google OAuth callback and create/login user.
    
    Expected request body:
    {
        "id_token": "Google ID token from OAuth flow"
    }
    
    Returns JWT token for authenticated user.
    """
    # Verify Google token and get user info
    user_info = verify_google_token(request.id_token)
    if not user_info:
        raise HTTPException(status_code=401, detail="Invalid Google token")
    
    if not user_info.get('email'):
        raise HTTPException(status_code=400, detail="Email is required")
    
    # Create or update user in database
    user_repo = UserRepository(db)
    now = datetime.utcnow()
    user = User(
        id=user_info['id'],
        email=user_info['email'],
        name=user_info.get('name'),
        created_at=now,
        updated_at=now,
    )
    
    try:
        user = user_repo.create_or_update(user)
    except Exception as e:
        logger.error(f"Failed to create/update user: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create/update user")

    # Legacy DB compatibility: if tasks were created before multi-user support,
    # they may have NULL user_id. Claim unowned tasks for this user so they
    # remain visible after login.
    try:
        db.execute(
            text("UPDATE tasks SET user_id = :uid WHERE user_id IS NULL OR user_id = ''"),
            {"uid": user.id},
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"Failed to claim legacy tasks for user {user.id}: {type(e).__name__}: {str(e)}")
    
    # Generate JWT token
    token = create_access_token(user.id)
    
    return AuthResponse(
        access_token=token,
        token_type="bearer",
        user=user.model_dump()
    )


@app.post("/auth/google/code-exchange", response_model=AuthResponse)
async def google_oauth_code_exchange(
    request: Request,
    payload: GoogleOAuthCodeExchangeRequest,
    db: Session = Depends(get_db),
):
    """Exchange a Google OAuth authorization code for tokens, then login the user.

    This endpoint supports a unified web flow where the browser obtains an OAuth
    authorization code (GIS code client) for both identity scopes and Calendar,
    and the backend exchanges it for:
    - id_token (identity, verified)
    - refresh_token (stored encrypted for Calendar sync)
    - access_token / expiry (optional, stored encrypted)
    """
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Google OAuth client is not configured")

    # Basic CSRF mitigation for popup code model:
    # the browser must set X-Requested-With and same-origin requests will include Origin.
    xrw = (request.headers.get("x-requested-with") or "").strip()
    if xrw.lower() != "xmlhttprequest":
        raise HTTPException(status_code=400, detail="Missing CSRF header")

    origin = (request.headers.get("origin") or "").strip()
    if origin:
        redirect_uri = origin.rstrip("/")
    else:
        # Test clients or unusual environments may omit Origin; fall back to request base URL.
        redirect_uri = str(request.base_url).rstrip("/")

    token_url = "https://oauth2.googleapis.com/token"
    token_resp = requests.post(
        token_url,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": payload.code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        timeout=15,
    )

    try:
        token_data = token_resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to parse Google token response")

    if not token_resp.ok:
        err = token_data.get("error_description") or token_data.get("error") or "Google token exchange failed"
        raise HTTPException(status_code=502, detail=str(err))

    id_token_str = token_data.get("id_token")
    if not id_token_str:
        raise HTTPException(status_code=502, detail="Google did not return an id_token for login")

    # Verify identity
    user_info = verify_google_token(str(id_token_str))
    if not user_info:
        raise HTTPException(status_code=401, detail="Invalid Google token")
    if not user_info.get("email"):
        raise HTTPException(status_code=400, detail="Email is required")

    # Create/update user in DB
    user_repo = UserRepository(db)
    now = datetime.utcnow()
    user = User(
        id=user_info["id"],
        email=user_info["email"],
        name=user_info.get("name"),
        created_at=now,
        updated_at=now,
    )
    try:
        user = user_repo.create_or_update(user)
    except Exception as e:
        logger.error(f"Failed to create/update user: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create/update user")

    # Legacy DB compatibility: claim unowned tasks for this user so they remain visible after login.
    try:
        db.execute(
            text("UPDATE tasks SET user_id = :uid WHERE user_id IS NULL OR user_id = ''"),
            {"uid": user.id},
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"Failed to claim legacy tasks for user {user.id}: {type(e).__name__}: {str(e)}")

    # Store Calendar refresh token (encrypted) for unified consent.
    refresh_token = token_data.get("refresh_token")
    access_token = token_data.get("access_token")
    expires_in = token_data.get("expires_in")
    scope_str = token_data.get("scope") or ""
    scopes = [s for s in str(scope_str).split() if s] or ["https://www.googleapis.com/auth/calendar"]

    expiry = None
    if isinstance(expires_in, (int, float)):
        expiry = datetime.utcnow() + timedelta(seconds=int(expires_in))

    token_repo = GoogleOAuthTokenRepository(db)
    if not refresh_token:
        # Google may omit refresh_token on subsequent grants.
        existing = token_repo.get_google_calendar(user.id)
        if not existing:
            raise HTTPException(
                status_code=400,
                detail="Google did not return a refresh token. Please revoke app access in your Google Account and try again.",
            )
        # Keep existing refresh token only if it is still valid (not revoked).
        try:
            existing_refresh = decrypt_secret(existing.refresh_token_encrypted)
            test_creds = GoogleCredentials(
                token=None,
                refresh_token=existing_refresh,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=client_id,
                client_secret=client_secret,
                scopes=scopes,
            )
            test_creds.refresh(GoogleAuthRequest())
        except Exception:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Google did not return a refresh token, and your existing Calendar authorization is no longer valid. "
                    "Please revoke qzWhatNext access in your Google Account (Security → Third-party access) and try again."
                ),
            )
        # Re-upsert to update scopes/access token/expiry and re-encrypt deterministically under current key.
        token_repo.upsert_google_calendar(
            user_id=user.id,
            refresh_token=str(existing_refresh),
            scopes=scopes,
            access_token=str(access_token) if access_token else None,
            expiry=expiry,
        )
    else:
        token_repo.upsert_google_calendar(
            user_id=user.id,
            refresh_token=str(refresh_token),
            scopes=scopes,
            access_token=str(access_token) if access_token else None,
            expiry=expiry,
        )

    # Issue qzWhatNext JWT
    token = create_access_token(user.id)
    return AuthResponse(access_token=token, token_type="bearer", user=user.model_dump())


@app.get("/auth/me")
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get current authenticated user information."""
    return {"user": current_user.model_dump()}


@app.get("/auth/google/calendar/start")
async def google_calendar_oauth_start(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Start per-user Google Calendar OAuth (authorization code flow).

    This is required for deployed environments (Cloud Run); do not use server-local OAuth flows.
    """
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Google OAuth client is not configured")

    redirect_uri = _public_url_for(request, "google_calendar_oauth_callback")
    state = _encode_calendar_oauth_state(current_user.id)

    auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/calendar",
        "access_type": "offline",
        # Force account chooser + consent so Google reliably returns a refresh_token on reconnect.
        "prompt": "consent select_account",
        "include_granted_scopes": "true",
        "state": state,
    }

    return RedirectResponse(url=f"{auth_url}?{urlencode(params)}", status_code=302)


@app.get("/auth/google/calendar/auth-url")
async def google_calendar_oauth_auth_url(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Return the Google consent URL for Calendar connect (JSON).

    This exists because browser popups can't attach Authorization headers to server routes.
    The UI fetches this URL (with JWT) then opens the returned Google URL in a popup.
    """
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Google OAuth client is not configured")

    redirect_uri = _public_url_for(request, "google_calendar_oauth_callback")
    state = _encode_calendar_oauth_state(current_user.id)

    auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/calendar",
        "access_type": "offline",
        # Force account chooser + consent so Google reliably returns a refresh_token on reconnect.
        "prompt": "consent select_account",
        "include_granted_scopes": "true",
        "state": state,
    }
    return {"url": f"{auth_url}?{urlencode(params)}"}


@app.get("/auth/google/calendar/callback", name="google_calendar_oauth_callback")
async def google_calendar_oauth_callback(
    request: Request,
    code: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
    error_description: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """OAuth callback that exchanges code for tokens and stores refresh token encrypted."""
    if error:
        msg = error_description or error
        return HTMLResponse(
            f"""<!doctype html>
<html><body>
<h3>Google Calendar connection failed</h3>
<p>{msg}</p>
</body></html>""",
            status_code=400,
        )

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing OAuth code/state")

    user_id = _decode_calendar_oauth_state(state)

    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Google OAuth client is not configured")

    redirect_uri = _public_url_for(request, "google_calendar_oauth_callback")

    token_url = "https://oauth2.googleapis.com/token"
    token_resp = requests.post(
        token_url,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        timeout=15,
    )

    try:
        token_data = token_resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to parse Google token response")

    if not token_resp.ok:
        err = token_data.get("error_description") or token_data.get("error") or "Google token exchange failed"
        raise HTTPException(status_code=502, detail=str(err))

    refresh_token = token_data.get("refresh_token")
    access_token = token_data.get("access_token")
    expires_in = token_data.get("expires_in")
    scope_str = token_data.get("scope") or ""
    scopes = [s for s in scope_str.split() if s] or ["https://www.googleapis.com/auth/calendar"]

    repo = GoogleOAuthTokenRepository(db)
    if not refresh_token:
        # Google may omit refresh_token on subsequent grants.
        existing = repo.get_google_calendar(user_id)
        if not existing:
            raise HTTPException(
                status_code=400,
                detail="Google did not return a refresh token. Please revoke app access in your Google Account and try again.",
            )
        # Keep existing refresh token only if it is still valid (not revoked).
        try:
            existing_refresh = decrypt_secret(existing.refresh_token_encrypted)
            test_creds = GoogleCredentials(
                token=None,
                refresh_token=existing_refresh,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=client_id,
                client_secret=client_secret,
                scopes=scopes,
            )
            test_creds.refresh(GoogleAuthRequest())
        except Exception:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Google did not return a refresh token, and your existing Calendar authorization is no longer valid. "
                    "Please revoke qzWhatNext access in your Google Account (Security → Third-party access) and try again."
                ),
            )
        html = """<!doctype html>
<html><body>
<script>
  (function () {
    try { if (window.opener) window.opener.postMessage({type: 'qz_google_calendar_connected'}, '*'); } catch (e) {}
    try { window.close(); } catch (e) {}
  })();
</script>
<p>Google Calendar is already connected. You can close this window.</p>
</body></html>"""
        return HTMLResponse(html, status_code=200)

    expiry = None
    if isinstance(expires_in, (int, float)):
        expiry = datetime.utcnow() + timedelta(seconds=int(expires_in))

    repo.upsert_google_calendar(
        user_id=user_id,
        refresh_token=str(refresh_token),
        scopes=scopes,
        access_token=str(access_token) if access_token else None,
        expiry=expiry,
    )

    html = """<!doctype html>
<html><body>
<script>
  (function () {
    try { if (window.opener) window.opener.postMessage({type: 'qz_google_calendar_connected'}, '*'); } catch (e) {}
    try { window.close(); } catch (e) {}
  })();
</script>
<p>Google Calendar connected. You can close this window.</p>
</body></html>"""
    return HTMLResponse(html, status_code=200)


@app.get("/auth/shortcut-token", response_model=ShortcutTokenStatusResponse)
async def get_shortcut_token_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get shortcut token status for the current user (does not reveal the token)."""
    token_db = (
        db.query(ApiTokenDB)
        .filter(ApiTokenDB.user_id == current_user.id, ApiTokenDB.revoked_at.is_(None))
        .order_by(ApiTokenDB.created_at.desc())
        .first()
    )
    if not token_db:
        return ShortcutTokenStatusResponse(active=False)
    return ShortcutTokenStatusResponse(
        active=True,
        token_prefix=token_db.token_prefix,
        created_at=token_db.created_at,
        last_used_at=token_db.last_used_at,
    )


@app.post("/auth/shortcut-token", response_model=ShortcutTokenCreateResponse)
async def create_shortcut_token(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create (or rotate) a shortcut token for the current user.

    The raw token is returned ONCE. Store it in your iOS Shortcut.
    """
    # Revoke any existing active tokens for this user (single active token policy).
    now = datetime.utcnow()
    db.query(ApiTokenDB).filter(
        ApiTokenDB.user_id == current_user.id,
        ApiTokenDB.revoked_at.is_(None),
    ).update({"revoked_at": now})
    db.commit()

    token = generate_shortcut_token()
    token_prefix = token[:6]
    token_hash = hash_shortcut_token(token)

    token_db = ApiTokenDB(
        user_id=current_user.id,
        token_hash=token_hash,
        token_prefix=token_prefix,
        name="ios_shortcut",
        created_at=now,
    )
    db.add(token_db)
    db.commit()

    return ShortcutTokenCreateResponse(token=token, token_prefix=token_prefix, created_at=now)


@app.delete("/auth/shortcut-token", status_code=204)
async def revoke_shortcut_token(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke the current user's active shortcut token(s)."""
    now = datetime.utcnow()
    db.query(ApiTokenDB).filter(
        ApiTokenDB.user_id == current_user.id,
        ApiTokenDB.revoked_at.is_(None),
    ).update({"revoked_at": now})
    db.commit()
    return Response(status_code=204)


# Single-input capture endpoint (recurring tasks + time blocks)
@app.post("/capture", response_model=CaptureResponse)
async def capture(
    request: CaptureRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Capture a natural language instruction and create/update the right entity.

    Phase 1: create-only.
    Phase 2: updates supported when entity_id is provided.
    """
    now = datetime.utcnow()
    instruction = request.instruction or ""

    # AI parsing is allowed only when not AI-excluded by prefix.
    ai_allowed = not instruction.strip().startswith(".")
    try:
        parsed = interpret_capture_instruction(instruction, ai_allowed=ai_allowed, now=now)
    except RecurrenceParseError as e:
        raise HTTPException(status_code=400, detail=str(e))

    preset_json = parsed.preset.model_dump(mode="json") if parsed.preset is not None else None

    def _next_date_for_weekly_start(d: date, by_weekday: list, *, max_days: int = 14) -> date:
        """Pick the next date on/after d matching by_weekday (Weekday enums)."""
        if not by_weekday:
            return d
        # Map Weekday enum values to Python weekday numbers.
        # Weekday values are like 'mo','tu'...
        wd_map = {"mo": 0, "tu": 1, "we": 2, "th": 3, "fr": 4, "sa": 5, "su": 6}
        targets = {wd_map.get(getattr(w, "value", str(w)).lower()) for w in by_weekday}
        targets.discard(None)
        if not targets:
            return d
        cur = d
        for _ in range(max_days):
            if cur.weekday() in targets:
                return cur
            cur = cur + timedelta(days=1)
        return d

    # Helper: get calendar client (used for time blocks)
    def _calendar_client_or_400() -> GoogleCalendarClient:
        token_repo = GoogleOAuthTokenRepository(db)
        token_row = token_repo.get_google_calendar(current_user.id)
        if not token_row:
            raise HTTPException(
                status_code=400,
                detail="Google Calendar not connected. Connect via /auth/google/calendar/auth-url (or click Sync in the UI).",
            )
        client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            raise HTTPException(status_code=500, detail="Google OAuth client is not configured")

        refresh_token = decrypt_secret(token_row.refresh_token_encrypted)
        scopes = token_row.scopes or ["https://www.googleapis.com/auth/calendar"]
        creds = GoogleCredentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes,
        )
        try:
            creds.refresh(GoogleAuthRequest())
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail="Google Calendar authorization expired or was revoked. Reconnect via /auth/google/calendar/auth-url.",
            )
        return GoogleCalendarClient(credentials=creds, calendar_id="primary")

    # Update flow (Phase 2)
    if request.entity_id:
        if parsed.entity_kind in ("task", "calendar_event"):
            raise HTTPException(
                status_code=400,
                detail="One-off instructions cannot update an existing entity. Use 'every ...' for repeating items.",
            )
        series_repo = RecurringTaskSeriesRepository(db)
        time_block_repo = RecurringTimeBlockRepository(db)

        series = series_repo.get(current_user.id, request.entity_id)
        if series is not None:
            if parsed.entity_kind != "task_series":
                raise HTTPException(status_code=400, detail="Instruction does not describe a recurring task series")
            updated = series_repo.update_from_instruction(
                current_user.id,
                request.entity_id,
                title_template=parsed.title,
                recurrence_preset=preset_json,
            )
            if updated is None:
                raise HTTPException(status_code=404, detail="Recurring task series not found")
            return CaptureResponse(action="updated", entity_kind="task_series", entity_id=updated.id)

        tb = time_block_repo.get(current_user.id, request.entity_id)
        if tb is not None:
            if parsed.entity_kind != "time_block":
                raise HTTPException(status_code=400, detail="Instruction does not describe a recurring time block")
            calendar_client = _calendar_client_or_400()
            tz = calendar_client.get_calendar_timezone()

            if parsed.preset.time_start is None or parsed.preset.time_end is None:
                raise HTTPException(status_code=400, detail="Time block requires start and end times")

            start_date = parsed.preset.start_date or now.date()
            if parsed.preset.frequency == "weekly" and parsed.preset.by_weekday:
                start_date = _next_date_for_weekly_start(start_date, parsed.preset.by_weekday)
            start_dt = datetime.combine(start_date, parsed.preset.time_start)
            end_dt = datetime.combine(start_date, parsed.preset.time_end)
            if parsed.preset.time_end <= parsed.preset.time_start:
                end_dt = end_dt + timedelta(days=1)

            rrule = preset_to_rrule(parsed.preset)
            desired = {
                "summary": parsed.title,
                "description": "",
                "start": {"dateTime": start_dt.isoformat(), "timeZone": tz},
                "end": {"dateTime": end_dt.isoformat(), "timeZone": tz},
                "recurrence": [f"RRULE:{rrule}"],
                "extendedProperties": {"private": {PRIVATE_KEY_TIME_BLOCK_ID: tb.id}},
            }

            event_id = tb.calendar_event_id
            if event_id:
                calendar_client.patch_event(event_id, desired)
            else:
                created = calendar_client.create_recurring_time_block_event(
                    title=parsed.title,
                    description="",
                    start_dt_iso=start_dt.isoformat(),
                    end_dt_iso=end_dt.isoformat(),
                    time_zone=tz,
                    rrule=rrule,
                    time_block_id=tb.id,
                )
                event_id = created.get("id")

            updated = time_block_repo.update_from_instruction(
                current_user.id,
                tb.id,
                title=parsed.title,
                recurrence_preset=preset_json,
                calendar_event_id=event_id,
            )
            if updated is None:
                raise HTTPException(status_code=404, detail="Recurring time block not found")
            return CaptureResponse(
                action="updated",
                entity_kind="time_block",
                entity_id=updated.id,
                calendar_event_id=updated.calendar_event_id,
            )

        raise HTTPException(status_code=404, detail="Entity not found for update")

    # Create flow (Phase 1)
    if parsed.entity_kind == "task":
        repo = TaskRepository(db)
        task = create_task_base(
            user_id=current_user.id,
            source_type="api",
            source_id=None,
            title=parsed.title,
            notes=None,
            start_after=getattr(parsed, "start_after", None),
            due_by=getattr(parsed, "due_by", None),
            ai_excluded=parsed.ai_excluded,
        )
        created_task = repo.create(task)
        return CaptureResponse(action="created", entity_kind="task", entity_id=created_task.id, tasks_created=1)

    if parsed.entity_kind == "task_series":
        series_repo = RecurringTaskSeriesRepository(db)
        # Deterministic defaults for common quick health habits.
        # These defaults matter because tiering is deterministic and recurrence tasks may have tight windows.
        title_lc = (parsed.title or "").lower()
        is_vitamins = ("vitamin" in title_lc) or ("vitamins" in title_lc)
        is_meds = ("med" in title_lc) or ("medicine" in title_lc) or ("meds" in title_lc)
        default_category = TaskCategory.HEALTH.value if (is_vitamins or is_meds) else TaskCategory.UNKNOWN.value
        default_duration = 5 if (is_vitamins or is_meds) else 30
        created_series = series_repo.create(
            user_id=current_user.id,
            title_template=parsed.title,
            notes_template=None,
            estimated_duration_min_default=default_duration,
            category_default=default_category,
            recurrence_preset=preset_json,
            ai_excluded=parsed.ai_excluded,
        )
        # Materialize into task instances inside the current scheduling horizon (7 days for now).
        tasks_created = materialize_recurring_tasks(
            db,
            user_id=current_user.id,
            window_start=now,
            window_end=now + timedelta(days=7),
        )
        return CaptureResponse(
            action="created",
            entity_kind="task_series",
            entity_id=created_series.id,
            tasks_created=tasks_created,
        )

    if parsed.entity_kind == "calendar_event":
        calendar_client = _calendar_client_or_400()
        tz = calendar_client.get_calendar_timezone()
        if parsed.one_off_date is None or parsed.one_off_time_start is None or parsed.one_off_time_end is None:
            raise HTTPException(status_code=400, detail="One-off calendar event requires date, start, and end times")

        start_dt = datetime.combine(parsed.one_off_date, parsed.one_off_time_start)
        end_dt = datetime.combine(parsed.one_off_date, parsed.one_off_time_end)
        if parsed.one_off_time_end <= parsed.one_off_time_start:
            end_dt = end_dt + timedelta(days=1)

        created = calendar_client.create_time_block_event(
            title=parsed.title,
            description="",
            start_dt_iso=start_dt.isoformat(),
            end_dt_iso=end_dt.isoformat(),
            time_zone=tz,
        )
        event_id = (created or {}).get("id")
        if not event_id:
            raise HTTPException(status_code=500, detail="Failed to create calendar event")

        return CaptureResponse(
            action="created",
            entity_kind="calendar_event",
            entity_id=event_id,
            calendar_event_id=event_id,
        )

    # time_block (recurring)
    calendar_client = _calendar_client_or_400()
    tz = calendar_client.get_calendar_timezone()
    if parsed.preset.time_start is None or parsed.preset.time_end is None:
        raise HTTPException(status_code=400, detail="Time block requires start and end times")

    start_date = parsed.preset.start_date or now.date()
    if parsed.preset.frequency == "weekly" and parsed.preset.by_weekday:
        start_date = _next_date_for_weekly_start(start_date, parsed.preset.by_weekday)
    start_dt = datetime.combine(start_date, parsed.preset.time_start)
    end_dt = datetime.combine(start_date, parsed.preset.time_end)
    if parsed.preset.time_end <= parsed.preset.time_start:
        end_dt = end_dt + timedelta(days=1)

    time_block_repo = RecurringTimeBlockRepository(db)
    block_id = str(uuid.uuid4())
    rrule = preset_to_rrule(parsed.preset)
    created_event = calendar_client.create_recurring_time_block_event(
        title=parsed.title,
        description="",
        start_dt_iso=start_dt.isoformat(),
        end_dt_iso=end_dt.isoformat(),
        time_zone=tz,
        rrule=rrule,
        time_block_id=block_id,
    )
    event_id = created_event.get("id")
    row = time_block_repo.create(
        block_id=block_id,
        user_id=current_user.id,
        title=parsed.title,
        recurrence_preset=preset_json,
        calendar_event_id=event_id,
    )
    return CaptureResponse(
        action="created",
        entity_kind="time_block",
        entity_id=row.id,
        calendar_event_id=row.calendar_event_id,
    )


# Task CRUD endpoints
@app.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(
    request: TaskCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new task."""
    repo = TaskRepository(db)
    
    # Check for duplicates if source_id is provided
    if request.source_id:
        duplicates = repo.find_duplicates(current_user.id, request.source_type, request.source_id, request.title)
        if duplicates:
            # For MVP, we just log but still create (no auto-dedupe)
            logger.warning(
                f"Potential duplicate task detected: source_type={request.source_type}, "
                f"source_id={request.source_id}, title={request.title[:50]}, "
                f"found {len(duplicates)} existing task(s)"
            )
    
    # Create task using factory (applies defaults from constants)
    task = create_task_base(
        user_id=current_user.id,
        source_type=request.source_type,
        source_id=request.source_id,
        title=request.title,
        notes=request.notes,
        deadline=request.deadline,
        start_after=request.start_after,
        due_by=request.due_by,
        estimated_duration_min=request.estimated_duration_min,
        category=request.category,
        ai_excluded=determine_ai_exclusion(request.title) if request.title else False,
    )
    
    try:
        created_task = repo.create(task)
        return TaskResponse(task=created_task)
    except Exception as e:
        logger.error(f"Failed to create task: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create task: {str(e)}")


@app.post("/tasks/add_smart", response_model=TaskResponse, status_code=201)
async def add_smart_task(
    request: TaskAddSmartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new task from iOS Shortcut with auto-generated title and category.
    
    This endpoint is designed for iOS Shortcuts integration. It accepts only
    a notes field and automatically generates:
    - Task title from notes using OpenAI API (or truncates notes as fallback)
    - Category from notes using OpenAI API (if not AI-excluded)
    
    If notes start with ".", the task is AI-excluded and uses fallback title generation.
    """
    
    repo = TaskRepository(db)
    
    # Check if notes starts with "." for AI exclusion
    ai_excluded = request.notes.startswith('.') if request.notes else False
    
    # Determine title: try AI generation if not excluded, otherwise use fallback
    task_title = ""
    notes = request.notes or ""
    
    # Generate title if not AI-excluded
    if not ai_excluded and notes.strip():
        # Create temporary task object for inference (minimal fields needed)
        # Use factory but override title to empty string to avoid AI exclusion check
        temp_task = create_task_base(
            user_id=current_user.id,
            source_type="api",
            source_id=None,
            title="",  # Empty title won't trigger AI exclusion check
            notes=notes,
            ai_excluded=False,  # We already checked this above
        )
        
        try:
            generated_title = generate_title(temp_task, max_length=100)
            if generated_title and generated_title.strip():
                task_title = generated_title.strip()
                logger.debug(f"Generated title for task: {task_title[:50]}...")
        except Exception as e:
            # Log error but don't fail task creation
            logger.error(f"Error generating title: {type(e).__name__}")
            # Fall through to fallback
    
    # Fallback: use first 100 characters of notes, or default if empty
    if not task_title:
        if notes.strip():
            task_title = notes[:100].strip()
            if len(notes) > 100:
                # Truncate at word boundary if possible
                truncated = task_title.rsplit(' ', 1)[0] if ' ' in task_title else task_title
                task_title = truncated if len(truncated) > 50 else task_title  # Keep at least 50 chars if possible
        else:
            task_title = "Untitled Task"
    
    # Create task with generated/fallback title using factory
    task = create_task_base(
        user_id=current_user.id,
        source_type="api",
        source_id=None,
        title=task_title,
        notes=request.notes,
        ai_excluded=ai_excluded,
    )
    
    # Infer category and duration if not AI-excluded
    if not ai_excluded:
        try:
            inferred_category, category_confidence = infer_category(task)
            # Update category if confidence meets threshold
            # (infer_category already applies threshold, so if it returns non-UNKNOWN, use it)
            if inferred_category != TaskCategory.UNKNOWN:
                task.category = inferred_category
                logger.debug(f"Task {task.id} category inferred as {inferred_category.value} with confidence {category_confidence}")
            else:
                logger.debug(f"Task {task.id} category inference returned UNKNOWN (confidence: {category_confidence})")
        except Exception as e:
            # Log error but don't fail task creation
            logger.error(f"Error inferring category for task {task.id}: {type(e).__name__}")
            # Continue with UNKNOWN category
        
        # Estimate duration
        try:
            estimated_duration, duration_confidence = estimate_duration(task)
            # Update duration if estimation succeeds (returns duration > 0 and confidence >= threshold)
            # (estimate_duration already applies threshold and constraints, so if it returns non-zero, use it)
            if estimated_duration > 0:
                task.estimated_duration_min = estimated_duration
                task.duration_confidence = duration_confidence
                logger.debug(f"Task {task.id} duration estimated as {estimated_duration} minutes with confidence {duration_confidence}")
            else:
                logger.debug(f"Task {task.id} duration estimation returned 0 (failed or below threshold)")
                # Keep default 30 minutes with 0.5 confidence
        except Exception as e:
            # Log error but don't fail task creation
            logger.error(f"Error estimating duration for task {task.id}: {type(e).__name__}")
            # Continue with default 30 minutes
    
    try:
        created_task = repo.create(task)
        return TaskResponse(task=created_task)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create task: {str(e)}")


@app.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all tasks for current user."""
    repo = TaskRepository(db)
    try:
        tasks = repo.get_all(current_user.id)
        return TaskListResponse(tasks=tasks, count=len(tasks))
    except Exception as e:
        logger.error(f"Failed to list tasks: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list tasks: {str(e)}")


@app.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a task by ID."""
    repo = TaskRepository(db)
    task = repo.get(current_user.id, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return TaskResponse(task=task)


@app.put("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str,
    request: TaskUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a task."""
    repo = TaskRepository(db)
    task = repo.get(current_user.id, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    
    # Update fields from request.
    # Use `model_fields_set` so we can distinguish "not provided" vs "explicitly null" (clears field).
    fields_set = getattr(request, "model_fields_set", set()) or set()

    if "title" in fields_set:
        task.title = request.title or ""
        # ai_excluded is derived from the leading '.' rule and is not directly editable.
        task.ai_excluded = determine_ai_exclusion(task.title)

    if "notes" in fields_set:
        task.notes = request.notes
    if "status" in fields_set and request.status is not None:
        task.status = request.status
    if "deadline" in fields_set:
        task.deadline = request.deadline
    if "start_after" in fields_set:
        task.start_after = request.start_after
    if "due_by" in fields_set:
        task.due_by = request.due_by
    if "estimated_duration_min" in fields_set and request.estimated_duration_min is not None:
        task.estimated_duration_min = request.estimated_duration_min
    if "category" in fields_set and request.category is not None:
        task.category = request.category
    if "energy_intensity" in fields_set and request.energy_intensity is not None:
        task.energy_intensity = request.energy_intensity
    if "risk_score" in fields_set:
        task.risk_score = request.risk_score
    if "impact_score" in fields_set:
        task.impact_score = request.impact_score
    
    task.updated_at = datetime.utcnow()
    
    try:
        updated_task = repo.update(task)
        return TaskResponse(task=updated_task)
    except ValueError as e:
        # ValueError from repository means task not found
        logger.warning(f"Task {task_id} not found for update")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update task {task_id}: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update task: {str(e)}")


@app.delete("/tasks/{task_id}", status_code=204)
async def delete_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Soft-delete a task (undoable via restore)."""
    repo = TaskRepository(db)
    schedule_repo = ScheduledBlockRepository(db)
    success = repo.delete(current_user.id, task_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    # Ensure schedule doesn't reference deleted tasks
    schedule_repo.delete_task_blocks(current_user.id, [task_id])
    return None


@app.post("/tasks/{task_id}/restore", response_model=TaskResponse)
async def restore_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Restore a soft-deleted task."""
    repo = TaskRepository(db)
    success = repo.restore(current_user.id, task_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    # Return the active task
    task = repo.get(current_user.id, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return TaskResponse(task=task)


@app.delete("/tasks/{task_id}/purge", status_code=204)
async def purge_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Permanently delete a task (irreversible)."""
    repo = TaskRepository(db)
    schedule_repo = ScheduledBlockRepository(db)
    success = repo.purge(current_user.id, task_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    # Ensure schedule doesn't reference deleted tasks
    schedule_repo.delete_task_blocks(current_user.id, [task_id])
    return None


@app.post("/tasks/bulk_delete", response_model=BulkActionResponse)
async def bulk_delete_tasks(
    request: BulkTaskIdsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft-delete multiple tasks (undoable via bulk restore)."""
    repo = TaskRepository(db)
    schedule_repo = ScheduledBlockRepository(db)
    result = repo.bulk_delete(current_user.id, request.task_ids)
    # Ensure schedule doesn't reference deleted tasks
    if result.get("affected_count", 0) > 0:
        schedule_repo.delete_task_blocks(current_user.id, request.task_ids)
    return BulkActionResponse(**result)


@app.post("/tasks/bulk_restore", response_model=BulkActionResponse)
async def bulk_restore_tasks(
    request: BulkTaskIdsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Restore multiple soft-deleted tasks."""
    repo = TaskRepository(db)
    result = repo.bulk_restore(current_user.id, request.task_ids)
    return BulkActionResponse(**result)


@app.post("/tasks/bulk_purge", response_model=BulkActionResponse)
async def bulk_purge_tasks(
    request: BulkTaskIdsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Permanently delete multiple tasks (irreversible)."""
    repo = TaskRepository(db)
    schedule_repo = ScheduledBlockRepository(db)
    result = repo.bulk_purge(current_user.id, request.task_ids)
    # Ensure schedule doesn't reference deleted tasks
    if result.get("affected_count", 0) > 0:
        schedule_repo.delete_task_blocks(current_user.id, request.task_ids)
    return BulkActionResponse(**result)


# Google Sheets import endpoint
@app.post("/import/sheets", response_model=ImportSheetsResponse)
async def import_from_sheets(
    request: ImportSheetsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Import tasks from Google Sheets.
    
    Note: On first use, this will open a browser window for OAuth authentication.
    The request will wait for you to complete the OAuth flow in the browser.
    """
    repo = TaskRepository(db)
    
    try:
        # Import tasks from Google Sheets
        # Note: Authentication happens in GoogleSheetsClient.__init__ which may open a browser
        # for OAuth flow on first use. This is a blocking operation that waits for OAuth completion.
        # Check the server console/terminal for authentication status messages.
        sheets_client = GoogleSheetsClient()
        imported_tasks = sheets_client.import_tasks(
            user_id=current_user.id,
            spreadsheet_id=request.spreadsheet_id,
            range_name=request.range_name,
            has_header=request.has_header
        )
        
        # Save tasks to database and detect duplicates
        saved_tasks = []
        duplicates_count = 0
        
        for task in imported_tasks:
            # Check for duplicates
            duplicates = repo.find_duplicates(current_user.id, task.source_type, task.source_id, task.title)
            if duplicates:
                duplicates_count += 1
                # For MVP: notify user but still import (no auto-dedupe)
            
            # Create task in database
            try:
                created_task = repo.create(task)
                saved_tasks.append(created_task)
            except Exception as e:
                # Log error but continue with other tasks
                logger.error(f"Error saving task '{task.title[:50]}': {type(e).__name__}: {str(e)}")
                continue
        
        return ImportSheetsResponse(
            imported_count=len(saved_tasks),
            tasks=saved_tasks,
            duplicates_detected=duplicates_count
        )
        
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Google Sheets credentials not found. {str(e)}"
        )
    except ValueError as e:
        # Spreadsheet ID extraction error
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        error_msg = str(e)
        # Check if it's an authentication issue
        if "credentials" in error_msg.lower() or "authentication" in error_msg.lower():
            raise HTTPException(
                status_code=401,
                detail=f"Authentication failed: {error_msg}"
            )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to import from Google Sheets: {error_msg}"
        )


@app.post("/schedule", response_model=ScheduleResponse)
async def build_schedule(
    horizon_days: int = Query(7, description="Schedule horizon in days (7/14/30; capped at 30)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Build schedule from tasks in database."""
    task_repo = TaskRepository(db)
    schedule_repo = ScheduledBlockRepository(db)

    # Schedule window (must match both calendar query and scheduler inputs).
    schedule_start = datetime.utcnow()
    horizon_days = int(horizon_days or 7)
    if horizon_days not in (7, 14, 30):
        raise HTTPException(status_code=400, detail="horizon_days must be one of: 7, 14, 30")
    schedule_end = schedule_start + timedelta(days=min(horizon_days, 30))

    # Materialize recurring series into concrete task instances within the horizon.
    # Best-effort: never block scheduling if a series cannot be materialized.
    try:
        materialize_recurring_tasks(
            db,
            user_id=current_user.id,
            window_start=schedule_start,
            window_end=schedule_end,
        )
    except Exception:
        pass

    tasks = task_repo.get_open(current_user.id)

    if not tasks:
        raise HTTPException(status_code=400, detail="No tasks available. Create tasks first.")
    
    try:
        # Scheduling requires Calendar connection so we can respect real availability.
        token_repo = GoogleOAuthTokenRepository(db)
        token_row = token_repo.get_google_calendar(current_user.id)
        if not token_row:
            raise HTTPException(
                status_code=400,
                detail="Google Calendar not connected. Connect via /auth/google/calendar/auth-url (or click Sync in the UI).",
            )

        client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            raise HTTPException(status_code=500, detail="Google OAuth client is not configured")

        refresh_token = decrypt_secret(token_row.refresh_token_encrypted)
        scopes = token_row.scopes or ["https://www.googleapis.com/auth/calendar"]

        creds = GoogleCredentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes,
        )
        try:
            creds.refresh(GoogleAuthRequest())
        except Exception as e:
            logger.warning(f"Google Calendar refresh failed for user {current_user.id}: {type(e).__name__}: {str(e)}")
            # If the refresh token is revoked/expired, clear it so the next schedule build forces reconnect.
            msg = str(e).lower()
            if "invalid_grant" in msg or "expired" in msg or "revoked" in msg:
                try:
                    token_repo.delete_google_calendar(current_user.id)
                except Exception:
                    pass
            raise HTTPException(
                status_code=400,
                detail=(
                    "Google Calendar authorization expired or was revoked. "
                    "Reconnect via /auth/google/calendar/auth-url (or click Sync in the UI)."
                ),
            )

        calendar_client = GoogleCalendarClient(credentials=creds, calendar_id="primary")
        # Ensure timezone is a real IANA tz database identifier (defensive for tests/mocks).
        calendar_tz_raw = calendar_client.get_calendar_timezone()
        calendar_tz = "UTC"
        try:
            tz_candidate = str(calendar_tz_raw) if calendar_tz_raw else "UTC"
            ZoneInfo(tz_candidate)  # validate
            calendar_tz = tz_candidate
        except Exception:
            calendar_tz = "UTC"

        # Schedule window (must match both calendar query and scheduler inputs).
        # schedule_start / schedule_end were chosen above (also used for recurring task materialization).

        # Preserve locked blocks from prior schedule (frozen placements).
        existing_blocks = schedule_repo.get_all(current_user.id)
        locked_blocks = [b for b in existing_blocks if b.locked]
        unlocked_blocks = [b for b in existing_blocks if not b.locked]

        # Preserve calendar_event_id mappings across rebuild by reusing prior block IDs per-task.
        # This prevents duplicate calendar events when schedule is rebuilt.
        unlocked_by_task: Dict[str, List[ScheduledBlock]] = {}
        for b in unlocked_blocks:
            if b.entity_type == "task":
                unlocked_by_task.setdefault(b.entity_id, []).append(b)
        for tid in unlocked_by_task:
            unlocked_by_task[tid].sort(key=lambda b: b.start_time)

        # Compute reserved intervals (locked time is off-limits for new blocks).
        reserved_intervals: List[Tuple[datetime, datetime]] = [(b.start_time, b.end_time) for b in locked_blocks]

        # Add non-managed Calendar event windows as reserved time (privacy: time window only).
        try:
            events = calendar_client.list_events_in_range(
                time_min_rfc3339=_to_rfc3339_z(schedule_start),
                time_max_rfc3339=_to_rfc3339_z(schedule_end),
                # Minimize data: only the fields needed to identify managed events and time windows.
                fields="items(start,end,status,extendedProperties(private)),nextPageToken",
            )
            for ev in events:
                priv = _event_private(ev)
                if priv.get(PRIVATE_KEY_MANAGED) == "1":
                    continue
                interval = _event_time_window_utc_naive(ev)
                if interval:
                    reserved_intervals.append(interval)
        except Exception:
            # Best-effort: if availability fetch fails, do not schedule blindly.
            # Return a clear error so the user can retry.
            raise HTTPException(status_code=400, detail="Failed to read calendar availability. Try again.")

        # Reduce per-task remaining duration by time already covered by locked blocks.
        locked_minutes_by_task: Dict[str, int] = {}
        for b in locked_blocks:
            if b.entity_type == "task":
                mins = int((b.end_time - b.start_time).total_seconds() // 60)
                locked_minutes_by_task[b.entity_id] = locked_minutes_by_task.get(b.entity_id, 0) + max(mins, 0)

        def _date_start_utc_naive(d: date, *, time_zone_id: str) -> datetime:
            try:
                tzinfo = ZoneInfo(time_zone_id)
            except Exception:
                tzinfo = ZoneInfo("UTC")
            local_start = datetime.combine(d, time(0, 0, 0), tzinfo=tzinfo)
            return local_start.astimezone(timezone.utc).replace(tzinfo=None)

        # Apply start_after as a hard earliest-start constraint (within this schedule window).
        # Represent it via flexibility_window so the scheduler can enforce it deterministically.
        tasks_with_start_after: List[Task] = []
        for t in tasks:
            if getattr(t, "start_after", None) is None:
                tasks_with_start_after.append(t)
                continue

            earliest = _date_start_utc_naive(t.start_after, time_zone_id=calendar_tz)
            existing = getattr(t, "flexibility_window", None)
            if existing:
                try:
                    ws, we = existing
                except Exception:
                    ws, we = None, None
                if ws is not None:
                    earliest = max(ws, earliest)
                latest = we if we is not None else schedule_end
                latest = min(latest, schedule_end)
            else:
                latest = schedule_end

            tasks_with_start_after.append(t.model_copy(update={"flexibility_window": (earliest, latest)}))

        # Stack rank tasks (tier first, then urgency within tier).
        ranked_tasks = stack_rank(tasks_with_start_after, now=schedule_start, time_zone=calendar_tz)

        # Schedule remaining work around locked placements.
        schedulable_tasks: List[Task] = []
        for t in ranked_tasks:
            consumed = locked_minutes_by_task.get(t.id, 0)
            remaining = max(int(t.estimated_duration_min) - consumed, 0)
            if remaining <= 0:
                continue
            schedulable_tasks.append(t.model_copy(update={"estimated_duration_min": remaining}))

        schedule_result = schedule_tasks(
            schedulable_tasks,
            start_time=schedule_start,
            end_time=schedule_end,
            reserved_intervals=reserved_intervals,
        )

        # Reuse unlocked block IDs + calendar sync metadata where possible (per task, by block order).
        adjusted_blocks: List[ScheduledBlock] = []
        new_by_task: Dict[str, List[ScheduledBlock]] = {}
        for b in schedule_result.scheduled_blocks:
            if b.entity_type == "task":
                new_by_task.setdefault(b.entity_id, []).append(b)
            else:
                adjusted_blocks.append(b)
        for tid in new_by_task:
            new_by_task[tid].sort(key=lambda b: b.start_time)
            prior = unlocked_by_task.get(tid, [])
            for i, b in enumerate(new_by_task[tid]):
                if i < len(prior):
                    old = prior[i]
                    b = b.model_copy(
                        update={
                            "id": old.id,
                            "calendar_event_id": old.calendar_event_id,
                            "calendar_event_etag": getattr(old, "calendar_event_etag", None),
                            "calendar_event_updated_at": getattr(old, "calendar_event_updated_at", None),
                        }
                    )
                adjusted_blocks.append(b)
        schedule_result.scheduled_blocks = adjusted_blocks

        # Store schedule in database (preserve locked, replace unlocked)
        schedule_repo.delete_unlocked_for_user(current_user.id)
        schedule_repo.create_batch(schedule_result.scheduled_blocks)

        # Combined view: locked blocks + newly scheduled blocks
        combined_blocks = sorted(locked_blocks + schedule_result.scheduled_blocks, key=lambda b: b.start_time)
        
        # Build task titles map for frontend lookup
        task_titles = _build_task_titles_dict(tasks, combined_blocks)
        
        return ScheduleResponse(
            scheduled_blocks=combined_blocks,
            overflow_tasks=schedule_result.overflow_tasks,
            start_time=schedule_result.start_time,
            task_titles=task_titles,
            time_zone=calendar_tz,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to build schedule: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to build schedule: {str(e)}")


@app.get("/schedule", response_model=ScheduleResponse)
async def view_schedule(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """View current schedule for user."""
    schedule_repo = ScheduledBlockRepository(db)
    task_repo = TaskRepository(db)
    
    blocks = schedule_repo.get_all(current_user.id)
    
    if not blocks:
        raise HTTPException(status_code=404, detail="No schedule available. Build a schedule first.")
    
    tasks = task_repo.get_all(current_user.id)
    task_titles = _build_task_titles_dict(tasks, blocks)
    
    # For MVP, overflow_tasks and start_time are not stored in DB
    # Return empty overflow and None start_time
    return ScheduleResponse(
        scheduled_blocks=blocks,
        overflow_tasks=[],
        start_time=None,
        task_titles=task_titles,
        time_zone=None,
    )


@app.post("/sync-calendar", response_model=SyncResponse)
async def sync_calendar(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Sync schedule to Google Calendar."""
    schedule_repo = ScheduledBlockRepository(db)
    task_repo = TaskRepository(db)
    
    blocks = schedule_repo.get_all(current_user.id)
    
    if not blocks:
        raise HTTPException(status_code=400, detail="No schedule available. Build a schedule first.")
    
    try:
        token_repo = GoogleOAuthTokenRepository(db)
        token_row = token_repo.get_google_calendar(current_user.id)
        if not token_row:
            raise HTTPException(
                status_code=400,
                detail="Google Calendar not connected. Connect via /auth/google/calendar/auth-url (or click Sync in the UI).",
            )

        client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            raise HTTPException(status_code=500, detail="Google OAuth client is not configured")

        refresh_token = decrypt_secret(token_row.refresh_token_encrypted)
        scopes = token_row.scopes or ["https://www.googleapis.com/auth/calendar"]

        creds = GoogleCredentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes,
        )
        try:
            creds.refresh(GoogleAuthRequest())
        except Exception as e:
            logger.warning(f"Google Calendar refresh failed for user {current_user.id}: {type(e).__name__}: {str(e)}")
            # If the refresh token is revoked/expired, clear it so the next sync forces reconnect.
            msg = str(e).lower()
            if "invalid_grant" in msg or "expired" in msg or "revoked" in msg:
                try:
                    token_repo.delete_google_calendar(current_user.id)
                except Exception:
                    # Best effort; never hide the original auth failure.
                    pass
            raise HTTPException(
                status_code=400,
                detail=(
                    "Google Calendar authorization expired or was revoked. "
                    "Reconnect via /auth/google/calendar/auth-url (or click Sync in the UI)."
                ),
            )

        calendar_client = GoogleCalendarClient(credentials=creds, calendar_id="primary")
        tasks = task_repo.get_all(current_user.id)
        tasks_dict = {task.id: task for task in tasks}
        current_block_ids = {b.id for b in blocks}
        
        def _is_managed_event_for_block(event: dict, block_id: str) -> bool:
            priv = _event_private(event)
            return priv.get(PRIVATE_KEY_MANAGED) == "1" and priv.get(PRIVATE_KEY_BLOCK_ID) == block_id

        def _needs_patch(event: dict, *, desired: dict) -> bool:
            # Compare only the fields we own (summary, description, start/end, private keys).
            if (event.get("summary") or "") != (desired.get("summary") or ""):
                return True
            if (event.get("description") or "") != (desired.get("description") or ""):
                return True
            ev_start = (event.get("start") or {}).get("dateTime")
            ev_end = (event.get("end") or {}).get("dateTime")
            d_start = (desired.get("start") or {}).get("dateTime")
            d_end = (desired.get("end") or {}).get("dateTime")
            if (ev_start or "") != (d_start or "") or (ev_end or "") != (d_end or ""):
                return True
            ev_priv = _event_private(event)
            d_priv = ((desired.get("extendedProperties") or {}).get("private") or {})
            for k in (PRIVATE_KEY_TASK_ID, PRIVATE_KEY_BLOCK_ID, PRIVATE_KEY_MANAGED):
                if (ev_priv.get(k) or "") != (d_priv.get(k) or ""):
                    return True
            return False

        events_created = 0
        event_ids: List[str] = []

        schedule_repo = ScheduledBlockRepository(db)

        # Cleanup: delete orphaned qzWhatNext-managed events within the schedule window.
        try:
            starts = [b.start_time for b in blocks if b.start_time]
            ends = [b.end_time for b in blocks if b.end_time]
            if starts and ends:
                from datetime import timedelta

                window_start = min(starts) - timedelta(days=2)
                window_end = max(ends) + timedelta(days=2)

                for ev in calendar_client.list_events_in_range(
                    time_min_rfc3339=_to_rfc3339_z(window_start),
                    time_max_rfc3339=_to_rfc3339_z(window_end),
                ):
                    priv = ((ev.get("extendedProperties") or {}).get("private") or {})
                    if priv.get(PRIVATE_KEY_MANAGED) != "1":
                        continue
                    ev_block_id = priv.get(PRIVATE_KEY_BLOCK_ID)
                    if not ev_block_id or ev_block_id in current_block_ids:
                        continue
                    ev_id = ev.get("id")
                    if ev_id:
                        calendar_client.delete_event(ev_id)
        except Exception:
            # Best-effort cleanup; never block sync.
            pass

        for block in blocks:
            if block.entity_type != "task":
                continue

            task = tasks_dict.get(block.entity_id)
            if task is None:
                continue

            try:
                event = None
                event_id = block.calendar_event_id

                # 1) Prefer direct lookup by persisted event id
                if event_id:
                    event = calendar_client.get_event(event_id)
                    # If the event was deleted in Google Calendar, treat as missing so we recreate it.
                    if event is None or (isinstance(event, dict) and event.get("status") == "cancelled"):
                        # Event missing (deleted). Clear mapping so we can recreate.
                        schedule_repo.update_calendar_sync_metadata(
                            current_user.id,
                            block.id,
                            calendar_event_id=None,
                            calendar_event_etag=None,
                            calendar_event_updated_at=None,
                        )
                        event_id = None
                        event = None

                # 2) Fallback: find existing event by private block id (legacy / adopted)
                if event is None and not event_id:
                    event = calendar_client.find_event_by_block_id(block.id)
                    if event is not None:
                        # Defensive: only accept if it actually carries our block marker.
                        priv = _event_private(event)
                        if priv.get(PRIVATE_KEY_BLOCK_ID) == block.id:
                            event_id = event.get("id")
                        else:
                            event = None
                            event_id = None

                # 3) Create if missing
                if event is None:
                    created = calendar_client.create_event_from_block(block, task)
                    event_id = created.get("id")
                    events_created += 1
                    if event_id:
                        event_ids.append(event_id)
                    schedule_repo.update_calendar_sync_metadata(
                        current_user.id,
                        block.id,
                        calendar_event_id=event_id,
                        calendar_event_etag=created.get("etag"),
                        calendar_event_updated_at=_to_utc_naive(_parse_rfc3339(created.get("updated"))),
                    )
                    continue

                if not event_id:
                    # Shouldn't happen, but never touch unknown ids.
                    continue

                # 4) Adopt legacy event by adding managed marker (if it looks like ours).
                priv = _event_private(event)
                if priv.get(PRIVATE_KEY_BLOCK_ID) == block.id and priv.get(PRIVATE_KEY_MANAGED) != "1":
                    patch_body = {
                        "extendedProperties": {
                            "private": {
                                PRIVATE_KEY_TASK_ID: block.entity_id,
                                PRIVATE_KEY_BLOCK_ID: block.id,
                                PRIVATE_KEY_MANAGED: "1",
                            }
                        }
                    }
                    event = calendar_client.patch_event(event_id, patch_body)

                # Safety: only update events proven managed for this block.
                if not _is_managed_event_for_block(event, block.id):
                    continue

                # Always persist event id mapping if found.
                if block.calendar_event_id != event_id:
                    schedule_repo.update_calendar_sync_metadata(
                        current_user.id,
                        block.id,
                        calendar_event_id=event_id,
                    )

                event_etag = event.get("etag")
                event_updated_at = _to_utc_naive(_parse_rfc3339(event.get("updated")))

                has_baseline = bool(block.calendar_event_etag or block.calendar_event_updated_at)
                calendar_changed = has_baseline and (
                    (block.calendar_event_etag or "") != (event_etag or "")
                    or (block.calendar_event_updated_at != event_updated_at)
                )

                if not has_baseline:
                    # First time we see this event with no stored calendar version metadata.
                    # Record baseline, but do NOT treat it as a user calendar edit.
                    schedule_repo.update_calendar_sync_metadata(
                        current_user.id,
                        block.id,
                        calendar_event_id=event_id,
                        calendar_event_etag=event_etag,
                        calendar_event_updated_at=event_updated_at,
                    )

                if calendar_changed:
                    # Import calendar time into qzWhatNext and lock if time changed.
                    start_str = (event.get("start") or {}).get("dateTime")
                    end_str = (event.get("end") or {}).get("dateTime")
                    if start_str and end_str:
                        ev_start = _to_utc_naive(_parse_rfc3339(start_str))
                        ev_end = _to_utc_naive(_parse_rfc3339(end_str))
                        if ev_start and ev_end:
                            time_changed = ev_start != block.start_time or ev_end != block.end_time
                            schedule_repo.update_times_and_lock(
                                current_user.id,
                                block.id,
                                start_time=ev_start,
                                end_time=ev_end,
                                lock=time_changed,
                            )
                    # Import title/notes from Calendar to prevent overwriting user edits.
                    ev_title = event.get("summary")
                    ev_notes = event.get("description")
                    if (ev_title is not None and ev_title != task.title) or (ev_notes is not None and ev_notes != task.notes):
                        existing = task_repo.get(current_user.id, task.id)
                        if existing is not None:
                            updated_task = existing.model_copy(
                                update={
                                    "title": ev_title if ev_title is not None else existing.title,
                                    "notes": ev_notes if ev_notes is not None else existing.notes,
                                    "updated_at": datetime.utcnow(),
                                }
                            )
                            task_repo.update(updated_task)
                    schedule_repo.update_calendar_sync_metadata(
                        current_user.id,
                        block.id,
                        calendar_event_id=event_id,
                        calendar_event_etag=event_etag,
                        calendar_event_updated_at=event_updated_at,
                    )
                    continue

                # No calendar-side edits since last sync: push app state if needed.
                desired = {
                    "summary": task.title,
                    "description": task.notes,
                    "start": {"dateTime": block.start_time.isoformat(), "timeZone": "UTC"},
                    "end": {"dateTime": block.end_time.isoformat(), "timeZone": "UTC"},
                    "extendedProperties": {
                        "private": {
                            PRIVATE_KEY_TASK_ID: block.entity_id,
                            PRIVATE_KEY_BLOCK_ID: block.id,
                            PRIVATE_KEY_MANAGED: "1",
                        }
                    },
                }
                if _needs_patch(event, desired=desired):
                    updated = calendar_client.patch_event(event_id, desired)
                    schedule_repo.update_calendar_sync_metadata(
                        current_user.id,
                        block.id,
                        calendar_event_id=event_id,
                        calendar_event_etag=updated.get("etag"),
                        calendar_event_updated_at=_to_utc_naive(_parse_rfc3339(updated.get("updated"))),
                    )

            except Exception as e:
                logger.error(
                    f"Failed to sync calendar event for block {block.id}: {type(e).__name__}: {str(e)}"
                )
                continue

        return SyncResponse(events_created=events_created, event_ids=event_ids)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to sync calendar: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to sync calendar: {str(e)}")


@app.post("/schedule/blocks/{block_id}/lock", response_model=ScheduledBlockResponse)
async def lock_scheduled_block(
    block_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Freeze a scheduled block date/time so rebuild won't move it."""
    repo = ScheduledBlockRepository(db)
    updated = repo.set_locked(current_user.id, block_id, True)
    if updated is None:
        raise HTTPException(status_code=404, detail="Scheduled block not found")
    return ScheduledBlockResponse(block=updated)


@app.post("/schedule/blocks/{block_id}/unlock", response_model=ScheduledBlockResponse)
async def unlock_scheduled_block(
    block_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Unfreeze a scheduled block so rebuild may move it again."""
    repo = ScheduledBlockRepository(db)
    updated = repo.set_locked(current_user.id, block_id, False)
    if updated is None:
        raise HTTPException(status_code=404, detail="Scheduled block not found")
    return ScheduledBlockResponse(block=updated)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
