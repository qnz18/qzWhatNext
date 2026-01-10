"""Google Sheets integration for qzWhatNext."""

import os
import re
import logging
from datetime import datetime
from typing import List, Optional
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from dotenv import load_dotenv
import uuid

from qzwhatnext.models.task import Task, TaskStatus, TaskCategory, EnergyIntensity
from qzwhatnext.models.task_factory import create_task_base, determine_ai_exclusion
from qzwhatnext.models.constants import DEFAULT_DURATION_MINUTES

load_dotenv()

logger = logging.getLogger(__name__)

# Google Sheets API scopes
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']

# Default column mapping (can be customized)
DEFAULT_COLUMNS = {
    'title': 'A',
    'notes': 'B',
    'deadline': 'C',
    'duration': 'D',
    'category': 'E',
}


def extract_spreadsheet_id(spreadsheet_input: str) -> str:
    """Extract spreadsheet ID from a URL or return the ID if already extracted.
    
    Supports various Google Sheets URL formats:
    - Full URL: https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit
    - Copy link URL: https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit?usp=sharing
    - Short URL: docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit
    - Just the ID: SPREADSHEET_ID
    
    Args:
        spreadsheet_input: Either a full Google Sheets URL (from "Copy link") or just the spreadsheet ID
        
    Returns:
        The spreadsheet ID
        
    Raises:
        ValueError: If the spreadsheet ID cannot be extracted
    """
    # Strip whitespace
    spreadsheet_input = spreadsheet_input.strip()
    
    # If it looks like just an ID (alphanumeric, dashes, underscores), return as-is
    if re.match(r'^[a-zA-Z0-9_-]+$', spreadsheet_input):
        return spreadsheet_input
    
    # Try to extract ID from URL patterns (handles various URL formats)
    patterns = [
        r'/spreadsheets/d/([a-zA-Z0-9_-]+)',  # Standard format
        r'spreadsheets/d/([a-zA-Z0-9_-]+)',   # Without leading slash
        r'd/([a-zA-Z0-9_-]+)',                # Short pattern
    ]
    
    for pattern in patterns:
        match = re.search(pattern, spreadsheet_input)
        if match:
            return match.group(1)
    
    raise ValueError(
        f"Could not extract spreadsheet ID from: {spreadsheet_input}. "
        "Please provide either the full Google Sheets URL (from 'Copy link' button) "
        "or just the spreadsheet ID (e.g., '1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms')"
    )


class GoogleSheetsClient:
    """Client for Google Sheets API integration."""
    
    def __init__(
        self,
        credentials_path: Optional[str] = None,
        token_path: str = "sheets_token.json"
    ):
        """Initialize Google Sheets client.
        
        Args:
            credentials_path: Path to OAuth2 credentials JSON file.
                             If None, reads from GOOGLE_SHEETS_CREDENTIALS_PATH env var.
            token_path: Path to store OAuth2 token (defaults to 'sheets_token.json').
        """
        self.credentials_path = credentials_path or os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "credentials.json")
        self.token_path = token_path
        self.service = None
        self._authenticate()
    
    def _authenticate(self):
        """Authenticate with Google Sheets API."""
        creds = None
        
        # Load existing token if available
        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
        
        # If no valid credentials, get new ones
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired Google Sheets credentials...")
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_path):
                    raise FileNotFoundError(
                        f"Google Sheets credentials not found at {self.credentials_path}. "
                        "Please download OAuth2 credentials from Google Cloud Console."
                    )
                
                logger.info("\n" + "="*60)
                logger.info("Google Sheets OAuth Authentication Required")
                logger.info("="*60)
                logger.info("A browser window will open for authentication.")
                logger.info("If no browser opens, visit the URL shown below.")
                logger.info("This may take a moment...")
                logger.info("="*60 + "\n")
                
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, SCOPES
                )
                # Use fixed port 8080 for OAuth redirect URI matching
                # Make sure http://localhost:8080/ is in authorized redirect URIs in Google Cloud Console
                try:
                    creds = flow.run_local_server(port=8080, open_browser=True)
                    logger.info("\n✓ Authentication successful!\n")
                except Exception as e:
                    logger.error(f"\n✗ Authentication failed: {e}\n")
                    raise Exception(
                        f"OAuth authentication failed: {str(e)}. "
                        "Please ensure http://localhost:8080/ is in your authorized redirect URIs in Google Cloud Console."
                    )
            
            # Save credentials for next run
            with open(self.token_path, 'w') as token:
                token.write(creds.to_json())
            logger.info(f"Credentials saved to {self.token_path}\n")
        
        self.creds = creds
        self.service = build('sheets', 'v4', credentials=creds)
    
    def import_tasks(
        self,
        spreadsheet_id: str,
        range_name: str = "Sheet1!A1:E10",
        has_header: bool = True
    ) -> List[Task]:
        """Import tasks from Google Sheets.
        
        Args:
            spreadsheet_id: The ID of the Google Sheet or full URL (from "Copy link" button)
            range_name: A1 notation range to read (e.g., 'Sheet1!A1:E10', default: 'Sheet1!A1:E10')
            has_header: Whether the first row contains headers
        
        Returns:
            List of Task objects
        """
        try:
            # Extract spreadsheet ID from URL if needed
            extracted_id = extract_spreadsheet_id(spreadsheet_id)
            
            # Read data from sheet
            sheet = self.service.spreadsheets()
            result = sheet.values().get(
                spreadsheetId=extracted_id,
                range=range_name
            ).execute()
            
            values = result.get('values', [])
            
            if not values:
                return []
            
            # Skip header row if present
            start_idx = 1 if has_header else 0
            rows = values[start_idx:]
            
            tasks = []
            now = datetime.utcnow()
            
            for row in rows:
                if not row or not row[0]:  # Skip empty rows
                    continue
                
                try:
                    # Parse row (assuming simple column order: title, notes, deadline, duration, category)
                    title = row[0].strip() if len(row) > 0 else ""
                    notes = row[1].strip() if len(row) > 1 else None
                    deadline_str = row[2].strip() if len(row) > 2 else None
                    duration_str = row[3].strip() if len(row) > 3 else None
                    category_str = row[4].strip() if len(row) > 4 else None
                    
                    if not title:
                        continue
                    
                    # Parse deadline
                    deadline = None
                    if deadline_str:
                        try:
                            # Try parsing common date formats
                            deadline = datetime.fromisoformat(deadline_str.replace('Z', '+00:00'))
                        except (ValueError, AttributeError):
                            try:
                                from dateutil import parser
                                deadline = parser.parse(deadline_str)
                            except:
                                pass  # If parsing fails, leave as None
                    
                    # Parse duration
                    estimated_duration_min = DEFAULT_DURATION_MINUTES
                    if duration_str:
                        try:
                            estimated_duration_min = int(duration_str)
                        except (ValueError, TypeError):
                            pass
                    
                    # Parse category
                    category = TaskCategory.UNKNOWN
                    if category_str:
                        try:
                            category = TaskCategory(category_str.lower())
                        except (ValueError, KeyError):
                            # Handle legacy category values
                            legacy_mapping = {
                                'social': TaskCategory.FAMILY,
                                'stress': TaskCategory.PERSONAL,
                                'other': TaskCategory.UNKNOWN,
                            }
                            category = legacy_mapping.get(category_str.lower(), TaskCategory.UNKNOWN)
                    
                    # Check for AI exclusion (period prefix)
                    ai_excluded = determine_ai_exclusion(title) if title else False
                    
                    # Create task using factory
                    task = create_task_base(
                        source_type="google_sheets",
                        source_id=None,  # Could use row number or other identifier
                        title=title,
                        notes=notes,
                        deadline=deadline,
                        estimated_duration_min=estimated_duration_min,
                        category=category,
                        ai_excluded=ai_excluded,
                    )
                    
                    tasks.append(task)
                    
                except Exception as e:
                    # Log error but continue processing other rows
                    logger.warning(f"Error parsing row (continuing with next row): {type(e).__name__}: {str(e)[:100]}")
                    continue
            
            return tasks
            
        except HttpError as e:
            error_details = e.error_details if hasattr(e, 'error_details') else str(e)
            status_code = e.resp.status if hasattr(e, 'resp') else None
            
            if status_code == 404:
                raise Exception(
                    f"Spreadsheet not found. Please check that the spreadsheet ID is correct "
                    f"and that you have access to the spreadsheet. Error: {error_details}"
                )
            elif status_code == 403:
                raise Exception(
                    f"Permission denied. Please ensure you have access to the spreadsheet "
                    f"and that your Google account has the necessary permissions. Error: {error_details}"
                )
            else:
                raise Exception(f"Failed to import from Google Sheets (HTTP {status_code}): {error_details}")
        except ValueError as e:
            # Re-raise ValueError from extract_spreadsheet_id
            raise
        except Exception as e:
            raise Exception(f"Unexpected error importing from Google Sheets: {str(e)}")

