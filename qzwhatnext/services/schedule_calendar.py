"""Schedule build + Google Calendar sync (shared by API routes and internal jobs)."""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials as GoogleCredentials
from sqlalchemy.orm import Session

from qzwhatnext.database.google_oauth_token_repository import (
    GoogleOAuthTokenRepository,
    decrypt_secret,
)
from qzwhatnext.database.repository import TaskRepository
from qzwhatnext.database.scheduled_block_repository import ScheduledBlockRepository
from qzwhatnext.database.user_repository import UserRepository
from qzwhatnext.engine.ranking import stack_rank
from qzwhatnext.engine.scheduler import schedule_tasks
from qzwhatnext.integrations.google_calendar import (
    GoogleCalendarClient,
    PRIVATE_KEY_BLOCK_ID,
    PRIVATE_KEY_MANAGED,
    PRIVATE_KEY_TASK_ID,
)
from qzwhatnext.models.scheduled_block import ScheduledBlock
from qzwhatnext.models.task import Task
from qzwhatnext.recurrence.materialize import materialize_recurring_tasks

logger = logging.getLogger(__name__)

INTERNAL_JOB_SECRET_HEADER = "X-qzwhatnext-job-secret"


def _parse_rfc3339(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except Exception:
        return None


def _to_utc_naive(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _to_rfc3339_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _event_private(event: dict) -> dict:
    return ((event.get("extendedProperties") or {}).get("private") or {})


def _event_time_window_utc_naive(event: dict) -> Optional[Tuple[datetime, datetime]]:
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


def _build_task_titles_dict(tasks: List[Task], scheduled_blocks: List[ScheduledBlock]) -> Dict[str, str]:
    task_dict = {task.id: task for task in tasks}
    task_titles: Dict[str, str] = {}
    for block in scheduled_blocks:
        if block.entity_type == "task" and block.entity_id in task_dict:
            task_titles[block.entity_id] = task_dict[block.entity_id].title
    return task_titles


def config_schedule_horizon_days() -> int:
    raw = os.getenv("QZ_SCHEDULE_HORIZON_DAYS", "7").strip()
    try:
        h = int(raw)
    except ValueError:
        h = 7
    if h not in (7, 14, 30):
        return 7
    return h


def _calendar_client_for_user(db: Session, user_id: str) -> Tuple[GoogleCalendarClient, GoogleOAuthTokenRepository]:
    token_repo = GoogleOAuthTokenRepository(db)
    token_row = token_repo.get_google_calendar(user_id)
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
        logger.warning("Google Calendar refresh failed for user %s: %s: %s", user_id, type(e).__name__, str(e))
        msg = str(e).lower()
        if "invalid_grant" in msg or "expired" in msg or "revoked" in msg:
            try:
                token_repo.delete_google_calendar(user_id)
            except Exception:
                pass
        raise HTTPException(
            status_code=400,
            detail=(
                "Google Calendar authorization expired or was revoked. "
                "Reconnect via /auth/google/calendar/auth-url (or click Sync in the UI)."
            ),
        ) from e

    return GoogleCalendarClient(credentials=creds, calendar_id="primary"), token_repo


def build_schedule_for_user(db: Session, user_id: str, horizon_days: int) -> Dict:
    """Build and persist schedule. Returns a dict suitable for ScheduleResponse."""
    task_repo = TaskRepository(db)
    schedule_repo = ScheduledBlockRepository(db)

    schedule_start = datetime.utcnow()
    horizon_days = int(horizon_days or 7)
    if horizon_days not in (7, 14, 30):
        raise HTTPException(status_code=400, detail="horizon_days must be one of: 7, 14, 30")
    schedule_end = schedule_start + timedelta(days=min(horizon_days, 30))

    try:
        materialize_recurring_tasks(
            db,
            user_id=user_id,
            window_start=schedule_start,
            window_end=schedule_end,
        )
    except Exception:
        pass

    tasks = task_repo.get_open(user_id)

    if not tasks:
        raise HTTPException(status_code=400, detail="No tasks available. Create tasks first.")

    try:
        calendar_client, _token_repo = _calendar_client_for_user(db, user_id)

        calendar_tz_raw = calendar_client.get_calendar_timezone()
        calendar_tz = "UTC"
        try:
            tz_candidate = str(calendar_tz_raw) if calendar_tz_raw else "UTC"
            ZoneInfo(tz_candidate)
            calendar_tz = tz_candidate
        except Exception:
            calendar_tz = "UTC"

        existing_blocks = schedule_repo.get_all(user_id)
        locked_blocks = [b for b in existing_blocks if b.locked]
        unlocked_blocks = [b for b in existing_blocks if not b.locked]

        unlocked_by_task: Dict[str, List[ScheduledBlock]] = {}
        for b in unlocked_blocks:
            if b.entity_type == "task":
                unlocked_by_task.setdefault(b.entity_id, []).append(b)
        for tid in unlocked_by_task:
            unlocked_by_task[tid].sort(key=lambda b: b.start_time)

        reserved_intervals: List[Tuple[datetime, datetime]] = [(b.start_time, b.end_time) for b in locked_blocks]

        try:
            events = calendar_client.list_events_in_range(
                time_min_rfc3339=_to_rfc3339_z(schedule_start),
                time_max_rfc3339=_to_rfc3339_z(schedule_end),
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
            raise HTTPException(status_code=400, detail="Failed to read calendar availability. Try again.")

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

        ranked_tasks = stack_rank(tasks_with_start_after, now=schedule_start, time_zone=calendar_tz)

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

        schedule_repo.delete_unlocked_for_user(user_id)
        schedule_repo.create_batch(schedule_result.scheduled_blocks)

        combined_blocks = sorted(locked_blocks + schedule_result.scheduled_blocks, key=lambda b: b.start_time)

        task_titles = _build_task_titles_dict(tasks, combined_blocks)

        return {
            "scheduled_blocks": combined_blocks,
            "overflow_tasks": schedule_result.overflow_tasks,
            "start_time": schedule_result.start_time,
            "task_titles": task_titles,
            "time_zone": calendar_tz,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to build schedule: %s: %s", type(e).__name__, str(e))
        raise HTTPException(status_code=500, detail=f"Failed to build schedule: {str(e)}") from e


def _sync_window_from_blocks_or_horizon(
    blocks: List[ScheduledBlock], horizon_days: int
) -> Tuple[datetime, datetime]:
    """UTC-naive [window_start, window_end] for orphan scan (inclusive padding)."""
    h = min(int(horizon_days), 30)
    if blocks:
        starts = [b.start_time for b in blocks if b.start_time]
        ends = [b.end_time for b in blocks if b.end_time]
        if starts and ends:
            window_start = min(starts) - timedelta(days=2)
            window_end = max(ends) + timedelta(days=2)
            return window_start, window_end
    schedule_start = datetime.utcnow()
    schedule_end = schedule_start + timedelta(days=h)
    return schedule_start - timedelta(days=2), schedule_end + timedelta(days=2)


def _run_orphan_managed_event_cleanup(
    calendar_client: GoogleCalendarClient,
    *,
    current_block_ids: set,
    window_start: datetime,
    window_end: datetime,
) -> int:
    deleted = 0
    try:
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
                deleted += 1
    except Exception:
        pass
    return deleted


def sync_calendar_for_user(db: Session, user_id: str, horizon_days: int) -> Dict:
    """Sync DB schedule to Google Calendar and return dict for SyncResponse."""
    schedule_repo = ScheduledBlockRepository(db)
    task_repo = TaskRepository(db)

    blocks = schedule_repo.get_all(user_id)

    try:
        calendar_client, _token_repo = _calendar_client_for_user(db, user_id)
        tasks = task_repo.get_all(user_id)
        tasks_dict = {task.id: task for task in tasks}
        current_block_ids = {b.id for b in blocks}

        def _is_managed_event_for_block(event: dict, block_id: str) -> bool:
            priv = _event_private(event)
            return priv.get(PRIVATE_KEY_MANAGED) == "1" and priv.get(PRIVATE_KEY_BLOCK_ID) == block_id

        def _needs_patch(event: dict, *, desired: dict) -> bool:
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

        ws, we = _sync_window_from_blocks_or_horizon(blocks, horizon_days)
        orphans_deleted = _run_orphan_managed_event_cleanup(
            calendar_client,
            current_block_ids=current_block_ids,
            window_start=ws,
            window_end=we,
        )

        for block in blocks:
            if block.entity_type != "task":
                continue

            task = tasks_dict.get(block.entity_id)
            if task is None:
                continue

            try:
                event = None
                event_id = block.calendar_event_id

                if event_id:
                    event = calendar_client.get_event(event_id)
                    if event is None or (isinstance(event, dict) and event.get("status") == "cancelled"):
                        schedule_repo.update_calendar_sync_metadata(
                            user_id,
                            block.id,
                            calendar_event_id=None,
                            calendar_event_etag=None,
                            calendar_event_updated_at=None,
                        )
                        event_id = None
                        event = None

                if event is None and not event_id:
                    event = calendar_client.find_event_by_block_id(block.id)
                    if event is not None:
                        priv = _event_private(event)
                        if priv.get(PRIVATE_KEY_BLOCK_ID) == block.id:
                            event_id = event.get("id")
                        else:
                            event = None
                            event_id = None

                if event is None:
                    created = calendar_client.create_event_from_block(block, task)
                    event_id = created.get("id")
                    events_created += 1
                    if event_id:
                        event_ids.append(event_id)
                    schedule_repo.update_calendar_sync_metadata(
                        user_id,
                        block.id,
                        calendar_event_id=event_id,
                        calendar_event_etag=created.get("etag"),
                        calendar_event_updated_at=_to_utc_naive(_parse_rfc3339(created.get("updated"))),
                    )
                    continue

                if not event_id:
                    continue

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

                if not _is_managed_event_for_block(event, block.id):
                    continue

                if block.calendar_event_id != event_id:
                    schedule_repo.update_calendar_sync_metadata(
                        user_id,
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
                    schedule_repo.update_calendar_sync_metadata(
                        user_id,
                        block.id,
                        calendar_event_id=event_id,
                        calendar_event_etag=event_etag,
                        calendar_event_updated_at=event_updated_at,
                    )

                if calendar_changed:
                    start_str = (event.get("start") or {}).get("dateTime")
                    end_str = (event.get("end") or {}).get("dateTime")
                    if start_str and end_str:
                        ev_start = _to_utc_naive(_parse_rfc3339(start_str))
                        ev_end = _to_utc_naive(_parse_rfc3339(end_str))
                        if ev_start and ev_end:
                            time_changed = ev_start != block.start_time or ev_end != block.end_time
                            schedule_repo.update_times_and_lock(
                                user_id,
                                block.id,
                                start_time=ev_start,
                                end_time=ev_end,
                                lock=time_changed,
                            )
                    ev_title = event.get("summary")
                    ev_notes = event.get("description")
                    if (ev_title is not None and ev_title != task.title) or (
                        ev_notes is not None and ev_notes != task.notes
                    ):
                        existing = task_repo.get(user_id, task.id)
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
                        user_id,
                        block.id,
                        calendar_event_id=event_id,
                        calendar_event_etag=event_etag,
                        calendar_event_updated_at=event_updated_at,
                    )
                    continue

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
                        user_id,
                        block.id,
                        calendar_event_id=event_id,
                        calendar_event_etag=updated.get("etag"),
                        calendar_event_updated_at=_to_utc_naive(_parse_rfc3339(updated.get("updated"))),
                    )

            except Exception as e:
                logger.error("Failed to sync calendar event for block %s: %s: %s", block.id, type(e).__name__, str(e))
                continue

        return {
            "events_created": events_created,
            "event_ids": event_ids,
            "orphans_deleted": orphans_deleted,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to sync calendar: %s: %s", type(e).__name__, str(e))
        raise HTTPException(status_code=500, detail=f"Failed to sync calendar: {str(e)}") from e


def best_effort_rebuild_and_sync(db: Session, user_id: str) -> None:
    """After task mutations: rebuild+sync when possible; never raises to callers."""
    horizon = config_schedule_horizon_days()
    token_repo = GoogleOAuthTokenRepository(db)
    if not token_repo.get_google_calendar(user_id):
        logger.info("best_effort_rebuild_and_sync skipped user=%s reason=no_calendar_token", user_id)
        return

    task_repo = TaskRepository(db)
    open_tasks = task_repo.get_open(user_id)
    try:
        if open_tasks:
            build_schedule_for_user(db, user_id, horizon)
        else:
            logger.info("best_effort_rebuild_and_sync skip_build user=%s reason=no_open_tasks", user_id)
        sync_calendar_for_user(db, user_id, horizon)
    except HTTPException as e:
        logger.warning(
            "best_effort_rebuild_and_sync failed user=%s status=%s detail=%s",
            user_id,
            e.status_code,
            e.detail,
        )
    except Exception as e:
        logger.warning("best_effort_rebuild_and_sync failed user=%s err=%s", user_id, type(e).__name__)


def run_daily_schedule_job(db: Session) -> Dict:
    """Process all users with calendar connected: rebuild+sync or sync-only."""
    horizon = config_schedule_horizon_days()
    ur = UserRepository(db)
    tr = TaskRepository(db)
    token_repo = GoogleOAuthTokenRepository(db)

    processed = 0
    errors: List[str] = []
    rebuilds = 0
    syncs = 0

    for user_id in ur.list_all_user_ids():
        if not token_repo.get_google_calendar(user_id):
            continue
        processed += 1
        try:
            open_tasks = tr.get_open(user_id)
            if open_tasks:
                build_schedule_for_user(db, user_id, horizon)
                rebuilds += 1
            sync_calendar_for_user(db, user_id, horizon)
            syncs += 1
        except HTTPException as e:
            errors.append(f"{user_id}: HTTP {e.status_code}")
        except Exception as e:
            errors.append(f"{user_id}: {type(e).__name__}")

    return {
        "users_processed": processed,
        "rebuilds": rebuilds,
        "syncs": syncs,
        "errors": errors,
    }


def verify_internal_job_secret(request: Request) -> None:
    """Raise HTTPException if job secret is missing or wrong."""
    expected = (os.getenv("QZ_INTERNAL_JOB_SECRET") or "").strip()
    if not expected:
        raise HTTPException(status_code=404, detail="Not found")
    got = request.headers.get(INTERNAL_JOB_SECRET_HEADER)
    if got != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
