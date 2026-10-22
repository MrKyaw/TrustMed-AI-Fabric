"""Shared time and identifier helpers.

Time is always timezone-aware UTC. Tests pass an explicit ``as_of`` instead of
sleeping or freezing the process clock, which keeps evaluations deterministic.
"""

from __future__ import annotations

import secrets
from datetime import UTC, date, datetime, timedelta


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def iso(value: datetime | date) -> str:
    return value.isoformat().replace("+00:00", "Z")


def days_from(anchor: datetime, days: int) -> datetime:
    return ensure_utc(anchor) + timedelta(days=days)


def new_id(prefix: str, length: int = 12) -> str:
    return f"{prefix}_{secrets.token_hex(length // 2)}"
