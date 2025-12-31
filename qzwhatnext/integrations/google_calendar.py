"""Google Calendar integration for qzWhatNext."""

import os
from datetime import datetime
from typing import List, Optional
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


class GoogleCalendarClient:
    """Client for Google Calendar API integration."""
    
    def __init__(
        self,
        credentials_path: Optional[str] = None,
        calendar_id: Optional[str] = None,
        token_path: str = "token.json"
    ):
        """Initialize Google Calendar client.
        
        Args:
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
                # For Web app credentials, ensure http://localhost is in authorized redirect URIs
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, SCOPES
                )
                creds = flow.run_local_server(port=0)
            
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
                    'qzwhatnext_task_id': block.entity_id,
                    'qzwhatnext_block_id': block.id,
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

