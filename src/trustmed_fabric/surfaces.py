"""Connector surface registry used by the platform release-window policy."""

from __future__ import annotations

from typing import Any, cast

from trustmed_fabric.fixtures import seed_pack


def surfaces() -> dict[str, dict[str, Any]]:
    return cast(dict[str, dict[str, Any]], seed_pack()["surfaces"])


def surface_status(version: str) -> str:
    return str(surfaces().get(version, {}).get("status", "UNKNOWN"))


def is_supported(version: str) -> bool:
    return surface_status(version) == "SUPPORTED"
