"""Google Calendar integration for qzWhatNext."""

import os
from datetime import datetime
from typing import List, Optional, Iterable
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv

from qzwhatnext.models.scheduled_block import ScheduledBlock, EntityType
from qzwhatnext.models.task import Task

load_dotenv()

# Google Calendar API scopes
SCOPES = ['https://www.googleapis.com/auth/calendar']

# Private extendedProperties keys used to identify qzWhatNext-managed events.
PRIVATE_KEY_TASK_ID = "qzwhatnext_task_id"
PRIVATE_KEY_BLOCK_ID = "qzwhatnext_block_id"
PRIVATE_KEY_MANAGED = "qzwhatnext_managed"
# Private key for recurring time blocks (NOT marked managed).
PRIVATE_KEY_TIME_BLOCK_ID = "qzwhatnext_time_block_id"


class GoogleCalendarClient:
    """Client for Google Calendar API integration."""
    
    def __init__(
        self,
        credentials: Optional[Credentials] = None,
        credentials_path: Optional[str] = None,
        calendar_id: Optional[str] = None,
        token_path: str = "token.json"
    ):
        """Initialize Google Calendar client.
        
        Args:
            credentials: Pre-authenticated OAuth2 credentials (preferred for deployed envs).
            credentials_path: Path to OAuth2 credentials JSON file.
                             If None, reads from GOOGLE_CALENDAR_CREDENTIALS_PATH env var.
            calendar_id: Google Calendar ID to use.
                        If None, reads from GOOGLE_CALENDAR_ID env var (defaults to 'primary').
            token_path: Path to store OAuth2 token (defaults to 'token.json').
        """
        self.credentials_path = credentials_path or os.getenv("GOOGLE_CALENDAR_CREDENTIALS_PATH", "credentials.json")
        self.calendar_id = calendar_id or os.getenv("GOOGLE_CALENDAR_ID", "primary")
        self.token_path = token_path
        self.service = None
        self.creds = credentials
        if self.creds is not None:
            self.service = build('calendar', 'v3', credentials=self.creds)
        else:
            # Legacy/local-dev OAuth flow. Do NOT use this for deployed web auth.
            self._authenticate()
    
    def _authenticate(self):
        """Authenticate with Google Calendar API using OAuth2."""
        creds = None
        
        # Load existing token if available
        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
        
        # If no valid credentials, get new ones
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_path):
                    raise FileNotFoundError(
                        f"Google Calendar credentials not found at {self.credentials_path}. "
                        "Please download OAuth2 credentials from Google Cloud Console."
                    )
                
                # InstalledAppFlow works with both Desktop and Web app credentials
                # Use fixed port 8080 for OAuth redirect URI matching
                # Make sure http://localhost:8080/ is in authorized redirect URIs in Google Cloud Console
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, SCOPES
                )
                creds = flow.run_local_server(port=8080)
            
            # Save credentials for next run
            with open(self.token_path, 'w') as token:
                token.write(creds.to_json())
        
        self.creds = creds
        self.service = build('calendar', 'v3', credentials=creds)
    
    def create_event_from_block(
        self,
        block: ScheduledBlock,
        task: Optional[Task] = None
    ) -> dict:
        """Create a Google Calendar event from a ScheduledBlock.
        
        Args:
            block: ScheduledBlock to create event from
            task: Optional Task object for additional metadata
            
        Returns:
            Created event dictionary from Google Calendar API
            
        Raises:
            HttpError: If API call fails
        """
        if block.entity_type != EntityType.TASK:
            raise ValueError(f"Cannot create event for entity type: {block.entity_type}")
        
        # Build event body
        event_body = {
            'summary': task.title if task else f"Task {block.entity_id}",
            'description': task.notes if task else f"Task ID: {block.entity_id}",
            'start': {
                'dateTime': block.start_time.isoformat(),
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': block.end_time.isoformat(),
                'timeZone': 'UTC',
            },
            'extendedProperties': {
                'private': {
                    PRIVATE_KEY_TASK_ID: block.entity_id,
                    PRIVATE_KEY_BLOCK_ID: block.id,
                    PRIVATE_KEY_MANAGED: "1",
                }
            }
        }
        
        try:
            event = self.service.events().insert(
                calendarId=self.calendar_id,
                body=event_body
            ).execute()
            
            return event
        except HttpError as error:
            raise Exception(f"Failed to create calendar event: {error}") from error

    def get_event(self, event_id: str) -> dict:
        """Get a calendar event by ID."""
        try:
            return self.service.events().get(calendarId=self.calendar_id, eventId=event_id).execute()
        except HttpError as error:
            # If the event was deleted from Calendar, treat as missing.
            status = getattr(getattr(error, "resp", None), "status", None)
            # Google may return 404 (not found) or 410 (gone) for deleted events.
            if status in (404, 410):
                return None
            raise

    def find_event_by_block_id(self, block_id: str, *, max_results: int = 5) -> Optional[dict]:
        """Find an event by qzWhatNext block id (private extended property)."""
        try:
            resp = (
                self.service.events()
                .list(
                    calendarId=self.calendar_id,
                    privateExtendedProperty=f"{PRIVATE_KEY_BLOCK_ID}={block_id}",
                    maxResults=max_results,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            items = resp.get("items") or []
            return items[0] if items else None
        except HttpError as error:
            raise

    def patch_event(self, event_id: str, body: dict) -> dict:
        """Patch an event (partial update)."""
        try:
            return (
                self.service.events()
                .patch(calendarId=self.calendar_id, eventId=event_id, body=body)
                .execute()
            )
        except HttpError as error:
            raise

    def delete_event(self, event_id: str) -> None:
        """Delete an event by ID."""
        try:
            self.service.events().delete(calendarId=self.calendar_id, eventId=event_id).execute()
        except HttpError as error:
            # Deleting a missing event is effectively a no-op.
            status = getattr(getattr(error, "resp", None), "status", None)
            if status in (404, 410):
                return
            raise

    def list_events_in_range(
        self,
        *,
        time_min_rfc3339: str,
        time_max_rfc3339: str,
        fields: Optional[str] = None,
        max_pages: int = 10,
    ) -> List[dict]:
        """List events in a time range (singleEvents) with pagination.

        Args:
            time_min_rfc3339: RFC3339 timeMin (e.g. 2026-01-01T00:00:00Z)
            time_max_rfc3339: RFC3339 timeMax
            fields: Optional partial response fields selector (minimize data returned).
            max_pages: safety cap on pagination
        """
        items: List[dict] = []
        page_token: Optional[str] = None
        pages = 0
        while True:
            pages += 1
            if pages > max_pages:
                break
            kwargs = dict(
                calendarId=self.calendar_id,
                timeMin=time_min_rfc3339,
                timeMax=time_max_rfc3339,
                singleEvents=True,
                orderBy="startTime",
                pageToken=page_token,
                maxResults=2500,
            )
            if fields:
                # google-api-python-client supports partial responses via the `fields` query parameter.
                kwargs["fields"] = fields
            resp = self.service.events().list(**kwargs).execute()
            items.extend(resp.get("items") or [])
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return items

    def get_calendar_timezone(self) -> str:
        """Return the calendar's timezone id (e.g., 'America/Los_Angeles')."""
        try:
            cal = self.service.calendars().get(calendarId=self.calendar_id).execute()
            tz = (cal or {}).get("timeZone")
            return tz or "UTC"
        except Exception:
            return "UTC"

    def create_recurring_time_block_event(
        self,
        *,
        title: str,
        description: Optional[str],
        start_dt_iso: str,
        end_dt_iso: str,
        time_zone: str,
        rrule: str,
        time_block_id: str,
    ) -> dict:
        """Create a recurring event that represents a user time block.

        Important: this event is intentionally NOT marked qzWhatNext-managed, so it is treated as reserved time.
        """
        event_body = {
            "summary": title,
            "description": description or "",
            "start": {"dateTime": start_dt_iso, "timeZone": time_zone},
            "end": {"dateTime": end_dt_iso, "timeZone": time_zone},
            "recurrence": [f"RRULE:{rrule}"],
            "extendedProperties": {
                "private": {
                    PRIVATE_KEY_TIME_BLOCK_ID: time_block_id,
                }
            },
        }
        try:
            return self.service.events().insert(calendarId=self.calendar_id, body=event_body).execute()
        except HttpError as error:
            raise Exception(f"Failed to create recurring time block event: {error}") from error
    
    def create_events_from_blocks(
        self,
        blocks: List[ScheduledBlock],
        tasks: Optional[dict[str, Task]] = None
    ) -> List[dict]:
        """Create multiple Google Calendar events from ScheduledBlocks.
        
        Args:
            blocks: List of ScheduledBlocks to create events from
            tasks: Optional dictionary mapping task_id -> Task for metadata
            
        Returns:
            List of created event dictionaries
        """
        events = []
        tasks_dict = tasks or {}
        
        for block in blocks:
            if block.entity_type == EntityType.TASK:
                task = tasks_dict.get(block.entity_id)
                event = self.create_event_from_block(block, task)
                events.append(event)
        
        return events
    
    def get_free_busy(
        self,
        start_time: datetime,
        end_time: datetime
    ) -> dict:
        """Get free/busy information for calendar (for future use).
        
        Args:
            start_time: Start of time range
            end_time: End of time range
            
        Returns:
            Free/busy response from Google Calendar API
        """
        try:
            body = {
                'timeMin': start_time.isoformat() + 'Z',
                'timeMax': end_time.isoformat() + 'Z',
                'items': [{'id': self.calendar_id}]
            }
            
            freebusy = self.service.freebusy().query(body=body).execute()
            return freebusy
        except HttpError as error:
            raise Exception(f"Failed to get free/busy info: {error}") from error

