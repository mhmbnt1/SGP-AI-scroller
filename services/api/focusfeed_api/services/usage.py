"""Usage accounting: entitlements, atomic reservations, settlement, deployment-wide spend guard.

Reservations run in their own short transaction and lock the user's entitlement row
(``SELECT … FOR UPDATE``) so concurrent workers cannot both pass the quota check.
An *estimate* is not a provider-enforced billing cap; see docs/PROVIDERS.md.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from focusfeed_api.config import get_settings
from focusfeed_api.db import session_scope
from focusfeed_api.errors import AppError
from focusfeed_api.models import Entitlement, UsageLedger
from focusfeed_api.providers.catalog import estimate_cost_usd, find_model


class QuotaExceeded(AppError):
    """Daily allowance exhausted (tokens, calls, messages, cost) or deployment spend guard reached."""

    status_code = 429
    code = "quota_exhausted"


class CostUnknownBlocked(AppError):
    """Strict cost guard: the call's cost cannot be estimated and the deployment refuses paid unknowns."""

    status_code = 409
    code = "cost_unknown_blocked"


@dataclass
class DailyUsage:
    tokens: int
    calls: int
    messages: int
    cost_usd: float
    cost_unknown_calls: int
    token_quota: int
    call_quota: int
    message_quota: int
    cost_quota_usd: float | None


def _day_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def get_or_create_entitlement(db: Session, user_id: uuid.UUID, *, for_update: bool = False) -> Entitlement:
    stmt = select(Entitlement).where(Entitlement.user_id == user_id)
    if for_update:
        stmt = stmt.with_for_update()
    ent = db.scalar(stmt)
    if ent is None:
        # Concurrent requests (e.g. a settings page loading options + usage in parallel) may race here:
        # insert idempotently and re-select instead of failing on the unique constraint.
        s = get_settings()
        db.execute(
            pg_insert(Entitlement)
            .values(
                id=uuid.uuid4(),
                user_id=user_id,
                daily_token_quota=s.ff_daily_token_quota_default,
                daily_call_quota=s.ff_daily_call_quota_default,
                daily_message_quota=s.ff_daily_message_quota_default,
                allowed_providers=[],
                note="",
            )
            .on_conflict_do_nothing(index_elements=[Entitlement.user_id])
        )
        ent = db.scalar(stmt)
        assert ent is not None
    return ent


def daily_usage(db: Session, user_id: uuid.UUID) -> DailyUsage:
    ent = get_or_create_entitlement(db, user_id)
    since = _day_start()
    rows = db.execute(
        select(
            func.coalesce(
                func.sum(
                    func.coalesce(UsageLedger.input_tokens, 0) + func.coalesce(UsageLedger.output_tokens, 0)
                ),
                0,
            ),
            func.coalesce(func.sum(UsageLedger.calls), 0),
            func.coalesce(func.sum(UsageLedger.messages), 0),
            func.coalesce(func.sum(func.coalesce(UsageLedger.cost_estimate_usd, 0.0)), 0.0),
            func.coalesce(func.sum(UsageLedger.reserved_tokens), 0),
        ).where(
            UsageLedger.user_id == user_id, UsageLedger.created_at >= since, UsageLedger.state != "released"
        )
    ).one()
    settled_tokens, calls, messages, cost, reserved = rows
    reserved_open = (
        db.scalar(
            select(func.coalesce(func.sum(UsageLedger.reserved_tokens), 0)).where(
                UsageLedger.user_id == user_id,
                UsageLedger.created_at >= since,
                UsageLedger.state == "reserved",
            )
        )
        or 0
    )
    unknown = (
        db.scalar(
            select(func.count())
            .select_from(UsageLedger)
            .where(
                UsageLedger.user_id == user_id,
                UsageLedger.created_at >= since,
                UsageLedger.state == "settled",
                UsageLedger.kind == "ai",
                UsageLedger.cost_estimate_usd.is_(None),
                UsageLedger.scope == "operator",
            )
        )
        or 0
    )
    return DailyUsage(
        tokens=int(settled_tokens) + int(reserved_open),
        calls=int(calls),
        messages=int(messages),
        cost_usd=float(cost),
        cost_unknown_calls=int(unknown),
        token_quota=ent.daily_token_quota,
        call_quota=ent.daily_call_quota,
        message_quota=ent.daily_message_quota,
        cost_quota_usd=ent.daily_cost_quota_usd,
    )


def deployment_cost_today(db: Session) -> float:
    since = _day_start()
    return float(
        db.scalar(
            select(func.coalesce(func.sum(func.coalesce(UsageLedger.cost_estimate_usd, 0.0)), 0.0)).where(
                UsageLedger.created_at >= since,
                UsageLedger.scope == "operator",
                UsageLedger.kind == "ai",
                UsageLedger.state != "released",
            )
        )
        or 0.0
    )


def reserve(
    *,
    user_id: uuid.UUID,
    kind: str,
    provider: str,
    model: str,
    scope: str,
    purpose: str,
    job_id: uuid.UUID | None = None,
    connection_id: uuid.UUID | None = None,
    reserved_tokens: int = 0,
    calls: int = 1,
    messages: int = 0,
) -> uuid.UUID:
    """Atomically check quotas and insert a reservation. Returns the ledger id. Own transaction."""
    settings = get_settings()
    with session_scope() as db:
        ent = get_or_create_entitlement(db, user_id, for_update=True)
        usage = daily_usage(db, user_id)
        if kind == "ai":
            if usage.calls + calls > ent.daily_call_quota:
                raise QuotaExceeded(
                    f"Daily AI call allowance ({ent.daily_call_quota}) reached. Try again tomorrow."
                )
            if usage.tokens + reserved_tokens > ent.daily_token_quota:
                raise QuotaExceeded(f"Daily AI token allowance ({ent.daily_token_quota}) reached.")
            spec = find_model(provider, model)
            est, _ = estimate_cost_usd(spec, reserved_tokens, 0)
            if scope == "operator":
                if spec is not None and spec.price is None and settings.ff_strict_cost_guard:
                    raise CostUnknownBlocked(
                        f"{provider}/{model} has no reliable price; strict cost guard blocks it."
                    )
                if (
                    ent.daily_cost_quota_usd is not None
                    and est is not None
                    and usage.cost_usd + est > ent.daily_cost_quota_usd
                ):
                    raise QuotaExceeded("Your daily AI cost allowance is reached.")
                if (
                    settings.ff_daily_spend_guard_usd
                    and deployment_cost_today(db) + (est or 0.0) > settings.ff_daily_spend_guard_usd
                ):
                    raise QuotaExceeded(
                        "The service's daily AI spending guard is reached. Please try again later."
                    )
        elif kind == "messaging":
            if usage.messages + messages > ent.daily_message_quota:
                raise QuotaExceeded(f"Daily message allowance ({ent.daily_message_quota}) reached.")
        row = UsageLedger(
            user_id=user_id,
            job_id=job_id,
            connection_id=connection_id,
            kind=kind,
            scope=scope,
            provider=provider,
            model=model,
            purpose=purpose,
            state="reserved",
            calls=calls,
            reserved_tokens=reserved_tokens,
            messages=messages,
        )
        db.add(row)
        db.flush()
        return row.id


def settle(
    ledger_id: uuid.UUID,
    *,
    input_tokens: int | None,
    output_tokens: int | None,
    provider: str | None = None,
    model: str | None = None,
    fallback_from: str | None = None,
    calls: int | None = None,
) -> None:
    with session_scope() as db:
        row = db.get(UsageLedger, ledger_id)
        if row is None:
            return
        if provider:
            row.provider = provider
        if model:
            row.model = model
        if calls is not None:
            row.calls = calls
        row.input_tokens = input_tokens
        row.output_tokens = output_tokens
        row.reserved_tokens = 0
        spec = find_model(row.provider, row.model)
        est, source = estimate_cost_usd(spec, input_tokens, output_tokens)
        row.cost_estimate_usd = est
        row.pricing_source = source
        row.fallback_from = fallback_from
        row.state = "settled"
        row.settled_at = datetime.now(UTC)


def release(ledger_id: uuid.UUID, *, note: str = "") -> None:
    with session_scope() as db:
        row = db.get(UsageLedger, ledger_id)
        if row is not None and row.state == "reserved":
            row.state = "released"
            row.reserved_tokens = 0
            row.calls = 0
            row.settled_at = datetime.now(UTC)
            row.pricing_source = note[:200] or row.pricing_source


def expire_stale_reservations(db: Session, older_than_minutes: int = 60) -> int:
    cutoff = datetime.now(UTC) - timedelta(minutes=older_than_minutes)
    n = 0
    for row in db.scalars(
        select(UsageLedger).where(UsageLedger.state == "reserved", UsageLedger.created_at < cutoff)
    ).all():
        row.state = "released"
        row.reserved_tokens = 0
        row.calls = 0
        n += 1
    return n
