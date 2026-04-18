"""OpenAI API integration for qzWhatNext.

This module provides OpenAI API integration for AI-assisted task attribute inference:
category, title, duration, and optional temporal fields (deadline, start_after, due_by) from notes.
"""

import os
import json
import logging
from typing import Any, Dict, Tuple, Optional
from openai import OpenAI, APIError
from dotenv import load_dotenv

from qzwhatnext.models.task import TaskCategory

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# OpenAI model to use for category inference
# Using gpt-4o-mini as it's the cheapest option for testing (~$0.15/$0.60 per million tokens)
OPENAI_MODEL = "gpt-4o-mini"

# Category inference prompt template
CATEGORY_PROMPT_TEMPLATE = """You are a task categorization assistant. Given a task note, determine the best matching category.

Available categories:
- WORK: Professional work, job-related tasks, meetings, deadlines
- CHILD: Childcare, school activities, children's needs
- FAMILY: Family activities, social commitments with family
- HEALTH: Personal health, medical appointments, exercise, wellness
- PERSONAL: Personal development, hobbies, individual activities
- IDEAS: Creative ideas, projects, brainstorming
- HOME: Home maintenance, household chores, repairs
- ADMIN: Administrative tasks, paperwork, bureaucracy
- UNKNOWN: If the note doesn't clearly fit any category or is ambiguous

Task note: "{notes}"

Respond with a JSON object containing:
- "category": One of the category names above (e.g., "WORK", "HEALTH")
- "confidence": A number between 0.0 and 1.0 indicating your confidence in the category assignment

Example response:
{{"category": "WORK", "confidence": 0.9}}

Respond only with the JSON object, no other text."""

# Title generation prompt template
TITLE_PROMPT_TEMPLATE = """You are a task title generation assistant. Given a task note, create a concise, actionable title.

Task note: "{notes}"

Generate a clear, descriptive title that summarizes the task. The title should be:
- Concise (maximum {max_length} characters)
- Actionable and clear
- Not just a copy of the notes, but a summary
- Suitable for display in a task list

Respond with only the title text, nothing else."""

# Duration estimation prompt template
DURATION_PROMPT_TEMPLATE = """You are a task duration estimation assistant. Given a task note, estimate how long it will take to complete the task.

Task note: "{notes}"

Provide a realistic estimate in minutes for completing this task. Consider:
- The complexity and scope of the task
- Typical time needed for similar tasks
- Preparation, execution, and any follow-up work

Respond with a JSON object containing:
- "duration_min": An integer representing the estimated duration in minutes
- "confidence": A number between 0.0 and 1.0 indicating your confidence in the estimate

Example responses:
- Quick task like "Schedule doctor appointment": {{"duration_min": 15, "confidence": 0.9}}
- Medium task like "Complete quarterly report": {{"duration_min": 120, "confidence": 0.8}}
- Complex task like "Plan family vacation": {{"duration_min": 180, "confidence": 0.7}}

Respond only with the JSON object, no other text."""

# Temporal fields (deadline, start_after, due_by) for add_smart — structured JSON only
TEMPORAL_PROMPT_TEMPLATE = """You extract scheduling hints from a task note. Use the anchor time and timezone to interpret relative phrases (e.g. "tomorrow", "next Friday").

Task note: "{notes}"

Anchor time (ISO 8601 UTC): {anchor_iso}
User timezone (IANA): {time_zone}

Rules:
- "start_after": YYYY-MM-DD — earliest calendar day the user may *start* this work (e.g. "not until Monday", "after April 10"). Omit or null if not stated or unclear.
- "due_by": YYYY-MM-DD — soft target day to finish when there is no specific clock cutoff. Omit or null if not stated or unclear.
- "deadline": ISO 8601 string with offset or Z — use ONLY when the note implies a real clock-time cutoff (e.g. "by 5pm Tuesday", "flight at 14:30"). If the note only names a day without a time, use due_by instead — do NOT invent a deadline time.
- For each of the three fields you output, include a confidence 0.0–1.0. Use 0.0 if the field is null/absent.

Respond with ONLY valid JSON in this exact shape (use null for unknown fields):
{{
  "deadline": null or string,
  "start_after": null or "YYYY-MM-DD",
  "due_by": null or "YYYY-MM-DD",
  "deadline_confidence": number,
  "start_after_confidence": number,
  "due_by_confidence": number
}}"""


class OpenAIClient:
    """Client for OpenAI API integration."""
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize OpenAI client.
        
        Args:
            api_key: OpenAI API key. If None, reads from OPENAI_API_KEY environment variable.
            
        Note:
            If API key is not provided and not found in environment, the client will still
            initialize but will fail on API calls. This allows graceful degradation.
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.client = None
        
        if self.api_key:
            self.client = OpenAI(api_key=self.api_key)
        else:
            logger.warning("OPENAI_API_KEY not found in environment. OpenAI inference will not be available.")
    
    def infer_category(self, notes: str) -> Tuple[TaskCategory, float]:
        """Infer task category from notes using OpenAI API.
        
        Args:
            notes: Task notes/description to analyze
            
        Returns:
            Tuple of (TaskCategory, confidence_score) where confidence is 0.0-1.0.
            Returns (TaskCategory.UNKNOWN, 0.0) if:
            - API key is not configured
            - API call fails
            - Response parsing fails
            - Confidence is below threshold
        """
        # Check if client is available
        if not self.client:
            logger.debug("OpenAI client not initialized. Returning UNKNOWN category.")
            return (TaskCategory.UNKNOWN, 0.0)
        
        # Handle empty notes
        if not notes or not notes.strip():
            logger.debug("Empty notes provided. Returning UNKNOWN category.")
            return (TaskCategory.UNKNOWN, 0.0)
        
        try:
            # Prepare prompt
            prompt = CATEGORY_PROMPT_TEMPLATE.format(notes=notes)
            
            # Call OpenAI API
            response = self.client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "You are a task categorization assistant. Respond only with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # Lower temperature for more deterministic responses
                max_tokens=100,   # JSON response is short
            )
            
            # Extract response content
            response_content = response.choices[0].message.content.strip()
            
            # Parse JSON response
            try:
                # Handle cases where response might have markdown code blocks
                if response_content.startswith("```json"):
                    response_content = response_content[7:]  # Remove ```json
                if response_content.startswith("```"):
                    response_content = response_content[3:]   # Remove ```
                if response_content.endswith("```"):
                    response_content = response_content[:-3]  # Remove trailing ```
                response_content = response_content.strip()
                
                result = json.loads(response_content)
                category_str = result.get("category", "").upper()
                confidence = float(result.get("confidence", 0.0))
                
                # Validate confidence range
                if confidence < 0.0 or confidence > 1.0:
                    logger.warning(f"Invalid confidence value {confidence} from OpenAI. Using 0.0.")
                    confidence = 0.0
                
                # Map to TaskCategory enum
                try:
                    category = TaskCategory(category_str.lower())
                except ValueError:
                    logger.warning(f"Invalid category '{category_str}' from OpenAI. Returning UNKNOWN.")
                    return (TaskCategory.UNKNOWN, 0.0)
                
                logger.debug(f"OpenAI inferred category: {category.value} with confidence {confidence}")
                return (category, confidence)
                
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse OpenAI JSON response: {e}. Response: {response_content[:100]}")
                return (TaskCategory.UNKNOWN, 0.0)
            
        except APIError as e:
            # Handle OpenAI API errors (rate limits, quota issues, invalid key, etc.)
            error_code = getattr(e, 'code', None)
            status_code = getattr(e, 'status_code', None)
            
            if error_code == 'insufficient_quota':
                logger.warning("OpenAI API quota insufficient. Please check billing/payment method in OpenAI dashboard.")
            elif status_code == 429:
                logger.warning("OpenAI API rate limit exceeded. Please wait before retrying.")
            else:
                logger.error(f"OpenAI API error: {status_code or 'unknown'} ({error_code or 'unknown'})")
            
            # Don't log full error message as it might contain sensitive info
            return (TaskCategory.UNKNOWN, 0.0)
        except Exception as e:
            # Handle any other errors (network, parsing, etc.)
            logger.error(f"Error calling OpenAI API: {type(e).__name__}")
            # Don't log full error message as it might contain sensitive info
            return (TaskCategory.UNKNOWN, 0.0)
    
    def generate_title(self, notes: str, max_length: int = 100) -> str:
        """Generate a concise title from task notes using OpenAI API.
        
        Args:
            notes: Task notes/description to generate title from
            max_length: Maximum length of the generated title (default: 100)
            
        Returns:
            Generated title string, or empty string if:
            - API key is not configured
            - API call fails
            - Notes are empty
            - Response is invalid
        """
        # Check if client is available
        if not self.client:
            logger.debug("OpenAI client not initialized. Returning empty title.")
            return ""
        
        # Handle empty notes
        if not notes or not notes.strip():
            logger.debug("Empty notes provided. Returning empty title.")
            return ""
        
        try:
            # Prepare prompt
            prompt = TITLE_PROMPT_TEMPLATE.format(notes=notes, max_length=max_length)
            
            # Call OpenAI API
            response = self.client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "You are a task title generation assistant. Respond with only the title text."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5,  # Slightly higher for more creative titles
                max_tokens=50,    # Titles should be short
            )
            
            # Extract response content
            title = response.choices[0].message.content.strip()
            
            # Clean up title (remove quotes if present, trim whitespace)
            if title.startswith('"') and title.endswith('"'):
                title = title[1:-1]
            if title.startswith("'") and title.endswith("'"):
                title = title[1:-1]
            title = title.strip()
            
            # Enforce max length (truncate if needed)
            if len(title) > max_length:
                title = title[:max_length].rstrip()
                logger.debug(f"Title truncated to {max_length} characters")
            
            if not title:
                logger.warning("OpenAI returned empty title")
                return ""
            
            logger.debug(f"OpenAI generated title: {title[:50]}...")
            return title
            
        except APIError as e:
            # Handle OpenAI API errors (rate limits, quota issues, invalid key, etc.)
            error_code = getattr(e, 'code', None)
            status_code = getattr(e, 'status_code', None)
            
            if error_code == 'insufficient_quota':
                logger.warning("OpenAI API quota insufficient for title generation. Please check billing/payment method in OpenAI dashboard.")
            elif status_code == 429:
                logger.warning("OpenAI API rate limit exceeded for title generation. Please wait before retrying.")
            else:
                logger.error(f"OpenAI API error during title generation: {status_code or 'unknown'} ({error_code or 'unknown'})")
            
            # Don't log full error message as it might contain sensitive info
            return ""
        except Exception as e:
            # Handle any other errors (network, parsing, etc.)
            logger.error(f"Error generating title with OpenAI API: {type(e).__name__}")
            # Don't log full error message as it might contain sensitive info
            return ""
    
    def estimate_duration(self, notes: str) -> Tuple[int, float]:
        """Estimate task duration from notes using OpenAI API.
        
        Args:
            notes: Task notes/description to analyze
            
        Returns:
            Tuple of (duration_minutes, confidence_score) where:
            - duration_minutes is an integer in minutes (0 if estimation failed)
            - confidence is 0.0-1.0
            
            Returns (0, 0.0) if:
            - API key is not configured
            - API call fails
            - Response parsing fails
            - Notes are empty
        """
        # Check if client is available
        if not self.client:
            logger.debug("OpenAI client not initialized. Returning duration 0.")
            return (0, 0.0)
        
        # Handle empty notes
        if not notes or not notes.strip():
            logger.debug("Empty notes provided. Returning duration 0.")
            return (0, 0.0)
        
        try:
            # Prepare prompt
            prompt = DURATION_PROMPT_TEMPLATE.format(notes=notes)
            
            # Call OpenAI API
            response = self.client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "You are a task duration estimation assistant. Respond only with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,  # Lower temperature for more deterministic responses
                max_tokens=100,   # JSON response is short
            )
            
            # Extract response content
            response_content = response.choices[0].message.content.strip()
            
            # Parse JSON response
            try:
                # Handle cases where response might have markdown code blocks
                if response_content.startswith("```json"):
                    response_content = response_content[7:]  # Remove ```json
                if response_content.startswith("```"):
                    response_content = response_content[3:]   # Remove ```
                if response_content.endswith("```"):
                    response_content = response_content[:-3]  # Remove trailing ```
                response_content = response_content.strip()
                
                result = json.loads(response_content)
                duration_min = int(result.get("duration_min", 0))
                confidence = float(result.get("confidence", 0.0))
                
                # Validate duration is positive
                if duration_min < 0:
                    logger.warning(f"Invalid duration value {duration_min} from OpenAI. Using 0.")
                    return (0, 0.0)
                
                # Validate confidence range
                if confidence < 0.0 or confidence > 1.0:
                    logger.warning(f"Invalid confidence value {confidence} from OpenAI. Using 0.0.")
                    confidence = 0.0
                
                logger.debug(f"OpenAI estimated duration: {duration_min} minutes with confidence {confidence}")
                return (duration_min, confidence)
                
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse OpenAI JSON response for duration: {e}. Response: {response_content[:100]}")
                return (0, 0.0)
            
        except APIError as e:
            # Handle OpenAI API errors (rate limits, quota issues, invalid key, etc.)
            error_code = getattr(e, 'code', None)
            status_code = getattr(e, 'status_code', None)
            
            if error_code == 'insufficient_quota':
                logger.warning("OpenAI API quota insufficient for duration estimation. Please check billing/payment method in OpenAI dashboard.")
            elif status_code == 429:
                logger.warning("OpenAI API rate limit exceeded for duration estimation. Please wait before retrying.")
            else:
                logger.error(f"OpenAI API error during duration estimation: {status_code or 'unknown'} ({error_code or 'unknown'})")
            
            # Don't log full error message as it might contain sensitive info
            return (0, 0.0)
        except Exception as e:
            # Handle any other errors (network, parsing, etc.)
            logger.error(f"Error estimating duration with OpenAI API: {type(e).__name__}")
            # Don't log full error message as it might contain sensitive info
            return (0, 0.0)

    def infer_temporal_fields(
        self,
        notes: str,
        *,
        anchor_iso: str,
        time_zone: str,
    ) -> Dict[str, Any]:
        """Infer optional deadline, start_after, due_by from notes (structured JSON).

        Returns a dict with keys deadline (str|None), start_after (str|None), due_by (str|None),
        and *_confidence floats. On failure returns all-null fields and zero confidences.
        """
        empty: Dict[str, Any] = {
            "deadline": None,
            "start_after": None,
            "due_by": None,
            "deadline_confidence": 0.0,
            "start_after_confidence": 0.0,
            "due_by_confidence": 0.0,
        }
        if not self.client:
            logger.debug("OpenAI client not initialized. Skipping temporal inference.")
            return dict(empty)
        if not notes or not notes.strip():
            logger.debug("Empty notes. Skipping temporal inference.")
            return dict(empty)

        try:
            prompt = TEMPORAL_PROMPT_TEMPLATE.format(
                notes=notes,
                anchor_iso=anchor_iso,
                time_zone=time_zone,
            )
            response = self.client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You extract dates from task notes. Respond only with valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=400,
            )
            response_content = response.choices[0].message.content.strip()
            if response_content.startswith("```json"):
                response_content = response_content[7:]
            if response_content.startswith("```"):
                response_content = response_content[3:]
            if response_content.endswith("```"):
                response_content = response_content[:-3]
            response_content = response_content.strip()

            result = json.loads(response_content)
            out = dict(empty)
            for key in ("deadline", "start_after", "due_by"):
                v = result.get(key)
                out[key] = v if v else None
            for key in ("deadline_confidence", "start_after_confidence", "due_by_confidence"):
                try:
                    c = float(result.get(key, 0.0))
                    if c < 0.0 or c > 1.0:
                        c = 0.0
                    out[key] = c
                except (TypeError, ValueError):
                    out[key] = 0.0
            return out
        except APIError as e:
            error_code = getattr(e, "code", None)
            status_code = getattr(e, "status_code", None)
            if error_code == "insufficient_quota":
                logger.warning("OpenAI quota insufficient for temporal inference.")
            elif status_code == 429:
                logger.warning("OpenAI rate limit for temporal inference.")
            else:
                logger.error(f"OpenAI API error (temporal): {status_code or 'unknown'}")
            return dict(empty)
        except Exception as e:
            logger.error(f"Error in temporal inference: {type(e).__name__}")
            return dict(empty)

