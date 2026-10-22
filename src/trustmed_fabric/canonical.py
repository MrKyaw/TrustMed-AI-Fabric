"""Canonical serialization used by hashes and audit exports.

A single implementation prevents the classic failure mode where two services
disagree about key ordering or datetime formatting and therefore disagree
about whether an audit record was tampered with.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel


def _default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime | date):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, set | frozenset):
        return sorted(value)
    raise TypeError(f"cannot canonically serialize {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return deterministic, compact JSON with sorted keys."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_default,
    )
