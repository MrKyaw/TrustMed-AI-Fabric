"""Versioned demo fixtures shipped inside the package.

Fixtures are synthetic by construction. Keeping them in data files (rather
than in test code) means the API, the CLI, the MCP tools and the evaluation
harness all exercise exactly the same governed content pack.
"""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files
from typing import Any


@cache
def load_data(name: str) -> dict[str, Any]:
    resource = files("trustmed_fabric").joinpath("data", name)
    with resource.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{name} must contain a JSON object")
    return data


def content_pack() -> dict[str, Any]:
    return load_data("content_pack.json")


def seed_pack() -> dict[str, Any]:
    return load_data("seed_pack.json")


def taxonomy_pack() -> dict[str, Any]:
    return load_data("taxonomy.json")


def eval_pack() -> dict[str, Any]:
    return load_data("evals.json")
