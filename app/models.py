from typing import Literal, TypedDict, Optional
from datetime import datetime


Domain = Literal[
    "HEALTH_FITNESS",
    "MEAL_FOOD",
    "WORK",
    "FAMILY_KIDS",
    "HOME_MAINTENANCE",
    "FINANCE_ADMIN",
    "PERSONAL_DEV",
    "OTHER",
]

Urgency = Literal["URGENT", "NEAR_TERM", "SOON", "SOMEDAY"]
Effort = Literal["TINY", "SMALL", "MEDIUM", "LARGE"]
Impact = Literal["LOW", "MEDIUM", "HIGH"]


class TaskRaw(TypedDict):
    id: str
    content: str
    description: str
    due: Optional[str]  # ISO8601 string or None
    priority: int
    labels: list[str]
    project_id: str
    created_at: str  # ISO8601


class TaskCategorized(TaskRaw):
    domain: Domain
    urgency: Urgency
    effort: Effort
    impact: Impact