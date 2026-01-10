"""OpenAI API integration for qzWhatNext.

This module provides OpenAI API integration for AI-assisted task attribute inference,
specifically for category inference and title generation from task notes.
"""

import os
import json
import logging
from typing import Tuple, Optional
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

