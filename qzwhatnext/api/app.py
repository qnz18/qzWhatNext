"""FastAPI web application for qzWhatNext."""

import logging
import os
import uuid
from datetime import datetime
from typing import List, Optional, Dict
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from qzwhatnext.models.task import Task, TaskStatus, TaskCategory, EnergyIntensity
from qzwhatnext.models.scheduled_block import ScheduledBlock
from qzwhatnext.models.task_factory import create_task_base, determine_ai_exclusion
from qzwhatnext.api.auth_models import GoogleOAuthCallbackRequest, AuthResponse
from qzwhatnext.integrations.google_calendar import GoogleCalendarClient
from qzwhatnext.integrations.google_sheets import GoogleSheetsClient
from qzwhatnext.engine.ranking import stack_rank
from qzwhatnext.engine.scheduler import schedule_tasks, SchedulingResult
from qzwhatnext.engine.inference import infer_category, generate_title, estimate_duration
from qzwhatnext.database.database import get_db, init_db
from qzwhatnext.database.repository import TaskRepository
from qzwhatnext.database.user_repository import UserRepository
from qzwhatnext.database.scheduled_block_repository import ScheduledBlockRepository
from qzwhatnext.database.models import ApiTokenDB
from qzwhatnext.auth.jwt import create_access_token
from qzwhatnext.auth.google_oauth import verify_google_token
from qzwhatnext.auth.dependencies import get_current_user
from qzwhatnext.auth.shortcut_tokens import generate_shortcut_token, hash_shortcut_token
from qzwhatnext.models.user import User

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


class ScheduleResponse(BaseModel):
    """Response for schedule view."""
    scheduled_blocks: List[ScheduledBlock]
    overflow_tasks: List[Task]
    start_time: Optional[datetime]
    task_titles: Dict[str, str] = Field(default_factory=dict, description="Map of entity_id to task title")


class SyncResponse(BaseModel):
    """Response for calendar sync."""
    events_created: int
    event_ids: List[str]


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
                <span id="tasksUpdated" class="muted"></span>
            </div>
            <div id="tasks"></div>
        </div>

        <div class="section">
            <h2>Actions</h2>
            <button onclick="buildSchedule()">Build Schedule</button>
            <button onclick="syncCalendar()">Sync to Google Calendar</button>
            <button onclick="viewSchedule()">View Schedule</button>
            <button onclick="viewTasks()">View All Tasks</button>
        </div>
        
        <div class="section">
            <h2>Schedule</h2>
            <div id="schedule"></div>
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
                await loadShortcutTokenStatus(version);
            }

            async function loadAuthConfig() {
                const res = await fetch('/auth/config');
                if (!res.ok) return null;
                return await res.json();
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
                if (!window.google || !google.accounts || !google.accounts.id) {
                    setAuthStatus('Google sign-in library not loaded yet. Refresh in a second.');
                    return;
                }
                setJwtUiState();
                google.accounts.id.initialize({
                    client_id: clientId,
                    callback: handleGoogleCredentialResponse,
                    // Don't auto-select account - force user to choose
                    auto_select: false,
                    // Cancel One Tap prompt to force button click for account selection
                    cancel_on_tap_outside: true
                });
                google.accounts.id.renderButton(
                    document.getElementById("gsi-button"),
                    { 
                        theme: "outline", 
                        size: "large",
                        text: "signin_with",
                        shape: "rectangular"
                    }
                );
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
                try {
                    if (window.google && google.accounts && google.accounts.id) {
                        // Prevent Google from silently reusing the last account selection.
                        google.accounts.id.disableAutoSelect();
                        // Best-effort revoke; even if it fails, local logout still stands.
                        if (currentUserEmail) {
                            google.accounts.id.revoke(currentUserEmail, () => {});
                        }
                    }
                } catch (e) {
                    // ignore
                }
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
                    const response = await apiFetch('/schedule', { method: 'POST' }, version);
                    const data = await response.json();
                    if (isStale(version)) return;
                    status.innerHTML = `Schedule built: ${data.scheduled_blocks.length} blocks, ${data.overflow_tasks.length} overflow`;
                    await viewSchedule(version);
                } catch (error) {
                    if (!isStale(version)) {
                        status.innerHTML = 'Error: ' + error.message;
                    }
                }
            }
            
            async function syncCalendar() {
                const version = authVersion;
                const status = document.getElementById('status');
                status.innerHTML = 'Syncing to Google Calendar...';
                try {
                    const response = await apiFetch('/sync-calendar', { method: 'POST' }, version);
                    const data = await response.json();
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
                    const data = await response.json();
                    if (isStale(version)) return;
                    
                    if (data.tasks.length === 0) {
                        tasksDiv.innerHTML = '<p>No tasks yet. Create a task or import from Google Sheets.</p>';
                        if (tasksUpdated) tasksUpdated.textContent = `Last refreshed: ${new Date().toLocaleString()}`;
                        return;
                    }
                    
                    let html = `<p><strong>Total tasks: ${data.count}</strong></p>`;
                    html += '<div class="tasks-container"><table><tr><th>Title</th><th>Category</th><th>Duration</th><th>Status</th><th>Notes</th></tr>';
                    data.tasks.forEach(task => {
                        const notes = task.notes ? task.notes.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;') : '';
                        html += `<tr>
                            <td>${task.title}</td>
                            <td>${task.category || 'N/A'}</td>
                            <td>${task.estimated_duration_min || 30} min</td>
                            <td>${task.status || 'OPEN'}</td>
                            <td class="notes">${notes || 'N/A'}</td>
                        </tr>`;
                    });
                    html += '</table></div>';
                    
                    tasksDiv.innerHTML = html;
                    if (tasksUpdated) tasksUpdated.textContent = `Last refreshed: ${new Date().toLocaleString()}`;
                } catch (error) {
                    if (isStale(version)) return;
                    tasksDiv.innerHTML = 'Error: ' + error.message;
                    const tasksUpdated = document.getElementById('tasksUpdated');
                    if (tasksUpdated) tasksUpdated.textContent = 'Refresh failed.';
                }
            }
            
            async function viewSchedule(version = authVersion) {
                const scheduleDiv = document.getElementById('schedule');
                try {
                    const response = await apiFetch('/schedule', {}, version);
                    const data = await response.json();
                    if (isStale(version)) return;
                    
                    if (data.scheduled_blocks.length === 0) {
                        scheduleDiv.innerHTML = '<p>No schedule available. Build a schedule first.</p>';
                        return;
                    }
                    
                    let html = '<table><tr><th>Start</th><th>End</th><th>Task</th></tr>';
                    data.scheduled_blocks.forEach(block => {
                        let taskName = 'Unknown';
                        if (block.entity_type === 'task' && data.task_titles && data.task_titles[block.entity_id]) {
                            taskName = data.task_titles[block.entity_id];
                        } else if (block.entity_type === 'transition') {
                            taskName = 'Transition';
                        } else {
                            taskName = block.entity_id; // Fallback to ID if title not found
                        }
                        html += `<tr>
                            <td>${new Date(block.start_time).toLocaleString()}</td>
                            <td>${new Date(block.end_time).toLocaleString()}</td>
                            <td>${taskName}</td>
                        </tr>`;
                    });
                    html += '</table>';
                    
                    if (data.overflow_tasks.length > 0) {
                        html += `<p><strong>Overflow tasks (${data.overflow_tasks.length}):</strong></p><ul>`;
                        data.overflow_tasks.forEach(task => {
                            html += `<li>${task.title}</li>`;
                        });
                        html += '</ul>';
                    }
                    
                    scheduleDiv.innerHTML = html;
                } catch (error) {
                    if (isStale(version)) return;
                    scheduleDiv.innerHTML = 'Error: ' + error.message;
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
    return {"google_oauth_client_id": os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")}


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


@app.get("/auth/me")
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get current authenticated user information."""
    return {"user": current_user.model_dump()}


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
    
    # Update fields from request (only provided fields)
    if request.title is not None:
        task.title = request.title
    if request.notes is not None:
        task.notes = request.notes
    if request.status is not None:
        task.status = request.status
    if request.deadline is not None:
        task.deadline = request.deadline
    if request.estimated_duration_min is not None:
        task.estimated_duration_min = request.estimated_duration_min
    if request.category is not None:
        task.category = request.category
    if request.energy_intensity is not None:
        task.energy_intensity = request.energy_intensity
    if request.risk_score is not None:
        task.risk_score = request.risk_score
    if request.impact_score is not None:
        task.impact_score = request.impact_score
    if request.ai_excluded is not None:
        task.ai_excluded = request.ai_excluded
    
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
    """Delete a task."""
    repo = TaskRepository(db)
    success = repo.delete(current_user.id, task_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return None


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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Build schedule from tasks in database."""
    task_repo = TaskRepository(db)
    schedule_repo = ScheduledBlockRepository(db)
    
    tasks = task_repo.get_open(current_user.id)
    
    if not tasks:
        raise HTTPException(status_code=400, detail="No tasks available. Create tasks first.")
    
    try:
        # Stack rank tasks
        ranked_tasks = stack_rank(tasks)
        
        # Schedule tasks (blocks will have user_id from task.user_id)
        schedule_result = schedule_tasks(ranked_tasks)
        
        # Store schedule in database (delete old, insert new)
        schedule_repo.delete_all_for_user(current_user.id)
        schedule_repo.create_batch(schedule_result.scheduled_blocks)
        
        # Build task titles map for frontend lookup
        task_titles = _build_task_titles_dict(tasks, schedule_result.scheduled_blocks)
        
        return ScheduleResponse(
            scheduled_blocks=schedule_result.scheduled_blocks,
            overflow_tasks=schedule_result.overflow_tasks,
            start_time=schedule_result.start_time,
            task_titles=task_titles
        )
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
        task_titles=task_titles
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
        calendar_client = GoogleCalendarClient()
        tasks = task_repo.get_all(current_user.id)
        tasks_dict = {task.id: task for task in tasks}
        
        events_created = 0
        event_ids = []
        
        for block in blocks:
            if block.entity_type == "task":
                task = tasks_dict.get(block.entity_id)
                try:
                    event = calendar_client.create_event_from_block(block, task)
                    events_created += 1
                    event_id = event.get('id', 'unknown')
                    event_ids.append(event_id)
                    
                    # Note: In MVP, we don't persist calendar_event_id updates
                    # This would require update method in ScheduledBlockRepository
                except Exception as e:
                    logger.error(f"Failed to create calendar event for block {block.id}: {type(e).__name__}: {str(e)}")
                    continue
        
        return SyncResponse(
            events_created=events_created,
            event_ids=event_ids
        )
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Google Calendar credentials not found. {str(e)}"
        )
    except Exception as e:
        logger.error(f"Failed to sync calendar: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to sync calendar: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
