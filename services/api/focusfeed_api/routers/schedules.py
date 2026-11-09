from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from focusfeed_api.auth.deps import DB, CurrentUser
from focusfeed_api.errors import NotFound
from focusfeed_api.models import Schedule
from focusfeed_api.schemas import OkOut, ScheduleIn, ScheduleOut
from focusfeed_api.services import audit
from focusfeed_api.services.schedules import upsert_schedule

router = APIRouter(prefix="/schedules", tags=["schedules"])


def _out(s: Schedule) -> ScheduleOut:
    return ScheduleOut(
        id=s.id,
        timezone=s.timezone,
        local_time=s.local_time,
        days_of_week=list(s.days_of_week or []),
        platforms=list(s.platforms or []),
        enabled=s.enabled,
        missed_run_policy=s.missed_run_policy,
        ready_by_time=s.ready_by_time,
        lead_minutes=s.lead_minutes,
        deliver_time=s.deliver_time,
        deliver_channels=list(s.deliver_channels or ["app"]),
        last_batch_id=s.last_batch_id,
        next_run_at=s.next_run_at,
        last_run_at=s.last_run_at,
        last_job_id=s.last_job_id,
    )


@router.get("", response_model=list[ScheduleOut])
def list_schedules(user: CurrentUser, db: DB) -> list[ScheduleOut]:
    return [
        _out(s)
        for s in db.scalars(
            select(Schedule).where(Schedule.user_id == user.id).order_by(Schedule.created_at)
        ).all()
    ]


@router.post("", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED)
def create_schedule(body: ScheduleIn, user: CurrentUser, db: DB, request: Request) -> ScheduleOut:
    s = upsert_schedule(db, user, body)
    audit.record(db, "schedule.created", user_id=user.id, request=request, data={"schedule_id": str(s.id)})
    db.commit()
    db.refresh(s)
    return _out(s)


@router.put("/{schedule_id}", response_model=ScheduleOut)
def update_schedule(schedule_id: uuid.UUID, body: ScheduleIn, user: CurrentUser, db: DB) -> ScheduleOut:
    s = db.get(Schedule, schedule_id)
    if s is None or s.user_id != user.id:
        raise NotFound()
    upsert_schedule(db, user, body, existing=s)
    db.commit()
    db.refresh(s)
    return _out(s)


@router.delete("/{schedule_id}", response_model=OkOut)
def delete_schedule(schedule_id: uuid.UUID, user: CurrentUser, db: DB) -> OkOut:
    s = db.get(Schedule, schedule_id)
    if s is None or s.user_id != user.id:
        raise NotFound()
    db.delete(s)
    db.commit()
    return OkOut(message="Schedule deleted.")
